"""Civ V importance-scored journal, ported for Civ6 seats.

Score is computed before the model call. Retention, pinning, ranking, and
sentence tiers use the ADJUSTED score (shared peer floor + rolling 20-turn
median baseline). Raw and adjusted are both stored.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import median
from typing import Any

from sidecar.civ6_common import dct as _dct
from sidecar.civ6_common import lst as _lst
from sidecar.civ6_common import turn as _turn

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "civ6-turn-importance.json"
FIELD_CAP_DEFAULT = 16000

_SIT_NORM = re.compile(r"\s+")


def load_config() -> dict[str, Any]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"), strict=False)
    except (OSError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def field_cap() -> int:
    try:
        return max(800, int(load_config().get("field_cap") or FIELD_CAP_DEFAULT))
    except (TypeError, ValueError):
        return FIELD_CAP_DEFAULT


def clip_field(text: Any) -> str:
    return str(text or "").strip()[:field_cap()]


def _wars(snapshot: dict[str, Any]) -> set[str]:
    diplo = _dct(_dct(snapshot.get("civ6")).get("diplomacy"))
    out: set[str] = set()
    for row in _lst(diplo.get("majors")) + _lst(diplo.get("city_states")):
        if isinstance(row, dict) and row.get("at_war") is True:
            pid = str(row.get("player_id") or "")
            if pid:
                out.add(pid)
    return out


def _city_ids(snapshot: dict[str, Any]) -> set[str]:
    return {
        str(c.get("city_id"))
        for c in _lst(snapshot.get("your_cities"))
        if isinstance(c, dict) and c.get("city_id")
    }


def _capital(snapshot: dict[str, Any]) -> dict[str, Any]:
    for city in _lst(snapshot.get("your_cities")):
        if isinstance(city, dict) and city.get("is_capital"):
            return city
    cities = [c for c in _lst(snapshot.get("your_cities")) if isinstance(c, dict)]
    return cities[0] if cities else {}


def update_event_tracking(snapshot: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
    """Diff this snapshot against last turn's tracking. Store on memory.event_tracking."""
    prev = _dct(memory.get("event_tracking"))
    wars = sorted(_wars(snapshot))
    cities = sorted(_city_ids(snapshot))
    prev_wars = {str(x) for x in _lst(prev.get("wars"))}
    prev_cities = {str(x) for x in _lst(prev.get("cities"))}
    now_wars = set(wars)
    now_cities = set(cities)
    units = [u for u in _lst(snapshot.get("your_units")) if isinstance(u, dict)]
    tracking = {
        "wars": wars,
        "cities": cities,
        "unit_count": len(units),
        "war_declared": sorted(now_wars - prev_wars),
        "peace_made": sorted(prev_wars - now_wars),
        "city_founded": sorted(now_cities - prev_cities),
        "city_lost": sorted(prev_cities - now_cities),
        "seen": list(prev.get("seen") or []),
        "non_exempt_history": list(prev.get("non_exempt_history") or []),
    }
    if prev.get("unit_count") is not None:
        try:
            lost = max(0, int(prev["unit_count"]) - len(units))
        except (TypeError, ValueError):
            lost = 0
        tracking["units_lost"] = lost
    memory["event_tracking"] = tracking
    snapshot["memory"] = {"event_tracking": tracking}
    return tracking


