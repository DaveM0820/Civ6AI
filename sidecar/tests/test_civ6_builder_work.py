"""Builder work: charges vs open improvable tiles, shared by scoring and ATTENTION; repeat-rejection note."""
from __future__ import annotations

import tempfile
import unittest

from sidecar import civ6_attention
from sidecar import civ6_legality as legal
from sidecar import civ6_priorities as prio
from sidecar import civ6_prompt_coaching as coaching


def _builder(uid, charges=3):
    return {"unit_id": uid, "unit_type_id": "UNIT_BUILDER", "build_charges": charges, "plot_id": "PLOT_1_1"}


def _improve(uid, x, y):
    return {"command_id": f"CMD_{uid}_improve_{x}_{y}", "kind": "move_unit",
            "fixed_arguments": {"unit_id": uid, "target_x": x, "target_y": y,
                                "improvement_id": "IMPROVEMENT_FARM", "intent": "improve", "A": 2}}


def _snap(builders=6, offers=()):
    units = [_builder(f"UNIT_{i}") for i in range(builders)]
    return {"decision": {"player_id": "PLAYER_0", "turn": 30},
            "your_units": units, "your_cities": [{"city_id": "CITY_1", "name": "Pokrovka"}],
            "legal_commands": [_improve("UNIT_0", x, y) for x, y in offers],
            "civ6": {"priorities": [{"id": prio.BY_KEY["improvements"]["id"], "level": 2}]}}


class BuilderWorkTests(unittest.TestCase):
    def test_counts_open_tiles_from_improve_offers(self):
        self.assertEqual(prio.builder_work(_snap(2, [(3, 4), (3, 4), (5, 6)])), (2, 6, 2))
        self.assertEqual(prio.builder_work(_snap(0)), (0, 0, None))

    def test_surplus_builder_scores_below_monument(self):
        sit = prio.situation_for_city(_snap(6, []), {"name": "Pokrovka"})
        self.assertTrue(sit["builder_surplus"])
        builder = prio.item_score("UNIT_BUILDER", ["PSEUDOYIELD_IMPROVEMENT"], sit, "unit")
        monument = prio.item_score("BUILDING_MONUMENT", ["YIELD_CULTURE"], sit, "building")
        self.assertLess(builder, monument)

    def test_builder_wanted_when_tiles_open(self):
        sit = prio.compose_situation(builders=1, builder_charges=2, open_tiles=5, cities=1)
        self.assertFalse(sit["builder_surplus"])
        self.assertGreaterEqual(sit["levels"].get(prio.BY_KEY["improvements"]["id"], 0), 1)

    def test_unknown_work_keeps_old_rule(self):
        sit = prio.compose_situation(builders=0, cities=2)
        self.assertFalse(sit["builder_surplus"])

    def test_attention_line(self):
        line = coaching.civ6_builder_work_attention(_snap(6, []))
        self.assertIn("6 builders with 18 charges", line)
        self.assertNotIn("improvements off", line)
        self.assertIsNone(coaching.civ6_builder_work_attention(_snap(1, [(1, 2), (2, 2), (3, 2)])))
        self.assertIn(line, civ6_attention.lines(_snap(6, [])))


class RepeatRejectionTests(unittest.TestCase):
    def test_repeat_note_with_advice(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = {"_session_dir": tmp, "decision": {"turn": 30}}
            for turn in (28, 29):
                legal.remember_rejections(snap, [{"order": "MoveTo(17,24)", "reason": "occupied", "turn": turn}])
            lines = legal.rejection_lines(snap)
            self.assertEqual(len(lines), 1)
            self.assertIn("rejected on 2 turns", lines[0])
            self.assertNotIn("move the unit that stands there", lines[0])

    def test_single_rejection_has_no_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = {"_session_dir": tmp, "decision": {"turn": 30}}
            legal.remember_rejections(snap, [{"order": "MoveTo(1,1)", "reason": "impassable", "turn": 29}])
            self.assertNotIn("stop ordering", legal.rejection_lines(snap)[0])


if __name__ == "__main__":
    unittest.main()
