"""Publish LLM apply payloads for Civ6Ai via the hidden InGame inbox."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_PENDING_APPLY: dict[tuple[str, int, int], str] = {}


def _pending_apply_key(session_id: str, player: int, turn: int) -> tuple[str, int, int]:
    return session_id, player, turn


def remember_pending_apply(session_id: str, player: int, turn: int, payload: str) -> None:
    _PENDING_APPLY[_pending_apply_key(session_id, player, turn)] = payload


def peek_pending_apply(session_id: str, player: int, turn: int) -> str | None:
    return _PENDING_APPLY.get(_pending_apply_key(session_id, player, turn))


def publish_pending_apply(payload: str, session_id: str, player: int, turn: int) -> bool:
    """Store apply JSON, write mod pending-apply Lua, and try hidden inbox inject."""
    if not payload:
        return False
    remember_pending_apply(session_id, player, turn, payload)
    from civ6_host_channel import inject_apply_payload, write_pending_apply_lua

    write_pending_apply_lua(payload, session_id, turn)
    return inject_apply_payload(payload, session_id, player, turn)


def _apply_ready_marker(player: int, turn: int) -> str:
    return f"inbox|apply_ready|player={player}|turn={turn}|"


def _apply_payload_marker(player: int, turn: int) -> str:
    return f"bridge|apply_payload|player={player}|turn={turn}|"


def _pending_apply_ok_marker(player: int) -> str:
    return f"bridge|pending_apply_ok|player={player}"


def apply_confirmed(lua_log: Path | None, player: int, turn: int) -> bool:
    if lua_log is None or not lua_log.is_file():
        return False
    from civ6_startup_log import lua_log_tail_has_exact_marker, lua_log_tail_has_pattern

    if lua_log_tail_has_exact_marker(lua_log, _apply_ready_marker(player, turn)):
        return True
    if lua_log_tail_has_pattern(lua_log, _pending_apply_ok_marker(player)):
        return True
    return lua_log_tail_has_pattern(lua_log, _apply_payload_marker(player, turn))


def wait_for_apply_confirmation(
    lua_log: Path,
    player: int,
    turn: int,
    *,
    timeout_seconds: float = 30.0,
    start_offset: int | None = None,
) -> bool:
    from civ6_startup_log import wait_for_lua_log_exact_marker, wait_for_lua_log_pattern

    if wait_for_lua_log_exact_marker(
        lua_log,
        _apply_ready_marker(player, turn),
        timeout_seconds=timeout_seconds,
        check_tail_first=False,
        start_offset=start_offset,
    ):
        return True
    if wait_for_lua_log_pattern(
        lua_log,
        _pending_apply_ok_marker(player),
        timeout_seconds=timeout_seconds,
        check_tail_first=False,
        start_offset=start_offset,
    ):
        return True
    return wait_for_lua_log_pattern(
        lua_log,
        _apply_payload_marker(player, turn),
        timeout_seconds=timeout_seconds,
        check_tail_first=False,
        start_offset=start_offset,
    )


def load_chat_apply_payload(player_dir: Path) -> str | None:
    decision_path = player_dir / "decision_chat.json"
    if not decision_path.is_file():
        return None
    try:
        decision = json.loads(decision_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        log.warning("decision_chat unreadable %s: %s", decision_path, error)
        return None
    validated = decision.get("validated") if isinstance(decision, dict) else None
    chat_messages: list[Any] = []
    if isinstance(validated, dict) and isinstance(validated.get("chat_messages"), list):
        chat_messages = validated["chat_messages"]
    if not chat_messages:
        return None
    return json.dumps({"commands": [], "chat_messages": chat_messages}, separators=(",", ":"), ensure_ascii=False)


def load_apply_payload(player_dir: Path) -> str | None:
    apply_path = player_dir / "apply_commands.json"
    if not apply_path.is_file():
        return None
    try:
        apply_data = json.loads(apply_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        log.warning("apply_commands unreadable %s: %s", apply_path, error)
        return None
    commands = apply_data.get("commands") if isinstance(apply_data, dict) else None
    if not isinstance(commands, list):
        commands = []
    chat_messages: list[Any] = []
    decision_path = player_dir / "decision.json"
    if decision_path.is_file():
        try:
            decision = json.loads(decision_path.read_text(encoding="utf-8-sig"))
            validated = decision.get("validated") if isinstance(decision, dict) else None
            if isinstance(validated, dict) and isinstance(validated.get("chat_messages"), list):
                chat_messages = validated["chat_messages"]
        except (OSError, json.JSONDecodeError):
            pass
    if not commands and not chat_messages:
        return None
    payload = {"commands": commands, "chat_messages": chat_messages}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _player_context(player_dir: Path) -> tuple[str, int, int] | None:
    session_id = player_dir.parent.name
    if not player_dir.name.startswith("PLAYER_"):
        return None
    try:
        player = int(player_dir.name.split("_", 1)[1])
    except (IndexError, ValueError):
        return None
    turn = 0
    snapshot_path = player_dir / "snapshot.json"
    if snapshot_path.is_file():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
            decision = snapshot.get("decision") if isinstance(snapshot, dict) else None
            if isinstance(decision, dict) and decision.get("turn") is not None:
                turn = int(decision["turn"])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return session_id, player, turn


def publish_apply_payload(
    player_dir: Path,
    session_id: str,
    player: int,
    turn: int,
    payload: str,
) -> bool:
    lua_log: Path | None = None
    try:
        from civ6_lua_log_bridge import default_lua_log

        lua_log = default_lua_log()
    except Exception:
        pass
    marker = player_dir / f"apply_turn_{turn}.done"
    if marker.is_file():
        if apply_confirmed(lua_log, player, turn):
            log.info("Apply already confirmed for player=%s turn=%s", player, turn)
            return True
        try:
            marker.unlink()
        except OSError as error:
            log.warning("Apply marker unlink failed: %s", error)
    try:
        from civ6_startup_log import log_event

        civ6ai_root = player_dir.parent.parent.parent
        log_event(civ6ai_root, "inbox_apply_begin", player=player, turn=turn)
    except Exception:
        pass
    confirm_offset = lua_log.stat().st_size if lua_log is not None and lua_log.is_file() else None
    if not publish_pending_apply(payload, session_id, player, turn):
        return False
    wait_seconds = 60.0 if session_id.startswith("autotest-") else 20.0
    log.info("Inbox apply publish player=%s turn=%s wait=%.0fs", player, turn, wait_seconds)
    if lua_log is None or not lua_log.is_file():
        log.warning("Lua.log unavailable for apply confirmation player=%s turn=%s", player, turn)
        return False
    confirmed = wait_for_apply_confirmation(
        lua_log,
        player,
        turn,
        timeout_seconds=wait_seconds,
        start_offset=confirm_offset,
    )
    if not confirmed:
        log.warning("Inbox apply not confirmed in Lua.log player=%s turn=%s", player, turn)
        if session_id.startswith("autotest-"):
            try:
                from civ6_startup_log import log_event

                civ6ai_root = player_dir.parent.parent.parent
                log_event(civ6ai_root, "inbox_apply_timeout", player=player, turn=turn)
            except Exception:
                pass
        return False
    marker.write_text(f"applied_at={time.strftime('%Y-%m-%dT%H:%M:%S')}\n", encoding="utf-8")
    log.info("Inbox apply confirmed player=%s turn=%s", player, turn)
    try:
        from civ6_startup_log import log_event

        civ6ai_root = player_dir.parent.parent.parent
        log_event(civ6ai_root, "inbox_apply_sent", player=player, turn=turn)
    except Exception:
        pass
    return True


def publish_from_player_dir(player_dir: Path, *, chat: bool = False) -> bool:
    context = _player_context(player_dir)
    if context is None:
        return False
    session_id, player, turn = context
    if chat:
        for snapshot_name in ("snapshot_chat.json", "snapshot.json"):
            snapshot_path = player_dir / snapshot_name
            if not snapshot_path.is_file():
                continue
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
                decision = snapshot.get("decision") if isinstance(snapshot, dict) else None
                if isinstance(decision, dict) and decision.get("turn") is not None:
                    turn = int(decision["turn"])
                    break
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        payload = load_chat_apply_payload(player_dir)
    else:
        payload = load_apply_payload(player_dir)
    if payload is None:
        return False
    return publish_apply_payload(player_dir, session_id, player, turn, payload)
