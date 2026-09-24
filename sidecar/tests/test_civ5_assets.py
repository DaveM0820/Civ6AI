"""Tests for Civ5 asset loading and strategic layer mapping."""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sidecar import civ5_assets
from sidecar import civ5_fpk
from sidecar import map_icons


def _write_uncompressed_dds(path: Path, width: int, height: int, rgba: tuple[int, int, int, int]) -> None:
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 12, height)
    struct.pack_into("<I", header, 16, width)
    struct.pack_into("<I", header, 20, width * height * 4)
    struct.pack_into("<I", header, 88, 32)
    pixels = bytes(rgba) * (width * height)
    path.write_bytes(bytes(header) + pixels)


def _encode_fpk_name(name: str) -> bytes:
    raw = name.encode("utf-8")
    blocks = (len(raw) + 3) // 4
    padded = bytearray(blocks * 4)
    for index, byte in enumerate(raw):
        padded[index] = (byte + 1) % 256
    return struct.pack("<I", len(raw)) + bytes(padded)


def _build_fpk(path: Path, files: dict[str, bytes]) -> None:
    entries: list[tuple[str, bytes]] = list(files.items())
    header_size = 8
    for name, _data in entries:
        header_size += 4 + ((len(name) + 3) // 4) * 4 + 16
    offset = header_size
    body = bytearray()
    index_parts: list[bytes] = []
    for name, data in entries:
        index_parts.append(_encode_fpk_name(name))
        index_parts.append(struct.pack("<IIII", 0, 0, len(data), offset))
        body.extend(data)
        offset += len(data)
    path.write_bytes(struct.pack("<II", 2, len(entries)) + b"".join(index_parts) + bytes(body))


class Civ5FpkTests(unittest.TestCase):
    def test_read_fpk_index_and_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            fpk_path = Path(tmp) / "pack.fpk"
            payload = b"hello-dds-payload"
            _build_fpk(fpk_path, {"assets/UI/Art/StrategicView_Terrain_Grass.dds": payload})
            index = civ5_fpk.read_fpk_index(fpk_path)
            self.assertEqual(1, len(index))
            self.assertEqual(payload, civ5_fpk.extract_entry(index[0]))


class Civ5AssetsTests(unittest.TestCase):
    def test_strategic_layers_include_base_and_feature(self):
        plot = {
            "terrain_id": "TERRAIN_GRASS",
            "hills": True,
            "feature_id": "FEATURE_FOREST",
        }
        layers = civ5_assets.strategic_dds_layers(plot)
        self.assertIn("sv_terrainhexgrasslands.dds", layers)
        self.assertIn("sv_forest.dds", layers)
        self.assertNotEqual(layers[0], "sv_forest.dds")

    def test_resource_sv_uses_fish_overlay_name(self):
        self.assertEqual("sv_fish.dds", civ5_assets.resource_sv_dds_name("RESOURCE_FISH"))
        plot = {
            "terrain_id": "TERRAIN_COAST",
            "resource_id": "RESOURCE_FISH",
        }
        layers = civ5_assets.strategic_dds_layers(plot)
        self.assertIn("sv_terrainhexcoast.dds", layers)
        self.assertNotIn("sv_fish.dds", layers)

    def test_punch_near_black_makes_corners_transparent(self):
        from PIL import Image

        image = Image.new("RGBA", (3, 3), (0, 0, 0, 255))
        image.putpixel((1, 1), (220, 40, 40, 255))
        keyed = civ5_assets._punch_near_black_alpha(image)
        self.assertEqual(0, keyed.getpixel((0, 0))[3])
        self.assertEqual(255, keyed.getpixel((1, 1))[3])

    def test_unit_sv_candidates_include_jaguar(self):
        names = civ5_assets.unit_sv_dds_candidates("UNIT_AZTEC_JAGUAR")
        self.assertIn("sv_jaguar.dds", names)

    def test_city_sv_uses_small_city_overlay(self):
        self.assertEqual("sv_ancient_africa_small_city.dds", civ5_assets.city_sv_dds_name(False))
        self.assertEqual("sv_ancient_africa_medium_city.dds", civ5_assets.city_sv_dds_name(True))

    def test_resolve_game_root_from_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CivilizationV.exe").write_bytes(b"")
            fpk_dir = root / "Resource" / "DX9"
            fpk_dir.mkdir(parents=True)
            dds_name = "sv_terrainhexgrasslands.dds"
            dds_bytes = b"DDS payload placeholder"
            _build_fpk(fpk_dir / "UITextures.fpk", {dds_name: dds_bytes})
            with mock.patch.dict("os.environ", {"CIV5_INSTALL": str(root)}, clear=False):
                civ5_assets._fpk_indexes.cache_clear()
                self.assertEqual(root, civ5_assets.resolve_game_root())
                self.assertTrue(civ5_assets.assets_available())

    def test_map_icons_prefer_civ5_skip_civ6(self):
        map_icons.set_render_context(prefer_civ5=True)
        with mock.patch.object(civ5_assets, "assets_available", return_value=True):
            slug = map_icons.icon_slug_for_unit("UNIT_WARRIOR")
            self.assertTrue(slug.startswith("UNIT_FLAG:"))
            self.assertFalse(slug.startswith("ICON_"))
            self.assertEqual("RESOURCE_IRON", map_icons.resource_icon_slug("RESOURCE_IRON"))
        map_icons.set_render_context(prefer_civ5=False)


if __name__ == "__main__":
    unittest.main()
