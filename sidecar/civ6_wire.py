"""Civ VI flat-wire prompt builder — TDD target for fixtures/civ6/."""
from __future__ import annotations

import re
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
CIV6_HUMAN_SEAT_POLICY = (
    "Units left without orders stay where they are; the human plays this seat's cities."
)


def prune_settlers_without_sites(snapshot: dict[str, Any]) -> int:
    """Drop extra settler production when walkable sites are fewer than settlers.

    Zero walkable sites is not "settlers already cover every site". That case
    is a blocked settler (often an embark away from the next legal tile).

    Disabled: settler production stays offered; the model decides (no pruning).
    """
    return 0
    settlers = [u for u in snapshot.get("your_units") or [] if isinstance(u, dict) and u.get("unit_type_id") == "UNIT_SETTLER"]
    sites: set[tuple[Any, Any]] = set()
    for u in settlers:
        settle = u.get("settle") if isinstance(u.get("settle"), dict) else {}
        sites.update((s.get("x"), s.get("y")) for s in settle.get("sites") or [] if isinstance(s, dict))
        if settle.get("here_ok"):
            sites.add(("here", u.get("unit_id")))
    if not settlers or len(sites) >= len(settlers):
        return 0
    from sidecar import civ6_legality as legality

    dropped = legality.apply_offer_filter(snapshot, "no_city_sites")
    if len(sites) == 0:
        snapshot["_settlers_no_walkable_site"] = len(settlers)
    else:
        snapshot["_no_city_sites"] = len(settlers)
    return dropped


def settler_offers_without_sites(snapshot: dict[str, Any], legal: list[Any]) -> list[Any]:
    """Offer filter: drop settler production offers."""
    return [c for c in legal if not (isinstance(c, dict) and c.get("kind") == "queue_production"
                                     and (c.get("fixed_arguments") or {}).get("build_id") == "UNIT_SETTLER")]


def no_city_sites_lines(context: dict[str, Any]) -> list[str]:
    if not isinstance(context, dict):
        return []
    # Removed: "no walkable / reachable site" and "build no more settlers".
    # The map shows the land and fog; the model decides where to settle.
    return []


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
    return CIV6_HUMAN_SEAT_POLICY


def chat_dm_examples(snapshot: dict[str, Any] | None) -> str:
    names: list[str] = []
    if isinstance(snapshot, dict):
        for rival in pipeline.chat_target_rivals(snapshot):
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


_FOUND_ALERT_RE = re.compile(r"^(UNIT_\d+) cannot found a city on its tile \(([^)]*)\)\.?")


def _plain_found_alert(context: dict[str, Any], text: str) -> str:
    """'settler_1 at (x,y) cannot found a city: too close: Qusqu is 2 tiles away; ...' (unit name, not raw id)."""
    match = _FOUND_ALERT_RE.match(text)
    if not match:
        return text
    units = [u for u in context.get("your_units", []) or [] if isinstance(u, dict)]
    unit = next((u for u in units if u.get("unit_id") == match.group(1)), None)
    if unit is None:
        return text
    name = pipeline._build_unit_wire_id_map(units).get(match.group(1), match.group(1))
    where = pipeline._plot_coords_text(unit.get("plot_id")) if unit.get("plot_id") else ""
    why = coaching.found_block_text(context, unit, match.group(2))
    return f"{name}{' at ' + where if where else ''} cannot found a city on its tile: {why}."


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
        embarked = coaching.embarked_text(unit, snapshot)
        if embarked:
            lines.append(pipeline._wire_line(f"{prefix}.terrain", embarked))
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


def _visible_city_defense(context: dict[str, Any], xy: tuple[int, int]) -> dict[str, Any] | None:
    """Engine HP for a city the seat can see right now, from combat.city_defenses or hostile_cities."""
    civ6 = context.get("civ6") if isinstance(context.get("civ6"), dict) else {}
    combat = civ6.get("combat") if isinstance(civ6, dict) else {}
    if not isinstance(combat, dict):
        return None
    for key in ("city_defenses", "hostile_cities"):
        for row in combat.get(key) or []:
            if not isinstance(row, dict):
                continue
            if row.get("x") == xy[0] and row.get("y") == xy[1]:
                return row
    return None


def city_defense_text(defense: dict[str, Any] | None) -> str | None:
    """Real city HP and wall HP when either is below full. Walls are omitted when the city has none."""
    if not isinstance(defense, dict):
        return None
    hp = defense.get("hp") if isinstance(defense.get("hp"), int) and not isinstance(defense.get("hp"), bool) else None
    max_hp = defense.get("max_hp") if isinstance(defense.get("max_hp"), int) and not isinstance(defense.get("max_hp"), bool) else None
    pct = defense.get("health_percent") if isinstance(defense.get("health_percent"), int) and not isinstance(defense.get("health_percent"), bool) else None
    wall = defense.get("wall_hp") if isinstance(defense.get("wall_hp"), int) and not isinstance(defense.get("wall_hp"), bool) else None
    wall_max = defense.get("wall_max_hp") if isinstance(defense.get("wall_max_hp"), int) and not isinstance(defense.get("wall_max_hp"), bool) else None
    if hp is not None and max_hp is not None and max_hp > 0:
        city_full = hp >= max_hp
        city_text = f"{hp}/{max_hp}"
    elif pct is not None:
        city_full = pct >= 100
        city_text = f"{pct}%"
    else:
        return None
    has_walls = wall_max is not None and wall_max > 0 and wall is not None
    walls_full = (not has_walls) or wall >= wall_max
    if city_full and walls_full:
        return None
    if has_walls:
        return f"{city_text}, walls {wall}/{wall_max}"
    return city_text


def _append_civ6_city_situation_wire(
    lines: list[str],
    snapshot: dict[str, Any],
    *,
    city_compact: bool = False,
) -> None:
    cities = [city for city in snapshot.get("your_cities", []) if isinstance(city, dict)]
    many_cities = len(cities) >= pipeline.WIRE_COMPACT_CITIES_THRESHOLD
    for city in cities:
        name = pipeline._city_prompt_name(city)
        city_id = city.get("city_id", "")
        extra = _city_extra(snapshot, str(city_id))
        is_capital = bool(city.get("is_capital"))
        plot_id = city.get("plot_id")
        if isinstance(plot_id, str) and plot_id.strip() and not (many_cities and not is_capital and not city_compact):
            lines.append(pipeline._wire_line(f"{name}.position", pipeline._plot_coords_text(plot_id)))
        if city_compact:
            lines.append(pipeline._wire_line(f"{name}.population", int(city.get("population", 1))))
            if is_capital:
                lines.append(pipeline._wire_line(f"{name}.capital", True))
            loyalty = extra.get("loyalty")
            if isinstance(loyalty, int) and not isinstance(loyalty, bool) and loyalty < 100:
                lines.append(pipeline._wire_line(f"{name}.loyalty", loyalty))
            damaged = city_defense_text(city.get("defense") if isinstance(city.get("defense"), dict) else None)
            if damaged:
                lines.append(pipeline._wire_line(f"{name}.hp", damaged))
            production = city.get("production", {})
            item = production.get("item_id") if isinstance(production, dict) else None
            if item and str(item).upper() not in ("NONE", "NULL"):
                lines.append(pipeline._wire_line(f"{name}.currentProduction", _production_label(item)))
            else:
                lines.append(pipeline._wire_line(f"{name}.currentProduction", _empty_production_text(snapshot)))
            _append_city_rate(lines, name, city)
            continue
        if many_cities and not is_capital:
            plot_id = city.get("plot_id")
            if isinstance(plot_id, str) and plot_id.strip():
                lines.append(pipeline._wire_line(f"{name}.position", pipeline._plot_coords_text(plot_id)))
            damaged = city_defense_text(city.get("defense") if isinstance(city.get("defense"), dict) else None)
            if damaged:
                lines.append(pipeline._wire_line(f"{name}.hp", damaged))
            production = city.get("production", {})
            item = production.get("item_id") if isinstance(production, dict) else None
            if not item or str(item).upper() in ("NONE", "NULL"):
                lines.append(pipeline._wire_line(f"{name}.currentProduction", _empty_production_text(snapshot)))
            _append_city_rate(lines, name, city)
            continue
        lines.append(pipeline._wire_line(f"{name}.population", int(city.get("population", 1))))
        if is_capital:
            lines.append(pipeline._wire_line(f"{name}.capital", True))
        loyalty = extra.get("loyalty")
        if isinstance(loyalty, int) and not isinstance(loyalty, bool):
            lines.append(pipeline._wire_line(f"{name}.loyalty", loyalty))
        # Districts are printed from the economy city row. Repeat them here only
        # when that row has none, so a missing economy block still shows them.
        economy_row = economy_wire._cities_by_id(snapshot).get(str(city_id), {})
        if not economy_row.get("built_districts"):
            districts = [str(d) for d in extra.get("districts") or [] if d]
            if districts:
                lines.append(pipeline._wire_line(f"{name}.districts", ", ".join(districts)))
        wonders = [str(w) for w in extra.get("wonders") or [] if w]
        if wonders:
            lines.append(pipeline._wire_line(f"{name}.wonders", ", ".join(wonders)))
        city_religion = extra.get("religion")
        if isinstance(city_religion, str) and city_religion.strip() and "UNKNOWN" not in city_religion.upper():
            lines.append(pipeline._wire_line(f"{name}.religion", city_religion))
        amenities = city.get("amenities")
        if isinstance(amenities, dict):
            net = amenities.get("net")
            if isinstance(net, int):
                lines.append(pipeline._wire_line(f"{name}.amenities", net))
        damaged = city_defense_text(city.get("defense") if isinstance(city.get("defense"), dict) else None)
        if damaged:
            lines.append(pipeline._wire_line(f"{name}.hp", damaged))
        production = city.get("production", {})
        item = production.get("item_id") if isinstance(production, dict) else None
        if item and str(item).upper() not in ("NONE", "NULL"):
            if not (many_cities and not is_capital):
                lines.append(pipeline._wire_line(f"{name}.currentProduction", _production_label(item)))
        else:
            lines.append(pipeline._wire_line(f"{name}.currentProduction", _empty_production_text(snapshot)))
        _append_city_rate(lines, name, city)


