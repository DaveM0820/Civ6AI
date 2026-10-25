#!/usr/bin/env python3
"""Start Civ6Ai sidecar workers for a live (or dry-run) session.

On Windows, child processes use CREATE_NO_WINDOW / pythonw so console windows
do not cover the desktop.

Usage:
  python scripts/start_live.py
  python scripts/start_live.py --dry-run
  python scripts/start_live.py --dry-run --state fixtures/civ6/snapshot-turn-classical-golden.json
  python scripts/start_live.py --dry-run --timeout 120

--dry-run exits 0 only when the model returned a usable, parsed decision;
otherwise it prints "DRY-RUN FAIL: <reason>" and exits 1.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import circuit_breaker_state  # noqa: E402
from civ6_paths import active_lua_log, live_runtime_dir, logs_dirs, lua_log_candidates  # noqa: E402
from sidecar.civ6_config import apply_config_to_environ, load_local_config  # noqa: E402
from windows_process import pid_alive, popen_hidden, python_executable, run_hidden  # noqa: E402

PID_DIR = live_runtime_dir()
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
        "CIV6AI_PARALLEL_SEATS",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENAI_BASE_URL",
        "PYTHONPATH",
    ):
        if key in os.environ:
            env[key] = os.environ[key]
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _ascii(text: object) -> str:
    """Console-safe (cp1252) text: replace anything non-ASCII."""
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


def _last_json_record(stdout: str | None) -> dict | None:
    """The sidecar prints one JSON record as its last stdout line."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def evaluate_dry_run(returncode: int | None, stdout: str | None, stderr: str | None = "") -> tuple[bool, str]:
    """Decide whether a dry run produced a usable model decision.

    PASS only when the sidecar exited cleanly and printed an ``approved`` record
    backed by a real model reply with at least one bound command. Anything else
    (fallback, transport / model errors, no record, crash) is a FAIL with a reason.
    """
    record = _last_json_record(stdout)
    if returncode not in (0, None) and record is None:
        tail = [line for line in (stderr or "").splitlines() if line.strip()]
        detail = f": {tail[-1].strip()}" if tail else ""
        return False, f"sidecar exited with code {returncode}{detail}"
    if record is None:
        return False, "sidecar printed no decision record"
    status = record.get("status")
    category = record.get("category")
    message = record.get("message") or ""
    if status != "approved" or category == "transport":
        reason = f"status={status} category={category}"
        if message:
            reason += f": {message}"
        return False, reason
    model = record.get("model")
    if not isinstance(model, dict) or not model.get("model"):
        return False, "status=approved but no model reply metadata (model not called?)"
    commands = record.get("commands")
    if not isinstance(commands, list) or not commands:
        rejections = len((record.get("validated") or {}).get("rejections") or [])
        return False, f"model replied but no commands survived validation (rejections={rejections})"
    if returncode not in (0, None):
        return False, f"sidecar exited with code {returncode} after printing a decision"
    note = f" (salvaged from {record['salvaged_from']})" if record.get("salvaged_from") else ""
    return True, f"model={model.get('model')} commands={len(commands)}{note}"


def _dry_run(cfg, state: Path, timeout_seconds: float | None = None) -> int:
    """Full sidecar pipeline against a fixture snapshot + real LM Studio (no Civ6).

    Returns 0 only when the model produced a usable, parsed decision; 1 otherwise.
    The circuit breaker is neither enforced nor updated for dry runs, so an earlier
    failed attempt cannot block or poison this one (and dry runs do not count).
    """
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
        "--no-circuit-breaker",
    ]
    wait = float(timeout_seconds) if timeout_seconds else float(cfg.timeout_seconds + 60)
    print("Dry-run (fixture + LM Studio, no Civ6):")
    print(" ", _ascii(" ".join(cmd)))
    print(f"  endpoint={cfg.endpoint} model={cfg.model} vision={cfg.vision} timeout={cfg.timeout_seconds}s wait={wait:g}s")
    breaker_line = circuit_breaker_state.describe(LOG_DIR / "circuit_breaker.json")
    print(_ascii(f"  circuit breaker: {breaker_line} -- ignored by dry run (not enforced, not updated)"))
    try:
        result = run_hidden(cmd, cwd=ROOT, env=_build_env(cfg), timeout=wait)
    except subprocess.TimeoutExpired:
        print(_ascii(f"DRY-RUN FAIL: sidecar did not finish within {wait:g}s (LM Studio slow or hung?)"))
        return 1
    sys.stdout.write(_ascii(result.stdout or ""))
    sys.stderr.write(_ascii(result.stderr or ""))
    if result.stdout and not result.stdout.endswith("\n"):
        sys.stdout.write("\n")
    ok, reason = evaluate_dry_run(result.returncode, result.stdout, result.stderr)
    if ok:
        print(_ascii(f"DRY-RUN PASS: {reason}"))
        return 0
    print(_ascii(f"DRY-RUN FAIL: {reason}"))
    print("  Fix: start LM Studio server, load the model, run python scripts/preflight.py, then retry.")
    return 1


def rotate_session_requested(args: argparse.Namespace) -> bool:
    """A bare start, and --keep-session, reuse the session already on disk."""
    return bool(getattr(args, "new_session", False))


