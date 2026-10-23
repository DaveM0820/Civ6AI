"""Civ VI command tokens shared by the prompt builder and the reply reader.

The prompt lists every legal unit/city order as a readable token such as
``MoveTo(15,24)``, ``Fortify`` or ``FoundCity``. The model answers with one JSON
object whose keys carry the REQUIRED COMMANDS row number (``"6.scout_1.command":
"MoveTo(15,24)"``). This module turns those tokens back into the exact legal
``command_id`` values so the prompt and the parser can never drift apart.
"""
from __future__ import annotations

import os
import re
from typing import Any

from sidecar import pipeline_v2 as pipeline
from sidecar.civ6_common import hex_dist as _hex_dist
from sidecar.civ6_common import plot_xy as _plot_xy

ROW_PREFIX_RE = re.compile(r"^\s*\d+\s*[.):]\s*")
_TOKEN_RE = re.compile(r"^\s*(?P<verb>[A-Za-z][A-Za-z0-9_]*)\s*(?:\((?P<args>.*)\))?\s*$")
_COORD_RE = re.compile(r"\(?\s*(-?\d+)\s*,\s*(-?\d+)\s*\)?")
_SETTLE_EQ_RE = re.compile(
    r"^\s*settle\s*=\s*\(?\s*(-?\d+)\s*,\s*(-?\d+)\s*\)?\s*$",
    re.IGNORECASE,
)

UNIT_POSTURE_TOKENS = {
    "unit_posture_fortify": "Fortify",
    "unit_posture_heal": "Heal",
    "unit_posture_alert": "Alert",
    "unit_posture_sleep": "Sleep",
    "unit_skip": "Skip",
}

# Wire property names the prompt uses for city orders.
CITY_PROPS = ("production", "buy", "purchase", "buyTile", "focus", "rangeStrike", "clearQueue", "removeQueueOrder")

# Keys that are prose/bookkeeping, never orders.
LAST_UNRESOLVED: list[str] = []

PROSE_KEYS = {"strategicmap.read", "tacticalmap.read", "map.read", "remember", "decision_summary"}

SETTLE_MARKER_RADIUS_DEFAULT = 4
MIN_CITY_FOUND_DISTANCE = 4  # engine: cannot found within 3 tiles (distance < 4)


def settle_marker_radius() -> int:
    raw = os.environ.get("CIV6_SETTLE_MARKER_RADIUS", "").strip()
    try:
        value = int(raw) if raw else SETTLE_MARKER_RADIUS_DEFAULT
    except ValueError:
        value = SETTLE_MARKER_RADIUS_DEFAULT
    return max(3, min(5, value))


def _city_plot_coords(city: dict[str, Any]) -> tuple[int, int] | None:
    if not isinstance(city, dict):
        return None
    for key in ("x", "y"):
        if key not in city and "plot_id" not in city:
            break
    if isinstance(city.get("x"), int) and isinstance(city.get("y"), int):
        return int(city["x"]), int(city["y"])
    return _plot_xy(city.get("plot_id"))


def _known_plot_at(snapshot: dict[str, Any], x: int, y: int) -> dict[str, Any] | None:
    known = snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else {}
    for plot in known.get("plots") or []:
        if not isinstance(plot, dict):
            continue
        if plot.get("x") == x and plot.get("y") == y:
            return plot
        if str(plot.get("plot_id") or "") == f"PLOT_{x}_{y}":
            return plot
    return None


def site_obeys_founding_rules(snapshot: dict[str, Any], x: int, y: int) -> bool:
    """No water/mountain tiles; not within 3 tiles of an existing city."""
    from sidecar import civ6_wire

    plot = _known_plot_at(snapshot, x, y)
    if isinstance(plot, dict):
        if plot.get("water") is True or plot.get("peak") is True:
            return False
        terrain = str(plot.get("terrain_id") or plot.get("terrain") or "").upper()
        if "COAST" in terrain or terrain.endswith("_OCEAN") or "MOUNTAIN" in terrain:
            return False
        if plot.get("city_id"):
            return False
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    width = game.get("map_width")
    wrap_x = game.get("wrap_x") is not False
    cities = list(snapshot.get("your_cities") or []) + list(snapshot.get("known_other_cities") or [])
    for city in cities:
        coords = _city_plot_coords(city) if isinstance(city, dict) else None
        if coords is None:
            continue
        if civ6_wire._odd_r_distance((x, y), coords, width, wrap_x) < MIN_CITY_FOUND_DISTANCE:
            return False
    return True


