"""Civ VI flat-wire prompt builder — TDD target for fixtures/civ6/."""
from __future__ import annotations

import copy
from typing import Any

from sidecar import pipeline_v2 as pipeline
from sidecar import civ6_prompt_coaching as coaching

UNITS_NATIVE_CONTROL_HINT = (
    "Firaxis AI moves unmoved units after your commands; use fortify/sleep/alert to hold a unit."
)
CITIES_NATIVE_PRODUCTION_HINT = (
    "Cities keep auto production unless you set changeProduction."
)
CIV6_NATIVE_FALLBACK_POLICY = (
    "Firaxis native AI moves unmoved units after your commands; cities keep auto production unless you override."
)

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
            elif isinstance(defense.get("percent"), int) and defense["percent"] < 100:
                lines.append(pipeline._wire_line(f"{name}.hp", defense["percent"]))
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


def build_civ6_role_instruction(snapshot: dict[str, Any]) -> str:
    """Civ IV-style role blob for Gemini system_instruction — adapted for Civ VI."""
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
        f"{role}, in a live Civilization VI match. "
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
        f"{CIV6_NATIVE_FALLBACK_POLICY}"
    )


def build_civ6_response_instructions(snapshot: dict[str, Any]) -> str:
    """Civ IV-style INSTRUCTIONS section — Civ VI wire keys and hybrid control."""
    personality = snapshot.get("personality", {})
    leader = personality.get("leader_name", personality.get("leader_id", "Leader"))
    civ_id = personality.get("civilization_id")
    civ_label = pipeline._readable_id(civ_id, "CIVILIZATION_") if civ_id else ""
    leader_label = leader + (f", playing as the {civ_label} civilization in Civilization VI" if civ_label else "")

    # Make responsibilities explicit: the LLM should not "forget" to act.
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    unit_wire_ids = pipeline._build_unit_wire_id_map(units)
    required_unit_wires = sorted({
        unit_wire_ids.get(str(unit.get("unit_id")))
        for unit in units
        if unit.get("needs_orders") is True and isinstance(unit.get("unit_id"), str)
    } - {None})  # type: ignore[arg-type]

    # Cities with at least one queue_production option should get an explicit production choice.
    queue_options_by_city_id: dict[str, set[str]] = {}
    for command in snapshot.get("legal_commands", []):
        if not isinstance(command, dict):
            continue
        if command.get("kind") != "queue_production":
            continue
        fixed = command.get("fixed_arguments", {})
        if not isinstance(fixed, dict):
            continue
        city_id = fixed.get("city_id")
        build_id = fixed.get("build_id")
        if not isinstance(city_id, str) or not isinstance(build_id, str):
            continue
        queue_options_by_city_id.setdefault(city_id, set()).add(_production_label(build_id))

    city_name_by_id = pipeline._city_name_map(snapshot)
    required_city_specs: list[tuple[str, list[str]]] = []
    for city_id, options in sorted(queue_options_by_city_id.items(), key=lambda kv: kv[0]):
        city_name = city_name_by_id.get(city_id)
        if not city_name:
            continue
        required_city_specs.append((city_name, sorted(options)))

    thought_rows = coaching.civ6_required_thought_rows(snapshot)
    required_game_rows = 0
    if required_unit_wires:
        required_game_rows += len(required_unit_wires)
    if required_city_specs:
        required_game_rows += len(required_city_specs)
    # Pending promotions are required when the snapshot marks them.
    promo_units = [
        unit_wire_ids.get(str(unit.get("unit_id")))
        for unit in units
        if unit.get("promotion_ready") and isinstance(unit.get("unit_id"), str)
    ]
    promo_units = sorted({p for p in promo_units if p})
    required_total = len(thought_rows) + required_game_rows + len(promo_units)

    lines = [
        "=== INSTRUCTIONS ===",
        f"You are {leader_label}.",
        "Read CURRENT SITUATION, MAP, ATTENTION (if present), and LEGAL COMMANDS above.",
        "Reply with flat key=value lines only — never JSON, braces, or code fences.",
        "The host ends your turn automatically after this response.",
        "",
        "=== REQUIRED COMMANDS THIS TURN ===",
        f"# required.count = {required_total} (thought/map-read rows + game orders)",
    ]
    row_i = 1
    for row in thought_rows:
        lines.append(f"{row_i}. {row}")
        row_i += 1
    lines.append(
        f"{row_i}. Units needing orders (issue at least one legal order each): "
        f"{', '.join(required_unit_wires) if required_unit_wires else '(none)'}"
    )
    row_i += 1
    lines.append(
        f"{row_i}. Cities needing production choice: "
        + (
            "; ".join(f"{name}: {' | '.join(opts)}" for name, opts in required_city_specs)
            if required_city_specs
            else "(none)"
        )
    )
    row_i += 1
    if promo_units:
        lines.append(
            f"{row_i}. Promote pending units (legal *.promote): {', '.join(promo_units)}"
        )
        row_i += 1
    lines.append("")
    lines.extend(coaching.civ6_optional_commands_preamble_lines(required_total))
    lines.extend([
        "",
        "Also include when useful (not counted above unless listed as required):",
        "- opinion.LeaderName = short line when your view of a rival changes",
        "- history.LeaderName = T{n} fragment only on major relationship events",
        "- decision_summary = one line naming concrete actions",
        "- Commands: cityName.changeProduction = …; unitId.moveTo = (x,y); legal.research.* / legal.trade.*",
        "- chat.all / chat.LeaderName (optional)",
        "- thought.freethinking = optional free-form reflection",
        "",
        "Rules:",
        f"- The host applies your overrides first; {CIV6_NATIVE_FALLBACK_POLICY}",
        f"- {coaching.CIV6_SETTLER_MAP_ADVICE}" if coaching.settler_present(snapshot) else None,
        "- Settlers and new cities are worth prioritizing when expansion is viable; foundCity is optional — moving first is fine.",
    ])
    lines = [line for line in lines if line is not None]
    lines.extend(f"- {line}" for line in pipeline._diplomatic_strategy_guidance(snapshot))
    lines.extend(f"- {line}" for line in coaching.civ6_diplomacy_guidance(snapshot))
    lines.extend([
        "- Issue only command ids listed under LEGAL COMMANDS this turn; a settler that already "
        "founded is a city, so foundCity is legal only while that settler still exists.",
        "- Movement: use coordinates listed under LEGAL COMMANDS (e.g. scout_1.moveTo = (15,24)).",
        "- Before moving, carefully inspect the attached minimap and each unit's position in "
        "CURRENT SITUATION — pick a tile that advances exploration, expansion, or defense.",
        f"- {coaching.civ6_map_axes_wrap_guidance(snapshot)}",
        f"- {coaching.CIV6_UNIT_STACKING_GUIDANCE}",
        f"- {coaching.CIV6_MOVE_THEN_ATTACK_GUIDANCE}",
        "- Hybrid control: native AI moves unmoved units; use fortify/sleep/alert to hold a unit.",
        "- Cities auto-pick production unless you set changeProduction.",
        "- War attacks on new enemies begin next turn.",
        "- Do not queue production already building.",
        "- decision_summary must name concrete actions.",
        "- When at war, attack options are appended onto unit move/stance lines when legal "
        "(no separate `| none` attack row).",
    ])
    lines.extend(f"- {line}" for line in pipeline._chat_voice_guidance(snapshot))
    lines.extend(f"- {line}" for line in pipeline._chat_format_guidance(snapshot))
    lines.extend([
        "- thought.tN.situation lines in CURRENT SITUATION are your prior board reads — use them for long-term memory.",
        "- opinion.* lines are your stored rival view — emit opinion.LeaderName only when it changes.",
        "- history.* is append-only; add a T{n} fragment only for major relationship shifts, not every message.",
        pipeline._wire_line("units.nativeControl", UNITS_NATIVE_CONTROL_HINT),
        pipeline._wire_line("cities.nativeProduction", CITIES_NATIVE_PRODUCTION_HINT),
    ])
    if pipeline._has_unit_stacks({"your_units": snapshot.get("your_units", [])}):
        lines.extend([
            "- Co-located units appear under stack.* in CURRENT SITUATION (e.g. stack.worker_1).",
            "- To move the whole tile together, use stack.moveTo = (x,y) when listed, or any unit id "
            "under that stack with a matching moveTo option.",
        ])
    return "\n".join(lines)


