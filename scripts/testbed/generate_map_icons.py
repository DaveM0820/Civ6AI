"""Generate minimap marker PNGs (Pillow). Sources: Fairline/Unciv (MIT), local Civ4/Civ6 installs."""

from __future__ import annotations

import argparse
import re
import struct
import sys
import urllib.parse
import urllib.request
import zlib
from io import BytesIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import civ6_assets
from sidecar.map_icons import ICON_DIR, ICON_SIZE

ART_XML = ROOT / "artifacts" / "AdvCiv-SAS-ai-slice" / "Assets" / "XML" / "Art" / "CIV4ArtDefines_Unit.xml"
BUTTON_CELL = 32

FAIRLINE_BASE = (
    "https://raw.githubusercontent.com/RobLoach/Fairline-Unitset/master/"
    "Images/TileSets/Fairline/Units"
)
FAIRLINE_UNIT_FILES: dict[str, str] = {
    "unit_settler": "Settler.png",
    "unit_worker": "Worker.png",
    "unit_scout": "Scout.png",
    "unit_archer": "Archer.png",
    "unit_galley": "Galley.png",
    "unit_warrior": "Warrior.png",
    "unit_spear": "Spearman.png",
    "unit_sword": "Swordsman.png",
}

CIV6_UNIT_ICONS: dict[str, str] = {
    "unit_settler": "ICON_UNIT_SETTLER",
    "unit_worker": "ICON_UNIT_BUILDER",
    "unit_scout": "ICON_UNIT_SCOUT",
    "unit_archer": "ICON_UNIT_ARCHER",
    "unit_galley": "ICON_UNIT_GALLEY",
    "unit_warrior": "ICON_UNIT_WARRIOR",
    "unit_spear": "ICON_UNIT_SPEARMAN",
    "unit_sword": "ICON_UNIT_SWORDSMAN",
}


