"""Per-seat turn report for Civ6 sidecar decisions (F12)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sidecar import pipeline_v2 as pipeline


def build_turn_report(
    *,
    snapshot: dict[str, Any],
    record: dict[str, Any],
    timings: dict[str, Any] | None = None,
    wire_text: str = "",
    dropped: list[str] | None = None,
) -> dict[str, Any]:
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    validated = record.get("validated") if isinstance(record.get("validated"), dict) else {}
    commands = record.get("commands") if isinstance(record.get("commands"), list) else []
    required = 0
    try:
        from sidecar import civ6_prompt_coaching as coaching

        required = len(coaching.civ6_required_thought_rows(snapshot))
    except Exception:
        required = 0
    given = len(commands)
    chats = validated.get("chat_messages") if isinstance(validated.get("chat_messages"), list) else []
    history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
    last_results = []
    for item in history.get("command_results") or []:
        if not isinstance(item, dict):
            continue
        last_results.append({
            "kind": item.get("kind") or item.get("order_kind"),
            "reason": item.get("reason"),
            "ok": item.get("kind") != "APPLY_FAILED" if item.get("kind") else item.get("ok"),
            "summary": str(item.get("summary") or "")[:200],
            "decision_turn": item.get("turn"),
            "apply_turn": item.get("apply_turn"),
            "unit": item.get("unit"),
        })
    return {
        "turn": int(decision.get("turn") or 0),
        "player_id": str(decision.get("player_id") or ""),
        "status": record.get("status"),
        "timings": dict(timings or {}),
        "wire_chars": len(wire_text or ""),
        "commands_required_rows": required,
        "commands_given": given,
        "chat_messages": len(chats),
        "dropped": list(dropped or []),
        "last_order_results": last_results[:24],
        "category": record.get("category"),
    }


def write_turn_report(session_dir: Path | None, report: dict[str, Any]) -> Path | None:
    if session_dir is None:
        return None
    turn = int(report.get("turn") or 0)
    path = Path(session_dir) / f"t{turn}_turn_report.json"
    path.write_text(pipeline.canonical_json(report) + "\n", encoding="utf-8")
    return path
