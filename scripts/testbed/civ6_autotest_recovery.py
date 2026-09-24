"""Autotest recovery: detect turn stall and force host apply / UI nudges."""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from civ6_lua_log_bridge import process_host_io, sync_session_files

log = logging.getLogger(__name__)

_INGAME_MARKERS = (
    "CIV6AI|ingame|ready",
    "CIV6AI|autotest|local_turn_begin",
    "CIV6AI|bridge|pulse",
    "CIV6AI|blob|begin|snapshot",
    "CIV6AI|autotest|enabled",
)


def _read_runtime(civ6ai_root: Path) -> dict[str, Any]:
    path = civ6ai_root / "runtime.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _active_session_dir(civ6ai_root: Path) -> Path | None:
    runtime = _read_runtime(civ6ai_root)
    session_id = str(runtime.get("session_id") or "").strip()
    sessions = civ6ai_root / "sessions"
    if session_id:
        candidate = sessions / session_id
        if candidate.is_dir():
            return candidate
    if not sessions.is_dir():
        return None
    autotest = sorted(
        [p for p in sessions.iterdir() if p.is_dir() and p.name.startswith("autotest-")],
        key=lambda p: p.stat().st_mtime,
    )
    return autotest[-1] if autotest else None


def game_started(progress: Any, lua_log: Path | None) -> bool:
    """True once in-game autotest activity is visible."""
    if progress.player_snapshots > 0 or progress.journal_lines > 0:
        return True
    if progress.autotest_pulses > 0 or progress.turn_metrics_lines > 0:
        return True
    if lua_log is not None and lua_log.is_file():
        try:
            tail = lua_log.read_text(encoding="utf-8", errors="replace")[-8000:]
        except OSError:
            tail = ""
        if any(marker in tail for marker in _INGAME_MARKERS):
            return True
    return False


def turn_has_progressed(progress: Any, *, past_turn: int = 1) -> bool:
    """True when autotest has advanced past turn `past_turn` (default: left turn 1)."""
    return progress.autotest_max_turn >= past_turn + 1


def force_turn_progression(
    civ6ai_root: Path,
    lua_log: Path | None,
    repo: Path,
    *,
    reason: str = "early_check",
) -> dict[str, Any]:
    """Retry sidecar inject and UI nudges when the game is stuck on turn 1."""
    from civ6_startup_log import log_event

    result: dict[str, Any] = {
        "reason": reason,
        "injected": [],
        "host_io_ran": False,
        "nudge": False,
        "session": None,
    }
    log_event(civ6ai_root, "force_progression_start", reason=reason)
    try:
        process_host_io(civ6ai_root, lua_log, repo)
        result["host_io_ran"] = True
    except Exception as error:
        log.warning("force progression host_io failed: %s", error)
        result["host_io_error"] = str(error)

    sync_session_files(civ6ai_root, lua_log)

    session_dir = _active_session_dir(civ6ai_root)
    if session_dir is not None:
        result["session"] = session_dir.name
        try:
            from civ6_pending_apply import publish_from_player_dir

            for player_dir in sorted(session_dir.glob("PLAYER_*")):
                if not player_dir.is_dir():
                    continue
                try:
                    ok = publish_from_player_dir(player_dir)
                    result["injected"].append({"player_dir": player_dir.name, "ok": ok})
                except Exception as error:
                    log.warning("force inject failed %s: %s", player_dir, error)
                    result["injected"].append(
                        {"player_dir": player_dir.name, "ok": False, "error": str(error)}
                    )
        except ImportError as error:
            result["inject_error"] = str(error)

    if sys.platform == "win32":
        try:
            from civ6_ui_automation import find_civ_window, focus_game, nudge_dialogs

            win = find_civ_window()
            if win is not None:
                focus_game(win.hwnd)
                time.sleep(0.2)
                result["nudge"] = nudge_dialogs(win, enter_count=5)
        except Exception as error:
            log.warning("force progression nudge failed: %s", error)
            result["nudge_error"] = str(error)

    try:
        process_host_io(civ6ai_root, lua_log, repo)
    except Exception as error:
        log.warning("force progression host_io (post-nudge) failed: %s", error)

    log_event(civ6ai_root, "force_progression_done", reason=reason, session=result.get("session"))
    return result
