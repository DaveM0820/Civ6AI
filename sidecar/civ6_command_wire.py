"""Civ VI command tokens shared by the prompt builder and the reply reader.

The prompt lists every legal unit/city order as a readable token such as
``MoveTo(15,24)``, ``Fortify`` or ``FoundCity``. The model answers with one JSON
object whose keys carry the REQUIRED COMMANDS row number (``"6.scout_1.command":
"MoveTo(15,24)"``). This module turns those tokens back into the exact legal
``command_id`` values so the prompt and the parser can never drift apart.
"""
from __future__ import annotations

import re
from typing import Any

from sidecar import pipeline_v2 as pipeline

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
        return f"MoveTo({xy[0]},{xy[1]})" if xy else None
    if kind in ("attack_target", "range_attack", "melee_attack"):
        return f"AttackTo({xy[0]},{xy[1]})" if xy else None
    if kind in UNIT_POSTURE_TOKENS:
        return UNIT_POSTURE_TOKENS[kind]
    if kind == "automate_explore":
        return "Automate(explore)"
    if kind == "found_city":
        return "FoundCity"
    if kind == "upgrade_unit":
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
        return f"{verb}({build})" if isinstance(build, str) and build else verb
    if kind in ("trade_route", "teleport_trader", "rebase", "paradrop", "nuke"):
        verb = {"trade_route": "TradeRoute", "teleport_trader": "Teleport", "rebase": "RebaseTo",
                "paradrop": "ParadropTo", "nuke": "NukeAt"}[kind]
        return f"{verb}({xy[0]},{xy[1]})" if xy else verb
    if kind == "activate_great_person":
        return "Activate"
    if kind == "spread_religion":
        return "SpreadReligion"
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


def _plot_xy(fixed: dict[str, Any]) -> tuple[int, int] | None:
    for key in ("plot_x", "x"):
        if key in fixed:
            try:
                return int(fixed[key]), int(fixed.get(key.replace("x", "y")))
            except (TypeError, ValueError):
                return None
    return None


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
                "disband": "delete"}
    match = _TOKEN_RE.match(str(value))
    has_verb = bool(match) and not str(value).strip().startswith("(")
    verb = synonyms.get(wanted_verb, wanted_verb) if has_verb else "moveto"
    coord = _COORD_RE.search(str(value))
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
    return None


def _synthesize_far_move(snapshot: dict[str, Any], unit_id: str, x: int, y: int) -> str | None:
    """Civ5-style destination order: ``MoveTo(x,y)`` to any on-map plot.

    The prompt lists no per-tile move options, so a destination that is not one of
    the listed adjacent moves becomes a host-built move_unit command. The game walks
    the engine's own route toward it until the unit's moves run out; an illegal or
    unreachable target simply fails at apply time. Only units that already have a
    legal move this turn get one.
    """
    legal = snapshot.get("legal_commands")
    if not isinstance(legal, list):
        return None
    has_move = any(
        isinstance(c, dict) and c.get("kind") == "move_unit"
        and isinstance(c.get("fixed_arguments"), dict)
        and c["fixed_arguments"].get("unit_id") == unit_id
        for c in legal
    )
    if not has_move:
        return None
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    width, height = game.get("map_width"), game.get("map_height")
    if isinstance(width, int) and width > 0 and not 0 <= x < width:
        return None
    if isinstance(height, int) and height > 0 and not 0 <= y < height:
        return None
    if x < 0 or y < 0:
        return None
    for unit in snapshot.get("your_units", []) or []:
        if isinstance(unit, dict) and unit.get("unit_id") == unit_id and unit.get("plot_id") == f"PLOT_{x}_{y}":
            return None
    cmd_id = f"CMD_{unit_id}_moveto_{x}_{y}"
    if any(isinstance(c, dict) and c.get("command_id") == cmd_id for c in legal):
        return cmd_id
    legal.append({
        "command_id": cmd_id,
        "kind": "move_unit",
        "description": "Move toward destination",
        "fixed_arguments": {"unit_id": unit_id, "target_x": x, "target_y": y},
        "parameter_domains": {},
        "affected_ids": [unit_id],
        "runtime_status": "tested",
    })
    return cmd_id


INTENT_FOUND = "found"
INTENT_IMPROVE = "improve"
INTENT_FOUND_RELIGION = "found_religion"
INTENT_TRADE = "trade"
# WP-A OrderChannel: A=0 move, 1 found, 2 improve, 3 found_religion, 4 trade. N is batch count.
INTENT_A_CODES = {
    INTENT_FOUND: 1,
    INTENT_IMPROVE: 2,
    INTENT_FOUND_RELIGION: 3,
    INTENT_TRADE: 4,
}


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
            fixed["goal"] = True
            fixed["intent"] = intent
        return cmd_id
    legal.append({
        "command_id": cmd_id,
        "kind": "move_unit",
        "description": f"Persistent {intent} goal",
        "fixed_arguments": {
            "unit_id": unit_id,
            "target_x": x,
            "target_y": y,
            "goal": True,
            "intent": intent,
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
    if args.get("improve") is True and kind in ("move_unit", "worker_improve"):
        intent = INTENT_IMPROVE
    if intent in INTENT_A_CODES:
        args["intent"] = intent
        args["goal"] = True
        args.pop("N", None)
    if kind == "worker_improve" and (args.get("target_x") is not None or args.get("x") is not None):
        args["goal"] = True
        args["intent"] = INTENT_IMPROVE
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
    prop_l = {"changeproduction": "production", "purchase": "purchase", "buy": "purchase",
              "changefocus": "focus", "attack": "rangestrike", "bombard": "rangestrike"}.get(prop.lower(), prop.lower())
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
        if prop.lower() == "improve" and head in units:
            raw = str(value).strip()
            token = raw if raw.lower().startswith("improve(") else f"Improve({raw})"
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
                unresolved.append(f"{key}={value}")
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
    LAST_UNRESOLVED[:] = unresolved
    return out


def take_unresolved() -> list[str]:
    """Copy and clear tokens the last expand_civ6_command_wire call could not bind."""
    items = list(LAST_UNRESOLVED)
    LAST_UNRESOLVED.clear()
    return items
