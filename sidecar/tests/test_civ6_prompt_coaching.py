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

    def test_map_axes_civ6_y_north_by_default(self):
        note = coaching.civ6_map_axes_wrap_guidance({"game": {"map_width": 80, "wrap_x": True}})
        self.assertIn("y increases north", note.lower())
        self.assertIn("wraps east-west", note)
        self.assertIn("x=79 is next to x=0", note)

    def test_map_axes_civ6_y_south_when_measured(self):
        note = coaching.civ6_map_axes_wrap_guidance({
            "game": {"map_width": 80, "wrap_x": True},
            "civ6": {"map": {"coords_note": "grid x,y; Y increases south (measured north_dy=-1)"}},
        })
        self.assertIn("y increases south", note.lower())

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
        self.assertIn("=== REQUIRED COMMANDS ===", text)
        self.assertIn("strategicmap.read", text)
        self.assertIn("thought.situation", text)
        self.assertIn("OPTIONAL COMMANDS are encouraged", text)
        self.assertIn("y increases north", text.lower())
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



    def test_expansion_and_chat_coaching_constants(self):
        self.assertIn("do not repeat", coaching.CIV6_CHAT_VARIETY_COACHING.lower())

    def test_explored_percent_is_the_whole_map_not_the_picture(self):
        from sidecar.map_situational import format_strategic_window

        snap = {
            "game": {"map_width": 74, "map_height": 46, "wrap_x": True},
            "decision": {"turn": 131, "player_id": "PLAYER_0"},
            "personality": {"leader_name": "Montezuma", "civilization_id": "CIVILIZATION_AZTEC"},
            "your_units": [{
                "unit_id": "UNIT_9",
                "unit_type_id": "UNIT_SCOUT",
                "needs_orders": True,
                "movement": {"current": 3},
            }],
            "your_cities": [],
            "legal_commands": [{
                "command_id": "CMD_explore_UNIT_9",
                "kind": "explore",
                "fixed_arguments": {"unit_id": "UNIT_9"},
            }],
            "known_map": {
                "explored_percent": 18,
                "revealed_count": 612,
                "visibility_grid": ["." * 31] * 34,
                "viewport": {"x0": 25, "y0": 2, "width": 31, "height": 34},
            },
        }
        self.assertEqual(18, coaching._civ6_explored_percent(snap))
        window = format_strategic_window(snap["known_map"]["viewport"], 74, 46)
        self.assertIn("window 31% of the map", window)
        self.assertNotIn("(31%)", window)
        prompt = civ6_wire.build_civ6_wire_prompt(snap)
        self.assertIn("map.explored = 18%", prompt)
        self.assertIn("map.unexplored = 82%", prompt)
        self.assertIn("delegation does not", prompt.lower())
        instructions = civ6_wire.build_civ6_response_instructions(snap)
        self.assertIn("Automate(explore)", instructions)
        self.assertIn("Nothing assigns this for you", instructions)
        advice = "\n".join(civ6_wire._advice_section(snap))
        self.assertIn("82% still unexplored gray fog", advice)
        self.assertIn("Automate(explore)", advice)
        self.assertIn("just as valid", advice)
        # 612 / (74*46) is the real visibility. The cached 18% stays on map.explored.
        self.assertIn("map.revealed_tiles = 612 of 3404 tiles", prompt)
        self.assertIn("17%", prompt)
        self.assertNotIn("NAVAL EXPLORE", prompt)

    def test_naval_explore_is_pushed_when_a_ship_can_move(self):
        snap = {
            "game": {"map_width": 74, "map_height": 46},
            "decision": {"turn": 40, "player_id": "PLAYER_0"},
            "your_units": [{
                "unit_id": "UNIT_3",
                "unit_type_id": "UNIT_GALLEY",
                "domain_id": "DOMAIN_SEA",
                "needs_orders": True,
                "movement": {"current": 2},
            }],
            "your_cities": [],
            "known_map": {"explored_percent": 12},
        }
        note = coaching.civ6_naval_explore_attention(snap)
        self.assertIn("NAVAL EXPLORE", note)
        self.assertIn("12%", note)
        snap["your_units"][0]["movement"]["current"] = 0
        self.assertIsNone(coaching.civ6_naval_explore_attention(snap))
        from sidecar.civ6_apply_results import describe_reason
        self.assertIn(
            "did not reveal",
            describe_reason("explore_no_reveal:explore_to=1,1:d=1:no_new_tiles"),
        )

    def test_revealed_count_fills_explored_percent_when_the_field_is_missing(self):
        snap = {
            "game": {"map_width": 74, "map_height": 46},
            "known_map": {"revealed_count": 612, "visibility_grid": ["...."]},
        }
        self.assertEqual((612 * 100) // (74 * 46), coaching._civ6_explored_percent(snap))

    def test_explore_command_is_not_advertised_when_it_is_not_legal(self):
        snap = {
            "personality": {"leader_name": "Pericles", "civilization_id": "CIVILIZATION_GREECE"},
            "your_units": [],
            "your_cities": [],
            "legal_commands": [],
            "decision": {"turn": 3},
            "game": {"map_width": 60, "wrap_x": True},
        }
        text = civ6_wire.build_civ6_response_instructions(snap)
        self.assertNotIn("Automate(explore)", text)

    def test_advice_mentions_expansion_when_settler_present(self):
        snap = {
            "your_units": [{"unit_id": "UNIT_1", "unit_type_id": "UNIT_SETTLER"}],
            "your_cities": [{"city_id": "CITY_1", "name": "Capital"}],
            "legal_commands": [
                {"kind": "found_city", "fixed_arguments": {"unit_id": "UNIT_1"}},
            ],
            "game": {"map_width": 80, "wrap_x": True},
        }
        # _advice_section is private-ish; use build path that includes advice
        from sidecar import civ6_wire
        from sidecar import civ6_attention

        settle = [i for i in civ6_attention.collect(snap) if i.topic == "settle"]
        self.assertEqual(1, sum(i.text.startswith("SETTLE:") for i in settle))
        self.assertEqual(("settler_1.command = FoundCity",), settle[0].commands)
        self.assertIn("Found a city this turn: settler_1.command = FoundCity", settle[0].text)
        self.assertNotIn("Settler", "\n".join(civ6_wire._advice_section(snap)))


if __name__ == "__main__":
    unittest.main()