def _empty_production_text(snapshot: dict[str, Any]) -> str:
    """An empty build slot. Only a seat that queues its own production has a truly empty queue;
    for a seat whose builds the game's AI picks, the pick happens at its turn start."""
    if _has_queue_production(snapshot):
        return "NONE (queue empty)"
    from sidecar.civ6_priorities import priorities_supported

    if priorities_supported(snapshot):
        return "NONE yet (the game picks from your build weights at your turn start)"
    return "NONE (queue empty)"


def _append_city_rate(lines: list[str], name: str, city: dict[str, Any]) -> None:
    """Production per turn and current-build turns: facts for choosing where to build."""
    production = city.get("production") if isinstance(city.get("production"), dict) else {}
    rate = production.get("production_per_turn")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool):
        text = f"{rate}/turn"
        turns = production.get("estimated_turns_remaining")
        item = production.get("item_id")
        if isinstance(turns, int) and item and str(item).upper() not in ("NONE", "NULL"):
            text += f", current build done in {turns} turns"
        lines.append(pipeline._wire_line(f"{name}.production", text))


def _append_civ6_empire_wire(lines: list[str], snapshot: dict[str, Any]) -> None:
    empire = snapshot.get("your_empire", {})
    if not isinstance(empire, dict):
        return
    yields = _civ6_yields(snapshot)
    pipeline._append_int_wire(lines, "empire.score", empire.get("score"))
    religion = empire.get("religion") if isinstance(empire.get("religion"), dict) else {}
    state_religion = religion.get("state_religion_id")
    if isinstance(state_religion, str) and state_religion.strip() and "UNKNOWN" not in state_religion.upper():
        lines.append(pipeline._wire_line("empire.religion", state_religion))
    governance = ((snapshot.get("civ6") or {}).get("governance") or {}) if isinstance(snapshot.get("civ6"), dict) else {}
    congress = governance.get("world_congress") if isinstance(governance, dict) else None
    if isinstance(congress, dict) and congress:
        bits = []
        for key in ("in_session", "meeting_status", "meeting_turn"):
            if congress.get(key) is not None:
                bits.append(f"{key}={congress[key]}")
        if bits:
            lines.append(pipeline._wire_line("empire.world_congress", " ".join(bits)))
    cities = [city for city in snapshot.get("your_cities", []) if isinstance(city, dict)]
    if cities:
        lines.append(pipeline._wire_line("empire.cities", len(cities)))
    anarchy = empire.get("anarchy_turns") if isinstance(empire.get("anarchy_turns"), int) else 0
    economy = ((snapshot.get("civ6") or {}).get("economy") or {}) if isinstance(snapshot.get("civ6"), dict) else {}
    if not isinstance(economy.get("gold"), dict):
        pipeline._append_int_wire(lines, "empire.gold", empire.get("gold"))
        if anarchy and empire.get("gold_per_turn") == 0:
            lines.append(pipeline._wire_line("empire.gold_per_turn", "0/turn due to anarchy"))
        else:
            pipeline._append_int_wire(lines, "empire.gold_per_turn", empire.get("gold_per_turn"))
    if anarchy:
        lines.append(pipeline._wire_line("empire.anarchy", f"{anarchy} turns left"))
    amenities = empire.get("amenities")
    if isinstance(amenities, dict):
        pipeline._append_int_wire(lines, "empire.amenities.net", amenities.get("net"))
    known = snapshot.get("known_map")
    if isinstance(known, dict) and isinstance(known.get("explored_percent"), int):
        pipeline._append_int_wire(lines, "empire.map.explored_percent", known.get("explored_percent"))
    for field in ("science", "culture", "faith", "favor"):
        value = yields.get(field)
        if isinstance(value, int):
            if anarchy and value == 0 and field != "favor":
                lines.append(pipeline._wire_line(f"empire.{field}", "0/turn due to anarchy"))
            else:
                lines.append(pipeline._wire_line(f"empire.{field}", value))
    research = empire.get("research", {})
    if isinstance(research, dict):
        pipeline._append_id_wire(lines, "empire.research.tech", research.get("tech_id"))
        pipeline._append_int_wire(lines, "empire.research.tech.progress", research.get("progress"))
        pipeline._append_int_wire(lines, "empire.research.tech.cost", research.get("cost"))
        pipeline._append_int_wire(lines, "empire.research.tech.per_turn", research.get("research_per_turn"))
        # Governance already asked the engine (GetTurnsLeft). The empire field
        # is a separate ceil and used to disagree by a turn.
        gov_techs = ((snapshot.get("civ6") or {}).get("governance") or {}).get("techs") if isinstance(snapshot.get("civ6"), dict) else None
        turns_left = research.get("estimated_turns_remaining")
        if isinstance(gov_techs, dict) and gov_techs.get("current") == research.get("tech_id") and isinstance(gov_techs.get("turns_left"), int):
            turns_left = gov_techs["turns_left"]
        pipeline._append_int_wire(lines, "empire.research.tech.turns_left", turns_left)
        lines.append(pipeline._wire_line("empire.techs.known", ", ".join(research.get("known_tech_ids") or []) or "none"))
    known_civics = [c.get("id") for c in empire.get("civics") or [] if isinstance(c, dict) and c.get("id")]
    lines.append(pipeline._wire_line("empire.civics.known", ", ".join(known_civics) or "none"))
    civic = _civ6_research_civic(snapshot)
    if civic.get("civic_id"):
        pipeline._append_id_wire(lines, "empire.research.civic", civic.get("civic_id"))
        pipeline._append_int_wire(lines, "empire.research.civic.progress", civic.get("progress"))
        gov_civics = ((snapshot.get("civ6") or {}).get("governance") or {}).get("civics") if isinstance(snapshot.get("civ6"), dict) else None
        civic_turns = civic.get("turns_left")
        if isinstance(gov_civics, dict) and gov_civics.get("current") == civic.get("civic_id") and isinstance(gov_civics.get("turns_left"), int):
            civic_turns = gov_civics["turns_left"]
        pipeline._append_int_wire(lines, "empire.research.civic.turns_left", civic_turns)
    government_id = _civ6_block(snapshot).get("government_id")
    if isinstance(government_id, str) and government_id.strip():
        pipeline._append_id_wire(lines, "empire.government", government_id)
    unit_counts = empire.get("unit_counts", {})
    if isinstance(unit_counts, dict):
        for field in ("total", "military", "settlers", "idle"):
            pipeline._append_int_wire(lines, f"empire.units.{field}", unit_counts.get(field))


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
        elif token and token.startswith("AttackTo("):
            token = combat_wire.with_attack_forecast(token, snapshot, unit_id=unit_id)
        if token and token not in out.setdefault(unit_id, []):
            out[unit_id].append(token)
    for unit in snapshot.get("your_units", []):
        if isinstance(unit, dict) and ((unit.get("movement") or {}).get("current") or 0) > 0:
            tokens = out.setdefault(str(unit.get("unit_id")), [])
            tokens[:0] = [] if "MoveTo(x,y)" in tokens else ["MoveTo(x,y)"]
    for unit_id, tokens in out.items():
        tokens.sort(key=_token_sort_key)
        out[unit_id] = _cap_attack_tokens(tokens)
    return out


_ATTACK_DMG_RE = re.compile(r"~(\d+)dmg")
_ATTACK_TOKEN_CAP = 4


def _attack_token_damage(token: str) -> int:
    match = _ATTACK_DMG_RE.search(token)
    return int(match.group(1)) if match else 0


def _cap_attack_tokens(tokens: list[str]) -> list[str]:
    """Keep the four AttackTo options with the highest forecast damage. The rest stay legal if typed."""
    attacks = [token for token in tokens if token.startswith("AttackTo(")]
    if len(attacks) <= _ATTACK_TOKEN_CAP:
        return tokens
    best = set(sorted(attacks, key=lambda token: (-_attack_token_damage(token), token))[:_ATTACK_TOKEN_CAP])
    return [token for token in tokens if not token.startswith("AttackTo(") or token in best]


_DISTRICT_AT = re.compile(r"^(DISTRICT_[A-Z0-9_]+)@\((\d+),(\d+)\)$")


