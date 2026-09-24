"""Load Civ V strategic-view sprites and UI icons from the local game install."""
from __future__ import annotations

import os
import re
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

from sidecar import civ5_fpk
from sidecar import civ6_assets

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "assets" / "civ5"
ICON_CACHE_DIR = CACHE_DIR / "icons"
STRATEGIC_CACHE_DIR = CACHE_DIR / "strategic"
EXTRACTED_DIR = CACHE_DIR / "extracted"

_GAME_SUFFIX = "Sid Meier's Civilization V"

_TERRAIN_HEX: dict[str, str] = {
    "TERRAIN_GRASS": "sv_terrainhexgrasslands.dds",
    "TERRAIN_PLAINS": "sv_terrainhexplains.dds",
    "TERRAIN_DESERT": "sv_terrainhexdesert.dds",
    "TERRAIN_TUNDRA": "sv_terrainhextundra.dds",
    "TERRAIN_SNOW": "sv_terrainhexsnow.dds",
    "TERRAIN_COAST": "sv_terrainhexcoast.dds",
    "TERRAIN_OCEAN": "sv_terrainhexocean.dds",
}

_FEATURE_SV: dict[str, str] = {
    "FEATURE_FOREST": "sv_forest.dds",
    "FEATURE_JUNGLE": "sv_jungle.dds",
    "FEATURE_MARSH": "sv_marsh.dds",
    "FEATURE_FLOOD_PLAINS": "sv_marsh.dds",
}

_HILLS_SV = "sv_hills.dds"
_MOUNTAIN_SV = "sv_mountains.dds"

_LOOSE_DDS_ROOTS = (
    "Assets/UI/Art",
    "assets/UI/Art",
    "Resource/DX9",
    "Assets/DLC/Expansion2/Assets/StrategicView",
    "Assets/UI/Art/StrategicView",
    "Assets/UI/Art/Icons",
    "Assets/UI/Art/Icons/Units",
)

_FPK_SEARCH_DIRS = (
    "Resource/DX9",
    "Resource",
    "Assets/DLC/Expansion2/Resource/DX9",
)


def resolve_game_root() -> Path | None:
    for key in ("CIV5_GAME_ROOT", "CIV5_INSTALL"):
        env = os.environ.get(key, "").strip()
        if env:
            path = Path(env)
            if path.is_dir() and (path / "CivilizationV.exe").is_file():
                return path
    steam_roots = [
        Path("C:/Program Files (x86)/Steam/steamapps/common"),
        Path("C:/Program Files/Steam/steamapps/common"),
        Path("D:/Steam/steamapps/common"),
        Path("D:/SteamLibrary/steamapps/common"),
        Path("E:/Steam/steamapps/common"),
        Path("G:/SteamLibrary/steamapps/common"),
    ]
    for steam_root in steam_roots:
        candidate = steam_root / _GAME_SUFFIX
        if (candidate / "CivilizationV.exe").is_file():
            return candidate
    for drive in range(ord("C"), ord("Z") + 1):
        letter = chr(drive)
        for lib in ("Steam/steamapps/common", "SteamLibrary/steamapps/common"):
            steam_common = Path(f"{letter}:/{lib}")
            if not steam_common.is_dir():
                continue
            candidate = steam_common / _GAME_SUFFIX
            if (candidate / "CivilizationV.exe").is_file():
                return candidate
    return None


def _documents_mods() -> list[Path]:
    roots: list[Path] = []
    for key in ("USERPROFILE", "HOME"):
        base = os.environ.get(key, "").strip()
        if not base:
            continue
        roots.append(Path(base) / "Documents" / "My Games" / "Sid Meier's Civilization 5" / "MODS")
        roots.append(
            Path(base) / "OneDrive" / "Documents" / "My Games" / "Sid Meier's Civilization 5" / "MODS"
        )
    return [path for path in roots if path.is_dir()]


@lru_cache(maxsize=1)
def _fpk_indexes() -> list[list[civ5_fpk.FpkEntry]]:
    game = resolve_game_root()
    if game is None:
        return []
    indexes: list[list[civ5_fpk.FpkEntry]] = []
    seen: set[Path] = set()
    for rel in _FPK_SEARCH_DIRS:
        folder = game / rel.replace("/", os.sep)
        if not folder.is_dir():
            continue
        for fpk_path in folder.rglob("*.fpk"):
            if fpk_path in seen:
                continue
            seen.add(fpk_path)
            index = civ5_fpk.read_fpk_index(fpk_path)
            if index:
                indexes.append(index)
    return indexes


