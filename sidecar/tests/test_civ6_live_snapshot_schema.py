"""Regression: a real in-game turn-1 snapshot (with audit fields such as
unit health_percent, empire amenities and known_map explored_percent) must pass
the runtime schema. Sample fixtures missed this and blocked every live pulse."""
import json
import unittest
from pathlib import Path

from sidecar import civ6_adapter

ROOT = Path(__file__).resolve().parents[2]


class LiveSnapshotSchemaTest(unittest.TestCase):
    def test_live_runtime_snapshot_upgrades(self):
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t1-snapshot.json").read_text(encoding="utf-8"))
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual(snap["your_units"][0]["health_percent"], 100)
        self.assertIn("amenities", snap["your_empire"])
        self.assertIn("explored_percent", snap["known_map"])

    def test_live_snapshot_with_city_upgrades(self):
        # Turn-4 snapshot of a seat that founded its capital: city amenities and
        # defense.health_percent made every seat with a city fail the sidecar
        # (empty-apply fallback for all but city-less seats).
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t4-city-snapshot.json").read_text(encoding="utf-8"))
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        city = snap["your_cities"][0]
        self.assertIn("amenities", city)
        self.assertEqual(100, city["defense"]["health_percent"])

    def test_live_snapshot_accepts_charges_districts_and_audited_fields(self):
        # T123 rejected every turn: builders carry build_charges and every plot
        # carries district_id (often null). Stamp those, plus the other snapshot
        # fields added alongside them, onto a real captured turn and upgrade it.
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t4-city-snapshot.json").read_text(encoding="utf-8"))
        raw["your_units"][0]["build_charges"] = 3
        plots = raw["known_map"]["plots"]
        for plot in plots:
            plot["district_id"] = None
        plots[1]["district_id"] = "DISTRICT_CAMPUS"
        plots[1]["improvement_pillaged"] = True
        raw["your_cities"][0]["defense"]["wall_hp"] = 80
        raw["your_cities"][0]["defense"]["wall_max_hp"] = 200
        raw["civ6"]["governance"] = {
            "in_anarchy": False,
            "anarchy_turns_left": 0,
            "change_allowed": True,
        }
        raw["civ6"]["diplomacy"] = {
            "majors": [{"player_id": "PLAYER_0", "at_war": True, "war_since_turn": 81}],
            "city_states": [{
                "player_id": "PLAYER_5",
                "your_envoys": 1,
                "suzerain_envoys": 3,
            }],
            "wars": [],
        }
        raw["legal_commands"].append({
            "command_id": "CMD_attack_UNIT_131073_50_28",
            "kind": "attack_target",
            "fixed_arguments": {
                "unit_id": "UNIT_131073",
                "target_x": 50,
                "target_y": 28,
                "target_kind": "unit",
                "ranged": False,
            },
            "parameter_domains": {},
            "affected_ids": ["UNIT_131073"],
            "runtime_status": "implemented_untested",
        })
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual(3, snap["your_units"][0]["build_charges"])
        by_id = {plot["plot_id"]: plot for plot in snap["known_map"]["plots"]}
        self.assertIsNone(by_id[plots[0]["plot_id"]]["district_id"])
        campus = by_id[plots[1]["plot_id"]]
        self.assertEqual("DISTRICT_CAMPUS", campus["district_id"])
        self.assertTrue(campus["improvement_pillaged"])
        self.assertEqual(80, snap["your_cities"][0]["defense"]["wall_hp"])
        self.assertEqual(200, snap["your_cities"][0]["defense"]["wall_max_hp"])
        diplomacy = snap["civ6"]["diplomacy"]
        self.assertEqual(81, diplomacy["majors"][0]["war_since_turn"])
        self.assertEqual(3, diplomacy["city_states"][0]["suzerain_envoys"])
        self.assertFalse(snap["civ6"]["governance"]["in_anarchy"])
        attack = next(cmd for cmd in snap["legal_commands"] if cmd["kind"] == "attack_target")
        self.assertEqual("unit", attack["fixed_arguments"]["target_kind"])
        self.assertIs(False, attack["fixed_arguments"]["ranged"])


if __name__ == "__main__":
    unittest.main()
