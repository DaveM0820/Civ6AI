"""Cropped minimap-style SVG renderer for LLM map context.

Renders only the known-territory viewport at fixed tile_px per plot, with
terrain, markers, labels, and a legend strip. Dependency-free (SVG only).
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from sidecar import map_icons

DEFAULT_TILE_PX = 32
DEFAULT_VIEWPORT_PAD = 3
MIN_VIEWPORT_TILES = 8
MAX_VIEWPORT_TILES = 48
MAX_CANVAS_PX = 960
MAX_COORD_LABEL_CELLS = 128
TERRITORY_TINT_ALPHA = 0.22
MODEL_IMAGE_SIZE = 512
MODEL_IMAGE_MIME = "image/png"
CIV5_OVERVIEW_MODEL_IMAGE_SIZE = 768
CIV5_TACTICAL_MODEL_IMAGE_SIZE = 1024
CIV5_FOCUS_MODEL_IMAGE_SIZE = 384
GRID_MERGE_THRESHOLD = 4  # legacy wire inflation guard; renderer always merges grid when present
LEGEND_HEIGHT = 96
AXIS_GUTTER = 12
LEGEND_FONT_BASE = 6
LEGEND_SWATCH_BASE = 6
LEGEND_ICON_BASE = 6
LEGEND_ITEM_PAD = 12
LEGEND_HEADER_GAP = 6
CELL_FONT_BASE = 5
UNEXPLORED_FILL = "#000000"

TERRAIN_COLORS: dict[str, str] = {
    "TERRAIN_OCEAN": "#426080",
    "TERRAIN_COAST": "#5a8ab0",
    "TERRAIN_GRASS": "#6a9a5a",
    "TERRAIN_PLAINS": "#b0a070",
    "TERRAIN_DESERT": "#c8b070",
    "TERRAIN_TUNDRA": "#a0b0a8",
    "TERRAIN_SNOW": "#dce0e0",
}

GRID_CHAR_COLORS: dict[str, str] = {
    ".": "#6a9a5a",
    "~": "#5a8ab0",
    "^": "#9b9b9b",
    "#": "#777777",
}

TERRAIN_LEGEND = [
    ("Grass", "#6a9a5a"),
    ("Coast", "#5a8ab0"),
    ("Ocean", "#426080"),
    ("Plains", "#b0a070"),
    ("Desert", "#c8b070"),
    ("Hills", "#9b9b9b"),
    ("Peak", "#777777"),
    ("Unexplored", UNEXPLORED_FILL),
]

MARKER_LEGEND = [
    ("City", "#f4c040", "circle"),
    ("Your unit", "#50d8f0", "diamond"),
    ("Foreign unit", "#f05050", "diamond"),
    ("Stack", "#90ee90", "square"),
]

# Civ4 BTS primary slot colors (PLAYER_N index → in-game tint).
PLAYER_SLOT_COLORS: dict[str, str] = {
    "PLAYER_0": "#2860b0",
    "PLAYER_1": "#c02828",
    "PLAYER_2": "#e0c020",
    "PLAYER_3": "#38a038",
    "PLAYER_4": "#e07820",
    "PLAYER_5": "#38b8b8",
    "PLAYER_6": "#a040c0",
    "PLAYER_7": "#e8e8e8",
    "PLAYER_8": "#886838",
    "PLAYER_9": "#e080a8",
}


def resolve_map_tile_px() -> int:
    """Pixels per map tile in minimap SVG; override with CIV4AI_MAP_TILE_PX (12–48)."""
    raw = os.environ.get("CIV4AI_MAP_TILE_PX", str(DEFAULT_TILE_PX)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_TILE_PX
    return max(12, min(64, value))


def _resolve_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def resolve_max_canvas_px() -> int:
    return _resolve_int_env("CIV4AI_MAP_MAX_CANVAS_PX", MAX_CANVAS_PX, 240, 2400)


def resolve_max_coord_label_cells() -> int:
    return _resolve_int_env("CIV4AI_MAP_MAX_COORD_CELLS", MAX_COORD_LABEL_CELLS, 16, 512)


def resolve_civ5_overview_model_image_size(override: int | None = None) -> int:
    if isinstance(override, int) and override > 0:
        return max(256, min(2048, int(override)))
    raw = os.environ.get("CIV5AI_OVERVIEW_MODEL_IMAGE_SIZE") or os.environ.get("CIV5_OVERVIEW_MODEL_IMAGE_SIZE")
    if raw and str(raw).strip():
        try:
            return max(256, min(2048, int(str(raw).strip())))
        except ValueError:
            pass
    return CIV5_OVERVIEW_MODEL_IMAGE_SIZE


def resolve_civ5_tactical_model_image_size(override: int | None = None) -> int:
    if isinstance(override, int) and override > 0:
        return max(256, min(2048, int(override)))
    raw = os.environ.get("CIV5AI_TACTICAL_MODEL_IMAGE_SIZE") or os.environ.get("CIV5_TACTICAL_MODEL_IMAGE_SIZE")
    if raw and str(raw).strip():
        try:
            return max(256, min(2048, int(str(raw).strip())))
        except ValueError:
            pass
    return CIV5_TACTICAL_MODEL_IMAGE_SIZE


def resolve_civ5_focus_model_image_size(override: int | None = None) -> int:
    """Low-res focus tactical (~6x6). Clamped to 256-512 to keep vision cost small."""
    if isinstance(override, int) and override > 0:
        return max(256, min(512, int(override)))
    raw = os.environ.get("CIV5AI_FOCUS_MODEL_IMAGE_SIZE") or os.environ.get("CIV5_FOCUS_MODEL_IMAGE_SIZE")
    if raw and str(raw).strip():
        try:
            return max(256, min(512, int(str(raw).strip())))
        except ValueError:
            pass
    return CIV5_FOCUS_MODEL_IMAGE_SIZE


def resolve_max_viewport_tiles() -> int | None:
    """Optional viewport crop on large revealed areas; unset = no tile cap."""
    raw = os.environ.get("CIV4AI_MAP_MAX_VIEWPORT_TILES", "").strip()
    if not raw:
        return None
    return _resolve_int_env("CIV4AI_MAP_MAX_VIEWPORT_TILES", MAX_VIEWPORT_TILES, MIN_VIEWPORT_TILES, 512)


def _cap_viewport_to_max_tiles(
    viewport: dict[str, int],
    coords: list[tuple[int, int]],
    map_width: int,
    map_height: int,
    max_tiles: int,
) -> dict[str, int]:
    x0 = viewport["x0"]
    y0 = viewport["y0"]
    vw = viewport["width"]
    vh = viewport["height"]
    if vw <= max_tiles and vh <= max_tiles:
        return viewport
    if coords:
        cx = sum(c[0] for c in coords) // len(coords)
        cy = sum(c[1] for c in coords) // len(coords)
    else:
        cx = x0 + vw // 2
        cy = y0 + vh // 2
    new_vw = min(vw, max_tiles, map_width)
    new_vh = min(vh, max_tiles, map_height)
    x0 = max(0, min(cx - new_vw // 2, map_width - new_vw))
    y0 = max(0, min(cy - new_vh // 2, map_height - new_vh))
    return {"x0": x0, "y0": y0, "width": new_vw, "height": new_vh}


def _effective_tile_px(base_tile_px: int, vw: int, vh: int) -> int:
    """Shrink tiles on large viewports so the SVG stays within model-friendly bounds."""
    if vw <= 0 or vh <= 0:
        return base_tile_px
    max_canvas = resolve_max_canvas_px()
    longest = max(vw, vh)
    cap = max(12, max_canvas // longest)
    return max(12, min(base_tile_px, cap))


def _should_show_tile_coord_labels(vw: int, vh: int) -> bool:
    return vw > 0 and vh > 0 and (vw * vh) <= resolve_max_coord_label_cells()


def _coord_label_flags(vw: int, vh: int) -> tuple[bool, bool]:
    """Axis gutter labels always on; per-tile x,y gated by viewport area."""
    show_axis = vw > 0 and vh > 0
    show_tile = _should_show_tile_coord_labels(vw, vh)
    return show_axis, show_tile


def _axis_label_font(tile_px: int, x0: int, y0: int, vw: int, vh: int) -> int:
    """Scale axis numbers to fit tile columns and wide world coordinates."""
    fit_in_tile = max(3, tile_px - 2)
    size = max(CELL_FONT_BASE, min(fit_in_tile, tile_px // 3))
    max_world = max(x0 + vw - 1, y0 + vh - 1, x0, y0)
    digits = len(str(max_world))
    if digits >= 3:
        size = max(3, size - (digits - 2))
    return max(3, min(size, fit_in_tile))


def _axis_gutter_size(axis_font: int) -> int:
    return max(AXIS_GUTTER, axis_font + 3)


def _load_bitmap_font(size: int) -> Any:
    from PIL import ImageFont

    px = max(6, size)
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def _scaled_fonts(tile_px: int) -> tuple[int, int, int, int, int]:
    cell_font = max(CELL_FONT_BASE, tile_px // 4)
    legend_font = max(LEGEND_FONT_BASE, tile_px // 3)
    legend_swatch = max(LEGEND_SWATCH_BASE, tile_px // 3)
    legend_icon = max(LEGEND_ICON_BASE, tile_px // 3)
    legend_height = max(LEGEND_HEIGHT, 72 + legend_font * 4)
    return cell_font, legend_font, legend_swatch, legend_icon, legend_height


def _legend_text_width(label: str, legend_font: int, font: Any | None = None) -> int:
    if font is not None:
        try:
            return int(font.getlength(label))
        except AttributeError:
            return int(font.getbbox(label)[2])
    return max(legend_font, int(len(label) * legend_font * 0.58))


def _legend_item_width(label: str, legend_font: int, legend_swatch: int, font: Any | None = None) -> int:
    return legend_swatch + 3 + _legend_text_width(label, legend_font, font) + LEGEND_ITEM_PAD


def _layout_legend_items(
    items: list[tuple[str, str]],
    canvas_w: int,
    legend_font: int,
    legend_swatch: int,
    font: Any | None = None,
) -> tuple[list[tuple[int, int, str, str]], int]:
    """Return positioned legend items and total legend strip height below the map."""
    placed: list[tuple[int, int, str, str]] = []
    lx = 4
    ly_row = 0
    row_height = legend_font + LEGEND_HEADER_GAP
    for label, color in items:
        item_w = _legend_item_width(label, legend_font, legend_swatch, font)
        if lx > 4 and lx + item_w > canvas_w - 4:
            lx = 4
            ly_row += row_height
        placed.append((lx, ly_row, label, color))
        lx += item_w
    return placed, ly_row + row_height + 4


def _parse_plot_coords(plot_id: Any) -> tuple[int, int] | None:
    if not isinstance(plot_id, str) or not plot_id.startswith("PLOT_"):
        return None
    parts = plot_id.split("_")
    if len(parts) < 3:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _svg_text(value: Any) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def _terrain_from_visibility_char(cell: str) -> tuple[str, bool, bool, bool]:
    """Map Civ6 visibility_grid char to terrain, water, hills, peak (see Civ6Ai_Snapshot._VisibilityChar)."""
    if cell == "~":
        return "TERRAIN_COAST", True, False, False
    if cell == "o":
        return "TERRAIN_OCEAN", True, False, False
    if cell == "^":
        return "TERRAIN_GRASS", False, True, True
    if cell == "#":
        return "TERRAIN_GRASS", False, True, False
    return "TERRAIN_GRASS", False, False, False


def _plot_from_grid_cell(x: int, y: int, cell: str, knowledge: str = "remembered") -> dict[str, Any]:
    terrain_id, water, hills, peak = _terrain_from_visibility_char(cell)
    return {
        "plot_id": f"PLOT_{x}_{y}",
        "x": x,
        "y": y,
        "knowledge": knowledge,
        "last_seen_turn": None,
        "area_id": "AREA_0",
        "terrain_id": terrain_id,
        "water": water,
        "hills": hills,
        "peak": peak,
        "fresh_water": False,
        "river_edges": [],
        "revealed_owner_id": None,
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


def visibility_grid_origin(known_map: dict[str, Any] | None) -> tuple[int, int]:
    """visibility_grid rows are cropped to known_map.viewport, not full-map (0,0)."""
    if not isinstance(known_map, dict):
        return 0, 0
    viewport = known_map.get("viewport")
    if not isinstance(viewport, dict):
        image = known_map.get("image")
        if isinstance(image, dict):
            viewport = image.get("viewport")
    if not isinstance(viewport, dict):
        return 0, 0
    try:
        return int(viewport.get("x0") or 0), int(viewport.get("y0") or 0)
    except (TypeError, ValueError):
        return 0, 0


def _normalize_visibility_grid(grid: list[Any], width: int, height: int) -> list[str] | None:
    if not isinstance(grid, list) or not grid:
        return None
    rows: list[str] = []
    for y in range(height):
        if y < len(grid) and isinstance(grid[y], str):
            rows.append(grid[y])
        else:
            rows.append("?" * width)
    if not any(cell != "?" for row in rows for cell in row):
        return None
    return rows


def _revealed_grid_count(grid: list[str], width: int, height: int) -> int:
    count = 0
    for y in range(min(height, len(grid))):
        row = grid[y]
        for x in range(min(width, len(row))):
            if row[x] != "?":
                count += 1
    return count


def _merge_grid_into_index(
    index: dict[tuple[int, int], dict[str, Any]],
    normalized: list[str],
    width: int,
    height: int,
    origin: tuple[int, int] = (0, 0),
) -> None:
    """visibility_grid is authoritative for revealed tiles; plots[] may be DLL-thinned."""
    ox, oy = origin
    for y in range(min(height, len(normalized))):
        row = normalized[y]
        for x in range(min(width, len(row))):
            cell = row[x]
            if cell == "?":
                continue
            wx, wy = ox + x, oy + y
            key = (wx, wy)
            if key not in index:
                index[key] = _plot_from_grid_cell(wx, wy, cell)
            elif index[key].get("terrain_id") is None:
                merged = _plot_from_grid_cell(wx, wy, cell)
                index[key]["terrain_id"] = merged["terrain_id"]
                index[key]["water"] = merged["water"]


def _tile_terrain_state(
    plot: dict[str, Any] | None,
    grid_char: str | None,
    has_visibility_grid: bool,
) -> str:
    """revealed | fog | unknown — unknown means thinned snapshot, not confirmed fog."""
    if has_visibility_grid:
        if grid_char is not None and grid_char != "?":
            return "revealed"
        return "fog"
    if plot is not None:
        return "revealed"
    return "unknown"


def build_render_plot_index(snapshot: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    """Merge plots[] with visibility_grid; grid is authoritative for reveal mask."""
    known_map = snapshot.get("known_map", {})
    if not isinstance(known_map, dict):
        return {}
    game = snapshot.get("game", {})
    width = int(game.get("map_width", 0))
    height = int(game.get("map_height", 0))
    index: dict[tuple[int, int], dict[str, Any]] = {}
    plots = known_map.get("plots", [])
    if isinstance(plots, list):
        for plot in plots:
            if not isinstance(plot, dict):
                continue
            x, y = int(plot.get("x", -1)), int(plot.get("y", -1))
            if x >= 0 and y >= 0:
                index[(x, y)] = plot
    grid = known_map.get("visibility_grid")
    normalized = _normalize_visibility_grid(grid if isinstance(grid, list) else [], width, height)
    if normalized is not None:
        _merge_grid_into_index(
            index, normalized, width, height, origin=visibility_grid_origin(known_map),
        )
    return index


def _collect_marker_coords(snapshot: dict[str, Any]) -> list[tuple[int, int]]:
    """Cities, units, and stacks — always included in the viewport bbox."""
    coords: list[tuple[int, int]] = []
    for city in snapshot.get("your_cities", []) + snapshot.get("known_other_cities", []):
        if isinstance(city, dict):
            c = _parse_plot_coords(city.get("plot_id"))
            if c:
                coords.append(c)
    for unit in snapshot.get("your_units", []) + snapshot.get("visible_other_units", []):
        if isinstance(unit, dict):
            c = _parse_plot_coords(unit.get("plot_id"))
            if c:
                coords.append(c)
    for stack in snapshot.get("known_map", {}).get("visible_stacks", []):
        if isinstance(stack, dict):
            c = _parse_plot_coords(stack.get("plot_id"))
            if c:
                coords.append(c)
    return coords


def _collect_viewport_coords(
    snapshot: dict[str, Any],
    plot_index: dict[tuple[int, int], dict[str, Any]],
    normalized: list[str] | None,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """BBox all revealed tiles (grid + plots) plus entity markers."""
    coords: set[tuple[int, int]] = set(plot_index.keys())
    if normalized is not None:
        ox, oy = visibility_grid_origin(snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else None)
        for y in range(min(height, len(normalized))):
            row = normalized[y]
            for x in range(min(width, len(row))):
                if row[x] != "?":
                    coords.add((ox + x, oy + y))
    coords.update(_collect_marker_coords(snapshot))
    return list(coords)


def clamp_viewport_to_map(
    viewport: dict[str, int],
    map_width: int,
    map_height: int,
    *,
    max_width: int | None = None,
    max_height: int | None = None,
) -> dict[str, int]:
    """Clamp a viewport rectangle to map bounds and optional max dimensions."""
    try:
        x0 = int(viewport.get("x0", 0))
        y0 = int(viewport.get("y0", 0))
        vw = int(viewport.get("width", 0))
        vh = int(viewport.get("height", 0))
    except (TypeError, ValueError):
        return {"x0": 0, "y0": 0, "width": max(1, map_width), "height": max(1, map_height)}
    if vw <= 0 or vh <= 0:
        return {"x0": 0, "y0": 0, "width": max(1, map_width), "height": max(1, map_height)}
    if max_width is not None:
        vw = min(vw, max(1, int(max_width)))
    if max_height is not None:
        vh = min(vh, max(1, int(max_height)))
    x0 = max(0, min(x0, map_width - 1))
    y0 = max(0, min(y0, map_height - 1))
    vw = max(1, min(vw, map_width - x0))
    vh = max(1, min(vh, map_height - y0))
    return {"x0": x0, "y0": y0, "width": vw, "height": vh}


def compute_viewport(
    snapshot: dict[str, Any],
    plot_index: dict[tuple[int, int], dict[str, Any]],
    pad: int = DEFAULT_VIEWPORT_PAD,
    min_tiles: int = MIN_VIEWPORT_TILES,
) -> dict[str, int]:
    width = int(snapshot["game"]["map_width"])
    height = int(snapshot["game"]["map_height"])
    known_map = snapshot.get("known_map", {})
    normalized = _normalize_visibility_grid(
        known_map.get("visibility_grid") if isinstance(known_map.get("visibility_grid"), list) else [],
        width, height,
    )
    coords = _collect_viewport_coords(snapshot, plot_index, normalized, width, height)
    if not coords:
        cx, cy = width // 2, height // 2
        half = min_tiles // 2
        return {
            "x0": max(0, cx - half),
            "y0": max(0, cy - half),
            "width": min(min_tiles, width),
            "height": min(min_tiles, height),
        }
    min_x = min(c[0] for c in coords) - pad
    min_y = min(c[1] for c in coords) - pad
    max_x = max(c[0] for c in coords) + pad
    max_y = max(c[1] for c in coords) + pad
    x0 = max(0, min_x)
    y0 = max(0, min_y)
    x1 = min(width - 1, max_x)
    y1 = min(height - 1, max_y)
    vw = x1 - x0 + 1
    vh = y1 - y0 + 1
    if vw < min_tiles:
        extra = min_tiles - vw
        x0 = max(0, x0 - extra // 2)
        vw = min(min_tiles, width)
        x0 = min(x0, width - vw)
    if vh < min_tiles:
        extra = min_tiles - vh
        y0 = max(0, y0 - extra // 2)
        vh = min(min_tiles, height)
        y0 = min(y0, height - vh)
    viewport = {"x0": x0, "y0": y0, "width": vw, "height": vh}
    max_tiles = resolve_max_viewport_tiles()
    if max_tiles is not None:
        viewport = _cap_viewport_to_max_tiles(viewport, coords, width, height, max_tiles)
    return viewport


def resolve_render_viewport(
    snapshot: dict[str, Any],
    plot_index: dict[tuple[int, int], dict[str, Any]],
    pad: int = DEFAULT_VIEWPORT_PAD,
    min_tiles: int = MIN_VIEWPORT_TILES,
    prefer_tight: bool = False,
) -> dict[str, int]:
    """Use host-provided known_map.viewport when set; otherwise auto-fit revealed tiles."""
    known_map = snapshot.get("known_map", {})
    explicit = None
    if not prefer_tight:
        explicit = known_map.get("viewport") if isinstance(known_map, dict) else None
    if isinstance(explicit, dict):
        try:
            map_width = int(snapshot["game"]["map_width"])
            map_height = int(snapshot["game"]["map_height"])
            x0 = int(explicit.get("x0", 0))
            y0 = int(explicit.get("y0", 0))
            vw = int(explicit.get("width", 0))
            vh = int(explicit.get("height", 0))
            if vw > 0 and vh > 0:
                x0 = max(0, min(x0, map_width - 1))
                y0 = max(0, min(y0, map_height - 1))
                vw = max(1, min(vw, map_width - x0))
                vh = max(1, min(vh, map_height - y0))
                return {"x0": x0, "y0": y0, "width": vw, "height": vh}
        except (TypeError, ValueError, KeyError):
            pass
    return compute_viewport(snapshot, plot_index, pad=pad, min_tiles=min_tiles)


def _player_index(player_id: str) -> int | None:
    if not player_id.startswith("PLAYER_"):
        return None
    try:
        return int(player_id.split("_", 1)[1])
    except (IndexError, ValueError):
        return None


def _player_color(player_id: str) -> str:
    if player_id in PLAYER_SLOT_COLORS:
        return PLAYER_SLOT_COLORS[player_id]
    index = _player_index(player_id)
    if index is not None:
        return PLAYER_SLOT_COLORS.get(f"PLAYER_{index}", "#888888")
    return "#888888"


def _player_label(snapshot: dict[str, Any], player_id: str) -> str:
    decision_player = str(snapshot.get("decision", {}).get("player_id", ""))
    if player_id == decision_player:
        personality = snapshot.get("personality", {})
        if isinstance(personality, dict):
            civ = personality.get("civilization_id")
            if civ:
                return f"You ({str(civ).removeprefix('CIVILIZATION_')})"
        return "You"
    for player in snapshot.get("known_players", []):
        if isinstance(player, dict) and str(player.get("player_id", "")) == player_id:
            civ = player.get("civilization_id")
            if civ:
                return str(civ).removeprefix("CIVILIZATION_")
            return player_id
    return player_id


def _revealed_owner(plot: dict[str, Any] | None) -> str | None:
    if plot is None:
        return None
    owner = plot.get("revealed_owner_id")
    if owner is None:
        return None
    owner_id = str(owner).strip()
    return owner_id or None


def _normalize_player_id(value: Any) -> str | None:
    if value is None:
        return None
    player_id = str(value).strip()
    return player_id or None


def _chebyshev_distance(x0: int, y0: int, x1: int, y1: int) -> int:
    return max(abs(x0 - x1), abs(y0 - y1))


def _estimate_city_culture_radius(city: dict[str, Any]) -> int:
    """Approximate in-game culture ring from city population and stored culture."""
    population = max(1, int(city.get("population", 1)))
    culture_block = city.get("culture")
    culture_cur = 0
    if isinstance(culture_block, dict):
        culture_cur = int(culture_block.get("current", 0))
    if culture_cur >= 10000:
        return min(6, 3 + population // 3)
    if culture_cur >= 1000:
        return min(5, 2 + population // 2)
    if culture_cur >= 100:
        return min(4, 2 + population // 3)
    return max(1, min(3, (population + 1) // 2))


def _normalize_territory_owner_grid(
    grid: list[Any],
    width: int,
    height: int,
) -> list[str] | None:
    if not isinstance(grid, list) or not grid:
        return None
    rows: list[str] = []
    for y in range(height):
        if y < len(grid) and isinstance(grid[y], str):
            rows.append(grid[y])
        else:
            rows.append("?" * width)
    if not any(cell not in {"?", "."} for row in rows for cell in row):
        return None
    return rows


def _owners_from_territory_grid(grid: list[str], width: int, height: int) -> dict[tuple[int, int], str]:
    owners: dict[tuple[int, int], str] = {}
    for y in range(min(height, len(grid))):
        row = grid[y]
        for x in range(min(width, len(row))):
            cell = row[x]
            if cell.isdigit():
                owners[(x, y)] = f"PLAYER_{cell}"
    return owners


def _revealed_coords_from_snapshot(
    snapshot: dict[str, Any],
    plot_index: dict[tuple[int, int], dict[str, Any]],
) -> set[tuple[int, int]]:
    known_map = snapshot.get("known_map", {})
    game = snapshot.get("game", {})
    width = int(game.get("map_width", 0))
    height = int(game.get("map_height", 0))
    grid = known_map.get("visibility_grid") if isinstance(known_map, dict) else None
    normalized = _normalize_visibility_grid(grid if isinstance(grid, list) else [], width, height)
    revealed: set[tuple[int, int]] = set()
    if normalized is not None:
        ox, oy = visibility_grid_origin(known_map if isinstance(known_map, dict) else None)
        for y in range(min(height, len(normalized))):
            row = normalized[y]
            for x in range(min(width, len(row))):
                if row[x] != "?":
                    revealed.add((ox + x, oy + y))
    else:
        revealed.update(plot_index.keys())
    return revealed


def _expand_territory_from_cities(
    owners: dict[tuple[int, int], str],
    snapshot: dict[str, Any],
    revealed: set[tuple[int, int]],
) -> None:
    """Fill culture rings around known cities on revealed tiles (matches in-game minimap)."""
    for city in snapshot.get("your_cities", []) + snapshot.get("known_other_cities", []):
        if not isinstance(city, dict):
            continue
        center = _parse_plot_coords(city.get("plot_id"))
        owner = _normalize_player_id(city.get("owner_player_id") or city.get("player_id"))
        if center is None or not owner:
            continue
        cx, cy = center
        radius = _estimate_city_culture_radius(city)
        for coords in revealed:
            x, y = coords
            if _chebyshev_distance(cx, cy, x, y) <= radius:
                owners.setdefault(coords, owner)


def build_territory_owner_index(
    snapshot: dict[str, Any],
    plot_index: dict[tuple[int, int], dict[str, Any]],
) -> dict[tuple[int, int], str]:
    """Culture borders: DLL territory grid or city rings, then plot owners and markers."""
    owners: dict[tuple[int, int], str] = {}
    known_map = snapshot.get("known_map", {})
    game = snapshot.get("game", {})
    width = int(game.get("map_width", 0))
    height = int(game.get("map_height", 0))
    revealed = _revealed_coords_from_snapshot(snapshot, plot_index)
    if isinstance(known_map, dict):
        territory_grid = known_map.get("territory_owner_grid")
        normalized_territory = _normalize_territory_owner_grid(
            territory_grid if isinstance(territory_grid, list) else [],
            width,
            height,
        )
        if normalized_territory is not None:
            owners.update(_owners_from_territory_grid(normalized_territory, width, height))
    for coords, plot in plot_index.items():
        owner = _revealed_owner(plot)
        if owner:
            owners[coords] = owner
    if not owners:
        _expand_territory_from_cities(owners, snapshot, revealed)
    for city in snapshot.get("your_cities", []) + snapshot.get("known_other_cities", []):
        if not isinstance(city, dict):
            continue
        coords = _parse_plot_coords(city.get("plot_id"))
        owner = _normalize_player_id(city.get("owner_player_id") or city.get("player_id"))
        if coords is not None and owner:
            owners[coords] = owner
    if isinstance(known_map, dict):
        for stack in known_map.get("visible_stacks", []):
            if not isinstance(stack, dict):
                continue
            coords = _parse_plot_coords(stack.get("plot_id"))
            owner = _normalize_player_id(stack.get("owner_player_id"))
            if coords is not None and owner and coords not in owners:
                owners[coords] = owner
    return owners


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    if not hex_color.startswith("#") or len(hex_color) != 7:
        return (128, 128, 128)
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def _blend_hex(base: str, overlay: str, alpha: float) -> str:
    br, bg, bb = _hex_to_rgb(base)
    or_, og, ob = _hex_to_rgb(overlay)
    alpha = max(0.0, min(1.0, alpha))
    inv = 1.0 - alpha
    return _rgb_to_hex(
        int(br * inv + or_ * alpha),
        int(bg * inv + og * alpha),
        int(bb * inv + ob * alpha),
    )


def _darken_hex(hex_color: str, factor: float = 0.65) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    factor = max(0.0, min(1.0, factor))
    return _rgb_to_hex(int(r * factor), int(g * factor), int(b * factor))


def _terrain_fill(plot: dict[str, Any] | None, grid_char: str | None, state: str) -> str:
    if state in ("fog", "unknown"):
        return UNEXPLORED_FILL
    if plot is not None:
        terrain = plot.get("terrain_id")
        if isinstance(terrain, str) and terrain in TERRAIN_COLORS:
            color = TERRAIN_COLORS[terrain]
            if plot.get("knowledge") == "remembered":
                return _dim_hex(color)
            return color
    if grid_char and grid_char in GRID_CHAR_COLORS:
        return GRID_CHAR_COLORS[grid_char]
    return "#1a1a22"


def _tile_fill(
    plot: dict[str, Any] | None,
    grid_char: str | None,
    state: str,
    territory_owner: str | None = None,
) -> str:
    fill = _terrain_fill(plot, grid_char if state == "revealed" else None, state)
    if state != "revealed":
        return fill
    owner = territory_owner if territory_owner is not None else _revealed_owner(plot)
    if owner is None:
        return fill
    owner_color = _player_color(owner)
    alpha = TERRITORY_TINT_ALPHA
    if plot is not None and plot.get("knowledge") == "remembered":
        alpha *= 0.6
    return _blend_hex(fill, owner_color, alpha)


def _border_inset(tile_px: int) -> int:
    return max(1, tile_px // 12)


def _border_offset(tile_px: int) -> int:
    """How far each civ's stripe sits inside its own tile from the shared edge."""
    return max(1, tile_px // 12)


def _owner_border_segments(
    world_x: int,
    world_y: int,
    owner: str,
    owner_index: dict[tuple[int, int], str],
    px: int,
    py: int,
    tile_px: int,
) -> list[tuple[int, int, int, int, str]]:
    """Inward civ-colored stripes on edges where territory owner changes.

    When two civs meet, each tile draws its stripe on its own side of the edge,
    producing the classic parallel double border. Unowned neighbors get a single stripe.
    """
    owner_color = _darken_hex(_player_color(owner), 0.75)
    segments: list[tuple[int, int, int, int, str]] = []
    inset = _border_inset(tile_px)
    offset = _border_offset(tile_px)
    x_lo = px + inset
    x_hi = px + tile_px - inset
    y_lo = py + inset
    y_hi = py + tile_px - inset
    for dx, dy, edge in ((0, -1, "n"), (1, 0, "e"), (0, 1, "s"), (-1, 0, "w")):
        neighbor_owner = owner_index.get((world_x + dx, world_y + dy))
        if neighbor_owner == owner:
            continue
        if edge == "n":
            y = py + offset
            segments.append((x_lo, y, x_hi, y, owner_color))
        elif edge == "e":
            x = px + tile_px - offset
            segments.append((x, y_lo, x, y_hi, owner_color))
        elif edge == "s":
            y = py + tile_px - offset
            segments.append((x_lo, y, x_hi, y, owner_color))
        else:
            x = px + offset
            segments.append((x, y_lo, x, y_hi, owner_color))
    return segments


def _territory_owners_in_viewport(
    owner_index: dict[tuple[int, int], str],
    viewport: dict[str, int],
) -> list[str]:
    x0, y0 = viewport["x0"], viewport["y0"]
    vw, vh = viewport["width"], viewport["height"]
    owners: set[str] = set()
    for vy in range(vh):
        for vx in range(vw):
            owner = owner_index.get((x0 + vx, y0 + vy))
            if owner:
                owners.add(owner)
    return sorted(owners, key=lambda pid: (_player_index(pid) is None, _player_index(pid) or 999, pid))


def _cell_label_color(fill: str) -> str:
    if fill in {UNEXPLORED_FILL, "#1a1a22", "#426080", "#777777"}:
        return "#ddd"
    return "#111"


def _coord_font_size(tile_px: int, world_x: int, world_y: int) -> int:
    base = max(7, tile_px // 4)
    if world_x > 99 or world_y > 99:
        return max(6, base - 1)
    return min(base, 12)


def _coord_label_font(coord_font: int) -> Any:
    return _load_bitmap_font(max(5, coord_font))


def civ6_tile_legend_color(
    plot: dict[str, Any] | None,
    grid_char: str | None,
    state: str,
) -> str:
    if state == "fog":
        return "#2a2a30"
    if state != "revealed":
        return UNEXPLORED_FILL
    if isinstance(plot, dict):
        if plot.get("peak"):
            return GRID_CHAR_COLORS["^"]
        if plot.get("hills"):
            return GRID_CHAR_COLORS["#"]
        terrain = plot.get("terrain_id")
        if isinstance(terrain, str) and terrain in TERRAIN_COLORS:
            return TERRAIN_COLORS[terrain]
    if grid_char and grid_char in GRID_CHAR_COLORS:
        return GRID_CHAR_COLORS[grid_char]
    return "#1a1a22"


def civ6_tile_legend_label(
    plot: dict[str, Any] | None,
    grid_char: str | None,
    state: str,
) -> str:
    from sidecar import civ6_assets

    labels_map = civ6_assets.civ6_terrain_labels()
    feature_map = civ6_assets.civ6_feature_labels()
    if state == "fog":
        return "Fog"
    if state != "revealed":
        return "Unexplored"
    terrain_label = "Grass"
    if isinstance(plot, dict):
        terrain_id = plot.get("terrain_id")
        if isinstance(terrain_id, str):
            upper = terrain_id.upper()
            composite = upper
            if plot.get("hills") and not upper.endswith("_HILLS") and not upper.endswith("_MOUNTAIN"):
                composite = f"{upper}_HILLS"
            if plot.get("peak"):
                base, _, _ = civ6_assets._parse_terrain_id(upper)
                composite = f"{base}_MOUNTAIN"
            # Prefer catalog label; if composite hills/mountain is missing from the
            # pantry map, title-case the composite before falling back to the base.
            terrain_label = labels_map.get(composite)
            if terrain_label is None and composite != upper:
                terrain_label = composite.replace("TERRAIN_", "").replace("_", " ").title()
            if terrain_label is None:
                terrain_label = (
                    labels_map.get(upper)
                    or upper.replace("TERRAIN_", "").replace("_", " ").title()
                )
        elif grid_char == "o":
            terrain_label = labels_map.get("TERRAIN_OCEAN", "Ocean")
        elif grid_char == "~":
            terrain_label = labels_map.get("TERRAIN_COAST", "Coast")
        elif grid_char == "^":
            terrain_label = labels_map.get("TERRAIN_GRASS_MOUNTAIN", "Mountain")
        elif grid_char == "#":
            terrain_label = labels_map.get("TERRAIN_GRASS_HILLS", "Hills")
        feature_id = plot.get("feature_id")
        if isinstance(feature_id, str):
            feature_label = feature_map.get(
                feature_id.upper(),
                feature_id.replace("FEATURE_", "").replace("_", " ").title(),
            )
            return f"{terrain_label} + {feature_label}"
    elif grid_char == "o":
        terrain_label = labels_map.get("TERRAIN_OCEAN", "Ocean")
    elif grid_char == "~":
        terrain_label = labels_map.get("TERRAIN_COAST", "Coast")
    elif grid_char == "^":
        terrain_label = labels_map.get("TERRAIN_GRASS_MOUNTAIN", "Mountain")
    elif grid_char == "#":
        terrain_label = labels_map.get("TERRAIN_GRASS_HILLS", "Hills")
    return terrain_label


def collect_civ6_viewport_terrain_legend(
    plot_index: dict[tuple[int, int], dict[str, Any]],
    viewport: dict[str, int],
    normalized: list[str] | None,
    known_map: dict[str, Any],
    has_visibility_grid: bool,
) -> list[tuple[str, str]]:
    x0, y0 = viewport["x0"], viewport["y0"]
    vw, vh = viewport["width"], viewport["height"]
    origin = visibility_grid_origin(known_map)
    seen: dict[str, str] = {}
    for vy in range(vh):
        for vx in range(vw):
            wx, wy = x0 + vx, y0 + vy
            plot = plot_index.get((wx, wy))
            grid_char = _grid_char_at(normalized, wx, wy, origin=origin)
            state = _tile_terrain_state(plot, grid_char, has_visibility_grid)
            label = civ6_tile_legend_label(plot, grid_char, state)
            seen[label] = civ6_tile_legend_color(plot, grid_char, state)
    priority = {
        "Ocean": 0,
        "Coast": 1,
        "Fog": 90,
        "Unexplored": 91,
    }
    def sort_key(label: str) -> tuple[int, str]:
        for key, rank in priority.items():
            if label == key or label.startswith(key):
                return (rank, label)
        return (10, label)
    return [(label, seen[label]) for label in sorted(seen.keys(), key=sort_key)]


def collect_civ6_viewport_resource_legend(
    plot_index: dict[tuple[int, int], dict[str, Any]],
    viewport: dict[str, int],
) -> list[tuple[str, str]]:
    from sidecar import map_icons

    x0, y0 = viewport["x0"], viewport["y0"]
    vw, vh = viewport["width"], viewport["height"]
    seen: dict[str, str] = {}
    for vy in range(vh):
        for vx in range(vw):
            plot = plot_index.get((x0 + vx, y0 + vy))
            if not isinstance(plot, dict):
                continue
            resource_id = plot.get("resource_id")
            if not isinstance(resource_id, str) or not resource_id.strip():
                continue
            slug = map_icons.resource_icon_slug(resource_id)
            if not slug:
                continue
            label = resource_id.replace("RESOURCE_", "").replace("_", " ").lower()
            seen[label] = slug
    return [(slug, label) for label, slug in sorted(seen.items())]


def viewport_has_river_edges(
    plot_index: dict[tuple[int, int], dict[str, Any]],
    viewport: dict[str, int],
) -> bool:
    x0, y0 = viewport["x0"], viewport["y0"]
    vw, vh = viewport["width"], viewport["height"]
    for vy in range(vh):
        for vx in range(vw):
            plot = plot_index.get((x0 + vx, y0 + vy))
            if isinstance(plot, dict) and plot.get("river_edges"):
                return True
    return False


def _center_icon_offset(tile_px: int, icon_px: int) -> tuple[int, int]:
    return ((tile_px - icon_px) // 2, (tile_px - icon_px) // 2)


def _stack_unit_count(stack: dict[str, Any]) -> int:
    return max(1, int(stack.get("unit_count", stack.get("count", 1))))


def build_tile_markers(snapshot: dict[str, Any], viewport: dict[str, int]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """Queue city/unit/stack markers per viewport tile; stacks subsume duplicate unit icons."""
    known_map = snapshot.get("known_map", {})
    x0, y0 = viewport["x0"], viewport["y0"]
    vw, vh = viewport["width"], viewport["height"]
    player_id = str(snapshot.get("decision", {}).get("player_id", ""))
    tile_markers: dict[tuple[int, int], list[dict[str, Any]]] = {}

    def _queue_marker(vx: int, vy: int, kind: str, **payload: Any) -> None:
        if 0 <= vx < vw and 0 <= vy < vh:
            tile_markers.setdefault((vx, vy), []).append({"kind": kind, **payload})

    stack_by_plot: dict[tuple[int, int], dict[str, Any]] = {}
    for stack in known_map.get("visible_stacks", []):
        if not isinstance(stack, dict):
            continue
        coords = _parse_plot_coords(stack.get("plot_id"))
        if coords is not None:
            stack_by_plot[coords] = stack

    unit_plots: set[tuple[int, int]] = set()
    for unit in snapshot.get("your_units", []) + snapshot.get("visible_other_units", []):
        if isinstance(unit, dict):
            coords = _parse_plot_coords(unit.get("plot_id"))
            if coords is not None:
                unit_plots.add(coords)

    for coords, stack in stack_by_plot.items():
        if _stack_unit_count(stack) > 1:
            _queue_marker(
                coords[0] - x0, coords[1] - y0, "stack",
                count=stack.get("unit_count", stack.get("count", "")),
            )

    for city in snapshot.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        coords = _parse_plot_coords(city.get("plot_id"))
        if coords is None:
            continue
        _queue_marker(
            coords[0] - x0, coords[1] - y0, "city",
            is_capital=bool(city.get("is_capital")),
            name=str(city.get("name", city.get("city_id", "City")))[:16],
            population=city.get("population"),
        )

    def _stack_suppresses_unit(coords: tuple[int, int]) -> bool:
        stack = stack_by_plot.get(coords)
        return stack is not None and _stack_unit_count(stack) > 1

    for unit in snapshot.get("your_units", []):
        if not isinstance(unit, dict):
            continue
        coords = _parse_plot_coords(unit.get("plot_id"))
        if coords is None or _stack_suppresses_unit(coords):
            continue
        _queue_marker(
            coords[0] - x0, coords[1] - y0, "unit",
            unit_type_id=str(unit.get("unit_type_id", "UNIT")),
            foreign=False,
        )

    for unit in snapshot.get("visible_other_units", []):
        if not isinstance(unit, dict):
            continue
        coords = _parse_plot_coords(unit.get("plot_id"))
        if coords is None or _stack_suppresses_unit(coords):
            continue
        _queue_marker(
            coords[0] - x0, coords[1] - y0, "unit",
            unit_type_id=str(unit.get("unit_type_id", "UNIT")),
            foreign=True,
        )

    for coords, stack in stack_by_plot.items():
        if _stack_unit_count(stack) > 1 or coords in unit_plots:
            continue
        type_mix = stack.get("type_mix_ids", [])
        unit_type = str(type_mix[0]) if type_mix else "UNIT"
        owner = str(stack.get("owner_player_id", ""))
        foreign = bool(player_id and owner and owner != player_id)
        _queue_marker(
            coords[0] - x0, coords[1] - y0, "unit",
            unit_type_id=unit_type,
            foreign=foreign,
        )

    return tile_markers


def _dim_hex(hex_color: str) -> str:
    if not hex_color.startswith("#") or len(hex_color) != 7:
        return hex_color
    r = int(hex_color[1:3], 16) // 2
    g = int(hex_color[3:5], 16) // 2
    b = int(hex_color[5:7], 16) // 2
    return f"#{r:02x}{g:02x}{b:02x}"


def _grid_char_at(
    normalized: list[str] | None,
    x: int,
    y: int,
    origin: tuple[int, int] = (0, 0),
) -> str | None:
    if normalized is None:
        return None
    gx = x - origin[0]
    gy = y - origin[1]
    if gy < 0 or gy >= len(normalized) or gx < 0:
        return None
    row = normalized[gy]
    if gx >= len(row):
        return None
    return row[gx]


def model_image_suffix() -> str:
    return ".map.png"


def model_image_mime() -> str:
    return MODEL_IMAGE_MIME


def _rgb_tuple(hex_color: str) -> tuple[int, int, int]:
    return _hex_to_rgb(hex_color)


def _paste_image_raster(
    canvas: Any,
    image_path: Path,
    x: int,
    y: int,
    size: int,
) -> None:
    from PIL import Image

    icon = Image.open(image_path).convert("RGBA")
    if icon.size != (size, size):
        icon = icon.resize((size, size), Image.Resampling.LANCZOS)
    canvas.paste(icon, (x, y), icon)


def _paste_image_raster_fit(
    canvas: Any,
    image_path: Path,
    cx: float,
    cy: float,
    width: int,
    height: int,
) -> None:
    from PIL import Image

    icon = Image.open(image_path).convert("RGBA")
    target = (max(1, width), max(1, height))
    if icon.size != target:
        icon = icon.resize(target, Image.Resampling.LANCZOS)
    x = int(cx - target[0] / 2)
    y = int(cy - target[1] / 2)
    canvas.paste(icon, (x, y), icon)


def _paste_icon_raster(
    canvas: Any,
    slug: str,
    x: int,
    y: int,
    size: int,
    tint_rgb: tuple[int, int, int] | None = None,
) -> None:
    path = map_icons.icon_path(slug, tint_rgb=tint_rgb)
    if path.is_file():
        _paste_image_raster(canvas, path, x, y, size)


def _strategic_sprite_path(
    plot: dict[str, Any] | None,
    prefer_civ5_sprites: bool = False,
) -> Path | None:
    if not isinstance(plot, dict):
        return None
    if prefer_civ5_sprites:
        try:
            from sidecar import civ5_assets

            if civ5_assets.assets_available():
                path = civ5_assets.strategic_png_path(plot)
                if path is not None:
                    return path
        except ImportError:
            pass
        return None
    try:
        from sidecar import civ5_assets

        if civ5_assets.assets_available():
            path = civ5_assets.strategic_png_path(plot)
            if path is not None:
                return path
    except ImportError:
        pass
    try:
        from sidecar import civ6_assets

        if civ6_assets.assets_available():
            return civ6_assets.strategic_png_path(plot)
    except ImportError:
        pass
    return None


def _paste_strategic_square(canvas: Any, plot: dict[str, Any] | None, px: int, py: int, tile_px: int) -> bool:
    sprite_path = _strategic_sprite_path(plot)
    if sprite_path is None:
        return False
    margin = max(1, tile_px // 8)
    size = tile_px - 2 * margin
    _paste_image_raster_fit(canvas, sprite_path, px + tile_px / 2, py + tile_px / 2, size, size)
    return True


def _paste_resource_corner(canvas: Any, plot: dict[str, Any] | None, px: int, py: int, tile_px: int) -> None:
    if not isinstance(plot, dict):
        return
    resource_id = plot.get("resource_id")
    if not isinstance(resource_id, str) or not resource_id.strip():
        return
    slug = map_icons.resource_icon_slug(resource_id)
    if not slug:
        return
    icon_px = max(6, tile_px // 3)
    ox = px + tile_px - icon_px - 1
    oy = py + 1
    _paste_icon_raster(canvas, slug, ox, oy, icon_px)


def _letterbox_model_image(image: Any, target_size: int | None = None) -> Any:
    """Scale the rendered minimap to a fixed square canvas for vision APIs."""
    from PIL import Image

    target = target_size or MODEL_IMAGE_SIZE
    work = image.convert("RGBA")
    scale = min(target / work.width, target / work.height)
    new_w = max(1, int(work.width * scale))
    new_h = max(1, int(work.height * scale))
    resized = work.resize((new_w, new_h), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (target, target), _rgb_tuple("#121218") + (255,))
    out.paste(resized, ((target - new_w) // 2, (target - new_h) // 2), resized)
    return out


def encode_model_image_bytes(image: Any, *, target_size: int | None = None) -> tuple[bytes, str]:
    """Encode a fixed-size PNG for LLM vision APIs."""
    import io

    buf = io.BytesIO()
    _letterbox_model_image(image, target_size=target_size).save(buf, format="PNG", optimize=True)
    return buf.getvalue(), MODEL_IMAGE_MIME


def model_image_data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def render_known_map_model_image(
    snapshot: dict[str, Any],
    path: Path | None = None,
    tile_px: int | None = None,
    viewport_pad: int = DEFAULT_VIEWPORT_PAD,
) -> dict[str, Any]:
    """Rasterize the minimap for LLM vision APIs (PNG/JPEG); SVG remains the archive format."""
    from PIL import Image, ImageDraw, ImageFont

    from sidecar import pipeline_v2 as pipeline

    if tile_px is None:
        tile_px = resolve_map_tile_px()
    pipeline.ensure_known_map_plots(snapshot)
    plot_index = build_render_plot_index(snapshot)
    viewport = compute_viewport(snapshot, plot_index, pad=viewport_pad)
    known_map = snapshot.get("known_map", {})
    game = snapshot.get("game", {})
    map_width = int(game.get("map_width"))
    map_height = int(game.get("map_height"))
    x0, y0 = viewport["x0"], viewport["y0"]
    vw, vh = viewport["width"], viewport["height"]
    tile_px = _effective_tile_px(tile_px, vw, vh)
    show_axis_labels, show_tile_coord_labels = _coord_label_flags(vw, vh)
    axis_font = _axis_label_font(tile_px, x0, y0, vw, vh)
    axis_gutter = _axis_gutter_size(axis_font) if show_axis_labels else 0
    cell_font, legend_font, legend_swatch, legend_icon, legend_height = _scaled_fonts(tile_px)
    normalized = _normalize_visibility_grid(
        known_map.get("visibility_grid") if isinstance(known_map.get("visibility_grid"), list) else [],
        map_width, map_height,
    )
    map_w = vw * tile_px
    map_h = vh * tile_px
    canvas_w = axis_gutter + map_w
    canvas_h = axis_gutter + map_h
    tile_markers = build_tile_markers(snapshot, viewport)
    owner_index = build_territory_owner_index(snapshot, plot_index)
    territory_owners = _territory_owners_in_viewport(owner_index, viewport)
    font = ImageFont.load_default()
    axis_label_font = _load_bitmap_font(axis_font)
    terrain_items, terrain_strip_h = _layout_legend_items(
        TERRAIN_LEGEND, canvas_w, legend_font, legend_swatch, font,
    )
    territory_labels = [
        (_player_label(snapshot, player_id), _player_color(player_id))
        for player_id in territory_owners
    ]
    territory_items, territory_strip_h = _layout_legend_items(
        territory_labels, canvas_w, legend_font, legend_swatch, font,
    ) if territory_labels else ([], 0)
    icon_slugs = map_icons.legend_icon_slugs()
    icon_row_h = (legend_icon + LEGEND_HEADER_GAP) if icon_slugs else 0
    viewport_header_h = legend_font + LEGEND_HEADER_GAP
    legend_strip_h = viewport_header_h + terrain_strip_h
    if territory_items:
        legend_strip_h += LEGEND_HEADER_GAP + territory_strip_h
    legend_strip_h += icon_row_h + 4
    total_h = canvas_h + legend_strip_h

    canvas = Image.new("RGBA", (canvas_w, total_h), _rgb_tuple("#121218") + (255,))
    draw = ImageDraw.Draw(canvas)

    if show_axis_labels:
        for vx in range(vw):
            wx = x0 + vx
            cx = axis_gutter + vx * tile_px + tile_px // 2
            draw.text((cx, axis_gutter // 2), str(wx), fill="#999999", font=axis_label_font, anchor="mm")
        for vy in range(vh):
            wy = y0 + vy
            cy = axis_gutter + vy * tile_px + tile_px // 2
            draw.text((axis_gutter - 2, cy), str(wy), fill="#999999", font=axis_label_font, anchor="rm")

    rendered_tiles = 0
    has_visibility_grid = normalized is not None
    grid_origin = visibility_grid_origin(known_map if isinstance(known_map, dict) else None)
    border_segments: list[tuple[int, int, int, int, str]] = []
    border_width = max(1, int(tile_px / 10))
    for vy in range(vh):
        world_y = y0 + vy
        for vx in range(vw):
            world_x = x0 + vx
            key = (world_x, world_y)
            plot = plot_index.get(key)
            grid_char = _grid_char_at(normalized, world_x, world_y, origin=grid_origin)
            state = _tile_terrain_state(plot, grid_char, has_visibility_grid)
            territory_owner = owner_index.get(key) if state == "revealed" else None
            fill = _tile_fill(plot, grid_char, state, territory_owner)
            if state == "revealed":
                rendered_tiles += 1
            px = axis_gutter + vx * tile_px
            py = axis_gutter + vy * tile_px
            draw.rectangle((px, py, px + tile_px - 1, py + tile_px - 1), fill=_rgb_tuple(fill), outline="#333333")
            if state == "revealed" and plot is not None:
                _paste_strategic_square(canvas, plot, px, py, tile_px)
                _paste_resource_corner(canvas, plot, px, py, tile_px)
            if territory_owner is not None:
                border_segments.extend(
                    _owner_border_segments(world_x, world_y, territory_owner, owner_index, px, py, tile_px)
                )
            if show_tile_coord_labels and state == "revealed":
                coord_font = _coord_font_size(tile_px, world_x, world_y)
                label_color = _cell_label_color(fill)
                draw.text(
                    (px + tile_px // 2, py + tile_px - 2),
                    f"{world_x},{world_y}",
                    fill=label_color,
                    font=_coord_label_font(coord_font),
                    anchor="ms",
                )

    for x1, y1, x2, y2, stroke in border_segments:
        draw.line((x1, y1, x2, y2), fill=_rgb_tuple(stroke), width=border_width)

    for (vx, vy), markers in sorted(tile_markers.items(), key=lambda item: (item[0][1], item[0][0])):
        px = axis_gutter + vx * tile_px
        py = axis_gutter + vy * tile_px
        cities = [m for m in markers if m.get("kind") == "city"]
        others = [m for m in markers if m.get("kind") != "city"]
        other_icon_px = map_icons.icon_px_for_tile(tile_px, len(others))
        for index, marker in enumerate(others):
            ox, oy = map_icons.tile_slot_offsets(tile_px, other_icon_px, index, len(others))
            ix, iy = px + ox, py + oy
            kind = marker.get("kind")
            if kind == "stack":
                _paste_icon_raster(canvas, "stack", ix, iy, other_icon_px)
            elif kind == "unit":
                foreign = bool(marker.get("foreign"))
                slug = "unit_foreign" if foreign else map_icons.icon_slug_for_unit(str(marker.get("unit_type_id", "UNIT")))
                _paste_icon_raster(canvas, slug, ix, iy, other_icon_px)
                if foreign:
                    draw.rectangle(
                        (ix, iy, ix + other_icon_px - 1, iy + other_icon_px - 1),
                        outline="#ff4444",
                        width=1,
                    )
        for marker in cities:
            city_icon_px = map_icons.icon_px_for_tile(tile_px, 1)
            ox, oy = _center_icon_offset(tile_px, city_icon_px)
            slug = "capital" if marker.get("is_capital") else "city"
            _paste_icon_raster(canvas, slug, px + ox, py + oy, city_icon_px)

    draw.line((0, canvas_h, canvas_w, canvas_h), fill="#444444", width=1)
    ly_header = canvas_h + 6
    draw.text((4, ly_header), f"viewport x0={x0} y0={y0} {vw}x{vh}", fill="#cccccc", font=font)
    legend_y = ly_header + viewport_header_h
    for lx, ly_row, label, color in terrain_items:
        row_y = legend_y + ly_row
        draw.rectangle(
            (lx, row_y - legend_swatch, lx + legend_swatch, row_y),
            fill=_rgb_tuple(color), outline="#555555",
        )
        draw.text((lx + legend_swatch + 3, row_y), label, fill="#bbbbbb", font=font, anchor="ls")
    legend_y += terrain_strip_h
    if territory_items:
        legend_y += LEGEND_HEADER_GAP
        for lx, ly_row, label, color in territory_items:
            row_y = legend_y + ly_row
            draw.rectangle(
                (lx, row_y - legend_swatch, lx + legend_swatch, row_y),
                fill=_rgb_tuple(color), outline="#555555",
            )
            draw.text((lx + legend_swatch + 3, row_y), label, fill="#bbbbbb", font=font, anchor="ls")
        legend_y += territory_strip_h
    if icon_slugs:
        legend_y += LEGEND_HEADER_GAP
        lx = 4
        ly_row = legend_y
        for slug, meaning in icon_slugs:
            url = map_icons.icon_data_url(slug)
            if url:
                _paste_icon_raster(canvas, slug, lx, ly_row - legend_icon, legend_icon)
                draw.text(
                    (lx + legend_icon + 3, ly_row), meaning,
                    fill="#bbbbbb", font=font, anchor="ls",
                )
                lx += _legend_item_width(meaning, legend_font, legend_icon, font)
                if lx > canvas_w - 50:
                    lx = 4
                    ly_row += legend_icon + LEGEND_HEADER_GAP

    raw, mime = encode_model_image_bytes(canvas)
    digest = hashlib.sha256(raw).hexdigest()
    meta: dict[str, Any] = {
        "format": "png-grid-v2",
        "mime_type": mime,
        "sha256": digest,
        "width": MODEL_IMAGE_SIZE,
        "height": MODEL_IMAGE_SIZE,
        "source_width": canvas_w,
        "source_height": total_h,
        "tile_px": tile_px,
        "viewport": viewport,
        "rendered_tiles": rendered_tiles,
        "known_plot_tiles": len(plot_index),
        "show_axis_labels": show_axis_labels,
        "show_tile_coord_labels": show_tile_coord_labels,
        "show_coord_labels": show_tile_coord_labels,
        "image_bytes": len(raw),
        "data_url": model_image_data_url(raw, mime),
    }
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        meta["path"] = str(path)
    return meta


def render_known_map_svg(
    snapshot: dict[str, Any],
    path: Path | None = None,
    tile_px: int | None = None,
    viewport_pad: int = DEFAULT_VIEWPORT_PAD,
) -> dict[str, Any]:
    """Render cropped minimap SVG; optionally write to path."""
    from sidecar import pipeline_v2 as pipeline

    if tile_px is None:
        tile_px = resolve_map_tile_px()
    pipeline.ensure_known_map_plots(snapshot)
    plot_index = build_render_plot_index(snapshot)
    viewport = compute_viewport(snapshot, plot_index, pad=viewport_pad)
    known_map = snapshot.get("known_map", {})
    game = snapshot.get("game", {})
    map_width = int(game.get("map_width"))
    map_height = int(game.get("map_height"))
    x0, y0 = viewport["x0"], viewport["y0"]
    vw, vh = viewport["width"], viewport["height"]
    tile_px = _effective_tile_px(tile_px, vw, vh)
    show_axis_labels, show_tile_coord_labels = _coord_label_flags(vw, vh)
    axis_font = _axis_label_font(tile_px, x0, y0, vw, vh)
    axis_gutter = _axis_gutter_size(axis_font) if show_axis_labels else 0
    cell_font, legend_font, legend_swatch, legend_icon, legend_height = _scaled_fonts(tile_px)
    normalized = _normalize_visibility_grid(
        known_map.get("visibility_grid") if isinstance(known_map.get("visibility_grid"), list) else [],
        map_width, map_height,
    )
    map_w = vw * tile_px
    map_h = vh * tile_px
    canvas_w = axis_gutter + map_w
    canvas_h = axis_gutter + map_h
    tile_markers = build_tile_markers(snapshot, viewport)
    owner_index = build_territory_owner_index(snapshot, plot_index)
    territory_owners = _territory_owners_in_viewport(owner_index, viewport)
    terrain_items, terrain_strip_h = _layout_legend_items(
        TERRAIN_LEGEND, canvas_w, legend_font, legend_swatch,
    )
    territory_labels = [
        (_player_label(snapshot, player_id), _player_color(player_id))
        for player_id in territory_owners
    ]
    territory_items, territory_strip_h = _layout_legend_items(
        territory_labels, canvas_w, legend_font, legend_swatch,
    ) if territory_labels else ([], 0)
    icon_slugs = map_icons.legend_icon_slugs()
    icon_row_h = (legend_icon + LEGEND_HEADER_GAP) if icon_slugs else 0
    viewport_header_h = legend_font + LEGEND_HEADER_GAP
    legend_strip_h = viewport_header_h + terrain_strip_h
    if territory_items:
        legend_strip_h += LEGEND_HEADER_GAP + territory_strip_h
    legend_strip_h += icon_row_h + 4
    total_h = canvas_h + legend_strip_h

    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{canvas_w}" height="{total_h}" viewBox="0 0 {canvas_w} {total_h}">',
        f'<rect width="{canvas_w}" height="{total_h}" fill="#121218"/>',
    ]
    if show_axis_labels:
        axis_y = max(1, axis_gutter - 2)
        for vx in range(vw):
            wx = x0 + vx
            cx = axis_gutter + vx * tile_px + tile_px // 2
            parts.append(
                f'<text x="{cx}" y="{axis_y}" text-anchor="middle" '
                f'font-family="Arial" font-size="{axis_font}" fill="#999">{wx}</text>'
            )
        for vy in range(vh):
            wy = y0 + vy
            cy = axis_gutter + vy * tile_px + tile_px // 2 + 1
            parts.append(
                f'<text x="{axis_gutter - 2}" y="{cy}" text-anchor="end" '
                f'font-family="Arial" font-size="{axis_font}" fill="#999">{wy}</text>'
            )

    rendered_tiles = 0
    has_visibility_grid = normalized is not None
    tile_coord_labels: list[tuple[int, int, int, str, str]] = []
    border_segments: list[tuple[int, int, int, int, str]] = []
    border_width = max(1.0, tile_px / 10)
    for vy in range(vh):
        world_y = y0 + vy
        for vx in range(vw):
            world_x = x0 + vx
            key = (world_x, world_y)
            plot = plot_index.get(key)
            grid_char = _grid_char_at(normalized, world_x, world_y, origin=visibility_grid_origin(known_map if isinstance(known_map, dict) else None))
            state = _tile_terrain_state(plot, grid_char, has_visibility_grid)
            territory_owner = owner_index.get(key) if state == "revealed" else None
            fill = _tile_fill(plot, grid_char, state, territory_owner)
            if state == "revealed":
                rendered_tiles += 1
            px = axis_gutter + vx * tile_px
            py = axis_gutter + vy * tile_px
            parts.append(
                f'<rect x="{px}" y="{py}" width="{tile_px}" height="{tile_px}" '
                f'fill="{fill}" stroke="#333" stroke-width="0.5"/>'
            )
            if territory_owner is not None:
                border_segments.extend(
                    _owner_border_segments(world_x, world_y, territory_owner, owner_index, px, py, tile_px)
                )
            if show_tile_coord_labels and state == "revealed":
                coord_font = _coord_font_size(tile_px, world_x, world_y)
                tile_coord_labels.append(
                    (px, py, coord_font, _cell_label_color(fill), f"{world_x},{world_y}")
                )

    for x1, y1, x2, y2, stroke in border_segments:
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{stroke}" stroke-width="{border_width}" stroke-linecap="square"/>'
        )

    for (vx, vy), markers in sorted(tile_markers.items(), key=lambda item: (item[0][1], item[0][0])):
        px = axis_gutter + vx * tile_px
        py = axis_gutter + vy * tile_px
        cities = [m for m in markers if m.get("kind") == "city"]
        others = [m for m in markers if m.get("kind") != "city"]
        other_icon_px = map_icons.icon_px_for_tile(tile_px, len(others))
        for index, marker in enumerate(others):
            ox, oy = map_icons.tile_slot_offsets(tile_px, other_icon_px, index, len(others))
            ix, iy = px + ox, py + oy
            kind = marker.get("kind")
            if kind == "stack":
                url = map_icons.stack_icon_data_url()
                if url:
                    parts.append(map_icons.svg_image_tag(ix, iy, other_icon_px, url))
            elif kind == "unit":
                url = map_icons.unit_icon_data_url(marker.get("unit_type_id", "UNIT"), bool(marker.get("foreign")))
                if url:
                    parts.append(map_icons.svg_image_tag(ix, iy, other_icon_px, url))
                if marker.get("foreign"):
                    parts.append(map_icons.svg_foreign_tint(ix, iy, other_icon_px))
        for marker in cities:
            city_icon_px = map_icons.icon_px_for_tile(tile_px, 1)
            ox, oy = _center_icon_offset(tile_px, city_icon_px)
            ix, iy = px + ox, py + oy
            url = map_icons.city_icon_data_url(bool(marker.get("is_capital")))
            if url:
                parts.append(map_icons.svg_image_tag(ix, iy, city_icon_px, url))

    for px, py, coord_font, label_color, coord_label in tile_coord_labels:
        parts.append(
            f'<text x="{px + tile_px // 2}" y="{py + tile_px - 2}" text-anchor="middle" '
            f'font-family="Arial" font-size="{coord_font}" fill="{label_color}">'
            f'{_svg_text(coord_label)}</text>'
        )

    parts.append(
        f'<line x1="0" y1="{canvas_h}" x2="{canvas_w}" y2="{canvas_h}" stroke="#444" stroke-width="1"/>'
    )
    ly_header = canvas_h + 6
    viewport_note = f"viewport x0={x0} y0={y0} {vw}x{vh}"
    parts.append(
        f'<text x="4" y="{ly_header + legend_font}" font-family="Arial" font-size="{legend_font + 1}" fill="#ccc">'
        f'{_svg_text(viewport_note)}</text>'
    )
    legend_y = ly_header + viewport_header_h
    for lx, ly_row, label, color in terrain_items:
        row_y = legend_y + ly_row
        parts.append(
            f'<rect x="{lx}" y="{row_y - legend_swatch}" width="{legend_swatch}" height="{legend_swatch}" '
            f'fill="{color}" stroke="#555"/>'
        )
        parts.append(
            f'<text x="{lx + legend_swatch + 3}" y="{row_y}" font-family="Arial" font-size="{legend_font}" '
            f'fill="#bbb">{_svg_text(label)}</text>'
        )
    legend_y += terrain_strip_h
    if territory_items:
        legend_y += LEGEND_HEADER_GAP
        for lx, ly_row, label, color in territory_items:
            row_y = legend_y + ly_row
            parts.append(
                f'<rect x="{lx}" y="{row_y - legend_swatch}" width="{legend_swatch}" height="{legend_swatch}" '
                f'fill="{color}" stroke="#555"/>'
            )
            parts.append(
                f'<text x="{lx + legend_swatch + 3}" y="{row_y}" font-family="Arial" font-size="{legend_font}" '
                f'fill="#bbb">{_svg_text(label)}</text>'
            )
        legend_y += territory_strip_h
    if icon_slugs:
        legend_y += LEGEND_HEADER_GAP
        lx = 4
        ly_row = legend_y
        for slug, meaning in icon_slugs:
            url = map_icons.icon_data_url(slug)
            if url:
                parts.append(map_icons.svg_image_tag(lx, ly_row - legend_icon, legend_icon, url))
                parts.append(
                    f'<text x="{lx + legend_icon + 3}" y="{ly_row}" font-family="Arial" font-size="{legend_font}" '
                    f'fill="#bbb">{_svg_text(meaning)}</text>'
                )
                lx += _legend_item_width(meaning, legend_font, legend_icon)
                if lx > canvas_w - 50:
                    lx = 4
                    ly_row += legend_icon + LEGEND_HEADER_GAP
    parts.append("</svg>")
    svg = "".join(parts)
    digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()
    legend = [
        {"symbol": slug, "meaning": meaning}
        for slug, meaning in map_icons.legend_icon_slugs()
    ] + [
        {"symbol": _player_color(player_id), "meaning": f"{_player_label(snapshot, player_id)} territory"}
        for player_id in territory_owners
    ] + [
        {"symbol": "black", "meaning": "unexplored"},
    ]
    meta: dict[str, Any] = {
        "format": "svg-grid-v2",
        "sha256": digest,
        "width": canvas_w,
        "height": total_h,
        "tile_px": tile_px,
        "viewport": viewport,
        "rendered_tiles": rendered_tiles,
        "known_plot_tiles": len(plot_index),
        "show_axis_labels": show_axis_labels,
        "show_tile_coord_labels": show_tile_coord_labels,
        "show_coord_labels": show_tile_coord_labels,
        "svg_bytes": len(svg.encode("utf-8")),
        "legend": legend,
        "data_url": "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii"),
    }
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")
        meta["path"] = str(path)
    image = snapshot.setdefault("known_map", {}).setdefault("image", {})
    if isinstance(image, dict):
        image["format"] = meta["format"]
        image["width"] = meta["width"]
        image["height"] = meta["height"]
        image["tile_px"] = tile_px
        image["viewport"] = viewport
        image["sha256"] = digest
        image["rendered_tiles"] = rendered_tiles
        image["show_axis_labels"] = show_axis_labels
        image["show_tile_coord_labels"] = show_tile_coord_labels
        image["show_coord_labels"] = show_tile_coord_labels
        image["legend"] = legend
    return meta
