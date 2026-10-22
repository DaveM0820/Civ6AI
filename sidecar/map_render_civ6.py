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
PEAK_LABEL = "mountain (white peak, impassable)"
NORTH_UP_ENV = "CIV6_MAP_NORTH_UP"
FOREIGN_RING = (255, 64, 64)
# Feature sprite (forest/jungle/marsh) drawn over the base terrain at this scale,
# so the terrain/hills underneath stays visible as a ring.
FEATURE_OVERLAY_SCALE = 0.66
_BASE_LAYER_CACHE: dict[str, Any] = {}
_BASE_LAYER_CACHE_LIMIT = 8
_HEX_LAYER_CACHE: dict[tuple[Any, ...], Any] = {}
_HEX_MASK_CACHE: dict[tuple[int, int, int], Any] = {}
_HEX_LAYER_CACHE_LIMIT = 256
_TINT_SOLID_CACHE: dict[tuple[Any, ...], Any] = {}
_TINT_MASK_CACHE: dict[tuple[int, int, int, int], Any] = {}
# 1px per-tile grid. A light, low-alpha stroke: the page background used to
# show through the seam as a black mesh, and a dark stroke upscales into a
# heavy line. Civ borders are a separate full-color stroke and stay bold.
HEX_GRID_OUTLINE = (255, 255, 255, 42)


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


# Embassy (Diplomatic Service) and exchanging capitals on first meeting reveal
# that one city tile. A delegation does not. A coloured ring on the black
# neighbours reads as land the seat explored.
LONE_CITY_LEGEND = (
    "Lone city in black fog: an embassy or exchanging capitals revealed that tile only. "
    "A delegation does not. Black neighbors were not explored."
)


def _reveal_state(
    plot_index: dict[tuple[int, int], dict[str, Any]],
    normalized: list[str] | None,
    known_map: dict[str, Any],
    has_visibility_grid: bool,
    x: int,
    y: int,
) -> str:
    grid_char = map_render._grid_char_at(
        normalized, x, y, origin=map_render.visibility_grid_origin(known_map),
    )
    return map_render._tile_terrain_state(plot_index.get((x, y)), grid_char, has_visibility_grid)


def isolated_revealed_cities(
    snapshot: dict[str, Any],
    plot_index: dict[tuple[int, int], dict[str, Any]],
    normalized: list[str] | None,
    known_map: dict[str, Any],
    has_visibility_grid: bool,
) -> set[tuple[int, int]]:
    """Revealed city plots whose six neighbours are still fog."""
    found: set[tuple[int, int]] = set()
    cities = list(snapshot.get("your_cities") or []) + list(snapshot.get("known_other_cities") or [])
    for city in cities:
        if not isinstance(city, dict):
            continue
        coords = map_render._parse_plot_coords(city.get("plot_id"))
        if coords is None:
            continue
        x, y = coords
        if _reveal_state(plot_index, normalized, known_map, has_visibility_grid, x, y) != "revealed":
            continue
        if all(
            _reveal_state(plot_index, normalized, known_map, has_visibility_grid, nx, ny) != "revealed"
            for nx, ny, _edge in _hex_neighbors_odd_r(x, y)
        ):
            found.add((x, y))
    return found


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


def _axis_gutter_for_tile(
    tile_px: int,
    x0: int,
    y0: int,
    vw: int,
    vh: int,
    *,
    show_axis: bool,
    prefer_civ5_sprites: bool,
) -> int:
    if not show_axis or vw <= 0 or vh <= 0:
        return 0
    axis_font = map_render._axis_label_font(tile_px, x0, y0, vw, vh)
    if prefer_civ5_sprites:
        axis_font = max(axis_font, 10)
    axis_gutter = map_render._axis_gutter_size(axis_font)
    return max(axis_gutter, axis_font * 2 + 8)


def _tile_px_for_model_target(
    current: int,
    vw: int,
    vh: int,
    target_size: int | None,
    *,
    x0: int,
    y0: int,
    show_axis: bool,
    prefer_civ5_sprites: bool,
) -> int:
    """Draw hexes near the PNG size that is sent, instead of stretching a smaller canvas.

    Fonts and icons are sized from tile_px. A letterbox upscale of a ~960px
    drawing does not add detail, so when a model image size is set the hex
    field is rasterized to about 88% of that square (the legend uses the rest).
    """
    if not isinstance(target_size, int) or target_size < 256 or vw <= 0 or vh <= 0:
        return current
    budget = max(128, int(target_size * 0.88))
    lo, hi = 12, 320
    best = 12
    found = False
    while lo <= hi:
        mid = (lo + hi) // 2
        gutter = _axis_gutter_for_tile(
            mid, x0, y0, vw, vh, show_axis=show_axis, prefer_civ5_sprites=prefer_civ5_sprites,
        )
        map_w, map_h = _odd_r_map_size(vw, vh, mid, gutter)
        if max(map_w, map_h) <= budget:
            best = mid
            found = True
            lo = mid + 1
        else:
            hi = mid - 1
    if not found:
        return current
    return max(current, best)


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
    scales = tuple(layer_scales or ())
    cache_key = (tuple(str(path) for path in sprite_paths), width, height, round(dim_factor, 2), scales)
    tile = _HEX_LAYER_CACHE.get(cache_key)
    if tile is None:
        tile = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        tcx, tcy = width / 2, height / 2
        for layer_index, sprite_path in enumerate(sprite_paths):
            name = sprite_path.name.lower()
            if layer_index < len(scales):
                layer_scale = scales[layer_index]
            else:
                layer_scale = 0.72 if "mountain" in name else 1.0
            layer_w = max(4, int(width * layer_scale))
            layer_h = max(4, int(height * layer_scale))
            map_render._paste_image_raster_fit(tile, sprite_path, tcx, tcy, layer_w, layer_h)
        if dim_factor < 1.0:
            tile = _dim_rgba_image(tile, dim_factor)
        _HEX_LAYER_CACHE[cache_key] = tile
        if len(_HEX_LAYER_CACHE) > _HEX_LAYER_CACHE_LIMIT:
            _HEX_LAYER_CACHE.pop(next(iter(_HEX_LAYER_CACHE)))
    mask_key = (width, height, int(hex_radius * 100))
    mask = _HEX_MASK_CACHE.get(mask_key)
    if mask is None:
        tcx, tcy = width / 2, height / 2
        corners = _flat_top_hex_corners(tcx, tcy, hex_radius)
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).polygon(corners, fill=255)
        _HEX_MASK_CACHE[mask_key] = mask
    origin_x = cx - width / 2
    origin_y = cy - height / 2
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


