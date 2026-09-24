"""Background sidecar job poller for Civ6 autotest (os.execute blocked in InGame)."""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from civ6_lua_log_bridge import default_lua_log, process_host_io
from civ6_startup_log import configure_startup_logging, log_event, tail_lua_log_to_startup

log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll civ6ai sessions for sidecar_job.json")
    parser.add_argument("--civ6ai-root", type=Path, required=True)
    parser.add_argument("--lua-log", type=Path, default=None)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    lua_log = args.lua_log or default_lua_log()
    repo = args.repo or Path(__file__).resolve().parents[2]
    configure_startup_logging(args.civ6ai_root, lua_log)
    log_event(args.civ6ai_root, "sidecar_poll_start", lua_log=lua_log, civ6ai_root=str(args.civ6ai_root))
    log.info("Sidecar poll watching %s lua_log=%s", args.civ6ai_root, lua_log)
    lua_offset = lua_log.stat().st_size if lua_log.is_file() else 0
    while True:
        ran = process_host_io(args.civ6ai_root, lua_log, repo)
        lua_offset = tail_lua_log_to_startup(args.civ6ai_root, lua_log, offset=lua_offset)
        if ran:
            log.info("Processed %d sidecar job(s)", ran)
            log_event(args.civ6ai_root, "sidecar_poll_processed", lua_log=lua_log, jobs=ran)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
