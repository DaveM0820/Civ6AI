"""Civ V flat-wire prompt builder."""
from __future__ import annotations

import copy
from typing import Any

from sidecar import pipeline_v2 as pipeline
from sidecar import prompt_gates

HUMAN_UNITS_CONTROL_HINT = (
    "After apply, leftover units still waiting for orders are skipped so the turn can end."
)
HUMAN_CITIES_PRODUCTION_HINT = (
    "After apply, cities with no production queued get auto production so the turn can end."
)
HUMAN_FALLBACK_POLICY = (
    "After apply, leftover units waiting for orders are skipped and cities with no production are set to auto production."
)
AI_UNITS_CONTROL_HINT = (
    "Community Patch AI moves unmoved units after your commands; use stance=fortify|sleep|skip to hold a unit."
)
AI_CITIES_PRODUCTION_HINT = (
    "Cities keep auto production unless you set production."
)
AI_FALLBACK_POLICY = (
    "Community Patch native AI moves unmoved units after your commands; cities keep auto production unless you override."
)

CIV5_EARLY_EXPAND_GATE = {"turn_lte": 15, "turn_scale": "speed"}
CIV5_EARLY_EXPAND_RULES = [
    {
        "when": CIV5_EARLY_EXPAND_GATE,
        "lines": [
            "- Exploration and early expansion are the top priorities: move units into fog every turn, "
            "keep the capital building settlers while you have only one or two cities, move idle settlers "
            "toward good sites, and found when the current tile is the best option listed.",
            "- Before moving, inspect the attached minimap and each unit's position — pick a tile that "
            "advances exploration, expansion, or defense.",
        ],
    },
]


def _civ5_is_human_player(snapshot: dict[str, Any]) -> bool:
    advciv = snapshot.get("advciv")
    if not isinstance(advciv, dict):
        return False
    return advciv.get("default_unit_controller") == "skip_leftover"


def _civ5_unit_control_hint(snapshot: dict[str, Any]) -> str:
    if _civ5_is_human_player(snapshot):
        return HUMAN_UNITS_CONTROL_HINT
    return AI_UNITS_CONTROL_HINT


def _civ5_city_production_hint(snapshot: dict[str, Any]) -> str:
    if _civ5_is_human_player(snapshot):
        return HUMAN_CITIES_PRODUCTION_HINT
    return AI_CITIES_PRODUCTION_HINT


def _civ5_fallback_policy(snapshot: dict[str, Any]) -> str:
    if _civ5_is_human_player(snapshot):
        return HUMAN_FALLBACK_POLICY
    return AI_FALLBACK_POLICY

CIV5_EMPIRE_WIRE: dict[str, tuple[str, str]] = {
    "set_research_tech": ("legal.research.tech", "tech_id"),
    "queue_production": ("legal.production", "build_id"),
    "adopt_social_policy": ("legal.policy", "policy_id"),
    "unlock_policy_branch": ("legal.policyBranch", "policy_branch_id"),
    "adopt_ideology": ("legal.ideology", "policy_branch_id"),
    "choose_maya_bonus": ("legal.mayaBonus", "unit_type_id"),
}

CIV5_UNIT_MISSION_WIRE: dict[str, tuple[str, str]] = {
    "improve_tile": ("improve", "build_id"),
    "automate_unit": ("automate", "automate_id"),
    "discover_tech": ("discover", "apply"),
    "hurry_production": ("hurry", "apply"),
    "trade_mission": ("trade", "apply"),
    "start_golden_age": ("goldenAge", "apply"),
    "create_great_work": ("greatWork", "apply"),
    "spread_religion": ("spread", "apply"),
    "remove_heresy": ("removeHeresy", "apply"),
    "pillage": ("pillage", "apply"),
    "upgrade_unit": ("upgrade", "unit_type_id"),
    "air_patrol": ("intercept", "apply"),
}

CIV5_OPEN_COORD_WIRE: dict[str, str] = {
    "move_unit": "moveTo",
    "attack_target": "attackTo",
    "range_attack": "rangedAttack",
    "rebase": "rebaseTo",
    "paradrop": "paradropTo",
    "nuke": "nukeAt",
}

CIV5_UNIT_POSTURE_KINDS = {
    "unit_posture_fortify": "fortify",
    "unit_posture_heal": "heal",
    "unit_posture_alert": "alert",
    "unit_posture_sleep": "sleep",
    "unit_skip": "skip",
}


def _civ5_block(snapshot: dict[str, Any]) -> dict[str, Any]:
    block = snapshot.get("civ5")
    return block if isinstance(block, dict) else {}


def _civ5_yields(snapshot: dict[str, Any]) -> dict[str, Any]:
    yields = _civ5_block(snapshot).get("yields", {})
    return yields if isinstance(yields, dict) else {}


def _production_label(build_id: Any) -> str:
    if not isinstance(build_id, str) or not build_id.strip():
        return "item"
    text = build_id.strip()
    if text.startswith(("UNIT_", "BUILDING_", "PROJECT_", "PROCESS_")):
        return text
    return pipeline._readable_id(text, "UNIT_")


def _format_amount_with_delta(stock: Any, delta: Any) -> str | None:
    if not isinstance(stock, int):
        return None
    if isinstance(delta, int):
        signed = f"+{delta}" if delta >= 0 else str(delta)
        return f"{stock} ({signed})"
    return str(stock)


def _production_turns_left(production: dict[str, Any]) -> int | None:
    estimated = production.get("estimated_turns_remaining")
    if isinstance(estimated, int) and estimated >= 0:
        return estimated
    cost = production.get("cost")
    progress = production.get("progress")
    per_turn = production.get("production_per_turn")
    if not isinstance(cost, int) or not isinstance(progress, int):
        return None
    if not isinstance(per_turn, int) or per_turn <= 0:
        return None
    remain = cost - progress
    if remain <= 0:
        return 1
    return (remain + per_turn - 1) // per_turn
    if not isinstance(build_id, str) or not build_id.strip():
        return "item"
    text = build_id.strip()
    if text.startswith(("UNIT_", "BUILDING_", "PROJECT_", "PROCESS_")):
        return text
    return pipeline._readable_id(text, "UNIT_")


