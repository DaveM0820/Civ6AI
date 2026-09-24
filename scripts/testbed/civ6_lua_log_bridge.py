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

from civ6_sidecar_jobs import _run_job, decision_suppresses_sidecar

log = logging.getLogger(__name__)

_BEGIN = re.compile(
    r"CIV6AI\|blob\|begin\|(?P<kind>[^|]+)\|(?P<id>[^|]+)\|(?P<chunks>\d+)\|"
    r"(?P<live>\d+)\|(?P<player>\d+)\|(?P<turn>-?\d+)\|(?P<session>[^\r\n]*)"
)
_CHUNK = re.compile(r"CIV6AI\|blob\|c\|(?P<id>[^|]+)\|(?P<index>\d+)\|(?P<data>[^\r\n]*)")
_END = re.compile(r"CIV6AI\|blob\|end\|(?P<id>[^|]+)")


def default_lua_log() -> Path:
    local_app = os.environ.get("LOCALAPPDATA") or ""
    return Path(local_app) / "Firaxis Games" / "Sid Meier's Civilization VI" / "Logs" / "Lua.log"


def log_civ6ai_root(lua_log: Path) -> Path:
    return lua_log.parent / "civ6ai"


def _offset_path(civ6ai_root: Path) -> Path:
    return civ6ai_root / "autotest" / "lua_bridge_offset.txt"


def _read_offset(civ6ai_root: Path) -> int:
    path = _offset_path(civ6ai_root)
    if not path.is_file():
        return 0
    try:
        return max(0, int(path.read_text(encoding="utf-8").strip() or "0"))
    except ValueError:
        return 0


def _write_offset(civ6ai_root: Path, offset: int) -> None:
    path = _offset_path(civ6ai_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(offset), encoding="utf-8")


