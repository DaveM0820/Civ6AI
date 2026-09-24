"""Rebuild Civ6Ai snapshots from Lua.log print dumps and run the sidecar.

Used when retail Lua cannot write files (io sandbox). Every Civ6 install
writes Logs/Lua.log via print(); Python publishes apply payloads via the hidden InGame inbox.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from civ5_sidecar_jobs import _read_json, _run_job, decision_suppresses_sidecar

log = logging.getLogger(__name__)

_BEGIN = re.compile(
    r"CIV5AI\|blob\|begin\|(?P<kind>[^|]+)\|(?P<id>[^|]+)\|(?P<chunks>\d+)\|"
    r"(?P<live>\d+)\|(?P<player>\d+)\|(?P<turn>-?\d+)\|(?P<session>[^\r\n]*)"
)
_CHUNK = re.compile(r"CIV5AI\|blob\|c\|(?P<id>[^|]+)\|(?P<index>\d+)\|(?P<data>[^\r\n]*)")
_END = re.compile(r"CIV5AI\|blob\|end\|(?P<id>[^|]+)")


def default_lua_log() -> Path:
    home = Path.home()
    candidates = [
        home / "OneDrive/Documents/My Games/Sid Meier's Civilization 5/Logs/Lua.log",
        home / "Documents/My Games/Sid Meier's Civilization 5/Logs/Lua.log",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]


def log_civ5ai_root(lua_log: Path) -> Path:
    return lua_log.parent / "civ5ai"


def _offset_path(civ5ai_root: Path) -> Path:
    return civ5ai_root / "autotest" / "lua_bridge_offset.txt"


def _read_offset(civ5ai_root: Path) -> int:
    path = _offset_path(civ5ai_root)
    if not path.is_file():
        return 0
    try:
        return max(0, int(path.read_text(encoding="utf-8").strip() or "0"))
    except ValueError:
        return 0


def _write_offset(civ5ai_root: Path, offset: int) -> None:
    path = _offset_path(civ5ai_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset), encoding="utf-8")


_PENDING_BLOBS: dict[str, dict[str, Any]] = {}


def parse_blob_lines(
    text: str,
    pending: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Parse CIV5AI blob frames from a Lua.log chunk.

    Incomplete blobs stay in *pending* so a dump split across two reads still
    completes. The watch process keeps a module-level store for that.
    """
    store = _PENDING_BLOBS if pending is None else pending
    complete: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        marker = line.find("CIV5AI|blob|")
        if marker < 0:
            continue
        line = line[marker:]
        begin = _BEGIN.search(line)
        if begin:
            store[begin.group("id")] = {
                "kind": begin.group("kind"),
                "id": begin.group("id"),
                "chunks": int(begin.group("chunks")),
                "live": begin.group("live") == "1",
                "player": int(begin.group("player")),
                "turn": int(begin.group("turn")),
                "session": begin.group("session").strip(),
                "parts": {},
            }
            continue
        chunk = _CHUNK.search(line)
        if chunk:
            blob = store.get(chunk.group("id"))
            if blob is not None:
                blob["parts"][int(chunk.group("index"))] = chunk.group("data")
            continue
        end = _END.search(line)
        if not end:
            continue
        blob = store.pop(end.group("id"), None)
        if blob is None:
            continue
        missing = [i for i in range(blob["chunks"]) if i not in blob["parts"]]
        if missing:
            log.warning(
                "Blob incomplete %s missing %s/%s chunks",
                blob["id"],
                len(missing),
                blob["chunks"],
            )
            continue
        pieces = [blob["parts"][i] for i in range(blob["chunks"])]
        encoded = "".join(pieces)
        try:
            payload = base64.b64decode(encoded.encode("ascii"), validate=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            log.warning("Blob decode failed %s: %s", blob["id"], error)
            continue
        blob["payload"] = payload
        complete.append(blob)
    return complete


def keep_current_snapshot_blobs(blobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the newest snapshot dump per player from one Lua.log chunk.

    Running every blob in order re-ran old LLM jobs (turn 0/1/3) while the
    game was already waiting on a later turn, so apply timed out.
    """
    latest_turn: dict[tuple[str, int], int] = {}
    for blob in blobs:
        if blob.get("kind") not in ("snapshot", "snapshot_chat"):
            continue
        key = (str(blob.get("session") or ""), int(blob.get("player") or 0))
        turn = int(blob.get("turn") or 0)
        if turn >= latest_turn.get(key, -1):
            latest_turn[key] = turn
    kept: list[dict[str, Any]] = []
    seen_kind: set[tuple[str, int, str]] = set()
    for blob in reversed(blobs):
        kind = blob.get("kind")
        if kind not in ("snapshot", "snapshot_chat"):
            continue
        key = (str(blob.get("session") or ""), int(blob.get("player") or 0))
        turn = int(blob.get("turn") or 0)
        if turn != latest_turn.get(key):
            continue
        kind_key = (key[0], key[1], str(kind))
        if kind_key in seen_kind:
            continue
        seen_kind.add(kind_key)
        kept.append(blob)
    kept.reverse()
    return kept


def _runtime(civ5ai_root: Path) -> dict[str, Any]:
    path = civ5ai_root / "runtime.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _copy_if_present(src: Path, dst: Path) -> None:
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def mirror_player_outputs(player_dir: Path, lua_log: Path, session_id: str, player: int) -> None:
    mirror = log_civ5ai_root(lua_log) / "sessions" / session_id / f"PLAYER_{player}"
    for name in ("decision.json", "decision_chat.json", "snapshot.json", "snapshot_chat.json"):
        _copy_if_present(player_dir / name, mirror / name)
    for src in player_dir.glob("*.json"):
        parts = src.stem.rsplit("_", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[2].lstrip("-").isdigit():
            _copy_if_present(src, mirror / src.name)


def _sidecar_job(
    repo: Path,
    python: str,
    player_dir: Path,
    session_id: str,
    live: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    args = [
        "--from-game",
        "--session-dir",
        str(player_dir),
        "--state",
        str(player_dir / "snapshot.json"),
        "--output",
        str(player_dir / "decision.json"),
        "--journal",
        str(player_dir / "journal.jsonl"),
        "--session-id",
        session_id,
    ]
    if live:
        args.append("--live")
    return {
        "python": python,
        "repo": str(repo),
        "script": "sidecar/run_civ5.py",
        "args": args,
        "timeout_seconds": timeout_seconds,
    }


def _sidecar_timeout_seconds(civ5ai_root: Path) -> int:
    runtime = _runtime(civ5ai_root)
    raw = runtime.get("sidecar_timeout_seconds") or runtime.get("SidecarTimeoutSeconds")
    try:
        return max(30, int(raw)) if raw not in (None, "") else 60
    except (TypeError, ValueError):
        return 60


def _complete_log_bytes(raw: bytes) -> tuple[bytes, bytes]:
    """Keep a trailing line that has no newline; the next read will finish it."""
    if not raw:
        return raw, b""
    if raw.endswith(b"\n") or raw.endswith(b"\r"):
        return raw, b""
    idx = raw.rfind(b"\n")
    if idx < 0:
        idx = raw.rfind(b"\r")
    if idx < 0:
        return b"", raw
    return raw[: idx + 1], raw[idx + 1 :]


def process_lua_log_blobs(
    lua_log: Path | None,
    civ5ai_root: Path,
    repo: Path,
    python: str = "python",
    timeout_seconds: int | None = None,
) -> int:
    """Read new Lua.log bytes, reconstruct snapshots, run sidecar. Returns jobs run."""
    if timeout_seconds is None:
        timeout_seconds = _sidecar_timeout_seconds(civ5ai_root)
    log_path = lua_log if lua_log is not None else default_lua_log()
    if not log_path.is_file():
        return 0
    offset = _read_offset(civ5ai_root)
    size = log_path.stat().st_size
    if offset > size:
        offset = 0
    with log_path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read()
    complete, _remainder = _complete_log_bytes(raw)
    if not complete:
        return 0
    new_offset = offset + len(complete)
    _write_offset(civ5ai_root, new_offset)
    chunk = complete.decode("utf-8", errors="replace")
    blobs = keep_current_snapshot_blobs(parse_blob_lines(chunk))
    ran = 0
    runtime = _runtime(civ5ai_root)
    active_session = str(runtime.get("session_id") or "").strip()
    live_default = str(runtime.get("sidecar_live") or "0") in ("1", "true", "True")
    python_exe = str(runtime.get("python") or python)
    repo_path = Path(str(runtime.get("repo") or repo))
    for blob in blobs:
        kind = blob.get("kind")
        if kind not in ("snapshot", "snapshot_chat"):
            continue
        is_chat = kind == "snapshot_chat"
        session_id = blob.get("session") or str(runtime.get("session_id") or "default")
        if active_session and session_id != active_session:
            continue
        player = int(blob.get("player") or 0)
        player_dir = civ5ai_root / "sessions" / session_id / f"PLAYER_{player}"
        player_dir.mkdir(parents=True, exist_ok=True)
        snapshot_name = "snapshot_chat.json" if is_chat else "snapshot.json"
        decision_name = "decision_chat.json" if is_chat else "decision.json"
        snapshot_path = player_dir / snapshot_name
        decision_path = player_dir / decision_name
        try:
            json.loads(blob["payload"])
        except json.JSONDecodeError as error:
            log.warning("Blob payload is not JSON %s: %s", blob.get("id"), error)
            continue
        snapshot_path.write_text(blob["payload"], encoding="utf-8")
        if not is_chat and decision_suppresses_sidecar(player_dir):
            mirror_player_outputs(player_dir, log_path, session_id, player)
            try:
                from civ5_pending_apply import publish_from_player_dir

                time.sleep(1.0)
                publish_from_player_dir(player_dir)
            except Exception as error:
                log.warning("Pending apply publish (suppressed sidecar) failed player=%s: %s", player, error)
            continue
        live = bool(blob.get("live")) or live_default
        if is_chat:
            live = True
        job = {
            "python": python_exe,
            "repo": str(repo_path),
            "script": "sidecar/run_civ5.py",
            "args": [
                "--from-game",
                "--session-dir",
                str(player_dir),
                "--state",
                str(snapshot_path),
                "--output",
                str(decision_path),
                "--journal",
                str(player_dir / "journal.jsonl"),
                "--session-id",
                session_id,
            ],
            "timeout_seconds": timeout_seconds,
        }
        if live:
            job["args"].append("--live")
        try:
            _run_job(job, repo_path)
            ran += 1
        except Exception as error:
            log.warning("Lua-log sidecar failed player=%s chat=%s: %s", player, is_chat, error)
            continue
        mirror_player_outputs(player_dir, log_path, session_id, player)
        try:
            from civ5_lua_log_bridge import sync_session_files

            sync_session_files(civ5ai_root, log_path)
        except Exception as error:
            log.warning("Session sync after sidecar failed player=%s: %s", player, error)
        try:
            from civ5_pending_apply import publish_from_player_dir

            time.sleep(1.0)
            publish_from_player_dir(player_dir, chat=is_chat)
        except Exception as error:
            log.warning("Pending apply publish failed player=%s: %s", player, error)
    return ran


def sync_session_files(civ5ai_root: Path, lua_log: Path | None = None) -> None:
    """Mirror session artifacts to Logs/civ5ai so InGame Lua can read them."""
    log_path = lua_log if lua_log is not None else default_lua_log()
    if log_path.is_file():
        _sync_session_trees(civ5ai_root, log_path)


def _sync_session_trees(civ5ai_root: Path, lua_log: Path) -> None:
    names = (
        "snapshot.json",
        "snapshot_chat.json",
        "decision.json",
        "decision_chat.json",
        "journal.jsonl",
        "sidecar_job.json",
    )
    roots = [civ5ai_root, log_civ5ai_root(lua_log)]
    for source_root in roots:
        sessions = source_root / "sessions"
        if not sessions.is_dir():
            continue
        for player_dir in sessions.glob("*/PLAYER_*"):
            rel = player_dir.relative_to(source_root)
            for dest_root in roots:
                if dest_root == source_root:
                    continue
                dest_dir = dest_root / rel
                dest_dir.mkdir(parents=True, exist_ok=True)
                files = [player_dir / name for name in names]
                for src in player_dir.glob("*.json"):
                    parts = src.stem.rsplit("_", 2)
                    if len(parts) == 3 and parts[1].isdigit() and parts[2].lstrip("-").isdigit():
                        files.append(src)
                files.extend(player_dir.glob("apply_t*.json"))
                for src in files:
                    if not src.is_file():
                        continue
                    dst = dest_dir / src.name
                    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size > 0:
                        continue
                    dst.write_bytes(src.read_bytes())


def process_pending_snapshots(
    civ5ai_root: Path,
    repo: Path,
    python: str = "python",
    timeout_seconds: int | None = None,
) -> int:
    """Run sidecar for snapshots that were dumped but never decided."""
    if timeout_seconds is None:
        timeout_seconds = _sidecar_timeout_seconds(civ5ai_root)
    runtime = _runtime(civ5ai_root)
    active_session = str(runtime.get("session_id") or "").strip()
    python_exe = str(runtime.get("python") or python)
    repo_path = Path(str(runtime.get("repo") or repo))
    live = str(runtime.get("sidecar_live") or "0") in ("1", "true", "True")
    ran = 0
    sessions = civ5ai_root / "sessions"
    if not sessions.is_dir():
        return 0
    for snapshot_path in sessions.rglob("snapshot.json"):
        player_dir = snapshot_path.parent
        session_id = player_dir.parent.name
        if active_session and session_id != active_session:
            continue
        if _read_json(snapshot_path) is None:
            continue
        if decision_suppresses_sidecar(player_dir):
            attempt = player_dir / "inbox_inject_attempt.lock"
            if attempt.is_file():
                continue
            try:
                from civ5_pending_apply import publish_from_player_dir

                publish_from_player_dir(player_dir)
            except Exception as error:
                log.warning("Pending apply publish (suppressed sidecar) failed %s: %s", player_dir, error)
            continue
        job = _sidecar_job(repo_path, python_exe, player_dir, session_id, live, timeout_seconds)
        try:
            _run_job(job, repo_path)
            ran += 1
        except Exception as error:
            log.warning("Pending snapshot sidecar failed %s: %s", player_dir, error)
            continue
        sync_session_files(civ5ai_root)
        try:
            from civ5_pending_apply import publish_from_player_dir

            publish_from_player_dir(player_dir)
        except Exception as error:
            log.warning("Pending apply publish failed %s: %s", player_dir, error)
    return ran


def _nudge_offset_path(civ5ai_root: Path) -> Path:
    return civ5ai_root / "autotest" / "autotest_nudge_offset.txt"


def _lua_nudge_offset_path(civ5ai_root: Path) -> Path:
    return civ5ai_root / "autotest" / "lua_nudge_offset.txt"


def _read_nudge_offset(offset_path: Path) -> int:
    if not offset_path.is_file():
        return 0
    try:
        return max(0, int(offset_path.read_text(encoding="utf-8").strip() or "0"))
    except ValueError:
        return 0


def _tail_file_for_nudge(path: Path, offset: int) -> tuple[str, int]:
    if not path.is_file():
        return "", offset
    size = path.stat().st_size
    read_offset = offset
    if read_offset > size:
        read_offset = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        handle.seek(read_offset)
        chunk = handle.read()
        new_offset = handle.tell()
    return chunk, new_offset


def _chunk_requests_nudge(chunk: str) -> bool:
    if not chunk:
        return False
    # Inbox focus blocks CONTROL_ENDTURN. Click the map so Lua can end the
    # turn after LLM apply. Do not send Enter — that skips the LLM turn.
    if "end_turn_blocked|" in chunk or "end_turn_failed|" in chunk:
        return True
    if "nudge_enter|" in chunk:
        return True
    return False


def process_autotest_nudges(civ5ai_root: Path, lua_log: Path | None = None) -> int:
    """Send Enter taps to the game when autotest or Lua.log requests dialog dismissal."""
    if os.name != "nt":
        return 0
    autotest_logs = [civ5ai_root / "autotest" / "autotest.log"]
    if lua_log is not None:
        mirror = log_civ5ai_root(lua_log) / "autotest" / "autotest.log"
        if mirror not in autotest_logs:
            autotest_logs.append(mirror)
    offset_path = _nudge_offset_path(civ5ai_root)
    offset = _read_nudge_offset(offset_path)
    lua_offset_path = _lua_nudge_offset_path(civ5ai_root)
    lua_offset = _read_nudge_offset(lua_offset_path)
    chunk_parts: list[str] = []
    new_offset = offset
    for autotest_log in autotest_logs:
        if not autotest_log.is_file():
            continue
        part, new_offset = _tail_file_for_nudge(autotest_log, new_offset)
        if part:
            chunk_parts.append(part)
    offset_path.parent.mkdir(parents=True, exist_ok=True)
    offset_path.write_text(str(new_offset), encoding="utf-8")
    new_lua_offset = lua_offset
    if lua_log is not None and lua_log.is_file():
        part, new_lua_offset = _tail_file_for_nudge(lua_log, lua_offset)
        if part:
            chunk_parts.append(part)
        lua_offset_path.write_text(str(new_lua_offset), encoding="utf-8")
    chunk = "".join(chunk_parts)
    if not _chunk_requests_nudge(chunk):
        return 0
    try:
        from civ5_host_channel import release_ui_focus

        # CONTROL_ENDTURN no-ops while HostInbox/chat has keyboard focus.
        if release_ui_focus():
            log.info("Autotest nudge: map click to release inbox focus")
            return 1
    except Exception as error:
        log.warning("Autotest nudge failed: %s", error)
    return 0


def process_host_io(
    civ5ai_root: Path,
    lua_log: Path | None,
    repo: Path,
    python: str = "python",
) -> int:
    """Portable host loop: Lua.log dumps + file jobs in civ5ai and Logs/civ5ai."""
    log_path = lua_log
    ran = 0
    # Enter first: leftover end_turn_failed must not wait behind 60–180s LLM jobs.
    if log_path is not None:
        ran += process_autotest_nudges(civ5ai_root, log_path)
    if log_path is not None and log_path.is_file():
        ran += process_lua_log_blobs(log_path, civ5ai_root, repo, python=python)
    ran += process_pending_snapshots(civ5ai_root, repo, python=python)
    from civ5_sidecar_jobs import process_sidecar_jobs

    roots = [civ5ai_root]
    if log_path is not None:
        roots.append(log_civ5ai_root(log_path))
    active_session = str(_runtime(civ5ai_root).get("session_id") or "").strip()
    ran += process_sidecar_jobs(roots, session_id=active_session or None)
    if log_path is not None:
        _sync_session_trees(civ5ai_root, log_path)
    else:
        sync_session_files(civ5ai_root)
    ran += process_autotest_nudges(civ5ai_root, log_path)
    return ran
