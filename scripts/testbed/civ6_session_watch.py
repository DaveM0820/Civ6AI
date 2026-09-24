"""Watch Civ6AI session artifacts for Gate 0 / seat experiment progress."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def _scan_session(civ6ai_root: Path) -> dict:
    sessions = civ6ai_root / "sessions"
    if not sessions.is_dir():
        return {"sessions": 0, "players": []}
    players = []
    for player_dir in sessions.rglob("PLAYER_*"):
        if not player_dir.is_dir():
            continue
        snapshot = player_dir / "snapshot.json"
        decision = player_dir / "decision.json"
        seat_log = player_dir / "seat-experiment.jsonl"
        players.append(
            {
                "path": str(player_dir),
                "snapshot": snapshot.is_file(),
                "decision": decision.is_file(),
                "seat_experiment_lines": sum(1 for _ in seat_log.open(encoding="utf-8")) if seat_log.is_file() else 0,
            }
        )
    return {"sessions_root": str(sessions), "players": players}


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Civ6AI session I/O")
    parser.add_argument("--civ6ai-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=0, help="Poll until timeout (0 = single scan)")
    parser.add_argument("--require-decision", action="store_true")
    parser.add_argument("--require-seat-log", action="store_true")
    args = parser.parse_args()

    deadline = time.monotonic() + max(0, args.timeout_seconds)
    while True:
        report = _scan_session(args.civ6ai_root)
        print(json.dumps(report, indent=2))
        ok = True
        if args.require_decision:
            ok = any(row["decision"] for row in report["players"])
        if args.require_seat_log:
            ok = ok and any(row["seat_experiment_lines"] > 0 for row in report["players"])
        if ok and (args.require_decision or args.require_seat_log):
            return
        if args.timeout_seconds <= 0:
            return
        if time.monotonic() >= deadline:
            raise SystemExit("TIMEOUT: required session artifacts not found")
        time.sleep(5)


if __name__ == "__main__":
    main()
