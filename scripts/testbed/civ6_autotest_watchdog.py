"""Civ6 autotest stall watchdog: detect frozen turns and capture screenshots."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from civ6_autotest_recovery import force_turn_progression, game_started, turn_has_progressed
from civ6_sidecar_jobs import discover_civ6ai_roots
from civ6_lua_log_bridge import process_host_io
from civ6_startup_log import configure_startup_logging, log_event, tail_lua_log_to_startup, close_startup_logging

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.strip():
                count += 1
    return count


def _file_mtime(path: Path) -> float:
    if not path.is_file():
        return 0.0
    return path.stat().st_mtime


def _glob_line_counts(root: Path, pattern: str) -> int:
    total = 0
    if not root.is_dir():
        return 0
    for path in root.rglob(pattern):
        if path.is_file():
            total += _count_lines(path)
    return total


@dataclass
class ProgressSnapshot:
    autotest_log_lines: int = 0
    autotest_pulses: int = 0
    autotest_max_turn: int = 0
    journal_lines: int = 0
    turn_metrics_lines: int = 0
    lua_civ6ai_lines: int = 0
    player_snapshots: int = 0
    session_summary: bool = False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "autotest_log_lines": self.autotest_log_lines,
            "autotest_pulses": self.autotest_pulses,
            "autotest_max_turn": self.autotest_max_turn,
            "journal_lines": self.journal_lines,
            "turn_metrics_lines": self.turn_metrics_lines,
            "lua_civ6ai_lines": self.lua_civ6ai_lines,
            "player_snapshots": self.player_snapshots,
            "session_summary": self.session_summary,
        }

    def activity_score(self) -> int:
        return (
            self.autotest_pulses
            + self.journal_lines
            + self.turn_metrics_lines
            + self.player_snapshots
            + self.lua_civ6ai_lines
        )


def _max_turn_from_journal_lines(journal_lines: int, civ6ai_root: Path) -> int:
    """Infer max turn from session journals when autotest.log is unavailable."""
    if journal_lines <= 0:
        return 0
    max_turn = 0
    sessions = civ6ai_root / "sessions"
    if not sessions.is_dir():
        return 0
    for journal_path in sessions.rglob("journal.jsonl"):
        if not journal_path.is_file():
            continue
        try:
            for line in journal_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    continue
                metrics = payload.get("metrics")
                turn = None
                if isinstance(metrics, dict) and metrics.get("turn") is not None:
                    turn = metrics.get("turn")
                private = payload.get("private")
                if turn is None and isinstance(private, dict) and private.get("turn") is not None:
                    turn = private.get("turn")
                if turn is not None:
                    max_turn = max(max_turn, int(turn))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return max_turn


def collect_progress(
    civ6ai_root: Path,
    lua_log: Path | None,
    extra_roots: list[Path] | None = None,
) -> ProgressSnapshot:
    roots = [civ6ai_root]
    if extra_roots:
        roots.extend(extra_roots)
    seen: set[str] = set()
    unique_roots: list[Path] = []
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        unique_roots.append(root)

    extra_autotest_logs: list[Path] = []
    if lua_log is not None:
        extra_autotest_logs.append(lua_log.parent / "civ6ai" / "autotest" / "autotest.log")

    pulses = 0
    max_turn = 0
    autotest_log_lines = 0
    journal_lines = 0
    turn_metrics_lines = 0
    snapshots = 0
    session_summary = False
    for root in unique_roots:
        autotest_logs = [root / "autotest" / "autotest.log"]
        for extra in extra_autotest_logs:
            if extra not in autotest_logs:
                autotest_logs.append(extra)
        sessions = root / "sessions"
        summary = root / "autotest" / "session_summary.json"
        if summary.is_file():
            session_summary = True
        autotest_text_parts: list[str] = []
        for autotest_log in autotest_logs:
            if not autotest_log.is_file():
                continue
            autotest_log_lines += _count_lines(autotest_log)
            try:
                autotest_text_parts.append(autotest_log.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
        autotest_text = "\n".join(autotest_text_parts)
        if autotest_text:
            pulses += sum(1 for line in autotest_text.splitlines() if "pulse|" in line)
            for line in autotest_text.splitlines():
                match = re.search(r"pulse\|turn=(\d+)", line)
                if match:
                    max_turn = max(max_turn, int(match.group(1)))
                match = re.search(r"stop\|turn=(\d+)", line)
                if match:
                    max_turn = max(max_turn, int(match.group(1)))
        journal_lines += _glob_line_counts(sessions, "journal.jsonl")
        turn_metrics_lines += _glob_line_counts(sessions, "turn_metrics.jsonl")
        if sessions.is_dir():
            snapshots += sum(1 for path in sessions.rglob("snapshot.json") if path.is_file())

    lua_lines = 0
    if lua_log and lua_log.is_file():
        with lua_log.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if "CIV6AI|" in line:
                    lua_lines += 1
                if "autotest|pulse|turn=" in line:
                    pulses += 1
                    match = re.search(r"pulse\|turn=(\d+)", line)
                    if match:
                        max_turn = max(max_turn, int(match.group(1)))
                if "autotest|stop|turn=" in line:
                    match = re.search(r"stop\|turn=(\d+)", line)
                    if match:
                        max_turn = max(max_turn, int(match.group(1)))

    return ProgressSnapshot(
        autotest_log_lines=autotest_log_lines,
        autotest_pulses=pulses,
        autotest_max_turn=max(max_turn, _max_turn_from_journal_lines(journal_lines, civ6ai_root)),
        journal_lines=journal_lines,
        turn_metrics_lines=turn_metrics_lines,
        lua_civ6ai_lines=lua_lines,
        player_snapshots=snapshots,
        session_summary=session_summary,
    )


def civ6_process_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import subprocess

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "($names = @('Civ6_Exe','Civ6_Exe_Child','CivilizationVI_DX12','CivilizationVI'); "
                "(Get-Process -Name $names -ErrorAction SilentlyContinue | Measure-Object).Count)",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return int(result.stdout.strip() or "0") > 0
    except Exception:
        return False


def _find_civ6_windows() -> list[tuple[int, str]]:
    if sys.platform != "win32":
        return []
    matches: list[tuple[int, str]] = []
    user32 = ctypes.windll.user32

    def callback(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title = buf.value or ""
        lower = title.lower()
        if "civilization" in lower or "civ6" in lower or "sid meier" in lower:
            matches.append((hwnd, title))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return matches


def _window_bbox(hwnd: int) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width < 200 or height < 200:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def capture_screenshots(output_dir: Path, reason: str) -> dict[str, Any]:
    from PIL import ImageGrab

    output_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "reason": reason,
        "captured_unix_ms": int(time.time() * 1000),
        "paths": {},
        "windows": [],
    }

    fullscreen = output_dir / "fullscreen.png"
    ImageGrab.grab(all_screens=True).save(fullscreen, format="PNG")
    meta["paths"]["fullscreen"] = str(fullscreen)

    for hwnd, title in _find_civ6_windows():
        bbox = _window_bbox(hwnd)
        window_meta = {"hwnd": hwnd, "title": title, "bbox": bbox}
        if bbox is None:
            meta["windows"].append(window_meta)
            continue
        safe = "".join(ch if ch.isalnum() else "_" for ch in title)[:40] or "civ6_window"
        window_path = output_dir / f"window_{safe}.png"
        ImageGrab.grab(bbox=bbox).save(window_path, format="PNG")
        window_meta["path"] = str(window_path)
        meta["paths"][f"window_{hwnd}"] = str(window_path)
        meta["windows"].append(window_meta)

    manifest = output_dir / "capture.json"
    manifest.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


@dataclass
class WatchdogState:
    last_progress: ProgressSnapshot | None = None
    last_activity_score: int = 0
    stall_seconds: float = 0.0
    last_screenshot_at: float = 0.0
    screenshot_count: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    game_started_at: float | None = None
    early_check_done: bool = False


def _stall_reason(progress: ProgressSnapshot, civ6_running: bool) -> str:
    if not civ6_running:
        return "civ6_not_running"
    if progress.session_summary:
        return "session_complete"
    if progress.activity_score() == 0:
        return "no_autotest_activity"
    if progress.autotest_pulses > 0:
        return "turn_progress_stalled"
    if progress.journal_lines > 0 and progress.turn_metrics_lines == 0:
        return "journal_without_metrics"
    return "turn_progress_stalled"


def run_watchdog(
    civ6ai_root: Path,
    lua_log: Path | None,
    timeout_seconds: int,
    stall_seconds: float,
    poll_seconds: float,
    screenshot_cooldown: float,
    capture_fn: Callable[[Path, str], dict[str, Any]] = capture_screenshots,
    early_check_seconds: float = 60.0,
) -> dict[str, Any]:
    autotest_dir = civ6ai_root / "autotest"
    screenshot_root = autotest_dir / "stall_screenshots"
    events_path = autotest_dir / "stall_events.jsonl"
    summary_path = autotest_dir / "session_summary.json"
    autotest_dir.mkdir(parents=True, exist_ok=True)

    civ6ai_roots = discover_civ6ai_roots(civ6ai_root)
    if lua_log is not None:
        civ6ai_roots.append(lua_log.parent / "civ6ai")
    repo = Path(__file__).resolve().parents[2]
    configure_startup_logging(civ6ai_root, lua_log)
    log_event(civ6ai_root, "watchdog_start", lua_log=lua_log, stall_seconds=stall_seconds)
    lua_offset = lua_log.stat().st_size if lua_log and lua_log.is_file() else 0
    state = WatchdogState()
    deadline = (
        time.monotonic() + max(1, timeout_seconds)
        if timeout_seconds > 0
        else float("inf")
    )
    start = time.monotonic()

    try:
        while time.monotonic() < deadline:
            process_host_io(civ6ai_root, lua_log, repo)
            lua_offset = tail_lua_log_to_startup(civ6ai_root, lua_log, offset=lua_offset)
            progress = collect_progress(civ6ai_root, lua_log, extra_roots=civ6ai_roots)
            if state.game_started_at is None and game_started(progress, lua_log):
                state.game_started_at = time.monotonic()
                log_event(
                    civ6ai_root,
                    "game_started",
                    elapsed_since_watchdog=int(time.monotonic() - start),
                )
            if (
                not state.early_check_done
                and state.game_started_at is not None
                and early_check_seconds > 0
                and (time.monotonic() - state.game_started_at) >= early_check_seconds
            ):
                state.early_check_done = True
                if not turn_has_progressed(progress):
                    recovery = force_turn_progression(
                        civ6ai_root,
                        lua_log,
                        repo,
                        reason="early_check_no_progress",
                    )
                    event = {
                        "event": "early_progression_check",
                        "elapsed_since_game_start": int(time.monotonic() - state.game_started_at),
                        "progress": progress.as_dict(),
                        "recovery": recovery,
                    }
                    state.events.append(event)
                    _append_event(events_path, event)
                    print(json.dumps(event), flush=True)
                    progress = collect_progress(civ6ai_root, lua_log, extra_roots=civ6ai_roots)
                else:
                    event = {
                        "event": "early_progression_check",
                        "status": "ok",
                        "elapsed_since_game_start": int(time.monotonic() - state.game_started_at),
                        "progress": progress.as_dict(),
                    }
                    _append_event(events_path, event)

            if progress.session_summary or summary_path.is_file():
                event = {
                    "event": "watchdog_complete",
                    "reason": "session_summary",
                    "final_turn": progress.autotest_max_turn,
                    "progress": progress.as_dict(),
                    "screenshots": state.screenshot_count,
                }
                _append_event(events_path, event)
                return {"status": "complete", "progress": progress.as_dict(), "events": state.events}

            score = progress.activity_score()
            if state.last_progress is None:
                state.last_progress = progress
                state.last_activity_score = score
            elif score > state.last_activity_score:
                state.stall_seconds = 0.0
                state.last_activity_score = score
                state.last_progress = progress
            else:
                state.stall_seconds += poll_seconds

            civ6_running = civ6_process_running()
            should_capture = (
                civ6_running
                and state.stall_seconds >= stall_seconds
                and (time.monotonic() - state.last_screenshot_at) >= screenshot_cooldown
            )
            if should_capture:
                reason = _stall_reason(progress, civ6_running)
                if sys.platform == "win32":
                    try:
                        from civ6_ui_automation import nudge_dialogs

                        nudge_dialogs()
                    except Exception:
                        pass
                stamp = _utc_stamp()
                out_dir = screenshot_root / f"{stamp}_{reason}"
                meta = capture_fn(out_dir, reason)
                state.screenshot_count += 1
                state.last_screenshot_at = time.monotonic()
                event = {
                    "event": "stall_screenshot",
                    "reason": reason,
                    "stall_seconds": state.stall_seconds,
                    "elapsed_seconds": int(time.monotonic() - start),
                    "progress": progress.as_dict(),
                    "capture_dir": str(out_dir),
                    "capture": meta,
                }
                state.events.append(event)
                _append_event(events_path, event)
                print(json.dumps(event), flush=True)
                state.stall_seconds = 0.0

            time.sleep(poll_seconds)

        progress = collect_progress(civ6ai_root, lua_log, extra_roots=civ6ai_roots)
        event = {
            "event": "watchdog_timeout",
            "progress": progress.as_dict(),
            "screenshots": state.screenshot_count,
        }
        _append_event(events_path, event)
        if civ6_process_running() and state.screenshot_count == 0:
            reason = _stall_reason(progress, True)
            out_dir = screenshot_root / f"{_utc_stamp()}_timeout_{reason}"
            meta = capture_fn(out_dir, f"timeout_{reason}")
            event["final_capture"] = meta
        return {"status": "timeout", "progress": progress.as_dict(), "events": state.events}
    finally:
        close_startup_logging()


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Civ6 autotest stall watchdog with screenshots")
    parser.add_argument("--civ6ai-root", type=Path, required=True)
    parser.add_argument("--lua-log", type=Path, help="Path to Civ6 Logs/Lua.log")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Watchdog deadline in seconds; 0 runs until session_summary",
    )
    parser.add_argument("--stall-seconds", type=float, default=90.0,
                        help="Seconds without progress before screenshot")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--screenshot-cooldown", type=float, default=60.0,
                        help="Minimum seconds between stall screenshots")
    parser.add_argument(
        "--stop-turn",
        type=int,
        default=0,
        help="When timeout fires but journal max turn reached this value, exit 0",
    )
    parser.add_argument(
        "--early-check-seconds",
        type=float,
        default=60.0,
        help="Seconds after game start to verify turn progression; force recovery if stuck",
    )
    args = parser.parse_args()

    lua_log = args.lua_log
    if lua_log is None:
        candidate = args.civ6ai_root.parent / "Logs" / "Lua.log"
        if candidate.is_file():
            lua_log = candidate

    result = run_watchdog(
        args.civ6ai_root,
        lua_log,
        args.timeout_seconds,
        args.stall_seconds,
        args.poll_seconds,
        args.screenshot_cooldown,
        early_check_seconds=args.early_check_seconds,
    )
    print(json.dumps(result, indent=2))
    if result.get("status") == "complete":
        raise SystemExit(0)
    if result.get("status") == "timeout":
        stop_turn = int(args.stop_turn or 0)
        max_turn = int(result.get("progress", {}).get("autotest_max_turn", 0) or 0)
        if stop_turn > 0 and max_turn >= stop_turn:
            print(json.dumps({"status": "stop_turn_reached", "max_turn": max_turn, "stop_turn": stop_turn}))
            raise SystemExit(0)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
