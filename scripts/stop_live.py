#!/usr/bin/env python3
"""Stop workers started by scripts/start_live.py."""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "runtime" / "live_workers.json"


def _terminate(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        # taskkill hides better than console CTRL events for pythonw children
        os.system(f'taskkill /PID {pid} /T /F >NUL 2>&1')
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(0.5)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def main() -> int:
    if not PID_FILE.is_file():
        print(f"No PID file at {PID_FILE} (nothing to stop).")
        return 0
    try:
        payload = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Corrupt PID file {PID_FILE}; deleting.")
        PID_FILE.unlink(missing_ok=True)
        return 1
    workers = payload.get("workers") if isinstance(payload, dict) else None
    if not isinstance(workers, list):
        print("No workers listed.")
        PID_FILE.unlink(missing_ok=True)
        return 0
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        pid = int(worker.get("pid") or 0)
        name = worker.get("name") or "?"
        print(f"Stopping {name} pid={pid}")
        _terminate(pid)
    PID_FILE.unlink(missing_ok=True)
    print("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
