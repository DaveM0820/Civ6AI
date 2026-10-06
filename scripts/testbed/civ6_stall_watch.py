"""Watch Lua.log for a turn that has not advanced (F7 stall watchdog helper)."""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

_TURN = re.compile(r"local_turn_begin\|player=\d+\|turn=(\d+)")
_STALL = re.compile(r"autotest\|stall\|")


def latest_turn(text: str) -> int | None:
    turns = [int(m.group(1)) for m in _TURN.finditer(text)]
    return turns[-1] if turns else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report if Civ6Ai Lua.log has stalled")
    parser.add_argument("lua_log", type=Path)
    parser.add_argument("--stall-seconds", type=int, default=240)
    args = parser.parse_args(argv)
    if not args.lua_log.is_file():
        print(f"missing {args.lua_log}", file=sys.stderr)
        return 2
    text = args.lua_log.read_text(encoding="utf-8", errors="replace")
    if _STALL.search(text):
        print("stall already logged")
        return 1
    turn = latest_turn(text)
    age = time.time() - args.lua_log.stat().st_mtime
    print(f"latest_turn={turn} log_age_s={age:.0f}")
    if age >= args.stall_seconds:
        print("stall_suspected|log_not_updated")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
