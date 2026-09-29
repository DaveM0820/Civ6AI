"""Regression: a real in-game turn-1 snapshot (with audit fields such as
unit health_percent, empire amenities and known_map explored_percent) must pass
the runtime schema. Sample fixtures missed this and blocked every live pulse."""
import json
import unittest
from pathlib import Path

from sidecar import civ6_adapter

ROOT = Path(__file__).resolve().parents[2]


class LiveSnapshotSchemaTest(unittest.TestCase):
    def test_live_runtime_snapshot_upgrades(self):
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t1-snapshot.json").read_text(encoding="utf-8"))
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        self.assertEqual(snap["your_units"][0]["health_percent"], 100)
        self.assertIn("amenities", snap["your_empire"])
        self.assertIn("explored_percent", snap["known_map"])

    def test_live_snapshot_with_city_upgrades(self):
        # Turn-4 snapshot of a seat that founded its capital: city amenities and
        # defense.health_percent made every seat with a city fail the sidecar
        # (empty-apply fallback for all but city-less seats).
        raw = json.loads((ROOT / "fixtures" / "civ6" / "live-runtime-t4-city-snapshot.json").read_text(encoding="utf-8"))
        snap = civ6_adapter.upgrade_runtime_snapshot(raw)
        city = snap["your_cities"][0]
        self.assertIn("amenities", city)
        self.assertEqual(100, city["defense"]["health_percent"])


if __name__ == "__main__":
    unittest.main()
