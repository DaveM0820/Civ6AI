"""Civ VI combat awareness for the flat-wire prompt (civ6.combat from Civ6Ai_Snapshot.lua).

The Lua side asks the engine (CombatManager.SimulateAttackVersus / SimulateAttackInto,
the same calls the unit panel's hover preview uses) for every number shown here;
this module only formats them. Ported in spirit from the Civ5 mod's WAR section
(war.strike.available, in-range threats, focus fire, isolated units).
"""
from __future__ import annotations

from typing import Any

from sidecar import pipeline_v2 as pipeline

PREDICTION_LABELS = {
    "DECISIVE_VICTORY": "Decisive Victory",
    "MAJOR_VICTORY": "Major Victory",
    "MINOR_VICTORY": "Minor Victory",
    "STALEMATE": "Stalemate",
    "MINOR_DEFEAT": "Minor Defeat",
    "MAJOR_DEFEAT": "Major Defeat",
    "DECISIVE_DEFEAT": "Decisive Defeat",
    "INEFFECTIVE": "Ineffective",
    "MINOR_CITY_DAMAGE": "Minor City Damage",
    "MAJOR_CITY_DAMAGE": "Major City Damage",
    "TOTAL_CITY_DAMAGE": "Total City Damage",
    "MINOR_WALL_DAMAGE": "Minor Wall Damage",
    "MAJOR_WALL_DAMAGE": "Major Wall Damage",
    "TOTAL_WALL_DAMAGE": "Total Wall Damage",
}
BAD_PREDICTIONS = {"MAJOR_DEFEAT", "DECISIVE_DEFEAT", "INEFFECTIVE"}
MAX_STRIKE_LINES = 12
MAX_THREAT_LINES = 8
ISOLATED_FRIEND_TILES = 2
ISOLATED_ENEMY_TILES = 4
LOW_HP_PCT = 30

WAR_TACTICS_ADVICE = [
    "- War tactics: soften a target with ranged attacks first (no return damage), then finish it with melee.",
    "- Do not take attacks previewed as Major Defeat or Decisive Defeat; a Stalemate only trades HP.",
    "- Focus fire: kill one enemy per turn with several units instead of wounding many.",
    "- Mass 3+ units (with ranged or siege support) before assaulting a city; walled cities shoot back.",
    "- Pull units under ~30% HP back to heal (in your territory or fortified); a dead unit costs far more.",
    "- Defend on hills, forest, or behind rivers (strength bonus), and keep civilians stacked with or behind military.",
]


def _combat(context: dict[str, Any]) -> dict[str, Any]:
    civ6 = context.get("civ6")
    block = civ6.get("combat") if isinstance(civ6, dict) else None
    return block if isinstance(block, dict) else {}


def _rows(block: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = block.get(key)
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _wire_ids(context: dict[str, Any]) -> dict[str, str]:
    units = [u for u in context.get("your_units", []) or [] if isinstance(u, dict)]
    return pipeline._build_unit_wire_id_map(units)


def _players(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(r.get("player_id")): r
        for r in context.get("known_players", []) or []
        if isinstance(r, dict) and r.get("player_id")
    }


def _owner_label(context: dict[str, Any], owner: Any) -> str:
    from sidecar import civ6_wire

    owner_id = str(owner or "")
    rival = _players(context).get(owner_id)
    kind = civ6_wire.civ6_player_kind(rival) if rival else "major"
    if kind == "barbarians":
        return "Barbarian"
    if kind == "free cities":
        return "Free Cities"
    return civ6_wire._player_display(context, owner_id)


def _tiles(value: Any) -> str:
    n = _int(value)
    if n is None:
        return "? tiles"
    return f"{n} tile" if n == 1 else f"{n} tiles"


def prediction_label(value: Any) -> str:
    text = str(value or "").strip().upper()
    return PREDICTION_LABELS.get(text, text.replace("_", " ").title() if text else "")


def _hp_text(hp: Any, max_hp: Any) -> str:
    hp_i, max_i = _int(hp), _int(max_hp)
    if hp_i is None:
        return ""
    if max_i and max_i != 100:
        return f"{hp_i}/{max_i}hp"
    return f"{hp_i}hp"


def _own_stats(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r.get("unit_id")): r for r in _rows(_combat(context), "units") if r.get("unit_id")}


