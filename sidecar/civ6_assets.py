"""Load real Civ6 UI icons and strategic-view sprites from the SDK Assets pantry."""
from __future__ import annotations

import os
import re
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "assets" / "civ6"
ICON_CACHE_DIR = CACHE_DIR / "icons"
STRATEGIC_CACHE_DIR = CACHE_DIR / "strategic"

_ICON_XML_GLOBS = (
    "Icons_Units.xml",
    "Icons_Resources.xml",
    "Icons_Districts.xml",
    "Icons_Buildings.xml",
    "Icons_Features.xml",
)

_TERRAIN_SUFFIX: dict[str, str] = {
    "TERRAIN_GRASS": "Grass",
    "TERRAIN_PLAINS": "Plains",
    "TERRAIN_DESERT": "Desert",
    "TERRAIN_TUNDRA": "Tundra",
    "TERRAIN_SNOW": "Snow",
    "TERRAIN_COAST": "Coast",
    "TERRAIN_OCEAN": "Ocean",
}

_FEATURE_STRATEGIC: dict[str, str] = {
    "FEATURE_FOREST": "StrategicView_Terrain_Forest.dds",
    "FEATURE_JUNGLE": "StrategicView_Terrain_Jungle.dds",
    "FEATURE_MARSH": "StrategicView_Terrain_Marsh.dds",
}


def _expand_rgb565(value: int) -> tuple[int, int, int, int]:
    red = ((value >> 11) & 0x1F) * 255 // 31
    green = ((value >> 5) & 0x3F) * 255 // 63
    blue = (value & 0x1F) * 255 // 31
    return red, green, blue, 255