def labeled_settle_sites(snapshot: dict[str, Any], radius: int | None = None) -> list[dict[str, Any]]:
    """Stable S1..Sn labels for legal nearby settle tiles (unranked; overlay + prompt)."""
    if radius is None:
        radius = settle_marker_radius()
    units = [u for u in snapshot.get("your_units", []) or [] if isinstance(u, dict)]
    collected: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for unit in units:
        settle = unit.get("settle")
        if not isinstance(settle, dict):
            continue
        unit_id = str(unit.get("unit_id") or "")
        for site in settle.get("sites") or []:
            if not isinstance(site, dict):
                continue
            try:
                x, y = int(site["x"]), int(site["y"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                dist = int(site.get("dist")) if site.get("dist") is not None else None
            except (TypeError, ValueError):
                dist = None
            if dist is not None and dist > radius:
                continue
            if (x, y) in seen:
                continue
            if not site_obeys_founding_rules(snapshot, x, y):
                continue
            seen.add((x, y))
            collected.append({
                "x": x,
                "y": y,
                "dist": dist,
                "coastal": bool(site.get("coastal") or site.get("coast")),
                "fresh_water": bool(site.get("fresh_water")),
                "unit_id": unit_id,
            })
    collected.sort(key=lambda row: (row.get("dist") is None, row.get("dist") or 0, row["x"], row["y"]))
    for index, row in enumerate(collected, start=1):
        row["label"] = f"S{index}"
    return collected


def extract_map_viewport(response: dict[str, Any]) -> Any:
    """The model's map.viewport reply, if this turn set one."""
    if not isinstance(response, dict):
        return None
    for key, value in response.items():
        if not isinstance(key, str):
            continue
        base = pipeline.normalize_wire_property_key(key)
        if base in ("map.viewport", "map.focus", "viewport"):
            return value
    return None


def extract_plan(response: dict[str, Any]) -> dict[str, Any] | None:
    """Pull plan.goal / plan.objective out of a wire reply and remove those keys."""
    if not isinstance(response, dict):
        return None
    goal = None
    objectives: list[str] = []
    done: list[str] = []
    drop: list[str] = []
    for key, value in list(response.items()):
        if not isinstance(key, str):
            continue
        base = pipeline.normalize_wire_property_key(strip_row_prefix(key))
        if base == "plan.goal":
            text = str(value or "").strip()
            if text:
                goal = text[:120]
            drop.append(key)
        elif base == "plan.objective.done" or (base.startswith("plan.objective.") and base.endswith(".done")):
            text = str(value or "").strip()
            if text:
                done.append(text[:160])
            drop.append(key)
        elif base == "plan.objective" or base.startswith("plan.objective."):
            text = str(value or "").strip()
            if text:
                objectives.append(text[:200])
            drop.append(key)
    for key in drop:
        response.pop(key, None)
    if goal is None and not objectives and not done:
        return None
    return {"goal": goal, "objectives": objectives, "done": done}


def extract_remember(response: dict[str, Any]) -> list[str]:
    """Collect `remember` / `N.remember` / `remember.N` notes from a wire reply."""
    notes: list[str] = []
    if not isinstance(response, dict):
        return notes
    for key, value in response.items():
        base = pipeline.normalize_wire_property_key(str(key)) if isinstance(key, str) else ""
        if base != "remember" and not base.startswith("remember."):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and item.strip():
                notes.append(item.strip())
    return notes[:6]


def _xy(fixed: dict[str, Any]) -> tuple[int, int] | None:
    x, y = fixed.get("target_x"), fixed.get("target_y")
    try:
        return int(x), int(y)
    except (TypeError, ValueError):
        pass
    coords = pipeline._coords_from_fixed_arguments(fixed)
    if isinstance(coords, str):
        match = _COORD_RE.search(coords)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def _camel(kind: str) -> str:
    parts = [p for p in kind.split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Command"


def unit_command_token(command: dict[str, Any]) -> str | None:
    """Readable order token for one legal unit command (``MoveTo(15,24)``)."""
    if not isinstance(command, dict):
        return None
    kind = str(command.get("kind", ""))
    fixed = command.get("fixed_arguments") or {}
    if not isinstance(fixed, dict):
        fixed = {}
    xy = _xy(fixed)
    if kind == "move_unit":
        intent = str(fixed.get("intent") or "")
        arrival = fixed.get("A")
        try:
            arrival = int(arrival) if arrival is not None else None
        except (TypeError, ValueError):
            arrival = None
        if (arrival == 1 or intent in ("found", "1")) and xy:
            return f"Settle({xy[0]},{xy[1]})"
        if (arrival == 3 or intent in ("found_religion", "3")) and xy:
            return f"FoundReligion({xy[0]},{xy[1]})"
        if (arrival == 4 or intent in ("trade", "4")) and xy:
            return f"TradeRoute({xy[0]},{xy[1]})"
        build = fixed.get("improvement_id")
        if (arrival == 2 or intent in ("improve", "2")) and xy and isinstance(build, str) and build:
            return f"Improve({xy[0]},{xy[1]},{build})"
        return f"MoveTo({xy[0]},{xy[1]})" if xy else None
    if kind in ("attack_target", "range_attack", "melee_attack"):
        return f"AttackTo({xy[0]},{xy[1]})" if xy else None
    if kind in UNIT_POSTURE_TOKENS:
        return UNIT_POSTURE_TOKENS[kind]
    if kind == "explore":
        return "Automate(explore)"
    if kind == "found_city":
        return "FoundCity"
    if kind == "upgrade_unit":
        target = fixed.get("unit_type_id")
        if isinstance(target, str) and target.strip():
            return f"Upgrade({target.strip()})"
        return "Upgrade"
    if kind == "promote_unit":
        promo = fixed.get("promotion_id")
        return f"Promote({promo})" if isinstance(promo, str) and promo else "Promote"
    if kind == "delete_unit":
        return "Delete"
    if kind == "pillage_improvement":
        return "Pillage"
    if kind.startswith("worker_"):
        build = fixed.get("improvement_id") or fixed.get("build_id") or fixed.get("route_id")
        verb = _camel(kind[len("worker_"):])
        if verb == "Improve" and xy and isinstance(build, str) and build and (
            fixed.get("intent") == "improve" or fixed.get("goal") == 1 or fixed.get("G") == 1 or fixed.get("A") == 2
        ):
            return f"Improve({xy[0]},{xy[1]}):{build}"
        return f"{verb}({build})" if isinstance(build, str) and build else verb
    if kind in ("trade_route", "teleport_trader", "rebase", "paradrop", "nuke"):
        verb = {"trade_route": "TradeRoute", "teleport_trader": "Teleport", "rebase": "RebaseTo",
                "paradrop": "ParadropTo", "nuke": "NukeAt"}[kind]
        city = fixed.get("city_id")
        if kind == "trade_route" and xy:
            return f"TradeRoute({xy[0]},{xy[1]})"
        if kind == "trade_route" and isinstance(city, str) and city:
            return f"TradeRoute({city})"
        return f"{verb}({xy[0]},{xy[1]})" if xy else verb
    if kind == "join_formation":
        return "FormCorps"
    if kind == "activate_great_person":
        if fixed.get("retire") in (1, True, "1"):
            return "Retire"
        return "Activate"
    if kind == "spread_religion":
        if str(fixed.get("action") or "") == "heal":
            return f"HealReligious({xy[0]},{xy[1]})" if xy else "HealReligious"
        return f"SpreadReligion({xy[0]},{xy[1]})" if xy else "SpreadReligion"
    return _camel(kind)


def production_token(build_id: Any, fixed: dict[str, Any] | None = None) -> str:
    text = str(build_id or "").strip()
    if text.startswith("TRAIN:"):
        text = text[6:]
    fixed = fixed or {}
    if text.startswith("DISTRICT_"):
        xy = _xy(fixed) or _plot_xy(fixed)
        if xy:
            return f"{text}@({xy[0]},{xy[1]})"
    return text or "item"


def city_command_token(command: dict[str, Any]) -> tuple[str, str] | None:
    """(property, token) for one legal city command (``("production", "UNIT_SETTLER")``)."""
    if not isinstance(command, dict):
        return None
    kind = str(command.get("kind", ""))
    fixed = command.get("fixed_arguments") or {}
    if not isinstance(fixed, dict):
        fixed = {}
    if kind == "queue_production":
        return "production", production_token(fixed.get("build_id"), fixed)
    if kind == "purchase_item":
        item = production_token(fixed.get("item_id"), fixed)
        if str(fixed.get("yield") or "").lower() == "faith":
            item = f"{item}:faith"
        return "purchase", item
    if kind == "purchase_tile":
        xy = _xy(fixed)
        return "buyTile", f"({xy[0]},{xy[1]})" if xy else "apply"
    if kind == "set_city_focus":
        return "focus", str(fixed.get("focus_id", "default"))
    if kind == "city_attack":
        xy = _xy(fixed)
        return "rangeStrike", f"({xy[0]},{xy[1]})" if xy else "apply"
    if kind == "clear_production_queue":
        return "clearQueue", "apply"
    if kind == "remove_queue_order":
        return "removeQueueOrder", "apply"
    return None


def bare_order_token(value: Any) -> str:
    """Drop a trailing combat forecast: ``AttackTo(1,2) (Major Victory ...)`` -> ``AttackTo(1,2)``."""
    raw = str(value or "").strip().strip('"').strip("'")
    cut = raw.find(") (")
    if cut >= 0:
        return raw[: cut + 1].strip()
    return raw


def _norm(text: Any) -> str:
    raw = str(text or "").strip().strip('"').strip("'")
    return re.sub(r"\s+", "", raw).lower()


def _verb(text: Any) -> str:
    match = _TOKEN_RE.match(str(text or ""))
    return match.group("verb").lower() if match else _norm(text)


def strip_row_prefix(key: str) -> str:
    if not isinstance(key, str):
        return key
    return ROW_PREFIX_RE.sub("", key.strip())


def _unit_maps(snapshot: dict[str, Any]) -> dict[str, str]:
    units = [u for u in snapshot.get("your_units", []) or [] if isinstance(u, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    return {wire: unit_id for unit_id, wire in wire_ids.items()}


_UNIT_ALIAS_RE = re.compile(r"^([a-z]+)_?0*(\d+)$")


def resolve_unit_alias(head: str, units: dict[str, str]) -> str | None:
    """Map Builder_1, builder-1, builder1, and builder_01 onto a real wire id.

    An index past the units of that type stays unresolved: builder_10 is not
    the only builder.
    """
    raw = re.sub(r"[\s\-]+", "_", str(head or "").strip().lower())
    raw = re.sub(r"_+", "_", raw).strip("_")
    if raw in units:
        return raw
    match = _UNIT_ALIAS_RE.match(raw)
    if match is None:
        return None
    prefix, number = match.group(1), int(match.group(2))
    canonical = f"{prefix}_{number}"
    if canonical in units:
        return canonical
    same = sorted(
        name for name in units
        if name.startswith(prefix + "_") and name[len(prefix) + 1:].isdigit()
    )
    if 1 <= number <= len(same):
        return same[number - 1]
    return None


def _city_maps(snapshot: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for city in snapshot.get("your_cities", []) or []:
        if isinstance(city, dict) and isinstance(city.get("city_id"), str):
            out[pipeline._city_prompt_name(city).lower()] = city["city_id"]
    return out


def resolve_unit_token(snapshot: dict[str, Any], unit_id: str, value: Any) -> str | None:
    """Return the legal command_id for ``unitId.command = <token>`` or None."""
    if isinstance(value, str) and value.strip().startswith("CMD_"):
        return value.strip()
    value = bare_order_token(value)
    found_xy = re.match(r"^\s*(?:FoundCity|Found)\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)\s*$", str(value or ""), re.I)
    if found_xy:
        # FoundCity(x,y) = settle there (own tile becomes FoundCity).
        return resolve_unit_token(snapshot, unit_id, f"Settle({found_xy.group(1)},{found_xy.group(2)})")
    settle_eq = _SETTLE_EQ_RE.match(str(value or ""))
    if settle_eq:
        return _synthesize_goal_move(
            snapshot, unit_id, int(settle_eq.group(1)), int(settle_eq.group(2)), intent=INTENT_FOUND,
        )
    wanted = _norm(value)
    if not wanted or "|" in wanted:
        return None
    wanted_verb = _verb(value)
    candidates: list[tuple[str, str]] = []
    for command in snapshot.get("legal_commands", []) or []:
        fixed = command.get("fixed_arguments") if isinstance(command, dict) else None
        if not isinstance(fixed, dict) or fixed.get("unit_id") != unit_id:
            continue
        token = unit_command_token(command)
        cmd_id = command.get("command_id")
        if not token or not isinstance(cmd_id, str):
            continue
        if _norm(token) == wanted:
            return cmd_id
        candidates.append((token, cmd_id))
    # Tolerant matches: synonyms (RangedAttack, Move, Settle, Disband), a bare verb for
    # arg-less orders (Automate for Automate(explore)), or bare coordinates meaning MoveTo.
    synonyms = {"rangedattack": "attackto", "attack": "attackto", "move": "moveto",
                "found": "foundcity", "explore": "automate",
                "disband": "delete", "improvetile": "improve"}
    match = _TOKEN_RE.match(str(value))
    has_verb = bool(match) and not str(value).strip().startswith("(")
    verb = synonyms.get(wanted_verb, wanted_verb) if has_verb else "moveto"
    coord = _COORD_RE.search(str(value))
    if verb == "settle":
        if coord:
            return _synthesize_settle(snapshot, unit_id, int(coord.group(1)), int(coord.group(2)))
        verb = "foundcity"
    if verb == "traderoute":
        return _synthesize_trade_route(snapshot, unit_id, value)
    improves = [(t, c) for t, c in candidates if _verb(t) == "improve" and _COORD_RE.search(t)]
    if improves and verb == "improve":
        return _pick_improve(improves, value, coord)
    for token, cmd_id in candidates:
        if _verb(token) != verb:
            continue
        token_coord = _COORD_RE.search(token)
        if coord and token_coord:
            if (coord.group(1), coord.group(2)) == (token_coord.group(1), token_coord.group(2)):
                return cmd_id
            continue
        if not coord:
            return cmd_id
    if verb == "settle" and coord:
        return _synthesize_goal_move(
            snapshot, unit_id, int(coord.group(1)), int(coord.group(2)), intent="found",
        )
    if verb == "moveto" and coord:
        return _synthesize_far_move(snapshot, unit_id, int(coord.group(1)), int(coord.group(2)))
    if verb == "fortify":
        return _synthesize_fortify(snapshot, unit_id)
    return None


_CIVILIAN_MARKERS = (
    "SETTLER", "BUILDER", "TRADER", "GREAT_", "MISSIONARY", "APOSTLE", "GURU", "INQUISITOR", "ROCK_BAND",
)


def _is_military_unit(unit: dict[str, Any] | None) -> bool:
    if not isinstance(unit, dict):
        return False
    type_id = str(unit.get("unit_type_id") or "").upper()
    if any(marker in type_id for marker in _CIVILIAN_MARKERS):
        return False
    strength = unit.get("strength")
    if isinstance(strength, dict):
        for key in ("current", "base", "combat"):
            value = strength.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return True
    return type_id.startswith("UNIT_")


def _synthesize_fortify(snapshot: dict[str, Any], unit_id: str) -> str | None:
    """Fortify was omitted when the UI CanStartOperation check failed for an AI seat."""
    unit = _unit_row(snapshot, unit_id)
    if not _is_military_unit(unit):
        return None
    return _append_legal(snapshot, {
        "command_id": f"CMD_fortify_{unit_id}",
        "kind": "unit_posture_fortify",
        "description": f"Fortify {unit_id}",
        "fixed_arguments": {"unit_id": unit_id},
    })


def unresolved_unit_note(snapshot: dict[str, Any], unit_id: str, key: str, value: Any) -> str:
    verb = _verb(value)
    if verb == "fortify":
        unit = _unit_row(snapshot, unit_id)
        if unit is None:
            return f"{key}={value}: that unit is not in your army"
        if not _is_military_unit(unit):
            return f"{key}={value}: Fortify is only for a military unit"
        return f"{key}={value}: this unit cannot fortify now"
    if verb in ("attackto", "attack", "rangedattack"):
        return (
            f"{key}={value}: no attack is legal at that tile this turn "
            "(the enemy is outside this unit's attack range, or you are not at war)"
        )
    if verb in ("moveto", "move") and _COORD_RE.search(str(value or "")) is None:
        return f"{key}={value}: MoveTo needs a destination as (x,y)"
    return f"{key}={value}"


# WP-A OrderChannel: A=0 move, 1 found, 2 improve, 3 found_religion, 4 trade. N is batch count.
INTENT_MOVE = "move"
INTENT_FOUND = "found"
INTENT_IMPROVE = "improve"
INTENT_FOUND_RELIGION = "found_religion"
INTENT_TRADE = "trade"
INTENT_A_CODES = {
    INTENT_MOVE: 0,
    INTENT_FOUND: 1,
    INTENT_IMPROVE: 2,
    INTENT_FOUND_RELIGION: 3,
    INTENT_TRADE: 4,
}


def _arrival_fields(intent: str = INTENT_MOVE, a: int | None = None) -> dict[str, Any]:
    """WP-A batch: G = persistent goal, A = arrival intent (N is batch length)."""
    persist = 1
    code = INTENT_A_CODES.get(intent, 0) if a is None else int(a)
    return {
        "G": persist,
        "A": code,
        "goal": persist,
        "intent": intent,
    }


def _unit_row(snapshot: dict[str, Any], unit_id: str) -> dict[str, Any] | None:
    for unit in snapshot.get("your_units", []) or []:
        if isinstance(unit, dict) and unit.get("unit_id") == unit_id:
            return unit
    return None


def _is_listed_settle_site(snapshot: dict[str, Any], unit: dict[str, Any] | None, x: int, y: int) -> bool:
    if not isinstance(unit, dict):
        return False
    if not str(unit.get("unit_type_id") or "").endswith("SETTLER"):
        return False
    settle = unit.get("settle") if isinstance(unit.get("settle"), dict) else {}
    for site in settle.get("sites") or []:
        if not isinstance(site, dict):
            continue
        try:
            if int(site["x"]) == x and int(site["y"]) == y:
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return any(row.get("x") == x and row.get("y") == y for row in labeled_settle_sites(snapshot))


def _on_map(snapshot: dict[str, Any], x: int, y: int) -> bool:
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    width, height = game.get("map_width"), game.get("map_height")
    if isinstance(width, int) and width > 0 and not 0 <= x < width:
        return False
    if isinstance(height, int) and height > 0 and not 0 <= y < height:
        return False
    return x >= 0 and y >= 0


def _append_legal(snapshot: dict[str, Any], command: dict[str, Any]) -> str | None:
    legal = snapshot.setdefault("legal_commands", [])
    if not isinstance(legal, list):
        return None
    cmd_id = command["command_id"]
    if any(isinstance(c, dict) and c.get("command_id") == cmd_id for c in legal):
        return str(cmd_id)
    legal.append(command)
    return str(cmd_id)


def _self_tile_command(snapshot: dict[str, Any], unit_id: str) -> str | None:
    """Own-tile MoveTo becomes FoundCity when this settler can found here. Otherwise dropped."""
    unit = _unit_row(snapshot, unit_id)
    settle = unit.get("settle") if isinstance(unit, dict) else None
    here_ok = isinstance(settle, dict) and settle.get("here_ok") is True
    legal = snapshot.get("legal_commands") if isinstance(snapshot.get("legal_commands"), list) else []
    if here_ok or (isinstance(unit, dict) and str(unit.get("unit_type_id") or "").endswith("SETTLER")):
        for command in legal:
            if not isinstance(command, dict):
                continue
            fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
            if command.get("kind") == "found_city" and fixed.get("unit_id") == unit_id:
                LAST_UNRESOLVED.append(f"dropped: self-tile move for {unit_id} became FoundCity")
                return str(command.get("command_id"))
        if here_ok:
            LAST_UNRESOLVED.append(f"dropped: self-tile move for {unit_id} became FoundCity")
            return _append_legal(snapshot, {
                "command_id": f"CMD_found_{unit_id}",
                "kind": "found_city",
                "description": "Found city here",
                "fixed_arguments": {"unit_id": unit_id},
                "parameter_domains": {},
                "affected_ids": [unit_id],
                "runtime_status": "tested",
            })
    return _append_legal(snapshot, {
        "command_id": f"CMD_skip_{unit_id}",
        "kind": "unit_skip",
        "description": f"Skip {unit_id}",
        "fixed_arguments": {"unit_id": unit_id},
        "parameter_domains": {},
        "affected_ids": [unit_id],
        "runtime_status": "tested",
    })


def _improve_xy(token: str) -> tuple[int, int] | None:
    found = _COORD_RE.search(token)
    if not found:
        return None
    return int(found.group(1)), int(found.group(2))


def _pick_improve(improves: list[tuple[str, str]], value: Any, coord: Any) -> str | None:
    """The Improve offer for that tile. An invalid tile uses the nearest owned offer."""
    if not coord or not improves:
        return None
    x, y = int(coord.group(1)), int(coord.group(2))
    here = [(t, c) for t, c in improves if _improve_xy(t) == (x, y)]
    want = _norm(value)
    for t, c in here:
        imp = t.rsplit(",", 1)[-1].rstrip(")").lower()
        if imp in want or imp.replace("improvement_", "") in want:
            return c
    if here:
        return here[0][1]
    named = re.search(r"improvement_[a-z0-9_]+", str(value).lower())

    def rank(pair: tuple[str, str]) -> tuple[int, int]:
        token, _cmd = pair
        xy = _improve_xy(token) or (x, y)
        named_penalty = 0 if named and named.group(0) in token.lower() else (1 if named else 0)
        return named_penalty, _hex_dist(x, y, xy[0], xy[1])

    chosen = min(improves, key=rank)
    return chosen[1]


def _legal_attack_at(snapshot: dict[str, Any], unit_id: str, x: int, y: int) -> str | None:
    """The offered AttackTo for this unit and tile, when the game already listed one."""
    for command in snapshot.get("legal_commands") or []:
        if not isinstance(command, dict):
            continue
        if command.get("kind") not in ("attack_target", "range_attack", "melee_attack"):
            continue
        fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
        if fixed.get("unit_id") != unit_id:
            continue
        try:
            if int(fixed.get("target_x")) == x and int(fixed.get("target_y")) == y:
                return str(command.get("command_id"))
        except (TypeError, ValueError):
            continue
    return None


def _synthesize_far_move(
    snapshot: dict[str, Any],
    unit_id: str,
    x: int,
    y: int,
    *,
    intent: str = INTENT_MOVE,
    A: int | None = None,
) -> str | None:
    """Civ5-style destination order: ``MoveTo(x,y)`` to any on-map plot.

    Adjacent-move rows are not required (F4). A settler's own tile becomes FoundCity.
    Encodes WP-A MOVE G=1 and A=arrival intent (found=1, improve=2, religion=3, trade=4).
    """
    if not _on_map(snapshot, x, y):
        LAST_UNRESOLVED.append(f"dropped: off-map MoveTo({x},{y}) for {unit_id}")
        return None
    unit = _unit_row(snapshot, unit_id)
    here = _plot_xy(unit)
    if here == (x, y):
        return _self_tile_command(snapshot, unit_id)
    if intent == INTENT_MOVE:
        attack = _legal_attack_at(snapshot, unit_id, x, y)
        if attack:
            return attack
    if intent == INTENT_MOVE and _is_listed_settle_site(snapshot, unit, x, y):
        intent = INTENT_FOUND
    cmd_id = f"CMD_{unit_id}_moveto_{x}_{y}"
    if intent != "move":
        cmd_id = f"CMD_{unit_id}_{intent}_{x}_{y}"
    fixed = {"unit_id": unit_id, "target_x": x, "target_y": y}
    fixed.update(_arrival_fields(intent, A))
    return _append_legal(snapshot, {
        "command_id": cmd_id,
        "kind": "move_unit",
        "description": "Move toward destination",
        "fixed_arguments": fixed,
        "parameter_domains": {},
        "affected_ids": [unit_id],
        "runtime_status": "tested",
    })


def _synthesize_settle(snapshot: dict[str, Any], unit_id: str, x: int, y: int) -> str | None:
    unit = _unit_row(snapshot, unit_id)
    here = _plot_xy(unit)
    settle = unit.get("settle") if isinstance(unit, dict) else None
    if here == (x, y) and isinstance(settle, dict) and settle.get("here_ok") is True:
        legal = snapshot.get("legal_commands") if isinstance(snapshot.get("legal_commands"), list) else []
        for command in legal:
            if isinstance(command, dict) and command.get("kind") == "found_city":
                fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
                if fixed.get("unit_id") == unit_id:
                    return str(command.get("command_id"))
        return _append_legal(snapshot, {
            "command_id": f"CMD_found_{unit_id}",
            "kind": "found_city",
            "description": "Found city here",
            "fixed_arguments": {"unit_id": unit_id},
            "parameter_domains": {},
            "affected_ids": [unit_id],
            "runtime_status": "tested",
        })
    if not site_obeys_founding_rules(snapshot, x, y):
        sites = labeled_settle_sites(snapshot, radius=12)
        if not sites:
            LAST_UNRESOLVED.append(f"dropped: Settle({x},{y}) for {unit_id}: too close to a city or not land; no legal site listed")
            return None
        best = min(sites, key=lambda r: _hex_dist(x, y, r["x"], r["y"]))
        LAST_UNRESOLVED.append(f"dropped: Settle({x},{y}) for {unit_id} is not a legal site; going to {best['label']} ({best['x']},{best['y']}) instead")
        x, y = best["x"], best["y"]
    return _synthesize_far_move(snapshot, unit_id, x, y, intent=INTENT_FOUND)


def _improve_id_from_value(value: Any) -> str | None:
    text = str(value or "")
    match = re.search(r"(IMPROVEMENT_[A-Z0-9_]+)", text, re.I)
    if match:
        return match.group(1).upper()
    after = re.search(r":\s*([A-Za-z0-9_]+)", text)
    if after:
        token = after.group(1)
        return token if token.upper().startswith("IMPROVEMENT_") else f"IMPROVEMENT_{token.upper()}"
    return None


def _synthesize_trade_route(snapshot: dict[str, Any], unit_id: str, value: Any) -> str | None:
    text = str(value or "")
    wanted = _norm(text)
    legal = snapshot.get("legal_commands") if isinstance(snapshot.get("legal_commands"), list) else []
    for command in legal:
        if not isinstance(command, dict):
            continue
        token = unit_command_token(command)
        cmd_id = command.get("command_id")
        if token and isinstance(cmd_id, str) and (_norm(token) == wanted or wanted in _norm(token)):
            return cmd_id
        fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
        if fixed.get("unit_id") != unit_id:
            continue
        city = str(fixed.get("city_id") or "")
        intent = str(fixed.get("intent") or "")
        if command.get("kind") not in ("trade_route", "move_unit") and intent != "trade":
            continue
        if city and (wanted == _norm(city) or city.lower() in text.lower() or city.replace("CITY_", "") in text):
            return str(cmd_id) if isinstance(cmd_id, str) else None
        if intent == "trade" and _norm(token or "") == wanted:
            return str(cmd_id) if isinstance(cmd_id, str) else None
    LAST_UNRESOLVED.append(f"dropped: trade_route={value} for {unit_id} is not a listed destination")
    return None


def _in_map_bounds(snapshot: dict[str, Any], x: int, y: int) -> bool:
    if x < 0 or y < 0:
        return False
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    width, height = game.get("map_width"), game.get("map_height")
    if isinstance(width, int) and width > 0 and not 0 <= x < width:
        return False
    if isinstance(height, int) and height > 0 and not 0 <= y < height:
        return False
    return True


def _synthesize_goal_move(
    snapshot: dict[str, Any],
    unit_id: str,
    x: int,
    y: int,
    *,
    intent: str,
) -> str | None:
    """Pack settle=(x,y) (and other on-arrival intents) as MOVE with goal+intent.

    WP-A reads arguments.goal / arguments.intent and maps them to batch fields G and A
    (not N). Own-tile targets are allowed so Lua can found-here or self_target_hold.
    """
    legal = snapshot.get("legal_commands")
    if not isinstance(legal, list) or not _in_map_bounds(snapshot, x, y):
        return None
    cmd_id = f"CMD_{unit_id}_settle_{x}_{y}" if intent == INTENT_FOUND else f"CMD_{unit_id}_{intent}_{x}_{y}"
    for command in legal:
        if not isinstance(command, dict) or command.get("command_id") != cmd_id:
            continue
        fixed = command.setdefault("fixed_arguments", {})
        if isinstance(fixed, dict):
            fixed.update(_arrival_fields(intent))
        return cmd_id
    legal.append({
        "command_id": cmd_id,
        "kind": "move_unit",
        "description": f"Persistent {intent} goal",
        "fixed_arguments": {
            "unit_id": unit_id,
            "target_x": x,
            "target_y": y,
            **_arrival_fields(intent),
        },
        "parameter_domains": {},
        "affected_ids": [unit_id],
        "runtime_status": "tested",
    })
    return cmd_id


def pack_apply_command(snapshot: dict[str, Any] | None, command: dict[str, Any]) -> dict[str, Any]:
    """Stamp WP-A goal/intent (G/A) and research fallbacks onto one bound command."""
    if not isinstance(command, dict):
        return command
    args = dict(command.get("arguments") or {})
    kind = str(command.get("kind") or "")
    intent = args.get("intent")
    if args.get("found") is True:
        intent = INTENT_FOUND
    if intent in INTENT_A_CODES:
        args["intent"] = intent
        args["goal"] = True
        args.pop("N", None)
    if kind == "trade_route":
        args["goal"] = True
        args["intent"] = INTENT_TRADE
    if kind in ("set_research_tech", "set_research_civic") and isinstance(snapshot, dict):
        field = "tech_id" if kind == "set_research_tech" else "civic_id"
        chosen = args.get(field)
        extras = []
        for item in snapshot.get("legal_commands") or []:
            if not isinstance(item, dict) or item.get("kind") != kind:
                continue
            fixed = item.get("fixed_arguments") if isinstance(item.get("fixed_arguments"), dict) else {}
            value = fixed.get(field)
            if isinstance(value, str) and value and value != chosen and value not in extras:
                extras.append(value)
            if len(extras) >= 2:
                break
        if extras:
            args[f"{field}_2"] = extras[0]
        if len(extras) > 1:
            args[f"{field}_3"] = extras[1]
    command["arguments"] = args
    return command


def resolve_city_token(snapshot: dict[str, Any], city_id: str, prop: str, value: Any) -> str | None:
    if isinstance(value, str) and value.strip().startswith("CMD_"):
        return value.strip()
    value = bare_order_token(value)
    prop_l = {"changeproduction": "production", "purchase": "purchase", "buy": "purchase",
              "changefocus": "focus", "attack": "rangestrike", "bombard": "rangestrike"}.get(prop.lower(), prop.lower())
    raw = str(value or "").strip()
    if "|" in raw and "@" in raw:
        head, _, rest = raw.partition("@")
        for piece in rest.split("|"):
            piece = piece.strip()
            if piece:
                hit = resolve_city_token(snapshot, city_id, prop, f"{head}@{piece}")
                if hit:
                    return hit
        return None
    wanted = _norm(value)
    if not wanted or "|" in wanted:
        return None
    if prop_l in ("production", "buy") and "(" in wanted and "@" not in wanted.split("(", 1)[0]:
        # Copied from a production catalog line: "UNIT_WARRIOR (5 turns, 20 str)" -> UNIT_WARRIOR.
        wanted = wanted.split("(", 1)[0]
    loose = None
    for command in snapshot.get("legal_commands", []) or []:
        fixed = command.get("fixed_arguments") if isinstance(command, dict) else None
        if not isinstance(fixed, dict) or fixed.get("city_id") != city_id:
            continue
        pair = city_command_token(command)
        cmd_id = command.get("command_id")
        if not pair or not isinstance(cmd_id, str) or pair[0].lower() != prop_l:
            continue
        token = _norm(pair[1])
        if token == wanted or wanted in ("apply", "true", "yes") and pair[1] == "apply":
            return cmd_id
        # DISTRICT_X without @(x,y) when only one placement is legal.
        if token.split("@", 1)[0] == wanted.split("@", 1)[0] and loose is None:
            loose = cmd_id
    return loose


def expand_civ6_command_wire(snapshot: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Strip row numbers and bind ``unitId.command`` / ``cityName.production`` to cmd.N ids.

    Anything this function does not recognise is passed through unchanged, so the
    older flat ``unitId.moveTo = (x,y)`` replies keep working.
    """
    if not isinstance(response, dict) or not isinstance(snapshot, dict):
        return response
    LAST_UNRESOLVED.clear()
    from sidecar import civ6_combat_wire as combat_wire

    combat_wire.retain_runnable_attacks(snapshot)
    units = _unit_maps(snapshot)
    cities = _city_maps(snapshot)
    out: dict[str, Any] = {}
    bound: list[str] = []
    unresolved: list[str] = []
    for raw_key, value in response.items():
        if not isinstance(raw_key, str):
            continue
        key = strip_row_prefix(raw_key)
        if not key or key.lower() in ("commands.required.count", "required.count"):
            continue
        low = key.lower()
        if low.startswith("event.") and low.endswith(".log"):
            out[key] = value
            continue
        if low in ("priorities", "priority", "build_priorities", "legal.priorities", "legal.priority"):
            from sidecar import civ6_priorities as prio

            wanted, problems = prio.parse_reply(value)
            if wanted is not None:
                from sidecar import civ6_combat_wire as combat_wire

                if combat_wire.war_active(snapshot):
                    bankruptcy = next(c["id"] for c in prio.CATEGORIES if c["key"] == "fix_bankruptcy")
                    level = wanted.get(bankruptcy)
                    if isinstance(level, int) and level > 2:
                        wanted[bankruptcy] = 2
                        problems.append(
                            "fix_bankruptcy capped at 2 while at war; level 3 blocks military production"
                        )
            unresolved.extend(f"{key}:{p}" for p in problems)
            if wanted is not None and prio.priorities_supported(snapshot):
                legal_ids = {c.get("command_id") for c in snapshot.get("legal_commands", []) if isinstance(c, dict)}
                for cmd_id in prio.plan_commands(prio.current_levels(snapshot), wanted):
                    if cmd_id in legal_ids:
                        bound.append(cmd_id)
            continue
        from sidecar import civ6_governance as governance_wire
        from sidecar import civ6_diplomacy as diplomacy_wire

        if governance_wire.is_reply_key(key):
            gov_ids, gov_notes = governance_wire.bind_reply(snapshot, key, value)
            bound.extend(gov_ids)
            unresolved.extend(gov_notes)
            continue
        if diplomacy_wire.is_reply_key(key):
            diplo_ids, diplo_notes = diplomacy_wire.bind_reply(snapshot, key, value)
            bound.extend(diplo_ids)
            unresolved.extend(diplo_notes)
            continue
        head, _, prop = key.partition(".")
        if prop and head not in units and head.lower() not in cities:
            alias = resolve_unit_alias(head, units)
            if alias is not None:
                head = alias
        if prop.lower() in ("settle",) and head in units:
            coord = _COORD_RE.search(str(value))
            if coord:
                cmd_id = _synthesize_goal_move(
                    snapshot, units[head], int(coord.group(1)), int(coord.group(2)), intent=INTENT_FOUND,
                )
                if cmd_id:
                    bound.append(cmd_id)
                    continue
            unresolved.append(f"{key}={value}")
            continue
        if prop.lower() in ("moveto", "move") and head in units:
            cmd_id = resolve_unit_token(snapshot, units[head], f"MoveTo{value}" if str(value).strip().startswith("(") else f"MoveTo({value})")
            if cmd_id:
                bound.append(cmd_id)
                continue
            unresolved.append(f"{key}={value}")
            continue
        if prop.lower() in ("settle", "found") and head in units:
            raw = str(value).strip()
            token = raw if raw.lower().startswith("settle") or raw.lower().startswith("found") else f"Settle({raw})"
            cmd_id = resolve_unit_token(snapshot, units[head], token)
            if cmd_id:
                bound.append(cmd_id)
                continue
            unresolved.append(f"{key}={value}")
            continue
        if prop.lower() in ("traderoute", "trade_route") and head in units:
            raw = str(value).strip()
            token = raw if raw.lower().startswith("traderoute") else f"TradeRoute({raw})"
            cmd_id = resolve_unit_token(snapshot, units[head], token)
            if cmd_id:
                bound.append(cmd_id)
                continue
            unresolved.append(f"{key}={value}")
            continue
        if prop == "command" and head in units:
            cmd_id = resolve_unit_token(snapshot, units[head], value)
            if cmd_id:
                bound.append(cmd_id)
            else:
                unresolved.append(unresolved_unit_note(snapshot, units[head], key, value))
            continue
        if prop and head.lower() in cities and prop.lower() in {
            p.lower() for p in CITY_PROPS
        } | {"changeproduction", "purchase", "buy", "changefocus", "attack", "bombard"}:
            cmd_id = resolve_city_token(snapshot, cities[head.lower()], prop, value)
            if cmd_id:
                bound.append(cmd_id)
                continue
            if prop.lower() == "production":
                out[f"{head}.changeProduction"] = value
                continue
            unresolved.append(f"{key}={value}")
            continue
        if prop and head not in units and head.lower() not in cities and prop.lower() in {
            "command", "moveto", "move", "settle", "found", "traderoute", "trade_route",
            "attack", "attackto", "fortify", "skip", "improve", "automate",
        }:
            known = ", ".join(list(units)[:12])
            shown = f" Known units: {known}." if known else ""
            unresolved.append(
                f"{key}={value}: {head} is not one of your units.{shown} "
                "Copy a unit id from legal.validUnits."
            )
            continue
        if key in out and raw_key != key:
            continue
        out[key] = value
    if bound:
        index = max(
            [int(k.split(".")[1]) for k in out if k.startswith("cmd.") and k.split(".")[1].isdigit()],
            default=-1,
        )
        for cmd_id in bound:
            index += 1
            out[f"cmd.{index}"] = cmd_id
    from sidecar import civ6_diplomacy as diplomacy_wire

    bound.extend(diplomacy_wire.instalment_ids(snapshot))
    LAST_UNRESOLVED.extend(unresolved)
    return out


def dropped_orders() -> list[str]:
    """Orders the sidecar discarded this bind (unresolved tokens, off-map, self-tile)."""
    return list(LAST_UNRESOLVED)


def take_unresolved() -> list[str]:
    """Copy and clear tokens the last expand_civ6_command_wire call could not bind."""
    items = list(LAST_UNRESOLVED)
    LAST_UNRESOLVED.clear()
    return items


def sitrep_offer_lines(snapshot: dict[str, Any]) -> list[str]:
    """Prompt-facing unit facts: settle sites, goals, command results.

    One helper so WP-C can keep the rest of civ6_wire.py; call from the unit
    situation section. Facts only, unranked (no yield scores).
    """
    from sidecar import pipeline_v2 as pipeline_mod

    lines: list[str] = []
    units = [u for u in snapshot.get("your_units", []) or [] if isinstance(u, dict)]
    wire_ids = pipeline_mod._build_unit_wire_id_map(units)
    for unit in units:
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str):
            continue
        prefix = wire_ids.get(unit_id, "unit")
        goal = unit.get("goal")
        if isinstance(goal, dict) and goal.get("x") is not None:
            eta = goal.get("eta")
            eta_bit = f" ETA~{eta}" if eta is not None else ""
            lines.append(pipeline_mod._wire_line(
                f"{prefix}.goal",
                f"({goal.get('x')},{goal.get('y')}) {goal.get('intent') or 'move'}{eta_bit}",
            ))
        settle = unit.get("settle")
        if not isinstance(settle, dict):
            continue
        here_ok = settle.get("here_ok") is True
        reason = settle.get("here_reason")
        here_bits = ["founding here is legal" if here_ok else "founding here is illegal"]
        if settle.get("coastal"):
            here_bits.append("coastal")
        if settle.get("fresh_water"):
            here_bits.append("fresh_water")
        else:
            here_bits.append("no_fresh_water")
        if not here_ok and reason:
            here_bits.append(str(reason))
        plot = unit.get("plot_id")
        coords = pipeline_mod._plot_coords_text(plot) if isinstance(plot, str) else ""
        lines.append(pipeline_mod._wire_line(f"{prefix}.settle.here", f"{coords} {' '.join(here_bits)}".strip()))
        if not here_ok and reason:
            lines.append(pipeline_mod._wire_line(f"{prefix}.settle.cannotFound", str(reason)))
        sites = [s for s in (settle.get("sites") or []) if isinstance(s, dict)]
        labeled = {(row["x"], row["y"]): row["label"] for row in labeled_settle_sites(snapshot)}
        if sites:
            site_bits = []
            for site in sites:
                try:
                    sx, sy = int(site["x"]), int(site["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                tag = labeled.get((sx, sy), "")
                bit = f"{tag} ({sx},{sy})".strip() if tag else f"({sx},{sy})"
                flags = []
                if site.get("coastal") or site.get("coast"):
                    flags.append("coastal")
                if site.get("fresh_water"):
                    flags.append("fresh water")
                if site.get("dist") is not None:
                    flags.append(f"dist {site.get('dist')}")
                if flags:
                    bit += " " + ", ".join(flags)
                site_bits.append(bit)
            lines.append(pipeline_mod._wire_line(f"{prefix}.settle.sites", " | ".join(site_bits)))
    history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
    results = history.get("command_results") if isinstance(history, dict) else []
    if isinstance(results, list):
        for row in results[:12]:
            if not isinstance(row, dict):
                continue
            dt = row.get("decision_turn", row.get("turn"))
            summary = row.get("summary") or ""
            effect = row.get("effect")
            extra = f" {effect}" if effect else ""
            lines.append(pipeline_mod._wire_line(f"history.T{dt}.order", f"{summary}{extra}".strip()))
    return lines
