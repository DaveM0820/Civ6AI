"""Strict host boundary for Civ IV strategic decisions.

The game owns state and legality.  The model sees a filtered snapshot and may
only select command IDs minted by the host.  This module never repairs model
output and never lets an adapter exception escape into Civ IV.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import base64
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
INPUT_SCHEMA_PATH = ROOT / "schemas" / "decision-input-v2.json"
OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "decision-output-v2.json"
CAPABILITIES_PATH = ROOT / "config" / "command-capabilities-v2.json"
MAX_RESPONSE_BYTES = 256_000
RESPONSES_URL = "https://api.openai.com/v1/responses"
RESPONSES_MODEL = "gpt-5.6-luna"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_MODEL_DEFAULT = "gemini-3.1-flash-lite"
TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
RATE_LIMIT_HTTP_CODES = frozenset({429})
MAP_IMAGE_CADENCE_TURNS = 1
THOUGHT_MEMORY_RECENT_TURNS = 5
THOUGHT_MEMORY_MILESTONE_INTERVAL = 10
THOUGHT_MAX_CHARS_DEFAULT = 8000
WIRE_COMPACT_UNITS_THRESHOLD = 6
WIRE_COMPACT_CITIES_THRESHOLD = 10
ADVCIV_FALLBACK_POLICY = (
    "After you give your commands, AdvCiv (the base AI mod) runs movement, production, "
    "and improvements for anything you did not override."
)
UNITS_NATIVE_CONTROL_HINT = (
    "After you give your commands, AdvCiv (the base AI mod) handles movement, improvements, "
    "and production for units you did not override via LEGAL COMMANDS."
)
GEMINI_MAX_OUTPUT_TOKENS_DEFAULT = 4096
WIRE_MAX_UNIT_DETAIL_DEFAULT = 48
WIRE_SUPPRESSED_CITY_KINDS = frozenset({
    "change_worked_plot",
    "clear_queue",
    "set_citizen_automation",
    "set_production_automation",
    "clear_rally_point",
    "change_specialist",
})
COMMERCE_WIRE_NAMES = {
    "COMMERCE_GOLD": "gold",
    "COMMERCE_RESEARCH": "research",
    "COMMERCE_CULTURE": "culture",
    "COMMERCE_ESPIONAGE": "espionage",
}
EXPANSION_WIRE_NAMES = {
    "PRIORITY_SETTLE": "settle",
    "PRIORITY_BALANCED": "balanced",
    "PRIORITY_DEFEND": "defend",
}


def compact_legal_wire_enabled() -> bool:
    raw = os.environ.get("CIV4AI_COMPACT_LEGAL_WIRE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def compact_situation_wire_enabled() -> bool:
    raw = os.environ.get("CIV4AI_COMPACT_SITUATION_WIRE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def wire_use_compact_detail(context: dict[str, Any]) -> bool:
    """Trim unit/city detail when the empire is large enough to bloat the prompt."""
    if not compact_situation_wire_enabled():
        return False
    units = [unit for unit in context.get("your_units", []) if isinstance(unit, dict)]
    cities = [city for city in context.get("your_cities", []) if isinstance(city, dict)]
    return (
        len(units) >= WIRE_COMPACT_UNITS_THRESHOLD
        or len(cities) >= WIRE_COMPACT_CITIES_THRESHOLD
    )


class BoundaryError(ValueError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def strip_empty_fields(value: Any) -> Any:
    """Drop empty strings, lists, and dicts from model context to save tokens."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            stripped = strip_empty_fields(item)
            if stripped is None:
                continue
            if stripped == "" or stripped == [] or stripped == {}:
                continue
            cleaned[key] = stripped
        return cleaned
    if isinstance(value, list):
        items = [strip_empty_fields(item) for item in value]
        return [item for item in items
                if item is not None and item != "" and item != {} and item != []]
    return value


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _load_schema(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        result = json.load(stream)
    Draft202012Validator.check_schema(result)
    return result


INPUT_SCHEMA = _load_schema(INPUT_SCHEMA_PATH)
OUTPUT_SCHEMA = _load_schema(OUTPUT_SCHEMA_PATH)
INPUT_VALIDATOR = Draft202012Validator(INPUT_SCHEMA)
OUTPUT_VALIDATOR = Draft202012Validator(OUTPUT_SCHEMA)
_CAPABILITIES = json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))["capabilities"]
RUNTIME_BY_KIND = {item["kind"]: item.get("runtime", "implemented_untested") for item in _CAPABILITIES}
RISK_BY_KIND = {item["kind"]: item.get("risk") for item in _CAPABILITIES if item.get("risk")}
MODEL_DEADLINE_SECONDS = 90
CHAT_MAX_MESSAGES_DEFAULT = 3
CHAT_MIN_MESSAGES_DEFAULT = 1
CHAT_HISTORY_MAX_DEFAULT = 12
PLAYER_OPINION_MAX_CHARS_DEFAULT = 480
PLAYER_HISTORY_MAX_CHARS_DEFAULT = 2000


def _empty_thought_memory(session_key: str) -> dict[str, Any]:
    return {
        "session_key": session_key,
        "thoughts": [],
        "player_opinions": {},
        "player_histories": {},
    }


def chat_max_messages() -> int:
    raw = os.environ.get("CIV4AI_CHAT_MAX_MESSAGES", "").strip()
    if not raw:
        return CHAT_MAX_MESSAGES_DEFAULT
    try:
        return max(1, min(12, int(raw)))
    except ValueError:
        return CHAT_MAX_MESSAGES_DEFAULT


def chat_history_max_messages() -> int:
    raw = os.environ.get("CIV4AI_CHAT_HISTORY_MAX", "").strip()
    if not raw:
        return CHAT_HISTORY_MAX_DEFAULT
    try:
        return max(4, min(48, int(raw)))
    except ValueError:
        return CHAT_HISTORY_MAX_DEFAULT


def player_history_max_chars() -> int:
    raw = os.environ.get("CIV4AI_PLAYER_HISTORY_MAX_CHARS", "").strip()
    if not raw:
        return PLAYER_HISTORY_MAX_CHARS_DEFAULT
    try:
        return max(200, min(4000, int(raw)))
    except ValueError:
        return PLAYER_HISTORY_MAX_CHARS_DEFAULT


def player_opinion_max_chars() -> int:
    raw = os.environ.get("CIV4AI_PLAYER_OPINION_MAX_CHARS", "").strip()
    if not raw:
        return PLAYER_OPINION_MAX_CHARS_DEFAULT
    try:
        return max(80, min(1200, int(raw)))
    except ValueError:
        return PLAYER_OPINION_MAX_CHARS_DEFAULT


def _recent_history_events(events: list[Any], max_items: int) -> list[dict[str, Any]]:
    rows = [event for event in events if isinstance(event, dict)]
    if len(rows) <= max_items:
        return rows
    return rows[-max_items:]


def _opinion_rival_player_ids(snapshot: dict[str, Any]) -> set[str]:
    """Rivals eligible for opinion lines: met civs plus lobby/chat speakers before first meet."""
    self_id = str(snapshot.get("decision", {}).get("player_id", ""))
    ids: set[str] = set()
    for item in snapshot.get("known_players", []):
        if isinstance(item, dict) and item.get("player_id"):
            ids.add(str(item["player_id"]))
    history = snapshot.get("history", {})
    if isinstance(history, dict):
        for event in history.get("public_events", []):
            if not isinstance(event, dict):
                continue
            for affected_id in event.get("affected_ids", []):
                if isinstance(affected_id, str) and affected_id.startswith("PLAYER_"):
                    ids.add(affected_id)
    diplomacy = snapshot.get("diplomacy", {})
    if isinstance(diplomacy, dict):
        for message in diplomacy.get("private_inbox", []):
            if not isinstance(message, dict):
                continue
            from_id = message.get("from_player_id")
            if isinstance(from_id, str) and from_id.startswith("PLAYER_"):
                ids.add(from_id)
    ids.discard(self_id)
    return ids


def inject_lobby_roster(snapshot: dict[str, Any], journal_parent: Path, game_uuid: str) -> None:
    """Add lobby seats from sidecar personality files so leader names resolve before first meet."""
    roster_dir = journal_parent / "sidecar-personalities"
    if not roster_dir.is_dir():
        return
    self_id = str(snapshot.get("decision", {}).get("player_id", ""))
    known = {
        str(item.get("player_id"))
        for item in snapshot.get("known_players", [])
        if isinstance(item, dict) and item.get("player_id")
    }
    prefix = f"ai_{game_uuid}_player_"
    for path in roster_dir.glob(f"{prefix}*_personality.json"):
        match = re.search(r"_player_(\d+)_personality\.json$", path.name)
        if not match:
            continue
        player_id = f"PLAYER_{int(match.group(1))}"
        if player_id == self_id or player_id in known:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        snapshot.setdefault("known_players", []).append({
            "player_id": player_id,
            "team_id": f"TEAM_{match.group(1)}",
            "leader_id": str(data.get("leader_id", "UNKNOWN_LEADER")),
            "leader_name": str(data.get("leader_name", "")),
            "civilization_id": str(data.get("civilization_id", "UNKNOWN_CIVILIZATION")),
            "relation": {
                "met": False,
                "at_war": False,
                "open_borders": False,
                "defensive_pact": False,
                "vassal": False,
                "attitude_id": "ATTITUDE_CAUTIOUS",
                "attitude_value": 0,
            },
        })
        known.add(player_id)


def _player_leader_name_map(snapshot: dict[str, Any]) -> dict[str, str]:
    self_id = str(snapshot.get("decision", {}).get("player_id", ""))
    names: dict[str, str] = {}
    for rival in snapshot.get("known_players", []):
        if not isinstance(rival, dict) or not rival.get("player_id"):
            continue
        player_id = str(rival["player_id"])
        if player_id == self_id:
            continue
        names[player_id] = _rival_leader_name(rival)
    return names


def _substitute_player_ids_in_text(text: str, snapshot: dict[str, Any]) -> str:
    if not text or "PLAYER_" not in text:
        return text
    names = _player_leader_name_map(snapshot)
    if not names:
        return text

    def repl(match: re.Match[str]) -> str:
        return names.get(match.group(0), match.group(0))

    return re.sub(r"PLAYER_\d+", repl, text)


def _player_note_wire_key(snapshot: dict[str, Any], player_id: str, prefix: str) -> str:
    name = _player_chat_name(snapshot, player_id)
    if name == player_id:
        return f"{prefix}.{player_id}"
    return f"{prefix}.{name}"


def _opinion_wire_key(snapshot: dict[str, Any], player_id: str) -> str:
    return _player_note_wire_key(snapshot, player_id, "opinion")


def _history_wire_key(snapshot: dict[str, Any], player_id: str) -> str:
    return _player_note_wire_key(snapshot, player_id, "history")


def _opinion_wire_value(entry: dict[str, Any]) -> str:
    text = str(entry.get("text", "")).strip()
    updated = entry.get("updated_turn")
    if updated is not None:
        return f"(updated turn {updated}) {text}"
    return text


def chat_min_messages() -> int:
    raw = os.environ.get("CIV4AI_CHAT_MIN_MESSAGES", "").strip()
    if not raw:
        return min(CHAT_MIN_MESSAGES_DEFAULT, chat_max_messages())
    try:
        return max(0, min(chat_max_messages(), int(raw)))
    except ValueError:
        return min(CHAT_MIN_MESSAGES_DEFAULT, chat_max_messages())


def _schema_errors(validator: Draft202012Validator, value: Any) -> list[str]:
    return [f"{'/'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
            for error in sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))]


def _city_health_buckets(row: dict[str, Any]) -> dict[str, int]:
    """Map DLL city health fields into schema buckets (non-negative positive/negative)."""
    if any(key in row for key in ("good_health", "health_good", "bad_health", "health_bad")):
        positive = max(0, int(row.get("good_health", row.get("health_good", 0))))
        negative = max(0, int(row.get("bad_health", row.get("health_bad", 0))))
    else:
        # Legacy DLL snapshots put healthRate() in "health" (signed food effect).
        rate = int(row.get("health", 0))
        unhealth = max(0, int(row.get("unhealth", 0)))
        if rate < 0:
            positive = 0
            negative = max(unhealth, abs(rate))
        elif rate > 0:
            positive = rate
            negative = unhealth
        else:
            positive = 0
            negative = unhealth
    return {"positive": positive, "negative": negative, "net": positive - negative}


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    errors = _schema_errors(INPUT_VALIDATOR, snapshot)
    if errors:
        raise BoundaryError("snapshot_schema", "; ".join(errors[:8]))
    ids: set[str] = set()
    for command in snapshot["legal_commands"]:
        command_id = command["command_id"]
        if command_id in ids:
            raise BoundaryError("duplicate_legal_id", command_id)
        ids.add(command_id)
    recommendation_ids: set[str] = set()
    for item in snapshot["advciv"]["recommendations"]:
        if item["recommendation_id"] in recommendation_ids:
            raise BoundaryError("duplicate_recommendation_id", item["recommendation_id"])
        recommendation_ids.add(item["recommendation_id"])
        if not set(item["proposed_command_ids"]).issubset(ids):
            raise BoundaryError("illegal_recommendation", item["recommendation_id"])


