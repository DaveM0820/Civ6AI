"""Detect a new Civ6 game on the host side and reset the seat state in place.

The session id reaches Lua through Civ6Ai_Paths.lua, read once when a game
loads, so a game started without ``start_live --new-session`` keeps the old id.
Instead of skipping its snapshots (helpers waited forever) or answering them
with the previous game's memory and queued orders, the host bridge:

* keeps only the blobs of the game currently writing Lua.log
  (:func:`current_game_blobs`), dropping an older game's backlog;
* adopts the session id that game actually carries as the active session;
* when the game is new (different map/game seed, or the turn falls back to the
  start turn below the session's last seen turn), archives that session's
  per-seat transients and seat memory and clears PendingApply, then lets the
  triggering snapshot be processed normally.

State lives in ``<civ6ai_root>/autotest/game_tracker.json``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TRACKER_NAME = "game_tracker.json"
_SNAPSHOT_KINDS = ("snapshot", "snapshot_chat")


def _tracker_path(civ6ai_root: Path) -> Path:
    return civ6ai_root / "autotest" / TRACKER_NAME


def load_tracker(civ6ai_root: Path) -> dict[str, Any]:
    path = _tracker_path(civ6ai_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_tracker(civ6ai_root: Path, state: dict[str, Any]) -> None:
    path = _tracker_path(civ6ai_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def game_identity(payload: str | None) -> dict[str, Any]:
    """Seeds and start turn from a snapshot's game block (present once the Lua emits them)."""
    out: dict[str, Any] = {}
    if not payload:
        return out
    try:
        snap = json.loads(payload)
    except ValueError:
        return out
    game = snap.get("game") if isinstance(snap, dict) else None
    if not isinstance(game, dict):
        return out
    seed_parts = [str(game[k]) for k in ("map_seed", "game_seed") if game.get(k) not in (None, "", 0)]
    if seed_parts:
        out["seed"] = "/".join(seed_parts)
    try:
        if game.get("start_turn") is not None:
            out["start_turn"] = int(game["start_turn"])
    except (TypeError, ValueError):
        pass
    return out


def is_new_game(prev: dict[str, Any] | None, turn: int, ident: dict[str, Any]) -> bool:
    """True when a snapshot at ``turn`` belongs to a different game than ``prev`` recorded."""
    if not prev:
        return False
    old_seed, new_seed = prev.get("seed"), ident.get("seed")
    if old_seed and new_seed:
        return old_seed != new_seed
    last = int(prev.get("last_turn") or 0)
    start = int(ident.get("start_turn") or prev.get("start_turn") or 1)
    return turn <= max(1, start) and last > turn


