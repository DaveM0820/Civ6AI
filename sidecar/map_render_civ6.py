"""Civ VI minimap renderer — flat-top odd-r hex layout with edge rivers."""
from __future__ import annotations

import base64
import hashlib
import math
import os
import re
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
RIVER_TILE_LABEL = "river on this tile (edge unknown)"
HILLS_LABEL = "hills (brown bumps)"
NORTH_UP_ENV = "CIV6_MAP_NORTH_UP"
FOREIGN_RING = (255, 64, 64)
# Feature sprite (forest/jungle/marsh) drawn over the base terrain at this scale,
# so the terrain/hills underneath stays visible as a ring.
FEATURE_OVERLAY_SCALE = 0.66


def civ6_map_north_up(snapshot: dict[str, Any] | None) -> bool:
    """Whether the Civ6 image (and prompt axis text) draws north at the top.

    Civ6, like Civ5, stores y=0 on the southern edge (y grows north). The snapshot Lua
    reports ``civ6.map.north_dy`` (dy of the NE neighbour); ``CIV6_MAP_NORTH_UP=0/1``
    overrides. Default: north up, like the Civ5 map images.
    """
    raw = os.environ.get(NORTH_UP_ENV, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    north_dy = _civ6_map_note_value(snapshot, "north_dy")
    if north_dy:
        return north_dy > 0
    return True


def _civ6_map_info(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    civ6 = snapshot.get("civ6")
    map_info = civ6.get("map") if isinstance(civ6, dict) else None
    return map_info if isinstance(map_info, dict) else {}


def _civ6_map_note_value(snapshot: dict[str, Any] | None, key: str) -> int | None:
    """``civ6.map.<key>`` if present, else ``measured <key>=N`` inside ``coords_note``.

    The schema keeps civ6.map closed, so newer Lua writes e.g.
    "grid x,y; Y increases north (measured north_dy=1); river_edges across-v2".
    The old hard-coded note ("Y increases south") carries no measurement and is ignored.
    """
    map_info = _civ6_map_info(snapshot)
    value = map_info.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    note = map_info.get("coords_note")
    if isinstance(note, str):
        match = re.search(rf"measured {re.escape(key)}=(-?\d+)", note)
        if match:
            return int(match.group(1))
    return None


def civ6_river_edges_trusted(snapshot: dict[str, Any] | None) -> bool:
    """False for legacy Lua output where every river edge is the (0,-1) fallback.

    Old Civ6Ai_Snapshot.lua called Map.PlotDirection (absent in Civ6), so every edge
    came back as dx=0, dy=-1: the tile has a river, but the side is unknown.
    """
    if not isinstance(snapshot, dict):
        return True
    map_info = _civ6_map_info(snapshot)
    note = map_info.get("coords_note")
    if map_info.get("river_edge_format") == "across-v2" or (
        isinstance(note, str) and "river_edges across-v2" in note
    ):
        return True
    known_map = snapshot.get("known_map")
    plots = known_map.get("plots") if isinstance(known_map, dict) else None
    items: list[dict[str, Any]] = []
    for plot in plots if isinstance(plots, list) else []:
        raw = plot.get("river_edges") if isinstance(plot, dict) else None
        if isinstance(raw, list):
            items.extend(item for item in raw if isinstance(item, dict))
    if len(items) < 2:
        return True
    return not all(
        item.get("dx") == 0 and item.get("dy") == -1 and not item.get("edge_id")
        for item in items
    )


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
    if abs(dx_i) > 1:
        # Neighbour across the X-wrap seam (dx = +/-(width-1)).
        dx_i = -1 if dx_i > 0 else 1
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
    # Per-channel lookup table instead of a per-pixel Python loop (same result).
    table = [int(value * factor) for value in range(256)]
    red, green, blue, alpha = work.split()
    return Image.merge("RGBA", (red.point(table), green.point(table), blue.point(table), alpha))


def _paste_hex_sprite_layers(
    canvas: Any,
    sprite_paths: list[Path],
    cx: float,
    cy: float,
    hex_radius: float,
    dim_factor: float = 1.0,
    layer_scales: list[float] | None = None,
) -> bool:
    if not sprite_paths:
        return False
    from PIL import Image, ImageDraw

    width, height = _hex_sprite_size(hex_radius)
    tile = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    tcx, tcy = width / 2, height / 2
    for layer_index, sprite_path in enumerate(sprite_paths):
        name = sprite_path.name.lower()
        if layer_scales is not None and layer_index < len(layer_scales):
            layer_scale = layer_scales[layer_index]
        else:
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
    layers = civ6_strategic_layers(plot)
    if not layers:
        return False
    return _paste_hex_sprite_layers(
        canvas,
        [path for path, _scale in layers],
        cx,
        cy,
        hex_radius,
        dim_factor,
        layer_scales=[scale for _path, scale in layers],
    )


def civ6_strategic_layers(plot: dict[str, Any] | None) -> list[tuple[Path, float]]:
    """Base terrain sprite, plus the feature sprite (forest/jungle/marsh) on top.

    The old renderer drew only the feature sprite, so "Grass Hills + Forest" looked
    like flat forest. Uses the cached crops even without a pantry install.
    """
    if not isinstance(plot, dict):
        return []
    top = civ6_assets.strategic_png_path(plot)
    if top is None:
        return []
    feature = plot.get("feature_id")
    if isinstance(feature, str) and feature.strip():
        base_plot = dict(plot)
        base_plot["feature_id"] = None
        base = civ6_assets.strategic_png_path(base_plot)
        if base is not None and base != top:
            return [(base, 1.0), (top, FEATURE_OVERLAY_SCALE)]
    return [(top, 1.0)]


def _plot_is_hills(plot: dict[str, Any] | None) -> bool:
    if not isinstance(plot, dict):
        return False
    if plot.get("peak"):
        return False
    terrain = str(plot.get("terrain_id") or "").upper()
    return bool(plot.get("hills")) or terrain.endswith("_HILLS")


def _draw_hills_glyph(draw: Any, cx: float, cy: float, hex_radius: float) -> None:
    """Two small brown bumps at the bottom of the hex; hills read as flat otherwise."""
    size = max(3.0, hex_radius * 0.24)
    base_y = cy + hex_radius * 0.62
    for offset, scale in ((-0.42, 1.0), (0.05, 0.8)):
        hx = cx + hex_radius * offset
        s = size * scale
        draw.pieslice(
            (hx - s, base_y - s, hx + s, base_y + s),
            180,
            360,
            fill=(150, 104, 58),
            outline=(52, 34, 16),
        )


def _draw_river_tile_mark(draw: Any, cx: float, cy: float, hex_radius: float) -> None:
    """Wavy blue stroke: this tile touches a river (legacy data has no side)."""
    width = max(2, int(hex_radius * 0.12))
    amp = hex_radius * 0.12
    x_start = cx - hex_radius * 0.55
    points = []
    steps = 8
    for i in range(steps + 1):
        t = i / steps
        points.append((x_start + t * hex_radius * 1.1, cy - hex_radius * 0.05 + amp * math.sin(t * 2 * math.pi)))
    draw.line(points, fill=map_render._rgb_tuple(RIVER_STROKE), width=width)


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
    icon_px = max(12, int(tile_px * 0.46))
    ox = int(cx + hex_radius * 0.22 - icon_px // 2)
    oy = int(cy - hex_radius * 0.62)
    if slug.startswith("ICON_"):
        # Dark badge (like Civ5's round resource plates) so the icon reads on any terrain.
        from PIL import ImageDraw

        badge = icon_px * 0.62
        bx, by = ox + icon_px / 2, oy + icon_px / 2
        ImageDraw.Draw(canvas).ellipse(
            (bx - badge, by - badge, bx + badge, by + badge),
            fill=(22, 22, 26, 255),
            outline=(210, 210, 210, 255),
        )
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


# Legend under each map image lists only resource icons (David, 2026-09-27).
LEGEND_RESOURCES_ONLY = True


def _terrain_legend_sample_plots(
    plot_index: dict[tuple[int, int], dict[str, Any]],
    viewport: dict[str, int],
    normalized: list[str] | None,
    known_map: dict[str, Any],
    has_visibility_grid: bool,
) -> dict[str, dict[str, Any]]:
    """First revealed plot per terrain legend label (for sprite thumbnails)."""
    samples: dict[str, dict[str, Any]] = {}
    origin = map_render.visibility_grid_origin(known_map)
    for vy in range(viewport["height"]):
        for vx in range(viewport["width"]):
            wx, wy = viewport["x0"] + vx, viewport["y0"] + vy
            plot = plot_index.get((wx, wy))
            grid_char = map_render._grid_char_at(normalized, wx, wy, origin=origin)
            state = map_render._tile_terrain_state(plot, grid_char, has_visibility_grid)
            if state != "revealed" or not isinstance(plot, dict):
                continue
            label = map_render.civ6_tile_legend_label(plot, grid_char, state)
            samples.setdefault(label, plot)
    return samples


def _owner_rgb(owner_player_id: str) -> tuple[int, int, int]:
    return map_render._hex_to_rgb(map_render._player_color(owner_player_id or ""))


def _owner_short_label(snapshot: dict[str, Any], owner_player_id: str) -> str:
    label = map_render._player_label(snapshot, owner_player_id) if owner_player_id else "?"
    label = label.removeprefix("CIVILIZATION_").replace("_", " ").title()
    return label[:14]


def _text_rgb_for(fill: tuple[int, int, int]) -> tuple[int, int, int]:
    luminance = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    return (16, 16, 16) if luminance > 150 else (245, 242, 232)


def _draw_hp_bar(draw: Any, cx: float, top: float, width: float, health_percent: Any) -> None:
    try:
        hp = float(health_percent)
    except (TypeError, ValueError):
        return
    if hp >= 100 or hp < 0:
        return
    height = max(2, int(width / 7))
    left = cx - width / 2
    draw.rectangle((left, top, left + width, top + height), fill=(30, 30, 30))
    frac = max(0.0, min(1.0, hp / 100.0))
    color = (70, 200, 70) if hp >= 66 else (230, 190, 40) if hp >= 33 else (220, 50, 40)
    draw.rectangle((left, top, left + max(1.0, width * frac), top + height), fill=color)


def _draw_unit_disc(
    canvas: Any,
    draw: Any,
    slug: str,
    cx: float,
    cy: float,
    disc_px: int,
    fill_rgb: tuple[int, int, int],
    foreign: bool,
    health_percent: Any = None,
) -> None:
    """Owner-coloured disc with the white Civ6 unit silhouette; red ring = not yours."""
    r = disc_px / 2
    ring = FOREIGN_RING if foreign else (18, 18, 18)
    ring_w = max(2, disc_px // 8) if foreign else max(1, disc_px // 14)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill_rgb, outline=ring, width=ring_w)
    icon_px = max(8, int(disc_px * 0.74))
    if slug:
        map_render._paste_icon_raster(canvas, slug, int(cx - icon_px / 2), int(cy - icon_px / 2), icon_px)
    _draw_hp_bar(draw, cx, cy + r + 1, disc_px, health_percent)


def _draw_civ6_nameplate(
    draw: Any,
    font: Any,
    cx: float,
    top_y: float,
    hex_radius: float,
    label: str,
    fill_rgb: tuple[int, int, int],
) -> None:
    del hex_radius
    bbox = draw.textbbox((cx, top_y), label, font=font, anchor="mm")
    pad = 2
    draw.rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        fill=fill_rgb,
        outline=(12, 12, 12),
    )
    draw.text((cx, top_y), label, fill=_text_rgb_for(fill_rgb), font=font, anchor="mm")


def _draw_civ6_tile_markers(
    canvas: Any,
    draw: Any,
    snapshot: dict[str, Any],
    cities: list[dict[str, Any]],
    others: list[dict[str, Any]],
    cx: float,
    cy: float,
    hex_radius: float,
    tile_px: int,
    nameplates: list[tuple[Any, float, float, float, str, tuple[int, int, int]]],
) -> None:
    for marker in cities:
        owner = str(marker.get("owner_player_id") or "")
        foreign = bool(marker.get("foreign"))
        owner_rgb = _owner_rgb(owner)
        icon_px = max(10, int(tile_px * 0.6))
        r = icon_px * 0.62
        ring = (244, 192, 64) if marker.get("is_capital") and not foreign else owner_rgb
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            fill=map_render._hex_to_rgb(map_render._darken_hex(map_render._player_color(owner), 0.45)),
            outline=ring,
            width=max(2, tile_px // 10),
        )
        slug = map_icons.city_icon_slug(bool(marker.get("is_capital")))
        map_render._paste_icon_raster(canvas, slug, int(cx - icon_px / 2), int(cy - icon_px / 2), icon_px)
        name = str(marker.get("name") or "City")
        pop = marker.get("population")
        label = name
        if pop is not None:
            try:
                label = f"{name} {int(pop)}"
            except (TypeError, ValueError):
                label = f"{name} {pop}"
        if marker.get("is_capital") and not foreign:
            label = f"{label} (capital)"
        if foreign:
            civ = _owner_short_label(snapshot, owner)
            if civ and civ.lower() not in name.lower():
                label = f"{label} ({civ})"
        font = map_render._load_bitmap_font(max(8, tile_px // 3))
        nameplates.append((font, cx, cy - hex_radius * 1.0, hex_radius, label[:30], owner_rgb))

    units = [m for m in others if m.get("kind") in ("unit", "stack")]
    if not units:
        return
    count = len(units)
    crowded = bool(cities) or count > 1
    disc_px = max(10, int(tile_px * (0.44 if crowded else 0.62)))
    player_id = str(snapshot.get("decision", {}).get("player_id", "PLAYER_0"))
    if cities:
        # Units sit on the lower edge of a city hex so the city icon stays readable.
        base_y = cy + hex_radius * 0.5
        spread = disc_px * 0.9
        start_x = cx - spread * (count - 1) / 2
        positions = [(start_x + i * spread, base_y) for i in range(count)]
    elif count == 1:
        positions = [(cx, cy)]
    else:
        spread = disc_px * 0.85
        start_x = cx - spread * (count - 1) / 2
        positions = [(start_x + i * spread, cy + (i % 2) * disc_px * 0.25) for i in range(count)]
    for (ux, uy), marker in zip(positions, units):
        if marker.get("kind") == "stack":
            _draw_unit_disc(canvas, draw, "", ux, uy, disc_px, _owner_rgb(player_id), False)
            font = map_render._load_bitmap_font(max(8, disc_px // 2))
            draw.text((ux, uy), str(marker.get("count") or "+"), fill="#ffffff", font=font, anchor="mm")
            continue
        owner = str(marker.get("owner_player_id") or player_id)
        foreign = bool(marker.get("foreign"))
        slug = map_icons.icon_slug_for_unit(str(marker.get("unit_type_id", "UNIT")))
        _draw_unit_disc(
            canvas, draw, slug, ux, uy, disc_px, _owner_rgb(owner), foreign,
            marker.get("health_percent"),
        )


def _civ6_marker_legend_entries(
    tile_markers: dict[tuple[int, int], list[dict[str, Any]]],
    snapshot: dict[str, Any],
    plot_index: dict[tuple[int, int], dict[str, Any]],
    viewport: dict[str, int],
) -> list[tuple[str, str]]:
    markers = [m for group in tile_markers.values() for m in group]
    entries: list[tuple[str, str]] = []
    if any(m.get("kind") == "city" and not m.get("foreign") for m in markers):
        entries.append(("__city_own__", "your city (gold ring = capital)"))
    if any(m.get("kind") == "city" and m.get("foreign") for m in markers):
        entries.append(("__city_foreign__", "other civ's city (ring/plate = owner colour)"))
    if any(m.get("kind") in ("unit", "stack") and not m.get("foreign") for m in markers):
        entries.append(("__unit_own__", "your unit (bar = damaged HP)"))
    if any(m.get("kind") == "unit" and m.get("foreign") for m in markers):
        entries.append(("__unit_foreign__", "foreign unit (red ring, owner colour)"))
    x0, y0 = viewport["x0"], viewport["y0"]
    in_view = [
        plot for (wx, wy), plot in plot_index.items()
        if x0 <= wx < x0 + viewport["width"] and y0 <= wy < y0 + viewport["height"]
    ]
    if any(_plot_is_hills(plot) for plot in in_view):
        entries.append(("__hills__", HILLS_LABEL))
    return entries


def _draw_legend_special(
    canvas: Any,
    draw: Any,
    slug: str,
    x: int,
    y: int,
    size: int,
    snapshot: dict[str, Any],
) -> None:
    cx, cy = x + size / 2, y + size / 2
    player_id = str(snapshot.get("decision", {}).get("player_id", "PLAYER_0"))
    own_rgb = _owner_rgb(player_id)
    foreign_rgb = map_render._hex_to_rgb("#b0b0b0")
    if slug == "__unit_own__":
        _draw_unit_disc(canvas, draw, map_icons.icon_slug_for_unit("UNIT_WARRIOR"), cx, cy, size, own_rgb, False)
    elif slug == "__unit_foreign__":
        _draw_unit_disc(canvas, draw, map_icons.icon_slug_for_unit("UNIT_WARRIOR"), cx, cy, size, foreign_rgb, True)
    elif slug in ("__city_own__", "__city_foreign__"):
        ring = (244, 192, 64) if slug == "__city_own__" else foreign_rgb
        r = size / 2
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(40, 40, 40), outline=ring, width=max(2, size // 8))
        icon = max(6, int(size * 0.8))
        map_render._paste_icon_raster(
            canvas, map_icons.city_icon_slug(False), int(cx - icon / 2), int(cy - icon / 2), icon,
        )
    elif slug == "__hills__":
        _draw_hills_glyph(draw, cx + size * 0.1, cy - size * 0.3, size * 0.6)


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
    flip_y = prefer_civ5_sprites or civ6_map_north_up(snapshot)
    rivers_trusted = prefer_civ5_sprites or civ6_river_edges_trusted(snapshot)
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
    terrain_sample_plots: dict[str, dict[str, Any]] = {}
    if prefer_civ5_sprites:
        terrain_items, terrain_strip_h = [], 0
    else:
        terrain_legend = map_render.collect_civ6_viewport_terrain_legend(
            plot_index, viewport, normalized, known_map, has_visibility_grid,
        )
        terrain_sample_plots = _terrain_legend_sample_plots(
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
        marker_entries = _civ6_marker_legend_entries(tile_markers, snapshot, plot_index, viewport)
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
    river_label = RIVER_LABEL if rivers_trusted else RIVER_TILE_LABEL
    river_items, river_strip_h = map_render._layout_legend_items(
        [(river_label, RIVER_STROKE)], map_w, legend_font, legend_swatch, legend_font_pil,
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
    if LEGEND_RESOURCES_ONLY:
        # Keep the axis header and the resource icons; terrain, borders, markers
        # and rivers read straight off the map and took half the image.
        terrain_items, terrain_strip_h = [], 0
        territory_items, territory_strip_h = [], 0
        river_items, river_strip_h = [], 0
        settle_items, settle_strip_h = [], 0
        resource_rows = [(label, "#888888") for _, label in resource_legend]
        icon_items, icon_strip_h = map_render._layout_legend_items(
            resource_rows, map_w, legend_font, legend_icon, legend_font_pil,
        ) if resource_rows else ([], 0)
        icon_slugs_for_draw = (
            ["_" for _ in resource_legend] if prefer_civ5_sprites
            else [slug for slug, _ in resource_legend]
        )
    # Header line plus room for the first legend row (whose baseline sits one
    # swatch below the header); the old value let row 1 overlap the header text.
    viewport_header_h = legend_font + map_render.LEGEND_HEADER_GAP + max(legend_font, legend_swatch)
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
                if not prefer_civ5_sprites:
                    if _plot_is_hills(plot):
                        _draw_hills_glyph(draw, cx, cy, hex_radius)
                    if not rivers_trusted and isinstance(plot, dict) and plot.get("river_edges"):
                        _draw_river_tile_mark(draw, cx, cy, hex_radius)
                _paste_resource_icon(canvas, plot, cx, cy, hex_radius, tile_px)
                _paste_ruins_marker(canvas, plot, cx, cy, hex_radius)
                if territory_owner is not None:
                    owner_color = map_render._player_color(territory_owner)
                    border_width = max(2, tile_px // 5) if prefer_civ5_sprites else max(2, tile_px // 7)
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

    nameplates: list[tuple[Any, float, float, float, str, tuple[int, int, int]]] = []
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
        _draw_civ6_tile_markers(
            canvas, draw, snapshot, cities, others, cx, cy, hex_radius, tile_px, nameplates,
        )

    for plate in nameplates:
        _draw_civ6_nameplate(draw, *plate)

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

    if rivers_trusted:
        river_segments, river_edges_drawn = _collect_river_segments(
            plot_index, normalized, known_map, has_visibility_grid, viewport,
            x0, y0, tile_px, axis_gutter, flip_y, vh, hex_radius,
            prefer_civ5=prefer_civ5_sprites,
        )
        _draw_river_network(draw, river_segments, river_width)

    draw.line((0, map_h, map_w, map_h), fill="#444444", width=1)
    ly_header = map_h + 6
    if prefer_civ5_sprites:
        header_text = f"viewport x0={x0} y0={y0} {vw}x{vh} flat-top odd-r hex"
    else:
        direction = "north up (y grows up)" if flip_y else "y grows down"
        header_text = (
            f"x {x0}-{x0 + vw - 1}, y {y0}-{y0 + vh - 1} | {direction} | odd rows shifted right"
        )
    draw.text((4, ly_header), header_text, fill="#cccccc", font=font)
    legend_y = ly_header + viewport_header_h
    for lx, ly_row, label, color in terrain_items:
        row_y = legend_y + ly_row
        sample = terrain_sample_plots.get(label)
        layers = civ6_strategic_layers(sample) if sample is not None else []
        swatch_r = legend_swatch * 0.62
        if layers and _paste_hex_sprite_layers(
            canvas,
            [path for path, _scale in layers],
            lx + legend_swatch / 2,
            row_y - legend_swatch / 2,
            swatch_r,
            layer_scales=[scale for _path, scale in layers],
        ):
            if _plot_is_hills(sample):
                _draw_hills_glyph(draw, lx + legend_swatch / 2, row_y - legend_swatch / 2, swatch_r)
        else:
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
            if slug.startswith("__"):
                _draw_legend_special(
                    canvas, draw, slug, lx, row_y - legend_icon, legend_icon, snapshot,
                )
            elif slug:
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
        "north_up": bool(flip_y),
        "river_edges_trusted": bool(rivers_trusted),
    }


def render_civ6_map_for_model(snapshot: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Civ VI always uses flat-top odd-r hex minimap (square Civ IV renderer is wrong for hex grids)."""
    return render_civ6_map_png(snapshot, path)
