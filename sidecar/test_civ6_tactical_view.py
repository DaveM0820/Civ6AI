import json
import tempfile
import unittest
from pathlib import Path

from sidecar import civ6_tactical_view as tv


def _snap(turn=10, units=None, plots=None, cities=None, width=40, wrap=True):
    return {
        "decision": {"turn": turn, "player_id": "PLAYER_0"},
        "game": {"map_width": width, "map_height": 30, "wrap_x": wrap},
        "your_units": units or [],
        "visible_other_units": [],
        "your_cities": cities if cities is not None else [{"plot_id": "PLOT_10_10", "is_capital": True}],
        "known_map": {"plots": plots or []},
    }


class TacticalViewTest(unittest.TestCase):
    def test_home_territory_framed_when_peaceful(self):
        plots = [{"x": x, "y": y, "revealed_owner_id": "PLAYER_0"} for x in range(8, 13) for y in range(8, 13)]
        rect, why = tv.pick_tactical_frame(_snap(plots=plots), at_war=False, damage=[])
        self.assertEqual(why, "home territory")
        self.assertEqual((rect["width"], rect["height"]), (tv.TACTICAL_TILES, tv.TACTICAL_TILES))
        self.assertTrue(rect["x0"] <= 8 and rect["x0"] + rect["width"] > 12)
        self.assertTrue(rect["y0"] <= 8 and rect["y0"] + rect["height"] > 12)

    def test_damage_wins_and_is_detected_from_hp_drop(self):
        unit = {"unit_id": "U1", "plot_id": "PLOT_30_20", "health_percent": 100}
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tv.update_damage(_snap(turn=5, units=[unit]), Path(d)), [])
            hurt = dict(unit, health_percent=60)
            self.assertEqual(tv.update_damage(_snap(turn=6, units=[hurt]), Path(d)), [(30, 20)])
            # Still shown the turn after, gone two turns later.
            self.assertEqual(tv.update_damage(_snap(turn=7, units=[hurt]), Path(d)), [(30, 20)])
            self.assertEqual(tv.update_damage(_snap(turn=8, units=[hurt]), Path(d)), [])
        rect, why = tv.pick_tactical_frame(_snap(), at_war=True, damage=[(30, 20)])
        self.assertIn("fighting", why)
        self.assertTrue(rect["x0"] <= 30 < rect["x0"] + rect["width"])

    def test_frame_crosses_east_west_seam(self):
        plots = [{"x": x % 40, "y": 10, "revealed_owner_id": "PLAYER_0"} for x in range(37, 43)]
        snap = _snap(plots=plots, cities=[{"plot_id": "PLOT_39_10", "is_capital": True}])
        rect, _ = tv.pick_tactical_frame(snap, at_war=False, damage=[])
        covered = {(rect["x0"] + i) % 40 for i in range(rect["width"])}
        self.assertTrue({37, 38, 39, 0, 1, 2} <= covered)

    def test_rotate_snapshot_moves_x_and_plot_ids(self):
        snap = _snap(units=[{"unit_id": "U", "plot_id": "PLOT_1_5", "health_percent": 100}],
                     plots=[{"x": 38, "y": 5}])
        snap["known_map"]["visibility_grid"] = ["ab" + "?" * 38]
        snap["known_map"]["viewport"] = {"x0": 0, "y0": 5, "width": 40, "height": 1}
        out = tv.rotate_snapshot_x(snap, 36)
        self.assertEqual(out["your_units"][0]["plot_id"], "PLOT_5_5")
        self.assertEqual(out["known_map"]["plots"][0]["x"], 2)
        self.assertEqual(out["known_map"]["visibility_grid"][5][4:6], "ab")
        self.assertEqual(snap["your_units"][0]["plot_id"], "PLOT_1_5")


if __name__ == "__main__":
    unittest.main()
