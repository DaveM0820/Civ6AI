#!/usr/bin/env python3
"""Keep the live helpers running: respawn a dead job_poller / lua_bridge in place.

Started by scripts/start_live.py (pass --no-watchdog to skip). Reads
live_workers.json every --interval seconds; a recorded worker whose PID is gone
is started again with the same command and the record is updated. The session
is kept (a respawn is the same as a helper restart). Exits when the PID file is
removed (scripts/stop_live.py) or no longer lists this watchdog.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from civ6_paths import live_runtime_dir  # noqa: E402
from windows_process import pid_alive, popen_hidden  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("live_watchdog")


def check_once(pid_file: Path, env: dict[str, str], *, alive=pid_alive, spawn=None) -> str:
    """One pass. Returns "stop" when the watchdog should exit, else "ok"."""
    try:
        payload = json.loads(pid_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "stop"
    workers = payload.get("workers") if isinstance(payload, dict) else None
    if not isinstance(workers, list):
        return "stop"
    me = os.getpid()
    if not any(isinstance(w, dict) and w.get("name") == "watchdog" and int(w.get("pid") or 0) == me
               for w in workers):
        return "stop"
    changed = False
    for worker in workers:
        if not isinstance(worker, dict) or worker.get("name") == "watchdog":
            continue
        if alive(int(worker.get("pid") or 0)):
            continue
        cmd = worker.get("cmd")
        if not isinstance(cmd, list) or not cmd:
            continue
        if spawn is None:
            log_path = Path(worker.get("log") or (pid_file.parent / "logs" / f"{worker.get('name')}.log"))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(log_path, "a", encoding="utf-8")
            new_pid = popen_hidden(cmd, cwd=ROOT, env=env, stdout=fh, stderr=fh).pid
        else:
            new_pid = spawn(cmd)
        log.warning("worker_respawned|name=%s|old_pid=%s|new_pid=%s", worker.get("name"), worker.get("pid"), new_pid)
        worker["pid"] = new_pid
        worker["respawns"] = int(worker.get("respawns") or 0) + 1
        changed = True
    if changed:
        pid_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return "ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=20.0)
    args = parser.parse_args()
    pid_file = live_runtime_dir() / "live_workers.json"
    env = os.environ.copy()
    # Give start_live a moment to write the record that lists this watchdog.
    time.sleep(5)
    log.info("Watching %s", pid_file)
    while True:
        try:
            if check_once(pid_file, env) == "stop":
                log.info("PID record gone or no longer lists this watchdog; exiting")
                return 0
        except Exception as error:
            log.warning("watchdog error: %s", error)
        time.sleep(max(5.0, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
