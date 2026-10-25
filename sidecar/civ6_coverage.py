"""Required-unit coverage check and one targeted repair ask (Civ VI).

Every unit row under REQUIRED COMMANDS must leave the sidecar as a bound order.
A row the model omitted, or whose value the binder dropped (illegal attack,
MoveTo onto its own tile, unknown token), used to leave the unit idle; on an AI
seat Lua then finished its moves for two turns, so new units piled up in the
capital. After parsing, this module dry-runs the binder on copies, lists the
uncovered required units with the drop reason and the row's legal options, and
asks the model once for just those keys. Model-first: no host-chosen orders.
CIV6AI_COVERAGE_REPAIR=0 turns it off.
"""
from __future__ import annotations

import copy
import os
import re
from typing import Any

_UNIT_ID_RE = re.compile(r"UNIT_\d+")


def enabled() -> bool:
    return os.environ.get("CIV6AI_COVERAGE_REPAIR", "1").strip().lower() not in ("0", "false", "off", "no")


def is_civ6(snapshot: Any) -> bool:
    return isinstance(snapshot, dict) and str(snapshot.get("schema_version", "")).startswith("civ6ai-input/")


def required_unit_rows(snapshot: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """unit_id -> (wire key, options hint) for every required unit row."""
    from sidecar import civ6_wire
    from sidecar import pipeline_v2 as pipeline

    units = [u for u in snapshot.get("your_units", []) if isinstance(u, dict)]
    by_wire = {wid: uid for uid, wid in pipeline._build_unit_wire_id_map(units).items()}
    out: dict[str, tuple[str, str]] = {}
    for key, hint in civ6_wire._civ6_required_rows(snapshot):
        if not key.endswith(".command"):
            continue
        head = key[: -len(".command")]
        uid = by_wire.get(head, head if head.startswith("UNIT_") else None)
        if uid:
            out[uid] = (key, hint)
    return out


def uncovered(snapshot: dict[str, Any], parsed: dict[str, Any]) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Required rows with no bound order, and the binder's drop note per unit."""
    from sidecar import civ6_command_wire as wire

    required = required_unit_rows(snapshot)
    if not required:
        return {}, {}
    saved = list(wire.LAST_UNRESOLVED)
    try:
        bound = wire.expand_civ6_command_wire(copy.deepcopy(snapshot), copy.deepcopy(parsed))
        notes = list(wire.LAST_UNRESOLVED)
    finally:
        wire.LAST_UNRESOLVED[:] = saved
    covered: set[str] = set()
    for key, value in (bound or {}).items():
        if isinstance(key, str) and key.startswith("cmd.") and isinstance(value, str):
            covered.update(_UNIT_ID_RE.findall(value))
    missing = {uid: row for uid, row in required.items() if uid not in covered}
    reasons: dict[str, str] = {}
    for uid, (key, _hint) in missing.items():
        head = key[: -len(".command")]
        for note in notes:
            if uid in note or f"{head}." in note:
                reasons[uid] = str(note)[:220]
                break
    return missing, reasons


def repair_prompt(missing: dict[str, tuple[str, str]], reasons: dict[str, str]) -> str:
    lines = [
        "Some REQUIRED COMMANDS unit rows have no valid order yet, so those units would sit idle this turn.",
        "Reply with ONE JSON object holding only these keys, one option copied from each row "
        "(Fortify or Skip if the unit should hold):",
    ]
    for uid, (key, hint) in missing.items():
        why = reasons.get(uid) or "no order given"
        lines.append(f'  "{key}": "{hint}"   # {why}')
    return "\n".join(lines)


def merge(parsed: dict[str, Any], repaired: dict[str, Any], missing: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Replace the missing units' keys in the first reply with the repaired ones."""
    from sidecar import civ6_command_wire as wire

    wanted = {key.lower() for key, _ in missing.values()}
    out = {k: v for k, v in parsed.items()
           if not (isinstance(k, str) and wire.strip_row_prefix(k).lower() in wanted)}
    for key, value in (repaired or {}).items():
        if isinstance(key, str) and wire.strip_row_prefix(key).lower() in wanted:
            out[wire.strip_row_prefix(key)] = value
    return out


def repair(snapshot: Any, parsed: dict[str, Any], retry_fn) -> tuple[dict[str, Any], dict[str, Any]]:
    """One targeted ask for uncovered required units. Returns (parsed, stats)."""
    stats: dict[str, Any] = {}
    if not enabled() or retry_fn is None or not is_civ6(snapshot) or not isinstance(parsed, dict):
        return parsed, stats
    try:
        missing, reasons = uncovered(snapshot, parsed)
    except Exception as error:  # never block a turn on the check itself
        return parsed, {"coverage_error": str(error)[:200]}
    stats["coverage_required"] = len(required_unit_rows(snapshot))
    stats["coverage_missing_before"] = len(missing)
    if not missing:
        return parsed, stats
    from sidecar import pipeline_v2 as pipeline

    try:
        repaired = pipeline.parse_model_text(retry_fn(repair_prompt(missing, reasons)))
    except Exception as error:
        stats["coverage_repair_error"] = str(error)[:200]
        return parsed, stats
    merged = merge(parsed, repaired if isinstance(repaired, dict) else {}, missing)
    try:
        still, _ = uncovered(snapshot, merged)
        stats["coverage_missing_after"] = len(still)
    except Exception:
        pass
    stats["coverage_repair"] = True
    return merged, stats
