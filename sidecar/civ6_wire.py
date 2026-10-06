"""Civ VI flat-wire prompt builder — TDD target for fixtures/civ6/."""
from __future__ import annotations

import copy
from typing import Any

from sidecar import pipeline_v2 as pipeline
from sidecar import civ6_economy as economy_wire
from sidecar import civ6_gs_wire as gs_wire
from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_apply_results
from sidecar import civ6_command_wire as command_wire
from sidecar import civ6_combat_wire as combat_wire
from sidecar import civ6_rankings_wire as rankings_wire

UNITS_NATIVE_CONTROL_HINT = (
    "Units you leave without orders stay where they are this turn; use fortify/sleep/alert to hold a unit on purpose."
)
CITIES_NATIVE_PRODUCTION_HINT = (
    "Cities keep auto production unless you set changeProduction."
)
CIV6_NATIVE_FALLBACK_POLICY = (
    "Units left without orders stay where they are; cities keep auto production unless you override."
)
CIV6_PRIORITY_PRODUCTION_POLICY = (
    "Units left without orders stay where they are; cities keep auto production, steered by build priorities."
)


def _has_queue_production(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    legal = snapshot.get("legal_commands")
    if not isinstance(legal, list):
        return False
    return any(isinstance(item, dict) and item.get("kind") == "queue_production" for item in legal)


def native_fallback_policy(snapshot: dict[str, Any] | None = None) -> str:
    """What happens when the model leaves cities/units alone, matching this seat's apply path."""
    if _has_queue_production(snapshot):
        return CIV6_NATIVE_FALLBACK_POLICY
    from sidecar import civ6_priorities
    if civ6_priorities.priorities_supported(snapshot or {}):
        return CIV6_PRIORITY_PRODUCTION_POLICY
    return CIV6_NATIVE_FALLBACK_POLICY


def chat_dm_examples(snapshot: dict[str, Any] | None) -> str:
    names: list[str] = []
    if isinstance(snapshot, dict):
        for rival in snapshot.get("known_players") or []:
            if not isinstance(rival, dict):
                continue
            name = pipeline._rival_leader_name(rival)
            if name and name not in names:
                names.append(name)
    if names:
        return ", ".join(f"chat.{name}" for name in names[:4])
    return "chat.<rival leader name>"


CIV6_EMPIRE_WIRE: dict[str, tuple[str, str]] = {
    "set_research_tech": ("legal.research.tech", "tech_id"),
    "set_research_civic": ("legal.research.civic", "civic_id"),
    "set_policies": ("legal.policies", "policy_ids"),
    "change_government": ("legal.government", "government_id"),
    "choose_dedication": ("legal.dedication", "dedication_index"),
    "choose_pantheon": ("legal.pantheon", "belief_id"),
    "found_religion": ("legal.religion", "belief_ids"),
    "appoint_governor": ("legal.governor.appoint", "governor_id"),
    "assign_governor": ("legal.governor.assign", "assignment"),
    "promote_governor": ("legal.governor.promote", "promotion"),
    "send_envoy": ("legal.envoy", "target_player_id"),
    "send_diplomatic_action": ("legal.diplomacy", "action_id"),
    "form_alliance": ("legal.alliance", "alliance_type"),
    "propose_trade": ("legal.trade.offer", "offer"),
    "propose_peace": ("legal.peace", "apply"),
    "respond_to_diplomacy": ("legal.diplomacy.respond", "response"),
    "respond_to_trade": ("legal.trade.respond", "response"),
    "recruit_great_person": ("legal.gp.recruit", "great_person_id"),
    "patronize_great_person": ("legal.gp.patronize", "great_person_id"),
    "reject_great_person": ("legal.gp.reject", "great_person_id"),
    "queue_wc_votes": ("legal.wc.votes", "votes"),
    "resolve_city_capture": ("legal.capture", "resolution"),
    "cancel_deal": ("legal.deal.cancel", "deal_kind"),
}

CIV6_UNIT_POSTURE_KINDS = {
    "unit_posture_fortify": "fortify",
    "unit_posture_heal": "heal",
    "unit_posture_alert": "alert",
    "unit_posture_sleep": "sleep",
    "unit_skip": "skip",
}


def _civ6_block(snapshot: dict[str, Any]) -> dict[str, Any]:
    block = snapshot.get("civ6")
    return block if isinstance(block, dict) else {}


def _city_extra(snapshot: dict[str, Any], city_id: str) -> dict[str, Any]:
    extras = _civ6_block(snapshot).get("city_extra", {})
    if not isinstance(extras, dict):
        return {}
    row = extras.get(city_id)
    return row if isinstance(row, dict) else {}


def _civ6_yields(snapshot: dict[str, Any]) -> dict[str, Any]:
    yields = _civ6_block(snapshot).get("yields", {})
    return yields if isinstance(yields, dict) else {}


def _civ6_research_civic(snapshot: dict[str, Any]) -> dict[str, Any]:
    civic = _civ6_block(snapshot).get("research_civic", {})
    return civic if isinstance(civic, dict) else {}


def _production_label(build_id: Any) -> str:
    if not isinstance(build_id, str) or not build_id.strip():
        return "item"
    text = build_id.strip()
    if text.startswith("TRAIN:"):
        text = text[6:]
    if text.startswith("UNIT_") or text.startswith("BUILDING_") or text.startswith("DISTRICT_"):
        return text
    return pipeline._readable_id(text, "UNIT_")


def _civ6_unit_property_parts(command: dict[str, Any]) -> tuple[str, str]:
    kind = str(command.get("kind", ""))
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    if kind == "move_unit":
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return "moveTo", f"({x},{y})"
        return "moveTo", pipeline._coords_from_fixed_arguments(fixed) or "target"
    if kind == "attack_target":
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return "attackTo", f"({x},{y})"
        return "attackTo", pipeline._coords_from_fixed_arguments(fixed) or "target"
    if kind in CIV6_UNIT_POSTURE_KINDS:
        return "stance", CIV6_UNIT_POSTURE_KINDS[kind]
    if kind == "automate_explore":
        return "automate", "explore"
    if kind == "found_city":
        return "foundCity", "apply"
    if kind == "upgrade_unit":
        return "upgrade", "apply"
    if kind == "promote_unit":
        promo = fixed.get("promotion_id")
        if isinstance(promo, str) and promo.strip():
            return "promote", promo
        return "promote", "apply"
    if kind == "delete_unit":
        return "delete", "apply"
    if kind.startswith("worker_"):
        action = kind.replace("worker_", "")
        camel = action[0].lower() + action[1:] if action else "improve"
        if camel == "remove_improvement":
            camel = "removeImprovement"
        elif camel == "remove_feature":
            camel = "removeFeature"
        elif camel == "build_route":
            camel = "buildRoute"
        build = fixed.get("improvement_id") or fixed.get("build_id") or fixed.get("route_id")
        if isinstance(build, str) and build.strip():
            return camel, build
        return camel, "apply"
    if kind == "trade_route":
        coords = pipeline._coords_from_fixed_arguments(fixed)
        return "tradeRoute", coords or "target"
    if kind == "activate_great_person":
        return "activate", "apply"
    if kind == "spread_religion":
        return "spreadReligion", "apply"
    if kind == "teleport_trader":
        coords = pipeline._coords_from_fixed_arguments(fixed)
        return "teleport", coords or "target"
    if kind == "clear_production_queue":
        return "clearQueue", "apply"
    if kind == "remove_queue_order":
        return "removeQueueOrder", "apply"
    property_name = kind[0].lower() + kind[1:] if kind else "command"
    return property_name, "apply"


def _group_civ6_unit_commands(commands: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for command in commands:
        prop_name, value_label = _civ6_unit_property_parts(command)
        values = grouped.setdefault(prop_name, [])
        if value_label not in values:
            values.append(value_label)
    return grouped


def _compact_civ6_unit_legal_lines(
    unit_wire_id: str,
    commands: list[dict[str, Any]],
    snapshot: dict[str, Any] | None = None,
) -> list[str]:
    options_by_prop = _group_civ6_unit_commands(commands)
    unit_id = None
    for command in commands:
        if isinstance(command, dict):
            fixed = command.get("fixed_arguments") or {}
            if isinstance(fixed, dict) and isinstance(fixed.get("unit_id"), str):
                unit_id = fixed["unit_id"]
                break
    attack_tokens: list[str] = []
    if unit_id and isinstance(snapshot, dict):
        attack_tokens = coaching.civ6_attack_option_tokens_for_unit(unit_id, snapshot)
    lines: list[str] = []
    appended_attacks = False
    for prop_name, values in sorted(options_by_prop.items()):
        if prop_name == "attackTo":
            # Prefer appending onto move/stance; skip standalone until end.
            continue
        merged = list(values)
        if prop_name in ("moveTo", "stance") and attack_tokens and not appended_attacks:
            merged = coaching.append_attack_options_to_unit_line(merged, attack_tokens)
            appended_attacks = True
        lines.append(pipeline._wire_line(f"{unit_wire_id}.{prop_name}", " | ".join(merged)))
    leftover = []
    if not appended_attacks and attack_tokens:
        leftover = attack_tokens
    elif "attackTo" in options_by_prop and not appended_attacks:
        leftover = options_by_prop["attackTo"]
    if leftover:
        lines.append(pipeline._wire_line(f"{unit_wire_id}.attackTo", " | ".join(leftover)))
    return lines


def _group_civ6_city_commands(commands: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for command in commands:
        kind = str(command.get("kind", ""))
        fixed = command.get("fixed_arguments", {})
        if not isinstance(fixed, dict):
            fixed = {}
        if kind == "queue_production":
            prop = "changeProduction"
            value = _production_label(fixed.get("build_id"))
        elif kind == "set_city_focus":
            prop = "changeFocus"
            value = str(fixed.get("focus_id", "default"))
        elif kind == "purchase_item":
            prop = "purchase"
            value = _production_label(fixed.get("item_id"))
        elif kind == "purchase_tile":
            prop = "buyTile"
            value = pipeline._coords_from_fixed_arguments(fixed) or "tile"
        elif kind == "city_attack":
            prop = "attack"
            value = pipeline._coords_from_fixed_arguments(fixed) or "target"
        elif kind == "clear_production_queue":
            prop = "clearQueue"
            value = "apply"
        elif kind == "remove_queue_order":
            prop = "removeQueueOrder"
            value = "apply"
        else:
            prop = kind
            value = "apply"
        values = grouped.setdefault(prop, [])
        if value not in values:
            values.append(value)
    return grouped


def _compact_civ6_city_legal_lines(city_name: str, commands: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    grouped = _group_civ6_city_commands(commands)
    for prop_name in ("changeProduction", "changeFocus", "purchase", "buyTile", "attack", "clearQueue", "removeQueueOrder"):
        values = grouped.pop(prop_name, [])
        if values:
            lines.append(pipeline._wire_line(f"{city_name}.{prop_name}", " | ".join(values)))
    for prop_name in sorted(grouped):
        values = grouped[prop_name]
        if values == ["apply"]:
            lines.append(pipeline._wire_line(f"{city_name}.{prop_name}", "apply"))
        else:
            lines.append(pipeline._wire_line(f"{city_name}.{prop_name}", " | ".join(values)))
    return lines


def _civ6_empire_wire_value(command: dict[str, Any]) -> tuple[str, str] | None:
    kind = str(command.get("kind", ""))
    mapping = CIV6_EMPIRE_WIRE.get(kind)
    if mapping is None:
        return None
    wire_key, arg_key = mapping
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    value = fixed.get(arg_key)
    if value is None:
        return wire_key, "apply"
    if isinstance(value, (list, dict)):
        return wire_key, pipeline.canonical_json(value)
    return wire_key, str(value)


def _compact_civ6_empire_legal_lines(commands: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    grouped: dict[str, list[str]] = {}
    for command in commands:
        pair = _civ6_empire_wire_value(command)
        if pair is None:
            continue
        wire_key, value = pair
        values = grouped.setdefault(wire_key, [])
        if value not in values:
            values.append(value)
    for wire_key in sorted(grouped):
        values = grouped[wire_key]
        lines.append(pipeline._wire_line(wire_key, " | ".join(values)))
    return lines


def _append_civ6_unit_situation_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    many_units = len(units) >= pipeline.WIRE_COMPACT_UNITS_THRESHOLD
    for unit in units:
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str):
            continue
        prefix = wire_ids.get(unit_id, "unit")
        plot_id = unit.get("plot_id")
        if isinstance(plot_id, str) and plot_id.strip():
            lines.append(pipeline._wire_line(f"{prefix}.position", pipeline._plot_coords_text(plot_id)))
        health = unit.get("health", {})
        if isinstance(health, dict):
            current = health.get("current")
            maximum = health.get("maximum")
            if isinstance(current, int) and isinstance(maximum, int) and maximum > 0:
                pct = int(current * 100 / maximum)
                # Hide full-health noise; show live % only when wounded.
                if pct < 100:
                    lines.append(pipeline._wire_line(f"{prefix}.hp", pct))
        elif isinstance(unit.get("health_percent"), int) and unit["health_percent"] < 100:
            lines.append(pipeline._wire_line(f"{prefix}.hp", unit["health_percent"]))
        if unit.get("promotion_ready"):
            lines.append(pipeline._wire_line(f"{prefix}.promotionReady", True))
        movement = unit.get("movement", {})
        if isinstance(movement, dict):
            current = movement.get("current")
            if isinstance(current, int):
                lines.append(pipeline._wire_line(f"{prefix}.moves", current))
        if unit.get("needs_orders"):
            lines.append(pipeline._wire_line(f"{prefix}.needsOrders", True))
    lines.extend(command_wire.sitrep_offer_lines(snapshot))


def _append_civ6_city_situation_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    cities = [city for city in snapshot.get("your_cities", []) if isinstance(city, dict)]
    many_cities = len(cities) >= pipeline.WIRE_COMPACT_CITIES_THRESHOLD
    for city in cities:
        name = pipeline._city_prompt_name(city)
        city_id = city.get("city_id", "")
        extra = _city_extra(snapshot, str(city_id))
        is_capital = bool(city.get("is_capital"))
        if many_cities and not is_capital:
            plot_id = city.get("plot_id")
            if isinstance(plot_id, str) and plot_id.strip():
                lines.append(pipeline._wire_line(f"{name}.position", pipeline._plot_coords_text(plot_id)))
            continue
        lines.append(pipeline._wire_line(f"{name}.population", int(city.get("population", 1))))
        if is_capital:
            lines.append(pipeline._wire_line(f"{name}.capital", True))
        loyalty = extra.get("loyalty")
        if isinstance(loyalty, int):
            lines.append(pipeline._wire_line(f"{name}.loyalty", loyalty))
        amenities = city.get("amenities")
        if isinstance(amenities, dict):
            net = amenities.get("net")
            if isinstance(net, int):
                lines.append(pipeline._wire_line(f"{name}.amenities", net))
        defense = city.get("defense")
        if isinstance(defense, dict):
            hp = defense.get("health_percent")
            if isinstance(hp, int) and hp < 100:
                lines.append(pipeline._wire_line(f"{name}.hp", hp))
        production = city.get("production", {})
        if isinstance(production, dict) and production.get("item_id"):
            lines.append(pipeline._wire_line(f"{name}.currentProduction", _production_label(production["item_id"])))


def _append_civ6_empire_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    empire = snapshot.get("your_empire", {})
    if not isinstance(empire, dict):
        return
    yields = _civ6_yields(snapshot)
    pipeline._append_int_wire(lines, "empire.score", empire.get("score"))
    cities = [city for city in snapshot.get("your_cities", []) if isinstance(city, dict)]
    if cities:
        lines.append(pipeline._wire_line("empire.cities", len(cities)))
    pipeline._append_int_wire(lines, "empire.gold", empire.get("gold"))
    pipeline._append_int_wire(lines, "empire.gold_per_turn", empire.get("gold_per_turn"))
    amenities = empire.get("amenities")
    if isinstance(amenities, dict):
        pipeline._append_int_wire(lines, "empire.amenities.net", amenities.get("net"))
    known = snapshot.get("known_map")
    if isinstance(known, dict) and isinstance(known.get("explored_percent"), int):
        pipeline._append_int_wire(lines, "empire.map.explored_percent", known.get("explored_percent"))
    for field in ("science", "culture", "faith", "favor"):
        value = yields.get(field)
        if isinstance(value, int):
            lines.append(pipeline._wire_line(f"empire.{field}", value))
    research = empire.get("research", {})
    if isinstance(research, dict):
        pipeline._append_id_wire(lines, "empire.research.tech", research.get("tech_id"))
        pipeline._append_int_wire(lines, "empire.research.tech.progress", research.get("progress"))
        pipeline._append_int_wire(lines, "empire.research.tech.cost", research.get("cost"))
        pipeline._append_int_wire(lines, "empire.research.tech.per_turn", research.get("research_per_turn"))
        pipeline._append_int_wire(lines, "empire.research.tech.turns_left", research.get("estimated_turns_remaining"))
    civic = _civ6_research_civic(snapshot)
    if civic.get("civic_id"):
        pipeline._append_id_wire(lines, "empire.research.civic", civic.get("civic_id"))
        pipeline._append_int_wire(lines, "empire.research.civic.progress", civic.get("progress"))
        pipeline._append_int_wire(lines, "empire.research.civic.turns_left", civic.get("turns_left"))
    government_id = _civ6_block(snapshot).get("government_id")
    if isinstance(government_id, str) and government_id.strip():
        pipeline._append_id_wire(lines, "empire.government", government_id)
    unit_counts = empire.get("unit_counts", {})
    if isinstance(unit_counts, dict):
        for field in ("total", "military", "settlers", "idle"):
            pipeline._append_int_wire(lines, f"empire.units.{field}", unit_counts.get(field))


def _append_civ6_rival_wire(lines: list[str], rival: dict[str, Any]) -> None:
    player_id = rival.get("player_id")
    if not isinstance(player_id, str) or not player_id.strip():
        return
    leader = pipeline._rival_leader_name(rival)
    civ_id = rival.get("civilization_id")
    civ_label = pipeline._readable_id(civ_id, "CIVILIZATION_") if isinstance(civ_id, str) else ""
    if civ_label:
        lines.append(pipeline._wire_line(f"rival.{player_id}.leader", leader))
        lines.append(pipeline._wire_line(f"rival.{player_id}.civ", civ_label))
    pipeline._append_int_wire(lines, f"rival.{player_id}.score", rival.get("score"))


# ---------------------------------------------------------------------------
# Civ5-parity prompt layout (GAME / EMPIRE / DIPLOMACY / OPPONENTS / ATTENTION /
# THOUGHTS / ADVICE / RESPONSE INSTRUCTIONS / OPTIONAL COMMANDS / REQUIRED COMMANDS).
# Orders use readable tokens from civ6_command_wire so prompt and parser match.
# ---------------------------------------------------------------------------

_CIV6_TOKEN_ORDER = ("MoveTo", "Settle", "Improve", "AttackTo", "FoundCity", "TradeRoute", "Automate",
                     "Activate", "Promote", "Upgrade",
                     "Fortify", "Alert", "Heal", "Sleep", "Skip", "Delete")


def _leader_civ(snapshot: dict[str, Any]) -> tuple[str, str]:
    personality = snapshot.get("personality", {})
    if not isinstance(personality, dict):
        personality = {}
    leader = personality.get("leader_name", personality.get("leader_id", "Leader"))
    civ_id = personality.get("civilization_id")
    civ_label = pipeline._readable_id(civ_id, "CIVILIZATION_") if civ_id else ""
    return str(leader), civ_label


def _token_sort_key(token: str) -> tuple[int, str]:
    verb = token.split("(", 1)[0]
    try:
        rank = _CIV6_TOKEN_ORDER.index(verb)
    except ValueError:
        rank = len(_CIV6_TOKEN_ORDER)
    return rank, token


def _civ6_unit_tokens(snapshot: dict[str, Any]) -> dict[str, list[str]]:
    """unit_id -> ordered, de-duplicated legal order tokens for that unit."""
    out: dict[str, list[str]] = {}
    for command in snapshot.get("legal_commands", []):
        if not isinstance(command, dict) or not command.get("command_id"):
            continue
        fixed = command.get("fixed_arguments", {})
        unit_id = fixed.get("unit_id") if isinstance(fixed, dict) else None
        if not isinstance(unit_id, str):
            continue
        token = command_wire.unit_command_token(command)
        # Civ5-style movement: a unit that can move gets one free-destination
        # MoveTo(x,y) (any plot; the game walks its own route), not a list of tiles.
        if token and token.startswith("MoveTo("):
            token = "MoveTo(x,y)"
        if token and token not in out.setdefault(unit_id, []):
            out[unit_id].append(token)
    for unit_id, tokens in out.items():
        tokens.sort(key=_token_sort_key)
    return out


def _civ6_city_tokens(snapshot: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """city_id -> {prop: [tokens]} for legal city orders."""
    out: dict[str, dict[str, list[str]]] = {}
    for command in snapshot.get("legal_commands", []):
        if not isinstance(command, dict) or not command.get("command_id"):
            continue
        fixed = command.get("fixed_arguments", {})
        city_id = fixed.get("city_id") if isinstance(fixed, dict) else None
        if not isinstance(city_id, str):
            continue
        pair = command_wire.city_command_token(command)
        if not pair:
            continue
        prop, token = pair
        bucket = out.setdefault(city_id, {}).setdefault(prop, [])
        if token not in bucket:
            bucket.append(token)
    return out


def _civ6_empire_tokens(snapshot: dict[str, Any]) -> dict[str, list[str]]:
    """wire key (legal.research.tech, ...) -> legal values."""
    out: dict[str, list[str]] = {}
    for command in snapshot.get("legal_commands", []):
        if not isinstance(command, dict) or not command.get("command_id"):
            continue
        fixed = command.get("fixed_arguments", {})
        if isinstance(fixed, dict) and (fixed.get("unit_id") or fixed.get("city_id")):
            continue
        pair = _civ6_empire_wire_value(command)
        if not pair:
            continue
        key, value = pair
        if value not in out.setdefault(key, []):
            out[key].append(value)
    return out


def _unit_type_label(unit: dict[str, Any]) -> str:
    type_id = str(unit.get("unit_type_id") or "UNIT")
    return type_id[5:] if type_id.startswith("UNIT_") else type_id


def _engine_known_id(value: Any) -> bool:
    """False for Lua placeholders the engine never filled (ERA_UNKNOWN, Unknown, empty)."""
    if not isinstance(value, str) or not value.strip():
        return False
    return "UNKNOWN" not in value.upper()


def _is_civilian(unit: dict[str, Any]) -> bool:
    type_id = str(unit.get("unit_type_id") or "")
    formation = str(unit.get("unit_class_id") or "")
    if formation == "FORMATION_CLASS_CIVILIAN":
        return True
    if formation in ("FORMATION_CLASS_LAND_COMBAT", "FORMATION_CLASS_NAVAL", "FORMATION_CLASS_AIR"):
        return False
    civilian_types = ("SETTLER", "BUILDER", "WORKER", "TRADER", "MISSIONARY", "APOSTLE",
                      "GURU", "INQUISITOR", "ARCHAEOLOGIST", "GREAT_", "NATURALIST", "ROCK_BAND",
                      "SPY", "MEDIC", "ENGINEER")
    if any(tag in type_id for tag in civilian_types):
        return True
    return False


def _required_unit_options(tokens: list[str]) -> list[str]:
    """Required-row options: drop Skip when anything else is legal (Civ5 parity)."""
    options = [t for t in tokens if t != "Skip"] or list(tokens)
    return options


def _required_city_rows(snapshot: dict[str, Any]) -> list[tuple[str, list[str]]]:
    city_tokens = _civ6_city_tokens(snapshot)
    rows: list[tuple[str, list[str]]] = []
    for city in snapshot.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        city_id = str(city.get("city_id", ""))
        production = city.get("production", {})
        building = isinstance(production, dict) and production.get("item_id")
        options = city_tokens.get(city_id, {}).get("production", [])
        if building or not options:
            continue
        rows.append((pipeline._city_prompt_name(city), options))
    return rows


def _event_log_rows(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    """(EventName, hint) rows for attention items that deserve a written thought."""
    rows: list[tuple[str, str]] = []
    idle = [u for u in snapshot.get("your_units", []) if isinstance(u, dict) and u.get("needs_orders")]
    if idle:
        rows.append(("Idle", "(write this turn's thought on this item)"))
    if civ6_apply_results.blocked_attention_lines(snapshot):
        rows.append(("Blocked", "(last turn's failed order: what went wrong and what you do differently)"))
    for note in coaching.collect_civ6_attention_items(snapshot):
        low = note.lower()
        name = None
        if low.startswith("explore") or "explor" in low[:40]:
            name = "Explore"
        elif "retreat" in low or "heal" in low[:60]:
            name = "Wounded"
        elif "focus" in low and "fire" in low:
            name = "FocusFire"
        elif "gold" in low or "bankrupt" in low or "amenit" in low:
            name = "Economy"
        if name and all(existing != name for existing, _ in rows):
            rows.append((name, "(write this turn's thought on this item)"))
    return rows


def _civ6_required_rows(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    """Ordered (key, value-hint) required rows (without numbers)."""
    rows: list[tuple[str, str]] = []
    for text in coaching.civ6_required_thought_rows(snapshot):
        key, _, hint = text.partition(" = ")
        rows.append((key.strip(), hint.strip()))
    for name, hint in _event_log_rows(snapshot):
        rows.append((f"Event.{name}.log", hint))
    units = [u for u in snapshot.get("your_units", []) if isinstance(u, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    unit_tokens = _civ6_unit_tokens(snapshot)
    for unit in units:
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str):
            continue
        needs = unit.get("needs_orders") is True or unit.get("promotion_ready")
        options = _required_unit_options(unit_tokens.get(unit_id, []))
        if not needs or not options:
            continue
        rows.append((f"{wire_ids.get(unit_id, unit_id)}.command", " | ".join(options)))
    for city_name, options in _required_city_rows(snapshot):
        rows.append((f"{city_name}.production", " | ".join(options)))
    from sidecar import civ6_diplomacy as diplomacy_wire
    rows.extend(diplomacy_wire.required_rows(snapshot))
    return rows


def _count_lines(count: int) -> list[str]:
    if count <= 0:
        return [
            "There are no required commands this turn. Still issue as many optional commands as useful, numbered from 1.",
        ]
    return [
        f"There are {count} required commands. You must respond with every required command, enumerated from 1 to {count}.",
        'In JSON, prefix each key with its row number (e.g. "2.settler_1.command"); the host strips the numeric prefix when applying orders.',
        f"Required rows are the minimum, not the whole turn. After row {count}, add as many optional commands as useful "
        f"(chat, diplomacy, research, civics, extra unit/city orders) starting at {count + 1}. There is no cap on optional commands this turn.",
    ]


def _civ6_chat_rules(snapshot: dict[str, Any]) -> list[str]:
    """Chat mechanics not already covered in DIPLOMACY (drops the repeated lobby/spam lines)."""
    keep: list[str] = []
    skip_words = ("lobby", "spam", "rare", "chat.public", "broadcast", "proactively")
    for line in pipeline._chat_format_guidance(snapshot):
        low = line.lower()
        # Keep early-turn intro lines even though they mention chat.all / greetings.
        if line.lstrip().startswith("EARLY TURN"):
            if line not in keep:
                keep.append(line)
            continue
        if any(word in low for word in skip_words) and "not spoken publicly" not in low:
            continue
        if line not in keep:
            keep.append(line)
    # Unconditional: also append if cadence path was filtered upstream.
    for line in pipeline.early_turn_intro_chat_lines(snapshot):
        if line not in keep:
            keep.append(line)
    keep.append(coaching.CIV6_CHAT_VARIETY_COACHING)
    keep.append(
        f"Private DMs use a rival's name as the key ({chat_dm_examples(snapshot)}), "
        "or chat.player.PLAYER_n / chat.PLAYER_n. chat.all is public. "
        f"Keep each line under {pipeline.CHAT_TEXT_MAX_LENGTH} characters."
    )
    return keep


def build_civ6_role_instruction(snapshot: dict[str, Any]) -> str:
    """System instruction: first-person role-play, Civ5-parity wording, Civ VI mechanics."""
    leader, civ_label = _leader_civ(snapshot)
    role = f"You are {leader}"
    if civ_label:
        role += f", playing as the {civ_label} civilization"
    attach_map = pipeline.map_image_attach_turn(snapshot)
    map_clause = (
        " A labeled map image is attached each turn — read geography and unit positions from it; "
        "hex labels use (x,y) like move commands. "
        if attach_map else " Use EMPIRE unit coordinates for movement this turn (no map image attached). "
    )
    gandhi_clause = pipeline._gandhi_role_clause() if pipeline._is_gandhi_leader(snapshot) else ""
    return (
        f"{role}, in a live Civilization VI match. "
        f"{gandhi_clause}"
        "Full role-play mode: you are this leader — recognizable, with their actual sense of humor "
        "(vain, pious, cruel, folksy, whatever they were), not a marble statue. "
        "Write and think in first person — I, my, we — embodying their temperament and emotional state this turn. "
        "thought.situation and thought.strategy are ONE paragraph each of guided thinking — "
        "board read, then strategy — never neutral analyst prose. "
        "thought.situation and thought.strategy must each be newly written this turn; lead with new observations "
        "and do not copy or lightly rephrase prior T{n} journal lines. "
        "thought.strategy holds your victory path and this turn's command plan in prose; "
        "unitId.command and cityName.production keys execute orders — never substitute prose for those keys. "
        "Event.*.log should sound like you thinking aloud. "
        "Diplomacy and rival psychology are part of the game — actively cultivate relationships, trades, and "
        "alliances (or rivalries) aligned with your path to victory; every player is trying to win. "
        "Play to win using Civilization VI mechanics (districts, adjacency, amenities, housing, loyalty, "
        "civics and policy cards, one military unit per tile); personality colors prose, not the build queue. "
        "Speak in the game: send chat.all and "
        f"{chat_dm_examples(snapshot)} whenever it fits (opening, first contact, deals, "
        "war, taunts, replies) — private DMs are expected on first meetings, war declarations, major deals, "
        f"and inbox replies. Use only facts from the prompt.{map_clause}"
        "After your response the host applies only your explicit orders; "
        f"{native_fallback_policy(snapshot)}"
    )


def _game_section(context: dict[str, Any], map_stats: list[str] | None) -> list[str]:
    leader, civ_label = _leader_civ(context)
    decision = context.get("decision", {}) if isinstance(context.get("decision"), dict) else {}
    player_id = decision.get("player_id", "PLAYER_0")
    lines = [
        "# == Context ==",
        f"You are {leader}" + (f", playing as the {civ_label} civilization in Civilization VI." if civ_label else ", in Civilization VI."),
        "Play Civilization VI (districts and adjacency, amenities, housing, loyalty, civics and policy cards, "
        "one military unit per tile). Personality colors prose, not production or unit orders.",
        "This is a race to develop: every turn is scarce. Move units aggressively into fog and toward objectives; "
        "advance exploration, expansion, tech, and civics without delay. Issue a command for every unit and city "
        "that needs orders — one idle turn compounds every turn after.",
        "Geography is strategy: read islands vs continents, coastal pockets, narrow land bridges, mountain and "
        "river choke points, and who controls the straits before you found cities, route armies, or declare war.",
        coaching.CIV6_MOVE_THEN_ATTACK_GUIDANCE,
        coaching.CIV6_UNIT_STACKING_GUIDANCE,
        coaching.civ6_map_axes_wrap_guidance(context),
        "Move orders: MoveTo(x,y) takes ANY destination on the map (read x,y off the minimap axis ticks and "
        "unitId.position). The game walks its own shortest route there and spends up to unitId.moves this turn; "
        "a farther destination stops partway, so reissue it next turn. Pick targets unitId.maxMovement or more "
        "tiles away on open ground — a one-tile hop wastes leftover movement. Scouts and warriors: aim into fog.",
        "War is integral to civilization — keep a military, watch gold, science, culture, faith, and amenities, "
        "and use theory of mind: play the other players, not just the board.",
        "",
        pipeline._wire_line("player", pipeline._player_identity_phrase(leader, civ_label, player_id)),
        pipeline._wire_line("turn", int(decision.get("turn", 0))),
    ]
    game = context.get("game", {})
    if isinstance(game, dict):
        pipeline._append_int_wire(lines, "year", decision.get("year"))
        for key, field in (("era", "era_id"), ("speed", "game_speed_id"),
                           ("difficulty", "difficulty_id"), ("world_size", "world_size_id")):
            value = game.get(field)
            if _engine_known_id(value):
                pipeline._append_id_wire(lines, key, value)
    map_lines: list[str] = []
    civ6_map = _civ6_block(context).get("map", {})
    if isinstance(civ6_map, dict) and civ6_map:
        pipeline._append_int_wire(map_lines, "map.world.width", civ6_map.get("width"))
        pipeline._append_int_wire(map_lines, "map.world.height", civ6_map.get("height"))
        hex_layout = civ6_map.get("hex_layout")
        if isinstance(hex_layout, str) and hex_layout.strip():
            map_lines.append(pipeline._wire_line("map.hex", hex_layout))
    elif isinstance(game, dict):
        pipeline._append_int_wire(map_lines, "map.world.width", game.get("map_width"))
        pipeline._append_int_wire(map_lines, "map.world.height", game.get("map_height"))
    if map_stats:
        map_lines.extend(map_stats)
    pipeline._append_map_wire_stats(map_lines, context, map_stats)
    explored = coaching._civ6_explored_percent(context)
    if isinstance(explored, int):
        map_lines.append(pipeline._wire_line("map.explored", f"{explored}%"))
    if pipeline.map_image_attach_turn(context) and not any("attached" in l for l in map_lines):
        map_lines.append(pipeline._wire_line("map.images", "attached — fog, terrain, coast, unit positions"))
    lines.extend(map_lines)
    return lines


def _empire_section(context: dict[str, Any]) -> list[str]:
    lines = ["# == Summary =="]
    _append_civ6_empire_wire(lines, context)
    lines.extend(economy_wire.empire_lines(context))
    lines.extend(gs_wire.empire_lines(context))
    summary = context.get("strategic_summary")
    if isinstance(summary, dict):
        for section, wire_name in (("city_alerts", "city"), ("economy_alerts", "economy"),
                                   ("military_alerts", "military"), ("diplomacy_alerts", "diplomacy"),
                                   ("resource_alerts", "resource")):
            for index, alert in enumerate(summary.get(section, [])[:6]):
                if isinstance(alert, dict) and alert.get("text"):
                    lines.append(pipeline._wire_line(f"alert.{wire_name}.{index}", str(alert["text"])[:200]))
    # Cities
    cities = [c for c in context.get("your_cities", []) if isinstance(c, dict)]
    if cities:
        lines.append("# == Cities ==")
        city_block: list[str] = []
        _append_civ6_city_situation_wire(city_block, context)
        for city in cities:
            name = pipeline._city_prompt_name(city)
            production = city.get("production", {})
            if not (isinstance(production, dict) and production.get("item_id")):
                city_block.append(f"***{name}.currentProduction = NONE***")
        # keep each city's lines together
        for city in cities:
            name = pipeline._city_prompt_name(city)
            lines.extend(l for l in city_block if l.startswith((f"{name}.", f"***{name}.")))
            lines.extend(economy_wire.city_lines(context, city, name))
            lines.extend(gs_wire.city_lines(context, city, name))
            lines.append("")
        if lines[-1] == "":
            lines.pop()
    # Units
    units = [u for u in context.get("your_units", []) if isinstance(u, dict)]
    if units:
        counts: dict[str, int] = {}
        for unit in units:
            label = _unit_type_label(unit).replace("_", " ").title()
            counts[label] = counts.get(label, 0) + 1
        lines.append(pipeline._wire_line(
            "units.inventory", ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        ))
        wire_ids = pipeline._build_unit_wire_id_map(units)
        unit_tokens = _civ6_unit_tokens(context)
        for title, group in (("Military", [u for u in units if not _is_civilian(u)]),
                             ("Civilian", [u for u in units if _is_civilian(u)])):
            if not group:
                continue
            lines.append(f"# == Units — {title} ==")
            seen_types: dict[str, list[str]] = {}
            for unit in group:
                kinds: list[str] = []
                for token in unit_tokens.get(str(unit.get("unit_id")), []):
                    verb = token.split("(", 1)[0]
                    shape = f"{verb}(x,y)" if "(" in token and verb in ("MoveTo", "AttackTo") else token
                    if shape not in kinds:
                        kinds.append(shape)
                bucket = seen_types.setdefault(_unit_type_label(unit), [])
                for shape in kinds:
                    if shape not in bucket:
                        bucket.append(shape)
            for type_label, shapes in seen_types.items():
                lines.append(f"# {type_label} legalCommands = {', '.join(shapes) if shapes else '(none this turn)'}")
            for unit in group:
                unit_id = unit.get("unit_id")
                if not isinstance(unit_id, str):
                    continue
                prefix = wire_ids.get(unit_id, "unit")
                plot_id = unit.get("plot_id")
                if isinstance(plot_id, str) and plot_id.strip():
                    lines.append(pipeline._wire_line(f"{prefix}.position", pipeline._plot_coords_text(plot_id)))
                lines.extend(combat_wire.unit_row_lines(prefix, unit, context))
                pct = coaching.civ6_unit_health_percent(unit)
                if isinstance(pct, int) and pct < 100:
                    lines.append(pipeline._wire_line(f"{prefix}.hp", f"{pct}%"))
                if unit.get("needs_orders"):
                    lines.append(f"***{prefix}.needsOrders = true***")
                if unit.get("promotion_ready"):
                    lines.append(pipeline._wire_line(f"{prefix}.promotionReady", True))
                movement = unit.get("movement", {})
                if isinstance(movement, dict):
                    if isinstance(movement.get("current"), int):
                        lines.append(pipeline._wire_line(f"{prefix}.moves", movement["current"]))
                    if isinstance(movement.get("maximum"), int) and movement["maximum"] > 0:
                        lines.append(pipeline._wire_line(f"{prefix}.maxMovement", movement["maximum"]))
                if "SETTLER" in str(unit.get("unit_type_id") or ""):
                    lines.extend(coaching.settler_fact_lines(prefix, unit, context))
                lines.append("")
            if lines[-1] == "":
                lines.pop()
        if coaching.settler_present(context):
            lines.append(f"# Settle: {coaching.CIV6_SETTLER_MAP_ADVICE}")
    return lines


_CIV6_DEAL_KINDS = frozenset({"form_alliance", "propose_trade", "propose_peace", "respond_to_trade",
                              "declare_war", "make_peace", "accept_deal", "reject_deal"})


def _diplomacy_section(context: dict[str, Any]) -> list[str]:
    from sidecar import civ6_diplomacy as diplomacy_wire

    deal_rows = diplomacy_wire.has_orders(context) or any(
        isinstance(c, dict) and c.get("kind") in _CIV6_DEAL_KINDS
        for c in context.get("legal_commands", []))
    met = [r for r in context.get("known_players", []) if isinstance(r, dict)
           and isinstance(r.get("relation"), dict) and r["relation"].get("met")]
    lines = [
        "Model what rivals want and fear — trade, isolation, and alliances are tools, not filler.",
        "HAGGLE IN DMs: highly encourage "
        f"{chat_dm_examples(context)} BEFORE any formal trade or alliance, and keep DMing "
        "WHILE a deal is pending (counter-offers, sweeteners, threats, flattery). Chat is where you bargain."
        + (" legal.diplomacy.Leader / legal.peace.Leader are the war and peace orders." if deal_rows else
           " There are no war or peace orders for you this turn, so agreements live in chat and in "
           "what you actually do on the map (remember them)."),
        f"Use private DMs ({chat_dm_examples(context)}) on relationship milestones: first meeting, declaring war, deal talks, "
        "ultimatums, and replies to fresh inbox messages.",
        "Never reveal military plans, weak cities, or hidden ambitions in chat.all (those go in private DMs).",
        "Be original and occasionally funny — in-character wit beats generic filler.",
        "chat.all is public. Send it when you have something original to say (opening, taunt, deal, war). "
        f"If many turns pass with no chat.all, send one. Prefer {chat_dm_examples(context)} for targeted talk.",
    ]
    if met:
        names = ", ".join(pipeline._rival_leader_name(r) for r in met)
        lines.append(
            f"You have met {names} — send {chat_dm_examples(context)} on first contact, war, and before/during deal talks."
        )
    lines.append(
        "In thought.strategy, name which rivals you are courting, isolating, or appeasing and why."
        + (f" Answer pending deals in OPTIONAL COMMANDS the same turn and send {chat_dm_examples(context)} explaining your "
           "accept, reject, or counter." if deal_rows else "")
    )
    history = context.get("history", {})
    chat_lines: list[str] = []
    if isinstance(history, dict):
        for index, event in enumerate(pipeline._recent_history_events(
                history.get("public_events", []), pipeline.chat_history_max_messages())):
            if not isinstance(event, dict):
                continue
            text = pipeline._format_public_chat_line(context, event)
            if text:
                chat_lines.append(pipeline._wire_line(f"chat.public.t{int(event.get('turn', 0))}.{index}", text))
    diplomacy_block = context.get("diplomacy", {})
    inbox = diplomacy_block.get("private_inbox", []) if isinstance(diplomacy_block, dict) else []
    for index, message in enumerate(pipeline._recent_history_events(inbox, pipeline.chat_history_max_messages())):
        if not isinstance(message, dict):
            continue
        text = pipeline.trim_chat_text(str(message.get("text", "")))
        if text:
            from_id = str(message.get("from_player_id", ""))
            sender = pipeline._player_chat_name(context, from_id) if from_id else "Rival"
            chat_lines.append(pipeline._wire_line(
                f"chat.private.t{int(message.get('turn', 0))}.{index}", f"{sender} (private): {text}"))
    lines.append("# == Chat Log ==")
    lines.extend(chat_lines or ["(no messages yet)"])
    lines.append(
        "Hint: actively use remember for deals, rival impressions, war aims, and multi-turn plans you will need "
        "later; set a duration in turns, or forever only when it matters the whole game."
    )
    return lines


def civ6_player_kind(player: dict[str, Any] | None) -> str:
    """major | city-state | free cities | barbarians (from Civ6 leader/civ ids)."""
    if not isinstance(player, dict):
        return "major"
    leader = str(player.get("leader_id") or "").upper()
    civ = str(player.get("civilization_id") or "").upper()
    if civ == "CIVILIZATION_BARBARIAN" or "BARBARIAN" in leader:
        return "barbarians"
    if civ == "CIVILIZATION_FREE_CITIES" or leader == "LEADER_FREE_CITIES":
        return "free cities"
    if leader.startswith("LEADER_MINOR_CIV_"):
        return "city-state"
    return "major"


def _odd_r_distance(a: tuple[int, int], b: tuple[int, int], width: int | None, wrap_x: bool) -> int:
    """Hex distance on the Civ odd-r grid (odd rows shifted east), X-wrap aware."""
    def cube(x: int, y: int) -> tuple[int, int, int]:
        q = x - (y - (y & 1)) // 2
        return q, -q - y, y

    candidates = [b]
    if wrap_x and width:
        candidates += [(b[0] + width, b[1]), (b[0] - width, b[1])]
    ax, ay, az = cube(*a)
    best = None
    for cx, cy in candidates:
        bx, by, bz = cube(cx, cy)
        dist = max(abs(ax - bx), abs(ay - by), abs(az - bz))
        best = dist if best is None else min(best, dist)
    return int(best or 0)


def _player_display(context: dict[str, Any], player_id: str) -> str:
    for rival in context.get("known_players", []) or []:
        if isinstance(rival, dict) and rival.get("player_id") == player_id:
            return pipeline._rival_leader_name(rival)
    return player_id or "Unknown"


def _other_player_lines(context: dict[str, Any]) -> list[str]:
    """Known foreign cities, visible foreign units, enemies near your units (Civ5 parity)."""
    lines: list[str] = []
    players = {
        str(r.get("player_id")): r
        for r in context.get("known_players", []) or []
        if isinstance(r, dict) and r.get("player_id")
    }
    cities = [c for c in context.get("known_other_cities", []) or [] if isinstance(c, dict)]
    if cities:
        lines.append("# == Known foreign cities ==")
        used: dict[str, int] = {}
        for city in cities[:24]:
            owner = str(city.get("owner_player_id") or "")
            name = str(city.get("name") or city.get("city_id") or "City").strip()
            used[name] = used.get(name, 0) + 1
            key = name if used[name] == 1 else f"{name}#{used[name]}"
            kind = civ6_player_kind(players.get(owner))
            owner_text = _player_display(context, owner)
            if kind != "major":
                owner_text = f"{owner_text} ({kind})"
            parts = [f"owner {owner_text}", f"at {pipeline._plot_coords_text(city.get('plot_id'))}"]
            if isinstance(city.get("population"), int):
                parts.append(f"pop {city['population']}")
            if city.get("is_capital") is True:
                parts.append("capital")
            parts.append("in view" if city.get("knowledge") == "visible" else "last seen (fogged)")
            lines.append(pipeline._wire_line(f"city.{key}", ", ".join(parts)))
    units = [u for u in context.get("visible_other_units", []) or [] if isinstance(u, dict)]
    if units:
        lines.append("# == Foreign units visible ==")
        used_keys: dict[str, int] = {}
        for unit in units[:24]:
            owner = str(unit.get("owner_player_id") or "")
            type_label = pipeline._readable_id(str(unit.get("unit_type_id") or "UNIT"), "UNIT_").lower()
            base = f"{_player_display(context, owner)}.{type_label}"
            used_keys[base] = used_keys.get(base, 0) + 1
            key = base if used_keys[base] == 1 else f"{base}_{used_keys[base]}"
            lines.append(pipeline._wire_line(f"{key}.position", pipeline._plot_coords_text(unit.get("plot_id"))))
            if isinstance(unit.get("visible_strength"), int) and unit["visible_strength"] > 0:
                lines.append(pipeline._wire_line(f"{key}.strength", unit["visible_strength"]))
            if isinstance(unit.get("health_percent"), int) and unit["health_percent"] < 100:
                lines.append(pipeline._wire_line(f"{key}.hp", f"{unit['health_percent']}%"))
        hostile_ids = {
            pid for pid, rival in players.items()
            if (isinstance(rival.get("relation"), dict) and rival["relation"].get("at_war"))
            or civ6_player_kind(rival) == "barbarians"
        }
        game = context.get("game", {}) if isinstance(context.get("game"), dict) else {}
        width = game.get("map_width") if isinstance(game.get("map_width"), int) else None
        wrap_x = game.get("wrap_x") is not False
        own_units = [u for u in context.get("your_units", []) or [] if isinstance(u, dict)]
        wire_ids = pipeline._build_unit_wire_id_map(own_units)
        in_range: list[str] = []
        for own in own_units:
            own_xy = pipeline._parse_plot_coords(own.get("plot_id"))
            if own_xy is None:
                continue
            threats = []
            for unit in units:
                owner = str(unit.get("owner_player_id") or "")
                xy = pipeline._parse_plot_coords(unit.get("plot_id"))
                if owner not in hostile_ids or xy is None:
                    continue
                dist = _odd_r_distance(own_xy, xy, width, wrap_x)
                if dist <= 3:
                    type_label = pipeline._readable_id(str(unit.get("unit_type_id") or "UNIT"), "UNIT_").lower()
                    strength = unit.get("visible_strength")
                    text = f"{_player_display(context, owner)}.{type_label}@({xy[0]},{xy[1]}) {dist} tiles"
                    if isinstance(strength, int) and strength > 0:
                        text += f" str{strength}"
                    threats.append(text)
            if threats:
                name = wire_ids.get(str(own.get("unit_id")), "unit")
                in_range.append(pipeline._wire_line(f"{name}.inRange", " | ".join(threats[:4])))
        if in_range:
            lines.append("# == Enemies in range ==")
            lines.extend(in_range)
    return lines


def _civ6_diplomacy(context: dict[str, Any]) -> dict[str, Any]:
    civ6 = context.get("civ6")
    block = civ6.get("diplomacy") if isinstance(civ6, dict) else None
    return block if isinstance(block, dict) else {}


def _attitude_label(value: Any) -> str:
    """DIPLO_STATE_FRIENDLY -> FRIENDLY; placeholder ids (ATTITUDE_3, ATTITUDE_NEUTRAL default) -> ''."""
    text = str(value or "")
    if not _engine_known_id(text) or text.split("_")[-1].lstrip("-").isdigit():
        return ""
    if text.startswith("DIPLO_STATE_"):
        return text[len("DIPLO_STATE_"):]
    if text == "ATTITUDE_NEUTRAL":
        return ""  # the old mod's placeholder, not an engine reading
    return text


_APPROACH_LABELS = {
    "war": "WAR",
    "alliance": "ALLIANCE",
    "declared_friendship": "DECLARED_FRIEND",
    "denounced": "DENOUNCED",
    "friendly": "FRIENDLY",
    "unfriendly": "UNFRIENDLY",
    "neutral": "NEUTRAL",
}


def _players_text(context: dict[str, Any], player_ids: list[Any]) -> str:
    self_id = str(context.get("decision", {}).get("player_id", "")) if isinstance(context.get("decision"), dict) else ""
    names = ["you" if str(pid) == self_id else _player_display(context, str(pid)) for pid in player_ids]
    return ", ".join(names)


def _civ6_major_relation_lines(context: dict[str, Any], name: str, diplo: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    attitude = _attitude_label(diplo.get("state"))
    if attitude:
        score = diplo.get("diplomatic_score")
        if isinstance(score, int) and not isinstance(score, bool):
            attitude += f" (score {score:+d})"
        lines.append(pipeline._wire_line(f"rival.{name}.attitude", attitude))
    approach = _APPROACH_LABELS.get(str(diplo.get("relationship") or ""))
    if diplo.get("alliance") and diplo.get("alliance_type"):
        approach = "ALLIANCE " + pipeline._readable_id(str(diplo["alliance_type"]), "ALLIANCE_")
    if approach:
        lines.append(pipeline._wire_line(f"rival.{name}.approach", approach))
    if diplo.get("defensive_pact"):
        lines.append(pipeline._wire_line(f"rival.{name}.defensivePact", True))
    reasons = [r for r in diplo.get("reasons", []) or [] if isinstance(r, dict) and r.get("text")]
    if reasons:
        lines.append(pipeline._wire_line(
            f"rival.{name}.why",
            " | ".join(f"{r['text']} {int(r.get('score') or 0):+d}" for r in reasons[:3])))
    wars = [pid for pid in diplo.get("at_war_with", []) or [] if isinstance(pid, str)]
    if wars:
        lines.append(pipeline._wire_line(f"rival.{name}.at_war_elsewhere", _players_text(context, wars)))
    return lines


def _civ6_city_state_lines(context: dict[str, Any], name: str, city_state: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if city_state.get("city_state_type"):
        lines.append(pipeline._wire_line(f"rival.{name}.cityStateType", str(city_state["city_state_type"]).lower()))
    suzerain = city_state.get("suzerain_id")
    lines.append(pipeline._wire_line(
        f"rival.{name}.suzerain", _players_text(context, [suzerain]) if suzerain else "none"))
    if isinstance(city_state.get("your_envoys"), int):
        lines.append(pipeline._wire_line(f"rival.{name}.yourEnvoys", city_state["your_envoys"]))
    return lines


def _resource_label(resource_id: Any) -> str:
    return pipeline._readable_id(str(resource_id or ""), "RESOURCE_").lower()


def _trade_stock_text(stock: dict[str, Any] | None) -> str:
    if not isinstance(stock, dict):
        return ""
    parts: list[str] = []
    if isinstance(stock.get("gold"), int):
        parts.append(f"gold:{stock['gold']}")
    if isinstance(stock.get("gold_per_turn"), int) and stock["gold_per_turn"] > 0:
        parts.append(f"gpt:{stock['gold_per_turn']}")
    for key in ("luxuries", "strategics"):
        for row in stock.get(key, []) or []:
            if isinstance(row, dict) and row.get("resource_id"):
                parts.append(f"{_resource_label(row['resource_id'])}:{int(row.get('amount') or 1)}")
    return " | ".join(parts)


def _luxury_ids(stock: dict[str, Any] | None) -> set[str]:
    if not isinstance(stock, dict):
        return set()
    return {str(r.get("resource_id")) for r in stock.get("luxuries", []) or [] if isinstance(r, dict) and r.get("resource_id")}


def _civ6_trade_lines(context: dict[str, Any], rivals: list[dict[str, Any]], diplomacy: dict[str, Any]) -> list[str]:
    """Civ5-style # == Diplomacy == block from civ6.diplomacy (absent with older mods)."""
    if not diplomacy:
        return []
    lines = ["# == Diplomacy =="]
    wars = [pair for pair in diplomacy.get("wars", []) or [] if isinstance(pair, list) and len(pair) == 2]
    if wars:
        lines.append(pipeline._wire_line(
            "diplomacy.wars", " | ".join(f"{_players_text(context, [a])} vs {_players_text(context, [b])}" for a, b in wars)))
    else:
        lines.append(pipeline._wire_line("diplomacy.wars", "none known between other civs"))
    if isinstance(diplomacy.get("envoys_to_give"), int) and diplomacy["envoys_to_give"] > 0:
        lines.append(pipeline._wire_line("diplomacy.envoys.available", diplomacy["envoys_to_give"]))
    mine = diplomacy.get("your_trade") if isinstance(diplomacy.get("your_trade"), dict) else None
    offer = _trade_stock_text(mine)
    lines.append(pipeline._wire_line("diplomacy.offer.you", offer or "(nothing tradable)"))
    lines.append(pipeline._wire_line(
        "diplomacy.offer.note",
        "Your stock that could go into a deal (luxuries, strategics, gold, gold per turn). Deals are made in chat; "
        "the engine only applies the legal commands listed for you."))
    lines.append(pipeline._wire_line(
        "diplomacy.request.note",
        "What each rival holds that you could ask for; 'wants' lists your luxuries they lack (trade bait)."))
    names = {str(r.get("player_id")): r for r in rivals if isinstance(r, dict)}
    my_lux = _luxury_ids(mine)
    for major in diplomacy.get("majors", []) or []:
        if not isinstance(major, dict):
            continue
        pid = str(major.get("player_id"))
        rival = names.get(pid)
        label = f"{pipeline._rival_leader_name(rival) if rival else pid} ({pid})"
        trade = major.get("trade") if isinstance(major.get("trade"), dict) else None
        text = _trade_stock_text(trade) or "(nothing tradable seen)"
        wants = sorted(_resource_label(r) for r in my_lux - _luxury_ids(trade))
        if trade is not None and wants:
            text += " ; wants: " + ", ".join(wants)
        if major.get("at_war"):
            text += " ; at war with you (peace first)"
        lines.append(pipeline._wire_line(f"diplomacy.request.{label}", text))
    return lines


def _opponents_section(context: dict[str, Any]) -> list[str]:
    leader, civ_label = _leader_civ(context)
    empire = context.get("your_empire", {}) if isinstance(context.get("your_empire"), dict) else {}
    rivals = [r for r in context.get("known_players", [])[:12] if isinstance(r, dict)]
    standings: list[tuple[int, str]] = []
    if isinstance(empire.get("score"), int):
        standings.append((empire["score"], f"{leader} ({civ_label}) {empire['score']} [you]"))
    for rival in rivals:
        kind = civ6_player_kind(rival)
        if kind in ("barbarians", "free cities"):
            continue  # not competitors; listed under Relations only
        if isinstance(rival.get("score"), int):
            civ = pipeline._readable_id(rival.get("civilization_id", ""), "CIVILIZATION_")
            tag = " (city-state)" if kind == "city-state" else ""
            standings.append((rival["score"], f"{pipeline._rival_leader_name(rival)} ({civ}){tag} {rival['score']}"))
    lines: list[str] = []
    if standings:
        lines.append("# == Standings ==")
        for rank, (_, text) in enumerate(sorted(standings, key=lambda s: -s[0]), start=1):
            lines.append(pipeline._wire_line(f"score.rank.{rank}", text))
    diplomacy = _civ6_diplomacy(context)
    diplo_majors = {str(m.get("player_id")): m for m in diplomacy.get("majors", []) if isinstance(m, dict)}
    diplo_city_states = {str(c.get("player_id")): c for c in diplomacy.get("city_states", []) if isinstance(c, dict)}
    if rivals:
        lines.append("# == Relations ==")
    for rival in rivals:
        name = pipeline._rival_leader_name(rival)
        civ = pipeline._readable_id(rival.get("civilization_id", ""), "CIVILIZATION_")
        if civ:
            lines.append(pipeline._wire_line(f"rival.{name}.civ", civ))
        kind = civ6_player_kind(rival)
        if kind != "major":
            lines.append(pipeline._wire_line(f"rival.{name}.type", kind))
        pipeline._append_int_wire(lines, f"rival.{name}.score", rival.get("score"))
        relation = rival.get("relation", {})
        diplo = diplo_majors.get(str(rival.get("player_id")))
        if diplo is not None:
            lines.extend(_civ6_major_relation_lines(context, name, diplo))
        elif isinstance(relation, dict):
            attitude = _attitude_label(relation.get("attitude_id"))
            if attitude:
                lines.append(pipeline._wire_line(f"rival.{name}.attitude", attitude))
        if isinstance(relation, dict):
            if relation.get("at_war"):
                lines.append(pipeline._wire_line(f"rival.{name}.atWar", True))
            if relation.get("open_borders"):
                lines.append(pipeline._wire_line(f"rival.{name}.openBorders", True))
            if relation.get("met") is False:
                lines.append(pipeline._wire_line(f"rival.{name}.met", False))
        city_state = diplo_city_states.get(str(rival.get("player_id")))
        if city_state is not None:
            lines.extend(_civ6_city_state_lines(context, name, city_state))
    lines.extend(_civ6_trade_lines(context, rivals, diplomacy))
    history = context.get("history", {})
    if isinstance(history, dict):
        for field, keyfn in (("player_opinions", pipeline._opinion_wire_key),
                             ("player_histories", pipeline._history_wire_key)):
            entries = history.get(field, {})
            if not isinstance(entries, dict):
                continue
            for rival_id, entry in entries.items():
                if not (isinstance(rival_id, str) and rival_id.startswith("PLAYER_") and isinstance(entry, dict)):
                    continue
                text = str(entry.get("text", "")).strip()
                if not text:
                    continue
                value = pipeline._opinion_wire_value(entry) if field == "player_opinions" else text
                lines.append(pipeline._wire_line(keyfn(context, rival_id), value))
    lines.extend(_other_player_lines(context))
    return lines


def _thoughts_section(context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    personality = context.get("personality", {})
    if isinstance(personality, dict):
        identity = personality.get("identity_summary") or personality.get("archetype")
        if isinstance(identity, str) and identity.strip():
            lines.append(pipeline._wire_line("identity", identity.strip()))
    history = context.get("history", {})
    budget = pipeline.JOURNAL_WIRE_CHAR_BUDGET
    used = 0
    if isinstance(history, dict):
        memory = history.get("memory_summary")
        if isinstance(memory, str) and memory.strip():
            lines.append(pipeline._wire_line("history.memory", memory.strip()[:400]))
        thought_rows = [entry for entry in history.get("thought_memory", []) if isinstance(entry, dict)]
        thought_rows = list(reversed(thought_rows))
        kept_thoughts: list[str] = []
        for entry in thought_rows:
            turn = int(entry.get("turn", 0))
            chunk: list[str] = []
            for field in ("situation", "strategy"):
                text = entry.get(field)
                if isinstance(text, str) and text.strip():
                    chunk.append(pipeline._wire_line(f"T{turn}.{field}", pipeline._clip_thought(text)))
            extra = sum(len(row) + 1 for row in chunk)
            if used + extra > budget and kept_thoughts:
                break
            kept_thoughts.extend(chunk)
            used += extra
        lines.extend(reversed(kept_thoughts))
        for note in history.get("remembered", []):
            if not isinstance(note, dict) or not str(note.get("text", "")).strip():
                continue
            expires = note.get("expires_turn")
            until = "forever" if expires is None else f"until T{expires}"
            lines.append(pipeline._wire_line(
                f"remembered.T{int(note.get('turn', 0))}", f"{str(note['text']).strip()} ({until})"
            ))
    lines.extend(civ6_apply_results.thoughts_lines(context))
    return lines


def _advice_section(context: dict[str, Any]) -> list[str]:
    lines = [
        "- In peacetime, scouts and warriors explore fog. Do not fortify the whole army, because units left "
        "without orders stay where they are.",
        "- Settlers should found or walk toward a settle tile; do not sleep on your own city.",
        f"- {coaching.CIV6_EXPANSION_COACHING}",
        "- Before you finish: issue one command for each entry under REQUIRED COMMANDS.",
    ]
    capital = coaching.capital_founding_coaching(context)
    if capital:
        lines.append(f"- {capital}")
    if coaching.settler_present(context):
        lines.append(
            "- Settlers are priority targets: when you have one, keep a military escort or nearby defender every "
            "turn until it founds or reaches safety."
        )
        lines.append(f"- Settler: {coaching.CIV6_SETTLER_MAP_ADVICE}")
        if any(isinstance(c, dict) and c.get("kind") == "found_city" for c in context.get("legal_commands", []) or []):
            lines.append(
                "- FoundCity is legal this turn for at least one Settler — strongly consider founding now unless "
                "a clearly better tile is within about three moves."
            )
    lines.append(f"- {coaching.CIV6_CHAT_VARIETY_COACHING}")
    lines.extend(combat_wire.tactics_advice_lines(context))
    lines.append("- Pick research and civics before they run out so science and culture are never wasted.")
    lines.append(
        "- For legal.research.tech / legal.research.civic, pick only from the listed options — never re-pick a "
        "tech or civic you already finished."
    )
    if _has_queue_production(context):
        lines.append("- Do not queue production that is already building.")
    return lines


def build_civ6_response_instructions(snapshot: dict[str, Any]) -> str:
    """RESPONSE INSTRUCTIONS + OPTIONAL COMMANDS + REQUIRED COMMANDS (Civ5 layout)."""
    required = _civ6_required_rows(snapshot)
    count = len(required)
    count_lines = _count_lines(count)
    event_count = sum(1 for key, _ in required if key.startswith("Event."))

    example_rows = ['"commands.required.count":' + str(count)]
    for index, (key, value) in enumerate(required, start=1):
        if key.endswith(".command") or key.endswith(".production"):
            example_rows.append(f'"{index}.{key}":"{value.split(" | ")[0]}"')
        else:
            example_rows.append(f'"{index}.{key}":"..."')
    example_rows.append(f'"{count + 1}.chat.all":"Hello rivals."')

    resp = [
        "=== RESPONSE INSTRUCTIONS ===",
        "Reply with ONE JSON object containing every field below — no code fences, no text outside the object.",
        'Prefix JSON keys with the REQUIRED COMMANDS row number (e.g. "3.scout_1.command"); the host strips the numeric prefix.',
        "If the API provides separate thinking/reasoning text, keep prose there if you like; game-order keys must be in the JSON object.",
        *count_lines,
        "In your JSON object put commands.required.count first (must equal the required row count), then prose keys "
        "(map reads, thought.*, Event.*), then numbered game-order keys (unitId.command, cityName.production, legal.*, chat.*).",
        "",
        "Prose and notes (JSON string values; first person as this leader):",
        "strategicmap.read = one paragraph — landmasses, coasts, fog, rivals, expansion lanes.",
        *(["tacticalmap.read = one short paragraph on the attached tactical close-up — exact (x,y) of your units, "
            "threats, terrain and the tiles you will move to."] if "tacticalmap.read" in {k for k, _ in required} else []),
        "thought.situation = what matters on the board this turn.",
        "thought.freethinking = optional extended inner monologue.",
        "thought.strategy = long-term path to victory, then this turn's plan: for each REQUIRED COMMANDS row (and each "
        "optional command you will issue), state what you will command and why — prose only, no wire keys here.",
        "Event.<Name>.log = required attention notes (see REQUIRED COMMANDS).",
        "remember = text plus duration; store deals, rival impressions, war aims, and multi-turn plans. opinion.* / history.* as needed.",
        f"Required Event.* logs this turn: {event_count} (numbered under REQUIRED COMMANDS).",
        "",
        "Game orders (executable JSON keys — must match REQUIRED COMMANDS rows):",
        "unitId.command = MoveTo(x,y) | AttackTo(x,y) | FoundCity | Fortify | Skip "
        "(one option per unit from its row; MoveTo(x,y) = any destination tile, the unit walks toward it).",
        "cityName.production = UNIT_* | BUILDING_* | PROJECT_* from that city's listed options (only when "
        "currentProduction is NONE, or to switch on purpose).",
        f"legal.research.tech, legal.research.civic, chat.all, {chat_dm_examples(snapshot)} — see OPTIONAL COMMANDS.",
        "Do not use Skip when another option is listed.",
        "",
        "GOOD JSON (entire reply — row numbers on keys; host strips the prefix):",
        "  {" + ", ".join(example_rows) + "}",
        "",
        "Command rules:",
        "- Movement: unitId.command = MoveTo(x,y) with any destination. One MoveTo spends the unit's remaining "
        "moves (unitId.moves of unitId.maxMovement) along the game's route; pick a destination at least that far "
        "on open ground. Hills, forest, and rivers cost extra; a step needs its full cost from the moves left, "
        "except that a unit that has not moved this turn can always enter one adjacent tile, however rough "
        "(that uses all its movement). Illegal or unreachable tiles are ignored.",
        f"- Coordinates: {coaching.civ6_y_axis_phrase(snapshot)} and x increases east; see the GAME "
        "section for X-wrap.",
        f"- {coaching.CIV6_UNIT_STACKING_GUIDANCE}",
        f"- {coaching.CIV6_MOVE_THEN_ATTACK_GUIDANCE}",
        "- Attacks: AttackTo(x,y) options appear on the unit's own row only when a visible enemy (a civ you are at "
        "war with, or barbarians) is in reach — adjacent for melee, within range for ranged units.",
        "- A city with currentProduction set: leave cityName.production out unless you really mean to switch.",
        "- Hybrid control: " + native_fallback_policy(snapshot),
        "- Optional commands (chat, research, civics, remember) are encouraged when useful; chat.all only when you have an original line.",
    ]
    if any(isinstance(c, dict) and c.get("kind") == "found_city" for c in snapshot.get("legal_commands", [])):
        resp.append("- FoundCity is optional: prefer founding this turn on a decent tile (fresh water/coast, not "
                    "cramped). Walking up to ~3 tiles for a clearly better site is fine; long treks are not.")
        if not snapshot.get("your_cities"):
            # Seats 1-4 read the line above as licence for 25-tile treks toward a far
            # landmass while cityless for 10+ turns.
            resp.append("- You have no city yet: every turn without a capital costs all your science, culture and "
                        "production. Settle the capital here or within about 3 tiles; do not march toward a distant "
                        "landmass first.")
        else:
            resp.append("- You already have a capital: still expand — FoundCity with idle Settlers rather than "
                        "guarding them in the capital forever.")
    resp.extend(f"- {line}" for line in _civ6_chat_rules(snapshot))

    # OPTIONAL COMMANDS
    optional_keys: list[tuple[str, str]] = []
    empire_tokens = _civ6_empire_tokens(snapshot)
    for key in ("legal.research.tech", "legal.research.civic"):
        if empire_tokens.get(key):
            optional_keys.append((key, " | ".join(empire_tokens[key])))
    for key, values in empire_tokens.items():
        if key not in ("legal.research.tech", "legal.research.civic"):
            optional_keys.append((key, " | ".join(values[:12])))
    from sidecar import civ6_governance as governance_wire

    optional_keys.extend(governance_wire.optional_key_hints(snapshot))
    from sidecar import civ6_diplomacy as diplomacy_wire

    optional_keys.extend(diplomacy_wire.optional_key_hints(snapshot))
    optional_keys.append(("chat", f"chat.all | {chat_dm_examples(snapshot)}"))
    optional_keys.append(("remember", "text (duration N turns | forever)"))
    from sidecar import civ6_priorities

    prio_lines = civ6_priorities.prompt_lines(snapshot)
    if prio_lines:
        optional_keys.append((civ6_priorities.REPLY_KEY, "key:level, key:level | none (see BUILD PRIORITIES)"))
    required_keys = {key for key, _ in required}
    units = [u for u in snapshot.get("your_units", []) if isinstance(u, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    unit_tokens = _civ6_unit_tokens(snapshot)
    for unit in units:
        unit_id = str(unit.get("unit_id"))
        key = f"{wire_ids.get(unit_id, unit_id)}.command"
        if key in required_keys or not unit_tokens.get(unit_id):
            continue
        optional_keys.append((key, " | ".join(unit_tokens[unit_id])))
    city_tokens = _civ6_city_tokens(snapshot)
    for city in snapshot.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        name = pipeline._city_prompt_name(city)
        for prop, tokens in city_tokens.get(str(city.get("city_id")), {}).items():
            key = f"{name}.{prop}"
            if key in required_keys:
                continue
            optional_keys.append((key, " | ".join(tokens)))

    opt = [
        "=== OPTIONAL COMMANDS ===",
        "OPTIONAL COMMANDS are encouraged every turn — not leftovers. Required rows are only the minimum.",
        f"Issue as many optional commands as you want this turn: chat.all, {chat_dm_examples(snapshot)}, research, civics, remember, "
        "extra unit/city orders, and any other listed shape.",
        "There is no cap. Use numbered JSON keys that continue after the last required row.",
        "Use only shapes listed here or on unit/city rows.",
        *count_lines,
        "",
        "Optional JSON keys:",
        "",
    ]
    for offset, (key, value) in enumerate(optional_keys, start=count + 1):
        opt.append(f'  "{offset}.{key}": "{value}",')
    opt.append("")
    opt.append("Reference catalogs (not numbered JSON keys):")
    if units:
        opt.append(pipeline._wire_line("legal.validUnits", " | ".join(
            wire_ids.get(str(u.get("unit_id")), "unit") for u in units)))
    cities = [c for c in snapshot.get("your_cities", []) if isinstance(c, dict)]
    if cities:
        opt.append(pipeline._wire_line("legal.validCities", " | ".join(pipeline._city_prompt_name(c) for c in cities)))
        opt.extend(economy_wire.production_catalog_lines(snapshot, city_tokens))
    opt.append("thought.freethinking = optional free-form reflection (not counted as required).")
    if prio_lines:
        opt.append("")
        opt.extend(prio_lines)

    req = [
        "=== REQUIRED COMMANDS ===",
        *count_lines,
        "Return one JSON object containing every required key below (host strips the numeric prefix on each key).",
        "Event.* / thought.* / map reads = prose strings; unitId.command / cityName.production = game orders — "
        "copy exactly one option from the row.",
        "",
        "Required JSON keys:",
        "",
        f'  "commands.required.count": {count},',
        f"  (echo the count above, then every numbered row 1..{count})" if count else "  (no numbered rows this turn)",
        "",
    ]
    placed_orders_header = False
    for index, (key, value) in enumerate(required, start=1):
        if not placed_orders_header and (key.endswith(".command") or key.endswith(".production")):
            req.append("  # --- UNIT / CITY ORDERS ---")
            placed_orders_header = True
        req.append(f'  "{index}.{key}": "{value}",')
    return "\n".join(resp) + "\n\n" + "\n".join(opt) + "\n\n" + "\n".join(req)


def build_civ6_wire_prompt(context: dict[str, Any], map_stats: list[str] | None = None) -> str:
    """Sectioned Civ VI prompt in the Civ5 layout (everything above RESPONSE INSTRUCTIONS)."""
    sections = [
        pipeline._wire_section("GAME", _game_section(context, map_stats)),
        pipeline._wire_section("EMPIRE", _empire_section(context)),
        pipeline._wire_section("DIPLOMACY", _diplomacy_section(context)),
    ]
    opponents = _opponents_section(context)
    if opponents:
        sections.append(pipeline._wire_section("OPPONENTS", opponents))
    rankings = rankings_wire.world_rankings_lines(context)
    if rankings:
        sections.append(pipeline._wire_section("WORLD RANKINGS", rankings))
    from sidecar import civ6_governance as governance_wire

    gov_lines = governance_wire.prompt_lines(context)
    if gov_lines:
        sections.append(pipeline._wire_section("GOVERNMENT & CULTURE", gov_lines))
    war_lines = combat_wire.war_section_lines(context)
    if war_lines:
        sections.append(pipeline._wire_section("WAR", war_lines))
    attention = list(coaching.collect_civ6_attention_items(context if isinstance(context, dict) else {}))
    attention.extend(civ6_apply_results.blocked_attention_lines(context if isinstance(context, dict) else {}))
    attention.extend(combat_wire.attention_items(context))
    idle = [
        pipeline._build_unit_wire_id_map([u for u in context.get("your_units", []) if isinstance(u, dict)]).get(
            str(u.get("unit_id")), "unit")
        for u in context.get("your_units", []) if isinstance(u, dict) and u.get("needs_orders")
    ]
    if idle:
        attention.append(f"***Idle units: {', '.join(sorted(idle))}***")
    attention.extend(economy_wire.attention_items(context))
    attention.extend(gs_wire.attention_items(context))
    attention.extend(governance_wire.attention_items(context))
    if attention:
        sections.append(pipeline._wire_section("ATTENTION", attention))
    thoughts = _thoughts_section(context)
    if thoughts:
        sections.append(pipeline._wire_section("THOUGHTS", thoughts))
    sections.append(pipeline._wire_section("ADVICE", _advice_section(context)))
    return "\n\n".join(sections)


def build_civ6_playable_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Slim model-facing view — mirrors pipeline_v2.build_playable_context for Civ VI."""
    context = pipeline.strip_empty_fields(copy.deepcopy(snapshot))
    if not isinstance(context, dict):
        return {}
    known_map = context.get("known_map")
    if isinstance(known_map, dict):
        known_map.pop("plots", None)
        known_map.pop("visibility_grid", None)
        image = known_map.get("image")
        if isinstance(image, dict):
            image["attached"] = pipeline.map_image_attach_turn(snapshot)
    legal = context.get("legal_commands")
    if isinstance(legal, list):
        compact_legal: list[dict[str, Any]] = []
        for command in legal:
            if not isinstance(command, dict):
                continue
            compact_legal.append({
                "command_id": command.get("command_id"),
                "kind": command.get("kind"),
                "fixed_arguments": copy.deepcopy(command.get("fixed_arguments", {})),
                "parameter_domains": copy.deepcopy(command.get("parameter_domains", {})),
                "runtime_status": command.get("runtime_status"),
            })
        context["legal_commands"] = compact_legal
    return context


def build_civ6_model_wire_text(snapshot: dict[str, Any]) -> str:
    map_stats = pipeline._map_wire_stats_from_snapshot(snapshot)
    context = build_civ6_playable_context(snapshot)
    return build_civ6_wire_prompt(context, map_stats=map_stats) + "\n\n" + build_civ6_response_instructions(snapshot)
