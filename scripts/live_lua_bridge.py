#!/usr/bin/env python3
"""Watch Lua.log blobs + pending snapshots and run the Civ6 sidecar host loop."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTBED = ROOT / "scripts" / "testbed"
for path in (ROOT, TESTBED, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from civ6_lua_log_bridge import default_lua_log, log_civ6ai_root, process_host_io  # noqa: E402
from civ6_paths import lua_log_candidates  # noqa: E402
from sidecar.civ6_config import apply_config_to_environ, load_local_config  # noqa: E402
from windows_process import python_executable  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("live_lua_bridge")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lua-log", type=Path, default=None)
    parser.add_argument("--interval", type=float, default=1.5)
    args = parser.parse_args()

    cfg = load_local_config()
    apply_config_to_environ(cfg)

    lua_log = args.lua_log
    if lua_log is None:
        for candidate in lua_log_candidates():
            if candidate.is_file():
                lua_log = candidate
                break
        if lua_log is None:
            lua_log = default_lua_log()

    # Prefer local Documents civ6ai (never OneDrive when local exists). Paths.lua
    # Civ6AiRoot must match so game + host write the same tree.
    from civ6_paths import preferred_my_games_root, is_onedrive_path  # noqa: PLC0415

    civ6ai_root = preferred_my_games_root() / "civ6ai"
    if lua_log is not None:
        logged = log_civ6ai_root(lua_log)
        if logged is not None and not is_onedrive_path(logged):
            civ6ai_root = logged

    civ6ai_root.mkdir(parents=True, exist_ok=True)
    python = python_executable(prefer_pythonw=True)
    log.info("Host IO loop lua_log=%s civ6ai_root=%s python=%s", lua_log, civ6ai_root, python)
    while True:
        try:
            ran = process_host_io(civ6ai_root, lua_log, ROOT, python=python)
            if ran:
                log.info("Processed %s host IO units", ran)
        except Exception as error:
            log.warning("host io error: %s", error)
        time.sleep(max(0.5, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
