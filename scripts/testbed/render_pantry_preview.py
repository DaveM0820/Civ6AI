"""Render pantry-test preview map with varied terrain and a single capital city."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import civ6_adapter, pipeline_v2 as pipeline
from sidecar.map_render_civ6 import render_civ6_map_png

GOLDEN = ROOT / "fixtures" / "civ6" / "snapshot-turn-classical-golden.json"
OUT = ROOT / "artifacts" / "map-preview" / "pantry-test" / "pantry-zoom.png"

# Civ6 visibility_grid chars: . flat, # hills, ^ mountain, ~ coast, o ocean
DEMO_GRID = [
    "o~~~~~~~~~~~",
    "oo#...^.....",
    "~#...#......",
    ".#..~~......",
    "...~~.......",
    "....#.......",
    ".....#......",
    "......#.....",
    ".......#....",
    "........#...",
]


def main() -> int:
    snap = civ6_adapter.load_golden_snapshot(GOLDEN)
    snap["known_map"]["viewport"] = {"x0": 12, "y0": 16, "width": 12, "height": 10}
    snap["known_map"]["visibility_grid"] = DEMO_GRID
    snap["known_map"]["plots"] = []
    snap["your_cities"] = [c for c in snap["your_cities"] if c.get("is_capital")]
    snap["your_units"] = [
        u for u in snap["your_units"]
        if u.get("plot_id") in {"PLOT_14_22", "PLOT_15_23"}
    ]
    pipeline.ensure_known_map_plots(snap)
    resource_tiles = {
        (14, 22): "RESOURCE_HORSES",
        (16, 23): "RESOURCE_WHEAT",
        (13, 24): "RESOURCE_DEER",
    }
    for plot in snap["known_map"]["plots"]:
        x, y = plot.get("x"), plot.get("y")
        if x is None or y is None:
            continue
        key = (x, y)
        if key in resource_tiles:
            plot["resource_id"] = resource_tiles[key]
        if x == 14 and y in (20, 21, 22):
            plot["river_edges"] = [{"dx": 1, "dy": 0}]
        if x == 15 and y in (21, 22):
            plot["river_edges"] = [{"dx": 0, "dy": 1}]
        if x == 12 and y == 17:
            plot["terrain_id"] = "TERRAIN_TUNDRA"
        if x == 13 and y == 18:
            plot["terrain_id"] = "TERRAIN_PLAINS"
        if x == 14 and y == 21 and not plot.get("hills"):
            plot["feature_id"] = "FEATURE_FOREST"
    meta = render_civ6_map_png(snap, OUT)
    print(f"wrote {OUT} viewport={meta['viewport']} tile_px={meta['tile_px']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
