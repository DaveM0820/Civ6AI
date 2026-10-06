"""Last turn's order results for a Civ VI seat, fed back into its prompt.

The in-game Lua cannot write files, so it prints ``CIV6AI|jsonl|{apply_result}``
lines into Lua.log; the host bridge copies them into
``sessions/<id>/PLAYER_N/apply-results.jsonl``. This module reads that file,
keeps the most recent applied turn, turns the raw reason codes into plain words
and stores the rows as ``history.command_results`` (schema history_item) so the
wire can print ``apply.last.N`` rows and ATTENTION "Blocked" lines (Civ5 parity).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sidecar import pipeline_v2 as pipeline

APPLY_RESULTS_NAME = "apply-results.jsonl"
KIND_OK = "APPLY_OK"
KIND_FAILED = "APPLY_FAILED"
KIND_NO_EFFECT = "APPLY_NO_EFFECT"
KIND_DROPPED = "APPLY_DROPPED"
# Failed moves/attacks from the few turns before the latest one: listed so the
# model does not bounce back to a destination that failed two turns ago.
KIND_FAILED_EARLIER = "APPLY_FAILED_EARLIER"
EARLIER_LOOKBACK_TURNS = 5
# Results older than this many turns are stale (seat skipped / fell back).
MAX_AGE_TURNS = 2
MAX_ROWS = 24
PRIOR_APPLY_WIRE_CAP = 12
NO_EFFECT_REASONS = frozenset({"already_there", "plot_unchanged"})
NON_TRANSIENT_FAILURES = (
    "no_path",
    "illegal_move",
    "cannot_build",
    "already_known",
    "stale",
    "tech_already_known",
    "civic_already_known",
    "stale_unit_id",
    "stale_city_id",
    "unit_not_found",
    "plot_occupied_exhausted",
    "site_no_longer_legal",
)
CHAT_NEAR_DUPE_THRESHOLD = 0.9
CHAT_NEAR_DUPE_LOOKBACK_TURNS = 3

_PATH_RE = re.compile(
    r"^(?P<partial>partial_)?path:(?P<fx>-?\d+),(?P<fy>-?\d+)>(?P<tx>-?\d+),(?P<ty>-?\d+)"
    r":steps=(?P<steps>\d+):len=(?P<len>\d+):stop=(?P<stop>.*)$"
)
_INSUFFICIENT_RE = re.compile(r"^insufficient_moves:(?P<cost>-?[\d.]+)>(?P<moves>-?[\d.]+)$")
_PARTIAL_MOVE_RE = re.compile(r"^partial_move_to_(?P<x>-?\d+)_(?P<y>-?\d+)$")
_RETARGET_RE = re.compile(
    r"^retargeted:(?P<ox>-?\d+),(?P<oy>-?\d+)>(?P<nx>-?\d+),(?P<ny>-?\d+)$"
)

_SIMPLE_REASONS = {
    "no_path": "the game found no route to that tile (water, mountains, or closed borders in the way)",
    "water": "that tile is water and this unit cannot embark there yet",
    "water_no_ocean_embark": "that tile is ocean and this unit cannot embark onto ocean yet",
    "land": "naval units cannot enter land tiles",
    "impassable": "that tile is impassable (mountain or natural wonder)",
    "occupied_foreign": "another civilization's unit is standing on that tile",
    "stack_limit": "one of your own military units already holds that tile (one military unit per tile)",
    "not_adjacent": "the tile is not next to the unit",
    "no_moves_left": "the unit had no movement left",
    "unit_not_found": "that unit no longer exists",
    "no_units": "that unit no longer exists",
    "plot_not_found": "that tile is off the map",
    "step_refused": "the game refused the next step of the route",
    "first_step_refused": "the game refused the step onto that rough tile",
    "bad_path_plot": "the route ran off the map",
    "script_move_no_progress": "the game did not move the unit",
    "script_move_rejected": "the game rejected the move",
    "move_unavailable": "the game rejected the move",
    "operation_illegal": "the game says that order is not legal for this unit now",
    "operation_rejected": "the game rejected the order",
    "already_there": "the unit was already on that tile",
    "arrived": "arrived",
    "tech_already_known": "that technology is already researched",
    "civic_already_known": "that civic is already known",
    "invalid_tech": "that technology cannot be researched now",
    "invalid_civic": "that civic cannot be studied now",
    "research_rejected": "the game rejected that research choice",
    "civic_rejected": "the game rejected that civic choice",
    "production_requires_local_player": "the host cannot change this seat's city production yet; the city keeps its current build",
    "attack_requires_local_player": "the host cannot issue attacks for this seat yet",
    "attack_rejected": "the game rejected the attack (target out of reach or no longer there)",
    "attack_op_missing": "the game has no attack order for this unit",
    "found_city_rejected": "a city cannot be founded on that tile (too close to another city, or bad terrain)",
    "fortify_rejected": "the unit cannot fortify now",
    "unsupported_kind": "the host does not support that order yet",
    "missing_unit_or_target": "the order had no unit or target",
    "local_player_swap_blocked_mp": "the host could not act for this seat in multiplayer",
    "stale_unit_id": "that unit no longer exists (stale id)",
    "stale_city_id": "that city no longer exists (stale id)",
    "self_target_hold": "the destination was this unit's own tile, so it held",
    "plot_occupied_exhausted": "the destination stayed occupied after retries, and no neighbour was free",
    "ok_superseded": "the chosen research/civic was already done, so a fallback was used",
    "ok_already_researching": "that technology or civic was already in progress",
    "site_no_longer_legal": "that tile is no longer a legal city site",
    "trade_unavailable": "the game has no trade-route operation for this unit",
    "explore_unavailable": "the game has no explore operation for this unit",
    "activate_unavailable": "the game could not activate that great person",
}


def describe_reason(reason: Any) -> str:
    """Plain-words explanation of a raw apply reason code ('' when there is nothing to say)."""
    text = str(reason or "").strip()
    if not text:
        return ""
    if text.startswith("illegal_move:"):
        return describe_reason(text[len("illegal_move:"):])
    match = _INSUFFICIENT_RE.match(text)
    if match:
        return (f"not enough movement left to enter that tile (needs {match.group('cost')}, "
                f"has {match.group('moves')}; hills, forest, marsh and river crossings cost extra; "
                "only a unit that has not moved this turn may enter a tile costing more than its moves)")
    match = _PATH_RE.match(text)
    if match:
        stop = describe_reason(match.group("stop"))
        steps = int(match.group("steps"))
        here = f"({match.group('tx')},{match.group('ty')})"
        route = int(match.group("len"))
        if match.group("stop") == "arrived":
            return f"arrived at {here}"
        if steps <= 0:
            return f"could not take the first step of the {route}-tile route — {stop}; the unit stayed at {here}"
        return f"moved {steps} of {route} steps, now at {here}; the next step failed: {stop}"
    match = _PARTIAL_MOVE_RE.match(text)
    if match:
        return f"moved partway, now at ({match.group('x')},{match.group('y')})"
    match = _RETARGET_RE.match(text)
    if match:
        return (f"destination ({match.group('ox')},{match.group('oy')}) was occupied; "
                f"moved toward ({match.group('nx')},{match.group('ny')}) instead")
    if text.startswith("retargeted:"):
        return "destination occupied; the game picked a free neighbouring tile"
    if text.startswith("gamecore_error:") or text.startswith("move_unit_error:"):
        return "the game raised a script error on that order"
    if text.startswith("gamecore_unavailable:"):
        return "the game-side order script was unavailable"
    if text in _SIMPLE_REASONS:
        return _SIMPLE_REASONS[text]
    return text.replace("_", " ")


def load_apply_results(session_dir: Path | None) -> list[dict[str, Any]]:
    if session_dir is None:
        return []
    path = Path(session_dir) / APPLY_RESULTS_NAME
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event", "apply_result") == "apply_result":
            rows.append(row)
    return rows


def _row_decision_turn(row: dict[str, Any]) -> int | None:
    for key in ("decision_turn", "turn"):
        try:
            return int(row.get(key))
        except (TypeError, ValueError):
            continue
    return None


def latest_turn_rows(rows: list[dict[str, Any]], player_id: str, current_turn: int) -> tuple[int | None, list[dict[str, Any]]]:
    """Rows of the most recent applied decision before current_turn (deduped, file order)."""
    mine: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        pid = row.get("player_id")
        if pid not in (None, "") and str(pid) != player_id:
            continue
        turn = _row_decision_turn(row)
        if turn is None:
            continue
        if turn >= current_turn or turn < current_turn - MAX_AGE_TURNS:
            continue
        mine.append((turn, row))
    if not mine:
        return None, []
    last = max(turn for turn, _ in mine)
    seen: set[str] = set()
    picked: list[dict[str, Any]] = []
    for turn, row in mine:
        if turn != last:
            continue
        key = str(row.get("command_id") or len(picked))
        if key in seen:
            continue
        seen.add(key)
        picked.append(row)
    return last, picked[:MAX_ROWS]


def _coords(fixed: dict[str, Any]) -> str | None:
    x, y = fixed.get("target_x"), fixed.get("target_y")
    if isinstance(x, int) and isinstance(y, int):
        return f"({x},{y})"
    return None


def _readable(value: Any, prefix: str) -> str:
    text = str(value or "")
    if text.startswith(prefix):
        text = text[len(prefix):]
    return text.replace("_", " ").title()


def _order_label(row: dict[str, Any], wire_ids: dict[str, str], city_names: dict[str, str]) -> tuple[str, str]:
    """(actor, order) e.g. ('warrior_1', 'MoveTo(6,10)')."""
    kind = str(row.get("kind") or "")
    fixed = row.get("fixed_arguments") if isinstance(row.get("fixed_arguments"), dict) else {}
    if not fixed:
        unit_raw = str(row.get("unit") or "")
        actor = wire_ids.get(unit_raw) or (unit_raw.lower() if unit_raw else "")
        coords = None
        if isinstance(row.get("x"), int) and isinstance(row.get("y"), int):
            coords = f"({row['x']},{row['y']})"
        kind_l = kind.lower()
        if kind_l in ("move_unit", "move", "moveto"):
            return actor, f"MoveTo{coords or '(?,?)'}"
        if kind_l in ("found_city", "found"):
            return actor, "FoundCity"
        if actor:
            return actor, kind or "command"
        # empty fixed still continues into kind-specific jsonl labels below
        fixed = {}
    unit_id = str(fixed.get("unit_id") or "")
    actor = wire_ids.get(unit_id) or (unit_id.lower() if unit_id else "")
    coords = _coords(fixed) or "(?,?)"
    if kind == "move_unit":
        return actor, f"MoveTo{coords}"
    if kind == "attack_target":
        return actor, f"AttackTo{coords}"
    if kind == "found_city":
        return actor, "FoundCity"
    if kind == "unit_posture_fortify":
        return actor, "Fortify"
    if kind == "unit_skip":
        return actor, "Skip"
    if kind == "queue_production":
        city = str(fixed.get("city_id") or "")
        return f"{city_names.get(city, city or 'city')}.production", str(fixed.get("build_id") or "?")
    if kind == "set_research_tech":
        return "legal.research.tech", str(fixed.get("tech_id") or "?")
    if kind == "set_research_civic":
        return "legal.research.civic", str(fixed.get("civic_id") or "?")
    from sidecar import civ6_governance

    if kind in civ6_governance.ORDER_LABELS:
        label, field = civ6_governance.ORDER_LABELS[kind]
        return label, str(fixed.get(field) or "?")
    from sidecar import civ6_diplomacy

    if kind in civ6_diplomacy.ORDER_LABELS:
        label, field = civ6_diplomacy.ORDER_LABELS[kind]
        return label, str(fixed.get(field) or "?")
    if kind == "purchase_item":
        city = str(fixed.get("city_id") or "")
        return f"{city_names.get(city, city or 'city')}.purchase", str(fixed.get("item_id") or "?")
    if kind == "purchase_tile":
        city = str(fixed.get("city_id") or "")
        return f"{city_names.get(city, city or 'city')}.buyTile", _coords(fixed) or "tile"
    if kind == "worker_improve":
        return actor or "builder", str(fixed.get("improvement_id") or "improve")
    if kind == "trade_route":
        return actor or "trader", f"TradeRoute({fixed.get('city_id') or fixed.get('dest_city_id') or '?'})"
    if kind == "explore":
        return actor or "scout", "Explore"
    if kind == "activate_great_person":
        return actor or "greatperson", "Activate"
    return actor or "order", kind or "command"


def _success_text(row: dict[str, Any]) -> str:
    kind = str(row.get("kind") or "")
    fixed = row.get("fixed_arguments") if isinstance(row.get("fixed_arguments"), dict) else {}
    reason = str(row.get("reason") or "")
    detail = describe_reason(reason)
    if kind == "move_unit":
        path = _PATH_RE.match(reason)
        arrived = path is not None and path.group("stop") == "arrived" and not path.group("partial")
        if reason in NO_EFFECT_REASONS:
            return f"no effect — already on {_coords(fixed) or 'that tile'}"
        if reason == "self_target_hold":
            return "ok — held on this tile (MoveTo was the unit's own plot)"
        if reason.startswith("retargeted:"):
            return f"ok — retargeted; {detail}"
        if not reason or arrived:
            return f"ok — moved to {_coords(fixed) or 'the target'}"
        if reason.startswith("first_step:"):
            return f"ok — moved to {_coords(fixed) or 'the target'} (rough tile: it used all its movement)"
        return f"ok (partial) — {detail}; reissue or pick a new destination"
    if kind == "attack_target":
        return "ok — attack made" + (f" ({detail})" if detail else "")
    if kind == "found_city":
        return "ok — city founded"
    if kind == "set_research_tech":
        if reason == "ok_superseded":
            return f"ok — first choice already known; researching {_readable(fixed.get('tech_id'), 'TECH_')}"
        if reason == "ok_already_researching":
            return "ok — already researching that technology"
        return f"ok — researching {_readable(fixed.get('tech_id'), 'TECH_')}"
    if kind == "set_research_civic":
        if reason == "ok_superseded":
            return f"ok — first choice already known; studying {_readable(fixed.get('civic_id'), 'CIVIC_')}"
        if reason == "ok_already_researching":
            return "ok — already studying that civic"
        return f"ok — studying {_readable(fixed.get('civic_id'), 'CIVIC_')}"
    if kind == "queue_production":
        return f"ok — now building {fixed.get('build_id') or 'it'}"
    from sidecar import civ6_governance

    gov_text = civ6_governance.success_text(kind, fixed)
    if gov_text:
        return gov_text
    from sidecar import civ6_diplomacy

    diplo_text = civ6_diplomacy.success_text(kind, fixed)
    if diplo_text:
        return diplo_text
    if kind == "purchase_item":
        return f"ok — bought {fixed.get('item_id') or 'item'}"
    if kind == "purchase_tile":
        return "ok — tile purchased"
    if kind == "worker_improve":
        return f"ok — built {fixed.get('improvement_id') or 'improvement'}"
    return "ok" + (f" ({detail})" if detail and not detail.startswith("finish moves") else "")


def build_command_results(snapshot: dict[str, Any], rows: list[dict[str, Any]], turn: int) -> list[dict[str, Any]]:
    units = [u for u in snapshot.get("your_units", []) if isinstance(u, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    city_names = {
        str(c.get("city_id")): pipeline._city_prompt_name(c)
        for c in snapshot.get("your_cities", []) if isinstance(c, dict)
    }
    items: list[dict[str, Any]] = []
    for row in rows:
        actor, order = _order_label(row, wire_ids, city_names)
        reason = str(row.get("reason") or "")
        ok = row.get("ok") is True or reason.startswith("ok_") or reason.startswith("retargeted:") or reason == "self_target_hold"
        no_effect = reason in NO_EFFECT_REASONS
        if no_effect:
            outcome = _success_text(row)
            wire_kind = KIND_NO_EFFECT
        elif ok:
            outcome = _success_text(row)
            wire_kind = KIND_OK
        else:
            outcome = "FAILED — " + (describe_reason(reason) or "the game rejected it")
            wire_kind = KIND_FAILED
        summary = f"{actor} {order}: {outcome}" if actor else f"{order}: {outcome}"
        affected: list[str] = []
        for value in (
            row.get("command_id"),
            (row.get("fixed_arguments") or {}).get("unit_id") if isinstance(row.get("fixed_arguments"), dict) else None,
            row.get("unit"),
        ):
            text = str(value or "").strip()[:128]
            if text and text not in affected:
                affected.append(text)
        decision_turn = _row_decision_turn(row)
        apply_turn = row.get("apply_turn")
        try:
            apply_turn_i = int(apply_turn) if apply_turn is not None else None
        except (TypeError, ValueError):
            apply_turn_i = None
        items.append({
            "turn": max(0, int(decision_turn if decision_turn is not None else turn)),
            "apply_turn": apply_turn_i,
            "kind": wire_kind,
            "summary": summary[:300],
            "affected_ids": affected,
            "reason": reason,
            "order_kind": str(row.get("kind") or ""),
            "unit": actor,
        })
    return items


def _target_key(row: dict[str, Any]) -> tuple[str, str, Any, Any] | None:
    fixed = row.get("fixed_arguments") if isinstance(row.get("fixed_arguments"), dict) else {}
    if row.get("kind") not in ("move_unit", "attack_target"):
        return None
    return (str(row.get("kind")), str(fixed.get("unit_id") or ""), fixed.get("target_x"), fixed.get("target_y"))


def _earlier_failed_items(snapshot: dict[str, Any], rows: list[dict[str, Any]], player_id: str,
                          latest: int, latest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Failed moves/attacks of the turns before `latest` whose unit+target was not retried in `latest`."""
    skip = {_target_key(r) for r in latest_rows}
    newest: dict[tuple[str, str, Any, Any], dict[str, Any]] = {}
    for row in rows:
        if str(row.get("player_id") or "") != player_id or row.get("ok") is True:
            continue
        try:
            turn = int(row.get("turn"))
        except (TypeError, ValueError):
            continue
        key = _target_key(row)
        if key is None or key in skip or not (latest - EARLIER_LOOKBACK_TURNS <= turn < latest):
            continue
        if key not in newest or turn >= int(newest[key]["turn"]):
            newest[key] = row
    ordered = sorted(newest.values(), key=lambda r: int(r["turn"]), reverse=True)[:6]
    items: list[dict[str, Any]] = []
    for row in ordered:
        item = build_command_results(snapshot, [row], int(row["turn"]))[0]
        item["kind"] = KIND_FAILED_EARLIER
        items.append(item)
    return items


