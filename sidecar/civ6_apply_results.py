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
    "stale_unit_id",
    "stale_city_id",
    "unit_not_found",
    "plot_occupied_exhausted",
    "site_no_longer_legal",
    "steps=0",
    "no_progress",
    "stack_limit",
    "impassable",
    "outside_borders",
    "forecast_failed",
    "no_combat_forecast",
    "no_effect",
    "no_city_district",
    "no_enemy_on_plot",
    "not_at_war",
    "out_of_range",
    "enemy_on_tile",
    "move_not_applied",
    "order_error",
    "mountain",
    "outside your borders",
    "outside borders",
)
CHAT_NEAR_DUPE_THRESHOLD = 0.6
CHAT_NEAR_DUPE_LOOKBACK_TURNS = 16
CHAT_INTRO_PATTERNS = re.compile(
    r"\b(i am|i'm|im|my name is|greetings from|let history remember|"
    r"stands firm|allow me to introduce|i introduce)\b",
    re.I,
)
CHAT_STOPWORDS = frozenset(
    "a an the and or but if to of in on for with from as at by is are was were be been "
    "being this that these those it its you your yours we our ours they their them me my "
    "mine i he she his her him who whom what which when where why how not no nor so than "
    "then too very can could should would will just also only own let may might shall "
    "do does did done have has had having before after all".split()
)

_PATH_RE = re.compile(
    r"^(?P<partial>partial_)?path:(?P<fx>-?\d+),(?P<fy>-?\d+)>(?P<tx>-?\d+),(?P<ty>-?\d+)"
    r":steps=(?P<steps>\d+):len=(?P<len>\d+):stop=(?P<stop>.*)$"
)
_INSUFFICIENT_RE = re.compile(r"^insufficient_moves:(?P<cost>-?[\d.]+)>(?P<moves>-?[\d.]+)$")
_PARTIAL_MOVE_RE = re.compile(r"^partial_move_to_(?P<x>-?\d+)_(?P<y>-?\d+)$")
_RETARGET_RE = re.compile(
    r"^retargeted:(?P<ox>-?\d+),(?P<oy>-?\d+)>(?P<nx>-?\d+),(?P<ny>-?\d+)$"
)
_STEP_TOWARD_RE = re.compile(
    r"^step_toward:(?P<ox>-?\d+),(?P<oy>-?\d+)>(?P<nx>-?\d+),(?P<ny>-?\d+)(?::(?P<why>.*))?$"
)

