"""Aggregate Civ VI autotest session metrics across players and turns."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
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


def _load_journal(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl(path)


def _player_dirs(session_dir: Path) -> list[Path]:
    return sorted(
        [child for child in session_dir.iterdir() if child.is_dir() and child.name.startswith("PLAYER_")],
        key=lambda p: p.name,
    )


def analyze_autotest_session(session_dir: Path, autotest_log: Path | None = None) -> dict[str, Any]:
    players = _player_dirs(session_dir)
    turn_metrics = _load_jsonl(session_dir / "turn_metrics.jsonl")
    by_turn_player: dict[tuple[int, str], dict[str, Any]] = defaultdict(dict)

    status_counts = Counter()
    kind_validated = Counter()
    kind_applied = Counter()
    apply_failures: list[dict[str, Any]] = []
    issues: list[str] = []
    token_total = 0
    wall_ms_total = 0

    for player_dir in players:
        player_id = player_dir.name
        journal_rows = _load_journal(player_dir / "journal.jsonl")
        apply_rows = _load_jsonl(player_dir / "apply-results.jsonl")
        io_dir = player_dir / "io_logs"

        for row in journal_rows:
            turn = int(row.get("private", {}).get("turn", row.get("metrics", {}).get("turn", 0)))
            key = (turn, player_id)
            by_turn_player[key]["journal"] = row
            status = str(row.get("status", "unknown"))
            status_counts[status] += 1
            metrics = row.get("metrics", {})
            if isinstance(metrics, dict):
                wall_ms_total += int(metrics.get("wall_ms", 0) or 0)
                usage = metrics.get("usage", {})
                if isinstance(usage, dict):
                    token_total += int(usage.get("total_tokens", 0) or 0)
            validated = row.get("validated", {})
            if isinstance(validated, dict):
                for cmd in validated.get("commands", []):
                    if isinstance(cmd, dict):
                        kind_validated[str(cmd.get("command_id", ""))] += 1
            if status == "approved" and not row.get("commands"):
                issues.append(f"{player_id} turn {turn}: approved but no commands")

        for row in apply_rows:
            if row.get("event") != "apply_result":
                continue
            turn = int(row.get("turn", 0))
            key = (turn, player_id)
            by_turn_player[key]["apply"] = by_turn_player[key].get("apply", []) + [row]
            kind = str(row.get("kind", ""))
            if row.get("ok"):
                kind_applied[kind] += 1
            else:
                apply_failures.append(row)

        if not io_dir.is_dir():
            issues.append(f"{player_id}: missing io_logs")
            continue
        input_logs = list(io_dir.glob("*_input.json"))
        if not input_logs and journal_rows:
            issues.append(f"{player_id}: journal without io_logs")

    autotest_events = []
    if autotest_log and autotest_log.is_file():
        autotest_events = autotest_log.read_text(encoding="utf-8-sig").splitlines()

    stall_screenshots = 0
    stall_events_path = session_dir.parent.parent / "autotest" / "stall_events.jsonl"
    if stall_events_path.is_file():
        stall_screenshots = sum(
            1 for line in stall_events_path.read_text(encoding="utf-8-sig").splitlines()
            if "stall_screenshot" in line
        )

    return {
        "session_dir": str(session_dir),
        "players": [p.name for p in players],
        "summary": {
            "turn_metrics_rows": len(turn_metrics),
            "journal_status": dict(status_counts),
            "validated_command_ids": dict(kind_validated),
            "applied_kinds": dict(kind_applied),
            "apply_failures": len(apply_failures),
            "apply_failure_kinds": Counter(str(r.get("kind")) for r in apply_failures),
            "token_total_est": token_total,
            "wall_ms_total": wall_ms_total,
            "issues": issues,
            "autotest_log_lines": len(autotest_events),
            "stall_screenshots": stall_screenshots,
        },
        "apply_failures": apply_failures[:50],
        "turn_player_keys": len(by_turn_player),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Civ VI autotest session")
    parser.add_argument("session_dir", type=Path, help="civ6ai/sessions/{session_id}")
    parser.add_argument("--autotest-log", type=Path, help="civ6ai/autotest/autotest.log")
    parser.add_argument("--output", type=Path, help="Write report.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    autotest_log = args.autotest_log
    if autotest_log is None:
        candidate = args.session_dir.parent.parent / "autotest" / "autotest.log"
        if candidate.is_file():
            autotest_log = candidate

    report = analyze_autotest_session(args.session_dir, autotest_log)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    elif autotest_log is not None:
        default_out = autotest_log.parent / "report.json"
        default_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
        return

    summary = report["summary"]
    print("Civ VI autotest report")
    print(f"  session: {report['session_dir']}")
    print(f"  players: {', '.join(report['players'])}")
    print(f"  journal status: {summary['journal_status']}")
    print(f"  apply failures: {summary['apply_failures']}")
    print(f"  wall_ms total: {summary['wall_ms_total']}")
    print(f"  token est total: {summary['token_total_est']}")
    if summary["issues"]:
        print("  issues:")
        for issue in summary["issues"]:
            print(f"    - {issue}")


if __name__ == "__main__":
    main()
