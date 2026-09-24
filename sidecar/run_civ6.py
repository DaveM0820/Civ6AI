"""Offline / host entry point for Civ VI LLM AI decisions."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sidecar import civ6_adapter
from sidecar import civ6_wire
from sidecar.map_render_civ6 import render_civ6_map_for_model
from sidecar import pipeline_v2 as pipeline
from sidecar.pipeline_v2 import CircuitBreaker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "fixtures" / "civ6" / "snapshot-turn-classical-golden.json"
DEFAULT_JOURNAL = ROOT / "artifacts" / "civ6-ai-result-journal.jsonl"


def _read(path: Path | None) -> dict:
    encoding = "utf-8-sig" if path else "utf-8"
    stream = path.open(encoding=encoding) if path else sys.stdin
    try:
        value = json.load(stream)
    finally:
        if path:
            stream.close()
    if not isinstance(value, dict):
        raise pipeline.BoundaryError("input", "Expected one object")
    return value


def _read_last_record(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    last = None
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                value = pipeline.parse_exact_json(line)
                if isinstance(value, dict):
                    last = value
    return last


def _load_dotenv_files(civ6ai_root: Path | None) -> None:
    if civ6ai_root is None:
        return
    for name in ("host.env", "autotest.env"):
        path = civ6ai_root / name
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _civ6ai_root_from_session(session_dir: Path | None) -> Path | None:
    if session_dir is None:
        return None
    if session_dir.parent.name == "sessions":
        return session_dir.parent.parent
    if session_dir.parent.parent.name == "sessions":
        return session_dir.parent.parent.parent
    return None


def _session_key(game_uuid: str, player_id: str) -> str:
    active = int(player_id.split("_", 1)[1]) if player_id.startswith("PLAYER_") else 0
    return f"{game_uuid}:player:{active}"


def _thought_memory_path(civ6ai_root: Path | None, game_uuid: str, player_id: str) -> Path:
    if civ6ai_root is not None:
        return civ6ai_root / "memory" / f"{game_uuid}_{player_id}.json"
    return Path("memory") / f"{game_uuid}_{player_id}.json"


def _apply_personality(snapshot: dict, path: Path | None) -> None:
    if path is None or not path.is_file():
        return
    profile = _read(path)
    snapshot_personality = snapshot.get("personality", {})
    if not isinstance(snapshot_personality, dict):
        snapshot_personality = {}
    merged = dict(snapshot_personality)
    for key, value in profile.items():
        if key in pipeline.PERSONALITY_IDENTITY_KEYS:
            continue
        merged[key] = value
    snapshot["personality"] = merged
    pipeline.normalize_personality(snapshot)


def _apply_previous_turn(snapshot: dict, record: dict | None) -> str | None:
    if not record:
        return None
    response = record.get("response", {})
    model = record.get("model", {})
    validated = record.get("validated", {})
    history = snapshot.setdefault("history", {})
    if isinstance(response, dict) and isinstance(response.get("decision_summary"), str):
        summary = pipeline.scrub_wire_from_summary(response["decision_summary"])[:300]
        command_ids = []
        for item in validated.get("commands", []):
            command_id = item.get("command_id") if isinstance(item, dict) else None
            if isinstance(command_id, str) and command_id not in command_ids:
                command_ids.append(command_id)
        accepted = history.setdefault("accepted_decisions", [])
        if isinstance(accepted, list):
            accepted.append({
                "turn": int(record.get("private", {}).get("turn", snapshot["decision"]["turn"])),
                "kind": "AI_DECISION",
                "summary": summary,
                "affected_ids": command_ids,
            })
        prior = history.get("memory_summary", "")
        if summary and summary not in str(prior).splitlines():
            history["memory_summary"] = (str(prior) + ("\n" if prior else "") + summary)[-4000:]
    return model.get("response_id") if isinstance(model, dict) and isinstance(model.get("response_id"), str) else None


def _write_io_log(journal: Path, suffix: str, payload: dict) -> Path:
    io_dir = journal.parent / "io_logs"
    io_dir.mkdir(parents=True, exist_ok=True)
    path = io_dir / (journal.stem + suffix)
    path.write_text(pipeline.canonical_json(payload) + "\n", encoding="utf-8")
    return path


def _load_circuit_breaker(path: Path) -> CircuitBreaker:
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            failures = {str(key): int(value) for key, value in payload.items()}
            return CircuitBreaker(failures=failures)
    return CircuitBreaker(failures={})


def _save_circuit_breaker(path: Path, breaker: CircuitBreaker) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pipeline.canonical_json(breaker.failures) + "\n", encoding="utf-8")


def _build_approved_record(
    snapshot: dict,
    private: dict,
    normalized_response: dict,
    model: dict | None,
    input_log: Path,
) -> dict:
    validated = pipeline.validate_model_response(snapshot, normalized_response)
    private_copy = copy.deepcopy(private)
    private_copy["legal_commands"] = {item["command_id"]: item for item in snapshot["legal_commands"]}
    commands = pipeline.bind_approved_commands(private_copy, validated)
    return {
        "status": "approved",
        "private": private_copy,
        "snapshot_hash": pipeline.canonical_hash(snapshot),
        "response": normalized_response,
        "validated": validated,
        "commands": commands,
        "model": model,
        "io": {"input_path": str(input_log)},
    }


def _salvage_approved_record(
    snapshot: dict,
    private: dict,
    raw_model_response: dict,
    model: dict | None,
    input_log: Path,
) -> dict | None:
    try:
        normalized = pipeline.normalize_model_response(snapshot, raw_model_response)
        return _build_approved_record(snapshot, private, normalized, model, input_log)
    except Exception:
        return None


def _persist_thought_memory(
    snapshot: dict,
    normalized_response: dict,
    model: dict | None,
    thought_memory: dict,
    thought_path: Path,
) -> dict:
    thought = normalized_response.get("thought", {})
    if not isinstance(thought, dict):
        return thought_memory
    situation = thought.get("situation", "")
    strategy = thought.get("strategy", "")
    private_thought = model.get("private_thought") if isinstance(model, dict) else None
    if isinstance(private_thought, str) and private_thought.strip():
        api_thought = pipeline._split_api_thought(private_thought)
        if api_thought.get("situation"):
            situation = api_thought["situation"]
        if api_thought.get("strategy"):
            strategy = api_thought["strategy"]
    if isinstance(situation, str) and situation.strip() and isinstance(strategy, str) and strategy.strip():
        thought_memory = pipeline.append_thought(
            thought_memory,
            int(snapshot["decision"]["turn"]),
            situation,
            strategy,
        )
    opinions = normalized_response.get("player_opinions", {})
    if isinstance(opinions, dict) and opinions:
        thought_memory = pipeline.update_player_opinions(
            thought_memory,
            int(snapshot["decision"]["turn"]),
            opinions,
        )
    histories = normalized_response.get("player_histories", {})
    if isinstance(histories, dict) and histories:
        thought_memory = pipeline.update_player_histories(
            thought_memory,
            int(snapshot["decision"]["turn"]),
            histories,
        )
    try:
        pipeline.save_thought_memory(thought_path, thought_memory)
    except OSError:
        pass
    return thought_memory


def _prepare_map_image(
    snapshot: dict,
    journal: Path,
    civ6ai_root: Path | None,
    session_id: str,
) -> tuple[str | None, Path, Path | None, dict]:
    turn = int(snapshot["decision"]["turn"])
    player_id = str(snapshot["decision"]["player_id"])
    map_path = journal.with_name("map.png")
    archive_dir = None
    archive_path = None
    if civ6ai_root is not None:
        archive_dir = civ6ai_root / "map_images" / session_id
        archive_path = archive_dir / f"{player_id}_turn_{turn:06d}.png"
    attach = pipeline.map_image_attach_turn(snapshot)
    if not attach:
        return None, map_path, archive_path, {"attached": False}
    meta = render_civ6_map_for_model(snapshot, map_path)
    if archive_path is not None:
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(map_path.read_bytes())
    known_map = snapshot.setdefault("known_map", {})
    if isinstance(known_map, dict):
        image = known_map.setdefault("image", {})
        if isinstance(image, dict):
            image["attached"] = True
            image["path"] = str(map_path)
            if archive_path is not None:
                image["archive_path"] = str(archive_path)
    return meta.get("data_url"), map_path, archive_path, meta


def _seat_experiment_response(snapshot: dict) -> dict:
    civ6 = snapshot.get("civ6") if isinstance(snapshot.get("civ6"), dict) else {}
    city_id = civ6.get("experiment_city_id")
    build_id = civ6.get("experiment_build_id")
    command_id = None
    for item in snapshot.get("legal_commands", []):
        if not isinstance(item, dict) or item.get("kind") != "queue_production":
            continue
        fixed = item.get("fixed_arguments")
        if not isinstance(fixed, dict):
            fixed = {}
        if city_id and build_id:
            if fixed.get("city_id") == city_id and fixed.get("build_id") == build_id:
                command_id = item.get("command_id")
                break
        if command_id is None and isinstance(item.get("command_id"), str):
            command_id = item["command_id"]
    commands = []
    if isinstance(command_id, str) and command_id:
        commands.append({"command_id": command_id, "arguments": {}})
    return {
        "thought": {
            "situation": "Seat-type experiment turn.",
            "strategy": "Queue distinctive capital production before native AI runs.",
        },
        "decision_summary": "Gate 2 seat experiment production inject.",
        "commands": commands,
        "chat_messages": [],
    }


def _command_entry(item: dict) -> dict | None:
    command_id = item.get("command_id")
    if not isinstance(command_id, str) or not command_id:
        return None
    return {"command_id": command_id, "arguments": {}}


def _unit_id_from_command(item: dict) -> str | None:
    fixed = item.get("fixed_arguments")
    if not isinstance(fixed, dict):
        return None
    unit_id = fixed.get("unit_id")
    return unit_id if isinstance(unit_id, str) and unit_id else None


def _runtime_autotest_response(snapshot: dict) -> dict:
    legal = [item for item in snapshot.get("legal_commands", []) if isinstance(item, dict)]
    commands: list[dict[str, Any]] = []
    handled_units: set[str] = set()

    for kind in ("set_research_tech", "queue_production"):
        for item in legal:
            if item.get("kind") != kind:
                continue
            entry = _command_entry(item)
            if entry is not None:
                commands.append(entry)
                break

    for item in legal:
        if item.get("kind") != "found_city":
            continue
        unit_id = _unit_id_from_command(item)
        if unit_id is None or unit_id in handled_units:
            continue
        entry = _command_entry(item)
        if entry is not None:
            commands.append(entry)
            handled_units.add(unit_id)

    for item in legal:
        if item.get("kind") != "move_unit":
            continue
        unit_id = _unit_id_from_command(item)
        if unit_id is None or unit_id in handled_units:
            continue
        entry = _command_entry(item)
        if entry is not None:
            commands.append(entry)
            handled_units.add(unit_id)

    for item in legal:
        if item.get("kind") != "unit_skip":
            continue
        unit_id = _unit_id_from_command(item)
        if unit_id is None or unit_id in handled_units:
            continue
        entry = _command_entry(item)
        if entry is not None:
            commands.append(entry)
            handled_units.add(unit_id)

    if not commands:
        for item in legal:
            entry = _command_entry(item)
            if entry is not None:
                commands.append(entry)
                break

    return {
        "thought": {"situation": "Runtime Civ VI turn.", "strategy": "Found, move, research, then clear leftovers."},
        "decision_summary": "Runtime autotest play.",
        "commands": commands,
        "chat_messages": [],
    }


def _fake_response(snapshot: dict, from_game: bool = False) -> dict:
    if not from_game:
        response_path = ROOT / "fixtures" / "civ6" / "response-turn-classical-golden.txt"
        if response_path.is_file():
            flat = pipeline.parse_flat_wire_lines(response_path.read_text(encoding="utf-8-sig"))
            return pipeline.expand_flat_response(flat)
    if from_game:
        return _runtime_autotest_response(snapshot)
    commands = []
    for item in snapshot.get("legal_commands", []):
        if not isinstance(item, dict):
            continue
        command_id = item.get("command_id")
        if isinstance(command_id, str) and command_id:
            commands.append({"command_id": command_id, "arguments": {}})
            break
    return {
        "thought": {"situation": "Runtime Civ VI turn.", "strategy": "Apply first legal command."},
        "decision_summary": "Gate 0 runtime apply.",
        "commands": commands,
        "chat_messages": [],
    }


def _write_decision_outputs(session_dir: Path | None, record: dict, output_path: Path | None) -> None:
    if session_dir is None and output_path is None:
        return
    target_dir = session_dir or output_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    decision_path = output_path or (target_dir / "decision.json")
    payload = {
        "status": record.get("status"),
        "validated": record.get("validated", {}),
        "commands": record.get("commands", []),
        "metrics": record.get("metrics", {}),
    }
    decision_path.write_text(pipeline.canonical_json(payload) + "\n", encoding="utf-8")
    apply_commands = []
    for command in record.get("commands", []):
        if not isinstance(command, dict):
            continue
        apply_commands.append({
            "kind": command.get("kind"),
            "command_id": command.get("command_id"),
            "arguments": command.get("arguments", {}),
        })
    apply_path = target_dir / "apply_commands.json"
    apply_path.write_text(pipeline.canonical_json({"commands": apply_commands}) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Civ VI LLM AI sidecar")
    parser.add_argument("--state", type=Path, default=None, help="Civ VI snapshot JSON")
    parser.add_argument("--snapshot", type=Path, help="Alias for --state")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--session-dir", type=Path, help="PLAYER session directory for file bridge")
    parser.add_argument("--output", type=Path, help="Decision JSON output path")
    parser.add_argument("--session-id", help="Session id for archives")
    parser.add_argument("--from-game", action="store_true", help="Snapshot came from Civ6Ai mod")
    parser.add_argument("--seat-experiment", action="store_true")
    parser.add_argument("--wire-only", action="store_true")
    parser.add_argument("--live", action="store_true", help="Call live model APIs")
    parser.add_argument("--personality", type=Path)
    parser.add_argument("--previous-response-id")
    args = parser.parse_args()

    state_path = args.snapshot or args.state or (args.session_dir / "snapshot.json" if args.session_dir else DEFAULT_SNAPSHOT)
    if args.session_dir is not None:
        args.journal = args.session_dir / "journal.jsonl"

    civ6ai_root = _civ6ai_root_from_session(args.session_dir)
    _load_dotenv_files(civ6ai_root)

    raw = _read(state_path)
    snapshot = civ6_adapter.upgrade_runtime_snapshot(raw) if args.from_game else raw
    civ6_adapter.normalize_civ6_snapshot(snapshot)
    _apply_personality(snapshot, args.personality)

    wire_text = civ6_wire.build_civ6_model_wire_text(snapshot)
    if args.wire_only:
        sys.stdout.write(wire_text)
        if not wire_text.endswith("\n"):
            sys.stdout.write("\n")
        return

    game_uuid = args.session_id or "civ6-runtime"
    if isinstance(snapshot.get("civ6"), dict) and snapshot["civ6"].get("session_id"):
        game_uuid = str(snapshot["civ6"]["session_id"])
    player_id = str(snapshot["decision"]["player_id"])
    session_key = _session_key(game_uuid, player_id)
    metrics_dir = args.session_dir.parent if args.session_dir is not None else args.journal.parent
    thought_path = _thought_memory_path(civ6ai_root, game_uuid, player_id)
    thought_memory = pipeline.load_thought_memory(thought_path, session_key, snapshot)
    pipeline.inject_thought_history(snapshot, thought_memory)

    breaker_path = metrics_dir / "circuit_breaker.json"
    breaker = _load_circuit_breaker(breaker_path)
    if breaker.open(player_id):
        raise pipeline.BoundaryError("circuit_breaker", "Helper circuit breaker is open for " + player_id)

    private = {
        "game_uuid": game_uuid,
        "turn": int(snapshot["decision"]["turn"]),
        "phase": "strategic_decision",
        "player_id": player_id,
        "state_hash": pipeline.canonical_hash(snapshot),
        "catalog_hash": "civ6-capabilities",
        "dll_fingerprint": "civ6-mod",
        "sequence_cursor": 0,
    }

    previous_response_id = args.previous_response_id or _apply_previous_turn(
        snapshot, _read_last_record(args.journal),
    )

    sidecar_started = time.monotonic()
    image_url, image_path, archive_path, render_meta = _prepare_map_image(
        snapshot, args.journal, civ6ai_root, game_uuid,
    )
    input_log = _write_io_log(args.journal, "_input.json", {
        "schema_version": snapshot.get("schema_version"),
        "decision": snapshot.get("decision"),
        "personality": snapshot.get("personality"),
        "your_empire": snapshot.get("your_empire"),
        "snapshot_hash": pipeline.canonical_hash(snapshot),
        "wire_chars": len(wire_text),
        "wire_path": str(args.journal.parent / "io_logs" / (args.journal.stem + "_wire.txt")),
        "map_image_path": str(image_path),
        "map_image_archive_path": str(archive_path) if archive_path else None,
        "map_image_attached": bool(image_url),
        "previous_response_id": previous_response_id,
        "snapshot": snapshot,
    })
    wire_path = Path(input_log.parent / (args.journal.stem + "_wire.txt"))
    wire_path.write_text(wire_text + "\n", encoding="utf-8")

    raw_model_response = None
    model = None
    normalized_response = None
    try:
        if args.live:
            response, model = pipeline.call_model(
                snapshot,
                os.environ.get("OPENAI_API_KEY", ""),
                image_url,
                previous_response_id,
            )
        elif args.seat_experiment:
            response, model = _seat_experiment_response(snapshot), {"model": "seat_experiment", "usage": {}}
        else:
            response, model = _fake_response(snapshot, from_game=args.from_game), {"model": "fixture", "usage": {}}
        raw_model_response = copy.deepcopy(response)
        normalized_response = pipeline.normalize_model_response(snapshot, response)
        record = _build_approved_record(snapshot, private, normalized_response, model, input_log)
        thought_memory = _persist_thought_memory(
            snapshot, normalized_response, model, thought_memory, thought_path,
        )
        breaker.record(player_id, True)
    except Exception as error:
        breaker.record_failure(player_id, getattr(error, "category", "pipeline_failure"), str(error))
        salvaged = _salvage_approved_record(
            snapshot, private, raw_model_response, model, input_log,
        ) if isinstance(raw_model_response, dict) else None
        if salvaged is not None:
            record = salvaged
            salvaged["salvaged_from"] = getattr(error, "category", "pipeline_failure")
            thought_memory = _persist_thought_memory(
                snapshot, salvaged.get("response", {}), model, thought_memory, thought_path,
            )
            breaker.record(player_id, True)
        else:
            record = {
                "status": "fallback",
                "private": copy.deepcopy(private),
                "snapshot_hash": pipeline.canonical_hash(snapshot),
                "category": getattr(error, "category", "pipeline_failure"),
                "message": str(error),
                "commands": [],
                "model": model,
                "response": normalized_response,
                "io": {"input_path": str(input_log)},
            }

    if raw_model_response is not None:
        output_log = _write_io_log(args.journal, "_raw_output.json", {
            "status": record.get("status"),
            "raw_model_response": raw_model_response,
            "normalized_response": record.get("response"),
            "model": record.get("model"),
        })
        record["io"]["raw_output_path"] = str(output_log)

    wall_ms = int((time.monotonic() - sidecar_started) * 1000)
    model_meta = record.get("model") if isinstance(record.get("model"), dict) else {}
    usage = model_meta.get("usage", {}) if isinstance(model_meta.get("usage"), dict) else {}
    metrics = {
        "game_uuid": game_uuid,
        "turn": int(snapshot["decision"]["turn"]),
        "player_id": player_id,
        "status": record.get("status"),
        "provider": model_meta.get("provider"),
        "model": model_meta.get("model"),
        "latency_ms": model_meta.get("latency_ms"),
        "usage": usage,
        "wall_ms": wall_ms,
        "context_chars": len(wire_text),
        "legal_commands": len(snapshot.get("legal_commands", [])),
        "known_plots": len(snapshot.get("known_map", {}).get("plots", [])),
        "image_attached": bool(image_url),
        "map_image_path": str(image_path),
        "map_image_archive_path": str(archive_path) if archive_path else None,
        "map_image_sha256": render_meta.get("sha256"),
        "map_image_bytes": render_meta.get("image_bytes"),
        "category": record.get("category"),
        "message": record.get("message"),
    }
    pipeline.append_turn_metrics(metrics_dir, metrics)
    record["metrics"] = metrics
    _save_circuit_breaker(breaker_path, breaker)
    pipeline.append_audit(args.journal, record)
    _write_decision_outputs(args.session_dir, record, args.output)
    print(pipeline.canonical_json(record))


if __name__ == "__main__":
    main()