_SIMPLE_REASONS = {
    "district_tile_invalid": "the game does not allow that district on that tile (out of city range, wrong terrain, or already used)",
    "district_needs_tile": "a district needs a tile; pick one of the offered DISTRICT_X@(x,y) rows",
    "not_your_territory": "the tile is outside your territory",
    "no_build_charges": "the builder has no build charges left",
    "no_path": "no path: the game found no route to that tile (water or closed borders in the way)",
    "too_many_focus": "too many focuses: the maximum is 3, and any focus past that is rejected",
    "water": "that tile is water and this unit cannot embark there yet",
    "water_no_ocean_embark": "that tile is ocean and this unit cannot embark onto ocean yet",
    "land": "naval units cannot enter land tiles",
    "impassable": "impassable: that tile is a mountain or natural wonder; do not move there. Do not order that destination again.",
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
    "production_requires_local_player": "this seat does not take production orders; AI seats use build priorities, and the human plays the local seat",
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
    "no_result_from_gameplay": "the game never reported a result for this order before the turn ended; reissue it if it is still legal",
    "no_city_district": "the city centre could not be resolved, so the attack was not made. Do not order that destination again.",
    "no_effect:zero_damage": "the combat forecast is 0 damage, so the attack was not made. Do not order that destination again.",
    "not_at_war": "you are not at war with that owner. Do not order that destination again.",
    "no_enemy_on_plot": "no enemy unit or city is on that tile. Do not order that destination again.",
    "no_attacks_left": "this unit has no attacks left this turn",
    "no_combat_forecast": "the game could not forecast that attack, so it was not made. Do not order that destination again.",
    "forecast_failed": "the game could not forecast that attack, so it was not made. Do not order that destination again.",
    "forecast_empty": "the game could not forecast that attack, so it was not made. Do not order that destination again.",
    "out_of_range": "the target is outside this unit's attack range. Do not order that destination again.",
    "outside_borders": "builders can only move onto your own tiles; that destination is outside your borders. Do not order that destination again.",
    "send_failed": "the order never left the host, so it was not played",
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
    match = _STEP_TOWARD_RE.match(text)
    if match:
        why = match.group("why") or ""
        detail = ""
        if why and not why.startswith("moved:"):
            plain = describe_reason(why)
            if plain:
                detail = f" ({plain})"
        return (
            f"destination ({match.group('ox')},{match.group('oy')}) is impassable or has no path; "
            f"stepped to the nearest reachable tile ({match.group('nx')},{match.group('ny')}) instead{detail}"
        )
    if text.startswith("retargeted:"):
        return "destination occupied; the game picked a free neighbouring tile"
    if text.startswith("auto:"):
        detail = describe_reason(text[len("auto:"):])
        base = "the host fired this unused ranged shot or city strike"
        return f"{base} ({detail})" if detail else base
    if text.startswith("approached:"):
        rest = text[len("approached:"):]
        if ":attack_instead:" in rest:
            detail = describe_reason("attack_instead:" + rest.split(":attack_instead:", 1)[1])
            where = rest.split(":", 1)[0]
            base = f"moved to ({where}), the nearest tile in reach, then attacked"
            return f"{base} ({detail})" if detail else base
        where = rest.split(":", 1)[0]
        return f"moved toward that enemy and stopped at ({where}), the nearest tile in reach"
    if text.startswith("engine:"):
        kind = text.split(":")
        label = kind[1] if len(kind) > 1 else "attack"
        target = kind[2] if len(kind) > 2 else ""
        noun = "city" if target == "city" else "unit"
        return f"the game's own {label} attack ran against that {noun}"
    if text.startswith("attack_instead:"):
        detail = describe_reason(text[len("attack_instead:"):])
        base = "the destination held an enemy, so the unit attacked instead"
        return f"{base} ({detail})" if detail else base
    if text.startswith("enemy_on_tile:"):
        detail = text[len("enemy_on_tile:"):].strip()
        if "cannot attack" in detail:
            return detail if detail.endswith(".") else detail + "."
        plain = describe_reason(detail) or detail.replace("_", " ")
        return (
            "that tile has an enemy and this unit cannot attack it this turn "
            f"({plain}). Do not order that destination again."
        )
    if text.startswith("forecast_failed") or text.startswith("no_combat_forecast") or text.startswith("forecast_empty"):
        return _SIMPLE_REASONS["forecast_failed"]
    if text.startswith("no_effect:zero_damage"):
        return _SIMPLE_REASONS["no_effect:zero_damage"]
    if text.startswith("no_effect:damage_not_applied"):
        forecast = text.split("forecast=", 1)[-1] if "forecast=" in text else ""
        extra = f" (forecast {forecast})" if forecast else ""
        return "the forecast dealt damage but the game did not apply it" + extra + ". Do not order that destination again."
    if text.startswith("no_effect:"):
        return "the attack would have had no effect. Do not order that destination again."
    if text.startswith("out_of_range"):
        return _SIMPLE_REASONS["out_of_range"]
    if text.startswith("not_at_war"):
        return _SIMPLE_REASONS["not_at_war"]
    if text.startswith("no_enemy_on_plot"):
        return _SIMPLE_REASONS["no_enemy_on_plot"]
    if text.startswith("no_city_district"):
        return _SIMPLE_REASONS["no_city_district"]
    if text.startswith("too_many_focus"):
        return _SIMPLE_REASONS["too_many_focus"]
    if text.startswith("activate_unavailable"):
        return "the game could not activate that great person"
    if text.startswith("cannot_start_trade_route") or text.startswith("trade_route_unavailable") or text.startswith("trade_unavailable"):
        return "no trade route can start for this unit right now"
    if text.startswith("order_error:"):
        detail = text[len("order_error:"):].strip()
        extra = f": {detail}" if detail else ""
        return "the game raised a script error on that order" + extra + "; do not reissue this same order"
    if text.startswith("explore_no_reveal"):
        where = ""
        if "explore_to=" in text:
            where = text.split("explore_to=", 1)[1].split(":", 1)[0]
        place = f" toward ({where})" if where else ""
        stuck = ""
        if ":stuck" in text:
            stuck = " The unit has revealed nothing for 2+ turns; the next explore steps onto the nearest fog, or toward a revealed unmet city or city-state."
        return "explore did not reveal any new tiles" + place + "." + stuck
    if text.startswith("move_not_applied"):
        return ("the game reported success but the unit did not leave its tile. "
                "Do not order that destination again.")
    if text.startswith("moved:"):
        where = text[len("moved:"):]
        return f"moved to ({where})" if where else "moved"
    if text.startswith("no_result_from_gameplay:"):
        detail = text[len("no_result_from_gameplay:"):].strip()
        base = "the game never reported a result for this order before the turn ended"
        if detail:
            return base + f" because a script error aborted the turn ({detail}); do not reissue this same order"
        return _SIMPLE_REASONS["no_result_from_gameplay"]
    if text.startswith("gamecore_error:") or text.startswith("move_unit_error:"):
        detail = text.split(":", 1)[1].strip()
        extra = f": {detail}" if detail else ""
        return "the game raised a script error on that order" + extra + "; do not reissue this same order"
    if text.startswith("gamecore_unavailable:"):
        return "the game-side order script was unavailable"
    if text.startswith("stale_turn"):
        return ("this order arrived after that turn had moved on, so it was not played; "
                "order it again next turn if it is still legal")
    if text.startswith("seat_turn_over"):
        return "this seat's turn had already ended, so the order was not played"
    if text.startswith("queue_replaced"):
        return "a newer batch replaced this order before the turn started, so it was not played"
    if text.startswith("outside_borders"):
        return _SIMPLE_REASONS["outside_borders"]
    if text.startswith("tile_cannot_have:"):
        return "that tile cannot have " + _readable(text.split(":", 1)[1], "IMPROVEMENT_")
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
        if reason.startswith("step_toward:"):
            return f"ok — {detail}"
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


# Every tile-targeted order: what it tried, for the shared failure line.
TILE_ACTIONS = {
    "move_unit": "move {actor} to", "attack_target": "attack with {actor} at",
    "city_attack": "strike from {actor} at", "found_city": "found a city with {actor} at",
    "queue_production": "place {build} at", "worker_improve": "build {build} with {actor} at",
    "build_fort": "build a fort with {actor} at", "trade_route": "send {actor} on a trade route to",
    "purchase_tile": "buy the tile", "pillage_improvement": "pillage with {actor} at",
}


def _plot_facts(snapshot: dict[str, Any], x: int, y: int, player_id: str) -> list[str]:
    """Tile problems the snapshot can see (water, mountain, owner, city, improvement)."""
    known = snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else {}
    plot = next((p for p in known.get("plots") or [] if isinstance(p, dict) and p.get("x") == x and p.get("y") == y), None)
    if plot is None:
        return ["tile not explored"]
    facts = []
    if plot.get("water"):
        facts.append("water")
    if plot.get("peak"):
        facts.append("mountain")
    owner = plot.get("revealed_owner_id")
    if owner and owner != player_id:
        facts.append(f"owned by {owner}")
    if plot.get("city_id"):
        facts.append("city tile")
    if plot.get("improvement_id"):
        facts.append(f"already has {_readable(plot['improvement_id'], 'IMPROVEMENT_')}")
    return facts


def tile_failure_text(snapshot: dict[str, Any], row: dict[str, Any], actor: str, reason: str) -> str | None:
    """'Last turn you tried to <action> (x,y) but it failed: <game reason> | <tile facts>' for tile orders."""
    kind = str(row.get("kind") or "")
    fixed = row.get("fixed_arguments") if isinstance(row.get("fixed_arguments"), dict) else {}
    x, y = fixed.get("target_x", row.get("x")), fixed.get("target_y", row.get("y"))
    if kind not in TILE_ACTIONS or not isinstance(x, int) or not isinstance(y, int):
        return None
    build = _readable(fixed.get("build_id") or fixed.get("improvement_id"), "DISTRICT_").replace("Improvement ", "")
    action = TILE_ACTIONS[kind].format(actor=actor or "the unit", build=build or "it")
    pid = str(snapshot.get("player_id") or (snapshot.get("decision") or {}).get("player_id") or "")
    reasons = [r for r in [describe_reason(reason) or "the game rejected it"] + _plot_facts(snapshot, x, y, pid) if r]
    return f"Last turn you tried to {action} ({x},{y}) but it failed: " + " | ".join(dict.fromkeys(reasons))


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
        ok = (
            row.get("ok") is True
            or reason.startswith("ok_")
            or reason.startswith("retargeted:")
            or reason.startswith("step_toward:")
            or reason in ("self_target_hold", "tech_already_known", "civic_already_known")
        )
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
        if wire_kind == KIND_FAILED:
            summary = tile_failure_text(snapshot, row, actor, reason) or summary
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
            "identity": _failure_identity(row),
        })
    return items


