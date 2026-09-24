"""Include prompt fragments when a snapshot matches a gate spec.

A spec is a dict. Every listed leaf must match (AND). Combinators:

- any: list of specs; at least one must match
- all: list of specs; every one must match
- not: nested spec that must not match
- turn_scale: "speed" multiplies turn_lte / turn_gte / turn_lt / turn_gt
  by game speed (Quick 0.67, Standard 1, Epic 1.5, Marathon 3)

Leaf keys (omit a key to ignore it):

- turn_lte, turn_gte, turn_lt, turn_gt
- era_in, era_not_in
- speed_in, world_size_in, map_script_in
- civ_in, leader_in
- tech_all, tech_any, tech_none
- city_count_lte, city_count_gte, settler_count_lte, settler_count_eq
- legal_kind_any
"""
from __future__ import annotations

from typing import Any

SPEED_TURN_SCALE = {
    "GAMESPEED_QUICK": 0.67,
    "GAMESPEED_STANDARD": 1.0,
    "GAMESPEED_EPIC": 1.5,
    "GAMESPEED_MARATHON": 3.0,
}

_ID_LIST_KEYS = {
    "era_in": "era_id",
    "era_not_in": "era_id",
    "speed_in": "game_speed_id",
    "world_size_in": "world_size_id",
    "map_script_in": "map_script",
    "civ_in": "civ_id",
    "leader_in": "leader_id",
}


def facts_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    data = snapshot if isinstance(snapshot, dict) else {}
    decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
    game = data.get("game") if isinstance(data.get("game"), dict) else {}
    personality = data.get("personality") if isinstance(data.get("personality"), dict) else {}
    empire = data.get("your_empire") if isinstance(data.get("your_empire"), dict) else {}
    research = empire.get("research") if isinstance(empire.get("research"), dict) else {}
    unit_counts = empire.get("unit_counts") if isinstance(empire.get("unit_counts"), dict) else {}
    cities = data.get("your_cities") if isinstance(data.get("your_cities"), list) else []
    legal = data.get("legal_commands") if isinstance(data.get("legal_commands"), list) else []
    known = research.get("known_tech_ids") if isinstance(research.get("known_tech_ids"), list) else []
    kinds: set[str] = set()
    for command in legal:
        if isinstance(command, dict) and command.get("kind"):
            kinds.add(str(command["kind"]))
    try:
        turn = int(decision.get("turn", 0) or 0)
    except (TypeError, ValueError):
        turn = 0
    try:
        settlers = int(unit_counts.get("settlers", 0) or 0)
    except (TypeError, ValueError):
        settlers = 0
    return {
        "turn": turn,
        "era_id": str(game.get("era_id") or ""),
        "game_speed_id": str(game.get("game_speed_id") or ""),
        "world_size_id": str(game.get("world_size_id") or ""),
        "map_script": str(game.get("map_script") or ""),
        "civ_id": str(personality.get("civilization_id") or ""),
        "leader_id": str(personality.get("leader_id") or ""),
        "known_techs": {str(tech) for tech in known if tech},
        "city_count": len([city for city in cities if isinstance(city, dict)]),
        "settler_count": settlers,
        "legal_kinds": kinds,
    }


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _id_in(actual: str, allowed: Any) -> bool:
    if not isinstance(allowed, (list, tuple, set)):
        allowed = [allowed]
    actual_n = _norm(actual)
    return any(_norm(item) == actual_n for item in allowed)


def _scaled_turn_limit(facts: dict[str, Any], spec: dict[str, Any], limit: Any) -> int:
    try:
        value = float(limit)
    except (TypeError, ValueError):
        return 0
    if spec.get("turn_scale") == "speed":
        value *= SPEED_TURN_SCALE.get(facts["game_speed_id"], 1.0)
    return int(round(value))


def _leaf_ok(facts: dict[str, Any], spec: dict[str, Any], key: str, value: Any) -> bool:
    if key in ("turn_lte", "turn_gte", "turn_lt", "turn_gt"):
        limit = _scaled_turn_limit(facts, spec, value)
        turn = facts["turn"]
        if key == "turn_lte":
            return turn <= limit
        if key == "turn_gte":
            return turn >= limit
        if key == "turn_lt":
            return turn < limit
        return turn > limit
    if key == "era_in":
        return _id_in(facts["era_id"], value)
    if key == "era_not_in":
        return not _id_in(facts["era_id"], value)
    if key in _ID_LIST_KEYS and key not in ("era_in", "era_not_in"):
        return _id_in(facts[_ID_LIST_KEYS[key]], value)
    if key == "tech_all":
        needed = {str(tech) for tech in (value or [])}
        return needed <= facts["known_techs"]
    if key == "tech_any":
        needed = {str(tech) for tech in (value or [])}
        return bool(needed & facts["known_techs"])
    if key == "tech_none":
        banned = {str(tech) for tech in (value or [])}
        return not (banned & facts["known_techs"])
    if key == "city_count_lte":
        return facts["city_count"] <= int(value)
    if key == "city_count_gte":
        return facts["city_count"] >= int(value)
    if key == "settler_count_lte":
        return facts["settler_count"] <= int(value)
    if key == "settler_count_eq":
        return facts["settler_count"] == int(value)
    if key == "legal_kind_any":
        if not isinstance(value, (list, tuple, set)):
            value = [value]
        return bool(facts["legal_kinds"] & {str(item) for item in value})
    return False


def matches(snapshot: dict[str, Any] | None, spec: dict[str, Any] | None) -> bool:
    if not spec:
        return True
    facts = facts_from_snapshot(snapshot)
    for key, value in spec.items():
        if key == "turn_scale":
            continue
        if key == "any":
            nested = value if isinstance(value, list) else []
            if not any(matches(snapshot, item) for item in nested):
                return False
            continue
        if key == "all":
            nested = value if isinstance(value, list) else []
            if not all(matches(snapshot, item) for item in nested):
                return False
            continue
        if key == "not":
            if matches(snapshot, value if isinstance(value, dict) else {}):
                return False
            continue
        if not _leaf_ok(facts, spec, key, value):
            return False
    return True


def gated_lines(snapshot: dict[str, Any] | None, fragments: list[dict[str, Any]]) -> list[str]:
    """Each fragment is {when: spec, lines: [str, ...]}."""
    out: list[str] = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        if not matches(snapshot, fragment.get("when") if isinstance(fragment.get("when"), dict) else {}):
            continue
        lines = fragment.get("lines")
        if isinstance(lines, str) and lines:
            out.append(lines)
        elif isinstance(lines, list):
            out.extend(str(line) for line in lines if line)
    return out
