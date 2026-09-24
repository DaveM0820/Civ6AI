"""Regression tests for Civ6 menu click coordinates (no game window required)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "testbed"
sys.path.insert(0, str(SCRIPT_DIR))

import civ6_ui_automation as ui  # noqa: E402


class Civ6MenuPositionTests(unittest.TestCase):
    def test_begin_game_hardcoded_coords_at_reference_resolution(self):
        win = ui.WindowInfo(hwnd=1, x=0, y=0, w=1600, h=1024)
        coords = ui._begin_game_client_coords(win)
        self.assertGreaterEqual(len(coords), 2)
        cx, cy = coords[0]
        self.assertEqual(579, cx)
        self.assertEqual(774, cy)

    def test_locked_begin_game_ignores_json_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "positions.json"
            path.write_text(
                json.dumps(
                    {
                        "ref_w": 1600,
                        "ref_h": 1024,
                        "items": {
                            "begin_game": {
                                "client_x": 800,
                                "client_y": 1003,
                                "pct_x": 0.5,
                                "pct_y": 0.98,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(ui, "_MENU_POSITIONS_PATH", path):
                entry = ui._position_entry("begin_game")
                default = ui._DEFAULT_MENU_POSITIONS["begin_game"]
                self.assertEqual(default["pct_x"], entry["pct_x"])
                self.assertEqual(default["pct_y"], entry["pct_y"])

    def test_begin_game_click_candidates_use_hardcoded_only(self):
        candidates = ui._begin_game_click_candidates()
        self.assertEqual(1, len(candidates))
        default = ui._DEFAULT_MENU_POSITIONS["begin_game"]
        self.assertEqual((default["pct_x"], default["pct_y"]), candidates[0])

    def test_sanitize_rejects_begin_game_at_bottom_of_screen(self):
        bad = {"pct_x": 0.5, "pct_y": 0.98, "client_x": 800, "client_y": 1003}
        fixed = ui._sanitize_position_entry("begin_game", bad)
        self.assertEqual(ui._DEFAULT_MENU_POSITIONS["begin_game"]["pct_y"], fixed["pct_y"])

    def test_start_game_not_confused_with_begin_game_region(self):
        begin = ui._DEFAULT_MENU_POSITIONS["begin_game"]
        start = ui._DEFAULT_MENU_POSITIONS["start_game"]
        self.assertLess(begin["pct_y"], 0.96)
        self.assertGreater(start["pct_y"], 0.9)

    def test_save_menu_position_skips_locked_begin_game(self):
        win = ui.WindowInfo(hwnd=1, x=0, y=0, w=1600, h=1024)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "positions.json"
            path.write_text(json.dumps({"ref_w": 1600, "ref_h": 1024, "items": {}}), encoding="utf-8")
            with mock.patch.object(ui, "_MENU_POSITIONS_PATH", path):
                ui.save_menu_position("begin_game", win, 800, 1003)
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("begin_game", data.get("items", {}))

    def test_save_menu_position_force_updates_locked_begin_game(self):
        win = ui.WindowInfo(hwnd=1, x=0, y=0, w=1600, h=1024)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "positions.json"
            path.write_text(json.dumps({"ref_w": 1600, "ref_h": 1024, "items": {}}), encoding="utf-8")
            with mock.patch.object(ui, "_MENU_POSITIONS_PATH", path):
                ui.save_menu_position("begin_game", win, 585, 822, force=True)
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(585, data["items"]["begin_game"]["client_x"])


if __name__ == "__main__":
    unittest.main()