def _native_snapshot_rows(existing: Any, current_turn: int) -> list[dict[str, Any]]:
    """WP-B history.command_results: {decision_turn, apply_turn, unit, kind, ok, reason, effect}."""
    if not isinstance(existing, list):
        return []
    native: list[dict[str, Any]] = []
    for row in existing:
        if not isinstance(row, dict):
            continue
        if row.get("kind") in (KIND_OK, KIND_FAILED, KIND_NO_EFFECT, KIND_DROPPED, KIND_FAILED_EARLIER):
            continue
        if "decision_turn" not in row and "apply_turn" not in row:
            continue
        native.append(row)
    if not native:
        return []
    turn, picked = latest_turn_rows(native, "", current_turn)
    return picked if turn is not None else native[-MAX_ROWS:]


def inject_command_results(snapshot: dict[str, Any], session_dir: Path | None) -> int:
    """Fill history.command_results from snapshot (WP-B) or apply-results.jsonl. Returns rows kept."""
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    player_id = str(decision.get("player_id") or "")
    try:
        current_turn = int(decision.get("turn"))
    except (TypeError, ValueError):
        return 0
    history = snapshot.setdefault("history", {})
    if not isinstance(history, dict):
        return 0
    existing = history.get("command_results")
    native = _native_snapshot_rows(existing, current_turn)
    if native:
        items = build_command_results(snapshot, native, _row_decision_turn(native[0]) or current_turn - 1)
        history["command_results"] = items[:PRIOR_APPLY_WIRE_CAP]
        return len(items)
    all_rows = load_apply_results(session_dir)
    turn, rows = latest_turn_rows(all_rows, player_id, current_turn)
    if turn is None or not rows:
        if isinstance(existing, list):
            return len([i for i in existing if isinstance(i, dict)])
        return 0
    items = build_command_results(snapshot, rows, turn)
    items.extend(_earlier_failed_items(snapshot, all_rows, player_id, turn, rows))
    history["command_results"] = items[:PRIOR_APPLY_WIRE_CAP]
    return len(items)


