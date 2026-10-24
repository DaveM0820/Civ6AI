#!/usr/bin/env python3
"""Restart the live helpers keeping the session: stop_live, then start_live.

Spawned by live_watchdog.py on a stall. stop_live ends the watchdog without its
process tree, so this script survives to start the new set of helpers.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    time.sleep(2)
    py = sys.executable
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "restart_live: stop_live", flush=True)
    subprocess.run([py, str(ROOT / "scripts" / "stop_live.py")], cwd=ROOT)
    time.sleep(3)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "restart_live: start_live (same session)", flush=True)
    return subprocess.run([py, str(ROOT / "scripts" / "start_live.py")], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
