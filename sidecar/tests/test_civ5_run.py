"""Sidecar step I/O is per managed seat, including AI majors (PLAYER_1+)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sidecar import civ5_adapter
from sidecar import run_civ5


class Civ5RunStepIoTests(unittest.TestCase):
    def test_write_step_io_names_files_by_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "PLAYER_3"
            path = run_civ5._write_step_io(session_dir, 7, "2_prompt", "out", "cmd.0 = CMD_x")
            self.assertEqual(session_dir / "t7_2_prompt_out.txt", path)
            self.assertEqual("cmd.0 = CMD_x\n", path.read_text(encoding="utf-8"))

    def test_from_game_writes_full_step_io_for_ai_seat(self):
        snapshot = civ5_adapter.build_classical_golden_snapshot()
        snapshot["decision"]["player_id"] = "PLAYER_2"
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = Path(tmp) / "PLAYER_2"
            player_dir.mkdir()
            state = player_dir / "snapshot.json"
            state.write_text(json.dumps(snapshot), encoding="utf-8")
            argv = [
                "run_civ5.py",
                "--from-game",
                "--session-dir",
                str(player_dir),
                "--state",
                str(state),
                "--journal",
                str(player_dir / "journal.jsonl"),
            ]
            with mock.patch.object(sys, "argv", argv):
                run_civ5.main()
            turn = snapshot["decision"]["turn"]
            for name in (
                f"t{turn}_1_gather_in.txt",
                f"t{turn}_1_gather_out.txt",
                f"t{turn}_2_prompt_in.txt",
                f"t{turn}_2_prompt_out.txt",
                f"t{turn}_3_llm_in.txt",
                f"t{turn}_3_llm_out.txt",
                f"t{turn}_4_parse_in.txt",
                f"t{turn}_4_parse_out.txt",
            ):
                path = player_dir / name
                self.assertTrue(path.is_file(), name)
                self.assertGreater(path.stat().st_size, 1, name)
            gather_in = json.loads((player_dir / f"t{turn}_1_gather_in.txt").read_text(encoding="utf-8"))
            self.assertEqual("PLAYER_2", gather_in["decision"]["player_id"])
            self.assertIn("PLAYER_2", (player_dir / f"t{turn}_2_prompt_out.txt").read_text(encoding="utf-8"))

    def test_malformed_snapshot_still_logs_gather(self):
        with tempfile.TemporaryDirectory() as tmp:
            player_dir = Path(tmp) / "PLAYER_1"
            player_dir.mkdir()
            state = player_dir / "snapshot.json"
            state.write_text("{not json", encoding="utf-8")
            argv = [
                "run_civ5.py",
                "--from-game",
                "--session-dir",
                str(player_dir),
                "--state",
                str(state),
            ]
            with mock.patch.object(sys, "argv", argv):
                run_civ5.main()
            self.assertTrue("{not json" in (player_dir / "tunknown_1_gather_in.txt").read_text(encoding="utf-8"))
            self.assertGreater(len((player_dir / "tunknown_1_gather_out.txt").read_text(encoding="utf-8")), 1)
            self.assertTrue(list(player_dir.glob("*_1_0.json")))


if __name__ == "__main__":
    unittest.main()