def _find_loose_dds(name: str) -> Path | None:
    game = resolve_game_root()
    if game is None:
        return None
    lower_name = name.lower()
    for rel in _LOOSE_DDS_ROOTS:
        root = game / rel.replace("/", os.sep)
        if not root.is_dir():
            continue
        direct = root / name
        if direct.is_file():
            return direct
        for path in root.rglob(name):
            if path.is_file():
                return path
        for path in root.rglob("*"):
            if path.is_file() and path.name.lower() == lower_name:
                return path
    for mods in _documents_mods():
        for child in mods.iterdir():
            if not child.is_dir():
                continue
            for path in (child / "Assets").rglob(name):
                if path.is_file():
                    return path
    return None


def _extract_dds_to_cache(name: str) -> Path | None:
    cached = EXTRACTED_DIR / name
    if cached.is_file():
        return cached
    loose = _find_loose_dds(name)
    if loose is not None:
        EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(civ6_assets.trim_dds_bytes(loose.read_bytes()))
        return cached
    entry = civ5_fpk.find_in_fpk_indexes(_fpk_indexes(), name)
    if entry is None:
        return None
    payload = civ6_assets.trim_dds_bytes(civ5_fpk.extract_entry(entry))
    if not payload:
        return None
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(payload)
    return cached


def _dds_to_cached_png(dds_name: str, cache_dir: Path, stem: str | None = None) -> Path | None:
    out_stem = stem or dds_name.replace(".dds", "")
    cached = cache_dir / f"{out_stem}.png"
    if cached.is_file():
        return cached
    source = _extract_dds_to_cache(dds_name)
    if source is None:
        return None
    image = civ6_assets.load_rgba_image(source)
    if image is None:
        return None
    image = civ6_assets._crop_alpha_bbox(image)
    civ6_assets._save_png(image, cached)
    return cached


def assets_available() -> bool:
    return resolve_game_root() is not None


def _parse_terrain_id(terrain_id: str) -> tuple[str, bool, bool]:
    upper = terrain_id.upper()
    hills = upper.endswith("_HILLS")
    peak = upper.endswith("_MOUNTAIN")
    base = upper
    if hills:
        base = base[:-6]
    if peak:
        base = base[:-9]
    return base, hills, peak


def strategic_dds_layers(plot: dict[str, Any] | None) -> list[str]:
    """Layered strategic-view DDS names from Civ5 StrategicViewTextures.fpk."""
    if not isinstance(plot, dict):
        return []
    layers: list[str] = []
    terrain_id = plot.get("terrain_id")
    if not isinstance(terrain_id, str):
        return layers
    base_id, parsed_hills, parsed_peak = _parse_terrain_id(terrain_id)
    hills = bool(plot.get("hills")) or parsed_hills
    peak = bool(plot.get("peak")) or parsed_peak
    base_hex = _TERRAIN_HEX.get(base_id)
    if base_hex is not None:
        layers.append(base_hex)
    feature_id = plot.get("feature_id")
    if isinstance(feature_id, str):
        overlay = _FEATURE_SV.get(feature_id.upper())
        if overlay:
            layers.append(overlay)
    if hills and not peak:
        layers.append(_HILLS_SV)
    if peak:
        layers.append(_MOUNTAIN_SV)
    seen: set[str] = set()
    unique: list[str] = []
    for name in layers:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def strategic_dds_name(plot: dict[str, Any] | None) -> str | None:
    layers = strategic_dds_layers(plot)
    return layers[0] if layers else None


def strategic_layer_png_paths(plot: dict[str, Any] | None) -> list[Path]:
    paths: list[Path] = []
    for dds_name in strategic_dds_layers(plot):
        png = _dds_to_cached_png(dds_name, STRATEGIC_CACHE_DIR)
        if png is not None:
            paths.append(png)
    return paths


def strategic_png_path(plot: dict[str, Any] | None) -> Path | None:
    paths = strategic_layer_png_paths(plot)
    return paths[0] if paths else None


@lru_cache(maxsize=1)
def _parse_icon_atlases() -> dict[tuple[str, int], tuple[str, int, int]]:
    game = resolve_game_root()
    if game is None:
        return {}
    atlases: dict[tuple[str, int], tuple[str, int, int]] = {}
    xml_paths = list(game.rglob("CIV5IconTextureAtlases.xml"))
    for xml_path in xml_paths:
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
            r"<Atlas>([^<]+)</Atlas>\s*<IconSize>(\d+)</IconSize>\s*<Filename>([^<]+)</Filename>\s*"
            r"<IconsPerRow>(\d+)</IconsPerRow>\s*<IconsPerColumn>(\d+)</IconsPerColumn>",
            text,
            flags=re.DOTALL,
        ):
            atlas, size, filename, per_row, _per_col = match.groups()
            atlases[(atlas.strip(), int(size))] = (filename.strip(), int(per_row), int(_per_col))
    return atlases


