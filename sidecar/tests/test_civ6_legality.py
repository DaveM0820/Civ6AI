"""One legality layer: tiles, diplo, government, city-strike parity, idle defaults, frontier."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sidecar import civ6_legality as legal


def _snap(**extra):
    snap = {
        "decision": {"player_id": "PLAYER_0", "turn": 20},
        "your_units": [{
            "unit_id": "UNIT_1", "unit_type_id": "UNIT_SCOUT", "domain_id": "DOMAIN_LAND",
            "plot_id": "PLOT_2_2", "needs_orders": True, "movement": {"current": 3, "maximum": 3},
        }],
        "your_cities": [{"city_id": "CITY_1", "plot_id": "PLOT_2_2", "name": "Capital"}],
        "your_empire": {"research": {"known_tech_ids": ["TECH_MINING"]}},
        "known_map": {"plots": [
            {"x": 2, "y": 2, "water": False, "peak": False},
            {"x": 3, "y": 2, "water": False, "peak": False},
            {"x": 4, "y": 2, "water": False, "peak": True, "terrain_id": "TERRAIN_GRASS_MOUNTAIN"},
            {"x": 2, "y": 3, "water": True, "peak": False},
            {"x": 3, "y": 3, "water": False, "peak": False},
        ]},
        "legal_commands": [],
        "civ6": {"diplomacy": {"majors": [
            {"player_id": "PLAYER_1", "at_war": False, "can_declare_war": True, "can_make_peace": True},
        ], "city_states": []}, "governance": {"government": {
            "current": "GOVERNMENT_CHIEFDOM",
            "change_allowed": False,
            "available": [{"id": "GOVERNMENT_AUTOCRACY"}],
        }}, "combat": {"city_strike_available": True, "hostiles": [], "hostile_cities": []}},
        "history": {"command_results": []},
    }
    snap.update(extra)
    return snap


class LegalityLayerTests(unittest.TestCase):
    def test_mountain_water_occupied_rejected(self):
        snap = _snap()
        snap["your_units"].append({
            "unit_id": "UNIT_RAM", "unit_type_id": "UNIT_BATTERING_RAM",
            "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_3_2",
        })
        self.assertEqual(legal.move_problem(snap, "UNIT_1", 4, 2), "impassable")
        self.assertEqual(legal.move_problem(snap, "UNIT_1", 2, 3), "impassable")
        self.assertEqual(legal.move_problem(snap, "UNIT_1", 3, 2), "occupied")
        self.assertIsNone(legal.move_problem(snap, "UNIT_1", 3, 3))
        kept, rejected = legal.filter_orders(snap, [
            {"kind": "move_unit", "arguments": {"unit_id": "UNIT_1", "target_x": 4, "target_y": 2}},
            {"kind": "move_unit", "arguments": {"unit_id": "UNIT_1", "target_x": 3, "target_y": 3}},
        ])
        self.assertEqual(len(kept), 1)
        self.assertTrue(any("impassable" in note for note in rejected))

    def test_peace_and_government_off_turn(self):
        snap = _snap()
        self.assertNotIn("PEACE_TREATY", legal.diplo_actions(snap, "PLAYER_1"))
        self.assertEqual(legal.diplo_problem(snap, "PLAYER_1", "PEACE_TREATY"), "peace_not_at_war")
        self.assertEqual(legal.pact_problem(snap, "PLAYER_1", {"peace"}), "peace_not_at_war")
        self.assertFalse(legal.change_government_allowed(snap))
        self.assertEqual(
            legal.order_problem(snap, {"kind": "change_government", "arguments": {"government_id": "GOVERNMENT_AUTOCRACY"}}),
            "government_locked",
        )
        snap["civ6"]["governance"]["government"]["change_allowed"] = True
        self.assertTrue(legal.change_government_allowed(snap))

    def test_city_strike_parity_between_paths(self):
        snap = _snap()
        snap["legal_commands"] = [{
            "command_id": "CMD_citystrike_1_5_5", "kind": "city_attack",
            "fixed_arguments": {"city_id": "CITY_1", "target_x": 5, "target_y": 5},
        }]
        self.assertTrue(legal.city_strike_available(snap))
        auto = legal.unused_city_strikes(snap, [])
        model = {"kind": "city_attack", "arguments": {"city_id": "CITY_1", "target_x": 5, "target_y": 5}}
        self.assertIsNone(legal.order_problem(snap, model))
        self.assertEqual(len(auto), 1)
        self.assertEqual(auto[0]["kind"], "city_attack")
        self.assertEqual(legal.unused_city_strikes(snap, [model]), [])
        snap["civ6"]["combat"]["city_strike_available"] = False
        snap["legal_commands"] = []
        self.assertFalse(legal.city_strike_available(snap))
        self.assertEqual(legal.order_problem(snap, model), "city_strike_unavailable")
        self.assertEqual(legal.unused_city_strikes(snap, []), [])

    def test_idle_default_table(self):
        snap = _snap()
        snap["your_units"] = [
            {"unit_id": "UNIT_W", "unit_type_id": "UNIT_WARRIOR", "unit_class_id": "FORMATION_CLASS_LAND_COMBAT",
             "domain_id": "DOMAIN_LAND", "plot_id": "PLOT_2_2", "needs_orders": True,
             "movement": {"current": 2}},
            {"unit_id": "UNIT_B", "unit_type_id": "UNIT_BUILDER", "domain_id": "DOMAIN_LAND",
             "plot_id": "PLOT_3_3", "needs_orders": True, "build_charges": 3,
             "movement": {"current": 2}},
            {"unit_id": "UNIT_S", "unit_type_id": "UNIT_SCOUT", "domain_id": "DOMAIN_LAND",
             "plot_id": "PLOT_2_2", "needs_orders": True, "movement": {"current": 3}},
        ]
        snap["known_map"]["plots"].append({
            "x": 3, "y": 2, "water": False, "peak": False,
            "revealed_owner_id": "PLAYER_0",
        })
        self.assertEqual(legal.unit_role(snap["your_units"][0]), "military")
        self.assertEqual(legal.ROLE_DEFAULTS[legal.unit_role(snap["your_units"][0])], "defend")
        self.assertEqual(legal.ROLE_DEFAULTS[legal.unit_role(snap["your_units"][1])], "improve")
        self.assertEqual(legal.ROLE_DEFAULTS[legal.unit_role(snap["your_units"][2])], "explore")
        extras = legal.idle_defaults(snap, [])
        kinds = {c["arguments"]["unit_id"]: c["kind"] for c in extras}
        self.assertEqual(kinds["UNIT_W"], "unit_posture_fortify")
        self.assertEqual(kinds["UNIT_B"], "move_unit")
        self.assertIn(kinds["UNIT_S"], {"move_unit", "explore"})
        line = legal.idle_prompt_line(snap)
        self.assertIn("host default applied", line)
        self.assertIn("UNIT_WARRIOR", line)

    def test_frontier_bfs_and_blacklist_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            seat = Path(tmp) / "PLAYER_0"
            seat.mkdir()
            snap = _snap()
            snap["_session_dir"] = str(seat)
            snap["decision"]["turn"] = 50
            dest = legal.frontier_target(snap, snap["your_units"][0])
            self.assertIsNotNone(dest)
            self.assertNotEqual(dest, (4, 2))
            legal.add_blacklist(snap, dest[0], dest[1], 50)
            self.assertTrue(legal.is_blacklisted(snap, dest[0], dest[1]))
            snap["decision"]["turn"] = 59
            self.assertTrue(legal.is_blacklisted(snap, dest[0], dest[1]))
            snap["decision"]["turn"] = 60
            self.assertFalse(legal.is_blacklisted(snap, dest[0], dest[1]))
            snap["decision"]["turn"] = 50
            snap["history"]["command_results"] = [{
                "turn": 50, "reason": "explore_no_reveal:explore_to=3,3", "order_kind": "explore",
            }]
            legal.ingest_results(snap)
            self.assertTrue(legal.is_blacklisted(snap, 3, 3))


if __name__ == "__main__":
    unittest.main()