def _production_turns(snapshot: dict[str, Any], city_id: str, token: str) -> int | None:
    economy = ((snapshot.get("civ6") or {}).get("economy") or {}) if isinstance(snapshot.get("civ6"), dict) else {}
    by_city = economy.get("build_turns") if isinstance(economy.get("build_turns"), dict) else {}
    turns = by_city.get(city_id) if isinstance(by_city.get(city_id), dict) else {}
    base = token.split("@", 1)[0].split(":", 1)[0]
    value = turns.get(token, turns.get(base))
    return value if isinstance(value, int) else None


def _collapse_district_tokens(tokens: list[str]) -> list[str]:
    """DISTRICT_X@(a,b) and DISTRICT_X@(c,d) become DISTRICT_X@(a,b)|(c,d)."""
    groups: dict[str, list[str]] = {}
    out: list[str] = []
    for token in tokens:
        match = _DISTRICT_AT.match(token)
        if match is None:
            out.append(token)
            continue
        key = match.group(1)
        groups.setdefault(key, []).append(f"({match.group(2)},{match.group(3)})")
        if key not in out:
            out.append(key)
    collapsed: list[str] = []
    for token in out:
        coords = groups.get(token)
        collapsed.append(f"{token}@{('|'.join(coords))}" if coords else token)
    return collapsed


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
        if prop == "rangeStrike" and token.startswith("("):
            token = combat_wire.with_attack_forecast(token, snapshot, city_id=city_id)
        if prop == "production" and (_production_turns(snapshot, city_id, token) or 0) >= 30:
            continue
        bucket = out.setdefault(city_id, {}).setdefault(prop, [])
        cap = 6 if prop == "purchase" else 4 if prop == "buyTile" else None
        if cap is not None and len(bucket) >= cap:
            if prop == "purchase" and token.startswith("UNIT_SETTLER") and token not in bucket:
                bucket[-1] = token
            continue
        if token not in bucket:
            bucket.append(token)
    for props in out.values():
        if "production" in props:
            props["production"] = _collapse_district_tokens(props["production"])
    return out


def _plain_strike_coord(token: str) -> str | None:
    match = re.match(r"\((\d+)\s*,\s*(\d+)\)", str(token).strip())
    if match is None:
        return None
    return f"({match.group(1)},{match.group(2)})"


def city_strike_prompt_lines(snapshot: dict[str, Any]) -> list[str]:
    """Plain city-strike coordinates, only when a city can strike this turn."""
    from sidecar.civ6_legality import city_strike_available

    if not city_strike_available(snapshot):
        return []
    tokens = _civ6_city_tokens(snapshot)
    rows: list[str] = []
    for city in snapshot.get("your_cities") or []:
        if not isinstance(city, dict):
            continue
        raw = (tokens.get(str(city.get("city_id") or "")) or {}).get("rangeStrike") or []
        ranked = sorted(raw, key=lambda token: (-_attack_token_damage(str(token)), str(token)))
        coords: list[str] = []
        for token in ranked[:4]:
            pair = _plain_strike_coord(str(token))
            if pair and pair not in coords:
                coords.append(pair)
        if not coords:
            continue
        name = pipeline._city_prompt_name(city)
        rows.append(f"  {name}.rangeStrike = {' | '.join(coords)}")
    if not rows:
        return []
    return [
        "CITY STRIKES — these are city attacks.",
        "Order CityName.rangeStrike = (x,y) with one coordinate from that city's line.",
        *rows,
        "",
    ]


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


def _example_command_value(value: str) -> str:
    """One sample for the example JSON. A builder row demonstrates Improve."""
    options = [part.strip() for part in str(value).split(" | ") if part.strip()]
    for option in options:
        if option.startswith("Improve("):
            return option
    return options[0] if options else str(value)


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
        name = pipeline._city_prompt_name(city)
        rows.append((name, [f"bare ID from {name}.production.catalog"]))
    return rows