def _failure_identity(row: dict[str, Any]) -> str:
    """Stable identity of one order, so the same failed policy can be counted."""
    fixed = row.get("fixed_arguments") if isinstance(row.get("fixed_arguments"), dict) else {}
    keys = (
        "unit_id", "city_id", "slots", "target_x", "target_y", "tech_id", "civic_id",
        "promotion_id", "unit_type_id", "government_id", "belief_id", "other_unit_id",
    )
    bits = [str(row.get("kind") or "")]
    for key in keys:
        if key in fixed and fixed[key] is not None:
            bits.append(f"{key}={fixed[key]}")
    return "|".join(bits)


def _annotate_repeat_failures(items: list[dict[str, Any]], rows: list[dict[str, Any]], player_id: str) -> None:
    counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        if str(row.get("player_id") or "") != player_id or row.get("ok") is True:
            continue
        key = (str(row.get("kind") or ""), str(row.get("reason") or ""), _failure_identity(row))
        counts[key] = counts.get(key, 0) + 1
    for item in items:
        if item.get("kind") != KIND_FAILED:
            continue
        key = (str(item.get("order_kind") or ""), str(item.get("reason") or ""), str(item.get("identity") or ""))
        n = counts.get(key, 1)
        if n > 1:
            item["repeats"] = n


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
    all_rows = load_apply_results(session_dir)
    turn, rows = latest_turn_rows(all_rows, player_id, current_turn)
    if turn is None or not rows:
        if isinstance(existing, list):
            return len([i for i in existing if isinstance(i, dict)])
        return 0
    items = build_command_results(snapshot, rows, turn)
    items.extend(_earlier_failed_items(snapshot, all_rows, player_id, turn, rows))
    _annotate_repeat_failures(items, all_rows, player_id)
    # A turn of hundreds of moves used to keep the first 12 and drop the
    # mountain or border failure the next order would repeat.
    def _keep_rank(item: dict[str, Any]) -> tuple[int, int]:
        failed = item.get("kind") in (KIND_FAILED, KIND_FAILED_EARLIER)
        reason = str(item.get("reason") or "") + " " + str(item.get("summary") or "")
        tile = _reason_is_non_transient(reason)
        return (0 if failed and tile else 1 if failed else 2, -int(item.get("turn") or 0))
    items = sorted(items, key=_keep_rank)
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
        auto = sum(1 for i in result_items if str(i.get("reason") or "").startswith("auto:"))
        if auto:
            lines.append(pipeline._wire_line(
                "apply.auto",
                f"{auto} unused ranged shots or city strikes fired by the host",
            ))
        for index, item in enumerate(result_items):
            text = str(item["summary"]).strip()
            repeats = item.get("repeats")
            reason = str(item.get("reason") or "").strip()
            plain = describe_reason(reason)
            if plain and plain not in text and "the game rejected it" in text:
                text = text.replace("the game rejected it", plain, 1)
            if isinstance(repeats, int) and repeats > 1 and item.get("kind") == KIND_FAILED:
                text += (f" — this same order failed {repeats} times for this reason; "
                         "do not send it again until that changes")
            lines.append(pipeline._wire_line(f"apply.last.{index}", text))
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