def _territory_tint_alpha(plot: dict[str, Any] | None) -> float:
    alpha = map_render.TERRITORY_TINT_ALPHA
    if isinstance(plot, dict) and plot.get("knowledge") == "remembered":
        alpha *= 0.6
    return alpha


def _paste_territory_tint(
    canvas: Any,
    cx: float,
    cy: float,
    hex_radius: float,
    owner_color: str,
    alpha: float,
) -> None:
    """Low-alpha player wash inside the hex, on top of a strategic sprite.

    ``_tile_fill`` already tints solid fills. A sprite paste covers that fill,
    so owned land with terrain art needs the same wash composited over the art.
    Icons and units are drawn later and stay untinted.
    """
    from PIL import Image, ImageDraw

    width, height = _hex_sprite_size(hex_radius)
    rgb = map_render._hex_to_rgb(owner_color)
    alpha_byte = max(1, min(255, int(round(max(0.0, min(1.0, alpha)) * 255))))
    solid_key = (width, height, rgb)
    solid = _TINT_SOLID_CACHE.get(solid_key)
    if solid is None:
        solid = Image.new("RGBA", (width, height), rgb + (255,))
        _TINT_SOLID_CACHE[solid_key] = solid
    mask_key = (width, height, int(round(hex_radius * 100)), alpha_byte)
    mask = _TINT_MASK_CACHE.get(mask_key)
    if mask is None:
        tcx, tcy = width / 2, height / 2
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).polygon(_flat_top_hex_corners(tcx, tcy, hex_radius), fill=alpha_byte)
        _TINT_MASK_CACHE[mask_key] = mask
    canvas.paste(solid, (int(cx - width / 2), int(cy - height / 2)), mask)


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


def _plot_is_peak(plot: dict[str, Any] | None) -> bool:
    if not isinstance(plot, dict):
        return False
    if plot.get("peak"):
        return True
    return str(plot.get("terrain_id") or "").upper().endswith("_MOUNTAIN")


def _draw_peak_glyph(draw: Any, cx: float, cy: float, hex_radius: float) -> None:
    """Tall white peak with a dark ridge. A missing or pale mountain sprite reads as grass."""
    height = max(6.0, hex_radius * 0.92)
    width = height * 0.72
    apex = (cx, cy - height * 0.55)
    left = (cx - width, cy + height * 0.38)
    right = (cx + width, cy + height * 0.38)
    draw.polygon([apex, left, right], fill=(244, 244, 244), outline=(24, 24, 32))
    draw.line([left, apex, right], fill=(32, 32, 40), width=max(2, int(hex_radius * 0.08)))


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


_CITY_HP_GREEN = (72, 210, 74)
_WALL_HP_BLUE = (66, 148, 232)
_BAR_TRACK = (24, 24, 24)


def _percent_bar(current: Any, maximum: Any) -> int | None:
    if isinstance(current, bool) or isinstance(maximum, bool):
        return None
    if not isinstance(current, int) or not isinstance(maximum, int) or maximum <= 0:
        return None
    return max(0, min(100, int(round(100 * current / maximum))))


def _bars_from_defense(defense: dict[str, Any] | None) -> dict[str, int | None] | None:
    """Green city percent, and blue wall percent only when the city has walls."""
    if not isinstance(defense, dict):
        return None
    city = _percent_bar(defense.get("hp"), defense.get("max_hp"))
    if city is None and isinstance(defense.get("health_percent"), int) and not isinstance(defense.get("health_percent"), bool):
        city = max(0, min(100, defense["health_percent"]))
    if city is None:
        return None
    wall = None
    wall_max = defense.get("wall_max_hp")
    wall_hp = defense.get("wall_hp")
    if isinstance(wall_max, int) and not isinstance(wall_max, bool) and wall_max > 0 and isinstance(wall_hp, int) and not isinstance(wall_hp, bool):
        wall = max(0, min(100, int(round(100 * wall_hp / wall_max))))
    return {"city": city, "wall": wall}


def _city_bar_index(snapshot: dict[str, Any]) -> dict[tuple[int, int], dict[str, int | None]]:
    """Visible cities only. Own cities are in view; foreign cities need knowledge == visible."""
    by_xy: dict[tuple[int, int], dict[str, Any]] = {}
    civ6 = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    combat = civ6.get("combat") if isinstance(civ6, dict) else {}
    if isinstance(combat, dict):
        for key in ("city_defenses", "hostile_cities"):
            for row in combat.get(key) or []:
                if isinstance(row, dict) and isinstance(row.get("x"), int) and isinstance(row.get("y"), int):
                    by_xy.setdefault((row["x"], row["y"]), row)
    index: dict[tuple[int, int], dict[str, int | None]] = {}
    for city in snapshot.get("your_cities") or []:
        if not isinstance(city, dict):
            continue
        coords = map_render._parse_plot_coords(city.get("plot_id"))
        bars = _bars_from_defense(city.get("defense") if isinstance(city.get("defense"), dict) else None)
        if coords is not None and bars is not None:
            index[coords] = bars
    for city in snapshot.get("known_other_cities") or []:
        if not isinstance(city, dict) or city.get("knowledge") != "visible":
            continue
        coords = map_render._parse_plot_coords(city.get("plot_id"))
        if coords is None or coords in index:
            continue
        bars = _bars_from_defense(by_xy.get(coords))
        if bars is not None:
            index[coords] = bars
    return index


