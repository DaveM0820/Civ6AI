"""Offline minimap SVG preview from io_log snapshots or fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import map_render, pipeline_v2 as pipeline


def load_snapshot(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw.get("snapshot"), dict):
        return raw["snapshot"]
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Render cropped minimap SVG from snapshot JSON")
    parser.add_argument("--input", type=Path, help="io_log input.json or snapshot JSON")
    parser.add_argument("--fixture", type=Path, help="Fixture under fixtures/map_snapshots/")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "map-preview")
    parser.add_argument("--compare-old", action="store_true", help="Also render legacy full-map PNG")
    parser.add_argument("--tile-px", type=int, default=None, help="Pixels per tile (default: CIV4AI_MAP_TILE_PX or 24)")
    args = parser.parse_args()
    source = args.input or args.fixture
    if source is None:
        parser.error("Provide --input or --fixture")
    snapshot = load_snapshot(source)
    image = snapshot.setdefault("known_map", {}).setdefault("image", {})
    if isinstance(image, dict):
        image["attached"] = True
    stem = source.stem.replace("_input", "")
    args.out.mkdir(parents=True, exist_ok=True)
    svg_path = args.out / f"{stem}.map.svg"
    tile_px = args.tile_px if args.tile_px is not None else map_render.resolve_map_tile_px()
    meta = map_render.render_known_map_svg(snapshot, svg_path, tile_px=tile_px)
    print(f"svg={svg_path}")
    print(f"sha256={meta['sha256']}")
    print(f"viewport={meta['viewport']}")
    print(f"size={meta['width']}x{meta['height']} tile_px={meta['tile_px']}")
    print(f"rendered_tiles={meta['rendered_tiles']} known_plot_tiles={meta['known_plot_tiles']}")
    print(f"bytes={meta['svg_bytes']}")
    if args.compare_old:
        png_path = args.out / f"{stem}.legacy.png"
        legacy = pipeline.render_known_map_png(snapshot, png_path)
        print(f"legacy_png={png_path} size={legacy['width']}x{legacy['height']} bytes={legacy['png_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
