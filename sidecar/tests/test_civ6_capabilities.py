"""Tests for civ6-command-capabilities.json generator output."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "testbed" / "generate_civ6_capabilities.py"
CAPABILITIES = ROOT / "config" / "civ6-command-capabilities.json"


class Civ6CapabilitiesTests(unittest.TestCase):
    def test_regenerate_capabilities(self):
        subprocess.run([sys.executable, str(GENERATOR)], check=True, cwd=ROOT)
        doc = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
        self.assertEqual("civ6ai-command-capabilities/1", doc["schema_version"])
        kinds = {row["kind"] for row in doc["capabilities"]}
        self.assertIn("set_research_tech", kinds)
        self.assertIn("found_religion", kinds)
        self.assertIn("clear_production_queue", kinds)
        self.assertIn("chat", kinds)
        chat = next(row for row in doc["capabilities"] if row["kind"] == "chat")
        self.assertEqual("v1", chat["tier"])
        found = next(row for row in doc["capabilities"] if row["kind"] == "found_religion")
        self.assertEqual("v1", found["tier"])
        self.assertGreaterEqual(len(kinds), 65)


if __name__ == "__main__":
    unittest.main()
