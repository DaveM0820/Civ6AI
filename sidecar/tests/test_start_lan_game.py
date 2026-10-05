"""OCR helpers for scripts/start_lan_game.py (no Civ6 process)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))

from civ6_ui_automation import (  # noqa: E402
    ocr_blob_is_loading_or_ingame,
    ocr_blob_is_main_menu,
)


class MainMenuBlobTests(unittest.TestCase):
    def test_title_menu(self):
        blob = "single player multiplayer game options gathering storm"
        self.assertTrue(ocr_blob_is_main_menu(blob))

    def test_not_lan_browser(self):
        blob = "local network games join game refresh create"
        self.assertFalse(ocr_blob_is_main_menu(blob))

    def test_not_staging(self):
        blob = "staging room are you ready add player"
        self.assertFalse(ocr_blob_is_main_menu(blob))


class LoadingOrIngameBlobTests(unittest.TestCase):
    def test_staging_turn_mode_is_not_ingame(self):
        blob = "staging room turn mode simultaneous turns not ready are you ready?"
        self.assertFalse(ocr_blob_is_loading_or_ingame(blob))

    def test_turn_one_hud(self):
        blob = "turn 1 4000 bc egypt"
        self.assertTrue(ocr_blob_is_loading_or_ingame(blob))

    def test_loading_screen(self):
        blob = "loading world"
        self.assertTrue(ocr_blob_is_loading_or_ingame(blob))


if __name__ == "__main__":
    unittest.main()
