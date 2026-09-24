"""Tests for Civ VI seat-type experiment analyzer."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANALYZER = ROOT / "scripts" / "testbed" / "civ6_seat_experiment_analyze.py"
SAMPLE = ROOT / "fixtures" / "civ6" / "seat-experiment-sample.jsonl"
RUN_CIV6 = ROOT / "sidecar" / "run_civ6.py"
MINIMAL = ROOT / "fixtures" / "civ6" / "snapshot-turn-runtime-minimal.json"


class Civ6SeatExperimentTests(unittest.TestCase):
    def test_analyzer_detects_production_overwrite(self):
        proc = subprocess.run(
            [sys.executable, str(ANALYZER), str(SAMPLE)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )
        self.assertEqual(0, proc.returncode, proc.stderr or proc.stdout)
        self.assertIn("reapply_production_after_native_ai", proc.stdout)
        self.assertIn("production overwrites: 1", proc.stdout)

    def test_run_civ6_seat_experiment_response(self):
        snapshot = json.loads(MINIMAL.read_text(encoding="utf-8"))
        snapshot["civ6"]["experiment_city_id"] = "CITY_1"
        snapshot["civ6"]["experiment_build_id"] = "TECH_MINING"
        snapshot["legal_commands"].insert(
            0,
            {
                "command_id": "CMD_exp_prod_MONUMENT",
                "kind": "queue_production",
                "fixed_arguments": {"city_id": "CITY_1", "build_id": "BUILDING_MONUMENT"},
                "parameter_domains": {},
                "affected_ids": [],
                "runtime_status": "implemented_untested",
            },
        )
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "snap.json"
            snap_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(RUN_CIV6),
                    "--state",
                    str(snap_path),
                    "--from-game",
                    "--seat-experiment",
                    "--journal",
                    str(Path(tmp) / "journal.jsonl"),
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr or proc.stdout)
            record = json.loads(proc.stdout.strip().splitlines()[-1])
            commands = record.get("commands") or []
            self.assertGreaterEqual(len(commands), 1)
            self.assertEqual("CMD_exp_prod_MONUMENT", commands[0]["command_id"])


if __name__ == "__main__":
    unittest.main()
