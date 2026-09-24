"""Civ V snapshot adapter — bridge between game snapshots and civ5_wire / pipeline_v2."""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import RefResolver

from sidecar import pipeline_v2 as pipeline

ROOT = Path(__file__).resolve().parents[1]
CIV5_SCHEMA_PATH = ROOT / "schemas" / "decision-input-civ5.json"
CAPABILITIES_PATH = ROOT / "config" / "civ5-command-capabilities.json"
GOLDEN_SNAPSHOT_PATH = ROOT / "fixtures" / "civ5" / "snapshot-turn-classical-golden.json"

_CIV5_INPUT_VALIDATOR: Draft202012Validator | None = None

_COORDS_RE = re.compile(r"^\s*\(?\s*(-?\d+)\s*,\s*(-?\d+)\s*\)?\s*$")

_STANCE_KINDS = {
    "fortify": "unit_posture_fortify",
    "heal": "unit_posture_heal",
    "sleep": "unit_posture_sleep",
    "skip": "unit_skip",
}

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
    "public_events",
    "private_inbox",
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
    "settle_sites",
    "look",
})


def _civ5_validator() -> Draft202012Validator:
    global _CIV5_INPUT_VALIDATOR
    if _CIV5_INPUT_VALIDATOR is None:
        schema_store = {
            CIV5_SCHEMA_PATH.name: json.loads(CIV5_SCHEMA_PATH.read_text(encoding="utf-8")),
            "decision-input-v2.json": json.loads((ROOT / "schemas" / "decision-input-v2.json").read_text(encoding="utf-8")),
        }
        resolver = RefResolver(
            base_uri=CIV5_SCHEMA_PATH.as_uri(),
            referrer=schema_store[CIV5_SCHEMA_PATH.name],
            store=schema_store,
        )
        _CIV5_INPUT_VALIDATOR = Draft202012Validator(schema_store[CIV5_SCHEMA_PATH.name], resolver=resolver)
    return _CIV5_INPUT_VALIDATOR


def _schema_errors(snapshot: dict[str, Any]) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in error.path)}: {error.message}"
        for error in _civ5_validator().iter_errors(snapshot)
    ]


def is_civ5_snapshot(snapshot: dict[str, Any]) -> bool:
    version = snapshot.get("schema_version")
    return isinstance(version, str) and version.startswith("civ5ai-input/")


def validate_civ5_snapshot(snapshot: dict[str, Any]) -> None:
    errors = _schema_errors(snapshot)
    if errors:
        raise pipeline.BoundaryError("civ5_snapshot_schema", "; ".join(errors[:8]))
    ids: set[str] = set()
    for command in snapshot.get("legal_commands", []):
        command_id = command.get("command_id")
        if not isinstance(command_id, str):
            continue
        if command_id in ids:
            raise pipeline.BoundaryError("duplicate_legal_id", command_id)
        ids.add(command_id)


def _lua_table_to_array(value: dict[str, Any]) -> list[Any]:
    if not value:
        return []
    if all(str(key).isdigit() for key in value):
        ordered = sorted(value.keys(), key=lambda key: int(str(key)))
        return [coerce_lua_empty_arrays(value[key]) for key in ordered]
    return [coerce_lua_empty_arrays(value)]


def coerce_lua_empty_arrays(node: Any) -> Any:
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
    if isinstance(node, list):
        return [_coerce_schema_integers(item) for item in node]
    if isinstance(node, dict):
        return {key: _coerce_schema_integers(value) for key, value in node.items()}
    coerced = _as_schema_int(node)
    if coerced is not None and not isinstance(node, bool) and isinstance(node, (int, float)):
        return coerced
    return node