# --- wire helpers ---------------------------------------------------------

_BLOCKED_RE = re.compile(
    r"^(?P<actor>\S+) (?P<order>MoveTo|AttackTo)\((?P<x>-?\d+),(?P<y>-?\d+)\): FAILED — (?P<why>.*)$"
)


def command_result_items(context: dict[str, Any]) -> list[dict[str, Any]]:
    history = context.get("history") if isinstance(context, dict) else None
    items = history.get("command_results") if isinstance(history, dict) else None
    return [i for i in (items or []) if isinstance(i, dict) and str(i.get("summary") or "").strip()]


def thoughts_lines(context: dict[str, Any]) -> list[str]:
    items = [
        i for i in command_result_items(context)
        if i.get("kind") in (KIND_OK, KIND_FAILED, KIND_NO_EFFECT, KIND_DROPPED)
    ]
    dropped = dropped_lines(context)
    if not items and not dropped:
        return []
    lines: list[str] = []
    result_items = [i for i in items if i.get("kind") != KIND_DROPPED]
    if result_items:
        turn = max(int(i.get("turn") or 0) for i in result_items)
        apply_turns = [int(i["apply_turn"]) for i in result_items if isinstance(i.get("apply_turn"), int)]
        apply_turn = max(apply_turns) if apply_turns else None
        failed = sum(1 for i in result_items if i.get("kind") == KIND_FAILED)
        noop = sum(1 for i in result_items if i.get("kind") == KIND_NO_EFFECT)
        ok = sum(1 for i in result_items if i.get("kind") == KIND_OK)
        label = f"Your T{turn} orders"
        if apply_turn is not None and apply_turn != turn:
            label += f" (applied T{apply_turn})"
        bits = [f"{ok} ok", f"{failed} failed"]
        if noop:
            bits.append(f"{noop} no effect")
        lines.append(pipeline._wire_line("prior.turn", f"{label}: {', '.join(bits)}"))
        for index, item in enumerate(result_items):
            lines.append(pipeline._wire_line(f"apply.last.{index}", str(item["summary"]).strip()))
    for index, note in enumerate(dropped):
        lines.append(pipeline._wire_line(f"dropped.{index}", note))
    return lines


