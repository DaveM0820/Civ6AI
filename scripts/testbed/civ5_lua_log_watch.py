"""Watch Civ 5 Lua.log for CIV5AI smoke-test gate markers."""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

SW_RESTORE = 9
ASFW_ANY = 0xFFFFFFFF
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

GATES: list[tuple[str, str]] = [
    ("G0", "CIV5AI|smoke|file_loaded"),
    ("G1", "CIV5AI|init|sequence_complete"),
    ("G2", "CIV5AI|init|load_screen_close"),
    ("G3", "CIV5AI|autotest|autoplay_armed"),
    ("G4", "CIV5AI|turn|active_start|turn=2"),
    ("G5", "CIV5AI|autotest|stop"),
]

G0_ALTERNATES = (
    "CIV5AI|ingame|file_loaded",
)

G1_ALTERNATES = (
    "CIV5AI|ingame|sequence_complete",
)

G2_ALTERNATES = (
    "CIV5AI|init|dawn_hidden",
    "CIV5AI|init|dawn_show",
    "CIV5AI|init|begin_journey|closed",
)

G4_ALTERNATES = (
    "CIV5AI|turn|active_start|turn=3",
    "CIV5AI|turn|player_do|turn=2",
    "CIV5AI|turn|player_do|turn=3",
)

NET_GATES: list[tuple[str, str]] = [
    ("NS", "net|send|player="),
    ("NR", "net|recv|player="),
    ("NA", "net|apply|ok"),
]

APPLY_GATES: list[tuple[str, str]] = [
    ("AR", "inbox|apply_ready|player="),
    ("AA", "net|recv|apply|player="),
]

DIPLOMACY_GATES: list[tuple[str, str]] = [
    ("DP", "apply|ok|propose_deal"),
    ("DR", "apply|ok|respond_to_deal"),
]


def gate_matched(gate_id: str, text: str) -> bool:
    if gate_id == "G0":
        return any(marker in text for marker in (GATES[0][1], *G0_ALTERNATES))
    if gate_id == "G1":
        return any(marker in text for marker in (GATES[1][1], *G1_ALTERNATES))
    if gate_id == "G2":
        return any(marker in text for marker in (GATES[2][1], *G2_ALTERNATES))
    if gate_id == "G4":
        return any(marker in text for marker in (GATES[4][1], *G4_ALTERNATES))
    for gid, marker in GATES:
        if gid == gate_id:
            return marker in text
    for gid, marker in NET_GATES:
        if gid == gate_id:
            return marker in text
    for gid, marker in APPLY_GATES:
        if gid == gate_id:
            return marker in text
    for gid, marker in DIPLOMACY_GATES:
        if gid == gate_id:
            return marker in text
    return False


def required_gates(
    require_stop: bool,
    require_net: bool = False,
    require_apply: bool = False,
    require_diplomacy: bool = False,
) -> list[str]:
    gates = ["G0", "G1", "G2", "G3", "G4"]
    if require_stop:
        gates.append("G5")
    if require_net:
        gates.extend(["NS", "NR", "NA"])
    if require_apply:
        gates.extend(["AR", "AA"])
    if require_diplomacy:
        gates.extend(["DP", "DR"])
    return gates


def read_from_offset(path: Path, offset: int) -> tuple[str, int]:
    if not path.is_file():
        return "", offset
    size = path.stat().st_size
    if offset > size:
        offset = 0
    start = min(max(0, offset), size)
    with path.open("rb") as stream:
        stream.seek(start)
        data = stream.read()
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = data.decode("latin-1", errors="replace")
    return text, size


def _civ5_hwnd() -> int:
    found: list[int] = []

    def _cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""
        if "Civilization V" in title or title.startswith("CivilizationV"):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found[0] if found else 0


class _RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


def screenshot_civ5(out_path: Path) -> str | None:
    hwnd = _civ5_hwnd()
    if not hwnd:
        print("screenshot|no_window")
        return None
    from civ4ai_controller import capture_window

    info = capture_window(hwnd, out_path)
    print(f"screenshot|{info['path']}|{info['width']}x{info['height']}")
    return str(info["path"])


def click_civ5_mods_next() -> bool:
    """Stock Mods Browser Next sits at the lower-right of the client area."""
    hwnd = _civ5_hwnd()
    if not hwnd:
        print("frontend|click_next|no_window")
        return False
    from civ4ai_controller import click_client

    client = _RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    width = max(1, client.right - client.left)
    height = max(1, client.bottom - client.top)
    x = int(width * 0.90)
    y = int(height * 0.93)
    _focus_civ5(hwnd)
    time.sleep(0.1)
    click_client(hwnd, x, y)
    print(f"frontend|click_next|client={x},{y}|{width}x{height}")
    return True


def _focus_civ5(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_RESTORE)
    try:
        user32.AllowSetForegroundWindow(ASFW_ANY)
    except Exception:
        pass
    foreground = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(foreground, None)
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()
    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, True)
    if target_tid and target_tid != cur_tid and target_tid != fg_tid:
        user32.AttachThreadInput(cur_tid, target_tid, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, False)
    if target_tid and target_tid != cur_tid and target_tid != fg_tid:
        user32.AttachThreadInput(cur_tid, target_tid, False)


