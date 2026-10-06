"""Civ VI snapshot adapter — bridge between game snapshots and civ6_wire / pipeline_v2."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import RefResolver

from sidecar import pipeline_v2 as pipeline

ROOT = Path(__file__).resolve().parents[1]
CIV6_SCHEMA_PATH = ROOT / "schemas" / "decision-input-civ6.json"
CAPABILITIES_PATH = ROOT / "config" / "civ6-command-capabilities.json"
GOLDEN_SNAPSHOT_PATH = ROOT / "fixtures" / "civ6" / "snapshot-turn-classical-golden.json"

_CIV6_INPUT_VALIDATOR: Draft202012Validator | None = None


def _civ6_validator() -> Draft202012Validator:
    global _CIV6_INPUT_VALIDATOR
    if _CIV6_INPUT_VALIDATOR is None:
        schema_store = {
            CIV6_SCHEMA_PATH.name: json.loads(CIV6_SCHEMA_PATH.read_text(encoding="utf-8")),
            "decision-input-v2.json": json.loads((ROOT / "schemas" / "decision-input-v2.json").read_text(encoding="utf-8")),
        }
        resolver = RefResolver(base_uri=CIV6_SCHEMA_PATH.as_uri(), referrer=schema_store[CIV6_SCHEMA_PATH.name], store=schema_store)
        _CIV6_INPUT_VALIDATOR = Draft202012Validator(schema_store[CIV6_SCHEMA_PATH.name], resolver=resolver)
    return _CIV6_INPUT_VALIDATOR


def _schema_errors(snapshot: dict[str, Any]) -> list[str]:
    return [f"{'.'.join(str(part) for part in error.path)}: {error.message}" for error in _civ6_validator().iter_errors(snapshot)]


def is_civ6_snapshot(snapshot: dict[str, Any]) -> bool:
    version = snapshot.get("schema_version")
    return isinstance(version, str) and version.startswith("civ6ai-input/")


def validate_civ6_snapshot(snapshot: dict[str, Any]) -> None:
    errors = _schema_errors(snapshot)
    if errors:
        raise pipeline.BoundaryError("civ6_snapshot_schema", "; ".join(errors[:8]))
    ids: set[str] = set()
    for command in snapshot.get("legal_commands", []):
        command_id = command.get("command_id")
        if not isinstance(command_id, str):
            continue
        if command_id in ids:
            raise pipeline.BoundaryError("duplicate_legal_id", command_id)
        ids.add(command_id)


_LUA_ARRAY_KEYS = frozenset({
    "promotion_ids",
    "mission_queue",
    "cargo_unit_ids",
    "upgrade_options",
    "legal_commands",
    "your_units",
    "your_cities",
    "commands",
    "chat_messages",
    "affected_ids",
    "visible_players",
    "known_players",
    "options",
    "victory_ids",
    "queue",
    "known_tech_ids",
    "known_civic_ids",
    "civics",
    "plots",
    "trade_routes",
    "specialists",
    "buildings",
    "religions",
    "corporations",
    "worked_plot_ids",
    "garrison_unit_ids",
    "production_queue",
    "river_edges",
    "visible_stack_ids",
    "areas",
    "frontiers",
    "visible_stacks",
    "legend",
    "label_ids",
    "convertible_religion_ids",
    "resources",
    "victory_progress",
    "strategics",
})


def _lua_table_to_array(value: dict[str, Any]) -> list[Any]:
    if not value:
        return []
    if all(str(key).isdigit() for key in value):
        ordered = sorted(value.keys(), key=lambda key: int(str(key)))
        return [coerce_lua_empty_arrays(value[key]) for key in ordered]
    return [coerce_lua_empty_arrays(value)]


def coerce_lua_empty_arrays(node: Any) -> Any:
    """Lua cannot distinguish {} from []; empty array fields arrive as objects."""
    if isinstance(node, list):
        return [coerce_lua_empty_arrays(item) for item in node]
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _LUA_ARRAY_KEYS:
                if isinstance(value, list):
                    out[key] = coerce_lua_empty_arrays(value)
                elif isinstance(value, dict):
                    out[key] = _lua_table_to_array(value)
                else:
                    out[key] = coerce_lua_empty_arrays(value)
            else:
                out[key] = coerce_lua_empty_arrays(value)
        return out
    return node


def _as_schema_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value >= 0:
            return int(math.floor(value + 0.5))
        return int(math.ceil(value - 0.5))
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number >= 0:
        return int(math.floor(number + 0.5))
    return int(math.ceil(number - 0.5))


def _coerce_schema_integers(node: Any) -> Any:
    """Civ6 yields are fractional; the shared input schema stores integers."""
    if isinstance(node, list):
        return [_coerce_schema_integers(item) for item in node]
    if isinstance(node, dict):
        return {key: _coerce_schema_integers(value) for key, value in node.items()}
    coerced = _as_schema_int(node)
    if coerced is not None and not isinstance(node, bool) and isinstance(node, (int, float)):
        return coerced
    return node


def _merge_live_city(city: dict[str, Any]) -> dict[str, Any]:
    plot_id = city.get("plot_id") if isinstance(city.get("plot_id"), str) else "PLOT_0_0"
    parts = plot_id.split("_")
    plot_x = int(parts[1]) if len(parts) >= 3 and str(parts[1]).isdigit() else 0
    plot_y = int(parts[2]) if len(parts) >= 3 and str(parts[2]).isdigit() else 0
    city_id = city.get("city_id") if isinstance(city.get("city_id"), str) else "CITY_0"
    name = city.get("name") if isinstance(city.get("name"), str) else city_id
    population = _as_schema_int(city.get("population")) or 1
    is_capital = city.get("is_capital") is True
    base = _empty_city(city_id, name, plot_x, plot_y, max(1, population), is_capital)
    _deep_merge_from_raw(base, city)
    production = base.get("production")
    if isinstance(production, dict):
        production.setdefault("item_id", None)
        production.setdefault("progress", 0)
        production.setdefault("cost", 0)
        production.setdefault("production_per_turn", 0)
        production.setdefault("estimated_turns_remaining", None)
    return base


def _merge_live_unit(unit: dict[str, Any]) -> dict[str, Any]:
    unit_id = unit.get("unit_id") if isinstance(unit.get("unit_id"), str) else "UNIT_0"
    unit_type = unit.get("unit_type_id") if isinstance(unit.get("unit_type_id"), str) else "UNIT_UNKNOWN"
    plot_id = unit.get("plot_id") if isinstance(unit.get("plot_id"), str) else "PLOT_0_0"
    parts = plot_id.split("_")
    plot_x = int(parts[1]) if len(parts) >= 3 and str(parts[1]).isdigit() else 0
    plot_y = int(parts[2]) if len(parts) >= 3 and str(parts[2]).isdigit() else 0
    moves = _as_schema_int((unit.get("movement") or {}).get("current") if isinstance(unit.get("movement"), dict) else 0) or 0
    base = _empty_unit(unit_id, unit_type, plot_x, plot_y, moves, unit.get("needs_orders") is True)
    _deep_merge_from_raw(base, unit)
    return base


def _normalize_empire_numbers(snapshot: dict[str, Any]) -> None:
    coerced = _coerce_schema_integers(snapshot)
    if coerced is not snapshot:
        snapshot.clear()
        snapshot.update(coerced)


_DECISION_REASON_WIRE_ALIASES = {
    "human_chat": "turn_start",
    "chat": "turn_start",
}

_HISTORY_EVENT_LIST_KEYS = (
    "public_events",
    "command_results",
    "accepted_decisions",
    "diplomacy_events",
)


def _normalize_history_item(event: Any) -> dict[str, Any]:
    """Map flat Lua wire (text, extra keys) into schema history_item."""
    if not isinstance(event, dict):
        return {"turn": 0, "kind": "EVENT_UNKNOWN", "summary": "", "affected_ids": []}
    turn_raw = event.get("turn", 0)
    try:
        turn = int(turn_raw)
    except (TypeError, ValueError):
        turn = 0
    kind = str(event.get("kind") or "EVENT_UNKNOWN")
    summary = str(event.get("summary") or event.get("text") or "").strip()[:300]
    affected = event.get("affected_ids")
    affected_ids: list[str] = []
    if isinstance(affected, list):
        affected_ids = [str(item) for item in affected if item is not None and str(item)]
    if not affected_ids and event.get("unit"):
        affected_ids = [str(event["unit"])]
    if not summary:
        bits = []
        if event.get("ok") is True:
            bits.append("ok")
        elif event.get("ok") is False:
            bits.append("fail")
        if event.get("kind"):
            bits.append(str(event["kind"]))
        if event.get("reason"):
            bits.append(str(event["reason"]))
        summary = " ".join(bits)[:300]
    return {
        "turn": turn,
        "kind": kind,
        "summary": summary,
        "affected_ids": affected_ids,
        **{
            key: event[key]
            for key in ("decision_turn", "apply_turn", "unit", "ok", "reason", "effect")
            if key in event
        },
    }


def _normalize_history_wire(history: dict[str, Any]) -> None:
    if history.get("memory_summary") is None:
        history["memory_summary"] = ""
    for key in _HISTORY_EVENT_LIST_KEYS:
        events = history.get(key)
        if isinstance(events, list):
            history[key] = [_normalize_history_item(event) for event in events]


def _normalize_decision_wire(decision: dict[str, Any]) -> None:
    reason = decision.get("reason")
    if isinstance(reason, str):
        mapped = _DECISION_REASON_WIRE_ALIASES.get(reason)
        if mapped is not None:
            decision["reason"] = mapped


_CHAT_TEXT_MAX = 240  # decision-input-v2 chat_record.text maxLength
_ID_MAX = 128


def inbox_message_id(turn: int, from_player_id: str, text: str) -> str:
    """Stable id for a private chat record (same message -> same id on every snapshot)."""
    digest = hashlib.sha1(f"{turn}|{from_player_id}|{text}".encode("utf-8")).hexdigest()[:16]
    return f"MSG_T{turn}_{digest}"


def _normalize_chat_record(message: Any) -> dict[str, Any] | None:
    """Coerce one Lua private_inbox entry to schema chat_record (message_id, from_player_id, turn, text).

    Older Civ6Ai_Chat.lua stored inbox messages without message_id, which failed
    schema validation and cost the seat its model turn.
    """
    if not isinstance(message, dict):
        return None
    try:
        turn = max(0, int(message.get("turn", 0)))
    except (TypeError, ValueError):
        turn = 0
    sender = str(message.get("from_player_id") or "").strip()[:_ID_MAX] or "PLAYER_UNKNOWN"
    text = message.get("text")
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    full_text = text
    text = text[:_CHAT_TEXT_MAX]
    message_id = str(message.get("message_id") or "").strip()[:_ID_MAX]
    if not message_id:
        message_id = inbox_message_id(turn, sender, full_text)
    return {"message_id": message_id, "from_player_id": sender, "turn": turn, "text": text}


def _normalize_private_inbox(snapshot: dict[str, Any]) -> None:
    diplomacy = snapshot.get("diplomacy")
    if not isinstance(diplomacy, dict):
        return
    inbox = diplomacy.get("private_inbox")
    if isinstance(inbox, dict):  # Lua empty/sparse array
        inbox = [inbox[k] for k in sorted(inbox, key=lambda k: int(k) if str(k).isdigit() else 0)]
    if not isinstance(inbox, list):
        return
    diplomacy["private_inbox"] = [r for r in (_normalize_chat_record(m) for m in inbox) if r is not None]


def _normalize_wire_shapes(snapshot: dict[str, Any]) -> None:
    """Normalize flat game/Lua wire into civ6ai-input schema before validation."""
    history = snapshot.get("history")
    if isinstance(history, dict):
        _normalize_history_wire(history)
    _normalize_private_inbox(snapshot)
    decision = snapshot.get("decision")
    if isinstance(decision, dict):
        _normalize_decision_wire(decision)


def normalize_civ6_snapshot(snapshot: dict[str, Any]) -> None:
    coerced = coerce_lua_empty_arrays(snapshot)
    if coerced is not snapshot:
        snapshot.clear()
        snapshot.update(coerced)
    _normalize_empire_numbers(snapshot)
    _normalize_wire_shapes(snapshot)
    snapshot["schema_version"] = "civ6ai-input/1"
    pipeline.normalize_personality(snapshot)
    civ6 = snapshot.get("civ6")
    if not isinstance(civ6, dict):
        snapshot["civ6"] = {}
    normalize_civ6_diplomacy(snapshot)
    normalize_civ6_late_game(snapshot)
    derive_known_other_cities(snapshot)
    validate_civ6_snapshot(snapshot)


def _as_list(value: Any) -> list[Any]:
    """Lua sends empty arrays as {} and sparse ones as {"1": ..}; accept both."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if not value:
            return []
        if all(str(key).isdigit() for key in value):
            return [value[key] for key in sorted(value, key=lambda key: int(str(key)))]
    return []


