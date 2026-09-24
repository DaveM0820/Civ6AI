"""Tests for Civ VI snapshot adapter."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from sidecar import civ6_adapter
from sidecar import pipeline_v2 as pipeline

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SNAPSHOT = ROOT / "fixtures" / "civ6" / "snapshot-turn-classical-golden.json"


class Civ6AdapterTests(unittest.TestCase):
    def test_classical_golden_snapshot_validates(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        self.assertEqual("civ6ai-input/1", snapshot["schema_version"])
        civ6_adapter.validate_civ6_snapshot(snapshot)

    def test_golden_snapshot_file_loads(self):
        if not GOLDEN_SNAPSHOT.is_file():
            civ6_adapter.write_classical_golden_snapshot()
        snapshot = civ6_adapter.load_golden_snapshot()
        self.assertEqual(18, snapshot["decision"]["turn"])
        self.assertGreaterEqual(len(snapshot["legal_commands"]), 10)

    def test_duplicate_legal_command_rejected(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"].append(snapshot["legal_commands"][0])
        with self.assertRaises(pipeline.BoundaryError):
            civ6_adapter.validate_civ6_snapshot(snapshot)

    def test_capabilities_load(self):
        doc = civ6_adapter.load_capabilities()
        kinds = {row["kind"] for row in doc["capabilities"]}
        self.assertIn("move_unit", kinds)
        self.assertIn("chat", kinds)
        self.assertIn("cancel_deal", kinds)
        v1 = sum(1 for row in doc["capabilities"] if row.get("tier") == "v1")
        self.assertGreaterEqual(v1, 45)

    def test_upgrade_runtime_snapshot(self):
        raw = json.loads(
            (ROOT / "fixtures" / "civ6" / "snapshot-turn-runtime-minimal.json").read_text(encoding="utf-8")
        )
        upgraded = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual(5, upgraded["decision"]["turn"])
        civ6_adapter.validate_civ6_snapshot(upgraded)

    def test_upgrade_runtime_preserves_known_map(self):
        raw = {
            "schema_version": "civ6ai-input/1",
            "decision": {"turn": 3, "player_id": "PLAYER_0"},
            "known_map": {
                "format": "plot-grid-v1",
                "visibility_mode": "player_visible",
                "plots": [
                    {
                        "plot_id": "PLOT_5_5",
                        "x": 5,
                        "y": 5,
                        "knowledge": "visible",
                        "last_seen_turn": 3,
                        "area_id": "AREA_0",
                        "terrain_id": "TERRAIN_GRASS",
                        "water": False,
                        "hills": False,
                        "peak": False,
                        "fresh_water": True,
                        "river_edges": ["N"],
                        "revealed_owner_id": "PLAYER_0",
                        "feature_id": None,
                        "improvement_id": None,
                        "route_id": None,
                        "resource_id": None,
                        "yields": {"food": 0, "production": 0, "commerce": 0},
                        "defense_percent": 0,
                        "city_id": None,
                        "worked_by_city_id": None,
                        "visible_stack_ids": [],
                    }
                ],
                "areas": [],
                "frontiers": [],
                "visible_stacks": [],
                "visibility_grid": ["...?", "...."],
                "image": {
                    "attached": False,
                    "format": "png-grid-v1",
                    "width": 4,
                    "height": 2,
                    "legend": [],
                    "label_ids": [],
                },
            },
            "civ6": {
                "session_id": "test",
                "map": {"width": 10, "height": 10, "hex_layout": "odd-r", "coords_note": "grid"},
            },
        }
        upgraded = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual(1, len(upgraded["known_map"]["plots"]))
        self.assertTrue(upgraded["known_map"]["plots"][0]["fresh_water"])
        self.assertEqual(10, upgraded["game"]["map_width"])

    def test_upgrade_runtime_preserves_live_units_not_golden_cities(self):
        raw = {
            "schema_version": "civ6ai-input/1",
            "decision": {"turn": 1, "player_id": "PLAYER_0", "phase": "strategic_decision", "reason": "turn_start"},
            "your_units": [
                civ6_adapter._empty_unit("UNIT_65536", "UNIT_SETTLER", 10, 10, 2, True),
            ],
            "your_cities": [],
            "legal_commands": [
                {
                    "command_id": "CMD_found_UNIT_65536",
                    "kind": "found_city",
                    "fixed_arguments": {"unit_id": "UNIT_65536"},
                }
            ],
            "civ6": {
                "session_id": "live-test",
                "map": {"width": 44, "height": 26, "hex_layout": "odd-r", "coords_note": "grid"},
            },
            "your_empire": {"score": 0, "gold": 0, "gold_per_turn": 0},
            "game": {"era_id": "ERA_ANCIENT"},
            "personality": {"leader_name": "Alexander"},
        }
        upgraded = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual([], upgraded["your_cities"])
        self.assertEqual(1, len(upgraded["your_units"]))
        self.assertNotIn("CITY_ATHENS", [c.get("city_id") for c in upgraded.get("your_cities", [])])
        civ6_adapter.validate_civ6_snapshot(upgraded)

    def test_lua_empty_tables_become_arrays(self):
        coerced = civ6_adapter.coerce_lua_empty_arrays({
            "your_units": [{"promotion_ids": {}, "mission_queue": {}, "cargo_unit_ids": {}, "upgrade_options": {}}],
            "parameter_domains": {},
        })
        self.assertEqual([], coerced["your_units"][0]["promotion_ids"])
        self.assertEqual({}, coerced["parameter_domains"])

    def test_runtime_snapshot_accepts_dx_dy_river_edges(self):
        raw = {
            "schema_version": "civ6ai-input/1",
            "decision": {"turn": 3, "player_id": "PLAYER_0"},
            "known_map": {
                "format": "plot-grid-v1",
                "visibility_mode": "player_visible",
                "plots": [
                    {
                        "plot_id": "PLOT_5_5",
                        "x": 5,
                        "y": 5,
                        "knowledge": "visible",
                        "last_seen_turn": 3,
                        "area_id": "AREA_0",
                        "terrain_id": "TERRAIN_GRASS",
                        "water": False,
                        "hills": False,
                        "peak": False,
                        "fresh_water": True,
                        "river_edges": [{"dx": 0, "dy": -1}],
                        "revealed_owner_id": "PLAYER_0",
                        "feature_id": None,
                        "improvement_id": None,
                        "route_id": None,
                        "resource_id": None,
                        "yields": {"food": 0, "production": 0, "commerce": 0},
                        "defense_percent": 0,
                        "city_id": None,
                        "worked_by_city_id": None,
                        "visible_stack_ids": [],
                    }
                ],
                "areas": [],
                "frontiers": [],
                "visible_stacks": [],
                "visibility_grid": ["...?", "...."],
                "image": {
                    "attached": False,
                    "format": "png-grid-v1",
                    "width": 4,
                    "height": 2,
                    "legend": [],
                    "label_ids": [],
                },
            },
            "civ6": {
                "session_id": "test",
                "map": {"width": 10, "height": 10, "hex_layout": "odd-r", "coords_note": "grid"},
            },
        }
        upgraded = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual([{"dx": 0, "dy": -1}], upgraded["known_map"]["plots"][0]["river_edges"])
        civ6_adapter.validate_civ6_snapshot(upgraded)

    def test_chat_wire_snapshot_normalizes_to_schema(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        snapshot["decision"]["reason"] = "human_chat"
        snapshot["history"]["public_events"] = [
            {
                "turn": 4,
                "kind": "CHAT_PUBLIC",
                "text": "Greetings from Kyoto.",
                "affected_ids": ["PLAYER_0"],
            }
        ]
        snapshot["history"]["memory_summary"] = ""
        civ6_adapter.normalize_civ6_snapshot(snapshot)
        self.assertEqual("turn_start", snapshot["decision"]["reason"])
        event = snapshot["history"]["public_events"][0]
        self.assertEqual("Greetings from Kyoto.", event["summary"])
        self.assertNotIn("text", event)

    def test_live_city_snapshot_fills_production_and_integer_yields(self):
        raw = {
            "schema_version": "civ6ai-input/1",
            "decision": {"turn": 23, "player_id": "PLAYER_0", "phase": "strategic_decision", "reason": "turn_start"},
            "your_units": [
                civ6_adapter._empty_unit("UNIT_131073", "UNIT_WARRIOR", 66, 25, 2, True),
            ],
            "your_cities": [
                {
                    "city_id": "CITY_65536",
                    "name": "London",
                    "plot_id": "PLOT_67_26",
                    "population": 2,
                    "is_capital": True,
                    "production": {"progress": 0, "production_per_turn": 0, "cost": 0},
                }
            ],
            "your_empire": {
                "score": 14,
                "gold": 116,
                "gold_per_turn": 5,
                "commerce": {
                    "gold": {"percent": 0, "rate": 5},
                    "research": {"percent": 100, "rate": 3},
                    "culture": {"percent": 0, "rate": 1.59765625},
                    "espionage": {"percent": 0, "rate": 0},
                },
                "research": {
                    "tech_id": "TECH_ANIMAL_HUSBANDRY",
                    "progress": 20.5,
                    "cost": 25,
                    "research_per_turn": 3,
                    "estimated_turns_remaining": 1,
                    "queue": {},
                    "known_tech_ids": {},
                },
            },
            "legal_commands": [
                {
                    "command_id": "CMD_skip_UNIT_131073",
                    "kind": "unit_skip",
                    "fixed_arguments": {"unit_id": "UNIT_131073"},
                }
            ],
            "civ6": {
                "session_id": "live-schema-test",
                "map": {"width": 74, "height": 46, "hex_layout": "odd-r", "coords_note": "grid"},
            },
            "game": {"era_id": "ERA_ANCIENT"},
            "personality": {"leader_name": "Eleanor of Aquitaine (England)"},
        }
        upgraded = civ6_adapter.upgrade_runtime_snapshot(raw)
        production = upgraded["your_cities"][0]["production"]
        self.assertIn("item_id", production)
        self.assertIn("estimated_turns_remaining", production)
        self.assertEqual(2, upgraded["your_empire"]["commerce"]["culture"]["rate"])
        self.assertEqual(21, upgraded["your_empire"]["research"]["progress"])
        civ6_adapter.validate_civ6_snapshot(upgraded)


if __name__ == "__main__":
    unittest.main()
