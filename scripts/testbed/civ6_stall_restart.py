"""Watchdog stall detection: when to restart the live helpers, and when not to.

A restart (stop_live then start_live, same session) is worth trying when:

(a) stalled: a seat's snapshot has waited for an answer (snapshot.json newer
    than decision.json) with no helper/pipeline activity for
    CIV6AI_WATCHDOG_STALL_MINUTES. A seat with nothing pending (every snapshot
    answered) never counts, so a human taking a long turn is left alone; or
(b) failing: in the last window, at least CIV6AI_WATCHDOG_FAIL_SEAT_PERCENT of
    the seats each logged CIV6AI_WATCHDOG_FAIL_COUNT or more consecutive
    sidecar failures in lua_bridge.log.

Guards: at most one restart per CIV6AI_WATCHDOG_RESTART_GAP_MINUTES and
CIV6AI_WATCHDOG_MAX_RESTARTS_PER_TURN per game turn. A failure whose error
line matches the one that triggered the previous restart is deterministic:
a restart cannot fix it, so it is logged loudly and no restart happens.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

FAIL_MARKERS = ("Pending snapshot sidecar failed", "Lua-log sidecar failed")
OK_MARKER = "Pending apply published"
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ ")
_PLAYER = re.compile(r"PLAYER_(\d+)|player=(\d+)")


def settings_values() -> dict[str, int]:
    from sidecar import settings

    return {
        "stall_minutes": settings.get_int("CIV6AI_WATCHDOG_STALL_MINUTES"),
        "fail_count": settings.get_int("CIV6AI_WATCHDOG_FAIL_COUNT"),
        "fail_seat_percent": settings.get_int("CIV6AI_WATCHDOG_FAIL_SEAT_PERCENT"),
        "gap_minutes": settings.get_int("CIV6AI_WATCHDOG_RESTART_GAP_MINUTES"),
        "max_per_turn": settings.get_int("CIV6AI_WATCHDOG_MAX_RESTARTS_PER_TURN"),
    }


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _turn_of(snapshot: Path) -> int:
    try:
        data = json.loads(snapshot.read_text(encoding="utf-8-sig"))
        return int((data.get("decision") or {}).get("turn") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def session_activity(session_dir: Path, log_files: list[Path]) -> dict[str, Any]:
    """Pending seats (snapshot newer than its answer), last activity time and game turn."""
    pending: list[str] = []
    last = 0.0
    turn = 0
    for seat in sorted(session_dir.glob("PLAYER_*")):
        snap = seat / "snapshot.json"
        if not snap.is_file():
            continue
        turn = max(turn, _turn_of(snap))
        s_time, d_time = _mtime(snap), _mtime(seat / "decision.json")
        if s_time > d_time + 1:
            pending.append(seat.name)
        for name in ("snapshot.json", "decision.json", "apply-results.jsonl", "journal.jsonl", "sidecar_job.json"):
            last = max(last, _mtime(seat / name))
    for path in log_files:
        last = max(last, _mtime(path))
    return {"pending": pending, "last_activity": last, "turn": turn}


def error_signature(text: str) -> str:
    """Comparable form of an error line: digits, paths and ids normalized."""
    line = text.strip().splitlines()[-1] if text.strip() else ""
    line = re.sub(r"[A-Za-z]:\\[^ '\"]*|/[^ '\"]*/[^ '\"]*", "<path>", line)
    line = re.sub(r"\d+", "N", line)
    return line[:300]


def recent_failures(log_text: str, since: float) -> list[dict[str, Any]]:
    """Sidecar outcome records after ``since``: failures (with the error's last line)
    and answers published (``ok``), in log order."""
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in log_text.splitlines():
        stamp = _TS.match(line)
        if stamp:
            if current is not None:
                records.append(current)
                current = None
            ok = OK_MARKER in line
            if ok or any(m in line for m in FAIL_MARKERS):
                when = time.mktime(time.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S"))
                match = _PLAYER.search(line)
                seat = (match.group(1) or match.group(2)) if match else "?"
                current = {"time": when, "seat": seat, "lines": [line], "ok": ok}
        elif current is not None and line.strip():
            current["lines"].append(line)
    if current is not None:
        records.append(current)
    out = []
    for rec in records:
        if rec["time"] < since:
            continue
        if rec["ok"]:
            out.append(rec)
            continue
        tail = [l for l in rec["lines"] if "Error" in l or "error" in l] or rec["lines"]
        rec["last_error"] = tail[-1].strip()[:400]
        rec["signature"] = error_signature(rec["last_error"])
        out.append(rec)
    return out


def failing_seats(records: list[dict[str, Any]], seats: int, fail_count: int, percent: int) -> tuple[bool, list[str]]:
    """True when enough seats each have ``fail_count`` consecutive failures at the end of the window."""
    streak: dict[str, int] = {}
    for rec in records:
        streak[rec["seat"]] = 0 if rec.get("ok") else streak.get(rec["seat"], 0) + 1
    bad = sorted(s for s, n in streak.items() if n >= fail_count)
    need = max(1, -(-max(1, seats) * percent // 100))
    return len(bad) >= need, bad


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def decide(*, now: float, activity: dict[str, Any], failures: list[dict[str, Any]], seats: int,
           state: dict[str, Any], cfg: dict[str, int]) -> dict[str, Any]:
    """Decision: {"action": "restart"|"none"|"blocked", "reason", "last_error", ...}."""
    stall_secs = cfg["stall_minutes"] * 60
    reason = ""
    errors = [f for f in failures if not f.get("ok")]
    last_error = errors[-1]["last_error"] if errors else ""
    signature = errors[-1]["signature"] if errors else ""
    is_failing, bad = failing_seats(failures, seats, cfg["fail_count"], cfg["fail_seat_percent"])
    idle = now - float(activity.get("last_activity") or 0)
    if is_failing:
        reason = f"sidecar failing for seats {','.join(bad)} ({len(errors)} failures)"
    elif activity.get("pending") and idle >= stall_secs:
        reason = (f"stalled: {','.join(activity['pending'])} waiting for an answer, "
                  f"no pipeline activity for {int(idle // 60)} min")
    if not reason:
        return {"action": "none"}
    out = {"reason": reason, "last_error": last_error, "signature": signature, "turn": activity.get("turn", 0)}
    if signature and signature == state.get("last_signature") and state.get("last_restart"):
        out["action"] = "blocked"
        out["why"] = "same error as before the last restart: deterministic, a restart will not fix it"
        return out
    if now - float(state.get("last_restart") or 0) < cfg["gap_minutes"] * 60:
        out["action"] = "blocked"
        out["why"] = f"backoff: last restart under {cfg['gap_minutes']} min ago"
        return out
    turn = int(activity.get("turn") or 0)
    per_turn = int((state.get("per_turn") or {}).get(str(turn)) or 0)
    if per_turn >= cfg["max_per_turn"]:
        out["action"] = "blocked"
        out["why"] = f"already {per_turn} restarts on turn {turn}"
        return out
    out["action"] = "restart"
    return out


def record_restart(state: dict[str, Any], now: float, decision: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["last_restart"] = now
    state["last_signature"] = decision.get("signature") or ""
    per_turn = dict(state.get("per_turn") or {})
    key = str(decision.get("turn") or 0)
    per_turn = {key: int(per_turn.get(key) or 0) + 1}
    state["per_turn"] = per_turn
    return state