def build_civ6_wire_prompt(context: dict[str, Any], map_stats: list[str] | None = None) -> str:
    """Sectioned Civ VI wire prompt (situation, map, legal commands)."""
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
            for rival_id, entry in opinions.items():
                if not isinstance(rival_id, str) or not rival_id.startswith("PLAYER_"):
                    continue
                if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
                    continue
                situation.append(pipeline._wire_line(
                    pipeline._opinion_wire_key(context, rival_id),
                    pipeline._opinion_wire_value(entry),
                ))
        histories = history.get("player_histories", {})
        if isinstance(histories, dict):
            for rival_id, entry in histories.items():
                if not isinstance(rival_id, str) or not rival_id.startswith("PLAYER_"):
                    continue
                if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
                    continue
                situation.append(pipeline._wire_line(
                    pipeline._history_wire_key(context, rival_id),
                    str(entry["text"]).strip(),
                ))

    game = context.get("game", {})
    if isinstance(game, dict):
        pipeline._append_int_wire(situation, "game.year", decision.get("year"))
        pipeline._append_id_wire(situation, "game.era", game.get("era_id"))
        pipeline._append_id_wire(situation, "game.speed", game.get("game_speed_id"))
        pipeline._append_id_wire(situation, "game.difficulty", game.get("difficulty_id"))
        pipeline._append_id_wire(situation, "game.world_size", game.get("world_size_id"))

    _append_civ6_empire_wire(situation, context)
    _append_civ6_city_situation_wire(situation, context)
    _append_civ6_unit_situation_wire(situation, context)
    situation.append(pipeline._wire_line("units.nativeControl", UNITS_NATIVE_CONTROL_HINT))

    for rival in context.get("known_players", [])[:12]:
        if isinstance(rival, dict):
            _append_civ6_rival_wire(situation, rival)

    summary = context.get("strategic_summary")
    if isinstance(summary, dict):
        alert_sections = {
            "city_alerts": "city",
            "economy_alerts": "economy",
            "military_alerts": "military",
            "diplomacy_alerts": "diplomacy",
            "resource_alerts": "resource",
        }
        for section, wire_name in alert_sections.items():
            for index, alert in enumerate(summary.get(section, [])[:6]):
                if isinstance(alert, dict) and alert.get("text"):
                    situation.append(pipeline._wire_line(f"alert.{wire_name}.{index}", alert["text"][:200]))

    if isinstance(history, dict):
        memory = history.get("memory_summary")
        if isinstance(memory, str) and memory.strip():
            situation.append(pipeline._wire_line("history.memory", memory.strip()[:400]))
        for index, event in enumerate(pipeline._recent_history_events(history.get("public_events", []), pipeline.chat_history_max_messages())):
            if not isinstance(event, dict):
                continue
            turn = int(event.get("turn", 0))
            text = pipeline._format_public_chat_line(context, event)
            if text:
                situation.append(pipeline._wire_line(f"chat.public.t{turn}.{index}", text))
        diplomacy_block = context.get("diplomacy", {})
        inbox = diplomacy_block.get("private_inbox", []) if isinstance(diplomacy_block, dict) else []
        for index, message in enumerate(pipeline._recent_history_events(inbox, pipeline.chat_history_max_messages())):
            if not isinstance(message, dict):
                continue
            turn = int(message.get("turn", 0))
            text = str(message.get("text", ""))[:240]
            if text:
                from_id = str(message.get("from_player_id", ""))
                sender = pipeline._player_chat_name(context, from_id) if from_id else "Rival"
                situation.append(pipeline._wire_line(f"chat.private.t{turn}.{index}", f"{sender} (private): {text}"))

    civ6_map = _civ6_block(context).get("map", {})
    if isinstance(civ6_map, dict):
        pipeline._append_int_wire(map_lines, "map.width", civ6_map.get("width"))
        pipeline._append_int_wire(map_lines, "map.height", civ6_map.get("height"))
        hex_layout = civ6_map.get("hex_layout")
        if isinstance(hex_layout, str) and hex_layout.strip():
            map_lines.append(pipeline._wire_line("map.hex", hex_layout))
        coords_note = civ6_map.get("coords_note")
        if isinstance(coords_note, str) and coords_note.strip():
            map_lines.append(pipeline._wire_line("map.coords", coords_note))
    else:
        game = context.get("game", {})
        if isinstance(game, dict):
            pipeline._append_int_wire(map_lines, "map.width", game.get("map_width"))
            pipeline._append_int_wire(map_lines, "map.height", game.get("map_height"))
    if map_stats:
        map_lines.extend(map_stats)
    pipeline._append_map_wire_stats(map_lines, context, map_stats)
    if not any(line.startswith("# minimap") for line in map_lines):
        map_lines.append("# minimap attached — fog, terrain, coast, unit positions")

    legal_lines.append("# Issue as many command lines as you need this turn.")
    legal_lines.append("# City: cityName.property = value. Unit: unitId.property = value.")
    legal_lines.append("# Unit movement: unitId.moveTo or stack.moveTo = (x,y)")
    legal_lines.append("# Districts: cityName.changeProduction = DISTRICT_CAMPUS@(x,y)")
    legal_lines.append("# Empire: legal.research.*, legal.policies, legal.diplomacy.*, legal.trade.*")

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
        legal_lines.extend(_compact_civ6_city_legal_lines(city_name, city_commands[city_name]))
    for unit_wire_id in sorted(unit_commands):
        legal_lines.extend(
            _compact_civ6_unit_legal_lines(unit_wire_id, unit_commands[unit_wire_id], context)
        )
    legal_lines.extend(_compact_civ6_empire_legal_lines(empire_commands))

    attention = coaching.collect_civ6_attention_items(context if isinstance(context, dict) else {})
    sections = [
        pipeline._wire_section("CURRENT SITUATION", situation),
        pipeline._wire_section("MAP", map_lines),
    ]
    if attention:
        sections.append(
            pipeline._wire_section(
                "ATTENTION",
                [pipeline._wire_line(f"attention.{i}", note) for i, note in enumerate(attention)],
            )
        )
    sections.append(pipeline._wire_section("LEGAL COMMANDS", legal_lines))
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
