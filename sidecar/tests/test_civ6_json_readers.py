"""Snapshot JSON may contain a raw tab from a Lua error string. Readers must
accept it, and an unreadable snapshot must not look like a finished decision."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / "scripts", ROOT / "scripts" / "testbed"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from sidecar import run_civ6  # noqa: E402
import civ6_sidecar_jobs as jobs  # noqa: E402


class JsonReaderTests(unittest.TestCase):
    def test_both_readers_accept_a_raw_tab_inside_a_string(self) -> None:
        payload = '{"history": {"memory_summary": "lua error:\there"}}'.replace("\\t", "\t")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(payload)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text(payload, encoding="utf-8")
            loaded = run_civ6._read(path)
            self.assertIn("\t", loaded["history"]["memory_summary"])
            again = jobs._read_json(path)
            self.assertEqual(loaded, again)

    def test_unreadable_snapshot_does_not_count_as_decided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            player = Path(tmp) / "PLAYER_3"
            player.mkdir()
            (player / "decision.json").write_text(
                json.dumps({"status": "approved", "metrics": {"turn": 5}}),
                encoding="utf-8",
            )
            (player / "snapshot.json").write_text('{"decision": {"turn": 5}, "history": "', encoding="utf-8")
            with self.assertLogs("civ6_sidecar_jobs", level="WARNING") as logs:
                self.assertFalse(jobs.decision_suppresses_sidecar(player))
            self.assertTrue(any("could not be parsed" in line for line in logs.output))

    def test_parsed_snapshot_with_a_raw_tab_still_matches_the_decision_turn(self) -> None:
        payload = '{"decision": {"turn": 5}, "history": {"memory_summary": "err\there"}}'.replace("\\t", "\t")
        with tempfile.TemporaryDirectory() as tmp:
            player = Path(tmp) / "PLAYER_3"
            player.mkdir()
            (player / "decision.json").write_text(
                json.dumps({"status": "approved", "metrics": {"turn": 5}}),
                encoding="utf-8",
            )
            (player / "snapshot.json").write_text(payload, encoding="utf-8")
            self.assertTrue(jobs.decision_suppresses_sidecar(player))