def _start_new_session() -> None:
    """Fresh session id for the next game + no stale per-player files or log backlog.

    The session id reaches Lua through the installed Civ6Ai_Paths.lua, which Civ6
    reads when a game loads; rotating it here (before the game starts) is what
    stops a new game from reusing the previous game's session directory.
    """
    try:
        from install_mod import rotate_session

        info = rotate_session()
        print(
            _ascii(
                f"New session: {info['new']} (previous: {info['old'] or '-'}); "
                f"updated {len(info['updated'])} installed module(s); archived {info['archived']} stale file(s)."
            )
        )
        if not info["updated"]:
            print("WARNING: no installed Civ6Ai_Paths.lua with a SessionId; run scripts/install_mod.py first.")
    except Exception as error:  # pragma: no cover - host dependent
        print(_ascii(f"WARNING: session rotation failed: {error}"))
    # Skip Lua.log content written before this session (old games' snapshot blobs
    # and nudge requests). A Civ6 restart rewrites Lua.log and resets the offset.
    try:
        if str(ROOT / "scripts" / "testbed") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
        from civ6_lua_log_bridge import store_log_offset
        from civ6_paths import civ6ai_root

        lua_log = active_lua_log()
        if lua_log is not None:
            autotest = civ6ai_root() / "autotest"
            size = lua_log.stat().st_size
            store_log_offset(autotest / "lua_nudge_offset.txt", lua_log, size)
            # A game that just began before the helpers started (log written in the last
            # 30 min, newest turn <= 3) keeps its snapshots: read from its first blob.
            # Older content is a previous game's backlog and is skipped.
            from civ6_new_game import current_game_offset

            fresh = time.time() - lua_log.stat().st_mtime < 1800
            start = current_game_offset(lua_log.read_bytes(), max_turn=3) if fresh else None
            bridge_at = size if start is None else start
            store_log_offset(autotest / "lua_bridge_offset.txt", lua_log, bridge_at)
            print(f"Lua.log offsets: bridge at {bridge_at}, nudges at end ({size} bytes).")
    except Exception as error:  # pragma: no cover - host dependent
        print(_ascii(f"WARNING: Lua.log offset reset failed: {error}"))


def recorded_live_workers(pid_file: Path, alive=pid_alive) -> list[dict]:
    """Workers in live_workers.json whose PID is still running (empty for a stale record)."""
    try:
        payload = json.loads(pid_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    workers = payload.get("workers") if isinstance(payload, dict) else None
    if not isinstance(workers, list):
        return []
    return [w for w in workers if isinstance(w, dict) and alive(int(w.get("pid") or 0))]


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
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Keep the current session id, Lua.log offsets, and queued answers. This is the default.",
    )
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Start a fresh session for a new game (new session id, archive stale per-player files, "
        "move Lua.log offsets to the end, clear PendingApply).",
    )
    parser.add_argument(
        "--no-watchdog",
        action="store_true",
        help="Do not start live_watchdog.py (it respawns a dead job_poller / lua_bridge, same session).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="--dry-run only: max seconds to wait for the sidecar (default: config timeout + 60)",
    )
    args = parser.parse_args()

    cfg = load_local_config()
    apply_config_to_environ(cfg)

    if args.dry_run:
        return _dry_run(cfg, args.state, args.timeout)

    if PID_FILE.is_file():
        alive = recorded_live_workers(PID_FILE)
        if alive:
            names = ", ".join(f"{w.get('name')} pid={w.get('pid')}" for w in alive)
            print(f"Workers already running ({names}). Run scripts/stop_live.py first.")
            return 1
        print(f"Stale {PID_FILE.name}: no recorded worker is running; treating the helpers as stopped.")
        PID_FILE.unlink(missing_ok=True)

    # Reuse the session already on disk unless a new game was asked for.
    # --keep-session is the same as the default, so an old restart command still works.
    if args.new_session and args.keep_session:
        print("WARNING: --new-session and --keep-session were both set; starting a new session.")
    if rotate_session_requested(args):
        _start_new_session()
    else:
        print("Keeping the current session. Pass --new-session to rotate it.")

    # A PendingApply module left over from an earlier session is rejected by Lua
    # every frame (stale session id); clear it only when rotating.
    # Queued answers belong to the running game, so a helper restart must leave them.
    try:
        if not rotate_session_requested(args):
            raise RuntimeError("kept for the current session")
        if str(ROOT / "scripts" / "testbed") not in sys.path:
            sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
        from civ6_host_channel import clear_pending_apply_lua

        clear_pending_apply_lua()
        print("Cleared stale PendingApply module(s).")
    except Exception as error:  # pragma: no cover - best effort on host
        print(f"PendingApply clear skipped: {_ascii(error)}")

    py = python_executable(prefer_pythonw=True)
    env = _build_env(cfg)
    workers: list[dict] = []

    poller = ROOT / "scripts" / "live_job_poller.py"
    workers.append(
        _spawn("job_poller", [py, str(poller), "--interval", str(args.poll_seconds)], env)
    )

    bridge = ROOT / "scripts" / "live_lua_bridge.py"
    # No --lua-log: the bridge follows whichever candidate Civ6 is writing
    # (newest mtime) and switches when another becomes active.
    lua_log = active_lua_log()
    print(_ascii(f"Lua.log (active now): {lua_log}"))
    bridge_cmd = [py, str(bridge)]
    workers.append(_spawn("lua_bridge", bridge_cmd, env))

    if not args.no_watchdog:
        # First in the record so stop_live stops it before the workers it would respawn.
        watchdog = ROOT / "scripts" / "live_watchdog.py"
        workers.insert(0, _spawn("watchdog", [py, str(watchdog)], env))
    _write_pid_record(workers)
    print(f"Started {len(workers)} hidden worker(s). PIDs -> {PID_FILE}")
    for w in workers:
        print(f"  {w['name']} pid={w['pid']} log={w['log']}")
    print("Config:", cfg.endpoint, cfg.model, f"vision={cfg.vision}")
    print("Stop with: python scripts/stop_live.py")
    print(f"Watch: Lua.log + {LOG_DIR}\\*.log  (see docs/REAL_TEST.md)")
    if logs_dirs():
        print("Logs dirs:", "; ".join(str(p) for p in logs_dirs()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
