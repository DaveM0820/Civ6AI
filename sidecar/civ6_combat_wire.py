"""Civ VI combat awareness for the flat-wire prompt (civ6.combat from Civ6Ai_Snapshot.lua).

The Lua side asks the engine (CombatManager.SimulateAttackVersus / SimulateAttackInto,
the same calls the unit panel's hover preview uses) for every number shown here;
this module only formats them. Ported in spirit from the Civ5 mod's WAR section
(war.strike.available, in-range threats, focus fire, isolated units).
"""
from __future__ import annotations

import re
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
ISOLATED_FRIEND_TILES = 3
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
    if kind == "free cities" or (not rival and owner_id.endswith("_62")):
        return "Free Cities"
    if not rival and owner_id.endswith("_63"):
        return "Barbarian"
    return civ6_wire._player_display(context, owner_id)


def enemy_reach(hostile: dict[str, Any]) -> int:
    """Tiles this enemy can attack from, using its move range.

    Held AI-seat units often report max_moves 0. A melee unit still moves 2
    unless the snapshot already carried a positive budget.
    """
    moves = _int(hostile.get("max_moves")) or 0
    if moves <= 0:
        moves = 2
    ranged = _int(hostile.get("range")) or 0
    ranged_strength = _int(hostile.get("ranged_strength")) or 0
    if hostile.get("is_ranged") or (ranged > 0 and ranged_strength > 0):
        return ranged + max(0, moves - 1)
    return max(1, moves)


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
    if not _is_military(unit, stats):
        return None
    parts: list[str] = []
    if strength:
        parts.append(f"{strength} str")
    if ranged and rng:
        parts.append(f"ranged {ranged} range {rng}")
    hp_text = _hp_text(hp, max_hp)
    if hp_text and hp_text not in ("100hp", "100/100hp"):
        parts.append(hp_text)
    if _int(unit.get("experience")):
        parts.append(f"xp {_int(unit['experience'])} level {_int(unit.get('level')) or 1}")
    promos = unit.get("promotion_ids")
    if isinstance(promos, list) and promos:
        parts.append("promotions " + ", ".join(str(p).replace("PROMOTION_", "") for p in promos))
    return ", ".join(parts) if parts else None


def _city_on_tile(context: dict[str, Any], x: int | None, y: int | None) -> dict[str, Any] | None:
    if x is None or y is None:
        return None
    for city in _rows(_combat(context), "hostile_cities"):
        if _int(city.get("x")) == x and _int(city.get("y")) == y and city.get("name"):
            return city
    return None


def _target_text(context: dict[str, Any], row: dict[str, Any]) -> str:
    city = _city_on_tile(context, _int(row.get("target_x")), _int(row.get("target_y")))
    if city is not None:
        owner = _owner_label(context, city.get("owner_player_id") or row.get("target_owner"))
        name = str(city.get("name"))
        label = f"{owner} city {name}"
    else:
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


def attack_forecast_note(row: dict[str, Any] | None) -> str:
    """Short parenthetical forecast for an attack option, or '' when the engine said nothing.

    The war section still prints the full outcome_text. Tokens only need the damage.
    """
    if not isinstance(row, dict):
        return ""
    to_it = _int(row.get("damage_to_defender"))
    if to_it is None:
        return ""
    if row.get("ranged"):
        return f" (~{to_it}dmg)"
    to_you = _int(row.get("damage_to_attacker")) or 0
    return f" (~{to_it}dmg/~{to_you}dmg)"


def _preview_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    civ6 = snapshot.get("civ6") if isinstance(snapshot, dict) else None
    combat = civ6.get("combat") if isinstance(civ6, dict) else None
    raw = combat.get("previews") if isinstance(combat, dict) else None
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def forecast_suffix_for(
    snapshot: dict[str, Any],
    x: int,
    y: int,
    *,
    unit_id: str | None = None,
    city_id: str | None = None,
) -> str:
    """`` (Major Victory ~12dmg ...)`` for the preview matching this attack, else ''."""
    for row in _preview_rows(snapshot):
        if _int(row.get("target_x")) != x or _int(row.get("target_y")) != y:
            continue
        if unit_id is not None:
            if row.get("unit_id") != unit_id or row.get("city_id"):
                continue
        elif city_id is not None:
            if row.get("city_id") != city_id:
                continue
        else:
            continue
        return attack_forecast_note(row)
    return ""


