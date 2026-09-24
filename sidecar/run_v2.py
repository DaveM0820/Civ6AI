"""One-process entry point for the strict v2 Civ IV host decision boundary."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidecar import map_render
from sidecar import pipeline_v2 as pipeline
from sidecar.pipeline_v2 import CircuitBreaker


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
                if not isinstance(value, dict):
                    raise pipeline.BoundaryError("previous_journal", "Journal record is not an object")
                last = value
    return last


def _apply_personality(snapshot: dict, path: Path | None) -> None:
    if path is None:
        return
    snapshot_personality = snapshot["personality"]
    if path.is_file():
        profile = _read(path)
        for legacy_key in (
            "communication_tone",
            "profile_version",
            "player_id",
            "stable_seed",
            "traits",
            "strategic_priorities",
            "risk_tolerance",
            "diplomacy_style",
            "aggression",
            "economic_bias",
        ):
            profile.pop(legacy_key, None)
        merged = dict(snapshot_personality)
        for key, value in profile.items():
            if key in pipeline.PERSONALITY_IDENTITY_KEYS:
                continue
            merged[key] = value
        snapshot["personality"] = merged
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    pipeline.normalize_personality(snapshot)
    pipeline.validate_snapshot(snapshot)
    path.write_text(pipeline.canonical_json(snapshot["personality"]) + "\n", encoding="utf-8")


def _session_key(game_uuid: str, player_id: str) -> str:
    active = int(player_id.split("_", 1)[1]) if player_id.startswith("PLAYER_") else 0
    return f"{game_uuid}:player:{active}"


def _apply_previous_turn(snapshot: dict, record: dict | None) -> str | None:
    if not record:
        return None
    response = record.get("response", {})
    model = record.get("model", {})
    validated = record.get("validated", {})
    if isinstance(response, dict) and isinstance(response.get("decision_summary"), str):
        summary = pipeline.scrub_wire_from_summary(response["decision_summary"])[:300]
        command_ids = []
        for item in validated.get("commands", []):
            command_id = item.get("command_id") if isinstance(item, dict) else None
            if isinstance(command_id, str) and command_id not in command_ids:
                command_ids.append(command_id)
        snapshot["history"]["accepted_decisions"].append({"turn": int(record.get("private", {}).get("turn", 0)),
            "kind": "AI_DECISION", "summary": summary, "affected_ids": command_ids})
        prior = snapshot["history"].get("memory_summary", "")
        if summary not in prior.splitlines():
            snapshot["history"]["memory_summary"] = (prior + ("\n" if prior else "") + summary)[-4000:]
    pipeline.normalize_personality(snapshot)
    pipeline.validate_snapshot(snapshot)
    return model.get("response_id") if isinstance(model, dict) and isinstance(model.get("response_id"), str) else None


def _map_image_paths(journal: Path, game_uuid: str, player_id: str, turn: int) -> tuple[Path, Path, Path, Path]:
    journal_svg = journal.with_suffix(".map.svg")
    journal_model = journal.with_suffix(map_render.model_image_suffix())
    archive_dir = journal.parent / "map_images" / game_uuid
    archive_svg = archive_dir / f"{player_id}_turn_{turn:06d}.map.svg"
    archive_model = archive_dir / f"{player_id}_turn_{turn:06d}{map_render.model_image_suffix()}"
    return journal_svg, journal_model, archive_svg, archive_model


def _prepare_map_image(
    snapshot: dict,
    explicit: Path | None,
    journal: Path,
    game_uuid: str,
) -> tuple[str | None, Path, Path, dict]:
    """Render SVG archive + raster model image; only the raster is sent to vision APIs."""
    turn = int(snapshot["decision"]["turn"])
    player_id = str(snapshot["decision"]["player_id"])
    journal_svg, journal_model, archive_svg, archive_model = _map_image_paths(
        journal, game_uuid, player_id, turn,
    )
    attach = pipeline.map_image_attach_turn(snapshot)
    image = snapshot.setdefault("known_map", {}).setdefault("image", {})
    if isinstance(image, dict):
        image["attached"] = attach
    svg_meta = map_render.render_known_map_svg(snapshot, journal_svg if attach else None)
    if not attach:
        return None, journal_model, archive_svg, {**svg_meta, "model": {}}
    model_meta = map_render.render_known_map_model_image(snapshot, journal_model)
    archive_svg.parent.mkdir(parents=True, exist_ok=True)
    archive_svg.write_text(journal_svg.read_text(encoding="utf-8"), encoding="utf-8")
    archive_model.write_bytes(journal_model.read_bytes())
    if isinstance(image, dict):
        image["archive_path"] = str(archive_svg)
        image["model_archive_path"] = str(archive_model)
        for key in ("sha256", "known_plot_tiles", "svg_bytes", "format", "viewport", "tile_px", "rendered_tiles"):
            if key in svg_meta:
                image[key] = svg_meta[key]
        image["model_format"] = model_meta["format"]
        image["model_mime_type"] = model_meta["mime_type"]
        image["model_bytes"] = model_meta["image_bytes"]
        image["model_sha256"] = model_meta["sha256"]
        image["model_width"] = model_meta["width"]
        image["model_height"] = model_meta["height"]
    render_meta = {**svg_meta, "model": model_meta}
    return model_meta["data_url"], journal_model, archive_svg, render_meta


def _map_image_url(snapshot: dict, explicit: Path | None, journal: Path) -> tuple[str | None, Path]:
    slug = journal.stem.split("_player_")[0] if "_player_" in journal.stem else journal.stem
    url, path, _, _ = _prepare_map_image(snapshot, explicit, journal, slug)
    return url, path


def _fake_public_chat(snapshot: dict, command: dict | None) -> dict:
	"""Concise public broadcast for fake/offline testing."""
	player_id = snapshot["decision"]["player_id"]
	empire = snapshot["your_empire"]
	research = empire["research"]
	leader = snapshot["personality"]["leader_name"]
	status = "Gold %d, %s %d/%d." % (
		int(empire["gold"]), research["tech_id"], int(research["progress"]), int(research["cost"]))
	if command is not None:
		action = "Action: %s." % command["command_id"]
	else:
		action = "Action: retain AdvCiv defaults."
	text = "%s Status: %s %s" % (leader, status, action)
	return {"target": "all", "text": text[:240], "grounding_ids": [player_id] +
		([command["command_id"]] if command is not None else [])}


def _proof_command(snapshot: dict) -> dict | None:
	proof_id = os.environ.get("CIV4AI_PROOF_COMMAND_ID", "").strip()
	proof_kind = os.environ.get("CIV4AI_PROOF_COMMAND_KIND", "").strip()
	if not proof_id and not proof_kind:
		return None
	commands = snapshot["legal_commands"]
	if proof_id:
		return next((item for item in commands if item.get("command_id") == proof_id), None)
	return next((item for item in commands if item.get("kind") == proof_kind), None)


def _command_payload_item(selected: dict) -> dict:
	return {"command_id": selected["command_id"],
		"arguments": {name: (domain["allowed_ids"][0] if domain["type"] == "id" else domain["minimum"] if domain["type"] == "integer" else False)
			for name, domain in selected["parameter_domains"].items()}}


def fake_response(snapshot: dict) -> dict:
	commands = snapshot["legal_commands"]
	proof = _proof_command(snapshot)
	proof_target = os.environ.get("CIV4AI_PROOF_COMMAND_ID", "").strip() or os.environ.get("CIV4AI_PROOF_COMMAND_KIND", "").strip()
	in_proof = bool(proof_target)
	if in_proof and proof is None:
		raise pipeline.BoundaryError("proof_command", "Proof command is not legal in this snapshot: " + proof_target)
	selected = proof
	if selected is None:
		selected = next((item for item in commands if item["runtime_status"] == "tested"), None)
		if selected is None:
			selected = commands[0] if commands else None
	command_payload = []
	if selected is not None:
		command_payload.append(_command_payload_item(selected))
	if in_proof and selected is not None and selected.get("kind") != "end_turn":
		end_turn = next((item for item in commands if item.get("kind") == "end_turn"), None)
		if end_turn is not None:
			command_payload.append(_command_payload_item(end_turn))
	summary = "Proof command %s." % selected["command_id"] if in_proof and selected is not None else (
		"Use the first currently tested legal choice." if selected else "Keep AdvCiv defaults.")
	return {"thought": {"situation": "Offline proof turn.", "strategy": "Exercise legal commands."},
		"decision_summary": summary, "recommendation_decisions": [], "commands": command_payload,
		"chat_messages": [_fake_public_chat(snapshot, selected)] if selected is not None else []}


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


def _write_io_log(journal: Path, suffix: str, payload: dict) -> Path:
    """Persist model input/output beside journals for post-run inspection."""
    io_dir = journal.parent / "io_logs"
    io_dir.mkdir(parents=True, exist_ok=True)
    path = io_dir / (journal.stem + suffix)
    path.write_text(pipeline.canonical_json(payload) + "\n", encoding="utf-8")
    return path


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
    resolution = pipeline.resolve_recommendations(snapshot, validated, lambda _rec: None)
    validated["recommendation_results"] = resolution["results"]
    validated["commands"] = resolution["commands"] + resolution["ordinary_commands"]
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
    """If the main path failed after a parseable model payload, approve parsed commands."""
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
    if isinstance(situation, str) and situation.strip() and isinstance(strategy, str) and strategy.strip() or (
        isinstance(opinions, dict) and opinions
    ) or (
        isinstance(histories, dict) and histories
    ):
        try:
            pipeline.save_thought_memory(thought_path, thought_memory)
        except OSError:
            pass
    return thought_memory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, help="Model-facing v2 snapshot; stdin when omitted")
    parser.add_argument("--stdio", action="store_true", help="Read one extracted snapshot object from stdin")
    parser.add_argument("--host-record", type=Path, help="Private authoritative metadata, never sent to the model")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--previous-journal", type=Path)
    parser.add_argument("--personality", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--previous-response-id")
    args = parser.parse_args()
    extracted = _read(args.state)
    host_metadata = extracted.pop("host_metadata", None) if isinstance(extracted, dict) else None
    snapshot = pipeline.build_model_input(extracted)
    _apply_personality(snapshot, args.personality)
    previous_response_id = _apply_previous_turn(snapshot, _read_last_record(args.previous_journal))
    private = _read(args.host_record) if args.host_record else (host_metadata if isinstance(host_metadata, dict) else {
        "game_uuid": str(extracted.get("game_uuid", "unknown")),
        "turn": int(extracted.get("turn", 0)),
        "phase": "strategic_decision", "player_id": "PLAYER_%d" % int(extracted.get("active_player_id", 0)), "state_hash": "host-bound",
        "catalog_hash": "host-catalog", "dll_fingerprint": "host-dll", "sequence_cursor": 0})
    pipeline.inject_lobby_roster(snapshot, args.journal.parent, private["game_uuid"])
    player_id = snapshot["decision"]["player_id"]
    session_key = _session_key(private["game_uuid"], player_id)
    thought_path = pipeline.thought_memory_path(args.journal.parent, private["game_uuid"], player_id)
    thought_memory = pipeline.load_thought_memory(thought_path, session_key, extracted)
    pipeline.inject_thought_history(snapshot, thought_memory)
    breaker_path = args.journal.parent / "circuit_breaker.json"
    breaker = _load_circuit_breaker(breaker_path)
    if breaker.open(player_id):
        raise pipeline.BoundaryError("circuit_breaker", "Helper circuit breaker is open for " + player_id)
    sidecar_started = time.monotonic()
    image_url, image_path, archive_path, render_meta = _prepare_map_image(
        snapshot, args.image, args.journal, private["game_uuid"])
    input_log = _write_io_log(args.journal, "_input.json", {
        "schema_version": snapshot.get("schema_version"),
        "decision": snapshot.get("decision"),
        "personality": snapshot.get("personality"),
        "snapshot_hash": pipeline.canonical_hash(snapshot),
        "map_image_path": str(image_path),
        "map_image_archive_path": str(archive_path),
        "map_svg_archive_path": str(archive_path),
        "map_image_attached": bool(image_url),
        "previous_response_id": args.previous_response_id or previous_response_id,
        "snapshot": snapshot,
    })
    raw_model_response = None
    model = None
    normalized_response = None
    try:
        if args.live:
            response, model = pipeline.call_model(snapshot, os.environ.get("OPENAI_API_KEY", ""), image_url,
                args.previous_response_id or previous_response_id)
        else:
            response, model = fake_response(snapshot), {"model": "fake", "response_id": None, "usage": {}}
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
    wire_text = pipeline.build_model_wire_text(snapshot)
    metrics = {
        "game_uuid": private["game_uuid"],
        "turn": int(snapshot["decision"]["turn"]),
        "player_id": player_id,
        "status": record.get("status"),
        "provider": model_meta.get("provider"),
        "model": model_meta.get("model"),
        "latency_ms": model_meta.get("latency_ms"),
        "usage": model_meta.get("usage"),
        "wall_ms": wall_ms,
        "context_chars": len(wire_text),
        "legal_commands": len(snapshot.get("legal_commands", [])),
        "known_plots": len(snapshot.get("known_map", {}).get("plots", [])),
        "image_attached": bool(image_url),
        "map_image_path": str(image_path),
        "map_image_archive_path": str(archive_path),
        "map_image_sha256": render_meta.get("model", {}).get("sha256"),
        "map_image_bytes": render_meta.get("model", {}).get("image_bytes"),
        "map_image_mime": render_meta.get("model", {}).get("mime_type"),
        "map_svg_bytes": render_meta.get("svg_bytes"),
        "map_known_plot_tiles": render_meta.get("known_plot_tiles"),
    }
    pipeline.append_turn_metrics(args.journal.parent, metrics)
    record["metrics"] = metrics
    _save_circuit_breaker(breaker_path, breaker)
    pipeline.append_audit(args.journal, record)
    stdout_record = copy.deepcopy(record)
    private = stdout_record.get("private")
    if isinstance(private, dict) and "legal_commands" in private:
        slim_private = {}
        for key, value in private.items():
            if key != "legal_commands":
                slim_private[key] = value
        stdout_record["private"] = slim_private
    print(pipeline.canonical_json(stdout_record))


if __name__ == "__main__":
    main()