def _draw_city_defense_bars(
    draw: Any,
    cx: float,
    above_y: float,
    width: float,
    city_hp: Any,
    wall_hp: Any,
) -> None:
    """In-game banner: blue wall HP on top, green city HP under it, just above the name."""
    if city_hp is None:
        return
    try:
        city_frac = max(0.0, min(1.0, float(city_hp) / 100.0))
    except (TypeError, ValueError):
        return
    height = max(3, int(width / 16))
    gap = max(1, height // 3)
    left = cx - width / 2

    def bar(top: float, frac: float, color: tuple[int, int, int]) -> None:
        draw.rectangle((left, top, left + width, top + height), fill=_BAR_TRACK)
        if frac > 0:
            draw.rectangle((left, top, left + max(1.0, width * frac), top + height), fill=color)

    green_top = above_y - gap - height
    bar(green_top, city_frac, _CITY_HP_GREEN)
    if wall_hp is None:
        return
    try:
        wall_frac = max(0.0, min(1.0, float(wall_hp) / 100.0))
    except (TypeError, ValueError):
        return
    bar(green_top - gap - height, wall_frac, _WALL_HP_BLUE)


def _draw_city_nameplate(
    draw: Any,
    font: Any,
    cx: float,
    cy: float,
    hex_radius: float,
    name: str,
    population: Any,
    confine: bool = False,
    city_hp: Any = None,
    wall_hp: Any = None,
) -> None:
    pop_text = ""
    if population is not None:
        try:
            pop_text = str(int(population))
        except (TypeError, ValueError):
            pop_text = str(population)
    label = f"{name}  {pop_text}" if pop_text else name
    label = label[:22]
    if confine:
        label_y = cy + hex_radius * 0.55
        _draw_label_inside_hex(draw, font, cx, label_y, hex_radius, label)
        bbox = draw.textbbox((cx, label_y), label, font=font, anchor="mm")
        _draw_city_defense_bars(draw, cx, bbox[1], max(28.0, hex_radius), city_hp, wall_hp)
        return
    text_y = cy - hex_radius * 1.05
    bbox = draw.textbbox((cx, text_y), label, font=font, anchor="mm")
    pad = 2
    draw.rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        fill=(72, 32, 24, 220),
    )
    draw.text((cx, text_y), label, fill="#f0ece0", font=font, anchor="mm")
    _draw_city_defense_bars(draw, cx, bbox[1] - pad, max(28.0, bbox[2] - bbox[0]), city_hp, wall_hp)


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
    *,
    centered: bool = False,
) -> None:
    if not isinstance(plot, dict):
        return
    resource_id = plot.get("resource_id")
    if not isinstance(resource_id, str) or not resource_id.strip():
        return
    slug = map_icons.resource_icon_slug(resource_id)
    if not slug:
        return
    icon_px = max(10, int(tile_px * (0.32 if centered else 0.46)))
    if centered:
        ox = int(cx - icon_px // 2)
        oy = int(cy - icon_px // 2)
    else:
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


# Owned-territory tile state the map image carries so the prompt does not list it.
# Goody huts and barb camps already have their own markers and are not builder improvements.
_SKIP_IMPROVEMENT = {"IMPROVEMENT_GOODY_HUT", "IMPROVEMENT_BARBARIAN_CAMP"}
_SKIP_DISTRICT = {"DISTRICT_CITY_CENTER"}
_MARK_LETTERS = {
    "IMPROVEMENT_FARM": "F",
    "IMPROVEMENT_MINE": "M",
    "IMPROVEMENT_PASTURE": "Pa",
    "IMPROVEMENT_PLANTATION": "Pl",
    "IMPROVEMENT_QUARRY": "Q",
    "IMPROVEMENT_CAMP": "C",
    "IMPROVEMENT_FISHING_BOATS": "Fb",
    "IMPROVEMENT_LUMBER_MILL": "Lm",
    "IMPROVEMENT_FORT": "Ft",
    "IMPROVEMENT_OIL_WELL": "Ow",
    "IMPROVEMENT_OFFSHORE_OIL_RIG": "Or",
    "IMPROVEMENT_GEOTHERMAL_PLANT": "Gp",
    "IMPROVEMENT_SOLAR_FARM": "Sf",
    "IMPROVEMENT_WIND_FARM": "Wf",
    "IMPROVEMENT_SEASIDE_RESORT": "Sr",
    "IMPROVEMENT_BEACH_RESORT": "Br",
    "IMPROVEMENT_SKI_RESORT": "Sk",
}
_ICON_FILE: dict[str, Path | None] = {}


def _icon_file(slug: str) -> Path | None:
    """Resolved icon path, once per slug. Missing icons stay missing (letter badge instead)."""
    if not slug:
        return None
    if slug not in _ICON_FILE:
        path = map_icons.icon_path(slug)
        _ICON_FILE[slug] = path if path.is_file() else None
    return _ICON_FILE[slug]


def _owned_plot(plot: dict[str, Any] | None) -> bool:
    if not isinstance(plot, dict):
        return False
    owner = plot.get("revealed_owner_id")
    return isinstance(owner, str) and owner not in ("", "None")


def _mark_label(type_id: str, prefix: str) -> str:
    token = type_id[len(prefix):] if type_id.startswith(prefix) else type_id
    return token.replace("_", " ").lower()


def _mark_letters(type_id: str) -> str:
    known = _MARK_LETTERS.get(type_id)
    if known:
        return known
    parts = [part for part in type_id.split("_")[1:] if part]
    if len(parts) >= 2:
        return parts[0][0].upper() + parts[1][0].lower()
    return (parts[0][:1] if parts else "?").upper()


def _plot_marks(
    plot: dict[str, Any] | None,
) -> tuple[tuple[str, str, str] | None, tuple[str, str, str] | None]:
    """Improvement and district on an owned tile: (type id, legend label, letter badge)."""
    if not _owned_plot(plot) or not isinstance(plot, dict):
        return None, None
    improvement = plot.get("improvement_id")
    district = plot.get("district_id")
    improvement_mark = None
    district_mark = None
    if isinstance(improvement, str) and improvement and improvement not in _SKIP_IMPROVEMENT:
        label = _mark_label(improvement, "IMPROVEMENT_")
        if plot.get("improvement_pillaged") is True:
            label += " (pillaged)"
        improvement_mark = (improvement, label, _mark_letters(improvement))
    if isinstance(district, str) and district and district not in _SKIP_DISTRICT:
        district_mark = (district, _mark_label(district, "DISTRICT_"), _mark_letters(district))
    return improvement_mark, district_mark


def _draw_letter_badge(
    draw: Any,
    cx: float,
    cy: float,
    px: int,
    letters: str,
    pillaged: bool = False,
) -> None:
    radius = max(8, px // 2)
    outline = (220, 64, 48, 255) if pillaged else (240, 240, 240, 255)
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(28, 28, 32, 230),
        outline=outline,
    )
    font = map_render._coord_label_font(max(11, int(px * 0.72)))
    _draw_outlined_text(draw, (cx, cy), letters, font, fill="#f4f4f4")
    if pillaged:
        draw.line((cx - radius, cy - radius, cx + radius, cy + radius), fill=outline, width=2)


def _paste_mark(
    canvas: Any,
    draw: Any,
    slug: str,
    letters: str,
    cx: float,
    cy: float,
    icon_px: int,
    pillaged: bool = False,
) -> str:
    """Icon from the cached atlas when one exists, otherwise a letter badge. Returns the legend slug."""
    if _icon_file(slug) is not None:
        from PIL import ImageDraw

        badge = icon_px * 0.58
        ImageDraw.Draw(canvas).ellipse(
            (cx - badge, cy - badge, cx + badge, cy + badge),
            fill=(22, 22, 26, 255),
            outline=(220, 64, 48, 255) if pillaged else (230, 230, 230, 255),
        )
        map_render._paste_icon_raster(canvas, slug, int(cx - icon_px / 2), int(cy - icon_px / 2), icon_px)
        return slug
    _draw_letter_badge(draw, cx, cy, icon_px, letters, pillaged)
    return f"__mk:{letters}"


def _paste_tile_marks(
    canvas: Any,
    draw: Any,
    plot: dict[str, Any] | None,
    cx: float,
    cy: float,
    hex_radius: float,
    tile_px: int,
    *,
    stacked: bool = False,
) -> None:
    improvement, district = _plot_marks(plot)
    if improvement is None and district is None:
        return
    icon_px = max(16 if stacked else 14, int(tile_px * (0.46 if stacked else 0.40)))
    mark_y = cy if stacked else cy + hex_radius * 0.28
    if improvement is not None:
        _paste_mark(
            canvas, draw, map_icons.improvement_icon_slug(improvement[0]), improvement[2],
            cx - hex_radius * 0.55, mark_y, icon_px,
            pillaged=bool(isinstance(plot, dict) and plot.get("improvement_pillaged")),
        )
    if district is not None:
        _paste_mark(
            canvas, draw, map_icons.district_icon_slug(district[0]), district[2],
            cx + hex_radius * 0.55, mark_y, icon_px,
        )


def _viewport_mark_legend(
    plot_index: dict[tuple[int, int], dict[str, Any]],
    viewport: dict[str, int],
) -> tuple[list[tuple[str, str]], list[str], int, int]:
    """Legend rows for improvement and district types actually drawn, plus tile counts."""
    seen: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()
    improvements = 0
    districts = 0
    x0, y0 = viewport["x0"], viewport["y0"]
    for vy in range(viewport["height"]):
        for vx in range(viewport["width"]):
            improvement, district = _plot_marks(plot_index.get((x0 + vx, y0 + vy)))
            for mark, kind in ((improvement, "improvement"), (district, "district")):
                if mark is None:
                    continue
                if kind == "improvement":
                    improvements += 1
                    slug = map_icons.improvement_icon_slug(mark[0])
                else:
                    districts += 1
                    slug = map_icons.district_icon_slug(mark[0])
                if mark[1] in seen_ids:
                    continue
                seen_ids.add(mark[1])
                seen.append((mark[1], "#888888", slug if _icon_file(slug) else f"__mk:{mark[2]}"))
    return [(label, color) for label, color, _slug in seen], [slug for _label, _color, slug in seen], improvements, districts


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


def collect_settle_markers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Labeled legal settle tiles for the overlay (not part of the cached base layer)."""
    if not vision_maps_enabled():
        return []
    from sidecar import civ6_command_wire as command_wire

    return command_wire.labeled_settle_sites(snapshot)


def _hex_coord_label_flags(vw: int, vh: int) -> tuple[bool, bool]:
    """Small viewports: in-hex coords only. About 2x an 8x12 view: axes only."""
    cells = vw * vh
    if cells <= 0:
        return False, False
    if cells >= HEX_AXIS_ONLY_MIN_CELLS:
        return True, False
    return False, True


def _draw_settle_site_marker(
    draw: Any,
    canvas: Any,
    cx: float,
    cy: float,
    hex_radius: float,
    tile_px: int,
    site: dict[str, Any],
    *,
    marker: bool = True,
    label: bool = True,
) -> None:
    corners = _flat_top_hex_corners(cx, cy, hex_radius)
    if marker:
        _draw_hex_ring(draw, corners, SETTLE_LOOK_COLOR, max(2, tile_px // 8))
    label_text = str(site.get("label") or "")
    if label and label_text:
        font = map_render._coord_label_font(max(8, tile_px // 3))
        _draw_outlined_text(draw, (cx, cy - hex_radius * 0.12), label_text, font, fill="#fff4c0")
    if not marker:
        return
    icon_r = max(2, int(hex_radius * 0.14))
    if site.get("coastal"):
        ox, oy = cx - hex_radius * 0.38, cy + hex_radius * 0.32
        draw.polygon(
            [(ox - icon_r, oy), (ox + icon_r, oy), (ox, oy + icon_r)],
            fill=(64, 176, 220, 255),
            outline=(20, 80, 120, 255),
        )
    if site.get("fresh_water"):
        ox, oy = cx + hex_radius * 0.38, cy + hex_radius * 0.28
        draw.ellipse(
            (ox - icon_r, oy - icon_r, ox + icon_r, oy + icon_r),
            fill=(80, 160, 255, 255),
            outline=(20, 60, 140, 255),
        )


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


def _wrap_legend_line(text: str, font: Any, max_width: int, max_lines: int = 4) -> list[str]:
    """Break a legend header so it stays inside the image."""
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        width = font.getlength(trial) if hasattr(font, "getlength") else len(trial) * 6
        if width <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines[:max_lines]


def _draw_label_inside_hex(
    draw: Any,
    font: Any,
    cx: float,
    cy: float,
    hex_radius: float,
    label: str,
) -> None:
    """City name kept on the one revealed hex, with no filled plate on the fog."""
    limit = max(8, int(math.sqrt(3) * hex_radius * 0.9))
    text = (label or "City").strip() or "City"
    while len(text) > 1:
        bbox = draw.textbbox((cx, cy), text, font=font, anchor="mm")
        if bbox[2] - bbox[0] <= limit:
            break
        text = text[:-1]
    _draw_outlined_text(draw, (cx, cy), text, font)


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


# Terrain swatches stay off the strip (they read off the map). Resource, improvement,
# and district marks stay, because the model uses them to tell tiles apart.
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
    if hp < 0 or hp > 100:
        return
    height = max(3, int(width / 5))
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
    confine: bool = False,
    city_hp: Any = None,
    wall_hp: Any = None,
) -> None:
    if confine:
        _draw_label_inside_hex(draw, font, cx, top_y, hex_radius, label)
        bbox = draw.textbbox((cx, top_y), label, font=font, anchor="mm")
        _draw_city_defense_bars(draw, cx, bbox[1], max(28.0, hex_radius), city_hp, wall_hp)
        return
    bbox = draw.textbbox((cx, top_y), label, font=font, anchor="mm")
    pad = 2
    draw.rectangle(
        (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad),
        fill=fill_rgb,
        outline=(12, 12, 12),
    )
    draw.text((cx, top_y), label, fill=_text_rgb_for(fill_rgb), font=font, anchor="mm")
    _draw_city_defense_bars(draw, cx, bbox[1] - pad, max(28.0, bbox[2] - bbox[0]), city_hp, wall_hp)


def _compact_city_label(name: str, pop: Any, civ: str) -> str:
    """Short banner: city and population, owner only when it still fits one hex."""
    text = name.strip() or "City"
    if text.isdigit():
        text = civ or "City"
        civ = ""
    if pop is not None:
        try:
            text = f"{text} {int(pop)}"
        except (TypeError, ValueError):
            text = f"{text} {pop}"
    if civ and civ.lower() not in text.lower():
        short = civ[:10]
        if len(text) + len(short) <= 16:
            text = f"{text} {short}"
    return text[:16]


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
    nameplates: list[tuple[Any, ...]],
    *,
    stacked: bool = False,
    confine_label: bool = False,
    city_bars: dict[str, int | None] | None = None,
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
        civ = _owner_short_label(snapshot, owner) if foreign else ""
        label = _compact_city_label(name, marker.get("population"), civ)
        if marker.get("is_capital") and not foreign and len(label) <= 12:
            label = f"{label}*"
        font = map_render._load_bitmap_font(max(8, min(11, tile_px // 5)))
        label_y = cy + hex_radius * 0.55 if confine_label else cy - hex_radius * 0.92
        city_hp = city_bars.get("city") if isinstance(city_bars, dict) else None
        wall_hp = city_bars.get("wall") if isinstance(city_bars, dict) else None
        nameplates.append((font, cx, label_y, hex_radius, label, owner_rgb, confine_label, city_hp, wall_hp))

    units = [m for m in others if m.get("kind") in ("unit", "stack")]
    if not units:
        return
    count = len(units)
    crowded = bool(cities) or count > 1
    disc_px = max(10, int(tile_px * (0.40 if crowded else 0.56)))
    player_id = str(snapshot.get("decision", {}).get("player_id", "PLAYER_0"))
    if stacked and not cities:
        military = [m for m in units if not m.get("civilian")]
        civilian = [m for m in units if m.get("civilian")]
        positions = []
        ordered: list[dict[str, Any]] = []
        if military:
            positions.append((cx, cy - hex_radius * 0.46))
            ordered.append(military[0])
        if civilian:
            positions.append((cx, cy + hex_radius * 0.46))
            ordered.append(civilian[0])
        units = ordered
    elif cities:
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
        entries.append(("__unit_own__", "your unit (bar = health)"))
    if any(m.get("kind") == "unit" and m.get("foreign") for m in markers):
        entries.append(("__unit_foreign__", "foreign unit (red ring, owner colour)"))
    x0, y0 = viewport["x0"], viewport["y0"]
    in_view = [
        plot for (wx, wy), plot in plot_index.items()
        if x0 <= wx < x0 + viewport["width"] and y0 <= wy < y0 + viewport["height"]
    ]
    if any(_plot_is_hills(plot) for plot in in_view):
        entries.append(("__hills__", HILLS_LABEL))
    if any(_plot_is_peak(plot) for plot in in_view):
        entries.append(("__peak__", PEAK_LABEL))
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
    elif slug == "__peak__":
        _draw_peak_glyph(draw, cx, cy, size * 0.55)


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
    # S1..Sn settle labels belong on the tactical close-up and in the prompt.
    # The strategic overview is the whole front; a dozen S-labels hide the land.
    show_settle_labels = image_role != "overview"
    # Close-ups used to stamp (x,y) on every hex. Edge ticks stay readable; the
    # strategic overview keeps the area-based choice.
    zoomed = image_role in ("viewport", "focus")
    if zoomed:
        show_axis, show_tile_coords = vw > 0 and vh > 0, False
    else:
        show_axis, show_tile_coords = _hex_coord_label_flags(vw, vh)
    tile_px = _tile_px_for_model_target(
        tile_px, vw, vh, target_size,
        x0=x0, y0=y0, show_axis=show_axis, prefer_civ5_sprites=prefer_civ5_sprites,
    )
    axis_font = map_render._axis_label_font(tile_px, x0, y0, vw, vh)
    if prefer_civ5_sprites:
        axis_font = max(axis_font, 10)
    axis_gutter = _axis_gutter_for_tile(
        tile_px, x0, y0, vw, vh, show_axis=show_axis, prefer_civ5_sprites=prefer_civ5_sprites,
    )
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
    isolated_cities = isolated_revealed_cities(
        snapshot, plot_index, normalized, known_map if isinstance(known_map, dict) else {},
        has_visibility_grid,
    )
    legend_note = LONE_CITY_LEGEND if isolated_cities else ""
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
    mark_rows, mark_slugs, improvements_drawn, districts_drawn = _viewport_mark_legend(plot_index, viewport)
    has_ruins = any(_plot_has_ruins(plot) for plot in plot_index.values())
    if prefer_civ5_sprites:
        marker_entries = []
    else:
        marker_entries = _civ6_marker_legend_entries(tile_markers, snapshot, plot_index, viewport)
    icon_legend_rows = [(meaning, "#888888") for _, meaning in marker_entries]
    icon_legend_rows.extend([(label, "#888888") for _, label in resource_legend])
    icon_legend_rows.extend(mark_rows)
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
    icon_slugs_for_draw.extend(mark_slugs)
    if has_ruins:
        icon_slugs_for_draw.append("")
    show_river_legend = map_render.viewport_has_river_edges(plot_index, viewport)
    river_label = RIVER_LABEL if rivers_trusted else RIVER_TILE_LABEL
    river_items, river_strip_h = map_render._layout_legend_items(
        [(river_label, RIVER_STROKE)], map_w, legend_font, legend_swatch, legend_font_pil,
    ) if show_river_legend else ([], 0)
    settle_markers = collect_settle_markers(snapshot) if show_settle_labels else []
    settle_legend_rows: list[tuple[str, str]] = []
    if settle_markers:
        settle_legend_rows.append(("settle S1.. (coast / fresh)", SETTLE_LOOK_COLOR))
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
        resource_rows.extend(mark_rows)
        icon_items, icon_strip_h = map_render._layout_legend_items(
            resource_rows, map_w, legend_font, legend_icon, legend_font_pil,
        ) if resource_rows else ([], 0)
        icon_slugs_for_draw = (
            ["_" for _ in resource_legend] if prefer_civ5_sprites
            else [slug for slug, _ in resource_legend]
        )
        icon_slugs_for_draw.extend(mark_slugs)
    # Header line plus room for the first legend row (whose baseline sits one
    # swatch below the header); the old value let row 1 overlap the header text.
    if prefer_civ5_sprites:
        header_text = f"viewport x0={x0} y0={y0} {vw}x{vh} flat-top odd-r hex"
    else:
        direction = "north up (y grows up)" if flip_y else "y grows down"
        owned = (
            "improvement left, district right, resource center"
            if zoomed else
            "improvement lower-left, district lower-right (blank = unimproved)"
        )
        header_text = (
            f"x {x0}-{x0 + vw - 1}, y {y0}-{y0 + vh - 1} | {direction} | odd rows shifted right | {owned}"
        )
    header_lines = _wrap_legend_line(header_text, font, map_w - 8)
    note_lines = _wrap_legend_line(legend_note, font, map_w - 8, max_lines=6) if legend_note else []
    line_h = legend_font + 2
    viewport_header_h = legend_font + map_render.LEGEND_HEADER_GAP + max(legend_font, legend_swatch)
    if not prefer_civ5_sprites:
        # The owned-tile sentence wraps onto a second line instead of clipping.
        viewport_header_h += legend_font + 2
    viewport_header_h = max(
        viewport_header_h,
        (len(header_lines) + len(note_lines)) * line_h + map_render.LEGEND_HEADER_GAP + max(legend_font, legend_swatch),
    )
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
    river_segments: list[tuple[tuple[int, int], tuple[int, int]]] = []
    if rivers_trusted:
        river_segments, river_edges_drawn = _collect_river_segments(
            plot_index, normalized, known_map, has_visibility_grid, viewport,
            x0, y0, tile_px, axis_gutter, flip_y, vh, hex_radius,
            prefer_civ5=prefer_civ5_sprites,
        )

    grid_blob = "".join(normalized) if isinstance(normalized, list) else ""
    hasher = hashlib.sha1()
    hasher.update(
        f"{map_w}x{map_h}:{tile_px}:{int(flip_y)}:{int(prefer_civ5_sprites)}:{int(zoomed)}:{x0},{y0},{vw},{vh}:{grid_blob}".encode()
    )
    revealed_in_view = 0
    for vy in range(vh):
        wy = y0 + vy
        for vx in range(vw):
            wx = x0 + vx
            plot = plot_index.get((wx, wy))
            grid_char = map_render._grid_char_at(
                normalized, wx, wy, origin=map_render.visibility_grid_origin(known_map),
            )
            state = map_render._tile_terrain_state(plot, grid_char, has_visibility_grid)
            if state == "revealed":
                revealed_in_view += 1
            terrain = ""
            owner = owner_index.get((wx, wy), "") if state == "revealed" else ""
            improvement_id = district_id = resource_id = ""
            pillaged = 0
            if isinstance(plot, dict):
                terrain = str(plot.get("terrain") or plot.get("terrain_type") or plot.get("terrain_id") or "")
                improvement_id = str(plot.get("improvement_id") or "")
                district_id = str(plot.get("district_id") or "")
                resource_id = str(plot.get("resource_id") or "")
                pillaged = 1 if plot.get("improvement_pillaged") else 0
            hasher.update(
                f"{wx},{wy},{state},{terrain},{owner},{improvement_id},{district_id},{resource_id},{pillaged}".encode()
            )
    cache_key = hasher.hexdigest()
    cached = _BASE_LAYER_CACHE.get(cache_key)
    used_base_cache = False
    if cached is not None and cached.size[0] == map_w and cached.size[1] == map_h:
        canvas.paste(cached, (0, 0))
        draw = ImageDraw.Draw(canvas)
        used_base_cache = True

    if show_axis and not used_base_cache:
        # Odd rows are shifted half a hex east. Drawing the same column number
        # on both parities printed every x label twice, half a hex apart.
        # One label, on the unshifted (even) column center.
        y_even = y0 - (y0 & 1)
        label_y = max(2, axis_font // 2 + 1)
        for vx in range(vw):
            wx = x0 + vx
            cx, _, _, _ = _odd_r_cell_center(
                wx, y_even, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh,
            )
            draw.text((cx, label_y), str(wx), fill="#9a9a9a", font=axis_label_font, anchor="mm")
        for vy in range(vh):
            wy = y0 + vy
            _, cy, _, _ = _odd_r_cell_center(x0, y0 + vy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
            draw.text((axis_gutter - 2, cy), str(wy), fill="#999999", font=axis_label_font, anchor="rm")

    if not used_base_cache:
        grid_overlay = Image.new("RGBA", (map_w, map_h), (0, 0, 0, 0))
        grid_draw = ImageDraw.Draw(grid_overlay)
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
                    # Terrain fill under the sprite closes the 1px seam. Without it
                    # the page background reads as a black grid between hexes.
                    fill_rgb = map_render._rgb_tuple(fill)
                    draw.polygon(corners, fill=fill_rgb, outline=fill_rgb)
                    used_sprite = _paste_strategic_hex(
                        canvas, plot, cx, cy, hex_radius, prefer_civ5_sprites=prefer_civ5_sprites,
                    )
                    if territory_owner is not None and used_sprite:
                        _paste_territory_tint(
                            canvas,
                            cx,
                            cy,
                            hex_radius,
                            map_render._player_color(territory_owner),
                            _territory_tint_alpha(plot),
                        )
                    # Civ5 sprite tiles never drew a per-tile stroke; keep that.
                    if not used_sprite or not prefer_civ5_sprites:
                        grid_draw.polygon(corners, outline=HEX_GRID_OUTLINE)
                else:
                    draw.polygon(corners, fill=map_render._rgb_tuple(fill))
        # Faint grid under icons. PIL's polygon outline replaces pixels, so the
        # stroke is composited from a clear layer instead of punched into the art.
        map_region = Image.alpha_composite(canvas.crop((0, 0, map_w, map_h)), grid_overlay)
        canvas.paste(map_region, (0, 0))
        draw = ImageDraw.Draw(canvas)
        # Terrain marks, then rivers, then civ borders. Icons and labels are
        # drawn after this layer so a river cannot cover a name.
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
                if state != "revealed":
                    continue
                cx, cy, _, _ = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
                if _plot_is_peak(plot):
                    # On top of the terrain sprite. A pale mountain tile otherwise
                    # reads as grass, and the model walks units onto it.
                    _draw_peak_glyph(draw, cx, cy, hex_radius)
                if prefer_civ5_sprites:
                    continue
                if _plot_is_hills(plot):
                    _draw_hills_glyph(draw, cx, cy, hex_radius)
                if not rivers_trusted and isinstance(plot, dict) and plot.get("river_edges"):
                    _draw_river_tile_mark(draw, cx, cy, hex_radius)
        if rivers_trusted and river_segments:
            _draw_river_network(draw, river_segments, river_width)
        border_width = max(2, tile_px // 5) if prefer_civ5_sprites else max(2, tile_px // 7)
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
                if state != "revealed":
                    continue
                territory_owner = owner_index.get(key)
                cx, cy, _, _ = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
                corners = _flat_top_hex_corners(cx, cy, hex_radius)
                if territory_owner is None:
                    continue
                owner_color = map_render._player_color(territory_owner)
                for nx, ny, edge in _hex_neighbors_odd_r(wx, wy):
                    if _reveal_state(
                        plot_index, normalized, known_map, has_visibility_grid, nx, ny,
                    ) != "revealed":
                        # A stroke on a black hex reads as explored land around a
                        # one-tile embassy capital.
                        continue
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
                if state != "revealed":
                    continue
                cx, cy, _, _ = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
                _paste_resource_icon(canvas, plot, cx, cy, hex_radius, tile_px, centered=zoomed)
                _paste_tile_marks(canvas, draw, plot, cx, cy, hex_radius, tile_px, stacked=zoomed)
                _paste_ruins_marker(canvas, plot, cx, cy, hex_radius)
        _BASE_LAYER_CACHE[cache_key] = canvas.crop((0, 0, map_w, map_h)).copy()
        if len(_BASE_LAYER_CACHE) > _BASE_LAYER_CACHE_LIMIT:
            _BASE_LAYER_CACHE.pop(next(iter(_BASE_LAYER_CACHE)))

    rendered_tiles = revealed_in_view

    nameplates: list[tuple[Any, float, float, float, str, tuple[int, int, int]]] = []
    civ5_nameplates: list[tuple[Any, ...]] = []
    city_bars = _city_bar_index(snapshot)
    for (vx, vy), markers in sorted(tile_markers.items(), key=lambda item: (item[0][1], item[0][0])):
        wx, wy = x0 + vx, y0 + vy
        cx, cy, _, _ = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
        cities = [m for m in markers if m.get("kind") == "city"]
        others = [m for m in markers if m.get("kind") != "city"]
        confine_label = (wx, wy) in isolated_cities
        bars = city_bars.get((wx, wy))
        if prefer_civ5_sprites:
            for marker in cities:
                slug = map_icons.city_icon_slug(bool(marker.get("is_capital")))
                _paste_civ5_overlay(canvas, slug, cx, cy, tile_px, 0.62)
                name_font = map_render._load_bitmap_font(max(7, tile_px // 4))
                civ5_nameplates.append((
                    name_font, cx, cy, hex_radius,
                    str(marker.get("name", "City")), marker.get("population"),
                    confine_label,
                    None if bars is None else bars.get("city"),
                    None if bars is None else bars.get("wall"),
                ))
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
            stacked=zoomed, confine_label=confine_label, city_bars=bars,
        )

    settle_rings_drawn = 0
    settle_label_sites: list[tuple[float, float, dict[str, Any]]] = []
    for site in settle_markers:
        wx, wy = int(site["x"]), int(site["y"])
        if wx < x0 or wy < y0 or wx >= x0 + vw or wy >= y0 + vh:
            continue
        cx, cy, _, _ = _odd_r_cell_center(wx, wy, x0, y0, tile_px, axis_gutter, flip_y=flip_y, vh=vh)
        _draw_settle_site_marker(
            draw, canvas, cx, cy, hex_radius, tile_px, site, marker=True, label=False,
        )
        settle_label_sites.append((cx, cy, site))
        settle_rings_drawn += 1

    # Labels are the top layer: coordinate text, then city names, then settle tags.
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
    for plate in civ5_nameplates:
        _draw_city_nameplate(draw, *plate)
    for plate in nameplates:
        _draw_civ6_nameplate(draw, *plate)
    for cx, cy, site in settle_label_sites:
        _draw_settle_site_marker(
            draw, canvas, cx, cy, hex_radius, tile_px, site, marker=False, label=True,
        )

    draw.line((0, map_h, map_w, map_h), fill="#444444", width=1)
    ly_header = map_h + 6
    for index, line in enumerate(header_lines + note_lines):
        draw.text((4, ly_header + index * (legend_font + 2)), line, fill="#cccccc", font=font)
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
            if _plot_is_peak(sample):
                _draw_peak_glyph(draw, lx + legend_swatch / 2, row_y - legend_swatch / 2, swatch_r)
            elif _plot_is_hills(sample):
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
            if slug.startswith("__mk:"):
                _draw_letter_badge(
                    draw, lx + legend_icon / 2, row_y - legend_icon / 2, legend_icon, slug.split(":", 1)[1],
                )
            elif slug.startswith("__"):
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

    # The hex field is already drawn near target_size. Allow a little grow so
    # the legend does not leave a short canvas, and no more: a bigger scale
    # would blur fonts and icons that were rasterized smaller.
    encode_kwargs: dict[str, Any] = {"target_size": target_size}
    if isinstance(target_size, int) and target_size > 0:
        encode_kwargs["max_upscale"] = 1.35
    elif zoomed and tile_px > 0:
        encode_kwargs["max_upscale"] = 72 / tile_px
    raw, mime = map_render.encode_model_image_bytes(canvas, **encode_kwargs)
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
        "settle_labels": [str(site.get("label")) for site in settle_markers],
        "known_plot_tiles": len(plot_index),
        "hex_layout": "odd-r-flat-top",
        "show_axis_labels": show_axis,
        "show_tile_coords": show_tile_coords,
        "legend_has_terrain": bool(terrain_items),
        "legend_has_markers": bool(marker_entries) or bool(mark_rows),
        "legend_note": legend_note,
        "improvements_drawn": improvements_drawn,
        "districts_drawn": districts_drawn,
        "tile_mark_legend": [label for label, _color in mark_rows],
        "north_up": bool(flip_y),
        "river_edges_trusted": bool(rivers_trusted),
    }


def render_civ6_map_for_model(snapshot: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Civ VI always uses flat-top odd-r hex minimap (square Civ IV renderer is wrong for hex grids)."""
    return render_civ6_map_png(snapshot, path)


def vision_maps_enabled() -> bool:
    """Qwen-flash default is text-only; skip rendering when vision is off (F9 / Q7)."""
    try:
        from sidecar.civ6_config import load_local_config

        return bool(load_local_config().vision)
    except Exception:
        return True
