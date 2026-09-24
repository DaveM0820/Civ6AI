"""Civ VI minimap renderer — flat-top odd-r hex layout with edge rivers."""
from __future__ import annotations

import base64
import hashlib
import math
from pathlib import Path
from typing import Any

from sidecar import civ6_assets
from sidecar import map_icons
from sidecar import map_render
from sidecar import pipeline_v2 as pipeline

RIVER_STROKE = "#4ec8f0"
RIVER_CORE = "#dff6ff"
RIVER_LABEL = "river edge"
SETTLE_LOOK_COLOR = "#f4c040"
SETTLE_HERE_COLOR = "#f7f3e8"
SETTLE_LOOK_LABEL = "better settle tile"
SETTLE_HERE_LABEL = "settler tile"
UNEXPLORED = map_render.UNEXPLORED_FILL
# Tight Civ5 view is about 8x12. Twice that many cells uses axis labels only.
HEX_AXIS_ONLY_MIN_CELLS = 8 * 12 * 2
# Screen Y grows down. Flat-top corners use angle π/6 + i·π/3, so:
#   edge 5 = east, edge 0 = southeast, edge 1 = southwest.
# Civ5MapImage uses 5/4/3 because it InvertY's the canvas first.
CIV5_RIVER_EDGE_INDEX: dict[str, int] = {"E": 5, "SE": 0, "SW": 1}
def _hex_neighbors_odd_r(x: int, y: int) -> list[tuple[int, int, int]]:
    """Return neighbor grid coords and edge index (0..5) for flat-top hex."""
    if y & 1:
        deltas = [(1, 0, 0), (1, 1, 1), (0, 1, 2), (-1, 0, 3), (0, -1, 4), (1, -1, 5)]
    else:
        deltas = [(1, 0, 0), (0, 1, 1), (-1, 1, 2), (-1, 0, 3), (-1, -1, 4), (0, -1, 5)]
    return [(x + dx, y + dy, edge) for dx, dy, edge in deltas]