def _event_log_rows(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    """(EventName, hint) rows for attention items that deserve a written thought."""
    rows: list[tuple[str, str]] = []
    idle = [u for u in snapshot.get("your_units", []) if isinstance(u, dict) and u.get("needs_orders")]
    if idle:
        wire_ids = pipeline._build_unit_wire_id_map(idle)
        names = [wire_ids.get(str(u.get("unit_id")), str(u.get("unit_id"))) for u in idle[:8]]
        extra = f" (+{len(idle) - 8} more)" if len(idle) > 8 else ""
        rows.append(("Idle", f"{len(idle)} units idle: {', '.join(names)}{extra}"))
    blocked_hint = "(last turn's failed order: what went wrong and what you do differently)"
    if civ6_apply_results.blocked_attention_lines(snapshot):
        rows.append(("Blocked", blocked_hint))
    from sidecar import civ6_attention

    for name in civ6_attention.event_names(snapshot):
        if all(existing != name for existing, _ in rows):
            rows.append((name, blocked_hint if name == "Blocked" else "(write this turn's thought on this item)"))
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
        options = _required_unit_options(unit_tokens.get(unit_id, []))
        has_attack = any(str(option).startswith("AttackTo(") for option in options)
        needs = unit.get("needs_orders") is True or unit.get("promotion_ready") or has_attack
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
    keep.extend(civ6_apply_results.chat_cadence_lines(
        snapshot, lambda pid: pipeline._player_chat_name(snapshot, pid)))
    intro_turn, intro_who = pipeline.first_self_intro_context(snapshot)
    if intro_turn is not None:
        keep.append(
            f"You already introduced yourself to {intro_who} on turn {intro_turn}; don't repeat it, "
            "respond to what they said or say something new."
        )
    keep.append(
        f"Private DMs use a rival's leader name as the key ({chat_dm_examples(snapshot)}). "
        "chat.all is public. Address people by those leader names, never as Player N. "
        "Write the line in English, in your own words — do not send another player's line back to them. "
        f"Keep each line under {pipeline.CHAT_TEXT_MAX_LENGTH} characters."
    )
    return keep


def _tactical_image_where(snapshot: dict[str, Any]) -> str:
    """Where image 2 is looking, so the reply can talk about that picture."""
    advciv = snapshot.get("advciv")
    manifest = advciv.get("map_images") if isinstance(advciv, dict) else None
    if not isinstance(manifest, list):
        return ""
    for row in manifest:
        if not isinstance(row, dict) or row.get("role") != "viewport":
            continue
        label = str(row.get("label") or "").strip()
        rect = row.get("viewport") if isinstance(row.get("viewport"), dict) else {}
        window = ""
        if rect:
            try:
                x0, y0 = int(rect["x0"]), int(rect["y0"])
                x1 = x0 + int(rect["width"]) - 1
                y1 = y0 + int(rect["height"]) - 1
                window = f"tiles x {x0}-{x1}, y {y0}-{y1}"
            except (KeyError, TypeError, ValueError):
                window = ""
        auto = "auto" if row.get("auto") is not False else "your last map.viewport"
        bits = [bit for bit in (label, window, auto) if bit]
        return ", ".join(bits)
    return ""


def _player_roster_line(snapshot: dict[str, Any]) -> str:
    """Every known seat by leader name, so replies do not invent Player N."""
    names: list[str] = []
    for rival in snapshot.get("known_players") or []:
        if not isinstance(rival, dict):
            continue
        if rival.get("is_you") is True:
            continue
        pid = str(rival.get("player_id") or "")
        decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
        if pid and pid == str(decision.get("player_id") or ""):
            continue
        name = pipeline._rival_leader_name(rival)
        kind = civ6_player_kind(rival)
        if kind == "city-state":
            names.append(f"{name} (city-state)")
        elif kind == "free cities":
            names.append("Free Cities")
        elif kind == "barbarians":
            names.append("Barbarians")
        else:
            civ = pipeline._readable_id(rival.get("civilization_id"), "CIVILIZATION_")
            names.append(f"{name} of {civ}" if civ and civ.lower() not in name.lower() else name)
    if not names:
        return ""
    return (
        "Players in this match, by name: " + ", ".join(names) + ". "
        "Address them by these names. There is no one called Player N. Write in English."
    )


def build_civ6_role_instruction(snapshot: dict[str, Any]) -> str:
    """System instruction: first-person role-play, Civ5-parity wording, Civ VI mechanics."""
    leader, civ_label = _leader_civ(snapshot)
    role = f"You are {leader}"
    if civ_label:
        role += f", playing as the {civ_label} civilization"
    attach_map = pipeline.map_image_attach_turn(snapshot)
    where = _tactical_image_where(snapshot)
    if attach_map:
        where_bit = f" ({where})" if where else ""
        map_clause = (
            " Two map images are attached. Image 1 is the strategic map of the whole front. "
            f"Image 2 is the tactical close-up{where_bit}. "
            "Read both, and say what image 2 shows in tacticalmap.read. "
            "Move image 2 next turn with map.viewport = (x,y) centered on the tile you care about, "
            "or map.viewport = auto. "
            "On the tactical close-up a military unit sits at the top of the hex, the resource icon in the center, "
            "a civilian unit at the bottom, an improvement on the left and a district on the right. "
            "A health bar under a unit is its hit points. Edge numbers are the (x,y) axes. "
            "Write every word of your reply in English. "
        )
    else:
        map_clause = (
            " Use EMPIRE unit coordinates for movement this turn (no map image attached). "
            "Write every word of your reply in English. "
        )
    gandhi_clause = pipeline._gandhi_role_clause() if pipeline._is_gandhi_leader(snapshot) else ""
    primer = coaching.civ6_game_primer()
    return (
        (primer + "\n\n" if primer else "")
        + f"{role}, in a live Civilization VI match. "
        f"{gandhi_clause}"
        "Full role-play mode: you are this leader — recognizable, with their actual sense of humor "
        "(vain, pious, cruel, folksy, whatever they were), not a marble statue. "
        "Write and think in first person — I, my, we — embodying their temperament and emotional state this turn. "
        "thought.situation and thought.strategy are ONE paragraph each of guided thinking — "
        "board read, then strategy — never neutral analyst prose. "
        "thought.situation and thought.strategy must each be newly written this turn; lead with new observations "
        "and do not copy or lightly rephrase prior T{n} journal lines. "
        "thought.strategy holds your victory path and this turn's command plan in prose; "
        f"{_orders_execute_clause(snapshot)}"
        "Event.*.log should sound like you thinking aloud. "
        f"{coaching.CIV6_DIPLOMACY_PSYCHOLOGY}"
        "Every player is trying to win. "
        "Play to win using Civilization VI mechanics (districts, adjacency, amenities, housing, loyalty, "
        "civics and policy cards, one military unit per tile); personality colors prose, not the build queue. "
        "Speak in the game: send chat.all and "
        f"{chat_dm_examples(snapshot)} when you have something new to say (opening, first contact, deals, "
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
        coaching.civ6_map_axes_wrap_guidance(context),
        "War, gold, science, culture, faith and amenities all matter; the other players are playing too.",
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
        unexplored = max(0, 100 - explored)
        map_lines.append(pipeline._wire_line("map.explored", f"{explored}%"))
        map_lines.append(pipeline._wire_line("map.unexplored", f"{unexplored}%"))
        map_lines.append(
            f"Whole world: {explored}% revealed, {unexplored}% still unexplored gray fog. "
            "The percent in map.strategic.window, and on the strategic image banner, is how much of the "
            "world that picture shows, not how much you have explored. "
            "A city sitting alone in gray fog is one revealed tile — an embassy, or capitals exchanged "
            "when you first met. A delegation does not reveal the map, and the gray fog hexes around that "
            "city were not explored."
        )
        true_map = coaching.civ6_true_explored(context)
        if true_map is not None:
            revealed_tiles, map_tiles, true_pct = true_map
            map_lines.append(pipeline._wire_line(
                "map.revealed_tiles",
                f"{revealed_tiles} of {map_tiles} tiles revealed on the whole map ({true_pct}%). "
                "This is your real visibility, not the trimmed picture.",
            ))
    naval = any(isinstance(u, dict) and u.get("domain_id") == "DOMAIN_SEA" for u in context.get("your_units") or [])
    grid = [list(r) for r in (context.get("known_map") or {}).get("visibility_grid") or []]
    todo = [tuple(map(int, str(o.get("plot_id")).split("_")[1:3])) for o in (context.get("your_units") or []) + (context.get("your_cities") or [])
            if isinstance(o, dict) and re.fullmatch(r"PLOT_\d+_\d+", str(o.get("plot_id")))]
    held = todo[:len([u for u in context.get("your_units") or [] if isinstance(u, dict) and re.fullmatch(r"PLOT_\d+_\d+", str(u.get("plot_id")))])]
    while todo:
        x, y = todo.pop()
        if 0 <= y < len(grid) and grid[y] and grid[y][x % len(grid[y])] in ".#":
            grid[y][x % len(grid[y])] = "*"
            todo += [(x - 1, y), (x + 1, y)] + [(x + d, y + e) for e in (-1, 1) for d in ((0, 1) if y % 2 else (-1, 0))]
    for x, y in held:
        if 0 <= y < len(grid) and grid[y]:
            grid[y][x % len(grid[y])] = "@"
    # Land/island/coast coordinate runs repeat the attached image. Keep them only when there is no image.
    if not pipeline.map_image_attach_turn(context):
        for name, pattern in (("land", r"\*+"), ("island", r"[.#]+"), ("coast", r"~+"))[:3 if naval else 2]:
            for y, row in enumerate("".join(r) for r in grid):
                runs = [m.span() for m in re.finditer(pattern, row)]
                if runs:
                    map_lines.append(pipeline._wire_line(f"map.{name}.y{y}", ", ".join(
                        str(a) if b - a == 1 else f"{a}-{b - 1}" for a, b in runs)))
    if pipeline.map_image_attach_turn(context) and not any("attached" in l for l in map_lines):
        map_lines.append(pipeline._wire_line(
            "map.images",
            "attached — fog, terrain, coast, resources, improvements (lower-left on owned tiles), "
            "districts (lower-right); a blank owned tile is unimproved",
        ))
    lines.extend(map_lines)
    return lines


_MILITARY_ALERT_RE = re.compile(r"unit|attack|war|enemy|barbarian|army|siege|defen|pillag|captur|threat", re.I)
_PLAYER_RE = re.compile(r"\bPLAYER_(\d+)\b")


def _clip_sentence(text: str, limit: int) -> str:
    """Cut at the last sentence end within limit (never mid-sentence when one exists)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + "…"


def _leader_names(context: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rival in list(context.get("known_players", []) or []) + list(context.get("rivals", []) or []):
        if isinstance(rival, dict) and isinstance(rival.get("player_id"), str):
            out[rival["player_id"]] = pipeline._rival_leader_name(rival)
    return out


def _compact_city_alert_lines(snapshot: dict[str, Any], city: dict[str, Any], name: str) -> list[str]:
    """Production timing and the alerts a compact city row still has to show."""
    lines: list[str] = []
    row = economy_wire._cities_by_id(snapshot).get(str(city.get("city_id")))
    if isinstance(row, dict):
        production = city.get("production") if isinstance(city.get("production"), dict) else {}
        item = row.get("production_item") or production.get("item_id")
        turns = row.get("production_turns")
        if item and isinstance(turns, int) and not isinstance(turns, bool):
            lines.append(pipeline._wire_line(f"{name}.currentProduction.turnsLeft", turns))
        starve = row.get("turns_to_starve")
        if isinstance(starve, int) and not isinstance(starve, bool):
            lines.append(pipeline._wire_line(
                f"{name}.growth", f"STARVING, loses a citizen in {starve} turns",
            ))
    for line in gs_wire.city_lines(snapshot, city, name):
        if "UNPOWERED" in line:
            lines.append(line)
    return lines


def _unit_idle_for(context: dict[str, Any], unit_id: str) -> int:
    """Turns since this unit's last successful order or move (civ6_economy tracking)."""
    tracking = ((context.get("civ6") or {}).get("economy") or {}).get("tracking") if isinstance(
        context.get("civ6"), dict) else None
    idle = tracking.get("idle_for") if isinstance(tracking, dict) else None
    n = idle.get(unit_id) if isinstance(idle, dict) else None
    return n if isinstance(n, int) and n > 0 else 0


def _empire_section(
    context: dict[str, Any],
    *,
    unit_compact: bool = False,
    city_compact: bool = False,
) -> list[str]:
    lines = ["# == Summary =="]
    _append_civ6_empire_wire(lines, context)
    lines.extend(economy_wire.empire_lines(context))
    lines.extend(gs_wire.empire_lines(context))
    summary = context.get("strategic_summary")
    if isinstance(summary, dict):
        seen_alerts: set[str] = set()
        counts: dict[str, int] = {}
        for section, wire_name in (("city_alerts", "city"), ("economy_alerts", "economy"),
                                   ("military_alerts", "military"), ("diplomacy_alerts", "diplomacy"),
                                   ("resource_alerts", "resource")):
            for alert in summary.get(section, [])[:6]:
                if not (isinstance(alert, dict) and alert.get("text")):
                    continue
                text = str(alert["text"]).replace(
                    " See that settler's settle.here / settle.sites facts (legal tiles only, unranked).", ""
                )[:200]
                text = _plain_found_alert(context, text)
                if text in seen_alerts:
                    continue
                seen_alerts.add(text)
                name = wire_name
                if name == "military" and re.search(r"wonder|loyalty", text, re.I):
                    name = "city"
                elif name == "military" and not _MILITARY_ALERT_RE.search(text):
                    name = "notice"  # generic game notification, not a military alert
                index = counts.get(name, 0)
                counts[name] = index + 1
                lines.append(pipeline._wire_line(f"alert.{name}.{index}", text))
        lines.extend(_expansion_threat_lines(summary, threats=False))
    # Cities
    cities = [c for c in context.get("your_cities", []) if isinstance(c, dict)]
    if cities:
        lines.append("# == Cities ==")
        city_block: list[str] = []
        _append_civ6_city_situation_wire(city_block, context, city_compact=city_compact)
        for city in cities:
            name = pipeline._city_prompt_name(city)
            production = city.get("production", {})
            if not (isinstance(production, dict) and production.get("item_id")):
                city_block.append(f"***{name}.currentProduction = NONE***")
        # keep each city's lines together
        for city in cities:
            name = pipeline._city_prompt_name(city)
            lines.extend(l for l in city_block if l.startswith((f"{name}.", f"***{name}.")))
            if city_compact:
                lines.extend(_compact_city_alert_lines(context, city, name))
            else:
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
        if not unit_compact:
            lines.append(pipeline._wire_line(
                "unit.ids",
                " | ".join(wire_ids.get(str(unit.get("unit_id")), "unit") for unit in units),
            ))
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
                    # Coordinates stay on each unit's own row. A shared type line of
                    # every Improve(x,y) made every builder look like the same two tiles.
                    if verb == "Improve":
                        shape = "Improve(x,y,IMPROVEMENT_X)"
                    elif "(" in token and verb in ("MoveTo", "AttackTo"):
                        shape = f"{verb}(x,y)"
                    else:
                        shape = token
                    if shape not in kinds:
                        kinds.append(shape)
                if _game_ai_builder(unit):
                    kinds = []
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
                embarked = coaching.embarked_text(unit, context)
                if embarked:
                    lines.append(pipeline._wire_line(f"{prefix}.terrain", embarked))
                if not unit_compact:
                    lines.extend(combat_wire.unit_row_lines(prefix, unit, context))
                pct = coaching.civ6_unit_health_percent(unit)
                if isinstance(pct, int) and pct < 100:
                    lines.append(pipeline._wire_line(f"{prefix}.hp", f"{pct}%"))
                if unit.get("needs_orders"):
                    lines.append(f"***{prefix}.needsOrders = true***")
                if _game_ai_builder(unit):
                    lines.append(pipeline._wire_line(
                        f"{prefix}.control", "the game's own builder AI improves tiles with this builder; no order needed"))
                elif _game_ai_civilian(unit):
                    lines.append(pipeline._wire_line(
                        f"{prefix}.control", "the game's own AI moves this unit (trade routes, spreading religion); no order needed"))
                idle_n = _unit_idle_for(context, unit_id)
                if idle_n:
                    lines.append(pipeline._wire_line(
                        f"{prefix}.idle", f"{idle_n} turn{'s' if idle_n != 1 else ''} since its last successful order or move"))
                if not unit_compact and unit.get("promotion_ready"):
                    lines.append(pipeline._wire_line(f"{prefix}.promotionReady", True))
                if not unit_compact:
                    upgrades = unit.get("upgrade_options")
                    if isinstance(upgrades, list) and upgrades:
                        bits = []
                        for option in upgrades:
                            if not isinstance(option, dict) or not option.get("unit_type_id"):
                                continue
                            label = str(option["unit_type_id"])
                            cost = option.get("gold_cost")
                            if isinstance(cost, int) and not isinstance(cost, bool):
                                label += f" ({cost} gold)"
                            bits.append(label)
                        if bits:
                            lines.append(pipeline._wire_line(f"{prefix}.upgrade", ", ".join(bits)))
                movement = unit.get("movement", {})
                if isinstance(movement, dict) and isinstance(movement.get("current"), int):
                    current_moves = movement["current"]
                    if unit_compact:
                        if current_moves == 0:
                            lines.append(pipeline._wire_line(f"{prefix}.moves", 0))
                    else:
                        lines.append(pipeline._wire_line(f"{prefix}.moves", current_moves))
                        if (isinstance(movement.get("maximum"), int) and movement["maximum"] > 0
                                and movement.get("maximum") != current_moves):
                            lines.append(pipeline._wire_line(f"{prefix}.maxMovement", movement["maximum"]))
                if not unit_compact and "SETTLER" in str(unit.get("unit_type_id") or ""):
                    lines.extend(coaching.settler_fact_lines(prefix, unit, context))
                if not unit_compact and str(unit.get("unit_type_id") or "") == "UNIT_BUILDER" and unit.get("needs_orders"):
                    lines.extend(coaching.builder_fact_lines(prefix, unit, context))
                lines.append("")
            if lines[-1] == "":
                lines.pop()
    return lines


def _game_ai_builder(unit: dict[str, Any]) -> bool:
    """AI-seat builder the mod leaves to the game's builder AI (charges, never needs orders)."""
    return (int(unit.get("build_charges") or 0) > 0 and not unit.get("needs_orders")
            and unit.get("can_act") is False)


_GAME_AI_CIVILIAN_TAGS = ("TRADER", "MISSIONARY", "APOSTLE", "INQUISITOR", "GURU")


def _game_ai_civilian(unit: dict[str, Any]) -> bool:
    """AI-seat trader or religious unit with moves left that the mod leaves to the game's AI."""
    typ = str(unit.get("unit_type_id") or "").upper()
    move = unit.get("movement") if isinstance(unit.get("movement"), dict) else {}
    return (any(tag in typ for tag in _GAME_AI_CIVILIAN_TAGS) and not unit.get("needs_orders")
            and unit.get("can_act") is False and (move.get("current") or 0) > 0)


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
        coaching.CIV6_LOBBY_CHAT_TONE,
        "chat.all is public. Send it only when you have something new to say (opening, taunt, deal, war); "
        f"silence is fine. Prefer {chat_dm_examples(context)} for targeted talk.",
        "When chatting, always make original statements unique to your own personality and situation. "
        "Do not repeat or paraphrase what other players have said in chat (lines marked You are your own).",
    ]
    roster = _player_roster_line(context)
    if roster:
        lines.append(roster)
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
    leaders = _leader_names(context)
    seen_chat: set[tuple[str, str]] = set()
    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}
    self_id = str(decision.get("player_id") or "")
    if isinstance(history, dict):
        for index, event in enumerate(pipeline._recent_history_events(
                history.get("public_events", []), pipeline.chat_history_max_messages())):
            if not isinstance(event, dict):
                continue
            kind = str(event.get("kind", "")).upper()
            if kind and kind != "CHAT_PUBLIC":
                continue
            text = pipeline._format_public_chat_line(context, event)
            if text:
                text = _PLAYER_RE.sub(lambda m: leaders.get(m.group(0), "an unmet leader"), text)
                affected = event.get("affected_ids")
                sender_id = str(affected[0]) if isinstance(affected, list) and affected else ""
                if sender_id and sender_id == self_id:
                    # Your own line: say so, so it is not read as a rival speaking.
                    text = "You (" + text.split(":", 1)[0].strip() + "): " + text.split(":", 1)[-1].strip()
                elif not sender_id:
                    text = "Unknown speaker: " + text
                body = text.split(":", 1)[-1].strip()[:120]
                if (sender_id, body) in seen_chat:
                    continue  # the same speaker's line echoed again
                seen_chat.add((sender_id, body))
                chat_lines.append(pipeline._wire_line(f"chat.public.t{int(event.get('turn', 0))}.{index}", text))
    diplomacy_block = context.get("diplomacy", {})
    inbox = diplomacy_block.get("private_inbox", []) if isinstance(diplomacy_block, dict) else []
    for index, message in enumerate(pipeline._recent_history_events(inbox, pipeline.chat_history_max_messages())):
        if not isinstance(message, dict):
            continue
        text = pipeline.trim_chat_text(str(message.get("text", "")))
        if text:
            body = text.strip()[:120]
            from_id = str(message.get("from_player_id", ""))
            if (from_id, body) in seen_chat:
                continue
            seen_chat.add((from_id, body))
            sender = pipeline._player_chat_name(context, from_id) if from_id else "Rival"
            chat_lines.append(pipeline._wire_line(
                f"chat.private.t{int(message.get('turn', 0))}.{index}", f"{sender} (private): {text}"))
    lines.append("# == Chat Log ==")
    lines.extend(chat_lines or ["(no messages yet)"])
    lines.append(
        "Hint: actively use remember for deals, rival impressions, war aims, and multi-turn plans you will need "
        "later; set a duration in turns, or forever only when it matters the whole game. "
        "Forever notes are for things you want to remember permanently; never use them for specific units or positions."
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
            if city.get("knowledge") == "visible":
                xy = pipeline._parse_plot_coords(city.get("plot_id"))
                defense = _visible_city_defense(context, xy) if xy is not None else None
                damaged = city_defense_text(defense)
                if damaged:
                    parts.append(damaged)
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
    reasons = [r for r in diplo.get("reasons", []) or [] if isinstance(r, dict) and r.get("text")
               and "unknown reason" not in str(r.get("text")).lower()]
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


def _trade_stock_text(stock: dict[str, Any] | None, snapshot: dict[str, Any] | None = None) -> str:
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
                extra = ""
                if key == "strategics" and snapshot is not None:
                    from sidecar.civ6_diplomacy import _usable_mark
                    extra = _usable_mark(snapshot, str(row["resource_id"]))
                parts.append(f"{_resource_label(row['resource_id'])}:{int(row.get('amount') or 1)}{extra}")
    return " | ".join(parts)


def _luxury_ids(stock: dict[str, Any] | None) -> set[str]:
    if not isinstance(stock, dict):
        return set()
    return {str(r.get("resource_id")) for r in stock.get("luxuries", []) or [] if isinstance(r, dict) and r.get("resource_id")}


def _civ6_trade_lines(context: dict[str, Any], rivals: list[dict[str, Any]], diplomacy: dict[str, Any]) -> list[str]:
    """Civ5-style # == Diplomacy == block from civ6.diplomacy (absent with older mods)."""
    if not diplomacy:
        return []
    from sidecar import civ6_diplomacy as diplomacy_wire
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
    offer = _trade_stock_text(mine, context)
    lines.append(pipeline._wire_line("diplomacy.offer.you", offer or "(nothing tradable)"))
    lines.append(pipeline._wire_line(
        "diplomacy.offer.note",
        "Your stock that could go into a deal (luxuries, strategics, gold, gold per turn). "
        "Chat never executes a trade; use deal.<Leader> or a propose_cmd."))
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
        text = _trade_stock_text(trade, context) or "(nothing tradable seen)"
        wants = sorted(_resource_label(r) for r in my_lux - _luxury_ids(trade))
        if trade is not None and wants:
            text += " ; wants: " + ", ".join(wants)
        lines.append(pipeline._wire_line(f"diplomacy.request.{label}", text))
    lines.extend(diplomacy_wire.city_state_lines(context))
    lines.extend(diplomacy_wire.deal_status_lines(context))
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
            from sidecar import civ6_diplomacy as diplomacy_wire

            lines.append(pipeline._wire_line(f"rival.{name}.trades", diplomacy_wire.trade_lines(context, str(rival.get("player_id")))))
        elif isinstance(relation, dict):
            attitude = _attitude_label(relation.get("attitude_id"))
            if attitude:
                lines.append(pipeline._wire_line(f"rival.{name}.attitude", attitude))
        status = None
        if diplo is not None:
            from sidecar import civ6_diplomacy as diplomacy_wire

            status = diplomacy_wire.rival_status_line(context, str(rival.get("player_id")))
        if status:
            lines.append(pipeline._wire_line(f"rival.{name}.status", status))
        if isinstance(relation, dict):
            if relation.get("at_war") and not status:
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
    seat = context.get("_seat_memory")
    if isinstance(seat, dict):
        from sidecar import civ6_seat_memory

        for key, value in civ6_seat_memory.prompt_lines(seat):
            if value.strip():
                lines.append(pipeline._wire_line(key, value.strip()))
    history = context.get("history", {})
    from sidecar import civ6_turn_importance as importance

    cfg = importance.load_config()
    budget = int(cfg.get("journal_char_budget") or 48000)
    used = 0
    current = 0
    try:
        current = int((context.get("decision") or {}).get("turn") or 0)
    except (TypeError, ValueError):
        current = 0
    recent_n = int(cfg.get("recent_full_turns") or 3)
    if isinstance(history, dict):
        memory = history.get("memory_summary")
        if isinstance(memory, str) and memory.strip():
            lines.append(pipeline._wire_line("history.memory", _clip_sentence(memory.strip(), 180)))
        scored = context.get("_importance") if isinstance(context.get("_importance"), dict) else {}
        if scored:
            top = ", ".join(
                f"{row.get('trigger')} {row.get('score')}"
                for row in (scored.get("breakdown") or [])[:3]
                if isinstance(row, dict)
            )
            lines.append(pipeline._wire_line(
                "importance",
                f"{scored.get('adjusted')} ({scored.get('intelligence_tier')})"
                + (f"; {top}" if top else ""),
            ))
            lines.extend(importance.journal_rules_lines(float(scored.get("adjusted") or 0)))
        # Compact memory: last turn's plan in one line, plus one line per unit
        # (position, standing destination). Older paragraphs were copied back
        # verbatim (27-34k chars, ~70% plan copies).
        thought_rows = [entry for entry in history.get("thought_memory", []) if isinstance(entry, dict)]
        last = max(thought_rows, key=lambda entry: int(entry.get("turn") or 0), default=None)
        if last is not None:
            turn = int(last.get("turn") or 0)
            for field, label, cap in (("strategy", "strategy", 240), ("decision", "plan", 600)):
                text = re.sub(r"\s+", " ", str(last.get(field) or "")).strip()
                if text:
                    lines.append(pipeline._wire_line(f"T{turn}.{label}", _clip_sentence(text, cap)))
        lines.extend(_unit_memory_lines(context))
        remembered = [note for note in history.get("remembered", []) if isinstance(note, dict)]
        remember_n = int(cfg.get("remember_prompt") or 12)
        for note in remembered[-remember_n:]:
            if not str(note.get("text", "")).strip():
                continue
            expires = note.get("expires_turn")
            until = "forever" if expires is None else f"until T{expires}"
            text = re.sub(r"\s*\((?:until T\d+|forever)\)", "", str(note["text"]))
            text = re.sub(r"\bduration\s*[:=]\s*(?:\d{1,4}\s*turns?|forever|permanent|always)\b", "", text, flags=re.I)
            text = re.sub(r"\s{2,}", " ", text).strip(" ,;-")
            lines.append(pipeline._wire_line(
                f"remembered.T{int(note.get('turn', 0))}", f"{text} ({until})"
            ))
        lines.extend(civ6_apply_results.thoughts_lines(context))
    return lines


def _unit_memory_lines(context: dict[str, Any]) -> list[str]:
    """One line per own unit: where it is and the destination it is still walking to."""
    units = [u for u in context.get("your_units", []) or [] if isinstance(u, dict)]
    names = pipeline._build_unit_wire_id_map(units)
    out: list[str] = []
    for unit in units[:40]:
        uid = str(unit.get("unit_id") or "")
        if not uid or not unit.get("plot_id"):
            continue
        text = "at " + pipeline._plot_coords_text(unit.get("plot_id"))
        goal = unit.get("goal") if isinstance(unit.get("goal"), dict) else None
        if goal and goal.get("x") is not None and goal.get("y") is not None:
            text += f"; heading to ({goal['x']},{goal['y']})"
            if goal.get("set_turn") not in (None, ""):
                text += f" since T{goal['set_turn']}"
        out.append(pipeline._wire_line(f"unit.{names.get(uid, uid)}", text))
    return out


def _memory_section(context: dict[str, Any]) -> list[str]:
    """Long-term journal: older thought turns, situation log, remembered notes."""
    from sidecar import civ6_turn_importance as importance

    lines: list[str] = []
    history = context.get("history") if isinstance(context.get("history"), dict) else {}
    current = 0
    try:
        current = int((context.get("decision") or {}).get("turn") or 0)
    except (TypeError, ValueError):
        current = 0
    recent_n = int(importance.load_config().get("recent_full_turns") or 3)
    for entry in []:  # old plan paragraphs are no longer replayed (compact memory)
        if not isinstance(entry, dict):
            continue
        try:
            turn = int(entry.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if turn > current - recent_n:
            continue
        text = str(entry.get("situation") or entry.get("decision") or "").strip()
        if not text:
            continue
        key = f"memory.T{turn}"
        lines.append(pipeline._wire_line(key, text[:400]))
        adj = entry.get("importance_adjusted", entry.get("importance_score"))
        if adj not in (None, ""):
            lines.append(pipeline._wire_line(f"{key}.adjusted", adj))
        if entry.get("pinned") or entry.get("pin"):
            lines.append(pipeline._wire_line(f"{key}.pin", True))
        tier = entry.get("intelligence_tier") or entry.get("tier")
        if isinstance(tier, str) and tier.strip():
            lines.append(pipeline._wire_line(f"{key}.tier", tier.strip()))
    seat = context.get("_seat_memory") if isinstance(context.get("_seat_memory"), dict) else {}
    hist_log = history.get("situation_log") if isinstance(history.get("situation_log"), list) else None
    log_rows = hist_log if hist_log is not None else importance.situation_log_rows(seat, current)
    prompt_n = min(6, int(importance.load_config().get("situation_log_prompt") or 12))
    for row in log_rows[-prompt_n:]:
        turn = int(row.get("turn") or 0)
        text = str(row.get("text") or "").strip()
        if text:
            ended = row.get("ended_turn")
            suffix = f" ended T{ended}" if ended not in (None, "") else ""
            lines.append(pipeline._wire_line(f"memory.log.T{turn}", text[:240] + suffix))
    block = context.get("long_term_memory") if isinstance(context.get("long_term_memory"), dict) else None
    if block is None and isinstance(seat.get("long_term_memory"), dict):
        block = seat["long_term_memory"]
    for row in (block or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        turn = int(row.get("turn") or 0)
        key = f"memory.T{turn}" if not row.get("id") else f"memory.{row.get('id')}"
        lines.append(pipeline._wire_line(key, text[:400]))
        if row.get("pin") is True or row.get("pinned") is True:
            lines.append(pipeline._wire_line(f"{key}.pin", True))
    return lines


def _war_going_badly(context: dict[str, Any]) -> bool:
    if not combat_wire.war_active(context):
        return False
    for city in context.get("your_cities") or []:
        if not isinstance(city, dict):
            continue
        defense = city.get("defense") if isinstance(city.get("defense"), dict) else {}
        hp, max_hp = defense.get("hp"), defense.get("max_hp")
        if isinstance(hp, int) and isinstance(max_hp, int) and max_hp > 0 and hp * 2 < max_hp:
            return True
    civ6 = context.get("civ6") if isinstance(context.get("civ6"), dict) else {}
    extras = civ6.get("city_extra") if isinstance(civ6.get("city_extra"), dict) else {}
    for extra in extras.values():
        if isinstance(extra, dict):
            loyalty = extra.get("loyalty")
            if isinstance(loyalty, int) and not isinstance(loyalty, bool) and loyalty < 30:
                return True
    return False


def _advice_section(context: dict[str, Any]) -> list[str]:
    # "At war" means a war with a major civ. Barbarians (always hostile) and
    # free cities get their own line, not the war wording.
    at_war = bool(combat_wire.major_wars(context))
    in_reach = combat_wire.enemies_within_their_reach(context) if combat_wire.war_active(context) else False
    if at_war and in_reach:
        opening = (
            "- You are at war and an enemy is within move range. Use the WAR section: "
            "strike enemies in range."
        )
    elif at_war:
        opening = (
            "- You are at war, but no enemy unit is within move range of your army or cities."
        )
    elif combat_wire.hostiles_visible(context):
        opening = (
            "- You are not at war with any civilization. Barbarians or other hostile units are in sight"
            + (" and within move range: the WAR section lists strikes on them."
               if in_reach else "; none is within move range of your army or cities.")
            + ""
        )
    else:
        opening = (
            "- Units left without orders stay where they are."
        )
    lines = [
        opening,
        "- Before you finish: issue one command for each entry under REQUIRED COMMANDS.",
    ]
    if _war_going_badly(context):
        lines.append(
            "- This war is going badly: a city is under half health or loyalty is collapsing. "
            "Offer peace to the civ you are actually fighting if they will take it."
        )
    lines.extend(combat_wire.tactics_advice_lines(context))
    explored = coaching._civ6_explored_percent(context)
    if isinstance(explored, int) and explored < 100 and not combat_wire.war_active(context):
        command = ""
        if _explore_offered(context):
            command = (
                " Automate(explore), when it is listed on a unit's row, walks that scout, soldier, or ship "
                "toward the nearest fog it can reach this turn. Order it again next turn to keep going. "
                "Land units stop at the coast; ships explore water. MoveTo a tile you chose is just as valid."
            )
        lines.append(
            f"- The world map is {explored}% explored and {100 - explored}% still unexplored gray fog.{command}"
        )
    lines.append("- Pick research and civics before they run out so science and culture are never wasted.")
    lines.append(
        "- For legal.research.tech / legal.research.civic, pick only from the listed options — never re-pick a "
        "tech or civic you already finished."
    )
    if _has_queue_production(context):
        lines.append("- Do not queue production that is already building.")
    return lines


def _explore_offered(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    return any(
        isinstance(command, dict) and command.get("kind") == "explore"
        for command in snapshot.get("legal_commands") or []
    )


def _orders_execute_clause(snapshot: dict[str, Any] | None) -> str:
    if _has_queue_production(snapshot):
        return "unitId.command and cityName.production keys execute orders — never substitute prose for those keys. "
    return "unitId.command keys execute orders — never substitute prose for those keys. "


def build_civ6_response_instructions(snapshot: dict[str, Any]) -> str:
    """RESPONSE INSTRUCTIONS + OPTIONAL COMMANDS + REQUIRED COMMANDS (Civ5 layout)."""
    required = _civ6_required_rows(snapshot)
    count = len(required)
    count_lines = _count_lines(count)
    event_count = sum(1 for key, _ in required if key.startswith("Event."))

    example_rows = ['"commands.required.count":' + str(count)]
    for index, (key, value) in enumerate(required, start=1):
        if key.endswith(".command") or key.endswith(".production"):
            example_rows.append(f'"{index}.{key}":"{_example_command_value(value)}"')
        else:
            example_rows.append(f'"{index}.{key}":"..."')
    example_rows.append(f'"{count + 1}.chat.all":"Hello rivals."')

    resp = [
        "=== RESPONSE INSTRUCTIONS ===",
        "Reply with ONE JSON object containing every field below — no code fences, no text outside the object.",
        'Prefix JSON keys with the REQUIRED COMMANDS row number (e.g. "3.scout_1.command"); the host strips the numeric prefix.',
        "If the API provides separate thinking/reasoning text, keep prose there if you like; game-order keys must be in the JSON object.",
        "In your JSON object put commands.required.count first (must equal the required row count), then prose keys "
        "(map reads, thought.*, Event.*), then numbered game-order keys ("
        + (
            "unitId.command, cityName.production, legal.*, chat.*)."
            if _has_queue_production(snapshot)
            else "unitId.command, legal.*, chat.*)."
        ),
        "",
        "Prose and notes (JSON string values; first person as this leader):",
        "strategicmap.read = one paragraph — landmasses, coasts, fog, rivals, expansion lanes.",
        *(["tacticalmap.read = one short paragraph on image 2, the tactical close-up"
            + (f" ({_tactical_image_where(snapshot)})" if _tactical_image_where(snapshot) else "")
            + " — exact (x,y) of your units, threats, terrain and the tiles you will move to."]
           if "tacticalmap.read" in {k for k, _ in required} else []),
        "thought.situation = what matters on the board this turn.",
        "thought.freethinking = optional extended inner monologue.",
        "thought.strategy = long-term path to victory and why — prose only, no wire keys here.",
        "thought.plan = the turn plan: every command you issue this turn and its intention (see REQUIRED COMMANDS).",
        "Event.<Name>.log = required attention notes (see REQUIRED COMMANDS).",
        "remember = text plus duration; store deals, rival impressions, war aims, and multi-turn plans. "
        "Forever notes are for things you want to remember permanently; never use them for specific units or positions. "
        "opinion.* / history.* as needed.",
        *(
            ["plan.goal = victory type (science, culture, domination, diplomacy, religion, or score). "
             "plan.objective = attack|peace|improve|settle|research|defend, the aim, and by T<turn>. "
             "plan.objective.done = that kind when the objective is finished. Update the plan every turn."]
            if isinstance(snapshot.get("_seat_memory"), dict) else []
        ),
        f"Required Event.* logs this turn: {event_count} (numbered under REQUIRED COMMANDS).",
        "",
        "Game orders (executable JSON keys — must match REQUIRED COMMANDS rows):",
        "unitId.command = MoveTo(x,y) | AttackTo(x,y) | "
        + ("Automate(explore) | " if _explore_offered(snapshot) else "")
        + "FoundCity | Improve(x,y,IMPROVEMENT_X) (builders) | Fortify | Skip "
        "(one option per unit from its row; MoveTo(x,y) = any destination tile, the unit walks toward it).",
        *(
            ["cityName.production = UNIT_* | BUILDING_* | PROJECT_* from that city's listed options (only when "
             "currentProduction is NONE, or to switch on purpose)."]
            if _has_queue_production(snapshot) else []
        ),
        f"legal.research.tech, legal.research.civic, chat.all, {chat_dm_examples(snapshot)} — see OPTIONAL COMMANDS.",
        *(
            ["Automate(explore), when it is listed on that unit's row, walks a scout, soldier, or ship toward "
             "unrevealed tiles this turn. Order it again next turn to continue. Land units stop at the coast; "
             "ships explore water. Nothing assigns this for you."]
            if _explore_offered(snapshot) else []
        ),
        "",
        "GOOD JSON (entire reply — row numbers on keys; host strips the prefix):",
        "  {" + ", ".join(example_rows) + "}",
        "",
        *city_strike_prompt_lines(snapshot),
        "Command rules:",
        "- Movement: unitId.command = MoveTo(x,y) with any destination. One MoveTo spends the unit's remaining "
        "moves (unitId.moves of unitId.maxMovement) along the game's route; pick a destination at least that far "
        "on open ground. Hills, forest, and rivers cost extra; a step needs its full cost from the moves left, "
        "except that a unit that has not moved this turn can always enter one adjacent tile, however rough "
        "(that uses all its movement).",
        "- Never MoveTo a mountain, a water tile this unit cannot enter, or a tile another of your units of the same kind "
        "(military or civilian) already holds. Mountains are impassable; water is impassable to land units until they can embark. "
        "A rejected move says impassable when the tile cannot be entered, and no_path when no route exists. "
        "The unit then takes one step toward that destination on a tile it can enter. Do not repeat a destination that stays blocked.",
        f"- Coordinates: {coaching.civ6_y_axis_phrase(snapshot)} and x increases east; see the GAME "
        "section for X-wrap.",
        f"- {coaching.CIV6_UNIT_STACKING_GUIDANCE}",
        f"- {coaching.CIV6_MOVE_THEN_ATTACK_GUIDANCE}",
        *(
            ["- CITY STRIKES above are city attacks. Order CityName.rangeStrike = (x,y) "
             "with one coordinate from that city's line."]
            if city_strike_prompt_lines(snapshot) else []
        ),
        "- Attacks: AttackTo(x,y) options appear on the unit's own row only when a visible enemy (a civ you are at "
        "war with, or barbarians) is in reach — adjacent for melee, within range for ranged units.",
        *(
            ["- The host fires any ranged shot or city strike you leave unused."]
            if _offers_ranged_or_strike(snapshot) else []
        ),
        *(
            ["- A city with currentProduction set: leave cityName.production out unless you really mean to switch."]
            if _has_queue_production(snapshot) else []
        ),
        "- Hybrid control: " + native_fallback_policy(snapshot),
        "- Optional commands (chat, research, civics, remember) are encouraged when useful; chat.all only when you have an original line.",
    ]
    if any(isinstance(u, dict) and isinstance(u.get("goal"), dict) for u in snapshot.get("your_units") or []):
        resp.append(
            "- A unit with a goal line is already walking. If its row lists AttackTo, that attack is required. "
            "Order MoveTo only to redirect a unit that has no attack."
        )
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
    where = _tactical_image_where(snapshot)
    viewport_hint = "(x,y) to center image 2 next turn, or auto"
    if where:
        viewport_hint = f"{viewport_hint}. Image 2 is now {where}"
    optional_keys.append(("map.viewport", viewport_hint))
    optional_keys.append(("remember", "text (duration N turns | forever)"))
    from sidecar import civ6_priorities

    prio_lines = civ6_priorities.prompt_lines(snapshot)
    if prio_lines:
        optional_keys.append((civ6_priorities.REPLY_KEY, "preset name | none (see PRODUCTION PRESET)"))
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
        props = city_tokens.get(str(city.get("city_id")), {})
        # Strikes and attacks before purchases so a long buy list does not bury them.
        ordered_props = sorted(props, key=lambda prop: {"rangeStrike": 0, "attack": 1, "production": 2}.get(prop, 3))
        for prop in ordered_props:
            tokens = props[prop]
            key = f"{name}.{prop}"
            if key in required_keys:
                continue
            if prop == "production":
                optional_keys.append((key, f"bare ID from {name}.production.catalog"))
                continue
            if prop == "rangeStrike":
                optional_keys.append((key, "one (x,y) from the CITY STRIKES list"))
                continue
            shown = list(tokens)
            if prop == "purchase" and len(shown) > 6:
                shown = shown[:6]
            optional_keys.append((key, " | ".join(shown)))

    opt = [
        "=== OPTIONAL COMMANDS ===",
        "OPTIONAL COMMANDS are encouraged every turn — not leftovers. Required rows are only the minimum.",
        f"Issue as many optional commands as you want this turn: chat.all, {chat_dm_examples(snapshot)}, research, civics, remember, "
        "map.viewport, extra unit/city orders, and any other listed shape.",
        "There is no cap. Use numbered JSON keys that continue after the last required row.",
        "Use only shapes listed here or on unit/city rows.",
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
        "Event.* / thought.* / map reads = prose strings; "
        + (
            "unitId.command / cityName.production = game orders — "
            if _has_queue_production(snapshot)
            else "unitId.command = game orders — "
        )
        + "copy exactly one option from the row.",
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


def _offers_ranged_or_strike(snapshot: dict[str, Any]) -> bool:
    for command in snapshot.get("legal_commands") or []:
        if not isinstance(command, dict):
            continue
        if command.get("kind") == "city_attack":
            return True
        if command.get("kind") in ("attack_target", "range_attack", "melee_attack"):
            fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
            if fixed.get("ranged") is True:
                return True
    return False


def build_civ6_wire_prompt(
    context: dict[str, Any],
    map_stats: list[str] | None = None,
    *,
    unit_compact: bool = False,
    city_compact: bool = False,
) -> str:
    """Sectioned Civ VI prompt in the Civ5 layout (everything above RESPONSE INSTRUCTIONS)."""
    combat_wire.retain_runnable_attacks(context)
    sections = [
        pipeline._wire_section("GAME", _game_section(context, map_stats)),
        pipeline._wire_section("EMPIRE", _empire_section(
            context, unit_compact=unit_compact, city_compact=city_compact,
        )),
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
    from sidecar import civ6_attention

    attention = civ6_attention.lines(context)
    if attention:
        sections.append(pipeline._wire_section(civ6_attention.SECTION, attention))
    thoughts = _thoughts_section(context)
    if thoughts:
        sections.append(pipeline._wire_section("THOUGHTS", thoughts))
    memory = _memory_section(context)
    if memory:
        sections.append(pipeline._wire_section("MEMORY", memory))
    sections.append(pipeline._wire_section("ADVICE", _advice_section(context)))
    return "\n\n".join(sections)


def build_civ6_playable_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Slim model-facing view — mirrors pipeline_v2.build_playable_context for Civ VI."""
    context = pipeline.strip_empty_fields(copy.deepcopy(snapshot))
    if not isinstance(context, dict):
        return {}
    known_map = context.get("known_map")
    if isinstance(known_map, dict):
        # Builder site facts need the plots that are stripped below.
        from sidecar import civ6_prompt_coaching as coaching

        for unit in context.get("your_units") or []:
            if isinstance(unit, dict) and unit.get("unit_type_id") == "UNIT_BUILDER":
                xy = coaching._unit_xy(unit)
                if xy is not None:
                    unit["improve_sites"] = coaching.builder_improve_sites(snapshot, *xy)
        plots = [p for p in known_map.get("plots") or [] if isinstance(p, dict)]
        if plots:
            known_map["water_percent"] = round(100 * sum(1 for p in plots if p.get("water")) / len(plots))
        known_map.pop("plots", None)
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


def _assemble_model_wire(
    snapshot: dict[str, Any],
    context: dict[str, Any],
    map_stats: list[str] | None,
    *,
    unit_compact: bool,
    city_compact: bool,
) -> str:
    return (
        build_civ6_wire_prompt(
            context, map_stats=map_stats, unit_compact=unit_compact, city_compact=city_compact,
        )
        + "\n\n"
        + build_civ6_response_instructions(snapshot)
    )


def _compact_with_attention(snapshot, context, map_stats, text, limit, unit_compact, city_compact):
    """Budget pass. When ATTENTION items are trimmed, rebuild without them so their
    Event.<name>.log rows leave REQUIRED COMMANDS and the rows renumber."""
    from sidecar import civ6_attention
    from sidecar import civ6_prompt_budget as prompt_budget

    trimmed: list[str] = []
    key = civ6_attention.TRIMMED_KEY
    fired: list[str] = []
    try:
        for _ in range(4):
            dropped: list[str] = []
            text, fired = prompt_budget.compact_to_budget(text, limit, civ6_attention.collect(context), dropped)
            if not dropped:
                break
            trimmed.extend(dropped)
            context[key] = snapshot[key] = list(trimmed)
            text = _assemble_model_wire(
                snapshot, context, map_stats, unit_compact=unit_compact, city_compact=city_compact,
            )
        else:
            text, fired = prompt_budget.compact_to_budget(text, limit, civ6_attention.collect(context))
        if trimmed and "attention" not in fired:
            fired = [*fired, "attention"]
        return text, fired
    finally:
        snapshot.pop(key, None)
        context.pop(key, None)


def build_civ6_model_wire_text(snapshot: dict[str, Any], *, max_prompt_chars: int | None = None) -> str:
    from sidecar import civ6_prompt_budget as prompt_budget

    map_stats = pipeline._map_wire_stats_from_snapshot(snapshot)
    context = build_civ6_playable_context(snapshot)
    units = [unit for unit in context.get("your_units") or [] if isinstance(unit, dict)]
    cities = [city for city in context.get("your_cities") or [] if isinstance(city, dict)]
    unit_compact = prompt_budget.units_need_compact(len(units))
    city_compact = prompt_budget.cities_need_compact(len(cities))
    full = _assemble_model_wire(
        snapshot, context, map_stats, unit_compact=False, city_compact=False,
    )
    compactions: list[str] = []
    if unit_compact or city_compact:
        text = _assemble_model_wire(
            snapshot, context, map_stats, unit_compact=unit_compact, city_compact=city_compact,
        )
        if unit_compact:
            compactions.append("units_compact")
        if city_compact:
            compactions.append("cities_compact")
    else:
        text = full
    limit = prompt_budget.resolve_max_prompt_chars(snapshot, max_prompt_chars)
    if limit > 0 and len(text) > limit:
        text, fired = _compact_with_attention(snapshot, context, map_stats, text, limit, unit_compact, city_compact)
        compactions.extend(fired)
    prompt_budget.store_report(snapshot, prompt_budget.make_report(full, text, limit, compactions))
    return text


def _expansion_threat_lines(summary: dict[str, Any], threats: bool = True) -> list[str]:
    """Plain facts from strategic_summary.expansion / .threat (no advice)."""
    out: list[str] = []
    exp = summary.get("expansion")
    if isinstance(exp, dict) and "cities" in exp:
        peers = [p for p in exp.get("met_majors") or [] if isinstance(p, dict)]
        peer_text = ", ".join(f"{p.get('player_id')}={p.get('cities')}" for p in peers[:8]) or "none met"
        out.append(pipeline._wire_line(
            "expansion.cities",
            f"you {exp.get('cities')}; met majors {peer_text}; settlers on map "
            f"{exp.get('settlers_on_map', 0)}; cities building a settler {exp.get('cities_building_settler', 0)}",
        ))
    threat = summary.get("threat") if threats else None
    if isinstance(threat, dict):
        hostiles = [h for h in threat.get("hostiles") or [] if isinstance(h, dict)]
        camps = [c for c in threat.get("camps") or [] if isinstance(c, dict)]
        out.append(pipeline._wire_line(
            "threat.near_cities",
            f"visible hostile land units within {threat.get('radius', 6)} tiles {len(hostiles)}; "
            f"revealed camps {len(camps)}; your land combat units there {threat.get('defenders', 0)}",
        ))
        for i, h in enumerate(sorted(hostiles, key=lambda r: r.get("distance", 99))[:6]):
            out.append(pipeline._wire_line(
                f"threat.hostile.{i}",
                f"{h.get('unit_type')} ({h.get('owner_kind')} {h.get('owner_id')}) at ({h.get('x')},{h.get('y')}), "
                f"{h.get('distance')} tiles from {h.get('nearest_city')}",
            ))
        for i, c in enumerate(sorted(camps, key=lambda r: r.get("distance", 99))[:3]):
            out.append(pipeline._wire_line(
                f"threat.camp.{i}",
                f"barbarian camp at ({c.get('x')},{c.get('y')}), {c.get('distance')} tiles from {c.get('nearest_city')}",
            ))
    return out
