"""Map marker PNG icons for minimap rendering."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from sidecar import civ6_assets

try:
    from sidecar import civ5_assets
except ImportError:
    civ5_assets = None  # type: ignore[assignment]

LEGACY_ICON_DIR = Path(__file__).resolve().parent / "assets" / "map_icons"
ICON_DIR = LEGACY_ICON_DIR  # backward compat for generate_map_icons.py
ICON_SIZE = 16

_RENDER_CONTEXT: dict[str, bool] = {"prefer_civ5": False}

_LEGACY_UNIT_ICON_MAP: dict[str, str] = {
    "UNIT_SETTLER": "unit_settler",
    "UNIT_BUILDER": "unit_worker",
    "UNIT_WORKER": "unit_worker",
    "UNIT_SCOUT": "unit_scout",
    "UNIT_ARCHER": "unit_archer",
    "UNIT_GALLEY": "unit_galley",
    "UNIT_WARRIOR": "unit_warrior",
    "UNIT_SPEARMAN": "unit_spear",
    "UNIT_SWORDSMAN": "unit_sword",
}

_DATA_URL_CACHE: dict[str, str] = {}


def set_render_context(prefer_civ5: bool = False) -> None:
    _RENDER_CONTEXT["prefer_civ5"] = prefer_civ5


def prefer_civ5_render() -> bool:
    return bool(_RENDER_CONTEXT.get("prefer_civ5"))


def _use_civ6_icons() -> bool:
    if prefer_civ5_render():
        return False
    return civ6_assets.assets_available()


def _use_civ5_icons() -> bool:
    return prefer_civ5_render() and civ5_assets is not None and civ5_assets.assets_available()


def icon_slug_for_unit(unit_type_id: str) -> str:
    if _use_civ5_icons():
        return civ5_assets.icon_slug_for_unit(unit_type_id)
    if _use_civ6_icons():
        return civ6_assets.icon_name_for_unit(unit_type_id)
    if unit_type_id in _LEGACY_UNIT_ICON_MAP:
        return _LEGACY_UNIT_ICON_MAP[unit_type_id]
    upper = unit_type_id.upper()
    if "GALLEY" in upper or "GALLEON" in upper or "CARAVEL" in upper or "NAVAL" in upper:
        return "unit_galley"
    if "SETTLER" in upper:
        return "unit_settler"
    if "BUILDER" in upper or "WORKER" in upper:
        return "unit_worker"
    if "SCOUT" in upper:
        return "unit_scout"
    if "ARCHER" in upper or "BOW" in upper:
        return "unit_archer"
    if "WARRIOR" in upper or "AXE" in upper or "MACE" in upper or "SPEAR" in upper or "SWORD" in upper:
        return "unit_warrior"
    return "unit_default"


def resource_icon_slug(resource_id: str) -> str:
    if _use_civ6_icons():
        return civ6_assets.icon_name_for_resource(resource_id)
    if _use_civ5_icons():
        return civ5_assets.icon_name_for_resource(resource_id)
    return ""


def city_icon_slug(is_capital: bool = False) -> str:
    if _use_civ5_icons():
        return civ5_assets.icon_slug_for_city(is_capital)
    if _use_civ6_icons():
        return "ICON_DISTRICT_CITY_CENTER"
    return "capital" if is_capital else "city"


def icon_path(slug: str, tint_rgb: tuple[int, int, int] | None = None) -> Path:
    if slug.startswith("UNIT_FLAG:") and _use_civ5_icons():
        unit_id = slug.split(":", 1)[1]
        cached = civ5_assets.unit_flag_png_path(unit_id, tint_rgb=tint_rgb)
        if cached is not None:
            return cached
    if slug.startswith("ICON_"):
        cached = civ6_assets.icon_png_path(slug, out_size=32)
        if cached is not None:
            return cached
    if slug.upper().startswith("RESOURCE_") and _use_civ5_icons():
        cached = civ5_assets.resource_png_path(slug)
        if cached is not None:
            return cached
    if slug in {"city", "city_capital", "capital"} and _use_civ5_icons():
        cached = civ5_assets.city_png_path(slug in {"city_capital", "capital"})
        if cached is not None:
            return cached
    return LEGACY_ICON_DIR / f"{slug}.png"


def _load_data_url(slug: str, tint_rgb: tuple[int, int, int] | None = None) -> str | None:
    cache_key = slug
    if tint_rgb is not None:
        cache_key = f"{slug}_{tint_rgb[0]:02x}{tint_rgb[1]:02x}{tint_rgb[2]:02x}"
    if cache_key in _DATA_URL_CACHE:
        return _DATA_URL_CACHE[cache_key]
    path = icon_path(slug, tint_rgb=tint_rgb)
    if not path.is_file():
        return None
    raw = path.read_bytes()
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    _DATA_URL_CACHE[cache_key] = data_url
    return data_url


def icon_data_url(slug: str) -> str | None:
    return _load_data_url(slug)


def unit_icon_data_url(unit_type_id: str, foreign: bool = False) -> str | None:
    slug = icon_slug_for_unit(unit_type_id)
    url = _load_data_url(slug)
    if url is not None:
        return url
    if foreign:
        return _load_data_url("unit_foreign") or _load_data_url("unit_default")
    return _load_data_url("unit_default")


def city_icon_data_url(is_capital: bool = False) -> str | None:
    return _load_data_url(city_icon_slug(is_capital))


def resource_icon_data_url(resource_id: str) -> str | None:
    slug = resource_icon_slug(resource_id)
    if not slug:
        return None
    return _load_data_url(slug)


def stack_icon_data_url() -> str | None:
    return _load_data_url("stack")


def legend_marker_entries(
    tile_markers: dict[tuple[int, int], list[dict[str, Any]]],
    snapshot: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    has_city = any(
        m.get("kind") == "city" for markers in tile_markers.values() for m in markers
    )
    has_capital = any(
        m.get("kind") == "city" and m.get("is_capital") for markers in tile_markers.values() for m in markers
    )
    has_unit = any(
        m.get("kind") == "unit" for markers in tile_markers.values() for m in markers
    )
    if has_city:
        label = "your city (★ = capital)" if has_capital else "your city"
        entries.append((city_icon_slug(False), label))
    if has_unit:
        unit_type = "UNIT_SCOUT"
        if snapshot is not None:
            for unit in snapshot.get("your_units", []):
                if isinstance(unit, dict) and unit.get("unit_type_id"):
                    unit_type = str(unit["unit_type_id"])
                    break
        entries.append((icon_slug_for_unit(unit_type), "your unit"))
    return entries


def legend_icon_slugs(snapshot: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Backward-compatible wrapper for square-map SVG renderer."""
    entries = legend_marker_entries({}, snapshot)
    if _use_civ5_icons():
        entries.append(("RESOURCE_IRON", "resource"))
        return entries
    entries.append(("ICON_RESOURCE_IRON", "resource"))
    if not _use_civ6_icons():
        return [
            ("city", "your city"),
            ("capital", "your capital"),
            ("unit_default", "your unit"),
            ("unit_foreign", "foreign unit"),
            ("stack", "unit stack"),
        ]
    return entries