def _normalize_empire_civics(snapshot: dict[str, Any]) -> None:
    empire = snapshot.get("your_empire")
    if not isinstance(empire, dict):
        return
    civics = empire.get("civics")
    if not isinstance(civics, list):
        return
    normalized: list[dict[str, str]] = []
    for item in civics:
        if isinstance(item, str) and item.strip():
            normalized.append({"key": "POLICY", "id": item.strip()})
            continue
        if isinstance(item, dict):
            civic_id = item.get("id")
            if isinstance(civic_id, str) and civic_id.strip():
                key = item.get("key")
                normalized.append({
                    "key": key.strip() if isinstance(key, str) and key.strip() else "POLICY",
                    "id": civic_id.strip(),
                })
    empire["civics"] = normalized


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
    return {
        "turn": turn,
        "kind": kind,
        "summary": summary,
        "affected_ids": affected_ids,
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


def _normalize_wire_shapes(snapshot: dict[str, Any]) -> None:
    history = snapshot.get("history")
    if isinstance(history, dict):
        _normalize_history_wire(history)
    decision = snapshot.get("decision")
    if isinstance(decision, dict):
        _normalize_decision_wire(decision)


def normalize_civ5_snapshot(snapshot: dict[str, Any]) -> None:
    coerced = coerce_lua_empty_arrays(snapshot)
    if coerced is not snapshot:
        snapshot.clear()
        snapshot.update(coerced)
    _normalize_empire_numbers(snapshot)
    _normalize_wire_shapes(snapshot)
    _normalize_empire_civics(snapshot)
    snapshot["schema_version"] = "civ5ai-input/1"
    pipeline.normalize_personality(snapshot)
    civ5 = snapshot.get("civ5")
    if not isinstance(civ5, dict):
        snapshot["civ5"] = {}
    validate_civ5_snapshot(snapshot)


def normalize_civ5_wire_flat(flat: dict[str, Any]) -> dict[str, Any]:
    """Map Civ5 city.production wire keys onto pipeline changeProduction resolver."""
    if not isinstance(flat, dict):
        return flat
    out: dict[str, Any] = {}
    for key, value in flat.items():
        if isinstance(key, str) and ".production" in key and not key.endswith(".changeProduction"):
            head, _ = key.rsplit(".production", 1)
            out[f"{head}.changeProduction"] = value
        else:
            out[key] = value
    return out


def load_capabilities() -> dict[str, Any]:
    return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))


def load_v1_capability_kinds() -> set[str]:
    doc = load_capabilities()
    return {
        str(row["kind"])
        for row in doc.get("capabilities", [])
        if isinstance(row, dict) and row.get("tier") == "v1" and row.get("kind")
    }


def load_deferred_capability_kinds() -> set[str]:
    doc = load_capabilities()
    return {
        str(row["kind"])
        for row in doc.get("deferred_capabilities", [])
        if isinstance(row, dict) and row.get("kind")
    }


def load_golden_snapshot(path: Path | None = None) -> dict[str, Any]:
    target = path or GOLDEN_SNAPSHOT_PATH
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise pipeline.BoundaryError("golden_snapshot", "Expected object")
    normalize_civ5_snapshot(payload)
    return payload


def _empty_amounts() -> dict[str, int | None]:
    return {"current": 0, "maximum": 0, "change_per_turn": 0}


def _empty_commerce_item() -> dict[str, int]:
    return {"percent": 0, "rate": 0}


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


def _classical_known_map() -> dict[str, Any]:
    """Synthetic revealed terrain around Athens/Corinth for offline map render tests."""
    from sidecar import map_render

    x0, y0 = 13, 21
    vw, vh = 6, 6
    grid_chars = [
        "....~~",
        ".####.",
        ".#..#.",
        "..##..",
        "....~~",
        "~~~~~~",
    ]
    plots: list[dict[str, Any]] = []
    visibility_grid: list[str] = []
    for vy, row_chars in enumerate(grid_chars):
        row = ""
        for vx, cell in enumerate(row_chars):
            wx, wy = x0 + vx, y0 + vy
            if cell == "?":
                row += "?"
                continue
            row += cell
            plot = map_render._plot_from_grid_cell(wx, wy, cell, knowledge="visible")
            plot["last_seen_turn"] = 18
            if cell == "#":
                plot["hills"] = True
            if cell == "^":
                plot["peak"] = True
            if wx == 15 and wy == 23:
                plot["revealed_owner_id"] = "PLAYER_0"
            if wx == 16 and wy == 24:
                plot["revealed_owner_id"] = "PLAYER_0"
            if wx == 14 and wy == 22 and cell == ".":
                plot["resource_id"] = "RESOURCE_DEER"
            if wx == 13 and wy == 21:
                plot["improvement_id"] = "IMPROVEMENT_GOODY_HUT"
            plots.append(plot)
        visibility_grid.append(row)
    viewport = {"x0": x0, "y0": y0, "width": vw, "height": vh}
    return {
        "format": "plot-grid-v1",
        "visibility_mode": "player_visible",
        "plots": plots,
        "areas": [],
        "frontiers": [],
        "visible_stacks": [],
        "visibility_grid": visibility_grid,
        "viewport": viewport,
        "image": {
            "attached": False,
            "format": "png-grid-v1",
            "width": 44,
            "height": 26,
            "legend": [],
            "label_ids": [],
        },
    }