def _is_military(unit: dict[str, Any], stats: dict[str, Any] | None) -> bool:
    if stats is not None and isinstance(stats.get("military"), bool):
        return stats["military"]
    from sidecar import civ6_wire

    return not civ6_wire._is_civilian(unit)


def unit_strength_text(unit: dict[str, Any], context: dict[str, Any]) -> str | None:
    """'20 str, 100hp' / '5 str, ranged 15 range 1, 100hp' for one of your units."""
    stats = _own_stats(context).get(str(unit.get("unit_id")))
    strength = _int(stats.get("strength")) if stats else None
    if strength is None and isinstance(unit.get("strength"), dict):
        strength = _int(unit["strength"].get("current"))
    ranged = _int(stats.get("ranged_strength")) if stats else None
    rng = _int(stats.get("range")) if stats else None
    hp, max_hp = (stats.get("hp"), stats.get("max_hp")) if stats else (None, None)
    if hp is None and isinstance(unit.get("health"), dict):
        hp, max_hp = unit["health"].get("current"), unit["health"].get("maximum")
    parts: list[str] = []
    if strength:
        parts.append(f"{strength} str")
    if ranged and rng:
        parts.append(f"ranged {ranged} range {rng}")
    if not parts and not _is_military(unit, stats):
        parts.append("civilian (no combat)")
    hp_text = _hp_text(hp, max_hp)
    if hp_text:
        parts.append(hp_text)
    return ", ".join(parts) if parts else None


def _target_text(context: dict[str, Any], row: dict[str, Any]) -> str:
    owner = _owner_label(context, row.get("target_owner"))
    name = str(row.get("target_name") or "unit")
    if row.get("target_kind") == "city":
        label = f"{owner} city {name}"
    else:
        label = f"{owner} {name}"
    bits: list[str] = []
    if _int(row.get("defender_strength")) is not None:
        bits.append(f"{_int(row['defender_strength'])} str")
    hp_text = _hp_text(row.get("defender_hp"), row.get("defender_max_hp"))
    if hp_text:
        bits.append(hp_text)
    if _int(row.get("defender_wall_max_hp")):
        bits.append(f"walls {_int(row.get('defender_wall_hp')) or 0}/{_int(row['defender_wall_max_hp'])}")
    return f"{label} ({', '.join(bits)})" if bits else label


def outcome_text(row: dict[str, Any]) -> str:
    """'Major Defeat ~12dmg to it vs ~35dmg to you' from a preview row."""
    label = prediction_label(row.get("prediction"))
    to_it = _int(row.get("damage_to_defender"))
    to_you = _int(row.get("damage_to_attacker"))
    parts = [label] if label else []
    if to_it is not None:
        if row.get("ranged"):
            parts.append(f"~{to_it}dmg to it, no return damage")
        else:
            parts.append(f"~{to_it}dmg to it vs ~{to_you or 0}dmg to you")
    walls = _int(row.get("damage_to_walls"))
    if walls:
        parts.append(f"(~{walls} to walls)")
    if not parts:
        return "no engine preview"
    return " ".join(parts)


