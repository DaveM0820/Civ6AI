"""Civ VI economy / empire panel for the flat-wire prompt (Civ5 parity).

Reads ``civ6.economy`` (written by Civ6Ai_Snapshot._BuildEconomy from the same
engine APIs the base-game TopPanel / CitySupport / ProductionPanel /
NotificationPanel use) and the unit list, and renders:

* gold income / expenses / net / turns until bankrupt + plain-words effects
* per-city yields, growth, housing, amenities -> mood, build + turns left,
  buildings and districts (***highlight*** for an empty production queue)
* the seat's notification feed tagged with the turn each was first seen
* per-city production catalogs with unit / building stats (reference lines;
  the orderable option rows stay bare IDs so reply parsing is unchanged)
* unit counts by domain and role, with idle-turn streaks tracked across turns
  in a small per-seat session file (the game does not expose idle time).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from sidecar import pipeline_v2 as pipeline

TRACKING_FILE = "economy_tracking.json"
NOTIFICATION_LIMIT = 10
# Noise the prompt already covers (idle units have their own lines).
NOTIFICATION_SKIP_TYPES = frozenset({
    "NOTIFICATION_COMMAND_UNITS",
    "NOTIFICATION_USER_DEFINED_1",
    "NOTIFICATION_USER_DEFINED_2",
    "NOTIFICATION_USER_DEFINED_3",
    "NOTIFICATION_USER_DEFINED_4",
    "NOTIFICATION_USER_DEFINED_5",
    "NOTIFICATION_USER_DEFINED_6",
    "NOTIFICATION_USER_DEFINED_7",
    "NOTIFICATION_USER_DEFINED_8",
    "NOTIFICATION_USER_DEFINED_9",
})

# Civilopedia "Bankruptcy" (Gathering Storm concepts/gold_4), verified 2026-09.
BANKRUPTCY_RULE = (
    "when the treasury is at 0 and net gold per turn is negative you are bankrupt: every city loses 1 amenity "
    "per 10 gold below zero, and units are disbanded automatically (one at -10 gold, two at -20, and so on)"
)

_MARKUP_RE = re.compile(r"\[(?:ICON_[A-Za-z0-9_]+|COLOR_[A-Za-z0-9_]+|ENDCOLOR|COLOR:[^\]]*)\]")
_NEWLINE_RE = re.compile(r"\[NEWLINE\]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def economy_block(snapshot: dict[str, Any]) -> dict[str, Any]:
    civ6 = snapshot.get("civ6") if isinstance(snapshot, dict) else None
    block = civ6.get("economy") if isinstance(civ6, dict) else None
    return block if isinstance(block, dict) else {}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "?"
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    if signed and value > 0:
        return "+" + text
    return text


def _short(type_id: Any, prefix: str) -> str:
    text = str(type_id or "")
    return text[len(prefix):] if text.startswith(prefix) else text


def clean_game_text(text: Any, limit: int = 300) -> str:
    raw = _NEWLINE_RE.sub(" | ", str(text or ""))
    raw = _MARKUP_RE.sub("", raw)
    raw = re.sub(r"\[[A-Z_]+\]", "", raw)
    raw = re.sub(r"\s*\|\s*(\|\s*)+", " | ", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" |")
    return raw[:limit]


def _cities_by_id(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in economy_block(snapshot).get("cities") or []:
        if isinstance(row, dict) and isinstance(row.get("city_id"), str):
            out[row["city_id"]] = row
    return out


def _unit_domain(unit: dict[str, Any]) -> str:
    domain = str(unit.get("domain_id") or "")
    formation = str(unit.get("unit_class_id") or "")
    if "SEA" in domain or "NAVAL" in formation:
        return "sea"
    if "AIR" in domain or "AIR" in formation:
        return "air"
    return "land"


# ---------------------------------------------------------------------------
# session tracking (idle streaks, notification first-seen turn)
# ---------------------------------------------------------------------------
def _notification_key(note: dict[str, Any]) -> str:
    return f"{note.get('id')}:{note.get('type')}:{str(note.get('message') or '')[:60]}"


def update_tracking(snapshot: dict[str, Any], state_dir: Path | str | None) -> dict[str, Any]:
    """Update per-seat idle/notification tracking and attach it as civ6.economy.tracking.

    Idle streak: a unit that needs orders and is on the same tile it held when it was
    last seen on an earlier turn keeps its ``idle_since`` turn; moving (or being
    fortified/asleep, i.e. not needing orders) resets it.
    Re-running the same turn (retries) does not advance anything.
    """
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    try:
        turn = int(decision.get("turn", 0))
    except (TypeError, ValueError):
        turn = 0
    path = Path(state_dir) / TRACKING_FILE if state_dir else None
    state: dict[str, Any] = {}
    if path is not None and path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, ValueError):
            state = {}
    units_state = state.get("units") if isinstance(state.get("units"), dict) else {}
    notes_state = state.get("notifications") if isinstance(state.get("notifications"), dict) else {}

    new_units: dict[str, Any] = {}
    idle_turns: dict[str, int] = {}
    for unit in snapshot.get("your_units") or []:
        if not isinstance(unit, dict) or not isinstance(unit.get("unit_id"), str):
            continue
        unit_id = unit["unit_id"]
        plot = unit.get("plot_id")
        prev = units_state.get(unit_id) if isinstance(units_state.get(unit_id), dict) else None
        needs = unit.get("needs_orders") is True
        if prev is not None and int(prev.get("turn", -1)) == turn:
            # Same-turn rerun: keep what the first run of this turn decided.
            record = dict(prev)
        else:
            record = {"turn": turn, "plot": plot, "idle_since": None}
            if needs:
                same_tile = prev is not None and prev.get("plot") == plot
                prev_since = prev.get("idle_since") if prev is not None else None
                if same_tile and isinstance(prev_since, int):
                    record["idle_since"] = prev_since
                else:
                    record["idle_since"] = turn
        new_units[unit_id] = record
        if needs and isinstance(record.get("idle_since"), int):
            idle_turns[unit_id] = max(0, turn - int(record["idle_since"]))

    note_turns: dict[str, int] = {}
    new_notes: dict[str, int] = {}
    for note in economy_block(snapshot).get("notifications") or []:
        if not isinstance(note, dict):
            continue
        key = _notification_key(note)
        first = notes_state.get(key)
        first_turn = int(first) if isinstance(first, int) else turn
        new_notes[key] = first_turn
        note_turns[key] = first_turn

    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"turn": turn, "units": new_units, "notifications": new_notes},
                                       sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    civ6 = snapshot.setdefault("civ6", {})
    if isinstance(civ6, dict):
        economy = civ6.setdefault("economy", {})
        if isinstance(economy, dict):
            economy["tracking"] = {"turn": turn, "idle_turns": idle_turns, "notification_turns": note_turns}
    return {"idle_turns": idle_turns, "notification_turns": note_turns}


def _tracking(snapshot: dict[str, Any]) -> dict[str, Any]:
    tracking = economy_block(snapshot).get("tracking")
    return tracking if isinstance(tracking, dict) else {}


# ---------------------------------------------------------------------------
# EMPIRE section lines
# ---------------------------------------------------------------------------
def gold_lines(snapshot: dict[str, Any]) -> list[str]:
    gold = economy_block(snapshot).get("gold")
    if not isinstance(gold, dict) or not gold:
        return []
    lines: list[str] = []
    treasury = _num(gold.get("treasury"))
    gross = _num(gold.get("gross_income"))
    total = _num(gold.get("maintenance_total"))
    net = _num(gold.get("net"))
    if net is None and gross is not None and total is not None:
        net = gross - total
    parts: list[tuple[str, float | None]] = [
        ("units", _num(gold.get("maintenance_units"))),
        ("buildings", _num(gold.get("maintenance_buildings"))),
        ("districts", _num(gold.get("maintenance_districts"))),
        ("wmd", _num(gold.get("maintenance_wmd"))),
    ]
    bits = [f"treasury {_fmt(treasury)}", f"net {_fmt(net, signed=True)}/turn"]
    if gross:
        bits.append(f"income {_fmt(gross, signed=True)}")
    for name, value in parts:
        if value:
            bits.append(f"{name} {_fmt(-value)}")
    if total is not None:
        known = sum(v for _, v in parts if v)
        if total - known > 0.05:
            bits.append(f"other {_fmt(-(total - known))}")
    empire = snapshot.get("your_empire") if isinstance(snapshot.get("your_empire"), dict) else {}
    anarchy = empire.get("anarchy_turns") if isinstance(empire.get("anarchy_turns"), int) else 0
    gov = ((snapshot.get("civ6") or {}).get("governance") or {}).get("government") if isinstance(snapshot.get("civ6"), dict) else {}
    gov = gov if isinstance(gov, dict) else {}
    tip = clean_game_text(gold.get("income_tooltip")) or ""
    in_anarchy = anarchy > 0 or gov.get("in_anarchy") is True or "anarchy" in tip.lower()
    if in_anarchy:
        left = anarchy or gov.get("anarchy_turns_left")
        bits.append(f"anarchy, {left} turns left" if left else "anarchy, yields paused until it ends")
    line = "; ".join(bits)
    lines.append(f"***empire.gold = {line}***" if net is not None and net < 0 else pipeline._wire_line("empire.gold", line))
    if net is not None and net < 0:
        if treasury is not None and treasury > 0:
            turns = int(math.floor(treasury / -net))
            lines.append(f"***empire.effects.gold = negative gold, about {turns} turns until the treasury hits 0***")
        else:
            lines.append("***empire.effects.gold = bankrupt; raise income or delete units this turn***")
    lost = sum(int(_num(c.get("amenities_lost_bankruptcy")) or 0) for c in _cities_by_id(snapshot).values())
    if lost > 0:
        lines.append(f"***empire.gold.bankruptcy_amenity_loss = -{lost} amenities across cities***")
    return lines


def _mood_text(row: dict[str, Any]) -> str:
    mood = _short(row.get("happiness"), "HAPPINESS_")
    growth = _num(row.get("happiness_growth_pct"))
    yields = _num(row.get("happiness_yield_pct"))
    bits = []
    if growth is not None:
        bits.append(f"growth {_fmt(growth, signed=True)}%")
    if yields is not None:
        bits.append(f"non-food yields {_fmt(yields, signed=True)}%")
    return (mood or "?") + (f" ({', '.join(bits)})" if bits else "")


def amenity_housing_lines(snapshot: dict[str, Any]) -> list[str]:
    rows = list(_cities_by_id(snapshot).values())
    if not rows:
        return []
    lines: list[str] = []
    worst = []
    for row in rows:
        have, need = _num(row.get("amenities")), _num(row.get("amenities_needed"))
        if have is not None and need is not None and have - need < 0:
            worst.append(f"{row.get('name')} {_fmt(have - need, signed=True)} {_mood_text(row)}")
    if worst:
        lines.append(f"***empire.amenities.short = {'; '.join(worst)}***")
    capped = []
    for row in rows:
        mult = _num(row.get("housing_growth_mult"))
        if mult is not None and mult < 1:
            capped.append(f"{row.get('name')} pop {row.get('population')}/housing {_fmt(_num(row.get('housing')))} "
                          f"(growth x{int(round(mult * 100))}%)")
    if capped:
        lines.append(f"***empire.housing.limited = {'; '.join(capped)}***")
    return lines


def unit_count_lines(snapshot: dict[str, Any]) -> list[str]:
    units = [u for u in snapshot.get("your_units") or [] if isinstance(u, dict)]
    if not units or not economy_block(snapshot):
        return []
    from sidecar.civ6_wire import _is_civilian  # local import: civ6_wire imports this module

    counts = {"land": 0, "sea": 0, "air": 0}
    military = civilian = 0
    for unit in units:
        counts[_unit_domain(unit)] += 1
        if _is_civilian(unit):
            civilian += 1
        else:
            military += 1
    lines = [
        pipeline._wire_line("empire.units.land", counts["land"]),
        pipeline._wire_line("empire.units.sea", counts["sea"]),
    ]
    if counts["air"]:
        lines.append(pipeline._wire_line("empire.units.air", counts["air"]))
    lines.append(pipeline._wire_line("empire.units.civilian", civilian))
    lines.append(pipeline._wire_line("empire.units.combat", military))
    idle_turns = _tracking(snapshot).get("idle_turns")
    idle_turns = idle_turns if isinstance(idle_turns, dict) else {}
    wire_ids = pipeline._build_unit_wire_id_map(units)
    idle_bits = []
    for unit in units:
        if not unit.get("needs_orders"):
            continue
        uid = str(unit.get("unit_id"))
        label = wire_ids.get(uid, uid)
        n = idle_turns.get(uid)
        if isinstance(n, int) and n > 0:
            idle_bits.append(f"{label} ({n} turn{'s' if n != 1 else ''} idle on the same tile)")
        else:
            idle_bits.append(f"{label} (needs orders)")
    if idle_bits:
        long_idle = [b for b in idle_bits if "idle on the same tile" in b]
        text = ", ".join(idle_bits)
        lines.append(f"***empire.units.idle.detail = {text}***" if long_idle
                     else pipeline._wire_line("empire.units.idle.detail", text))
    return lines


def notification_lines(snapshot: dict[str, Any]) -> list[str]:
    notes = [n for n in economy_block(snapshot).get("notifications") or [] if isinstance(n, dict)]
    if not notes:
        return []
    turns = _tracking(snapshot).get("notification_turns")
    turns = turns if isinstance(turns, dict) else {}
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    current = int(decision.get("turn", 0) or 0)
    kept: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for note in notes:
        if str(note.get("type")) in NOTIFICATION_SKIP_TYPES:
            continue
        message = clean_game_text(note.get("message"), 120)
        summary = clean_game_text(note.get("summary"), 200)
        if summary and message and summary.lower().startswith(message.lower()):
            message = ""
        text = " — ".join(p for p in (message, summary) if p)
        if not text or text in seen:
            continue
        seen.add(text)
        turn = int(turns.get(_notification_key(note), current) or current)
        if current - turn > 5:
            continue
        kept.append((turn, int(_num(note.get("id")) or 0), text))
    kept.sort()
    kept = kept[-NOTIFICATION_LIMIT:]
    return [pipeline._wire_line(f"notification.t{turn}.{index}", text)
            for index, (turn, _, text) in enumerate(kept)]


def empire_lines(snapshot: dict[str, Any]) -> list[str]:
    """Lines appended to the EMPIRE summary (after the existing empire.* lines)."""
    lines: list[str] = []
    for builder in (gold_lines, amenity_housing_lines, unit_count_lines, notification_lines):
        try:
            lines.extend(builder(snapshot))
        except Exception:  # never let the panel break the prompt
            continue
    return lines


# ---------------------------------------------------------------------------
# per-city lines
# ---------------------------------------------------------------------------
def city_lines(snapshot: dict[str, Any], city: dict[str, Any], name: str) -> list[str]:
    row = _cities_by_id(snapshot).get(str(city.get("city_id")))
    if not row:
        return []
    lines: list[str] = []
    anarchy = (snapshot.get("your_empire") or {}).get("anarchy_turns") if isinstance(snapshot.get("your_empire"), dict) else 0
    yields = []
    for key, label in (("food", "food"), ("production", "prod"), ("gold", "gold"),
                       ("science", "science"), ("culture", "culture"), ("faith", "faith")):
        value = _num(row.get(key))
        if value is None or value == 0 and not (anarchy and label in ("gold", "science", "culture", "faith")):
            continue
        if value == 0 and anarchy:
            yields.append(f"{label}=0/turn due to anarchy")
        else:
            yields.append(f"{label}={_fmt(value)}")
    if yields:
        lines.append(pipeline._wire_line(f"{name}.yields", " ".join(yields)))
    growth_bits = []
    surplus = _num(row.get("food_surplus"))
    if surplus is not None:
        growth_bits.append(f"{_fmt(surplus, signed=True)} food/turn")
    if isinstance(row.get("turns_to_growth"), int):
        growth_bits.append(f"grows in {row['turns_to_growth']} turns")
    elif isinstance(row.get("turns_to_starve"), int):
        growth_bits.append(f"STARVING, loses a citizen in {row['turns_to_starve']} turns")
    else:
        growth_bits.append("not growing")
    lines.append(pipeline._wire_line(f"{name}.growth", ", ".join(growth_bits)))
    housing = _num(row.get("housing"))
    if housing is not None:
        mult = _num(row.get("housing_growth_mult"))
        text = f"{_fmt(housing)} for {row.get('population', city.get('population'))} pop"
        if mult is not None:
            text += f" (growth x{int(round(mult * 100))}%)"
        lines.append(pipeline._wire_line(f"{name}.housing", text))
    have, need = _num(row.get("amenities")), _num(row.get("amenities_needed"))
    # A shortage is one empire line (empire.amenities.short). A city at or above its need has no mood line.
    if have is not None and need is not None and have - need >= 0:
        lost = [f"-{int(_num(row.get(k)) or 0)} {label}" for k, label in
                (("amenities_lost_bankruptcy", "bankruptcy"), ("amenities_lost_war_weariness", "war weariness"))
                if (_num(row.get(k)) or 0) > 0]
        if lost:
            lines.append(pipeline._wire_line(f"{name}.mood", f"{_fmt(have)} of {_fmt(need)} needed, incl. " + ", ".join(lost)))
    turns = row.get("production_turns")
    if row.get("production_item") and isinstance(turns, int):
        lines.append(pipeline._wire_line(f"{name}.currentProduction.turnsLeft", turns))
    buildings = [str(b) for b in row.get("built_buildings") or [] if b]
    if buildings:
        lines.append(pipeline._wire_line(f"{name}.buildings", ", ".join(buildings)))
    districts = [str(d) for d in row.get("built_districts") or [] if d]
    if districts and not pipeline.map_image_attach_turn(snapshot):
        lines.append(pipeline._wire_line(f"{name}.districts", ", ".join(districts)))
    return lines


def attention_items(snapshot: dict[str, Any]) -> list[str]:
    items: list[str] = []
    idle_cities = []
    for city in snapshot.get("your_cities") or []:
        if not isinstance(city, dict):
            continue
        production = city.get("production") if isinstance(city.get("production"), dict) else {}
        item = production.get("item_id")
        if not item or str(item).upper() in ("NONE", "NULL"):
            idle_cities.append(pipeline._city_prompt_name(city))
    if idle_cities:
        from sidecar.civ6_priorities import priorities_supported
        from sidecar.civ6_wire import _has_queue_production

        names = ", ".join(idle_cities)
        if _has_queue_production(snapshot):
            detail = "Choose an item from each city's catalog this turn. Nothing will be queued for you."
        elif priorities_supported(snapshot):
            detail = (
                "The engine AI picks the next item under the current build priorities. "
                "Change priorities if the mix is wrong. Nothing will be queued for you."
            )
        else:
            detail = "This seat does not take production orders. Nothing will be queued for you."
        items.append(f"QUEUE EMPTY: {names} have nothing in production. {detail}")
    return items


# ---------------------------------------------------------------------------
# production catalogs (reference lines, not orderable rows)
# ---------------------------------------------------------------------------
def _catalog_stats(item: dict[str, Any], turns: Any) -> str:
    bits: list[str] = []
    if isinstance(turns, int):
        bits.append(f"{turns} turn{'s' if turns != 1 else ''}")
    kind = item.get("category")
    cost = _num(item.get("cost"))
    if cost:
        bits.append(f"{_fmt(cost)} prod")
    if kind == "unit":
        combat, ranged = _num(item.get("combat")) or 0, _num(item.get("ranged")) or 0
        if combat:
            bits.append(f"{_fmt(combat)} str")
        if ranged:
            bits.append(f"{_fmt(ranged)} rng str")
            rng = _num(item.get("range")) or 0
            if rng:
                bits.append(f"{_fmt(rng)} range")
        moves = _num(item.get("moves")) or 0
        if moves:
            bits.append(f"{_fmt(moves)} mov")
        upkeep = _num(item.get("upkeep")) or 0
        if upkeep:
            bits.append(f"-{_fmt(upkeep)}gpt")
    elif kind == "building":
        yields = item.get("yields")
        if isinstance(yields, str) and yields.strip():
            bits.append(yields.strip())
        for key, label in (("housing", "housing"), ("amenities", "amenity")):
            value = _num(item.get(key)) or 0
            if value:
                bits.append(f"+{_fmt(value)} {label}")
        maint = _num(item.get("maintenance")) or 0
        if maint:
            bits.append(f"-{_fmt(maint)}gpt")
    return ", ".join(bits)


def production_catalog_lines(snapshot: dict[str, Any], city_tokens: dict[str, dict[str, list[str]]]) -> list[str]:
    """``City.production.catalog = UNIT_X (5 turns, 40 prod, 20 str, 2 mov, -1gpt) | ...``.

    Stats live here, in the reference catalog, so the orderable option rows keep bare
    IDs (the reply parser matches the ID exactly).
    """
    economy = economy_block(snapshot)
    catalog = economy.get("build_catalog") if isinstance(economy.get("build_catalog"), dict) else {}
    turns_by_city = economy.get("build_turns") if isinstance(economy.get("build_turns"), dict) else {}
    if not catalog and not turns_by_city:
        return []
    lines: list[str] = []
    for city in snapshot.get("your_cities") or []:
        if not isinstance(city, dict):
            continue
        city_id = str(city.get("city_id"))
        options = (city_tokens.get(city_id) or {}).get("production") or []
        if not options:
            continue
        turns = turns_by_city.get(city_id) if isinstance(turns_by_city.get(city_id), dict) else {}
        from sidecar import civ6_combat_wire as combat_wire

        threatened = city_id in combat_wire.threatened_city_ids(snapshot)
        ranked: list[tuple[int, int, str]] = []
        for index, token in enumerate(options):
            base = token.split("@", 1)[0].split(":", 1)[0]
            turn_n = turns.get(token, turns.get(base))
            if isinstance(turn_n, int) and turn_n >= 30:
                continue
            item = catalog.get(token) if isinstance(catalog.get(token), dict) else catalog.get(base, {})
            if not isinstance(item, dict):
                item = {}
            stats = _catalog_stats(item, turn_n if isinstance(turn_n, int) else None)
            text = f"{token} ({stats})" if stats else token
            rank = index
            if threatened:
                upper = base.upper()
                ranged = _num(item.get("ranged")) or 0
                combat = _num(item.get("combat")) or 0
                ranged_name = any(k in upper for k in ("ARCHER", "CROSSBOW", "SLINGER", "CANNON", "CATAPULT", "TREBUCHET", "BOMBARD"))
                if "WALL" in upper:
                    rank = 0
                elif ranged > 0 or ranged_name:
                    rank = 1
                elif combat > 0 or upper.startswith("UNIT_"):
                    rank = 2
                else:
                    rank = 3
            ranked.append((rank, index, text))
        ranked.sort()
        parts = [text for _, _, text in ranked]
        prefix = "THREATENED — walls, ranged, then melee first: " if threatened and parts else ""
        lines.append(pipeline._wire_line(
            f"{pipeline._city_prompt_name(city)}.production.catalog", prefix + " | ".join(parts),
        ))
    if lines:
        lines.insert(0, "# Production catalogs (stats only; reply with the bare ID, e.g. UNIT_WARRIOR):")
    return lines
