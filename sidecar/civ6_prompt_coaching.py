"""Civ6 soft coaching / REQUIRED COMMANDS helpers ported from Civ5 wire patterns.

Prompt guidance stays coaching (never hard rules). Map-axis text follows the renderer's
orientation (``map_render_civ6.civ6_map_north_up``) so image and prompt always agree.
"""
from __future__ import annotations

from typing import Any

from sidecar import pipeline_v2 as pipeline

CIV6_RETREAT_HEAL_HP_THRESHOLD = 30
CIV6_EXPLORE_STALL_TURNS = 5
CIV6_EXPLORE_STALL_BELOW_PCT = 90
# Consecutive turns with no newly revealed tiles. The line fires on the next
# turn after this gap, and only while the true map is still under 80%.
CIV6_EXPLORE_QUIET_TURNS = 4
CIV6_EXPLORE_NUDGE_BELOW_PCT = 80

CIV6_SETTLER_MAP_ADVICE = (
    "Carefully observe the attached map to choose a settle location, and remember it for "
    "as many turns as the walk takes. Weigh strategic and luxury resources, choke points, "
    "fresh water and coast access, and tile yields (food/production/gold)."
)

CIV6_EXPANSION_COACHING = (
    "Expansion: a Settler that sits idle wastes growth. Prefer FoundCity this turn when the "
    "tile is legal and decent (fresh water or coast, not cramped by another city). If the "
    "best site is a few tiles away, MoveTo that tile and FoundCity as soon as FoundCity is "
    "legal — do not park the Settler on your capital or wander the map for ten-plus turns."
)

CIV6_CHAT_VARIETY_COACHING = (
    "Chat: do not repeat your opening introduction every turn. After first contact, send a "
    "fresh line tied to this turn (deal, threat, tease, map discovery, war, amenity, or "
    "silence via no chat). Prefer a private chat.<rival leader> key for one met major rival; "
    "use chat.all sparingly. "
    "A near-copy or re-introduction after your first public line is dropped, not sent. "
    "thought.strategy is planning prose — do not paste it into chat."
)

CIV6_CAPITAL_T1_COACHING = (
    "Founding: unless this start tile is clearly bad (no fresh water or coast, or FoundCity is "
    "illegal here), found the capital this turn. Walking inland for a 'high-yield' tile delays "
    "science, culture and production. Prefer coast and fresh water when they are legal."
)

CIV6_MOVE_THEN_ATTACK_GUIDANCE = (
    "When an attack is offered, prefer it over a move: AttackTo on a unit row "
    "(melee, ranged, or bombard) and rangeStrike on a city row (a city attack or city strike). "
    "Move instead only when you judge that attack the wrong fight. "
    "A unit with leftover movement can often still attack this turn after moving — "
    "do not treat \"already moved\" as \"cannot attack\" unless the unit has 0 moves left "
    "or the attack is otherwise illegal."
)

CIV6_UNIT_STACKING_GUIDANCE = (
    "Civ6 stacking: typically one military formation-class unit per tile, plus one civilian "
    "or support unit; two military units of the same formation class cannot share a tile. "
    "Use corps/armies and support units (e.g. battering ram, siege tower) intentionally."
)


def _civ6_tactical_map_attached(snapshot: dict[str, Any] | None) -> bool:
    """True when the tactical close-up is (or, before rendering, will be) attached.

    After rendering, run_civ6 stores the real manifest in advciv.map_images; only a
    "viewport" entry means the tactical image went out. Before rendering, the
    context-budget plan says whether the tactical image will be omitted.
    """
    if not isinstance(snapshot, dict):
        return False
    advciv = snapshot.get("advciv")
    if not isinstance(advciv, dict):
        return True
    manifest = advciv.get("map_images")
    if isinstance(manifest, list) and manifest:
        return any(isinstance(row, dict) and row.get("role") == "viewport" for row in manifest)
    budget = advciv.get("context_budget")
    if isinstance(budget, dict) and (budget.get("omit_tactical") is True or budget.get("tactical_image_size") == 0):
        return False
    return True


