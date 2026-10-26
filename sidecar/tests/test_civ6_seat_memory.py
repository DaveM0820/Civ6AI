"""Seat memory, objective tracking, purchase checks, and same-reply chat dedupe."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sidecar import civ6_apply_results as results
from sidecar import civ6_command_wire as command_wire
from sidecar import civ6_seat_memory as memory
from sidecar import pipeline_v2 as pipeline


def _snap(turn=40):
    return {
        "decision": {"player_id": "PLAYER_0", "turn": turn},
        "known_players": [{"player_id": "PLAYER_1", "leader_name": "Cleopatra"}],
        "your_cities": [{
            "city_id": "CITY_1", "name": "Capital", "plot_id": "PLOT_10_10",
            "worked_plot_ids": ["PLOT_10_10", "PLOT_11_10"],
        }],
        "known_map": {"plots": [
            {"plot_id": "PLOT_11_10", "improvement_id": None, "water": False, "peak": False},
        ]},
        "your_empire": {"gold": 10, "religion": {"faith": 5, "state_religion_id": "RELIGION_BUDDHISM"}},
        "civ6": {"diplomacy": {"majors": [{
            "player_id": "PLAYER_1", "at_war": True, "war_since_turn": 12,
        }], "city_states": []}, "economy": {"cities": [{
            "city_id": "CITY_1", "name": "Capital", "turns_to_starve": 3,
        }]}},
    }


class SeatMemoryTests(unittest.TestCase):
    def test_exploration_metric_counts_new_tiles_and_nudges_a_stall(self):
        from sidecar import civ6_prompt_coaching as coaching
        from sidecar import civ6_wire

        line = (
            "It has been {n} turns without revealing any new tiles. "
            "Continue exploring: send scouts/ships into unexplored areas."
        )

        def snap(turn, revealed):
            return {
                "decision": {"player_id": "PLAYER_0", "turn": turn},
                "game": {"map_width": 10, "map_height": 10},
                "known_map": {"revealed_count": revealed},
                "your_units": [],
                "your_cities": [],
                "legal_commands": [],
            }

        def nudge_rows(stored_memory):
            return [
                row for row in stored_memory.get("situation_log") or []
                if "without revealing any new tiles" in row.get("text", "")
            ]

        first = snap(1, 10)
        stored = memory.note_exploration(first, {"tracked": {}})
        self.assertEqual(10, first["_explore_metric"]["revealed"])
        self.assertEqual(0, first["_explore_metric"]["turns_since_reveal"])
        self.assertNotIn("new_tiles_this_turn", first["_explore_metric"])
        early = coaching.civ6_exploration_attention(first)
        self.assertIn("10% of the map revealed (10 of 100 tiles)", early)
        self.assertNotIn("without revealing any new tiles", early)

        second = snap(2, 14)
        stored = memory.note_exploration(second, stored)
        self.assertEqual(4, second["_explore_metric"]["new_tiles_this_turn"])
        self.assertEqual(0, second["_explore_metric"]["turns_since_reveal"])
        prompt = civ6_wire.build_civ6_wire_prompt(second)
        self.assertNotIn("without revealing any new tiles", prompt)
        self.assertEqual([], nudge_rows(stored))

        # T2 revealed. T6 is four quiet turns later, which is not yet > 4.
        quiet = snap(6, 14)
        stored = memory.note_exploration(quiet, stored)
        self.assertEqual(0, quiet["_explore_metric"]["new_tiles_this_turn"])
        self.assertEqual(4, quiet["_explore_metric"]["turns_since_reveal"])
        self.assertNotIn("without revealing any new tiles", coaching.civ6_exploration_attention(quiet) or "")
        self.assertEqual([], nudge_rows(stored))

        stalled = snap(7, 14)
        stored = memory.note_exploration(stalled, stored)
        self.assertEqual(0, stalled["_explore_metric"]["new_tiles_this_turn"])
        self.assertEqual(5, stalled["_explore_metric"]["turns_since_reveal"])
        self.assertEqual(14, stalled["_explore_metric"]["percent"])
        note = coaching.civ6_exploration_attention(stalled)
        self.assertEqual(line.format(n=5), note)
        prompt = civ6_wire.build_civ6_wire_prompt(stalled)
        self.assertIn("=== ATTENTION ===", prompt)
        self.assertIn(line.format(n=5), prompt)
        self.assertEqual([line.format(n=5)], [row["text"] for row in nudge_rows(stored)])

        again = snap(7, 14)
        stored = memory.note_exploration(again, stored)
        self.assertEqual(1, len(nudge_rows(stored)))
        self.assertEqual(line.format(n=5), nudge_rows(stored)[0]["text"])

        still = snap(8, 14)
        stored = memory.note_exploration(still, stored)
        self.assertEqual(6, still["_explore_metric"]["turns_since_reveal"])
        self.assertEqual([line.format(n=6)], [row["text"] for row in nudge_rows(stored)])
        self.assertEqual(line.format(n=6), coaching.civ6_exploration_attention(still))

        # A reveal clears the prompt line and the situation log.
        opened = snap(9, 20)
        stored = memory.note_exploration(opened, stored)
        self.assertEqual(6, opened["_explore_metric"]["new_tiles_this_turn"])
        self.assertEqual(0, opened["_explore_metric"]["turns_since_reveal"])
        self.assertNotIn("without revealing any new tiles", coaching.civ6_exploration_attention(opened) or "")
        self.assertNotIn("without revealing any new tiles", civ6_wire.build_civ6_wire_prompt(opened))
        self.assertEqual([], nudge_rows(stored))

        # A drop in revealed tiles is not a reveal, so the clock keeps running.
        shrunk = snap(10, 12)
        stored = memory.note_exploration(shrunk, stored)
        self.assertEqual(-8, shrunk["_explore_metric"]["new_tiles_this_turn"])
        self.assertEqual(1, shrunk["_explore_metric"]["turns_since_reveal"])
        self.assertEqual([], nudge_rows(stored))

        # 80% explored does not nudge, even after a long quiet stretch.
        covered = snap(8, 80)
        covered_memory = memory.note_exploration(covered, {
            "tracked": {"explore": [{"turn": 1, "revealed": 80}], "last_reveal_turn": 1},
        })
        self.assertEqual(7, covered["_explore_metric"]["turns_since_reveal"])
        self.assertIsNone(coaching.civ6_exploration_attention(covered))
        self.assertEqual([], nudge_rows(covered_memory))

    def test_lethargy_is_an_alert_and_a_situation_line(self):
        snap = _snap(turn=40)
        snap["your_cities"][0]["production"] = {"item_id": "NONE"}
        snap["your_units"] = [{
            "unit_id": "UNIT_1",
            "unit_type_id": "UNIT_WARRIOR",
            "unit_class_id": "FORMATION_CLASS_LAND_COMBAT",
        }]
        snap["civ6"]["economy"]["tracking"] = {"idle_turns": {"UNIT_1": 4}}
        snap["history"] = {"command_results": [{
            "turn": 30, "order_kind": "attack_target", "summary": "warrior attacked",
        }]}
        stored = memory.note_lethargy(snap, {"tracked": {}})
        text = " ".join(row["text"] for row in stored["situation_log"])
        self.assertIn("LETHARGY", text)
        self.assertIn("Cleopatra", text)
        self.assertIn("Idle cities", text)
        self.assertIn("WARRIOR", text)
        line = memory.lethargy_line(snap)
        self.assertTrue(line.startswith("LETHARGY:"))
        # A fresh attack this turn clears the war clause. The city and army remain.
        snap["history"]["command_results"].append({
            "turn": 40, "order_kind": "city_attack", "summary": "city strike",
        })
        snap.pop("_lethargy_alert", None)
        again = memory.note_lethargy(snap, stored)
        self.assertNotIn("no attack", memory.lethargy_line(snap))
        self.assertEqual(1, sum(1 for row in again["situation_log"] if row["text"].startswith("LETHARGY: At war")))
    def test_observe_fills_history_and_keeps_alerts(self):
        snap = _snap()
        stored = memory.observe(snap, {"session_key": "g:player:0", "thoughts": []})
        self.assertIn("War with Cleopatra", stored["situation_log"][0]["text"])
        self.assertIn("PLAYER_1", stored["player_opinions"])
        self.assertIn("PLAYER_1", stored["player_histories"])
        self.assertTrue(stored["player_histories"]["PLAYER_1"]["text"])
        alerts = {row["key"]: row["text"] for row in stored["alerts"]}
        self.assertIn("starve:CITY_1", alerts)
        self.assertIn("unimproved:PLOT_11_10", alerts)
        again = memory.observe(snap, stored)
        self.assertEqual(1, sum(1 for row in again["situation_log"] if "War with" in row["text"]))
        fixed = _snap()
        fixed["civ6"]["economy"]["cities"] = []
        fixed["your_cities"][0]["worked_plot_ids"] = ["PLOT_10_10"]
        cleared = memory.observe(fixed, again)
        self.assertEqual([], cleared["alerts"])

    def test_plan_round_trip_and_objective_note(self):
        response = {"4.plan.goal": "domination", "5.plan.objective": "attack their capital by T80"}
        update = command_wire.extract_plan(response)
        self.assertNotIn("4.plan.goal", response)
        stored = memory.apply_plan({"thoughts": []}, 40, update)
        self.assertEqual("domination", stored["plan"]["goal"])
        self.assertEqual(80, stored["plan"]["objectives"][0]["target_turn"])
        note = results.strategy_orders_note("hold", [{"kind": "move_unit"}], stored["plan"])
        self.assertIn("objective attack", note)
        self.assertIsNone(results.strategy_orders_note("hold", [{"kind": "attack_target"}], stored["plan"]))
        self.assertIn("attacking", results.strategy_orders_note("Attack Utrecht and take it.", [{"kind": "move_unit"}]))

    def test_promises_and_contradictions(self):
        chats = [{"text": "I will not attack you."}, {"text": "I will not attack you."}]
        kept, dropped = results.filter_repeat_public_chat({"decision": {"player_id": "PLAYER_0", "turn": 3}, "history": {}}, chats)
        # Chat is never blocked: the repeat is sent and noted.
        self.assertEqual(2, len(kept))
        self.assertTrue(dropped and dropped[0].startswith("note:"))
        promises = memory.extract_promises(kept)
        snap = {
            "known_players": [
                {"player_id": "PLAYER_1", "leader_id": "LEADER_TRAJAN", "civilization_id": "CIVILIZATION_ROME"},
                {"player_id": "PLAYER_63", "leader_id": "LEADER_BARBARIAN", "civilization_id": "CIVILIZATION_BARBARIAN"},
            ],
            "civ6": {"combat": {"previews": [
                {"unit_id": "UNIT_1", "target_x": 3, "target_y": 4, "target_owner": "PLAYER_1"},
                {"unit_id": "UNIT_1", "target_x": 5, "target_y": 6, "target_owner": "PLAYER_63"},
            ]}},
        }
        attack = lambda x, y: [{"kind": "attack_target", "arguments": {"target_x": x, "target_y": y}}]
        notes = memory.contradiction_notes(promises, attack(3, 4), snap)
        self.assertIn("promised peace", notes[0])
        # Fighting barbarians does not break a peace promise.
        self.assertEqual([], memory.contradiction_notes(promises, attack(5, 6), snap))
        notes = memory.contradiction_notes(
            ["I will attack at dawn."],
            [{"kind": "execute_deal", "arguments": {"mode": 1}}],
        )
        self.assertIn("promised an attack", notes[0])

    def test_purchase_over_gold_is_dropped(self):
        snap = _snap()
        commands = [
            {"kind": "purchase_item", "arguments": {"item_id": "UNIT_WARRIOR", "cost": 40}},
            {"kind": "purchase_item", "arguments": {"item_id": "UNIT_MISSIONARY", "cost": 4, "yield": "faith"}},
            {"kind": "move_unit", "arguments": {}},
        ]
        kept, notes = results.drop_unaffordable_purchases(snap, commands)
        self.assertEqual(["purchase_item", "move_unit"], [c["kind"] for c in kept])
        self.assertIn("40 gold", notes[0])

    def test_loader_keeps_plan_and_folder_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "game_PLAYER_0.json"
            payload = {
                "session_key": "game:player:0",
                "thoughts": [{"turn": 10, "situation": "a", "strategy": "b"}],
                "player_opinions": {},
                "player_histories": {},
                "plan": {"goal": "science", "objectives": [], "updated_turn": 10},
                "situation_log": [{"turn": 10, "text": "War with Cleopatra since T4."}],
                "alerts": [{"key": "starve:CITY_1", "text": "Capital is starving", "since_turn": 8}],
            }
            pipeline.save_thought_memory(path, payload)
            loaded = pipeline.load_thought_memory(path, "game:player:0")
            self.assertEqual("science", loaded["plan"]["goal"])
            self.assertEqual("War with Cleopatra since T4.", loaded["situation_log"][0]["text"])
            memory.write_folder(path, loaded, "game", "PLAYER_0")
            folder = Path(tmp) / "game" / "PLAYER_0"
            self.assertIn("science", (folder / "plan.json").read_text(encoding="utf-8"))
            self.assertIn("War with", (folder / "situation.jsonl").read_text(encoding="utf-8"))

    def test_ten_turn_milestone(self):
        stored = memory.observe(_snap(turn=20), {"thoughts": [], "plan": {"goal": "science", "objectives": []}})
        self.assertEqual(20, stored["milestones"][-1]["turn"])
        self.assertIn("science", stored["milestones"][-1]["text"])


if __name__ == "__main__":
    unittest.main()