def _unit_position(context: dict[str, Any], actor: str) -> tuple[str | None, int | None]:
    units = [u for u in context.get("your_units", []) if isinstance(u, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    for unit in units:
        if wire_ids.get(str(unit.get("unit_id"))) != actor:
            continue
        plot = str(unit.get("plot_id") or "")
        match = re.match(r"^PLOT_(-?\d+)_(-?\d+)$", plot)
        pos = f"({match.group(1)},{match.group(2)})" if match else None
        movement = unit.get("movement") if isinstance(unit.get("movement"), dict) else {}
        moves = movement.get("current") if isinstance(movement.get("current"), int) else None
        return pos, moves
    return None, None


def _unit_max_moves(context: dict[str, Any], actor: str) -> int | None:
    units = [u for u in context.get("your_units", []) if isinstance(u, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    for unit in units:
        if wire_ids.get(str(unit.get("unit_id"))) == actor:
            movement = unit.get("movement") if isinstance(unit.get("movement"), dict) else {}
            value = movement.get("maximum")
            return value if isinstance(value, int) else None
    return None


_NEEDS_RE = re.compile(r"needs (?P<cost>\d+), has (?P<has>\d+)")


def blocked_attention_lines(context: dict[str, Any]) -> list[str]:
    """One ATTENTION line per failed move/attack of last turn."""
    lines: list[str] = []
    for item in command_result_items(context):
        if item.get("kind") != KIND_FAILED:
            continue
        match = _BLOCKED_RE.match(str(item["summary"]).strip())
        if not match:
            continue
        actor, order = match.group("actor"), match.group("order")
        target = f"({match.group('x')},{match.group('y')})"
        pos, moves = _unit_position(context, actor)
        where = ""
        if pos:
            where = f" It is now at {pos}" + (f" with {moves} moves." if moves is not None else ".")
        needs = _NEEDS_RE.search(match.group("why"))
        full = _unit_max_moves(context, actor)
        if needs and full is not None and int(needs.group("cost")) > int(needs.group("has")):
            where += (f" A unit at full movement ({full}) can always enter one adjacent tile, however rough "
                      f"(it spends all its movement): start a turn next to the {needs.group('cost')}-move tile "
                      "and make it the first step, or route around it.")
        if order == "MoveTo":
            advice = (f"Do not repeat MoveTo{target} — pick a different destination: a nearer open tile it can "
                      "afford this turn, or a route around the rough terrain/water.")
        else:
            advice = (f"Do not repeat AttackTo{target} — only attack targets listed on the unit's row this turn; "
                      "otherwise move to a better position first.")
        lines.append(f"Blocked: {actor} {order}{target} failed last turn — {match.group('why')}.{where} {advice}")
    earlier: list[str] = []
    for item in command_result_items(context):
        if item.get("kind") != KIND_FAILED_EARLIER:
            continue
        match = _BLOCKED_RE.match(str(item["summary"]).strip())
        if match:
            earlier.append(f"{match.group('actor')} {match.group('order')}({match.group('x')},{match.group('y')}) "
                           f"on T{int(item.get('turn') or 0)} ({match.group('why').split(';')[0]})")
    if earlier and lines:  # only alongside a fresh failure; keeps Event.Blocked.log meaningful
        lines.append("Blocked earlier (also avoid these destinations unless the situation changed): "
                     + "; ".join(earlier) + ".")
    return lines


def dropped_lines(context: dict[str, Any]) -> list[str]:
    history = context.get("history") if isinstance(context, dict) else None
    raw = history.get("dropped_orders") if isinstance(history, dict) else None
    notes: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                notes.append(item.strip())
            elif isinstance(item, dict) and str(item.get("summary") or "").strip():
                notes.append(str(item["summary"]).strip())
    for item in command_result_items(context):
        if item.get("kind") == KIND_DROPPED:
            notes.append(str(item["summary"]).strip())
    seen: set[str] = set()
    out: list[str] = []
    for note in notes:
        if note not in seen:
            seen.add(note)
            out.append(note)
    return out[:12]


def record_dropped(snapshot: dict[str, Any], notes: list[str]) -> None:
    history = snapshot.setdefault("history", {})
    if not isinstance(history, dict):
        return
    existing = history.get("dropped_orders")
    merged = list(existing) if isinstance(existing, list) else []
    for note in notes:
        text = str(note).strip()
        if text and text not in merged:
            merged.append(text)
    history["dropped_orders"] = merged[:24]


def token_jaccard(left: str, right: str) -> float:
    ta = set(re.findall(r"[a-z0-9]+", (left or "").lower()))
    tb = set(re.findall(r"[a-z0-9]+", (right or "").lower()))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _reason_is_non_transient(reason: str) -> bool:
    text = (reason or "").lower()
    return any(token in text for token in NON_TRANSIENT_FAILURES)


def _command_fingerprint(command: dict[str, Any]) -> tuple[str, str, Any, Any]:
    args = command.get("arguments") if isinstance(command.get("arguments"), dict) else {}
    return (
        str(command.get("kind") or ""),
        str(args.get("unit_id") or command.get("unit") or ""),
        args.get("target_x", args.get("x")),
        args.get("target_y", args.get("y")),
    )


def _result_fingerprint(item: dict[str, Any]) -> tuple[str, str, Any, Any] | None:
    if item.get("kind") not in (KIND_FAILED, KIND_FAILED_EARLIER):
        return None
    reason = str(item.get("reason") or item.get("summary") or "")
    if not _reason_is_non_transient(reason):
        return None
    order_kind = str(item.get("order_kind") or "")
    unit = str(item.get("unit") or "")
    match = _BLOCKED_RE.match(str(item.get("summary") or "").strip())
    if match:
        return (
            "move_unit" if match.group("order") == "MoveTo" else "attack_target",
            match.group("actor"),
            int(match.group("x")),
            int(match.group("y")),
        )
    return (order_kind, unit, None, None)


def filter_repeat_failures(snapshot: dict[str, Any], commands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop orders that replay a non-transient failure from the last two decisions."""
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    fails: list[tuple[tuple[str, str, Any, Any], int, str]] = []
    for item in command_result_items(snapshot):
        fp = _result_fingerprint(item)
        if fp is None:
            continue
        fails.append((fp, int(item.get("turn") or 0), str(item.get("reason") or "failure")))
    units = [u for u in snapshot.get("your_units", []) if isinstance(u, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    reverse = {v: k for k, v in wire_ids.items()}
    for command in commands:
        fp = _command_fingerprint(command)
        matched = None
        for fail_fp, fail_turn, fail_reason in fails:
            same_kind = fail_fp[0] == fp[0] or (fail_fp[0] in ("move_unit", "attack_target") and fp[0] == fail_fp[0])
            unit_a = fail_fp[1]
            unit_b = fp[1]
            unit_ok = unit_a == unit_b or wire_ids.get(unit_b) == unit_a or reverse.get(unit_a) == unit_b
            target_ok = fail_fp[2] == fp[2] and fail_fp[3] == fp[3]
            if same_kind and unit_ok and target_ok:
                matched = (fail_turn, fail_reason)
                break
        if matched is not None:
            dropped.append(
                f"dropped: repeat of T{matched[0]} failure ({matched[1].split(':')[0] or 'non-transient'})"
            )
            continue
        kept.append(command)
    return kept, dropped


def recent_self_public_chats(snapshot: dict[str, Any], lookback: int = CHAT_NEAR_DUPE_LOOKBACK_TURNS) -> list[str]:
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    self_id = str(decision.get("player_id") or "")
    try:
        current_turn = int(decision.get("turn") or 0)
    except (TypeError, ValueError):
        current_turn = 0
    history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
    lines: list[str] = []
    for event in history.get("public_events", []) or []:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "").upper()
        if kind and kind != "CHAT_PUBLIC":
            continue
        affected = event.get("affected_ids", [])
        sender = str(affected[0]) if isinstance(affected, list) and affected else ""
        if sender != self_id:
            continue
        try:
            turn = int(event.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if current_turn - lookback <= turn < current_turn or (current_turn == 0):
            text = str(event.get("text") or event.get("summary") or "").strip()
            if text:
                lines.append(text)
    return lines


def is_near_duplicate_chat(text: str, recent: list[str], threshold: float = CHAT_NEAR_DUPE_THRESHOLD) -> bool:
    from difflib import SequenceMatcher

    needle = (text or "").strip()
    if not needle:
        return False
    for prior in recent:
        ratio = SequenceMatcher(None, needle.lower(), prior.lower()).ratio()
        if max(ratio, token_jaccard(needle, prior)) >= threshold:
            return True
    return False


def filter_repeat_public_chat(
    snapshot: dict[str, Any],
    chat_messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    recent = recent_self_public_chats(snapshot)
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for message in chat_messages:
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "")
        if message.get("target") == "all" and is_near_duplicate_chat(text, recent):
            dropped.append(
                "dropped: public chat was a near-repeat of your own recent line and was not sent"
            )
            continue
        kept.append(message)
        if message.get("target") == "all" and text.strip():
            recent.append(text)
    return kept, dropped