def _draw_city(draw, size: int, fill: str, stroke: str) -> None:
    from PIL import ImageDraw

    w = size
    base = int(w * 0.55)
    h = int(w * 0.45)
    x0 = (w - base) // 2
    y0 = w - h - 2
    draw.rectangle([x0, y0, x0 + base, y0 + h], fill=fill, outline=stroke)
    roof = [x0 - 2, y0, x0 + base // 2, y0 - int(h * 0.35), x0 + base + 2, y0]
    draw.polygon(roof, fill=fill, outline=stroke)


def _draw_capital(draw, size: int) -> None:
    from PIL import ImageDraw

    _draw_city(draw, size, "#f4c040", "#804000")
    cx, cy = size // 2, size // 4
    r = max(2, size // 6)
    draw.polygon(
        [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
        fill="#fff8c0",
        outline="#804000",
    )


def _draw_worker(draw, size: int) -> None:
    from PIL import ImageDraw

    cx = size // 2
    draw.line([(cx, 4), (cx, size - 4)], fill="#c0c0c0", width=2)
    draw.line([(cx - 5, size - 6), (cx + 5, size - 6)], fill="#888", width=2)


def _draw_settler(draw, size: int) -> None:
    from PIL import ImageDraw

    cx = size // 2
    draw.ellipse([cx - 4, 3, cx + 4, 11], fill="#e8d8b0", outline="#604020")
    draw.rectangle([cx - 3, 10, cx + 3, size - 3], fill="#6a9a5a", outline="#304020")


def _draw_scout(draw, size: int) -> None:
    from PIL import ImageDraw

    draw.ellipse([4, 4, size - 4, size - 4], fill="#8ec8e8", outline="#206080")
    draw.ellipse([size // 2 - 2, size // 2 - 2, size // 2 + 2, size // 2 + 2], fill="#fff")


def _draw_archer(draw, size: int) -> None:
    from PIL import ImageDraw

    draw.arc([3, 3, size - 3, size - 3], 200, 340, fill="#c0a060", width=2)
    draw.line([(size // 2, 4), (size // 2, size - 4)], fill="#888", width=1)


def _draw_galley(draw, size: int) -> None:
    from PIL import ImageDraw

    draw.polygon(
        [(3, size - 5), (size // 2, 4), (size - 3, size - 5)],
        fill="#5a8ab0",
        outline="#204060",
    )
    draw.line([(size // 2, 4), (size // 2, 2)], fill="#888", width=1)


def _draw_warrior(draw, size: int) -> None:
    from PIL import ImageDraw

    draw.rectangle([size // 2 - 1, 3, size // 2 + 1, size - 4], fill="#aaa", outline="#444")
    draw.polygon([(size // 2 - 5, 6), (size // 2 + 5, 6), (size // 2, 2)], fill="#c44")


def _draw_default(draw, size: int, fill: str) -> None:
    from PIL import ImageDraw

    draw.ellipse([3, 3, size - 3, size - 3], fill=fill, outline="#333")


def _save_icon_image(img, out_path: Path, size: int) -> None:
    from PIL import Image

    if img.size != (size, size):
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def _tint_image_red(img) -> "Image.Image":
    from PIL import Image

    tinted = img.copy().convert("RGBA")
    red = Image.new("RGBA", tinted.size, (255, 80, 80, 90))
    return Image.alpha_composite(tinted, red)


def fetch_fairline_icons(out_dir: Path, size: int) -> int:
    from PIL import Image

    count = 0
    for slug, filename in FAIRLINE_UNIT_FILES.items():
        url = f"{FAIRLINE_BASE}/{urllib.parse.quote(filename)}"
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                raw = response.read()
        except OSError as exc:
            print("fairline download failed", slug, exc)
            continue
        img = Image.open(BytesIO(raw)).convert("RGBA")
        _save_icon_image(img, out_dir / f"{slug}.png", size)
        print("fairline", slug, "from", filename)
        count += 1

    warrior = out_dir / "unit_warrior.png"
    if warrior.is_file():
        from PIL import Image

        _save_icon_image(_tint_image_red(Image.open(warrior)), out_dir / "unit_foreign.png", size)
        print("fairline unit_foreign (tinted warrior)")
        count += 1

    default_src = out_dir / "unit_scout.png"
    if default_src.is_file():
        from PIL import Image

        _save_icon_image(Image.open(default_src), out_dir / "unit_default.png", size)
        print("fairline unit_default (scout)")
        count += 1

    return count


def _parse_civ6_icon_tables(icons_dir: Path) -> tuple[dict[str, tuple[int, int, int, str]], dict[str, tuple[str, int]]]:
    """Return atlas rows and icon definitions from Civ6 Icons/*.xml."""
    atlases: dict[str, tuple[int, int, int, str]] = {}
    definitions: dict[str, tuple[str, int]] = {}
    if not icons_dir.is_dir():
        return atlases, definitions
    for xml_path in sorted(icons_dir.glob("*.xml")):
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        for block in re.finditer(
            r"<Row\s+Name=\"([^\"]+)\"\s+IconSize=\"(\d+)\"\s+IconsPerRow=\"(\d+)\"\s+IconsPerColumn=\"(\d+)\"\s+Filename=\"([^\"]+)\"",
            text,
        ):
            name, icon_size, per_row, per_col, filename = block.groups()
            atlases[name] = (int(icon_size), int(per_row), int(per_col), filename)
        for block in re.finditer(
            r"<Row\s+Name=\"(ICON_[^\"]+)\"\s+(?:Index=\"(\d+)\"\s+)?Atlas=\"([^\"]+)\"|"
            r"<Row\s+Name=\"(ICON_[^\"]+)\"\s+Atlas=\"([^\"]+)\"\s+Index=\"(\d+)\"",
            text,
        ):
            if block.group(1):
                icon_name, index, atlas = block.group(1), int(block.group(2) or 0), block.group(3)
            else:
                icon_name, atlas, index = block.group(4), block.group(5), int(block.group(6))
            if "_PORTRAIT" in icon_name or "_FOW" in icon_name:
                continue
            definitions[icon_name] = (atlas, index)
    return atlases, definitions


def extract_civ6_icons(civ6_root: Path, out_dir: Path, size: int) -> int:
    from PIL import Image

    icons_dir = civ6_root / "Base" / "Assets" / "UI" / "Icons"
    textures_dir = civ6_root / "Base" / "Assets" / "UI" / "Art" / "Icons"
    atlases, definitions = _parse_civ6_icon_tables(icons_dir)
    if not atlases:
        print("civ6: no icon XML in", icons_dir)
        return 0

    count = 0
    for slug, icon_name in CIV6_UNIT_ICONS.items():
        resolved = definitions.get(icon_name)
        if resolved is None:
            continue
        atlas_name, index = resolved
        atlas_row = atlases.get(atlas_name)
        if atlas_row is None:
            continue
        icon_size, per_row, _per_col, filename = atlas_row
        dds_candidates = [
            textures_dir / filename,
            icons_dir / filename,
            civ6_root / "Base" / "Assets" / "UI" / "Art" / "Textures" / filename,
        ]
        dds_path = next((p for p in dds_candidates if p.is_file()), None)
        if dds_path is None:
            print("civ6: missing atlas file", filename)
            continue
        decoded = _read_dds_rgba(dds_path)
        if decoded is None:
            print("civ6: could not decode", dds_path)
            continue
        pixels, aw, ah = decoded
        base = Image.frombytes("RGBA", (aw, ah), pixels)
        col = index % per_row
        row = index // per_row
        x, y = col * icon_size, row * icon_size
        tile = base.crop((x, y, x + icon_size, y + icon_size))
        _save_icon_image(tile, out_dir / f"{slug}.png", size)
        print("civ6", slug, f"from {filename} index {index}")
        count += 1

    if count and (out_dir / "unit_warrior.png").is_file():
        from PIL import Image

        _save_icon_image(
            _tint_image_red(Image.open(out_dir / "unit_warrior.png")),
            out_dir / "unit_foreign.png",
            size,
        )
    if count and (out_dir / "unit_scout.png").is_file():
        from PIL import Image

        _save_icon_image(Image.open(out_dir / "unit_scout.png"), out_dir / "unit_default.png", size)
    return count


def scan_civ5_unpacked_icons(civ5_root: Path, out_dir: Path, size: int) -> int:
    """Use unpacked Civ5 PNG/DDS from Resource/ after FPK extraction (see CivFanatics guides)."""
    from PIL import Image

    search_roots = [
        civ5_root / "Resource" / "DX9",
        civ5_root / "Assets" / "UI" / "Art" / "Icons" / "Units",
    ]
    name_map = {
        "settler": "unit_settler",
        "worker": "unit_worker",
        "scout": "unit_scout",
        "archer": "unit_archer",
        "galley": "unit_galley",
        "warrior": "unit_warrior",
        "spearman": "unit_spear",
        "swordsman": "unit_sword",
    }
    count = 0
    for root in search_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".png", ".dds"}:
                continue
            stem = path.stem.lower().replace("sv_", "")
            slug = name_map.get(stem)
            if slug is None:
                continue
            if path.suffix.lower() == ".dds":
                decoded = _read_dds_rgba(path)
                if decoded is None:
                    continue
                pixels, aw, ah = decoded
                img = Image.frombytes("RGBA", (aw, ah), pixels)
            else:
                img = Image.open(path).convert("RGBA")
            _save_icon_image(img, out_dir / f"{slug}.png", size)
            print("civ5", slug, "from", path)
            count += 1
    if not count:
        print(
            "civ5: no unpacked unit icons under Resource/DX9 or Assets/UI/Art/Icons/Units; "
            "unpack UITextures.fpk first (DragonUnpacker / Civ5 SDK Nexus)"
        )
    return count


def generate_builtin_icons(out_dir: Path, size: int, only_missing: bool = True) -> int:
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    specs: dict[str, Any] = {
        "city": lambda d: _draw_city(d, size, "#d0b060", "#604020"),
        "capital": lambda d: _draw_capital(d, size),
        "unit_settler": lambda d: _draw_settler(d, size),
        "unit_worker": lambda d: _draw_worker(d, size),
        "unit_scout": lambda d: _draw_scout(d, size),
        "unit_archer": lambda d: _draw_archer(d, size),
        "unit_galley": lambda d: _draw_galley(d, size),
        "unit_warrior": lambda d: _draw_warrior(d, size),
        "unit_spear": lambda d: _draw_warrior(d, size),
        "unit_sword": lambda d: _draw_warrior(d, size),
        "unit_default": lambda d: _draw_default(d, size, "#50d8f0"),
        "unit_foreign": lambda d: _draw_default(d, size, "#f05050"),
        "stack": lambda d: _draw_default(d, size, "#90ee90"),
    }
    for name, fn in specs.items():
        out_path = out_dir / f"{name}.png"
        if only_missing and out_path.is_file():
            continue
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        fn(draw)
        img.save(out_path)
        print("builtin", out_path)
        written += 1
    return written


def _parse_button_line(text: str) -> tuple[str, int, int] | None:
    m = re.search(r"Unit_Resource_Atlas\.dds,(\d+),(\d+)", text)
    if not m:
        return None
    return "unit_resource_atlas", int(m.group(1)), int(m.group(2))


def _read_dds_rgba(path: Path) -> tuple[bytes, int, int] | None:
    """Minimal DDS reader for uncompressed / DXT1 (common Civ4 UI atlases)."""
    raw = path.read_bytes()
    if len(raw) < 128 or raw[:4] != b"DDS ":
        return None
    height, width = struct.unpack_from("<II", raw, 12)
    fourcc = raw[84:88]
    offset = 128
    if fourcc == b"DXT1":
        return _decode_dxt1(raw[offset:], width, height), width, height
    if fourcc == b"\x00\x00\x00\x00":
        bpp = struct.unpack_from("<I", raw, 88)[0]
        if bpp == 32:
            pixels = bytearray(width * height * 4)
            for i in range(width * height):
                b, g, r, a = raw[offset + 4 * i: offset + 4 * i + 4]
                pixels[4 * i: 4 * i + 4] = (r, g, b, a)
            return bytes(pixels), width, height
    return None


def _decode_dxt1(data: bytes, width: int, height: int) -> bytes:
    """Decode DXT1 block texture to RGBA bytes."""
    out = bytearray(width * height * 4)
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    pos = 0
    for by in range(bh):
        for bx in range(bw):
            c0, c1 = struct.unpack_from("<HH", data, pos)
            pos += 8
            bits = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            colors = [_expand_rgb565(c0), _expand_rgb565(c1)]
            if c0 > c1:
                colors.extend([
                    _mix(colors[0], colors[1], 2, 1),
                    _mix(colors[0], colors[1], 1, 1),
                ])
            else:
                colors.extend([
                    _mix(colors[0], colors[1], 1, 1),
                    (0, 0, 0, 0),
                ])
            for py in range(4):
                for px in range(4):
                    x, y = bx * 4 + px, by * 4 + py
                    if x >= width or y >= height:
                        continue
                    idx = (bits >> (py * 4 + px)) & 3
                    r, g, b, a = colors[idx]
                    o = (y * width + x) * 4
                    out[o:o + 4] = (r, g, b, a)
    return bytes(out)


def _expand_rgb565(c: int) -> tuple[int, int, int, int]:
    r = ((c >> 11) & 0x1f) * 255 // 31
    g = ((c >> 5) & 0x3f) * 255 // 63
    b = (c & 0x1f) * 255 // 31
    return r, g, b, 255


def _mix(a: tuple[int, int, int, int], b: tuple[int, int, int, int], w1: int, w2: int) -> tuple[int, int, int, int]:
    t = w1 + w2
    return tuple((a[i] * w1 + b[i] * w2) // t for i in range(3)) + (255,)


def extract_civ4_icons(bts_root: Path, out_dir: Path, size: int) -> int:
    from PIL import Image

    atlas = bts_root / "Assets" / "Art" / "Interface" / "Buttons" / "Unit_Resource_Atlas.dds"
    if not atlas.is_file():
        print("missing atlas", atlas)
        return 0
    decoded = _read_dds_rgba(atlas)
    if decoded is None:
        print("could not decode", atlas)
        return 0
    pixels, aw, ah = decoded
    base = Image.frombytes("RGBA", (aw, ah), pixels)
    if not ART_XML.is_file():
        return 0
    text = ART_XML.read_text(encoding="utf-8", errors="replace")
    mapping = {
        "ART_DEF_UNIT_SETTLER_MALE": "unit_settler",
        "ART_DEF_UNIT_WORKER": "unit_worker",
        "ART_DEF_UNIT_SCOUT": "unit_scout",
        "ART_DEF_UNIT_ARCHER": "unit_archer",
        "ART_DEF_UNIT_GALLEY": "unit_galley",
        "ART_DEF_UNIT_WARRIOR": "unit_warrior",
    }
    count = 0
    for art_type, slug in mapping.items():
        block = re.search(
            rf"<Type>{art_type}</Type>\s*<Button>[^<]*Unit_Resource_Atlas\.dds,(\d+),(\d+)",
            text,
        )
        if not block:
            continue
        col, row = int(block.group(1)), int(block.group(2))
        x, y = col * BUTTON_CELL, row * BUTTON_CELL
        tile = base.crop((x, y, x + BUTTON_CELL, y + BUTTON_CELL))
        tile = tile.resize((size, size), Image.Resampling.LANCZOS)
        out_dir.mkdir(parents=True, exist_ok=True)
        tile.save(out_dir / f"{slug}.png")
        print("extracted", slug, f"from atlas {col},{row}")
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build minimap marker PNGs from Fairline (web), Civ4/Civ5/Civ6 installs, or Pillow fallbacks."
    )
    parser.add_argument("--out", type=Path, default=ICON_DIR)
    parser.add_argument("--size", type=int, default=ICON_SIZE)
    parser.add_argument("--bts-root", type=Path, help="Civ4 BTS or mod root with Assets/Art")
    parser.add_argument("--civ6-root", type=Path, help="Civ6 install root (Sid Meier's Civilization VI)")
    parser.add_argument("--civ5-root", type=Path, help="Civ5 install root (unpacked Resource/DX9 icons)")
    parser.add_argument(
        "--fairline",
        action="store_true",
        help="Download Civ-style unit PNGs from RobLoach/Fairline-Unitset (MIT)",
    )
    parser.add_argument(
        "--civ6-sdk",
        action="store_true",
        help="Extract real Civ6 unit/resource/city icons from SDK Assets pantry + game XML",
    )
    args = parser.parse_args()
    sourced = 0
    if args.civ6_sdk or (args.civ6_root is None and civ6_assets.assets_available()):
        counts = civ6_assets.ensure_civ6_assets(icon_size=args.size)
        sourced += sum(counts.values())
        print("civ6 pantry", counts)
    if args.civ6_root:
        sourced += extract_civ6_icons(args.civ6_root, args.out, args.size)
    if args.civ5_root:
        sourced += scan_civ5_unpacked_icons(args.civ5_root, args.out, args.size)
    if args.bts_root:
        sourced += extract_civ4_icons(args.bts_root, args.out, args.size)
    if args.fairline:
        sourced += fetch_fairline_icons(args.out, args.size)
    builtin = generate_builtin_icons(args.out, args.size, only_missing=True)
    print(f"done: {sourced} sourced icons + {builtin} builtin fills in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
