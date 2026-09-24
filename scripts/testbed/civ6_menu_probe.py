"""Quick probe: capture Civ6 main menu, dismiss overlays, try Single Player click."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from civ6_ui_automation import (
    calibrate_menu_position,
    detect_menu,
    dismiss_main_menu_overlays,
    find_civ_window,
    load_menu_positions,
    open_advanced_setup,
    open_single_player_menu,
    screenshot_to,
    wait_for_main_menu,
    _hide_blocking_overlays,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
OUT = Path(__file__).resolve().parents[2] / "artifacts" / "civ6-menu-probe"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="OCR current screen and update civ6_menu_positions.json",
    )
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    win = None
    for _ in range(60):
        win = find_civ_window()
        if win:
            break
        time.sleep(1)
    if win is None:
        print("No Civ6 window")
        return 1

    print(f"Window {win.w}x{win.h} at ({win.x},{win.y}) hwnd={win.hwnd}")
    print("positions file:", load_menu_positions())

    if detect_menu(win) != "main":
        print("skip dismiss — already past main menu:", detect_menu(win))
    else:
        _hide_blocking_overlays(win)
    wait_for_main_menu(win, timeout=15)
    screenshot_to(OUT / "01_main.png", win)
    print("menu before:", detect_menu(win))

    dismissed = dismiss_main_menu_overlays(win, timeout=8)
    print("dismissed:", dismissed)
    screenshot_to(OUT / "02_after_dismiss.png", win)

    if args.calibrate and detect_menu(win) == "main":
        ok = calibrate_menu_position(win, "main_single_player")
        print("calibrate main_single_player:", ok)

    ok = open_single_player_menu(win)
    screenshot_to(OUT / "03_after_sp.png", win)
    print("open SP:", ok, "menu:", detect_menu(win))

    if args.calibrate and detect_menu(win) == "single_player":
        ok_adv = calibrate_menu_position(win, "sp_create_game")
        print("calibrate sp_create_game:", ok_adv)

    if not ok:
        print("screenshots:", OUT)
        return 1

    adv = open_advanced_setup(win)
    screenshot_to(OUT / "04_advanced_setup.png", win)
    print("advanced setup:", adv, "menu:", detect_menu(win))
    print("screenshots:", OUT)
    return 0 if adv else 1


if __name__ == "__main__":
    raise SystemExit(main())
