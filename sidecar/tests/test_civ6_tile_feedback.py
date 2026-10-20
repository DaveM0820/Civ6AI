import unittest

from sidecar import civ6_apply_results as results
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

    def test_district_row_matches_its_tile_only(self):
        cmd = {"kind": "queue_production", "command_id": "CMD_x",
               "fixed_arguments": {"city_id": "C", "build_id": "DISTRICT_CAMPUS", "target_x": 3, "target_y": 4}}
        match = pipeline_v2._command_matches_city_property
        self.assertTrue(match(cmd, "C", ["changeProduction"], "DISTRICT_CAMPUS@(3,4)"))
        self.assertFalse(match(cmd, "C", ["changeProduction"], "DISTRICT_CAMPUS@(5,6)"))


if __name__ == "__main__":
    unittest.main()
