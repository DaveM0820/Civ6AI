#!/usr/bin/env python3
"""Keep the live helpers running: respawn a dead job_poller / lua_bridge in place.

Started by scripts/start_live.py (pass --no-watchdog to skip). Reads
live_workers.json every --interval seconds; a recorded worker whose PID is gone
is started again with the same command and the record is updated. The session
is kept (a respawn is the same as a helper restart). Exits when the PID file is
removed (scripts/stop_live.py) or no longer lists this watchdog.

It also restarts all helpers (stop_live then start_live, same session) when the
pipeline is stalled or every seat's sidecar keeps failing; see stall_check and
scripts/testbed/civ6_stall_restart.py for triggers, backoff and the
deterministic-error stop.
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


def stall_check(pid_file: Path, *, now: float | None = None, spawn_restart=None) -> str:
    """Restart the helpers (same session) when the pipeline is stalled or failing.

    Returns "restart", "blocked" or "none". See scripts/testbed/civ6_stall_restart.py.
    """
    testbed = ROOT / "scripts" / "testbed"
    if str(testbed) not in sys.path:
        sys.path.insert(0, str(testbed))
    import civ6_stall_restart as sr
    from civ6_paths import civ6ai_root

    now = time.time() if now is None else now
    root = civ6ai_root()
    try:
        runtime = json.loads((root / "runtime.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "none"
    session = str(runtime.get("session_id") or "")
    if not session:
        return "none"
    logs = pid_file.parent / "logs"
    bridge_log = logs / "lua_bridge.log"
    session_dir = root / "sessions" / session
    activity = sr.session_activity(session_dir, [bridge_log, logs / "job_poller.log"])
    seats = sum(1 for d in session_dir.glob("PLAYER_*") if (d / "snapshot.json").is_file())
    cfg = sr.settings_values()
    state_path = pid_file.parent / "watchdog_state.json"
    state = sr.load_state(state_path)
    since = max(float(state.get("last_restart") or 0), now - 2 * cfg["stall_minutes"] * 60)
    try:
        with bridge_log.open("rb") as fh:
            fh.seek(max(0, bridge_log.stat().st_size - 2_000_000))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        text = ""
    failures = sr.recent_failures(text, since)
    decision = sr.decide(now=now, activity=activity, failures=failures, seats=seats, state=state, cfg=cfg)
    action = decision["action"]
    if action == "none":
        if state.get("last_blocked"):
            state.pop("last_blocked", None)
            sr.save_state(state_path, state)
        return "none"
    if action == "blocked":
        key = decision["reason"].split(":")[0] + "|" + decision["why"] + "|" + decision.get("signature", "")
        if state.get("last_blocked") != key:
            state["last_blocked"] = key
            sr.save_state(state_path, state)
            loud = "DETERMINISTIC" if "deterministic" in decision["why"] else "restart_skipped"
            log.error("%s|turn=%s|reason=%s|why=%s|last_error=%s", loud, decision.get("turn"),
                      decision["reason"], decision["why"], decision.get("last_error") or "-")
        return "blocked"
    state = sr.record_restart(state, now, decision)
    state.pop("last_blocked", None)
    sr.save_state(state_path, state)
    log.warning("helpers_restart|turn=%s|reason=%s|last_error=%s", decision.get("turn"),
                decision["reason"], decision.get("last_error") or "-")
    cmd = [sys.executable, str(ROOT / "scripts" / "restart_live.py")]
    if spawn_restart is not None:
        spawn_restart(cmd)
    else:
        out = open(logs / "restart_live.log", "a", encoding="utf-8")
        popen_hidden(cmd, cwd=ROOT, env=os.environ.copy(), stdout=out, stderr=out)
    return "restart"


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
            if stall_check(pid_file) == "restart":
                # restart_live stops this watchdog and starts a new one.
                time.sleep(120)
        except Exception as error:
            log.warning("watchdog error: %s", error)
        time.sleep(max(5.0, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
