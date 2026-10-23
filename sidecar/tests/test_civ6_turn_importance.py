"""Importance-scored journal: floor, baseline, prune, select, pin, T90 budget."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sidecar import civ6_prompt_budget as budget
from sidecar import civ6_turn_importance as importance
from sidecar import civ6_wire
from sidecar.tests.test_civ6_prompt_budget import _late_snapshot


def _snap(*, turn=10, player="PLAYER_0", wars=(), units=1, cities=1, **extra):
    your_units = []
    for index in range(units):
        your_units.append({
            "unit_id": f"UNIT_{index}",
            "unit_type_id": "UNIT_WARRIOR",
            "needs_orders": True,
            "health": {"current": 100, "maximum": 100},
        })
    your_cities = []
    for index in range(cities):
        your_cities.append({
            "city_id": f"CITY_{index}",
            "is_capital": index == 0,
            "x": 4,
            "y": 4,
            "defense": {"hp": 200, "max_hp": 200},
            "production": {"item_id": "UNIT_WARRIOR"},
        })
    majors = [{"player_id": pid, "at_war": True} for pid in wars]
    snap = {
        "schema_version": "civ6ai-input/1",
        "decision": {"turn": turn, "player_id": player},
        "your_units": your_units,
        "your_cities": your_cities,
        "your_empire": {"gold": 40, "gold_per_turn": 4, "research": {"tech": "TECH_MINING", "turns_left": 4}},
        "civ6": {"diplomacy": {"majors": majors}, "combat": {"hostiles": []}},
    }
    snap.update(extra)
    return snap


class ScoreNormalizationTests(unittest.TestCase):
    def test_exempt_events_survive_the_peer_floor(self):
        memory = {}
        snap = _snap(turn=12, wars=("PLAYER_1",), cities=2)
        snap["memory"] = {"event_tracking": {"wars": [], "cities": ["CITY_0"], "unit_count": 1}}
        scored = importance.score_turn(snap, memory, peer_scores=[40.0])
        self.assertGreaterEqual(scored["exempt"], 4)
        self.assertGreater(scored["raw"], scored["adjusted"])
        self.assertIn(scored["intelligence_tier"], {"low", "medium", "high", "critical"})

    def test_late_game_background_does_not_pin_every_turn(self):
        memory = {}
        pinned = 0
        for turn in range(1, 26):
            snap = _snap(turn=turn, wars=("PLAYER_1",), units=28, cities=8)
            if turn > 1:
                snap_mem = memory
            else:
                snap_mem = memory
            scored = importance.score_turn(snap, snap_mem, peer_scores=[12.0, 11.0])
            if scored["adjusted"] >= 15:
                pinned += 1
        self.assertLess(pinned, 25)
        late = importance.score_turn(
            _snap(turn=26, wars=("PLAYER_1",), units=28, cities=8),
            memory,
            peer_scores=[12.0, 11.0],
        )
        self.assertLess(late["adjusted"], 15)
        self.assertNotEqual(late["intelligence_tier"], "critical")

    def test_importance_file_stores_raw_and_adjusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "PLAYER_0_thought.json"
            snap = _snap(turn=3, player="PLAYER_0")
            memory = {}
            scored = importance.apply_score_to_snapshot(snap, memory, path)
            written = path.parent / f"{path.stem}_importance_t3.json"
            self.assertTrue(written.is_file())
            data = json.loads(written.read_text(encoding="utf-8"), strict=False)
            self.assertEqual(data["player_id"], "PLAYER_0")
            self.assertEqual(data["raw"], scored["raw"])
            self.assertEqual(data["adjusted"], scored["adjusted"])
            self.assertIn("intelligence_tier", data)


class PruneAndSelectTests(unittest.TestCase):
    def test_prune_keeps_opening_last_ten_window_peak_and_pins(self):
        memory = {"thoughts": []}
        for turn in range(1, 41):
            adj = 16 if turn == 5 else (9 if turn == 14 else 1)
            memory["thoughts"].append({
                "turn": turn,
                "situation": f"sit {turn}",
                "strategy": f"plan {turn}",
                "importance_adjusted": adj,
                "importance_score": adj,
                "intelligence_tier": importance.intelligence_tier(adj),
            })
        importance.prune_thought_memory(memory)
        turns = {int(row["turn"]) for row in memory["thoughts"]}
        self.assertIn(1, turns)
        self.assertTrue({31, 32, 33, 34, 35, 36, 37, 38, 39, 40} <= turns)
        self.assertIn(5, turns)
        self.assertIn(14, turns)
        pinned = [row for row in memory["thoughts"] if row.get("pinned")]
        self.assertTrue(any(int(row["turn"]) == 5 for row in pinned))

    def test_select_is_last_three_opening_and_ranked(self):
        memory = {"thoughts": []}
        for turn in range(1, 21):
            memory["thoughts"].append({
                "turn": turn,
                "situation": f"unique situation {turn}",
                "strategy": "hold",
                "importance_adjusted": 18 if turn == 8 else 2,
                "importance_score": 18 if turn == 8 else 2,
            })
        chosen = importance.select_thought_turns_for_wire(memory, 21)
        self.assertIn(1, chosen)
        self.assertIn(8, chosen)
        self.assertEqual(chosen[-3:], [18, 19, 20])
        self.assertLessEqual(len(chosen), 20)

    def test_select_dedupes_near_duplicate_situations(self):
        memory = {"thoughts": [
            {"turn": 1, "situation": "Same city screen as always", "importance_adjusted": 2},
            {"turn": 2, "situation": "Same city screen as always", "importance_adjusted": 9},
            {"turn": 3, "situation": "War just started on the border", "importance_adjusted": 12},
            {"turn": 4, "situation": "Same city screen as always", "importance_adjusted": 3},
            {"turn": 5, "situation": "Same city screen as always", "importance_adjusted": 3},
        ]}
        chosen = importance.select_thought_turns_for_wire(memory, 6)
        self.assertIn(3, chosen)
        self.assertIn(5, chosen)
        self.assertIn(4, chosen)
        self.assertNotIn(2, chosen)


class PersistAndBudgetTests(unittest.TestCase):
    def test_attach_row_stores_tier_and_both_scores(self):
        memory = {}
        scored = {"raw": 11, "adjusted": 7.5, "breakdown": [{"trigger": "at_war", "score": 4}], "intelligence_tier": "medium"}
        importance.attach_thought_row(memory, 9, "We are at war.", "Hold the capital.", "Fortify.", scored)
        row = memory["thoughts"][0]
        self.assertEqual(row["importance_score"], 11)
        self.assertEqual(row["importance_adjusted"], 7.5)
        self.assertEqual(row["intelligence_tier"], "medium")
        self.assertEqual(row["decision"], "Fortify.")
        self.assertFalse(row["pinned"])
        self.assertEqual(memory["situation_log"][0]["turn"], 9)

    def test_late_prompt_stays_under_sixty_k_tokens(self):
        snap = _late_snapshot()
        text = civ6_wire.build_civ6_model_wire_text(snap, max_prompt_chars=240000)
        self.assertLessEqual(budget.estimate_tokens(text), 60000)
        report = snap["advciv"]["prompt_budget"]
        self.assertIn("memory_turns_shown", report)
        self.assertLessEqual(report["after_tokens_est"], 60000)


if __name__ == "__main__":
    unittest.main()