def _civ6_attach_map_images(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return True
    return pipeline.map_image_attach_turn(snapshot)


def civ6_required_thought_rows(snapshot: dict[str, Any] | None) -> list[str]:
    """Map-read + thought keys that belong in REQUIRED COMMANDS and the required count."""
    rows: list[str] = []
    if _civ6_attach_map_images(snapshot):
        rows.append(
            "strategicmap.read = one short paragraph on the attached strategic map "
            "(land vs water, chokes, your borders, one takeaway)"
        )
        if _civ6_tactical_map_attached(snapshot):
            rows.append(
                "tacticalmap.read = one short paragraph on the attached tactical map "
                "(key (x,y) for units, cities, resources)"
            )
    rows.append(
        "thought.situation = one paragraph board read this turn "
        "(economy, science, amenities, military, geography; new observations only)"
    )
    rows.append(
        "thought.strategy = one paragraph: long-term path to victory, then this turn's plan "
        "for each required and optional command you will issue"
    )
    return rows


def civ6_optional_commands_preamble_lines(required_count: int | None = None) -> list[str]:
    lines = [
        "OPTIONAL COMMANDS are encouraged every turn — not leftovers. Required rows are only the minimum.",
        "Issue as many optional commands as you want this turn: chat.all, chat.<rival leader>, diplomacy deals, "
        "research, map.viewport, extra unit/city orders, and any other listed shape.",
        "There is no cap. Models often emit only required rows — you may keep going with useful optionals.",
        "thought.freethinking = ... is optional free-form reflection (not counted as required).",
    ]
    if required_count is not None:
        n = max(0, int(required_count))
        if n <= 0:
            lines.append(
                "There are no required command rows this turn. Still issue as many optional commands as useful, "
                "numbered from 1."
            )
        else:
            lines.append(
                f"There are {n} required commands. Respond with every required command, enumerated from 1 to {n}."
            )
            lines.append(
                f"After row {n}, add as many optional commands as useful starting at {n + 1}. There is no cap."
            )
    return lines


def civ6_y_axis_phrase(snapshot: dict[str, Any] | None = None) -> str:
    """How plot y maps onto the attached images (same switch the renderer uses)."""
    from sidecar.map_render_civ6 import civ6_map_north_up

    if civ6_map_north_up(snapshot):
        return "game-plot y increases north (up on the map image; north at top)"
    return "game-plot y increases south (down on the map image)"


def civ6_map_axes_wrap_guidance(snapshot: dict[str, Any] | None = None) -> str:
    """Standing map-axis / X-wrap coaching for Civ6 (orientation matches the images)."""
    width = None
    wrap_x = True
    if isinstance(snapshot, dict):
        game = snapshot.get("game")
        if isinstance(game, dict):
            try:
                width = int(game.get("map_width")) if game.get("map_width") is not None else None
            except (TypeError, ValueError):
                width = None
            if width is not None and width <= 0:
                width = None
            if game.get("wrap_x") is False:
                wrap_x = False
    w_label = str(width) if width is not None else "map.width"
    if width is not None and width >= 20:
        near = width - 10
        seam_example = (
            f"with width {w_label}, a tile at x={near} and a tile at x=10 are 20 tiles apart "
            f"(10+10), not the long way around"
        )
    else:
        seam_example = (
            f"with width {w_label}, a tile at x=width-10 and a tile at x=10 are 20 tiles apart "
            f"(10+10), not the long way around"
        )
    wrap_clause = (
        f"The world wraps on X only (max X loops to 0); Y does not wrap. "
        f"Distance across the X seam uses the short way: {seam_example}."
        if wrap_x
        else "This map does not wrap on X; treat left/right edges as map borders."
    )
    return (
        "Map axes on the strategic/tactical images: game-plot x increases east (right on the image); "
        f"{civ6_y_axis_phrase(snapshot)} — Civ6 hex grid, odd rows shifted half a hex east. "
        f"{wrap_clause}"
    )


def civ6_unit_health_percent(unit: dict[str, Any]) -> int | None:
    health = unit.get("health")
    if isinstance(health, dict):
        current = health.get("current")
        maximum = health.get("maximum")
        if isinstance(current, int) and isinstance(maximum, int) and maximum > 0:
            return int(current * 100 / maximum)
    raw = unit.get("health_percent")
    if isinstance(raw, int):
        return raw
    return None


def civ6_wounded_hp_label(pct: int | None) -> str | None:
    if not isinstance(pct, int) or pct >= 100:
        return None
    return f"{pct}%"


def _civ6_explored_percent(snapshot: dict[str, Any]) -> int | None:
    """Whole-map reveal percent. The strategic image's crop percent is not this."""
    known = snapshot.get("known_map")
    if not isinstance(known, dict):
        return None
    cached = known.get("explored_percent")
    if isinstance(cached, int):
        return max(0, min(100, cached))
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    try:
        width = int(game.get("map_width") or 0)
        height = int(game.get("map_height") or 0)
        revealed = int(known.get("revealed_count"))
    except (TypeError, ValueError):
        return None
    total = width * height
    if total <= 0 or revealed < 0:
        return None
    return max(0, min(100, (revealed * 100) // total))


def civ6_true_explored(snapshot: dict[str, Any]) -> tuple[int, int, int] | None:
    """Revealed tiles over the whole map. The cropped visibility grid is not this."""
    known = snapshot.get("known_map")
    game = snapshot.get("game")
    if not isinstance(known, dict) or not isinstance(game, dict):
        return None
    try:
        width = int(game.get("map_width") or 0)
        height = int(game.get("map_height") or 0)
        revealed = int(known.get("revealed_count"))
    except (TypeError, ValueError):
        return None
    if isinstance(revealed, bool) or revealed < 0:
        return None
    total = width * height
    if total <= 0:
        return None
    return revealed, total, max(0, min(100, (revealed * 100) // total))


def _unit_moves_left(unit: dict[str, Any]) -> int | None:
    movement = unit.get("movement")
    if isinstance(movement, dict):
        current = movement.get("current")
        if isinstance(current, int) and not isinstance(current, bool):
            return current
    for key in ("moves_remaining", "moves"):
        value = unit.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def civ6_naval_explore_attention(snapshot: dict[str, Any]) -> str | None:
    """Push a ship into coastal fog once one exists and the world is still dark."""
    explored = _civ6_explored_percent(snapshot)
    if not isinstance(explored, int) or explored >= CIV6_EXPLORE_STALL_BELOW_PCT:
        return None
    ships = 0
    for unit in snapshot.get("your_units") or []:
        if not isinstance(unit, dict) or unit.get("domain_id") != "DOMAIN_SEA":
            continue
        kind = str(unit.get("unit_class_id") or "")
        type_id = str(unit.get("unit_type_id") or "")
        if kind == "FORMATION_CLASS_CIVILIAN":
            continue
        if any(tag in type_id for tag in ("TRADER", "GREAT_", "SETTLER", "BUILDER", "MISSIONARY", "APOSTLE")):
            continue
        moves = _unit_moves_left(unit)
        if moves is None:
            if unit.get("needs_orders") is False:
                continue
        elif moves <= 0:
            continue
        ships += 1
    if ships <= 0:
        return None
    true = civ6_true_explored(snapshot)
    pct = true[2] if true is not None else explored
    noun = "ship" if ships == 1 else "ships"
    return (
        f"NAVAL EXPLORE: {ships} {noun} can still move and the world is only {pct}% revealed "
        "(your real visibility, not the trimmed picture). Send a ship along the coast into unexplored water this turn."
    )


def civ6_lethargy_attention(snapshot: dict[str, Any]) -> str | None:
    """War with no fighting, an empty city queue, or a military unit that has sat still."""
    from sidecar import civ6_seat_memory

    return civ6_seat_memory.lethargy_line(snapshot)


def civ6_explore_stall_line(turns_since_reveal: int) -> str:
    """The temporary exploration nudge. N is the consecutive quiet-turn count."""
    return (
        f"It has been {int(turns_since_reveal)} turns without revealing any new tiles. "
        "Continue exploring: send scouts/ships into unexplored areas."
    )


def civ6_exploration_attention(snapshot: dict[str, Any]) -> str | None:
    metric = snapshot.get("_explore_metric")
    if isinstance(metric, dict):
        since = metric.get("turns_since_reveal")
        percent = metric.get("percent")
        if (
            isinstance(since, int) and not isinstance(since, bool)
            and isinstance(percent, int) and not isinstance(percent, bool)
            and percent < CIV6_EXPLORE_NUDGE_BELOW_PCT
            and since > CIV6_EXPLORE_QUIET_TURNS
        ):
            return civ6_explore_stall_line(since)
    explored = _civ6_explored_percent(snapshot)
    if not isinstance(explored, int) or explored >= CIV6_EXPLORE_STALL_BELOW_PCT:
        return None
    history = snapshot.get("history")
    tracking = history.get("explore_tracking") if isinstance(history, dict) else None
    samples = tracking.get("samples") if isinstance(tracking, dict) else None
    if not isinstance(samples, list) or len(samples) < 2:
        if explored < 25:
            return (
                f"Map only {explored}% explored — soft advice: give scouts Automate(explore) or push them into fog "
                "when safe; under-explored maps hide settle sites and rivals."
            )
        return None
    try:
        newest = max(samples, key=lambda row: int(row.get("turn", -1)) if isinstance(row, dict) else -1)
        newest_turn = int(newest.get("turn", -1))
        newest_revealed = int(newest.get("revealed", -1))
    except (TypeError, ValueError, AttributeError):
        return None
    older = [
        row
        for row in samples
        if isinstance(row, dict)
        and int(row.get("turn", -1)) <= newest_turn - CIV6_EXPLORE_STALL_TURNS
    ]
    if not older:
        return None
    try:
        baseline = max(int(row.get("revealed", -1)) for row in older)
    except (TypeError, ValueError):
        return None
    if newest_revealed >= 0 and baseline >= 0 and newest_revealed <= baseline:
        return (
            f"No new exploration in {CIV6_EXPLORE_STALL_TURNS}+ turns while map is only "
            f"{explored}% explored — soft advice: send a scout or military unit into fog this turn."
        )
    return None


def civ6_low_hp_retreat_attention(snapshot: dict[str, Any]) -> str | None:
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    bits: list[str] = []
    for unit in units:
        hp = civ6_unit_health_percent(unit)
        if not isinstance(hp, int) or hp >= CIV6_RETREAT_HEAL_HP_THRESHOLD:
            continue
        # Skip pure civilians for retreat-heal coaching.
        type_id = str(unit.get("unit_type_id") or "")
        if any(token in type_id for token in ("SETTLER", "BUILDER", "TRADER", "MISSIONARY", "APOSTLE")):
            continue
        unit_id = unit.get("unit_id")
        prefix = wire_ids.get(str(unit_id), "unit") if isinstance(unit_id, str) else "unit"
        bits.append(f"{prefix} at {hp}% HP")
    if not bits:
        return None
    joined = "; ".join(bits[:6])
    more = "" if len(bits) <= 6 else f" (+{len(bits) - 6} more)"
    return (
        f"{joined}{more} — almost always better to retreat and heal "
        "unless this is an intentional sacrifice"
    )


def _civ6_attack_target_keys(snapshot: dict[str, Any]) -> dict[tuple[int, int], list[str]]:
    """Map target plot -> list of friendly unit wire ids that can attack it (from legal_commands)."""
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    grouped: dict[tuple[int, int], list[str]] = {}
    for command in snapshot.get("legal_commands", []) or []:
        if not isinstance(command, dict) or command.get("kind") != "attack_target":
            continue
        fixed = command.get("fixed_arguments") or {}
        if not isinstance(fixed, dict):
            continue
        unit_id = fixed.get("unit_id")
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if x is None or y is None:
            plot_id = fixed.get("plot_id")
            if isinstance(plot_id, str):
                parsed = pipeline._parse_plot_coords(plot_id) if hasattr(pipeline, "_parse_plot_coords") else None
                if isinstance(parsed, tuple) and len(parsed) == 2:
                    x, y = parsed
        try:
            xi, yi = int(x), int(y)
        except (TypeError, ValueError):
            continue
        if not isinstance(unit_id, str):
            continue
        prefix = wire_ids.get(unit_id, unit_id)
        bucket = grouped.setdefault((xi, yi), [])
        if prefix not in bucket:
            bucket.append(prefix)
    return grouped


def civ6_focus_fire_attention(snapshot: dict[str, Any]) -> str | None:
    grouped = _civ6_attack_target_keys(snapshot)
    bits: list[str] = []
    for (x, y), attackers in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(attackers) < 2:
            continue
        bits.append(f"{len(attackers)} friendly units ({', '.join(attackers[:4])}) can hit ({x},{y})")
    if not bits:
        return None
    return (
        " | ".join(bits[:3])
        + " — soft advice: focus-fire the shared target rather than splitting strikes"
    )


def civ6_economy_attention(snapshot: dict[str, Any]) -> list[str]:
    out: list[str] = []
    empire = snapshot.get("your_empire")
    if not isinstance(empire, dict):
        return out
    gold = empire.get("gold")
    gpt = empire.get("gold_per_turn")
    try:
        gold_i = int(gold) if gold is not None else None
        gpt_i = int(gpt) if gpt is not None else None
    except (TypeError, ValueError):
        gold_i, gpt_i = None, None
    if isinstance(gpt_i, int) and gpt_i < 0:
        out.append(
            f"Gold per turn is {gpt_i} — soft advice: bankruptcy / negative GPT shrinks maintenance "
            "headroom and can force unit or building losses; raise income or cut costs."
        )
    if isinstance(gold_i, int) and gold_i < 0:
        out.append(
            f"Treasury is {gold_i} gold — soft advice: clear the deficit before expanding army size."
        )
    amenities = empire.get("amenities")
    if isinstance(amenities, dict):
        net = amenities.get("net")
        try:
            net_i = int(net) if net is not None else None
        except (TypeError, ValueError):
            net_i = None
        if isinstance(net_i, int) and net_i < 0:
            out.append(
                f"Empire amenities net {net_i} — soft advice: unhappy cities grow slower and revolt risk rises; "
                "fix luxuries, entertainment, or policies. Builders: improve luxury resources in your borders "
                "(plantation, camp, quarry, etc.) — each new luxury type gives amenities to several cities; "
                "trade for a luxury you lack."
            )
    return out


def civ6_diplomacy_guidance(snapshot: dict[str, Any]) -> list[str]:
    lines = [
        "Diplomacy: when legal.trade / deal rows list a rival, prefer a clear propose line "
        "(legal.trade.offer.Leader = ...) and answer pending deals with accept/reject/counter shapes.",
        "Soft advice: haggle in private DMs (chat.<rival leader>) before or with a formal deal — "
        "explain what you want and what you offer.",
        "chat.all is broadcast posture — funny/original tone is welcome; skip spam when the lobby "
        "is already noisy every turn; keep military secrets in DMs.",
    ]
    inventories = snapshot.get("legal_trade_inventory")
    if isinstance(inventories, list) and inventories:
        lines.append(
            "Per-civ tradeable inventories appear under legal trade / inventory rows when known — "
            "offer only items you can actually give."
        )
    return lines


def civ6_loyalty_attention(snapshot: dict[str, Any]) -> list[str]:
    """Cities near a loyalty flip, with the levers that stop it."""
    civ6 = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    extras = civ6.get("city_extra") if isinstance(civ6.get("city_extra"), dict) else {}
    notes: list[str] = []
    for city in snapshot.get("your_cities") or []:
        if not isinstance(city, dict):
            continue
        extra = extras.get(str(city.get("city_id")))
        if not isinstance(extra, dict):
            continue
        loyalty = extra.get("loyalty")
        if not isinstance(loyalty, int) or isinstance(loyalty, bool) or loyalty >= 40:
            continue
        name = pipeline._city_prompt_name(city)
        per = extra.get("loyalty_per_turn")
        drift = f", {per:+g}/turn" if isinstance(per, (int, float)) and not isinstance(per, bool) else ""
        notes.append(
            f"LOYALTY: {name} is at {loyalty}{drift}. A city near 0 rebels. "
            "Raise amenities, keep a governor, or ease the nearby pressure before it flips."
        )
    return notes


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unit_id_from(value: Any) -> str | None:
    text = str(value or "")
    start = text.find("UNIT_")
    while start >= 0:
        cursor = start + len("UNIT_")
        if cursor < len(text) and text[cursor].isdigit():
            while cursor < len(text) and (text[cursor].isdigit() or text[cursor] == "_"):
                cursor += 1
            token = text[start:cursor].rstrip("_")
            if any(ch.isdigit() for ch in token):
                return token
        start = text.find("UNIT_", start + len("UNIT_"))
    return None


def explore_quiet_units(snapshot: dict[str, Any], turns_needed: int = 2) -> list[str]:
    """Units whose explore orders revealed nothing on this many distinct turns.

    While most of the map is still fog, keep Automate(explore) visible: hiding
    it is what left explorers walking into the same mountain and water tiles.
    """
    explored = _civ6_explored_percent(snapshot)
    if isinstance(explored, int) and explored < CIV6_EXPLORE_NUDGE_BELOW_PCT:
        return []
    history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
    rows = history.get("command_results") if isinstance(history.get("command_results"), list) else []
    by_unit: dict[str, set[int]] = {}
    for item in rows:
        if not isinstance(item, dict) or "explore_no_reveal" not in str(item.get("reason") or ""):
            continue
        turn = _as_int(item.get("turn"))
        if turn is None:
            continue
        blobs = [item.get("identity"), item.get("command_id"), *(item.get("affected_ids") or [])]
        for blob in blobs:
            unit_id = _unit_id_from(blob)
            if unit_id:
                by_unit.setdefault(unit_id, set()).add(turn)
    return sorted(unit for unit, turns in by_unit.items() if len(turns) >= turns_needed)


def civ6_expansion_attention(snapshot: dict[str, Any]) -> str | None:
    """City-count target for this turn, and settler due when a city can train one."""
    from sidecar.civ6_priorities import ONLINE_AIM_TURN, _SPEED_PERCENT, _game_speed, situation_for_city

    cities = [city for city in snapshot.get("your_cities") or [] if isinstance(city, dict)]
    if not cities:
        return None
    situation = situation_for_city(snapshot, cities[0])
    target = _as_int(situation.get("city_target"))
    if target is None or len(cities) >= target:
        return None
    speed = str(_game_speed(snapshot) or "GAMESPEED_ONLINE").upper()
    percent = _SPEED_PERCENT.get(speed, 200) or 200
    aim_turn = (ONLINE_AIM_TURN * 200) // percent
    speed_name = speed.replace("GAMESPEED_", "").title() or "Online"
    band = "6-8" if situation.get("land") is not False else "6"
    line = (
        f"EXPANSION: {len(cities)} cities. On {speed_name}, aim for {band} cities by turn {aim_turn} "
        f"(this turn's target is {target})."
    )
    if situation.get("need_expansion"):
        line += _settler_due_clause(snapshot, situation, target)
    return line


def _settler_due_clause(snapshot: dict[str, Any], situation: dict[str, Any], target: int) -> str:
    """Name the purchase and priority commands the prompt already offers."""
    from sidecar.civ6_priorities import priorities_supported

    cities = [city for city in snapshot.get("your_cities") or [] if isinstance(city, dict)]
    city_n = len(cities)
    level = 2 if city_n + 2 < int(target) else 1
    parts: list[str] = []
    purchase = _affordable_settler_purchase(snapshot)
    if purchase is not None:
        city, token, cost, yield_name, balance = purchase
        parts.append(f"{city}.purchase = {token} ({cost} {yield_name}, you have {balance})")
    produced = _offered_settler_production(snapshot)
    if produced is not None:
        parts.append(f"{produced}.production = UNIT_SETTLER")
    if priorities_supported(snapshot):
        parts.append(
            f'"priorities": "expansion:{level}" '
            f"(add expansion:{level} to that complete set; a priority you leave out is switched off)"
        )
    if not parts:
        return " Settler due."
    return " Settler due: " + ", or ".join(parts) + "."


def _affordable_settler_purchase(
    snapshot: dict[str, Any],
) -> tuple[str, str, int, str, int] | None:
    """Cheapest settler the offer list can pay for. Unaffordable buys are omitted."""
    cities = {
        str(city.get("city_id")): pipeline._city_prompt_name(city)
        for city in snapshot.get("your_cities") or []
        if isinstance(city, dict)
    }
    best: tuple[int, str, str, int, str, int] | None = None
    for command in snapshot.get("legal_commands") or []:
        if not isinstance(command, dict) or command.get("kind") != "purchase_item":
            continue
        fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
        item = str(fixed.get("item_id") or "")
        if "SETTLER" not in item.upper():
            continue
        cost = _as_int(fixed.get("cost"))
        if cost is None or cost <= 0:
            continue
        yield_name = "faith" if str(fixed.get("yield") or "").lower() == "faith" else "gold"
        balance = _stockpile(snapshot, yield_name)
        if balance is None or cost > balance:
            continue
        token = f"{item}:faith" if yield_name == "faith" else item
        city = cities.get(str(fixed.get("city_id") or ""), str(fixed.get("city_id") or "a city"))
        row = (cost, city, token, cost, yield_name, balance)
        if best is None or row < best:
            best = row
    if best is None:
        return None
    _, city, token, cost, yield_name, balance = best
    return city, token, cost, yield_name, balance


def _offered_settler_production(snapshot: dict[str, Any]) -> str | None:
    """City prompt name when that city's production row offers a settler."""
    from sidecar.civ6_command_wire import city_command_token

    cities = {
        str(city.get("city_id")): pipeline._city_prompt_name(city)
        for city in snapshot.get("your_cities") or []
        if isinstance(city, dict)
    }
    for command in snapshot.get("legal_commands") or []:
        if not isinstance(command, dict) or command.get("kind") != "queue_production":
            continue
        fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
        pair = city_command_token(command)
        if pair is None or pair[0] != "production" or "SETTLER" not in str(pair[1]).upper():
            continue
        return cities.get(str(fixed.get("city_id") or ""), str(fixed.get("city_id") or "a city"))
    return None


def _stockpile(snapshot: dict[str, Any], yield_name: str) -> int | None:
    if yield_name == "faith":
        from sidecar.civ6_governance import governance

        gov = governance(snapshot)
        religion = gov.get("religion") if isinstance(gov.get("religion"), dict) else {}
        faith = _as_int(religion.get("faith"))
        if faith is not None:
            return faith
        empire = snapshot.get("your_empire") if isinstance(snapshot.get("your_empire"), dict) else {}
        return _as_int(empire.get("faith"))
    empire = snapshot.get("your_empire") if isinstance(snapshot.get("your_empire"), dict) else {}
    return _as_int(empire.get("gold"))


def _cities_below_target(snapshot: dict[str, Any]) -> bool:
    from sidecar.civ6_priorities import situation_for_city

    cities = [city for city in snapshot.get("your_cities") or [] if isinstance(city, dict)]
    if not cities:
        return False
    target = _as_int(situation_for_city(snapshot, cities[0]).get("city_target"))
    return target is not None and len(cities) < target


def _exploration_needed(snapshot: dict[str, Any]) -> bool:
    """Scouts are a buy only while the map is still dark or the reveal streak has stalled."""
    metric = snapshot.get("_explore_metric")
    if isinstance(metric, dict):
        since = metric.get("turns_since_reveal")
        percent = metric.get("percent")
        if (
            isinstance(since, int) and not isinstance(since, bool)
            and isinstance(percent, int) and not isinstance(percent, bool)
            and percent < CIV6_EXPLORE_NUDGE_BELOW_PCT
            and since > CIV6_EXPLORE_QUIET_TURNS
        ):
            return True
    explored = _civ6_explored_percent(snapshot)
    return isinstance(explored, int) and explored < CIV6_EXPLORE_NUDGE_BELOW_PCT


def civ6_military_cap_attention(snapshot: dict[str, Any]) -> str | None:
    """Soft cap: at peace, an army more than twice the city count should stop growing."""
    from sidecar.civ6_priorities import _unit_counts, situation_for_city

    cities = [city for city in snapshot.get("your_cities") or [] if isinstance(city, dict)]
    if not cities:
        return None
    situation = situation_for_city(snapshot, cities[0])
    if not situation.get("army_heavy"):
        return None
    _, military = _unit_counts(snapshot)
    return (
        f"MILITARY: {military} military units for {len(cities)} cities, and you are at peace. "
        "That is more than twice your cities. Favour settlers, builders, and districts over more combat units "
        "until a war starts."
    )


def _best_purchase_labels(snapshot: dict[str, Any], limit: int = 3) -> list[str]:
    cities = {
        str(city.get("city_id")): pipeline._city_prompt_name(city)
        for city in snapshot.get("your_cities") or []
        if isinstance(city, dict)
    }
    below = _cities_below_target(snapshot)
    exploring = _exploration_needed(snapshot)
    rows: list[tuple[int, int, str]] = []
    for command in snapshot.get("legal_commands") or []:
        if not isinstance(command, dict) or command.get("kind") != "purchase_item":
            continue
        fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
        item = str(fixed.get("item_id") or "")
        cost = _as_int(fixed.get("cost"))
        if not item or cost is None:
            continue
        upper = item.upper()
        if "SETTLER" in upper:
            rank = 0
        elif "BUILDER" in upper:
            rank = 1
        elif "SCOUT" in upper or "RECON" in upper:
            # Below the city target, scouts wait unless the map still needs exploring.
            if below and not exploring:
                continue
            rank = 2
        elif below:
            continue
        else:
            rank = 2
        yield_name = str(fixed.get("yield") or "gold")
        city = cities.get(str(fixed.get("city_id") or ""), str(fixed.get("city_id") or "a city"))
        rows.append((rank, cost, f"{item} in {city} ({cost} {yield_name})"))
    rows.sort()
    labels: list[str] = []
    for _, _, label in rows:
        if label in labels:
            continue
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def civ6_idle_resources_attention(snapshot: dict[str, Any]) -> str | None:
    """Unspent gold, faith, and envoys, with the concrete buys the snapshot already priced."""
    from sidecar.civ6_diplomacy import diplomacy
    from sidecar.civ6_governance import governance

    bits: list[str] = []
    empire = snapshot.get("your_empire") if isinstance(snapshot.get("your_empire"), dict) else {}
    gold = _as_int(empire.get("gold"))
    gpt = _as_int(empire.get("gold_per_turn"))
    gold_idle = gold is not None and (
        gold >= 300 or (gpt is not None and gpt > 0 and gold > 8 * gpt)
    )
    if gold_idle and gold is not None:
        extra = f", more than 8 turns of +{gpt}/turn" if gpt is not None and gpt > 0 and gold > 8 * gpt else ""
        bits.append(f"{gold} gold unspent{extra}")
    gov = governance(snapshot)
    religion = gov.get("religion") if isinstance(gov.get("religion"), dict) else {}
    faith = _as_int(religion.get("faith"))
    faith_rate = _as_int(religion.get("faith_per_turn"))
    cost = _as_int(religion.get("pantheon_cost")) or 25
    faith_idle = faith is not None and faith > 0 and (
        faith >= cost
        or faith >= 50
        or (faith_rate is not None and faith_rate > 0 and faith > 8 * faith_rate)
    )
    if faith_idle and faith is not None:
        if religion.get("can_found_pantheon"):
            bits.append(f"{faith} faith, enough for a pantheon ({cost})")
        else:
            bits.append(f"{faith} faith unspent")
    envoys = _as_int(diplomacy(snapshot).get("envoys_to_give"))
    if envoys is None:
        top = snapshot.get("diplomacy") if isinstance(snapshot.get("diplomacy"), dict) else {}
        envoys = _as_int(top.get("envoys_to_give"))
    if envoys is not None and envoys > 0:
        bits.append(f"{envoys} envoys unspent (the game's own AI sends them; do not order envoy)")
    if gold_idle or faith_idle:
        buys = _best_purchase_labels(snapshot)
        if buys:
            bits.append("Buy " + "; ".join(buys))
    if not bits:
        return None
    policies = gov.get("policies") if isinstance(gov.get("policies"), dict) else {}
    empty = _as_int(policies.get("empty_slots"))
    if empty and policies.get("change_allowed"):
        noun = "slot" if empty == 1 else "slots"
        bits.append(f"{empty} empty policy {noun}")
    governors = gov.get("governors") if isinstance(gov.get("governors"), dict) else {}
    routes = gov.get("routes") if isinstance(gov.get("routes"), dict) else {}
    if governors.get("can_appoint") and routes.get("governors", True) is not False:
        bits.append("a governor title is unassigned")
    return "IDLE: " + ". ".join(bits) + "."


def civ6_occupied_tile_attention(snapshot: dict[str, Any]) -> str | None:
    """Tiles one of our units already holds — MoveTo there fails occupied."""
    from sidecar.civ6_apply_results import _own_occupied_plots

    held = _own_occupied_plots(snapshot)
    if not held:
        return None
    bits = [f"({x},{y})" for x, y in sorted(held)[:12]]
    extra = "" if len(held) <= 12 else f" and {len(held) - 12} more"
    return (
        "OCCUPIED: your units already stand on " + ", ".join(bits) + extra
        + ". Do not MoveTo those tiles (builders and rams included)."
    )


def civ6_explore_quiet_attention(snapshot: dict[str, Any]) -> str | None:
    quiet = explore_quiet_units(snapshot)
    if not quiet:
        return None
    noun = "unit" if len(quiet) == 1 else "units"
    return (
        f"EXPLORE: {len(quiet)} {noun} revealed nothing for 2 turns. "
        "Automate(explore) is hidden for them. MoveTo a frontier tile instead."
    )


def collect_civ6_attention_items(snapshot: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for fn in (
        civ6_exploration_attention,
        civ6_naval_explore_attention,
        civ6_lethargy_attention,
        civ6_low_hp_retreat_attention,
        civ6_focus_fire_attention,
        civ6_expansion_attention,
        civ6_military_cap_attention,
        civ6_explore_quiet_attention,
        civ6_occupied_tile_attention,
        civ6_idle_resources_attention,
    ):
        note = fn(snapshot)
        if note:
            items.append(note)
    items.extend(civ6_loyalty_attention(snapshot))
    items.extend(civ6_economy_attention(snapshot))
    return items


def append_attack_options_to_unit_line(options: list[str], attack_tokens: list[str]) -> list[str]:
    """Append legal attack tokens onto an existing options list (no `| none`, no duplicate rows)."""
    out = list(options)
    for token in attack_tokens:
        if token and token not in out and token != "none":
            out.append(token)
    return out


def civ6_attack_option_tokens_for_unit(unit_id: str, snapshot: dict[str, Any]) -> list[str]:
    """Build attackTo/(x,y)[+preview] tokens from legal attack_target commands for one unit."""
    from sidecar import civ6_combat_wire as combat_wire

    tokens: list[str] = []
    previews = snapshot.get("strategic_summary", {})
    preview_rows = []
    if isinstance(previews, dict):
        raw = previews.get("combat_previews")
        if isinstance(raw, list):
            preview_rows = [row for row in raw if isinstance(row, dict)]
    for command in snapshot.get("legal_commands", []) or []:
        if not isinstance(command, dict) or command.get("kind") != "attack_target":
            continue
        fixed = command.get("fixed_arguments") or {}
        if not isinstance(fixed, dict) or fixed.get("unit_id") != unit_id:
            continue
        x, y = fixed.get("target_x"), fixed.get("target_y")
        if x is None or y is None:
            continue
        try:
            xi, yi = int(x), int(y)
        except (TypeError, ValueError):
            continue
        label = f"attackTo/({xi},{yi})"
        suffix = combat_wire.forecast_suffix_for(snapshot, xi, yi, unit_id=unit_id)
        if suffix:
            label = f"{label}{suffix}"
        else:
            for row in preview_rows:
                if row.get("attacker_unit_id") != unit_id:
                    continue
                if int(row.get("target_x", -1)) != xi or int(row.get("target_y", -1)) != yi:
                    continue
                dmg_e = row.get("damage_to_enemy")
                dmg_s = row.get("damage_to_self")
                pred = row.get("prediction")
                bits = []
                if pred:
                    bits.append(str(pred))
                if isinstance(dmg_e, int) and isinstance(dmg_s, int):
                    bits.append(f"~{dmg_e}toThem/~{dmg_s}toUs")
                if bits:
                    label = f"{label}[{','.join(bits)}]"
                break
        if label not in tokens:
            tokens.append(label)
    return tokens


def settler_present(snapshot: dict[str, Any]) -> bool:
    for unit in snapshot.get("your_units", []) or []:
        if not isinstance(unit, dict):
            continue
        type_id = str(unit.get("unit_type_id") or "")
        if "SETTLER" in type_id:
            return True
    return False


def _plot_fresh_coast(snapshot: dict[str, Any], plot_id: str) -> tuple[bool | None, bool | None]:
    known = snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else {}
    plots = known.get("plots") if isinstance(known, dict) else None
    if not isinstance(plots, list):
        return None, None
    for plot in plots:
        if not isinstance(plot, dict) or str(plot.get("plot_id") or "") != plot_id:
            continue
        fresh = plot.get("fresh_water")
        coast = plot.get("is_coastal")
        if coast is None:
            coast = plot.get("coastal")
        if coast is None and plot.get("water") is False:
            coast = None
        return (bool(fresh) if isinstance(fresh, bool) else None,
                bool(coast) if isinstance(coast, bool) else None)
    return None, None


def _hex_dist(ax: int, ay: int, bx: int, by: int) -> int:
    """Odd-r offset hex distance (no X wrap)."""
    def cube(x: int, y: int) -> tuple[int, int, int]:
        q = x - (y - (y & 1)) // 2
        return q, y, -q - y
    a, b = cube(ax, ay), cube(bx, by)
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def builder_improve_sites(snapshot: dict[str, Any], x: int, y: int, cap: int = 6) -> list[dict[str, Any]]:
    """Own, unimproved, non-city land tiles (resources first, then nearest) a builder can work."""
    me = str((snapshot.get("decision") or {}).get("player_id") or "")
    known = snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else {}
    rows = []
    for p in known.get("plots") or []:
        if not isinstance(p, dict) or p.get("water") or p.get("peak") or p.get("city_id") or p.get("improvement_id"):
            continue
        if not me or p.get("revealed_owner_id") != me:
            continue
        try:
            px, py = int(p["x"]), int(p["y"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({"x": px, "y": py, "resource": p.get("resource_id"), "dist": _hex_dist(x, y, px, py)})
    rows.sort(key=lambda r: (r["resource"] is None, r["dist"]))
    return rows[:cap]


def _unit_xy(unit: dict[str, Any]) -> tuple[int, int] | None:
    parts = str(unit.get("plot_id") or "").split("_")
    if len(parts) < 3:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _improve_offer_tokens(unit: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    """Improve(x,y,IMPROVEMENT_X) tokens this builder was actually offered. Coordinates are the command."""
    from sidecar.civ6_command_wire import unit_command_token

    uid = str(unit.get("unit_id") or "")
    tokens: list[str] = []
    for command in snapshot.get("legal_commands") or []:
        if not isinstance(command, dict) or command.get("kind") != "move_unit":
            continue
        fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
        if str(fixed.get("unit_id") or "") != uid:
            continue
        token = unit_command_token(command)
        if not token or not token.startswith("Improve("):
            continue
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def builder_fact_lines(prefix: str, unit: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    """Improve commands for this builder. Plot dumps stay off the prompt when the map image shows them."""
    from sidecar import pipeline_v2 as pipeline

    offers = _improve_offer_tokens(unit, snapshot)
    if offers:
        more = f" and {len(offers) - 1} more" if len(offers) > 1 else ""
        return [pipeline._wire_line(
            f"{prefix}.improve",
            f"{len(offers)} owned unimproved tiles near this builder; nearest {offers[0]}{more}. "
            "An invalid Improve tile is replaced by the nearest owned site.",
        )]
    if pipeline.map_image_attach_turn(snapshot):
        return [pipeline._wire_line(
            f"{prefix}.improve",
            "no Improve command this turn; the map marks improved owned tiles lower-left, so a blank owned tile is unimproved",
        )]
    xy = _unit_xy(unit)
    if xy is None:
        return []
    sites = unit.get("improve_sites")
    if not isinstance(sites, list):
        sites = builder_improve_sites(snapshot, *xy)
    if not sites:
        return [pipeline._wire_line(f"{prefix}.improve.sites", "none inside your borders; move toward a city's tiles")]
    nearest = sites[0]
    res = str(nearest["resource"] or "").replace("RESOURCE_", "").title()
    where = f"({nearest['x']},{nearest['y']})" + (f" {res}" if res else "")
    return [pipeline._wire_line(
        f"{prefix}.improve.sites",
        f"{len(sites)} owned unimproved tiles near this builder; nearest {where}. "
        "Order Improve(x,y,IMPROVEMENT_X) for that tile. An invalid tile is replaced by the nearest owned site.",
    )]


def settler_fact_lines(prefix: str, unit: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    """Unranked settle facts from WP-B `unit.settle` when present; otherwise plot flags."""
    from sidecar import pipeline_v2 as pipeline

    lines: list[str] = []
    settle = unit.get("settle") if isinstance(unit.get("settle"), dict) else {}
    plot_id = str(unit.get("plot_id") or "")
    here_ok = settle.get("here_ok") if settle else None
    here_reason = settle.get("here_reason") if settle else None
    coast = settle.get("coast") if settle else None
    if coast is None:
        coast = settle.get("is_coastal") if settle else None
    fresh = settle.get("fresh_water") if settle else None
    if coast is None or fresh is None:
        plot_fresh, plot_coast = _plot_fresh_coast(snapshot, plot_id)
        if fresh is None:
            fresh = plot_fresh
        if coast is None:
            coast = plot_coast
    bits: list[str] = []
    if here_ok is True:
        bits.append("FoundCity legal here")
    elif here_ok is False:
        bits.append("FoundCity illegal here" + (f" ({here_reason})" if here_reason else ""))
    elif here_reason:
        bits.append(str(here_reason))
    if fresh is True:
        bits.append("fresh water")
    elif fresh is False:
        bits.append("no fresh water")
    if coast is True:
        bits.append("coast")
    elif coast is False:
        bits.append("inland")
    if bits:
        lines.append(pipeline._wire_line(f"{prefix}.settle.here", ", ".join(bits)))
    sites = settle.get("sites") if settle else None
    if isinstance(sites, list) or settle.get("no_reachable_site"):
        from sidecar import civ6_command_wire as command_wire

        labeled = {
            (row["x"], row["y"]): row["label"]
            for row in command_wire.labeled_settle_sites(snapshot)
        }
        labels: list[str] = []
        for site in sites or []:
            if not isinstance(site, dict):
                continue
            try:
                x, y = int(site["x"]), int(site["y"])
            except (KeyError, TypeError, ValueError):
                continue
            dist = site.get("dist")
            tag = labeled.get((x, y), "")
            bits = [f"{tag} ({x},{y})".strip() if tag else f"({x},{y})"]
            if site.get("coastal") or site.get("coast"):
                bits.append("coastal")
            if site.get("fresh_water"):
                bits.append("fresh water")
            if dist is not None:
                bits.append(f"dist {dist}")
            labels.append(", ".join(bits) if len(bits) > 1 else bits[0])
        if labels:
            lines.append(pipeline._wire_line(f"{prefix}.settle.nearby", "; ".join(labels)))
        else:
            embark = settle.get("embark_site") if isinstance(settle.get("embark_site"), dict) else None
            if embark is not None:
                try:
                    ex, ey = int(embark["x"]), int(embark["y"])
                except (KeyError, TypeError, ValueError):
                    embark = None
            if embark is not None:
                dist = embark.get("dist")
                where = f"({ex},{ey})" + (f", dist {dist}" if dist is not None else "")
                if embark.get("can_embark") is False:
                    how = "this settler cannot embark yet (Shipbuilding for coast, Cartography for ocean)"
                else:
                    how = "embarking can reach it; FoundCity stays illegal until the settler is on that tile"
                lines.append(pipeline._wire_line(
                    f"{prefix}.settle.nearby",
                    f"none on foot; nearest legal site on another landmass is {where}; {how}",
                ))
                return lines
            from sidecar.civ6_command_wire import site_obeys_founding_rules
            from sidecar.civ6_wire import _odd_r_distance

            origin = _unit_xy(unit)
            known = snapshot.get("known_map") if isinstance(snapshot.get("known_map"), dict) else {}
            game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
            width = game.get("map_width") if isinstance(game.get("map_width"), int) else None
            wrap = game.get("wrap_x") is not False
            far: list[tuple[int, int, int]] = []
            if origin is not None:
                for plot in known.get("plots") or []:
                    if not isinstance(plot, dict):
                        continue
                    try:
                        x, y = int(plot["x"]), int(plot["y"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not site_obeys_founding_rules(snapshot, x, y):
                        continue
                    far.append((_odd_r_distance(origin, (x, y), width, wrap), x, y))
            far.sort()
            nearest = "; ".join(f"({x},{y}) path {dist}" for dist, x, y in far[:6])
            lines.append(pipeline._wire_line(
                f"{prefix}.settle.nearby",
                f"none reachable from here; nearest legal sites: {nearest}" if nearest else "none reachable from here",
            ))
    return lines


def capital_founding_coaching(snapshot: dict[str, Any]) -> str | None:
    if not settler_present(snapshot):
        return None
    cities = snapshot.get("your_cities") or []
    has_city = any(isinstance(c, dict) for c in cities)
    if has_city:
        return None
    return CIV6_CAPITAL_T1_COACHING
