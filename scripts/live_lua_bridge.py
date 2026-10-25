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

from civ6_lua_log_bridge import default_lua_log, process_host_io  # noqa: E402
from civ6_paths import active_lua_log, lua_log_candidates  # noqa: E402
from sidecar.civ6_config import apply_config_to_environ, load_local_config  # noqa: E402
from windows_process import python_executable  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("live_lua_bridge")


def follow_active_log(current: Path, candidates: list[Path] | None = None) -> Path:
    """Switch to another candidate Lua.log once Civ6 writes it more recently."""
    active = active_lua_log(candidates)
    if active is None or active == current:
        return current
    try:
        current_mtime = current.stat().st_mtime
    except OSError:
        current_mtime = -1.0
    if active.stat().st_mtime > current_mtime + 2.0:
        log.info("Lua.log switch: %s -> %s (newer writes)", current, active)
        return active
    return current


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lua-log", type=Path, default=None)
    parser.add_argument("--interval", type=float, default=1.5)
    args = parser.parse_args()

    cfg = load_local_config()
    apply_config_to_environ(cfg)

    pinned = args.lua_log
    lua_log = pinned or active_lua_log() or default_lua_log()

    from civ6_paths import civ6ai_root as _civ6ai_root  # noqa: PLC0415

    civ6ai_root = _civ6ai_root()

    civ6ai_root.mkdir(parents=True, exist_ok=True)
    python = python_executable(prefer_pythonw=True)
    log.info("Host IO loop lua_log=%s civ6ai_root=%s python=%s", lua_log, civ6ai_root, python)
    while True:
        if pinned is None:
            lua_log = follow_active_log(lua_log)
        try:
            ran = process_host_io(civ6ai_root, lua_log, ROOT, python=python)
            if ran:
                log.info("Processed %s host IO units", ran)
        except Exception as error:
            log.warning("host io error: %s", error)
        time.sleep(max(0.5, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