def parse_blob_lines(text: str) -> list[dict[str, Any]]:
    """Parse CIV6AI blob frames from a Lua.log chunk."""
    pending: dict[str, dict[str, Any]] = {}
    complete: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        marker = line.find("CIV6AI|blob|")
        if marker < 0:
            continue
        line = line[marker:]
        begin = _BEGIN.search(line)
        if begin:
            pending[begin.group("id")] = {
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
            blob = pending.get(chunk.group("id"))
            if blob is not None:
                blob["parts"][int(chunk.group("index"))] = chunk.group("data")
            continue
        end = _END.search(line)
        if not end:
            continue
        blob = pending.pop(end.group("id"), None)
        if blob is None:
            continue
        pieces = [blob["parts"].get(i, "") for i in range(blob["chunks"])]
        encoded = "".join(pieces)
        try:
            payload = base64.b64decode(encoded.encode("ascii"), validate=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            log.warning("Blob decode failed %s: %s", blob["id"], error)
            continue
        blob["payload"] = payload
        complete.append(blob)
    return complete


def _runtime(civ6ai_root: Path) -> dict[str, Any]:
    path = civ6ai_root / "runtime.json"
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
    mirror = log_civ6ai_root(lua_log) / "sessions" / session_id / f"PLAYER_{player}"
    for name in ("decision.json", "decision_chat.json", "apply_commands.json", "snapshot.json", "snapshot_chat.json"):
        _copy_if_present(player_dir / name, mirror / name)


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
        "script": "sidecar/run_civ6.py",
        "args": args,
        "timeout_seconds": timeout_seconds,
    }


def _sidecar_timeout_seconds(civ6ai_root: Path) -> int:
    runtime = _runtime(civ6ai_root)
    raw = runtime.get("sidecar_timeout_seconds") or runtime.get("SidecarTimeoutSeconds")
    try:
        return max(30, int(raw)) if raw not in (None, "") else 60
    except (TypeError, ValueError):
        return 60


def process_lua_log_blobs(
    lua_log: Path | None,
    civ6ai_root: Path,
    repo: Path,
    python: str = "python",
    timeout_seconds: int | None = None,
) -> int:
    """Read new Lua.log bytes, reconstruct snapshots, run sidecar. Returns jobs run."""
    if timeout_seconds is None:
        timeout_seconds = _sidecar_timeout_seconds(civ6ai_root)
    log_path = lua_log if lua_log is not None else default_lua_log()
    if not log_path.is_file():
        return 0
    offset = _read_offset(civ6ai_root)
    size = log_path.stat().st_size
    if offset > size:
        offset = 0
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        chunk = handle.read()
        new_offset = handle.tell()
    if not chunk:
        return 0
    _write_offset(civ6ai_root, new_offset)
    blobs = parse_blob_lines(chunk)
    ran = 0
    runtime = _runtime(civ6ai_root)
    live_default = str(runtime.get("sidecar_live") or "0") in ("1", "true", "True")
    python_exe = str(runtime.get("python") or python)
    repo_path = Path(str(runtime.get("repo") or repo))
    for blob in blobs:
        kind = blob.get("kind")
        if kind not in ("snapshot", "snapshot_chat"):
            continue
        is_chat = kind == "snapshot_chat"
        session_id = blob.get("session") or str(runtime.get("session_id") or "default")
        player = int(blob.get("player") or 0)
        player_dir = civ6ai_root / "sessions" / session_id / f"PLAYER_{player}"
        player_dir.mkdir(parents=True, exist_ok=True)
        snapshot_name = "snapshot_chat.json" if is_chat else "snapshot.json"
        decision_name = "decision_chat.json" if is_chat else "decision.json"
        snapshot_path = player_dir / snapshot_name
        decision_path = player_dir / decision_name
        snapshot_path.write_text(blob["payload"], encoding="utf-8")
        if not is_chat and decision_suppresses_sidecar(player_dir):
            mirror_player_outputs(player_dir, log_path, session_id, player)
            try:
                from civ6_pending_apply import publish_from_player_dir

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
            "script": "sidecar/run_civ6.py",
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
            from civ6_pending_apply import publish_from_player_dir

            time.sleep(1.0)
            publish_from_player_dir(player_dir, chat=is_chat)
        except Exception as error:
            log.warning("Pending apply publish failed player=%s: %s", player, error)
    return ran


def sync_session_files(civ6ai_root: Path, lua_log: Path | None = None) -> None:
    """Mirror session artifacts to Logs/civ6ai so InGame Lua can read them."""
    log_path = lua_log if lua_log is not None else default_lua_log()
    if log_path.is_file():
        _sync_session_trees(civ6ai_root, log_path)


def _sync_session_trees(civ6ai_root: Path, lua_log: Path) -> None:
    names = (
        "snapshot.json",
        "decision.json",
        "apply_commands.json",
        "journal.jsonl",
        "sidecar_job.json",
    )
    roots = [civ6ai_root, log_civ6ai_root(lua_log)]
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
                for name in names:
                    src = player_dir / name
                    if not src.is_file():
                        continue
                    dst = dest_dir / name
                    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size > 0:
                        continue
                    dst.write_bytes(src.read_bytes())


def process_pending_snapshots(
    civ6ai_root: Path,
    repo: Path,
    python: str = "python",
    timeout_seconds: int | None = None,
) -> int:
    """Run sidecar for snapshots that were dumped but never decided."""
    if timeout_seconds is None:
        timeout_seconds = _sidecar_timeout_seconds(civ6ai_root)
    runtime = _runtime(civ6ai_root)
    active_session = str(runtime.get("session_id") or "").strip()
    python_exe = str(runtime.get("python") or python)
    repo_path = Path(str(runtime.get("repo") or repo))
    live = str(runtime.get("sidecar_live") or "0") in ("1", "true", "True")
    ran = 0
    sessions = civ6ai_root / "sessions"
    if not sessions.is_dir():
        return 0
    for snapshot_path in sessions.rglob("snapshot.json"):
        player_dir = snapshot_path.parent
        session_id = player_dir.parent.name
        if active_session and session_id != active_session:
            continue
        if decision_suppresses_sidecar(player_dir):
            try:
                from civ6_pending_apply import publish_from_player_dir

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
        sync_session_files(civ6ai_root)
        try:
            from civ6_pending_apply import publish_from_player_dir

            publish_from_player_dir(player_dir)
        except Exception as error:
            log.warning("Pending apply publish failed %s: %s", player_dir, error)
    return ran


def _nudge_offset_path(civ6ai_root: Path) -> Path:
    return civ6ai_root / "autotest" / "autotest_nudge_offset.txt"


def _lua_nudge_offset_path(civ6ai_root: Path) -> Path:
    return civ6ai_root / "autotest" / "lua_nudge_offset.txt"


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
    return chunk, max(new_offset, offset)


def _chunk_requests_nudge(chunk: str) -> bool:
    if not chunk:
        return False
    if "nudge_enter|" in chunk:
        return True
    if "autotest|nudge_enter|" in chunk:
        return True
    if "end_turn_blocked|" in chunk or "end_turn_failed|" in chunk:
        return True
    return False


def process_autotest_nudges(civ6ai_root: Path, lua_log: Path | None = None) -> int:
    """Send Enter taps to the game when autotest or Lua.log requests dialog dismissal."""
    if os.name != "nt":
        return 0
    autotest_logs = [civ6ai_root / "autotest" / "autotest.log"]
    if lua_log is not None:
        mirror = log_civ6ai_root(lua_log) / "autotest" / "autotest.log"
        if mirror not in autotest_logs:
            autotest_logs.append(mirror)
    offset_path = _nudge_offset_path(civ6ai_root)
    offset = _read_nudge_offset(offset_path)
    lua_offset_path = _lua_nudge_offset_path(civ6ai_root)
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
        from civ6_ui_automation import nudge_dialogs

        if nudge_dialogs():
            log.info("Autotest nudge: sent Enter taps to dismiss blocking dialog")
            return 1
    except Exception as error:
        log.warning("Autotest nudge failed: %s", error)
    return 0


def process_host_io(
    civ6ai_root: Path,
    lua_log: Path | None,
    repo: Path,
    python: str = "python",
) -> int:
    """Portable host loop: Lua.log dumps + file jobs in civ6ai and Logs/civ6ai."""
    log_path = lua_log
    ran = 0
    if log_path is not None and log_path.is_file():
        ran += process_lua_log_blobs(log_path, civ6ai_root, repo, python=python)
    ran += process_pending_snapshots(civ6ai_root, repo, python=python)
    from civ6_sidecar_jobs import process_sidecar_jobs

    roots = [civ6ai_root]
    if log_path is not None:
        roots.append(log_civ6ai_root(log_path))
    ran += process_sidecar_jobs(roots)
    if log_path is not None:
        _sync_session_trees(civ6ai_root, log_path)
    else:
        sync_session_files(civ6ai_root)
    ran += process_autotest_nudges(civ6ai_root, log_path)
    return ran