@lru_cache(maxsize=1)
def _parse_resource_icons() -> dict[str, tuple[str, int, int]]:
    game = resolve_game_root()
    if game is None:
        return {}
    mapping: dict[str, tuple[str, int, int]] = {}
    for xml_path in game.rglob("CIV5Resources.xml"):
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        for block in re.finditer(r"<Row>(.*?)</Row>", text, flags=re.DOTALL):
            chunk = block.group(1)
            type_match = re.search(r"<Type>(RESOURCE_[^<]+)</Type>", chunk)
            if not type_match:
                continue
            resource_id = type_match.group(1).strip()
            atlas_match = re.search(r"<IconAtlas>([^<]+)</IconAtlas>", chunk)
            index_match = re.search(r"<PortraitIndex>(-?\d+)</PortraitIndex>", chunk)
            if not atlas_match or not index_match:
                continue
            index = int(index_match.group(1))
            if index < 0:
                continue
            mapping[resource_id] = (atlas_match.group(1).strip(), index)
    return mapping


@lru_cache(maxsize=1)
def _parse_unit_flag_icons() -> dict[str, tuple[str, int, str]]:
    game = resolve_game_root()
    if game is None:
        return {}
    mapping: dict[str, tuple[str, int, str]] = {}
    for xml_path in game.rglob("CIV5Units.xml"):
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        for block in re.finditer(r"<Row>(.*?)</Row>", text, flags=re.DOTALL):
            chunk = block.group(1)
            type_match = re.search(r"<Type>(UNIT_[^<]+)</Type>", chunk)
            if not type_match:
                continue
            unit_id = type_match.group(1).strip()
            offset_match = re.search(r"<UnitFlagIconOffset>(\d+)</UnitFlagIconOffset>", chunk)
            atlas_match = re.search(r"<UnitFlagAtlas>([^<]+)</UnitFlagAtlas>", chunk)
            if not offset_match:
                continue
            offset = int(offset_match.group(1))
            atlas = atlas_match.group(1).strip() if atlas_match else "UNIT_FLAG_ATLAS"
            mapping[unit_id] = (atlas, offset)
    return mapping


@lru_cache(maxsize=1)
def _parse_strategic_view_assets() -> dict[str, str]:
    game = resolve_game_root()
    if game is None:
        return {}
    mapping: dict[str, str] = {}
    for xml_path in game.rglob("Civ5ArtDefines_SV*.xml"):
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
            r"<StrategicViewType>([^<]+)</StrategicViewType>\s*<TileType>[^<]+</TileType>\s*<Asset>([^<]+)</Asset>",
            text,
            flags=re.DOTALL,
        ):
            mapping[match.group(1).strip()] = match.group(2).strip()
    return mapping


@lru_cache(maxsize=1)
def _parse_resource_art_tags() -> dict[str, str]:
    game = resolve_game_root()
    if game is None:
        return {}
    mapping: dict[str, str] = {}
    for xml_path in game.rglob("CIV5Resources.xml"):
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        for block in re.finditer(r"<Row>(.*?)</Row>", text, flags=re.DOTALL):
            chunk = block.group(1)
            type_match = re.search(r"<Type>(RESOURCE_[^<]+)</Type>", chunk)
            art_match = re.search(r"<ArtDefineTag>(ART_DEF_[^<]+)</ArtDefineTag>", chunk)
            if type_match and art_match:
                mapping[type_match.group(1).strip()] = art_match.group(1).strip()
    return mapping


def resource_sv_dds_name(resource_id: str) -> str | None:
    """Strategic-view overlay for a resource (sv_fish.dds), not the UI icon atlas."""
    slug = resource_id.strip().upper()
    if not slug.startswith("RESOURCE_"):
        return None
    art_tag = _parse_resource_art_tags().get(slug)
    if art_tag:
        mapped = _parse_strategic_view_assets().get(art_tag)
        if mapped:
            return mapped
    return f"sv_{slug[len('RESOURCE_'):].lower()}.dds"


def _punch_near_black_alpha(image: Any, threshold: int = 16) -> Any:
    """SV sprites use opaque black corners instead of alpha."""
    work = image.convert("RGBA")
    pixels = work.load()
    for y in range(work.height):
        for x in range(work.width):
            red, green, blue, alpha = pixels[x, y]
            if red <= threshold and green <= threshold and blue <= threshold:
                pixels[x, y] = (red, green, blue, 0)
    return work