def _normalize_trade_stock(stock: Any) -> dict[str, Any] | None:
    if not isinstance(stock, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("luxuries", "strategics"):
        rows = []
        for row in _as_list(stock.get(key)):
            if isinstance(row, dict) and isinstance(row.get("resource_id"), str):
                amount = _as_schema_int(row.get("amount"))
                rows.append({"resource_id": row["resource_id"], "amount": amount if amount is not None else 1})
        out[key] = rows
    for key in ("gold", "gold_per_turn"):
        number = _as_schema_int(stock.get(key))
        if number is not None:
            out[key] = number
    return out


def normalize_civ6_diplomacy(snapshot: dict[str, Any]) -> None:
    """Shape the optional ``civ6.diplomacy`` block (newer mods only).

    Absent -> nothing to do (older Lua); malformed -> dropped rather than failing
    schema validation, so a partly-working engine query never costs the turn.
    """
    civ6 = snapshot.get("civ6")
    if not isinstance(civ6, dict) or "diplomacy" not in civ6:
        return
    raw = civ6.get("diplomacy")
    if not isinstance(raw, dict):
        civ6.pop("diplomacy", None)
        return
    out: dict[str, Any] = {}
    majors = []
    for row in _as_list(raw.get("majors")):
        if not isinstance(row, dict) or not isinstance(row.get("player_id"), str):
            continue
        major: dict[str, Any] = {"player_id": row["player_id"]}
        for key in ("state", "relationship", "alliance_type"):
            if isinstance(row.get(key), str) and row[key]:
                major[key] = row[key]
        score = _as_schema_int(row.get("diplomatic_score"))
        if score is not None:
            major["diplomatic_score"] = score
        for key in ("at_war", "denounced", "declared_friendship", "alliance", "open_borders", "defensive_pact",
                    "can_declare_war", "can_make_peace"):
            if isinstance(row.get(key), bool):
                major[key] = row[key]
        major["at_war_with"] = [p for p in _as_list(row.get("at_war_with")) if isinstance(p, str)]
        reasons = []
        for reason in _as_list(row.get("reasons")):
            if isinstance(reason, dict) and isinstance(reason.get("text"), str):
                reasons.append({"text": reason["text"][:80], "score": _as_schema_int(reason.get("score")) or 0})
        major["reasons"] = reasons
        trade = _normalize_trade_stock(row.get("trade"))
        if trade is not None:
            major["trade"] = trade
        majors.append(major)
    out["majors"] = majors
    city_states = []
    for row in _as_list(raw.get("city_states")):
        if not isinstance(row, dict) or not isinstance(row.get("player_id"), str):
            continue
        cs: dict[str, Any] = {"player_id": row["player_id"]}
        for key in ("name", "city_state_type", "suzerain_id"):
            if isinstance(row.get(key), str) and row[key]:
                cs[key] = row[key]
        envoys = _as_schema_int(row.get("your_envoys"))
        if envoys is not None:
            cs["your_envoys"] = envoys
        if isinstance(row.get("at_war"), bool):
            cs["at_war"] = row["at_war"]
        for key in ("can_declare_war", "can_make_peace"):
            if isinstance(row.get(key), bool):
                cs[key] = row[key]
        city_states.append(cs)
    out["city_states"] = city_states
    wars = []
    for pair in _as_list(raw.get("wars")):
        members = [p for p in _as_list(pair) if isinstance(p, str)]
        if len(members) == 2:
            wars.append(members)
    out["wars"] = wars
    trade = _normalize_trade_stock(raw.get("your_trade"))
    if trade is not None:
        out["your_trade"] = trade
    envoys = _as_schema_int(raw.get("envoys_to_give"))
    if envoys is not None:
        out["envoys_to_give"] = envoys
    civ6["diplomacy"] = out


def _keep_late_game_numbers(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, str) and value:
            out[key] = value
    return out


def normalize_civ6_late_game(snapshot: dict[str, Any]) -> None:
    """Shape optional Gathering Storm climate / power / stockpile blocks.

    Absent (older mods, base game, or not yet relevant) is fine. Malformed
    tables are dropped so they never fail schema validation.
    """
    civ6 = snapshot.get("civ6")
    if not isinstance(civ6, dict):
        return
    climate = civ6.get("climate")
    if "climate" in civ6:
        if not isinstance(climate, dict):
            civ6.pop("climate", None)
        else:
            kept = _keep_late_game_numbers(climate, (
                "source", "co2_world", "co2_you", "level", "temperature_c_tenths",
                "sea_rise_turns", "tiles_flooded", "tiles_submerged",
                "storm_pct", "flood_pct", "drought_pct",
            ))
            if kept:
                civ6["climate"] = kept
            else:
                civ6.pop("climate", None)
    power = civ6.get("power")
    if "power" in civ6:
        if not isinstance(power, dict):
            civ6.pop("power", None)
        else:
            cities = []
            for row in _as_list(power.get("cities")):
                if not isinstance(row, dict) or not isinstance(row.get("city_id"), str):
                    continue
                city = _keep_late_game_numbers(row, (
                    "city_id", "name", "required", "free", "temporary",
                    "powered", "powered_by_project",
                ))
                if city.get("city_id"):
                    cities.append(city)
            if cities:
                out: dict[str, Any] = {"cities": cities}
                if isinstance(power.get("source"), str) and power["source"]:
                    out["source"] = power["source"]
                for key in ("cities_powered", "cities_needing"):
                    number = _as_schema_int(power.get(key))
                    if number is not None:
                        out[key] = number
                civ6["power"] = out
            else:
                civ6.pop("power", None)
    stock = civ6.get("stockpiles")
    if "stockpiles" in civ6:
        if not isinstance(stock, dict):
            civ6.pop("stockpiles", None)
        else:
            rows = []
            for row in _as_list(stock.get("strategics")):
                if not isinstance(row, dict) or not isinstance(row.get("resource_id"), str):
                    continue
                item = _keep_late_game_numbers(row, (
                    "resource_id", "amount", "cap", "reserved", "per_turn",
                    "from_improvements", "import", "bonus", "unit_demand", "power_demand",
                ))
                if item.get("resource_id"):
                    rows.append(item)
            if rows:
                out = {"strategics": rows}
                if isinstance(stock.get("source"), str) and stock["source"]:
                    out["source"] = stock["source"]
                civ6["stockpiles"] = out
            else:
                civ6.pop("stockpiles", None)


def _is_city_state_player(player: dict[str, Any]) -> bool:
    leader = str(player.get("leader_id") or "").upper()
    return leader.startswith("LEADER_MINOR_CIV_")


def derive_known_other_cities(snapshot: dict[str, Any]) -> int:
    """Fill ``known_other_cities`` from revealed city plots owned by other players.

    Older Civ6Ai_Snapshot.lua always sent an empty list even though
    ``known_map.plots`` carries ``city_id`` + ``revealed_owner_id`` for every
    revealed foreign city tile, so the map had no foreign city marker and the prompt
    no city list. Returns how many cities were added. No-op when the list is filled.
    """
    existing = snapshot.get("known_other_cities")
    if isinstance(existing, list) and existing:
        return 0
    player_id = str((snapshot.get("decision") or {}).get("player_id") or "")
    known_map = snapshot.get("known_map")
    plots = known_map.get("plots") if isinstance(known_map, dict) else None
    if not isinstance(plots, list):
        return 0
    players = {
        str(p.get("player_id")): p
        for p in snapshot.get("known_players", []) or []
        if isinstance(p, dict) and p.get("player_id")
    }
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    decision = snapshot.get("decision") if isinstance(snapshot.get("decision"), dict) else {}
    turn = next(
        (value for value in (game.get("turn"), decision.get("turn")) if isinstance(value, int) and value >= 0),
        0,
    )
    cities: list[dict[str, Any]] = []
    for plot in plots:
        if not isinstance(plot, dict) or not plot.get("city_id"):
            continue
        owner = plot.get("revealed_owner_id")
        if not isinstance(owner, str) or not owner or owner == player_id:
            continue
        x, y = plot.get("x"), plot.get("y")
        plot_id = plot.get("plot_id") or (f"PLOT_{x}_{y}" if x is not None and y is not None else None)
        if not plot_id:
            continue
        player = players.get(owner, {})
        leader_name = str(player.get("leader_name") or "").strip()
        civ = str(player.get("civilization_id") or owner).removeprefix("CIVILIZATION_")
        civ_label = civ.replace("_", " ").title()
        if player and _is_city_state_player(player):
            name = leader_name or civ_label
        else:
            name = f"{civ_label} city"
        knowledge = plot.get("knowledge") if plot.get("knowledge") in ("visible", "remembered") else "remembered"
        last_seen = plot.get("last_seen_turn")
        if not isinstance(last_seen, int) or last_seen < 0:
            last_seen = turn if knowledge == "visible" else 0
        cities.append({
            # Lua city ids are per-owner (CITY_65536 repeats across players); make them unique.
            "city_id": f"CITY_{owner}_{plot_id}",
            "owner_player_id": owner,
            "name": name,
            "plot_id": str(plot_id),
            "area_id": str(plot.get("area_id") or "AREA_UNKNOWN"),
            "knowledge": knowledge,
            "last_seen_turn": int(last_seen),
            "population": None,
            "is_capital": None,
            "visible_defense": None,
        })
    if cities:
        snapshot["known_other_cities"] = cities
    return len(cities)


def load_capabilities() -> dict[str, Any]:
    return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))