def _hex_metrics(tile_px: int) -> tuple[float, float, float]:
    """Flat-top hex: radius, horizontal center pitch, vertical center pitch."""
    radius = max(4, tile_px // 2 - 1)
    horiz = math.sqrt(3) * radius
    vert = 1.5 * radius
    return radius, horiz, vert


def _flat_top_hex_corners(cx: float, cy: float, radius: float) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for i in range(6):
        angle = math.pi / 6 + i * math.pi / 3
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def _odd_r_cell_center(
    wx: int,
    wy: int,
    x0: int,
    y0: int,
    tile_px: int,
    gutter: int,
    flip_y: bool = False,
    vh: int = 1,
) -> tuple[float, float, int, int]:
    radius, horiz, vert = _hex_metrics(tile_px)
    lx = wx - x0
    ly = wy - y0
    if flip_y:
        ly = (y0 + vh - 1) - wy
    px = horiz * lx + (horiz / 2 if (wy & 1) else 0)
    py = vert * ly
    cx = gutter + px + horiz / 2
    cy = gutter + py + radius
    return cx, cy, lx, ly


def _odd_r_map_size(vw: int, vh: int, tile_px: int, gutter: int) -> tuple[int, int]:
    radius, horiz, vert = _hex_metrics(tile_px)
    map_w = int(horiz * vw + horiz / 2)
    map_h = int((vh - 1) * vert + 2 * radius)
    return gutter + map_w, gutter + map_h


def _hex_edge_segment(
    corners: list[tuple[float, float]],
    edge: int,
    inset: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    a = corners[edge]
    b = corners[(edge + 1) % 6]
    ax, ay = a
    bx, by = b
    mx, my = (ax + bx) / 2, (ay + by) / 2
    ax = ax + (mx - ax) * inset
    ay = ay + (my - ay) * inset
    bx = bx + (mx - bx) * inset
    by = by + (my - by) * inset
    return (ax, ay), (bx, by)


def _edge_index_for_neighbor(wx: int, wy: int, dx: int, dy: int) -> int | None:
    for nx, ny, edge in _hex_neighbors_odd_r(wx, wy):
        if nx - wx == dx and ny - wy == dy:
            return edge
    return None


def _edge_index_toward_neighbor(
    cx: float,
    cy: float,
    ncx: float,
    ncy: float,
    corners: list[tuple[float, float]],
) -> int:
    """Pick the hex edge that faces a neighbor center (Civ5 north-up safe)."""
    target = math.atan2(ncy - cy, ncx - cx)
    best_edge = 0
    best_delta = 1e9
    for edge in range(6):
        ax, ay = corners[edge]
        bx, by = corners[(edge + 1) % 6]
        mid_angle = math.atan2((ay + by) / 2 - cy, (ax + bx) / 2 - cx)
        delta = target - mid_angle
        while delta > math.pi:
            delta -= 2 * math.pi
        while delta < -math.pi:
            delta += 2 * math.pi
        abs_delta = abs(delta)
        if abs_delta < best_delta:
            best_delta = abs_delta
            best_edge = edge
    return best_edge


def _civ5_river_edge_from_delta(wx: int, wy: int, dx: int, dy: int) -> int | None:
    """Map Lua neighbor deltas onto Civ5's three stored river edges.

    Snapshot Lua looks up the neighbor *opposite* the river:
    IsWOfRiver + WEST → east edge, IsNWOfRiver + NW → SE, IsNEOfRiver + NE → SW.
    Odd-r, y increases north, odd rows shifted east.
    """
    del wx
    if (dx, dy) == (-1, 0):
        return CIV5_RIVER_EDGE_INDEX["E"]
    if wy & 1:
        mapping = {
            (0, 1): CIV5_RIVER_EDGE_INDEX["SE"],
            (1, 1): CIV5_RIVER_EDGE_INDEX["SW"],
        }
    else:
        mapping = {
            (-1, 1): CIV5_RIVER_EDGE_INDEX["SE"],
            (0, 1): CIV5_RIVER_EDGE_INDEX["SW"],
        }
    return mapping.get((dx, dy))


def _river_edge_for_item(
    item: dict[str, Any],
    wx: int,
    wy: int,
    cx: float,
    cy: float,
    corners: list[tuple[float, float]],
    x0: int,
    y0: int,
    tile_px: int,
    axis_gutter: int,
    flip_y: bool,
    vh: int,
    prefer_civ5: bool,
) -> int | None:
    edge_id = item.get("edge_id")
    if prefer_civ5 and isinstance(edge_id, str):
        edge = CIV5_RIVER_EDGE_INDEX.get(edge_id.strip().upper())
        if edge is not None:
            return edge
    dx = item.get("dx")
    dy = item.get("dy")
    if dx is None or dy is None:
        return None
    dx_i, dy_i = int(dx), int(dy)
    if prefer_civ5:
        return _civ5_river_edge_from_delta(wx, wy, dx_i, dy_i)
    if flip_y:
        nx, ny = wx + dx_i, wy + dy_i
        ncx, ncy, _, _ = _odd_r_cell_center(
            nx, ny, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh,
        )
        return _edge_index_toward_neighbor(cx, cy, ncx, ncy, corners)
    return _edge_index_for_neighbor(wx, wy, dx_i, dy_i)


def _iter_river_neighbor_deltas(
    plot: dict[str, Any] | None,
    wy: int,
) -> list[tuple[int, int, int | None]]:
    """Return (dx, dy, legacy_edge). legacy_edge is set for Civ6 string labels."""
    if plot is None:
        return []
    raw = plot.get("river_edges")
    if not isinstance(raw, list):
        return []
    deltas: list[tuple[int, int, int | None]] = []
    for item in raw:
        if isinstance(item, dict):
            dx = item.get("dx")
            dy = item.get("dy")
            if dx is not None and dy is not None:
                deltas.append((int(dx), int(dy), None))
        elif isinstance(item, str):
            legacy = _legacy_river_edge(item, wy)
            if legacy is not None:
                deltas.append((0, 0, legacy))
    return deltas


def _snap_point(point: tuple[float, float]) -> tuple[int, int]:
    return (int(round(point[0])), int(round(point[1])))


def _collect_river_segments(
    plot_index: dict[tuple[int, int], dict[str, Any]],
    normalized: list[list[str]],
    known_map: dict[str, Any],
    has_visibility_grid: bool,
    viewport: dict[str, int],
    x0: int,
    y0: int,
    tile_px: int,
    axis_gutter: int,
    flip_y: bool,
    vh: int,
    hex_radius: float,
    prefer_civ5: bool,
) -> tuple[list[tuple[tuple[int, int], tuple[int, int]]], int]:
    """Unique river edges as snapped screen segments."""
    vw = viewport["width"]
    seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    segments: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for vy in range(vh):
        wy = y0 + vy
        for vx in range(vw):
            wx = x0 + vx
            plot = plot_index.get((wx, wy))
            grid_char = map_render._grid_char_at(
                normalized, wx, wy, origin=map_render.visibility_grid_origin(known_map),
            )
            state = map_render._tile_terrain_state(plot, grid_char, has_visibility_grid)
            if state != "revealed" or plot is None:
                continue
            cx, cy, _, _ = _odd_r_cell_center(
                wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh,
            )
            corners = _flat_top_hex_corners(cx, cy, hex_radius)
            raw = plot.get("river_edges")
            if not isinstance(raw, list):
                continue
            for item in raw:
                edge: int | None = None
                if isinstance(item, str):
                    edge = _legacy_river_edge(item, wy)
                elif isinstance(item, dict):
                    edge = _river_edge_for_item(
                        item, wx, wy, cx, cy, corners,
                        x0, y0, tile_px, axis_gutter, flip_y, vh, prefer_civ5,
                    )
                if edge is None:
                    continue
                a, b = _hex_edge_segment(corners, edge, 0.0)
                sa, sb = _snap_point(a), _snap_point(b)
                key = (sa, sb) if sa <= sb else (sb, sa)
                if key in seen:
                    continue
                seen.add(key)
                segments.append(key)
    return segments, len(segments)


def _river_polylines(
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
) -> list[list[tuple[int, int]]]:
    """Join shared vertices into continuous paths."""
    adj: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for a, b in segments:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    remaining: set[tuple[tuple[int, int], tuple[int, int]]] = set(segments)
    paths: list[list[tuple[int, int]]] = []

    def _take(start: tuple[int, int], nxt: tuple[int, int]) -> list[tuple[int, int]]:
        path = [start, nxt]
        remaining.discard((start, nxt) if start <= nxt else (nxt, start))
        prev, cur = start, nxt
        while True:
            options = [
                n for n in adj.get(cur, [])
                if n != prev and ((cur, n) if cur <= n else (n, cur)) in remaining
            ]
            if len(options) != 1:
                break
            nxt = options[0]
            remaining.discard((cur, nxt) if cur <= nxt else (nxt, cur))
            path.append(nxt)
            prev, cur = cur, nxt
        return path

    endpoints = [v for v, nbrs in adj.items() if len(nbrs) == 1]
    for start in endpoints:
        for nxt in list(adj.get(start, [])):
            key = (start, nxt) if start <= nxt else (nxt, start)
            if key in remaining:
                paths.append(_take(start, nxt))
    while remaining:
        a, b = next(iter(remaining))
        paths.append(_take(a, b))
    return paths


def _legacy_river_edge(label: str, wy: int) -> int | None:
    if label in ("N", "NE"):
        return 1 if (wy & 1) else 0
    if label == "W":
        return 3
    if label in ("NW", "SW"):
        return 5 if (wy & 1) else 4
    return None


def _weld_segments(
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
    radius: int,
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Merge endpoints that sit on the same hex vertex but rounded apart."""
    if not segments:
        return []
    points: list[tuple[int, int]] = []
    for a, b in segments:
        points.append(a)
        points.append(b)
    parent = list(range(len(points)))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    thresh = max(2, radius)
    thresh_sq = thresh * thresh
    for i, (x1, y1) in enumerate(points):
        for j in range(i + 1, len(points)):
            x2, y2 = points[j]
            dx = x1 - x2
            dy = y1 - y2
            if dx * dx + dy * dy <= thresh_sq:
                a, b = _find(i), _find(j)
                if a != b:
                    parent[b] = a
    sums: dict[int, list[int]] = {}
    for i, (x, y) in enumerate(points):
        root = _find(i)
        bucket = sums.setdefault(root, [0, 0, 0])
        bucket[0] += x
        bucket[1] += y
        bucket[2] += 1
    centroid: dict[int, tuple[int, int]] = {}
    for root, (sx, sy, n) in sums.items():
        centroid[root] = (int(round(sx / n)), int(round(sy / n)))
    mapped = [centroid[_find(i)] for i in range(len(points))]
    welded: list[tuple[tuple[int, int], tuple[int, int]]] = []
    seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for i in range(0, len(mapped), 2):
        a, b = mapped[i], mapped[i + 1]
        if a == b:
            continue
        key = (a, b) if a <= b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        welded.append(key)
    return welded


def _draw_river_network(
    draw: Any,
    segments: list[tuple[tuple[int, int], tuple[int, int]]],
    width: int,
) -> None:
    if not segments:
        return
    stroke = map_render._rgb_tuple(RIVER_STROKE)
    width = max(4, width)
    rad = max(3, (width * 2 + 2) // 3)
    weld_r = max(rad, 4)
    welded = _weld_segments(segments, weld_r)
    for path in _river_polylines(welded):
        if len(path) < 2:
            continue
        for i in range(len(path) - 1):
            draw.line([path[i], path[i + 1]], fill=stroke, width=width)
        for x, y in path:
            draw.ellipse((x - rad, y - rad, x + rad, y + rad), fill=stroke)


def _hex_sprite_size(hex_radius: float) -> tuple[int, int]:
    """Flat-top hex bounding box — strategic sprites fill this area."""
    scale = 1.15
    width = max(8, int(math.sqrt(3) * hex_radius * scale))
    height = max(8, int(hex_radius * 2 * scale))
    return width, height


def _dim_rgba_image(image: Any, factor: float) -> Any:
    from PIL import Image

    work = image.convert("RGBA")
    factor = max(0.0, min(1.0, factor))
    pixels = work.load()
    for y in range(work.height):
        for x in range(work.width):
            red, green, blue, alpha = pixels[x, y]
            pixels[x, y] = (
                int(red * factor),
                int(green * factor),
                int(blue * factor),
                alpha,
            )
    return work


def _paste_hex_sprite_layers(
    canvas: Any,
    sprite_paths: list[Path],
    cx: float,
    cy: float,
    hex_radius: float,
    dim_factor: float = 1.0,
) -> bool:
    if not sprite_paths:
        return False
    from PIL import Image, ImageDraw

    width, height = _hex_sprite_size(hex_radius)
    tile = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    tcx, tcy = width / 2, height / 2
    for sprite_path in sprite_paths:
        name = sprite_path.name.lower()
        layer_scale = 0.72 if "mountain" in name else 1.0
        layer_w = max(4, int(width * layer_scale))
        layer_h = max(4, int(height * layer_scale))
        map_render._paste_image_raster_fit(tile, sprite_path, tcx, tcy, layer_w, layer_h)
    if dim_factor < 1.0:
        tile = _dim_rgba_image(tile, dim_factor)
    local_corners: list[tuple[float, float]] = []
    origin_x = cx - width / 2
    origin_y = cy - height / 2
    for px, py in _flat_top_hex_corners(cx, cy, hex_radius):
        local_corners.append((px - origin_x, py - origin_y))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).polygon(local_corners, fill=255)
    canvas.paste(tile, (int(origin_x), int(origin_y)), mask)
    return True


def _paste_strategic_hex(
    canvas: Any,
    plot: dict[str, Any] | None,
    cx: float,
    cy: float,
    hex_radius: float,
    prefer_civ5_sprites: bool = False,
) -> bool:
    dim_factor = 1.0
    if isinstance(plot, dict) and plot.get("knowledge") == "remembered":
        dim_factor = 0.55
    if prefer_civ5_sprites:
        try:
            from sidecar import civ5_assets

            if civ5_assets.assets_available():
                paths = civ5_assets.strategic_layer_png_paths(plot)
                if paths:
                    return _paste_hex_sprite_layers(canvas, paths, cx, cy, hex_radius, dim_factor)
        except ImportError:
            pass
        sprite_path = map_render._strategic_sprite_path(plot, prefer_civ5_sprites=True)
        if sprite_path is None:
            return False
        width, height = _hex_sprite_size(hex_radius)
        map_render._paste_image_raster_fit(canvas, sprite_path, cx, cy, width, height)
        return True
    if civ6_assets.assets_available():
        sprite_path = civ6_assets.strategic_png_path(plot)
    else:
        sprite_path = None
    if sprite_path is None:
        return False
    width, height = _hex_sprite_size(hex_radius)
    map_render._paste_image_raster_fit(canvas, sprite_path, cx, cy, width, height)
    return True


def _draw_city_nameplate(
    draw: Any,
    font: Any,
    cx: float,
    cy: float,
    hex_radius: float,
    name: str,
    population: Any,
) -> None:
    pop_text = ""
    if population is not None:
        try:
            pop_text = str(int(population))
        except (TypeError, ValueError):
            pop_text = str(population)
    label = f"{name}  {pop_text}" if pop_text else name
    label = label[:22]
    text_y = cy - hex_radius * 1.05
    bbox = draw.textbbox((cx, text_y), label, font=font, anchor="mm")
    pad = 2
    draw.rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        fill=(72, 32, 24, 220),
    )
    draw.text((cx, text_y), label, fill="#f0ece0", font=font, anchor="mm")


def _paste_civ5_overlay(
    canvas: Any,
    slug: str,
    cx: float,
    cy: float,
    tile_px: int,
    scale: float,
    tint_rgb: tuple[int, int, int] | None = None,
) -> None:
    icon_px = max(14, int(tile_px * scale))
    ox = int(cx - icon_px / 2)
    oy = int(cy - icon_px / 2)
    map_render._paste_icon_raster(canvas, slug, ox, oy, icon_px, tint_rgb=tint_rgb)


def _paste_civ5_unit(
    canvas: Any,
    draw: Any,
    slug: str,
    cx: float,
    cy: float,
    tile_px: int,
    scale: float,
    fill_rgb: tuple[int, int, int],
) -> None:
    disc_px = max(14, int(tile_px * scale))
    r = disc_px / 2
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=fill_rgb,
        outline=(20, 20, 20),
        width=max(1, disc_px // 12),
    )
    _paste_civ5_overlay(canvas, slug, cx, cy, tile_px, scale * 0.72, (248, 248, 248))


def _paste_resource_icon(
    canvas: Any,
    plot: dict[str, Any] | None,
    cx: float,
    cy: float,
    hex_radius: float,
    tile_px: int,
) -> None:
    if not isinstance(plot, dict):
        return
    resource_id = plot.get("resource_id")
    if not isinstance(resource_id, str) or not resource_id.strip():
        return
    slug = map_icons.resource_icon_slug(resource_id)
    if not slug:
        return
    icon_px = max(12, int(tile_px * 0.42))
    ox = int(cx + hex_radius * 0.22 - icon_px // 2)
    oy = int(cy - hex_radius * 0.62)
    map_render._paste_icon_raster(canvas, slug, ox, oy, icon_px)


def _plot_has_ruins(plot: dict[str, Any] | None) -> bool:
    if not isinstance(plot, dict):
        return False
    if plot.get("goody") is True:
        return True
    improvement = plot.get("improvement_id")
    return isinstance(improvement, str) and improvement == "IMPROVEMENT_GOODY_HUT"


def _paste_ruins_marker(
    canvas: Any,
    plot: dict[str, Any] | None,
    cx: float,
    cy: float,
    hex_radius: float,
) -> None:
    if not _plot_has_ruins(plot):
        return
    from PIL import ImageDraw

    draw = ImageDraw.Draw(canvas)
    r = max(3, int(hex_radius * 0.22))
    color = (232, 196, 72, 255)
    outline = (90, 60, 10, 255)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline=outline)
    draw.ellipse((cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2), fill=outline)


def collect_settle_markers(snapshot: dict[str, Any]) -> list[tuple[int, int, str]]:
    """No ranked settle overlays (Civ5 policy): model reads the map itself."""
    _ = snapshot
    return []


def _hex_coord_label_flags(vw: int, vh: int) -> tuple[bool, bool]:
    """Small viewports: in-hex coords only. About 2x an 8x12 view: axes only."""
    cells = vw * vh
    if cells <= 0:
        return False, False
    if cells >= HEX_AXIS_ONLY_MIN_CELLS:
        return True, False
    return False, True


def _draw_hex_ring(
    draw: Any,
    corners: list[tuple[float, float]],
    color: str,
    width: int,
) -> None:
    if len(corners) < 2:
        return
    points = list(corners) + [corners[0]]
    draw.line(points, fill=map_render._rgb_tuple(color), width=max(1, width))


def _draw_outlined_text(
    draw: Any,
    xy: tuple[float, float],
    text: str,
    font: Any,
    fill: str = "#f2f2f2",
    outline: str = "#101010",
    anchor: str = "mm",
) -> None:
    x, y = xy
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        draw.text((x + dx, y + dy), text, fill=outline, font=font, anchor=anchor)
    draw.text((x, y), text, fill=fill, font=font, anchor=anchor)


def render_civ6_map_png(
    snapshot: dict[str, Any],
    path: Path | None = None,
    prefer_civ5_sprites: bool = False,
    *,
    viewport: dict[str, int] | None = None,
    target_size: int | None = None,
    image_role: str | None = None,
) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    map_icons.set_render_context(prefer_civ5=prefer_civ5_sprites)
    if not prefer_civ5_sprites and civ6_assets.assets_available():
        civ6_assets.ensure_civ6_assets()
    pipeline.ensure_known_map_plots(snapshot)
    tile_px_base = map_render.resolve_map_tile_px()
    if prefer_civ5_sprites:
        tile_px_base = max(tile_px_base, 64)
    plot_index = map_render.build_render_plot_index(snapshot)
    viewport_pad = 1 if prefer_civ5_sprites else map_render.DEFAULT_VIEWPORT_PAD
    min_viewport = 1 if prefer_civ5_sprites else map_render.MIN_VIEWPORT_TILES
    if viewport is None:
        viewport = map_render.resolve_render_viewport(
            snapshot, plot_index, pad=viewport_pad, min_tiles=min_viewport,
            prefer_tight=prefer_civ5_sprites,
        )
    else:
        viewport = map_render.clamp_viewport_to_map(
            viewport,
            int(snapshot["game"]["map_width"]),
            int(snapshot["game"]["map_height"]),
        )
    known_map = snapshot.get("known_map", {})
    game = snapshot.get("game", {})
    map_width = int(game.get("map_width"))
    map_height = int(game.get("map_height"))
    x0, y0 = viewport["x0"], viewport["y0"]
    vw, vh = viewport["width"], viewport["height"]
    tile_px = map_render._effective_tile_px(tile_px_base, vw, vh)
    if prefer_civ5_sprites:
        cap = max(52, map_render.resolve_max_canvas_px() // max(vw, vh))
        tile_px = max(52, min(tile_px_base, cap))
    flip_y = prefer_civ5_sprites
    _ = image_role
    show_axis, show_tile_coords = _hex_coord_label_flags(vw, vh)
    axis_font = map_render._axis_label_font(tile_px, x0, y0, vw, vh)
    if prefer_civ5_sprites:
        axis_font = max(axis_font, 10)
    axis_gutter = map_render._axis_gutter_size(axis_font) if show_axis else 0
    if show_axis:
        axis_gutter = max(axis_gutter, axis_font * 2 + 8)
    cell_font, legend_font, legend_swatch, legend_icon, _ = map_render._scaled_fonts(tile_px)
    if prefer_civ5_sprites:
        legend_font = max(legend_font, 11)
    legend_font_pil = map_render._load_bitmap_font(legend_font)
    normalized = map_render._normalize_visibility_grid(
        known_map.get("visibility_grid") if isinstance(known_map.get("visibility_grid"), list) else [],
        map_width,
        map_height,
    )
    map_w, map_h = _odd_r_map_size(vw, vh, tile_px, axis_gutter)
    tile_markers = map_render.build_tile_markers(snapshot, viewport)
    owner_index = map_render.build_territory_owner_index(snapshot, plot_index)
    territory_owners = map_render._territory_owners_in_viewport(owner_index, viewport)
    from PIL import ImageFont as _ImageFont

    font = legend_font_pil
    axis_label_font = map_render._load_bitmap_font(axis_font)
    has_visibility_grid = normalized is not None
    if prefer_civ5_sprites:
        terrain_items, terrain_strip_h = [], 0
    else:
        terrain_legend = map_render.collect_civ6_viewport_terrain_legend(
            plot_index, viewport, normalized, known_map, has_visibility_grid,
        )
        terrain_items, terrain_strip_h = map_render._layout_legend_items(
            terrain_legend, map_w, legend_font, legend_swatch, legend_font_pil,
        )
    territory_labels = [
        (map_render._player_label(snapshot, player_id), map_render._player_color(player_id))
        for player_id in territory_owners
    ]
    territory_items, territory_strip_h = map_render._layout_legend_items(
        territory_labels, map_w, legend_font, legend_swatch, legend_font_pil,
    ) if territory_labels else ([], 0)
    resource_legend = map_render.collect_civ6_viewport_resource_legend(plot_index, viewport)
    has_ruins = any(_plot_has_ruins(plot) for plot in plot_index.values())
    if prefer_civ5_sprites:
        marker_entries = []
    else:
        marker_entries = map_icons.legend_marker_entries(tile_markers, snapshot)
    icon_legend_rows = [(meaning, "#888888") for _, meaning in marker_entries]
    icon_legend_rows.extend([(label, "#888888") for _, label in resource_legend])
    if has_ruins:
        icon_legend_rows.append(("ruins", "#e8c448"))
    icon_items, icon_strip_h = map_render._layout_legend_items(
        icon_legend_rows, map_w, legend_font, legend_icon, legend_font_pil,
    ) if icon_legend_rows else ([], 0)
    icon_slugs_for_draw = [slug for slug, _ in marker_entries]
    if prefer_civ5_sprites:
        icon_slugs_for_draw.extend("_" for _ in resource_legend)
    else:
        icon_slugs_for_draw.extend(slug for slug, _ in resource_legend)
    if has_ruins:
        icon_slugs_for_draw.append("")
    show_river_legend = map_render.viewport_has_river_edges(plot_index, viewport)
    river_items, river_strip_h = map_render._layout_legend_items(
        [(RIVER_LABEL, RIVER_STROKE)], map_w, legend_font, legend_swatch, legend_font_pil,
    ) if show_river_legend else ([], 0)
    settle_markers = collect_settle_markers(snapshot)
    settle_legend_rows: list[tuple[str, str]] = []
    if any(role == "look" for _x, _y, role in settle_markers):
        settle_legend_rows.append((SETTLE_LOOK_LABEL, SETTLE_LOOK_COLOR))
    if any(role == "here" for _x, _y, role in settle_markers):
        settle_legend_rows.append((SETTLE_HERE_LABEL, SETTLE_HERE_COLOR))
    settle_items, settle_strip_h = map_render._layout_legend_items(
        settle_legend_rows, map_w, legend_font, legend_swatch, legend_font_pil,
    ) if settle_legend_rows else ([], 0)
    viewport_header_h = legend_font + map_render.LEGEND_HEADER_GAP
    legend_strip_h = viewport_header_h + terrain_strip_h + river_strip_h
    if settle_items:
        legend_strip_h += map_render.LEGEND_HEADER_GAP + settle_strip_h
    if territory_items:
        legend_strip_h += map_render.LEGEND_HEADER_GAP + territory_strip_h
    if icon_items:
        legend_strip_h += map_render.LEGEND_HEADER_GAP + icon_strip_h
    legend_strip_h += 4
    total_h = map_h + legend_strip_h

    canvas = Image.new("RGBA", (map_w, total_h), map_render._rgb_tuple("#121218") + (255,))
    draw = ImageDraw.Draw(canvas)
    radius, _, _ = _hex_metrics(tile_px)
    hex_radius = radius
    river_width = max(10, tile_px // 5) if prefer_civ5_sprites else max(4, tile_px // 8)
    rendered_tiles = 0
    river_edges_drawn = 0

    if show_axis:
        y_even = y0 - (y0 & 1)
        y_odd = y_even + 1
        even_label_y = max(2, axis_font // 2 + 1)
        odd_label_y = axis_gutter - max(2, axis_font // 2 + 1)
        for vx in range(vw):
            wx = x0 + vx
            cx_even, _, _, _ = _odd_r_cell_center(
                wx, y_even, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh,
            )
            cx_odd, _, _, _ = _odd_r_cell_center(
                wx, y_odd, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh,
            )
            draw.text((cx_even, even_label_y), str(wx), fill="#9a9a9a", font=axis_label_font, anchor="mm")
            draw.text((cx_odd, odd_label_y), str(wx), fill="#d0d0d0", font=axis_label_font, anchor="mm")
        for vy in range(vh):
            wy = y0 + vy
            _, cy, _, _ = _odd_r_cell_center(x0, y0 + vy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
            draw.text((axis_gutter - 2, cy), str(wy), fill="#999999", font=axis_label_font, anchor="rm")

    for vy in range(vh):
        wy = y0 + vy
        for vx in range(vw):
            wx = x0 + vx
            key = (wx, wy)
            plot = plot_index.get(key)
            grid_char = map_render._grid_char_at(
                normalized, wx, wy, origin=map_render.visibility_grid_origin(known_map),
            )
            state = map_render._tile_terrain_state(plot, grid_char, has_visibility_grid)
            territory_owner = owner_index.get(key) if state == "revealed" else None
            fill = map_render._tile_fill(plot, grid_char, state, territory_owner)
            cx, cy, lx, ly = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
            corners = _flat_top_hex_corners(cx, cy, hex_radius)
            if state == "revealed":
                rendered_tiles += 1
                used_sprite = _paste_strategic_hex(
                    canvas, plot, cx, cy, hex_radius, prefer_civ5_sprites=prefer_civ5_sprites,
                )
                if not used_sprite:
                    draw.polygon(corners, fill=map_render._rgb_tuple(fill), outline="#333333")
                elif not prefer_civ5_sprites:
                    draw.polygon(corners, outline="#333333")
                _paste_resource_icon(canvas, plot, cx, cy, hex_radius, tile_px)
                _paste_ruins_marker(canvas, plot, cx, cy, hex_radius)
                if territory_owner is not None:
                    owner_color = map_render._player_color(territory_owner)
                    border_width = max(2, tile_px // 5) if prefer_civ5_sprites else max(1, tile_px // 10)
                    if not prefer_civ5_sprites:
                        owner_color = map_render._darken_hex(owner_color, 0.75)
                    for nx, ny, edge in _hex_neighbors_odd_r(wx, wy):
                        neighbor_owner = owner_index.get((nx, ny))
                        if neighbor_owner != territory_owner:
                            inset = 0.0 if prefer_civ5_sprites else 0.15
                            if flip_y:
                                ncx, ncy, _, _ = _odd_r_cell_center(
                                    nx, ny, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh,
                                )
                                edge = _edge_index_toward_neighbor(cx, cy, ncx, ncy, corners)
                            seg = _hex_edge_segment(corners, edge, inset)
                            draw.line(
                                seg,
                                fill=map_render._rgb_tuple(owner_color),
                                width=border_width,
                            )
            else:
                draw.polygon(corners, fill=map_render._rgb_tuple(fill))

    if show_tile_coords:
        for vy in range(vh):
            wy = y0 + vy
            for vx in range(vw):
                wx = x0 + vx
                cx, cy, _, _ = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
                coord_font = map_render._coord_font_size(tile_px, wx, wy)
                _draw_outlined_text(
                    draw,
                    (cx, cy + hex_radius * 0.52),
                    f"{wx},{wy}",
                    map_render._coord_label_font(coord_font),
                )

    for (vx, vy), markers in sorted(tile_markers.items(), key=lambda item: (item[0][1], item[0][0])):
        wx, wy = x0 + vx, y0 + vy
        cx, cy, _, _ = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
        px = int(cx - tile_px // 2)
        py = int(cy - tile_px // 2)
        cities = [m for m in markers if m.get("kind") == "city"]
        others = [m for m in markers if m.get("kind") != "city"]
        if prefer_civ5_sprites:
            for marker in cities:
                slug = map_icons.city_icon_slug(bool(marker.get("is_capital")))
                _paste_civ5_overlay(canvas, slug, cx, cy, tile_px, 0.62)
                name_font = map_render._load_bitmap_font(max(7, tile_px // 4))
                _draw_city_nameplate(
                    draw,
                    name_font,
                    cx,
                    cy,
                    hex_radius,
                    str(marker.get("name", "City")),
                    marker.get("population"),
                )
            player_id = str(snapshot.get("decision", {}).get("player_id", "PLAYER_0"))
            own_rgb = map_render._hex_to_rgb(map_render._player_color(player_id))
            foreign_rgb = map_render._hex_to_rgb("#ff4444")
            unit_scale = 0.42 if not cities else 0.34
            for index, marker in enumerate(others):
                kind = marker.get("kind")
                if kind == "stack":
                    _paste_civ5_unit(
                        canvas, draw, "UNIT_FLAG:UNIT_WARRIOR", cx, cy, tile_px, unit_scale, own_rgb,
                    )
                    continue
                if kind != "unit":
                    continue
                foreign = bool(marker.get("foreign"))
                slug = map_icons.icon_slug_for_unit(str(marker.get("unit_type_id", "UNIT")))
                fill = foreign_rgb if foreign else own_rgb
                dy = hex_radius * 0.22 * index
                _paste_civ5_unit(canvas, draw, slug, cx, cy + dy, tile_px, unit_scale, fill)
            continue
        city_icon_px = map_icons.icon_px_for_tile(tile_px, 1)
        for marker in cities:
            ox, oy = map_render._center_icon_offset(tile_px, city_icon_px)
            slug = map_icons.city_icon_slug(bool(marker.get("is_capital")))
            ix, iy = px + ox, py + oy
            map_render._paste_icon_raster(canvas, slug, ix, iy, city_icon_px)
            if marker.get("is_capital"):
                draw.rectangle(
                    (ix - 1, iy - 1, ix + city_icon_px, iy + city_icon_px),
                    outline="#f4c040",
                    width=max(2, tile_px // 12),
                )
        other_icon_px = map_icons.icon_px_for_tile(tile_px, len(others))
        for index, marker in enumerate(others):
            kind = marker.get("kind")
            ox, oy = map_icons.tile_slot_offsets(tile_px, other_icon_px, index, len(others))
            ix, iy = px + ox, py + oy
            if kind == "stack":
                map_render._paste_icon_raster(canvas, "stack", ix, iy, other_icon_px)
            elif kind == "unit":
                foreign = bool(marker.get("foreign"))
                slug = map_icons.icon_slug_for_unit(str(marker.get("unit_type_id", "UNIT")))
                tint_rgb: tuple[int, int, int] | None = None
                if foreign and not slug.startswith("ICON_") and not slug.startswith("UNIT_FLAG:"):
                    slug = "unit_foreign"
                map_render._paste_icon_raster(canvas, slug, ix, iy, other_icon_px, tint_rgb=tint_rgb)
                if foreign:
                    draw.rectangle(
                        (ix, iy, ix + other_icon_px - 1, iy + other_icon_px - 1),
                        outline="#ff4444",
                        width=1,
                    )

    settle_rings_drawn = 0
    for wx, wy, role in settle_markers:
        if wx < x0 or wy < y0 or wx >= x0 + vw or wy >= y0 + vh:
            continue
        cx, cy, _, _ = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
        corners = _flat_top_hex_corners(cx, cy, hex_radius)
        if role == "look":
            _draw_hex_ring(draw, corners, SETTLE_LOOK_COLOR, max(3, tile_px // 7))
        else:
            _draw_hex_ring(draw, corners, SETTLE_HERE_COLOR, max(2, tile_px // 10))
        settle_rings_drawn += 1

    river_segments, river_edges_drawn = _collect_river_segments(
        plot_index, normalized, known_map, has_visibility_grid, viewport,
        x0, y0, tile_px, axis_gutter, flip_y, vh, hex_radius,
        prefer_civ5=prefer_civ5_sprites,
    )
    _draw_river_network(draw, river_segments, river_width)

    draw.line((0, map_h, map_w, map_h), fill="#444444", width=1)
    ly_header = map_h + 6
    draw.text(
        (4, ly_header),
        f"viewport x0={x0} y0={y0} {vw}x{vh} flat-top odd-r hex",
        fill="#cccccc",
        font=font,
    )
    legend_y = ly_header + viewport_header_h
    for lx, ly_row, label, color in terrain_items:
        row_y = legend_y + ly_row
        draw.rectangle(
            (lx, row_y - legend_swatch, lx + legend_swatch, row_y),
            fill=map_render._rgb_tuple(color),
            outline="#555555",
        )
        draw.text((lx + legend_swatch + 3, row_y), label, fill="#bbbbbb", font=font, anchor="ls")
    legend_y += terrain_strip_h
    for lx, ly_row, label, color in river_items:
        row_y = legend_y + ly_row
        draw.line(
            (lx, row_y - legend_swatch // 2, lx + legend_swatch, row_y - legend_swatch // 2),
            fill=map_render._rgb_tuple(color),
            width=max(2, legend_swatch // 3),
        )
        draw.text((lx + legend_swatch + 3, row_y), label, fill="#bbbbbb", font=font, anchor="ls")
    legend_y += river_strip_h
    if settle_items:
        legend_y += map_render.LEGEND_HEADER_GAP
        for lx, ly_row, label, color in settle_items:
            row_y = legend_y + ly_row
            draw.line(
                (lx, row_y - legend_swatch // 2, lx + legend_swatch, row_y - legend_swatch // 2),
                fill=map_render._rgb_tuple(color),
                width=max(2, legend_swatch // 3),
            )
            draw.text((lx + legend_swatch + 3, row_y), label, fill="#bbbbbb", font=font, anchor="ls")
        legend_y += settle_strip_h
    if territory_items:
        legend_y += map_render.LEGEND_HEADER_GAP
        for lx, ly_row, label, color in territory_items:
            row_y = legend_y + ly_row
            draw.rectangle(
                (lx, row_y - legend_swatch, lx + legend_swatch, row_y),
                fill=map_render._rgb_tuple(color),
                outline="#555555",
            )
            draw.text((lx + legend_swatch + 3, row_y), label, fill="#bbbbbb", font=font, anchor="ls")
        legend_y += territory_strip_h
    if icon_items:
        legend_y += map_render.LEGEND_HEADER_GAP
        for (lx, ly_row, meaning, _), slug in zip(icon_items, icon_slugs_for_draw):
            row_y = legend_y + ly_row
            if slug:
                map_render._paste_icon_raster(canvas, slug, lx, row_y - legend_icon, legend_icon)
            else:
                draw.ellipse(
                    (lx, row_y - legend_icon, lx + legend_icon, row_y),
                    fill=(232, 196, 72),
                    outline=(90, 60, 10),
                )
            draw.text((lx + legend_icon + 3, row_y), meaning, fill="#bbbbbb", font=legend_font_pil, anchor="ls")
        legend_y += icon_strip_h

    raw, mime = map_render.encode_model_image_bytes(canvas, target_size=target_size)
    digest = hashlib.sha256(raw).hexdigest()
    data_url = map_render.model_image_data_url(raw, mime)
    model_size = target_size or map_render.MODEL_IMAGE_SIZE
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return {
        "format": "png-hex-flat-top-v2",
        "mime_type": mime,
        "sha256": digest,
        "width": model_size,
        "height": model_size,
        "source_width": map_w,
        "source_height": total_h,
        "image_bytes": len(raw),
        "data_url": data_url,
        "tile_px": tile_px,
        "viewport": viewport,
        "image_role": image_role,
        "rendered_tiles": rendered_tiles,
        "river_edges_drawn": river_edges_drawn,
        "settle_rings_drawn": settle_rings_drawn,
        "known_plot_tiles": len(plot_index),
        "hex_layout": "odd-r-flat-top",
        "show_axis_labels": show_axis,
        "show_tile_coords": show_tile_coords,
        "legend_has_terrain": bool(terrain_items),
        "legend_has_markers": bool(marker_entries),
    }


def render_civ6_map_for_model(snapshot: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Civ VI always uses flat-top odd-r hex minimap (square Civ IV renderer is wrong for hex grids)."""
    return render_civ6_map_png(snapshot, path)
