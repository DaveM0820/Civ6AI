"""Inspect Civ6 window: OCR text positions + annotated screenshot."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from civ6_ui_automation import find_civ_window, inspect_ui

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR Civ6 UI and save annotated screenshot")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--filter", default="", help="Only show OCR lines containing this substring")
    args = parser.parse_args()

    win = find_civ_window()
    if win is None:
        print("Civ6 window not found.")
        return 1

    report = inspect_ui(win, out_dir=args.out_dir, filter_substr=args.filter)
    print(json.dumps(report, indent=2))
    print(f"Screenshot: {report['screenshot']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