def _previews(context: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(_combat(context), "previews")


def unit_row_lines(prefix: str, unit: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Extra EMPIRE unit-row lines: strength/HP, and attack odds for targets in reach now."""
    lines: list[str] = []
    text = unit_strength_text(unit, context)
    if text:
        lines.append(pipeline._wire_line(f"{prefix}.combat", text))
    odds: list[str] = []
    for row in _previews(context):
        if row.get("unit_id") != unit.get("unit_id") or row.get("needs_move"):
            continue
        x, y = _int(row.get("target_x")), _int(row.get("target_y"))
        if x is None or y is None:
            continue
        odds.append(f"AttackTo({x},{y}) {outcome_text(row)}")
    if odds:
        lines.append(pipeline._wire_line(f"{prefix}.attackOdds", " | ".join(odds[:4])))
    return lines


def hostiles_visible(context: dict[str, Any]) -> bool:
    block = _combat(context)
    return bool(_rows(block, "hostiles") or _rows(block, "hostile_cities"))


def major_wars(context: dict[str, Any]) -> list[str]:
    from sidecar import civ6_wire

    names: list[str] = []
    for rival in _players(context).values():
        relation = rival.get("relation")
        if not (isinstance(relation, dict) and relation.get("at_war")):
            continue
        if civ6_wire.civ6_player_kind(rival) in ("barbarians", "free cities"):
            continue
        names.append(pipeline._rival_leader_name(rival))
    return names


def war_active(context: dict[str, Any]) -> bool:
    return hostiles_visible(context) or bool(major_wars(context))


def _strike_sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
    return (
        1 if row.get("needs_move") else 0,
        1 if str(row.get("prediction") or "").upper() in BAD_PREDICTIONS else 0,
        -(_int(row.get("damage_to_defender")) or 0),
    )


def strike_lines(context: dict[str, Any]) -> list[str]:
    wire_ids = _wire_ids(context)
    stats = _own_stats(context)
    lines: list[str] = []
    for row in sorted(_previews(context), key=_strike_sort_key)[:MAX_STRIKE_LINES]:
        unit_id = str(row.get("unit_id"))
        name = wire_ids.get(unit_id, unit_id)
        x, y = _int(row.get("target_x")), _int(row.get("target_y"))
        if x is None or y is None:
            continue
        own = f"you {_int(row.get('attacker_strength')) or 0} str"
        own_hp = _hp_text(row.get("attacker_hp"), row.get("attacker_max_hp"))
        if not own_hp and unit_id in stats:
            own_hp = _hp_text(stats[unit_id].get("hp"), stats[unit_id].get("max_hp"))
        if own_hp:
            own += f", {own_hp}"
        verb = "rangedAttack" if row.get("ranged") else "attackTo"
        detail = f"vs {_target_text(context, row)} [{own}]: {outcome_text(row)}"
        if row.get("needs_move"):
            dist = _int(row.get("distance"))
            key = "war.strike.afterMove"
            text = f"{name} -> ({x},{y}) {_tiles(dist)} away, move into reach first — {detail}"
        else:
            key = "war.strike.available"
            text = f"{name}.{verb}({x},{y}) {detail}"
        lines.append(pipeline._wire_line(key, text))
    return lines


def war_section_lines(context: dict[str, Any]) -> list[str]:
    """=== WAR === body (empty when nothing hostile is visible and no major war)."""
    if not war_active(context):
        return []
    lines: list[str] = []
    wars = major_wars(context)
    if wars:
        lines.append(pipeline._wire_line("war.rivals", ", ".join(wars)))
    block = _combat(context)
    hostiles = _rows(block, "hostiles")
    if hostiles:
        bits = []
        for h in hostiles[:10]:
            text = f"{_owner_label(context, h.get('owner_player_id'))} {h.get('name') or 'unit'} ({_int(h.get('x'))},{_int(h.get('y'))})"
            stat = [f"{_int(h.get('strength')) or 0} str"]
            if _int(h.get("ranged_strength")) and _int(h.get("range")):
                stat.append(f"ranged {_int(h['ranged_strength'])} range {_int(h['range'])}")
            hp_text = _hp_text(h.get("hp"), h.get("max_hp"))
            if hp_text:
                stat.append(hp_text)
            if _int(h.get("max_moves")):
                stat.append(f"{_int(h['max_moves'])} moves")
            bits.append(f"{text} {', '.join(stat)}")
        lines.append(pipeline._wire_line("war.enemies.visible", " | ".join(bits)))
    for c in _rows(block, "hostile_cities")[:6]:
        stat = []
        if _int(c.get("strength")):
            stat.append(f"{_int(c['strength'])} str")
        hp_text = _hp_text(c.get("hp"), c.get("max_hp"))
        if hp_text:
            stat.append(hp_text)
        stat.append(f"walls {_int(c.get('wall_hp')) or 0}/{_int(c['wall_max_hp'])}" if _int(c.get("wall_max_hp"))
                    else "no walls (cannot strike)")
        lines.append(pipeline._wire_line(
            f"war.city.{c.get('name') or 'city'}",
            f"{_owner_label(context, c.get('owner_player_id'))} ({_int(c.get('x'))},{_int(c.get('y'))}) {', '.join(stat)}"))
    strikes = strike_lines(context)
    if strikes:
        lines.append("# == Attack previews (engine combat simulation, same as the in-game hover preview) ==")
        lines.extend(strikes)
    elif hostiles:
        lines.append("# No enemy is within reach of your military this turn.")
    return lines


def _threat_lines(context: dict[str, Any]) -> list[str]:
    wire_ids = _wire_ids(context)
    own_units = {str(u.get("unit_id")): u for u in context.get("your_units", []) or [] if isinstance(u, dict)}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _rows(_combat(context), "threats"):
        if row.get("source_type") == "city" and row.get("can_strike") is False:
            continue
        grouped.setdefault(str(row.get("unit_id")), []).append(row)
    lines: list[str] = []
    for unit_id, rows in grouped.items():
        rows.sort(key=lambda r: (-(_int(r.get("damage_to_defender")) or 0), _int(r.get("distance")) or 99))
        unit = own_units.get(unit_id, {})
        name = wire_ids.get(unit_id, unit_id)
        own = unit_strength_text(unit, context) or ""
        pos = pipeline._plot_coords_text(unit.get("plot_id")) if unit.get("plot_id") else ""
        sources: list[str] = []
        civilian = any(r.get("civilian") for r in rows)
        for r in rows[:3]:
            who = f"{_owner_label(context, r.get('source_owner'))} {r.get('source_name') or 'unit'}"
            if r.get("source_type") == "city":
                who += " (city strike)"
            sx, sy = _int(r.get("source_x")), _int(r.get("source_y"))
            text = f"{who} ({_int(r.get('enemy_strength')) or 0} str) at ({sx},{sy}), {_tiles(r.get('distance'))}"
            to_you = _int(r.get("damage_to_defender"))
            if to_you is not None and not r.get("civilian"):
                att_s, def_s = _int(r.get("attacker_strength")), _int(r.get("defender_strength"))
                odds = f" ({att_s} vs your {def_s} defending)" if att_s is not None and def_s is not None else ""
                text += f" — if it attacks{odds}: ~{to_you}dmg to you"
                if not r.get("ranged"):
                    text += f", ~{_int(r.get('damage_to_attacker')) or 0} to it"
                own_hp = _int(r.get("own_hp"))
                if own_hp is not None and to_you >= own_hp:
                    text += " (KILLS you)"
            sources.append(text)
        advice = ("can be captured — move it away or stack it with a military unit" if civilian
                  else "pull back, fortify on defensive terrain, or stack support nearby")
        head = f"threat: {name}"
        if own:
            head += f" ({own})"
        if pos:
            head += f" at {pos}"
        lines.append(f"{head} is in reach of {' | '.join(sources)} — {advice}")
    return lines[:MAX_THREAT_LINES]


def _distance(context: dict[str, Any], a: tuple[int, int], b: tuple[int, int]) -> int:
    from sidecar import civ6_wire

    game = context.get("game", {}) if isinstance(context.get("game"), dict) else {}
    width = game.get("map_width") if isinstance(game.get("map_width"), int) else None
    civ6 = context.get("civ6")
    if width is None and isinstance(civ6, dict) and isinstance(civ6.get("map"), dict):
        width = _int(civ6["map"].get("width"))
    return civ6_wire._odd_r_distance(a, b, width, game.get("wrap_x") is not False)


def _isolated_lines(context: dict[str, Any]) -> list[str]:
    hostiles = [(h, (_int(h.get("x")), _int(h.get("y")))) for h in _rows(_combat(context), "hostiles")]
    hostiles = [(h, xy) for h, xy in hostiles if xy[0] is not None and xy[1] is not None]
    if not hostiles:
        return []
    stats = _own_stats(context)
    units = [u for u in context.get("your_units", []) or [] if isinstance(u, dict)]
    coords = {str(u.get("unit_id")): pipeline._parse_plot_coords(u.get("plot_id")) for u in units}
    wire_ids = _wire_ids(context)
    out: list[str] = []
    for unit in units:
        unit_id = str(unit.get("unit_id"))
        xy = coords.get(unit_id)
        if xy is None or not _is_military(unit, stats.get(unit_id)):
            continue
        friends = any(other != unit_id and oxy is not None and _distance(context, xy, oxy) <= ISOLATED_FRIEND_TILES
                      for other, oxy in coords.items())
        if friends:
            continue
        near = [(h, _distance(context, xy, hxy)) for h, hxy in hostiles]
        near = [(h, d) for h, d in near if d <= ISOLATED_ENEMY_TILES]
        if not near:
            continue
        h, d = min(near, key=lambda item: item[1])
        out.append(f"isolated: {wire_ids.get(unit_id, unit_id)} at ({xy[0]},{xy[1]}) has no friendly unit within "
                   f"{ISOLATED_FRIEND_TILES} tiles and {_owner_label(context, h.get('owner_player_id'))} "
                   f"{h.get('name') or 'unit'} is {_tiles(d)} away — group up or fall back")
    return out


def _focus_fire_line(context: dict[str, Any]) -> str | None:
    from sidecar import civ6_prompt_coaching as coaching

    if coaching.civ6_focus_fire_attention(context):
        return None  # legal-command version already covers it
    wire_ids = _wire_ids(context)
    targets: dict[tuple[int, int], list[str]] = {}
    names: dict[tuple[int, int], str] = {}
    for row in _previews(context):
        if row.get("needs_move") or str(row.get("prediction") or "").upper() == "INEFFECTIVE":
            continue
        x, y = _int(row.get("target_x")), _int(row.get("target_y"))
        if x is None or y is None:
            continue
        bucket = targets.setdefault((x, y), [])
        name = wire_ids.get(str(row.get("unit_id")), str(row.get("unit_id")))
        if name not in bucket:
            bucket.append(name)
        names[(x, y)] = str(row.get("target_name") or "target")
    bits = [f"{', '.join(units[:4])} can all hit {names[xy]} at ({xy[0]},{xy[1]})"
            for xy, units in sorted(targets.items(), key=lambda kv: -len(kv[1])) if len(units) >= 2]
    if not bits:
        return None
    return "focus fire: " + " | ".join(bits[:3]) + " — strike the same target, ranged first, melee to finish"


def _low_hp_threat_lines(context: dict[str, Any]) -> list[str]:
    """Low-HP units that are also threatened (the generic low-HP note lives in coaching)."""
    threatened = {str(r.get("unit_id")) for r in _rows(_combat(context), "threats")
                  if not (r.get("source_type") == "city" and r.get("can_strike") is False)}
    wire_ids = _wire_ids(context)
    out: list[str] = []
    for row in _rows(_combat(context), "units"):
        hp, max_hp = _int(row.get("hp")), _int(row.get("max_hp"))
        unit_id = str(row.get("unit_id"))
        if hp is None or not max_hp or not row.get("military") or unit_id not in threatened:
            continue
        if hp * 100 < LOW_HP_PCT * max_hp:
            out.append(f"retreat: {wire_ids.get(unit_id, unit_id)} is at {hp}/{max_hp}hp and in enemy reach — "
                       "pull back to heal unless the sacrifice is intentional")
    return out


def attention_items(context: dict[str, Any]) -> list[str]:
    if not war_active(context):
        return []
    items: list[str] = []
    items.extend(_threat_lines(context))
    items.extend(_low_hp_threat_lines(context))
    focus = _focus_fire_line(context)
    if focus:
        items.append(focus)
    items.extend(_isolated_lines(context))
    return items


def tactics_advice_lines(context: dict[str, Any]) -> list[str]:
    return list(WAR_TACTICS_ADVICE) if war_active(context) else []