def with_attack_forecast(
    token: str,
    snapshot: dict[str, Any],
    *,
    unit_id: str | None = None,
    city_id: str | None = None,
) -> str:
    """Append the engine forecast to ``AttackTo(x,y)`` or ``(x,y)`` when a preview exists."""
    if not token or not isinstance(snapshot, dict):
        return token
    match = re.search(r"(-?\d+)\s*,\s*(-?\d+)", token)
    if match is None:
        return token
    note = forecast_suffix_for(
        snapshot, int(match.group(1)), int(match.group(2)), unit_id=unit_id, city_id=city_id,
    )
    if note and ") (" not in token:
        return token + note
    return token


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


def _is_civilian_capture(row: dict[str, Any]) -> bool:
    return (not row.get("ranged") and row.get("target_kind") != "city"
            and not _int(row.get("defender_strength")))


def _previews(context: dict[str, Any]) -> list[dict[str, Any]]:
    # A ranged shot at a 0-strength civilian is wasted; a melee unit captures it instead.
    return [r for r in _rows(_combat(context), "previews")
            if not (r.get("ranged") and r.get("target_kind") != "city" and not _int(r.get("defender_strength")))
            and not _is_civilian_capture(r)]


def unit_row_lines(prefix: str, unit: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Extra EMPIRE unit-row lines: strength and HP. Attack forecasts stay on AttackTo tokens."""
    lines: list[str] = []
    text = unit_strength_text(unit, context)
    if text:
        lines.append(pipeline._wire_line(f"{prefix}.combat", text))
    # AttackTo tokens on the unit row already carry the forecast. A second
    # attackOdds line repeated that text on every unit and inflated the prompt.
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


def capture_lines(context: dict[str, Any]) -> list[str]:
    """Melee captures: 0-strength civilians, and enemy cities already at 0 HP."""
    wire_ids = _wire_ids(context)
    lines: list[str] = []
    for row in _rows(_combat(context), "previews"):
        if not _is_civilian_capture(row):
            continue
        x, y = _int(row.get("target_x")), _int(row.get("target_y"))
        if x is None or y is None:
            continue
        name = wire_ids.get(str(row.get("unit_id")), str(row.get("unit_id") or "unit"))
        who = _target_text(context, row)
        extra = " after moving into reach" if row.get("needs_move") else ""
        lines.append(pipeline._wire_line(
            "war.capture",
            f"{name} can capture {who} at ({x},{y}){extra}",
        ))
    for city in _rows(_combat(context), "hostile_cities"):
        hp, max_hp = _int(city.get("hp")), _int(city.get("max_hp"))
        if hp != 0 or not max_hp:
            continue
        x, y = _int(city.get("x")), _int(city.get("y"))
        if x is None or y is None:
            continue
        name = str(city.get("name") or "city")
        lines.append(pipeline._wire_line(
            "war.capture",
            f"{name}: capture with a melee unit adjacent at ({x},{y})",
        ))
    return lines


_SIEGE_TAGS = ("CATAPULT", "TREBUCHET", "BOMBARD", "SIEGE")


def _army_has_siege(context: dict[str, Any]) -> bool:
    for unit in context.get("your_units") or []:
        if not isinstance(unit, dict):
            continue
        type_id = str(unit.get("unit_type_id") or "").upper()
        if any(tag in type_id for tag in _SIEGE_TAGS):
            return True
    return False


def siege_guidance_line(context: dict[str, Any]) -> str | None:
    """Walled enemy cities and no siege unit: say so, and that an all-in economy blocks the army."""
    walled = [c for c in _rows(_combat(context), "hostile_cities") if _int(c.get("wall_max_hp"))]
    if not walled or _army_has_siege(context):
        return None
    names = ", ".join(str(c.get("name") or "city") for c in walled[:4])
    verb = "needs" if len(walled) == 1 else "need"
    return pipeline._wire_line(
        "war.siege",
        f"{names} {verb} siege and this army has none. Set war:3 or build a Catapult. "
        "An all-in economic focus (fix_bankruptcy:3) blocks military production.",
    )


def _staging_tile(context: dict[str, Any], cx: int, cy: int) -> tuple[int, int]:
    """Nearest known land tile beside the city: lowest x, then y. Else the tile west of it."""
    known = context.get("known_map") if isinstance(context.get("known_map"), dict) else {}
    candidates: list[tuple[int, int]] = []
    for plot in known.get("plots") or []:
        if not isinstance(plot, dict) or plot.get("water") or plot.get("peak"):
            continue
        x, y = _int(plot.get("x")), _int(plot.get("y"))
        if x is None or y is None:
            continue
        if _distance(context, (x, y), (cx, cy)) == 1:
            candidates.append((x, y))
    if candidates:
        return min(candidates)
    return (cx - 1, cy)


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
    stats = _own_stats(context)
    idle = [_wire_ids(context).get(str(u.get("unit_id")), str(u.get("unit_id"))) for u in context.get("your_units", []) or []
            if isinstance(u, dict) and u.get("needs_orders") and not u.get("goal") and _is_military(u, stats.get(str(u.get("unit_id"))))]
    if wars and idle:
        lines.append(pipeline._wire_line("war.idle", f"{len(idle)} combat units have no orders: {', '.join(idle)}"))
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
    mine = [(u, pipeline._parse_plot_coords(u.get("plot_id"))) for u in context.get("your_units", []) or []
            if isinstance(u, dict) and _is_military(u, stats.get(str(u.get("unit_id"))))]
    for c in _rows(block, "hostile_cities")[:6]:
        stat = []
        strength = _int(c.get("strength")) or next((_int(r.get("defender_strength")) for r in _previews(context)
                                                    if r.get("target_kind") == "city" and r.get("target_name") == c.get("name")), None)
        if strength:
            stat.append(f"{strength} str")
        hp_text = _hp_text(c.get("hp"), c.get("max_hp"))
        if hp_text:
            stat.append(hp_text)
        pop = next((_int(k.get("population")) for k in context.get("known_other_cities", []) or []
                    if isinstance(k, dict) and k.get("name") == c.get("name")), None) or 1
        stat.append(f"walls {_int(c.get('wall_hp')) or 0}/{_int(c['wall_max_hp'])}, needs siege or a ram"
                    if _int(c.get("wall_max_hp")) else
                    f"no walls, melee can assault (~{max(2, pop + (_int(c.get('strength')) or 0) // 8 + 1)} melee to capture)")
        cxy = (_int(c.get("x")), _int(c.get("y")))
        near = [u for u, xy in mine if xy is not None and cxy[0] is not None and _distance(context, xy, cxy) <= 3]
        far = sum(1 for u in near if _int((stats.get(str(u.get("unit_id"))) or {}).get("ranged_strength")))
        stat.append(f"you have {len(near)} military within 3 ({far} siege/ranged)")
        stage = ""
        if cxy[0] is not None and cxy[1] is not None:
            sx, sy = _staging_tile(context, cxy[0], cxy[1])
            stage = f"; mass at ({sx},{sy}) and bring siege"
        capture = ""
        city_hp, city_max = _int(c.get("hp")), _int(c.get("max_hp"))
        if city_hp == 0 and city_max:
            capture = f"; capture with a melee unit adjacent at ({_int(c.get('x'))},{_int(c.get('y'))})"
        lines.append(pipeline._wire_line(
            f"war.city.{c.get('name') or 'city'}",
            f"{_owner_label(context, c.get('owner_player_id'))} ({_int(c.get('x'))},{_int(c.get('y'))}) {', '.join(stat)}{stage}{capture}"))
    lines.extend(city_threat_lines(context))
    siege = siege_guidance_line(context)
    if siege:
        lines.append(siege)
    lines.extend(capture_lines(context))
    strikes = strike_lines(context)
    if strikes:
        lines.append("# == Attack previews (engine combat simulation, same as the in-game hover preview) ==")
        lines.extend(strikes)
    elif hostiles or _rows(block, "threats"):
        if enemies_within_their_reach(context):
            lines.append("# Enemies are within their move range of your units or cities, but none of your units can strike this turn.")
        else:
            lines.append("# No enemy is within reach of your military this turn.")
    return lines


def _own_military_plots(context: dict[str, Any]) -> list[tuple[int, int]]:
    stats = _own_stats(context)
    plots: list[tuple[int, int]] = []
    for unit in context.get("your_units", []) or []:
        if not isinstance(unit, dict) or not _is_military(unit, stats.get(str(unit.get("unit_id")))):
            continue
        xy = pipeline._parse_plot_coords(unit.get("plot_id"))
        if xy is not None:
            plots.append(xy)
    return plots


def _city_plot(city: dict[str, Any]) -> tuple[int, int] | None:
    return pipeline._parse_plot_coords(city.get("plot_id")) if isinstance(city, dict) else None


def enemies_within_their_reach(context: dict[str, Any]) -> bool:
    """True when a visible enemy's own move/attack range covers one of our units or cities."""
    if _rows(_combat(context), "threats"):
        return True
    hostiles = [(h, (_int(h.get("x")), _int(h.get("y")))) for h in _rows(_combat(context), "hostiles")]
    targets = _own_military_plots(context)
    for city in context.get("your_cities", []) or []:
        xy = _city_plot(city) if isinstance(city, dict) else None
        if xy is not None:
            targets.append(xy)
    for hostile, hxy in hostiles:
        if hxy[0] is None or hxy[1] is None:
            continue
        reach = enemy_reach(hostile)
        if any(_distance(context, hxy, xy) <= reach for xy in targets):
            return True
    return False


def threatened_city_ids(context: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    hostiles = [(h, (_int(h.get("x")), _int(h.get("y")))) for h in _rows(_combat(context), "hostiles")]
    for city in context.get("your_cities", []) or []:
        if not isinstance(city, dict):
            continue
        xy = _city_plot(city)
        if xy is None:
            continue
        for hostile, hxy in hostiles:
            if hxy[0] is None:
                continue
            dist = _distance(context, xy, hxy)
            if 1 <= dist <= enemy_reach(hostile):
                ids.add(str(city.get("city_id")))
                break
    return ids


def city_threat_lines(context: dict[str, Any]) -> list[str]:
    """One line per city: garrison, walls, adjacent enemies, enemies inside their move range."""
    cities = [c for c in context.get("your_cities", []) or [] if isinstance(c, dict)]
    if not cities:
        return []
    wire_ids = _wire_ids(context)
    hostiles = [(h, (_int(h.get("x")), _int(h.get("y")))) for h in _rows(_combat(context), "hostiles")]
    ranked: list[tuple[int, str]] = []
    for city in cities:
        xy = _city_plot(city)
        adjacent: list[str] = []
        nearby: list[str] = []
        if xy is not None:
            for hostile, hxy in hostiles:
                if hxy[0] is None:
                    continue
                dist = _distance(context, xy, hxy)
                if dist < 1 or dist > enemy_reach(hostile):
                    continue
                who = (f"{_owner_label(context, hostile.get('owner_player_id'))} "
                       f"{hostile.get('name') or 'unit'} ({hxy[0]},{hxy[1]}) {_tiles(dist)}")
                if dist == 1:
                    adjacent.append(who)
                else:
                    nearby.append(who)
        garrison_ids = [str(u) for u in city.get("garrison_unit_ids") or [] if u]
        garrison = ", ".join(wire_ids.get(u, u) for u in garrison_ids) or "none"
        defense = city.get("defense") if isinstance(city.get("defense"), dict) else {}
        wall_max = _int(defense.get("wall_max_hp")) or 0
        if wall_max > 0:
            walls = f"{_int(defense.get('wall_hp')) or 0}/{wall_max}"
        else:
            buildings = [str(b) for b in city.get("buildings") or []]
            walls = "yes" if any("WALL" in b for b in buildings) else "no"
        name = city.get("name") or pipeline._city_prompt_name(city)
        text = (f"garrison={garrison}; walls={walls}; "
                f"adjacent={', '.join(adjacent) or 'none'}; nearby={', '.join(nearby) or 'none'}")
        ranked.append((0 if adjacent or nearby else 1, pipeline._wire_line(f"war.city.{name}.threat", text)))
    ranked.sort(key=lambda item: item[0])
    rendered = [line for _, line in ranked[:12]]
    if not rendered:
        return []
    threatened = any(rank == 0 for rank, _ in ranked[:12])
    header = ("# == Your cities (garrison, walls, enemies within their move range) ==" if threatened
              else "# == Your cities (garrison and walls; no enemy is within move range) ==")
    return [header] + rendered


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


def retain_runnable_attacks(snapshot: dict[str, Any]) -> None:
    """Drop attack offers the combat preview says the game cannot run.

    Only when civ6.combat.previews is a list. Snapshots with no combat block keep
    every offer, so unit tests that never simulated a fight stay unchanged.
    A usable preview is simulated (or the flag is absent), deals damage, and
    does not require a move first.
    """
    if not isinstance(snapshot, dict):
        return
    civ6 = snapshot.get("civ6")
    combat = civ6.get("combat") if isinstance(civ6, dict) else None
    previews = combat.get("previews") if isinstance(combat, dict) else None
    if not isinstance(previews, list):
        return
    from sidecar import civ6_legality as legality

    legality.apply_offer_filter(snapshot, "combat_runnable")


def runnable_attack_offers(snapshot: dict[str, Any], legal: list[Any]) -> list[Any]:
    """Offer filter: keep attack offers with a usable simulated preview."""
    previews = (((snapshot.get("civ6") or {}).get("combat") or {}).get("previews"))
    if not isinstance(previews, list):
        return legal
    good: set[tuple[str, str, int, int]] = set()
    for row in previews:
        if not isinstance(row, dict) or row.get("needs_move") or row.get("simulated") is False:
            continue
        damage = row.get("damage_to_defender")
        if not isinstance(damage, int) or isinstance(damage, bool) or damage <= 0:
            continue
        try:
            x, y = int(row["target_x"]), int(row["target_y"])
        except (KeyError, TypeError, ValueError):
            continue
        if row.get("city_id"):
            good.add(("city", str(row.get("city_id")), x, y))
        elif row.get("unit_id"):
            good.add(("unit", str(row.get("unit_id")), x, y))
    attack_kinds = {"attack_target", "range_attack", "melee_attack", "city_attack"}
    kept: list[Any] = []
    for command in legal:
        if not isinstance(command, dict) or command.get("kind") not in attack_kinds:
            kept.append(command)
            continue
        fixed = command.get("fixed_arguments") if isinstance(command.get("fixed_arguments"), dict) else {}
        try:
            x, y = int(fixed["target_x"]), int(fixed["target_y"])
        except (KeyError, TypeError, ValueError):
            continue
        if command.get("kind") == "city_attack":
            key = ("city", str(fixed.get("city_id") or ""), x, y)
        else:
            key = ("unit", str(fixed.get("unit_id") or ""), x, y)
        if key in good:
            kept.append(command)
    return kept


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
    at_war = bool(major_wars(context))
    stats = _own_stats(context)
    units = [u for u in context.get("your_units", []) or [] if isinstance(u, dict)
             and _is_military(u, stats.get(str(u.get("unit_id")))) and u.get("domain_id") != "DOMAIN_SEA"]
    coords = {str(u.get("unit_id")): pipeline._parse_plot_coords(u.get("plot_id")) for u in units}
    wire_ids = _wire_ids(context)
    out: list[str] = []
    for unit_id, xy in coords.items():
        if xy is None or any(other != unit_id and oxy is not None and _distance(context, xy, oxy) <= ISOLATED_FRIEND_TILES
                             for other, oxy in coords.items()):
            continue
        near = sorted(((h, _distance(context, xy, hxy)) for h, hxy in hostiles), key=lambda item: item[1])
        name = f"isolated: {wire_ids.get(unit_id, unit_id)} at ({xy[0]},{xy[1]}) has no friendly military within {ISOLATED_FRIEND_TILES} tiles"
        others = [oxy for other, oxy in coords.items() if other != unit_id and oxy is not None]
        if others:
            hub = max(others, key=lambda o: sum(1 for p in others if _distance(context, o, p) <= ISOLATED_FRIEND_TILES))
            count = sum(1 for p in others if _distance(context, hub, p) <= ISOLATED_FRIEND_TILES)
            name += f", nearest army: {count} units around ({hub[0]},{hub[1]})"
        if near and near[0][1] <= ISOLATED_ENEMY_TILES:
            h, d = near[0]
            out.append(f"{name} and {_owner_label(context, h.get('owner_player_id'))} {h.get('name') or 'unit'} is "
                       f"{_tiles(d)} away — group up or fall back")
        elif at_war:
            out.append(f"{name} — group it with your army")
    return out


def _undefended_city_lines(context: dict[str, Any]) -> list[str]:
    enemies = [(h, (_int(h.get("x")), _int(h.get("y")))) for h in _rows(_combat(context), "hostiles")
               if (_int(h.get("strength")) or 0) > 0]
    out: list[str] = []
    for city in context.get("your_cities", []) or []:
        xy = pipeline._parse_plot_coords(city.get("plot_id")) if isinstance(city, dict) else None
        if xy is None or city.get("garrison_unit_ids"):
            continue
        near = [(h, _distance(context, xy, hxy)) for h, hxy in enemies if hxy[0] is not None]
        near = [item for item in near if item[1] <= ISOLATED_ENEMY_TILES]
        if near:
            h, d = min(near, key=lambda item: item[1])
            build = (city.get("production") or {}).get("item_id") or "nothing"
            out.append(f"undefended: {city.get('name')} has no garrison, {h.get('name') or 'enemy'} is {_tiles(d)} away, "
                       f"building {build}. Walls and military units are listed first in that city's catalog.")
    return out


def _focus_fire_line(context: dict[str, Any]) -> str | None:
    from sidecar import civ6_prompt_coaching as coaching

    if coaching.civ6_focus_fire_attention(context):
        return None  # legal-command version already covers it
    wire_ids = _wire_ids(context)
    targets: dict[tuple[int, int], list[str]] = {}
    names: dict[tuple[int, int], str] = {}
    dmg: dict[tuple[int, int], int] = {}
    hp: dict[tuple[int, int], int] = {}
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
            dmg[(x, y)] = dmg.get((x, y), 0) + (_int(row.get("damage_to_defender")) or 0)
        names[(x, y)] = str(row.get("target_name") or "target")
        if _int(row.get("defender_hp")) is not None:
            hp[(x, y)] = _int(row.get("defender_hp"))
    bits = [f"{', '.join(units[:4])} can all hit {names[xy]} at ({xy[0]},{xy[1]})"
            + (f" (combined ~{dmg[xy]}dmg vs {hp[xy]}hp: lethal)" if xy in hp and dmg.get(xy, 0) >= hp[xy] else "")
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
    items.extend(_undefended_city_lines(context))
    for city in _rows(_combat(context), "hostile_cities"):
        hp, max_hp = _int(city.get("hp")), _int(city.get("max_hp"))
        x, y = _int(city.get("x")), _int(city.get("y"))
        if hp == 0 and max_hp and x is not None and y is not None:
            name = city.get("name") or "city"
            items.append(f"{name} is at 0 city HP: capture with a melee unit adjacent at ({x},{y})")
    types = {str(u.get("unit_type_id")) for u in context.get("your_units", []) or [] if isinstance(u, dict)}
    if major_wars(context) and "UNIT_GREAT_GENERAL" in types:
        items.append("great generals: keep each within 2 tiles of your attacking units (+5 str, +1 move)")
    if major_wars(context) and types & {"UNIT_MILITARY_ENGINEER", "UNIT_ROMAN_LEGION"}:
        items.append("forts: use BuildFort on a hill or choke near the front (+4 defence, units auto-fortify)")
    walled = any(_int(c.get("wall_max_hp")) for c in _rows(_combat(context), "hostile_cities"))
    if major_wars(context) and walled and not any(_int(s.get("ranged_strength")) for s in _own_stats(context).values()):
        items.append("siege: enemy cities here are walled and you have no ranged/siege unit; build a Bombard/Trebuchet or a Siege Tower/Battering Ram before assaulting")
    return items


def tactics_advice_lines(context: dict[str, Any]) -> list[str]:
    if not war_active(context):
        return []
    if enemies_within_their_reach(context) or strike_lines(context):
        return list(WAR_TACTICS_ADVICE)
    return ["- War tactics: no enemy is within move range of your army or cities, so do not mass units or plan a strike this turn."]