def _tint_to_rgb(image: Any, rgb: tuple[int, int, int]) -> Any:
    work = image.convert("RGBA")
    pixels = work.load()
    tr, tg, tb = rgb
    for y in range(work.height):
        for x in range(work.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                continue
            lum = max(red, green, blue)
            pixels[x, y] = (tr * lum // 255, tg * lum // 255, tb * lum // 255, alpha)
    return work


def _keyed_sv_png(
    dds_name: str,
    cache_stem: str,
    tint_rgb: tuple[int, int, int] | None = None,
) -> Path | None:
    tint_key = ""
    if tint_rgb is not None:
        tint_key = f"_{tint_rgb[0]:02x}{tint_rgb[1]:02x}{tint_rgb[2]:02x}"
    cached = ICON_CACHE_DIR / f"{cache_stem}{tint_key}_keyed.png"
    if cached.is_file():
        return cached
    source = _extract_dds_to_cache(dds_name)
    if source is None:
        return None
    image = civ6_assets.load_rgba_image(source)
    if image is None:
        return None
    image = civ6_assets._crop_alpha_bbox(_punch_near_black_alpha(image))
    if tint_rgb is not None:
        image = _tint_to_rgb(image, tint_rgb)
    civ6_assets._save_png(image, cached)
    return cached


def city_sv_dds_name(is_capital: bool = False) -> str:
    if is_capital:
        return "sv_ancient_africa_medium_city.dds"
    return "sv_ancient_africa_small_city.dds"


def unit_sv_dds_candidates(unit_type_id: str) -> list[str]:
    slug = unit_type_id.strip().upper()
    stem = slug[5:].lower() if slug.startswith("UNIT_") else slug.lower()
    tokens = [part for part in stem.split("_") if part]
    names: list[str] = []
    if stem:
        names.append(f"sv_{stem}.dds")
    if len(tokens) >= 2:
        names.append(f"sv_{''.join(tokens[-2:])}.dds")
    if tokens:
        names.append(f"sv_{tokens[-1]}.dds")
    names.append("sv_warrior.dds")
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def unit_sv_dds_name(unit_type_id: str) -> str | None:
    for name in unit_sv_dds_candidates(unit_type_id):
        if _extract_dds_to_cache(name) is not None:
            return name
    return None


def _crop_atlas_icon(atlas: str, icon_size: int, index: int, out_path: Path) -> Path | None:
    atlases = _parse_icon_atlases()
    entry = atlases.get((atlas, icon_size))
    if entry is None:
        for (name, size), value in atlases.items():
            if name == atlas:
                entry = value
                icon_size = size
                break
    if entry is None:
        return None
    filename, per_row, _per_col = entry
    dds_path = _extract_dds_to_cache(filename)
    if dds_path is None:
        return None
    image = civ6_assets.load_rgba_image(dds_path)
    if image is None:
        return None
    column = index % per_row
    row = index // per_row
    tile = image.crop((
        column * icon_size,
        row * icon_size,
        (column + 1) * icon_size,
        (row + 1) * icon_size,
    ))
    civ6_assets._save_png(tile, out_path)
    return out_path


def resource_png_path(resource_id: str) -> Path | None:
    if not isinstance(resource_id, str) or not resource_id.strip():
        return None
    slug = resource_id.strip().upper()
    sv_name = resource_sv_dds_name(slug)
    if not sv_name:
        return None
    return _keyed_sv_png(sv_name, f"resource_sv_{slug}")


def city_png_path(is_capital: bool = False) -> Path | None:
    slug = "city_capital" if is_capital else "city"
    return _keyed_sv_png(city_sv_dds_name(is_capital), f"city_sv_{slug}")


def unit_flag_png_path(unit_type_id: str, tint_rgb: tuple[int, int, int] | None = None) -> Path | None:
    unit_id = str(unit_type_id or "").strip().upper()
    if not unit_id:
        unit_id = "UNIT_WARRIOR"
    dds_name = unit_sv_dds_name(unit_id)
    if dds_name is None:
        return None
    return _keyed_sv_png(dds_name, f"unit_sv_{unit_id}", tint_rgb=tint_rgb)


def icon_name_for_resource(resource_id: str) -> str:
    return resource_id.strip().upper()


def icon_slug_for_unit(unit_type_id: str) -> str:
    return f"UNIT_FLAG:{unit_type_id.strip().upper()}"


def icon_slug_for_city(is_capital: bool = False) -> str:
    return "city_capital" if is_capital else "city"
