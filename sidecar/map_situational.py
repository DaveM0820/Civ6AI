"""Situational map images for Civ V: overview, main tactical, and optional 6x6 focus."""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from typing import Any

from sidecar import map_render
from sidecar.map_render_civ6 import HEX_AXIS_ONLY_MIN_CELLS, render_civ6_map_png

STRATEGIC_MAP_BANNER = "Civ 5 strategic map"
TACTICAL_MAP_BANNER = "Civ 5 tactical map"
FOCUS_TACTICAL_MAP_BANNER = "Civ 5 focus tactical 6x6"
CIV6_STRATEGIC_MAP_BANNER = "Civ 6 strategic map"
CIV6_TACTICAL_MAP_BANNER = "Civ 6 tactical map"
CIV6_FOCUS_TACTICAL_MAP_BANNER = "Civ 6 focus tactical 6x6"

VIEWPORT_AGENT_STALE_TURNS = 20
TACTICAL_OVERLAP_OMIT_THRESHOLD = 0.90
TACTICAL_SIMILAR_SIZE_RATIO = 1.25
FOCUS_TACTICAL_VIEWPORT_SIZE = 6
FOCUS_COVERED_BY_MAIN_THRESHOLD = 0.90


def viewport_area(viewport: dict[str, Any]) -> int:
    return max(0, int(viewport.get("width", 0) or 0)) * max(0, int(viewport.get("height", 0) or 0))


