"""Analyze Civ VI seat-type experiment logs (Gate 2)."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8-sig")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            events.append(payload)
    return events


def analyze_seat_experiment(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_turn: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    for event in events:
        if event.get("event") != "seat_experiment":
            continue
        key = (str(event.get("player_id", "PLAYER_?")), int(event.get("turn", 0)))
        by_turn[key][str(event.get("phase", ""))] = event

    rows: list[dict[str, Any]] = []
    production_overwrites = 0
    unit_fallback_turns = 0
    llm_apply_ok = 0
    human_seats = 0
    ai_seats = 0

    for (player_id, turn), phases in sorted(by_turn.items(), key=lambda item: (item[0][1], item[0][0])):
        start = phases.get("turn_start", {})
        post_apply = phases.get("post_llm_apply", {})
        post_native = phases.get("post_native_ai", {})
        seat_human = bool(start.get("seat_human"))
        if seat_human:
            human_seats += 1
        else:
            ai_seats += 1
        if post_apply.get("llm_apply_ok"):
            llm_apply_ok += 1
        if post_native.get("production_overwritten"):
            production_overwrites += 1
        if post_native.get("units_moved_by_native"):
            unit_fallback_turns += 1
        rows.append(
            {
                "turn": turn,
                "player_id": player_id,
                "seat_human": seat_human,
                "experiment_target": start.get("experiment_target"),
                "observed_post_apply": post_apply.get("observed_production"),
                "observed_post_native": post_native.get("observed_production"),
                "production_overwritten": bool(post_native.get("production_overwritten")),
                "units_moved_by_native": bool(post_native.get("units_moved_by_native")),
                "llm_apply_ok": bool(post_apply.get("llm_apply_ok")),
            }
        )

    total = len(rows)
    overwrite_rate = (production_overwrites / total) if total else 0.0
    unit_fallback_rate = (unit_fallback_turns / total) if total else 0.0

    if production_overwrites > 0:
        recommendation = "reapply_production_after_native_ai"
        rationale = (
            "Firaxis city AI overwrote LLM production on AI seats. "
            "Keep AI seats for unit fallback; re-apply production after PlayerTurnActivated "
            "or skip city AI for managed seats."
        )
    elif unit_fallback_turns > 0:
        recommendation = "hybrid_ai_seats"
        rationale = (
            "Native AI moved unmoved units without overwriting production. "
            "Keep standard AI seats with hybrid unit fallback."
        )
    else:
        recommendation = "needs_more_data"
        rationale = "No overwrite or unit-move signal captured yet. Run more turns with CIV6AI_SEAT_EXPERIMENT=1."

    return {
        "summary": {
            "turns_analyzed": total,
            "human_seat_turns": human_seats,
            "ai_seat_turns": ai_seats,
            "llm_apply_ok": llm_apply_ok,
            "production_overwrites": production_overwrites,
            "production_overwrite_rate": overwrite_rate,
            "unit_fallback_turns": unit_fallback_turns,
            "unit_fallback_rate": unit_fallback_rate,
            "recommendation": recommendation,
            "rationale": rationale,
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Civ VI seat-experiment.jsonl")
    parser.add_argument("log", type=Path, help="Path to seat-experiment.jsonl")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()

    report = analyze_seat_experiment(_load_events(args.log))
    if args.json:
        print(json.dumps(report, indent=2))
        return

    summary = report["summary"]
    print("Civ VI seat-type experiment report")
    print(f"  turns analyzed: {summary['turns_analyzed']}")
    print(f"  human seat turns: {summary['human_seat_turns']}")
    print(f"  ai seat turns: {summary['ai_seat_turns']}")
    print(f"  llm production apply ok: {summary['llm_apply_ok']}")
    print(f"  production overwrites: {summary['production_overwrites']} ({summary['production_overwrite_rate']:.0%})")
    print(f"  unit fallback turns: {summary['unit_fallback_turns']} ({summary['unit_fallback_rate']:.0%})")
    print(f"  recommendation: {summary['recommendation']}")
    print(f"  rationale: {summary['rationale']}")


if __name__ == "__main__":
    main()