def _count(snapshot: dict[str, Any], kind: str) -> int:
    if kind == "unit_needs_orders":
        return sum(1 for u in _lst(snapshot.get("your_units")) if isinstance(u, dict) and u.get("needs_orders"))
    if kind == "city_needs_production":
        n = 0
        for city in _lst(snapshot.get("your_cities")):
            if not isinstance(city, dict):
                continue
            prod = _dct(city.get("production"))
            if not prod.get("item_id"):
                n += 1
        return n
    if kind == "unit_damaged":
        n = 0
        for unit in _lst(snapshot.get("your_units")):
            if not isinstance(unit, dict):
                continue
            hp = _dct(unit.get("health"))
            cur, mx = hp.get("current"), hp.get("maximum")
            if isinstance(cur, (int, float)) and isinstance(mx, (int, float)) and mx > 0 and cur < mx:
                n += 1
        return n
    if kind == "idle_settlers":
        return sum(
            1 for u in _lst(snapshot.get("your_units"))
            if isinstance(u, dict) and "SETTLER" in str(u.get("unit_type_id") or "") and u.get("needs_orders")
        )
    if kind == "expansion_settler":
        return sum(
            1 for u in _lst(snapshot.get("your_units"))
            if isinstance(u, dict) and "SETTLER" in str(u.get("unit_type_id") or "")
        )
    return 0


def _capital_low(snapshot: dict[str, Any]) -> bool:
    city = _capital(snapshot)
    defense = _dct(city.get("defense"))
    hp, mx = defense.get("hp"), defense.get("max_hp")
    if isinstance(hp, (int, float)) and isinstance(mx, (int, float)) and mx > 0:
        return hp * 2 <= mx
    return False


def _capital_threatened(snapshot: dict[str, Any]) -> bool:
    combat = _dct(_dct(snapshot.get("civ6")).get("combat"))
    cap = _capital(snapshot)
    try:
        cx, cy = int(cap.get("x")), int(cap.get("y"))
    except (TypeError, ValueError):
        plot = str(cap.get("plot_id") or "")
        match = re.search(r"PLOT_(-?\d+)_(-?\d+)$", plot)
        if not match:
            return False
        cx, cy = int(match.group(1)), int(match.group(2))
    for row in _lst(combat.get("hostiles")) + _lst(combat.get("hostile_cities")):
        if not isinstance(row, dict):
            continue
        try:
            if max(abs(int(row["x"]) - cx), abs(int(row["y"]) - cy)) <= 3:
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


def _science_stall(snapshot: dict[str, Any]) -> bool:
    research = _dct(_dct(snapshot.get("your_empire")).get("research"))
    left = research.get("tech_turns_left") or research.get("turns_left")
    try:
        return int(left) <= 0 and not research.get("tech") and not research.get("current")
    except (TypeError, ValueError):
        return False


def _bankrupt(snapshot: dict[str, Any]) -> bool:
    empire = _dct(snapshot.get("your_empire"))
    gold = empire.get("gold")
    gpt = empire.get("gold_per_turn")
    try:
        return int(gold) < 0 or (int(gold) < 10 and int(gpt or 0) < 0)
    except (TypeError, ValueError):
        return False


def _falling_behind(snapshot: dict[str, Any]) -> bool:
    rankings = _dct(_dct(snapshot.get("civ6")).get("rankings"))
    science = rankings.get("science") or rankings.get("yield_science")
    if isinstance(science, list) and science and isinstance(science[0], dict):
        return str(science[0].get("player_id") or "") != str(_dct(snapshot.get("decision")).get("player_id") or "")
    return False