def _civ5_automate_label(raw: Any) -> str:
    if raw in (0, "0", "INT_0", "AUTOMATE_BUILD", "build"):
        return "build"
    if raw in (1, "1", "INT_1", "AUTOMATE_EXPLORE", "explore"):
        return "explore"
    if isinstance(raw, str) and raw.startswith("AUTOMATE_"):
        return pipeline._readable_id(raw, "AUTOMATE_").lower()
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return "build"


def _civ5_unit_property_parts(command: dict[str, Any]) -> tuple[str, str]:
    kind = str(command.get("kind", ""))
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    if kind in CIV5_OPEN_COORD_WIRE:
        return "", ""
    if kind == "automate_unit":
        return "automate", _civ5_automate_label(fixed.get("automate_id") or fixed.get("data1_id"))
    if kind in CIV5_UNIT_POSTURE_KINDS:
        label = CIV5_UNIT_POSTURE_KINDS[kind]
        if label == "alert":
            return "", ""
        return "stance", label
    if kind == "found_city":
        return "foundCity", "apply"
    if kind == "promote_unit":
        promo = fixed.get("promotion_id")
        if isinstance(promo, str) and promo.strip():
            return "promote", promo.strip()
        return "promote", "apply"
    mission_wire = CIV5_UNIT_MISSION_WIRE.get(kind)
    if mission_wire is not None:
        wire_key, arg_key = mission_wire
        if arg_key == "apply":
            return wire_key, "apply"
        value = fixed.get(arg_key)
        if isinstance(value, str) and value.strip():
            return wire_key, value.strip()
        return wire_key, "apply"
    property_name = kind[0].lower() + kind[1:] if kind else "command"
    return property_name, "apply"


def _legal_kinds_in_snapshot(snapshot: dict[str, Any]) -> set[str]:
    kinds: set[str] = set()
    for command in snapshot.get("legal_commands", []):
        if isinstance(command, dict) and command.get("kind"):
            kinds.add(str(command["kind"]))
    return kinds


def _civ5_command_instruction_lines(legal_kinds: set[str]) -> list[str]:
    lines: list[str] = []
    lines.append("   cityName.production = UNIT_* / BUILDING_* / PROJECT_* / PROCESS_*")
    unit_bits: list[str] = []
    if "move_unit" in legal_kinds:
        unit_bits.append("unitId.moveTo = (x,y)")
    if "rebase" in legal_kinds:
        unit_bits.append("unitId.rebaseTo = (x,y)")
    if "paradrop" in legal_kinds:
        unit_bits.append("unitId.paradropTo = (x,y)")
    if any(k in legal_kinds for k in CIV5_UNIT_POSTURE_KINDS if k != "unit_posture_alert"):
        unit_bits.append("unitId.stance = fortify|skip|sleep|heal")
    if "found_city" in legal_kinds:
        unit_bits.append("unitId.foundCity = apply")
    if "improve_tile" in legal_kinds:
        unit_bits.append("unitId.improve = BUILD_*")
    if "automate_unit" in legal_kinds:
        unit_bits.append("unitId.automate = build|explore")
    if "discover_tech" in legal_kinds:
        unit_bits.append("unitId.discover = apply")
    if "hurry_production" in legal_kinds:
        unit_bits.append("unitId.hurry = apply")
    if "trade_mission" in legal_kinds:
        unit_bits.append("unitId.trade = apply")
    if "start_golden_age" in legal_kinds:
        unit_bits.append("unitId.goldenAge = apply")
    if "create_great_work" in legal_kinds:
        unit_bits.append("unitId.greatWork = apply")
    if "attack_target" in legal_kinds:
        unit_bits.append("unitId.attackTo = (x,y)")
    if "range_attack" in legal_kinds:
        unit_bits.append("unitId.rangedAttack = (x,y)")
    if "nuke" in legal_kinds:
        unit_bits.append("unitId.nukeAt = (x,y)")
    if "spread_religion" in legal_kinds:
        unit_bits.append("unitId.spread = apply")
    if "remove_heresy" in legal_kinds:
        unit_bits.append("unitId.removeHeresy = apply")
    if "pillage" in legal_kinds:
        unit_bits.append("unitId.pillage = apply")
    if "upgrade_unit" in legal_kinds:
        unit_bits.append("unitId.upgrade = UNIT_*")
    if "air_patrol" in legal_kinds:
        unit_bits.append("unitId.intercept = apply")
    if "promote_unit" in legal_kinds:
        unit_bits.append("unitId.promote = PROMOTION_*")
    if unit_bits:
        lines.append("   " + ", ".join(unit_bits))
    if "set_research_tech" in legal_kinds:
        lines.append("   legal.research.tech = TECH_*")
    if "adopt_social_policy" in legal_kinds:
        lines.append("   legal.policy = POLICY_*")
    if "unlock_policy_branch" in legal_kinds:
        lines.append("   legal.policyBranch = POLICY_BRANCH_*")
    if "adopt_ideology" in legal_kinds:
        lines.append("   legal.ideology = POLICY_BRANCH_FREEDOM|ORDER|AUTOCRACY")
    if "choose_maya_bonus" in legal_kinds:
        lines.append("   legal.mayaBonus = UNIT_*")
    if "propose_deal" in legal_kinds:
        lines.append("   cmd.N = CMD_propose_* (see diplomacy.proposal.*)")
    if "respond_to_deal" in legal_kinds:
        lines.append("   cmd.N = diplomacy.pending.N.accept_cmd | reject_cmd")
    if "cancel_deal" in legal_kinds:
        lines.append("   cmd.N = CMD_cancel_DEAL_*")
    if "declare_war" in legal_kinds:
        lines.append(
            "   cmd.N = CMD_declare_war_PLAYER_* "
            "(same-turn war; do not walk into their land)"
        )
    return lines


