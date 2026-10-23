"""OCR helpers for scripts/start_lan_game.py (no Civ6 process)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
sys.path.insert(0, str(ROOT / "scripts"))

from civ6_ui_automation import (  # noqa: E402
    lan_create_button,
    lan_host_screen,
    lan_load_phase,
    lan_missing_setup,
    lan_option_button,
    lan_setup_verified,
    lan_start_failed,
    lan_test_setup,
    menu_blob_has,
    ocr_blob_is_loading_or_ingame,
    ocr_blob_is_main_menu,
    ocr_dropped_initial,
    pick_newest_save_label,
    _is_create_game_phrase,
    _text_matches_target,
)
import start_lan_game  # noqa: E402


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

    def test_newer_date_beats_an_older_row_that_sits_higher(self):
        rows = [
            ("AutoSave_0009", 300, 180),
            ("9/23/2025", 700, 184),
            ("AutoSave_0186", 300, 260),
            ("10/22/2026", 700, 264),
        ]
        self.assertEqual(pick_newest_save_label(rows), ("AutoSave_0186", 300, 260))


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


class LanCreateGameTests(unittest.TestCase):
    def test_setup_is_four_players_and_timers_off(self):
        setup = {labels[0]: option for labels, option in lan_test_setup()}
        self.assertEqual(setup["choose number of players"], "4")
        self.assertEqual(setup["turn timer"], "No Turn Timer")
        self.assertEqual(setup["smart timer"], "Off")

    def test_load_game_screen_is_not_the_create_button(self):
        self.assertEqual("load_game", lan_host_screen("back oad game no file"))
        self.assertEqual("file_picker", lan_host_screen("back load game utosaves"))
        self.assertEqual("lan", lan_host_screen("local network games join game refresh load game"))
        self.assertEqual("setup", lan_host_screen("multiplayer game setup"))
        rows = [
            ("Load Game", 900, 1001),
            ("Join Game", 400, 400),
            ("Refresh", 200, 400),
        ]
        self.assertIsNone(lan_create_button(rows))

    def test_split_create_game_beats_load_game_on_the_same_row(self):
        rows = [
            ("Load", 900, 1000),
            ("Game", 980, 1000),
            ("Create", 1180, 1000),
            ("Game", 1260, 1000),
        ]
        hit = lan_create_button(rows)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("create", hit[0])
        self.assertNotIn("load", hit[0])
        self.assertGreater(hit[1], 1100)

    def test_dropped_initial_still_finds_create(self):
        rows = [("Reate", 1180, 900), ("Game", 1260, 900), ("Oad", 900, 900), ("Game", 980, 900)]
        hit = lan_create_button(rows)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("reate", hit[0])
        self.assertGreater(hit[1], 1100)

    def test_garbled_rea_e_ame_is_create_and_load_is_not(self):
        self.assertTrue(_is_create_game_phrase("rea e ame"))
        self.assertFalse(_is_create_game_phrase("oad game"))
        self.assertFalse(_is_create_game_phrase("oadgame"))
        self.assertFalse(_is_create_game_phrase("game"))
        rows = [
            ("Load", 900, 1000),
            ("Game", 980, 1000),
            ("rea", 1180, 1000),
            ("e", 1220, 1000),
            ("ame", 1280, 1000),
        ]
        hit = lan_create_button(rows)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("rea", hit[0])
        self.assertIn("ame", hit[0])
        self.assertNotIn("load", hit[0])
        self.assertGreater(hit[1], 1100)

    def test_unreadable_button_right_of_load_is_create(self):
        rows = [("Load Game", 900, 1000), ("btn", 1200, 1000)]
        hit = lan_create_button(rows)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(1200, hit[1])
        self.assertEqual(1000, hit[2])
        self.assertIsNone(lan_create_button([
            ("Load Game", 900, 1001),
            ("Join Game", 400, 400),
            ("Refresh", 200, 400),
        ]))
        self.assertIsNone(lan_create_button([
            ("Load Game", 900, 1000),
            ("oad game", 1200, 1000),
        ]))

    def test_missing_create_is_a_failed_start(self):
        self.assertTrue(lan_start_failed([
            "already_lan_browser", "create_game_not_found", "never_reached_mp_setup",
        ]))
        self.assertTrue(lan_start_failed(["create_game_not_found"]))
        self.assertTrue(lan_start_failed([
            "create_game_not_found", "reached_mp_setup",
        ]))
        self.assertTrue(lan_start_failed(["already_mp_setup"]))
        self.assertTrue(lan_start_failed(["already_staging"]))
        failed = ["create_game_not_found", "never_reached_mp_setup"]
        with mock.patch.object(start_lan_game, "run", return_value=failed):
            self.assertEqual(1, start_lan_game.main(["--no-kill"]))
        with mock.patch.object(start_lan_game, "run", return_value=["reached_mp_setup"]):
            self.assertEqual(1, start_lan_game.main(["--no-kill"]))

    def test_lan_ok_only_when_every_setup_row_is_verified(self):
        verified = [
            "reached_mp_setup",
            "choose_number_of_players:verified",
            "turn_timer:verified",
            "smart_timer:verified",
        ]
        self.assertFalse(lan_start_failed(verified))
        self.assertEqual([], lan_missing_setup(verified))
        skipped = ["already_staging", "clicked_ready"]
        self.assertEqual(
            ["choose_number_of_players", "turn_timer", "smart_timer"],
            lan_missing_setup(skipped),
        )
        self.assertTrue(lan_start_failed(skipped))
        partial = [
            "reached_mp_setup",
            "choose_number_of_players:verified",
            "turn_timer:failed",
            "smart_timer:verified",
        ]
        self.assertEqual(["turn_timer"], lan_missing_setup(partial))
        with mock.patch.object(start_lan_game, "run", return_value=verified):
            self.assertEqual(0, start_lan_game.main(["--no-kill"]))
        with mock.patch.object(start_lan_game, "run", return_value=skipped):
            with mock.patch("builtins.print") as printed:
                self.assertEqual(1, start_lan_game.main(["--no-kill"]))
            text = " ".join(str(arg) for arg in printed.call_args[0])
            self.assertIn("LAN_START_FAIL", text)
            self.assertIn("choose_number_of_players", text)
            self.assertIn("turn_timer", text)
            self.assertIn("smart_timer", text)

    def test_setup_row_verify_needs_option_on_the_same_line(self):
        rows = [
            ("Choose Number of Players", 120, 200),
            ("4", 520, 200),
            ("Turn Timer", 120, 260),
            ("No Turn Timer", 480, 260),
            ("Smart Timer", 120, 320),
            ("Off", 480, 320),
        ]
        self.assertTrue(lan_setup_verified(rows, ("choose number of players",), "4"))
        self.assertTrue(lan_setup_verified(rows, ("turn timer",), "No Turn Timer"))
        self.assertTrue(lan_setup_verified(rows, ("smart timer",), "Off"))
        self.assertFalse(lan_setup_verified(rows, ("turn timer",), "Off"))
        self.assertFalse(lan_setup_verified(
            [("Choose Number of Players", 120, 200), ("6", 520, 200)],
            ("choose number of players",),
            "4",
        ))

    def test_no_turn_timer_assembles_and_off_is_exact(self):
        rows = [
            ("No", 500, 400),
            ("Turn", 560, 402),
            ("Timer", 640, 400),
            ("Classic", 500, 460),
            ("Offer", 500, 520),
        ]
        hit = lan_option_button(rows, "No Turn Timer")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("no turn timer", hit[0])
        self.assertIsNone(lan_option_button(rows, "Off"))
        rows.append(("Off", 500, 580))
        off = lan_option_button(rows, "Off")
        self.assertIsNotNone(off)
        assert off is not None
        self.assertEqual(off[0], "off")
        self.assertIsNone(lan_option_button([("14", 10, 10), ("Offer", 10, 40)], "4"))
        four = lan_option_button([("2", 10, 10), ("4", 10, 40), ("6", 10, 70)], "4")
        self.assertIsNotNone(four)
        assert four is not None
        self.assertEqual(four[0], "4")

    def test_create_click_does_not_use_the_load_game_coordinate(self):
        text = (ROOT / "scripts" / "testbed" / "civ6_ui_automation.py").read_text(encoding="utf-8")
        start = text.index("def _start_lan_test_game_clicks")
        end = text.index("\ndef bootstrap_create_game_timed")
        body = text[start:end]
        self.assertNotIn("1180, 1001", body)
        self.assertNotIn("1180,1001", body)
        self.assertNotIn("958, 511", body)
        self.assertIn("_configure_lan_test_setup", body)
        self.assertIn("lan_create_button", body)


class LanLoadPhaseTests(unittest.TestCase):
    def test_load_game_screen_is_not_the_button(self):
        self.assertEqual("load_game", lan_load_phase("back oad game"))
        self.assertEqual("autosaves", lan_load_phase("back load game utosaves"))
        self.assertEqual("autosaves", lan_load_phase("auto save list"))
        self.assertEqual("staging", lan_load_phase("staging room are you ready"))
        self.assertEqual("lan", lan_load_phase("local network games join game refresh"))
        self.assertEqual("other", lan_load_phase("single player multiplayer"))


if __name__ == "__main__":
    unittest.main()
