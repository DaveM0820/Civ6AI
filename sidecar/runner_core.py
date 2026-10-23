"""Shared turn core for run_civ6, run_v2 (Civ IV) and run_civ5.

build_approved_record validates and binds a normalized response; each game adds
its own step through ``post_bind``. run_model_turn is the one model call,
approve, salvage and fallback loop every runner used to copy.
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sidecar import pipeline_v2 as pipeline
from sidecar.pipeline_v2 import CircuitBreaker

# (snapshot, validated, commands) -> (validated, commands, dropped or None)
PostBind = Callable[[dict, dict, list], "tuple[dict, list, list[str] | None]"]


def session_key(game_uuid: str, player_id: str) -> str:
    active = int(player_id.split("_", 1)[1]) if player_id.startswith("PLAYER_") else 0
    return f"{game_uuid}:player:{active}"


def load_circuit_breaker(path: Path) -> CircuitBreaker:
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            failures = {str(key): int(value) for key, value in payload.items()}
            return CircuitBreaker(failures=failures)
    return CircuitBreaker(failures={})


def save_circuit_breaker(path: Path, breaker: CircuitBreaker) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pipeline.canonical_json(breaker.failures) + "\n", encoding="utf-8")


def build_approved_record(
    snapshot: dict,
    private: dict,
    normalized_response: dict,
    model: dict | None,
    input_log: Path,
    *,
    resolve_recommendations: bool = False,
    post_bind: PostBind | None = None,
) -> dict:
    validated = pipeline.validate_model_response(snapshot, normalized_response)
    private_copy = copy.deepcopy(private)
    private_copy["legal_commands"] = {item["command_id"]: item for item in snapshot["legal_commands"]}
    if resolve_recommendations:
        resolution = pipeline.resolve_recommendations(snapshot, validated, lambda _rec: None)
        validated["recommendation_results"] = resolution["results"]
        validated["commands"] = resolution["commands"] + resolution["ordinary_commands"]
    commands = pipeline.bind_approved_commands(private_copy, validated)
    dropped = None
    if post_bind is not None:
        validated, commands, dropped = post_bind(snapshot, validated, commands)
    record = {
        "status": "approved",
        "private": private_copy,
        "snapshot_hash": pipeline.canonical_hash(snapshot),
        "response": normalized_response,
        "validated": validated,
        "commands": commands,
        "model": model,
        "io": {"input_path": str(input_log)},
    }
    if dropped is not None:
        record["dropped"] = dropped
    return record


def salvage_approved_record(
    snapshot: dict,
    raw_model_response: dict,
    normalize: Callable[[dict, dict], dict],
    build: Callable[[dict], dict],
) -> dict | None:
    """If the main path failed after a parseable model payload, approve parsed commands."""
    try:
        return build(normalize(snapshot, raw_model_response))
    except Exception:
        return None


@dataclass
class TurnResult:
    record: dict
    raw_model_response: dict | None = None
    normalized_response: dict | None = None
    model: dict | None = None
    timings: dict[str, int] = field(default_factory=dict)


def run_model_turn(
    snapshot: dict,
    private: dict,
    input_log: Path,
    journal: Path,
    breaker: CircuitBreaker,
    player_id: str,
    *,
    call: Callable[[], tuple[dict, dict]],
    build: Callable[[dict, dict | None], dict],
    persist: Callable[[dict, dict], None],
    write_io_log: Callable[[Path, str, dict], Path],
    normalize: Callable[[dict, dict], dict] = pipeline.normalize_model_response,
) -> TurnResult:
    """Call the model, approve its orders, salvage a parseable reply, or record a fallback.

    ``build(normalized, model)`` makes the approved record. ``persist(response, record)``
    runs after each approved record (thought memory and the like).
    """
    raw_model_response = None
    model = None
    normalized_response = None
    timings = {"llm_ms": 0, "parse_ms": 0}
    try:
        started = time.monotonic()
        response, model = call()
        timings["llm_ms"] = int((time.monotonic() - started) * 1000)
        raw_model_response = copy.deepcopy(response)
        started = time.monotonic()
        normalized_response = normalize(snapshot, response)
        timings["parse_ms"] = int((time.monotonic() - started) * 1000)
        record = build(normalized_response, model)
        persist(normalized_response, record)
        breaker.record(player_id, True)
    except Exception as error:
        category = getattr(error, "category", "pipeline_failure")
        breaker.record_failure(player_id, category, str(error))
        salvaged = salvage_approved_record(
            snapshot, raw_model_response, normalize, lambda norm: build(norm, model),
        ) if isinstance(raw_model_response, dict) else None
        if salvaged is not None:
            record = salvaged
            salvaged["salvaged_from"] = category
            persist(salvaged.get("response", {}), salvaged)
            breaker.record(player_id, True)
        else:
            record = {
                "status": "fallback",
                "private": copy.deepcopy(private),
                "snapshot_hash": pipeline.canonical_hash(snapshot),
                "category": category,
                "message": str(error),
                "commands": [],
                "model": model,
                "response": normalized_response,
                "io": {"input_path": str(input_log)},
            }
    if raw_model_response is not None:
        output_log = write_io_log(journal, "_raw_output.json", {
            "status": record.get("status"),
            "raw_model_response": raw_model_response,
            "normalized_response": record.get("response"),
            "model": record.get("model"),
        })
        record["io"]["raw_output_path"] = str(output_log)
    return TurnResult(record, raw_model_response, normalized_response, model, timings)
