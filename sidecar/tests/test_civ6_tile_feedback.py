import unittest

from sidecar import civ6_apply_results as results
from sidecar import civ6_economy as economy
from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_wire
from sidecar import pipeline_v2


class TileFeedbackTests(unittest.TestCase):
    def test_district_failure_line(self):
        snap = {"decision": {"player_id": "PLAYER_0"},
                "known_map": {"plots": [{"x": 24, "y": 34, "peak": True, "revealed_owner_id": "PLAYER_1"}]}}
        row = {"kind": "queue_production", "ok": False, "reason": "district_tile_invalid",
               "fixed_arguments": {"city_id": "C", "build_id": "DISTRICT_CAMPUS", "target_x": 24, "target_y": 34}}
        text = results.build_command_results(snap, [row], 5)[0]["summary"]
        self.assertTrue(text.startswith("Last turn you tried to place Campus at (24,34) but it failed:"))
        self.assertIn("mountain", text)
        self.assertIn("owned by PLAYER_1", text)

    def test_move_failure_unexplored(self):
        row = {"kind": "move_unit", "ok": False, "reason": "x", "fixed_arguments": {"unit_id": "U", "target_x": 1, "target_y": 2}}
        self.assertIn("tile not explored", results.build_command_results({}, [row], 5)[0]["summary"])


class SettlerAndDistrictTests(unittest.TestCase):
    def test_settlers_covering_all_sites_drop_settler_production(self):
        site = {"sites": [{"x": 4, "y": 5}]}
        snap = {"your_units": [{"unit_id": "A", "unit_type_id": "UNIT_SETTLER", "settle": site},
                               {"unit_id": "B", "unit_type_id": "UNIT_SETTLER", "settle": site}],
                "legal_commands": [{"kind": "queue_production", "fixed_arguments": {"build_id": "UNIT_SETTLER"}},
                                   {"kind": "queue_production", "fixed_arguments": {"build_id": "UNIT_BUILDER"}}]}
        self.assertEqual(civ6_wire.prune_settlers_without_sites(snap), 1)
        self.assertEqual(len(snap["legal_commands"]), 1)
        self.assertTrue(civ6_wire.no_city_sites_lines(snap))

    def test_zero_walkable_sites_are_not_described_as_already_covered(self):
        snap = {"your_units": [{"unit_id": "A", "unit_type_id": "UNIT_SETTLER", "settle": {"sites": []}}],
                "legal_commands": [{"kind": "queue_production", "fixed_arguments": {"build_id": "UNIT_SETTLER"}},
                                   {"kind": "queue_production", "fixed_arguments": {"build_id": "UNIT_BUILDER"}}]}
        self.assertEqual(civ6_wire.prune_settlers_without_sites(snap), 1)
        text = "\n".join(civ6_wire.no_city_sites_lines(snap))
        self.assertIn("No walkable city site", text)
        self.assertIn("embarking", text)
        self.assertNotIn("already cover", text)

    def test_embark_site_names_the_nearest_other_landmass(self):
        unit = {
            "unit_id": "A", "unit_type_id": "UNIT_SETTLER", "plot_id": "PLOT_10_10",
            "settle": {
                "sites": [], "no_reachable_site": True, "here_ok": False,
                "here_reason": "unit_cannot_found_city",
                "embark_site": {"x": 22, "y": 10, "dist": 12, "can_embark": False},
            },
        }
        blob = "\n".join(coaching.settler_fact_lines("settler_1", unit, {
            "game": {"map_width": 40, "wrap_x": True}, "known_map": {"plots": []},
        }))
        self.assertIn("FoundCity illegal here", blob)
        self.assertIn("(22,10)", blob)
        self.assertIn("another landmass", blob)
        self.assertIn("cannot embark yet", blob)

    def test_city_lists_districts_even_when_the_map_image_is_attached(self):
        snap = {
            "decision": {"turn": 5, "player_id": "PLAYER_0"},
            "your_cities": [{"city_id": "CITY_1", "name": "Rome", "population": 2,
                             "production": {"item_id": "BUILDING_MONUMENT"}}],
            "your_units": [],
            "your_empire": {"research": {}},
            "civ6": {"economy": {"cities": [{
                "city_id": "CITY_1",
                "built_buildings": ["BUILDING_MONUMENT"],
                "built_districts": ["DISTRICT_CAMPUS", "DISTRICT_HOLY_SITE (pillaged)"],
            }]}},
        }
        self.assertTrue(pipeline_v2.map_image_attach_turn(snap))
        text = "\n".join(civ6_wire._empire_section(snap))
        self.assertIn("Rome.buildings = BUILDING_MONUMENT", text)
        self.assertIn("Rome.districts = DISTRICT_CAMPUS, DISTRICT_HOLY_SITE (pillaged)", text)

    def test_steel_turns_left_follows_the_engine_number(self):
        snap = {
            "your_empire": {"research": {
                "tech_id": "TECH_STEEL",
                "estimated_turns_remaining": 7,
                "progress": 39,
                "cost": 100,
                "research_per_turn": 10,
                "known_tech_ids": [],
            }},
            "civ6": {"governance": {"techs": {"current": "TECH_STEEL", "turns_left": 6}}},
        }
        lines: list[str] = []
        civ6_wire._append_civ6_empire_wire(lines, snap)
        self.assertIn("empire.research.tech.turns_left = 6", lines)
        self.assertNotIn("empire.research.tech.turns_left = 7", lines)

    def test_district_row_matches_its_tile_only(self):
        cmd = {"kind": "queue_production", "command_id": "CMD_x",
               "fixed_arguments": {"city_id": "C", "build_id": "DISTRICT_CAMPUS", "target_x": 3, "target_y": 4}}
        match = pipeline_v2._command_matches_city_property
        self.assertTrue(match(cmd, "C", ["changeProduction"], "DISTRICT_CAMPUS@(3,4)"))
        self.assertFalse(match(cmd, "C", ["changeProduction"], "DISTRICT_CAMPUS@(5,6)"))


if __name__ == "__main__":
    unittest.main()
