"""Shared snapshot primitives: plot_xy and odd-r hex distance."""
from __future__ import annotations

import unittest

from sidecar import civ6_common as common
from sidecar import civ6_legality as legality


class PlotXyTests(unittest.TestCase):
    def test_reads_xy_plot_id_and_plot_x(self):
        self.assertEqual((4, 9), common.plot_xy({"x": 4, "y": 9}))
        self.assertEqual((4, 9), common.plot_xy({"plot_id": "PLOT_4_9"}))
        self.assertEqual((4, 9), common.plot_xy("PLOT_4_9"))
        self.assertEqual((4, 9), common.plot_xy({"plot_x": 4, "plot_y": 9}))
        self.assertIsNone(common.plot_xy(None))
        self.assertIsNone(common.plot_xy({}))

    def test_legality_plot_xy_is_the_shared_function(self):
        self.assertIs(legality.plot_xy, common.plot_xy)
        self.assertEqual((10, 11), legality.plot_xy({"plot_id": "PLOT_10_11"}))


class HexDistTests(unittest.TestCase):
    def test_odd_r_neighbors_are_distance_one(self):
        self.assertEqual(0, common.hex_dist(5, 5, 5, 5))
        self.assertEqual(1, common.hex_dist(5, 5, 6, 5))
        self.assertEqual(1, common.hex_dist(5, 5, 5, 6))

    def test_wrap_false_matches_the_old_copies(self):
        self.assertEqual(common.hex_dist(0, 0, 19, 0, width=20, wrap=False), 19)
        self.assertEqual(common.hex_dist(0, 0, 19, 0, width=20, wrap=True), 1)


if __name__ == "__main__":
    unittest.main()