def load_golden_snapshot(path: Path | None = None) -> dict[str, Any]:
    target = path or GOLDEN_SNAPSHOT_PATH
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise pipeline.BoundaryError("golden_snapshot", "Expected object")
    normalize_civ6_snapshot(payload)
    return payload


def _empty_amounts() -> dict[str, int | None]:
    return {"current": 0, "maximum": 0, "change_per_turn": 0}


def _empty_commerce_item() -> dict[str, int]:
    return {"percent": 0, "rate": 0}


def _empty_plot(plot_id: str = "PLOT_0_0", x: int = 0, y: int = 0) -> dict[str, Any]:
    return {
        "plot_id": plot_id,
        "x": x,
        "y": y,
        "knowledge": "visible",
        "last_seen_turn": 1,
        "area_id": "AREA_0",
        "terrain_id": "TERRAIN_GRASS",
        "water": False,
        "hills": False,
        "peak": False,
        "fresh_water": False,
        "river_edges": [],
        "revealed_owner_id": None,
        "feature_id": None,
        "improvement_id": None,
        "route_id": None,
        "resource_id": None,
        "yields": {"food": 0, "production": 0, "commerce": 0},
        "defense_percent": 0,
        "city_id": None,
        "worked_by_city_id": None,
        "visible_stack_ids": [],
    }


