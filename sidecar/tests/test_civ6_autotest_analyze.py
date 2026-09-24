"""Tests for Civ VI autotest session analyzer."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sidecar.civ6_autotest_analyze import analyze_autotest_session

ROOT = Path(__file__).resolve().parents[2]


class Civ6AutotestAnalyzeTests(unittest.TestCase):
    def test_analyze_fixture_session_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "autotest-session"
            player = session / "PLAYER_0"
            player.mkdir(parents=True)
            journal = player / "journal.jsonl"
            journal.write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "private": {"turn": 2, "player_id": "PLAYER_0"},
                        "validated": {"commands": [{"command_id": "CMD_research_TECH_MINING"}]},
                        "commands": [{"kind": "set_research_tech", "command_id": "CMD_research_TECH_MINING"}],
                        "metrics": {"wall_ms": 100, "usage": {"total_tokens": 50}},
                    }
                ) + "\n",
                encoding="utf-8",
            )
            apply = player / "apply-results.jsonl"
            apply.write_text(
                json.dumps(
                    {
                        "event": "apply_result",
                        "turn": 2,
                        "player_id": "PLAYER_0",
                        "kind": "set_research_tech",
                        "ok": True,
                        "empire": {"gold": 10},
                    }
                ) + "\n",
                encoding="utf-8",
            )
            io_dir = player / "io_logs"
            io_dir.mkdir()
            io_dir.joinpath("journal_input.json").write_text("{}", encoding="utf-8")
            (session / "turn_metrics.jsonl").write_text(
                json.dumps({"turn": 2, "player_id": "PLAYER_0", "status": "approved"}) + "\n",
                encoding="utf-8",
            )
            report = analyze_autotest_session(session)
            self.assertIn("PLAYER_0", report["players"])
            self.assertEqual(report["summary"]["journal_status"]["approved"], 1)
            self.assertEqual(report["summary"]["apply_failures"], 0)


if __name__ == "__main__":
    unittest.main()