def viewport_overlap_fraction(inner: dict[str, Any], outer: dict[str, Any]) -> float:
    """Share of inner's area that lies inside outer."""
    ix0 = int(inner.get("x0", 0) or 0)
    iy0 = int(inner.get("y0", 0) or 0)
    iw = int(inner.get("width", 0) or 0)
    ih = int(inner.get("height", 0) or 0)
    ox0 = int(outer.get("x0", 0) or 0)
    oy0 = int(outer.get("y0", 0) or 0)
    ow = int(outer.get("width", 0) or 0)
    oh = int(outer.get("height", 0) or 0)
    x0 = max(ix0, ox0)
    y0 = max(iy0, oy0)
    x1 = min(ix0 + iw, ox0 + ow)
    y1 = min(iy0 + ih, oy0 + oh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inner_area = max(1, iw * ih)
    return (x1 - x0) * (y1 - y0) / inner_area


def viewport_shows_tile_coords(viewport: dict[str, Any]) -> bool:
    from sidecar.map_render_civ6 import _hex_coord_label_flags

    width = int(viewport.get("width", 0) or 0)
    height = int(viewport.get("height", 0) or 0)
    _, show_tile = _hex_coord_label_flags(width, height)
    return show_tile


def should_omit_tactical_map(
    overview: dict[str, Any],
    tactical: dict[str, Any],
) -> tuple[bool, str]:
    """Skip redundant tactical image when strategic already shows detail."""
    if viewport_shows_tile_coords(overview):
        return True, "strategic_tile_coords"
    overlap = viewport_overlap_fraction(tactical, overview)
    if overlap >= TACTICAL_OVERLAP_OMIT_THRESHOLD:
        overview_area = viewport_area(overview)
        tactical_area = max(1, viewport_area(tactical))
        if overview_area <= tactical_area * TACTICAL_SIMILAR_SIZE_RATIO:
            return True, "overlaps_strategic"
    return False, ""


def tactical_map_attached(snapshot: dict[str, Any]) -> bool:
    advciv = snapshot.get("advciv", {})
    if not isinstance(advciv, dict):
        return True
    manifest = advciv.get("map_images", [])
    if not isinstance(manifest, list) or not manifest:
        return True
    return any(isinstance(item, dict) and item.get("role") == "viewport" for item in manifest)


def focus_map_attached(snapshot: dict[str, Any]) -> bool:
    advciv = snapshot.get("advciv", {})
    if not isinstance(advciv, dict):
        return False
    manifest = advciv.get("map_images", [])
    if not isinstance(manifest, list):
        return False
    return any(isinstance(item, dict) and item.get("role") == "focus" for item in manifest)


def format_strategic_window(viewport: dict[str, Any], map_width: int, map_height: int) -> str:
    """Human-readable crop vs full map, e.g. '(39,25)-(54,41) of 80x52 (8%)'."""
    x0 = int(viewport.get("x0") or 0)
    y0 = int(viewport.get("y0") or 0)
    width = max(1, int(viewport.get("width") or 1))
    height = max(1, int(viewport.get("height") or 1))
    x1 = x0 + width - 1
    y1 = y0 + height - 1
    total = max(1, int(map_width) * int(map_height))
    pct = max(1, min(100, int(round(100.0 * (width * height) / total))))
    return f"({x0},{y0})-({x1},{y1}) of {int(map_width)}x{int(map_height)} ({pct}%)"


def map_images_manifest(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Manifest of attached situational map images (overview / viewport / focus)."""
    advciv = snapshot.get("advciv")
    if isinstance(advciv, dict):
        manifest = advciv.get("map_images")
        if isinstance(manifest, list) and manifest:
            return [item for item in manifest if isinstance(item, dict)]
    known = snapshot.get("known_map")
    if isinstance(known, dict):
        images = known.get("images")
        if isinstance(images, list) and images:
            return [item for item in images if isinstance(item, dict)]
    return []


def overview_viewport_from_snapshot(snapshot: dict[str, Any]) -> dict[str, int] | None:
    known = snapshot.get("known_map")
    if isinstance(known, dict):
        image = known.get("image")
        if isinstance(image, dict) and isinstance(image.get("viewport"), dict):
            return image["viewport"]
        images = known.get("images")
        if isinstance(images, list):
            for item in images:
                if isinstance(item, dict) and item.get("role") == "overview" and isinstance(item.get("viewport"), dict):
                    return item["viewport"]
    advciv = snapshot.get("advciv")
    if isinstance(advciv, dict):
        for item in advciv.get("map_images") or []:
            if isinstance(item, dict) and item.get("role") == "overview" and isinstance(item.get("viewport"), dict):
                return item["viewport"]
    return None


def strategic_scale_wire_lines(snapshot: dict[str, Any]) -> list[str]:
    map_width, map_height = _map_dimensions(snapshot)
    lines = [
        f"map.world.width = {map_width}",
        f"map.world.height = {map_height}",
    ]
    manifest = map_images_manifest(snapshot)
    role_wire_prefix = {
        "overview": "map.strategic",
        "viewport": "map.tactical",
        "focus": "map.focus",
    }
    if manifest:
        overview_meta: dict[str, Any] | None = None
        for item in manifest:
            role = str(item.get("role") or "")
            if role == "overview":
                overview_meta = item
            prefix = role_wire_prefix.get(role)
            if not prefix:
                continue
            viewport = item.get("viewport")
            if isinstance(viewport, dict):
                lines.append(
                    f"{prefix}.window = " + format_strategic_window(viewport, map_width, map_height)
                )
            detail = item.get("detail")
            if isinstance(detail, str) and detail.strip():
                lines.append(f"{prefix}.detail = {detail}")
            image_size = item.get("image_size")
            if isinstance(image_size, int) and image_size > 0:
                lines.append(f"{prefix}.image_size = {image_size}px")
            if role == "viewport" and "auto" in item:
                lines.append(f"{prefix}.auto = {str(bool(item.get('auto'))).lower()}")
        if isinstance(overview_meta, dict):
            if overview_meta.get("tactical_omitted"):
                reason = str(overview_meta.get("tactical_omit_reason") or "true")
                lines.append(f"map.tactical.omitted = {reason}")
            if overview_meta.get("focus_omitted"):
                reason = str(overview_meta.get("focus_omit_reason") or "true")
                lines.append(f"map.focus.omitted = {reason}")
        return lines
    viewport = overview_viewport_from_snapshot(snapshot)
    if viewport is None:
        try:
            viewport = compute_overview_viewport(snapshot)
        except Exception:
            viewport = None
    if isinstance(viewport, dict):
        lines.append("map.strategic.window = " + format_strategic_window(viewport, map_width, map_height))
    return lines


def _stamp_map_banner(path: Path, title: str) -> None:
    """Draw a labeled bar on the image so the model can match it to prompt names.

    Soft-fails on bad/partial PNGs (writer race, torn read): log once and leave
    the unstamped map in place so the pulse continues.
    """
    import sys
    import time as _time
    from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

    image = None
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            if not path.is_file() or path.stat().st_size < 24:
                last_err = OSError(f"map image missing or too small: {path}")
            else:
                # Full load (not just open) catches truncated PNG IDAT.
                with Image.open(path) as im:
                    image = im.convert("RGBA")
                break
        except (OSError, UnidentifiedImageError, SyntaxError, ValueError) as err:
            last_err = err
            if attempt == 0:
                _time.sleep(0.05)
    if image is None:
        print(
            f"map_banner_stamp_skip path={path} err={type(last_err).__name__}: {last_err}",
            file=sys.stderr,
        )
        return
    try:
        bar_h = max(28, image.height // 22)
        canvas = Image.new("RGBA", (image.width, image.height + bar_h), (12, 10, 8, 255))
        canvas.paste(image, (0, bar_h))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, image.width, bar_h), fill=(20, 16, 12, 255))
        font = None
        for candidate in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
            try:
                font = ImageFont.truetype(candidate, max(14, bar_h - 12))
                break
            except OSError:
                continue
        if font is None:
            font = ImageFont.load_default()
        text_y = max(2, (bar_h - 16) // 2)
        draw.text((10, text_y), title, fill=(236, 220, 180, 255), font=font)
        canvas.convert("RGB").save(path)
    except (OSError, UnidentifiedImageError, SyntaxError, ValueError) as err:
        print(
            f"map_banner_stamp_skip path={path} err={type(err).__name__}: {err}",
            file=sys.stderr,
        )

def _refresh_data_url(meta: dict[str, Any], path: Path) -> None:
    import base64

    meta["data_url"] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    meta["path"] = str(path)




def _chebyshev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


def _map_dimensions(snapshot: dict[str, Any]) -> tuple[int, int]:
    game = snapshot.get("game", {})
    if not isinstance(game, dict):
        return 1, 1
    return int(game.get("map_width", 1) or 1), int(game.get("map_height", 1) or 1)


def max_tactical_viewport_size_with_coords() -> int:
    """Largest square viewport that still shows (x,y) labels on each hex."""
    return max(6, int(math.isqrt(HEX_AXIS_ONLY_MIN_CELLS - 1)))


def clamp_map_viewport(
    x0: int,
    y0: int,
    width: int,
    height: int,
    map_width: int,
    map_height: int,
) -> dict[str, int]:
    max_w = max(4, int(map_width * 0.5))
    max_h = max(4, int(map_height * 0.5))
    return map_render.clamp_viewport_to_map(
        {"x0": x0, "y0": y0, "width": width, "height": height},
        map_width,
        map_height,
        max_width=max_w,
        max_height=max_h,
    )


def viewport_centered_on_plot(
    x: int,
    y: int,
    map_width: int,
    map_height: int,
    *,
    size: int | None = None,
) -> dict[str, int]:
    tile_size = size if size is not None else max_tactical_viewport_size_with_coords()
    half = max(1, tile_size // 2)
    return clamp_map_viewport(
        x - half,
        y - half,
        tile_size,
        tile_size,
        map_width,
        map_height,
    )


def viewport_focused_on_tile(
    x: int,
    y: int,
    map_width: int,
    map_height: int,
) -> dict[str, int]:
    return viewport_centered_on_plot(
        x,
        y,
        map_width,
        map_height,
        size=max_tactical_viewport_size_with_coords(),
    )


def parse_map_focus_tile(raw: Any) -> tuple[int, int] | None:
    if isinstance(raw, dict):
        focus_x = raw.get("focus_x")
        focus_y = raw.get("focus_y")
        if focus_x is not None and focus_y is not None:
            try:
                return int(focus_x), int(focus_y)
            except (TypeError, ValueError):
                return None
        return None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    match = re.fullmatch(r"\(?\s*(-?\d+)\s*,\s*(-?\d+)\s*\)?", text)
    if not match:
        return None
    try:
        return int(match.group(1)), int(match.group(2))
    except ValueError:
        return None


def parse_named_map_focus(snapshot: dict[str, Any], raw: Any) -> tuple[int, int] | None:
    """Unit id / city name -> current plot for tactical-map pin."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or "," in text:
        return None
    from sidecar.civ5_adapter import _resolve_named_move_plot

    return _resolve_named_move_plot(snapshot, text)


def parse_map_viewport_value(raw: Any) -> dict[str, int] | None:
    """Legacy rectangle parser kept for stored memory and tests."""
    if isinstance(raw, dict):
        try:
            return {
                "x0": int(raw["x0"]),
                "y0": int(raw["y0"]),
                "width": int(raw["width"]),
                "height": int(raw["height"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    parts = [part.strip() for part in text.replace(" ", "").split(",") if part.strip()]
    if len(parts) != 4:
        return None
    try:
        x0, y0, width, height = (int(part) for part in parts)
    except ValueError:
        return None
    return {"x0": x0, "y0": y0, "width": width, "height": height}


def viewport_rect_from_stored(
    stored: dict[str, Any],
    map_width: int,
    map_height: int,
) -> dict[str, int] | None:
    focus = parse_map_focus_tile(stored)
    if focus is not None:
        return viewport_focused_on_tile(focus[0], focus[1], map_width, map_height)
    parsed = parse_map_viewport_value(stored)
    if parsed is None:
        return None
    return clamp_map_viewport(
        parsed["x0"],
        parsed["y0"],
        parsed["width"],
        parsed["height"],
        map_width,
        map_height,
    )


def normalize_stored_viewport(
    stored: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    map_width, map_height = _map_dimensions(snapshot)
    focus = parse_map_focus_tile(stored)
    if focus is not None:
        x, y = focus
        return {"focus_x": x, "focus_y": y}
    rect = parse_map_viewport_value(stored)
    if rect is None:
        return None
    clamped = clamp_map_viewport(
        rect["x0"],
        rect["y0"],
        rect["width"],
        rect["height"],
        map_width,
        map_height,
    )
    return {
        "focus_x": clamped["x0"] + clamped["width"] // 2,
        "focus_y": clamped["y0"] + clamped["height"] // 2,
    }


def _unit_plot_coords(unit: dict[str, Any]) -> tuple[int, int] | None:
    return map_render._parse_plot_coords(unit.get("plot_id"))


def _city_coords(snapshot: dict[str, Any]) -> list[tuple[int, int]]:
    coords: list[tuple[int, int]] = []
    for city in snapshot.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        parsed = map_render._parse_plot_coords(city.get("plot_id"))
        if parsed is not None:
            coords.append(parsed)
    return coords


def _capital_coords(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    for city in snapshot.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        if city.get("is_capital") is True:
            return _unit_plot_coords(city)
    cities = _city_coords(snapshot)
    return cities[0] if cities else None


def _unit_coords(snapshot: dict[str, Any], *, own: bool, military_only: bool) -> list[tuple[int, int]]:
    key = "your_units" if own else "visible_other_units"
    coords: list[tuple[int, int]] = []
    for unit in snapshot.get(key, []):
        if not isinstance(unit, dict):
            continue
        if military_only and not _is_military_unit(unit):
            continue
        parsed = map_render._parse_plot_coords(unit.get("plot_id"))
        if parsed is not None:
            coords.append(parsed)
    return coords


def _is_military_unit(unit: dict[str, Any]) -> bool:
    class_id = str(unit.get("unit_class_id", ""))
    if class_id in {
        "UNITCLASS_SETTLER", "UNITCLASS_WORKER", "UNITCLASS_WORKBOAT",
        "UNITCLASS_MISSIONARY", "UNITCLASS_INQUISITOR", "UNITCLASS_TRADER",
        "UNITCLASS_ARCHAEOLOGIST",
    }:
        return False
    type_id = str(unit.get("unit_type_id", ""))
    if type_id.startswith((
        "UNIT_SETTLER", "UNIT_WORKER", "UNIT_WORKBOAT", "UNIT_MISSIONARY",
        "UNIT_INQUISITOR", "UNIT_TRADER", "UNIT_ARCHAEOLOGIST",
        "UNIT_GREAT_",
    )):
        return False
    combat = unit.get("combat_strength")
    if isinstance(combat, int) and combat > 0:
        return True
    ranged = unit.get("ranged_combat_strength")
    if isinstance(ranged, int) and ranged > 0:
        return True
    strength = unit.get("strength")
    if isinstance(strength, dict):
        current = strength.get("current")
        if isinstance(current, int) and current > 0:
            return True
    return True


def pick_auto_explore_focus_tile(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    """Peacetime tactical focus: settler, then scout/warrior, then any owned unit."""
    settlers: list[tuple[int, int]] = []
    scouts: list[tuple[int, int]] = []
    others: list[tuple[int, int]] = []
    for unit in snapshot.get("your_units") or []:
        if not isinstance(unit, dict):
            continue
        coords = _unit_plot_coords(unit)
        if coords is None:
            continue
        utype = str(unit.get("unit_type") or unit.get("type") or "").upper()
        if "SETTLER" in utype:
            settlers.append(coords)
        elif "SCOUT" in utype or "WARRIOR" in utype:
            scouts.append(coords)
        else:
            others.append(coords)
    if settlers:
        return settlers[0]
    if scouts:
        return scouts[0]
    if others:
        return others[0]
    return None


def pick_auto_war_focus_tile(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    """Center tile for the tightest friendly/enemy contact cluster."""
    own = _unit_coords(snapshot, own=True, military_only=False)
    enemy = _unit_coords(snapshot, own=False, military_only=False)
    if not enemy:
        return None
    cluster_pts: list[tuple[int, int]] = []
    if own:
        best: tuple[tuple[int, int], list[tuple[int, int]]] | None = None
        for ox, oy in own:
            for ex, ey in enemy:
                dist = _chebyshev(ox, oy, ex, ey)
                mx, my = (ox + ex) // 2, (oy + ey) // 2
                pts = [(ox, oy), (ex, ey)]
                nearby = 0
                for px, py in own + enemy:
                    if _chebyshev(px, py, mx, my) <= 4:
                        nearby += 1
                        pts.append((px, py))
                score = (dist, -nearby)
                if best is None or score < best[0]:
                    best = (score, pts)
        if best is not None:
            cluster_pts = best[1]
    if not cluster_pts:
        cities = _city_coords(snapshot)
        if not cities:
            return enemy[0]
        best_city: tuple[int, list[tuple[int, int]]] | None = None
        for cx, cy in cities:
            nearest = min(enemy, key=lambda e: _chebyshev(cx, cy, e[0], e[1]))
            dist = _chebyshev(cx, cy, nearest[0], nearest[1])
            if best_city is None or dist < best_city[0]:
                best_city = (dist, [(cx, cy), nearest])
        cluster_pts = best_city[1] if best_city else [enemy[0]]
    cx = sum(point[0] for point in cluster_pts) // len(cluster_pts)
    cy = sum(point[1] for point in cluster_pts) // len(cluster_pts)
    return cx, cy


def _is_settler_unit(unit: dict[str, Any]) -> bool:
    class_id = str(unit.get("unit_class_id", "") or "")
    type_id = str(unit.get("unit_type_id") or unit.get("unit_type") or unit.get("type") or "")
    return class_id == "UNITCLASS_SETTLER" or "SETTLER" in type_id.upper()


def _unit_needs_orders(unit: dict[str, Any]) -> bool:
    return unit.get("needs_orders") is True or unit.get("can_act") is True


def pick_combat_contact_focus_tile(
    snapshot: dict[str, Any],
    *,
    contact_distance: int = 5,
) -> tuple[int, int] | None:
    """Midpoint of the closest own/enemy pair within contact range."""
    own = _unit_coords(snapshot, own=True, military_only=False)
    enemy = _unit_coords(snapshot, own=False, military_only=False)
    if not own or not enemy:
        return None
    best: tuple[int, tuple[int, int]] | None = None
    for ox, oy in own:
        for ex, ey in enemy:
            dist = _chebyshev(ox, oy, ex, ey)
            if dist > contact_distance:
                continue
            mid = ((ox + ex) // 2, (oy + ey) // 2)
            if best is None or dist < best[0]:
                best = (dist, mid)
    return best[1] if best is not None else None


def pick_settler_needs_orders_focus_tile(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    for unit in snapshot.get("your_units") or []:
        if not isinstance(unit, dict) or not _is_settler_unit(unit):
            continue
        if not _unit_needs_orders(unit):
            continue
        coords = _unit_plot_coords(unit)
        if coords is not None:
            return coords
    return None


def pick_military_needs_orders_focus_tile(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    for unit in snapshot.get("your_units") or []:
        if not isinstance(unit, dict) or not _is_military_unit(unit):
            continue
        if _is_settler_unit(unit):
            continue
        if not _unit_needs_orders(unit):
            continue
        coords = _unit_plot_coords(unit)
        if coords is not None:
            return coords
    return None


def pick_focus_tactical_target(
    snapshot: dict[str, Any],
    *,
    main_focus: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """High-value 6x6 focus: combat → settler orders → military orders → main/auto fallback."""
    combat = pick_combat_contact_focus_tile(snapshot)
    if combat is not None:
        return {
            "center": combat,
            "reason": "combat_contact",
            "label": f"combat contact near ({combat[0]},{combat[1]})",
        }
    settler = pick_settler_needs_orders_focus_tile(snapshot)
    if settler is not None:
        return {
            "center": settler,
            "reason": "settler_needs_orders",
            "label": f"settler needing orders at ({settler[0]},{settler[1]})",
        }
    military = pick_military_needs_orders_focus_tile(snapshot)
    if military is not None:
        return {
            "center": military,
            "reason": "military_needs_orders",
            "label": f"unit needing orders at ({military[0]},{military[1]})",
        }
    if main_focus is not None:
        return {
            "center": main_focus,
            "reason": "main_tactical_fallback",
            "label": f"main tactical focus ({main_focus[0]},{main_focus[1]})",
        }
    auto = pick_auto_focus_tile({}, snapshot)
    return {
        "center": auto,
        "reason": "auto_fallback",
        "label": f"auto focus ({auto[0]},{auto[1]})",
    }


def should_omit_focus_map(
    overview: dict[str, Any],
    focus: dict[str, Any],
    *,
    main: dict[str, Any] | None = None,
    main_attached: bool = False,
) -> tuple[bool, str]:
    """Skip focus when strategic already shows detail, or main tactical already covers it."""
    omit, reason = should_omit_tactical_map(overview, focus)
    if omit:
        return True, reason
    if main_attached and isinstance(main, dict):
        if viewport_overlap_fraction(focus, main) >= FOCUS_COVERED_BY_MAIN_THRESHOLD:
            return True, "covered_by_main_tactical"
    return False, ""


def pick_auto_focus_tile(
    memory: dict[str, Any],
    snapshot: dict[str, Any],
) -> tuple[int, int]:
    tracking = memory.get("event_tracking", {})
    if isinstance(tracking, dict):
        damaged = tracking.get("damaged_units", [])
        if isinstance(damaged, list) and damaged:
            target_id = None
            worst_loss = -1
            for row in damaged:
                if not isinstance(row, dict):
                    continue
                unit_id = row.get("unit_id")
                if not isinstance(unit_id, str) or not unit_id.strip():
                    continue
                try:
                    loss = int(row.get("loss", 0))
                except (TypeError, ValueError):
                    loss = 0
                if loss > worst_loss:
                    worst_loss = loss
                    target_id = unit_id
            if target_id is not None:
                for unit in snapshot.get("your_units", []):
                    if not isinstance(unit, dict) or unit.get("unit_id") != target_id:
                        continue
                    coords = _unit_plot_coords(unit)
                    if coords is not None:
                        return coords
    war_focus = pick_auto_war_focus_tile(snapshot)
    if war_focus is not None:
        return war_focus
    explore = pick_auto_explore_focus_tile(snapshot)
    if explore is not None:
        return explore
    capital = _capital_coords(snapshot)
    if capital is not None:
        return capital
    map_width, map_height = _map_dimensions(snapshot)
    return map_width // 2, map_height // 2


def resolve_tactical_viewport(
    thought_memory: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Ensure memory holds a tactical focus; auto-pick when the agent has been idle 20+ turns."""
    memory = thought_memory
    turn = int(snapshot.get("decision", {}).get("turn", 0) or 0)
    map_width, map_height = _map_dimensions(snapshot)
    last_agent = memory.get("last_agent_viewport_turn")
    stale = not isinstance(last_agent, int) or turn - last_agent >= VIEWPORT_AGENT_STALE_TURNS
    stored = memory.get("map_viewport")
    if not stale and isinstance(stored, dict):
        pinned = stored.get("focus_unit")
        if isinstance(pinned, str) and pinned.strip():
            named = parse_named_map_focus(snapshot, pinned)
            if named is not None:
                focus = named
                rect = viewport_focused_on_tile(focus[0], focus[1], map_width, map_height)
                memory["map_viewport"] = {
                    "focus_x": focus[0],
                    "focus_y": focus[1],
                    "focus_unit": pinned.strip(),
                    **rect,
                    "turn": stored.get("turn", turn),
                    "auto": False,
                }
                return memory
        focus = parse_map_focus_tile(stored)
        if focus is None and viewport_rect_from_stored(stored, map_width, map_height) is not None:
            rect = viewport_rect_from_stored(stored, map_width, map_height)
            assert rect is not None
            focus = (
                rect["x0"] + rect["width"] // 2,
                rect["y0"] + rect["height"] // 2,
            )
        if focus is not None:
            rect = viewport_focused_on_tile(focus[0], focus[1], map_width, map_height)
            memory["map_viewport"] = {
                "focus_x": focus[0],
                "focus_y": focus[1],
                **rect,
                "turn": stored.get("turn", turn),
                "auto": bool(stored.get("auto")),
            }
            return memory
    focus = pick_auto_focus_tile(memory, snapshot)
    rect = viewport_focused_on_tile(focus[0], focus[1], map_width, map_height)
    memory["map_viewport"] = {
        "focus_x": focus[0],
        "focus_y": focus[1],
        **rect,
        "turn": turn,
        "auto": True,
    }
    return memory


def map_viewport_from_flat(flat: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    raw = flat.get("map.viewport")
    if raw is None:
        raw = flat.get("map.focus")
    if raw is None:
        nested_focus = {
            "focus_x": flat.get("map.viewport.x"),
            "focus_y": flat.get("map.viewport.y"),
        }
        if nested_focus["focus_x"] is not None and nested_focus["focus_y"] is not None:
            raw = nested_focus
        else:
            nested = {
                "x0": flat.get("map.viewport.x0"),
                "y0": flat.get("map.viewport.y0"),
                "width": flat.get("map.viewport.width"),
                "height": flat.get("map.viewport.height"),
            }
            if all(value is not None for value in nested.values()):
                raw = nested
    focus = parse_map_focus_tile(raw)
    named = None if focus is not None else parse_named_map_focus(snapshot, raw)
    if named is not None:
        focus = named
    if focus is not None:
        x, y = focus
        map_width, map_height = _map_dimensions(snapshot)
        out = {
            "focus_x": x,
            "focus_y": y,
            **viewport_focused_on_tile(x, y, map_width, map_height),
        }
        if named is not None and isinstance(raw, str):
            out["focus_unit"] = raw.strip()
        return out
    parsed = parse_map_viewport_value(raw)
    if parsed is None:
        return None
    map_width, map_height = _map_dimensions(snapshot)
    clamped = clamp_map_viewport(
        parsed["x0"],
        parsed["y0"],
        parsed["width"],
        parsed["height"],
        map_width,
        map_height,
    )
    return {
        "focus_x": clamped["x0"] + clamped["width"] // 2,
        "focus_y": clamped["y0"] + clamped["height"] // 2,
        **clamped,
    }


def compute_overview_viewport(snapshot: dict[str, Any]) -> dict[str, int]:
    from sidecar import pipeline_v2 as pipeline

    pipeline.ensure_known_map_plots(snapshot)
    plot_index = map_render.build_render_plot_index(snapshot)
    return map_render.compute_viewport(snapshot, plot_index, pad=2)


def _render_role(
    snapshot: dict[str, Any],
    path: Path,
    *,
    viewport: dict[str, int],
    target_size: int,
    role: str,
    label: str,
    prefer_civ5_sprites: bool = True,
    strategic_banner: str = STRATEGIC_MAP_BANNER,
    tactical_banner: str = TACTICAL_MAP_BANNER,
    focus_banner: str = FOCUS_TACTICAL_MAP_BANNER,
) -> dict[str, Any]:
    meta = render_civ6_map_png(
        snapshot,
        path,
        prefer_civ5_sprites=prefer_civ5_sprites,
        viewport=viewport,
        target_size=target_size,
        image_role=role,
    )
    if role == "overview":
        map_width, map_height = _map_dimensions(snapshot)
        banner = f"{strategic_banner}  {format_strategic_window(viewport, map_width, map_height)}"
    elif role == "focus":
        banner = focus_banner
    else:
        banner = tactical_banner
    _stamp_map_banner(path, banner)
    _refresh_data_url(meta, path)
    meta["role"] = role
    meta["banner"] = banner
    meta["label"] = banner if role == "overview" else f"{banner} — {label}"
    meta["path"] = str(path)
    return meta


def prepare_civ5_situational_maps(
    snapshot: dict[str, Any],
    journal_dir: Path,
    *,
    attach: bool,
    map_viewport: dict[str, Any] | None = None,
    at_war: bool = False,
    overview_size: int | None = None,
    tactical_size: int | None = None,
    omit_tactical: bool | None = None,
    focus_size: int | None = None,
    omit_focus: bool | None = True,
    prefer_civ5_sprites: bool = True,
    strategic_banner: str = STRATEGIC_MAP_BANNER,
    tactical_banner: str = TACTICAL_MAP_BANNER,
    focus_banner: str = FOCUS_TACTICAL_MAP_BANNER,
) -> dict[str, Any]:
    """Render overview, main tactical viewport, and optional low-res 6x6 focus.

    overview_size / tactical_size / omit_tactical / focus_size come from context_budget when set.
    """
    from sidecar import pipeline_v2 as pipeline

    _ = at_war
    if not attach:
        return {"attached": False, "images": [], "manifest": [], "data_urls": []}

    pipeline.ensure_known_map_plots(snapshot)
    journal_dir.mkdir(parents=True, exist_ok=True)
    images: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    map_width, map_height = _map_dimensions(snapshot)
    role_kwargs = {
        "prefer_civ5_sprites": prefer_civ5_sprites,
        "strategic_banner": strategic_banner,
        "tactical_banner": tactical_banner,
        "focus_banner": focus_banner,
    }

    resolved_overview = map_render.resolve_civ5_overview_model_image_size(overview_size)
    if isinstance(tactical_size, int) and tactical_size <= 0:
        force_omit_tactical = True
        resolved_tactical = 0
    else:
        force_omit_tactical = bool(omit_tactical)
        resolved_tactical = 0 if force_omit_tactical else map_render.resolve_civ5_tactical_model_image_size(tactical_size)

    overview_viewport = compute_overview_viewport(snapshot)
    overview_meta = _render_role(
        snapshot,
        journal_dir / "map_overview.png",
        viewport=overview_viewport,
        target_size=resolved_overview,
        role="overview",
        label=strategic_banner,
        **role_kwargs,
    )
    images.append(overview_meta)
    manifest.append({
        "role": "overview",
        "label": overview_meta["label"],
        "viewport": overview_viewport,
        "detail": "low",
        "image_size": resolved_overview,
    })

    tactical_rect: dict[str, int] | None = None
    tactical_label = tactical_banner
    if isinstance(map_viewport, dict):
        tactical_rect = viewport_rect_from_stored(map_viewport, map_width, map_height)
        focus = parse_map_focus_tile(map_viewport)
        if focus is not None:
            tactical_label = f"Tactical viewport centered on ({focus[0]},{focus[1]})"
        elif tactical_rect is not None:
            tactical_label = (
                "Tactical viewport "
                f"({tactical_rect['x0'] + tactical_rect['width'] // 2},"
                f"{tactical_rect['y0'] + tactical_rect['height'] // 2})"
            )
    if tactical_rect is None:
        focus = pick_auto_focus_tile({}, snapshot)
        tactical_rect = viewport_focused_on_tile(focus[0], focus[1], map_width, map_height)
        tactical_label = f"Auto tactical viewport centered on ({focus[0]},{focus[1]})"

    omit_tactical_flag, omit_reason = should_omit_tactical_map(overview_viewport, tactical_rect)
    if force_omit_tactical:
        omit_tactical_flag = True
        omit_reason = omit_reason or "context_budget"
    if omit_tactical_flag or resolved_tactical <= 0:
        manifest[0]["tactical_omitted"] = True
        manifest[0]["tactical_omit_reason"] = omit_reason or "context_budget"
        manifest[0]["overview_image_size"] = resolved_overview
    else:
        tactical_meta = _render_role(
            snapshot,
            journal_dir / "map_viewport.png",
            viewport=tactical_rect,
            target_size=resolved_tactical,
            role="viewport",
            label=tactical_label,
            **role_kwargs,
        )
        images.append(tactical_meta)
        manifest.append({
            "role": "viewport",
            "label": tactical_meta["label"],
            "viewport": tactical_rect,
            "detail": "high",
            "image_size": resolved_tactical,
            "requested_turn": map_viewport.get("turn") if isinstance(map_viewport, dict) else None,
            "auto": bool(map_viewport.get("auto")) if isinstance(map_viewport, dict) else True,
        })

    # Second low-res 6x6 focus tactical (combat / settler / needs_orders / main fallback).
    main_attached = any(isinstance(item, dict) and item.get("role") == "viewport" for item in manifest)
    main_focus_xy: tuple[int, int] | None = None
    if isinstance(map_viewport, dict):
        main_focus_xy = parse_map_focus_tile(map_viewport)
    if main_focus_xy is None and tactical_rect is not None:
        main_focus_xy = (
            tactical_rect["x0"] + tactical_rect["width"] // 2,
            tactical_rect["y0"] + tactical_rect["height"] // 2,
        )
    force_omit_focus = bool(omit_focus) or force_omit_tactical
    if isinstance(focus_size, int) and focus_size <= 0:
        force_omit_focus = True
        resolved_focus = 0
    else:
        resolved_focus = 0 if force_omit_focus else map_render.resolve_civ5_focus_model_image_size(focus_size)
    focus_target = pick_focus_tactical_target(snapshot, main_focus=main_focus_xy)
    focus_center = focus_target["center"]
    focus_rect = viewport_centered_on_plot(
        focus_center[0],
        focus_center[1],
        map_width,
        map_height,
        size=FOCUS_TACTICAL_VIEWPORT_SIZE,
    )
    omit_focus_flag, focus_omit_reason = should_omit_focus_map(
        overview_viewport,
        focus_rect,
        main=tactical_rect,
        main_attached=main_attached,
    )
    if force_omit_focus:
        omit_focus_flag = True
        focus_omit_reason = focus_omit_reason or "context_budget"
    if omit_focus_flag or resolved_focus <= 0:
        manifest[0]["focus_omitted"] = True
        manifest[0]["focus_omit_reason"] = focus_omit_reason or "context_budget"
    else:
        focus_label = str(focus_target.get("label") or f"focus ({focus_center[0]},{focus_center[1]})")
        focus_meta = _render_role(
            snapshot,
            journal_dir / "map_focus.png",
            viewport=focus_rect,
            target_size=resolved_focus,
            role="focus",
            label=focus_label,
            **role_kwargs,
        )
        images.append(focus_meta)
        manifest.append({
            "role": "focus",
            "label": focus_meta["label"],
            "viewport": focus_rect,
            "detail": "low",
            "image_size": resolved_focus,
            "reason": focus_target.get("reason"),
            "center": {"x": focus_center[0], "y": focus_center[1]},
        })

    known_map = snapshot.setdefault("known_map", {})
    if isinstance(known_map, dict):
        image = known_map.setdefault("image", {})
        if isinstance(image, dict):
            image["attached"] = True
            image["path"] = images[0]["path"]
            image["viewport"] = overview_viewport
            image["legend"] = overview_meta.get("legend", [])
            image["images"] = copy.deepcopy(manifest)

    return {
        "attached": True,
        "images": images,
        "manifest": manifest,
        "data_urls": [
            {
                "data_url": item["data_url"],
                "detail": "low" if item.get("role") in {"overview", "focus"} else "high",
                "role": item.get("role", "map"),
                "label": item.get("label", ""),
            }
            for item in images
            if isinstance(item.get("data_url"), str)
        ],
    }


def prepare_civ6_situational_maps(
    snapshot: dict[str, Any],
    journal_dir: Path,
    *,
    attach: bool,
    map_viewport: dict[str, Any] | None = None,
    at_war: bool = False,
    overview_size: int | None = None,
    tactical_size: int | None = None,
    omit_tactical: bool | None = None,
    focus_size: int | None = None,
    omit_focus: bool | None = True,
) -> dict[str, Any]:
    """Civ6 strategic/tactical map windows (same layout as Civ5, Civ6 sprites/banners)."""
    return prepare_civ5_situational_maps(
        snapshot,
        journal_dir,
        attach=attach,
        map_viewport=map_viewport,
        at_war=at_war,
        overview_size=overview_size,
        tactical_size=tactical_size,
        omit_tactical=omit_tactical,
        focus_size=focus_size,
        omit_focus=omit_focus,
        prefer_civ5_sprites=False,
        strategic_banner=CIV6_STRATEGIC_MAP_BANNER,
        tactical_banner=CIV6_TACTICAL_MAP_BANNER,
        focus_banner=CIV6_FOCUS_TACTICAL_MAP_BANNER,
    )


# Backward-compatible aliases for older imports/tests.
AUTO_DAMAGE_VIEWPORT_SIZE = max_tactical_viewport_size_with_coords()
AUTO_WAR_VIEWPORT_MAX = max_tactical_viewport_size_with_coords()
TACTICAL_CONTACT_DISTANCE = 5
TACTICAL_CLUSTER_DISTANCE = 8
MAX_TACTICAL_IMAGES = 2  # main tactical + low-res focus


def apply_auto_damage_viewport(
    thought_memory: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    return resolve_tactical_viewport(thought_memory, snapshot)


def pick_auto_war_viewport(snapshot: dict[str, Any]) -> dict[str, int] | None:
    focus = pick_auto_war_focus_tile(snapshot)
    if focus is None:
        return None
    map_width, map_height = _map_dimensions(snapshot)
    return viewport_focused_on_tile(focus[0], focus[1], map_width, map_height)


def detect_tactical_hotspots(
    snapshot: dict[str, Any],
    *,
    contact_distance: int = TACTICAL_CONTACT_DISTANCE,
    max_images: int = MAX_TACTICAL_IMAGES,
) -> list[dict[str, Any]]:
    focus = pick_auto_war_focus_tile(snapshot)
    if focus is None:
        return []
    map_width, map_height = _map_dimensions(snapshot)
    viewport = viewport_focused_on_tile(focus[0], focus[1], map_width, map_height)
    return [{
        "role": "viewport",
        "label": f"Tactical contact near ({focus[0]},{focus[1]})",
        "viewport": viewport,
        "center": focus,
    }][:max_images]