def _empty_city(city_id: str, name: str, plot_x: int, plot_y: int, population: int, is_capital: bool) -> dict[str, Any]:
    return {
        "city_id": city_id,
        "name": name,
        "plot_id": f"PLOT_{plot_x}_{plot_y}",
        "area_id": "AREA_0",
        "is_capital": is_capital,
        "is_coastal": False,
        "population": population,
        "food": _empty_amounts(),
        "production": {
            "item_id": None,
            "progress": 0,
            "cost": 0,
            "production_per_turn": 0,
            "estimated_turns_remaining": None,
        },
        "production_queue": [],
        "yields": {"food": 0, "production": 0, "commerce": 0},
        "commerce": {
            "gold": _empty_commerce_item(),
            "research": _empty_commerce_item(),
            "culture": _empty_commerce_item(),
            "espionage": _empty_commerce_item(),
        },
        "happiness": {"positive": 0, "negative": 0, "net": 0},
        "health": {"positive": 0, "negative": 0, "net": 0},
        "maintenance": 0,
        "culture": _empty_amounts(),
        "great_people": _empty_amounts(),
        "specialists": [],
        "buildings": [],
        "religions": [],
        "corporations": [],
        "trade_routes": [],
        "worked_plot_ids": [],
        "automation": {"citizens": False, "production": True},
        "defense": {"percent": 0, "bombard_damage": 0},
        "occupation_turns": 0,
        "garrison_unit_ids": [],
    }


