"""Record a full click path through Civ6 bootstrap menus into civ6_menu_sequence.json.

Left-click each menu button in order (Single Player -> Create Game -> Start Game -> Begin Game).
Press F10 when you have reached in-game. Autotest bootstrap replays the saved path.
"""
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
    load_menu_sequence,
    refresh_window,
    replay_menu_sequence,
    save_menu_sequence,
)

log = logging.getLogger(__name__)

VK_LBUTTON = 0x01
VK_F10 = 0x79


def _key_down(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def record_click_sequence(win, timeout: float) -> list[dict]:
    if sys.platform != "win32":
        raise RuntimeError("Windows only")
    import win32gui

    user32 = ctypes.windll.user32
    steps: list[dict] = []
    last_time = time.monotonic()
    deadline = time.monotonic() + timeout
    last_print = 0.0

    print("Recording... left-click buttons inside Civ6. Press F10 when in-game.")
    print()

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
                f"\r  step {len(steps) + 1}  cursor ({cx:4d},{cy:4d})  pct ({pct_x:.4f},{pct_y:.4f})  ",
                end="",
                flush=True,
            )
            last_print = now

        if _key_down(VK_F10):
            while _key_down(VK_F10):
                time.sleep(0.02)
            print()
            if steps:
                print(f"Finished recording ({len(steps)} clicks).")
                break
            print("No clicks recorded yet — keep clicking or wait for timeout.")
            continue

        if _key_down(VK_LBUTTON):
            if inside:
                while _key_down(VK_LBUTTON):
                    time.sleep(0.02)
                delay = now - last_time
                last_time = time.monotonic()
                pct_x = cx / max(win.w, 1)
                pct_y = cy / max(win.h, 1)
                step = {
                    "label": f"click_{len(steps) + 1}",
                    "delay_before_s": round(delay, 2),
                    "pct_x": round(pct_x, 4),
                    "pct_y": round(pct_y, 4),
                    "client_x": cx,
                    "client_y": cy,
                }
                steps.append(step)
                print()
                print(
                    f"  + step {len(steps)}: client ({cx},{cy}) "
                    f"delay {step['delay_before_s']}s"
                )
        time.sleep(0.02)

    if not steps:
        print()
        print("Timed out — no clicks recorded.")
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record Civ6 bootstrap menu clicks into civ6_menu_sequence.json"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Seconds to wait for clicks (default: 600)",
    )
    parser.add_argument(
        "--replay-test",
        action="store_true",
        help="After saving, replay the sequence once (Civ6 must stay open)",
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
    existing = load_menu_sequence().get("steps", [])
    print(f"Civ6 client {win.w}x{win.h} hwnd={win.hwnd}")
    if existing:
        print(f"Existing sequence has {len(existing)} steps (will be replaced).")
    print()
    print("1. Get Civ6 to the main menu (dismiss overlays if needed).")
    print("2. Left-click each button: Single Player -> Create Game -> Start Game -> Begin Game.")
    print("3. Press F10 when you are in-game.")
    print()
    print(f"Waiting up to {int(args.timeout)}s...")
    print()

    steps = record_click_sequence(win, args.timeout)
    if not steps:
        return 1

    win = refresh_window(win)
    save_menu_sequence(win, steps)
    print()
    print(f"Saved {len(steps)} steps to scripts/testbed/civ6_menu_sequence.json")
    print("Autotest bootstrap will replay this path instead of hardcoded menu coords.")
    print()
    print("Step summary:")
    for index, step in enumerate(steps, start=1):
        print(
            f"  {index}. {step['label']}: "
            f"({step['client_x']},{step['client_y']}) "
            f"wait {step['delay_before_s']}s"
        )

    if args.replay_test:
        print()
        print("Replay test in 3s — do not touch mouse...")
        time.sleep(3.0)
        win = refresh_window(win)
        events = replay_menu_sequence(win)
        print(f"Replay events: {events}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
