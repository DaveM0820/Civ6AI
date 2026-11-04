"""Game 11 fixes: scouting fact line, naval primer, multi-pair governor assign."""
from __future__ import annotations

import unittest

from sidecar import civ6_attention
from sidecar import civ6_governance as governance
from sidecar import civ6_prompt_coaching as coaching


def _snap():
    plots = []
    for x in range(4):
        for y in range(4):
            plots.append({"x": x, "y": y, "water": x >= 2,
                          "terrain_id": "TERRAIN_OCEAN" if x == 3 else ("TERRAIN_COAST" if x == 2 else "TERRAIN_GRASS")})
    return {
        "game": {"turn": 30, "map_width": 10, "map_height": 10, "wrap_x": False},
        "known_map": {"plots": plots, "revealed_count": 16},
        "your_units": [
            {"unit_id": "U1", "unit_type_id": "UNIT_GALLEY", "unit_class_id": "FORMATION_CLASS_NAVAL", "domain_id": "DOMAIN_SEA"},
            {"unit_id": "U2", "unit_type_id": "UNIT_BUILDER", "unit_class_id": "FORMATION_CLASS_CIVILIAN"},
        ],
        "your_cities": [],
        "civ6": {"economy": {"tracking": {"idle_turns": {"U1": 4, "U2": 9}}}},
    }


class ScoutingLineTests(unittest.TestCase):
    def test_fact_line_counts_water_frontier_and_idle_ship(self):
        text = coaching.civ6_scouting_fact_line(_snap())
        self.assertTrue(text.startswith("SCOUTING: 16% of the map revealed"))
        # water x=2..3, frontier rows: y=3 (south edge on-map) and x=3 east neighbours unknown
        self.assertIn("revealed water tiles border unexplored tiles", text)
        self.assertIn("the rest are ocean", text)
        self.assertIn("Units idle while that frontier exists", text)
        self.assertIn("4t", text)
        self.assertNotIn("9t", text)  # civilians are not listed

    def test_fact_line_is_registered_high_priority(self):
        items = [i for i in civ6_attention.collect(_snap()) if i.text.startswith("SCOUTING:")]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].priority, 1)

    def test_primer_is_generic_and_covers_sea_exploration(self):
        p = coaching.CIV6_GAME_PRIMER
        self.assertNotIn("archipelago", p)
        self.assertIn("embarked land units", p)
        self.assertIn("AND water never stops", p)
        self.assertIn("escort embarked settlers", p)


class GovernorAssignTests(unittest.TestCase):
    def _gov_snap(self):
        return {"civ6": {"governance": {
            "routes": {"governors": True},
            "governors": {"supported": True,
                          "appointed": [{"id": "GOVERNOR_THE_DEFENDER"}, {"id": "GOVERNOR_THE_BUILDER"}],
                          "cities": [{"city_id": "C1", "name": "Rome"}, {"city_id": "C2", "name": "Lugdunum"}]},
        }}, "legal_commands": []}

    def test_two_pairs_in_one_value_both_bind(self):
        snap = self._gov_snap()
        ids, notes = governance.bind_reply(snap, "governor.assign",
                                           "THE_DEFENDER @ Rome; THE_BUILDER @ Lugdunum")
        self.assertEqual(len(ids), 2, notes)
        self.assertFalse([n for n in notes if "is not yours" in n])

    def test_single_pair_unchanged(self):
        ids, notes = governance.bind_reply(self._gov_snap(), "governor.assign", "THE_BUILDER @ Lugdunum")
        self.assertEqual(len(ids), 1, notes)


if __name__ == "__main__":
    unittest.main()
