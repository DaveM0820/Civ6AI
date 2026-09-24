"""Build per-player sequential turn timelines for Civ VI autotest."""
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


def _wire_excerpt(player_dir: Path, turn: int) -> str:
    io_dir = player_dir / "io_logs"
    if not io_dir.is_dir():
        return ""
    for path in sorted(io_dir.glob("*_wire.txt")):
        return path.read_text(encoding="utf-8-sig")[:2000]
    wire = player_dir / "io_logs"
    return ""


def _input_for_turn(player_dir: Path, turn: int) -> dict[str, Any]:
    io_dir = player_dir / "io_logs"
    if not io_dir.is_dir():
        return {}
    for path in sorted(io_dir.glob("*_input.json")):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        decision = payload.get("decision", {})
        if int(decision.get("turn", -1)) == turn:
            return payload
    paths = sorted(io_dir.glob("*_input.json"))
    if paths:
        return json.loads(paths[-1].read_text(encoding="utf-8-sig"))
    return {}


def build_player_timeline(player_dir: Path) -> list[dict[str, Any]]:
    player_id = player_dir.name
    journal = _load_jsonl(player_dir / "journal.jsonl")
    apply_rows = _load_jsonl(player_dir / "apply-results.jsonl")
    apply_by_turn: dict[int, list[dict[str, Any]]] = {}
    for row in apply_rows:
        if row.get("event") != "apply_result":
            continue
        turn = int(row.get("turn", 0))
        apply_by_turn.setdefault(turn, []).append(row)

    timeline: list[dict[str, Any]] = []
    for row in journal:
        turn = int(row.get("private", {}).get("turn", row.get("metrics", {}).get("turn", 0)))
        response = row.get("response", {})
        thought = response.get("thought", {}) if isinstance(response, dict) else {}
        validated = row.get("validated", {})
        intended = []
        if isinstance(validated, dict):
            intended = validated.get("commands", [])
        apply_turn = apply_by_turn.get(turn, [])
        executed = [r for r in apply_turn if r.get("ok")]
        failed = [r for r in apply_turn if not r.get("ok")]
        input_payload = _input_for_turn(player_dir, turn)
        map_path = input_payload.get("map_image_path")
        empire = None
        if executed:
            empire = executed[-1].get("empire")
        elif isinstance(input_payload.get("your_empire"), dict):
            empire = input_payload["your_empire"]
        timeline.append({
            "turn": turn,
            "player_id": player_id,
            "status": row.get("status"),
            "wire_excerpt": _wire_excerpt(player_dir, turn)[:1500],
            "thought_situation": thought.get("situation") if isinstance(thought, dict) else None,
            "thought_strategy": thought.get("strategy") if isinstance(thought, dict) else None,
            "intended_commands": intended,
            "executed_commands": executed,
            "failed_commands": failed,
            "map_image_path": map_path,
            "empire": empire,
            "metrics": row.get("metrics", {}),
        })
    return timeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Civ VI per-player timeline")
    parser.add_argument("player_dir", type=Path, help="sessions/{id}/PLAYER_N")
    parser.add_argument("--output", type=Path, help="Output JSONL path")
    args = parser.parse_args()

    timeline = build_player_timeline(args.player_dir)
    out = args.output
    if out is None:
        autotest = args.player_dir.parent.parent.parent / "autotest" / "timelines"
        autotest.mkdir(parents=True, exist_ok=True)
        out = autotest / f"{args.player_dir.name}.jsonl"

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as stream:
        for row in timeline:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(timeline)} turns to {out}")


if __name__ == "__main__":
    main()
