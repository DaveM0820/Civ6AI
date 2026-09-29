"""Publish LLM apply payloads for Civ6Ai via the hidden InGame inbox."""
from __future__ import annotations

import hashlib
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


_EMPTY_PAYLOAD = '{"commands":[],"chat_messages":[]}'


def publish_pending_apply(payload: str, session_id: str, player: int, turn: int, *, kind: str = "turn") -> bool:
    """Store apply JSON and write it into the mod PendingApply module (per player).

    Success means the module was written; that is the channel Lua reads. The
    keystroke inbox inject is optional (CIV6AI_INBOX_INJECT=1) and never decides
    the result, so a missing UI-automation dependency cannot cause republish loops.
    """
    if not payload:
        return False
    remember_pending_apply(session_id, player, turn, payload)
    from civ6_host_channel import inbox_inject_enabled, inject_apply_payload, write_pending_apply_lua

    written = write_pending_apply_lua(payload, session_id, player, turn, kind=kind)
    if inbox_inject_enabled() and kind == "turn":
        inject_apply_payload(payload, session_id, player, turn)
    return bool(written)


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


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        log.warning("unreadable %s: %s", path, error)
        return None


def decision_turn(player_dir: Path) -> int | None:
    """Turn of the snapshot the turn decision (decision.json) answered, if recorded."""
    path = player_dir / "decision.json"
    if not path.is_file():
        return None
    decision = _read_json(path)
    metrics = decision.get("metrics") if isinstance(decision, dict) else None
    try:
        return int(metrics["turn"]) if isinstance(metrics, dict) and metrics.get("turn") is not None else None
    except (TypeError, ValueError):
        return None


def load_apply_payload(player_dir: Path, *, expected_turn: int | None = None, allow_empty: bool = False) -> str | None:
    """Turn apply payload for player_dir.

    Commands come from decision.json (the turn decision) when it lists them, else
    from apply_commands.json. When expected_turn is given and decision.json records
    a different turn, the files belong to an earlier snapshot and None is returned,
    so an old answer is never re-tagged with the current turn.
    """
    decision_path = player_dir / "decision.json"
    decision = _read_json(decision_path) if decision_path.is_file() else None
    if expected_turn is not None and isinstance(decision, dict):
        answered = decision_turn(player_dir)
        if answered is not None and answered != int(expected_turn):
            return None
    commands: Any = None
    if isinstance(decision, dict) and isinstance(decision.get("commands"), list):
        commands = [
            {"kind": c.get("kind"), "command_id": c.get("command_id"), "arguments": c.get("arguments", {})}
            for c in decision["commands"]
            if isinstance(c, dict)
        ]
    if commands is None:
        apply_path = player_dir / "apply_commands.json"
        if apply_path.is_file():
            apply_data = _read_json(apply_path)
            commands = apply_data.get("commands") if isinstance(apply_data, dict) else None
    if not isinstance(commands, list):
        commands = []
        if decision is None and not allow_empty:
            return None
    chat_messages: list[Any] = []
    validated = decision.get("validated") if isinstance(decision, dict) else None
    if isinstance(validated, dict) and isinstance(validated.get("chat_messages"), list):
        chat_messages = validated["chat_messages"]
    if not commands and not chat_messages and not allow_empty:
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


def _marker_path(player_dir: Path, turn: int, kind: str, payload: str) -> Path:
    if kind == "chat":
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
        return player_dir / f"apply_chat_{turn}_{digest}.done"
    return player_dir / f"apply_turn_{turn}.done"


def publish_apply_payload(
    player_dir: Path,
    session_id: str,
    player: int,
    turn: int,
    payload: str,
    *,
    kind: str = "turn",
    confirm_seconds: float = 0.0,
) -> bool:
    """Publish one answer once. The marker records the published apply id.

    The same answer (same apply id) is never republished, so host loops that call
    this every cycle do not rewrite the module or block. Lua applies it when the
    seat-timing rule allows (local seat: its current turn; AI seats: their next
    activation), which can be a whole turn later, so by default this does not wait.
    With confirm_seconds > 0 it waits for the Lua confirmation line and returns
    False when none appears (the marker still prevents a republish loop).
    """
    from civ6_host_channel import pending_apply_id

    apply_id = pending_apply_id(payload, session_id, player, turn, kind)
    marker = _marker_path(player_dir, turn, kind, payload)
    if marker.is_file():
        try:
            recorded = marker.read_text(encoding="utf-8")
        except OSError:
            recorded = ""
        if f"id={apply_id}" in recorded or "id=" not in recorded:
            return True
    lua_log: Path | None = None
    try:
        from civ6_lua_log_bridge import default_lua_log

        lua_log = default_lua_log()
    except Exception:
        pass
    try:
        from civ6_startup_log import log_event

        civ6ai_root = player_dir.parent.parent.parent
        log_event(civ6ai_root, "inbox_apply_begin", player=player, turn=turn)
    except Exception:
        pass
    confirm_offset = lua_log.stat().st_size if lua_log is not None and lua_log.is_file() else None
    if not publish_pending_apply(payload, session_id, player, turn, kind=kind):
        return False
    marker.write_text(
        f"published_at={time.strftime('%Y-%m-%dT%H:%M:%S')} id={apply_id} kind={kind}\n", encoding="utf-8"
    )
    log.info("Pending apply published player=%s turn=%s kind=%s id=%s", player, turn, kind, apply_id)
    if confirm_seconds <= 0:
        return True
    if lua_log is None or not lua_log.is_file():
        log.warning("Lua.log unavailable for apply confirmation player=%s turn=%s", player, turn)
        return False
    confirmed = wait_for_apply_confirmation(
        lua_log,
        player,
        turn,
        timeout_seconds=confirm_seconds,
        start_offset=confirm_offset,
    )
    if not confirmed:
        log.warning("Pending apply not confirmed in Lua.log player=%s turn=%s", player, turn)
        return False
    log.info("Pending apply confirmed player=%s turn=%s", player, turn)
    try:
        from civ6_startup_log import log_event

        civ6ai_root = player_dir.parent.parent.parent
        log_event(civ6ai_root, "inbox_apply_sent", player=player, turn=turn)
    except Exception:
        pass
    return True


def publish_from_player_dir(player_dir: Path, *, chat: bool = False, confirm_seconds: float = 0.0) -> bool:
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
        if payload is None:
            return False
        return publish_apply_payload(player_dir, session_id, player, turn, payload, kind="chat",
                                     confirm_seconds=confirm_seconds)
    # Turn answer: only for the current snapshot's turn; an answered-but-empty turn
    # is still published (empty payload) so Lua knows the seat's answer arrived.
    answered = decision_turn(player_dir)
    payload = load_apply_payload(player_dir, expected_turn=turn, allow_empty=answered == turn)
    if payload is None:
        return False
    return publish_apply_payload(player_dir, session_id, player, turn, payload, confirm_seconds=confirm_seconds)


def publish_empty_for_turn(player_dir: Path) -> bool:
    """The sidecar failed for this snapshot: tell Lua the seat has no orders this turn."""
    context = _player_context(player_dir)
    if context is None:
        return False
    session_id, player, turn = context
    log.info("Publishing empty apply (no model answer) player=%s turn=%s", player, turn)
    return publish_apply_payload(player_dir, session_id, player, turn, _EMPTY_PAYLOAD)
