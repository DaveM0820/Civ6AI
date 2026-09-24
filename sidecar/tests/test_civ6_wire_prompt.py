"""Tests for Civ VI wire prompt builder."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from sidecar import civ6_adapter
from sidecar import civ6_wire
from sidecar import pipeline_v2 as pipeline

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PROMPT = ROOT / "fixtures" / "civ6" / "prompt-turn-classical-golden.txt"
GOLDEN_RESPONSE = ROOT / "fixtures" / "civ6" / "response-turn-classical-golden.txt"
CAPABILITIES = ROOT / "config" / "civ6-command-capabilities.json"


class Civ6WirePromptTests(unittest.TestCase):
    def test_golden_prompt_matches_builder(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        wire = civ6_wire.build_civ6_model_wire_text(snapshot).strip()
        golden = GOLDEN_PROMPT.read_text(encoding="utf-8-sig").strip()
        self.assertEqual(golden, wire)

    def test_sections_present(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        wire = civ6_wire.build_civ6_model_wire_text(snapshot)
        self.assertIn("=== CURRENT SITUATION ===", wire)
        self.assertIn("=== MAP ===", wire)
        self.assertIn("=== LEGAL COMMANDS ===", wire)
        self.assertIn("=== INSTRUCTIONS ===", wire)
        self.assertIn("units.nativeControl", wire)
        self.assertIn("cities.nativeProduction", wire)

    def test_chat_lines_in_situation_when_present(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        snapshot["history"]["public_events"] = [
            {
                "turn": 17,
                "kind": "CHAT_PUBLIC",
                "summary": "Cleopatra: Greetings.",
                "affected_ids": ["PLAYER_1"],
            }
        ]
        wire = civ6_wire.build_civ6_model_wire_text(snapshot)
        self.assertIn("chat.public.t17.0", wire)

    def test_flat_wire_parse_no_json_braces(self):
        text = GOLDEN_RESPONSE.read_text(encoding="utf-8-sig")
        self.assertNotIn("{", text)
        self.assertNotIn("}", text)
        parsed = pipeline.parse_flat_wire_lines(text)
        self.assertIn("thought.situation", parsed)
        self.assertIn("legal.research.tech", parsed)

    def test_golden_response_binds_commands(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        flat = pipeline.parse_flat_wire_lines(GOLDEN_RESPONSE.read_text(encoding="utf-8-sig"))
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_research_tech_pottery", command_ids)
        self.assertIn("CMD_scout_move_15_24", command_ids)
        self.assertIn("CMD_settler_move_17_25", command_ids)
        self.assertIn("CMD_spearman_fortify", command_ids)

    def test_found_city_wire_binds_command(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"].append({
            "command_id": "CMD_found_UNIT_SETTLER_1",
            "kind": "found_city",
            "description": "found_city unit_id=UNIT_SETTLER_1",
            "fixed_arguments": {"unit_id": "UNIT_SETTLER_1"},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SETTLER_1"],
            "runtime_status": "implemented_untested",
        })
        flat = {
            "thought.situation": "Settler ready.",
            "thought.strategy": "Found the second city now.",
            "decision_summary": "Found city with settler.",
            "settler_1.foundCity": "apply",
        }
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_found_UNIT_SETTLER_1", command_ids)

    def test_unit_role_prefix_on_move_key_binds_command(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        flat = {
            "thought.situation": "Scout the ridge.",
            "thought.strategy": "Move the scout east.",
            "decision_summary": "Scout east.",
            "Unit: scout_1.moveTo": "(15,24)",
        }
        resolved = pipeline.resolve_property_wire(snapshot, flat)
        expanded = pipeline.expand_flat_response(resolved, snapshot)
        normalized = pipeline.normalize_model_response(snapshot, expanded)
        validated = pipeline.validate_model_response(snapshot, normalized)
        command_ids = [item["command_id"] for item in validated["commands"]]
        self.assertIn("CMD_scout_move_15_24", command_ids)

    def test_found_city_is_encouraged_not_required(self):
        snapshot = civ6_adapter.build_classical_golden_snapshot()
        snapshot["legal_commands"].append({
            "command_id": "CMD_found_UNIT_SETTLER_1",
            "kind": "found_city",
            "description": "found_city unit_id=UNIT_SETTLER_1",
            "fixed_arguments": {"unit_id": "UNIT_SETTLER_1"},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SETTLER_1"],
            "runtime_status": "implemented_untested",
        })
        snapshot["your_cities"] = []
        wire = civ6_wire.build_civ6_response_instructions(snapshot)
        self.assertNotIn("must include", wire)
        self.assertNotIn("foundCity = apply this turn", wire)
        self.assertNotIn("as soon as a legal tile is available", wire)
        self.assertIn("foundCity is optional", wire)


if __name__ == "__main__":
    unittest.main()
