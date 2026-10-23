"""Prompt-size budget: count compact, then drop lower-priority sections."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from sidecar import civ6_prompt_budget as budget
from sidecar import civ6_wire

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "civ6" / "snapshot-turn-classical-golden.json"


def _late_snapshot() -> dict:
    """Classical golden grown to a late-game seat: many units, cities, and catalogs.

    No saved turn-90 snapshot is in the repo. This is the same fixture, expanded
    so the uncompacted prompt is the size live seats reached.
    """
    snap = json.loads(GOLDEN.read_text(encoding="utf-8"))
    snap["decision"]["turn"] = 90
    base_unit = snap["your_units"][0]
    units = []
    for index in range(14):
        unit = copy.deepcopy(base_unit)
        unit["unit_id"] = f"UNIT_W_{index:02d}"
        unit["unit_type_id"] = "UNIT_WARRIOR"
        unit["plot_id"] = f"PLOT_{10 + index}_20"
        unit["needs_orders"] = True
        unit["movement"] = {"current": 0 if index == 0 else 2, "maximum": 2}
        unit["health"] = {"current": 50 if index == 1 else 100, "maximum": 100}
        unit["upgrade_options"] = [{"unit_type_id": "UNIT_SWORDSMAN", "gold_cost": 80}] if index == 2 else []
        units.append(unit)
    snap["your_units"] = units
    base_city = snap["your_cities"][0]
    cities = []
    economy_rows = []
    buildings = [f"BUILDING_{name}" for name in (
        "MONUMENT WALLS GRANARY WATER_MILL LIBRARY AMPHITHEATER BARRACKS STABLE "
        "MARKET LIGHTHOUSE WORKSHOP ARENA TEMPLE SHRINE PALACE"
    ).split()]
    for index in range(8):
        city = copy.deepcopy(base_city)
        city["city_id"] = f"CITY_{index}"
        city["name"] = f"Polis{index}"
        city["is_capital"] = index == 0
        city["population"] = 4 + index
        city["plot_id"] = f"PLOT_{20 + index}_12"
        if index == 1:
            city["defense"] = {"hp": 80, "max_hp": 200}
            city["production"] = {"item_id": "BUILDING_WALLS"}
        elif index == 3:
            city["production"] = {"item_id": None}
        else:
            city["production"] = {"item_id": "UNIT_WARRIOR"}
        cities.append(city)
        economy_rows.append({
            "city_id": city["city_id"],
            "population": city["population"],
            "production_item": city["production"].get("item_id"),
            "production_turns": 6,
            "turns_to_starve": 2 if index == 4 else None,
            "food": 12,
            "production": 8,
            "gold": 4,
            "science": 5,
            "culture": 3,
            "faith": 1,
            "housing": 8,
            "built_buildings": buildings,
            "built_districts": ["DISTRICT_CAMPUS", "DISTRICT_ENCAMPMENT"],
        })
    snap["your_cities"] = cities
    civ6 = snap.setdefault("civ6", {})
    extra = {}
    for index, city in enumerate(cities):
        extra[city["city_id"]] = {"loyalty": 40 if index == 2 else 100, "districts": ["DISTRICT_CAMPUS"]}
    civ6["city_extra"] = extra
    economy = civ6.setdefault("economy", {})
    economy["cities"] = economy_rows
    tokens = [f"UNIT_LATE_{n}" for n in range(20)]
    economy["build_catalog"] = {token: {"cost": 80 + n} for n, token in enumerate(tokens)}
    economy["build_turns"] = {city["city_id"]: {token: 4 for token in tokens} for city in cities}
    commands = list(snap.get("legal_commands") or [])
    for city in cities:
        for token in tokens:
            commands.append({
                "command_id": f"CMD_{city['city_id']}_{token}",
                "kind": "queue_production",
                "fixed_arguments": {"city_id": city["city_id"], "build_id": token},
                "parameter_domains": {},
                "runtime_status": "tested",
            })
    snap["legal_commands"] = commands
    snap["your_empire"]["research"]["known_tech_ids"] = [f"TECH_LATE_{n}" for n in range(80)]
    snap["your_empire"]["civics"] = [{"id": f"CIVIC_LATE_{n}"} for n in range(40)]
    essay = "They have raided the coast every decade and still hold the strait. " * 50
    snap["history"]["player_opinions"] = {"PLAYER_1": {"text": essay, "updated_turn": 80}}
    snap["history"]["player_histories"] = {"PLAYER_1": {"text": essay}}
    snap["history"]["thought_memory"] = [
        {"turn": turn, "situation": essay, "strategy": essay} for turn in range(70, 91)
    ]
    snap["history"]["memory_summary"] = essay
    snap["known_players"][0]["relation"]["at_war"] = True
    snap["strategic_summary"]["military_alerts"] = [{
        "text": "Cleopatra's army is inside move range of Polis1",
    }]
    snap["_seat_memory"] = {
        "plan": {"goal": "domination", "objectives": [{
            "kind": "attack", "text": "hold Polis1", "status": "active", "target_turn": 100,
        }]},
        "situation_log": [{"turn": 90, "text": "Cleopatra is the threat this turn"}],
        "promises": [],
        "alerts": [],
        "milestones": [{"turn": 10, "text": "met Cleopatra years ago " + essay}],
    }
    foreign = []
    for index in range(20):
        foreign.append({
            "city_id": f"FOREIGN_{index}",
            "name": f"Foreign{index}",
            "owner_player_id": "PLAYER_1",
            "plot_id": f"PLOT_{index}_3",
            "population": 6,
            "is_capital": index == 0,
            "knowledge": "visible" if index == 1 else "remembered",
        })
    snap["known_other_cities"] = foreign
    return snap


class PromptBudgetTests(unittest.TestCase):
    def test_count_compact_keeps_order_facts_and_drops_healthy_detail(self):
        snap = _late_snapshot()
        text = civ6_wire.build_civ6_model_wire_text(snap, max_prompt_chars=0)
        self.assertIn("units_compact", snap["advciv"]["prompt_budget"]["compactions"])
        self.assertIn("cities_compact", snap["advciv"]["prompt_budget"]["compactions"])
        self.assertIn("warrior_2.position = (11,20)", text)
        self.assertIn("warrior_2.hp = 50%", text)
        self.assertNotIn("warrior_2.moves", text)
        self.assertNotIn("warrior_3.upgrade", text)
        self.assertNotIn("warrior_2.combat", text)
        self.assertIn("warrior_1.moves = 0", text)
        self.assertIn("warrior_1.position = (10,20)", text)
        self.assertIn("WARRIOR legalCommands", text)
        self.assertIn("Polis1.population = 5", text)
        self.assertIn("Polis1.currentProduction = BUILDING_WALLS", text)
        self.assertIn("Polis1.hp = 80/200", text)
        self.assertIn("Polis2.loyalty = 40", text)
        self.assertNotIn("Polis0.loyalty", text)
        self.assertIn("Polis4.growth = STARVING", text)
        self.assertNotIn("Polis0.buildings", text)
        self.assertNotIn("Polis0.districts", text)
        self.assertNotIn("Polis0.yields", text)
        self.assertTrue("map.images" in text or "minimap attached" in text)
        self.assertIn("=== WAR ===", text)
        self.assertIn("war.rivals", text)
        self.assertIn("Cleopatra's army is inside move range of Polis1", text)
        self.assertIn("plan.goal = domination", text)
        self.assertIn("situation.T90 = Cleopatra is the threat this turn", text)
        self.assertIn(".command", text)

    def test_ladder_fits_a_late_prompt_and_logs_sections(self):
        snap = _late_snapshot()
        text = civ6_wire.build_civ6_model_wire_text(snap, max_prompt_chars=30000)
        report = snap["advciv"]["prompt_budget"]
        self.assertGreaterEqual(report["before_chars"], 43000)
        self.assertLessEqual(report["after_chars"], 30000)
        self.assertLess(report["after_chars"], report["before_chars"])
        self.assertEqual(len(text), report["after_chars"])
        self.assertEqual(budget.estimate_tokens(text), report["after_tokens_est"])
        self.assertIn("history", report["compactions"])
        self.assertNotIn("still_over_budget", report["compactions"])
        self.assertNotIn("opinion.Cleopatra", text)
        self.assertNotIn("history.Cleopatra", text)
        self.assertIn("=== ATTENTION ===", text)
        self.assertIn("=== WAR ===", text)
        self.assertIn("=== REQUIRED COMMANDS ===", text)
        self.assertIn("plan.goal = domination", text)
        self.assertTrue("map.images" in text or "minimap attached" in text)
        war = text.split("=== WAR ===", 1)[1].split("===", 1)[0]
        self.assertIn("war.rivals", war)
        fields = budget.metrics_fields(snap)
        self.assertEqual(30000, fields["max_prompt_chars"])
        self.assertEqual(report["before_chars"], fields["prompt_chars_before"])
        self.assertEqual(report["section_chars"], fields["prompt_section_chars"])
        self.assertIn("WAR", fields["prompt_section_chars"])
        self.assertIn("ATTENTION", fields["prompt_section_chars"])
        self.assertIn("REQUIRED COMMANDS", fields["prompt_section_chars"])
        self.assertTrue(report["map_image_kept"])

    def test_tiny_budget_never_drops_protected_sections(self):
        snap = _late_snapshot()
        full = civ6_wire.build_civ6_model_wire_text(snap, max_prompt_chars=0)
        war = full.split("=== WAR ===", 1)[1].split("===", 1)[0]
        attention = full.split("=== ATTENTION ===", 1)[1].split("===", 1)[0]
        required = full.split("=== REQUIRED COMMANDS ===", 1)[1]
        text = civ6_wire.build_civ6_model_wire_text(snap, max_prompt_chars=800)
        self.assertIn("still_over_budget", snap["advciv"]["prompt_budget"]["compactions"])
        self.assertIn(war.strip(), text)
        self.assertIn(attention.strip(), text)
        self.assertIn(required.strip(), text)
        self.assertIn("plan.goal = domination", text)
        self.assertTrue("map.images" in text or "minimap attached" in text)
        self.assertNotIn("omit_overview", " ".join(snap["advciv"]["prompt_budget"]["compactions"]))

    def test_section_passes_are_ordered_and_keep_offered_commands(self):
        catalog = " | ".join(f"UNIT_{n} (4t, 40p)" for n in range(8))
        essay = "Play the map and read the fog. " * 20
        text = "\n\n".join([
            "=== GAME ===",
            "You are Test.",
            essay,
            "map.images = attached — fog and terrain",
            "=== EMPIRE ===",
            f"Athens.production.catalog = {catalog}",
            "Athens.buildings = BUILDING_MONUMENT, BUILDING_WALLS",
            "Athens.population = 7",
            "warrior_1.moves = 2",
            "warrior_1.position = (1,1)",
            "=== OPPONENTS ===",
            "opinion.Cleopatra = " + ("old grievance " * 30),
            "rival.Cleopatra.atWar = true",
            "=== ATTENTION ===",
            "QUEUE EMPTY: Athens",
            "=== THOUGHTS ===",
            "plan.goal = science",
            "T1.situation = ancient note",
            "T9.situation = this turn",
            "history.memory = a long memory",
            "=== OPTIONAL COMMANDS ===",
            '  "12.Athens.production": "UNIT_WARRIOR | UNIT_SETTLER",',
            "=== REQUIRED COMMANDS ===",
            '  "1.warrior_1.command": "MoveTo(2,2) | Skip",',
            "=== WAR ===",
            "war.rivals = Cleopatra",
        ])
        compact, fired = budget.compact_to_budget(text, 400)
        self.assertIn("still_over_budget", fired)
        self.assertIn("history", fired)
        self.assertIn("catalogs", fired)
        self.assertIn("city_detail", fired)
        self.assertIn("units_budget", fired)
        self.assertNotIn("Athens.buildings", compact)
        self.assertIn("Athens.population = 7", compact)
        self.assertNotIn("opinion.Cleopatra", compact)
        self.assertNotIn("T1.situation", compact)
        self.assertIn("T9.situation = this turn", compact)
        self.assertIn("plan.goal = science", compact)
        self.assertIn("rival.Cleopatra.atWar = true", compact)
        self.assertIn("QUEUE EMPTY: Athens", compact)
        self.assertIn("war.rivals = Cleopatra", compact)
        self.assertIn("1.warrior_1.command", compact)
        self.assertIn("12.Athens.production", compact)
        self.assertIn("map.images = attached", compact)
        self.assertIn("+4 more", compact)
        self.assertNotIn("warrior_1.moves = 2", compact)


if __name__ == "__main__":
    unittest.main()
