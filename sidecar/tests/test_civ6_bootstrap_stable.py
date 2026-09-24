"""Regression locks for stable Civ6 bootstrap behavior."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))

from civ6_ui_automation import WindowInfo, bootstrap_create_game_timed, has_menu_sequence


class Civ6BootstrapStableTests(unittest.TestCase):
    def test_bootstrap_prefers_recorded_menu_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            seq_path = Path(tmp) / "civ6_menu_sequence.json"
            seq_path.write_text(
                json.dumps(
                    {
                        "ref_w": 1280,
                        "ref_h": 720,
                        "steps": [
                            {
                                "label": "click_1",
                                "delay_before_s": 0.0,
                                "pct_x": 0.5,
                                "pct_y": 0.5,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            win = WindowInfo(hwnd=1, x=0, y=0, w=1280, h=720)
            with mock.patch("civ6_ui_automation._MENU_SEQUENCE_PATH", seq_path):
                with mock.patch("civ6_ui_automation._ensure_civ_foreground", return_value=win):
                    with mock.patch("civ6_ui_automation.replay_menu_sequence", return_value=["sequence_click_1"]) as replay:
                        with mock.patch("civ6_ui_automation.refresh_window", side_effect=lambda w: w):
                            with mock.patch("civ6_ui_automation.find_civ_window", return_value=win):
                                with mock.patch("civ6_ui_automation.bootstrap_click_begin_game_timed") as begin:
                                    with mock.patch("civ6_ui_automation.bootstrap_click_menu") as calibrated:
                                        events = bootstrap_create_game_timed(win)
            replay.assert_called_once()
            begin.assert_called_once()
            calibrated.assert_not_called()
            self.assertIn("begin_game_after_sequence", events)

    def test_menu_sequence_file_exists_in_repo(self):
        repo_seq = ROOT / "scripts" / "testbed" / "civ6_menu_sequence.json"
        self.assertTrue(repo_seq.is_file(), "Recorded menu sequence is required for stable bootstrap")
        self.assertTrue(has_menu_sequence())


if __name__ == "__main__":
    unittest.main()
