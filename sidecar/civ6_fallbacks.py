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
from collections import deque
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


def frontier_target(snapshot: dict[str, Any], unit: dict[str, Any]) -> tuple[int, int] | None:
    """Nearest reachable known tile that touches an unrevealed hex."""
    start = legality.plot_xy(unit)
    if start is None:
        return None
    plots = legality.known_plots(snapshot)
    seen = {start}
    q: deque[tuple[tuple[int, int], tuple[int, int] | None]] = deque([(start, None)])
    while q:
        cur, first_step = q.popleft()
        for nx, ny in legality.hex_neighbors(*cur):
            if (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            if (nx, ny) not in plots:
                if cur != start and not legality.is_blacklisted(snapshot, *cur):
                    if legality.tile_passable(snapshot, unit, *cur) is None:
                        return cur
                continue
            if legality.tile_passable(snapshot, unit, nx, ny) is not None:
                continue
            if legality.is_blacklisted(snapshot, nx, ny):
                continue
            step = first_step or (nx, ny)
            if any(n not in plots for n in legality.hex_neighbors(nx, ny)) and (nx, ny) != start:
                return (nx, ny)
            q.append(((nx, ny), step))
    return None


def threatened_cities(snapshot: dict[str, Any]) -> list[tuple[int, int]]:
    cities = []
    for city in _lst(snapshot.get("your_cities")):
        if not isinstance(city, dict):
            continue
        xy = legality.plot_xy(city)
        if xy:
            cities.append(xy)
    combat = _dct(_dct(snapshot.get("civ6")).get("combat"))
    hostiles = []
    for row in _lst(combat.get("hostiles")) + _lst(combat.get("hostile_cities")):
        if isinstance(row, dict):
            try:
                hostiles.append((int(row["x"]), int(row["y"])))
            except (KeyError, TypeError, ValueError):
                continue
    threatened = []
    for cx, cy in cities:
        if any(max(abs(cx - hx), abs(cy - hy)) <= 3 for hx, hy in hostiles):
            threatened.append((cx, cy))
    return threatened


def improve_tile(snapshot: dict[str, Any], unit: dict[str, Any]) -> tuple[int, int] | None:
    here = legality.plot_xy(unit)
    if here is None:
        return None
    me = legality._me(snapshot)
    occupied = legality.own_occupied_plots(snapshot)
    uid = str(unit.get("unit_id") or "")
    rows: list[tuple[int, int, int, bool]] = []
    for xy, plot in legality.known_plots(snapshot).items():
        if plot.get("water") or legality.is_mountain(plot) or plot.get("city_id") or plot.get("improvement_id"):
            continue
        if me and plot.get("revealed_owner_id") != me:
            continue
        holders = [h for h in occupied.get(xy, []) if h != uid]
        if holders:
            continue
        if legality.move_problem(snapshot, uid, xy[0], xy[1]):
            continue
        dist = max(abs(here[0] - xy[0]), abs(here[1] - xy[1]))
        rows.append((dist, xy[0], xy[1], bool(plot.get("resource_id"))))
    rows.sort(key=lambda r: (not r[3], r[0], r[1], r[2]))
    if not rows:
        return None
    return rows[0][1], rows[0][2]


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
    threatened = threatened_cities(snapshot)
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
            out.append(_hint(uid, "explore", frontier_target(snapshot, unit)))
        elif action == "improve":
            target = improve_tile(snapshot, unit)
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
    from sidecar.civ6_priorities import early_lock, early_lock_packets, empty_queue_nudge

    out = []
    packets = early_lock_packets(snapshot) if early_lock(snapshot) else empty_queue_nudge(snapshot, commands)
    for packet in packets:
        args = _dct(packet.get("arguments"))
        out.append({
            "command_id": f"HINT_priority_{args.get('priority_id')}_{args.get('priority_level')}",
            "kind": KIND,
            "arguments": {"role": "priority", "role_code": ROLE_CODES["priority"],
                          "priority_id": args.get("priority_id"), "priority_level": args.get("priority_level")},
            "source": "fallback",
        })
    return out


def is_local_seat(snapshot: dict[str, Any]) -> bool:
    """The local client seat applies through the UI path, which has no fallback pass."""
    from sidecar.civ6_governance import governance

    return _dct(governance(snapshot).get("routes")).get("mode") == "local_player"


def plan(snapshot: dict[str, Any], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every fallback hint for this batch (empty when the ledger is switched off)."""
    if not enabled() or is_local_seat(snapshot):
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