def strategy_orders_note(
    strategy: str,
    commands: list[dict[str, Any]],
    plan: dict[str, Any] | None = None,
) -> str | None:
    """One context line when the stated strategy and the issued orders diverge. Does not change orders.

    A stored plan with active objectives is checked against those objectives.
    With no plan, the strategy text is checked for peace / attack / defend words.
    """
    if not isinstance(commands, list):
        return None
    from sidecar.civ6_seat_memory import OBJECTIVE_ORDERS, active_objectives

    active = active_objectives({"plan": plan} if isinstance(plan, dict) else None)
    if active:
        kinds = {str(c.get("kind") or "") for c in commands if isinstance(c, dict)}
        notes: list[str] = []
        for obj in active:
            if not (OBJECTIVE_ORDERS[str(obj.get("kind"))] & kinds):
                label = str(obj.get("text") or obj.get("kind") or "objective")
                notes.append(f"objective {obj.get('kind')} ({label}) has no matching order")
        return "; ".join(notes) or None
    text = (strategy or "").lower()
    if not text.strip():
        return None

    def mentioned(*words: str) -> bool:
        return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)

    kinds = {str(c.get("kind") or "") for c in commands if isinstance(c, dict)}
    notes: list[str] = []
    if mentioned("peace", "treaty") and not ({"execute_deal", "send_diplomatic_action"} & kinds):
        notes.append("strategy mentioned peace but no peace or deal order was issued")
    if mentioned("attack", "assault", "capture", "invade", "strike") and not (
        {"attack_target", "city_attack"} & kinds
    ):
        notes.append("strategy mentioned attacking but no attack or city strike was issued")
    if mentioned("defend", "garrison", "fortify", "walls") and not (
        {"unit_posture_fortify", "attack_target", "city_attack", "queue_production"} & kinds
    ):
        notes.append("strategy mentioned defense but no fortify, attack, city strike, or production order was issued")
    if not notes:
        return None
    return "; ".join(notes)


def attach_strategy_orders_note(thought_memory: dict[str, Any], turn: int, commands: list[dict[str, Any]]) -> None:
    thoughts = thought_memory.get("thoughts") if isinstance(thought_memory, dict) else None
    if not isinstance(thoughts, list):
        return
    entry = next((item for item in thoughts if isinstance(item, dict) and int(item.get("turn", -1)) == turn), None)
    if not isinstance(entry, dict):
        return
    plan = thought_memory.get("plan") if isinstance(thought_memory.get("plan"), dict) else None
    note = strategy_orders_note(str(entry.get("strategy") or ""), commands, plan)
    if note:
        entry["orders_note"] = note
    else:
        entry.pop("orders_note", None)


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