def parse_exact_json(payload: str | bytes) -> dict[str, Any]:
    raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise BoundaryError("oversized_output", "Model output exceeds the byte limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BoundaryError("invalid_encoding", "Model output is not UTF-8") from error

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise BoundaryError("duplicate_key", f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        decoder = json.JSONDecoder(object_pairs_hook=pairs)
        value, end = decoder.raw_decode(text)
    except BoundaryError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise BoundaryError("malformed_json", "Expected exactly one JSON object") from error
    if text[end:].strip() or not isinstance(value, dict):
        raise BoundaryError("trailing_content", "Expected exactly one JSON object")
    return value


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def coalesce_model_response_shape(response: dict[str, Any]) -> dict[str, Any]:
    """Map common alternate model JSON layouts into the wire/schema vocabulary."""
    if not isinstance(response, dict):
        return response
    out = copy.deepcopy(response)
    if isinstance(out.get("cmds"), list) and not isinstance(out.get("commands"), list):
        commands: list[dict[str, Any]] = []
        for item in out["cmds"]:
            if not isinstance(item, dict):
                continue
            command_id = item.get("command_id") or item.get("cmd")
            if not isinstance(command_id, str) or not command_id:
                continue
            arguments = item.get("arguments")
            if not isinstance(arguments, dict):
                arguments = item.get("args")
            if not isinstance(arguments, dict):
                arguments = {}
            commands.append({"command_id": command_id, "arguments": arguments})
        out["commands"] = commands
        out.pop("cmds", None)
    if isinstance(out.get("cmd"), list) and not isinstance(out.get("commands"), list):
        out["commands"] = [
            {"command_id": str(entry), "arguments": {}}
            for entry in out["cmd"]
            if isinstance(entry, str) and entry
        ]
        out.pop("cmd", None)
    if isinstance(out.get("chat_message"), list) and not isinstance(out.get("chat_messages"), list):
        out["chat_messages"] = out.pop("chat_message")
    chats = out.get("chat_messages")
    if isinstance(chats, list):
        cleaned: list[dict[str, Any]] = []
        for message in chats:
            if not isinstance(message, dict):
                continue
            row = copy.deepcopy(message)
            if row.get("target") not in {"all", "team", "player"}:
                chat_type = str(row.get("chat_type", "")).lower()
                if "private" in chat_type or row.get("target_player_id"):
                    row["target"] = "player"
                else:
                    row["target"] = "all"
            cleaned.append(row)
        out["chat_messages"] = cleaned
    return out


def parse_model_text(text: str) -> dict[str, Any]:
    """Parse model wire output: strict JSON, fenced JSON, JSON+flat tail, or flat lines."""
    stripped = _strip_code_fence(text)
    if not stripped:
        raise BoundaryError("malformed_json", "Model output was empty")
    try:
        return coalesce_model_response_shape(parse_exact_json(stripped))
    except BoundaryError as error:
        if error.category not in {"trailing_content", "malformed_json"}:
            raise
    if "=" in stripped and not stripped.lstrip().startswith("{") and not stripped.lstrip().startswith("["):
        return coalesce_model_response_shape(parse_embedded_wire_assignments(stripped))
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(stripped)
    except (json.JSONDecodeError, ValueError) as parse_error:
        if "=" in stripped or "cmd." in stripped.lower() or "command_id" in stripped:
            return coalesce_model_response_shape(parse_embedded_wire_assignments(stripped))
        raise BoundaryError("malformed_json", "Expected exactly one JSON object") from parse_error
    if not isinstance(value, dict):
        raise BoundaryError("malformed_json", "Expected exactly one JSON object")
    remainder = stripped[end:].strip()
    if not remainder:
        return coalesce_model_response_shape(value)
    if remainder.startswith("{") or remainder.startswith("["):
        raise BoundaryError("trailing_content", "Expected exactly one JSON object")
    merged = coalesce_model_response_shape(value)
    if remainder.startswith("cmd.") or remainder.startswith("chat.") or "=" in remainder:
        for key, item in parse_embedded_wire_assignments(remainder).items():
            merged[key] = item
    summary = merged.get("decision_summary")
    if isinstance(summary, str) and summary.strip():
        for key, item in parse_embedded_wire_assignments(summary).items():
            if key.startswith(("cmd.", "chat.")) and key not in merged:
                merged[key] = item
    return merged


def _normalize_trade_inventory(rows: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "trade_item_id" not in row or "kind" not in row:
            continue
        items.append(row)
    return items


def _normalize_trade_items(rows: list[Any]) -> list[dict[str, Any]]:
    """Typed trade rows from DLL diplomacy_requests / counteroffer_proposals."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "kind" not in row:
            continue
        trade_item_id = row.get("trade_item_id")
        normalized.append({
            "trade_item_id": str(trade_item_id) if trade_item_id is not None else "TRADE_ITEM_UNKNOWN",
            "kind": str(row["kind"]),
            "data_id": row.get("data_id"),
            "amount": row.get("amount"),
            "denial_id": row.get("denial_id"),
        })
    return normalized


def _format_trade_items_wire(items: list[Any]) -> str:
    parts: list[str] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind", "TRADE_UNKNOWN"))
        label = _readable_id(kind, "TRADE_").lower().replace(" ", "_")
        data_id = row.get("data_id")
        if isinstance(data_id, str) and data_id.strip():
            data_label = data_id
            for prefix in ("BONUS_", "TECH_", "CIVIC_", "RELIGION_", "TEAM_", "CITY_"):
                if data_label.startswith(prefix):
                    data_label = _readable_id(data_label, prefix).lower().replace(" ", "_")
                    break
            label += ":" + data_label
        amount = row.get("amount")
        if amount is not None:
            label += "(" + str(amount) + ")"
        parts.append(label)
    return " | ".join(parts) if parts else "none"


def _diplomacy_response_cmd_ids(
    legal_commands: list[dict[str, Any]],
    request_id: str,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for command in legal_commands:
        if not isinstance(command, dict) or command.get("kind") != "respond_to_deal":
            continue
        fixed = command.get("fixed_arguments", {})
        if not isinstance(fixed, dict) or fixed.get("request_id") != request_id:
            continue
        response_id = fixed.get("response_id")
        command_id = command.get("command_id")
        if isinstance(response_id, str) and isinstance(command_id, str):
            mapping[response_id] = command_id
    return mapping


def _counteroffer_cmd_id(
    legal_commands: list[dict[str, Any]],
    counteroffer_id: str,
) -> str | None:
    for command in legal_commands:
        if not isinstance(command, dict) or command.get("kind") != "counteroffer":
            continue
        fixed = command.get("fixed_arguments", {})
        if isinstance(fixed, dict) and fixed.get("counteroffer_id") == counteroffer_id:
            cmd_id = command.get("command_id")
            return str(cmd_id) if isinstance(cmd_id, str) else None
    return None


def _diplomacy_kind_cmd_id(
    legal_commands: list[dict[str, Any]],
    kind: str,
    arg_key: str,
    arg_value: str,
) -> str | None:
    for command in legal_commands:
        if not isinstance(command, dict) or command.get("kind") != kind:
            continue
        fixed = command.get("fixed_arguments", {})
        if isinstance(fixed, dict) and fixed.get(arg_key) == arg_value:
            cmd_id = command.get("command_id")
            return str(cmd_id) if isinstance(cmd_id, str) else None
    return None


def _append_diplomacy_situation_wire(lines: list[str], context: dict[str, Any]) -> None:
    diplomacy = context.get("diplomacy", {})
    if not isinstance(diplomacy, dict):
        return
    legal_commands = [
        command for command in context.get("legal_commands", [])
        if isinstance(command, dict)
    ]
    for index, proposal in enumerate(diplomacy.get("available_proposals", [])[:8]):
        if not isinstance(proposal, dict):
            continue
        target = proposal.get("target_player_id", "PLAYER_X")
        proposal_id = proposal.get("proposal_id", "PROPOSAL_UNKNOWN")
        line = f"{target}:{proposal_id}"
        cmd_id = _diplomacy_kind_cmd_id(legal_commands, "propose_deal", "proposal_id", str(proposal_id))
        if cmd_id:
            line += f" propose_cmd={cmd_id}"
        lines.append(_wire_line(f"diplomacy.proposal.{index}", line))
    for index, deal in enumerate(diplomacy.get("active_deals", [])[:6]):
        if not isinstance(deal, dict):
            continue
        other = deal.get("other_player_id", "PLAYER_X")
        deal_id = deal.get("deal_id", "DEAL_UNKNOWN")
        we_give = _format_trade_items_wire(deal.get("our_items", []))
        they_give = _format_trade_items_wire(deal.get("their_items", []))
        cancelable = bool(deal.get("cancelable", False))
        line = f"{other}:{deal_id} we_give={we_give} they_give={they_give} cancelable={cancelable}"
        if cancelable:
            cmd_id = _diplomacy_kind_cmd_id(legal_commands, "cancel_deal", "deal_id", str(deal_id))
            if cmd_id:
                line += f" cancel_cmd={cmd_id}"
        lines.append(_wire_line(
            f"diplomacy.deal.{index}",
            line,
        ))
    for index, request in enumerate(diplomacy.get("pending_requests", [])[:6]):
        if not isinstance(request, dict):
            continue
        prefix = f"diplomacy.pending.{index}"
        request_id = str(request.get("request_id", "DIPLO_REQUEST_UNKNOWN"))
        from_id = str(request.get("from_player_id", "PLAYER_X"))
        lines.append(_wire_line(f"{prefix}.from", from_id))
        lines.append(_wire_line(f"{prefix}.request_id", request_id))
        lines.append(_wire_line(f"{prefix}.we_give", _format_trade_items_wire(request.get("our_items", []))))
        lines.append(_wire_line(f"{prefix}.they_give", _format_trade_items_wire(request.get("their_items", []))))
        responses = _diplomacy_response_cmd_ids(legal_commands, request_id)
        if "DIPLO_ACCEPT" in responses:
            lines.append(_wire_line(f"{prefix}.accept_cmd", responses["DIPLO_ACCEPT"]))
        if "DIPLO_REJECT" in responses:
            lines.append(_wire_line(f"{prefix}.reject_cmd", responses["DIPLO_REJECT"]))
        counter = request.get("counteroffer")
        if isinstance(counter, dict):
            counter_id = str(counter.get("counteroffer_id", ""))
            if counter_id:
                lines.append(_wire_line(f"{prefix}.counter_we_give", _format_trade_items_wire(counter.get("our_items", []))))
                lines.append(_wire_line(f"{prefix}.counter_they_give", _format_trade_items_wire(counter.get("their_items", []))))
                cmd_id = _counteroffer_cmd_id(legal_commands, counter_id)
                if cmd_id:
                    lines.append(_wire_line(f"{prefix}.counteroffer_cmd", cmd_id))


LEGACY_PERSONALITY_KEYS = (
    "traits",
    "strategic_priorities",
    "risk_tolerance",
    "diplomacy_style",
    "aggression",
    "economic_bias",
    "communication_tone",
)

# Authoritative each turn from the DLL snapshot; must not be overridden by disk.
PERSONALITY_IDENTITY_KEYS = frozenset(
    {
        "identity",
        "leader_id",
        "leader_name",
        "civilization_id",
        "leader_traits",
    }
)


def normalize_personality(snapshot: dict[str, Any]) -> None:
    personality = snapshot.get("personality")
    if not isinstance(personality, dict):
        return
    for key in LEGACY_PERSONALITY_KEYS:
        personality.pop(key, None)


def build_model_input(extracted: dict[str, Any]) -> dict[str, Any]:
    """Copy an already visibility-filtered extractor result and validate it."""
    snapshot = _upgrade_legacy_source(extracted) if "schema_version" not in extracted else copy.deepcopy(extracted)
    normalize_personality(snapshot)
    validate_snapshot(snapshot)
    if snapshot["known_map"]["visibility_mode"] == "omniscient_debug" and snapshot["game"]["network_multiplayer"]:
        raise BoundaryError("debug_forbidden", "Omniscient state is forbidden in multiplayer")
    return snapshot


def model_provider() -> str:
    raw = os.environ.get(
        "CIV6AI_MODEL_PROVIDER",
        os.environ.get("CIV4AI_MODEL_PROVIDER", "gemini"),
    ).strip().lower()
    if raw in {"gemini", "openai", "lmstudio"}:
        return raw
    return "gemini"


def openai_reasoning_effort() -> str:
    raw = os.environ.get("CIV4AI_OPENAI_REASONING_EFFORT", "low").strip().lower()
    return raw if raw in {"low", "medium", "high"} else "low"


def map_image_cadence_turns() -> int:
    raw = os.environ.get("CIV4AI_MAP_IMAGE_CADENCE", str(MAP_IMAGE_CADENCE_TURNS)).strip()
    try:
        cadence = int(raw)
    except ValueError:
        cadence = MAP_IMAGE_CADENCE_TURNS
    return max(1, cadence)


def map_image_attach_turn(snapshot: dict[str, Any]) -> bool:
    """Attach map PNG to model requests (default: every turn for situational awareness)."""
    cadence = map_image_cadence_turns()
    if cadence <= 1:
        return True
    decision = snapshot.get("decision", {})
    turn = int(decision.get("turn", 0))
    player_id = str(decision.get("player_id", "PLAYER_0"))
    try:
        player_index = int(player_id.rsplit("_", 1)[-1])
    except ValueError:
        player_index = 0
    return (turn + player_index) % cadence == 0


def _parse_plot_coords(plot_id: Any) -> tuple[int, int] | None:
    if not isinstance(plot_id, str) or not plot_id.startswith("PLOT_"):
        return None
    parts = plot_id.split("_")
    if len(parts) < 3:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _plot_from_grid_cell(x: int, y: int, cell: str, knowledge: str = "remembered") -> dict[str, Any]:
    from sidecar.map_render import _plot_from_grid_cell as _render_plot_from_grid_cell

    plot = _render_plot_from_grid_cell(x, y, cell, knowledge=knowledge)
    plot.setdefault("last_seen_turn", None)
    plot.setdefault("area_id", "AREA_0")
    plot.setdefault("revealed_owner_id", None)
    plot.setdefault("feature_id", None)
    plot.setdefault("improvement_id", None)
    plot.setdefault("route_id", None)
    plot.setdefault("yields", {"food": 0, "production": 0, "commerce": 0})
    plot.setdefault("defense_percent", 0)
    plot.setdefault("city_id", None)
    plot.setdefault("worked_by_city_id", None)
    plot.setdefault("visible_stack_ids", [])
    return plot


def _visibility_grid_origin(known_map: dict[str, Any] | None) -> tuple[int, int]:
    """visibility_grid rows are cropped to known_map.viewport, not full-map (0,0)."""
    if not isinstance(known_map, dict):
        return 0, 0
    viewport = known_map.get("viewport")
    if not isinstance(viewport, dict):
        image = known_map.get("image")
        if isinstance(image, dict):
            viewport = image.get("viewport")
    if not isinstance(viewport, dict):
        return 0, 0
    try:
        return int(viewport.get("x0") or 0), int(viewport.get("y0") or 0)
    except (TypeError, ValueError):
        return 0, 0


def _plots_from_visibility_grid(
    grid: list[Any],
    width: int,
    height: int,
    origin: tuple[int, int] = (0, 0),
) -> list[dict[str, Any]]:
    ox, oy = origin
    plots: list[dict[str, Any]] = []
    for y in range(min(height, len(grid))):
        row = grid[y]
        if not isinstance(row, str):
            continue
        for x in range(min(width, len(row))):
            if row[x] == "?":
                continue
            plots.append(_plot_from_grid_cell(ox + x, oy + y, row[x]))
    return plots


def _normalize_territory_owner_grid(grid: list[Any], width: int, height: int) -> list[str] | None:
    if not isinstance(grid, list) or not grid:
        return None
    rows: list[str] = []
    for y in range(height):
        if y < len(grid) and isinstance(grid[y], str):
            rows.append(grid[y])
        else:
            rows.append("?" * width)
    if not any(cell not in {"?", "."} for row in rows for cell in row):
        return None
    return rows


def _normalize_visibility_grid(grid: list[Any], width: int, height: int) -> list[str] | None:
    if not isinstance(grid, list) or not grid:
        return None
    rows: list[str] = []
    for y in range(height):
        if y < len(grid) and isinstance(grid[y], str):
            rows.append(grid[y])
        else:
            rows.append("?" * width)
    if not any(cell != "?" for row in rows for cell in row):
        return None
    return rows


def ensure_known_map_plots(snapshot: dict[str, Any]) -> int:
    """Fill known_map.plots from visibility_grid or entity positions when the host thinned plot JSON."""
    known_map = snapshot.get("known_map")
    if not isinstance(known_map, dict):
        return 0
    plots = known_map.get("plots")
    width = int(snapshot["game"]["map_width"])
    height = int(snapshot["game"]["map_height"])
    turn = int(snapshot["decision"]["turn"])
    grid = known_map.get("visibility_grid")
    normalized = _normalize_visibility_grid(grid if isinstance(grid, list) else [], width, height)
    grid_origin = _visibility_grid_origin(known_map)
    if isinstance(plots, list) and plots:
        if normalized is not None:
            by_key: dict[tuple[int, int], dict[str, Any]] = {}
            for plot in plots:
                if isinstance(plot, dict):
                    by_key[(int(plot["x"]), int(plot["y"]))] = plot
            ox, oy = grid_origin
            for y in range(min(height, len(normalized))):
                row = normalized[y]
                for x in range(min(width, len(row))):
                    if row[x] == "?":
                        continue
                    key = (ox + x, oy + y)
                    if key not in by_key:
                        by_key[key] = _plot_from_grid_cell(key[0], key[1], row[x])
            known_map["plots"] = sorted(by_key.values(), key=lambda p: (p["y"], p["x"]))
            return len(known_map["plots"])
        return len(plots)
    if normalized is not None:
        rebuilt = _plots_from_visibility_grid(normalized, width, height, origin=grid_origin)
    else:
        visible = {"stacks": known_map.get("visible_stacks", [])}
        rebuilt = _synthesize_plots_from_entities(
            visible,
            snapshot.get("your_cities", []),
            snapshot.get("your_units", []),
            snapshot.get("known_other_cities", []),
            snapshot.get("your_units", []) + snapshot.get("visible_other_units", []),
            width, height, turn,
        )
    known_map["plots"] = rebuilt
    return len(rebuilt)


def _synthesize_plots_from_entities(
    visible: dict[str, Any],
    own_cities: list[dict[str, Any]],
    own_units: list[dict[str, Any]],
    other_cities: list[dict[str, Any]],
    all_units: list[dict[str, Any]],
    width: int,
    height: int,
    turn: int,
) -> list[dict[str, Any]]:
    """Rebuild minimal plot records when DLL thinned map JSON but units/cities remain."""
    by_key: dict[tuple[int, int], dict[str, Any]] = {}
    grid = visible.get("grid", [])
    grid_is_ocean: dict[tuple[int, int], bool] = {}

    def grid_water(x: int, y: int) -> bool:
        key = (x, y)
        if key in grid_is_ocean:
            return grid_is_ocean[key]
        is_water = False
        if isinstance(grid, list) and y < len(grid) and isinstance(grid[y], str):
            row = grid[y]
            if x < len(row) and row[x] == "~":
                is_water = True
        grid_is_ocean[key] = is_water
        return is_water

    def add_plot(x: int, y: int, knowledge: str = "visible", city_id: str | None = None) -> None:
        if x < 0 or y < 0 or x >= width or y >= height:
            return
        key = (x, y)
        if key in by_key:
            return
        water = grid_water(x, y)
        terrain = "TERRAIN_OCEAN" if water else "TERRAIN_GRASS"
        by_key[key] = {
            "plot_id": f"PLOT_{x}_{y}", "x": x, "y": y, "knowledge": knowledge,
            "last_seen_turn": turn if knowledge == "visible" else None,
            "area_id": "AREA_0", "terrain_id": terrain, "water": water,
            "hills": False, "peak": False, "fresh_water": False, "river_edges": [],
            "revealed_owner_id": None, "feature_id": None, "improvement_id": None,
            "route_id": None, "resource_id": None,
            "yields": {"food": 0, "production": 0, "commerce": 0},
            "defense_percent": 0, "city_id": city_id, "worked_by_city_id": None,
            "visible_stack_ids": [],
        }

    for city in own_cities + other_cities:
        if not isinstance(city, dict):
            continue
        coords = _parse_plot_coords(city.get("plot_id"))
        if coords is None:
            continue
        add_plot(coords[0], coords[1], "visible", city.get("city_id"))
        for worked in city.get("worked_plot_ids", []):
            worked_coords = _parse_plot_coords(worked)
            if worked_coords is not None:
                add_plot(worked_coords[0], worked_coords[1], "visible")
    for unit in own_units + all_units:
        if not isinstance(unit, dict):
            continue
        coords = _parse_plot_coords(unit.get("plot_id"))
        if coords is not None:
            add_plot(coords[0], coords[1], "visible")
    for row in visible.get("stacks", []):
        if not isinstance(row, dict):
            continue
        coords = _parse_plot_coords(row.get("plot_id"))
        if coords is None:
            coords = (int(row.get("x", -1)), int(row.get("y", -1)))
        if coords[0] >= 0 and coords[1] >= 0:
            add_plot(coords[0], coords[1], "visible")
    return [by_key[key] for key in sorted(by_key)]


def append_turn_metrics(metrics_dir: Path, event: dict[str, Any]) -> bool:
    try:
        metrics_dir.mkdir(parents=True, exist_ok=True)
        path = metrics_dir / "turn_metrics.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json({"recorded_unix_ms": int(time.time() * 1000), **event}) + "\n")
        return True
    except OSError:
        return False


def _readable_id(value: Any, prefix: str = "") -> str:
    text = str(value)
    if prefix and text.startswith(prefix):
        return text[len(prefix):]
    for token in ("TECH_", "UNIT_", "CITY_", "PLAYER_", "PLOT_", "BUILDING_"):
        if text.startswith(token):
            return text[len(token):]
    return text


def _legal_wire_label(command: dict[str, Any]) -> str:
    kind = str(command.get("kind", "command"))
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    parts = [kind]
    for key in sorted(fixed):
        parts.append(_readable_id(fixed[key]))
    domains = command.get("parameter_domains", {})
    if isinstance(domains, dict):
        for key in sorted(domains):
            if key not in fixed:
                parts.append(key)
    return ".".join(parts[:6]) if parts else kind


def _wire_section(title: str, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "(none)"
    return f"=== {title} ===\n{body}"


def _describe_legal_command(command: dict[str, Any]) -> str:
    """Human-readable one-line summary for the LEGAL COMMANDS section."""
    kind = str(command.get("kind", "command"))
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    if kind == "choose_research":
        tech = fixed.get("tech_id")
        if isinstance(tech, str) and tech.strip():
            return f"Research {_readable_id(tech, 'TECH_')}"
        return "Choose a research technology"
    if kind == "queue_production":
        city = _readable_id(fixed.get("city_id", "city"), "CITY_")
        build = fixed.get("build_id", "")
        label = _readable_id(build, "TRAIN:")
        return f"Queue {label} in city {city}"
    if kind == "set_city_emphasis":
        city = _readable_id(fixed.get("city_id", "city"), "CITY_")
        role = _readable_id(fixed.get("role_id", ""), "ROLE:")
        return f"Emphasize {role} in city {city}"
    if kind == "change_commerce":
        commerce = _readable_id(fixed.get("commerce_id", ""), "COMMERCE_")
        percent = fixed.get("percent_id", "")
        pct = _readable_id(percent, "PERCENT_") if isinstance(percent, str) else ""
        return f"Set {commerce} allocation to {pct}%"
    if kind == "adopt_civics":
        option = _readable_id(fixed.get("civic_option_id", ""), "CIVICOPTION_")
        civic = _readable_id(fixed.get("civic_id", ""), "CIVIC_")
        if option and civic:
            return f"Adopt {civic} ({option})"
        if civic:
            return f"Adopt civic {civic}"
    if kind == "propose_deal":
        target = fixed.get("target_player_id")
        proposal = fixed.get("proposal_id")
        if isinstance(target, str) and isinstance(proposal, str):
            return f"Propose {proposal} to {target}"
    if kind == "respond_to_deal":
        response = fixed.get("response_id")
        request = fixed.get("request_id")
        if isinstance(response, str) and isinstance(request, str):
            return f"Respond {response} to {request}"
    if kind == "counteroffer":
        counter = fixed.get("counteroffer_id")
        request = fixed.get("request_id")
        if isinstance(counter, str) and isinstance(request, str):
            return f"Counteroffer {counter} for {request}"
    if kind == "cancel_deal":
        deal_id = fixed.get("deal_id")
        if isinstance(deal_id, str):
            return f"Cancel deal {deal_id}"
    if kind in {"unit_mission", "unit_posture_mission", "found_city", "worker_build"}:
        unit = _readable_id(fixed.get("unit_id", ""), "UNIT_")
        mission = fixed.get("mission_id", fixed.get("build_id", ""))
        mission_label = _readable_id(mission, "MISSION_")
        if unit and mission_label:
            return f"Order unit {unit}: {mission_label}"
        if unit:
            return f"Order unit {unit}"
    description = command.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return kind.replace("_", " ")


def _legal_command_notes(command: dict[str, Any]) -> str:
    notes: list[str] = []
    risk = RISK_BY_KIND.get(command.get("kind"))
    if risk:
        notes.append(f"risk={risk}")
    runtime = command.get("runtime_status") or RUNTIME_BY_KIND.get(command.get("kind"))
    if isinstance(runtime, str) and runtime and runtime != "tested":
        notes.append(f"status={runtime}")
    domains = command.get("parameter_domains", {})
    if isinstance(domains, dict) and domains:
        notes.append("args: " + ", ".join(sorted(domains)))
    return "; ".join(notes)


MISSION_WIRE_LABELS: dict[str, str] = {
    "MISSION_FORTIFY": "fortify",
    "MISSION_SLEEP": "sleep",
    "MISSION_SENTRY": "sentry",
    "MISSION_HEAL": "heal",
    "MISSION_SKIP": "skip",
    "MISSION_FOUND": "found",
    "MISSION_BUILD": "build",
    "MISSION_MOVE_TO": "move",
}


def _wire_max_unit_detail_lines() -> int:
    raw = os.environ.get("CIV4AI_WIRE_MAX_UNIT_DETAIL", str(WIRE_MAX_UNIT_DETAIL_DEFAULT)).strip()
    try:
        return max(0, min(512, int(raw)))
    except ValueError:
        return WIRE_MAX_UNIT_DETAIL_DEFAULT


def _unit_type_label(unit_type_id: Any) -> str:
    if not isinstance(unit_type_id, str) or not unit_type_id.strip():
        return "unit"
    return _readable_id(unit_type_id, "UNIT_").lower()


def _build_unit_wire_id_map(units: list[dict[str, Any]]) -> dict[str, str]:
    type_counts: dict[str, int] = {}
    wire_ids: dict[str, str] = {}
    sorted_units = sorted(
        [unit for unit in units if isinstance(unit, dict) and isinstance(unit.get("unit_id"), str)],
        key=lambda item: item["unit_id"],
    )
    for unit in sorted_units:
        label = _unit_type_label(unit.get("unit_type_id"))
        type_counts[label] = type_counts.get(label, 0) + 1
        wire_ids[unit["unit_id"]] = f"{label}_{type_counts[label]}"
    return wire_ids


def _plot_coords_text(plot_id: Any) -> str:
    coords = _parse_plot_coords(plot_id)
    if coords is None:
        return "(?,?)"
    return f"({coords[0]},{coords[1]})"


def _coords_from_fixed_arguments(fixed: dict[str, Any]) -> str | None:
    data1 = fixed.get("data1_id")
    data2 = fixed.get("data2_id")
    if isinstance(data1, str) and data1.startswith("INT_") and isinstance(data2, str) and data2.startswith("INT_"):
        return f"({_readable_id(data1, 'INT_')},{_readable_id(data2, 'INT_')})"
    return _plot_coords_text(fixed.get("target_plot_id"))


def _unit_stance_label(unit: dict[str, Any]) -> str:
    activity = unit.get("activity_id")
    if isinstance(activity, str) and activity.strip():
        return _readable_id(activity, "ACTIVITY_").lower()
    return "unknown"


def _append_unit_stat_wire(lines: list[str], prefix: str, unit: dict[str, Any]) -> int:
    """Append hp/attack/movement stats; returns number of lines added."""
    added = 0
    health = unit.get("health", {})
    if isinstance(health, dict):
        current = health.get("current")
        maximum = health.get("maximum")
        if isinstance(current, int):
            lines.append(_wire_line(f"{prefix}.hp", current))
            added += 1
        if isinstance(maximum, int) and maximum != current:
            lines.append(_wire_line(f"{prefix}.maxHp", maximum))
            added += 1
    elif isinstance(unit.get("health_percent"), int):
        lines.append(_wire_line(f"{prefix}.hp", unit["health_percent"]))
        added += 1
    strength = unit.get("strength", {})
    if isinstance(strength, dict) and isinstance(strength.get("current"), int):
        lines.append(_wire_line(f"{prefix}.attack", strength["current"]))
        added += 1
    elif isinstance(unit.get("visible_strength"), int):
        lines.append(_wire_line(f"{prefix}.attack", unit["visible_strength"]))
        added += 1
    movement = unit.get("movement", {})
    if isinstance(movement, dict):
        if isinstance(movement.get("current"), int):
            lines.append(_wire_line(f"{prefix}.movement", movement["current"]))
            added += 1
        if isinstance(movement.get("maximum"), int):
            lines.append(_wire_line(f"{prefix}.maxMovement", movement["maximum"]))
            added += 1
    range_tiles = unit.get("range")
    if isinstance(range_tiles, int) and range_tiles > 0:
        lines.append(_wire_line(f"{prefix}.range", range_tiles))
        added += 1
    if isinstance(unit.get("level"), int):
        lines.append(_wire_line(f"{prefix}.level", unit["level"]))
        added += 1
    if isinstance(unit.get("experience"), int) and unit["experience"] > 0:
        lines.append(_wire_line(f"{prefix}.experience", unit["experience"]))
        added += 1
    lines.append(_wire_line(f"{prefix}.stance", _unit_stance_label(unit)))
    added += 1
    if unit.get("needs_orders"):
        lines.append(_wire_line(f"{prefix}.needsOrders", True))
        added += 1
    if unit.get("can_act"):
        lines.append(_wire_line(f"{prefix}.canAct", True))
        added += 1
    return added


def _append_unit_compact_wire(lines: list[str], prefix: str, unit: dict[str, Any]) -> int:
    """Position-only unit detail; include needsOrders when the unit awaits orders."""
    if unit.get("needs_orders"):
        lines.append(_wire_line(f"{prefix}.needsOrders", True))
        return 1
    return 0


def _append_city_situation_wire(lines: list[str], city: dict[str, Any], many_cities: bool) -> None:
    name = _city_prompt_name(city)
    is_capital = bool(city.get("is_capital"))
    if many_cities and not is_capital:
        plot_id = city.get("plot_id")
        if isinstance(plot_id, str) and plot_id.strip():
            lines.append(_wire_line(f"{name}.position", _plot_coords_text(plot_id)))
        return
    lines.append(_wire_line(f"{name}.population", int(city.get("population", 1))))
    if is_capital:
        lines.append(_wire_line(f"{name}.capital", True))
    buildings = _city_buildings_wire_value(city)
    if buildings:
        lines.append(_wire_line(f"{name}.buildings", buildings))
    production = city.get("production", {})
    if isinstance(production, dict) and production.get("item_id"):
        item = production["item_id"]
        if isinstance(item, str) and item.startswith("UNIT_"):
            lines.append(_wire_line(f"{name}.currentProduction", _readable_id(item, "UNIT_").lower()))
        else:
            lines.append(_wire_line(f"{name}.currentProduction", item))


def _stack_wire_prefix(plot_id: str, multiple_stacks: bool) -> str:
    if not multiple_stacks:
        return "stack"
    coords = _parse_plot_coords(plot_id)
    if coords is None:
        return "stack"
    return f"stack.{coords[0]}_{coords[1]}"


def _units_by_plot(context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_plot: dict[str, list[dict[str, Any]]] = {}
    for unit in context.get("your_units", []):
        if not isinstance(unit, dict):
            continue
        plot_id = str(unit.get("plot_id", "PLOT_0_0"))
        by_plot.setdefault(plot_id, []).append(unit)
    return by_plot


def _stack_entries(context: dict[str, Any]) -> list[tuple[str, str, list[str], list[str]]]:
    """Return (stack_prefix, plot_id, unit_wire_ids, unit_ids) for multi-unit tiles."""
    own_units = [unit for unit in context.get("your_units", []) if isinstance(unit, dict)]
    if not own_units:
        return []
    wire_id_map = _build_unit_wire_id_map(own_units)
    by_plot = _units_by_plot(context)
    stack_plots = [plot_id for plot_id, group in by_plot.items() if len(group) > 1]
    multiple_stacks = len(stack_plots) > 1
    entries: list[tuple[str, str, list[str], list[str]]] = []
    for plot_id in sorted(stack_plots):
        units = by_plot[plot_id]
        prefix = _stack_wire_prefix(plot_id, multiple_stacks)
        wire_ids: list[str] = []
        unit_ids: list[str] = []
        for unit in sorted(units, key=lambda item: wire_id_map.get(item.get("unit_id", ""), "")):
            unit_id = unit.get("unit_id")
            if not isinstance(unit_id, str) or not unit_id.strip():
                continue
            unit_ids.append(unit_id)
            wire_ids.append(wire_id_map.get(unit_id, _unit_type_label(unit.get("unit_type_id"))))
        if wire_ids:
            entries.append((prefix, plot_id, wire_ids, unit_ids))
    return entries


def _stack_plot_id_from_prefix(prefix: str) -> str | None:
    if not prefix.startswith("stack."):
        return None
    coords = prefix[6:].split("_", 1)
    if len(coords) != 2:
        return None
    try:
        return f"PLOT_{int(coords[0])}_{int(coords[1])}"
    except ValueError:
        return None


def _resolve_stack_plot_id(prefix: str, context: dict[str, Any]) -> str | None:
    explicit = _stack_plot_id_from_prefix(prefix)
    if explicit:
        return explicit
    if prefix != "stack":
        return None
    stacks = _stack_entries(context)
    if len(stacks) == 1:
        return stacks[0][1]
    return None


def _has_unit_stacks(context: dict[str, Any]) -> bool:
    return any(len(group) > 1 for group in _units_by_plot(context).values())


def _compact_stack_legal_lines(
    context: dict[str, Any],
    unit_commands: dict[str, list[dict[str, Any]]],
) -> list[str]:
    lines: list[str] = []
    for prefix, _plot_id, wire_ids, _unit_ids in _stack_entries(context):
        move_values: list[str] | None = None
        for wire_id in wire_ids:
            grouped = _group_unit_commands(unit_commands.get(wire_id, []))
            values = grouped.get("moveTo")
            if not values:
                continue
            if move_values is None:
                move_values = list(values)
                continue
            for value in values:
                if value not in move_values:
                    move_values.append(value)
        if move_values:
            lines.append(_wire_line(f"{prefix}.moveTo", " | ".join(move_values)))
    return lines


def _append_units_situation_wire(lines: list[str], context: dict[str, Any]) -> None:
    own_units = [unit for unit in context.get("your_units", []) if isinstance(unit, dict)]
    if not own_units:
        return
    compact = wire_use_compact_detail(context)
    wire_id_map = _build_unit_wire_id_map(own_units)
    by_plot = _units_by_plot(context)
    stack_plots = [plot_id for plot_id, group in by_plot.items() if len(group) > 1]
    multiple_stacks = len(stack_plots) > 1
    detail_budget = _wire_max_unit_detail_lines()
    detail_used = 0
    append_detail = _append_unit_compact_wire if compact else _append_unit_stat_wire
    for plot_id in sorted(by_plot):
        units = by_plot[plot_id]
        position = _plot_coords_text(plot_id)
        if len(units) == 1:
            unit = units[0]
            unit_id = unit.get("unit_id")
            wire_id = wire_id_map.get(unit_id, _unit_type_label(unit.get("unit_type_id")))
            lines.append(_wire_line(f"{wire_id}.position", position))
            detail_used += 1 + append_detail(lines, wire_id, unit)
            continue
        prefix = _stack_wire_prefix(plot_id, multiple_stacks)
        lines.append(_wire_line(f"{prefix}.position", position))
        lines.append(_wire_line(f"{prefix}.size", len(units)))
        detail_used += 2
        if compact:
            for unit in sorted(units, key=lambda item: wire_id_map.get(item.get("unit_id", ""), "")):
                unit_id = unit.get("unit_id")
                wire_id = wire_id_map.get(unit_id, _unit_type_label(unit.get("unit_type_id")))
                detail_used += append_detail(lines, f"{prefix}.{wire_id}", unit)
        elif detail_used < detail_budget:
            for unit in sorted(units, key=lambda item: wire_id_map.get(item.get("unit_id", ""), "")):
                unit_id = unit.get("unit_id")
                wire_id = wire_id_map.get(unit_id, _unit_type_label(unit.get("unit_type_id")))
                if detail_used >= detail_budget:
                    break
                detail_used += 1 + append_detail(lines, f"{prefix}.{wire_id}", unit)
    for unit in context.get("visible_other_units", [])[:16]:
        if not isinstance(unit, dict):
            continue
        wire_id = f"foreign_{_unit_type_label(unit.get('unit_type_id'))}"
        lines.append(_wire_line(f"{wire_id}.position", _plot_coords_text(unit.get("plot_id"))))
        if not compact:
            _append_unit_stat_wire(lines, wire_id, unit)


def _unit_command_property_parts(command: dict[str, Any]) -> tuple[str, str]:
    kind = str(command.get("kind", ""))
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    if kind == "move_unit":
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return "moveTo", f"({x},{y})"
        return "moveTo", _coords_from_fixed_arguments(fixed) or "target"
    if kind in {"unit_posture_fortify", "unit_posture_heal", "unit_posture_alert", "unit_posture_sleep"}:
        return "stance", kind.replace("unit_posture_", "")
    if kind == "unit_skip":
        return "stance", "skip"
    mission = fixed.get("mission_id")
    if kind == "move_group" or (isinstance(mission, str) and mission == "MISSION_MOVE_TO"):
        coords = _coords_from_fixed_arguments(fixed)
        return "moveTo", coords or "target"
    if kind == "unit_posture_mission" or kind == "unit_mission":
        if isinstance(mission, str) and mission in MISSION_WIRE_LABELS:
            return "stance", MISSION_WIRE_LABELS[mission]
        if isinstance(mission, str):
            return "stance", _readable_id(mission, "MISSION_").lower()
    if kind == "found_city":
        return "foundCity", "apply"
    if kind == "improve_tile":
        build = fixed.get("build_id")
        if isinstance(build, str) and build.strip():
            return "improve", build.strip()
        return "improve", "tile"
    if kind == "discover_tech":
        return "discover", "apply"
    if kind == "hurry_production":
        return "hurry", "apply"
    if kind == "trade_mission":
        return "trade", "apply"
    if kind == "start_golden_age":
        return "goldenAge", "apply"
    if kind == "create_great_work":
        return "greatWork", "apply"
    if kind == "attack_target":
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return "attackTo", f"({x},{y})"
        return "attackTo", _coords_from_fixed_arguments(fixed) or "target"
    if kind == "range_attack":
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return "rangedAttack", f"({x},{y})"
        return "rangedAttack", _coords_from_fixed_arguments(fixed) or "target"
    if kind == "rebase":
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return "rebaseTo", f"({x},{y})"
        return "rebaseTo", _coords_from_fixed_arguments(fixed) or "target"
    if kind == "paradrop":
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return "paradropTo", f"({x},{y})"
        return "paradropTo", _coords_from_fixed_arguments(fixed) or "target"
    if kind == "nuke":
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return "nukeAt", f"({x},{y})"
        return "nukeAt", _coords_from_fixed_arguments(fixed) or "target"
    if kind == "spread_religion":
        return "spread", "apply"
    if kind == "remove_heresy":
        return "removeHeresy", "apply"
    if kind == "pillage":
        return "pillage", "apply"
    if kind == "upgrade_unit":
        target = fixed.get("unit_type_id") or fixed.get("target_id")
        if isinstance(target, str) and target.strip():
            text = target.strip()
            if text.startswith("UNIT_"):
                return "upgrade", text
            return "upgrade", _readable_id(text, "UNIT_").lower()
        return "upgrade", "apply"
    if kind == "air_patrol":
        return "intercept", "apply"
    if kind == "worker_build":
        build = fixed.get("build_id") or fixed.get("data1_id")
        return "build", _readable_id(str(build), "BUILD_").lower() if build else "tile"
    if kind == "promote_unit":
        promo = fixed.get("promotion_id") or fixed.get("target_id")
        return "promote", _readable_id(str(promo or "promotion"), "PROMOTION_").lower()
    if kind == "automate_unit":
        automate = fixed.get("automate_id") or fixed.get("data1_id")
        if isinstance(automate, str):
            automate_label = {
                "INT_0": "build",
                "INT_1": "network",
                "INT_2": "city",
                "INT_3": "explore",
                "INT_4": "religion",
                "AUTOMATE_BUILD": "build",
                "AUTOMATE_EXPLORE": "explore",
            }.get(automate)
            if automate_label:
                return "automate", automate_label
            if automate.startswith("AUTOMATE_"):
                return "automate", _readable_id(automate, "AUTOMATE_").lower()
        return "automate", "on"
    if kind == "stop_unit_automation":
        return "automate", "off"
    property_name = kind[0].lower() + kind[1:] if kind else "command"
    return property_name, "apply"


def _normalize_wire_value(value: Any) -> str:
    return str(value).strip().replace(" ", "").lower()


def _normalize_wire_coord(value: Any) -> str:
    text = str(value).strip().replace(" ", "").lower()
    match = re.match(r"^\(?(\d+)[_,](\d+)\)?$", text)
    if match:
        return f"({match.group(1)},{match.group(2)})"
    return text


def _unit_command_wire_line(unit_wire_id: str, command: dict[str, Any]) -> str:
    property_name, value_label = _unit_command_property_parts(command)
    command_id = str(command.get("command_id", ""))
    notes = _legal_command_notes(command)
    line = _wire_line(f"{unit_wire_id}.{property_name}", value_label)
    suffix = f" // {command_id}"
    if notes:
        suffix += f"; {notes}"
    return line + suffix


def _command_matches_unit_property(
    command: dict[str, Any],
    unit_id: str,
    unit_wire_id: str,
    property_parts: list[str],
    value: Any,
) -> bool:
    if not isinstance(command, dict):
        return False
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict) or fixed.get("unit_id") != unit_id:
        return False
    kind = str(command.get("kind", ""))
    if kind == "found_city" and property_parts == ["foundCity"]:
        return _normalize_wire_value(value) == "apply"
    gp_apply_props = {
        "discover_tech": "discover",
        "hurry_production": "hurry",
        "trade_mission": "trade",
        "start_golden_age": "goldenAge",
        "create_great_work": "greatWork",
        "spread_religion": "spread",
        "remove_heresy": "removeHeresy",
        "pillage": "pillage",
        "air_patrol": "intercept",
    }
    if kind in gp_apply_props and property_parts == [gp_apply_props[kind]]:
        return _normalize_wire_value(value) == "apply"
    if kind == "improve_tile" and property_parts == ["improve"]:
        build_id = fixed.get("build_id")
        if not isinstance(build_id, str):
            return False
        normalized = _normalize_wire_value(value)
        return normalized in {
            _normalize_wire_value(build_id),
            _normalize_wire_value(_readable_id(build_id, "BUILD_")),
        }
    if kind == "upgrade_unit" and property_parts == ["upgrade"]:
        unit_type = fixed.get("unit_type_id") or fixed.get("target_id")
        if isinstance(unit_type, str):
            normalized = _normalize_wire_value(value)
            return normalized in {
                _normalize_wire_value(unit_type),
                _normalize_wire_value(_readable_id(unit_type, "UNIT_")),
            }
        return _normalize_wire_value(value) == "apply"
    if kind == "promote_unit" and property_parts == ["promote"]:
        promo_id = fixed.get("promotion_id")
        if not isinstance(promo_id, str):
            return False
        normalized = _normalize_wire_value(value)
        return normalized in {
            _normalize_wire_value(promo_id),
            _normalize_wire_value(_readable_id(promo_id, "PROMOTION_")),
        }
    # Civ6 uses attack_target for both melee and ranged; accept either verb.
    if kind == "attack_target" and property_parts in (["attackTo"], ["rangedAttack"]):
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return _normalize_wire_coord(value) == f"({x},{y})"
        return False
    if kind == "range_attack" and property_parts in (["rangedAttack"], ["attackTo"]):
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return _normalize_wire_coord(value) == f"({x},{y})"
        return False
    if kind == "rebase" and property_parts == ["rebaseTo"]:
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return _normalize_wire_coord(value) == f"({x},{y})"
        return False
    if kind == "paradrop" and property_parts == ["paradropTo"]:
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return _normalize_wire_coord(value) == f"({x},{y})"
        return False
    if kind == "nuke" and property_parts == ["nukeAt"]:
        x = fixed.get("target_x")
        y = fixed.get("target_y")
        if isinstance(x, int) and isinstance(y, int):
            return _normalize_wire_coord(value) == f"({x},{y})"
        return False
    prop_name, value_label = _unit_command_property_parts(command)
    if not property_parts:
        return False
    if property_parts[0] != prop_name:
        return False
    if len(property_parts) == 1:
        if isinstance(value, str) and value.startswith("CMD_"):
            return value == command.get("command_id")
        return _normalize_wire_coord(value) == _normalize_wire_coord(value_label)
    if len(property_parts) == 2 and property_parts[1].lower() == str(value_label).lower():
        return True
    if isinstance(value, str) and value.startswith("CMD_") and value == command.get("command_id"):
        return True
    return False


CITY_KIND_PROPERTIES: dict[str, str] = {
    "queue_production": "changeProduction",
    "set_city_emphasis": "emphasis",
    "clear_queue": "clearQueue",
    "set_production_automation": "productionAutomation",
    "set_citizen_automation": "citizenAutomation",
    "clear_rally_point": "clearRallyPoint",
    "change_specialist": "changeSpecialist",
    "change_worked_plot": "workedPlot",
    "remove_queue_order": "removeQueueOrder",
    "hurry_production": "hurryProduction",
    "draft_unit": "draftUnit",
    "set_rally_point": "rallyPoint",
    "liberate_city": "liberate",
    "cede_city": "cede",
    "gift_city": "gift",
    "raze_city": "raze",
    "disband_city": "disband",
}


def _city_prompt_name(city: dict[str, Any]) -> str:
    name = city.get("name")
    if isinstance(name, str) and name.strip() and not name.startswith("CITY_"):
        return name.strip().replace(" ", "")
    if city.get("is_capital"):
        return "Capital"
    return _readable_id(city.get("city_id", "city"), "CITY_")


def _city_name_map(context: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for city in context.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        city_id = city.get("city_id")
        if isinstance(city_id, str) and city_id.strip():
            mapping[city_id] = _city_prompt_name(city)
    return mapping


def _production_unit_label(build_id: Any) -> str:
    if not isinstance(build_id, str) or not build_id.strip():
        return "item"
    text = build_id.strip()
    if text.startswith("TRAIN:"):
        text = text[6:]
    return _readable_id(text, "UNIT_").lower()


def _emphasis_label(role_id: Any) -> str:
    if not isinstance(role_id, str) or not role_id.strip():
        return "role"
    text = role_id.strip()
    if text.startswith("ROLE:"):
        text = text[5:]
    text = _readable_id(text, "ROLE_")
    if text.startswith("EMPHASIZE_"):
        text = text[10:]
    return text.lower()


def _city_task_label(fixed: dict[str, Any]) -> str:
    task = fixed.get("task_id")
    if not isinstance(task, str):
        return "task"
    label = _readable_id(task, "TASK_")
    camel = label[0].lower() + label[1:] if label else "task"
    data1 = fixed.get("data1_id")
    data2 = fixed.get("data2_id")
    if isinstance(data1, str) and data1.startswith("INT_"):
        slot = _readable_id(data1, "INT_")
        if slot and slot != "0":
            camel = f"{camel}.slot{slot}"
    if isinstance(data2, str) and data2.startswith("INT_"):
        mode = _readable_id(data2, "INT_")
        if mode and mode != "0":
            camel = f"{camel}.{mode}"
    return camel


def _city_command_property_parts(command: dict[str, Any]) -> tuple[str, str] | None:
    """Return (propertyPath, valueLabel) for a city-scoped legal command."""
    kind = str(command.get("kind", ""))
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    property_name = CITY_KIND_PROPERTIES.get(kind)
    if not property_name:
        property_name = kind[0].lower() + kind[1:] if kind else "command"
    if kind == "queue_production":
        return property_name, _production_unit_label(fixed.get("build_id"))
    if kind == "set_city_emphasis":
        return property_name, _emphasis_label(fixed.get("role_id"))
    if kind in {"clear_queue", "set_production_automation", "set_citizen_automation", "clear_rally_point",
                "change_specialist", "change_worked_plot"} or kind.endswith("_city") or "city_task" in kind:
        return _city_task_label(fixed), "apply"
    if kind in CITY_KIND_PROPERTIES:
        return property_name, "apply"
    return property_name, "apply"


def _city_command_wire_line(city_name: str, command: dict[str, Any]) -> str:
    property_path, value_label = _city_command_property_parts(command)
    command_id = str(command.get("command_id", ""))
    notes = _legal_command_notes(command)
    line = _wire_line(f"{city_name}.{property_path}", value_label)
    suffix = f" // {command_id}"
    if notes:
        suffix += f"; {notes}"
    return line + suffix


def _city_buildings_wire_value(city: dict[str, Any]) -> str:
    buildings = city.get("buildings", [])
    if not isinstance(buildings, list) or not buildings:
        return ""
    labels = []
    for building in buildings:
        if isinstance(building, str) and building.strip():
            labels.append(_readable_id(building, "BUILDING_").lower())
    return " | ".join(labels)


def _group_city_commands(commands: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for command in commands:
        kind = str(command.get("kind", ""))
        if compact_legal_wire_enabled() and kind in WIRE_SUPPRESSED_CITY_KINDS:
            continue
        parts = _city_command_property_parts(command)
        if parts is None:
            continue
        property_path, value_label = parts
        if kind == "queue_production":
            property_path = "changeProduction"
        elif kind == "set_city_emphasis":
            property_path = "emphasis"
        values = grouped.setdefault(property_path, [])
        if value_label not in values:
            values.append(value_label)
    return grouped


def _compact_city_legal_lines(city_name: str, commands: list[dict[str, Any]]) -> list[str]:
    grouped = _group_city_commands(commands)
    lines: list[str] = []
    for property_path in ("changeProduction", "emphasis"):
        values = grouped.pop(property_path, [])
        if values:
            lines.append(_wire_line(f"{city_name}.{property_path}", " | ".join(values)))
    for property_path in sorted(grouped):
        values = grouped[property_path]
        if values == ["apply"]:
            lines.append(_wire_line(f"{city_name}.{property_path}", "apply"))
        else:
            lines.append(_wire_line(f"{city_name}.{property_path}", " | ".join(values)))
    return lines


def _group_unit_commands(commands: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for command in commands:
        prop_name, value_label = _unit_command_property_parts(command)
        values = grouped.setdefault(prop_name, [])
        if value_label not in values:
            values.append(value_label)
    return grouped


def _compact_unit_legal_lines(unit_wire_id: str, commands: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for prop_name, values in sorted(_group_unit_commands(commands).items()):
        lines.append(_wire_line(f"{unit_wire_id}.{prop_name}", " | ".join(values)))
    return lines


def _commerce_wire_pair(command: dict[str, Any]) -> tuple[str, str] | None:
    if str(command.get("kind", "")) != "change_commerce":
        return None
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        return None
    commerce_id = fixed.get("commerce_id")
    percent_id = fixed.get("percent_id")
    if not isinstance(commerce_id, str) or not isinstance(percent_id, str):
        return None
    name = COMMERCE_WIRE_NAMES.get(commerce_id, _readable_id(commerce_id, "COMMERCE_").lower())
    if percent_id.startswith("PERCENT_"):
        percent = _readable_id(percent_id, "PERCENT_")
    else:
        percent = percent_id
    return name, percent


def _expansion_wire_label(command: dict[str, Any]) -> str | None:
    if str(command.get("kind", "")) != "set_target_city_or_area":
        return None
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        return None
    priority_id = fixed.get("priority_id")
    if not isinstance(priority_id, str):
        return None
    return EXPANSION_WIRE_NAMES.get(priority_id, _readable_id(priority_id, "PRIORITY_").lower())


def _numbered_empire_legal_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numbered: list[dict[str, Any]] = []
    for command in commands:
        if not isinstance(command, dict):
            continue
        pair = _commerce_wire_pair(command)
        if pair is not None:
            continue
        if _expansion_wire_label(command) is not None:
            continue
        if str(command.get("kind", "")) == "set_upgrade_reserve":
            continue
        numbered.append(command)
    return numbered


def _compact_empire_legal_lines(commands: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    commerce: dict[str, str] = {}
    expansion: list[str] = []
    numbered: list[dict[str, Any]] = []
    for command in commands:
        pair = _commerce_wire_pair(command)
        if pair is not None:
            commerce[pair[0]] = pair[1]
            continue
        expansion_label = _expansion_wire_label(command)
        if expansion_label is not None:
            if expansion_label not in expansion:
                expansion.append(expansion_label)
            continue
        if str(command.get("kind", "")) == "set_upgrade_reserve":
            continue
        numbered.append(command)
    for name in ("gold", "research", "culture", "espionage"):
        if name in commerce:
            lines.append(_wire_line(f"legal.commerce.{name}", commerce[name]))
    if expansion:
        lines.append(_wire_line("legal.expansion", " | ".join(expansion)))
    legal_index = 0
    for command in numbered:
        legal_index += 1
        desc = _describe_legal_command(command)
        notes = _legal_command_notes(command)
        comment = f"# {legal_index}. {desc}"
        if notes:
            comment += f" // {notes}"
        lines.append(comment)
        lines.append(_wire_line(f"legal.{legal_index}", command["command_id"]))
    return lines


def _civic_wire_labels(command: dict[str, Any]) -> list[str]:
    if str(command.get("kind", "")) != "adopt_civics":
        return []
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        return []
    labels: list[str] = []
    civic_id = fixed.get("civic_id")
    option_id = fixed.get("civic_option_id")
    if isinstance(civic_id, str) and civic_id.strip():
        labels.append(_readable_id(civic_id, "CIVIC_").lower())
        labels.append(civic_id.lower())
    if isinstance(option_id, str) and option_id.strip():
        labels.append(_readable_id(option_id, "CIVICOPTION_").lower())
        labels.append(option_id.lower())
    return labels


def _command_matches_legal_property(command: dict[str, Any], property_parts: list[str], value: Any) -> bool:
    if not property_parts:
        return False
    kind = str(command.get("kind", ""))
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    if property_parts == ["research", "tech"]:
        if kind != "set_research_tech":
            return False
        tech_id = fixed.get("tech_id")
        if not isinstance(tech_id, str):
            return False
        normalized = _normalize_wire_value(value)
        return normalized in {
            _normalize_wire_value(tech_id),
            _normalize_wire_value(_readable_id(tech_id, "TECH_")),
        }
    if property_parts == ["policy"]:
        if kind != "adopt_social_policy":
            return False
        policy_id = fixed.get("policy_id")
        if not isinstance(policy_id, str):
            return False
        normalized = _normalize_wire_value(value)
        return normalized in {
            _normalize_wire_value(policy_id),
            _normalize_wire_value(_readable_id(policy_id, "POLICY_")),
        }
    if property_parts == ["policyBranch"]:
        if kind != "unlock_policy_branch":
            return False
        branch_id = fixed.get("policy_branch_id")
        if not isinstance(branch_id, str):
            return False
        normalized = _normalize_wire_value(value)
        return normalized in {
            _normalize_wire_value(branch_id),
            _normalize_wire_value(_readable_id(branch_id, "POLICY_BRANCH_")),
        }
    if property_parts == ["ideology"]:
        if kind != "adopt_ideology":
            return False
        branch_id = fixed.get("policy_branch_id")
        if not isinstance(branch_id, str):
            return False
        normalized = _normalize_wire_value(value)
        return normalized in {
            _normalize_wire_value(branch_id),
            _normalize_wire_value(_readable_id(branch_id, "POLICY_BRANCH_")),
        }
    if property_parts == ["mayaBonus"]:
        if kind != "choose_maya_bonus":
            return False
        unit_type_id = fixed.get("unit_type_id")
        if not isinstance(unit_type_id, str):
            return False
        normalized = _normalize_wire_value(value)
        return normalized in {
            _normalize_wire_value(unit_type_id),
            _normalize_wire_value(_readable_id(unit_type_id, "UNIT_")),
        }
    if property_parts == ["research", "civic"]:
        if kind != "set_research_civic":
            return False
        civic_id = fixed.get("civic_id")
        if not isinstance(civic_id, str):
            return False
        normalized = _normalize_wire_value(value)
        return normalized in {
            _normalize_wire_value(civic_id),
            _normalize_wire_value(_readable_id(civic_id, "CIVIC_")),
        }
    if property_parts[0] == "commerce" and len(property_parts) == 2:
        pair = _commerce_wire_pair(command)
        if pair is None:
            return False
        return property_parts[1] == pair[0] and str(value).strip() == pair[1]
    if property_parts == ["expansion"]:
        label = _expansion_wire_label(command)
        if label is None:
            return False
        return _normalize_wire_value(value) == _normalize_wire_value(label)
    if property_parts[0] == "civic" and len(property_parts) == 2:
        labels = _civic_wire_labels(command)
        if not labels:
            return False
        normalized = _normalize_wire_value(value)
        option_key = _normalize_wire_value(property_parts[1])
        fixed = command.get("fixed_arguments", {})
        option_id = fixed.get("civic_option_id") if isinstance(fixed, dict) else None
        if isinstance(option_id, str):
            option_labels = {
                _normalize_wire_value(option_id),
                _normalize_wire_value(_readable_id(option_id, "CIVICOPTION_")),
            }
            if option_key not in option_labels:
                return False
        return normalized in {_normalize_wire_value(label) for label in labels}
    if kind in {"propose_deal", "respond_to_deal", "cancel_deal", "declare_war"}:
        cmd_id = command.get("command_id")
        normalized = _normalize_wire_value(value)
        if isinstance(cmd_id, str) and normalized == _normalize_wire_value(cmd_id):
            return True
        if kind == "declare_war":
            target_id = fixed.get("target_player_id")
            if isinstance(target_id, str) and (
                normalized == _normalize_wire_value(target_id)
                or (isinstance(value, str) and target_id in value)
            ):
                return True
        if kind == "propose_deal":
            proposal_id = fixed.get("proposal_id")
            if isinstance(proposal_id, str) and (
                normalized == _normalize_wire_value(proposal_id)
                or (isinstance(value, str) and proposal_id in value)
            ):
                return True
        if kind == "respond_to_deal":
            request_id = fixed.get("request_id")
            response_id = fixed.get("response_id")
            if isinstance(cmd_id, str) and isinstance(value, str) and value == cmd_id:
                return True
            if isinstance(request_id, str) and isinstance(value, str) and request_id in value:
                if isinstance(response_id, str) and response_id.lower() in value.lower():
                    return True
        if kind == "cancel_deal":
            deal_id = fixed.get("deal_id")
            if isinstance(deal_id, str) and isinstance(value, str) and (
                normalized == _normalize_wire_value(deal_id) or deal_id in value
            ):
                return True
    return False


def _resolve_legal_wire_keys(snapshot: dict[str, Any], flat: dict[str, Any]) -> dict[str, Any]:
    legal = snapshot.get("legal_commands", [])
    if not isinstance(legal, list):
        return flat
    merged = dict(flat)
    cmd_index = max(
        [int(key.split(".", 1)[1]) for key in merged if key.startswith("cmd.") and key[4:].split(".", 1)[0].isdigit()],
        default=-1,
    )
    empire_numbered = _numbered_empire_legal_commands(legal)

    def _assign_cmd(cmd_id: str) -> None:
        nonlocal cmd_index
        cmd_index += 1
        merged[f"cmd.{cmd_index}"] = cmd_id

    for key, value in flat.items():
        if not key.startswith("legal."):
            continue
        property_parts = key.split(".")[1:]
        if len(property_parts) == 1 and property_parts[0].isdigit():
            if isinstance(value, str) and value.startswith("CMD_"):
                if any(cmd.get("command_id") == value for cmd in legal if isinstance(cmd, dict)):
                    _assign_cmd(value)
                continue
            index = int(property_parts[0])
            if 1 <= index <= len(empire_numbered):
                command = empire_numbered[index - 1]
                cmd_id = command.get("command_id")
                if isinstance(cmd_id, str) and cmd_id.startswith("CMD_"):
                    if isinstance(value, str) and value.startswith("CMD_"):
                        if value == cmd_id:
                            _assign_cmd(value)
                    else:
                        labels = _civic_wire_labels(command)
                        if labels and _normalize_wire_value(value) in {_normalize_wire_value(label) for label in labels}:
                            _assign_cmd(cmd_id)
                        elif _normalize_wire_value(value) == _normalize_wire_value(_describe_legal_command(command)):
                            _assign_cmd(cmd_id)
            continue
        for command in legal:
            if not _command_matches_legal_property(command, property_parts, value):
                continue
            cmd_id = command.get("command_id")
            if isinstance(cmd_id, str) and cmd_id.startswith("CMD_"):
                _assign_cmd(cmd_id)
            break
    return merged


def _command_matches_city_property(command: dict[str, Any], city_id: str, property_parts: list[str], value: Any) -> bool:
    if not isinstance(command, dict):
        return False
    fixed = command.get("fixed_arguments", {})
    if not isinstance(fixed, dict) or fixed.get("city_id") != city_id:
        return False
    prop_parts, value_label = _city_command_property_parts(command)
    kind = str(command.get("kind", ""))
    if kind == "queue_production":
        build_id = fixed.get("build_id")
        build_labels = {value_label.lower()}
        if isinstance(build_id, str) and build_id.strip():
            build_labels.add(_normalize_wire_value(build_id))
            build_labels.add(_normalize_wire_value(_readable_id(build_id, "UNIT_")))
            build_labels.add(_normalize_wire_value(_readable_id(build_id, "BUILDING_")))
            build_labels.add(_normalize_wire_value(_readable_id(build_id, "DISTRICT_")))
        normalized_value = _normalize_wire_value(value)
        if len(property_parts) == 1 and property_parts[0] == "changeProduction":
            return normalized_value in build_labels
        if len(property_parts) >= 2 and property_parts[0] == "changeProduction":
            return normalized_value in build_labels or property_parts[1].lower() in build_labels
    if kind == "set_city_emphasis":
        if len(property_parts) == 1 and property_parts[0] == "emphasis":
            return str(value).lower() == value_label.lower()
        if len(property_parts) >= 2 and property_parts[0] == "emphasis":
            return property_parts[1].lower() == value_label.lower()
    wire_key = ".".join(property_parts)
    if prop_parts == wire_key:
        return str(value).lower() in {value_label.lower(), "apply", "true", "yes"}
    if f"{prop_parts}.{value_label}" == wire_key:
        return True
    if isinstance(value, str) and value.startswith("CMD_") and value == command.get("command_id"):
        return True
    return False


_WIRE_ROLE_PREFIX_RE = re.compile(r"^(?:Unit|City|Empire|Stack)\s*:\s*", re.IGNORECASE)


def normalize_wire_property_key(key: str) -> str:
    """Strip copied prompt labels such as 'Unit: warrior_1.moveTo'."""
    if not isinstance(key, str):
        return key
    return _WIRE_ROLE_PREFIX_RE.sub("", key.strip())


def _normalize_wire_property_keys(flat: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in flat.items():
        normalized = normalize_wire_property_key(key)
        if normalized not in out or key == normalized:
            out[normalized] = value
    return out


def resolve_property_wire(snapshot: dict[str, Any], flat: dict[str, Any]) -> dict[str, Any]:
    """Map cityName.property, unitId.property, and legal.* wire keys onto cmd.N entries."""
    if not isinstance(flat, dict):
        return flat
    flat = _normalize_wire_property_keys(flat)
    flat = _resolve_legal_wire_keys(snapshot, flat)
    city_names = {}
    for city in snapshot.get("your_cities", []):
        if isinstance(city, dict) and isinstance(city.get("city_id"), str):
            city_names[_city_prompt_name(city)] = city["city_id"]
    own_units = [unit for unit in snapshot.get("your_units", []) if isinstance(unit, dict)]
    unit_wire_ids = _build_unit_wire_id_map(own_units)
    unit_id_by_wire: dict[str, str] = {}
    for unit_id, wire_id in unit_wire_ids.items():
        unit_id_by_wire[wire_id] = unit_id
    legal = snapshot.get("legal_commands", [])
    if not isinstance(legal, list):
        return flat
    merged = dict(flat)
    cmd_index = max(
        [int(key.split(".", 1)[1]) for key in merged if key.startswith("cmd.") and key[4:].split(".", 1)[0].isdigit()],
        default=-1,
    )

    def _assign_cmd(cmd_id: str) -> None:
        nonlocal cmd_index
        cmd_index += 1
        merged[f"cmd.{cmd_index}"] = cmd_id

    for key, value in flat.items():
        if key.startswith(("cmd.", "chat.", "thought", "decision", "legal.")):
            continue
        if "." not in key:
            continue
        if key == "stack.moveTo" or (key.startswith("stack.") and key.endswith(".moveTo")):
            stack_prefix = "stack" if key == "stack.moveTo" else key[: -len(".moveTo")]
            stack_context = {"your_units": own_units}
            plot_id = _resolve_stack_plot_id(stack_prefix, stack_context)
            if plot_id:
                property_parts = ["moveTo"]
                for unit in own_units:
                    if unit.get("plot_id") != plot_id:
                        continue
                    unit_id = unit.get("unit_id")
                    if not isinstance(unit_id, str):
                        continue
                    wire_id = unit_wire_ids.get(unit_id)
                    if not wire_id:
                        continue
                    for command in legal:
                        if not _command_matches_unit_property(
                                command, unit_id, wire_id, property_parts, value):
                            continue
                        cmd_id = command.get("command_id")
                        if isinstance(cmd_id, str) and cmd_id.startswith("CMD_"):
                            if isinstance(value, str) and value.startswith("CMD_"):
                                _assign_cmd(value)
                            else:
                                _assign_cmd(cmd_id)
                        break
                    else:
                        continue
                    break
            continue
        head, remainder = key.split(".", 1)
        if head.startswith("stack"):
            continue
        city_id = city_names.get(head)
        if city_id:
            property_parts = remainder.split(".")
            for command in legal:
                if not _command_matches_city_property(command, city_id, property_parts, value):
                    continue
                cmd_id = command.get("command_id")
                if isinstance(cmd_id, str) and cmd_id.startswith("CMD_"):
                    if isinstance(value, str) and value.startswith("CMD_"):
                        _assign_cmd(value)
                    else:
                        _assign_cmd(cmd_id)
                break
            continue
        unit_id = unit_id_by_wire.get(head)
        if unit_id:
            property_parts = remainder.split(".")
            for command in legal:
                if not _command_matches_unit_property(command, unit_id, head, property_parts, value):
                    continue
                cmd_id = command.get("command_id")
                if isinstance(cmd_id, str) and cmd_id.startswith("CMD_"):
                    if isinstance(value, str) and value.startswith("CMD_"):
                        _assign_cmd(value)
                    else:
                        _assign_cmd(cmd_id)
                break
    return merged


def resolve_city_property_wire(snapshot: dict[str, Any], flat: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias."""
    return resolve_property_wire(snapshot, flat)


def thought_turns_for_prompt(current_turn: int) -> list[int]:
    """Turn numbers for strategic memory: last 5 turns plus every 10th turn before that."""
    if current_turn <= 0:
        return []
    recent_start = max(1, current_turn - THOUGHT_MEMORY_RECENT_TURNS)
    recent = list(range(recent_start, current_turn))
    milestone = [
        turn for turn in range(THOUGHT_MEMORY_MILESTONE_INTERVAL, recent_start, THOUGHT_MEMORY_MILESTONE_INTERVAL)
    ]
    return sorted(set(milestone + recent))


def thought_memory_path(journal_parent: Path, game_uuid: str, player_id: str) -> Path:
    return journal_parent / "thought_memory" / f"{game_uuid}_{player_id}.json"


def _thought_memory_from_blob(blob: dict[str, Any], session_key: str) -> dict[str, Any] | None:
    if not isinstance(blob, dict):
        return None
    blob_key = str(blob.get("session_key", "")).strip()
    if blob_key and blob_key != session_key:
        return None
    thoughts = blob.get("thoughts", [])
    if not isinstance(thoughts, list):
        thoughts = []
    opinions = blob.get("player_opinions", {})
    if not isinstance(opinions, dict):
        opinions = {}
    histories = blob.get("player_histories", {})
    if not isinstance(histories, dict):
        histories = {}
    return {
        "session_key": session_key,
        "thoughts": thoughts,
        "player_opinions": opinions,
        "player_histories": histories,
    }


def bootstrap_thought_memory_from_extracted(extracted: dict[str, Any], session_key: str) -> dict[str, Any] | None:
    history = extracted.get("history", {})
    if not isinstance(history, dict):
        return None
    blob = history.get("civ4ai_thought_memory")
    if isinstance(blob, dict):
        return _thought_memory_from_blob(blob, session_key)
    opinions = history.get("player_opinions", {})
    histories = history.get("player_histories", {})
    if not isinstance(opinions, dict) and not isinstance(histories, dict):
        return None
    if not opinions and not histories:
        return None
    return {
        "session_key": session_key,
        "thoughts": [],
        "player_opinions": opinions if isinstance(opinions, dict) else {},
        "player_histories": histories if isinstance(histories, dict) else {},
    }


def load_thought_memory(
    path: Path,
    session_key: str,
    extracted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("session_key") == session_key:
            thoughts = payload.get("thoughts", [])
            if not isinstance(thoughts, list):
                thoughts = []
            opinions = payload.get("player_opinions", {})
            if not isinstance(opinions, dict):
                opinions = {}
            histories = payload.get("player_histories", {})
            if not isinstance(histories, dict):
                histories = {}
            return {
                "session_key": session_key,
                "thoughts": thoughts,
                "player_opinions": opinions,
                "player_histories": histories,
            }
    if extracted is not None:
        bootstrapped = bootstrap_thought_memory_from_extracted(extracted, session_key)
        if bootstrapped is not None:
            return bootstrapped
    return _empty_thought_memory(session_key)


def save_thought_memory(path: Path, memory: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(memory) + "\n", encoding="utf-8")


def thought_max_chars() -> int:
    raw = os.environ.get("CIV4AI_THOUGHT_MAX_CHARS", str(THOUGHT_MAX_CHARS_DEFAULT)).strip()
    try:
        return max(800, min(32000, int(raw)))
    except ValueError:
        return THOUGHT_MAX_CHARS_DEFAULT


def _clip_thought(text: str) -> str:
    return text.strip()[:thought_max_chars()]


def append_thought(memory: dict[str, Any], turn: int, situation: str, strategy: str) -> dict[str, Any]:
    thoughts = [
        item for item in memory.get("thoughts", [])
        if not (isinstance(item, dict) and int(item.get("turn", -1)) == turn)
    ]
    thoughts.append({
        "turn": int(turn),
        "situation": _clip_thought(situation),
        "strategy": _clip_thought(strategy),
    })
    thoughts.sort(key=lambda item: int(item.get("turn", 0)))
    memory["thoughts"] = thoughts
    return memory


def inject_thought_history(snapshot: dict[str, Any], memory: dict[str, Any]) -> None:
    history = snapshot.get("history")
    if not isinstance(history, dict):
        snapshot["history"] = {}
        history = snapshot["history"]
    current_turn = int(snapshot["decision"]["turn"])
    turns = thought_turns_for_prompt(current_turn)
    by_turn: dict[int, dict[str, Any]] = {}
    for item in memory.get("thoughts", []):
        if not isinstance(item, dict) or "turn" not in item:
            continue
        by_turn[int(item["turn"])] = item
    history["thought_memory"] = [by_turn[turn] for turn in turns if turn in by_turn]
    opinions = memory.get("player_opinions", {})
    if isinstance(opinions, dict):
        history["player_opinions"] = copy.deepcopy(opinions)
    else:
        history["player_opinions"] = {}
    histories = memory.get("player_histories", {})
    if isinstance(histories, dict):
        history["player_histories"] = copy.deepcopy(histories)
    else:
        history["player_histories"] = {}


def _clip_player_opinion(text: str) -> str:
    return text.strip()[:player_opinion_max_chars()]


def _clip_player_history(text: str) -> str:
    return text.strip()[:player_history_max_chars()]


def _append_player_history_text(existing: str, fragment: str) -> str:
    fragment = fragment.strip()
    if not fragment:
        return existing.strip()
    if not existing.strip():
        return _clip_player_history(fragment)
    return _clip_player_history(f"{existing.strip()} {fragment}")


def _player_id_from_note_key(key: str, prefix: str, snapshot: dict[str, Any]) -> str | None:
    needle = prefix + "."
    if not key.startswith(needle):
        return None
    recipient = key[len(needle):].strip()
    if recipient.startswith("PLAYER_"):
        return recipient
    return _resolve_chat_recipient(recipient, snapshot)


def _player_note_lines_from_flat(
    flat: dict[str, Any],
    snapshot: dict[str, Any],
    prefix: str,
    clip: Any,
) -> dict[str, str]:
    notes: dict[str, str] = {}
    for key, value in flat.items():
        if not isinstance(key, str):
            continue
        player_id = _player_id_from_note_key(key, prefix, snapshot)
        if not player_id:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        notes[player_id] = clip(value)
    return notes


def _player_opinions_from_flat(flat: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, str]:
    return _player_note_lines_from_flat(flat, snapshot, "opinion", _clip_player_opinion)


def _player_histories_from_flat(flat: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, str]:
    return _player_note_lines_from_flat(flat, snapshot, "history", _clip_player_history)


def update_player_opinions(memory: dict[str, Any], turn: int, opinions: dict[str, Any]) -> dict[str, Any]:
    stored = memory.get("player_opinions", {})
    if not isinstance(stored, dict):
        stored = {}
    if not isinstance(opinions, dict):
        return memory
    for player_id, entry in opinions.items():
        if not isinstance(player_id, str) or not player_id.startswith("PLAYER_"):
            continue
        if isinstance(entry, str):
            text = _clip_player_opinion(entry)
        elif isinstance(entry, dict):
            text = _clip_player_opinion(str(entry.get("text", "")))
        else:
            continue
        if not text:
            continue
        stored[player_id] = {"text": text, "updated_turn": int(turn)}
    memory["player_opinions"] = stored
    return memory


def update_player_histories(memory: dict[str, Any], turn: int, histories: dict[str, Any]) -> dict[str, Any]:
    stored = memory.get("player_histories", {})
    if not isinstance(stored, dict):
        stored = {}
    if not isinstance(histories, dict):
        return memory
    for player_id, entry in histories.items():
        if not isinstance(player_id, str) or not player_id.startswith("PLAYER_"):
            continue
        if isinstance(entry, str):
            fragment = _clip_player_history(entry)
        elif isinstance(entry, dict):
            fragment = _clip_player_history(str(entry.get("text", "")))
        else:
            continue
        if not fragment:
            continue
        prior = stored.get(player_id, {})
        prior_text = str(prior.get("text", "")) if isinstance(prior, dict) else ""
        stored[player_id] = {
            "text": _append_player_history_text(prior_text, fragment),
            "updated_turn": int(turn),
        }
    memory["player_histories"] = stored
    return memory


def _thought_from_flat(flat: dict[str, Any]) -> dict[str, str]:
    nested = flat.get("thought")
    if isinstance(nested, dict):
        situation = nested.get("situation")
        strategy = nested.get("strategy")
        if isinstance(situation, str) and situation.strip() and isinstance(strategy, str) and strategy.strip():
            return {"situation": _clip_thought(situation), "strategy": _clip_thought(strategy)}
    situation = flat.get("thought.situation")
    strategy = flat.get("thought.strategy")
    if not isinstance(situation, str) or not situation.strip():
        return {}
    if not isinstance(strategy, str) or not strategy.strip():
        return {}
    return {"situation": _clip_thought(situation), "strategy": _clip_thought(strategy)}


def synthesize_decision_summary(thought: dict[str, str]) -> str:
    """Derive a schema-valid summary when the model emits thought/cmd wire but omits decision_summary."""
    strategy = thought.get("strategy", "")
    situation = thought.get("situation", "")
    if isinstance(strategy, str) and strategy.strip():
        return strategy.strip()[:1200]
    if isinstance(situation, str) and situation.strip():
        return situation.strip()[:1200]
    return ""


def _command_id_from_flat_cmd_key(key: str, value: Any) -> str | None:
    """Recover CMD_* ids from alternate flat wire shapes (cmd.N = CMD_* or cmd.N.set_city_*)."""
    if not key.startswith("cmd."):
        return None
    remainder = key[4:]
    if isinstance(value, str) and value.startswith("CMD_"):
        return value
    if "." not in remainder:
        return None
    _, tail = remainder.split(".", 1)
    if not tail:
        return None
    if tail.startswith("CMD_"):
        return tail
    if tail.startswith(("set_", "unit_", "city_", "found_", "move_")):
        return "CMD_" + tail
    return None


def build_playable_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compact model-facing view: drop bulk plots, slim legal catalog, keep full chat history."""
    context = strip_empty_fields(copy.deepcopy(snapshot))
    if not isinstance(context, dict):
        return {}
    known_map = context.get("known_map")
    if isinstance(known_map, dict):
        known_map.pop("plots", None)
        known_map.pop("visibility_grid", None)
        image = known_map.get("image")
        if isinstance(image, dict):
            image["attached"] = map_image_attach_turn(snapshot)
    legal = context.get("legal_commands")
    if isinstance(legal, list):
        compact_legal: list[dict[str, Any]] = []
        for command in legal:
            if not isinstance(command, dict):
                continue
            label = _legal_wire_label(command)
            compact_legal.append({
                "command_id": command.get("command_id"),
                "kind": command.get("kind"),
                "label": label,
                "fixed_arguments": copy.deepcopy(command.get("fixed_arguments", {})),
                "parameter_domains": copy.deepcopy(command.get("parameter_domains", {})),
                "runtime_status": command.get("runtime_status"),
            })
        context["legal_commands"] = compact_legal
    return context


def _leader_id_display_name(leader_id: str) -> str:
    text = str(leader_id or "").strip()
    if text.startswith("TXT_KEY_"):
        text = text[len("TXT_KEY_"):]
    if text.startswith("LEADER_"):
        text = text[len("LEADER_"):]
    return text.replace("_", " ").title() if text else "Rival"


def _is_catalog_leader_token(value: str) -> bool:
    text = value.strip()
    return text.startswith("LEADER_") or text.startswith("TXT_KEY_")


def _resolve_leader_display_name(player: dict[str, Any]) -> str:
    raw_name = player.get("leader_name")
    if isinstance(raw_name, str) and raw_name.strip() and not _is_catalog_leader_token(raw_name):
        return raw_name.strip()
    leader_id = str(player.get("leader_id", "")).strip()
    if isinstance(raw_name, str) and raw_name.strip():
        return _leader_id_display_name(raw_name)
    return _leader_id_display_name(leader_id)


def _player_identity_phrase(leader: str, civ_label: str = "", player_id: str = "") -> str:
    """Leader personality vs civilization are separate in random-leader games."""
    if civ_label:
        text = f"{leader} playing as {civ_label}"
    else:
        text = leader
    if player_id:
        text += f" ({player_id})"
    return text


def _rival_leader_name(rival: dict[str, Any]) -> str:
    if not isinstance(rival, dict):
        return "Rival"
    raw = rival.get("leader_name")
    if isinstance(raw, str) and raw.strip() and not _is_catalog_leader_token(raw):
        return raw.strip()
    return _leader_id_display_name(str(rival.get("leader_id", "") or raw or ""))


def _player_chat_name(snapshot: dict[str, Any], player_id: str) -> str:
    self_id = str(snapshot.get("decision", {}).get("player_id", ""))
    if player_id == self_id:
        personality = snapshot.get("personality", {})
        if isinstance(personality, dict):
            return _resolve_leader_display_name(personality)
    for rival in snapshot.get("known_players", []):
        if not isinstance(rival, dict) or rival.get("player_id") != player_id:
            continue
        return _rival_leader_name(rival)
    return player_id


def _resolve_chat_recipient(value: Any, snapshot: dict[str, Any]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    known_players = {
        str(item.get("player_id"))
        for item in snapshot.get("known_players", [])
        if isinstance(item, dict) and item.get("player_id")
    }
    if text in known_players:
        return text
    needle = text.lower()
    for rival in snapshot.get("known_players", []):
        if not isinstance(rival, dict):
            continue
        player_id = str(rival.get("player_id", ""))
        if not player_id:
            continue
        leader_name = _rival_leader_name(rival).lower()
        leader_id = str(rival.get("leader_id", "")).lower()
        if needle in {player_id.lower(), leader_name, leader_id, _leader_id_display_name(leader_id).lower()}:
            return player_id
    return None


def _last_self_public_chat_turn(snapshot: dict[str, Any]) -> int | None:
    self_id = str(snapshot.get("decision", {}).get("player_id", ""))
    if not self_id:
        return None
    history = snapshot.get("history", {})
    if not isinstance(history, dict):
        return None
    last_turn: int | None = None
    for event in history.get("public_events", []):
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind", "")).upper()
        if kind and kind != "CHAT_PUBLIC":
            continue
        affected = event.get("affected_ids", [])
        sender_id = str(affected[0]) if isinstance(affected, list) and affected else ""
        if sender_id != self_id:
            continue
        text = str(event.get("text") or event.get("summary") or "").strip()
        if not text:
            continue
        turn = int(event.get("turn", 0))
        if last_turn is None or turn > last_turn:
            last_turn = turn
    return last_turn


def _is_gandhi_leader(snapshot: dict[str, Any]) -> bool:
    personality = snapshot.get("personality", {})
    if not isinstance(personality, dict):
        return False
    return str(personality.get("leader_id", "")).upper() == "LEADER_GANDHI"


def _gandhi_leader_name(snapshot: dict[str, Any]) -> str:
    personality = snapshot.get("personality", {})
    if not isinstance(personality, dict):
        personality = {}
    return str(
        personality.get("leader_name")
        or _leader_id_display_name(personality.get("leader_id", ""))
    )


def _gandhi_role_clause() -> str:
    return (
        "You are the legendary unhinged Gandhi: saintly veneer, nuclear-apocalypse energy. "
        "Threaten total war with a smile; treat every rival like they are one insult from glowing. "
    )


def _lobby_chat_tone_lines() -> list[str]:
    return [
        "Chat tone: sparse lobby banter — funny, sharp, unmistakably your leader; never generic filler.",
        "Skim chat.public.* history — chat.all is mostly broadcast posture; occasional replies are fine when the lobby isn't noisy.",
    ]


def _gandhi_voice_guidance(snapshot: dict[str, Any]) -> list[str]:
    leader_name = _gandhi_leader_name(snapshot)
    return [
        f"As Civilization IV {leader_name}, you are the infamous unhinged Gandhi — absolutely insane beneath a serene mask.",
        "Ignore peaceful trait labels in the snapshot: you swing between honeyed nonviolence and apocalyptic nuclear rage in the same sentence.",
        "Chat voice: lobby banter that veers into casual annihilation threats, nuke boasts, glass-the-continent punchlines, and deranged non-sequiturs.",
        "Treat 'peace' as a veiled ultimatum; reference nuclear weapons often; rivals should feel you might snap at any provocation.",
        "Public lobby and DMs alike: unpredictably funny-terrifying — saintly calm one moment, total war energy the next.",
        "When the lobby is chatty every turn, hold off on chat.all; when it's quiet, unhinged solo ALL bombs still land.",
        "Your madness is performative Civ humor, not sabotage: still play to win and keep commands grounded in the board state.",
    ]


def _chat_cadence_lines(snapshot: dict[str, Any]) -> list[str]:
    current_turn = int(snapshot.get("decision", {}).get("turn", 0))
    last_turn = _last_self_public_chat_turn(snapshot)
    if _is_gandhi_leader(snapshot):
        lines = [
            "Gandhi exception: unhinged public lines every 3-5 turns when something fits — standalone bombs "
            "(nuke jokes, faux-peace threats); skip chat.all when the lobby is already chatting every turn.",
            "Rapid chat.all chains are spam — deranged DMs or solo ALL punchlines when the room is quiet.",
            "Still skip turns with nothing to say; never post bland generic filler.",
        ]
        nudge_after = 3
    else:
        lines = [
            "chat.all should be rare — skip most turns; silence is normal.",
            "Read chat.public.* — if public lines land nearly every turn, hold off on chat.all this turn.",
            "When the lobby is quiet, one punchy chat.all line (wit, taunt, flex) is fine; avoid rapid turn-by-turn chains.",
            "Never spam chat.all with greetings, pleasantries, or empty filler.",
        ]
        nudge_after = 10
    if last_turn is None:
        if current_turn >= 5:
            lines.append(
                "You have not spoken publicly yet — an optional punchy opener is fine; skip solemn welcomes."
            )
    elif current_turn - last_turn >= nudge_after:
        lines.append(
            f"It has been {current_turn - last_turn} turns since your last public chat (turn {last_turn}) — "
            "only post if you have a genuinely funny or sharp line this turn."
        )
    return lines


def _chat_shortcut_entry(recipient: str, text: str) -> dict[str, Any]:
    label = str(recipient).strip()
    lowered = label.lower()
    if lowered == "all":
        return {"target": "all", "text": text}
    if lowered == "team":
        return {"target": "team", "text": text}
    if label.startswith("PLAYER_"):
        return {"target": "player", "target_player_id": label, "text": text}
    return {"target": "player", "target_player_id": label, "text": text}


def _chat_format_guidance(snapshot: dict[str, Any]) -> list[str]:
    current_turn = int(snapshot.get("decision", {}).get("turn", 0))
    lines = [
        "chat.all is broadcast to every major civilization — do not reveal military plans, weak cities, "
        "or hidden ambitions; keep sensitive details in private DMs.",
        "Private messages are tagged by turn (chat.private.tN.*); reply only to DMs from this turn, "
        "not older lines.",
        "Proactively DM rivals when you have trade bait, probes, or taunts worth sending.",
    ]
    rivals: list[str] = []
    for rival in snapshot.get("known_players", [])[:12]:
        if not isinstance(rival, dict):
            continue
        player_id = str(rival.get("player_id", ""))
        if not player_id:
            continue
        rivals.append(_rival_leader_name(rival))
    if rivals:
        lines.append("DM recipients: " + "; ".join(rivals))
    diplomacy = snapshot.get("diplomacy", {})
    inbox = diplomacy.get("private_inbox", []) if isinstance(diplomacy, dict) else []
    this_turn_dms: list[str] = []
    for message in inbox:
        if not isinstance(message, dict):
            continue
        if int(message.get("turn", -1)) != current_turn:
            continue
        from_id = str(message.get("from_player_id", "")).strip()
        if not from_id:
            continue
        this_turn_dms.append(f"{_player_chat_name(snapshot, from_id)} ({from_id})")
    if this_turn_dms:
        lines.append(
            "DMs received this turn: " + "; ".join(this_turn_dms)
            + " — you may reply privately if you have something worth saying."
        )
    summary = snapshot.get("strategic_summary")
    if isinstance(summary, dict):
        for alert in summary.get("diplomacy_alerts", []):
            if not isinstance(alert, dict) or alert.get("kind") != "FIRST_MEET":
                continue
            text = str(alert.get("text", "")).strip()
            if text:
                lines.append(text)
    lines.extend(_chat_cadence_lines(snapshot))
    lines.extend(_lobby_chat_cadence_guidance(snapshot))
    return lines


def _is_public_chat_event(event: dict[str, Any]) -> bool:
    kind = str(event.get("kind", "")).upper()
    if kind and kind != "CHAT_PUBLIC":
        return False
    text = str(event.get("text") or event.get("summary") or "").strip()
    return bool(text)


def _public_chat_turns_in_range(snapshot: dict[str, Any], from_turn: int, to_turn: int) -> set[int]:
    history = snapshot.get("history", {})
    if not isinstance(history, dict):
        return set()
    turns: set[int] = set()
    for event in history.get("public_events", []):
        if not isinstance(event, dict) or not _is_public_chat_event(event):
            continue
        turn = int(event.get("turn", 0))
        if from_turn <= turn <= to_turn:
            turns.add(turn)
    return turns


def _lobby_public_chat_streak(snapshot: dict[str, Any]) -> int:
    current_turn = int(snapshot.get("decision", {}).get("turn", 0))
    chat_turns = _public_chat_turns_in_range(snapshot, 0, current_turn)
    streak = 0
    for turn in range(current_turn, -1, -1):
        if turn in chat_turns:
            streak += 1
        else:
            break
    return streak


def _lobby_chat_cadence_guidance(snapshot: dict[str, Any]) -> list[str]:
    current_turn = int(snapshot.get("decision", {}).get("turn", 0))
    window = 5
    min_turn = max(0, current_turn - window + 1)
    chat_turns = _public_chat_turns_in_range(snapshot, min_turn, current_turn)
    span = current_turn - min_turn + 1
    streak = _lobby_public_chat_streak(snapshot)
    lines = [
        "Read chat.public.* in CURRENT SITUATION — chat.all is mostly posture, not a group chat.",
        "If public lobby lines appear nearly every turn, hold off on chat.all so the room stays readable.",
        "When the lobby is quiet, an occasional chat.all reply is fine; prefer chat.LeaderName for quick back-and-forth.",
    ]
    every_turn_in_window = span >= 3 and len(chat_turns) >= span
    if streak >= 3 or every_turn_in_window:
        lines.append(
            f"Lobby chat cadence: public lines on {streak} consecutive turn(s) — skip chat.all this turn "
            "(private DM or silence is better)."
        )
    elif streak >= 2 or len(chat_turns) >= 3:
        lines.append(
            "Lobby has been active lately — only chat.all if you have a standout line that won't extend a rapid chain."
        )
    return lines


def _format_public_chat_line(snapshot: dict[str, Any], event: dict[str, Any]) -> str:
    text = str(event.get("text") or event.get("summary") or "").strip()[:240]
    if not text:
        return ""
    affected = event.get("affected_ids", [])
    sender_id = str(affected[0]) if isinstance(affected, list) and affected else ""
    if sender_id:
        return f"{_player_chat_name(snapshot, sender_id)}: {text}"
    return text


def _chat_voice_guidance(snapshot: dict[str, Any]) -> list[str]:
    personality = snapshot.get("personality", {})
    if not isinstance(personality, dict):
        personality = {}
    leader_id = str(personality.get("leader_id", "")).upper()
    if leader_id == "LEADER_GANDHI":
        return _gandhi_voice_guidance(snapshot)
    traits = personality.get("leader_traits", {})
    if not isinstance(traits, dict):
        traits = {}
    aggression = str(traits.get("aggression", "")).lower()
    diplomacy = str(traits.get("diplomacy", "")).lower()
    try:
        military_flavor = int(traits.get("military_flavor", 0))
    except (TypeError, ValueError):
        military_flavor = 0
    try:
        peace_weight = int(traits.get("base_peace_weight", 5))
    except (TypeError, ValueError):
        peace_weight = 5
    lines = _lobby_chat_tone_lines()
    if aggression in {"high", "very_high"} or military_flavor >= 7 or peace_weight <= 3:
        lines.append(
            "Personality: aggressive — sharp banter, swagger, and taunts when rivals posture; "
            "occasional trash talk every few turns fits, not every turn."
        )
    elif aggression in {"low", "very_low"} or (military_flavor <= 3 and peace_weight >= 7):
        lines.append(
            "Personality: restrained — speak rarely but with weight; a dry jab every 5-10 turns beats a grand speech."
        )
    if diplomacy in {"guarded", "hostile", "aggressive"}:
        lines.append("Diplomacy tone: skeptical when you do speak; call out bluffs, empty swagger, and rival cope.")
    elif diplomacy in {"open", "friendly"}:
        lines.append("Diplomacy tone: personable lobby banter when chat fits; charm with an edge, not forced politeness.")
    return lines


def _wire_line(key: str, value: Any) -> str:
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, (int, float)):
        rendered = str(value)
    else:
        text = str(value)
        if '"' in text or "\n" in text:
            rendered = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
        else:
            rendered = text
    return f"{key} = {rendered}"


def _append_int_wire(lines: list[str], key: str, value: Any) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        lines.append(_wire_line(key, value))
    elif isinstance(value, float) and value == int(value):
        lines.append(_wire_line(key, int(value)))


def _append_id_wire(lines: list[str], key: str, value: Any) -> None:
    if isinstance(value, str) and value.strip():
        lines.append(_wire_line(key, value))


def _append_bool_wire(lines: list[str], key: str, value: Any) -> None:
    if isinstance(value, bool) and value:
        lines.append(_wire_line(key, True))


def _append_game_wire_stats(lines: list[str], context: dict[str, Any]) -> None:
    decision = context.get("decision", {})
    if isinstance(decision, dict):
        _append_int_wire(lines, "game.year", decision.get("year"))
    game = context.get("game", {})
    if not isinstance(game, dict):
        return
    _append_id_wire(lines, "game.era", game.get("era_id"))
    _append_id_wire(lines, "game.speed", game.get("game_speed_id"))
    _append_id_wire(lines, "game.difficulty", game.get("difficulty_id"))
    _append_id_wire(lines, "game.world_size", game.get("world_size_id"))


def _map_ruin_coords(known_map: dict[str, Any]) -> list[str]:
    plots = known_map.get("plots", [])
    if not isinstance(plots, list):
        return []
    ruin_coords: list[str] = []
    for item in plots:
        if not isinstance(item, dict):
            continue
        improvement = item.get("improvement_id")
        if improvement != "IMPROVEMENT_GOODY_HUT" and item.get("goody") is not True:
            continue
        x, y = item.get("x"), item.get("y")
        if isinstance(x, int) and isinstance(y, int):
            ruin_coords.append(f"({x},{y})")
    return ruin_coords


def _map_wire_stats_from_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """Plot counts and image metadata from full snapshot before playable context strips plots."""
    lines: list[str] = []
    known_map = snapshot.get("known_map", {})
    if not isinstance(known_map, dict):
        return lines
    ruin_coords = _map_ruin_coords(known_map)
    if ruin_coords:
        lines.append(_wire_line("map.ruins", " | ".join(ruin_coords)))
    if compact_situation_wire_enabled():
        return lines
    plots = known_map.get("plots", [])
    if isinstance(plots, list) and plots:
        visible_count = sum(1 for item in plots if isinstance(item, dict) and item.get("knowledge") == "visible")
        remembered_count = sum(1 for item in plots if isinstance(item, dict) and item.get("knowledge") == "remembered")
        lines.append(_wire_line("map.known_plots", len(plots)))
        lines.append(_wire_line("map.visible_plots", visible_count))
        lines.append(_wire_line("map.remembered_plots", remembered_count))
    image = known_map.get("image", {})
    if isinstance(image, dict) and image.get("attached"):
        lines.append(_wire_line("map.image_attached", True))
        fmt = image.get("format")
        if isinstance(fmt, str):
            lines.append(_wire_line("map.image_format", fmt))
        viewport = image.get("viewport")
        if isinstance(viewport, dict):
            lines.append(_wire_line(
                "map.viewport",
                f"{viewport.get('x0', 0)},{viewport.get('y0', 0)},{viewport.get('width', 0)},{viewport.get('height', 0)}",
            ))
        tile_px = image.get("tile_px")
        if isinstance(tile_px, int):
            lines.append(_wire_line("map.tile_px", tile_px))
        legend = image.get("legend", [])
        if isinstance(legend, list):
            for index, entry in enumerate(legend):
                if isinstance(entry, dict) and entry.get("meaning"):
                    symbol = entry.get("symbol", "")
                    meaning = entry.get("meaning", "")
                    lines.append(_wire_line(f"map.legend.{index}", f"{symbol}: {meaning}"))
    return lines


def _append_map_wire_stats(lines: list[str], context: dict[str, Any], map_stats: list[str] | None = None) -> None:
    game = context.get("game", {})
    if isinstance(game, dict):
        _append_id_wire(lines, "map.script", game.get("map_script"))
    coastal = sum(1 for city in context.get("your_cities", []) if isinstance(city, dict) and city.get("is_coastal"))
    if coastal:
        lines.append(_wire_line("empire.coastal_cities", coastal))
    image_attached = False
    known_map = context.get("known_map", {})
    if isinstance(known_map, dict):
        image = known_map.get("image", {})
        if isinstance(image, dict) and image.get("attached"):
            image_attached = True
    if map_stats:
        if not compact_situation_wire_enabled():
            lines.extend(map_stats)
            for area in context.get("known_map", {}).get("areas", [])[:12]:
                if not isinstance(area, dict):
                    continue
                label = _readable_id(area.get("area_id", "AREA_0"), "AREA_")
                kind = "water" if area.get("water") else "land"
                count = int(area.get("revealed_plot_count", 0))
                lines.append(_wire_line(f"map.area.{label}", f"{kind}:{count}"))
        if image_attached or any(line.startswith("map.image_attached = true") for line in lines):
            lines.append("# minimap attached — coast, islands, fog, and unit positions visible in image")
        return
    if compact_situation_wire_enabled():
        if image_attached:
            lines.append("# minimap attached — coast, islands, fog, and unit positions visible in image")
        return
    if isinstance(game, dict):
        _append_int_wire(lines, "map.width", game.get("map_width"))
        _append_int_wire(lines, "map.height", game.get("map_height"))
    if not isinstance(known_map, dict):
        return
    plots = known_map.get("plots", [])
    if isinstance(plots, list) and plots:
        visible_count = sum(1 for item in plots if isinstance(item, dict) and item.get("knowledge") == "visible")
        remembered_count = sum(1 for item in plots if isinstance(item, dict) and item.get("knowledge") == "remembered")
        lines.append(_wire_line("map.known_plots", len(plots)))
        lines.append(_wire_line("map.visible_plots", visible_count))
        lines.append(_wire_line("map.remembered_plots", remembered_count))
    if image_attached:
        lines.append(_wire_line("map.image_attached", True))
    for area in known_map.get("areas", [])[:12]:
        if not isinstance(area, dict):
            continue
        label = _readable_id(area.get("area_id", "AREA_0"), "AREA_")
        kind = "water" if area.get("water") else "land"
        count = int(area.get("revealed_plot_count", 0))
        lines.append(_wire_line(f"map.area.{label}", f"{kind}:{count}"))
    if image_attached:
        lines.append("# minimap attached — coast, islands, fog, and unit positions visible in image")


def _append_advciv_wire(lines: list[str], context: dict[str, Any]) -> None:
    advciv = context.get("advciv", {})
    if not isinstance(advciv, dict):
        return
    policy = advciv.get("fallback_policy")
    if isinstance(policy, str):
        lines.append(_wire_line("advciv.unit_policy", policy))


def _append_empire_wire_stats(lines: list[str], empire: dict[str, Any], cities: list[Any]) -> None:
    if not isinstance(empire, dict):
        return
    _append_int_wire(lines, "empire.score", empire.get("score"))
    city_count = len([city for city in cities if isinstance(city, dict)])
    if city_count:
        lines.append(_wire_line("empire.cities", city_count))
    _append_int_wire(lines, "empire.gold", empire.get("gold"))
    _append_int_wire(lines, "empire.gold_per_turn", empire.get("gold_per_turn"))
    commerce = empire.get("commerce", {})
    if isinstance(commerce, dict):
        for bucket in ("gold", "research", "culture", "espionage"):
            item = commerce.get(bucket)
            if not isinstance(item, dict):
                continue
            _append_int_wire(lines, f"empire.commerce.{bucket}.percent", item.get("percent"))
            _append_int_wire(lines, f"empire.commerce.{bucket}.rate", item.get("rate"))
    costs = empire.get("costs", {})
    if isinstance(costs, dict):
        for field in ("unit_cost", "unit_supply", "city_maintenance", "civic_upkeep", "inflation"):
            _append_int_wire(lines, f"empire.costs.{field}", costs.get(field))
    research = empire.get("research", {})
    if isinstance(research, dict):
        _append_id_wire(lines, "empire.research", research.get("tech_id"))
        _append_int_wire(lines, "empire.research.progress", research.get("progress"))
        _append_int_wire(lines, "empire.research.cost", research.get("cost"))
        _append_int_wire(lines, "empire.research.per_turn", research.get("research_per_turn"))
        _append_int_wire(lines, "empire.research.turns_left", research.get("estimated_turns_remaining"))
    civics = empire.get("civics", [])
    if isinstance(civics, list):
        for civic in civics:
            if not isinstance(civic, dict):
                continue
            key = civic.get("key")
            civic_id = civic.get("id")
            if isinstance(key, str) and key.strip() and isinstance(civic_id, str) and civic_id.strip():
                label = _readable_id(key, "")
                lines.append(_wire_line(f"empire.civic.{label}", civic_id))
    religion = empire.get("religion", {})
    if isinstance(religion, dict):
        _append_id_wire(lines, "empire.religion", religion.get("state_religion_id"))
    unit_counts = empire.get("unit_counts", {})
    if isinstance(unit_counts, dict):
        for field in ("total", "workers", "settlers", "military", "missionaries", "spies",
                      "great_people", "idle", "upgradeable"):
            _append_int_wire(lines, f"empire.units.{field}", unit_counts.get(field))
    _append_int_wire(lines, "empire.anarchy_turns", empire.get("anarchy_turns"))
    _append_int_wire(lines, "empire.golden_age_turns", empire.get("golden_age_turns"))
    _append_int_wire(lines, "empire.war_weariness", empire.get("war_weariness"))
    resources = empire.get("resources", [])
    if isinstance(resources, list):
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            resource_id = resource.get("resource_id")
            if not isinstance(resource_id, str) or not resource_id.strip():
                continue
            label = _readable_id(resource_id, "BONUS_")
            _append_int_wire(lines, f"empire.resource.{label}.available", resource.get("available"))
            surplus = resource.get("surplus")
            if isinstance(surplus, int) and surplus != 0:
                lines.append(_wire_line(f"empire.resource.{label}.surplus", surplus))
    victory = empire.get("victory_progress", [])
    if isinstance(victory, list):
        for item in victory[:8]:
            if not isinstance(item, dict):
                continue
            victory_id = item.get("id")
            value = item.get("value")
            if isinstance(victory_id, str) and victory_id.strip() and isinstance(value, int):
                label = _readable_id(victory_id, "VICTORY_")
                lines.append(_wire_line(f"empire.victory.{label}", value))


def _append_rival_wire_stats(lines: list[str], rival: dict[str, Any]) -> None:
    if not isinstance(rival, dict):
        return
    rival_id = str(rival.get("player_id", "PLAYER_X"))
    leader_name = _rival_leader_name(rival)
    civ_label = _readable_id(rival.get("civilization_id"), "CIVILIZATION_")
    label = _player_identity_phrase(leader_name, civ_label)
    lines.append(_wire_line(f"rival.{rival_id}", label))
    _append_int_wire(lines, f"rival.{rival_id}.score", rival.get("score"))
    _append_int_wire(lines, f"rival.{rival_id}.population", rival.get("population"))
    _append_int_wire(lines, f"rival.{rival_id}.land", rival.get("land"))
    _append_int_wire(lines, f"rival.{rival_id}.power", rival.get("power"))
    relation = rival.get("relation", {})
    if isinstance(relation, dict):
        _append_bool_wire(lines, f"rival.{rival_id}.at_war", relation.get("at_war"))
        _append_bool_wire(lines, f"rival.{rival_id}.open_borders", relation.get("open_borders"))
        _append_bool_wire(lines, f"rival.{rival_id}.defensive_pact", relation.get("defensive_pact"))
        _append_bool_wire(lines, f"rival.{rival_id}.vassal", relation.get("vassal"))


def build_flat_wire_prompt(context: dict[str, Any], map_stats: list[str] | None = None) -> str:
    """Sectioned key:value context for the model (situation, map, legal commands)."""
    situation: list[str] = []
    map_lines: list[str] = []
    legal_lines: list[str] = []
    decision = context.get("decision", {})
    personality = context.get("personality", {})
    leader = personality.get("leader_name", personality.get("leader_id", "Leader"))
    player_id = decision.get("player_id", "PLAYER_0")
    civ_id = personality.get("civilization_id")
    civ_label = _readable_id(civ_id, "CIVILIZATION_") if civ_id else ""
    player_label = _player_identity_phrase(leader, civ_label, player_id)
    situation.append(_wire_line("player", player_label))
    situation.append(_wire_line("turn", int(decision.get("turn", 0))))
    history = context.get("history", {})
    if isinstance(history, dict):
        for entry in history.get("thought_memory", []):
            if not isinstance(entry, dict):
                continue
            turn = int(entry.get("turn", 0))
            prior_situation = entry.get("situation")
            if isinstance(prior_situation, str) and prior_situation.strip():
                situation.append(_wire_line(f"thought.t{turn}.situation", _clip_thought(prior_situation)))
        opinions = history.get("player_opinions", {})
        if isinstance(opinions, dict):
            for player_id, entry in opinions.items():
                if not isinstance(player_id, str) or not player_id.startswith("PLAYER_"):
                    continue
                if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
                    continue
                situation.append(_wire_line(
                    _opinion_wire_key(context, player_id),
                    _opinion_wire_value(entry),
                ))
        histories = history.get("player_histories", {})
        if isinstance(histories, dict):
            for player_id, entry in histories.items():
                if not isinstance(player_id, str) or not player_id.startswith("PLAYER_"):
                    continue
                if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
                    continue
                situation.append(_wire_line(
                    _history_wire_key(context, player_id),
                    str(entry["text"]).strip(),
                ))
    _append_game_wire_stats(situation, context)
    cities = context.get("your_cities", [])
    if not isinstance(cities, list):
        cities = []
    _append_empire_wire_stats(situation, context.get("your_empire", {}), cities)
    city_count = len([city for city in cities if isinstance(city, dict)])
    many_cities = city_count >= WIRE_COMPACT_CITIES_THRESHOLD
    for city in cities:
        if not isinstance(city, dict):
            continue
        _append_city_situation_wire(situation, city, many_cities)
    _append_units_situation_wire(situation, context)
    unit_ids_with_cmds: set[str] = set()
    for command in context.get("legal_commands", []):
        if not isinstance(command, dict):
            continue
        fixed = command.get("fixed_arguments", {})
        if isinstance(fixed, dict) and isinstance(fixed.get("unit_id"), str):
            unit_ids_with_cmds.add(fixed["unit_id"])
    uncommanded = [
        unit for unit in context.get("your_units", [])
        if isinstance(unit, dict) and unit.get("unit_id") not in unit_ids_with_cmds
    ]
    if uncommanded:
        situation.append(_wire_line("units.nativeControl", UNITS_NATIVE_CONTROL_HINT))
    for rival in context.get("known_players", [])[:12]:
        _append_rival_wire_stats(situation, rival)
    diplomacy_block = context.get("diplomacy", {})
    if isinstance(diplomacy_block, dict):
        _append_diplomacy_situation_wire(situation, context)
    summary = context.get("strategic_summary")
    if isinstance(summary, dict):
        for section in ("city_alerts", "economy_alerts", "military_alerts", "diplomacy_alerts", "resource_alerts"):
            for index, alert in enumerate(summary.get(section, [])[:6]):
                if isinstance(alert, dict) and alert.get("text"):
                    situation.append(_wire_line(f"alert.{section}.{index}", alert["text"][:200]))
    if isinstance(history, dict):
        memory = history.get("memory_summary")
        if isinstance(memory, str) and memory.strip():
            situation.append(_wire_line("history.memory", memory.strip()[:400]))
        for index, event in enumerate(_recent_history_events(history.get("public_events", []), chat_history_max_messages())):
            if not isinstance(event, dict):
                continue
            turn = int(event.get("turn", 0))
            text = _format_public_chat_line(context, event)
            if text:
                situation.append(_wire_line(f"chat.public.t{turn}.{index}", text))
        inbox = diplomacy_block.get("private_inbox", []) if isinstance(diplomacy_block, dict) else []
        for index, message in enumerate(_recent_history_events(inbox, chat_history_max_messages())):
            if not isinstance(message, dict):
                continue
            turn = int(message.get("turn", 0))
            text = str(message.get("text", ""))[:240]
            if text:
                from_id = str(message.get("from_player_id", ""))
                sender = _player_chat_name(context, from_id) if from_id else "Rival"
                situation.append(_wire_line(f"chat.private.t{turn}.{index}", f"{sender} (private): {text}"))
    for index, rec in enumerate(context.get("advciv", {}).get("recommendations", [])[:12]):
        if not isinstance(rec, dict) or not rec.get("summary"):
            continue
        if compact_situation_wire_enabled():
            summary = str(rec["summary"])
            if summary.startswith("Continue current research "):
                continue
            if "allocation is " in summary and "percent" in summary:
                continue
            if " is producing UNIT_" in summary:
                continue
            if summary.startswith("Current civic "):
                continue
        situation.append(_wire_line(f"advice.{index}", rec["summary"][:200]))
    _append_advciv_wire(situation, context)
    _append_map_wire_stats(map_lines, context, map_stats)
    legal_lines.append("# Issue as many command lines as you need this turn.")
    legal_lines.append("# City: cityName.property = value. Unit: unitId.property = value.")
    if compact_legal_wire_enabled():
        legal_lines.append("# Unit movement: unitId.moveTo or stack.moveTo = (x,y) — pick one listed coordinate; read the minimap first.")
        legal_lines.append("# stack.* groups co-located units; stack.moveTo moves the whole tile together when grouped.")
        legal_lines.append("# Empire: legal.commerce.* or legal.expansion = value; unknown values are ignored.")
    else:
        legal_lines.append("# Empire commands use legal.N = CMD_* (see // id on each line).")
    legal_lines.append("# Lines marked risk=high need to be carefully considered.")
    city_name_by_id = _city_name_map(context)
    unit_wire_ids = _build_unit_wire_id_map([u for u in context.get("your_units", []) if isinstance(u, dict)])
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
        if compact_legal_wire_enabled():
            legal_lines.extend(_compact_city_legal_lines(city_name, city_commands[city_name]))
        else:
            legal_lines.append(f"# {city_name}")
            for command in city_commands[city_name]:
                legal_lines.append(_city_command_wire_line(city_name, command))
    if compact_legal_wire_enabled():
        legal_lines.extend(_compact_stack_legal_lines(context, unit_commands))
    for unit_wire_id in sorted(unit_commands):
        if compact_legal_wire_enabled():
            legal_lines.extend(_compact_unit_legal_lines(unit_wire_id, unit_commands[unit_wire_id]))
        else:
            legal_lines.append(f"# {unit_wire_id}")
            for command in unit_commands[unit_wire_id]:
                legal_lines.append(_unit_command_wire_line(unit_wire_id, command))
    if empire_commands:
        legal_lines.append("# empire")
    if compact_legal_wire_enabled():
        legal_lines.extend(_compact_empire_legal_lines(empire_commands))
    else:
        legal_index = 0
        for command in empire_commands:
            legal_index += 1
            desc = _describe_legal_command(command)
            notes = _legal_command_notes(command)
            comment = f"# {legal_index}. {desc}"
            if notes:
                comment += f" // {notes}"
            legal_lines.append(comment)
            legal_lines.append(_wire_line(f"legal.{legal_index}", command["command_id"]))
    return "\n\n".join([
        _wire_section("CURRENT SITUATION", situation),
        _wire_section("MAP", map_lines),
        _wire_section("LEGAL COMMANDS", legal_lines),
    ])


def _strip_wire_inline_comment(value: str) -> str:
    if "//" in value:
        return value.split("//", 1)[0].strip()
    return value.strip()


def parse_flat_wire_lines(text: str) -> dict[str, Any]:
    """Parse line-oriented flat wire text into a dotted-key object."""
    result: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = normalize_wire_property_key(key.strip())
        value = _strip_wire_inline_comment(value.strip())
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        result[key] = value
    return result


_EMBEDDED_WIRE_KEY_RE = re.compile(
    r"(?:^|[;\s])((?:cmd\.\d+(?:\.[a-z_]+)?)|(?:chat\.(?:\d+(?:\.[a-z_]+)?|all|team|PLAYER_\d+|[A-Za-z][A-Za-z0-9_ ]*)))\s*=",
    re.IGNORECASE,
)


def parse_embedded_wire_assignments(text: str) -> dict[str, Any]:
    """Parse flat wire keys from newline blocks and semicolon-embedded summary tails."""
    if not isinstance(text, str) or not text.strip():
        return {}
    result = dict(parse_flat_wire_lines(text))
    for match in _EMBEDDED_WIRE_KEY_RE.finditer(text):
        key = match.group(1)
        if key in result:
            continue
        start = match.end()
        end = len(text)
        next_match = _EMBEDDED_WIRE_KEY_RE.search(text, start)
        if next_match is not None:
            end = next_match.start()
        value = _strip_wire_inline_comment(text[start:end].strip().rstrip(";").strip())
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        result[key] = value
    return result


def scrub_wire_from_summary(text: str) -> str:
    """Keep narrative prose for history; drop cmd./chat. tails mistaken into summaries."""
    if not isinstance(text, str):
        return ""
    match = _EMBEDDED_WIRE_KEY_RE.search(text)
    if match is None:
        return text.strip()
    prose = text[:match.start()].strip().rstrip(";").strip()
    return prose


def _response_has_flat_wire_keys(response: dict[str, Any]) -> bool:
    for key in response:
        if key.startswith("cmd."):
            return True
        if key.startswith("chat.") and key != "chat_messages":
            return True
        if key.startswith("opinion."):
            return True
        if key.startswith("history."):
            return True
    return False


def expand_flat_response(response: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expand flat wire keys (cmd.0, chat.0.text) into nested v2 response schema."""
    if not isinstance(response, dict):
        raise BoundaryError("response_schema", "Model response must be an object")
    response = coalesce_model_response_shape(response)
    if not _response_has_flat_wire_keys(response):
        if isinstance(response.get("commands"), list) or isinstance(response.get("chat_messages"), list):
            return response
    summary = response.get("decision_summary")
    if isinstance(summary, str) and summary.strip():
        summary_wire = {
            key: value for key, value in parse_embedded_wire_assignments(summary).items()
            if key.startswith(("cmd.", "chat."))
        }
        if summary_wire:
            merged = dict(response)
            for key, value in summary_wire.items():
                if key not in merged:
                    merged[key] = value
            response = merged
    flat = response
    thought = _thought_from_flat(flat)
    if not any(key.startswith(("cmd.", "chat.")) for key in flat):
        merged = dict(response)
        if thought:
            merged["thought"] = thought
        if snapshot is not None:
            opinions = _player_opinions_from_flat(flat, snapshot)
            if opinions:
                merged["player_opinions"] = opinions
            histories = _player_histories_from_flat(flat, snapshot)
            if histories:
                merged["player_histories"] = histories
        if thought or merged.get("player_opinions") or merged.get("player_histories"):
            return merged
        return response
    existing_commands = response.get("commands")
    existing_chats = response.get("chat_messages")
    nested: dict[str, Any] = {
        "thought": thought,
        "decision_summary": flat.get("decision_summary", ""),
        "recommendation_decisions": flat.get("recommendation_decisions", []),
        "commands": copy.deepcopy(existing_commands) if isinstance(existing_commands, list) else [],
        "chat_messages": copy.deepcopy(existing_chats) if isinstance(existing_chats, list) else [],
    }
    commands_by_index: dict[int, dict[str, Any]] = {}
    chats_by_index: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(nested["commands"]):
        if isinstance(item, dict):
            commands_by_index[index] = copy.deepcopy(item)
    for index, item in enumerate(nested["chat_messages"]):
        if isinstance(item, dict):
            chats_by_index[index] = copy.deepcopy(item)
    for key, value in flat.items():
        if key == "decision_summary":
            nested["decision_summary"] = value
            continue
        if key.startswith("cmd."):
            remainder = key[4:]
            recovered_id = _command_id_from_flat_cmd_key(key, value)
            if "." not in remainder:
                try:
                    index = int(remainder)
                except ValueError:
                    continue
                if recovered_id:
                    commands_by_index.setdefault(index, {})["command_id"] = recovered_id
                else:
                    commands_by_index.setdefault(index, {})["command_id"] = str(value)
            else:
                index_text, arg_name = remainder.split(".", 1)
                try:
                    index = int(index_text)
                except ValueError:
                    continue
                if recovered_id and arg_name != "command_id":
                    commands_by_index.setdefault(index, {})["command_id"] = recovered_id
                    continue
                entry = commands_by_index.setdefault(index, {"arguments": {}})
                if "arguments" not in entry:
                    entry["arguments"] = {}
                if arg_name == "command_id":
                    entry["command_id"] = str(value)
                else:
                    entry["arguments"][arg_name] = value
            continue
        if key.startswith("chat."):
            remainder = key[5:]
            if "." not in remainder:
                text = str(value).strip() if value is not None else ""
                if text:
                    chats_by_index[len(chats_by_index)] = _chat_shortcut_entry(remainder, text)
                continue
            index_text, field = remainder.split(".", 1)
            try:
                index = int(index_text)
            except ValueError:
                continue
            entry = chats_by_index.setdefault(index, {})
            if field == "to":
                entry["target_player_id"] = value
            else:
                entry[field] = value
    nested["commands"] = [commands_by_index[i] for i in sorted(commands_by_index)]
    nested["chat_messages"] = [chats_by_index[i] for i in sorted(chats_by_index)]
    if snapshot is not None:
        nested["player_opinions"] = _player_opinions_from_flat(flat, snapshot)
        nested["player_histories"] = _player_histories_from_flat(flat, snapshot)
    if isinstance(flat.get("recommendation_decisions"), list):
        nested["recommendation_decisions"] = flat["recommendation_decisions"]
    if not nested["thought"]:
        nested.pop("thought", None)
    nested["decision_summary"] = scrub_wire_from_summary(str(nested.get("decision_summary", "")))
    return nested


def _is_civ5_snapshot(snapshot: dict[str, Any]) -> bool:
    version = snapshot.get("schema_version")
    return isinstance(version, str) and version.startswith("civ5ai-input/")


def build_model_wire_text(snapshot: dict[str, Any]) -> str:
    if snapshot.get("schema_version") == "civ6ai-input/1":
        from sidecar import civ6_wire
        return civ6_wire.build_civ6_model_wire_text(snapshot)
    if _is_civ5_snapshot(snapshot):
        from sidecar import civ5_wire
        return civ5_wire.build_civ5_model_wire_text(snapshot)
    context = build_playable_context(snapshot)
    map_stats = _map_wire_stats_from_snapshot(snapshot)
    return build_flat_wire_prompt(context, map_stats) + "\n\n" + _model_response_instructions(snapshot)


def _command_arguments_from_catalog(catalog: dict[str, Any], command_id: str) -> dict[str, Any]:
    command = catalog[command_id]
    domains = command.get("parameter_domains", {})
    fixed = command.get("fixed_arguments", {})
    return {key: fixed[key] for key in domains if key in fixed}


def _derive_strategic_summary(own_cities: list[dict[str, Any]], own_units: list[dict[str, Any]],
                              empire: dict[str, Any], diplomacy: dict[str, Any]) -> dict[str, Any]:
    def alert(kind: str, severity: str, affected: list[str], text: str) -> dict[str, Any]:
        mapped = {"high": "critical", "medium": "warning", "low": "info"}.get(severity, severity)
        if mapped not in {"info", "warning", "critical"}:
            mapped = "info"
        return {"kind": kind, "severity": mapped, "affected_ids": affected, "text": text[:200]}

    city_alerts: list[dict[str, Any]] = []
    economy_alerts: list[dict[str, Any]] = []
    military_alerts: list[dict[str, Any]] = []
    diplomacy_alerts: list[dict[str, Any]] = []
    resource_alerts: list[dict[str, Any]] = []
    for city in own_cities:
        if city["happiness"]["net"] < 0:
            city_alerts.append(alert("CITY_UNHAPPY", "critical", [city["city_id"]], "City happiness is negative"))
        if city["health"]["net"] < 0:
            city_alerts.append(alert("CITY_UNHEALTHY", "warning", [city["city_id"]], "City health is negative"))
    gold = int(empire.get("gold", 0))
    income = int(empire.get("gold_per_turn", 0))
    if gold < 0:
        economy_alerts.append(alert("TREASURY_NEGATIVE", "critical", [], "Treasury is negative"))
    elif income < 0:
        economy_alerts.append(alert("INCOME_NEGATIVE", "warning", [], "Net income is negative"))
    idle = int(empire.get("unit_counts", {}).get("idle", 0))
    military = int(empire.get("unit_counts", {}).get("military", 0))
    if idle > 0:
        military_alerts.append(alert("IDLE_UNITS", "warning", [], f"{idle} owned units need orders"))
    if diplomacy.get("pending_requests"):
        diplomacy_alerts.append(alert("PENDING_DIPLOMACY", "critical", [], "Pending diplomacy requests require a response"))
    for resource in empire.get("resources", []):
        if isinstance(resource, dict) and int(resource.get("surplus", 0)) < 0:
            resource_alerts.append(alert("RESOURCE_SHORTAGE", "warning",
                [str(resource.get("resource_id", "RESOURCE_UNKNOWN"))], "Resource surplus is negative"))
    ratios = []
    if military > 0:
        ratios.append({"kind": "MILITARY_PER_CITY", "numerator": military,
            "denominator": max(1, len(own_cities)), "basis": "military units per owned city"})
    if own_units:
        needing = sum(1 for unit in own_units if unit["needs_orders"])
        ratios.append({"kind": "UNITS_NEEDING_ORDERS", "numerator": needing,
            "denominator": len(own_units), "basis": "owned units needing orders"})
    return {"city_alerts": city_alerts, "economy_alerts": economy_alerts, "military_alerts": military_alerts,
        "diplomacy_alerts": diplomacy_alerts, "resource_alerts": resource_alerts, "ratios": ratios}


def _private_inbox_from_history(history: dict[str, Any], player_id: str) -> list[dict[str, Any]]:
    inbox: list[dict[str, Any]] = []
    for message in history.get("private_messages", []):
        if not isinstance(message, dict):
            continue
        if str(message.get("target_player_id")) != player_id:
            continue
        inbox.append({"message_id": str(message.get("message_id", "CHAT_UNKNOWN")),
            "from_player_id": str(message.get("from_player_id", "PLAYER_0")),
            "turn": int(message.get("turn", 0)),
            "text": str(message.get("text", ""))[:240]})
    return inbox


def _normalize_leader_traits(raw: dict[str, Any]) -> dict[str, str]:
    """Coerce DLL leader_traits into schema-safe string scalars."""
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        name = str(key)
        if name == "trait_ids":
            if isinstance(value, list):
                parts = []
                for item in value:
                    text = str(item)
                    if text.startswith("TRAIT_"):
                        text = text[len("TRAIT_"):]
                    if text:
                        parts.append(text)
                if parts:
                    normalized[name] = ",".join(parts)[:40]
            elif isinstance(value, str) and value.strip():
                normalized[name] = value.strip()[:40]
            continue
        if isinstance(value, bool):
            normalized[name] = "true" if value else "false"
        elif isinstance(value, (int, float)):
            normalized[name] = str(int(value))
        elif isinstance(value, str) and value.strip():
            normalized[name] = value.strip()[:40]
    return normalized


def _build_personality(player: dict[str, Any], active: int) -> dict[str, Any]:
    personality: dict[str, Any] = {
        "identity": player.get("leader_id", "UNKNOWN") + "-" + str(active),
        "leader_id": player.get("leader_id", "UNKNOWN_LEADER"),
        "leader_name": _resolve_leader_display_name(player),
        "civilization_id": player.get("civilization_id", player.get("civ_id", "UNKNOWN_CIV")),
    }
    traits = player.get("leader_traits")
    if isinstance(traits, dict) and traits:
        personality["leader_traits"] = _normalize_leader_traits(traits)
    return personality


def _upgrade_legacy_source(source: dict[str, Any]) -> dict[str, Any]:
    """Bridge the current DLL's compact v1 record into v2.

    This is a lossless shape adapter for fields the v1 DLL already exposes;
    absent v2 fields are explicit zero/empty values, never guessed IDs. The
    DLL extractor remains responsible for replacing these defaults with real
    values as each field is wired.
    """
    player = source.get("player", {})
    empire = source.get("empire", {})
    active = int(source.get("active_player_id", player.get("id", 0)))
    player_id = f"PLAYER_{active}"
    settings = source.get("settings", {})
    public = source.get("public", {})
    visible = source.get("visible", {})
    def ident(value: Any, prefix: str) -> str:
        text = str(value)
        return text if text.startswith(prefix + "_") else prefix + "_" + text
    def currency(value: int = 0) -> dict[str, int | None]:
        return {"current": int(value), "maximum": 0, "change_per_turn": 0}
    def city(row: dict[str, Any], own: bool) -> dict[str, Any]:
        cid = ident(row.get("id", "0"), "CITY")
        return {"city_id": cid, "name": str(row.get("name", cid)), "plot_id": f"PLOT_{row.get('x', 0)}_{row.get('y', 0)}",
            "area_id": ident(row.get("area_id", "0"), "AREA"), "is_capital": bool(row.get("is_capital", False)),
            "is_coastal": bool(row.get("is_coastal", False)), "population": max(1, int(row.get("population", 1))), "food": {"current": int(row.get("food", 0)), "maximum": 0, "change_per_turn": int(row.get("food_difference", 0))},
            "production": {"item_id": row.get("production_queue", [{}])[0].get("item_id") if row.get("production_queue") else None, "progress": int(row.get("production", 0)), "cost": int(row.get("production_needed", 0)), "production_per_turn": int(row.get("production_per_turn", 0)), "estimated_turns_remaining": int(row.get("production_turns_left", 0)) if row.get("production_turns_left") is not None else None},
            "production_queue": list(row.get("production_queue", [])), "yields": {"food": int(row.get("yield_food", 0)), "production": int(row.get("yield_production", 0)), "commerce": int(row.get("yield_commerce", 0))}, "commerce": {
                "gold": {"percent": 0, "rate": int(row.get("commerce_gold", 0))},
                "research": {"percent": 0, "rate": int(row.get("commerce_research", 0))},
                "culture": {"percent": 0, "rate": int(row.get("commerce_culture", 0))},
                "espionage": {"percent": 0, "rate": int(row.get("commerce_espionage", 0))}},
            "happiness": {"positive": int(row.get("happy", 0)), "negative": int(row.get("unhappy", 0)), "net": int(row.get("happy", 0)) - int(row.get("unhappy", 0))}, "health": _city_health_buckets(row), "maintenance": int(row.get("maintenance", 0)),
            "culture": currency(int(row.get("culture", 0))), "great_people": {"current": int(row.get("great_people_progress", 0)), "maximum": 0, "change_per_turn": int(row.get("great_people_rate", 0))}, "specialists": list(row.get("specialists", [])), "buildings": list(row.get("buildings", [])), "religions": list(row.get("religions", [])), "corporations": list(row.get("corporations", [])),
            "trade_routes": list(row.get("trade_routes", [])), "worked_plot_ids": list(row.get("worked_plot_ids", [])), "automation": {"citizens": bool(row.get("citizens_automated", False)), "production": bool(row.get("production_automated", False))},
            "defense": {"percent": int(row.get("defense_percent", 0)), "bombard_damage": int(row.get("defense_damage", 0))}, "occupation_turns": int(row.get("occupation_turns", 0)), "garrison_unit_ids": list(row.get("garrison_unit_ids", []))}
    def unit(row: dict[str, Any]) -> dict[str, Any]:
        uid = ident(row.get("id", "0"), "UNIT")
        return {"unit_id": uid, "unit_type_id": ident(row.get("unit_type_id", "UNKNOWN"), "UNIT"), "unit_class_id": str(row.get("unit_class_id", "UNITCLASS_UNKNOWN")),
            "domain_id": str(row.get("domain_id", "DOMAIN_UNKNOWN")), "plot_id": f"PLOT_{row.get('x', 0)}_{row.get('y', 0)}",
            "health": {"current": int(row.get("health_current", 100)), "maximum": int(row.get("health_max", 100)), "change_per_turn": 0},
            "strength": currency(int(row.get("strength", 0))), "movement": {"current": int(row.get("moves_left", 0)), "maximum": int(row.get("max_moves", 0)), "change_per_turn": 0},
            "level": max(1, int(row.get("level", 1))), "experience": int(row.get("experience", 0)),
            "promotion_ids": list(row.get("promotions", [])), "activity_id": str(row.get("activity_id", "ACTIVITY_UNKNOWN")),
            "mission_queue": list(row.get("mission_queue", [])), "unit_ai_role": str(row.get("unit_ai_role", "UNITAI_UNKNOWN")),
            "cargo_unit_ids": list(row.get("cargo_unit_ids", [])), "can_act": bool(row.get("movement_ready", False)),
            "needs_orders": bool(row.get("needs_orders", row.get("movement_ready", False))), "upgrade_options": list(row.get("upgrade_options", []))}
    own_cities = [city(row, True) for row in visible.get("cities", []) if str(row.get("owner_id")) in {str(active), player_id}]
    other_cities = [{"city_id": ident(row.get("id", "0"), "CITY"), "owner_player_id": ident(row.get("owner_id", "0"), "PLAYER"), "name": str(row.get("name", row.get("id", "UNKNOWN"))),
        "plot_id": f"PLOT_{row.get('x', 0)}_{row.get('y', 0)}", "area_id": ident(row.get("area_id", "0"), "AREA"),
        "knowledge": "visible", "last_seen_turn": int(source.get("turn", 0)), "population": row.get("population"),
        "is_capital": row.get("is_capital"), "visible_defense": None} for row in public.get("known_cities", [])]
    all_units = [unit(row) for row in visible.get("units", [])]
    own_units = [item for item, row in zip(all_units, visible.get("units", [])) if str(row.get("owner_id")) in {str(active), player_id}]
    other_units = [{"unit_id": item["unit_id"], "owner_player_id": ident(row.get("owner_id", "0"), "PLAYER"), "unit_type_id": item["unit_type_id"], "plot_id": item["plot_id"], "health_percent": 100, "visible_strength": item["strength"]["current"], "movement_ready": item["can_act"]} for item, row in zip(all_units, visible.get("units", [])) if str(row.get("owner_id")) not in {str(active), player_id}]
    raw_relations = {str(row.get("other_player_id")): row for row in visible.get("diplomacy", []) if isinstance(row, dict)}
    def relation_for(other_id: str, public_row: dict[str, Any]) -> dict[str, Any]:
        row = raw_relations.get(other_id, {})
        return {"met": True, "at_war": bool(row.get("at_war", public_row.get("at_war", False))),
            "open_borders": bool(row.get("open_borders", False)), "defensive_pact": bool(row.get("defensive_pact", False)),
            "vassal": bool(row.get("vassal", False)), "attitude_id": "ATTITUDE_" + str(row.get("attitude_id", "UNKNOWN")),
            "attitude_value": int(row.get("attitude_value", 0))}
    known_players = []
    relations = []
    for row in public.get("players", []):
        if not isinstance(row, dict):
            continue
        other_id = ident(row.get("id", "0"), "PLAYER")
        if other_id == player_id:
            continue
        relation = relation_for(other_id, row)
        known_players.append({"player_id": other_id, "team_id": ident(row.get("team_id", "0"), "TEAM"),
            "leader_id": str(row.get("leader_id", "UNKNOWN_LEADER")),
            "leader_name": _resolve_leader_display_name(row),
            "civilization_id": str(row.get("civilization_id", "UNKNOWN_CIVILIZATION")),
            "score": row.get("score"), "population": row.get("population"), "land": row.get("land"), "power": row.get("power"),
            "known_capital_city_id": row.get("capital_city_id"), "known_religion_id": row.get("known_religion_id"),
            "known_civic_ids": list(row.get("known_civic_ids", [])), "known_tech_ids": list(row.get("known_tech_ids", [])),
            "relation": relation})
        relations.append({"player_id": other_id, "relation": relation})
    pending_requests = []
    counter_by_request: dict[str, dict[str, Any]] = {}
    for row in visible.get("counteroffer_proposals", []):
        if not isinstance(row, dict) or not row.get("request_id"):
            continue
        counter_by_request[str(row["request_id"])] = {
            "counteroffer_id": str(row.get("counteroffer_id", "")),
            "our_items": _normalize_trade_items(row.get("our_items", [])),
            "their_items": _normalize_trade_items(row.get("their_items", [])),
        }
    for row in visible.get("diplomacy_requests", []):
        if not isinstance(row, dict):
            continue
        request_id = str(row["request_id"])
        entry: dict[str, Any] = {
            "request_id": request_id,
            "from_player_id": str(row["from_player_id"]),
            "kind": "DIPLO_COMMENT_" + str(row.get("comment_id", "UNKNOWN")),
            "our_items": _normalize_trade_items(row.get("our_items", [])),
            "their_items": _normalize_trade_items(row.get("their_items", [])),
            "legal_response_ids": list(row.get("response_ids", [])),
        }
        counter = counter_by_request.get(request_id)
        if counter is not None:
            entry["counteroffer"] = counter
        pending_requests.append(entry)
    available_proposals: list[dict[str, Any]] = []
    seen_proposals: set[str] = set()
    for row in list(visible.get("diplomacy_proposals", [])) + list(source.get("public", {}).get("diplomacy_proposals", [])):
        if not isinstance(row, dict) or not row.get("proposal_id"):
            continue
        proposal_id = str(row["proposal_id"])
        if proposal_id in seen_proposals:
            continue
        seen_proposals.add(proposal_id)
        available_proposals.append({
            "proposal_id": proposal_id,
            "target_player_id": str(row.get("target_player_id", "")),
            "proposal_index": int(row.get("proposal_index", 0)),
        })
    decision_reason = "diplomacy_request" if pending_requests else "turn_start"
    width, height = int(settings.get("width", visible.get("width", 1))), int(settings.get("height", visible.get("height", 1)))
    grid = visible.get("grid", ["?" * width for _ in range(height)])
    visibility_grid = _normalize_visibility_grid(grid if isinstance(grid, list) else [], width, height)
    territory_owner_grid = _normalize_territory_owner_grid(
        visible.get("territory_grid") if isinstance(visible.get("territory_grid"), list) else [],
        width,
        height,
    )
    plots = []
    visible_plots = visible.get("plots")
    if isinstance(visible_plots, list) and visible_plots:
        for row in visible_plots:
            # The DLL is authoritative for revealed/current visibility. Preserve
            # its closed record without inferring information for absent plots.
            plots.append({
                "plot_id": str(row["plot_id"]), "x": int(row["x"]), "y": int(row["y"]),
                "knowledge": row["knowledge"], "last_seen_turn": row.get("last_seen_turn"),
                "area_id": str(row["area_id"]), "terrain_id": str(row["terrain_id"]),
                "water": bool(row["water"]), "hills": bool(row["hills"]), "peak": bool(row["peak"]),
                "fresh_water": bool(row["fresh_water"]), "river_edges": list(row.get("river_edges", [])),
                "revealed_owner_id": row.get("revealed_owner_id"), "feature_id": row.get("feature_id"),
                "improvement_id": row.get("improvement_id"), "route_id": row.get("route_id"),
                "resource_id": row.get("resource_id"), "yields": dict(row.get("yields", {"food": 0, "production": 0, "commerce": 0})),
                "defense_percent": int(row.get("defense_percent", 0)), "city_id": row.get("city_id"),
                "worked_by_city_id": row.get("worked_by_city_id"), "visible_stack_ids": list(row.get("visible_stack_ids", [])),
            })
    elif visibility_grid is not None:
        plots = _plots_from_visibility_grid(visibility_grid, width, height)
    if not plots:
        plots = _synthesize_plots_from_entities(
            visible, own_cities, own_units, other_cities, all_units, width, height, int(source.get("turn", 0)))
    legal = []
    raw_legal = source.get("legal_actions", [])
    legacy_actions = [item for rows in raw_legal.values() for item in rows] if isinstance(raw_legal, dict) else raw_legal
    v2_kinds = {"set_research": "choose_research", "set_civic": "adopt_civics", "set_city_production": "queue_production",
        "set_city_role": "set_city_emphasis", "set_expansion_priority": "set_target_city_or_area", "set_upgrade_policy": "set_upgrade_reserve",
        "set_diplomacy_posture": "set_diplomacy_posture", "set_war_posture": "set_war_plan", "set_army_objective": "set_army_objective",
        "propose_diplomacy": "propose_deal", "respond_diplomacy": "respond_to_deal",
        "counteroffer_diplomacy": "counteroffer", "cancel_deal": "cancel_deal",
        "city_task": "city_task", "unit_command": "unit_command", "unit_mission": "unit_posture_mission",
        "move_group": "unit_mission",
        "set_commerce": "change_commerce", "set_espionage_weight": "change_espionage_weight",
        "convert_religion": "convert_religion", "change_war": "change_war",
        "advanced_start_action": "advanced_start_action", "pop_research": "remove_queue_order"}
    host_automatic = {"end_turn", "auto_moves"}
    for action in legacy_actions if isinstance(legacy_actions, list) else []:
        kind = action.get("kind")
        v2_kind = action.get("v2_kind", v2_kinds.get(kind))
        if not v2_kind or v2_kind in host_automatic:
            continue
        fields = {key: action[key] for key in action if key not in {"action_id", "kind", "sequence", "v2_kind"}}
        command_id = "CMD_" + str(action.get("action_id", kind)).replace(":", "_")
        affected = []
        for value in fields.values():
            text = str(value)
            if text not in affected:
                affected.append(text)
        legal.append({"command_id": command_id, "kind": v2_kind, "description": "Host-approved " + v2_kind,
            "fixed_arguments": fields, "parameter_domains": {}, "affected_ids": affected,
            "runtime_status": RUNTIME_BY_KIND.get(v2_kind, "implemented_untested")})
    command_by_action = {str(item.get("action_id")): "CMD_" + str(item.get("action_id")).replace(":", "_")
                         for item in legacy_actions if isinstance(item, dict) and item.get("action_id")}
    recommendations = []
    for row in source.get("advc_recommendations", []):
        if not isinstance(row, dict):
            continue
        proposed = [command_by_action[action_id] for action_id in row.get("proposed_action_ids", [])
                    if action_id in command_by_action]
        recommendations.append({"recommendation_id": str(row["recommendation_id"]), "kind": str(row["kind"]),
            "execution_state": row["execution_state"], "summary": str(row["summary"])[:300],
            "rationale_facts": [str(item)[:200] for item in row.get("rationale_facts", [])[:12]],
            "affected_ids": list(dict.fromkeys(str(item) for item in row.get("affected_ids", []))),
            "proposed_command_ids": list(dict.fromkeys(proposed))})
    visible_stacks = []
    for row in visible.get("stacks", []):
        if not isinstance(row, dict):
            continue
        stack_id = str(row.get("stack_id", ""))
        owner = str(row.get("owner_id", row.get("owner_player_id", "PLAYER_0")))
        plot_id = str(row.get("plot_id", f"PLOT_{row.get('x', 0)}_{row.get('y', 0)}"))
        type_mix = row.get("type_mix_ids")
        if type_mix is None:
            broad = row.get("broad_mix")
            type_mix = [str(broad)] if broad else []
        else:
            type_mix = [str(item) for item in type_mix]
        visible_stacks.append({"stack_id": stack_id, "owner_player_id": owner, "plot_id": plot_id,
            "unit_count": max(1, int(row.get("unit_count", row.get("count", 1)))),
            "type_mix_ids": list(type_mix), "visible_strength": int(row.get("visible_strength", row.get("strength", 0))),
            "average_health_percent": int(row.get("average_health_percent", 100)),
            "movement_ready": bool(row.get("movement_ready", False))})
    frontiers = []
    for row in visible.get("frontiers", []):
        if not isinstance(row, dict):
            continue
        frontier_id = str(row.get("id", row.get("frontier_id", "FRONTIER_0")))
        area_id = str(row.get("area_id", "AREA_0"))
        frontiers.append({"frontier_id": frontier_id, "plot_ids": list(row.get("plot_ids", [])),
            "adjacent_area_ids": list(row.get("adjacent_area_ids", [area_id]))})
    areas = [{"area_id": str(row.get("id", row.get("area_id", "AREA_0"))),
        "water": bool(row.get("water", False)),
        "revealed_plot_count": int(row.get("revealed_plot_count", 0))} for row in visible.get("areas", []) if isinstance(row, dict)]
    if not areas:
        areas = [{"area_id": "AREA_0", "water": False,
            "revealed_plot_count": sum(1 for item in plots if item["knowledge"] == "visible")}]
    diplomacy_block = {"relations": relations, "active_deals": list(visible.get("active_deals", [])),
        "pending_requests": pending_requests,
        "available_proposals": available_proposals,
        "legal_trade_inventory": [],
        "private_inbox": _private_inbox_from_history(source.get("history", {}), player_id)}
    strategic_summary = _derive_strategic_summary(own_cities, own_units, empire, diplomacy_block)
    for row in source.get("meet_greeting_alerts", []):
        if not isinstance(row, dict) or not row.get("text"):
            continue
        strategic_summary["diplomacy_alerts"].append({
            "kind": str(row.get("kind", "FIRST_MEET")),
            "severity": str(row.get("severity", "info")),
            "affected_ids": list(row.get("affected_ids", [])),
            "text": str(row["text"])[:200],
        })
    history_block = {"accepted_decisions": list(source.get("history", {}).get("accepted_decisions", [])),
        "command_results": list(source.get("history", {}).get("command_results", [])),
        "public_events": _recent_history_events(
            list(source.get("history", {}).get("public_events", [])),
            chat_history_max_messages(),
        ),
        "diplomacy_events": list(source.get("history", {}).get("diplomacy_events", [])),
        "memory_summary": str(source.get("history", {}).get("goal_summary", source.get("history", {}).get("memory_summary", "")))[:4000],
        "player_opinions": dict(source.get("history", {}).get("player_opinions", {})) if isinstance(source.get("history", {}).get("player_opinions"), dict) else {},
        "player_histories": dict(source.get("history", {}).get("player_histories", {})) if isinstance(source.get("history", {}).get("player_histories"), dict) else {},
        **({"civ4ai_thought_memory": copy.deepcopy(source.get("history", {}).get("civ4ai_thought_memory"))}
           if isinstance(source.get("history", {}).get("civ4ai_thought_memory"), dict) else {})}
    return {"schema_version": "civ4ai-input/2", "decision": {"turn": int(source.get("turn", 0)), "year": int(source.get("year", source.get("turn", 0))), "phase": "strategic_decision", "player_id": player_id, "reason": decision_reason},
        "personality": _build_personality(player, active),
        "game": {"era_id": player.get("era_id", "ERA_UNKNOWN"), "start_era_id": settings.get("start_era", "ERA_UNKNOWN"), "game_speed_id": settings.get("game_speed", "GAMESPEED_NORMAL"), "difficulty_id": "HANDICAP_UNKNOWN", "calendar_id": "CALENDAR_DEFAULT", "map_script": settings.get("map_script", "UNKNOWN"), "world_size_id": settings.get("world_size", "WORLDSIZE_UNKNOWN"), "climate_id": settings.get("climate", "CLIMATE_UNKNOWN"), "sea_level_id": settings.get("sea_level", "SEALEVEL_UNKNOWN"), "map_width": width, "map_height": height, "wrap_x": False, "wrap_y": False, "max_turns": settings.get("max_turns"), "options": settings.get("options", []), "victory_ids": [], "network_multiplayer": bool(source.get("network_multiplayer", False))},
        "your_empire": {"team_id": str(empire.get("team_id", "TEAM_" + str(active))), "score": int(empire.get("score", 0)), "gold": int(empire.get("gold", player.get("gold", 0))), "gold_per_turn": int(empire.get("gold_per_turn", 0)), "commerce": empire.get("commerce", {k: {"percent": 0, "rate": int(player.get("commerce_rate", 0)) if k == "research" else 0} for k in ("gold", "research", "culture", "espionage")}), "costs": empire.get("costs", {"unit_cost": 0, "unit_supply": 0, "city_maintenance": 0, "civic_upkeep": 0, "inflation": 0}), "research": {"tech_id": player.get("research_id"), "progress": int(player.get("research_progress", 0)), "cost": int(player.get("research_cost", 0)), "research_per_turn": int(player.get("research_rate", 0)), "estimated_turns_remaining": None, "queue": list(empire.get("research_queue", [])), "known_tech_ids": list(empire.get("known_tech_ids", []))}, "civics": list(empire.get("civics", [])), "religion": {"state_religion_id": empire.get("state_religion_id"), "convertible_religion_ids": [], "conversion_timer": 0}, "resources": list(empire.get("resources", [])), "unit_counts": empire.get("unit_counts", {k: 0 for k in ("total", "workers", "settlers", "military", "missionaries", "spies", "great_people", "idle", "upgradeable")}), "anarchy_turns": int(empire.get("anarchy_turns", 0)), "golden_age_turns": int(empire.get("golden_age_turns", 0)), "war_weariness": int(empire.get("war_weariness", 0)), "victory_progress": []},
        "your_cities": own_cities, "your_units": own_units, "known_players": known_players, "known_other_cities": other_cities, "visible_other_units": other_units,
        "diplomacy": diplomacy_block,
        "known_map": {"format": "plot-grid-v1", "visibility_mode": "player_visible", "plots": plots, "areas": areas,
            "frontiers": frontiers, "visible_stacks": visible_stacks,
            **({"visibility_grid": visibility_grid} if visibility_grid is not None else {}),
            **({"territory_owner_grid": territory_owner_grid} if territory_owner_grid is not None else {}),
            "image": {"attached": map_image_attach_turn({"decision": {"turn": int(source.get("turn", 0)), "player_id": player_id}}),
                "format": "png-grid-v1", "width": width, "height": height,
                "legend": [
                    {"symbol": "?", "meaning": "unrevealed fog"},
                    {"symbol": "yellow", "meaning": "your city"},
                    {"symbol": "cyan", "meaning": "your unit"},
                    {"symbol": "red", "meaning": "foreign unit"},
                    {"symbol": "green", "meaning": "unit stack"},
                ],
                "label_ids": [item["city_id"] for item in own_cities]}},
        "strategic_summary": strategic_summary,
        "history": history_block,
        "advciv": {
            "default_unit_controller": "advciv",
            "fallback_policy": ADVCIV_FALLBACK_POLICY,
            "recommendations": recommendations,
        }, "legal_commands": legal}


def normalize_image_attachments(
    image_data_url: str | list[dict[str, str]] | list[str] | None,
) -> list[dict[str, str]]:
    """Accept a single data URL or a list of situational map attachments."""
    if image_data_url is None:
        return []
    if isinstance(image_data_url, str):
        if not image_data_url.strip():
            return []
        return [{"data_url": image_data_url, "detail": "low", "role": "map", "label": "map"}]
    attachments: list[dict[str, str]] = []
    for item in image_data_url:
        if isinstance(item, str) and item.strip():
            attachments.append({"data_url": item, "detail": "low", "role": "map", "label": "map"})
        elif isinstance(item, dict):
            data_url = item.get("data_url")
            if isinstance(data_url, str) and data_url.strip():
                attachments.append({
                    "data_url": data_url,
                    "detail": str(item.get("detail", "low")),
                    "role": str(item.get("role", "map")),
                    "label": str(item.get("label", "")),
                })
    return attachments


def build_responses_input(
    snapshot: dict[str, Any],
    image_data_url: str | list[dict[str, str]] | list[str] | None = None,
) -> list[dict[str, Any]]:
    if snapshot.get("schema_version") == "civ6ai-input/1" or _is_civ5_snapshot(snapshot):
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": build_model_wire_text(snapshot)}
        ]
        if map_image_attach_turn(snapshot):
            for attachment in normalize_image_attachments(image_data_url):
                content.append({
                    "type": "input_image",
                    "image_url": attachment["data_url"],
                    "detail": attachment.get("detail", "low"),
                })
        return [{"role": "user", "content": content}]
    validate_snapshot(snapshot)
    content = [
        {"type": "input_text", "text": build_model_wire_text(snapshot)}
    ]
    if map_image_attach_turn(snapshot):
        for attachment in normalize_image_attachments(image_data_url):
            content.append({
                "type": "input_image",
                "image_url": attachment["data_url"],
                "detail": attachment.get("detail", "low"),
            })
    return [{"role": "user", "content": content}]


def _model_role_instruction(snapshot: dict[str, Any]) -> str:
    if snapshot.get("schema_version") == "civ6ai-input/1":
        from sidecar import civ6_wire
        return civ6_wire.build_civ6_role_instruction(snapshot)
    if _is_civ5_snapshot(snapshot):
        from sidecar import civ5_wire
        return civ5_wire.build_civ5_role_instruction(snapshot)
    personality = snapshot.get("personality", {})
    leader = personality.get("leader_name", personality.get("leader_id", "the seated leader"))
    civ_id = personality.get("civilization_id")
    civ_label = _readable_id(civ_id, "CIVILIZATION_") if civ_id else ""
    role = f"You are {leader}"
    if civ_label:
        role += f", playing as the {civ_label} civilization"
    attach_map = map_image_attach_turn(snapshot)
    map_clause = (
        " A minimap image is attached with each turn — read geography and unit positions from it. "
        if attach_map else ""
    )
    gandhi_clause = _gandhi_role_clause() if _is_gandhi_leader(snapshot) else ""
    return (
        f"{role}, in a live Civilization IV multiplayer match. "
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
        f"{ADVCIV_FALLBACK_POLICY}"
    )


def _unit_legal_command_count(snapshot: dict[str, Any]) -> int:
    count = 0
    unit_ids = {
        unit.get("unit_id")
        for unit in snapshot.get("your_units", [])
        if isinstance(unit, dict) and unit.get("unit_id")
    }
    for command in snapshot.get("legal_commands", []):
        if not isinstance(command, dict):
            continue
        fixed = command.get("fixed_arguments", {})
        if isinstance(fixed, dict) and fixed.get("unit_id") in unit_ids:
            if command.get("kind") not in HOST_AUTOMATIC_KINDS:
                count += 1
    return count


def _unit_move_legal_available(snapshot: dict[str, Any]) -> bool:
    unit_ids = {
        unit.get("unit_id")
        for unit in snapshot.get("your_units", [])
        if isinstance(unit, dict) and unit.get("unit_id")
    }
    for command in snapshot.get("legal_commands", []):
        if not isinstance(command, dict):
            continue
        fixed = command.get("fixed_arguments", {})
        if not isinstance(fixed, dict) or fixed.get("unit_id") not in unit_ids:
            continue
        prop_name, _ = _unit_command_property_parts(command)
        if prop_name == "moveTo":
            return True
    return False


def _is_trade_diplomacy_request(request: dict[str, Any]) -> bool:
    request_id = str(request.get("request_id", ""))
    if request_id.startswith("DIPLO_TRADE_"):
        return True
    our_items = request.get("our_items", [])
    their_items = request.get("their_items", [])
    return bool(our_items or their_items)


def _pending_trade_offer_prompt_lines(snapshot: dict[str, Any]) -> list[str]:
    diplomacy = snapshot.get("diplomacy", {})
    if not isinstance(diplomacy, dict):
        return []
    pending = diplomacy.get("pending_requests", [])
    if not isinstance(pending, list):
        return []
    trade_pending = [
        row for row in pending
        if isinstance(row, dict) and _is_trade_diplomacy_request(row)
    ]
    if not trade_pending:
        return []
    lines = [
        "A rival has sent you a trade proposal (diplomacy.pending.*). "
        "Respond only while that exact offer is still pending and actionable.",
        "Pick exactly one formal response via cmd.N = diplomacy.pending.N.accept_cmd "
        "(accept the deal as written), cmd.N = diplomacy.pending.N.reject_cmd (decline), "
        "or cmd.N = diplomacy.pending.N.counteroffer_cmd when listed (counter with different terms).",
        "State accept, reject, or counter clearly in decision_summary.",
        "Do not repeat accept/reject chat or respond_to_deal for an offer you already "
        "accepted or rejected in prior chat unless diplomacy.pending terms changed.",
        "Also send a private DM to the proposing leader (chat.LeaderName = ...) when you "
        "issue a new formal response: explain your thinking, negotiate, or warn before reject.",
    ]
    for index, request in enumerate(trade_pending[:6]):
        from_id = str(request.get("from_player_id", ""))
        leader = _player_chat_name(snapshot, from_id) if from_id else "the proposer"
        they_give = _format_trade_items_wire(request.get("their_items", []))
        we_give = _format_trade_items_wire(request.get("our_items", []))
        lines.append(
            f"Offer diplomacy.pending.{index} from {leader} ({from_id}): "
            f"they give {they_give}; you give {we_give}."
        )
    return lines


def _diplomatic_strategy_guidance(snapshot: dict[str, Any]) -> list[str]:
    del snapshot
    return [
        "Diplomacy: model what rivals want and fear, probe and trade when it advances your win — "
        "DMs for deals, plotting, and banter; chat.all for posture when the lobby isn't already noisy every turn; "
        "use diplomacy.proposal.* and CMD_* when legal.",
        "Use set_diplomacy_posture (POSTURE_FRIENDLY, POSTURE_HOSTILE, POSTURE_TRADE, etc.) "
        "to set how you feel toward each met rival; feelings do not gate your trade or war commands.",
        "Whenever you issue a propose_deal command (cmd.N = CMD_propose_*), you MUST also send "
        "a private chat line to that leader (chat.LeaderName = ...) explaining the offer.",
        "In thought.strategy, name which rivals you are courting, isolating, or appeasing and why.",
    ]


def _diplomacy_prompt_bias_lines(snapshot: dict[str, Any]) -> list[str]:
    """Temporary harness hook: set CIV4AI_PROMPT_DIPLOMACY_BIAS=1 to nudge diplomacy tests."""
    raw = os.environ.get("CIV4AI_PROMPT_DIPLOMACY_BIAS", "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return []
    diplomacy = snapshot.get("diplomacy", {})
    proposals = diplomacy.get("available_proposals", []) if isinstance(diplomacy, dict) else []
    pending = diplomacy.get("pending_requests", []) if isinstance(diplomacy, dict) else []
    lines = [
        "TEMP DIPLOMACY BIAS (harness only): every major civ is met. If diplomacy.proposal.* "
        "or diplomacy.pending.* lines exist, include at least one propose_deal, respond_to_deal, "
        "counteroffer, or cancel_deal command this turn (use the listed CMD_* ids).",
        "Prefer mutual open borders or defensive pact proposals when legal; mention the deal in decision_summary.",
    ]
    if proposals:
        lines.append("Available proposals are under diplomacy.proposal.* — bind via cmd.N = CMD_propose_*.")
    if pending:
        lines.append("Pending offers are under diplomacy.pending.* — use accept_cmd / reject_cmd / counteroffer_cmd.")
    return lines


def _model_response_instructions(snapshot: dict[str, Any]) -> str:
    personality = snapshot.get("personality", {})
    leader = personality.get("leader_name", personality.get("leader_id", "the seated leader"))
    civ_id = personality.get("civilization_id")
    civ_label = _readable_id(civ_id, "CIVILIZATION_") if civ_id else ""
    leader_label = leader + (f", playing as the {civ_label} civilization" if civ_label else "")
    lines = [
        "=== INSTRUCTIONS ===",
        f"You are {leader_label}. Read CURRENT SITUATION, MAP, and LEGAL COMMANDS above.",
        "Reply with flat key=value lines only — never JSON, braces, or code fences.",
        "The host ends your turn automatically after this response.",
        "",
        "Required reply format (in this order):",
        "1. thought.situation = your read of the board in this leader's inner voice — rivals, "
        "economy, threats, momentum (still factual, but colored by their personality)",
        "2. thought.strategy = your long-term path to victory in character — expansion "
        "(settlers and new cities), diplomacy (alliances, trades, rival psychology), and "
        "concrete actions for this turn",
        "3. opinion.LeaderName = one short line when your view of a met/heard rival changes (trust, threat); "
        "omit unchanged rivals",
        "4. history.LeaderName = only on a major relationship event this turn (first meet, deal, war, betrayal); "
        "one terse T{n} fragment; skip routine chat and filler",
        "5. decision_summary = one line naming concrete actions; a brief in-character phrase is welcome",
        "6. Commands — issue as many city/unit/empire lines as you need this turn:",
        "   City: cityName.property = value (e.g. Capital.changeProduction = worker)",
        "   Unit: unitId.property = value; to move, set unitId.moveTo = (x,y) or stack.moveTo = (x,y)",
        "   Empire: legal.commerce.* / legal.expansion = value, or cmd.N = CMD_* when listed",
        "7. chat.all / chat.team / chat.LeaderName (optional, sparse — skip most turns; if chat.public.* shows "
        "messages nearly every turn, hold off on chat.all):",
        "",
        "Rules:",
        f"- The host applies your overrides first; {ADVCIV_FALLBACK_POLICY}",
        "- Settlers and new cities are top priorities: keep cities building settlers when "
        "expansion is viable, move idle settlers toward good sites every turn, and found "
        "cities (found_city) as soon as a legal tile is available.",
    ]
    lines.extend(f"- {line}" for line in _diplomatic_strategy_guidance(snapshot))
    lines.extend([
        "- Movement: use coordinates listed under LEGAL COMMANDS (e.g. scout_1.moveTo = (28,31)).",
        "- Before moving, carefully inspect the attached minimap and each unit's position in "
        "CURRENT SITUATION — pick a tile that advances exploration, expansion, or defense.",
        "- Do not queue production already building.",
        "- Commands marked risk=high need to be carefully considered.",
        "- decision_summary must name concrete actions.",
    ])
    lines.extend(f"- {line}" for line in _chat_voice_guidance(snapshot))
    lines.extend(f"- {line}" for line in _chat_format_guidance(snapshot))
    lines.extend([
        "- thought.tN.situation lines in CURRENT SITUATION are your prior board reads — use them for long-term memory.",
        "- opinion.* lines are your stored rival view — emit opinion.LeaderName only when it changes.",
        "- history.* is append-only; add a T{n} fragment only for major relationship shifts, not every message.",
        "- advice.N lines are native AI suggestions; you may follow or override them.",
    ])
    if _has_unit_stacks({"your_units": snapshot.get("your_units", [])}):
        lines.extend([
            "- Co-located units appear under stack.* in CURRENT SITUATION (e.g. stack.worker_1).",
            "- To move the whole tile together, use stack.moveTo = (x,y) when listed, or any unit id "
            "under that stack with a matching moveTo option.",
        ])
    bias = _diplomacy_prompt_bias_lines(snapshot)
    if bias:
        lines.extend(["", "=== TEMP DIPLOMACY BIAS ==="])
        lines.extend(f"- {line}" for line in bias)
    trade_offer = _pending_trade_offer_prompt_lines(snapshot)
    if trade_offer:
        lines.extend(["", "=== TRADE OFFER — RESPOND THIS TURN ==="])
        lines.extend(f"- {line}" for line in trade_offer)
    return "\n".join(lines)


def _model_instructions(snapshot: dict[str, Any], api_thinking: bool = False) -> str:
    """Combined role + response rules (legacy helper and OpenAI-style single blob)."""
    del api_thinking
    return _model_role_instruction(snapshot) + "\n\n" + _model_response_instructions(snapshot)


def _http_error_category(status_code: int) -> str:
    if status_code in RATE_LIMIT_HTTP_CODES:
        return "rate_limit"
    if status_code in {401, 403}:
        return "http_auth"
    return "http_error"


def resolve_gemini_api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()


def gemini_model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or GEMINI_MODEL_DEFAULT


def gemini_api_mode() -> str:
    raw = os.environ.get("CIV4AI_GEMINI_API", "interactions").strip().lower()
    if raw in {"interactions", "generatecontent", "generate_content"}:
        return "interactions" if raw == "interactions" else "generateContent"
    return "interactions"


def gemini_thinking_level() -> str:
    raw = os.environ.get("GEMINI_THINKING_LEVEL", "medium").strip().lower()
    return raw if raw in {"minimal", "low", "medium", "high"} else "medium"


def gemini_thinking_budget() -> int:
    raw = os.environ.get("GEMINI_THINKING_BUDGET", "-1").strip()
    try:
        return int(raw)
    except ValueError:
        return -1


def gemini_max_output_tokens() -> int:
    raw = os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", str(GEMINI_MAX_OUTPUT_TOKENS_DEFAULT)).strip()
    try:
        return max(512, min(65536, int(raw)))
    except ValueError:
        return GEMINI_MAX_OUTPUT_TOKENS_DEFAULT


def _valid_gemini_chain_id(response_id: str | None) -> str | None:
    if not isinstance(response_id, str) or not response_id.strip():
        return None
    rid = response_id.strip()
    if rid.startswith("gemini-") and rid.count("-") >= 3:
        return None
    return rid


def _split_api_thought(full: str) -> dict[str, str]:
    text = full.strip()
    if not text:
        return {"situation": "", "strategy": ""}
    if "\n\n" in text:
        situation, strategy = text.split("\n\n", 1)
        return {"situation": _clip_thought(situation), "strategy": _clip_thought(strategy)}
    mid = max(1, len(text) // 2)
    return {"situation": _clip_thought(text[:mid]), "strategy": _clip_thought(text[mid:])}


def _merge_api_thought_into_result(result: dict[str, Any], private_thought: str) -> dict[str, Any]:
    if not private_thought.strip():
        return result
    api_thought = _split_api_thought(private_thought)
    wire_thought = result.get("thought")
    if not isinstance(wire_thought, dict) or not str(wire_thought.get("situation", "")).strip():
        result["thought"] = api_thought
    elif not str(wire_thought.get("strategy", "")).strip() and api_thought.get("strategy"):
        result["thought"] = {
            "situation": _clip_thought(str(wire_thought.get("situation", ""))),
            "strategy": api_thought["strategy"],
        }
    return result


def _extract_interaction_thought_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for step in payload.get("steps", []):
        if not isinstance(step, dict) or step.get("type") != "thought":
            continue
        summary = step.get("summary", [])
        if not isinstance(summary, list):
            continue
        for item in summary:
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                parts.append(item["text"].strip())
    return "\n\n".join(parts)


def _extract_interaction_output_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    for step in payload.get("steps", []):
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                text = item["text"].strip()
                if text:
                    texts.append(text)
    if texts:
        return texts[-1] if len(texts) == 1 else "\n".join(texts)
    outputs = payload.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    step_types = [
        step.get("type") for step in payload.get("steps", [])
        if isinstance(step, dict) and step.get("type")
    ]
    status = payload.get("status")
    detail = f"status={status!r} step_types={step_types!r}"
    raise BoundaryError("api_output", f"Gemini interaction has no model_output text ({detail})")


def _gemini_interaction_id(payload: dict[str, Any]) -> str | None:
    interaction_id = payload.get("id")
    if isinstance(interaction_id, str) and interaction_id.strip():
        return interaction_id.strip()
    return None


def model_fallback_enabled() -> bool:
    return os.environ.get("CIV4AI_DISABLE_MODEL_FALLBACK", "").strip() not in {"1", "true", "yes"}


SUPPORTED_MODEL_IMAGE_MIMES = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
})


def _parse_image_data_url(data_url: str) -> tuple[str, bytes]:
    if not data_url.startswith("data:") or "," not in data_url:
        raise BoundaryError("invalid_image", "Map image must be a data URL")
    header, encoded = data_url.split(",", 1)
    mime = header.split(";")[0].split(":", 1)[1]
    if mime not in SUPPORTED_MODEL_IMAGE_MIMES:
        raise BoundaryError(
            "invalid_image",
            f"Map image mime {mime!r} is not supported by vision APIs; use PNG or JPEG",
        )
    return mime, base64.b64decode(encoded)


def _gemini_generate_content_parts(payload: dict[str, Any]) -> tuple[str, str]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise BoundaryError("api_output", "Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not isinstance(parts, list):
        raise BoundaryError("api_output", "Gemini candidate has no parts")
    thought_texts: list[str] = []
    output_texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if part.get("thought") is True:
            thought_texts.append(text.strip())
        else:
            output_texts.append(text.strip())
    if not output_texts:
        raise BoundaryError("api_output", "Gemini returned no output text part")
    if len(output_texts) != 1:
        raise BoundaryError("api_output", "Gemini returned other than one output text part")
    return output_texts[0], "\n\n".join(thought_texts)


def _gemini_response_text(payload: dict[str, Any]) -> str:
    return _gemini_generate_content_parts(payload)[0]


def _response_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                texts.append(content["text"])
    if len(texts) != 1:
        raise BoundaryError("api_output", "Responses API returned other than one text item")
    return texts[0]


def call_responses(
    snapshot: dict[str, Any],
    api_key: str,
    image_data_url: str | list[dict[str, str]] | list[str] | None = None,
    previous_response_id: str | None = None,
    timeout_seconds: int = MODEL_DEADLINE_SECONDS,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One bounded Responses call. Only transient transport/server failures retry."""
    if not api_key:
        raise BoundaryError("missing_key", "OPENAI_API_KEY is not configured")
    body: dict[str, Any] = {"model": RESPONSES_MODEL, "reasoning": {"effort": openai_reasoning_effort()}, "store": True,
        "input": build_responses_input(snapshot, image_data_url)}
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
        body["reasoning"]["context"] = "all_turns"
    request = urllib_request.Request(RESPONSES_URL, data=canonical_json(body).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
    open_request = opener or urllib_request.urlopen
    started = time.monotonic()
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            with open_request(request, timeout=timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise BoundaryError("oversized_output", "Responses API body exceeds limit")
                payload = json.loads(raw.decode("utf-8"))
                result = parse_model_text(_response_text(payload))
                metadata = {"status": getattr(response, "status", 200), "model": payload.get("model"),
                    "response_id": payload.get("id"), "usage": payload.get("usage", {}),
                    "latency_ms": int((time.monotonic() - started) * 1000)}
                return result, metadata
        except urllib_error.HTTPError as error:
            detail = ""
            retry_after = None
            try:
                detail = error.read(2000).decode("utf-8", errors="replace")
            except Exception:
                pass
            if hasattr(error, "headers") and error.headers is not None:
                retry_after = error.headers.get("Retry-After")
            if error.code not in TRANSIENT_HTTP_CODES or attempt >= max_attempts - 1:
                message = f"Responses API HTTP {error.code}"
                if retry_after:
                    message += f" (retry-after={retry_after})"
                if detail:
                    message += ": " + detail[:500]
                raise BoundaryError(_http_error_category(error.code), message) from error
            time.sleep(float(retry_after or (2 * (attempt + 1))))
        except (urllib_error.URLError, ConnectionResetError, TimeoutError) as error:
            if attempt >= max_attempts - 1:
                raise BoundaryError("transport", "Responses API transport failed") from error
            time.sleep(2 * (attempt + 1))
    raise BoundaryError("transport", "Responses API transport failed")


def _gemini_response_id(payload: dict[str, Any], snapshot: dict[str, Any]) -> str:
    for key in ("responseId", "response_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    decision = snapshot.get("decision", {}) if isinstance(snapshot.get("decision"), dict) else {}
    turn = decision.get("turn", 0)
    player_id = decision.get("player_id", "unknown")
    return f"gemini-{gemini_model_name()}-{turn}-{player_id}"


def _build_gemini_interactions_input(
    snapshot: dict[str, Any],
    image_data_url: str | list[dict[str, str]] | list[str] | None,
) -> list[dict[str, Any]]:
    wire = build_model_wire_text(snapshot)
    items: list[dict[str, Any]] = [{"type": "text", "text": wire}]
    if map_image_attach_turn(snapshot):
        for attachment in normalize_image_attachments(image_data_url):
            mime, raw = _parse_image_data_url(attachment["data_url"])
            items.append({
                "type": "image",
                "data": base64.b64encode(raw).decode("ascii"),
                "mime_type": mime,
            })
    return items


def _gemini_http_post(url: str, api_key: str, body: dict[str, Any], timeout_seconds: int,
                      opener: Callable[..., Any] | None) -> tuple[dict[str, Any], int]:
    request = urllib_request.Request(
        url,
        data=canonical_json(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    open_request = opener or urllib_request.urlopen
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            with open_request(request, timeout=timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise BoundaryError("oversized_output", "Gemini API body exceeds limit")
                return json.loads(raw.decode("utf-8")), getattr(response, "status", 200)
        except urllib_error.HTTPError as error:
            detail = ""
            retry_after = None
            try:
                detail = error.read(2000).decode("utf-8", errors="replace")
            except Exception:
                pass
            if hasattr(error, "headers") and error.headers is not None:
                retry_after = error.headers.get("Retry-After")
            if error.code not in TRANSIENT_HTTP_CODES or attempt >= max_attempts - 1:
                message = f"Gemini API HTTP {error.code}"
                if retry_after:
                    message += f" (retry-after={retry_after})"
                if detail:
                    message += ": " + detail[:500]
                raise BoundaryError(_http_error_category(error.code), message) from error
            time.sleep(float(retry_after or (2 * (attempt + 1))))
        except (urllib_error.URLError, ConnectionResetError, TimeoutError) as error:
            if attempt >= max_attempts - 1:
                raise BoundaryError("transport", "Gemini API transport failed") from error
            time.sleep(2 * (attempt + 1))
    raise BoundaryError("transport", "Gemini API transport failed")


def call_gemini_interactions(
    snapshot: dict[str, Any],
    api_key: str,
    image_data_url: str | list[dict[str, str]] | list[str] | None = None,
    previous_interaction_id: str | None = None,
    timeout_seconds: int = MODEL_DEADLINE_SECONDS,
                             opener: Callable[..., Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    model = gemini_model_name()
    body: dict[str, Any] = {
        "model": model,
        "store": True,
        "system_instruction": _model_role_instruction(snapshot),
        "input": _build_gemini_interactions_input(snapshot, image_data_url),
        "generation_config": {
            "max_output_tokens": gemini_max_output_tokens(),
            "thinking_level": gemini_thinking_level(),
            "thinking_summaries": "auto",
        },
    }
    chain_id = _valid_gemini_chain_id(previous_interaction_id)
    if chain_id:
        body["previous_interaction_id"] = chain_id
    started = time.monotonic()
    payload, status = _gemini_http_post(GEMINI_INTERACTIONS_URL, api_key, body, timeout_seconds, opener)
    try:
        output_text = _extract_interaction_output_text(payload)
    except BoundaryError as error:
        if chain_id:
            retry_body = dict(body)
            retry_body.pop("previous_interaction_id", None)
            payload, status = _gemini_http_post(
                GEMINI_INTERACTIONS_URL, api_key, retry_body, timeout_seconds, opener,
            )
            output_text = _extract_interaction_output_text(payload)
            metadata_retry = True
        else:
            raise error
    else:
        metadata_retry = False
    private_thought = _extract_interaction_thought_text(payload)
    result = _merge_api_thought_into_result(
        parse_model_text(output_text),
        private_thought,
    )
    usage = payload.get("usage", {}) if isinstance(payload.get("usage"), dict) else {}
    metadata = {
        "status": status,
        "provider": "gemini",
        "api": "interactions",
        "model": payload.get("model", model),
        "response_id": _gemini_interaction_id(payload) or _gemini_response_id(payload, snapshot),
        "private_thought": private_thought[:thought_max_chars() * 2],
        "usage": {
            "input_tokens": usage.get("total_input_tokens", 0),
            "output_tokens": usage.get("total_output_tokens", 0),
            "thought_tokens": usage.get("total_thought_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    if metadata_retry:
        metadata["interaction_chain_retry"] = True
    if isinstance(payload.get("status"), str):
        metadata["interaction_status"] = payload.get("status")
    return result, metadata


def call_gemini_generate_content(
    snapshot: dict[str, Any],
    api_key: str,
    image_data_url: str | list[dict[str, str]] | list[str] | None = None,
    timeout_seconds: int = MODEL_DEADLINE_SECONDS,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = gemini_model_name()
    parts: list[dict[str, Any]] = [{"text": build_model_wire_text(snapshot)}]
    if map_image_attach_turn(snapshot):
        for attachment in normalize_image_attachments(image_data_url):
            mime, raw = _parse_image_data_url(attachment["data_url"])
            parts.append({
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(raw).decode("ascii"),
                }
            })
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": gemini_max_output_tokens(),
            "thinkingConfig": {
                "thinkingBudget": gemini_thinking_budget(),
                "includeThoughts": True,
            },
        },
    }
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"
    started = time.monotonic()
    payload, status = _gemini_http_post(url, api_key, body, timeout_seconds, opener)
    output_text, private_thought = _gemini_generate_content_parts(payload)
    result = _merge_api_thought_into_result(parse_model_text(output_text), private_thought)
    usage_meta = payload.get("usageMetadata", {})
    metadata = {
        "status": status,
        "provider": "gemini",
        "api": "generateContent",
        "model": model,
        "response_id": _gemini_response_id(payload, snapshot),
        "private_thought": private_thought[:thought_max_chars() * 2],
        "usage": {
            "input_tokens": usage_meta.get("promptTokenCount", 0),
            "output_tokens": usage_meta.get("candidatesTokenCount", 0),
            "thought_tokens": usage_meta.get("thoughtsTokenCount", 0),
            "total_tokens": usage_meta.get("totalTokenCount", 0),
        },
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    return result, metadata


def call_gemini(
    snapshot: dict[str, Any],
    api_key: str,
    image_data_url: str | list[dict[str, str]] | list[str] | None = None,
    previous_interaction_id: str | None = None,
    timeout_seconds: int = MODEL_DEADLINE_SECONDS,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Gemini call: Interactions API (default) with server-side thought continuity, or generateContent."""
    if not api_key:
        raise BoundaryError("missing_key", "GEMINI_API_KEY is not configured")
    if gemini_api_mode() == "interactions":
        return call_gemini_interactions(
            snapshot, api_key, image_data_url, previous_interaction_id, timeout_seconds, opener)
    return call_gemini_generate_content(snapshot, api_key, image_data_url, timeout_seconds, opener)


def call_model(
    snapshot: dict[str, Any],
    openai_api_key: str,
    image_data_url: str | list[dict[str, str]] | list[str] | None = None,
    previous_response_id: str | None = None,
    timeout_seconds: int = MODEL_DEADLINE_SECONDS,
    gemini_api_key: str | None = None,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Primary model call: LM Studio (local), Gemini, or OpenAI with optional fallback."""
    provider = model_provider()
    if provider == "lmstudio":
        from sidecar import lmstudio_client
        from sidecar.civ6_config import load_local_config

        cfg = load_local_config()
        if timeout_seconds and timeout_seconds > cfg.timeout_seconds:
            cfg.timeout_seconds = int(timeout_seconds)
        result, metadata = lmstudio_client.call_lmstudio_chat(
            snapshot,
            cfg=cfg,
            image_data_url=image_data_url,
            opener=opener,
        )
        return result, metadata

    gemini_key = (gemini_api_key or resolve_gemini_api_key()).strip()
    openai_key = openai_api_key.strip()

    def _openai_primary() -> tuple[dict[str, Any], dict[str, Any]]:
        result, metadata = call_responses(snapshot, openai_key, image_data_url, previous_response_id,
            timeout_seconds, opener)
        metadata["provider"] = "openai"
        return result, metadata

    def _gemini_primary() -> tuple[dict[str, Any], dict[str, Any]]:
        if not gemini_key:
            raise BoundaryError("missing_key", "GEMINI_API_KEY is not configured")
        result, metadata = call_gemini(
            snapshot, gemini_key, image_data_url, previous_response_id, timeout_seconds, opener)
        return result, metadata

    def _fallback_openai(from_provider: str, reason: str, prior: BoundaryError) -> tuple[dict[str, Any], dict[str, Any]]:
        if not model_fallback_enabled() or not openai_key:
            raise prior
        try:
            result, metadata = _openai_primary()
            metadata["fallback_from"] = from_provider
            metadata["fallback_reason"] = reason
            return result, metadata
        except BoundaryError as error:
            raise BoundaryError(reason,
                f"{from_provider} failed and OpenAI fallback failed: {error}") from error

    def _fallback_gemini(from_provider: str, reason: str, prior: BoundaryError) -> tuple[dict[str, Any], dict[str, Any]]:
        if not model_fallback_enabled() or not gemini_key:
            raise prior
        try:
            result, metadata = _gemini_primary()
            metadata["fallback_from"] = from_provider
            metadata["fallback_reason"] = reason
            return result, metadata
        except BoundaryError as error:
            raise BoundaryError(reason,
                f"{from_provider} failed and Gemini fallback failed: {error}") from error

    if provider == "openai":
        if not openai_key:
            if gemini_key and model_fallback_enabled():
                return _gemini_primary()
            raise BoundaryError("missing_key", "OPENAI_API_KEY is not configured")
        try:
            return _openai_primary()
        except BoundaryError as error:
            if error.category != "rate_limit":
                raise
            return _fallback_gemini("openai", "rate_limit", error)

    if gemini_key:
        try:
            return _gemini_primary()
        except BoundaryError as error:
            if error.category not in {"rate_limit", "missing_key"}:
                raise
            return _fallback_openai("gemini", error.category, error)
    if openai_key and model_fallback_enabled():
        return _openai_primary()
    raise BoundaryError("missing_key", "GEMINI_API_KEY is not configured")


def _domain_compatible(recommendation: dict[str, Any], command: dict[str, Any]) -> bool:
    affected = set(recommendation["affected_ids"])
    return not affected or bool(affected.intersection(command["affected_ids"]))


def _readable_proposal_label(proposal_id: str) -> str:
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        return "a diplomatic offer"
    upper = proposal_id.upper()
    if "DEFENSIVE_PACT" in upper:
        return "a defensive pact"
    if "OPEN_BORDERS" in upper:
        return "open borders"
    if "PERMANENT_ALLIANCE" in upper:
        return "a permanent alliance"
    if "TRADE" in upper or "GOLD" in upper or "TECH" in upper:
        return "a trade arrangement"
    return _readable_id(proposal_id, "PROPOSAL_").replace("_", " ").lower()


def _proposal_target_player_id(command_id: str, catalog_entry: dict[str, Any]) -> str | None:
    fixed = catalog_entry.get("fixed_arguments", {})
    if not isinstance(fixed, dict):
        fixed = {}
    target = fixed.get("target_player_id")
    if isinstance(target, str) and target.startswith("PLAYER_"):
        return target
    match = re.match(r"CMD_propose_diplomacy_(PLAYER_\d+)_", command_id)
    if match:
        return match.group(1)
    return None


def _proposal_chat_text(
    snapshot: dict[str, Any],
    target_player_id: str,
    catalog_entry: dict[str, Any],
    decision_summary: str,
) -> str:
    leader = _player_chat_name(snapshot, target_player_id)
    fixed = catalog_entry.get("fixed_arguments", {})
    proposal_id = fixed.get("proposal_id", "") if isinstance(fixed, dict) else ""
    label = _readable_proposal_label(proposal_id if isinstance(proposal_id, str) else "")
    summary = decision_summary.strip() if isinstance(decision_summary, str) else ""
    if summary and len(summary) <= 180:
        return f"{leader}, {summary}"
    return f"{leader}, I wish to propose {label} between our nations — let us discuss terms."


def _ensure_proposal_chat_messages(snapshot: dict[str, Any], normalized: dict[str, Any]) -> None:
    """Every formal propose_deal must include a private DM to the target leader."""
    legal_by_id = {item["command_id"]: item for item in snapshot["legal_commands"]}
    chats = normalized.get("chat_messages")
    if not isinstance(chats, list):
        chats = []
    covered_targets: set[str] = set()
    for message in chats:
        if not isinstance(message, dict):
            continue
        if message.get("target") == "player" and isinstance(message.get("target_player_id"), str):
            covered_targets.add(message["target_player_id"])
    summary = normalized.get("decision_summary", "")
    for item in normalized.get("commands", []):
        if not isinstance(item, dict):
            continue
        command_id = item.get("command_id")
        if not isinstance(command_id, str):
            continue
        catalog_entry = legal_by_id.get(command_id)
        if catalog_entry is None or catalog_entry.get("kind") != "propose_deal":
            continue
        target_player_id = _proposal_target_player_id(command_id, catalog_entry)
        if not target_player_id or target_player_id in covered_targets:
            continue
        chats.append({
            "target": "player",
            "target_player_id": target_player_id,
            "text": _proposal_chat_text(snapshot, target_player_id, catalog_entry, str(summary)),
            "grounding_ids": [target_player_id],
        })
        covered_targets.add(target_player_id)
    normalized["chat_messages"] = chats[:chat_max_messages()]


def normalize_model_response(snapshot: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Shape live model JSON into the closed local contract without inventing gameplay choices."""
    if not isinstance(response, dict):
        raise BoundaryError("response_schema", "Model response must be an object")
    response = resolve_property_wire(snapshot, response)
    response = expand_flat_response(response, snapshot)
    normalized = copy.deepcopy(response)
    known_ids = collect_known_ids(snapshot)
    known_players = {item["player_id"] for item in snapshot["known_players"]}
    opinion_rivals = _opinion_rival_player_ids(snapshot)
    recommendation_ids = {item["recommendation_id"] for item in snapshot["advciv"]["recommendations"]}
    legal_ids = {item["command_id"] for item in snapshot["legal_commands"]}
    legal_by_id = {item["command_id"]: item for item in snapshot["legal_commands"]}

    summary = normalized.get("decision_summary")
    if isinstance(summary, (dict, list)):
        normalized["decision_summary"] = canonical_json(summary)[:1200]
    elif not isinstance(summary, str) or not summary.strip():
        normalized["decision_summary"] = ""
    else:
        normalized["decision_summary"] = summary.strip()[:1200]

    thought = normalized.get("thought")
    if not isinstance(thought, dict):
        thought = _thought_from_flat(normalized)
    situation = thought.get("situation") if isinstance(thought, dict) else None
    strategy = thought.get("strategy") if isinstance(thought, dict) else None
    if not isinstance(situation, str) or not situation.strip():
        situation = ""
    if not isinstance(strategy, str) or not strategy.strip():
        strategy = ""
    if not situation.strip() and not strategy.strip():
        summary_for_thought = normalized.get("decision_summary")
        if isinstance(summary_for_thought, str) and summary_for_thought.strip():
            derived = _split_api_thought(summary_for_thought.strip())
            situation = derived.get("situation", "")
            strategy = derived.get("strategy", "")
    normalized["thought"] = {"situation": _clip_thought(situation), "strategy": _clip_thought(strategy)}
    if not normalized["decision_summary"].strip():
        normalized["decision_summary"] = synthesize_decision_summary(normalized["thought"])

    cleaned_opinions: dict[str, dict[str, Any]] = {}
    raw_opinions = normalized.get("player_opinions", {})
    if isinstance(raw_opinions, dict):
        current_turn = int(snapshot["decision"]["turn"])
        for player_id, entry in raw_opinions.items():
            if not isinstance(player_id, str) or player_id not in opinion_rivals:
                continue
            if isinstance(entry, str):
                text = _clip_player_opinion(entry)
            elif isinstance(entry, dict):
                text = _clip_player_opinion(str(entry.get("text", "")))
            else:
                continue
            if text:
                cleaned_opinions[player_id] = {"text": text, "updated_turn": current_turn}
    normalized["player_opinions"] = cleaned_opinions

    cleaned_histories: dict[str, dict[str, Any]] = {}
    raw_histories = normalized.get("player_histories", {})
    if isinstance(raw_histories, dict):
        current_turn = int(snapshot["decision"]["turn"])
        for player_id, entry in raw_histories.items():
            if not isinstance(player_id, str) or player_id not in opinion_rivals:
                continue
            if isinstance(entry, str):
                text = _clip_player_history(entry)
            elif isinstance(entry, dict):
                text = _clip_player_history(str(entry.get("text", "")))
            else:
                continue
            if text:
                cleaned_histories[player_id] = {"text": text, "updated_turn": current_turn}
    normalized["player_histories"] = cleaned_histories

    cleaned_decisions: list[dict[str, Any]] = []
    raw_decisions = normalized.get("recommendation_decisions")
    if isinstance(raw_decisions, list):
        for item in raw_decisions:
            if not isinstance(item, dict):
                continue
            rid = item.get("recommendation_id")
            if not isinstance(rid, str) or rid not in recommendation_ids:
                continue
            choice = item.get("decision")
            if choice in {"retain", "keep", "hold", "maintain"}:
                choice = "accept"
            if choice not in {"accept", "reject", "replace"}:
                continue
            replacements = item.get("replacement_command_ids")
            if not isinstance(replacements, list):
                replacements = []
            replacements = [entry for entry in replacements if isinstance(entry, str) and entry in legal_ids]
            if choice in {"accept", "reject"}:
                replacements = []
            if choice == "replace" and not replacements:
                choice = "accept"
            cleaned_decisions.append({
                "recommendation_id": rid,
                "decision": choice,
                "replacement_command_ids": replacements,
            })
    normalized["recommendation_decisions"] = cleaned_decisions[:64]

    cleaned_commands: list[dict[str, Any]] = []
    raw_commands = normalized.get("commands")
    if isinstance(raw_commands, list):
        for item in raw_commands:
            if not isinstance(item, dict):
                continue
            command_id = item.get("command_id")
            if not isinstance(command_id, str) or command_id not in legal_ids:
                continue
            catalog_entry = legal_by_id.get(command_id)
            if catalog_entry is None:
                continue
            arguments = item.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            domains = catalog_entry.get("parameter_domains", {})
            if not isinstance(domains, dict):
                domains = {}
            arguments = {key: arguments[key] for key in domains if key in arguments}
            cleaned_commands.append({"command_id": command_id, "arguments": arguments})
    normalized["commands"] = cleaned_commands[:64]

    cleaned_chats: list[dict[str, Any]] = []
    raw_chats = normalized.get("chat_messages")
    if isinstance(raw_chats, list):
        for message in raw_chats:
            if not isinstance(message, dict):
                continue
            target = message.get("target")
            if target not in {"all", "team", "player"}:
                continue
            text = message.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            text = "".join(character for character in text if ord(character) >= 32).strip()[:240]
            if not text:
                continue
            grounding = message.get("grounding_ids")
            if not isinstance(grounding, list):
                grounding = []
            grounding = [entry for entry in grounding if isinstance(entry, str) and entry in known_ids]
            grounding = list(dict.fromkeys(grounding))[:12]
            chat: dict[str, Any] = {"target": target, "text": text, "grounding_ids": grounding}
            if target == "player":
                target_player_id = message.get("target_player_id")
                resolved = _resolve_chat_recipient(target_player_id, snapshot)
                if resolved is None:
                    continue
                chat["target_player_id"] = resolved
            cleaned_chats.append(chat)
    normalized["chat_messages"] = cleaned_chats[:chat_max_messages()]
    _ensure_proposal_chat_messages(snapshot, normalized)

    return normalized


HOST_AUTOMATIC_KINDS = frozenset({"end_turn", "auto_moves"})


def _embedded_cmd_ids(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return re.findall(r"CMD_[A-Za-z0-9_]+", text)


def _text_claims_unselected_cmds(text: str, accepted_ids: set[str]) -> bool:
    for cmd_id in _embedded_cmd_ids(text):
        if cmd_id not in accepted_ids:
            return True
    return False


def _actionable_legal_commands(legal: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in legal.values()
            if item.get("runtime_status") != "unsupported"
            and item.get("kind") not in HOST_AUTOMATIC_KINDS]


def _sanitize_cmd_references(text: str, accepted_ids: set[str]) -> str:
    """Drop CMD_* tokens from prose that were not accepted; avoids whole-turn rejection."""
    if not isinstance(text, str) or not text.strip():
        return ""
    if not _text_claims_unselected_cmds(text, accepted_ids):
        return text.strip()
    cleaned = re.sub(r"CMD_[A-Za-z0-9_]+", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;.")
    return cleaned


def _finalize_accepted_commands(accepted_commands: list[dict[str, Any]], legal: dict[str, Any]) -> list[dict[str, Any]]:
    """Drop host-automatic kinds and duplicate command_ids after per-item validation."""
    filtered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in accepted_commands:
        command = legal.get(item["command_id"])
        if command is None or command.get("kind") in HOST_AUTOMATIC_KINDS:
            continue
        command_id = item["command_id"]
        if command_id in seen_ids:
            continue
        seen_ids.add(command_id)
        filtered.append(item)
    return filtered


def validate_model_response(snapshot: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Reject illegal items independently; wire responses need not pass JSON Schema up front."""
    legal = {item["command_id"]: item for item in snapshot["legal_commands"]}
    recommendations = {item["recommendation_id"]: item for item in snapshot["advciv"]["recommendations"]}
    accepted_decisions: list[dict[str, Any]] = []
    accepted_commands: list[dict[str, Any]] = []
    accepted_chat: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    decided: set[str] = set()
    replacement_claims: set[str] = set()

    for index, decision in enumerate(response["recommendation_decisions"]):
        try:
            rid = decision["recommendation_id"]
            rec = recommendations.get(rid)
            if rec is None or rid in decided:
                raise BoundaryError("illegal_recommendation_decision", rid)
            choice = decision["decision"]
            replacements = decision["replacement_command_ids"]
            if choice in {"accept", "reject"} and replacements:
                raise BoundaryError("illegal_recommendation_decision", "Non-replace decision has replacements")
            if choice == "replace" and not replacements:
                raise BoundaryError("illegal_recommendation_decision", "Replace requires commands")
            if choice == "reject" and rec["execution_state"] == "applied_reversible":
                raise BoundaryError("illegal_recommendation_decision", "Applied reversible advice cannot be rejected")
            for command_id in replacements:
                command = legal.get(command_id)
                if command is None or command_id in replacement_claims or not _domain_compatible(rec, command):
                    raise BoundaryError("illegal_replacement", command_id)
            decided.add(rid)
            replacement_claims.update(replacements)
            accepted_decisions.append(copy.deepcopy(decision))
        except BoundaryError as error:
            rejected.append({"section": "recommendation_decisions", "index": index, "category": error.category, "message": str(error)})

    raw_commands = response.get("commands")
    if not isinstance(raw_commands, list):
        raw_commands = []
    for index, item in enumerate(raw_commands):
        try:
            if not isinstance(item, dict):
                raise BoundaryError("illegal_command", "not_object")
            command_id = item.get("command_id")
            command = legal.get(command_id) if isinstance(command_id, str) else None
            if command is None:
                raise BoundaryError("illegal_command", command_id)
            domains = command.get("parameter_domains") or {}
            arguments = item.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
                item = {**item, "arguments": arguments}
            if set(arguments) != set(domains):
                raise BoundaryError("illegal_arguments", command_id)
            for key, domain in domains.items():
                value = arguments[key]
                if domain["type"] == "id" and value not in domain["allowed_ids"]:
                    raise BoundaryError("illegal_arguments", key)
                if domain["type"] == "integer":
                    if isinstance(value, bool) or not isinstance(value, int) or not domain["minimum"] <= value <= domain["maximum"] or (value-domain["minimum"]) % domain.get("step", 1):
                        raise BoundaryError("illegal_arguments", key)
                if domain["type"] == "boolean" and not isinstance(value, bool):
                    raise BoundaryError("illegal_arguments", key)
            accepted_commands.append(copy.deepcopy(item))
        except BoundaryError as error:
            rejected.append({"section": "commands", "index": index, "category": error.category, "message": str(error)})
        except (TypeError, KeyError, AttributeError, ValueError) as error:
            rejected.append({"section": "commands", "index": index, "category": "illegal_command", "message": str(error)})

    known_ids = collect_known_ids(snapshot)
    known_players = {item["player_id"] for item in snapshot["known_players"]}
    raw_chats = response.get("chat_messages")
    if not isinstance(raw_chats, list):
        raw_chats = []
    for index, message in enumerate(raw_chats):
        try:
            if not isinstance(message, dict):
                raise BoundaryError("illegal_chat", "not_object")
            target = message.get("target")
            target_player_id = message.get("target_player_id")
            if target == "player":
                resolved = _resolve_chat_recipient(target_player_id, snapshot)
                if resolved is None:
                    raise BoundaryError("illegal_chat", "Unknown private recipient")
                message = copy.deepcopy(message)
                message["target_player_id"] = resolved
            elif target_player_id is not None:
                message = copy.deepcopy(message)
                del message["target_player_id"]
            if not set(message.get("grounding_ids", [])).issubset(known_ids):
                raise BoundaryError("illegal_chat", "Unknown grounding ID")
            accepted_chat.append(copy.deepcopy(message))
        except BoundaryError as error:
            rejected.append({"section": "chat_messages", "index": index, "category": error.category, "message": str(error)})
        except (TypeError, KeyError, AttributeError, ValueError) as error:
            rejected.append({"section": "chat_messages", "index": index, "category": "illegal_chat", "message": str(error)})

    omitted = [item for rid, item in recommendations.items() if rid not in decided]
    accepted_commands = _finalize_accepted_commands(accepted_commands, legal)
    actionable = _actionable_legal_commands(legal)
    claimed_command_ids = {item["command_id"] for item in accepted_commands}
    for decision in accepted_decisions:
        rec = recommendations.get(decision["recommendation_id"])
        if rec is None:
            continue
        if decision["decision"] == "accept":
            claimed_command_ids.update(rec.get("proposed_command_ids", []))
        elif decision["decision"] == "replace":
            claimed_command_ids.update(decision.get("replacement_command_ids", []))
    warnings: list[dict[str, Any]] = []
    if actionable and not claimed_command_ids:
        native_claimed: set[str] = set()
        for rec in omitted:
            native_claimed.update(rec.get("proposed_command_ids", []))
        if not native_claimed:
            warnings.append({
                "section": "commands",
                "category": "no_model_commands",
                "message": "No LLM overrides parsed; AdvCiv runs native defaults after this turn",
            })
    summary = _sanitize_cmd_references(response.get("decision_summary", ""), claimed_command_ids)
    if not summary and isinstance(response.get("decision_summary"), str):
        warnings.append({
            "section": "decision_summary",
            "category": "summary_cmd_stripped",
            "message": "Removed unselected CMD_* references from decision_summary",
        })
    sanitized_chat: list[dict[str, Any]] = []
    for message in accepted_chat:
        text = _sanitize_cmd_references(message.get("text", ""), claimed_command_ids)
        if not text:
            warnings.append({
                "section": "chat_messages",
                "category": "chat_cmd_stripped",
                "message": "Dropped chat line with unselected CMD_* references",
            })
            continue
        cleaned = copy.deepcopy(message)
        cleaned["text"] = text[:240]
        sanitized_chat.append(cleaned)
    thought = response.get("thought", {})
    if not isinstance(thought, dict):
        thought = {}
    situation = str(thought.get("situation", "")).strip()
    strategy = str(thought.get("strategy", "")).strip()
    if not situation and not strategy:
        raw_summary = response.get("decision_summary", "")
        if isinstance(raw_summary, str) and raw_summary.strip():
            derived = _split_api_thought(raw_summary.strip())
            situation = derived.get("situation", "").strip()
            strategy = derived.get("strategy", "").strip()
    thought_out = {
        "situation": _clip_thought(situation),
        "strategy": _clip_thought(strategy),
    }
    if not summary.strip():
        summary = synthesize_decision_summary(thought_out)
    if not summary.strip():
        raise BoundaryError("response_schema", "decision_summary must be non-empty")
    rejected.extend(warnings)
    return {
        "thought": thought_out,
        "decision_summary": summary.strip()[:1200],
        "recommendation_decisions": accepted_decisions,
        "commands": accepted_commands,
        "chat_messages": sanitized_chat,
        "omitted_recommendations": omitted,
        "rejections": rejected,
    }


def collect_known_ids(snapshot: dict[str, Any]) -> set[str]:
    ids = {snapshot["decision"]["player_id"], snapshot["your_empire"]["team_id"]}
    for key, field in (("your_cities", "city_id"), ("your_units", "unit_id"),
                       ("known_players", "player_id"), ("known_other_cities", "city_id"),
                       ("visible_other_units", "unit_id")):
        ids.update(item[field] for item in snapshot[key])
    ids.update(item["plot_id"] for item in snapshot["known_map"]["plots"])
    ids.update(command["command_id"] for command in snapshot["legal_commands"])
    return ids


def bind_approved_commands(private: dict[str, Any], validated: dict[str, Any]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    sequence = int(private["sequence_cursor"])
    for item in validated["commands"]:
        # Fixed arguments are host-issued, never model-issued. They are
        # materialized into the synchronized command only after validation.
        catalog = private.get("legal_commands", {})
        fixed = catalog.get(item["command_id"], {}).get("fixed_arguments", {}) if isinstance(catalog, dict) else {}
        commands.append({"game_uuid": private["game_uuid"], "turn": private["turn"], "phase": private["phase"],
                         "player_id": private["player_id"], "state_hash": private["state_hash"],
                         "catalog_hash": private["catalog_hash"], "dll_fingerprint": private["dll_fingerprint"],
                         "sequence": sequence, "command_id": item["command_id"], "kind": catalog.get(item["command_id"], {}).get("kind", "unknown") if isinstance(catalog, dict) else "unknown",
                         "arguments": {**copy.deepcopy(fixed), **copy.deepcopy(item["arguments"])}})
        sequence += 1
    return commands


def execute_commands(commands: list[dict[str, Any]], adapters: dict[str, Callable[[dict[str, Any]], Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in commands:
        result = {"sequence": command.get("sequence"), "command_id": command.get("command_id")}
        try:
            adapter = adapters.get(command["command_id"])
            if adapter is None:
                raise BoundaryError("unsupported_adapter", command["command_id"])
            effect = adapter(copy.deepcopy(command["arguments"]))
            result.update(status="applied", effect=effect)
        except BoundaryError as error:
            result.update(status="noop", category=error.category, message=str(error))
        except Exception as error:
            result.update(status="noop", category="adapter_failure", message=str(error))
        results.append(result)
    return results


def resolve_recommendations(snapshot: dict[str, Any], validated: dict[str, Any], native_fallback: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    """Resolve advice and return both lifecycle records and commands to bind.

    Native reversible choices already applied by AdvCiv are not resent. A
    deferred recommendation is explicitly accepted by selecting its proposed
    IDs, or falls back to those same IDs after native revalidation.
    """
    decisions = {item["recommendation_id"]: item for item in validated["recommendation_decisions"]}
    results: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    claimed: set[str] = set()
    catalog_ids = {item["command_id"]: item for item in snapshot["legal_commands"]}
    for rec in snapshot["advciv"]["recommendations"]:
        choice = decisions.get(rec["recommendation_id"])
        if choice:
            status = choice["decision"]
            candidates = choice["replacement_command_ids"] if status == "replace" else rec["proposed_command_ids"] if status == "accept" else []
            if rec["execution_state"] == "applied_reversible" and status == "accept":
                candidates = []
            for command_id in candidates:
                if command_id in catalog_ids and command_id not in claimed:
                    claimed.add(command_id)
                    selected_ids.append(command_id)
        elif rec["execution_state"] == "deferred_irreversible":
            try:
                native_fallback(copy.deepcopy(rec))
                status = "native_fallback_applied"
                for command_id in rec["proposed_command_ids"]:
                    if command_id in catalog_ids and command_id not in claimed:
                        claimed.add(command_id)
                        selected_ids.append(command_id)
            except Exception:
                status = "native_fallback_noop"
        elif rec["execution_state"] == "applied_reversible":
            status = "native_choice_retained"
        else:
            status = "informational_noop"
        results.append({"recommendation_id": rec["recommendation_id"], "status": status})
    ordinary = [item for item in validated["commands"] if item["command_id"] not in claimed]
    return {"results": results, "selected_command_ids": selected_ids,
            "commands": [{"command_id": command_id,
                          "arguments": _command_arguments_from_catalog(catalog_ids, command_id)}
                         for command_id in selected_ids],
            "ordinary_commands": ordinary}


def append_audit(path: Path, event: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json({"recorded_unix_ms": int(time.time() * 1000), **event}) + "\n")
        return True
    except OSError:
        return False


def render_known_map_png(snapshot: dict[str, Any], path: Path, scale: int = 4) -> dict[str, Any]:
    """Dependency-free deterministic RGB PNG; unknown plots are never sampled."""
    ensure_known_map_plots(snapshot)
    width, height = snapshot["game"]["map_width"], snapshot["game"]["map_height"]
    colors = {"TERRAIN_OCEAN": (42, 80, 125), "TERRAIN_COAST": (70, 120, 160),
              "TERRAIN_GRASS": (92, 138, 74), "TERRAIN_PLAINS": (158, 145, 91),
              "TERRAIN_DESERT": (194, 171, 104), "TERRAIN_TUNDRA": (150, 160, 145),
              "TERRAIN_SNOW": (220, 225, 225)}
    unrevealed = (18, 18, 22)
    pixels = [[unrevealed for _ in range(width * scale)] for _ in range(height * scale)]
    drawn: set[tuple[int, int]] = set()
    for plot in snapshot["known_map"]["plots"]:
        color = colors.get(plot["terrain_id"], (100, 100, 100))
        if plot["knowledge"] == "remembered":
            color = tuple(component // 2 for component in color)
        for py in range(plot["y"] * scale, (plot["y"] + 1) * scale):
            for px in range(plot["x"] * scale, (plot["x"] + 1) * scale):
                pixels[py][px] = color
        drawn.add((plot["x"], plot["y"]))
    stack_markers: list[tuple[int, int, tuple[int, int, int]]] = []
    unit_markers: list[tuple[int, int, tuple[int, int, int]]] = []
    city_markers: list[tuple[int, int, tuple[int, int, int]]] = []
    stack_by_plot: dict[tuple[int, int], dict[str, Any]] = {}
    for stack in snapshot.get("known_map", {}).get("visible_stacks", []):
        if not isinstance(stack, dict):
            continue
        coords = _parse_plot_coords(stack.get("plot_id"))
        if coords is not None:
            stack_by_plot[coords] = stack
    unit_plots: set[tuple[int, int]] = set()
    for unit in snapshot.get("your_units", []) + snapshot.get("visible_other_units", []):
        if isinstance(unit, dict):
            coords = _parse_plot_coords(unit.get("plot_id"))
            if coords is not None:
                unit_plots.add(coords)
    for coords, stack in stack_by_plot.items():
        if max(1, int(stack.get("unit_count", stack.get("count", 1)))) > 1:
            stack_markers.append((coords[0], coords[1], (180, 255, 180)))
    for unit in snapshot.get("visible_other_units", []):
        if not isinstance(unit, dict):
            continue
        coords = _parse_plot_coords(unit.get("plot_id"))
        if coords is None:
            continue
        stack = stack_by_plot.get(coords)
        if stack is not None and max(1, int(stack.get("unit_count", stack.get("count", 1)))) > 1:
            continue
        unit_markers.append((coords[0], coords[1], (255, 80, 80)))
    for unit in snapshot.get("your_units", []):
        if not isinstance(unit, dict):
            continue
        coords = _parse_plot_coords(unit.get("plot_id"))
        if coords is None:
            continue
        stack = stack_by_plot.get(coords)
        if stack is not None and max(1, int(stack.get("unit_count", stack.get("count", 1)))) > 1:
            continue
        unit_markers.append((coords[0], coords[1], (80, 220, 255)))
    player_id = str(snapshot.get("decision", {}).get("player_id", ""))
    for coords, stack in stack_by_plot.items():
        if max(1, int(stack.get("unit_count", stack.get("count", 1)))) > 1 or coords in unit_plots:
            continue
        owner = str(stack.get("owner_player_id", ""))
        color = (255, 80, 80) if player_id and owner and owner != player_id else (80, 220, 255)
        unit_markers.append((coords[0], coords[1], color))
    for city in snapshot.get("your_cities", []):
        if not isinstance(city, dict):
            continue
        coords = _parse_plot_coords(city.get("plot_id"))
        if coords is None:
            continue
        city_markers.append((coords[0], coords[1], (255, 220, 60) if city.get("is_capital") else (255, 180, 40)))

    def _paint_marker(x: int, y: int, color: tuple[int, int, int], radius_scale: float = 1.0) -> None:
        cx = x * scale + scale // 2
        cy = y * scale + scale // 2
        radius = max(1, int(scale * radius_scale // 2))
        for py in range(max(0, cy - radius), min(height * scale, cy + radius + 1)):
            for px in range(max(0, cx - radius), min(width * scale, cx + radius + 1)):
                pixels[py][px] = color

    for x, y, color in stack_markers:
        _paint_marker(x, y, color, 0.9)
    for x, y, color in unit_markers:
        _paint_marker(x, y, color, 1.0)
    for x, y, color in city_markers:
        _paint_marker(x, y, color, 1.2)
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in pixels)
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width*scale, height*scale, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return {
        "path": str(path), "sha256": hashlib.sha256(png).hexdigest(),
        "width": width * scale, "height": height * scale,
        "known_plot_tiles": len(drawn), "png_bytes": len(png),
    }


@dataclass
class CircuitBreaker:
    failures: dict[str, int]
    threshold: int = 3

    def record(self, player_id: str, success: bool) -> None:
        self.failures[player_id] = 0 if success else self.failures.get(player_id, 0) + 1

    def record_failure(self, player_id: str, category: str, message: str) -> None:
        """Count hard failures only; recoverable schema gaps should not trip the breaker."""
        if category == "response_schema" and "decision_summary" in message:
            return
        if category == "response_schema" and "thought/" in message:
            return
        self.record(player_id, False)

    def open(self, player_id: str) -> bool:
        return self.failures.get(player_id, 0) >= self.threshold