def _mix(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
    left_weight: int,
    right_weight: int,
) -> tuple[int, int, int, int]:
    total = left_weight + right_weight
    return tuple((left[index] * left_weight + right[index] * right_weight) // total for index in range(3)) + (255,)


def dds_file_byte_size(raw: bytes) -> int | None:
    """Exact byte length of a DDS file from its header (Civ5 FPK blobs may pad past this)."""
    if len(raw) < 128 or raw[:4] != b"DDS ":
        return None
    height, width = struct.unpack_from("<II", raw, 12)
    blocks_w = (width + 3) // 4
    blocks_h = (height + 3) // 4
    fourcc = raw[84:88]
    if fourcc == b"DXT1":
        return 128 + blocks_w * blocks_h * 8
    if fourcc in (b"DXT3", b"DXT5"):
        return 128 + blocks_w * blocks_h * 16
    if fourcc == b"\x00\x00\x00\x00":
        bpp = struct.unpack_from("<I", raw, 88)[0]
        if bpp == 32:
            return 128 + width * height * 4
    return None


def trim_dds_bytes(raw: bytes) -> bytes:
    size = dds_file_byte_size(raw)
    if size is not None and size <= len(raw):
        return raw[:size]
    return raw


def read_dds_rgba(path: Path) -> tuple[bytes, int, int] | None:
    """DDS reader for RGBA32, DXT1, DXT3, and DXT5 (Civ5/Civ6 UI atlases)."""
    raw = trim_dds_bytes(path.read_bytes())
    if len(raw) < 128 or raw[:4] != b"DDS ":
        return None
    height, width = struct.unpack_from("<II", raw, 12)
    fourcc = raw[84:88]
    offset = 128
    if fourcc == b"DXT1":
        return _decode_dxt1(raw[offset:], width, height), width, height
    if fourcc == b"DXT3":
        return _decode_dxt3(raw[offset:], width, height), width, height
    if fourcc == b"DXT5":
        return _decode_dxt5(raw[offset:], width, height), width, height
    if fourcc == b"\x00\x00\x00\x00":
        bpp = struct.unpack_from("<I", raw, 88)[0]
        if bpp == 32:
            pixels = bytearray(width * height * 4)
            for index in range(width * height):
                blue, green, red, alpha = raw[offset + 4 * index: offset + 4 * index + 4]
                base = index * 4
                pixels[base: base + 4] = (red, green, blue, alpha)
            return bytes(pixels), width, height
    return None


def _decode_dxt1(data: bytes, width: int, height: int) -> bytes:
    from PIL import Image

    del Image  # runtime import happens in load_rgba_image
    output = bytearray(width * height * 4)
    blocks_wide = (width + 3) // 4
    blocks_high = (height + 3) // 4
    pos = 0
    for block_y in range(blocks_high):
        for block_x in range(blocks_wide):
            color0, color1 = struct.unpack_from("<HH", data, pos)
            pos += 4
            bits = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            colors = [_expand_rgb565(color0), _expand_rgb565(color1)]
            if color0 > color1:
                colors.extend([
                    _mix(colors[0], colors[1], 2, 1),
                    _mix(colors[0], colors[1], 1, 1),
                ])
            else:
                colors.extend([
                    _mix(colors[0], colors[1], 1, 1),
                    (0, 0, 0, 0),
                ])
            for pixel_y in range(4):
                for pixel_x in range(4):
                    x = block_x * 4 + pixel_x
                    y = block_y * 4 + pixel_y
                    if x >= width or y >= height:
                        continue
                    palette_index = (bits >> (pixel_y * 4 + pixel_x)) & 3
                    red, green, blue, alpha = colors[palette_index]
                    offset = (y * width + x) * 4
                    output[offset: offset + 4] = (red, green, blue, alpha)
    return bytes(output)


def _decode_dxt3(data: bytes, width: int, height: int) -> bytes:
    output = bytearray(width * height * 4)
    blocks_wide = (width + 3) // 4
    blocks_high = (height + 3) // 4
    pos = 0
    for block_y in range(blocks_high):
        for block_x in range(blocks_wide):
            alpha_block = data[pos: pos + 8]
            pos += 8
            color0, color1 = struct.unpack_from("<HH", data, pos)
            pos += 4
            bits = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            colors = [_expand_rgb565(color0), _expand_rgb565(color1)]
            if color0 > color1:
                colors.extend([
                    _mix(colors[0], colors[1], 2, 1),
                    _mix(colors[0], colors[1], 1, 1),
                ])
            else:
                colors.extend([
                    _mix(colors[0], colors[1], 1, 1),
                    (0, 0, 0, 0),
                ])
            for pixel_y in range(4):
                for pixel_x in range(4):
                    x = block_x * 4 + pixel_x
                    y = block_y * 4 + pixel_y
                    if x >= width or y >= height:
                        continue
                    alpha_nibble = (alpha_block[pixel_y * 2 + pixel_x // 2] >> (4 * (pixel_x % 2))) & 0xF
                    alpha = alpha_nibble * 17
                    palette_index = (bits >> (pixel_y * 4 + pixel_x)) & 3
                    red, green, blue, _ = colors[palette_index]
                    offset = (y * width + x) * 4
                    output[offset: offset + 4] = (red, green, blue, alpha)
    return bytes(output)


def _decode_dxt5(data: bytes, width: int, height: int) -> bytes:
    output = bytearray(width * height * 4)
    blocks_wide = (width + 3) // 4
    blocks_high = (height + 3) // 4
    pos = 0
    for block_y in range(blocks_high):
        for block_x in range(blocks_wide):
            alpha0, alpha1 = data[pos], data[pos + 1]
            pos += 2
            alpha_bits = 0
            for shift in range(6):
                alpha_bits |= data[pos] << (8 * shift)
                pos += 1
            if alpha0 > alpha1:
                alpha_lut = [
                    alpha0,
                    alpha1,
                    (6 * alpha0 + 1 * alpha1) // 7,
                    (5 * alpha0 + 2 * alpha1) // 7,
                    (4 * alpha0 + 3 * alpha1) // 7,
                    (3 * alpha0 + 4 * alpha1) // 7,
                    (2 * alpha0 + 5 * alpha1) // 7,
                    (1 * alpha0 + 6 * alpha1) // 7,
                ]
            else:
                alpha_lut = [
                    alpha0,
                    alpha1,
                    (4 * alpha0 + 1 * alpha1) // 5,
                    (3 * alpha0 + 2 * alpha1) // 5,
                    (2 * alpha0 + 3 * alpha1) // 5,
                    (1 * alpha0 + 4 * alpha1) // 5,
                    0,
                    255,
                ]
            color0, color1 = struct.unpack_from("<HH", data, pos)
            pos += 4
            bits = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            colors = [_expand_rgb565(color0), _expand_rgb565(color1)]
            if color0 > color1:
                colors.extend([
                    _mix(colors[0], colors[1], 2, 1),
                    _mix(colors[0], colors[1], 1, 1),
                ])
            else:
                colors.extend([
                    _mix(colors[0], colors[1], 1, 1),
                    (0, 0, 0, 0),
                ])
            for pixel_y in range(4):
                for pixel_x in range(4):
                    x = block_x * 4 + pixel_x
                    y = block_y * 4 + pixel_y
                    if x >= width or y >= height:
                        continue
                    alpha_index = (alpha_bits >> (pixel_y * 12 + pixel_x * 3)) & 7
                    alpha = alpha_lut[alpha_index]
                    palette_index = (bits >> (pixel_y * 4 + pixel_x)) & 3
                    red, green, blue, _ = colors[palette_index]
                    offset = (y * width + x) * 4
                    output[offset: offset + 4] = (red, green, blue, alpha)
    return bytes(output)


def resolve_game_root() -> Path | None:
    env = os.environ.get("CIV6_GAME_ROOT", "").strip()
    if env:
        candidate = Path(env)
        if candidate.is_dir():
            return candidate
    steam = Path("D:/SteamLibrary/steamapps/common")
    for name in (
        "Sid Meier's Civilization VI",
        "Sid Meier's Civilization VI Gathering Storm",
    ):
        candidate = steam / name
        if (candidate / "Base" / "Assets" / "UI" / "Icons").is_dir():
            return candidate
    return None


def resolve_pantry_textures() -> Path | None:
    env = os.environ.get("CIV6_SDK_PANTRY", "").strip()
    if env:
        candidate = Path(env)
        if candidate.is_dir():
            return candidate
    sdk = Path("D:/SteamLibrary/steamapps/common/Sid Meier's Civilization VI SDK Assets")
    candidate = sdk / "Civ6" / "pantry" / "Textures"
    return candidate if candidate.is_dir() else None


def icons_xml_dir() -> Path | None:
    game_root = resolve_game_root()
    if game_root is None:
        return None
    icons = game_root / "Base" / "Assets" / "UI" / "Icons"
    return icons if icons.is_dir() else None


@lru_cache(maxsize=1)
def _parse_icon_catalog() -> dict[str, tuple[str, int, int, int]]:
    """Map ICON_* name -> (dds filename, icon_size, icons_per_row, index)."""
    icons_dir = icons_xml_dir()
    if icons_dir is None:
        return {}
    atlases: dict[tuple[str, int], tuple[int, int, str]] = {}
    definitions: dict[str, tuple[str, int]] = {}
    for xml_name in _ICON_XML_GLOBS:
        xml_path = icons_dir / xml_name
        if not xml_path.is_file():
            continue
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
            r'<Row\s+Name="([^"]+)"\s+IconSize="(\d+)"\s+IconsPerRow="(\d+)"\s+IconsPerColumn="(\d+)"\s+Filename="([^"]+)"',
            text,
        ):
            atlas_name, icon_size, per_row, _per_col, filename = match.groups()
            if "_FOW" in atlas_name or "_PORTRAIT" in filename.upper():
                continue
            key = (atlas_name, int(icon_size))
            atlases[key] = (int(per_row), int(icon_size), filename)
        for match in re.finditer(
            r'<Row\s+Name="(ICON_[^"]+)"\s+'
            r'(?:Atlas="([^"]+)"\s+Index="(\d+)"|Index="(\d+)"\s+Atlas="([^"]+)")',
            text,
        ):
            if match.group(2) is not None:
                icon_name, atlas_name, index = match.group(1), match.group(2), int(match.group(3))
            else:
                icon_name, index, atlas_name = match.group(1), int(match.group(4)), match.group(5)
            if "_FOW" in icon_name or "_PORTRAIT" in icon_name:
                continue
            definitions[icon_name] = (atlas_name, index)

    catalog: dict[str, tuple[str, int, int, int]] = {}
    # Prefer larger atlases — Units32 tiles are low-detail silhouettes; Units50 has readable art.
    preferred_sizes = (50, 64, 80, 38, 32, 22, 128, 256)
    for icon_name, (atlas_name, index) in definitions.items():
        chosen: tuple[str, int, int, int] | None = None
        for size in preferred_sizes:
            atlas = atlases.get((atlas_name, size))
            if atlas is None:
                continue
            per_row, icon_size, filename = atlas
            chosen = (filename if filename.endswith(".dds") else f"{filename}.dds", icon_size, per_row, index)
            break
        if chosen is not None:
            catalog[icon_name] = chosen
    return catalog


def icon_name_for_unit(unit_type_id: str) -> str:
    unit_type = str(unit_type_id or "").strip().upper()
    if not unit_type:
        return "ICON_UNIT_WARRIOR"
    if unit_type.startswith("ICON_"):
        return unit_type
    if unit_type.startswith("UNIT_"):
        return f"ICON_{unit_type}"
    return f"ICON_UNIT_{unit_type}"


def icon_name_for_resource(resource_id: str) -> str:
    resource = str(resource_id or "").strip().upper()
    if not resource:
        return ""
    if resource.startswith("ICON_"):
        return resource
    if resource.startswith("RESOURCE_"):
        return f"ICON_{resource}"
    return f"ICON_RESOURCE_{resource}"


def icon_slug(icon_name: str) -> str:
    return str(icon_name or "").strip()


def _crop_alpha_bbox(image: Any, alpha_threshold: int = 8) -> Any:
    alpha = image.split()[3]
    bbox = alpha.point(lambda value: 255 if value > alpha_threshold else 0).getbbox()
    if bbox is None:
        return image
    return image.crop(bbox)


def load_rgba_image(path: Path) -> Any | None:
    from PIL import Image

    if not path.is_file():
        return None
    if path.suffix.lower() == ".dds":
        decoded = read_dds_rgba(path)
        if decoded is None:
            return None
        pixels, width, height = decoded
        return Image.frombytes("RGBA", (width, height), pixels)
    try:
        return Image.open(path).convert("RGBA")
    except OSError:
        return None


def _save_png(image: Any, path: Path, size: int | None = None) -> None:
    from PIL import Image

    work = image
    if size is not None and work.size != (size, size):
        work = work.resize((size, size), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    work.save(path)


def extract_icon(icon_name: str, out_size: int = 32) -> Path | None:
    catalog = _parse_icon_catalog()
    entry = catalog.get(icon_name)
    pantry = resolve_pantry_textures()
    if entry is None or pantry is None:
        return None
    filename, icon_size, per_row, index = entry
    dds_path = pantry / filename
    if not dds_path.is_file():
        return None
    image = load_rgba_image(dds_path)
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
    out_path = ICON_CACHE_DIR / f"{icon_name}_atlas{icon_size}.png"
    _save_png(tile, out_path, out_size)
    return out_path


def icon_png_path(icon_name: str, out_size: int = 32) -> Path | None:
    catalog = _parse_icon_catalog()
    entry = catalog.get(icon_name)
    if entry is not None:
        _, atlas_size, _, _ = entry
        cached = ICON_CACHE_DIR / f"{icon_name}_atlas{atlas_size}.png"
        if cached.is_file():
            return cached
    return extract_icon(icon_name, out_size=out_size)


def civ6_terrain_labels() -> dict[str, str]:
    """Human labels for TERRAIN_* ids from Civ6 Terrains.xml when available."""
    cached = _load_civ6_terrain_labels()
    if cached:
        return cached
    return {
        "TERRAIN_GRASS": "Grass",
        "TERRAIN_PLAINS": "Plains",
        "TERRAIN_DESERT": "Desert",
        "TERRAIN_TUNDRA": "Tundra",
        "TERRAIN_SNOW": "Snow",
        "TERRAIN_COAST": "Coast",
        "TERRAIN_OCEAN": "Ocean",
    }


@lru_cache(maxsize=1)
def _load_civ6_terrain_labels() -> dict[str, str]:
    game_root = resolve_game_root()
    if game_root is None:
        return {}
    xml_path = game_root / "Base" / "Assets" / "Gameplay" / "Data" / "Terrains.xml"
    if not xml_path.is_file():
        return {}
    labels: dict[str, str] = {}
    text = xml_path.read_text(encoding="utf-8", errors="replace")
    for match in re.finditer(
        r'<Row\s+TerrainType="(TERRAIN_[^"]+)"\s+Name="LOC_TERRAIN_([^"]+)_NAME"',
        text,
    ):
        terrain_type, token = match.groups()
        labels[terrain_type] = token.replace("_", " ").title()
    return labels


def civ6_feature_labels() -> dict[str, str]:
    cached = _load_civ6_feature_labels()
    if cached:
        return cached
    return {
        "FEATURE_FOREST": "Forest",
        "FEATURE_JUNGLE": "Jungle",
        "FEATURE_MARSH": "Marsh",
        "FEATURE_OASIS": "Oasis",
        "FEATURE_FLOODPLAINS": "Floodplains",
        "FEATURE_ICE": "Ice",
    }


@lru_cache(maxsize=1)
def _load_civ6_feature_labels() -> dict[str, str]:
    game_root = resolve_game_root()
    if game_root is None:
        return {}
    xml_path = game_root / "Base" / "Assets" / "Gameplay" / "Data" / "Features.xml"
    if not xml_path.is_file():
        return {}
    labels: dict[str, str] = {}
    text = xml_path.read_text(encoding="utf-8", errors="replace")
    for match in re.finditer(
        r'<Row\s+FeatureType="(FEATURE_[^"]+)"\s+Name="LOC_FEATURE_([^"]+)_NAME"',
        text,
    ):
        feature_type, token = match.groups()
        labels[feature_type] = token.replace("_", " ").title()
    return labels


def _parse_terrain_id(terrain_id: str) -> tuple[str, bool, bool]:
    upper = terrain_id.strip().upper()
    peak = upper.endswith("_MOUNTAIN")
    hills = upper.endswith("_HILLS")
    base = upper
    if peak:
        base = base[:-9]
    elif hills:
        base = base[:-6]
    return base, hills, peak


def strategic_dds_name(plot: dict[str, Any] | None) -> str | None:
    if not isinstance(plot, dict):
        return None
    feature_id = plot.get("feature_id")
    if isinstance(feature_id, str):
        mapped = _FEATURE_STRATEGIC.get(feature_id.upper())
        if mapped is not None:
            return mapped
    terrain_id = plot.get("terrain_id")
    if not isinstance(terrain_id, str):
        return None
    base_id, parsed_hills, parsed_peak = _parse_terrain_id(terrain_id)
    hills = bool(plot.get("hills")) or parsed_hills
    peak = bool(plot.get("peak")) or parsed_peak
    base = _TERRAIN_SUFFIX.get(base_id)
    if base is None:
        base = _TERRAIN_SUFFIX.get(terrain_id.upper())
    if base is None:
        return None
    if peak:
        suffix = f"{base}_Mountain"
    elif hills:
        suffix = f"{base}_Hills"
    else:
        suffix = base
    candidate = f"StrategicView_Terrain_{suffix}.dds"
    pantry = resolve_pantry_textures()
    if pantry is not None and (pantry / candidate).is_file():
        return candidate
    if peak and pantry is not None and (pantry / "StrategicView_Terrain_Mountain.dds").is_file():
        return "StrategicView_Terrain_Mountain.dds"
    return candidate


def strategic_png_path(plot: dict[str, Any] | None) -> Path | None:
    dds_name = strategic_dds_name(plot)
    if dds_name is None:
        return None
    cached = STRATEGIC_CACHE_DIR / dds_name.replace(".dds", ".crop.png")
    if cached.is_file():
        return cached
    pantry = resolve_pantry_textures()
    if pantry is None:
        return None
    source = pantry / dds_name
    if not source.is_file():
        return None
    image = load_rgba_image(source)
    if image is None:
        return None
    image = _crop_alpha_bbox(image)
    _save_png(image, cached)
    return cached


def ensure_civ6_assets(
    *,
    icon_size: int = 32,
    extract_units: bool = True,
    extract_resources: bool = True,
    extract_districts: bool = True,
) -> dict[str, int]:
    """Extract real Civ6 pantry icons into sidecar/assets/civ6/icons/."""
    counts = {"units": 0, "resources": 0, "districts": 0, "buildings": 0}
    if resolve_pantry_textures() is None or icons_xml_dir() is None:
        return counts
    catalog = _parse_icon_catalog()
    for icon_name in sorted(catalog):
        if extract_units and icon_name.startswith("ICON_UNIT_"):
            if extract_icon(icon_name, out_size=icon_size):
                counts["units"] += 1
        elif extract_resources and icon_name.startswith("ICON_RESOURCE_"):
            if extract_icon(icon_name, out_size=icon_size):
                counts["resources"] += 1
        elif extract_districts and icon_name.startswith("ICON_DISTRICT_"):
            if extract_icon(icon_name, out_size=icon_size):
                counts["districts"] += 1
        elif icon_name.startswith("ICON_BUILDING_"):
            if extract_icon(icon_name, out_size=icon_size):
                counts["buildings"] += 1
    for icon_name in ("ICON_DISTRICT_CITY_CENTER", "ICON_BUILDING_PALACE"):
        if icon_png_path(icon_name, out_size=icon_size):
            counts["districts"] += int(icon_name.startswith("ICON_DISTRICT_"))
            counts["buildings"] += int(icon_name.startswith("ICON_BUILDING_"))
    return counts


def assets_available() -> bool:
    return resolve_pantry_textures() is not None and icons_xml_dir() is not None
