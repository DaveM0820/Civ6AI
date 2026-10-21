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

    def test_settle_site_overlay_draws_labels_and_skips_illegal_tiles(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        snapshot["your_units"] = [{
            "unit_id": "UNIT_SETTLER_1",
            "unit_type_id": "UNIT_SETTLER",
            "plot_id": "PLOT_15_23",
            "settle": {
                "here_ok": False,
                "sites": [
                    {"x": 16, "y": 23, "dist": 1, "coastal": True, "fresh_water": True},
                    {"x": 17, "y": 23, "dist": 2, "coastal": False, "fresh_water": False},
                    {"x": 18, "y": 23, "dist": 1, "coastal": False, "fresh_water": False},
                ],
            },
        }]
        snapshot["your_cities"] = []
        snapshot["known_other_cities"] = []
        snapshot["known_map"]["viewport"] = {"x0": 14, "y0": 21, "width": 6, "height": 5}
        snapshot["known_map"]["visibility_grid"] = ["......"] * 5
        snapshot["known_map"]["plots"] = [
            {"plot_id": f"PLOT_{x}_{y}", "x": x, "y": y, "knowledge": "visible",
             "terrain_id": "TERRAIN_GRASS" if not (x == 18 and y == 23) else "TERRAIN_COAST",
             "water": x == 18 and y == 23, "peak": False}
            for y in range(21, 26) for x in range(14, 20)
        ]
        from sidecar.map_render_civ6 import _BASE_LAYER_CACHE, collect_settle_markers, render_civ6_map_png
        _BASE_LAYER_CACHE.clear()
        markers = collect_settle_markers(snapshot)
        labels = {row["label"] for row in markers}
        coords = {(row["x"], row["y"]) for row in markers}
        self.assertIn("S1", labels)
        self.assertIn((16, 23), coords)
        self.assertNotIn((18, 23), coords)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settle.png"
            meta = render_civ6_map_png(snapshot, path)
            self.assertGreaterEqual(meta.get("settle_rings_drawn", 0), 1)
            self.assertIn("S1", meta.get("settle_labels") or [])
            from PIL import Image
            img = Image.open(path)
            pixels = list(img.getdata())
            yellow = sum(1 for px in pixels if px[0] > 200 and 140 < px[1] < 230 and px[2] < 120)
            self.assertGreater(yellow, 20)
            overview = render_civ6_map_png(snapshot, Path(tmp) / "overview.png", image_role="overview")
            self.assertEqual(0, overview.get("settle_rings_drawn", 0))
            self.assertEqual([], overview.get("settle_labels") or [])

    def test_settle_overlay_skipped_when_vision_off(self):
        from unittest import mock
        from sidecar.map_render_civ6 import collect_settle_markers
        snap = {
            "your_units": [{
                "unit_id": "UNIT_SETTLER_1", "unit_type_id": "UNIT_SETTLER",
                "settle": {"sites": [{"x": 4, "y": 4, "dist": 1, "coastal": True}]},
            }],
            "your_cities": [],
            "known_other_cities": [],
        }
        with mock.patch("sidecar.map_render_civ6.vision_maps_enabled", return_value=False):
            self.assertEqual([], collect_settle_markers(snap))

    def test_base_layer_cache_second_render_is_faster(self):
        import time
        from sidecar.map_render_civ6 import _BASE_LAYER_CACHE, _HEX_LAYER_CACHE, render_civ6_map_png

        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        snapshot["known_map"]["viewport"] = {"x0": 10, "y0": 18, "width": 16, "height": 14}
        snapshot["known_map"]["visibility_grid"] = ["." * 16] * 14
        snapshot["known_map"]["plots"] = [
            {"plot_id": f"PLOT_{x}_{y}", "x": x, "y": y, "knowledge": "visible",
             "terrain_id": "TERRAIN_GRASS", "terrain": "TERRAIN_GRASS", "water": False, "peak": False}
            for y in range(18, 32) for x in range(10, 26)
        ]
        _BASE_LAYER_CACHE.clear()
        _HEX_LAYER_CACHE.clear()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.png"
            t0 = time.perf_counter()
            render_civ6_map_png(snapshot, path)
            first = time.perf_counter() - t0
            t1 = time.perf_counter()
            render_civ6_map_png(snapshot, path)
            second = time.perf_counter() - t1
        self.assertGreater(first, 0)
        self.assertLess(second, first)
        print(f"map_render first={first:.4f}s second={second:.4f}s")

    def test_owned_improvements_and_districts_are_marked(self):
        import time

        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        snapshot["game"]["map_width"] = 4
        snapshot["game"]["map_height"] = 3

        def plot(x: int, y: int, **extra: object) -> dict:
            row = {
                "plot_id": f"PLOT_{x}_{y}",
                "x": x,
                "y": y,
                "knowledge": "visible",
                "terrain_id": "TERRAIN_GRASS",
                "water": False,
                "hills": False,
                "peak": False,
                "revealed_owner_id": "PLAYER_0",
                "improvement_id": None,
                "district_id": None,
                "resource_id": None,
                "city_id": None,
            }
            row.update(extra)
            return row

        snapshot["known_map"]["plots"] = [
            plot(0, 0, improvement_id="IMPROVEMENT_FARM"),
            plot(1, 0, district_id="DISTRICT_CAMPUS"),
            plot(2, 0),
            plot(3, 0, improvement_id="IMPROVEMENT_MINE", revealed_owner_id=None),
            plot(0, 1, improvement_id="IMPROVEMENT_GOODY_HUT", revealed_owner_id=None),
            plot(1, 1, improvement_id="IMPROVEMENT_FARM", improvement_pillaged=True),
        ]
        snapshot["known_map"]["visibility_grid"] = ["....", "....", "...."]
        snapshot["known_map"]["viewport"] = {"x0": 0, "y0": 0, "width": 4, "height": 3}
        started = time.perf_counter()
        meta = render_civ6_map_png(snapshot, None)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(2, meta["improvements_drawn"])
        self.assertEqual(1, meta["districts_drawn"])
        legend = " ".join(meta["tile_mark_legend"])
        self.assertIn("farm", legend)
        self.assertIn("pillaged", legend)
        self.assertIn("campus", legend)
        self.assertNotIn("mine", legend)
        bare = civ6_adapter.load_golden_snapshot(GOLDEN)
        bare["game"]["map_width"] = 4
        bare["game"]["map_height"] = 3
        bare["known_map"]["plots"] = [plot(x, y) for y in range(3) for x in range(4)]
        bare["known_map"]["visibility_grid"] = ["....", "....", "...."]
        bare["known_map"]["viewport"] = {"x0": 0, "y0": 0, "width": 4, "height": 3}
        blank = render_civ6_map_png(bare, None)
        self.assertNotEqual(meta["sha256"], blank["sha256"])
        self.assertEqual(0, blank["improvements_drawn"])
        self.assertEqual(0, blank["districts_drawn"])

    def test_sprite_territory_tint_is_a_light_wash(self):
        from PIL import Image

        from sidecar.map_render_civ6 import _paste_strategic_hex, _paste_territory_tint, _territory_tint_alpha

        canvas = Image.new("RGBA", (96, 96), (18, 18, 24, 255))
        plot = {
            "terrain_id": "TERRAIN_DESERT",
            "knowledge": "visible",
            "water": False,
            "hills": False,
            "peak": False,
        }
        self.assertTrue(_paste_strategic_hex(canvas, plot, 48, 48, 28))
        before = canvas.getpixel((48, 48))
        color = map_render._player_color("PLAYER_1")
        alpha = _territory_tint_alpha(plot)
        self.assertLess(alpha, 0.3)
        _paste_territory_tint(canvas, 48, 48, 28, color, alpha)
        after = canvas.getpixel((48, 48))
        self.assertEqual(255, after[3])
        player = map_render._hex_to_rgb(color)
        for index, channel in enumerate(player):
            expected = (channel - before[index]) * alpha
            self.assertAlmostEqual(after[index] - before[index], expected, delta=8)
        moved = sum((after[i] - before[i]) ** 2 for i in range(3))
        remaining = sum((after[i] - player[i]) ** 2 for i in range(3))
        self.assertLess(moved, remaining)
        remembered = dict(plot, knowledge="remembered")
        self.assertAlmostEqual(_territory_tint_alpha(remembered), alpha * 0.6, places=3)

    def test_hex_grid_outline_stays_thin_and_translucent(self):
        from PIL import Image, ImageDraw

        from sidecar.map_render_civ6 import HEX_GRID_OUTLINE, _flat_top_hex_corners

        base = (210, 180, 110, 255)
        canvas = Image.new("RGBA", (96, 96), base)
        overlay = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        ImageDraw.Draw(overlay).polygon(_flat_top_hex_corners(48, 48, 30), outline=HEX_GRID_OUTLINE)
        merged = Image.alpha_composite(canvas, overlay)
        self.assertEqual(base, merged.getpixel((48, 48)))
        changed = [
            merged.getpixel((x, y))
            for y in range(96)
            for x in range(96)
            if merged.getpixel((x, y)) != base
        ]
        self.assertGreater(len(changed), 20)
        self.assertLess(len(changed), 400)
        for pixel in changed:
            self.assertGreater(pixel[0], 140)
            self.assertNotEqual(pixel[:3], (0x33, 0x33, 0x33))
        self.assertLess(HEX_GRID_OUTLINE[3], 96)

    def test_overview_and_tactical_renders_stay_under_one_second(self):
        import json
        import time

        from sidecar.map_render_civ6 import _BASE_LAYER_CACHE, render_civ6_map_png
        from sidecar.map_situational import compute_overview_viewport, pick_auto_focus_tile, viewport_focused_on_tile

        snapshot = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t4-city-snapshot.json").read_text())
        overview_vp = compute_overview_viewport(snapshot)
        focus = pick_auto_focus_tile({}, snapshot)
        width = int(snapshot["game"]["map_width"])
        height = int(snapshot["game"]["map_height"])
        tactical_vp = viewport_focused_on_tile(focus[0], focus[1], width, height)
        _BASE_LAYER_CACHE.clear()
        with tempfile.TemporaryDirectory() as tmp:
            render_civ6_map_png(
                snapshot, Path(tmp) / "warm-overview.png", viewport=overview_vp, image_role="overview", target_size=768,
            )
            render_civ6_map_png(
                snapshot, Path(tmp) / "warm-tactical.png", viewport=tactical_vp, image_role="viewport", target_size=1024,
            )
            started = time.perf_counter()
            render_civ6_map_png(
                snapshot, Path(tmp) / "overview.png", viewport=overview_vp, image_role="overview", target_size=768,
            )
            overview_s = time.perf_counter() - started
            started = time.perf_counter()
            render_civ6_map_png(
                snapshot, Path(tmp) / "tactical.png", viewport=tactical_vp, image_role="viewport", target_size=1024,
            )
            tactical_s = time.perf_counter() - started
        self.assertLess(overview_s, 1.0)
        self.assertLess(tactical_s, 1.0)
        print(f"overview={overview_s:.4f}s tactical={tactical_s:.4f}s")

    def test_city_nameplate_paints_over_rivers(self):
        import json

        from PIL import Image

        from sidecar.map_render_civ6 import _BASE_LAYER_CACHE, render_civ6_map_png
        from sidecar.map_situational import pick_auto_focus_tile, viewport_focused_on_tile

        snapshot = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t4-city-snapshot.json").read_text())
        snapshot.setdefault("civ6", {}).setdefault("map", {})["river_edge_format"] = "across-v2"
        focus = pick_auto_focus_tile({}, snapshot)
        width = int(snapshot["game"]["map_width"])
        height = int(snapshot["game"]["map_height"])
        tactical = viewport_focused_on_tile(focus[0], focus[1], width, height)
        saved: dict[str, Image.Image] = {}
        original = map_render.encode_model_image_bytes

        def _capture(image, *, target_size=None):
            saved["canvas"] = image.copy()
            return original(image, target_size=target_size)

        map_render.encode_model_image_bytes = _capture
        try:
            _BASE_LAYER_CACHE.clear()
            meta = render_civ6_map_png(
                snapshot, None, viewport=tactical, image_role="viewport", target_size=1024,
            )
        finally:
            map_render.encode_model_image_bytes = original
        self.assertGreater(meta.get("river_edges_drawn", 0), 0)
        image = saved["canvas"].convert("RGB")
        player_id = str(snapshot["decision"]["player_id"])
        plate = map_render._hex_to_rgb(map_render._player_color(player_id))
        river = map_render._hex_to_rgb("#4ec8f0")
        width, height = image.size
        river_pixels = 0
        name_runs: list[tuple[int, int, int]] = []
        for y in range(height):
            run = 0
            start = 0
            for x in range(width + 1):
                pixel = image.getpixel((x, y)) if x < width else None
                if pixel == river:
                    river_pixels += 1
                if pixel == plate:
                    if run == 0:
                        start = x
                    run += 1
                else:
                    if run > 40:
                        name_runs.append((y, start, start + run - 1))
                    run = 0
        self.assertGreater(river_pixels, 30)
        self.assertGreater(len(name_runs), 2)
        covered = 0
        for y, start, end in name_runs:
            for x in range(start, end + 1):
                if image.getpixel((x, y)) == river:
                    covered += 1
        self.assertEqual(0, covered)


if __name__ == "__main__":
    unittest.main()
