"""Bootstrap Civ6 autotest session: timer-based UI clicks, then wait for Lua ingame.

STABLE PATH (verified working — do not refactor casually):
  dismiss -> bootstrap_create_game_timed -> ingame wait (_ingame_ready)
See .cursor/rules/civ6-stable-runtime.mdc before editing this file or menu bootstrap.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from civ6_lua_log_bridge import process_host_io
from civ6_startup_log import configure_startup_logging, log_event, tail_lua_log_to_startup
from civ6_sidecar_jobs import discover_civ6ai_roots
from civ6_ui_automation import (
    audit_screenshot,
    bootstrap_create_game_timed,
    bootstrap_dismiss_timed,
    find_civ_window,
    focus_game,
    nudge_dialogs,
    navigate_load_save,
    refresh_window,
)

_INGAME_MARKERS = (
    "CIV6AI|ingame|catchup",
    "CIV6AI|bridge|pulse",
    "CIV6AI|bridge|snapshot_dumped",
    "CIV6AI|blob|begin|",
    "CIV6AI|autotest|enabled",
    "CIV6AI|autotest|pulse|turn=",
    "MP_helper: Turn",
)

log = logging.getLogger(__name__)


def _lua_log_chunk(lua_log: Path | None, start_offset: int = 0) -> str:
    if lua_log is None or not lua_log.is_file():
        return ""
    try:
        with lua_log.open(encoding="utf-8", errors="replace") as handle:
            handle.seek(max(0, start_offset))
            return handle.read()
    except OSError:
        return ""


def _lua_log_has_ingame(lua_log: Path | None, start_offset: int = 0) -> bool:
    chunk = _lua_log_chunk(lua_log, start_offset)
    if not chunk:
        return False
    return any(marker in chunk for marker in _INGAME_MARKERS)


def _autotest_log_has_pulse(civ6ai_roots: list[Path]) -> bool:
    for root in civ6ai_roots:
        autotest_log = root / "autotest" / "autotest.log"
        if not autotest_log.is_file():
            continue
        try:
            tail = autotest_log.read_text(encoding="utf-8", errors="replace")[-4000:]
            if "pulse|turn=" in tail or "end_turn|player=" in tail:
                return True
        except OSError:
            pass
    return False


def _lua_log_has_pulse(lua_log: Path | None, start_offset: int = 0) -> bool:
    chunk = _lua_log_chunk(lua_log, start_offset)
    return "autotest|pulse|turn=" in chunk or "autotest|end_turn|player=" in chunk


def _resolve_bootstrap_save(civ6ai_root: Path, saves_single: Path | None) -> Path | None:
    candidates = [
        civ6ai_root / "autotest" / "bootstrap.Civ6Save",
        saves_single / "civ6ai_autotest.Civ6Save" if saves_single else None,
    ]
    for path in candidates:
        if path is not None and path.is_file():
            return path
    return None


def _save_stem(path: Path) -> str:
    name = path.name
    if name.lower().endswith(".civ6save"):
        return name[:-9]
    return path.stem


def _ingame_ready(
    lua_log: Path | None,
    civ6ai_roots: list[Path],
    lua_log_offset: int,
) -> bool:
    return (
        _lua_log_has_ingame(lua_log, lua_log_offset)
        or _lua_log_has_pulse(lua_log, lua_log_offset)
        or _autotest_log_has_pulse(civ6ai_roots)
    )


def run_bootstrap(
    civ6ai_root: Path,
    lua_log: Path | None,
    saves_single: Path | None,
    prefer_load: bool,
    menu_timeout: float,
    load_timeout: float,
) -> dict:
    from civ6_ui_automation import _BOOTSTRAP_INGAME_POLL_S, _BOOTSTRAP_NUDGE_INTERVAL_S

    audit_dir = civ6ai_root / "autotest" / "bootstrap_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    configure_startup_logging(civ6ai_root, lua_log)
    log_event(civ6ai_root, "bootstrap_start", lua_log=lua_log, timed=True)
    events: list[str] = []
    lua_log_offset = 0
    if lua_log is not None and lua_log.is_file():
        try:
            lua_log_offset = lua_log.stat().st_size
        except OSError:
            lua_log_offset = 0

    win = None
    deadline = time.monotonic() + min(menu_timeout, 45.0)
    while time.monotonic() < deadline:
        win = find_civ_window()
        if win is not None:
            break
        time.sleep(0.5)
    if win is None:
        raise RuntimeError("Civ6 window not found")

    for _ in range(5):
        if focus_game(win.hwnd):
            break
        time.sleep(0.4)

    # STABLE: Esc dismiss + fixed wait — do not replace with OCR/menu detection.
    events.extend(bootstrap_dismiss_timed(win))
    audit_screenshot(win, audit_dir, "after_dismiss")

    bootstrap_save = _resolve_bootstrap_save(civ6ai_root, saves_single)
    loaded = False
    if prefer_load and bootstrap_save is not None:
        try:
            save_name = _save_stem(bootstrap_save)
            events.extend(navigate_load_save(win, save_name))
            loaded = True
            events.append(f"loaded_save={save_name}")
        except RuntimeError as error:
            log.warning("Load save failed: %s", error)
            events.append(f"load_failed={error}")
            audit_screenshot(win, audit_dir, "load_failed")

    if not loaded:
        # STABLE: recorded menu sequence + Begin Game rounds — see civ6_menu_sequence.json.
        events.extend(bootstrap_create_game_timed(win))
        audit_screenshot(win, audit_dir, "after_create_game")

    civ6ai_roots = discover_civ6ai_roots(civ6ai_root)
    repo = Path(__file__).resolve().parents[2]
    # STABLE: wait for first pulse / ingame markers — triggers sidecar without editing Bridge pulse code.
    ingame_deadline = time.monotonic() + load_timeout
    last_nudge = 0.0
    while time.monotonic() < ingame_deadline:
        process_host_io(civ6ai_root, lua_log, repo)
        if _ingame_ready(lua_log, civ6ai_roots, lua_log_offset):
            break
        now = time.monotonic()
        if now - last_nudge >= _BOOTSTRAP_NUDGE_INTERVAL_S:
            try:
                win = refresh_window(win) if win is not None else find_civ_window()
                if win is not None:
                    nudge_dialogs(win)
            except Exception as error:
                log.warning("bootstrap nudge failed: %s", error)
            last_nudge = now
        time.sleep(_BOOTSTRAP_INGAME_POLL_S)

    audit_screenshot(win, audit_dir, "after_ingame_wait")

    if not _ingame_ready(lua_log, civ6ai_roots, lua_log_offset):
        audit_screenshot(win, audit_dir, "not_ingame")
        raise RuntimeError("Game did not reach in-game autotest state")

    events.append("ingame_ok")
    log_event(civ6ai_root, "bootstrap_complete", lua_log=lua_log, events=len(events))
    tail_lua_log_to_startup(civ6ai_root, lua_log, offset=lua_log_offset)
    report = {
        "ok": True,
        "events": events,
        "audit_dir": str(audit_dir),
        "bootstrap_save": str(bootstrap_save) if bootstrap_save else None,
        "loaded_save": loaded,
    }
    report_path = civ6ai_root / "autotest" / "bootstrap_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Civ6 autotest UI bootstrap")
    parser.add_argument("--civ6ai-root", type=Path, required=True)
    parser.add_argument("--lua-log", type=Path, default=None)
    parser.add_argument("--saves-single", type=Path, default=None)
    parser.add_argument("--prefer-load", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--menu-timeout", type=float, default=60.0)
    parser.add_argument("--load-timeout", type=float, default=90.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        report = run_bootstrap(
            civ6ai_root=args.civ6ai_root,
            lua_log=args.lua_log,
            saves_single=args.saves_single,
            prefer_load=args.prefer_load,
            menu_timeout=args.menu_timeout,
            load_timeout=args.load_timeout,
        )
        print(json.dumps(report, indent=2))
        return 0
    except Exception as error:
        log.error("Bootstrap failed: %s", error)
        fail_report = {"ok": False, "error": str(error)}
        fail_path = args.civ6ai_root / "autotest" / "bootstrap_report.json"
        fail_path.parent.mkdir(parents=True, exist_ok=True)
        fail_path.write_text(json.dumps(fail_report, indent=2) + "\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
