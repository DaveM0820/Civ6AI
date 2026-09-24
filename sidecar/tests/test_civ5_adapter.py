"""Tests for Civ V snapshot adapter."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from sidecar import civ5_adapter
from sidecar import pipeline_v2 as pipeline

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SNAPSHOT = ROOT / "fixtures" / "civ5" / "snapshot-turn-classical-golden.json"


class Civ5AdapterTests(unittest.TestCase):
    def test_classical_golden_snapshot_validates(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        self.assertEqual("civ5ai-input/1", snapshot["schema_version"])
        civ5_adapter.validate_civ5_snapshot(snapshot)

    def test_golden_snapshot_file_loads(self):
        if not GOLDEN_SNAPSHOT.is_file():
            civ5_adapter.write_classical_golden_snapshot()
        snapshot = civ5_adapter.load_golden_snapshot()
        self.assertEqual(18, snapshot["decision"]["turn"])
        self.assertGreaterEqual(len(snapshot["legal_commands"]), 3)

    def test_duplicate_legal_command_rejected(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"].append(snapshot["legal_commands"][0])
        with self.assertRaises(pipeline.BoundaryError):
            civ5_adapter.validate_civ5_snapshot(snapshot)

    def test_capabilities_load(self):
        doc = civ5_adapter.load_capabilities()
        kinds = {row["kind"] for row in doc["capabilities"]}
        self.assertIn("set_research_tech", kinds)
        self.assertIn("queue_production", kinds)
        self.assertIn("move_unit", kinds)

    def test_runtime_snapshot_accepts_civ5_river_edge_id(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["known_map"]["plots"][0]["river_edges"] = [
            {"dx": -1, "dy": 0, "edge_id": "E"},
            {"dx": 0, "dy": 1, "edge_id": "SW"},
            {"dx": 0, "dy": -1, "edge_id": "SE"},
        ]
        civ5_adapter.validate_civ5_snapshot(snapshot)

    def test_upgrade_runtime_snapshot(self):
        raw = {
            "schema_version": "civ5ai-input/1",
            "decision": {"turn": 5, "player_id": "PLAYER_0", "phase": "strategic_decision", "reason": "turn_start"},
            "legal_commands": [
                {
                    "command_id": "CMD_research_tech_pottery",
                    "kind": "set_research_tech",
                    "fixed_arguments": {"tech_id": "TECH_POTTERY"},
                }
            ],
            "civ5": {
                "session_id": "runtime-test",
                "map": {"width": 44, "height": 26},
                "yields": {"gold": 0, "science": 0, "culture": 0, "faith": 0, "happiness": 0},
            },
        }
        upgraded = civ5_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual(5, upgraded["decision"]["turn"])
        civ5_adapter.validate_civ5_snapshot(upgraded)

    def test_inject_open_unit_commands_move(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        flat = {
            "scout_1.moveTo": "(15,24)",
            "thought.situation": "Scout east.",
            "thought.strategy": "Explore.",
            "decision_summary": "Move scout.",
        }
        civ5_adapter.inject_open_unit_commands(snapshot, flat)
        command_ids = [item["command_id"] for item in snapshot["legal_commands"]]
        self.assertIn("CMD_move_UNIT_SCOUT_1_15_24", command_ids)

    def test_inject_open_unit_commands_ignores_unknown_unit(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        before = len(snapshot["legal_commands"])
        civ5_adapter.inject_open_unit_commands(snapshot, {"phantom_1.moveTo": "(1,2)"})
        self.assertEqual(before, len(snapshot["legal_commands"]))

    def test_inject_open_unit_commands_binds_via_pipeline(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        flat = {
            "scout_1.moveTo": "(12,34)",
            "thought.situation": "Scout ridge.",
            "thought.strategy": "Move scout.",
            "decision_summary": "Scout move.",
        }
        flat = civ5_adapter.normalize_civ5_wire_flat(flat)
        civ5_adapter.inject_open_unit_commands(snapshot, flat)
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_move_UNIT_SCOUT_1_12_34", command_ids)

    def test_legal_research_wire_resolves(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        flat = {
            "thought.situation": "Research pottery.",
            "thought.strategy": "Finish pottery.",
            "decision_summary": "Research pottery.",
            "legal.research.tech": "TECH_POTTERY",
        }
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_research_tech_pottery", command_ids)

    def test_inject_city_production_commands(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"] = [
            item for item in snapshot["legal_commands"] if item.get("kind") != "queue_production"
        ]
        flat = {
            "Athens.production": "UNIT_SETTLER",
            "thought.situation": "Train a settler.",
            "thought.strategy": "Expand.",
            "decision_summary": "Queue settler in Athens.",
        }
        flat = civ5_adapter.normalize_civ5_wire_flat(flat)
        civ5_adapter.inject_city_production_commands(snapshot, flat)
        command_ids = [item["command_id"] for item in snapshot["legal_commands"]]
        self.assertIn("CMD_prod_CITY_ATHENS_UNIT_SETTLER", command_ids)
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        bound_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_prod_CITY_ATHENS_UNIT_SETTLER", bound_ids)

    def test_inject_special_unit_commands(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        base = snapshot["your_units"][0]
        snapshot["your_units"].extend([
            {
                **base,
                "unit_id": "UNIT_BOMBER_1",
                "unit_type_id": "UNIT_BOMBER",
                "unit_class_id": "UNITCLASS_BOMBER",
                "domain_id": "DOMAIN_AIR",
            },
            {
                **base,
                "unit_id": "UNIT_MISSIONARY_1",
                "unit_type_id": "UNIT_MISSIONARY",
                "unit_class_id": "UNITCLASS_MISSIONARY",
            },
        ])
        flat = {
            "bomber_1.rebaseTo": "(8,9)",
            "bomber_1.rangedAttack": "(14,15)",
            "missionary_1.spread": "apply",
            "scout_1.pillage": "apply",
            "scout_1.upgrade": "UNIT_SPEARMAN",
        }
        civ5_adapter.inject_open_unit_commands(snapshot, flat)
        command_ids = [item["command_id"] for item in snapshot["legal_commands"]]
        self.assertIn("CMD_rebase_UNIT_BOMBER_1_8_9", command_ids)
        self.assertIn("CMD_range_UNIT_BOMBER_1_14_15", command_ids)
        self.assertIn("CMD_spread_UNIT_MISSIONARY_1", command_ids)
        self.assertIn("CMD_pillage_UNIT_SCOUT_1", command_ids)
        self.assertIn("CMD_upgrade_UNIT_SCOUT_1_UNIT_SPEARMAN", command_ids)

    def test_inject_city_production_ignores_unknown_city(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        before = len(snapshot["legal_commands"])
        civ5_adapter.inject_city_production_commands(snapshot, {"Nowhere.production": "UNIT_SETTLER"})
        self.assertEqual(before, len(snapshot["legal_commands"]))


if __name__ == "__main__":
    unittest.main()