def icon_px_for_tile(tile_px: int, marker_count: int) -> int:
    if marker_count <= 1:
        return max(10, min(tile_px - 2, ICON_SIZE))
    if marker_count <= 4:
        return max(6, tile_px // 2 - 2)
    return max(5, tile_px // 3)


def tile_slot_offsets(tile_px: int, icon_px: int, index: int, total: int) -> tuple[int, int]:
    if total <= 1:
        margin = max(0, (tile_px - icon_px) // 2)
        return (margin, margin)
    quad_w = max(1, tile_px // 2)
    quad_h = max(1, tile_px // 2)
    quads = [(0, 0), (quad_w, 0), (0, quad_h), (quad_w, quad_h)]
    qx, qy = quads[min(index, len(quads) - 1)]
    ox = qx + max(0, (quad_w - icon_px) // 2)
    oy = qy + max(0, (quad_h - icon_px) // 2)
    if index >= len(quads):
        ox = max(0, (tile_px - icon_px) // 2)
        oy = max(0, (tile_px - icon_px) // 2)
    return (ox, oy)


def svg_image_tag(x: int, y: int, size: int, data_url: str, clip_id: str | None = None) -> str:
    href = data_url.replace("&", "&amp;")
    clip = f' clip-path="url(#{clip_id})"' if clip_id else ""
    return (
        f'<image x="{x}" y="{y}" width="{size}" height="{size}" '
        f'preserveAspectRatio="xMidYMid meet" href="{href}"{clip}/>'
    )


def svg_foreign_tint(x: int, y: int, size: int) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{size}" height="{size}" '
        f'fill="none" stroke="#ff4444" stroke-width="1.5" rx="2"/>'
    )