def _empty_unit(unit_id: str, unit_type: str, plot_x: int, plot_y: int, moves: int, needs_orders: bool) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "unit_type_id": unit_type,
        "unit_class_id": "UNITCLASS_UNKNOWN",
        "domain_id": "DOMAIN_LAND",
        "plot_id": f"PLOT_{plot_x}_{plot_y}",
        "health": {"current": 100, "maximum": 100, "change_per_turn": 0},
        "strength": {"current": 0, "maximum": 0, "change_per_turn": 0},
        "movement": {"current": moves, "maximum": moves, "change_per_turn": 0},
        "level": 1,
        "experience": 0,
        "promotion_ids": [],
        "activity_id": "ACTIVITY_UNKNOWN",
        "mission_queue": [],
        "unit_ai_role": "UNITAI_UNKNOWN",
        "cargo_unit_ids": [],
        "can_act": needs_orders,
        "needs_orders": needs_orders,
        "upgrade_options": [],
    }


def build_classical_golden_snapshot() -> dict[str, Any]:
    """Minimal Classical-era snapshot matching fixtures/civ6 golden prompt."""
    athens = _empty_city("CITY_ATHENS", "Athens", 15, 23, 4, True)
    athens["production"]["item_id"] = "UNIT_SPEARMAN"
    corinth = _empty_city("CITY_CORINTH", "Corinth", 16, 24, 3, False)
    corinth["production"]["item_id"] = "BUILDING_GRANARY"

    scout = _empty_unit("UNIT_SCOUT_1", "UNIT_SCOUT", 14, 22, 2, True)
    settler = _empty_unit("UNIT_SETTLER_1", "UNIT_SETTLER", 16, 24, 2, True)
    spearman = _empty_unit("UNIT_SPEARMAN_1", "UNIT_SPEARMAN", 15, 23, 2, True)

    legal_commands: list[dict[str, Any]] = [
        {
            "command_id": "CMD_athens_prod_settler",
            "kind": "queue_production",
            "description": "Queue settler in Athens",
            "fixed_arguments": {"city_id": "CITY_ATHENS", "build_id": "UNIT_SETTLER"},
            "parameter_domains": {},
            "affected_ids": ["CITY_ATHENS"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_athens_prod_monument",
            "kind": "queue_production",
            "description": "Queue monument in Athens",
            "fixed_arguments": {"city_id": "CITY_ATHENS", "build_id": "BUILDING_MONUMENT"},
            "parameter_domains": {},
            "affected_ids": ["CITY_ATHENS"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_scout_move_15_24",
            "kind": "move_unit",
            "description": "Move scout",
            "fixed_arguments": {"unit_id": "UNIT_SCOUT_1", "target_x": 15, "target_y": 24},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SCOUT_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_scout_move_16_24",
            "kind": "move_unit",
            "description": "Move scout",
            "fixed_arguments": {"unit_id": "UNIT_SCOUT_1", "target_x": 16, "target_y": 24},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SCOUT_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_scout_move_14_25",
            "kind": "move_unit",
            "description": "Move scout",
            "fixed_arguments": {"unit_id": "UNIT_SCOUT_1", "target_x": 14, "target_y": 25},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SCOUT_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_settler_move_17_25",
            "kind": "move_unit",
            "description": "Move settler",
            "fixed_arguments": {"unit_id": "UNIT_SETTLER_1", "target_x": 17, "target_y": 25},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SETTLER_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_settler_move_18_26",
            "kind": "move_unit",
            "description": "Move settler",
            "fixed_arguments": {"unit_id": "UNIT_SETTLER_1", "target_x": 18, "target_y": 26},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SETTLER_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_settler_move_16_26",
            "kind": "move_unit",
            "description": "Move settler",
            "fixed_arguments": {"unit_id": "UNIT_SETTLER_1", "target_x": 16, "target_y": 26},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SETTLER_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_spearman_move_16_23",
            "kind": "move_unit",
            "description": "Move spearman",
            "fixed_arguments": {"unit_id": "UNIT_SPEARMAN_1", "target_x": 16, "target_y": 23},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SPEARMAN_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_spearman_move_15_24",
            "kind": "move_unit",
            "description": "Move spearman",
            "fixed_arguments": {"unit_id": "UNIT_SPEARMAN_1", "target_x": 15, "target_y": 24},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SPEARMAN_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_spearman_fortify",
            "kind": "unit_posture_fortify",
            "description": "Fortify spearman",
            "fixed_arguments": {"unit_id": "UNIT_SPEARMAN_1"},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SPEARMAN_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_spearman_skip",
            "kind": "unit_skip",
            "description": "Skip spearman",
            "fixed_arguments": {"unit_id": "UNIT_SPEARMAN_1"},
            "parameter_domains": {},
            "affected_ids": ["UNIT_SPEARMAN_1"],
            "runtime_status": "tested",
        },
        {
            "command_id": "CMD_research_tech_pottery",
            "kind": "set_research_tech",
            "description": "Research pottery",
            "fixed_arguments": {"tech_id": "TECH_POTTERY"},
            "parameter_domains": {},
            "affected_ids": ["TECH_POTTERY"],
            "runtime_status": "tested",
        },
    ]

    snapshot: dict[str, Any] = {
        "schema_version": "civ6ai-input/1",
        "decision": {
            "turn": 18,
            "year": -3400,
            "phase": "strategic_decision",
            "player_id": "PLAYER_0",
            "reason": "turn_start",
        },
        "personality": {
            "identity": "Alexander",
            "leader_id": "LEADER_ALEXANDER",
            "leader_name": "Alexander",
            "civilization_id": "CIVILIZATION_GREECE",
        },
        "game": {
            "era_id": "ERA_ANCIENT",
            "start_era_id": "ERA_ANCIENT",
            "game_speed_id": "GAMESPEED_STANDARD",
            "difficulty_id": "HANDICAP_PRINCE",
            "calendar_id": "CALENDAR_DEFAULT",
            "map_script": "Continents",
            "world_size_id": "WORLDSIZE_STANDARD",
            "climate_id": "CLIMATE_TEMPERATE",
            "sea_level_id": "SEALEVEL_MEDIUM",
            "map_width": 44,
            "map_height": 26,
            "wrap_x": False,
            "wrap_y": False,
            "max_turns": None,
            "options": [],
            "victory_ids": [],
            "network_multiplayer": False,
        },
        "your_empire": {
            "team_id": "TEAM_0",
            "score": 142,
            "gold": 86,
            "gold_per_turn": 12,
            "commerce": {
                "gold": {"percent": 0, "rate": 12},
                "research": {"percent": 100, "rate": 18},
                "culture": {"percent": 0, "rate": 11},
                "espionage": {"percent": 0, "rate": 0},
            },
            "costs": {
                "unit_cost": 0,
                "unit_supply": 0,
                "city_maintenance": 0,
                "civic_upkeep": 0,
                "inflation": 0,
            },
            "research": {
                "tech_id": "TECH_POTTERY",
                "progress": 4,
                "cost": 25,
                "research_per_turn": 18,
                "estimated_turns_remaining": 2,
                "queue": [],
                "known_tech_ids": [],
            },
            "civics": [],
            "religion": {
                "state_religion_id": None,
                "convertible_religion_ids": [],
                "conversion_timer": 0,
            },
            "resources": [],
            "unit_counts": {
                "total": 5,
                "workers": 0,
                "settlers": 1,
                "military": 2,
                "missionaries": 0,
                "spies": 0,
                "great_people": 0,
                "idle": 3,
                "upgradeable": 0,
            },
            "anarchy_turns": 0,
            "golden_age_turns": 0,
            "war_weariness": 0,
            "victory_progress": [],
        },
        "your_cities": [athens, corinth],
        "your_units": [scout, settler, spearman],
        "known_players": [
            {
                "player_id": "PLAYER_1",
                "team_id": "TEAM_1",
                "leader_id": "LEADER_CLEOPATRA",
                "leader_name": "Cleopatra",
                "civilization_id": "CIVILIZATION_EGYPT",
                "score": 138,
                "population": None,
                "land": None,
                "power": None,
                "known_capital_city_id": None,
                "known_religion_id": None,
                "known_civic_ids": [],
                "known_tech_ids": [],
                "relation": {
                    "met": True,
                    "at_war": False,
                    "open_borders": False,
                    "defensive_pact": False,
                    "vassal": False,
                    "attitude_id": "ATTITUDE_CAUTIOUS",
                    "attitude_value": 0,
                },
            }
        ],
        "known_other_cities": [],
        "visible_other_units": [],
        "diplomacy": {
            "relations": [],
            "active_deals": [],
            "pending_requests": [],
            "available_proposals": [],
            "legal_trade_inventory": [],
            "private_inbox": [],
        },
        "known_map": {
            "format": "plot-grid-v1",
            "visibility_mode": "player_visible",
            "plots": [],
            "areas": [],
            "frontiers": [],
            "visible_stacks": [],
            "image": {
                "attached": False,
                "format": "png-grid-v1",
                "width": 44,
                "height": 26,
                "legend": [],
                "label_ids": [],
            },
        },
        "strategic_summary": {
            "city_alerts": [],
            "economy_alerts": [],
            "military_alerts": [
                {
                    "kind": "ALERT_MILITARY",
                    "severity": "info",
                    "affected_ids": [],
                    "text": "Barbarian scout spotted east of Corinth",
                }
            ],
            "diplomacy_alerts": [],
            "resource_alerts": [],
            "ratios": [],
        },
        "history": {
            "accepted_decisions": [],
            "command_results": [],
            "public_events": [],
            "diplomacy_events": [],
            "memory_summary": "Expand to third city after Pottery; scout eastern coast.",
        },
        "advciv": {
            "default_unit_controller": "native",
            "fallback_policy": "Firaxis native AI handles unmoved units after LLM apply.",
            "recommendations": [],
        },
        "legal_commands": legal_commands,
        "civ6": {
            "yields": {"science": 18, "culture": 11, "faith": 0, "favor": 0},
            "government_id": "GOVERNMENT_CHIEFDOM",
            "research_civic": {
                "civic_id": "CIVIC_CRAFTSMANSHIP",
                "progress": 12,
                "turns_left": 4,
            },
            "city_extra": {
                "CITY_ATHENS": {"loyalty": 100},
            },
            "map": {
                "width": 44,
                "height": 26,
                "hex_layout": "odd-r",
                "coords_note": "grid x,y; Y increases south",
            },
        },
    }
    normalize_civ6_snapshot(snapshot)
    return snapshot


def write_classical_golden_snapshot(path: Path | None = None) -> Path:
    target = path or GOLDEN_SNAPSHOT_PATH
    snapshot = build_classical_golden_snapshot()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(pipeline.canonical_json(snapshot) + "\n", encoding="utf-8")
    return target


def _enrich_runtime_legal_command(command: dict[str, Any]) -> dict[str, Any]:
    enriched = copy.deepcopy(command)
    fixed = enriched.get("fixed_arguments")
    if not isinstance(fixed, dict):
        fixed = {}
        enriched["fixed_arguments"] = fixed
    if not enriched.get("description"):
        parts = [str(enriched.get("kind") or "command")]
        for key, value in sorted(fixed.items()):
            parts.append(f"{key}={value}")
        enriched["description"] = " ".join(parts)
    if "parameter_domains" not in enriched:
        enriched["parameter_domains"] = {}
    if "affected_ids" not in enriched:
        affected: list[str] = []
        unit_id = fixed.get("unit_id")
        city_id = fixed.get("city_id")
        if isinstance(unit_id, str):
            affected.append(unit_id)
        if isinstance(city_id, str):
            affected.append(city_id)
        enriched["affected_ids"] = affected
    if "runtime_status" not in enriched:
        enriched["runtime_status"] = "implemented_untested"
    return enriched


def _is_live_runtime_snapshot(raw: dict[str, Any]) -> bool:
    """True when the mod wrote real turn data — not a minimal test fixture."""
    units = raw.get("your_units")
    if isinstance(units, list) and len(units) > 0:
        return True
    cities = raw.get("your_cities")
    if isinstance(cities, list) and len(cities) > 0:
        return True
    known = raw.get("known_map")
    if isinstance(known, dict):
        plots = known.get("plots")
        if isinstance(plots, list) and len(plots) > 4:
            return True
    return False


def _merge_template_dict(target: dict[str, Any], template: dict[str, Any]) -> None:
    for key, value in template.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_template_dict(target[key], value)


def _merge_known_players(runtime: list[Any], template: list[Any]) -> list[dict[str, Any]]:
    template_by_id: dict[str, dict[str, Any]] = {}
    default_tpl: dict[str, Any] = {}
    for item in template:
        if isinstance(item, dict):
            if not default_tpl:
                default_tpl = item
            player_id = item.get("player_id")
            if isinstance(player_id, str):
                template_by_id[player_id] = item
    merged: list[dict[str, Any]] = []
    for item in runtime:
        if not isinstance(item, dict):
            continue
        player_id = item.get("player_id")
        base = copy.deepcopy(template_by_id.get(player_id, default_tpl))
        _deep_merge_from_raw(base, item)
        merged.append(base)
    return merged if merged else copy.deepcopy(template)


def _optional_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _expand_cropped_grid(
    grid: Any,
    viewport: Any,
    map_width: int | None,
    map_height: int | None,
) -> list[str] | None:
    """Re-anchor a viewport-cropped ``visibility_grid`` to full-map (0,0) rows.

    Lua crops the grid to ``known_map.viewport`` (e.g. x0=1, y0=6). The merge below
    drops that viewport, and every reader then treated row 0 as y=0, which shifted the
    revealed area on the map image by (x0, y0) tiles away from the real plots/units.
    """
    if not isinstance(grid, list) or not grid or not isinstance(viewport, dict):
        return None
    try:
        x0 = int(viewport.get("x0") or 0)
        y0 = int(viewport.get("y0") or 0)
    except (TypeError, ValueError):
        return None
    if x0 == 0 and y0 == 0:
        return None
    rows = [row if isinstance(row, str) else "" for row in grid]
    row_len = max((len(row) for row in rows), default=0)
    width = int(map_width) if map_width else x0 + row_len
    height = int(map_height) if map_height else y0 + len(rows)
    full = [["?"] * width for _ in range(height)]
    for r, row in enumerate(rows):
        wy = y0 + r
        if not 0 <= wy < height:
            continue
        for c, ch in enumerate(row):
            wx = x0 + c
            if 0 <= wx < width:
                full[wy][wx] = ch
    return ["".join(line) for line in full]


def _merge_known_map(
    runtime: dict[str, Any],
    template: dict[str, Any],
    map_width: int | None = None,
    map_height: int | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(template)
    if not isinstance(runtime, dict):
        return out
    crop_viewport = runtime.get("viewport")
    if not isinstance(crop_viewport, dict):
        image_block = runtime.get("image")
        if isinstance(image_block, dict):
            crop_viewport = image_block.get("viewport")
    tpl_plots = template.get("plots", [])
    tpl_plot: dict[str, Any] = tpl_plots[0] if tpl_plots and isinstance(tpl_plots[0], dict) else _empty_plot()
    for key, value in runtime.items():
        if key == "plots" and isinstance(value, list):
            merged_plots: list[dict[str, Any]] = []
            for plot in value:
                if not isinstance(plot, dict):
                    continue
                x = int(plot.get("x") or 0)
                y = int(plot.get("y") or 0)
                plot_id = plot.get("plot_id") if isinstance(plot.get("plot_id"), str) else f"PLOT_{x}_{y}"
                base = copy.deepcopy(tpl_plot if tpl_plots else _empty_plot(plot_id, x, y))
                _deep_merge_from_raw(base, plot)
                if base.get("plot_id") is None:
                    base["plot_id"] = plot_id
                base["x"] = x
                base["y"] = y
                merged_plots.append(base)
            out["plots"] = merged_plots
        elif key != "viewport":
            out[key] = copy.deepcopy(value)
    for grid_key in ("visibility_grid", "territory_owner_grid"):
        expanded = _expand_cropped_grid(out.get(grid_key), crop_viewport, map_width, map_height)
        if expanded is not None:
            out[grid_key] = expanded
    out.pop("viewport", None)
    image = out.get("image")
    if isinstance(image, dict):
        image.pop("viewport", None)
    return out


def _deep_merge_from_raw(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Merge live snapshot fields without letting empty Lua tables replace template shells."""
    for key, value in source.items():
        if isinstance(value, dict) and not value and isinstance(target.get(key), dict):
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge_from_raw(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _fill_civ6_schema_defaults(shell: dict[str, Any], template: dict[str, Any]) -> None:
    """Add schema-required shells without golden-game city/unit fiction."""
    for key in ("known_other_cities", "visible_other_units"):
        if key not in shell or shell[key] is None:
            shell[key] = copy.deepcopy(template.get(key, []))
    if "your_cities" not in shell:
        shell["your_cities"] = []
    if "your_units" not in shell:
        shell["your_units"] = []
    if "known_players" not in shell:
        shell["known_players"] = copy.deepcopy(template.get("known_players", []))
    if "known_map" not in shell:
        shell["known_map"] = copy.deepcopy(template.get("known_map", {}))
    if not isinstance(shell.get("diplomacy"), dict):
        shell["diplomacy"] = copy.deepcopy(template.get("diplomacy", {}))
    if not isinstance(shell.get("history"), dict):
        shell["history"] = copy.deepcopy(template.get("history", {}))
    else:
        _merge_template_dict(shell["history"], template.get("history", {}))
    if not isinstance(shell.get("advciv"), dict):
        shell["advciv"] = copy.deepcopy(template.get("advciv", {}))
    if not isinstance(shell.get("strategic_summary"), dict):
        shell["strategic_summary"] = copy.deepcopy(template.get("strategic_summary", {}))
    if not isinstance(shell.get("game"), dict):
        shell["game"] = copy.deepcopy(template.get("game", {}))
    else:
        _merge_template_dict(shell["game"], template.get("game", {}))
    if not isinstance(shell.get("personality"), dict):
        shell["personality"] = copy.deepcopy(template.get("personality", {}))
    else:
        _merge_template_dict(shell["personality"], template.get("personality", {}))
    if not isinstance(shell.get("decision"), dict):
        shell["decision"] = copy.deepcopy(template.get("decision", {}))
    else:
        _merge_template_dict(shell["decision"], template.get("decision", {}))
    if not isinstance(shell.get("your_empire"), dict):
        shell["your_empire"] = copy.deepcopy(template.get("your_empire", {}))
    else:
        _merge_template_dict(shell["your_empire"], template.get("your_empire", {}))
    if not isinstance(shell.get("civ6"), dict):
        shell["civ6"] = copy.deepcopy(template.get("civ6", {}))
    else:
        _merge_template_dict(shell["civ6"], template.get("civ6", {}))


def upgrade_runtime_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    """Merge a minimal mod-written snapshot into a valid civ6 shell for the sidecar."""
    raw = coerce_lua_empty_arrays(raw)
    template = build_classical_golden_snapshot()
    if _is_live_runtime_snapshot(raw):
        shell = copy.deepcopy(raw)
        _fill_civ6_schema_defaults(shell, template)
        if isinstance(raw.get("history"), dict):
            _deep_merge_from_raw(shell["history"], raw["history"])
        if isinstance(raw.get("your_empire"), dict):
            _deep_merge_from_raw(shell["your_empire"], raw["your_empire"])
        if isinstance(raw.get("game"), dict):
            _deep_merge_from_raw(shell["game"], raw["game"])
        if isinstance(raw.get("personality"), dict):
            _deep_merge_from_raw(shell["personality"], raw["personality"])
        if isinstance(raw.get("civ6"), dict):
            _deep_merge_from_raw(shell["civ6"], raw["civ6"])
        if isinstance(raw.get("known_map"), dict):
            raw_map = raw.get("civ6", {}).get("map") if isinstance(raw.get("civ6"), dict) else None
            raw_game = raw.get("game") if isinstance(raw.get("game"), dict) else {}
            raw_map = raw_map if isinstance(raw_map, dict) else {}
            shell["known_map"] = _merge_known_map(
                raw["known_map"],
                template.get("known_map", {}),
                map_width=_optional_int(raw_map.get("width") or raw_game.get("map_width")),
                map_height=_optional_int(raw_map.get("height") or raw_game.get("map_height")),
            )
        if isinstance(raw.get("your_cities"), list):
            shell["your_cities"] = [
                _merge_live_city(city) for city in raw["your_cities"] if isinstance(city, dict)
            ]
        if isinstance(raw.get("your_units"), list):
            shell["your_units"] = [
                _merge_live_unit(unit) for unit in raw["your_units"] if isinstance(unit, dict)
            ]
        if isinstance(raw.get("known_players"), list):
            shell["known_players"] = _merge_known_players(raw["known_players"], template.get("known_players", []))
        if isinstance(raw.get("strategic_summary"), dict):
            shell["strategic_summary"] = copy.deepcopy(raw["strategic_summary"])
        if "legal_commands" in raw:
            shell["legal_commands"] = [
                _enrich_runtime_legal_command(command)
                for command in raw["legal_commands"]
                if isinstance(command, dict)
            ]
        civ6_block = shell.get("civ6", {})
        if isinstance(civ6_block, dict) and isinstance(civ6_block.get("map"), dict):
            civ6_map = civ6_block["map"]
            game_block = shell.setdefault("game", {})
            if isinstance(game_block, dict):
                if civ6_map.get("width") is not None:
                    game_block["map_width"] = int(civ6_map["width"])
                if civ6_map.get("height") is not None:
                    game_block["map_height"] = int(civ6_map["height"])
        _fill_civ6_schema_defaults(shell, template)
        shell = coerce_lua_empty_arrays(shell)
        normalize_civ6_snapshot(shell)
        return shell

    shell = template
    for key in ("decision", "personality", "your_empire", "civ6"):
        block = raw.get(key)
        if isinstance(block, dict):
            shell[key].update(block)
    if isinstance(raw.get("game"), dict):
        shell["game"].update(raw["game"])
    civ6_block = shell.get("civ6", {})
    if isinstance(civ6_block, dict) and isinstance(civ6_block.get("map"), dict):
        civ6_map = civ6_block["map"]
        game_block = shell.setdefault("game", {})
        if isinstance(game_block, dict):
            if civ6_map.get("width") is not None:
                game_block["map_width"] = int(civ6_map["width"])
            if civ6_map.get("height") is not None:
                game_block["map_height"] = int(civ6_map["height"])
    if isinstance(raw.get("known_map"), dict):
        shell["known_map"] = copy.deepcopy(raw["known_map"])
    if isinstance(raw.get("your_cities"), list):
        shell["your_cities"] = [
            _merge_live_city(city) for city in raw["your_cities"] if isinstance(city, dict)
        ]
    if isinstance(raw.get("known_players"), list):
        shell["known_players"] = copy.deepcopy(raw["known_players"])
    if isinstance(raw.get("strategic_summary"), dict):
        shell["strategic_summary"] = copy.deepcopy(raw["strategic_summary"])
    if isinstance(raw.get("history"), dict):
        shell["history"].update(raw["history"])
    if "legal_commands" in raw:
        shell["legal_commands"] = [
            _enrich_runtime_legal_command(command)
            for command in raw["legal_commands"]
            if isinstance(command, dict)
        ]
    if isinstance(raw.get("your_units"), list):
        shell["your_units"] = [
            _merge_live_unit(unit) for unit in raw["your_units"] if isinstance(unit, dict)
        ]
    normalize_civ6_snapshot(shell)
    return shell
