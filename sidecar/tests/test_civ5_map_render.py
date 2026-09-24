"""Tests for Civ V map rendering path."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sidecar import civ5_adapter
from sidecar import civ5_assets
from sidecar import civ6_assets
from sidecar import map_icons
from sidecar import map_render
from sidecar.map_render_civ5 import render_civ5_map_for_model
from sidecar.map_render_civ6 import (
    CIV5_RIVER_EDGE_INDEX,
    HEX_AXIS_ONLY_MIN_CELLS,
    collect_settle_markers,
    _civ5_river_edge_from_delta,
    _hex_coord_label_flags,
    _river_polylines,
)


class Civ5MapRenderTests(unittest.TestCase):
    def test_classical_snapshot_renders_hex_tiles(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        plot_index = map_render.build_render_plot_index(snapshot)
        self.assertGreater(len(plot_index), 0)
        with mock.patch.object(civ5_assets, "strategic_layer_png_paths", return_value=[]):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "map.png"
                meta = render_civ5_map_for_model(snapshot, path)
        self.assertGreater(meta.get("rendered_tiles", 0), 0)
        self.assertEqual("odd-r-flat-top", meta.get("hex_layout"))
        self.assertIn("data_url", meta)
        # No ranked settle overlays (shared Civ5/Civ6 policy): model reads the map.
        self.assertEqual(0, meta.get("settle_rings_drawn", 0))
        self.assertFalse(meta.get("legend_has_terrain"))
        self.assertFalse(meta.get("legend_has_markers"))
        self.assertFalse(meta.get("show_axis_labels"))
        self.assertTrue(meta.get("show_tile_coords"))

    def test_hex_coord_flags_switch_at_double_tight_view(self):
        self.assertEqual((False, True), _hex_coord_label_flags(8, 12))
        self.assertEqual((True, False), _hex_coord_label_flags(16, 12))
        self.assertEqual(192, HEX_AXIS_ONLY_MIN_CELLS)

    def test_ruins_plot_is_in_render_index(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        plot_index = map_render.build_render_plot_index(snapshot)
        ruins = plot_index.get((13, 21))
        self.assertIsNotNone(ruins)
        self.assertEqual("IMPROVEMENT_GOODY_HUT", ruins.get("improvement_id"))

    def test_known_map_viewport_from_plots(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        plot_index = map_render.build_render_plot_index(snapshot)
        viewport = map_render.compute_viewport(snapshot, plot_index)
        self.assertGreater(viewport["width"], 0)
        self.assertGreater(viewport["height"], 0)

    def test_settle_markers_empty_no_ranked_overlays(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        markers = collect_settle_markers(snapshot)
        self.assertEqual([], markers)

    def test_civ5_render_skips_civ6_strategic_tiles(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        map_icons.set_render_context(prefer_civ5=True)
        with mock.patch.object(civ6_assets, "assets_available", return_value=True):
            with mock.patch.object(civ5_assets, "assets_available", return_value=True):
                with mock.patch.object(civ5_assets, "strategic_layer_png_paths", return_value=[]):
                    with mock.patch.object(civ6_assets, "strategic_png_path") as civ6_sv:
                        with tempfile.TemporaryDirectory() as tmp:
                            path = Path(tmp) / "map.png"
                            render_civ5_map_for_model(snapshot, path)
                        civ6_sv.assert_not_called()
        map_icons.set_render_context(prefer_civ5=False)

    def test_civ5_river_delta_maps_to_e_se_sw_screen_edges(self):
        self.assertEqual(CIV5_RIVER_EDGE_INDEX["E"], 5)
        self.assertEqual(CIV5_RIVER_EDGE_INDEX["SE"], 0)
        self.assertEqual(CIV5_RIVER_EDGE_INDEX["SW"], 1)
        self.assertEqual(_civ5_river_edge_from_delta(46, 24, -1, 0), 5)
        self.assertEqual(_civ5_river_edge_from_delta(46, 24, -1, 1), 0)
        self.assertEqual(_civ5_river_edge_from_delta(47, 22, 0, 1), 1)
        self.assertEqual(_civ5_river_edge_from_delta(45, 23, -1, 0), 5)
        self.assertEqual(_civ5_river_edge_from_delta(46, 23, 1, 1), 1)
        self.assertIsNone(_civ5_river_edge_from_delta(47, 24, 0, -1))

    def test_river_polylines_join_shared_vertices(self):
        a, b, c = (0, 0), (10, 0), (15, 8)
        paths = _river_polylines([(a, b), (b, c)])
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(paths[0]), 3)

    def test_weld_segments_merges_nearby_vertices(self):
        from sidecar.map_render_civ6 import _weld_segments
        segs = [((0, 0), (10, 0)), ((11, 1), (20, 8))]
        welded = _weld_segments(segs, 3)
        paths = _river_polylines(welded)
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(paths[0]), 3)


if __name__ == "__main__":
    unittest.main()