def build_classical_golden_snapshot() -> dict[str, Any]:
    athens = _empty_city("CITY_ATHENS", "Athens", 15, 23, 4, True)
    athens["production"]["item_id"] = "UNIT_SPEARMAN"
    athens["production"]["cost"] = 56
    athens["production"]["progress"] = 16
    athens["production"]["production_per_turn"] = 8
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
        "schema_version": "civ5ai-input/1",
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
                "city_maintenance": 0,
                "civic_upkeep": 0,
                "inflation": 0,
                "unit_supply": 0,
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
        "known_map": _classical_known_map(),
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
            "default_unit_controller": "skip_leftover",
            "fallback_policy": "After apply, leftover units waiting for orders are skipped.",
            "recommendations": [],
        },
        "legal_commands": legal_commands,
        "civ5": {
            "yields": {"gold": 86, "science": 18, "culture": 11, "faith": 0, "happiness": 10},
            "research_tech": "TECH_POTTERY",
            "map": {
                "width": 44,
                "height": 26,
                "hex_layout": "odd-r",
                "coords_note": "grid x,y; Y increases south",
            },
            "settle_sites": [
                {
                    "unit_id": "UNIT_SETTLER_1",
                    "here": {
                        "x": 16,
                        "y": 24,
                        "distance": 0,
                        "coast": False,
                        "lake": False,
                        "river": False,
                        "hills": False,
                        "can_found": True,
                        "resources": [],
                        "score": 0,
                    },
                    "look": [
                        {
                            "x": 14,
                            "y": 22,
                            "distance": 2,
                            "coast": True,
                            "lake": False,
                            "river": True,
                            "hills": False,
                            "ruins": True,
                            "can_found": True,
                            "resources": ["RESOURCE_DEER"],
                            "score": 8,
                        }
                    ],
                }
            ],
        },
    }
    normalize_civ5_snapshot(snapshot)
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