def _group_civ5_unit_commands(commands: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for command in commands:
        prop_name, value_label = _civ5_unit_property_parts(command)
        if not prop_name:
            continue
        values = grouped.setdefault(prop_name, [])
        if value_label not in values:
            values.append(value_label)
    return grouped


def _compact_civ5_unit_legal_lines(unit_wire_id: str, commands: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for prop_name, values in sorted(_group_civ5_unit_commands(commands).items()):
        lines.append(pipeline._wire_line(f"{unit_wire_id}.{prop_name}", " | ".join(values)))
    return lines


def _group_civ5_city_commands(commands: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for command in commands:
        kind = str(command.get("kind", ""))
        fixed = command.get("fixed_arguments", {})
        if not isinstance(fixed, dict):
            fixed = {}
        if kind == "queue_production":
            prop = "production"
            value = _production_label(fixed.get("build_id"))
        else:
            prop = kind
            value = "apply"
        values = grouped.setdefault(prop, [])
        if value not in values:
            values.append(value)
    return grouped


def _compact_civ5_city_legal_lines(city_name: str, commands: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    grouped = _group_civ5_city_commands(commands)
    for prop_name in ("production",):
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


def _civ5_empire_wire_value(command: dict[str, Any]) -> tuple[str, str] | None:
    kind = str(command.get("kind", ""))
    mapping = CIV5_EMPIRE_WIRE.get(kind)
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


def _compact_civ5_empire_legal_lines(commands: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    grouped: dict[str, list[str]] = {}
    for command in commands:
        pair = _civ5_empire_wire_value(command)
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


_NEED_ORDERS_PROP_ORDER = (
    "moveTo",
    "rebaseTo",
    "paradropTo",
    "improve",
    "automate",
    "foundCity",
    "attackTo",
    "rangedAttack",
    "nukeAt",
    "spread",
    "removeHeresy",
    "pillage",
    "upgrade",
    "intercept",
    "discover",
    "hurry",
    "trade",
    "goldenAge",
    "greatWork",
    "promote",
    "stance",
)


def _civ5_need_orders_available(unit_id: str, snapshot: dict[str, Any]) -> str:
    grouped: dict[str, list[str]] = {}
    for command in snapshot.get("legal_commands", []):
        if not isinstance(command, dict):
            continue
        fixed = command.get("fixed_arguments", {})
        if not isinstance(fixed, dict) or fixed.get("unit_id") != unit_id:
            continue
        kind = str(command.get("kind", ""))
        wire_name = CIV5_OPEN_COORD_WIRE.get(kind)
        if wire_name:
            grouped.setdefault(wire_name, [])
            continue
        prop_name, value_label = _civ5_unit_property_parts(command)
        if not prop_name:
            continue
        values = grouped.setdefault(prop_name, [])
        if value_label and value_label not in values and value_label != "apply":
            values.append(value_label)
    bits: list[str] = []
    seen: set[str] = set()
    for prop_name in _NEED_ORDERS_PROP_ORDER:
        if prop_name not in grouped:
            continue
        seen.add(prop_name)
        values = grouped[prop_name]
        if not values:
            bits.append(prop_name)
        else:
            bits.append(f"{prop_name}={'|'.join(values)}")
    for prop_name in sorted(grouped):
        if prop_name in seen:
            continue
        values = grouped[prop_name]
        if not values:
            bits.append(prop_name)
        else:
            bits.append(f"{prop_name}={'|'.join(values)}")
    if not bits:
        return ""
    return "[" + " | ".join(bits) + "]"


def _civ5_need_orders_move_clause(unit: dict[str, Any], prefix: str) -> str:
    if unit.get("domain_id") == "DOMAIN_AIR":
        return ""
    movement = unit.get("movement", {})
    current = movement.get("current") if isinstance(movement, dict) else None
    if isinstance(current, int):
        tile_word = "tile" if current == 1 else "tiles"
        return f"{prefix} can move {current} {tile_word} this turn"
    return f"{prefix} can move"


def _civ5_unit_has_kind(unit_id: str, snapshot: dict[str, Any] | None, kind: str) -> bool:
    if snapshot is None:
        return False
    for command in snapshot.get("legal_commands", []):
        if not isinstance(command, dict) or command.get("kind") != kind:
            continue
        fixed = command.get("fixed_arguments", {})
        if isinstance(fixed, dict) and fixed.get("unit_id") == unit_id:
            return True
    return False


def _civ5_need_orders_range_clause(unit: dict[str, Any], prefix: str, snapshot: dict[str, Any] | None) -> str:
    unit_id = unit.get("unit_id")
    if not isinstance(unit_id, str) or not _civ5_unit_has_kind(unit_id, snapshot, "range_attack"):
        return ""
    tiles = unit.get("range")
    if not isinstance(tiles, int) or tiles <= 0:
        return ""
    tile_word = "tile" if tiles == 1 else "tiles"
    return f"{prefix} can rangedAttack {tiles} {tile_word}"


def _civ5_need_orders_phrase(unit: dict[str, Any], prefix: str, snapshot: dict[str, Any] | None = None) -> str:
    move_clause = _civ5_need_orders_move_clause(unit, prefix)
    range_clause = _civ5_need_orders_range_clause(unit, prefix, snapshot)
    available = ""
    unit_id = unit.get("unit_id")
    if snapshot is not None and isinstance(unit_id, str):
        available = _civ5_need_orders_available(unit_id, snapshot)
    bits: list[str] = []
    if available:
        bits.append(f"{prefix} can {available}.")
    if move_clause:
        bits.append(move_clause + ("." if range_clause else ""))
    if range_clause:
        bits.append(range_clause + ".")
    if not bits:
        return prefix
    return " ".join(bits)


def _civ5_need_orders_parts(snapshot: dict[str, Any]) -> list[str]:
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    parts: list[str] = []
    for unit in units:
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str) or unit.get("needs_orders") is not True:
            continue
        prefix = wire_ids.get(unit_id, "unit")
        parts.append(_civ5_need_orders_phrase(unit, prefix, snapshot))
    return parts


def _append_civ5_need_orders_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    unit_parts = _civ5_need_orders_parts(snapshot)
    lines.append(pipeline._wire_line(
        "units.needOrders",
        " | ".join(unit_parts) if unit_parts else "(none)",
    ))
    city_parts: list[str] = []
    for city in snapshot.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        production = city.get("production", {})
        item_id = production.get("item_id") if isinstance(production, dict) else None
        if isinstance(item_id, str) and item_id.strip():
            continue
        name = pipeline._city_prompt_name(city)
        city_parts.append(name)
        lines.append(pipeline._wire_line(f"{name}.needsProduction", True))
    lines.append(pipeline._wire_line(
        "cities.needProduction",
        " | ".join(city_parts) if city_parts else "(none)",
    ))


def _append_civ5_unit_situation_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    for unit in units:
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str):
            continue
        prefix = wire_ids.get(unit_id, "unit")
        plot_id = unit.get("plot_id")
        if isinstance(plot_id, str) and plot_id.strip():
            lines.append(pipeline._wire_line(f"{prefix}.position", pipeline._plot_coords_text(plot_id)))
        pipeline._append_unit_stat_wire(lines, prefix, unit)
        if unit.get("promotion_ready"):
            lines.append(pipeline._wire_line(f"{prefix}.promotionReady", True))
    _append_civ5_settle_wire(lines, snapshot)


def _settle_resource_label(resource_id: str) -> str:
    return pipeline._readable_id(resource_id, "RESOURCE_")


def _format_settle_tile(tile: dict[str, Any], with_distance: bool = False) -> str:
    x = tile.get("x")
    y = tile.get("y")
    coord = f"({x},{y})"
    if with_distance:
        distance = tile.get("distance")
        if isinstance(distance, int) and distance > 0:
            coord += f"+{distance}"
    tags: list[str] = []
    if tile.get("coast") is True:
        tags.append("coast")
    elif tile.get("lake") is True:
        tags.append("lake")
    else:
        tags.append("inland")
    if tile.get("river") is True:
        tags.append("river")
    else:
        tags.append("dry")
    if tile.get("hills") is True:
        tags.append("hills")
    if tile.get("ruins") is True:
        tags.append("ruins")
    resources = tile.get("resources")
    if isinstance(resources, list):
        names = [_settle_resource_label(item) for item in resources if isinstance(item, str) and item.strip()]
        if names:
            tags.append(",".join(names))
    return f"{coord} {' '.join(tags)}".strip()


def _append_civ5_settle_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    sites = _civ5_block(snapshot).get("settle_sites")
    if not isinstance(sites, list) or not sites:
        return
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    for site in sites:
        if not isinstance(site, dict):
            continue
        unit_id = site.get("unit_id")
        if not isinstance(unit_id, str):
            continue
        prefix = wire_ids.get(unit_id, "settler")
        here = site.get("here")
        if isinstance(here, dict):
            lines.append(pipeline._wire_line(f"{prefix}.settle.here", _format_settle_tile(here)))
        look = site.get("look")
        look_tiles = [tile for tile in look if isinstance(tile, dict)] if isinstance(look, list) else []
        if look_tiles:
            parts = [_format_settle_tile(tile, True) for tile in look_tiles]
            lines.append(pipeline._wire_line(f"{prefix}.settle.look", " | ".join(parts)))
        else:
            lines.append(pipeline._wire_line(
                f"{prefix}.settle.look",
                "(none — current tile is the best revealed site)",
            ))


def _append_civ5_city_situation_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    cities = [city for city in snapshot.get("your_cities", []) if isinstance(city, dict)]
    for city in cities:
        name = pipeline._city_prompt_name(city)
        lines.append(pipeline._wire_line(f"{name}.population", int(city.get("population", 1))))
        if city.get("is_capital"):
            lines.append(pipeline._wire_line(f"{name}.capital", True))
        production = city.get("production", {})
        if isinstance(production, dict) and production.get("item_id"):
            label = _production_label(production["item_id"])
            turns = _production_turns_left(production)
            if turns is not None:
                turn_word = "turn" if turns == 1 else "turns"
                label = f"{label} ({turns} {turn_word} left)"
            lines.append(pipeline._wire_line(f"{name}.currentProduction", label))


def _append_civ5_empire_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    empire = snapshot.get("your_empire", {})
    if not isinstance(empire, dict):
        return
    yields = _civ5_yields(snapshot)
    pipeline._append_int_wire(lines, "empire.score", empire.get("score"))
    cities = [city for city in snapshot.get("your_cities", []) if isinstance(city, dict)]
    if cities:
        lines.append(pipeline._wire_line("empire.cities", len(cities)))
    gold = empire.get("gold")
    if not isinstance(gold, int):
        gold = yields.get("gold")
    gold_line = _format_amount_with_delta(gold, empire.get("gold_per_turn"))
    if gold_line is not None:
        lines.append(pipeline._wire_line("empire.gold", gold_line))
    research = empire.get("research", {})
    if not isinstance(research, dict):
        research = {}
    science_rate = research.get("research_per_turn")
    if not isinstance(science_rate, int):
        science_rate = yields.get("science")
    progress = research.get("progress")
    cost = research.get("cost")
    if isinstance(progress, int) and isinstance(cost, int) and isinstance(science_rate, int):
        signed = f"+{science_rate}" if science_rate >= 0 else str(science_rate)
        lines.append(pipeline._wire_line("empire.science", f"{progress}/{cost} ({signed})"))
    elif isinstance(science_rate, int):
        signed = f"+{science_rate}" if science_rate >= 0 else str(science_rate)
        lines.append(pipeline._wire_line("empire.science", signed))
    commerce = empire.get("commerce", {})
    culture_block = commerce.get("culture", {}) if isinstance(commerce, dict) else {}
    if not isinstance(culture_block, dict):
        culture_block = {}
    culture_stock = culture_block.get("stored")
    culture_rate = culture_block.get("rate")
    if not isinstance(culture_rate, int):
        culture_rate = yields.get("culture")
    culture_line = _format_amount_with_delta(culture_stock, culture_rate)
    if culture_line is None and isinstance(culture_rate, int):
        signed = f"+{culture_rate}" if culture_rate >= 0 else str(culture_rate)
        culture_line = signed
    if culture_line is not None:
        lines.append(pipeline._wire_line("empire.culture", culture_line))
    religion = empire.get("religion", {})
    if not isinstance(religion, dict):
        religion = {}
    faith_stock = religion.get("faith")
    if not isinstance(faith_stock, int):
        faith_stock = yields.get("faith")
    faith_line = _format_amount_with_delta(faith_stock, religion.get("faith_per_turn"))
    if faith_line is None and isinstance(yields.get("faith"), int):
        faith_line = _format_amount_with_delta(yields.get("faith"), 0)
    if faith_line is not None:
        lines.append(pipeline._wire_line("empire.faith", faith_line))
    happiness = yields.get("happiness")
    if isinstance(happiness, int):
        lines.append(pipeline._wire_line("empire.happiness", happiness))
    pipeline._append_id_wire(lines, "empire.research.tech", research.get("tech_id"))
    research_tech = _civ5_block(snapshot).get("research_tech")
    if isinstance(research_tech, str) and research_tech.strip():
        if research.get("tech_id") != research_tech:
            pipeline._append_id_wire(lines, "empire.research.current", research_tech)
    pipeline._append_id_wire(lines, "empire.religion.state", religion.get("state_religion_id"))
    if religion.get("has_pantheon") is True:
        lines.append(pipeline._wire_line("empire.religion.pantheon", True))
    if religion.get("has_religion") is True:
        lines.append(pipeline._wire_line("empire.religion.founded", True))
    civics = empire.get("civics", [])
    if isinstance(civics, list) and civics:
        labels: list[str] = []
        for item in civics:
            if isinstance(item, dict):
                civic_id = item.get("id")
                if isinstance(civic_id, str) and civic_id.strip():
                    labels.append(civic_id)
            elif isinstance(item, str) and item.strip():
                labels.append(item)
        if labels:
            lines.append(pipeline._wire_line("empire.policies", " | ".join(labels)))
    unit_counts = empire.get("unit_counts", {})
    if isinstance(unit_counts, dict):
        for field in ("total", "military", "settlers", "idle"):
            pipeline._append_int_wire(lines, f"empire.units.{field}", unit_counts.get(field))
    pipeline._append_int_wire(lines, "empire.culture.nextPolicy", culture_block.get("next_policy_cost"))
    pipeline._append_int_wire(lines, "empire.policies.free", culture_block.get("free_policies"))


def _append_civ5_rival_wire(lines: list[str], rival: dict[str, Any]) -> None:
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


def build_civ5_role_instruction(snapshot: dict[str, Any]) -> str:
    personality = snapshot.get("personality", {})
    leader = personality.get("leader_name", personality.get("leader_id", "the seated leader"))
    civ_id = personality.get("civilization_id")
    civ_label = pipeline._readable_id(civ_id, "CIVILIZATION_") if civ_id else ""
    role = f"You are {leader}"
    if civ_label:
        role += f", playing as the {civ_label} civilization"
    attach_map = pipeline.map_image_attach_turn(snapshot)
    map_clause = (
        " A minimap image is attached with each turn — read geography and unit positions from it. "
        if attach_map else ""
    )
    gandhi_clause = pipeline._gandhi_role_clause() if pipeline._is_gandhi_leader(snapshot) else ""
    return (
        f"{role}, in a live Civilization V multiplayer match. "
        f"{gandhi_clause}"
        "Full role-play mode: you are this leader — dramatic, recognizable, and impossible to "
        "mistake for anyone else. Match their historical voice, rhetorical habits, values, and "
        "temper (grandeur, austerity, wit, menace, piety, melancholy, etc.). "
        "thought.situation, thought.strategy, decision_summary, and every chat line should sound "
        "like them thinking and speaking, not a neutral analyst. "
        "Diplomacy and rival psychology are part of the game — actively cultivate relationships, "
        "trades, and alliances (or rivalries) aligned with your path to victory; every player is "
        "trying to win. "
        "Play to win; personality colors prose, not strategy. "
        "Chat adds personality but should not crowd every turn: aim for a meaningful public line every "
        "5-10 turns when something fits, and reply to fresh DMs. Skip generic filler. "
        f"Use only facts from the prompt.{map_clause}"
        "After your response the host applies only your explicit overrides; "
        f"{_civ5_fallback_policy(snapshot)}"
    )


def _civ5_required_order_bullets(snapshot: dict[str, Any], legal_kinds: set[str]) -> list[str]:
    bullets: list[str] = []
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    promo_units = sorted({
        wire_ids.get(str(unit.get("unit_id")))
        for unit in units
        if unit.get("promotion_ready") is True and isinstance(unit.get("unit_id"), str)
    } - {None})  # type: ignore[arg-type]
    if "adopt_social_policy" in legal_kinds or "unlock_policy_branch" in legal_kinds:
        bullets.append(
            "- Set legal.policy and/or legal.policyBranch this turn — the policy screen blocks End Turn until you adopt or unlock."
        )
    if promo_units and "promote_unit" in legal_kinds:
        bullets.append(
            "- Set unitId.promote = PROMOTION_* for each promotion-ready unit: "
            + ", ".join(promo_units)
            + "."
        )
    if "choose_maya_bonus" in legal_kinds:
        bullets.append(
            "- Set legal.mayaBonus = UNIT_* this turn — Maya Long Count blocks End Turn until you choose."
        )
    empire = snapshot.get("your_empire", {})
    unit_counts = empire.get("unit_counts", {}) if isinstance(empire, dict) else {}
    cities = [city for city in snapshot.get("your_cities", []) if isinstance(city, dict)]
    settlers = unit_counts.get("settlers", 0) if isinstance(unit_counts, dict) else 0
    if len(cities) == 1 and isinstance(settlers, int) and settlers == 0:
        capital_name = pipeline._city_prompt_name(cities[0]) if cities else "capital"
        bullets.append(
            f"- Expansion: one city and no settler yet — set {capital_name}.production = UNIT_SETTLER "
            f"this turn. Do not queue a worker first."
        )
    return bullets


def _civ5_chat_rule_lines(snapshot: dict[str, Any]) -> list[str]:
    lines = list(pipeline._chat_voice_guidance(snapshot))
    lines.append(
        "chat.all is broadcast to every major civilization — do not reveal military plans, weak cities, "
        "or hidden ambitions; keep sensitive details in private DMs."
    )
    lines.append(
        "Private messages are tagged by turn (chat.private.tN.*); reply only to DMs from this turn, "
        "not older lines."
    )
    lines.append("Proactively DM rivals when you have trade bait, probes, or taunts worth sending.")
    rivals: list[str] = []
    for rival in snapshot.get("known_players", [])[:12]:
        if not isinstance(rival, dict):
            continue
        player_id = str(rival.get("player_id", ""))
        if not player_id:
            continue
        rivals.append(pipeline._rival_leader_name(rival))
    if rivals:
        lines.append("DM recipients: " + "; ".join(rivals))
    current_turn = int(snapshot.get("decision", {}).get("turn", 0))
    diplomacy = snapshot.get("diplomacy", {})
    inbox = diplomacy.get("private_inbox", []) if isinstance(diplomacy, dict) else []
    this_turn_dms: list[str] = []
    for message in inbox:
        if not isinstance(message, dict):
            continue
        if int(message.get("turn", -1)) != current_turn:
            continue
        from_id = str(message.get("from_player_id", "")).strip()
        if not from_id:
            continue
        this_turn_dms.append(f"{pipeline._player_chat_name(snapshot, from_id)} ({from_id})")
    if this_turn_dms:
        lines.append(
            "DMs received this turn: " + "; ".join(this_turn_dms)
            + " — you may reply privately if you have something worth saying."
        )
    summary = snapshot.get("strategic_summary")
    if isinstance(summary, dict):
        for alert in summary.get("diplomacy_alerts", []):
            if not isinstance(alert, dict) or alert.get("kind") != "FIRST_MEET":
                continue
            text = str(alert.get("text", "")).strip()
            if text:
                lines.append(text)
    lines.append("chat.all should be rare — skip most turns; silence is normal.")
    return lines


def build_civ5_instructions_preamble(snapshot: dict[str, Any]) -> str:
    personality = snapshot.get("personality", {})
    leader = personality.get("leader_name", personality.get("leader_id", "Leader"))
    civ_id = personality.get("civilization_id")
    civ_label = pipeline._readable_id(civ_id, "CIVILIZATION_") if civ_id else ""
    leader_label = leader + (f", playing as the {civ_label} civilization in Civilization V" if civ_label else "")
    return "\n".join([
        "=== INSTRUCTIONS ===",
        f"You are {leader_label}.",
        "Read CURRENT SITUATION, MAP, and LEGAL COMMANDS below.",
        "Reply with one key = value line per statement. Never JSON, braces, objects, or code fences.",
        "Example:",
        "thought.situation = The river valley is still empty of rivals.",
        "thought.strategy = Scout south, then settle a second city.",
        "decision_summary = Move unitId to (14,22); keep settler in the queue.",
        "unitId.moveTo = (14,22)",
        "cityName.production = UNIT_SETTLER",
        "legal.research.tech = TECH_POTTERY",
        "The host ends your turn automatically after this response.",
    ])


def build_civ5_response_instructions(snapshot: dict[str, Any]) -> str:
    legal_kinds = _legal_kinds_in_snapshot(snapshot)
    command_lines = _civ5_command_instruction_lines(legal_kinds)
    need_orders = _civ5_need_orders_parts(snapshot)

    human = _civ5_is_human_player(snapshot)
    leftover_clause = (
        "Leftover awake units are skipped after apply; required policy, promotion, and Maya choices must be set when listed."
        if human
        else "Community Patch AI moves leftover units."
    )
    production_clause = (
        "Set cityName.production if you want a specific item; otherwise auto production is applied after your commands."
        if human
        else "Cities keep Community Patch auto-production unless you set cityName.production = UNIT_* / BUILDING_* / PROJECT_* / PROCESS_*."
    )

    lines = [
        "=== REQUIRED ORDERS THIS TURN ===",
        (
            "- Needs orders: "
            + (" | ".join(need_orders) if need_orders else "(none)")
            + ". Brackets list the order types available for that unit this turn. "
            "You may also order any other unit this turn, even if it does not need orders. "
            f"{leftover_clause}"
        ),
        (
            f"- Cities with no currentProduction are listed in cities.needProduction. {production_clause}"
        ),
    ]
    for bullet in _civ5_required_order_bullets(snapshot, legal_kinds):
        lines.append(bullet)
    if prompt_gates.matches(snapshot, CIV5_EARLY_EXPAND_GATE):
        strategy_line = (
            "2. thought.strategy = your long-term path to victory — exploration, expansion "
            "(settlers and new cities), and concrete actions for this turn"
        )
    else:
        strategy_line = "2. thought.strategy = your path to victory and this turn's actions"
    lines.extend([
        "",
        "Required reply format (in this order):",
        "1. thought.situation = your read of the board in this leader's inner voice",
        strategy_line,
        "3. opinion.LeaderName = one short line when your view of a met rival changes; omit unchanged rivals",
        "4. history.LeaderName = only on a major relationship event this turn (first meet, deal, war)",
        "5. decision_summary = one line naming concrete actions",
        "6. Commands —",
    ])
    if command_lines:
        lines.extend(command_lines)
    else:
        lines.append("   (no override commands available this turn)")
    lines.extend([
        "7. chat.all / chat.LeaderName (if chat.public.* has a line from another player this turn, "
        "reply this turn; otherwise optional and sparse):",
        "",
        "Rules:",
        f"- The host applies your overrides first; {_civ5_fallback_policy(snapshot)}",
    ])
    lines.extend(prompt_gates.gated_lines(snapshot, CIV5_EARLY_EXPAND_RULES))
    lines.extend([
        "- Movement: set unitId.moveTo = (x,y) using coordinates on the attached minimap (axis ticks) and unitId.position in CURRENT SITUATION.",
        "- Do not walk into a rival's land to start a war. That only opens a Yes/No popup. "
        "Use cmd.N = CMD_declare_war_PLAYER_* the same turn, then move.",
        "- One moveTo spends the remaining tiles in units.needOrders / unitId.maxMovement this turn. "
        "Pick a dest that far on open ground; a one-tile hop wastes leftover movement. "
        "Hills and forest cost extra, so a 2-move unit may only reach one rough tile.",
        "- Do not invent unit ids. Illegal or unreachable tiles are ignored.",
        "- You may still order units that are not listed.",
        "- thought.tN.situation lines are your prior board reads — use them for long-term memory.",
        "- opinion.* lines are your stored rival view — emit opinion.LeaderName only when it changes.",
        "- history.* is append-only; add a fragment only for major relationship shifts.",
    ])
    if "found_city" in legal_kinds:
        lines.append(
            "- foundCity is optional: it founds on the settler's current tile only. "
            "If unitId.settle.look lists a better coast, river, or resource tile, "
            "moveTo that tile (or toward it) this turn instead of founding."
        )
    if "rebase" in legal_kinds:
        lines.append(
            "- Aircraft rebase with unitId.rebaseTo = (x,y) to a city or carrier; "
            "they do not walk. Strike with unitId.rangedAttack = (x,y); intercept with unitId.intercept = apply."
        )
    if "range_attack" in legal_kinds and "rebase" not in legal_kinds:
        lines.append(
            "- Ranged units strike with unitId.rangedAttack = (x,y); that is not a walk. "
            "Use moveTo only to reposition. units.needOrders names the strike range."
        )
    if "spread_religion" in legal_kinds or "remove_heresy" in legal_kinds:
        lines.append(
            "- Religious units walk with moveTo, then unitId.spread = apply or "
            "unitId.removeHeresy = apply on the current city tile."
        )
    if "paradrop" in legal_kinds:
        lines.append("- Paratroopers jump with unitId.paradropTo = (x,y).")
    if "nuke" in legal_kinds:
        lines.append("- Nuclear units strike with unitId.nukeAt = (x,y).")
    lines.extend(f"- {line}" for line in _civ5_chat_rule_lines(snapshot))
    lines.extend([
        pipeline._wire_line("units.nativeControl", _civ5_unit_control_hint(snapshot)),
        pipeline._wire_line("cities.nativeProduction", _civ5_city_production_hint(snapshot)),
    ])
    return "\n".join(lines)


def build_civ5_wire_prompt(context: dict[str, Any], map_stats: list[str] | None = None) -> str:
    situation: list[str] = []
    map_lines: list[str] = []
    legal_lines: list[str] = []

    decision = context.get("decision", {})
    personality = context.get("personality", {})
    leader = personality.get("leader_name", personality.get("leader_id", "Leader"))
    player_id = decision.get("player_id", "PLAYER_0")
    civ_id = personality.get("civilization_id")
    civ_label = pipeline._readable_id(civ_id, "CIVILIZATION_") if civ_id else ""
    situation.append(pipeline._wire_line("player", pipeline._player_identity_phrase(leader, civ_label, player_id)))
    situation.append(pipeline._wire_line("turn", int(decision.get("turn", 0))))

    history = context.get("history", {})
    if isinstance(history, dict):
        for entry in history.get("thought_memory", []):
            if not isinstance(entry, dict):
                continue
            turn = int(entry.get("turn", 0))
            prior_situation = entry.get("situation")
            if isinstance(prior_situation, str) and prior_situation.strip():
                situation.append(pipeline._wire_line(
                    f"thought.t{turn}.situation",
                    pipeline._clip_thought(prior_situation),
                ))
        opinions = history.get("player_opinions", {})
        if isinstance(opinions, dict):
            for player_id, entry in opinions.items():
                if not isinstance(player_id, str) or not player_id.startswith("PLAYER_"):
                    continue
                if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
                    continue
                situation.append(pipeline._wire_line(
                    pipeline._opinion_wire_key(context, player_id),
                    pipeline._opinion_wire_value(entry),
                ))
        histories = history.get("player_histories", {})
        if isinstance(histories, dict):
            for player_id, entry in histories.items():
                if not isinstance(player_id, str) or not player_id.startswith("PLAYER_"):
                    continue
                if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
                    continue
                situation.append(pipeline._wire_line(
                    pipeline._history_wire_key(context, player_id),
                    str(entry["text"]).strip(),
                ))
        memory = history.get("memory_summary")
        if isinstance(memory, str) and memory.strip():
            situation.append(pipeline._wire_line("history.memory", memory.strip()[:400]))

    game = context.get("game", {})
    if isinstance(game, dict):
        pipeline._append_int_wire(situation, "game.year", decision.get("year"))
        pipeline._append_id_wire(situation, "game.era", game.get("era_id"))
        pipeline._append_id_wire(situation, "game.speed", game.get("game_speed_id"))
        pipeline._append_id_wire(situation, "game.difficulty", game.get("difficulty_id"))

    _append_civ5_empire_wire(situation, context)
    _append_civ5_need_orders_wire(situation, context)
    _append_civ5_city_situation_wire(situation, context)
    _append_civ5_unit_situation_wire(situation, context)
    situation.append(pipeline._wire_line("units.nativeControl", _civ5_unit_control_hint(context)))

    for rival in context.get("known_players", [])[:12]:
        if isinstance(rival, dict):
            _append_civ5_rival_wire(situation, rival)

    if isinstance(history, dict):
        for index, event in enumerate(
            pipeline._recent_history_events(
                history.get("public_events", []),
                pipeline.chat_history_max_messages(),
            )
        ):
            if not isinstance(event, dict):
                continue
            turn = int(event.get("turn", 0))
            text = pipeline._format_public_chat_line(context, event)
            if text:
                situation.append(pipeline._wire_line(f"chat.public.t{turn}.{index}", text))
    diplomacy_block = context.get("diplomacy", {})
    inbox = diplomacy_block.get("private_inbox", []) if isinstance(diplomacy_block, dict) else []
    for index, message in enumerate(
        pipeline._recent_history_events(inbox, pipeline.chat_history_max_messages())
    ):
        if not isinstance(message, dict):
            continue
        turn = int(message.get("turn", 0))
        text = str(message.get("text", ""))[:240]
        if not text:
            continue
        from_id = str(message.get("from_player_id", ""))
        sender = pipeline._player_chat_name(context, from_id) if from_id else "Rival"
        situation.append(pipeline._wire_line(f"chat.private.t{turn}.{index}", f"{sender} (private): {text}"))

    pipeline._append_diplomacy_situation_wire(situation, context)

    summary = context.get("strategic_summary")
    if isinstance(summary, dict):
        for section, wire_name in {
            "city_alerts": "city",
            "economy_alerts": "economy",
            "military_alerts": "military",
            "diplomacy_alerts": "diplomacy",
            "resource_alerts": "resource",
        }.items():
            for index, alert in enumerate(summary.get(section, [])[:6]):
                if isinstance(alert, dict) and alert.get("text"):
                    situation.append(pipeline._wire_line(f"alert.{wire_name}.{index}", alert["text"][:200]))

    civ5_map = _civ5_block(context).get("map", {})
    if isinstance(civ5_map, dict):
        pipeline._append_int_wire(map_lines, "map.width", civ5_map.get("width"))
        pipeline._append_int_wire(map_lines, "map.height", civ5_map.get("height"))
    else:
        game_block = context.get("game", {})
        if isinstance(game_block, dict):
            pipeline._append_int_wire(map_lines, "map.width", game_block.get("map_width"))
            pipeline._append_int_wire(map_lines, "map.height", game_block.get("map_height"))
    if map_stats:
        for line in map_stats:
            if line.startswith("#"):
                continue
            map_lines.append(line)
    coastal = sum(
        1 for city in context.get("your_cities", [])
        if isinstance(city, dict) and city.get("is_coastal")
    )
    if coastal:
        map_lines.append(pipeline._wire_line("empire.coastal_cities", coastal))
    if _civ5_block(context).get("settle_sites"):
        map_lines.append("# gold hex rings mark better settle tiles than the settler's current plot")

    legal_lines.append("# Issue as many command lines as you need this turn.")
    legal_lines.append("# City: cityName.production = UNIT_* / BUILDING_* / PROJECT_* / PROCESS_*")
    legal_lines.append("# Unit: unitId.property = value.")
    legal_lines.append(
        "# Unit movement: unitId.moveTo = (x,y) — one command walks the remaining tiles "
        "in units.needOrders / unitId.maxMovement; use minimap axis ticks."
    )
    legal_kinds = _legal_kinds_in_snapshot(context)
    if "set_research_tech" in legal_kinds:
        legal_lines.append("# Empire: legal.research.tech = TECH_*")
    if "adopt_social_policy" in legal_kinds:
        legal_lines.append("# Empire: legal.policy = POLICY_*")
    if "unlock_policy_branch" in legal_kinds:
        legal_lines.append("# Empire: legal.policyBranch = POLICY_BRANCH_*")
    if "adopt_ideology" in legal_kinds:
        legal_lines.append("# Empire: legal.ideology = POLICY_BRANCH_*")
    if "choose_maya_bonus" in legal_kinds:
        legal_lines.append("# Empire: legal.mayaBonus = UNIT_*")
    if "promote_unit" in legal_kinds:
        legal_lines.append("# Unit: unitId.promote = PROMOTION_* when promotionReady = true")
    if "improve_tile" in legal_kinds:
        legal_lines.append("# Unit: unitId.improve = BUILD_* on current tile")
    if "automate_unit" in legal_kinds:
        legal_lines.append("# Unit: unitId.automate = build (workers) or explore (scouts)")
    if "rebase" in legal_kinds:
        legal_lines.append("# Unit: unitId.rebaseTo = (x,y) for aircraft")
    if "range_attack" in legal_kinds:
        legal_lines.append("# Unit: unitId.rangedAttack = (x,y) within the strike range in units.needOrders")
    if "spread_religion" in legal_kinds:
        legal_lines.append("# Unit: unitId.spread = apply on the current city tile")
    if "remove_heresy" in legal_kinds:
        legal_lines.append("# Unit: unitId.removeHeresy = apply on the current city tile")
    if "paradrop" in legal_kinds:
        legal_lines.append("# Unit: unitId.paradropTo = (x,y)")
    if "nuke" in legal_kinds:
        legal_lines.append("# Unit: unitId.nukeAt = (x,y)")
    if "pillage" in legal_kinds:
        legal_lines.append("# Unit: unitId.pillage = apply on the current tile")
    if "upgrade_unit" in legal_kinds:
        legal_lines.append("# Unit: unitId.upgrade = UNIT_*")
    if "air_patrol" in legal_kinds:
        legal_lines.append("# Unit: unitId.intercept = apply")

    city_name_by_id = pipeline._city_name_map(context)
    unit_wire_ids = pipeline._build_unit_wire_id_map(
        [unit for unit in context.get("your_units", []) if isinstance(unit, dict)]
    )
    city_commands: dict[str, list[dict[str, Any]]] = {}
    unit_commands: dict[str, list[dict[str, Any]]] = {}
    empire_commands: list[dict[str, Any]] = []
    for command in context.get("legal_commands", []):
        if not isinstance(command, dict) or not command.get("command_id"):
            continue
        fixed = command.get("fixed_arguments", {})
        if not isinstance(fixed, dict):
            fixed = {}
        city_id = fixed.get("city_id")
        unit_id = fixed.get("unit_id")
        if isinstance(city_id, str) and city_id in city_name_by_id:
            city_commands.setdefault(city_name_by_id[city_id], []).append(command)
        elif isinstance(unit_id, str) and unit_id in unit_wire_ids:
            unit_commands.setdefault(unit_wire_ids[unit_id], []).append(command)
        else:
            empire_commands.append(command)

    for city_name in sorted(city_commands):
        legal_lines.extend(_compact_civ5_city_legal_lines(city_name, city_commands[city_name]))
    for unit_wire_id in sorted(unit_commands):
        legal_lines.extend(_compact_civ5_unit_legal_lines(unit_wire_id, unit_commands[unit_wire_id]))
    diplo_ids = [
        str(command.get("command_id"))
        for command in empire_commands
        if isinstance(command, dict)
        and command.get("kind") in ("propose_deal", "respond_to_deal", "cancel_deal", "declare_war")
        and isinstance(command.get("command_id"), str)
    ]
    empire_commands = [
        command
        for command in empire_commands
        if not (
            isinstance(command, dict)
            and command.get("kind") in ("propose_deal", "respond_to_deal", "cancel_deal", "declare_war")
        )
    ]
    legal_lines.extend(_compact_civ5_empire_legal_lines(empire_commands))
    if diplo_ids:
        legal_lines.append("# Diplomacy: cmd.N = " + " | ".join(diplo_ids))

    return "\n\n".join([
        pipeline._wire_section("CURRENT SITUATION", situation),
        pipeline._wire_section("MAP", map_lines),
        pipeline._wire_section("LEGAL COMMANDS", legal_lines),
    ])


def build_civ5_playable_context(snapshot: dict[str, Any]) -> dict[str, Any]:
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


def build_civ5_model_wire_text(snapshot: dict[str, Any]) -> str:
    map_stats = pipeline._map_wire_stats_from_snapshot(snapshot)
    context = build_civ5_playable_context(snapshot)
    return "\n\n".join([
        build_civ5_instructions_preamble(snapshot),
        build_civ5_wire_prompt(context, map_stats=map_stats),
        build_civ5_response_instructions(snapshot),
    ])
