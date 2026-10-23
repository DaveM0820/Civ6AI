"""Host fallback targets: the sidecar proposes, Gameplay Lua decides.

One hint per unit with a role (and settlers), plus empty-production priority
packets, sent in the same synced batch as the model's orders (kind
``fallback_hint``). Civ6Ai_Orders._RunHostFallbacks uses a hint only for an
entity no successful model order handled, so a fallback never overrides the
model. Hints go to every role unit, not only unordered ones: a model order that
the sidecar drops, or that fails in the game, still leaves its unit a target.

CIV6AI_FALLBACK_LEDGER=0 is a kill switch: no hints are sent, and the Lua pass
keeps only its own rows (combat, goals, explore).
"""
from __future__ import annotations

import os
from typing import Any

from sidecar import civ6_legality as legality
from sidecar.civ6_common import dct as _dct
from sidecar.civ6_common import lst as _lst

KIND = "fallback_hint"
# Lua Civ6Ai_Orders.HINT_ROLE
ROLE_CODES = {"explore": 1, "improve": 2, "defend": 3, "settle": 4, "priority": 9}


def enabled() -> bool:
    return os.environ.get("CIV6AI_FALLBACK_LEDGER", "1").strip().lower() not in ("0", "false", "off", "no")


def _hint(uid: str, role: str, target: tuple[int, int] | None) -> dict[str, Any]:
    args: dict[str, Any] = {"unit_id": uid, "role": role, "role_code": ROLE_CODES[role]}
    if target is not None:
        args["target_x"], args["target_y"] = int(target[0]), int(target[1])
    return {"command_id": f"HINT_{role}_{uid}", "kind": KIND, "arguments": args, "source": "fallback"}


def _settle_target(snapshot: dict[str, Any], unit: dict[str, Any]) -> tuple[int, int] | None:
    """Found here when legal, otherwise the nearest listed legal site."""
    from sidecar.civ6_command_wire import site_obeys_founding_rules

    settle = _dct(unit.get("settle"))
    if settle.get("here_ok") is True:
        return legality.plot_xy(unit)
    best: tuple[int, int, int] | None = None
    for site in _lst(settle.get("sites")):
        try:
            x, y = int(site["x"]), int(site["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not site_obeys_founding_rules(snapshot, x, y):
            continue
        try:
            dist = int(site.get("dist"))
        except (TypeError, ValueError):
            dist = 99
        if best is None or (dist, x, y) < best:
            best = (dist, x, y)
    return (best[1], best[2]) if best else None


def unit_hints(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    threatened = legality._threatened_cities(snapshot)
    for unit in _lst(snapshot.get("your_units")):
        if not isinstance(unit, dict) or not unit.get("unit_id"):
            continue
        uid = str(unit["unit_id"])
        if str(unit.get("unit_type_id") or "").endswith("SETTLER"):
            target = _settle_target(snapshot, unit)
            if target is not None:
                out.append(_hint(uid, "settle", target))
            continue
        action = legality.ROLE_DEFAULTS.get(legality.unit_role(unit) or "")
        if action == "explore":
            out.append(_hint(uid, "explore", legality.frontier_target(snapshot, unit)))
        elif action == "improve":
            target = legality._improve_tile(snapshot, unit)
            if target is not None:
                out.append(_hint(uid, "improve", target))
        elif action == "defend":
            here = legality.plot_xy(unit)
            target = None
            if threatened and here is not None:
                dest = min(threatened, key=lambda xy: max(abs(here[0] - xy[0]), abs(here[1] - xy[1])))
                if here != dest and legality.move_problem(snapshot, uid, dest[0], dest[1]) is None:
                    target = dest
            out.append(_hint(uid, "defend", target))
    return out


def priority_hints(snapshot: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Empty production: the priority packets the engine fills queues from."""
    from sidecar.civ6_priorities import empty_queue_nudge

    out = []
    for packet in empty_queue_nudge(snapshot, commands):
        args = _dct(packet.get("arguments"))
        out.append({
            "command_id": f"HINT_priority_{args.get('priority_id')}_{args.get('priority_level')}",
            "kind": KIND,
            "arguments": {"role": "priority", "role_code": ROLE_CODES["priority"],
                          "priority_id": args.get("priority_id"), "priority_level": args.get("priority_level")},
            "source": "fallback",
        })
    return out


def plan(snapshot: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every fallback hint for this batch (empty when the ledger is switched off)."""
    if not enabled():
        return []
    return unit_hints(snapshot) + priority_hints(snapshot, commands)


def ledger(rows: list[dict[str, Any]] | None) -> dict[str, str]:
    """Entity -> who acted this turn, from apply results: model, fallback or model_failed."""
    out: dict[str, str] = {}
    rank = {"model": 3, "fallback": 2, "model_failed": 1}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("kind") == KIND:
            continue
        fixed = _dct(row.get("fixed_arguments")) or _dct(row.get("arguments"))
        if fixed.get("unit_id") not in (None, ""):
            entity = f"unit:{fixed['unit_id']}"
        elif fixed.get("city_id") not in (None, ""):
            entity = f"city:{fixed['city_id']}"
        else:
            continue
        source = "fallback" if row.get("source") == "fallback" or str(row.get("command_id") or "").startswith("AUTO_") else "model"
        state = source if row.get("ok") is True else ("model_failed" if source == "model" else None)
        if state and rank[state] > rank.get(out.get(entity, ""), 0):
            out[entity] = state
    return out