def content_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return {tok for tok in tokens if tok not in CHAT_STOPWORDS and len(tok) > 2}


def content_jaccard(left: str, right: str) -> float:
    ta, tb = content_tokens(left), content_tokens(right)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _speaker_identity_needles(snapshot: dict[str, Any]) -> list[str]:
    personality = snapshot.get("personality") if isinstance(snapshot.get("personality"), dict) else {}
    names: list[str] = []
    for raw in (
        personality.get("leader_name"),
        pipeline._leader_id_display_name(str(personality.get("leader_id") or "")),
        pipeline._readable_id(personality.get("civilization_id"), "CIVILIZATION_"),
    ):
        text = str(raw or "").strip().lower()
        if text:
            names.append(text)
    return names


def is_self_reintroduction(text: str, snapshot: dict[str, Any]) -> bool:
    body = (text or "").strip()
    if not body:
        return False
    lowered = body.lower()
    has_intro = bool(CHAT_INTRO_PATTERNS.search(body))
    has_identity = any(needle and needle in lowered for needle in _speaker_identity_needles(snapshot))
    return has_intro and has_identity


def chat_target_key(message: dict[str, Any]) -> str:
    target = str(message.get("target") or "all")
    if target == "player":
        return f"player:{message.get('target_player_id') or ''}"
    return target


