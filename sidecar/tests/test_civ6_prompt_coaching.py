"""Tests for Civ6 prompt coaching ported from Civ5 patterns."""
from __future__ import annotations

import unittest

from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_wire


class Civ6PromptCoachingTests(unittest.TestCase):
    def test_required_thought_rows_include_maps_and_thoughts(self):
        rows = coaching.civ6_required_thought_rows({"decision": {"turn": 1}})
        joined = "\n".join(rows)
        self.assertIn("strategicmap.read", joined)
        self.assertIn("thought.situation", joined)
        self.assertIn("thought.strategy", joined)
        self.assertTrue(any(r.startswith("thought.situation") for r in rows))

    def test_optional_preamble_encourages_extra_commands(self):
        lines = coaching.civ6_optional_commands_preamble_lines(4)
        blob = "\n".join(lines)
        self.assertIn("no cap", blob.lower())
        self.assertIn("optional", blob.lower())
        self.assertIn("1 to 4", blob)

    def test_map_axes_civ6_y_south(self):
        note = coaching.civ6_map_axes_wrap_guidance({"game": {"map_width": 80, "wrap_x": True}})
        self.assertIn("y increases south", note.lower())
        self.assertIn("x=70", note)
        self.assertIn("x=10", note)

    def test_hp_label_hides_full_health(self):
        self.assertIsNone(coaching.civ6_wounded_hp_label(100))
        self.assertEqual("42%", coaching.civ6_wounded_hp_label(42))

    def test_retreat_attention_under_30(self):
        snap = {
            "your_units": [
                {
                    "unit_id": "UNIT_1",
                    "unit_type_id": "UNIT_WARRIOR",
                    "health": {"current": 20, "maximum": 100},
                }
            ]
        }
        note = coaching.civ6_low_hp_retreat_attention(snap)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("20% HP", note)
        self.assertIn("retreat", note.lower())

    def test_focus_fire_attention(self):
        snap = {
            "your_units": [
                {"unit_id": "UNIT_1", "unit_type_id": "UNIT_ARCHER"},
                {"unit_id": "UNIT_2", "unit_type_id": "UNIT_WARRIOR"},
            ],
            "legal_commands": [
                {
                    "kind": "attack_target",
                    "fixed_arguments": {"unit_id": "UNIT_1", "target_x": 5, "target_y": 6},
                },
                {
                    "kind": "attack_target",
                    "fixed_arguments": {"unit_id": "UNIT_2", "target_x": 5, "target_y": 6},
                },
            ],
        }
        note = coaching.civ6_focus_fire_attention(snap)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("focus-fire", note.lower())

    def test_attack_options_append_without_none(self):
        opts = coaching.append_attack_options_to_unit_line(
            ["(1,1)", "(2,2)"],
            ["attackTo/(5,6)", "none"],
        )
        self.assertEqual(["(1,1)", "(2,2)", "attackTo/(5,6)"], opts)

    def test_economy_negative_gpt(self):
        notes = coaching.civ6_economy_attention(
            {"your_empire": {"gold": 10, "gold_per_turn": -8, "amenities": {"net": -2}}}
        )
        blob = "\n".join(notes)
        self.assertIn("Gold per turn is -8", blob)
        self.assertIn("amenities", blob.lower())

    def test_wire_instructions_include_required_thought_rows(self):
        snap = {
            "personality": {"leader_name": "Pericles", "civilization_id": "CIVILIZATION_GREECE"},
            "your_units": [],
            "your_cities": [],
            "legal_commands": [],
            "decision": {"turn": 3},
            "game": {"map_width": 60, "wrap_x": True},
        }
        text = civ6_wire.build_civ6_response_instructions(snap)
        self.assertIn("=== REQUIRED COMMANDS THIS TURN ===", text)
        self.assertIn("strategicmap.read", text)
        self.assertIn("thought.situation", text)
        self.assertIn("OPTIONAL COMMANDS are encouraged", text)
        self.assertIn("y increases south", text.lower())
        self.assertIn("stacking", text.lower())

    def test_ranged_attack_wire_binds_to_attack_target(self):
        from sidecar.pipeline_v2 import _command_matches_unit_property

        command = {
            "kind": "attack_target",
            "command_id": "CMD_attack_u1",
            "fixed_arguments": {"unit_id": "UNIT_1", "target_x": 9, "target_y": 4},
        }
        self.assertTrue(
            _command_matches_unit_property(
                command, "UNIT_1", "archer_1", ["rangedAttack"], "(9,4)"
            )
        )
        self.assertTrue(
            _command_matches_unit_property(
                command, "UNIT_1", "archer_1", ["attackTo"], "(9,4)"
            )
        )


if __name__ == "__main__":
    unittest.main()
