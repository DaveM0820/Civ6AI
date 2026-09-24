"""Tests for Civ VI map renderer."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sidecar import civ6_adapter
from sidecar import map_render
from sidecar.map_render_civ6 import render_civ6_map_for_model, render_civ6_map_png

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "civ6" / "snapshot-turn-classical-golden.json"


class Civ6MapRenderTests(unittest.TestCase):
    def test_render_png_bytes(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        snapshot["known_map"]["visibility_grid"] = ["....", ".~..", "...."]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.png"
            meta = render_civ6_map_png(snapshot, path)
            self.assertTrue(path.is_file())
            self.assertGreater(meta["image_bytes"], 100)
            self.assertEqual("image/png", meta["mime_type"])
            self.assertIn("data:image/png;base64,", meta["data_url"])

    def test_render_with_river_edges(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        snapshot["game"]["map_width"] = 3
        snapshot["game"]["map_height"] = 3
        snapshot["known_map"]["plots"] = [
            {
                "plot_id": "PLOT_1_1",
                "x": 1,
                "y": 1,
                "knowledge": "visible",
                "last_seen_turn": 18,
                "area_id": "AREA_0",
                "terrain_id": "TERRAIN_GRASS",
                "water": False,
                "hills": False,
                "peak": False,
                "fresh_water": True,
                "river_edges": [{"dx": -1, "dy": 0}],
                "revealed_owner_id": "PLAYER_0",
                "feature_id": None,
                "improvement_id": None,
                "route_id": None,
                "resource_id": None,
                "yields": {"food": 0, "production": 0, "commerce": 0},
                "defense_percent": 0,
                "city_id": None,
                "worked_by_city_id": None,
                "visible_stack_ids": [],
            }
        ]
        snapshot["known_map"]["visibility_grid"] = ["...", "...", "..."]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.png"
            meta = render_civ6_map_png(snapshot, path)
            self.assertGreater(meta.get("river_edges_drawn", 0), 0)
            self.assertEqual("odd-r-flat-top", meta.get("hex_layout"))

    def test_render_with_fresh_water_viewport(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        snapshot["known_map"]["plots"] = [
            {
                "plot_id": "PLOT_15_23",
                "x": 15,
                "y": 23,
                "knowledge": "visible",
                "last_seen_turn": 18,
                "area_id": "AREA_0",
                "terrain_id": "TERRAIN_GRASS",
                "water": False,
                "hills": False,
                "peak": False,
                "fresh_water": True,
                "river_edges": ["N"],
                "revealed_owner_id": "PLAYER_0",
                "feature_id": None,
                "improvement_id": None,
                "route_id": None,
                "resource_id": None,
                "yields": {"food": 0, "production": 0, "commerce": 0},
                "defense_percent": 0,
                "city_id": None,
                "worked_by_city_id": None,
                "visible_stack_ids": [],
            }
        ]
        snapshot["known_map"]["viewport"] = {"x0": 14, "y0": 22, "width": 3, "height": 3}
        snapshot["known_map"]["visibility_grid"] = ["...", "...", "..."]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.png"
            meta = render_civ6_map_png(snapshot, path)
            self.assertGreater(meta["image_bytes"], 500)
            self.assertEqual("odd-r-flat-top", meta.get("hex_layout"))
            self.assertGreaterEqual(meta.get("rendered_tiles", 0), 1)

    def test_viewport_terrain_legend_from_detected_types(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        snapshot["known_map"]["viewport"] = {"x0": 0, "y0": 0, "width": 4, "height": 3}
        snapshot["known_map"]["visibility_grid"] = ["o~..", ".#^.", "..#."]
        snapshot["known_map"]["plots"] = [
            {
                "plot_id": "PLOT_2_1",
                "x": 2,
                "y": 1,
                "knowledge": "visible",
                "terrain_id": "TERRAIN_TUNDRA",
                "water": False,
                "hills": False,
                "peak": True,
            },
            {
                "plot_id": "PLOT_3_2",
                "x": 3,
                "y": 2,
                "knowledge": "visible",
                "terrain_id": "TERRAIN_PLAINS",
                "water": False,
                "hills": True,
                "peak": False,
            },
        ]
        plot_index = map_render.build_render_plot_index(snapshot)
        viewport = map_render.resolve_render_viewport(snapshot, plot_index)
        normalized = map_render._normalize_visibility_grid(
            snapshot["known_map"]["visibility_grid"],
            snapshot["game"]["map_width"],
            snapshot["game"]["map_height"],
        )
        legend = map_render.collect_civ6_viewport_terrain_legend(
            plot_index,
            viewport,
            normalized,
            snapshot["known_map"],
            normalized is not None,
        )
        labels = [label for label, _ in legend]
        self.assertIn("Ocean", labels)
        self.assertIn("Coast", labels)
        self.assertTrue(any("Tundra" in label for label in labels))
        self.assertTrue(any("Plains" in label and "Hills" in label for label in labels))

    def test_cropped_visibility_grid_uses_viewport_origin(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        snapshot["game"]["map_width"] = 80
        snapshot["game"]["map_height"] = 50
        snapshot["known_map"]["viewport"] = {"x0": 45, "y0": 4, "width": 4, "height": 3}
        snapshot["known_map"]["visibility_grid"] = ["..~.", ".#..", "...."]
        snapshot["known_map"]["plots"] = [{
            "plot_id": "PLOT_57_16",
            "x": 57,
            "y": 16,
            "knowledge": "visible",
            "terrain_id": "TERRAIN_PLAINS",
            "water": False,
        }]
        index = map_render.build_render_plot_index(snapshot)
        self.assertIn((47, 4), index)
        self.assertNotIn((2, 0), index)

    def test_model_renderer_hex_layout(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        plots = []
        for y in range(6):
            for x in range(6):
                plots.append({
                    "plot_id": f"PLOT_{x}_{y}",
                    "x": x,
                    "y": y,
                    "knowledge": "visible",
                    "last_seen_turn": 18,
                    "area_id": "AREA_0",
                    "terrain_id": "TERRAIN_GRASS",
                    "water": False,
                    "hills": False,
                    "peak": False,
                    "fresh_water": False,
                    "river_edges": [],
                    "revealed_owner_id": "PLAYER_0",
                    "feature_id": None,
                    "improvement_id": None,
                    "route_id": None,
                    "resource_id": None,
                    "yields": {"food": 0, "production": 0, "commerce": 0},
                    "defense_percent": 0,
                    "city_id": None,
                    "worked_by_city_id": None,
                    "visible_stack_ids": [],
                })
        snapshot["known_map"]["plots"] = plots
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.png"
            meta = render_civ6_map_for_model(snapshot, path)
            self.assertEqual("png-hex-flat-top-v2", meta.get("format"))
            self.assertEqual("odd-r-flat-top", meta.get("hex_layout"))
            self.assertGreater(meta.get("image_bytes", 0), 1000)


if __name__ == "__main__":
    unittest.main()