def collect_hits(snapshot: dict[str, Any], tracking: dict[str, Any]) -> list[tuple[str, float, bool]]:
    """(name, raw_amount_before_persist_scale, is_new)."""
    cfg = load_config()
    hits: list[tuple[str, float, bool]] = []
    turn = _turn(snapshot)
    if turn <= 1:
        hits.append(("first_turn", 12, True))
    if _wars(snapshot):
        hits.append(("at_war", 4, bool(tracking.get("war_declared"))))
    lost = _lst(tracking.get("city_lost"))
    if lost:
        hits.append(("city_lost", 10 * len(lost), True))
    if _capital_low(snapshot):
        hits.append(("capital_low_health", 15, True))
    if _capital_threatened(snapshot):
        hits.append(("capital_under_threat", 8, True))
    if snapshot.get("_nuke") or _dct(snapshot.get("civ6")).get("nuke"):
        hits.append(("nuke", 12, True))
    combat = _dct(_dct(snapshot.get("civ6")).get("combat"))
    if combat.get("casualties") or combat.get("you_lost_units"):
        hits.append(("combat_casualties", 4, True))
    if _lst(combat.get("hostiles")):
        hits.append(("enemy_in_range", 2, True))
    lost_u = int(tracking.get("units_lost") or 0)
    if lost_u:
        hits.append(("unit_destroyed", 2 * lost_u, True))
    diplo = _dct(_dct(snapshot.get("civ6")).get("diplomacy"))
    if _lst(diplo.get("pending_deals")) or snapshot.get("_pending_deal"):
        hits.append(("pending_deal", 3, True))
    if tracking.get("first_meet") or snapshot.get("_first_meet"):
        hits.append(("first_meet", 2, True))
    if _count(snapshot, "expansion_settler"):
        hits.append(("expansion_settler", 2, True))
    if _bankrupt(snapshot):
        hits.append(("bankruptcy_spiral", 4, True))
    if _falling_behind(snapshot):
        hits.append(("falling_behind", 3, True))
    if _science_stall(snapshot):
        hits.append(("science_stall", 2, True))
    if len(_city_ids(snapshot)) == 1 and turn <= 8:
        hits.append(("first_city", 4, True))
    if _count(snapshot, "idle_settlers"):
        hits.append(("idle_settlers", 2, True))
    if _lst(tracking.get("war_declared")):
        hits.append(("war_declared", 10, True))
    if _lst(tracking.get("peace_made")):
        hits.append(("peace_made", 8, True))
    deals = int(tracking.get("deals_accepted") or 0)
    if deals:
        hits.append(("deal_accepted", 5 * deals, True))
    if tracking.get("alliance_or_friendship") or snapshot.get("_alliance_or_friendship"):
        hits.append(("alliance_or_friendship", 5, True))
    founded = _lst(tracking.get("city_founded"))
    if founded:
        hits.append(("city_founded", 4 * len(founded), True))
    captured = int(tracking.get("cities_captured") or 0)
    if captured:
        hits.append(("city_captured", 8 * captured, True))
    if tracking.get("wonder_completed") or snapshot.get("_wonder_completed"):
        hits.append(("wonder_completed", 3, True))
    if tracking.get("era_or_age") or snapshot.get("_era_or_age"):
        hits.append(("era_or_age", 3, True))
    if tracking.get("government_change") or snapshot.get("_government_change"):
        hits.append(("government_change", 3, True))
    if snapshot.get("_promise_made") or tracking.get("promise_new"):
        hits.append(("promise_made", 2, True))
    if snapshot.get("_government_or_dedication_choice"):
        hits.append(("government_or_dedication_choice", 2, True))
    for name in ("unit_needs_orders", "city_needs_production", "unit_damaged"):
        n = _count(snapshot, name)
        if n:
            weight = 0.5 if name == "unit_needs_orders" else 0.2
            hits.append((name, weight * n, True))
    _ = cfg
    return hits


def _scale(name: str, amount: float, is_new: bool, seen: set[str], spec: dict[str, Any]) -> tuple[float, bool]:
    first = name not in seen
    if "init" in spec and "persistent" in spec:
        if first:
            return float(spec["init"]), True
        if is_new:
            return float(spec["persistent"]) * 2.0, False
        return float(spec["persistent"]) * 0.5, False
    if first and spec.get("importance_init"):
        return float(spec.get("score") or amount), True
    if name in {"at_war"} and not first and not is_new:
        return amount * 0.5, False
    if is_new and name in seen:
        return amount * 2.0 if spec.get("persistent") else amount, False
    return float(amount), first