def _deep_merge_from_raw(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and not value and isinstance(target.get(key), dict):
            continue
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge_from_raw(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _fill_civ5_schema_defaults(shell: dict[str, Any], template: dict[str, Any]) -> None:
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
    if not isinstance(shell.get("civ5"), dict):
        shell["civ5"] = copy.deepcopy(template.get("civ5", {}))
    else:
        _merge_template_dict(shell["civ5"], template.get("civ5", {}))


def upgrade_runtime_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    raw = coerce_lua_empty_arrays(raw)
    template = build_classical_golden_snapshot()
    if _is_live_runtime_snapshot(raw):
        shell = copy.deepcopy(raw)
        _fill_civ5_schema_defaults(shell, template)
        if isinstance(raw.get("history"), dict):
            _deep_merge_from_raw(shell["history"], raw["history"])
        if isinstance(raw.get("your_empire"), dict):
            _deep_merge_from_raw(shell["your_empire"], raw["your_empire"])
        if isinstance(raw.get("game"), dict):
            _deep_merge_from_raw(shell["game"], raw["game"])
        if isinstance(raw.get("personality"), dict):
            _deep_merge_from_raw(shell["personality"], raw["personality"])
        if isinstance(raw.get("civ5"), dict):
            _deep_merge_from_raw(shell["civ5"], raw["civ5"])
        if "legal_commands" in raw:
            shell["legal_commands"] = [
                _enrich_runtime_legal_command(command)
                for command in raw["legal_commands"]
                if isinstance(command, dict)
            ]
        civ5_block = shell.get("civ5", {})
        if isinstance(civ5_block, dict) and isinstance(civ5_block.get("map"), dict):
            civ5_map = civ5_block["map"]
            game_block = shell.setdefault("game", {})
            if isinstance(game_block, dict):
                if civ5_map.get("width") is not None:
                    game_block["map_width"] = int(civ5_map["width"])
                if civ5_map.get("height") is not None:
                    game_block["map_height"] = int(civ5_map["height"])
        _fill_civ5_schema_defaults(shell, template)
        shell = coerce_lua_empty_arrays(shell)
        normalize_civ5_snapshot(shell)
        return shell

    shell = copy.deepcopy(template)
    for key in ("decision", "personality", "your_empire", "civ5"):
        block = raw.get(key)
        if isinstance(block, dict):
            shell[key].update(block)
    if isinstance(raw.get("game"), dict):
        shell["game"].update(raw["game"])
    if isinstance(raw.get("history"), dict):
        shell["history"].update(raw["history"])
    if "legal_commands" in raw:
        shell["legal_commands"] = [
            _enrich_runtime_legal_command(command)
            for command in raw["legal_commands"]
            if isinstance(command, dict)
        ]
    normalize_civ5_snapshot(shell)
    return shell


def _parse_wire_coords(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = _COORDS_RE.match(value.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _make_open_command(
    kind: str,
    command_id: str,
    fixed_arguments: dict[str, Any],
    affected_ids: list[str],
) -> dict[str, Any]:
    return {
        "command_id": command_id,
        "kind": kind,
        "description": kind.replace("_", " "),
        "fixed_arguments": fixed_arguments,
        "parameter_domains": {},
        "affected_ids": affected_ids,
        "runtime_status": "implemented_untested",
    }


def inject_open_unit_commands(snapshot: dict[str, Any], parsed_wire: dict[str, Any]) -> None:
    """Inject move/stance/found commands from open wire coordinates before pipeline validation."""
    if not isinstance(parsed_wire, dict):
        return
    units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    wire_ids = pipeline._build_unit_wire_id_map(units)
    unit_id_by_wire = {wire: unit_id for unit_id, wire in wire_ids.items()}
    legal = snapshot.setdefault("legal_commands", [])
    if not isinstance(legal, list):
        legal = []
        snapshot["legal_commands"] = legal
    existing_ids = {
        item.get("command_id")
        for item in legal
        if isinstance(item, dict) and isinstance(item.get("command_id"), str)
    }

    def _append(command: dict[str, Any]) -> None:
        cmd_id = command.get("command_id")
        if not isinstance(cmd_id, str) or cmd_id in existing_ids:
            return
        legal.append(command)
        existing_ids.add(cmd_id)

    for key, value in parsed_wire.items():
        if not isinstance(key, str) or key.startswith(("cmd.", "chat.", "thought", "decision", "legal.")):
            continue
        if "." not in key:
            continue
        head, remainder = key.split(".", 1)
        unit_id = unit_id_by_wire.get(head)
        if not unit_id:
            continue
        if remainder == "moveTo":
            coords = _parse_wire_coords(value)
            if coords is None:
                continue
            x, y = coords
            cmd_id = f"CMD_move_{unit_id}_{x}_{y}"
            _append(_make_open_command(
                "move_unit",
                cmd_id,
                {"unit_id": unit_id, "target_x": x, "target_y": y},
                [unit_id],
            ))
        elif remainder == "attackTo":
            coords = _parse_wire_coords(value)
            if coords is None:
                continue
            x, y = coords
            cmd_id = f"CMD_attack_{unit_id}_{x}_{y}"
            _append(_make_open_command(
                "attack_target",
                cmd_id,
                {"unit_id": unit_id, "target_x": x, "target_y": y},
                [unit_id],
            ))
        elif remainder == "rangedAttack":
            coords = _parse_wire_coords(value)
            if coords is None:
                continue
            x, y = coords
            cmd_id = f"CMD_range_{unit_id}_{x}_{y}"
            _append(_make_open_command(
                "range_attack",
                cmd_id,
                {"unit_id": unit_id, "target_x": x, "target_y": y},
                [unit_id],
            ))
        elif remainder == "rebaseTo":
            coords = _parse_wire_coords(value)
            if coords is None:
                continue
            x, y = coords
            cmd_id = f"CMD_rebase_{unit_id}_{x}_{y}"
            _append(_make_open_command(
                "rebase",
                cmd_id,
                {"unit_id": unit_id, "target_x": x, "target_y": y},
                [unit_id],
            ))
        elif remainder == "paradropTo":
            coords = _parse_wire_coords(value)
            if coords is None:
                continue
            x, y = coords
            cmd_id = f"CMD_paradrop_{unit_id}_{x}_{y}"
            _append(_make_open_command(
                "paradrop",
                cmd_id,
                {"unit_id": unit_id, "target_x": x, "target_y": y},
                [unit_id],
            ))
        elif remainder == "nukeAt":
            coords = _parse_wire_coords(value)
            if coords is None:
                continue
            x, y = coords
            cmd_id = f"CMD_nuke_{unit_id}_{x}_{y}"
            _append(_make_open_command(
                "nuke",
                cmd_id,
                {"unit_id": unit_id, "target_x": x, "target_y": y},
                [unit_id],
            ))
        elif remainder == "foundCity" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_found_{unit_id}"
            _append(_make_open_command(
                "found_city",
                cmd_id,
                {"unit_id": unit_id},
                [unit_id],
            ))
        elif remainder == "improve":
            build_id = str(value).strip()
            if not build_id.upper().startswith("BUILD_"):
                continue
            cmd_id = f"CMD_improve_{unit_id}_{build_id}"
            _append(_make_open_command(
                "improve_tile",
                cmd_id,
                {"unit_id": unit_id, "build_id": build_id},
                [unit_id],
            ))
        elif remainder == "automate":
            label = str(value).strip().lower()
            automate_id = {
                "build": "AUTOMATE_BUILD",
                "explore": "AUTOMATE_EXPLORE",
            }.get(label)
            if automate_id is None and label.upper().startswith("AUTOMATE_"):
                automate_id = label.upper()
            if not automate_id:
                continue
            cmd_id = f"CMD_automate_{unit_id}_{automate_id}"
            _append(_make_open_command(
                "automate_unit",
                cmd_id,
                {"unit_id": unit_id, "automate_id": automate_id},
                [unit_id],
            ))
        elif remainder == "discover" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_discover_{unit_id}"
            _append(_make_open_command("discover_tech", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "hurry" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_hurry_{unit_id}"
            _append(_make_open_command("hurry_production", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "trade" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_trade_{unit_id}"
            _append(_make_open_command("trade_mission", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "goldenAge" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_golden_{unit_id}"
            _append(_make_open_command("start_golden_age", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "greatWork" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_greatwork_{unit_id}"
            _append(_make_open_command("create_great_work", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "spread" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_spread_{unit_id}"
            _append(_make_open_command("spread_religion", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "removeHeresy" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_heresy_{unit_id}"
            _append(_make_open_command("remove_heresy", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "pillage" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_pillage_{unit_id}"
            _append(_make_open_command("pillage", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "upgrade":
            unit_type_id = str(value).strip()
            if not unit_type_id.upper().startswith("UNIT_"):
                continue
            cmd_id = f"CMD_upgrade_{unit_id}_{unit_type_id}"
            _append(_make_open_command(
                "upgrade_unit",
                cmd_id,
                {"unit_id": unit_id, "unit_type_id": unit_type_id},
                [unit_id, unit_type_id],
            ))
        elif remainder == "intercept" and str(value).strip().lower() == "apply":
            cmd_id = f"CMD_intercept_{unit_id}"
            _append(_make_open_command("air_patrol", cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "stance":
            kind = _STANCE_KINDS.get(str(value).strip().lower())
            if kind is None:
                continue
            cmd_id = f"CMD_{kind}_{unit_id}"
            _append(_make_open_command(kind, cmd_id, {"unit_id": unit_id}, [unit_id]))
        elif remainder == "promote":
            promo_id = str(value).strip()
            if not promo_id.upper().startswith("PROMOTION_"):
                continue
            cmd_id = f"CMD_promote_{unit_id}_{promo_id}"
            _append(_make_open_command(
                "promote_unit",
                cmd_id,
                {"unit_id": unit_id, "promotion_id": promo_id},
                [unit_id, promo_id],
            ))


_PRODUCTION_PREFIXES = ("UNIT_", "BUILDING_", "PROJECT_", "PROCESS_")


def inject_city_production_commands(snapshot: dict[str, Any], parsed_wire: dict[str, Any]) -> None:
    """Inject queue_production from cityName.production / changeProduction before validation."""
    if not isinstance(parsed_wire, dict):
        return
    city_id_by_name: dict[str, str] = {}
    for city in snapshot.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        city_id = city.get("city_id")
        if isinstance(city_id, str) and city_id:
            city_id_by_name[pipeline._city_prompt_name(city)] = city_id
    legal = snapshot.setdefault("legal_commands", [])
    if not isinstance(legal, list):
        legal = []
        snapshot["legal_commands"] = legal
    existing_ids = {
        item.get("command_id")
        for item in legal
        if isinstance(item, dict) and isinstance(item.get("command_id"), str)
    }

    def _append(command: dict[str, Any]) -> None:
        cmd_id = command.get("command_id")
        if not isinstance(cmd_id, str) or cmd_id in existing_ids:
            return
        legal.append(command)
        existing_ids.add(cmd_id)

    for key, value in parsed_wire.items():
        if not isinstance(key, str) or "." not in key:
            continue
        if key.startswith(("cmd.", "chat.", "thought", "decision", "legal.")):
            continue
        head, remainder = key.split(".", 1)
        if remainder not in ("production", "changeProduction"):
            continue
        city_id = city_id_by_name.get(head)
        if not city_id:
            continue
        build_id = str(value).strip()
        if not build_id.startswith(_PRODUCTION_PREFIXES):
            continue
        cmd_id = f"CMD_prod_{city_id}_{build_id}"
        _append(_make_open_command(
            "queue_production",
            cmd_id,
            {"city_id": city_id, "build_id": build_id},
            [city_id],
        ))
