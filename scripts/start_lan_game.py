#!/usr/bin/env python3
"""Relaunch Civ6 and host a LAN test game (no manual menu clicks).

  python scripts/start_lan_game.py
  python scripts/start_lan_game.py --no-kill

Kills the running Civ process by default so a fresh Mods/Paths.lua load (Autotest
on) actually applies. Then waits for the main menu and clicks Multiplayer ->
Local Network -> Create Game -> setup -> staging Ready.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTBED = ROOT / "scripts" / "testbed"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(TESTBED))
sys.path.insert(0, str(SCRIPTS))

from windows_process import run_hidden  # noqa: E402

from civ6_ui_automation import (  # noqa: E402
    find_civ_window,
    start_lan_test_game,
    wait_for_host_click_ui,
)

log = logging.getLogger("start_lan_game")
LAUNCH = TESTBED / "Invoke-Civ6AiLaunch.ps1"


def launch_civ(*, kill_existing: bool) -> None:
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(LAUNCH),
        "-WaitForProcess",
    ]
    if kill_existing:
        args.append("-KillExisting")
    result = run_hidden(args, timeout=180)
    if result.stdout:
        for line in result.stdout.splitlines():
            log.info("%s", line)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise RuntimeError(f"Civ6 launch failed: {err}")


def run(*, kill_existing: bool) -> list[str]:
    if kill_existing:
        launch_civ(kill_existing=True)
    elif find_civ_window() is None:
        launch_civ(kill_existing=False)
    win = wait_for_host_click_ui(timeout_s=180.0)
    time.sleep(0.6)
    return start_lan_test_game(win)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Host a Civ6 LAN test game from the main menu")
    parser.add_argument(
        "--no-kill",
        action="store_true",
        help="Do not restart Civ (use the window that is already open)",
    )
    args = parser.parse_args(argv)
    try:
        steps = run(kill_existing=not args.no_kill)
    except Exception as error:
        print(f"LAN_START_FAIL {error}")
        return 1
    print("LAN_START_OK", steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