def current_game_blobs(blobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blobs of the game now writing the log: everything after the last game boundary.

    A boundary is a change of session id between snapshot blobs, or a seat's turn
    falling back to 1 or below after a later turn in the same read.
    """
    start = 0
    prev_session: str | None = None
    seat_turn: dict[tuple[str, int], int] = {}
    for index, blob in enumerate(blobs):
        if blob.get("kind") not in _SNAPSHOT_KINDS:
            continue
        session = str(blob.get("session") or "")
        turn = int(blob.get("turn") or 0)
        key = (session, int(blob.get("player") or 0))
        if prev_session is not None and session != prev_session:
            start = index
            seat_turn.clear()
        elif turn <= 1 and seat_turn.get(key, turn) > turn:
            start = index
            seat_turn.clear()
        prev_session = session
        seat_turn[key] = max(turn, seat_turn.get(key, turn))
    return blobs[start:]


def archive_seat_memory(memory_dir: Path, session_id: str, stamp: str) -> int:
    """Move ``<session>_*`` memory files and the ``<session>`` folder into an archive dir."""
    if not session_id or not memory_dir.is_dir():
        return 0
    dest = memory_dir / f"_archive_{stamp}_{session_id}"
    moved = 0
    for path in sorted(memory_dir.iterdir()):
        if path.name == session_id or path.name.startswith(session_id + "_"):
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest / path.name))
            moved += 1
    return moved


def reset_session_in_place(civ6ai_root: Path, session_id: str, *, lua_log: Path | None = None,
                           memory_dir: Path | None = None, clear_pending: bool = True) -> dict[str, int]:
    """Same clean slate as ``start_live --new-session``, keeping the id the game runs under."""
    from install_mod import archive_session_transients

    stamp = time.strftime("%Y%m%d_%H%M%S")
    roots = [civ6ai_root]
    if lua_log is not None:
        mirror = lua_log.parent / "civ6ai"
        if mirror != civ6ai_root:
            roots.append(mirror)
    archived = sum(archive_session_transients(base / "sessions" / session_id, stamp) for base in roots)
    if memory_dir is None:
        override = os.environ.get("CIV6AI_MEMORY_DIR")
        memory_dir = Path(override) if override else civ6ai_root / "memory"
    memory = archive_seat_memory(memory_dir, session_id, stamp)
    if clear_pending:
        try:
            from civ6_host_channel import clear_pending_apply_lua

            clear_pending_apply_lua()
        except Exception as error:  # pragma: no cover - host dependent
            log.warning("new game: PendingApply clear failed: %s", error)
    return {"archived": archived, "memory": memory}


def _set_active_session(civ6ai_root: Path, session_id: str) -> None:
    path = civ6ai_root / "runtime.json"
    try:
        runtime = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        runtime = {}
    if not isinstance(runtime, dict):
        runtime = {}
    runtime["session_id"] = session_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")


def _bootstrap_last_turn(civ6ai_root: Path, session_id: str) -> int:
    """Highest snapshot turn already on disk for a session the tracker has not seen."""
    best = 0
    for snap in (civ6ai_root / "sessions" / session_id).glob("PLAYER_*/snapshot.json"):
        try:
            data = json.loads(snap.read_text(encoding="utf-8-sig"))
            best = max(best, int((data.get("decision") or {}).get("turn") or 0))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return best


def track_game(civ6ai_root: Path, blobs: list[dict[str, Any]], active_session: str, *,
               lua_log: Path | None = None, memory_dir: Path | None = None) -> tuple[list[dict[str, Any]], str]:
    """Run before the bridge answers a log read. Returns (blobs to process, active session).

    Adopts the running game's session id and resets it in place when a new game
    started under it; the triggering snapshot stays in the returned list.
    """
    blobs = current_game_blobs(blobs)
    snaps = [b for b in blobs if b.get("kind") in _SNAPSHOT_KINDS and b.get("session")]
    if not snaps:
        return blobs, active_session
    state = load_tracker(civ6ai_root)
    sessions = state.setdefault("sessions", {})
    changed = False
    for blob in snaps:
        session = str(blob["session"])
        turn = int(blob.get("turn") or 0)
        ident = game_identity(blob.get("payload"))
        prev = sessions.get(session)
        if prev is None:
            last = _bootstrap_last_turn(civ6ai_root, session)
            prev = {"last_turn": last} if last else None
        if session != active_session:
            log.warning("game_session_adopted|session=%s|previous_active=%s|turn=%s",
                        session, active_session or "-", turn)
            _set_active_session(civ6ai_root, session)
            active_session = session
            changed = True
        if is_new_game(prev, turn, ident):
            info = reset_session_in_place(civ6ai_root, session, lua_log=lua_log, memory_dir=memory_dir)
            log.warning("new_game_detected|session=%s|turn=%s|previous_last_turn=%s|archived=%s|memory=%s",
                        session, turn, (prev or {}).get("last_turn"), info["archived"], info["memory"])
            prev = None
        entry = dict(prev or {})
        entry["last_turn"] = max(turn, int(entry.get("last_turn") or 0)) if prev else turn
        for key in ("seed", "start_turn"):
            if ident.get(key) is not None:
                entry[key] = ident[key]
        if sessions.get(session) != entry:
            sessions[session] = entry
            changed = True
    if changed:
        state["active_session"] = active_session
        save_tracker(civ6ai_root, state)
    return blobs, active_session


def current_game_offset(data: bytes, *, max_turn: int | None = None) -> int | None:
    """Byte offset of the first blob begin of the game now writing ``data`` (a Lua.log read).

    With ``max_turn``, None unless that game is still that young: a rotation before a
    new game must not answer the previous game's backlog, only a game that just began.
    """
    from civ6_lua_log_bridge import _BEGIN

    begins: list[tuple[int, dict[str, Any]]] = []
    pos = 0
    for line in data.splitlines(keepends=True):
        text = line.decode("utf-8", errors="replace")
        match = _BEGIN.search(text)
        if match and match.group("kind") in _SNAPSHOT_KINDS:
            begins.append((pos, {"kind": match.group("kind"), "session": match.group("session").strip(),
                                 "player": int(match.group("player")), "turn": int(match.group("turn"))}))
        pos += len(line)
    if not begins:
        return None
    kept = current_game_blobs([b for _p, b in begins])
    if max_turn is not None and max(int(b["turn"]) for b in kept) > max_turn:
        return None
    return begins[len(begins) - len(kept)][0]
