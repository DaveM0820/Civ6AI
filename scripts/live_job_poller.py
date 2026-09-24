#!/usr/bin/env python3
"""Poll Civ6Ai sidecar_job.json files and run them (hidden on Windows)."""
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

from civ6_paths import logs_dirs, my_games_roots  # noqa: E402
from civ6_sidecar_jobs import process_sidecar_jobs  # noqa: E402
from sidecar.civ6_config import apply_config_to_environ, load_local_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("live_job_poller")


def discover_roots() -> list[Path]:
    roots: list[Path] = []
    for game in my_games_roots():
        roots.append(game / "civ6ai")
    for logs in logs_dirs():
        roots.append(logs / "civ6ai")
    # Dedup
    seen: set[str] = set()
    out: list[Path] = []
    for path in roots:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    cfg = load_local_config()
    apply_config_to_environ(cfg)
    roots = discover_roots()
    log.info("Polling sidecar jobs under %s", roots)
    while True:
        try:
            ran = process_sidecar_jobs(roots)
            if ran:
                log.info("Ran %s sidecar job(s)", ran)
        except Exception as error:
            log.warning("poll error: %s", error)
        time.sleep(max(0.5, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
