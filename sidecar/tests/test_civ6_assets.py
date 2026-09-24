"""Tests for Civ6 pantry asset loader."""
from __future__ import annotations

import unittest
from pathlib import Path

from sidecar import civ6_assets

ROOT = Path(__file__).resolve().parents[2]


class Civ6AssetsTests(unittest.TestCase):
    def test_icon_name_for_unit(self):
        self.assertEqual(civ6_assets.icon_name_for_unit("UNIT_WARRIOR"), "ICON_UNIT_WARRIOR")
        self.assertEqual(civ6_assets.icon_name_for_unit("ICON_UNIT_SCOUT"), "ICON_UNIT_SCOUT")

    def test_icon_name_for_resource(self):
        self.assertEqual(civ6_assets.icon_name_for_resource("RESOURCE_IRON"), "ICON_RESOURCE_IRON")
        self.assertEqual(civ6_assets.icon_name_for_resource(""), "")

    def test_strategic_dds_name(self):
        plot = {"terrain_id": "TERRAIN_GRASS", "hills": False, "peak": False}
        self.assertTrue(str(civ6_assets.strategic_dds_name(plot)).startswith("StrategicView_Terrain_"))
        plot_hills = {"terrain_id": "TERRAIN_PLAINS", "hills": True, "peak": False}
        self.assertIn("Hills", civ6_assets.strategic_dds_name(plot_hills) or "")
        plot_forest = {"terrain_id": "TERRAIN_GRASS", "feature_id": "FEATURE_FOREST"}
        self.assertEqual(civ6_assets.strategic_dds_name(plot_forest), "StrategicView_Terrain_Forest.dds")

    def test_icon_catalog_scout_index(self):
        if not civ6_assets.assets_available():
            self.skipTest("Civ6 game + SDK pantry not installed")
        civ6_assets._parse_icon_catalog.cache_clear()
        entry = civ6_assets._parse_icon_catalog().get("ICON_UNIT_SCOUT")
        self.assertIsNotNone(entry)
        filename, icon_size, per_row, index = entry
        self.assertEqual("Units50.dds", filename)
        self.assertEqual(19, index)
        self.assertEqual(50, icon_size)
        if not civ6_assets.assets_available():
            self.skipTest("Civ6 game + SDK pantry not installed")
        path = civ6_assets.extract_icon("ICON_UNIT_SETTLER", out_size=32)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size, 100)

    def test_ensure_civ6_assets_when_available(self):
        if not civ6_assets.assets_available():
            self.skipTest("Civ6 game + SDK pantry not installed")
        counts = civ6_assets.ensure_civ6_assets(icon_size=32)
        self.assertGreater(counts["units"], 10)
        self.assertGreater(counts["resources"], 5)

    def test_terrain_labels_from_game_xml(self):
        if not civ6_assets.assets_available():
            self.skipTest("Civ6 game + SDK pantry not installed")
        labels = civ6_assets.civ6_terrain_labels()
        self.assertIn("TERRAIN_GRASS", labels)
        self.assertEqual(labels["TERRAIN_GRASS"], "Grass")
        self.assertIn("TERRAIN_TUNDRA", labels)
        self.assertIn("TERRAIN_DESERT", labels)


if __name__ == "__main__":
    unittest.main()
