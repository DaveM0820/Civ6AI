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
# Failed moves/attacks from the few turns before the latest one: listed so the
# model does not bounce back to a destination that failed two turns ago.
KIND_FAILED_EARLIER = "APPLY_FAILED_EARLIER"
EARLIER_LOOKBACK_TURNS = 5
# Results older than this many turns are stale (seat skipped / fell back).
MAX_AGE_TURNS = 2
MAX_ROWS = 24

_PATH_RE = re.compile(
    r"^(?P<partial>partial_)?path:(?P<fx>-?\d+),(?P<fy>-?\d+)>(?P<tx>-?\d+),(?P<ty>-?\d+)"
    r":steps=(?P<steps>\d+):len=(?P<len>\d+):stop=(?P<stop>.*)$"
)
_INSUFFICIENT_RE = re.compile(r"^insufficient_moves:(?P<cost>-?[\d.]+)>(?P<moves>-?[\d.]+)$")
_PARTIAL_MOVE_RE = re.compile(r"^partial_move_to_(?P<x>-?\d+)_(?P<y>-?\d+)$")

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


def latest_turn_rows(rows: list[dict[str, Any]], player_id: str, current_turn: int) -> tuple[int | None, list[dict[str, Any]]]:
    """Rows of the most recent applied turn before current_turn (deduped, file order)."""
    mine: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        if str(row.get("player_id") or "") != player_id:
            continue
        try:
            turn = int(row.get("turn"))
        except (TypeError, ValueError):
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
    return actor or "order", kind or "command"


def _success_text(row: dict[str, Any]) -> str:
    kind = str(row.get("kind") or "")
    fixed = row.get("fixed_arguments") if isinstance(row.get("fixed_arguments"), dict) else {}
    reason = str(row.get("reason") or "")
    detail = describe_reason(reason)
    if kind == "move_unit":
        path = _PATH_RE.match(reason)
        arrived = path is not None and path.group("stop") == "arrived" and not path.group("partial")
        if not reason or reason == "already_there" or arrived:
            return f"ok — moved to {_coords(fixed) or 'the target'}"
        if reason.startswith("first_step:"):
            return f"ok — moved to {_coords(fixed) or 'the target'} (rough tile: it used all its movement)"
        return f"ok (partial) — {detail}; reissue or pick a new destination"
    if kind == "attack_target":
        return "ok — attack made" + (f" ({detail})" if detail else "")
    if kind == "found_city":
        return "ok — city founded"
    if kind == "set_research_tech":
        return f"ok — researching {_readable(fixed.get('tech_id'), 'TECH_')}"
    if kind == "set_research_civic":
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
        ok = row.get("ok") is True
        if ok:
            outcome = _success_text(row)
        else:
            outcome = "FAILED — " + (describe_reason(row.get("reason")) or "the game rejected it")
        summary = f"{actor} {order}: {outcome}" if actor else f"{order}: {outcome}"
        affected: list[str] = []
        for value in (row.get("command_id"),
                      (row.get("fixed_arguments") or {}).get("unit_id") if isinstance(row.get("fixed_arguments"), dict) else None):
            text = str(value or "").strip()[:128]
            if text and text not in affected:
                affected.append(text)
        items.append({
            "turn": max(0, int(turn)),
            "kind": KIND_OK if ok else KIND_FAILED,
            "summary": summary[:300],
            "affected_ids": affected,
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


def inject_command_results(snapshot: dict[str, Any], session_dir: Path | None) -> int:
    """Fill snapshot history.command_results from last turn's apply-results.jsonl. Returns rows added."""
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    player_id = str(decision.get("player_id") or "")
    try:
        current_turn = int(decision.get("turn"))
    except (TypeError, ValueError):
        return 0
    all_rows = load_apply_results(session_dir)
    turn, rows = latest_turn_rows(all_rows, player_id, current_turn)
    if turn is None or not rows:
        return 0
    items = build_command_results(snapshot, rows, turn)
    items.extend(_earlier_failed_items(snapshot, all_rows, player_id, turn, rows))
    history = snapshot.setdefault("history", {})
    if not isinstance(history, dict):
        return 0
    existing = history.get("command_results")
    history["command_results"] = (list(existing) if isinstance(existing, list) else []) + items
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
    items = [i for i in command_result_items(context) if i.get("kind") in (KIND_OK, KIND_FAILED)]
    if not items:
        return []
    turn = max(int(i.get("turn") or 0) for i in items)
    failed = sum(1 for i in items if i.get("kind") == KIND_FAILED)
    lines = [pipeline._wire_line(
        "prior.turn",
        f"T{turn} order results: {len(items) - failed} ok, {failed} failed (what the game did with your last orders)",
    )]
    for index, item in enumerate(items):
        lines.append(pipeline._wire_line(f"apply.last.{index}", str(item["summary"]).strip()))
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