def press_civ5_enter() -> bool:
    """Send Enter to Civ5 so Mods Browser Next runs from a key handler."""
    hwnd = _civ5_hwnd()
    if not hwnd:
        print("frontend|enter|no_window")
        return False
    _focus_civ5(hwnd)
    time.sleep(0.15)
    user32.keybd_event(VK_RETURN, 0, 0, 0)
    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
    print(f"frontend|enter|sent hwnd={hwnd}", flush=True)
    return True


def press_civ5_escape() -> bool:
    """Send Escape to Civ5. Closes GenericPopup as No (does not declare war)."""
    hwnd = _civ5_hwnd()
    if not hwnd:
        print("frontend|escape|no_window")
        return False
    _focus_civ5(hwnd)
    time.sleep(0.15)
    user32.keybd_event(VK_ESCAPE, 0, 0, 0)
    user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
    print(f"frontend|escape|sent hwnd={hwnd}", flush=True)
    return True


def tail_civ5ai_lines(path: Path, limit: int = 80) -> list[str]:
    if not path.is_file():
        return []
    lines: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if "CIV5AI|" in line:
                lines.append(line.rstrip("\n\r"))
    return lines[-limit:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch Civ5 Lua.log for smoke gates")
    parser.add_argument("--log", type=Path, default=None, help="Path to Lua.log")
    parser.add_argument("--from-offset", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--require-stop",
        action="store_true",
        help="Require G5 autotest|stop (default: G0-G4 only)",
    )
    parser.add_argument(
        "--require-net",
        action="store_true",
        help="Also require send/receive/apply network probe markers",
    )
    parser.add_argument(
        "--require-apply",
        action="store_true",
        help="Require LLM/fixture inbox apply (inbox|apply_ready and net|recv|apply)",
    )
    parser.add_argument(
        "--require-diplomacy",
        action="store_true",
        help="Require at least one successful propose_deal and respond_to_deal apply",
    )
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument(
        "--bridge",
        action="store_true",
        help="Run civ5_lua_log_bridge while watching (blob snapshots + sidecar)",
    )
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument(
        "--civ5ai-root",
        type=Path,
        default=None,
        help="Mod runtime folder (default: <My Games>/MODS/Civ5Ai/runtime)",
    )
    parser.add_argument(
        "--gates",
        default=None,
        help="Comma-separated gate ids to require (default: G0-G4, plus NS/NR/NA if --require-net)",
    )
    parser.add_argument(
        "--keep-watching",
        action="store_true",
        help="After required gates match, keep running until --timeout (live sidecar)",
    )
    parser.add_argument(
        "--screenshot-dir",
        type=Path,
        default=None,
        help="Directory for UI screenshots (default: <civ5ai>/autotest/screenshots)",
    )
    parser.add_argument(
        "--nudge-frontend",
        action="store_true",
        help="Screenshot, Enter, and click Mods Next once, then exit",
    )
    parser.add_argument(
        "--press-escape",
        action="store_true",
        help="Send Escape to Civ5 once (closes war-move popup as No), then exit",
    )
    args = parser.parse_args()

    log_path = args.log
    if log_path is None:
        docs = Path.home() / "Documents" / "My Games" / "Sid Meier's Civilization 5" / "Logs" / "Lua.log"
        onedrive = (
            Path.home()
            / "OneDrive"
            / "Documents"
            / "My Games"
            / "Sid Meier's Civilization 5"
            / "Logs"
            / "Lua.log"
        )
        log_path = onedrive if onedrive.is_file() else docs

    offset = max(0, args.from_offset)
    if log_path.is_file() and offset > log_path.stat().st_size:
        offset = 0
    deadline = time.monotonic() + max(1, args.timeout)
    matched: set[str] = set()
    required = required_gates(
        args.require_stop,
        args.require_net,
        args.require_apply,
        args.require_diplomacy,
    )
    if args.gates:
        required = [token.strip() for token in args.gates.split(",") if token.strip()]
    browser_ready = False
    next_started = False
    last_enter_at = 0.0
    leader_enter_due_at = 0.0
    last_leader_enter_at = 0.0
    war_escape_due_at = 0.0
    last_war_escape_at = 0.0

    repo = args.repo
    if args.bridge and repo is None:
        repo = Path(__file__).resolve().parents[2]
    if args.civ5ai_root is not None:
        civ5ai_root = args.civ5ai_root
    else:
        civ5ai_root = log_path.parent.parent / "MODS" / "Civ5Ai" / "runtime"
    shot_dir = args.screenshot_dir
    if shot_dir is None:
        shot_dir = civ5ai_root / "autotest" / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    last_shot_label = ""
    enter_attempts = 0
    last_stall_shot = 0.0
    blob_ended_at = 0.0
    apply_seen = False
    stall_apply_logged = False

    def _shot(label: str, every: bool = False) -> None:
        nonlocal last_shot_label
        if not every and last_shot_label == label:
            return
        last_shot_label = label
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            screenshot_civ5(shot_dir / f"{stamp}_{label}.png")
        except Exception as error:
            print(f"screenshot|error|{label}|{error}", flush=True)

    if args.nudge_frontend:
        _shot("nudge_before")
        press_civ5_enter()
        time.sleep(0.4)
        click_civ5_mods_next()
        time.sleep(0.6)
        _shot("nudge_after")
        return 0
    if args.press_escape:
        press_civ5_escape()
        return 0

    print(f"Watching {log_path} from offset {offset} for {args.timeout}s", flush=True)

    while time.monotonic() < deadline:
        chunk, offset = read_from_offset(log_path, offset)
        if chunk:
            for line in chunk.splitlines():
                if "CIV5AI|automation|waiting_frontend" in line:
                    browser_ready = False
                    next_started = False
                    enter_attempts = 0
                if "CIV5AI|frontend|mods_browser_ready" in line:
                    browser_ready = True
                if "CIV5AI|frontend|mods_next_begin" in line:
                    next_started = True
                    _shot("mods_next")
                if "CIV5AI|frontend|modsmenu_sp" in line:
                    _shot("mods_menu")
                if "CIV5AI|ingame|file_loaded" in line or "CIV5AI|smoke|file_loaded" in line:
                    _shot("ingame_loaded")
                if "CIV5AI|init|load_screen_close" in line:
                    _shot("load_screen_close")
                if "CIV5AI|blob|end|" in line:
                    blob_ended_at = time.monotonic()
                    apply_seen = False
                    stall_apply_logged = False
                if (
                    "apply_payload|player=" in line
                    or "bridge|apply_payload|" in line
                    or "bridge|pending_apply_ok|" in line
                    or "inbox|apply_ready|" in line
                    or "bridge|inbox_apply_done|" in line
                ):
                    apply_seen = True
                if "Handling LeaderMessage" in line:
                    # CP/EUI Goodbye is Return. Press after QueuePopup finishes.
                    leader_enter_due_at = time.monotonic() + 0.4
                if "apply|war_move_popup" in line or "apply|war_move_blocked" in line:
                    # GenericPopup Yes is first; Enter would declare war. Escape is No.
                    war_escape_due_at = time.monotonic() + 0.2
                if "CIV5AI|turn|active_start" in line or "CIV5AI|turn|player_do" in line:
                    turn_bit = "turn"
                    for token in line.split("|"):
                        if token.startswith("turn="):
                            turn_bit = token.replace("=", "")
                            break
                    _shot(f"turn_{turn_bit}")
            for gate_id in required:
                if gate_id not in matched and gate_matched(gate_id, chunk):
                    matched.add(gate_id)
                    print(f"PASS {gate_id}", flush=True)
        now = time.monotonic()
        if leader_enter_due_at > 0 and now >= leader_enter_due_at:
            leader_enter_due_at = 0.0
            if now - last_leader_enter_at >= 1.0:
                press_civ5_enter()
                last_leader_enter_at = now
                print("leader|enter|sent", flush=True)
                _shot("leader_enter", every=True)
        if war_escape_due_at > 0 and now >= war_escape_due_at:
            war_escape_due_at = 0.0
            if now - last_war_escape_at >= 1.0:
                press_civ5_escape()
                last_war_escape_at = now
                print("war_move|escape|sent", flush=True)
                _shot("war_move_escape", every=True)
        if browser_ready and not next_started:
            now = time.monotonic()
            if now - last_enter_at >= 2.0:
                press_civ5_enter()
                enter_attempts += 1
                if enter_attempts >= 2:
                    click_civ5_mods_next()
                if enter_attempts == 1 or enter_attempts % 8 == 0:
                    _shot(f"mods_stall_{enter_attempts}")
                last_enter_at = now
        now = time.monotonic()
        if (
            blob_ended_at > 0
            and not apply_seen
            and not stall_apply_logged
            and now - blob_ended_at >= 45.0
        ):
            print("STALL|apply_missing|blob_end_with_no_apply", flush=True)
            _shot("stall_apply_missing", every=True)
            stall_apply_logged = True
        if now - last_stall_shot >= 20.0:
            _shot("stall_poll", every=True)
            last_stall_shot = now
        if args.bridge and repo is not None and next_started:
            try:
                from civ5_lua_log_bridge import process_host_io

                ran = process_host_io(civ5ai_root, log_path, repo)
                if ran:
                    print(f"bridge|processed|jobs={ran}")
            except Exception as error:
                print(f"bridge|error|{error}")
        if all(g in matched for g in required):
            if not args.keep_watching:
                print("All required gates matched.")
                return 0
        time.sleep(args.poll_interval)

    if all(g in matched for g in required):
        print("All required gates matched.")
        return 0
    missing = [g for g in required if g not in matched]
    print(f"TIMEOUT missing gates: {', '.join(missing)}")
    for line in tail_civ5ai_lines(log_path):
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