def score_turn(
    snapshot: dict[str, Any],
    memory: dict[str, Any],
    *,
    peer_scores: list[float] | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    tracking = update_event_tracking(snapshot, memory)
    seen = {str(x) for x in _lst(tracking.get("seen"))}
    specs = _dct(cfg.get("triggers"))
    exempt_names = {str(x) for x in _lst(cfg.get("exempt"))}
    breakdown: list[dict[str, Any]] = []
    exempt = 0.0
    non_exempt = 0.0
    micro = 0.0
    micro_cap = float(cfg.get("micro_cap") or 6)
    hits = collect_hits(snapshot, tracking)
    for name, amount, is_new in hits:
        spec = _dct(specs.get(name))
        value, first = _scale(name, amount, is_new, seen, spec)
        if spec.get("micro"):
            micro += value
            continue
        row = {"trigger": name, "score": round(value, 3), "new": first or is_new}
        breakdown.append(row)
        if name in exempt_names:
            exempt += value
        else:
            non_exempt += value
        seen.add(name)
    if micro:
        micro = min(micro, micro_cap)
        breakdown.append({"trigger": "micro", "score": round(micro, 3), "new": True})
        non_exempt += micro
    tracking["seen"] = sorted(seen)
    raw = exempt + non_exempt
    floor = 0.0
    peers = list(peer_scores or [])
    if len(peers) >= 1:
        # Need this seat + one peer, or two peers. "at least 2 seats"
        floor = min(peers) if peers else 0.0
    if len(peers) + 1 >= 2 and peers:
        floor = min(peers)
    else:
        floor = 0.0
    frac = float(cfg.get("floor_fraction") or 0.25)
    after_floor = max(0.0, non_exempt - frac * floor)
    history = [float(x) for x in _lst(tracking.get("non_exempt_history")) if isinstance(x, (int, float))]
    baseline = 0.0
    window = int(cfg.get("baseline_turns") or 20)
    if history:
        baseline = float(median(history[-window:]))
    adjusted_non = max(0.0, after_floor - baseline)
    adjusted = exempt + adjusted_non
    history.append(non_exempt)
    tracking["non_exempt_history"] = history[-window:]
    tracking["raw"] = raw
    tracking["adjusted"] = adjusted
    memory["event_tracking"] = tracking
    breakdown.sort(key=lambda r: -float(r.get("score") or 0))
    tier = intelligence_tier(adjusted)
    result = {
        "raw": round(raw, 3),
        "adjusted": round(adjusted, 3),
        "exempt": round(exempt, 3),
        "non_exempt": round(non_exempt, 3),
        "floor": round(floor, 3),
        "baseline": round(baseline, 3),
        "breakdown": breakdown[:12],
        "intelligence_tier": tier,
        "turn": _turn(snapshot),
    }
    snapshot["_importance"] = result
    return result


def intelligence_tier(adjusted: float) -> str:
    if adjusted >= 15:
        return "critical"
    if adjusted >= 10:
        return "high"
    if adjusted >= 5:
        return "medium"
    return "low"


def sentence_minimum(adjusted: float) -> int:
    mins = load_config().get("sentence_mins") or [[5, 5], [10, 8], [15, 10], [20, 15]]
    need = 0
    for threshold, count in mins:
        if adjusted >= float(threshold):
            need = int(count)
    return need


def _row_score(row: dict[str, Any]) -> float:
    for key in ("importance_adjusted", "adjusted", "importance_score"):
        try:
            return float(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def first_journal_turn(thoughts: list[dict[str, Any]]) -> int | None:
    turns = [int(r["turn"]) for r in thoughts if isinstance(r, dict) and r.get("turn") is not None]
    return min(turns) if turns else None


def _peak_turn_in_range(thoughts: list[dict[str, Any]], start: int, end: int) -> int | None:
    best: tuple[float, int] | None = None
    for row in thoughts:
        if not isinstance(row, dict) or row.get("turn") is None:
            continue
        turn = int(row["turn"])
        if turn < start or turn >= end:
            continue
        score = _row_score(row)
        if best is None or score > best[0] or (score == best[0] and turn > best[1]):
            best = (score, turn)
    return best[1] if best else None


def prune_thought_memory(memory: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    thoughts = [r for r in _lst(memory.get("thoughts")) if isinstance(r, dict) and r.get("turn") is not None]
    if not thoughts:
        return memory
    thoughts.sort(key=lambda r: int(r["turn"]))
    latest = int(thoughts[-1]["turn"])
    keep_last = int(cfg.get("keep_last") or 10)
    window = int(cfg.get("window") or 10)
    pin_threshold = float(cfg.get("pin_threshold") or 15)
    pin_max = int(cfg.get("pin_max") or 12)
    keep: set[int] = set()
    opening = first_journal_turn(thoughts)
    if opening is not None:
        keep.add(opening)
    for row in thoughts:
        if int(row["turn"]) > latest - keep_last:
            keep.add(int(row["turn"]))
    end = latest - keep_last
    start = opening or 1
    cursor = start
    while cursor < end:
        peak = _peak_turn_in_range(thoughts, cursor, min(cursor + window, end))
        if peak is not None:
            keep.add(peak)
        cursor += window
    pinned = [r for r in thoughts if _row_score(r) >= pin_threshold]
    pinned.sort(key=lambda r: (_row_score(r), int(r["turn"])))
    while len(pinned) > pin_max:
        pinned.pop(0)
    for row in pinned:
        keep.add(int(row["turn"]))
        row["pinned"] = True
    memory["thoughts"] = [r for r in thoughts if int(r["turn"]) in keep]
    notes = [n for n in _lst(memory.get("remembered")) if isinstance(n, dict)]
    disk = int(cfg.get("remember_disk") or 128)
    memory["remembered"] = notes[-disk:]
    return memory


def _sit_key(row: dict[str, Any]) -> str:
    text = _SIT_NORM.sub(" ", str(row.get("situation") or "")).strip().lower()[:240]
    return text


def rank_key(row: dict[str, Any], current: int, decay_mode: str) -> float:
    age = max(0, current - int(row.get("turn") or 0))
    score = _row_score(row)
    if decay_mode == "half_life":
        return score * (0.5 ** (age / 10.0))
    return score / (1.0 + age)


def select_thought_turns_for_wire(memory: dict[str, Any], current_turn: int) -> list[int]:
    cfg = load_config()
    thoughts = [r for r in _lst(memory.get("thoughts")) if isinstance(r, dict) and r.get("turn") is not None]
    if not thoughts:
        return []
    thoughts.sort(key=lambda r: int(r["turn"]))
    recent_n = int(cfg.get("recent_full_turns") or 3)
    cap = int(cfg.get("journal_turn_cap") or 20)
    decay = str(cfg.get("decay_mode") or "age")
    chosen: list[dict[str, Any]] = []
    seen_sit: set[str] = set()
    eligible = sorted({int(r["turn"]) for r in thoughts if int(r["turn"]) <= current_turn})
    recent = set(eligible[-recent_n:])
    opening = first_journal_turn(thoughts)
    must = set(recent)
    if opening is not None:
        must.add(opening)
    for row in thoughts:
        if int(row["turn"]) in must:
            key = _sit_key(row)
            if key:
                seen_sit.add(key)
            chosen.append(row)
    rest = [r for r in thoughts if int(r["turn"]) not in must]
    rest.sort(key=lambda r: -rank_key(r, current_turn, decay))
    for row in rest:
        if len(chosen) >= cap:
            break
        key = _sit_key(row)
        if key and key in seen_sit:
            continue
        if key:
            seen_sit.add(key)
        chosen.append(row)
    chosen.sort(key=lambda r: int(r["turn"]))
    return [int(r["turn"]) for r in chosen]


def attach_thought_row(
    memory: dict[str, Any],
    turn: int,
    situation: str,
    strategy: str,
    decision: str,
    scored: dict[str, Any],
) -> dict[str, Any]:
    thoughts = [
        item for item in _lst(memory.get("thoughts"))
        if not (isinstance(item, dict) and int(item.get("turn", -1)) == turn)
    ]
    thoughts.append({
        "turn": int(turn),
        "situation": clip_field(situation),
        "strategy": clip_field(strategy),
        "decision": clip_field(decision),
        "importance_score": scored.get("raw") or 0,
        "importance_adjusted": scored.get("adjusted") or 0,
        "importance_breakdown": list(scored.get("breakdown") or []),
        "intelligence_tier": scored.get("intelligence_tier") or "low",
        "pinned": float(scored.get("adjusted") or 0) >= float(load_config().get("pin_threshold") or 15),
    })
    thoughts.sort(key=lambda item: int(item.get("turn") or 0))
    memory["thoughts"] = thoughts
    append_situation_log(memory, turn, situation)
    return memory


def append_situation_log(memory: dict[str, Any], turn: int, text: str) -> dict[str, Any]:
    rows = [r for r in _lst(memory.get("situation_log")) if isinstance(r, dict)]
    rows = [r for r in rows if int(r.get("turn") or -1) != int(turn)]
    clipped = clip_field(text)[:240]
    if clipped:
        rows.append({"turn": int(turn), "text": clipped})
    cap = int(load_config().get("situation_log_max") or 24)
    memory["situation_log"] = rows[-cap:]
    return memory


def write_importance_file(thought_path: Path, player_id: str, scored: dict[str, Any]) -> Path | None:
    if thought_path is None:
        return None
    turn = int(scored.get("turn") or 0)
    path = thought_path.parent / f"{thought_path.stem}_importance_t{turn}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "player_id": player_id,
            "turn": turn,
            "raw": scored.get("raw"),
            "adjusted": scored.get("adjusted"),
            "exempt": scored.get("exempt"),
            "non_exempt": scored.get("non_exempt"),
            "floor": scored.get("floor"),
            "baseline": scored.get("baseline"),
            "intelligence_tier": scored.get("intelligence_tier"),
            "breakdown": scored.get("breakdown"),
        }, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return None
    return path


def peer_scores(thought_path: Path | None, player_id: str, turn: int) -> list[float]:
    if thought_path is None or not thought_path.parent.is_dir():
        return []
    scores: list[float] = []
    for when in (turn, turn - 1):
        if when <= 0:
            continue
        for path in thought_path.parent.glob(f"*_importance_t{when}.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"), strict=False)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or str(data.get("player_id") or "") == player_id:
                continue
            try:
                scores.append(float(data.get("raw") or 0))
            except (TypeError, ValueError):
                continue
    return scores


def situation_log_rows(memory: dict[str, Any], current_turn: int) -> list[dict[str, Any]]:
    cfg = load_config()
    rows = [r for r in _lst(memory.get("situation_log")) if isinstance(r, dict)]
    keep: list[dict[str, Any]] = []
    for row in rows:
        try:
            turn = int(row.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if turn == current_turn or turn % 10 == 0 or turn > current_turn - 12:
            keep.append(row)
    cap = int(cfg.get("situation_log_max") or 24)
    return keep[-cap:]


def apply_score_to_snapshot(snapshot: dict[str, Any], memory: dict[str, Any], thought_path: Path | None = None) -> dict[str, Any]:
    player_id = str(_dct(snapshot.get("decision")).get("player_id") or "")
    peers = peer_scores(thought_path, player_id, _turn(snapshot)) if thought_path else []
    scored = score_turn(snapshot, memory, peer_scores=peers)
    snapshot["_importance"] = scored
    memory["last_importance"] = scored
    if thought_path is not None:
        write_importance_file(thought_path, player_id, scored)
    return scored


def journal_rules_lines(adjusted: float) -> list[str]:
    need = sentence_minimum(adjusted)
    lines = [
        "Journal rows are one field per line (situation, strategy, decision). Do not join them with pipes.",
    ]
    if need:
        lines.append(
            f"This turn's importance is {adjusted:.0f}: write at least {need} sentences across thought.situation and thought.strategy."
        )
    return lines
