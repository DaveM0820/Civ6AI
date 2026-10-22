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
        self.assertGreaterEqual(alpha, 0.4)
        self.assertLess(alpha, 0.5)
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
        self.assertGreater(sum(abs(after[i] - before[i]) for i in range(3)), 60)
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
                snapshot, Path(tmp) / "warm-overview.png", viewport=overview_vp, image_role="overview", target_size=1536,
            )
            render_civ6_map_png(
                snapshot, Path(tmp) / "warm-tactical.png", viewport=tactical_vp, image_role="viewport", target_size=2048,
            )
            started = time.perf_counter()
            render_civ6_map_png(
                snapshot, Path(tmp) / "overview.png", viewport=overview_vp, image_role="overview", target_size=1536,
            )
            overview_s = time.perf_counter() - started
            started = time.perf_counter()
            render_civ6_map_png(
                snapshot, Path(tmp) / "tactical.png", viewport=tactical_vp, image_role="viewport", target_size=2048,
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

        def _capture(image, *, target_size=None, **kwargs):
            saved["canvas"] = image.copy()
            return original(image, target_size=target_size, **kwargs)

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


    def test_tactical_role_uses_axis_ticks_not_every_hex(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        viewport = {"x0": 0, "y0": 0, "width": 8, "height": 6}
        with tempfile.TemporaryDirectory() as tmp:
            meta = render_civ6_map_png(
                snapshot, Path(tmp) / "tac.png", viewport=viewport, target_size=1024, image_role="viewport",
            )
        self.assertTrue(meta["show_axis_labels"])
        self.assertFalse(meta["show_tile_coords"])

    def test_agent_viewport_survives_the_next_turn(self):
        from sidecar import map_situational

        snapshot = {
            "decision": {"turn": 20, "player_id": "PLAYER_1"},
            "game": {"map_width": 40, "map_height": 30},
            "your_units": [],
            "your_cities": [],
        }
        memory: dict = {}
        map_situational.store_agent_viewport(memory, snapshot, "(22,16)")
        snapshot["decision"]["turn"] = 21
        memory = map_situational.resolve_tactical_viewport(memory, snapshot)
        self.assertEqual(22, memory["map_viewport"]["focus_x"])
        self.assertEqual(16, memory["map_viewport"]["focus_y"])
        self.assertFalse(memory["map_viewport"]["auto"])

    def test_free_city_slot_is_named(self):
        from sidecar import map_render

        label = map_render._player_label(
            {"decision": {"player_id": "PLAYER_0"}, "known_players": []}, "PLAYER_62",
        )
        self.assertEqual("Free Cities", label)

    def test_default_model_images_are_double_and_high_detail(self):
        from unittest.mock import patch

        from sidecar import context_budget
        from sidecar import map_situational

        import os

        self.assertEqual(1536, map_render.CIV5_OVERVIEW_MODEL_IMAGE_SIZE)
        self.assertEqual(2048, map_render.CIV5_TACTICAL_MODEL_IMAGE_SIZE)
        saved = {
            name: os.environ.pop(name, None)
            for name in (
                "CIV5_OVERVIEW_MODEL_IMAGE_SIZE",
                "CIV5AI_OVERVIEW_MODEL_IMAGE_SIZE",
                "CIV5_TACTICAL_MODEL_IMAGE_SIZE",
                "CIV5AI_TACTICAL_MODEL_IMAGE_SIZE",
            )
        }
        try:
            self.assertEqual((1536, 2048, 0), context_budget.default_image_sizes())
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value

        def fake_render(snapshot, path, prefer_civ5_sprites=False, **kwargs):
            from PIL import Image

            Image.new("RGBA", (32, 32), (20, 20, 20, 255)).save(path, format="PNG")
            return {
                "data_url": "data:image/png;base64,AAAA",
                "label": kwargs.get("image_role") or "map",
                "legend": [],
            }

        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "sidecar.map_situational.render_civ6_map_png", fake_render,
        ):
            bundle = map_situational.prepare_civ6_situational_maps(
                snapshot, Path(tmp), attach=True, omit_focus=True,
            )
        by_role = {item["role"]: item for item in bundle["manifest"]}
        self.assertEqual("high", by_role["overview"]["detail"])
        self.assertEqual("high", by_role["viewport"]["detail"])
        self.assertEqual(1536, by_role["overview"]["image_size"])
        self.assertEqual(2048, by_role["viewport"]["image_size"])
        sent = {item["role"]: item["detail"] for item in bundle["data_urls"]}
        self.assertEqual("high", sent["overview"])
        self.assertEqual("high", sent["viewport"])

    def test_larger_target_is_drawn_finer_not_stretched(self):
        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        viewport = {"x0": 0, "y0": 0, "width": 14, "height": 12}
        with tempfile.TemporaryDirectory() as tmp:
            small = render_civ6_map_png(
                snapshot, Path(tmp) / "small.png", viewport=viewport, target_size=1024, image_role="viewport",
            )
            large = render_civ6_map_png(
                snapshot, Path(tmp) / "large.png", viewport=viewport, target_size=2048, image_role="viewport",
            )
            raw = (Path(tmp) / "large.png").read_bytes()
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(large["tile_px"], small["tile_px"])
        small_long = max(small["source_width"], small["source_height"])
        large_long = max(large["source_width"], large["source_height"])
        self.assertGreater(large_long, small_long * 1.5)
        self.assertGreater(large_long, 1600)
        self.assertEqual(2048, large["width"])
        self.assertEqual(2048, large["height"])
        self.assertEqual("image/png", large["mime_type"])


class LoneRevealedCapitalTests(unittest.TestCase):
    """An embassy or a shared capital reveals one tile. Fog around it stays fog."""

    def _snapshot(self) -> dict:
        width = height = 7
        grid = ["?" * width for _ in range(height)]
        row = list(grid[3])
        row[3] = "."
        grid[3] = "".join(row)
        return {
            "decision": {"player_id": "PLAYER_1", "turn": 131},
            "game": {"map_width": width, "map_height": height, "wrap_x": True},
            "personality": {"leader_name": "Test"},
            "your_units": [],
            "your_cities": [],
            "known_other_cities": [{
                "city_id": "CITY_4_1",
                "name": "Kabul",
                "plot_id": "PLOT_3_3",
                "owner_player_id": "PLAYER_4",
                "is_capital": True,
                "population": 9,
                "knowledge": "remembered",
            }],
            "known_map": {
                "viewport": {"x0": 0, "y0": 0, "width": width, "height": height},
                "visibility_grid": grid,
                "plots": [{
                    "plot_id": "PLOT_3_3",
                    "x": 3,
                    "y": 3,
                    "knowledge": "remembered",
                    "terrain_id": "TERRAIN_PLAINS",
                    "water": False,
                    "peak": False,
                    "revealed_owner_id": "PLAYER_4",
                }],
                "explored_percent": 1,
            },
            "legal_commands": [],
        }

    def test_fog_neighbors_stay_black_and_legend_names_embassy(self):
        import io
        from unittest import mock
        from PIL import Image

        from sidecar.map_render_civ6 import (
            LONE_CITY_LEGEND,
            _BASE_LAYER_CACHE,
            _axis_gutter_for_tile,
            _hex_metrics,
            _odd_r_cell_center,
            render_civ6_map_png,
        )

        def keep_source(image, **_kwargs):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue(), "image/png"

        viewport = {"x0": 0, "y0": 0, "width": 7, "height": 7}
        player = map_render._hex_to_rgb(map_render._player_color("PLAYER_4"))

        def distance(pixel, rgb):
            return sum((int(pixel[i]) - rgb[i]) ** 2 for i in range(3))

        for sprites in (False, True):
            with self.subTest(sprites=sprites):
                _BASE_LAYER_CACHE.clear()
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "lone.png"
                    with mock.patch("sidecar.map_render.encode_model_image_bytes", keep_source):
                        meta = render_civ6_map_png(
                            self._snapshot(),
                            path,
                            prefer_civ5_sprites=sprites,
                            viewport=viewport,
                        )
                    self.assertEqual(LONE_CITY_LEGEND, meta.get("legend_note"))
                    image = Image.open(path).convert("RGBA")
                    tile_px = int(meta["tile_px"])
                    gutter = _axis_gutter_for_tile(
                        tile_px, 0, 0, 7, 7,
                        show_axis=bool(meta.get("show_axis_labels")),
                        prefer_civ5_sprites=sprites,
                    )
                    radius = _hex_metrics(tile_px)[0]
                    cx, cy, _, _ = _odd_r_cell_center(
                        3, 3, 0, 0, tile_px, gutter,
                        flip_y=bool(meta.get("north_up")), vh=7,
                    )
                    plains = (176, 160, 112)
                    colored = 0
                    for dx in range(-3, 4):
                        for dy in range(-3, 4):
                            pixel = image.getpixel((int(cx) + dx, int(cy) + dy))
                            if distance(pixel, (0, 0, 0)) > 800:
                                colored += 1
                    self.assertGreater(colored, 4, "the revealed capital tile was not drawn")
                    # Odd row: the six neighbours. Their centres must stay fog.
                    for nx, ny in ((4, 3), (4, 4), (3, 4), (2, 3), (3, 2), (4, 2)):
                        ncx, ncy, _, _ = _odd_r_cell_center(
                            nx, ny, 0, 0, tile_px, gutter,
                            flip_y=bool(meta.get("north_up")), vh=7,
                        )
                        pixel = image.getpixel((int(ncx), int(ncy)))
                        self.assertLess(distance(pixel, (0, 0, 0)), 500, pixel)
                        self.assertLess(distance(pixel, (0, 0, 0)), distance(pixel, player))
                        self.assertLess(distance(pixel, (0, 0, 0)), distance(pixel, plains))
                    del radius

    def test_a_revealed_neighbor_is_not_an_embassy_tile(self):
        from sidecar.map_render_civ6 import isolated_revealed_cities

        snapshot = self._snapshot()
        grid = snapshot["known_map"]["visibility_grid"]
        row = list(grid[3])
        row[4] = "."
        grid[3] = "".join(row)
        snapshot["known_map"]["plots"].append({
            "plot_id": "PLOT_4_3", "x": 4, "y": 3, "knowledge": "visible",
            "terrain_id": "TERRAIN_PLAINS", "water": False,
        })
        from sidecar import pipeline_v2 as pipeline
        pipeline.ensure_known_map_plots(snapshot)
        index = map_render.build_render_plot_index(snapshot)
        known = snapshot["known_map"]
        normalized = map_render._normalize_visibility_grid(known["visibility_grid"], 7, 7)
        self.assertEqual(set(), isolated_revealed_cities(snapshot, index, normalized, known, True))

    def test_column_labels_are_drawn_once_on_the_unshifted_column(self):
        import io
        from unittest import mock
        from PIL import Image

        from sidecar.map_render_civ6 import _BASE_LAYER_CACHE, _axis_gutter_for_tile, render_civ6_map_png

        def keep_source(image, **_kwargs):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue(), "image/png"

        snapshot = civ6_adapter.load_golden_snapshot(GOLDEN)
        viewport = {"x0": 0, "y0": 0, "width": 6, "height": 4}
        _BASE_LAYER_CACHE.clear()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "axis.png"
            with mock.patch("sidecar.map_render.encode_model_image_bytes", keep_source):
                meta = render_civ6_map_png(
                    snapshot, path, viewport=viewport, target_size=256, image_role="viewport",
                )
            image = Image.open(path).convert("RGB")
        self.assertTrue(meta["show_axis_labels"])
        tile_px = int(meta["tile_px"])
        gutter = _axis_gutter_for_tile(
            tile_px, 0, 0, 6, 4, show_axis=True, prefer_civ5_sprites=False,
        )
        from sidecar.map_render_civ6 import _odd_r_cell_center

        # Bitmap text is antialiased, so the ink is near #9a9a9a rather than that exact gray.
        xs: list[int] = []
        for y in range(gutter):
            for x in range(image.width):
                pixel = image.getpixel((x, y))
                if min(pixel) >= 100:
                    xs.append(x)
        xs.sort()
        groups: list[list[int]] = []
        gap = max(4, tile_px // 3)
        for x in xs:
            if not groups or x - groups[-1][-1] > gap:
                groups.append([x])
            else:
                groups[-1].append(x)
        self.assertEqual(6, len(groups))
        for column, group in enumerate(groups):
            mid = (group[0] + group[-1]) / 2
            even, _, _, _ = _odd_r_cell_center(column, 0, 0, 0, tile_px, gutter, flip_y=False, vh=4)
            odd, _, _, _ = _odd_r_cell_center(column, 1, 0, 0, tile_px, gutter, flip_y=False, vh=4)
            self.assertLess(abs(mid - even), abs(mid - odd))


class PeakGlyphTests(unittest.TestCase):
    def test_peak_glyph_is_visible_on_a_pale_tile(self):
        from PIL import Image, ImageDraw

        from sidecar.map_render_civ6 import _draw_peak_glyph

        image = Image.new("RGB", (48, 48), (244, 244, 244))
        _draw_peak_glyph(ImageDraw.Draw(image), 24, 24, 18)
        dark = 0
        for x in range(8, 40):
            for y in range(8, 40):
                pixel = image.getpixel((x, y))
                if pixel[0] < 80 and pixel[1] < 80 and pixel[2] < 80:
                    dark += 1
        self.assertGreater(dark, 8, "mountain peak has no dark ridge on a pale tile")


if __name__ == "__main__":
    unittest.main()
