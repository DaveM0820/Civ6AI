"""Tests for Civ VI run_civ6 file bridge."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sidecar import civ6_adapter
from sidecar import run_civ6

ROOT = Path(__file__).resolve().parents[2]
RUN_CIV6 = ROOT / "sidecar" / "run_civ6.py"
MINIMAL_SNAPSHOT = ROOT / "fixtures" / "civ6" / "snapshot-turn-runtime-minimal.json"


class Civ6RunBridgeTests(unittest.TestCase):
    def test_turn_metrics_use_real_visibility_and_per_player_board(self):
        snap = {
            "game": {"map_width": 10, "map_height": 10},
            "known_map": {
                "explored_percent": 50,
                "revealed_count": 12,
                "plots": [{}, {}, {}],
                "visibility_grid": ["???"],
            },
            "civ6": {"rankings": {"players": [
                {"player_id": "PLAYER_0", "score": 20, "era": "ERA_CLASSICAL", "era_score": 8,
                 "wonders": 1, "religion": "Buddhism", "cities": 2},
                {"player_id": "PLAYER_1", "score": 15, "religion_founded": {"name": "Catholicism"}},
            ]}},
        }
        board = run_civ6.board_for_turn_metrics(snap)
        # 12 of 100 tiles, not the cached 50 and not the three-plot crop.
        self.assertEqual(12, board["explored_percent"])
        self.assertEqual(12, board["revealed_tiles"])
        self.assertEqual(100, board["map_tiles"])
        snap["_explore_metric"] = {"delta": 3, "since_turn": 8}
        self.assertEqual(3, run_civ6.board_for_turn_metrics(snap)["revealed_delta"])
        rows = {row["player_id"]: row for row in board["players"]}
        self.assertEqual(rows["PLAYER_0"]["era"], "ERA_CLASSICAL")
        self.assertEqual(rows["PLAYER_0"]["era_score"], 8)
        self.assertEqual(rows["PLAYER_0"]["wonders"], 1)
        self.assertEqual(rows["PLAYER_0"]["religion"], "Buddhism")
        self.assertEqual(rows["PLAYER_0"]["cities"], 2)
        self.assertEqual(rows["PLAYER_0"]["score"], 20)
        self.assertEqual(rows["PLAYER_1"]["religion"], "Catholicism")
        self.assertEqual(rows["PLAYER_1"]["score"], 15)
    def test_upgrade_runtime_snapshot_validates(self):
        raw = json.loads(MINIMAL_SNAPSHOT.read_text(encoding="utf-8"))
        upgraded = civ6_adapter.upgrade_runtime_snapshot(raw)
        civ6_adapter.validate_civ6_snapshot(upgraded)
        self.assertEqual("PLAYER_1", upgraded["decision"]["player_id"])
        self.assertIn("your_cities", upgraded)
        self.assertGreater(len(upgraded["your_cities"]), 0)

    def test_session_dir_writes_decision_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sessions" / "gate0" / "PLAYER_1"
            journal = Path(tmp) / "journal.jsonl"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(RUN_CIV6),
                    "--state",
                    str(MINIMAL_SNAPSHOT),
                    "--journal",
                    str(journal),
                    "--session-dir",
                    str(session_dir),
                    "--from-game",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                check=False,
            )
            self.assertEqual(0, proc.returncode, proc.stderr or proc.stdout)
            decision_path = session_dir / "decision.json"
            self.assertTrue(decision_path.is_file())
            payload = json.loads(decision_path.read_text(encoding="utf-8"))
            self.assertIn(payload["status"], {"approved", "fallback"})
            commands = payload.get("commands") or []
            self.assertGreaterEqual(len(commands), 1)
            self.assertEqual("CMD_research_TECH_MINING", commands[0]["command_id"])
            self.assertTrue((session_dir / "apply_commands.json").is_file())

    @mock.patch("sidecar.run_civ6.pipeline.call_model")
    def test_live_mock_writes_io_logs(self, mock_call):
        mock_call.return_value = (
            {
                "thought": {"situation": "Live mock.", "strategy": "Research."},
                "decision_summary": "Mock live path.",
                "commands": [{"command_id": "CMD_research_TECH_MINING", "arguments": {}}],
                "chat_messages": [],
            },
            {"model": "mock", "provider": "gemini", "usage": {"total_tokens": 12}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sessions" / "live" / "PLAYER_1"
            journal = session_dir / "journal.jsonl"
            argv = [
                "run_civ6.py",
                "--state",
                str(MINIMAL_SNAPSHOT),
                "--journal",
                str(journal),
                "--session-dir",
                str(session_dir),
                "--from-game",
                "--live",
                "--session-id",
                "live",
            ]
            with mock.patch.object(sys, "argv", argv):
                run_civ6.main()
            self.assertTrue(mock_call.called)
            self.assertTrue((session_dir / "decision.json").is_file())
            self.assertTrue((session_dir / "io_logs").is_dir())
            self.assertTrue((session_dir.parent / "turn_metrics.jsonl").is_file())
            self.assertTrue((session_dir.parent / "circuit_breaker.json").is_file())


if __name__ == "__main__":
    unittest.main()

