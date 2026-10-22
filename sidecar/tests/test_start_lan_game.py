"""OCR helpers for scripts/start_lan_game.py (no Civ6 process)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))

from civ6_ui_automation import (  # noqa: E402
    menu_blob_has,
    ocr_blob_is_loading_or_ingame,
    ocr_blob_is_main_menu,
    ocr_dropped_initial,
    pick_newest_save_label,
    _text_matches_target,
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


class OcrMenuLabelTests(unittest.TestCase):
    def test_load_game_matches_dropped_first_letter(self):
        self.assertTrue(ocr_dropped_initial("Oad Game", "Load Game"))
        self.assertTrue(_text_matches_target("oad game", "load game", exact=True))
        self.assertTrue(menu_blob_has("back oad game autosaves", "load game"))
        self.assertTrue(_text_matches_target("ocal network", "local network", exact=True))
        self.assertTrue(_text_matches_target("utosaves", "autosaves", exact=False))

    def test_short_labels_do_not_use_the_dropped_letter(self):
        self.assertFalse(ocr_dropped_initial("ack", "back"))
        self.assertFalse(_text_matches_target("ack", "back", exact=True))


class NewestAutosaveTests(unittest.TestCase):
    def test_top_row_is_newest_and_chrome_is_skipped(self):
        rows = [
            ("Autosaves", 200, 80),
            ("Sort by Last Modified", 400, 120),
            ("AutoSave_0186", 300, 220),
            ("AutoSave_0185", 300, 260),
            ("Load", 700, 900),
        ]
        self.assertEqual(pick_newest_save_label(rows), ("AutoSave_0186", 300, 220))
        garbled = [("Oad Game", 200, 80), ("AutoSave_0186", 300, 220)]
        self.assertEqual(pick_newest_save_label(garbled), ("AutoSave_0186", 300, 220))

    def test_empty_list(self):
        self.assertIsNone(pick_newest_save_label([("Autosaves", 1, 1), ("Back", 2, 2)]))


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