def recent_self_chats_by_target(
    snapshot: dict[str, Any], lookback: int = CHAT_NEAR_DUPE_LOOKBACK_TURNS
) -> dict[str, list[tuple[int, str]]]:
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    self_id = str(decision.get("player_id") or "")
    try:
        current_turn = int(decision.get("turn") or 0)
    except (TypeError, ValueError):
        current_turn = 0
    history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
    by_target: dict[str, list[tuple[int, str]]] = {}
    for event in history.get("public_events", []) or []:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "").upper()
        if kind and kind not in ("CHAT_PUBLIC", "CHAT_PRIVATE"):
            continue
        affected = event.get("affected_ids", [])
        sender = str(affected[0]) if isinstance(affected, list) and affected else ""
        if sender != self_id:
            continue
        try:
            turn = int(event.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if current_turn - lookback <= turn < current_turn:
            text = str(event.get("text") or event.get("summary") or "").strip()
            if text:
                target = "all" if kind != "CHAT_PRIVATE" else f"player:{affected[1] if len(affected) > 1 else ''}"
                by_target.setdefault(target, []).append((turn, text))
                by_target.setdefault("all", []).append((turn, text))
    inbox = snapshot.get("diplomacy", {}).get("private_inbox") if isinstance(snapshot.get("diplomacy"), dict) else None
    for message in inbox or []:
        if not isinstance(message, dict):
            continue
        if str(message.get("from_player_id") or "") != self_id:
            continue
        try:
            turn = int(message.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if current_turn - lookback <= turn < current_turn:
            text = str(message.get("text") or "").strip()
            if text:
                by_target.setdefault("all", []).append((turn, text))
    return by_target


def recent_self_public_chats(snapshot: dict[str, Any], lookback: int = CHAT_NEAR_DUPE_LOOKBACK_TURNS) -> list[str]:
    return [text for _turn, text in recent_self_chats_by_target(snapshot, lookback).get("all", [])]


def is_near_duplicate_chat(text: str, recent: list[str], threshold: float = CHAT_NEAR_DUPE_THRESHOLD) -> bool:
    from difflib import SequenceMatcher

    needle = (text or "").strip()
    if not needle:
        return False
    for prior in recent:
        ratio = SequenceMatcher(None, needle.lower(), prior.lower()).ratio()
        overlap = max(ratio, token_jaccard(needle, prior), content_jaccard(needle, prior))
        if overlap >= threshold:
            return True
    return False


def _recent_other_lines(snapshot: dict[str, Any]) -> list[str]:
    """Lines this seat heard from someone else (public, and private to this seat)."""
    me = str((snapshot.get("decision") or {}).get("player_id") or "")
    texts: list[str] = []
    history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
    for event in history.get("public_events") or []:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "").upper()
        if kind and kind not in ("CHAT_PUBLIC", "CHAT_PRIVATE"):
            continue
        affected = event.get("affected_ids") or []
        sender = str(affected[0]) if isinstance(affected, list) and affected else ""
        if sender == me:
            continue
        text = str(event.get("text") or event.get("summary") or "").strip()
        if text:
            texts.append(text)
    inbox = snapshot.get("diplomacy", {}).get("private_inbox") if isinstance(snapshot.get("diplomacy"), dict) else None
    for message in inbox or []:
        if not isinstance(message, dict):
            continue
        if str(message.get("from_player_id") or "") == me:
            continue
        text = str(message.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts[-12:]


def filter_repeat_public_chat(
    snapshot: dict[str, Any],
    chat_messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    recent_map = recent_self_chats_by_target(snapshot)
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    batch: list[str] = []
    for message in chat_messages:
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "")
        needle = text.strip()
        if needle and any(needle.lower() == prior.lower() or is_near_duplicate_chat(needle, [prior]) for prior in batch):
            dropped.append("dropped: public chat repeated a line in this reply and was not sent")
            continue
        key = chat_target_key(message)
        prior_rows = recent_map.get(key, []) + recent_map.get("all", [])
        prior_texts = list(dict.fromkeys(row[1] for row in prior_rows))
        if prior_texts and is_self_reintroduction(text, snapshot):
            dropped.append(
                "dropped: public chat re-introduced you after a prior line to that civilization and was not sent"
            )
            continue
        if prior_texts and is_near_duplicate_chat(text, prior_texts):
            dropped.append(
                "dropped: public chat was a near-repeat of your own recent line and was not sent"
            )
            continue
        leader = str(((snapshot.get("personality") or {}).get("leader_name")) or "").strip().lower()
        low = text.strip().lower()
        if leader and (low.startswith(f"friend {leader}") or low.startswith(leader + ",") or low.startswith(leader + ":")):
            dropped.append("dropped: public chat addressed your own leader and was not sent")
            continue
        others = _recent_other_lines(snapshot)
        if others and is_near_duplicate_chat(text, others):
            dropped.append("dropped: chat repeated another player's recent line and was not sent")
            continue
        kept.append(message)
        if needle:
            batch.append(needle)
        if text.strip():
            try:
                turn = int((snapshot.get("decision") or {}).get("turn") or 0)
            except (TypeError, ValueError):
                turn = 0
            recent_map.setdefault(key, []).append((turn, text))
    return kept, dropped


def _on_hand(snapshot: dict[str, Any]) -> tuple[int | None, int | None]:
    gold = None
    faith = None
    civ6 = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    economy = civ6.get("economy") if isinstance(civ6, dict) else {}
    gold_row = economy.get("gold") if isinstance(economy, dict) else None
    if isinstance(gold_row, dict) and isinstance(gold_row.get("treasury"), int) and not isinstance(gold_row.get("treasury"), bool):
        gold = gold_row["treasury"]
    empire = snapshot.get("your_empire") if isinstance(snapshot.get("your_empire"), dict) else {}
    if gold is None and isinstance(empire.get("gold"), int) and not isinstance(empire.get("gold"), bool):
        gold = empire["gold"]
    religion = empire.get("religion") if isinstance(empire.get("religion"), dict) else {}
    if isinstance(religion.get("faith"), int) and not isinstance(religion.get("faith"), bool):
        faith = religion["faith"]
    governance = civ6.get("governance") if isinstance(civ6, dict) else {}
    gov_rel = governance.get("religion") if isinstance(governance, dict) else {}
    if faith is None and isinstance(gov_rel, dict) and isinstance(gov_rel.get("faith"), int) and not isinstance(gov_rel.get("faith"), bool):
        faith = gov_rel["faith"]
    trade = (civ6.get("diplomacy") or {}).get("your_trade") if isinstance(civ6, dict) else None
    if gold is None and isinstance(trade, dict) and isinstance(trade.get("gold"), int) and not isinstance(trade.get("gold"), bool):
        gold = trade["gold"]
    return gold, faith


def drop_unaffordable_purchases(
    snapshot: dict[str, Any], commands: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop a purchase whose listed cost is above the gold or faith on hand."""
    gold, faith = _on_hand(snapshot)
    kept: list[dict[str, Any]] = []
    notes: list[str] = []
    for command in commands:
        if not isinstance(command, dict) or command.get("kind") != "purchase_item":
            kept.append(command)
            continue
        args = command.get("arguments") if isinstance(command.get("arguments"), dict) else {}
        cost = args.get("cost")
        if isinstance(cost, bool) or not isinstance(cost, int):
            kept.append(command)
            continue
        yield_name = str(args.get("yield") or "gold")
        balance = faith if yield_name == "faith" else gold
        if isinstance(balance, int) and cost > balance:
            item = args.get("item_id") or "item"
            notes.append(f"dropped: purchase {item} costs {cost} {yield_name}, have {balance}")
            continue
        kept.append(command)
    return kept, notes


def _reason_is_non_transient(reason: str) -> bool:
    text = (reason or "").lower()
    if any(token in text for token in NON_TRANSIENT_FAILURES):
        return True
    # describe_reason prose no longer contains the raw token.
    return "mountain" in text or "natural wonder" in text or "outside your borders" in text or "outside borders" in text


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
    if not unit:
        named = re.search(
            r"\b(?:move|attack with|strike from) (\S+)",
            str(item.get("summary") or ""),
            re.I,
        )
        if named:
            unit = named.group(1).strip(".,")
    match = _BLOCKED_RE.match(str(item.get("summary") or "").strip())
    if match:
        return (
            "move_unit" if match.group("order") == "MoveTo" else "attack_target",
            match.group("actor"),
            int(match.group("x")),
            int(match.group("y")),
        )
    if order_kind in ("move_unit", "attack_target", "city_attack", "range_attack", "melee_attack"):
        # Tile-failure summaries ("...move scout_1 to (43,10) but it failed...") no longer
        # match _BLOCKED_RE; take the target from the command id so repeats are still caught.
        # CMD_attack_UNIT_1_45_19 ends in _45_19, which the verb-shaped pattern missed.
        # Unknown coordinates must not match every later order by that unit.
        for value in list(item.get("affected_ids") or []) + [item.get("command_id"), item.get("identity"), item.get("summary")]:
            text = str(value or "")
            m = _CMD_TARGET_RE.search(text)
            if m:
                kind = "move_unit" if order_kind == "move_unit" else "attack_target"
                return (kind, unit, int(m.group(1)), int(m.group(2)))
            xy = re.search(r"\((-?\d+),(-?\d+)\)", text)
            if xy:
                kind = "move_unit" if order_kind == "move_unit" else "attack_target"
                return (kind, unit, int(xy.group(1)), int(xy.group(2)))
            ident = re.search(r"target_x=(-?\d+).*target_y=(-?\d+)", text)
            if ident:
                kind = "move_unit" if order_kind == "move_unit" else "attack_target"
                return (kind, unit, int(ident.group(1)), int(ident.group(2)))
        return None
    return None


_CMD_TARGET_RE = re.compile(r"_(-?\d+)_(-?\d+)$")


def _explore_substitute(snapshot: dict[str, Any], dropped_move: dict[str, Any],
                        reverse: dict[str, str]) -> dict[str, Any] | None:
    """A legal explore order for the unit whose move was dropped, shaped like the bound move."""
    args = dropped_move.get("arguments") if isinstance(dropped_move.get("arguments"), dict) else {}
    unit = str(args.get("unit_id") or "")
    unit = reverse.get(unit, unit)
    cmd_id = f"CMD_explore_{unit}"
    if not any(isinstance(c, dict) and c.get("command_id") == cmd_id for c in snapshot.get("legal_commands") or []):
        return None
    sub = {k: v for k, v in dropped_move.items() if k not in ("arguments", "command_id", "kind")}
    sub.update({"command_id": cmd_id, "kind": "explore", "arguments": {"unit_id": unit}})
    return sub


def _land_units_cannot_embark(snapshot: dict[str, Any]) -> bool:
    """Shipbuilding not researched yet: Sailing or Shipbuilding is still current or offered."""
    techs = ((snapshot.get("civ6") or {}).get("governance") or {}).get("techs") or {}
    if not isinstance(techs, dict):
        return False
    ids = {techs.get("current")} | {o.get("id") for o in techs.get("options") or [] if isinstance(o, dict)}
    return bool(ids & {"TECH_SAILING", "TECH_SHIPBUILDING"})


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
    combat = (snapshot.get("civ6") or {}).get("combat") or {}
    enemy_plots = {(h.get("x"), h.get("y")) for key in ("hostiles", "hostile_cities") for h in combat.get(key) or [] if isinstance(h, dict)}
    water_blocked = _land_units_cannot_embark(snapshot)
    known = snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else {}
    water_plots = {(p.get("x"), p.get("y")) for p in known.get("plots") or [] if isinstance(p, dict) and p.get("water")}
    land_units = {u.get("unit_id") for u in units if u.get("domain_id") == "DOMAIN_LAND"}
    land_units |= {wire_ids.get(uid) for uid in list(land_units) if wire_ids.get(uid)}
    peak_plots = {(p.get("x"), p.get("y")) for p in known.get("plots") or [] if isinstance(p, dict) and p.get("peak")}
    substitutes: list[dict[str, Any]] = []
    failed_tiles: set[tuple[Any, Any]] = {(f[0][2], f[0][3]) for f in fails if f[0][0] == "move_unit"}
    me = str((snapshot.get("decision") or {}).get("player_id") or "")
    plot_owner = {(p.get("x"), p.get("y")): p.get("revealed_owner_id") for p in known.get("plots") or [] if isinstance(p, dict)}
    builders = {u.get("unit_id") for u in units if u.get("unit_type_id") == "UNIT_BUILDER"}
    builders |= {wire_ids.get(uid) for uid in list(builders) if wire_ids.get(uid)}

    seen_orders: set[tuple[Any, ...]] = set()

    def _explore_instead(command: dict[str, Any]) -> None:
        unit = str((command.get("arguments") or {}).get("unit_id") or "")
        if any(str((c.get("arguments") or {}).get("unit_id") or "") == unit for c in kept + substitutes
               if c is not command and isinstance(c.get("arguments"), dict)):
            return
        sub = _explore_substitute(snapshot, command, reverse)
        if sub is not None and sub["arguments"]["unit_id"] not in {str((c.get("arguments") or {}).get("unit_id")) for c in substitutes}:
            substitutes.append(sub)
            dropped.append(f"note: {unit} explores instead")

    for command in commands:
        fp = _command_fingerprint(command)
        matched = None
        if (water_blocked and fp[0] == "move_unit" and (fp[2], fp[3]) in water_plots
                and (fp[1] in land_units or reverse.get(fp[1]) in land_units)):
            dropped.append(f"dropped: MoveTo({fp[2]},{fp[3]}) is water; land units cannot embark before Shipbuilding")
            _explore_instead(command)
            continue
        if (fp[0] == "move_unit" and (fp[1] in builders or reverse.get(fp[1]) in builders)
                and (fp[2], fp[3]) in plot_owner and plot_owner[(fp[2], fp[3])] != me):
            dropped.append(f"dropped: builder MoveTo({fp[2]},{fp[3]}) is outside your borders; builders improve only your own tiles")
            continue
        if fp[0] == "move_unit" and (fp[2], fp[3]) in peak_plots:
            dropped.append(f"dropped: MoveTo({fp[2]},{fp[3]}) is a mountain; no unit can enter it")
            _explore_instead(command)
            continue
        if fp[0] == "attack_target" and (fp[2], fp[3]) not in enemy_plots:
            dropped.append(f"dropped: AttackTo({fp[2]},{fp[3]}) has no visible enemy unit or city to hit")
            continue
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
                f"dropped: repeat of T{matched[0]} failure ({matched[1].split(':')[0] or 'non-transient'}). "
                "Do not order that destination again."
            )
            if fp[0] == "move_unit":
                _explore_instead(command)
                failed_tiles.add((fp[2], fp[3]))
            continue
        if fp[0] in ("move_unit", "attack_target") and fp[2] is not None and fp[3] is not None:
            signature = (fp[0], fp[1], fp[2], fp[3])
            if signature in seen_orders:
                dropped.append(
                    f"dropped: duplicate order to ({fp[2]},{fp[3]}). Do not order that destination again."
                )
                continue
            seen_orders.add(signature)
        kept.append(command)
    kept_units = {str((c.get("arguments") or {}).get("unit_id") or "") for c in kept if isinstance(c.get("arguments"), dict)}
    kept.extend(s for s in substitutes if s["arguments"]["unit_id"] not in kept_units)
    return _one_site_per_builder(snapshot, kept, dropped, failed_tiles), dropped


def suppress_failed_offers(snapshot: dict[str, Any]) -> None:
    """Drop legal moves and attacks that repeat a located non-transient failure.

    A failure with no coordinates is ignored: it must not hide every attack by that unit.
    """
    legal = snapshot.get("legal_commands")
    if not isinstance(legal, list):
        return
    units = [u for u in snapshot.get("your_units", []) if isinstance(u, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    reverse = {v: k for k, v in wire_ids.items()}
    blocked: list[tuple[str, str, Any, Any]] = []
    for item in command_result_items(snapshot):
        fp = _result_fingerprint(item)
        if fp is None or fp[2] is None or fp[3] is None:
            continue
        blocked.append(fp)
    if not blocked:
        return
    attack_kinds = {"attack_target", "range_attack", "melee_attack", "city_attack"}
    kept: list[Any] = []
    for command in legal:
        if not isinstance(command, dict):
            kept.append(command)
            continue
        kind = str(command.get("kind") or "")
        if kind != "move_unit" and kind not in attack_kinds:
            kept.append(command)
            continue
        fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
        order = "move_unit" if kind == "move_unit" else "attack_target"
        unit = str(fixed.get("unit_id") or fixed.get("city_id") or "")
        try:
            x, y = int(fixed["target_x"]), int(fixed["target_y"])
        except (KeyError, TypeError, ValueError):
            kept.append(command)
            continue
        drop = False
        for fail in blocked:
            unit_ok = (
                fail[1] == unit
                or wire_ids.get(unit) == fail[1]
                or reverse.get(fail[1]) == unit
                or wire_ids.get(fail[1]) == unit
            )
            if fail[0] == order and unit_ok and fail[2] == x and fail[3] == y:
                drop = True
                break
        if not drop:
            kept.append(command)
    snapshot["legal_commands"] = kept


def _one_site_per_builder(snapshot: dict[str, Any], commands: list[dict[str, Any]],
                          dropped: list[str], failed: set | None = None) -> list[dict[str, Any]]:
    """Builders keep the Improve tile the model named. Two builders on one tile is a model miss."""
    del snapshot, dropped, failed
    return commands

