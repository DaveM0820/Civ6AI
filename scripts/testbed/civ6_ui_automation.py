"""Windows OCR + click helpers for Civ6 menu automation (no human in the loop)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Structure):
    _fields_ = [("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_input", _INPUT_UNION),
    ]


def _send_input_keyboard(vk: int, keyup: bool = False) -> None:
    user32 = ctypes.windll.user32
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.dwFlags = KEYEVENTF_KEYUP if keyup else 0
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _send_input_unicode_text(text: str) -> None:
    if not text:
        return
    user32 = ctypes.windll.user32
    for ch in text:
        code = ord(ch)
        down = _INPUT()
        down.type = INPUT_KEYBOARD
        down.ki.wScan = code
        down.ki.dwFlags = KEYEVENTF_UNICODE
        up = _INPUT()
        up.type = INPUT_KEYBOARD
        up.ki.wScan = code
        up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))
        time.sleep(0.008)


def press_enter_sendinput(win: WindowInfo, *, refocus: bool = True) -> None:
    if refocus:
        focus_game(win.hwnd)
        time.sleep(0.04)
    _send_input_keyboard(VK_RETURN, keyup=False)
    time.sleep(0.02)
    _send_input_keyboard(VK_RETURN, keyup=True)


def press_space_sendinput(win: WindowInfo) -> None:
    focus_game(win.hwnd)
    time.sleep(0.04)
    _send_input_keyboard(0x20, keyup=False)
    time.sleep(0.02)
    _send_input_keyboard(0x20, keyup=True)


def type_text_sendinput(win: WindowInfo, text: str) -> None:
    focus_game(win.hwnd)
    time.sleep(0.04)
    user32 = ctypes.windll.user32
    VK_SHIFT = 0x10
    for ch in text:
        code = user32.VkKeyScanW(ord(ch))
        if code == -1:
            _send_input_unicode_text(ch)
            continue
        vk = code & 0xFF
        shift = (code >> 8) & 0xFF
        if shift & 1:
            _send_input_keyboard(VK_SHIFT, keyup=False)
        _send_input_keyboard(vk, keyup=False)
        time.sleep(0.006)
        _send_input_keyboard(vk, keyup=True)
        if shift & 1:
            _send_input_keyboard(VK_SHIFT, keyup=True)
        time.sleep(0.006)


@dataclass
class WindowInfo:
    hwnd: int
    x: int
    y: int
    w: int
    h: int


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Civ6 UI automation currently supports Windows only")


def _process_exe_name(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(260)
        size = ctypes.c_uint32(260)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)
    return ""


_CIV_GAME_EXES = frozenset(
    {
        "civilizationv.exe",
        "civilizationvi.exe",
        "civilizationvi_dx12.exe",
        "civ6_exe.exe",
        "civ6_exe_child.exe",
    }
)


def find_civ_window() -> WindowInfo | None:
    _require_windows()
    import win32gui
    import win32process

    user32 = ctypes.windll.user32
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_ssize_t(-4)
    old_ctx = None
    try:
        old_ctx = user32.SetThreadDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
    except Exception:
        pass

    matches: list[WindowInfo] = []

    def callback(hwnd: int, _: None) -> bool:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe = _process_exe_name(pid).lower()
        title = win32gui.GetWindowText(hwnd) or ""
        exe_match = exe in _CIV_GAME_EXES
        title_match = "Civilization" in title
        if not exe_match and not title_match:
            return True
        if not win32gui.IsWindowVisible(hwnd) and not exe_match:
            return True
        cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
        w = cr - cl
        h = cb - ct
        min_w = 200 if exe_match else 400
        min_h = 200 if exe_match else 300
        if w < min_w or h < min_h:
            return True
        screen_x, screen_y = win32gui.ClientToScreen(hwnd, (cl, ct))
        matches.append(
            WindowInfo(hwnd=hwnd, x=screen_x, y=screen_y, w=w, h=h)
        )
        return True

    win32gui.EnumWindows(callback, None)

    if old_ctx:
        user32.SetThreadDpiAwarenessContext(ctypes.c_ssize_t(old_ctx))

    if not matches:
        return None
    return max(matches, key=lambda m: m.w * m.h)


def _hide_blocking_overlays(game_win: WindowInfo) -> list[str]:
    """Hide third-party overlays (Discord, etc.) stacked on top of the game window."""
    import win32gui

    hidden: list[str] = []
    overlay_markers = ("overlay", "nvidia", "geforce", "xbox")

    def callback(hwnd: int, _: None) -> bool:
        if hwnd == game_win.hwnd or not win32gui.IsWindowVisible(hwnd):
            return True
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        lower = title.lower()
        if not title and win32gui.GetClassName(hwnd) not in ("CEF-OSC-WIDGET",):
            return True
        if not any(marker in lower for marker in overlay_markers) and title != "Discord Overlay":
            if win32gui.GetClassName(hwnd) != "CEF-OSC-WIDGET":
                return True
        cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
        w, h = cr - cl, cb - ct
        if w < game_win.w - 80 or h < game_win.h - 80:
            return True
        win32gui.ShowWindow(hwnd, 0)
        hidden.append(title or win32gui.GetClassName(hwnd))
        return True

    win32gui.EnumWindows(callback, None)
    if hidden:
        log.info("Hidden overlay windows: %s", ", ".join(hidden))
    return hidden


def refresh_window(win: WindowInfo) -> WindowInfo:
    import win32gui

    def _hwnd_usable(hwnd: int) -> bool:
        if not win32gui.IsWindow(hwnd):
            return False
        try:
            cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
            return (cr - cl) > 0 and (cb - ct) > 0
        except Exception:
            return False

    if not _hwnd_usable(win.hwnd):
        found = None
        for _ in range(24):
            found = find_civ_window()
            if found is not None:
                break
            time.sleep(0.25)
        if found is None:
            raise RuntimeError("Civ6 window handle stale and no replacement found")
        log.info("refreshed stale hwnd %d -> %d", win.hwnd, found.hwnd)
        win = found
    cl, ct, cr, cb = win32gui.GetClientRect(win.hwnd)
    sx, sy = _client_to_screen(win.hwnd, cl, ct)
    return WindowInfo(hwnd=win.hwnd, x=sx, y=sy, w=cr - cl, h=cb - ct)


def _game_launcher():
    import sys
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "artifacts" / "reference" / "civ6-mcp" / "src"
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
    from civ_mcp import game_launcher

    return game_launcher


def focus_game(hwnd: int) -> bool:
    """Bring the given Civ6 hwnd to the foreground; return True if it is focused."""
    user32 = ctypes.windll.user32
    if user32.GetForegroundWindow() == hwnd:
        return True
    try:
        import win32gui

        try:
            user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
        except Exception:
            pass
        our_thread = user32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached_fg = False
        attached_target = False
        if fg_thread and fg_thread != our_thread:
            attached_fg = bool(user32.AttachThreadInput(our_thread, fg_thread, True))
        if target_thread and target_thread != our_thread:
            attached_target = bool(user32.AttachThreadInput(our_thread, target_thread, True))
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, 9)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        if attached_target:
            user32.AttachThreadInput(our_thread, target_thread, False)
        if attached_fg:
            user32.AttachThreadInput(our_thread, fg_thread, False)
    except Exception:
        log.debug("focus_game failed for hwnd %s", hwnd)
    time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


def _foreground_matches_civ(win: WindowInfo) -> bool:
    user32 = ctypes.windll.user32
    fg = user32.GetForegroundWindow()
    if fg == win.hwnd:
        return True
    if not fg:
        return False
    try:
        import win32process

        _, civ_pid = win32process.GetWindowThreadProcessId(win.hwnd)
        _, fg_pid = win32process.GetWindowThreadProcessId(fg)
        return civ_pid != 0 and civ_pid == fg_pid
    except Exception:
        return False


def _civ_sendinput_ready(win: WindowInfo) -> bool:
    """True when keystrokes/clicks should reach Civ6 (main hwnd or same-process child)."""
    user32 = ctypes.windll.user32
    if user32.GetForegroundWindow() == win.hwnd:
        return True
    return _foreground_matches_civ(win)


def _post_client_click(hwnd: int, client_x: int, client_y: int, taps: int = 1) -> None:
    """Click via posted mouse messages so Cursor stealing focus cannot eat the input."""
    user32 = ctypes.windll.user32
    lparam = (int(client_y) << 16) | (int(client_x) & 0xFFFF)
    for _ in range(max(1, taps)):
        user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)  # WM_LBUTTONDOWN
        time.sleep(0.04)
        user32.PostMessageW(hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP
        time.sleep(0.08)


def _send_mouse_click_screen(screen_x: int, screen_y: int, taps: int = 1) -> None:
    """Click via civ6-mcp SendInput after the game is already foreground."""
    gl = _game_launcher()
    ctypes.windll.user32.SetCursorPos(int(screen_x), int(screen_y))
    time.sleep(0.08)
    for _ in range(max(1, taps)):
        gl._click_win32(screen_x, screen_y)
        time.sleep(0.12)


def _client_to_screen(hwnd: int, client_x: int, client_y: int) -> tuple[int, int]:
    """ClientToScreen under per-monitor DPI v2 (matches SendInput click mapping)."""
    import win32gui

    user32 = ctypes.windll.user32
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_ssize_t(-4)
    old_ctx = None
    try:
        old_ctx = user32.SetThreadDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
    except Exception:
        pass
    try:
        return win32gui.ClientToScreen(hwnd, (client_x, client_y))
    finally:
        if old_ctx is not None:
            user32.SetThreadDpiAwarenessContext(ctypes.c_ssize_t(old_ctx))


def click_client(
    win: WindowInfo,
    client_x: int,
    client_y: int,
    taps: int = 1,
    *,
    require_foreground: bool = False,
    use_postmessage: bool = False,
) -> None:
    """Click inside the game client area."""
    _hide_blocking_overlays(win)
    if use_postmessage:
        _post_client_click(win.hwnd, client_x, client_y, taps=taps)
        log.info(
            "postmessage click client (%d,%d) hwnd=%d taps=%d",
            client_x,
            client_y,
            win.hwnd,
            taps,
        )
        return
    sendinput = False
    for _ in range(12):
        focus_game(win.hwnd)
        if _civ_sendinput_ready(win):
            sendinput = True
            break
        time.sleep(0.25)
    screen_x, screen_y = _client_to_screen(win.hwnd, client_x, client_y)
    if sendinput:
        _send_mouse_click_screen(screen_x, screen_y, taps=taps)
    else:
        if require_foreground:
            raise RuntimeError(
                f"Civ6 not foreground; refused click at client ({client_x},{client_y}) hwnd={win.hwnd}"
            )
        log.warning("Civ6 not foreground (hwnd=%s); posting click to client (%d,%d)", win.hwnd, client_x, client_y)
        _post_client_click(win.hwnd, client_x, client_y, taps=taps)
    log.info(
        "click client (%d,%d) screen (%d,%d) hwnd=%d sendinput=%s",
        client_x,
        client_y,
        screen_x,
        screen_y,
        win.hwnd,
        sendinput,
    )


def press_escape(win: WindowInfo) -> None:
    _press_vk(win, 0x1B, "Escape")


def _press_vk(win: WindowInfo, vk: int, label: str) -> None:
    user32 = ctypes.windll.user32
    focus_game(win.hwnd)
    user32.PostMessageW(win.hwnd, 0x0100, vk, 0)
    time.sleep(0.04)
    user32.PostMessageW(win.hwnd, 0x0101, vk, 0)
    log.info("sent %s to game window", label)


def press_space(win: WindowInfo) -> None:
    """Space advances leader intro and can end turn when no units need orders."""
    _press_vk(win, 0x20, "Space")


def press_enter(win: WindowInfo) -> None:
    """Enter confirms Begin Game and other modal buttons."""
    _press_vk(win, 0x0D, "Enter")


def _post_key(win: WindowInfo, vk: int, keyup: bool = False) -> None:
    user32 = ctypes.windll.user32
    msg = 0x0101 if keyup else 0x0100
    user32.PostMessageW(win.hwnd, msg, vk, 0)


def _post_char(win: WindowInfo, char: str) -> None:
    if not char:
        return
    user32 = ctypes.windll.user32
    for code in char:
        user32.PostMessageW(win.hwnd, 0x0102, ord(code), 0)


def _set_clipboard_text(text: str) -> bool:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception as error:
        log.warning("clipboard set failed: %s", error)
        return False


def paste_text(win: WindowInfo, text: str, *, refocus: bool = True) -> bool:
    if not _set_clipboard_text(text):
        return False
    if refocus:
        focus_game(win.hwnd)
        time.sleep(0.05)
    VK_CONTROL = 0x11
    VK_V = 0x56
    _send_input_keyboard(VK_CONTROL, keyup=False)
    _send_input_keyboard(VK_V, keyup=False)
    time.sleep(0.04)
    _send_input_keyboard(VK_V, keyup=True)
    _send_input_keyboard(VK_CONTROL, keyup=True)
    return True


# Civ6Ai hidden inbox EditBox — Size 1400x24 Offset 0,0 in Civ6Ai_InGame.xml
HOST_INBOX_CLIENT_X = 700
HOST_INBOX_CLIENT_Y = 12


def _focus_inbox_editbox(win: WindowInfo) -> WindowInfo:
    win = refresh_window(win)
    _hide_blocking_overlays(win)
    for _ in range(12):
        focus_game(win.hwnd)
        if _civ_sendinput_ready(win):
            break
        time.sleep(0.15)
    click_client(win, HOST_INBOX_CLIENT_X, HOST_INBOX_CLIENT_Y, taps=2, require_foreground=False)
    time.sleep(0.15)
    return refresh_window(win)


def send_inbox_line(win: WindowInfo, line: str) -> bool:
    win = _focus_inbox_editbox(win)
    if not _civ_sendinput_ready(win):
        log.warning("inbox inject: Civ6 process not foreground hwnd=%s", win.hwnd)
        return False
    if not paste_text(win, line, refocus=False):
        log.warning("inbox inject: paste failed for line len=%d", len(line))
        return False
    time.sleep(0.12)
    press_enter_sendinput(win, refocus=False)
    time.sleep(0.22)
    return True


def inject_inbox_lines(lines: list[str]) -> bool:
    """Paste each wire line into the inbox; InGame Poll reads GetText() per line."""
    if not lines:
        return False
    win = find_civ_window()
    if win is None:
        log.warning("inbox inject: Civ6 window not found")
        return False
    win = _focus_inbox_editbox(win)
    if not _civ_sendinput_ready(win):
        log.warning("inbox inject: Civ6 process not foreground hwnd=%s", win.hwnd)
        return False
    for line in lines:
        win = refresh_window(win)
        if not paste_text(win, line, refocus=False):
            log.warning("inbox inject: paste failed for line len=%d", len(line))
            return False
        time.sleep(0.35)
    log.info("inbox inject: sent %d lines", len(lines))
    return True


def nudge_dialogs(win: WindowInfo | None = None, enter_count: int = 3) -> bool:
    """Dismiss Eureka/Continue modals and nudge end turn via repeated Enter."""
    if win is None:
        win = find_civ_window()
    if win is None:
        return False
    focus_game(win.hwnd)
    time.sleep(0.05)
    taps = max(1, enter_count)
    for _ in range(taps):
        press_enter_sendinput(win)
        time.sleep(0.15)
    log.info("nudge_dialogs: sent %d Enter to hwnd=%s", taps, win.hwnd)
    return True


# Default client fractions (right-rail). Overridden by civ6_menu_positions.json when present.
_DEFAULT_MENU_POSITIONS: dict[str, dict[str, float]] = {
    "main_single_player": {"pct_x": 0.47, "pct_y": 0.43},
    "sp_load_game": {"pct_x": 0.54, "pct_y": 0.52},
    "sp_create_game": {"pct_x": 0.54, "pct_y": 0.55},
    "sp_scenarios": {"pct_x": 0.54, "pct_y": 0.59},
    "start_game": {"pct_x": 0.85, "pct_y": 0.92},
    # Begin Game (leader-ready screen) — below leader text, above screen bottom; not Start Game.
    # Begin Game on leader intro — recorded @ 1600×1024 client (Invoke-Civ6RecordMenuClick).
    "begin_game": {"pct_x": 0.3622, "pct_y": 0.7559},
    "continue_intro": {"pct_x": 0.38, "pct_y": 0.80},
}

# OCR fallbacks: short prefixes tolerate garbled labels (e.g. "Sinale Plaver").
_MENU_OCR_HINTS: dict[str, tuple[tuple[str, ...], str]] = {
    "main_single_player": (("sin", "sing", "sngl", "plav"), "single player"),
    "sp_create_game": (("cre", "creat"), "create game"),
    "sp_load_game": (("load", "loa"), "load game"),
    "sp_scenarios": (("scen", "scena"), "scenarios"),
    "start_game": (("start", "sta"), "start game"),
    "begin_game": (("beg",), "begin game"),
    "continue_intro": (("cont", "contin"), "continue"),
    "back": (("back", "bac"), "back"),
    "play_aspyr": (("play", "pla"), "play"),
}

_MENU_POSITIONS_PATH = Path(__file__).resolve().parent / "civ6_menu_positions.json"
_MENU_SEQUENCE_PATH = Path(__file__).resolve().parent / "civ6_menu_sequence.json"


def load_menu_positions() -> dict:
    if _MENU_POSITIONS_PATH.is_file():
        try:
            return json.loads(_MENU_POSITIONS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            log.warning("Could not read %s: %s", _MENU_POSITIONS_PATH, error)
    return {"ref_w": 1600, "ref_h": 1024, "items": dict(_DEFAULT_MENU_POSITIONS)}


def save_menu_position(
    key: str,
    win: WindowInfo,
    client_x: int,
    client_y: int,
    *,
    force: bool = False,
    recorded: bool = False,
) -> None:
    if key in _LOCKED_MENU_POSITION_KEYS and not force:
        log.info("save_menu_position skipped locked key %s", key)
        return
    data = load_menu_positions()
    data["ref_w"] = win.w
    data["ref_h"] = win.h
    items = data.setdefault("items", {})
    entry: dict[str, float | bool] = {
        "client_x": client_x,
        "client_y": client_y,
        "pct_x": round(client_x / max(win.w, 1), 4),
        "pct_y": round(client_y / max(win.h, 1), 4),
    }
    if recorded:
        entry["recorded"] = True
    items[key] = entry
    _MENU_POSITIONS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    log.info("saved menu position %s -> client (%d,%d)", key, client_x, client_y)


_RIGHT_RAIL_MENU_KEYS = frozenset({
    "main_single_player",
    "sp_load_game",
    "sp_create_game",
    "sp_scenarios",
})

# Never auto-save these from OCR retries — use Invoke-Civ6RecordMenuClick.ps1 to recalibrate.
_LOCKED_MENU_POSITION_KEYS = frozenset({"begin_game"})

_SUBMENU_RAIL_MENU_KEYS = frozenset({
    "sp_load_game",
    "sp_create_game",
    "sp_scenarios",
})

# OCR text sits left of the blue tab on the main menu rail; submenu labels are centered on tabs.
_TAB_CLICK_X_OFFSET = 96

_MENU_CALIBRATE_REGION: dict[str, dict[str, float]] = {
    "main_single_player": {"min_y_fraction": 0.38, "max_y_fraction": 0.52, "min_x_fraction": 0.42},
    "sp_load_game": {"min_y_fraction": 0.48, "max_y_fraction": 0.56, "min_x_fraction": 0.50},
    "sp_create_game": {"min_y_fraction": 0.52, "max_y_fraction": 0.60, "min_x_fraction": 0.50},
    "sp_scenarios": {"min_y_fraction": 0.56, "max_y_fraction": 0.66, "min_x_fraction": 0.50},
}


def _sanitize_position_entry(key: str, entry: dict[str, float]) -> dict[str, float]:
    if key == "main_single_player" and entry.get("pct_x", 0) < 0.4:
        log.warning(
            "ignoring saved %s pct_x=%.3f (left of main menu rail); using default",
            key,
            entry.get("pct_x", 0),
        )
        return dict(_DEFAULT_MENU_POSITIONS[key])
    if key in _SUBMENU_RAIL_MENU_KEYS and entry.get("pct_x", 0) < 0.5:
        log.warning(
            "ignoring saved %s pct_x=%.3f (not on SP submenu rail); using default",
            key,
            entry.get("pct_x", 0),
        )
        return dict(_DEFAULT_MENU_POSITIONS[key])
    if key == "begin_game":
        pct_x = entry.get("pct_x", 0)
        pct_y = entry.get("pct_y", 0)
        if pct_y < 0.65 or pct_y > 0.96 or pct_x < 0.22 or pct_x > 0.52:
            log.warning(
                "ignoring saved begin_game pct (%.3f, %.3f); using hardcoded default",
                pct_x,
                pct_y,
            )
            return dict(_DEFAULT_MENU_POSITIONS["begin_game"])
    return entry


def _position_entry(key: str) -> dict[str, float] | None:
    if key in _LOCKED_MENU_POSITION_KEYS:
        return dict(_DEFAULT_MENU_POSITIONS[key])
    items = load_menu_positions().get("items", {})
    entry = items.get(key) or _DEFAULT_MENU_POSITIONS.get(key)
    if entry is None:
        return None
    return _sanitize_position_entry(key, dict(entry))


def _has_saved_menu_position(key: str) -> bool:
    return key in load_menu_positions().get("items", {})


def _click_menu_ocr(win: WindowInfo, key: str, post_delay: float) -> bool:
    hints = _MENU_OCR_HINTS.get(key)
    if hints is None:
        return False
    prefixes, target = hints
    region = _MENU_CALIBRATE_REGION.get(key, {})
    return click_text(
        win,
        target,
        timeout=8,
        exact=False,
        post_delay=post_delay,
        prefixes=prefixes,
        save_position_key=key,
        min_y_fraction=region.get("min_y_fraction", 0.0),
        max_y_fraction=region.get("max_y_fraction", 0.0),
        min_x_fraction=region.get("min_x_fraction", 0.0),
        x_offset=_TAB_CLICK_X_OFFSET if key == "main_single_player" else 0,
    )


def _menu_client_coords(win: WindowInfo, key: str, entry: dict[str, float]) -> tuple[int, int]:
    cx = int(win.w * entry["pct_x"])
    cy = int(win.h * entry["pct_y"])
    # OCR saves text-left-of-tab; manual recording stores the real button center.
    if key == "main_single_player" and not entry.get("recorded"):
        cx = min(cx + _TAB_CLICK_X_OFFSET, win.w - 4)
    return cx, cy


def click_menu(win: WindowInfo, key: str, post_delay: float = 0.8) -> bool:
    """Click a menu item at saved client fractions (deterministic — no OCR)."""
    win = refresh_window(win)
    entry = _position_entry(key)
    if entry is None:
        log.warning("click_menu %s: no calibrated position", key)
        return False
    cx, cy = _menu_client_coords(win, key, entry)
    click_client(win, cx, cy, taps=2)
    time.sleep(post_delay)
    log.info("click_menu %s at client (%d,%d)", key, cx, cy)
    return True


def calibrate_menu_position(win: WindowInfo, key: str) -> bool:
    """OCR a menu label (with prefix hints) and write client coords to JSON."""
    hints = _MENU_OCR_HINTS.get(key)
    if hints is None:
        return False
    prefixes, target = hints
    region = _MENU_CALIBRATE_REGION.get(key, {})
    results = ocr_window(win)
    match = find_text(
        results,
        target,
        exact=False,
        prefixes=prefixes,
        win=win,
        min_y_fraction=region.get("min_y_fraction", 0.0),
        max_y_fraction=region.get("max_y_fraction", 0.0),
        min_x_fraction=region.get("min_x_fraction", 0.0),
    )
    if match is None:
        return False
    _, x, y = match
    win = refresh_window(win)
    client_x = x - win.x
    if key in _RIGHT_RAIL_MENU_KEYS and key == "main_single_player":
        client_x += _TAB_CLICK_X_OFFSET
    save_menu_position(key, win, client_x, y - win.y)
    return True


# Legacy aliases (used by a few fallbacks)
_MENU_MAIN_SINGLE_PLAYER = (
    _DEFAULT_MENU_POSITIONS["main_single_player"]["pct_x"],
    _DEFAULT_MENU_POSITIONS["main_single_player"]["pct_y"],
)
_MENU_SP_CREATE_GAME = (
    _DEFAULT_MENU_POSITIONS["sp_create_game"]["pct_x"],
    _DEFAULT_MENU_POSITIONS["sp_create_game"]["pct_y"],
)
_MENU_SP_LOAD_GAME = (
    _DEFAULT_MENU_POSITIONS["sp_load_game"]["pct_x"],
    _DEFAULT_MENU_POSITIONS["sp_load_game"]["pct_y"],
)
_MENU_START_GAME = (
    _DEFAULT_MENU_POSITIONS["start_game"]["pct_x"],
    _DEFAULT_MENU_POSITIONS["start_game"]["pct_y"],
)
_MENU_CONTINUE = (
    _DEFAULT_MENU_POSITIONS["continue_intro"]["pct_x"],
    _DEFAULT_MENU_POSITIONS["continue_intro"]["pct_y"],
)


def _click_at(win: WindowInfo, screen_x: int, screen_y: int, postmessage: bool = False) -> None:
    win = refresh_window(win)
    client_x = screen_x - win.x
    client_y = screen_y - win.y
    if 0 <= client_x < win.w and 0 <= client_y < win.h:
        click_client(win, client_x, client_y)
    else:
        focus_game(win.hwnd)
        _send_mouse_click_screen(screen_x, screen_y)


_JUNK_OCR_SUBSTRINGS = (
    "output:",
    "apply fail",
    "invoke-",
    ".ps1",
    "cursor",
    "human-",
    "kind + reason",
    "bootstrap",
    "autotest",
)


def _ocr_line_plausible(text: str, exact: bool) -> bool:
    if len(text) > 36 and not exact:
        return False
    lower = text.lower()
    return not any(junk in lower for junk in _JUNK_OCR_SUBSTRINGS)


def capture_window(win: WindowInfo):
    from PIL import Image
    import win32gui
    import win32ui

    win = refresh_window(win)
    hwnd = win.hwnd
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w = right - left
    h = bottom - top
    if w <= 0 or h <= 0:
        raise RuntimeError(f"Invalid Civ6 client rect {w}x{h}")

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bitmap)
    ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
    bmpinfo = bitmap.GetInfo()
    bmpstr = bitmap.GetBitmapBits(True)
    image = Image.frombuffer(
        "RGB",
        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
        bmpstr,
        "raw",
        "BGRX",
        0,
        1,
    )
    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return image


def ocr_image(image, origin_x: int, origin_y: int) -> list[tuple[str, int, int]]:
    try:
        return _ocr_winrt(image, origin_x, origin_y)
    except Exception as error:
        log.warning("WinRT OCR failed (%s), trying Tesseract", error)
        try:
            return _ocr_tesseract(image, origin_x, origin_y)
        except Exception as tess_error:
            log.warning("Tesseract OCR failed (%s)", tess_error)
            return []


def _ocr_winrt(image, origin_x: int, origin_y: int) -> list[tuple[str, int, int]]:
    import asyncio
    import io

    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    img_w, img_h = image.size

    async def _run():
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(png_bytes)
        await writer.store_async()
        await writer.flush_async()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return None
        return await engine.recognize_async(bitmap)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            ocr_result = pool.submit(lambda: asyncio.run(_run())).result(timeout=15)
    else:
        ocr_result = asyncio.run(_run())

    if ocr_result is None:
        return []

    out: list[tuple[str, int, int]] = []
    for line in ocr_result.lines:
        words = list(line.words)
        if not words:
            continue
        x0 = min(w.bounding_rect.x for w in words)
        y0 = min(w.bounding_rect.y for w in words)
        x1 = max(w.bounding_rect.x + w.bounding_rect.width for w in words)
        y1 = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
        cx = origin_x + int((x0 + x1) / 2 / img_w * img_w)
        cy = origin_y + int((y0 + y1) / 2 / img_h * img_h)
        out.append((line.text.strip(), cx, cy))
    return out


def _ocr_tesseract(image, origin_x: int, origin_y: int) -> list[tuple[str, int, int]]:
    import pytesseract

    img_w, img_h = image.size
    data = pytesseract.image_to_data(image, config="--psm 11", output_type=pytesseract.Output.DICT)
    out: list[tuple[str, int, int]] = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text or int(data["conf"][i]) < 50:
            continue
        cx = origin_x + int(data["left"][i] + data["width"][i] / 2)
        cy = origin_y + int(data["top"][i] + data["height"][i] / 2)
        out.append((text, cx, cy))
    return out


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _text_matches_target(
    got: str,
    want: str,
    exact: bool,
    prefixes: tuple[str, ...] = (),
    phrase_min_len: int = 0,
) -> bool:
    if exact and got == want:
        return True
    if phrase_min_len > 0 and len(want) >= phrase_min_len and want in got:
        return True
    if not exact and phrase_min_len <= 0 and want in got:
        return True
    for prefix in prefixes:
        p = prefix.lower()
        if got.startswith(p) or p in got:
            return True
    return False


def find_text(
    results: list[tuple[str, int, int]],
    target: str,
    exact: bool = False,
    prefer_bottom: bool = False,
    prefer_top: bool = False,
    min_y_fraction: float = 0.0,
    max_y_fraction: float = 0.0,
    min_x_fraction: float = 0.0,
    win: WindowInfo | None = None,
    prefixes: tuple[str, ...] = (),
    phrase_min_len: int = 0,
) -> tuple[str, int, int] | None:
    want = _normalize(target)
    min_y = 0
    max_y = 10_000_000
    min_x = 0
    if win is not None:
        if min_y_fraction > 0:
            min_y = int(win.y + win.h * min_y_fraction)
        if max_y_fraction > 0:
            max_y = int(win.y + win.h * max_y_fraction)
        if min_x_fraction > 0:
            min_x = int(win.x + win.w * min_x_fraction)
    matches: list[tuple[str, int, int]] = []
    for text, x, y in results:
        if y < min_y or y > max_y or x < min_x:
            continue
        if not _ocr_line_plausible(text, exact):
            continue
        got = _normalize(text)
        if _text_matches_target(got, want, exact, prefixes, phrase_min_len):
            matches.append((text, x, y))
    if not matches:
        return None
    if prefer_bottom:
        return max(matches, key=lambda item: item[2])
    if prefer_top:
        return min(matches, key=lambda item: item[2])
    return matches[0]


def ocr_window(win: WindowInfo) -> list[tuple[str, int, int]]:
    win = refresh_window(win)
    image = capture_window(win)
    return ocr_image(image, win.x, win.y)


def wait_for_text(
    win: WindowInfo,
    target: str,
    timeout: float = 30.0,
    exact: bool = False,
    interval: float = 1.0,
    prefer_bottom: bool = False,
    prefer_top: bool = False,
    min_y_fraction: float = 0.0,
) -> tuple[str, int, int] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        results = ocr_window(win)
        match = find_text(
            results,
            target,
            exact=exact,
            prefer_bottom=prefer_bottom,
            min_y_fraction=min_y_fraction,
            win=win,
        )
        if match:
            return match
        time.sleep(interval)
    return None


def click_text(
    win: WindowInfo,
    target: str,
    timeout: float = 12.0,
    exact: bool = False,
    post_delay: float = 0.35,
    prefer_bottom: bool = False,
    prefer_top: bool = False,
    min_y_fraction: float = 0.0,
    max_y_fraction: float = 0.0,
    min_x_fraction: float = 0.0,
    y_offset: int = 0,
    x_offset: int = 0,
    prefixes: tuple[str, ...] = (),
    save_position_key: str | None = None,
    phrase_min_len: int = 0,
) -> bool:
    if sys.platform != "win32":
        return False
    _hide_blocking_overlays(win)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        results = ocr_window(win)
        match = find_text(
            results,
            target,
            exact=exact,
            prefer_bottom=prefer_bottom,
            prefer_top=prefer_top,
            min_y_fraction=min_y_fraction,
            max_y_fraction=max_y_fraction,
            min_x_fraction=min_x_fraction,
            win=win,
            prefixes=prefixes,
            phrase_min_len=phrase_min_len,
        )
        if match:
            text, x, y = match
            win_ref = refresh_window(win)
            click_x = x + x_offset
            click_y = y + y_offset
            click_client(win_ref, click_x - win_ref.x, click_y - win_ref.y)
            if save_position_key:
                win_ref = refresh_window(win)
                save_client_x = click_x - win_ref.x
                if save_position_key in _RIGHT_RAIL_MENU_KEYS and save_position_key == "main_single_player":
                    save_client_x -= _TAB_CLICK_X_OFFSET
                save_menu_position(
                    save_position_key,
                    win_ref,
                    save_client_x,
                    click_y - win_ref.y,
                )
            log.info("click '%s' screen (%d,%d) prefixes=%s", text, click_x, click_y, prefixes)
            time.sleep(post_delay)
            return True
        time.sleep(0.35)
    return False


def click_relative(
    win: WindowInfo,
    pct_x: float,
    pct_y: float,
    post_delay: float = 0.35,
) -> None:
    client_x = int(win.w * pct_x)
    client_y = int(win.h * pct_y)
    log.info("click relative (%.2f,%.2f) -> client (%d,%d)", pct_x, pct_y, client_x, client_y)
    click_client(win, client_x, client_y)
    time.sleep(post_delay)


def _is_begin_game_ocr_label(norm: str) -> bool:
    if norm == "game":
        return True
    if re.fullmatch(r"begin(\s+game)?", norm):
        return True
    if len(norm) <= 14 and norm.startswith("beg") and " the " not in norm and " in " not in norm:
        return True
    return False


def _ocr_text_blob(win: WindowInfo) -> str:
    return " ".join(_normalize(text) for text, _, _ in ocr_window(win))


def _is_game_options_blob(blob: str) -> bool:
    settings_markers = (
        "quick combat",
        "quick movement",
        "auto end turn",
        "restore defaults",
        "turns between autosaves",
        "number of autosaves to keep",
        "city ranged attack turn blocking",
    )
    hits = sum(1 for marker in settings_markers if marker in blob)
    if hits >= 2:
        return True
    # Main menu lists "Game Options" as a nav item — only treat as settings when detail text is present.
    if "game options" in blob and hits >= 1:
        return True
    return False


def _exit_game_options(win: WindowInfo) -> bool:
    if detect_menu(win) != "game_options":
        return True
    log.info("on Game Options screen — going back")
    if click_text(win, "BACK", timeout=3, exact=True, post_delay=0.4, prefixes=("back", "bac")):
        return detect_menu(win) != "game_options"
    press_escape(win)
    time.sleep(0.4)
    return detect_menu(win) != "game_options"


def detect_menu(win: WindowInfo) -> str:
    blob = _ocr_text_blob(win)
    if _is_game_options_blob(blob):
        return "game_options"
    if "map type" in blob or "map size" in blob or "game speed" in blob or "choose map" in blob:
        return "advanced_setup"
    if "autosaves" in blob or "sort by last modified" in blob or "no saved games" in blob:
        return "load_game_screen"
    # SP submenu shows Create Game + Load Game together (main menu only has Single Player).
    if "load game" in blob and "create game" in blob:
        return "single_player"
    if "create game" in blob and "choose map" not in blob and "map type" not in blob:
        if "single player" not in blob or "load game" in blob:
            return "single_player"
    if "scenarios" in blob or "advanced setup" in blob or re.search(r"\badv", blob):
        return "single_player"
    if ("local network" in blob or "hot seat" in blob or "play by cloud" in blob) and "additional content" not in blob:
        return "multiplayer_sub"
    if "single player" in blob and "multiplayer" in blob and "create game" not in blob:
        return "main"
    if "multiplayer" in blob and re.search(r"\bsin", blob) and "create game" not in blob:
        return "main"
    if "next turn" in blob or "continue game" in blob or "end turn" in blob:
        return "ingame"
    if re.search(r"\bturn\s*\d+\s*/\s*\d+", blob):
        return "ingame"
    if "choose research" in blob and re.search(r"\bturn\s*\d", blob):
        return "ingame"
    if (
        re.search(r"\bbegin\s+game\b", blob)
        and "create game" not in blob
        and "start game" not in blob
        and "choose map" not in blob
        and "map type" not in blob
    ):
        return "begin_game"
    if "joins the world stage" in blob or "joins the world" in blob:
        if re.search(r"\bbegin\s+game\b", blob):
            return "begin_game"
        return "leader_intro"
    if re.search(r"\bjoins\b", blob) and re.search(r"\bworld\b", blob):
        return "leader_intro"
    if re.search(r"\bturn\s*\d", blob) or (
        "turn" in blob and any(k in blob for k in ("gold", "science", "culture", "faith", "tourism"))
    ):
        return "ingame"
    return "unknown"


def _wait_for_menu(win: WindowInfo, want: str, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if detect_menu(win) == want:
            return True
        time.sleep(0.25)
    return False


def open_single_player_menu(win: WindowInfo) -> bool:
    if detect_menu(win) == "single_player":
        return True
    if detect_menu(win) == "game_options":
        _exit_game_options(win)
    if detect_menu(win) == "load_game_screen":
        return _back_from_load_game(win)
    if detect_menu(win) == "multiplayer_sub":
        press_escape(win)
        time.sleep(0.4)
    if detect_menu(win) not in ("main", "unknown"):
        return False

    _hide_blocking_overlays(win)
    for attempt in range(3):
        if detect_menu(win) == "single_player":
            return True
        focus_game(win.hwnd)
        click_menu(win, "main_single_player", post_delay=1.2)
        if _wait_for_menu(win, "single_player", timeout=3.0):
            return True
        if detect_menu(win) == "main":
            log.info("SP submenu miss (attempt %d) — retry calibrated click", attempt + 1)
        time.sleep(0.5)

    state = detect_menu(win)
    if state == "load_game_screen":
        _back_from_load_game(win)
        state = detect_menu(win)
    if state == "multiplayer_sub":
        press_escape(win)
        time.sleep(0.4)
        state = detect_menu(win)
    if state != "single_player":
        region = _MENU_CALIBRATE_REGION.get("main_single_player", {})
        if click_text(
            win,
            "Single Player",
            timeout=6,
            exact=False,
            post_delay=1.2,
            prefixes=("sin", "sing", "sngl", "plav"),
            save_position_key="main_single_player",
            min_y_fraction=region.get("min_y_fraction", 0.0),
            max_y_fraction=region.get("max_y_fraction", 0.0),
            min_x_fraction=region.get("min_x_fraction", 0.0),
            x_offset=_TAB_CLICK_X_OFFSET,
        ):
            if _wait_for_menu(win, "single_player", timeout=3.0):
                return True
        state = detect_menu(win)
    return state == "single_player"


def _back_from_load_game(win: WindowInfo) -> bool:
    if detect_menu(win) != "load_game_screen":
        return True
    log.info("on Load Game screen — going back")
    if click_text(win, "BACK", timeout=3, exact=True, post_delay=0.4, prefixes=("back", "bac")):
        return detect_menu(win) == "single_player"
    press_escape(win)
    time.sleep(0.4)
    return detect_menu(win) == "single_player"


def _leader_intro_visible(win: WindowInfo) -> bool:
    blob = _ocr_text_blob(win)
    return "joins the world stage" in blob or "joins the world" in blob


def _confirmed_ingame(win: WindowInfo) -> bool:
    """In-game per OCR, excluding leader-intro / Begin Game screens."""
    if _on_leader_intro_screen(win) or _screen_has_begin_game(win):
        return False
    return detect_menu(win) == "ingame"


def _on_leader_intro_screen(win: WindowInfo) -> bool:
    menu = detect_menu(win)
    if menu == "ingame":
        return False
    if menu in ("leader_intro", "begin_game"):
        return True
    return _leader_intro_visible(win) or _screen_has_begin_game(win)


def _must_click_begin_game(win: WindowInfo) -> bool:
    return (
        _on_leader_intro_screen(win)
        or _screen_has_begin_game(win)
        or detect_menu(win) in ("leader_intro", "begin_game")
    )


def open_advanced_setup(win: WindowInfo) -> bool:
    """Open Create Game setup (map/players screen). No separate Advanced Setup item in current Civ6 UI."""
    menu = detect_menu(win)
    if menu in ("advanced_setup", "leader_intro", "begin_game"):
        return True
    if menu == "game_options":
        _exit_game_options(win)
    if detect_menu(win) == "load_game_screen":
        _back_from_load_game(win)
    if detect_menu(win) != "single_player":
        if not open_single_player_menu(win):
            return False

    focus_game(win.hwnd)
    click_menu(win, "sp_create_game", post_delay=1.0)
    time.sleep(2.0)
    if _wait_for_menu(win, "advanced_setup", timeout=6.0):
        return True
    if _wait_for_menu(win, "leader_intro", timeout=12.0):
        log.info("past setup after sp_create_game (menu=leader_intro)")
        return True
    if _leader_intro_visible(win):
        log.info("past setup after sp_create_game (leader intro OCR)")
        return True
    if _wait_for_menu(win, "leader_intro", timeout=8.0) or _wait_for_menu(win, "begin_game", timeout=4.0):
        return True
    menu = detect_menu(win)
    if menu in ("leader_intro", "begin_game"):
        return True
    if menu == "main":
        open_single_player_menu(win)
    elif menu != "single_player":
        open_single_player_menu(win)
    click_menu(win, "sp_create_game", post_delay=1.0)
    if _wait_for_menu(win, "advanced_setup", timeout=6.0):
        return True
    menu = detect_menu(win)
    if menu in ("leader_intro", "begin_game"):
        return True
    if menu == "load_game_screen":
        _back_from_load_game(win)
        click_menu(win, "sp_create_game", post_delay=1.0)
        if _wait_for_menu(win, "advanced_setup", timeout=6.0):
            return True
        menu = detect_menu(win)
        if menu in ("leader_intro", "ingame"):
            return True
    region = _MENU_CALIBRATE_REGION.get("sp_create_game", {})
    if click_text(
        win,
        "Create Game",
        timeout=5,
        exact=False,
        post_delay=1.0,
        prefixes=("cre", "creat"),
        save_position_key="sp_create_game",
        min_y_fraction=region.get("min_y_fraction", 0.0),
        max_y_fraction=region.get("max_y_fraction", 0.0),
        min_x_fraction=region.get("min_x_fraction", 0.0),
    ):
        if _wait_for_menu(win, "advanced_setup", timeout=6.0):
            return True
    return _wait_for_menu(win, "advanced_setup", timeout=6.0)


# Create Game setup rows (right panel). Click row label to open list, then pick option.
_SETUP_DROPDOWNS: dict[str, dict[str, object]] = {
    "game_speed": {"row": "choose game speed", "y": (0.38, 0.46)},
    "map_type": {"row": "choose map type", "y": (0.46, 0.53)},
    "map_size": {"row": "choose map size", "y": (0.53, 0.61)},
    "num_players": {"row": "choose number of players", "y": (0.61, 0.69)},
}

_SETUP_PANEL_X_MIN = 0.42


def _click_setup_row(win: WindowInfo, row_key: str) -> bool:
    row_cfg = _SETUP_DROPDOWNS[row_key]
    y_band = row_cfg["y"]
    return click_text(
        win,
        str(row_cfg["row"]),
        timeout=4,
        post_delay=0.45,
        min_y_fraction=float(y_band[0]),
        max_y_fraction=float(y_band[1]),
        min_x_fraction=_SETUP_PANEL_X_MIN,
        phrase_min_len=10,
    )


def _pick_setup_option(win: WindowInfo, option: str) -> bool:
    """Pick an item from an open setup dropdown (exact label match)."""
    want = _normalize(option)
    if click_text(
        win,
        option,
        timeout=4,
        exact=True,
        post_delay=0.35,
        min_y_fraction=0.18,
        max_y_fraction=0.92,
        min_x_fraction=0.30,
    ):
        return True
    # Fallback: OCR sometimes splits labels across tokens — match whole-word only.
    results = ocr_window(win)
    for text, x, y in results:
        if _normalize(text) == want:
            click_client(win, x - win.x, y - win.y)
            time.sleep(0.35)
            log.info("setup option exact token '%s' at (%d,%d)", text, x, y)
            return True
    return False


def _select_setup_dropdown(win: WindowInfo, row_key: str, option: str) -> bool:
    if not _click_setup_row(win, row_key):
        log.warning("setup row not found: %s", row_key)
        return False
    time.sleep(0.35)
    if _pick_setup_option(win, option):
        return True
    log.warning("setup option not found: %s for %s", option, row_key)
    return False


def dismiss_aspyr_launcher(win: WindowInfo, timeout: float = 15.0) -> bool:
    if detect_menu(win) in ("main", "single_player", "advanced_setup", "ingame"):
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if detect_menu(win) in ("main", "single_player", "advanced_setup", "ingame"):
            return True
        gl = _game_launcher()
        if gl._click_text("PLAY", timeout=2, exact=True, post_delay=0.5):
            return True
        time.sleep(0.4)
    return False


def dismiss_main_menu_overlays(win: WindowInfo, timeout: float = 4.0) -> list[str]:
    """Hide overlays; do not click promo panels (they open a browser)."""
    return _hide_blocking_overlays(win)


def dismiss_startup_prompts(win: WindowInfo, timeout: float = 45.0) -> list[str]:
    """Dismiss TOS, legal, Aspyr launcher until main menu."""
    dismissed: list[str] = []
    dismissed.extend(_hide_blocking_overlays(win))
    prompts = ("Accept", "I Agree", "Agree", "OK", "Apply", "PLAY", "Play", "Low")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        dismiss_aspyr_launcher(win, timeout=2)
        menu = detect_menu(win)
        if menu == "main":
            _hide_blocking_overlays(win)
            return dismissed
        results = ocr_window(win)
        clicked = False
        for prompt in prompts:
            match = find_text(results, prompt, exact=True)
            if match and len(match[0]) <= 24:
                if click_text(win, prompt, timeout=1, exact=True, post_delay=0.35):
                    dismissed.append(prompt)
                    clicked = True
                    break
        if not clicked:
            time.sleep(0.4)
    return dismissed


def wait_for_main_menu(win: WindowInfo, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if detect_menu(win) == "main":
            return True
        time.sleep(0.35)
    return False


def navigate_load_save(win: WindowInfo, save_name: str) -> list[str]:
    """Main menu -> Single Player -> Load Game -> select save -> Load."""
    steps: list[str] = []
    if not open_single_player_menu(win):
        raise RuntimeError("Could not open Single Player menu")
    steps.append("single_player")
    if not click_text(win, "Load Game", timeout=6, exact=True, post_delay=0.35, y_offset=12):
        raise RuntimeError("Could not find Load Game")
    steps.append("load_game_menu")
    if not click_text(win, save_name, timeout=10, post_delay=0.35):
        raise RuntimeError(f"Save '{save_name}' not found")
    steps.append(f"selected_{save_name}")
    if click_text(
        win,
        "Load Game",
        timeout=6,
        post_delay=0.5,
        prefer_bottom=True,
        min_y_fraction=0.65,
    ):
        steps.append("load_game_button")
    else:
        steps.append("load_game_button_skipped")
    return steps


# Leader intro: Space-first — never sweep positional clicks on the map.
def _click_continue_button(win: WindowInfo) -> bool:
    if click_menu(win, "continue_intro", post_delay=0.8):
        return True
    return click_text(
        win,
        "CONTINUE",
        timeout=3,
        post_delay=0.8,
        prefer_bottom=True,
        min_y_fraction=0.65,
        prefixes=("cont", "contin"),
        phrase_min_len=6,
    ) or click_text(
        win,
        "Continue",
        timeout=2,
        post_delay=0.8,
        prefer_bottom=True,
        min_y_fraction=0.65,
        prefixes=("cont", "contin"),
        phrase_min_len=6,
    )


def _client_coords_for_key(win: WindowInfo, key: str) -> tuple[int, int] | None:
    entry = _position_entry(key)
    if entry is None:
        return None
    return int(win.w * entry["pct_x"]), int(win.h * entry["pct_y"])


def _screen_has_begin_game(win: WindowInfo) -> bool:
    blob = _ocr_text_blob(win)
    if "create game" in blob or "start game" in blob or "choose map" in blob or "map type" in blob:
        return False
    if "shift" in blob and "tab" in blob:
        return False
    if re.search(r"\bbegin\s+game\b", blob):
        return True
    win = refresh_window(win)
    for text, x, y in ocr_window(win):
        norm = _normalize(text)
        if not _is_begin_game_ocr_label(norm):
            continue
        cx = x - win.x
        cy = y - win.y
        if norm == "game" and 0.32 < cx / max(win.w, 1) < 0.68 and 0.32 < cy / max(win.h, 1) < 0.62:
            return True
        if norm.startswith("beg") and cy > win.h * 0.68:
            return True
    return False


def _left_begin_game_screen(win: WindowInfo) -> bool:
    return detect_menu(win) == "ingame" or (
        not _screen_has_begin_game(win) and detect_menu(win) not in ("begin_game", "leader_intro")
    )


def _begin_game_ocr_targets(win: WindowInfo) -> list[tuple[int, int, str]]:
    """Return client click candidates from OCR (label + offsets above for the panel)."""
    win = refresh_window(win)
    targets: list[tuple[int, int, str]] = []
    for text, x, y in ocr_window(win):
        norm = _normalize(text)
        cx = x - win.x
        cy = y - win.y
        if cy < win.h * 0.15:
            continue
        if _is_begin_game_ocr_label(norm):
            if norm.startswith("beg") and cy < win.h * 0.68:
                continue
            for y_off in (-96, -72, -48, -24, 0, 24):
                targets.append((cx, cy + y_off, text))
        elif norm == "game" and 0.22 < cx / max(win.w, 1) < 0.78 and cy > win.h * 0.55:
            for y_off in (-96, -72, -48, -24):
                targets.append((cx, cy + y_off, f"{text}+{y_off}"))
    return targets


_BEGIN_GAME_REF_CLIENT = (579, 774)
_BEGIN_GAME_PAINT_CLIENT = (585, 822)
# Some leader intros place Begin Game lower (e.g. Russia/Peter @ ~94% client height).
_BEGIN_GAME_LOW_CLIENT = (579, 970)
_BEGIN_GAME_RETRY_SECONDS = 5.0
_LEADER_INTRO_SETTLE_SECONDS = 3.0

# Autotest bootstrap: fixed delays between hardcoded clicks (no OCR menu gates).
_BOOTSTRAP_DISMISS_WAIT_S = 12.0
_BOOTSTRAP_BEFORE_MENU_CLICKS_S = 2.0
_BOOTSTRAP_AFTER_SINGLE_PLAYER_S = 2.0
_BOOTSTRAP_AFTER_CREATE_GAME_S = 8.0
_BOOTSTRAP_AFTER_START_GAME_S = 15.0
_BOOTSTRAP_BEGIN_GAME_INTRO_WAIT_S = 3.0
_BOOTSTRAP_BEGIN_GAME_ROUNDS = 8
_BOOTSTRAP_BEGIN_GAME_INTERVAL_S = 5.0
_BOOTSTRAP_INGAME_POLL_S = 2.0
_BOOTSTRAP_NUDGE_INTERVAL_S = 15.0


def _begin_game_bootstrap_coords(win: WindowInfo) -> list[tuple[int, int]]:
    """Begin Game targets for timed bootstrap — exclude low fallback (hits Tutorial on main menu)."""
    ref_w, ref_h = 1600, 1024
    coords: list[tuple[int, int]] = []
    for ref_x, ref_y in (_BEGIN_GAME_REF_CLIENT, _BEGIN_GAME_PAINT_CLIENT):
        cx = int(ref_x * win.w / ref_w)
        cy = int(ref_y * win.h / ref_h)
        if cx < 0 or cy < 0 or cx >= win.w or cy >= win.h:
            continue
        if (cx, cy) not in coords:
            coords.append((cx, cy))
    entry = _DEFAULT_MENU_POSITIONS["begin_game"]
    pct_cx = int(win.w * entry["pct_x"])
    pct_cy = int(win.h * entry["pct_y"])
    if (pct_cx, pct_cy) not in coords:
        coords.insert(0, (pct_cx, pct_cy))
    return coords


def _begin_game_client_coords(win: WindowInfo) -> list[tuple[int, int]]:
    """Hardcoded Begin Game targets scaled to current client size."""
    ref_w, ref_h = 1600, 1024
    coords: list[tuple[int, int]] = []
    for ref_x, ref_y in (_BEGIN_GAME_REF_CLIENT, _BEGIN_GAME_PAINT_CLIENT, _BEGIN_GAME_LOW_CLIENT):
        cx = int(ref_x * win.w / ref_w)
        cy = int(ref_y * win.h / ref_h)
        if cx < 0 or cy < 0 or cx >= win.w or cy >= win.h:
            continue
        if (cx, cy) not in coords:
            coords.append((cx, cy))
    entry = _DEFAULT_MENU_POSITIONS["begin_game"]
    pct_cx = int(win.w * entry["pct_x"])
    pct_cy = int(win.h * entry["pct_y"])
    if (pct_cx, pct_cy) not in coords:
        coords.insert(0, (pct_cx, pct_cy))
    return coords


def _begin_game_click_candidates() -> list[tuple[float, float]]:
    """Begin Game on leader-ready screen — hardcoded default fractions."""
    entry = _DEFAULT_MENU_POSITIONS["begin_game"]
    return [(entry["pct_x"], entry["pct_y"])]


def _begin_game_click_succeeded(win: WindowInfo, before_menu: str) -> bool:
    """Only ingame counts — 'unknown' during loading is not success."""
    return detect_menu(win) == "ingame"


def _wait_for_begin_game_button(win: WindowInfo, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        win = refresh_window(win)
        if detect_menu(win) == "ingame":
            return False
        if _screen_has_begin_game(win) or detect_menu(win) == "begin_game":
            return True
        if _on_leader_intro_screen(win):
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    return _screen_has_begin_game(win) or detect_menu(win) == "begin_game"


def _click_begin_game_once(win: WindowInfo) -> tuple[int, int]:
    win = refresh_window(win)
    for _ in range(6):
        if focus_game(win.hwnd):
            break
        time.sleep(0.25)
    last_cx, last_cy = _begin_game_client_coords(win)[0]
    for cx, cy in _begin_game_client_coords(win):
        last_cx, last_cy = cx, cy
        log.info("begin_game click client (%d,%d) size=%dx%d", cx, cy, win.w, win.h)
        click_client(win, cx, cy, taps=2)
        time.sleep(0.4)
        press_enter_sendinput(win)
        time.sleep(0.8)
        if detect_menu(win) == "ingame":
            return cx, cy
    return last_cx, last_cy


def _advance_leader_intro_to_ingame(win: WindowInfo, timeout: float = 120.0) -> bool:
    """Click Begin Game on leader intro until the match actually starts."""
    if _confirmed_ingame(win):
        return True
    log.info("advance_leader_intro: waiting for Begin Game button")
    if not _wait_for_begin_game_button(win, timeout=min(45.0, timeout)):
        log.warning("advance_leader_intro: Begin Game button not detected via OCR")
    return _retry_begin_game_until_ready(win, timeout=timeout)


def _retry_begin_game_until_ready(win: WindowInfo, timeout: float) -> bool:
    """Wait for leader-intro load, then click Begin Game every 5s until ingame."""
    log.info(
        "leader intro: waiting %.0fs for load, then Begin Game every %.0fs",
        _LEADER_INTRO_SETTLE_SECONDS,
        _BEGIN_GAME_RETRY_SECONDS,
    )
    time.sleep(_LEADER_INTRO_SETTLE_SECONDS)
    deadline = time.monotonic() + max(0.0, timeout - _LEADER_INTRO_SETTLE_SECONDS)
    while time.monotonic() < deadline:
        win = refresh_window(win)
        menu = detect_menu(win)
        if _confirmed_ingame(win):
            return True
        if menu in ("main", "single_player", "load_game_screen") and not _must_click_begin_game(win):
            return False
        if menu == "advanced_setup" and not _must_click_begin_game(win):
            time.sleep(1.0)
            continue
        before = menu
        if menu in ("leader_intro", "begin_game", "unknown") or _must_click_begin_game(win):
            cx, cy = _click_begin_game_once(win)
            check_deadline = time.monotonic() + _BEGIN_GAME_RETRY_SECONDS
            while time.monotonic() < check_deadline and time.monotonic() < deadline:
                win = refresh_window(win)
                menu = detect_menu(win)
                if menu == "ingame":
                    save_menu_position("begin_game", win, cx, cy, force=True)
                    return True
                if _begin_game_click_succeeded(win, before):
                    save_menu_position("begin_game", win, cx, cy, force=True)
                    return True
                time.sleep(0.5)
            win = refresh_window(win)
            if detect_menu(win) in ("leader_intro", "begin_game", "unknown"):
                log.info("begin_game calibrated miss; trying OCR + Space")
                if _click_begin_game_ocr(win):
                    return True
                press_space(win)
                time.sleep(1.0)
                press_enter(win)
                time.sleep(1.0)
                if detect_menu(win) == "ingame":
                    return True
        else:
            time.sleep(1.0)
    return detect_menu(win) == "ingame"


def _click_begin_game_ocr(win: WindowInfo) -> bool:
    """OCR fallback for Begin Game — calibration only; bootstrap uses saved fractions."""
    win = refresh_window(win)
    seen: set[tuple[int, int]] = set()
    for cx, cy, text in _begin_game_ocr_targets(win):
        key = (cx, cy)
        if key in seen:
            continue
        seen.add(key)
        before = detect_menu(win)
        log.info("begin_game OCR '%s' -> client (%d,%d)", text, cx, cy)
        click_client(win, cx, cy, taps=2)
        time.sleep(2.0)
        press_enter_sendinput(win)
        time.sleep(1.5)
        if _confirmed_ingame(win):
            save_menu_position("begin_game", win, cx, cy, force=True)
            return True
    return False


def _click_begin_game(win: WindowInfo) -> bool:
    """Click Begin Game on the leader-ready screen (calibrated — not Start Game)."""
    return _retry_begin_game_until_ready(win, timeout=120.0)


def dismiss_post_start_prompts(win: WindowInfo, timeout: float = 120.0) -> bool:
    """Leader intro: wait for load, then retry Begin Game until ingame."""
    win = refresh_window(win)
    if detect_menu(win) == "ingame" and not _on_leader_intro_screen(win):
        return True
    if _on_leader_intro_screen(win) or detect_menu(win) in ("leader_intro", "begin_game", "unknown"):
        return _advance_leader_intro_to_ingame(win, timeout=timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        win = refresh_window(win)
        menu = detect_menu(win)
        if menu == "ingame" and not _on_leader_intro_screen(win):
            return True
        if menu in ("main", "single_player", "advanced_setup", "load_game_screen"):
            return False
        if _on_leader_intro_screen(win) or menu in ("leader_intro", "begin_game", "unknown"):
            return _advance_leader_intro_to_ingame(win, timeout=deadline - time.monotonic())
        time.sleep(0.6)
    return detect_menu(win) == "ingame" and not _on_leader_intro_screen(win)


def dismiss_leader_intro(win: WindowInfo, timeout: float = 30.0) -> bool:
    return dismiss_post_start_prompts(win, timeout=timeout)


def _configure_all_ai_players(win: WindowInfo, num_players: int) -> list[str]:
    steps: list[str] = []
    for seat in range(1, num_players + 1):
        label = f"Player {seat}"
        if click_text(win, label, timeout=4, exact=False, post_delay=0.25):
            steps.append(f"select_{label}")
        if click_text(win, "Human", timeout=3, exact=True, post_delay=0.25):
            steps.append(f"human_toggle_{seat}")
            for ai_label in ("AI (Computer)", "Computer"):
                if click_text(win, ai_label, timeout=3, exact=False, post_delay=0.25):
                    steps.append(f"ai_{seat}")
                    break
    return steps


def _click_start_game(win: WindowInfo) -> bool:
    """Click Start Game on Create Game screen (defaults OK — no map/speed setup)."""
    win = refresh_window(win)
    if _on_leader_intro_screen(win):
        log.info("start_game skipped — already on leader intro / begin game")
        return True
    if _screen_has_begin_game(win):
        log.info("start_game skipped — Begin Game visible (not Start Game screen)")
        return True
    candidates: list[tuple[float, float]] = []
    entry = _position_entry("start_game")
    if entry is not None:
        candidates.append((entry["pct_x"], entry["pct_y"]))
    candidates.extend(
        [
            (0.50, 0.98),
            (0.50, 0.95),
            (0.85, 0.98),
            (0.80, 0.95),
            (0.50, 0.92),
        ]
    )
    before = detect_menu(win)
    for pct_x, pct_y in candidates:
        cx = int(win.w * pct_x)
        cy = int(win.h * pct_y)
        log.info("start_game calibrated client (%d,%d) pct (%.2f, %.2f)", cx, cy, pct_x, pct_y)
        click_client(win, cx, cy, taps=2)
        time.sleep(2.5)
        menu = detect_menu(win)
        if menu != before and menu not in ("advanced_setup", "main", "single_player"):
            save_menu_position("start_game", win, cx, cy)
            return True
        if menu in ("leader_intro", "unknown", "ingame"):
            save_menu_position("start_game", win, cx, cy)
            return True
    if not _has_saved_menu_position("start_game"):
        return click_text(
            win,
            "Start Game",
            timeout=5,
            post_delay=2.0,
            prefer_bottom=True,
            min_y_fraction=0.88,
            prefixes=("start", "sta"),
            save_position_key="start_game",
        ) and (
            detect_menu(win) != before
            or detect_menu(win) in ("leader_intro", "unknown", "ingame")
        )
    log.warning("start_game calibrated clicks failed — run Invoke-Civ6RecordMenuClick.ps1 -Key start_game")
    return False


def _ensure_civ_foreground(win: WindowInfo, label: str = "", max_wait_s: float = 45.0) -> WindowInfo:
    """Focus Civ6 for bootstrap clicks; refresh window rect after focus."""
    user32 = ctypes.windll.user32
    win = refresh_window(win)
    _hide_blocking_overlays(win)
    deadline = time.monotonic() + max(max_wait_s, 0.5)
    while time.monotonic() < deadline:
        if focus_game(win.hwnd) and _foreground_matches_civ(win):
            time.sleep(0.2)
            return refresh_window(win)
        time.sleep(0.25)
    raise RuntimeError(f"Civ6 not foreground before {label or 'click'} (hwnd={win.hwnd})")


def has_menu_sequence() -> bool:
    return _MENU_SEQUENCE_PATH.is_file()


def load_menu_sequence() -> dict:
    if not _MENU_SEQUENCE_PATH.is_file():
        return {"ref_w": 1600, "ref_h": 1024, "steps": []}
    try:
        return json.loads(_MENU_SEQUENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        log.warning("Could not read %s: %s", _MENU_SEQUENCE_PATH, error)
        return {"ref_w": 1600, "ref_h": 1024, "steps": []}


def save_menu_sequence(win: WindowInfo, steps: list[dict]) -> None:
    payload = {
        "ref_w": win.w,
        "ref_h": win.h,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "steps": steps,
    }
    _MENU_SEQUENCE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log.info("saved menu sequence with %d steps to %s", len(steps), _MENU_SEQUENCE_PATH)


def _sequence_step_client_coords(win: WindowInfo, step: dict, seq: dict) -> tuple[int, int]:
    """Map a recorded menu step to client coords for the current Civ6 window size."""
    ref_w = int(seq.get("ref_w") or win.w or 1)
    ref_h = int(seq.get("ref_h") or win.h or 1)
    if step.get("client_x") is not None and step.get("client_y") is not None:
        cx = int(round(int(step["client_x"]) * win.w / max(ref_w, 1)))
        cy = int(round(int(step["client_y"]) * win.h / max(ref_h, 1)))
    else:
        cx = int(win.w * float(step["pct_x"]))
        cy = int(win.h * float(step["pct_y"]))
    return cx, cy


def replay_menu_sequence(win: WindowInfo) -> list[str]:
    """Replay a recorded click path (positions + delays) through bootstrap menus.

    STABLE PATH — SendInput + foreground + recorded client coords.
    Do not switch to PostMessage (invisible; Civ6 ignores). See civ6-stable-runtime.mdc.
    """
    seq = load_menu_sequence()
    steps = seq.get("steps", [])
    if not steps:
        raise RuntimeError(f"Menu sequence file is empty: {_MENU_SEQUENCE_PATH}")
    events: list[str] = []
    log.info(
        "replay_menu_sequence: %d steps from %s (ref %sx%s, client %dx%d, sendinput)",
        len(steps),
        _MENU_SEQUENCE_PATH,
        seq.get("ref_w"),
        seq.get("ref_h"),
        win.w,
        win.h,
    )
    for index, step in enumerate(steps):
        delay = float(step.get("delay_before_s", 0.0))
        if delay > 0:
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                win = refresh_window(win)
                if win is not None:
                    _hide_blocking_overlays(win)
                    focus_game(win.hwnd)
                time.sleep(min(1.5, max(0.1, deadline - time.monotonic())))
        label = str(step.get("label", f"click_{index + 1}"))
        win = refresh_window(win)
        cx, cy = _sequence_step_client_coords(win, step, seq)
        clicked = False
        for attempt in range(3):
            try:
                win = _ensure_civ_foreground(win, f"sequence_{label}", max_wait_s=12.0)
                click_client(win, cx, cy, taps=2, require_foreground=True)
                clicked = True
                break
            except RuntimeError:
                if attempt >= 2:
                    log.warning("sequence_%s: foreground miss; postmessage fallback", label)
                    win = refresh_window(win)
                    click_client(win, cx, cy, taps=2, require_foreground=False)
                    clicked = True
                    break
                _hide_blocking_overlays(win)
                time.sleep(0.75)
                win = refresh_window(win)
        if not clicked:
            raise RuntimeError(f"sequence click failed for {label}")
        log.info(
            "replay_menu_sequence %s at client (%d,%d) after %.2fs",
            label,
            cx,
            cy,
            delay,
        )
        events.append(f"sequence_{label}")
    return events


def bootstrap_click_menu(win: WindowInfo, key: str) -> tuple[int, int]:
    """Bootstrap menu click: must be foreground + SendInput (no PostMessage fallback)."""
    win = _ensure_civ_foreground(win, key)
    entry = _position_entry(key)
    if entry is None:
        raise RuntimeError(f"No calibrated position for menu key {key}")
    cx, cy = _menu_client_coords(win, key, entry)
    click_client(win, cx, cy, taps=2, require_foreground=True)
    log.info("bootstrap_click_menu %s at client (%d,%d)", key, cx, cy)
    return cx, cy


def bootstrap_dismiss_timed(win: WindowInfo) -> list[str]:
    """Hide overlays, Esc, fixed wait — no OCR main-menu detection.

    STABLE PATH — part of working bootstrap; see civ6-stable-runtime.mdc.
    """
    _hide_blocking_overlays(win)
    for _ in range(3):
        press_escape(win)
        time.sleep(0.4)
    log.info("bootstrap_dismiss: waiting %.0fs for main menu", _BOOTSTRAP_DISMISS_WAIT_S)
    time.sleep(_BOOTSTRAP_DISMISS_WAIT_S)
    return ["timed_dismiss"]


def bootstrap_click_begin_game_timed(win: WindowInfo) -> None:
    """Click every hardcoded Begin Game coordinate on a fixed schedule.

    STABLE PATH — runs after replay_menu_sequence; see civ6-stable-runtime.mdc.
    """
    log.info(
        "bootstrap_begin_game: wait %.0fs then %d rounds every %.0fs",
        _BOOTSTRAP_BEGIN_GAME_INTRO_WAIT_S,
        _BOOTSTRAP_BEGIN_GAME_ROUNDS,
        _BOOTSTRAP_BEGIN_GAME_INTERVAL_S,
    )
    intro_deadline = time.monotonic() + _BOOTSTRAP_BEGIN_GAME_INTRO_WAIT_S
    while time.monotonic() < intro_deadline:
        win = refresh_window(win)
        if win is not None:
            if _confirmed_ingame(win):
                log.info("bootstrap_begin_game: ingame during intro wait")
                return
            _hide_blocking_overlays(win)
            focus_game(win.hwnd)
        time.sleep(min(1.0, max(0.1, intro_deadline - time.monotonic())))
    for round_idx in range(_BOOTSTRAP_BEGIN_GAME_ROUNDS):
        win = refresh_window(win)
        if win is not None and _confirmed_ingame(win):
            log.info("bootstrap_begin_game: ingame before round %d", round_idx + 1)
            return
        try:
            win = _ensure_civ_foreground(win, f"begin_game_round_{round_idx + 1}", max_wait_s=12.0)
            require_foreground = True
        except RuntimeError as error:
            log.warning("bootstrap_begin_game round=%d: foreground miss (%s)", round_idx + 1, error)
            require_foreground = False
        for cx, cy in _begin_game_bootstrap_coords(win):
            log.info(
                "bootstrap_begin_game round=%d client (%d,%d)",
                round_idx + 1,
                cx,
                cy,
            )
            click_client(win, cx, cy, taps=2, require_foreground=require_foreground)
            time.sleep(0.35)
            press_enter_sendinput(win)
            time.sleep(0.45)
            win = refresh_window(win)
            if win is not None and _confirmed_ingame(win):
                log.info("bootstrap_begin_game: ingame after round %d click", round_idx + 1)
                return
        if round_idx + 1 < _BOOTSTRAP_BEGIN_GAME_ROUNDS:
            time.sleep(_BOOTSTRAP_BEGIN_GAME_INTERVAL_S)


def bootstrap_create_game_timed(win: WindowInfo) -> list[str]:
    """Deterministic new-game bootstrap: recorded sequence or calibrated clicks + fixed sleeps.

    STABLE PATH — see .cursor/rules/civ6-stable-runtime.mdc before editing.
    """
    if has_menu_sequence() and load_menu_sequence().get("steps"):
        win = _ensure_civ_foreground(win, "bootstrap_start")
        time.sleep(_BOOTSTRAP_BEFORE_MENU_CLICKS_S)
        events = replay_menu_sequence(win)
        win = refresh_window(win)
        if win is None:
            win = find_civ_window()
        if win is not None:
            bootstrap_click_begin_game_timed(win)
            events.append("begin_game_after_sequence")
        return events

    steps: list[str] = []
    win = _ensure_civ_foreground(win, "bootstrap_start")
    time.sleep(_BOOTSTRAP_BEFORE_MENU_CLICKS_S)

    bootstrap_click_menu(win, "main_single_player")
    steps.append("clicked_single_player")
    time.sleep(_BOOTSTRAP_AFTER_SINGLE_PLAYER_S)

    win = _ensure_civ_foreground(win, "after_single_player")
    bootstrap_click_menu(win, "sp_create_game")
    steps.append("clicked_create_game")
    time.sleep(_BOOTSTRAP_AFTER_CREATE_GAME_S)

    win = _ensure_civ_foreground(win, "after_create_game")
    bootstrap_click_menu(win, "start_game")
    steps.append("clicked_start_game")
    time.sleep(_BOOTSTRAP_AFTER_START_GAME_S)

    win = _ensure_civ_foreground(win, "before_begin_game")
    bootstrap_click_begin_game_timed(win)
    steps.append("clicked_begin_game")
    return steps


def create_advanced_setup_game(
    win: WindowInfo,
    map_type: str = "Islands",
    map_size: str = "Small",
    game_speed: str = "Online",
    num_players: int = 4,
    configure_players: bool = False,
    configure_setup: bool = False,
) -> list[str]:
    """Open Create Game and start with current defaults (setup optional)."""

    steps: list[str] = []

    def _require_begin_game() -> None:
        if "clicked_begin_game" in steps:
            return
        steps.append("leader_intro_ready")
        if not _advance_leader_intro_to_ingame(win):
            _log_ocr_sample(win, "begin_game_failed")
            raise RuntimeError("Could not click Begin Game on leader intro")
        steps.append("clicked_begin_game")

    if _must_click_begin_game(win):
        _require_begin_game()
        return steps

    if _confirmed_ingame(win):
        return steps

    if not open_advanced_setup(win):
        menu = detect_menu(win)
        if _must_click_begin_game(win):
            _require_begin_game()
            return steps
        if _confirmed_ingame(win):
            return steps
        _log_ocr_sample(win, "advanced_setup_failed")
        raise RuntimeError("Could not open Advanced Setup")

    if _must_click_begin_game(win):
        _require_begin_game()
        return steps

    menu = detect_menu(win)
    if menu == "advanced_setup":
        steps.append("advanced_setup")
    else:
        steps.append(f"setup_menu={menu}")

    if configure_setup:
        speed_options = [game_speed]
        if game_speed.lower() == "online":
            speed_options.append("Quick")
        for speed in speed_options:
            if _select_setup_dropdown(win, "game_speed", speed):
                steps.append(f"game_speed={speed}")
                break
        if _select_setup_dropdown(win, "map_type", map_type):
            steps.append(f"map_type={map_type}")
        if _select_setup_dropdown(win, "map_size", map_size):
            steps.append(f"map_size={map_size}")
        if _select_setup_dropdown(win, "num_players", str(num_players)):
            steps.append(f"players={num_players}")

    if configure_players:
        steps.extend(_configure_all_ai_players(win, num_players))

    if not _click_start_game(win):
        _log_ocr_sample(win, "start_game_failed")
        raise RuntimeError("Could not click Start Game")
    steps.append("clicked_start_game")
    _require_begin_game()
    return steps


def inspect_ui(
    win: WindowInfo | None = None,
    out_dir: Path | None = None,
    filter_substr: str = "",
) -> dict:
    """Capture Civ6 window, OCR all text with client coords, annotate screenshot."""
    from PIL import ImageDraw

    if win is None:
        win = find_civ_window()
    if win is None:
        raise RuntimeError("Civ6 window not found")
    win = refresh_window(win)
    if out_dir is None:
        out_dir = Path(__file__).resolve().parents[2] / "artifacts" / "civ6-ui-inspect"
    out_dir.mkdir(parents=True, exist_ok=True)

    menu = detect_menu(win)
    results = ocr_window(win)
    entries: list[dict[str, object]] = []
    highlights: list[tuple[int, int, str]] = []
    needle = filter_substr.lower().strip()

    for text, x, y in results:
        cx = x - win.x
        cy = y - win.y
        norm = _normalize(text)
        entry = {
            "text": text,
            "client_x": cx,
            "client_y": cy,
            "pct_x": round(cx / max(win.w, 1), 4),
            "pct_y": round(cy / max(win.h, 1), 4),
        }
        if needle and needle not in norm:
            continue
        entries.append(entry)
        if not needle and (
            norm.startswith("beg")
            or norm == "game"
            or "begin" in norm
            or "continue" in norm
            or "start" in norm
        ):
            highlights.append((cx, cy, text))

    saved: dict[str, object] = {}
    for key in ("begin_game", "start_game", "main_single_player", "sp_create_game"):
        coords = _client_coords_for_key(win, key)
        if coords is not None:
            saved[key] = {"client_x": coords[0], "client_y": coords[1]}

    image = capture_window(win)
    draw = ImageDraw.Draw(image)
    for cx, cy, label in highlights:
        draw.rectangle((cx - 6, cy - 6, cx + 6, cy + 6), outline="lime", width=2)
        draw.text((cx + 8, cy - 8), label[:24], fill="lime")
    for key, pos in saved.items():
        cx = int(pos["client_x"])
        cy = int(pos["client_y"])
        draw.rectangle((cx - 10, cy - 10, cx + 10, cy + 10), outline="red", width=2)
        draw.text((cx + 12, cy - 10), f"saved:{key}", fill="red")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    png_path = out_dir / f"inspect_{stamp}.png"
    json_path = out_dir / f"inspect_{stamp}.json"
    image.save(png_path, format="PNG")

    report = {
        "menu": menu,
        "window": {"w": win.w, "h": win.h, "hwnd": win.hwnd},
        "ocr_count": len(results),
        "entries": entries if needle else entries[:80],
        "highlights": [{"text": t, "client_x": x, "client_y": y} for x, y, t in highlights],
        "saved_positions": saved,
        "screenshot": str(png_path),
    }
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    log.info("UI inspect menu=%s highlights=%d screenshot=%s", menu, len(highlights), png_path)
    return report


def _log_ocr_sample(win: WindowInfo, label: str, limit: int = 25) -> None:
    results = ocr_window(win)
    sample = [f"{text}@({x},{y})" for text, x, y in results[:limit]]
    log.info("OCR %s (%d hits): %s", label, len(results), "; ".join(sample))


def audit_screenshot(win: WindowInfo, directory: Path, label: str) -> str:
    path = directory / f"{label}.png"
    return screenshot_to(path, win)


def screenshot_to(path, win: WindowInfo | None = None) -> str:
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    win = win or find_civ_window()
    if win is None:
        raise RuntimeError("Civ6 window not found for screenshot")
    image = capture_window(win)
    image.save(target, format="PNG")
    return str(target)
