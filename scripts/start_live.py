#!/usr/bin/env python3
"""Start Civ6Ai sidecar workers for a live (or dry-run) session.

On Windows, child processes use CREATE_NO_WINDOW / pythonw so console windows
do not cover the desktop.

Usage:
  python scripts/start_live.py
  python scripts/start_live.py --dry-run
  python scripts/start_live.py --dry-run --state fixtures/civ6/snapshot-turn-classical-golden.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from civ6_paths import logs_dirs, lua_log_candidates  # noqa: E402
from sidecar.civ6_config import apply_config_to_environ, load_local_config  # noqa: E402
from windows_process import popen_hidden, python_executable, run_hidden  # noqa: E402

PID_DIR = ROOT / "runtime"
PID_FILE = PID_DIR / "live_workers.json"
LOG_DIR = PID_DIR / "logs"


def _write_pid_record(workers: list[dict]) -> None:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workers": workers,
    }
    PID_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _worker_log(name: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{name}.log"


def _spawn(name: str, cmd: list[str], env: dict[str, str]) -> dict:
    log_path = _worker_log(name)
    log_fh = open(log_path, "a", encoding="utf-8")
    proc = popen_hidden(cmd, cwd=ROOT, env=env, stdout=log_fh, stderr=log_fh)
    return {"name": name, "pid": proc.pid, "cmd": cmd, "log": str(log_path)}


def _build_env(cfg) -> dict[str, str]:
    env = os.environ.copy()
    apply_config_to_environ(cfg)
    for key in (
        "CIV6AI_MODEL_PROVIDER",
        "CIV4AI_MODEL_PROVIDER",
        "LMSTUDIO_BASE_URL",
        "LMSTUDIO_MODEL",
        "LMSTUDIO_API_KEY",
        "CIV6AI_LMSTUDIO_TIMEOUT_SECONDS",
        "CIV4AI_LMSTUDIO_TIMEOUT_SECONDS",
        "CIV6AI_LMSTUDIO_VISION",
        "CIV4AI_LMSTUDIO_VISION",
        "CIV6AI_LMSTUDIO_REASONING",
        "CIV6AI_CONTEXT_BUDGET",
        "CIV6AI_QUEUE_SHARED_MODEL",
        "CIV6AI_MP_MOVE_SYNC",
        "PYTHONPATH",
    ):
        if key in os.environ:
            env[key] = os.environ[key]
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _dry_run(cfg, state: Path) -> int:
    """Full sidecar pipeline against a fixture snapshot + real LM Studio (no Civ6)."""
    apply_config_to_environ(cfg)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(ROOT / "sidecar" / "run_civ6.py"),
        "--state",
        str(state),
        "--live",
        "--session-id",
        "dry-run-local",
        "--journal",
        str(LOG_DIR / "dry_run_journal.jsonl"),
    ]
    print("Dry-run (fixture + LM Studio, no Civ6):")
    print(" ", " ".join(cmd))
    print(f"  endpoint={cfg.endpoint} model={cfg.model} vision={cfg.vision} timeout={cfg.timeout_seconds}s")
    result = run_hidden(cmd, cwd=ROOT, env=_build_env(cfg), timeout=cfg.timeout_seconds + 60)
    sys.stdout.write(result.stdout or "")
    sys.stderr.write(result.stderr or "")
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Civ6Ai live sidecar workers")
    parser.add_argument("--dry-run", action="store_true", help="Fixture + LM Studio only (no game)")
    parser.add_argument(
        "--state",
        type=Path,
        default=ROOT / "fixtures" / "civ6" / "snapshot-turn-classical-golden.json",
        help="Snapshot JSON for --dry-run",
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()

    cfg = load_local_config()
    apply_config_to_environ(cfg)

    if args.dry_run:
        return _dry_run(cfg, args.state)

    if PID_FILE.is_file():
        print(f"Workers already recorded in {PID_FILE}. Run scripts/stop_live.py first.")
        return 1

    py = python_executable(prefer_pythonw=True)
    env = _build_env(cfg)
    workers: list[dict] = []

    poller = ROOT / "scripts" / "live_job_poller.py"
    workers.append(
        _spawn("job_poller", [py, str(poller), "--interval", str(args.poll_seconds)], env)
    )

    bridge = ROOT / "scripts" / "live_lua_bridge.py"
    lua_candidates = lua_log_candidates()
    lua_log = next((p for p in lua_candidates if p.is_file()), lua_candidates[0] if lua_candidates else None)
    bridge_cmd = [py, str(bridge)]
    if lua_log is not None:
        bridge_cmd.extend(["--lua-log", str(lua_log)])
    workers.append(_spawn("lua_bridge", bridge_cmd, env))

    _write_pid_record(workers)
    print(f"Started {len(workers)} hidden worker(s). PIDs -> {PID_FILE}")
    for w in workers:
        print(f"  {w['name']} pid={w['pid']} log={w['log']}")
    print("Config:", cfg.endpoint, cfg.model, f"vision={cfg.vision}", f"mp_sync={cfg.mp_move_sync}")
    print("Stop with: python scripts/stop_live.py")
    print("Watch: Lua.log + runtime/logs/*.log  (see docs/REAL_TEST.md)")
    if logs_dirs():
        print("Logs dirs:", "; ".join(str(p) for p in logs_dirs()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
