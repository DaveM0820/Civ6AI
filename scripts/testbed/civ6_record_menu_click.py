"""Record a manual click inside the Civ6 window into civ6_menu_positions.json."""
from __future__ import annotations

import argparse
import ctypes
import logging
import sys
import time
from ctypes import wintypes

SCRIPT_DIR = __import__("pathlib").Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from civ6_ui_automation import (
    find_civ_window,
    load_menu_positions,
    refresh_window,
    save_menu_position,
)

log = logging.getLogger(__name__)

VK_LBUTTON = 0x01


def wait_for_client_click(win, timeout: float) -> tuple[int, int] | None:
    if sys.platform != "win32":
        raise RuntimeError("Windows only")
    import win32gui

    user32 = ctypes.windll.user32
    deadline = time.monotonic() + timeout
    last_print = 0.0

    while time.monotonic() < deadline:
        win = refresh_window(win)
        hwnd = win.hwnd
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        cx, cy = win32gui.ScreenToClient(hwnd, (pt.x, pt.y))
        inside = 0 <= cx < win.w and 0 <= cy < win.h
        now = time.monotonic()
        if inside and now - last_print > 0.12:
            pct_x = cx / max(win.w, 1)
            pct_y = cy / max(win.h, 1)
            print(
                f"\r  cursor client ({cx:4d},{cy:4d})  pct ({pct_x:.4f},{pct_y:.4f})  ",
                end="",
                flush=True,
            )
            last_print = now

        if user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
            if inside:
                while user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
                    time.sleep(0.02)
                print()
                return cx, cy
        time.sleep(0.02)
    print()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record a click in Civ6 into civ6_menu_positions.json"
    )
    parser.add_argument(
        "--key",
        default="begin_game",
        help="Position key to save (default: begin_game)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for click (default: 300)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    win = None
    for _ in range(120):
        win = find_civ_window()
        if win is not None:
            break
        time.sleep(0.5)
    if win is None:
        print("Civ6 window not found. Launch Civ6 first.")
        return 1

    win = refresh_window(win)
    print(f"Civ6 client {win.w}x{win.h} hwnd={win.hwnd}")
    print(f"Positions file: {load_menu_positions().get('items', {}).get(args.key, 'not set')}")
    print()
    print(f"Navigate to the screen with '{args.key}', then left-click the target button.")
    print("Move the mouse over Civ6 to see live client coordinates.")
    print(f"Waiting up to {int(args.timeout)}s for your click...")
    print()

    coords = wait_for_client_click(win, args.timeout)
    if coords is None:
        print("Timed out — no click recorded.")
        return 1

    cx, cy = coords
    win = refresh_window(win)
    save_menu_position(args.key, win, cx, cy, force=True, recorded=True)
    data = load_menu_positions()
    entry = data.get("items", {}).get(args.key, {})
    print(f"Recorded {args.key}:")
    print(f"  client_x={entry.get('client_x')} client_y={entry.get('client_y')}")
    print(f"  pct_x={entry.get('pct_x')} pct_y={entry.get('pct_y')}")
    print(f"  ref {data.get('ref_w')}x{data.get('ref_h')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
