"""Deep inspect one Civ VI autotest turn: journal, io_logs, apply-results, autotest.log."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def inspect_turn(session_dir: Path, player_id: str, turn: int, autotest_log: Path | None) -> dict[str, Any]:
    player_dir = session_dir / player_id
    issues: list[str] = []
    journal_match = None
    for row in _load_jsonl(player_dir / "journal.jsonl"):
        row_turn = int(row.get("private", {}).get("turn", row.get("metrics", {}).get("turn", -1)))
        if row_turn == turn:
            journal_match = row
            break
    if journal_match is None:
        issues.append("missing journal row for turn")

    io_dir = player_dir / "io_logs"
    input_path = None
    wire_path = None
    raw_path = None
    if io_dir.is_dir():
        for path in sorted(io_dir.glob("*_input.json")):
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            decision = payload.get("decision", {})
            if int(decision.get("turn", -1)) == turn:
                input_path = path
                wire_path = path.with_name(path.stem.replace("_input", "_wire") + ".txt")
                raw_path = path.with_name(path.stem.replace("_input", "_raw_output") + ".json")
                break
    else:
        issues.append("missing io_logs directory")

    if journal_match and input_path is None:
        issues.append("journal exists but no matching io input log")
    if input_path and not input_path.is_file():
        issues.append("expected input log missing")
    if wire_path and not wire_path.is_file():
        issues.append("expected wire log missing")
    if journal_match and journal_match.get("status") == "approved" and not journal_match.get("commands"):
        issues.append("approved without commands")

    apply_rows = [
        row for row in _load_jsonl(player_dir / "apply-results.jsonl")
        if row.get("event") == "apply_result" and int(row.get("turn", -1)) == turn
    ]
    if journal_match and journal_match.get("commands") and not apply_rows:
        issues.append("commands bound but no apply-results")

    log_lines = []
    if autotest_log and autotest_log.is_file():
        for line in autotest_log.read_text(encoding="utf-8-sig").splitlines():
            if f"turn={turn}" in line or f"player={player_id.split('_', 1)[-1]}" in line:
                log_lines.append(line)

    return {
        "session_dir": str(session_dir),
        "player_id": player_id,
        "turn": turn,
        "issues": issues,
        "journal_status": journal_match.get("status") if journal_match else None,
        "journal_commands": len(journal_match.get("commands", [])) if journal_match else 0,
        "input_path": str(input_path) if input_path else None,
        "wire_path": str(wire_path) if wire_path and wire_path.is_file() else None,
        "raw_output_path": str(raw_path) if raw_path and raw_path.is_file() else None,
        "apply_results": apply_rows,
        "autotest_log_lines": log_lines[-20:],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one Civ VI autotest turn")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--player", default="PLAYER_0")
    parser.add_argument("--turn", type=int, required=True)
    parser.add_argument("--autotest-log", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    autotest_log = args.autotest_log
    if autotest_log is None:
        candidate = args.session_dir.parent.parent / "autotest" / "autotest.log"
        if candidate.is_file():
            autotest_log = candidate

    report = inspect_turn(args.session_dir, args.player, args.turn, autotest_log)
    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"Inspect {args.player} turn {args.turn}")
    print(f"  journal status: {report['journal_status']}")
    print(f"  journal commands: {report['journal_commands']}")
    print(f"  apply results: {len(report['apply_results'])}")
    if report["issues"]:
        print("  issues:")
        for issue in report["issues"]:
            print(f"    - {issue}")
    else:
        print("  issues: none")


if __name__ == "__main__":
    main()
