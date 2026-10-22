#!/usr/bin/env python3
"""Load the newest LAN autosave and ready the staging room (one recovery command).

  python scripts/load_lan_autosave.py
  python scripts/load_lan_autosave.py --no-kill

Kills the running Civ process by default, waits for the main menu, then clicks
Multiplayer -> Local Network -> Load Game -> Autosaves -> the top (newest)
save -> Load, and the same staging Ready flow as scripts/start_lan_game.py.
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
    load_lan_autosave,
    wait_for_host_click_ui,
)

log = logging.getLogger("load_lan_autosave")
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


def run(*, kill_existing: bool, dry_run: bool = False) -> list[str]:
    if dry_run:
        log.info("dry-run: no process kill, no clicks")
        win = find_civ_window()
        if win is None:
            log.info("dry-run: Civ window not found; logging the click plan only")
            print("LAN_LOAD_DRY_RUN", ["dry_run", "no_window"])
            return ["dry_run", "no_window"]
        return load_lan_autosave(win, dry_run=True)
    if kill_existing:
        launch_civ(kill_existing=True)
    elif find_civ_window() is None:
        launch_civ(kill_existing=False)
    win = wait_for_host_click_ui(timeout_s=180.0)
    time.sleep(0.6)
    return load_lan_autosave(win)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Load the newest Civ6 LAN autosave and ready the host")
    parser.add_argument(
        "--no-kill",
        action="store_true",
        help="Do not restart Civ (use the window that is already open)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log the Multiplayer, Load Game, and Autosaves toggle plan without clicking",
    )
    args = parser.parse_args(argv)
    try:
        steps = run(kill_existing=not args.no_kill, dry_run=args.dry_run)
    except Exception as error:
        print(f"LAN_LOAD_FAIL {error}")
        return 1
    print("LAN_LOAD_OK", steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
