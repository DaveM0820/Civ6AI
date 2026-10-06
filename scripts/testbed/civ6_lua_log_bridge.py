"""Rebuild Civ6Ai snapshots from Lua.log print dumps and run the sidecar.

Used when retail Lua cannot write files (io sandbox). Every Civ6 install
writes Logs/Lua.log via print(); Python publishes apply payloads via the hidden InGame inbox.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from civ6_sidecar_jobs import (
    _pool,
    _run_job,
    claim_sidecar_slot,
    decision_suppresses_sidecar,
    parallel_seat_limit,
    release_sidecar_slot,
)

log = logging.getLogger(__name__)

_BEGIN = re.compile(
    r"CIV6AI\|blob\|begin\|(?P<kind>[^|]+)\|(?P<id>[^|]+)\|(?P<chunks>\d+)\|"
    r"(?P<live>\d+)\|(?P<player>\d+)\|(?P<turn>-?\d+)\|(?P<session>[^\r\n]*)"
)
_CHUNK = re.compile(r"CIV6AI\|blob\|c\|(?P<id>[^|]+)\|(?P<index>\d+)\|(?P<data>[^\r\n]*)")
_END = re.compile(r"CIV6AI\|blob\|end\|(?P<id>[^|]+)")


def _decode_blob_payload(raw: bytes) -> str:
    """Decode snapshot JSON bytes; salvage seats when legacy blobs have bad UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        log.warning("Blob payload has invalid UTF-8 (%s); using replacement characters", error)
        return raw.decode("utf-8", errors="replace")


_LOGGED_ONCE: set[str] = set()


def _log_once(key: str, message: str, *args: Any) -> None:
    if key in _LOGGED_ONCE:
        return
    _LOGGED_ONCE.add(key)
    log.info(message, *args)


def default_lua_log() -> Path:
    local_app = os.environ.get("LOCALAPPDATA") or ""
    return Path(local_app) / "Firaxis Games" / "Sid Meier's Civilization VI" / "Logs" / "Lua.log"


def log_civ6ai_root(lua_log: Path) -> Path:
    return lua_log.parent / "civ6ai"


def _offset_path(civ6ai_root: Path) -> Path:
    return civ6ai_root / "autotest" / "lua_bridge_offset.txt"


def _log_head(path: Path, size: int = 512) -> str:
    """Hash of the first bytes of a log, so a rewritten Lua.log (Civ6 reboot) is detected."""
    try:
        with path.open("rb") as handle:
            return hashlib.sha1(handle.read(size)).hexdigest()
    except OSError:
        return ""


def _load_offset_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if isinstance(data, int):
        return {"offset": max(0, data)}
    return data if isinstance(data, dict) else {}


def resolve_log_offset(state_path: Path, log_path: Path) -> int:
    """Stored read offset for log_path, or 0 when the log was rewritten.

    Civ6 truncates Lua.log on every boot. The old check (offset > size) missed a
    rewrite whenever the new log was still smaller than the old offset only at the
    moment we looked, or had already grown past it; we then skipped the new game's
    snapshots forever. Detect a rewrite by a shrinking size or a changed head.
    """
    state = _load_offset_state(state_path)
    offset = int(state.get("offset") or 0)
    size = log_path.stat().st_size
    if offset > size or size < int(state.get("size") or 0):
        return 0
    head = state.get("head")
    if head is not None and head != _log_head(log_path):
        return 0
    return max(0, offset)


def store_log_offset(state_path: Path, log_path: Path, offset: int) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = log_path.stat().st_size
    except OSError:
        size = offset
    state = {"offset": int(offset), "size": int(size), "head": _log_head(log_path)}
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _read_offset(civ6ai_root: Path, log_path: Path | None = None) -> int:
    path = _offset_path(civ6ai_root)
    if log_path is None or not log_path.is_file():
        return int(_load_offset_state(path).get("offset") or 0)
    return resolve_log_offset(path, log_path)


def _write_offset(civ6ai_root: Path, offset: int, log_path: Path | None = None) -> None:
    path = _offset_path(civ6ai_root)
    if log_path is None or not log_path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"offset": int(offset)}), encoding="utf-8")
        return
    store_log_offset(path, log_path, offset)


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
            payload = _decode_blob_payload(base64.b64decode(encoded.encode("ascii"), validate=False))
        except ValueError as error:
            log.warning("Blob decode failed %s: %s", blob["id"], error)
            continue
        blob["payload"] = payload
        complete.append(blob)
    return complete


_JSONL_MARK = "CIV6AI|jsonl|"
APPLY_RESULTS_NAME = "apply-results.jsonl"
_APPLY_RESULT_KEEP = ("ok", "event", "kind", "reason", "turn", "fixed_arguments", "command_id", "player_id")


def parse_apply_result_lines(text: str) -> list[dict[str, Any]]:
    """apply_result rows the in-game Lua printed as CIV6AI|jsonl|{...} (it cannot write files).

    Partial or garbled lines (a read that ends mid-line) are skipped; the reader
    re-reads a trailing partial line on the next pass and rows are de-duplicated.
    """
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        marker = raw.find(_JSONL_MARK)
        if marker < 0:
            continue
        body = raw[marker + len(_JSONL_MARK):].strip()
        try:
            row = json.loads(body)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("event") != "apply_result":
            continue
        player = str(row.get("player_id") or "")
        if not re.fullmatch(r"PLAYER_\d+", player):
            continue
        try:
            row["turn"] = int(row.get("turn"))
        except (TypeError, ValueError):
            continue
        rows.append({key: row.get(key) for key in _APPLY_RESULT_KEEP if key in row})
    return rows


def _apply_result_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return (str(row.get("player_id")), int(row.get("turn") or 0), str(row.get("command_id") or ""))


def append_apply_results(civ6ai_root: Path, session_id: str, rows: list[dict[str, Any]]) -> int:
    """Append new rows to sessions/<session>/PLAYER_N/apply-results.jsonl (dedup on command_id+turn)."""
    if not session_id or not rows:
        return 0
    by_player: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_player.setdefault(str(row["player_id"]), []).append(row)
    written = 0
    for player, player_rows in by_player.items():
        path = civ6ai_root / "sessions" / session_id / player / APPLY_RESULTS_NAME
        seen: set[tuple[str, int, str]] = set()
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    old = json.loads(line)
                except ValueError:
                    continue
                if isinstance(old, dict):
                    try:
                        seen.add(_apply_result_key(old))
                    except (TypeError, ValueError):
                        continue
        fresh: list[str] = []
        for row in player_rows:
            key = _apply_result_key(row)
            if key in seen:
                continue
            seen.add(key)
            fresh.append(json.dumps(row, separators=(",", ":"), sort_keys=True))
        if not fresh:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(fresh) + "\n")
        written += len(fresh)
    return written


def record_apply_results(civ6ai_root: Path, chunk: str, blobs: list[dict[str, Any]], active_session: str) -> int:
    """Persist this chunk's apply_result rows before the seats' next prompts are built."""
    rows = parse_apply_result_lines(chunk)
    if not rows:
        return 0
    session_id = active_session
    if not session_id:
        sessions = [str(b.get("session") or "") for b in blobs if b.get("session")]
        session_id = sessions[-1] if sessions else ""
    if not session_id:
        _log_once("apply_results_no_session", "apply_result rows seen but no active session; not recorded")
        return 0
    try:
        return append_apply_results(civ6ai_root, session_id, rows)
    except OSError as error:
        log.warning("apply-results append failed: %s", error)
        return 0


# A blob whose begin line was read but whose end line was not yet in Lua.log.
# The reader used to advance its offset past such a partial blob, so the next
# read saw chunks + end without a begin and silently dropped the snapshot: the
# game then waited forever for that seat's answer (P0 turn 27 stalled 30+ min).
_MAX_HOLD_BYTES = 4 * 1024 * 1024
_BEGIN_MARK = b"CIV6AI|blob|begin|"
_END_MARK = b"CIV6AI|blob|end|"
_PROCESSED_BLOBS: list[str] = []


def incomplete_blob_offset(data: bytes) -> int | None:
    """Byte offset (line start) of the earliest blob begun but not ended in data."""
    open_at: dict[bytes, int] = {}
    pos = 0
    for line in data.splitlines(keepends=True):
        begin = line.find(_BEGIN_MARK)
        if begin >= 0:
            fields = line[begin + len(_BEGIN_MARK):].split(b"|")
            if len(fields) >= 2:
                open_at.setdefault(fields[1].strip(), pos)
        else:
            end = line.find(_END_MARK)
            if end >= 0:
                open_at.pop(line[end + len(_END_MARK):].strip(), None)
        pos += len(line)
    # A trailing partial line (no newline yet) could be a begin/end in progress.
    if data and not data.endswith((b"\n", b"\r")):
        tail_start = max(data.rfind(b"\n"), data.rfind(b"\r")) + 1
        open_at.setdefault(b"__partial_line__", tail_start)
    return min(open_at.values()) if open_at else None


def _blob_key(blob: dict[str, Any]) -> str:
    digest = hashlib.sha1(str(blob.get("payload") or "").encode("utf-8")).hexdigest()
    return f"{blob.get('id')}|{digest}"


def _already_processed(blob: dict[str, Any]) -> bool:
    key = _blob_key(blob)
    if key in _PROCESSED_BLOBS:
        return True
    _PROCESSED_BLOBS.append(key)
    del _PROCESSED_BLOBS[:-500]
    return False


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


_PUBLISH_LOCK = threading.Lock()


def session_id_of(player_dir: Path) -> str:
    return player_dir.parent.name


def _parallel_seats() -> int:
    try:
        return max(1, int(os.environ.get("CIV6AI_PARALLEL_SEATS") or 1))
    except ValueError:
        return 1


def latest_blob_per_seat(blobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the newest snapshot blob per (session, player, kind).

    After a helper restart the log backlog can hold many turns of snapshots for
    each seat; answering old turns wastes model time and publishes stale orders.
    """
    newest: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    order: list[tuple[Any, Any, Any]] = []
    for blob in blobs:
        if blob.get("kind") not in ("snapshot", "snapshot_chat"):
            continue
        key = (blob.get("session"), blob.get("player"), blob.get("kind"))
        prev = newest.get(key)
        if prev is None:
            order.append(key)
        if prev is None or int(blob.get("turn") or 0) >= int(prev.get("turn") or 0):
            newest[key] = blob
    return [newest[k] for k in order]


def _note_build_stamp(chunk: str, repo: Path) -> None:
    match = re.search(r"CIV6AI\|build\|([^\s|]+)", chunk)
    if not match:
        return
    seen = match.group(1).strip()
    try:
        from install_mod import compute_build_stamp
    except Exception:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        try:
            from install_mod import compute_build_stamp
        except Exception:
            return
    expected = compute_build_stamp(repo)
    if expected and seen and expected != seen:
        _log_once(
            f"build_mismatch|{seen}|{expected}",
            "build_mismatch|installed=%s repo=%s — re-run scripts/install_mod.py",
            seen,
            expected,
        )


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
    offset = _read_offset(civ6ai_root, log_path)
    with log_path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
        new_offset = handle.tell()
    if not data:
        _write_offset(civ6ai_root, offset, log_path)
        return 0
    hold = incomplete_blob_offset(data)
    if hold is not None and len(data) - hold < _MAX_HOLD_BYTES:
        # Re-read from the unfinished blob's begin next time. Complete blobs in this
        # read are processed now and de-duplicated when read again. A begin with
        # megabytes of log after it and still no end is stale and is let go.
        new_offset = offset + hold
    chunk = data.decode("utf-8", errors="replace")
    _write_offset(civ6ai_root, new_offset, log_path)
    blobs = parse_blob_lines(chunk)
    ran = 0
    runtime = _runtime(civ6ai_root)
    live_default = str(runtime.get("sidecar_live") or "0") in ("1", "true", "True")
    python_exe = str(runtime.get("python") or python)
    repo_path = Path(str(runtime.get("repo") or repo))
    active_session = str(runtime.get("session_id") or "").strip()
    record_apply_results(civ6ai_root, chunk, blobs, active_session)
    _note_build_stamp(chunk, repo_path)
    if "autotest|stall|" in chunk or "CIV6AI|autotest|stall|" in chunk:
        log.warning("stall reported in Lua.log")
    blobs = latest_blob_per_seat(blobs)
    jobs: list[tuple[dict[str, Any], int, bool, Path]] = []
    for blob in blobs:
        kind = blob.get("kind")
        if kind not in ("snapshot", "snapshot_chat"):
            continue
        is_chat = kind == "snapshot_chat"
        if _already_processed(blob):
            continue
        session_id = blob.get("session") or active_session or "default"
        if active_session and session_id != active_session:
            # A game still running an older session (or old Lua.log content): never
            # spend model time on it or publish its answers into the live module.
            _log_once(f"skip_session|{session_id}", "Skipping snapshot blobs of inactive session %s (active %s)",
                      session_id, active_session)
            continue
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
        jobs.append((job, player, is_chat, player_dir))

    def _one(item: tuple[dict[str, Any], int, bool, Path]) -> bool:
        job, player, is_chat, player_dir = item
        claim = claim_sidecar_slot(player_dir)
        if claim is None:
            return False
        try:
            try:
                _run_job(job, repo_path)
            except Exception as error:
                log.warning("Lua-log sidecar failed player=%s chat=%s: %s | %s", player, is_chat, error,
                            getattr(error, "stderr", "") or "")
                return False
            with _PUBLISH_LOCK:
                mirror_player_outputs(player_dir, log_path, session_id_of(player_dir), player)
                try:
                    from civ6_pending_apply import publish_from_player_dir

                    time.sleep(1.0)
                    publish_from_player_dir(player_dir, chat=is_chat)
                except Exception as error:
                    log.warning("Pending apply publish failed player=%s: %s", player, error)
            return True
        finally:
            release_sidecar_slot(claim)

    workers = max(1, min(len(jobs), _parallel_seats(), parallel_seat_limit()))
    if workers <= 1:
        ran = sum(1 for item in jobs if _one(item))
    else:
        # Persistent pool: a slow seat does not open/close a ThreadPoolExecutor
        # around the whole batch (that serialized two-wave turns).
        futures = [_pool(workers).submit(_one, item) for item in jobs]
        ran = len(futures)
    return ran


def sync_session_files(civ6ai_root: Path, lua_log: Path | None = None) -> None:
    """Mirror session artifacts to Logs/civ6ai so InGame Lua can read them."""
    log_path = lua_log if lua_log is not None else default_lua_log()
    if log_path.is_file():
        _sync_session_trees(civ6ai_root, log_path)


def _sync_session_trees(civ6ai_root: Path, lua_log: Path) -> None:
    """One-way copy session -> Logs/civ6ai mirror, keeping mtime (copy2).

    Two-way write_bytes ping-ponged files forever because mtime was not kept.
    """
    import shutil

    names = (
        "snapshot.json",
        "decision.json",
        "apply_commands.json",
        "journal.jsonl",
        "sidecar_job.json",
    )
    dest_root = log_civ6ai_root(lua_log)
    sessions = civ6ai_root / "sessions"
    if not sessions.is_dir() or dest_root == civ6ai_root:
        return
    for player_dir in sessions.glob("*/PLAYER_*"):
        rel = player_dir.relative_to(civ6ai_root)
        dest_dir = dest_root / rel
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            src = player_dir / name
            if not src.is_file():
                continue
            dst = dest_dir / name
            if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size == src.stat().st_size:
                continue
            shutil.copy2(src, dst)


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
            log.warning("Pending snapshot sidecar failed %s: %s | %s", player_dir, error, getattr(error, "stderr", "") or "")
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


_NUDGE_REQUESTS = ("nudge_enter|", "end_turn_blocked|", "end_turn_failed|")
_NUDGE_RESOLVED = ("autotest|local_turn_begin|",)


def _chunk_requests_nudge(chunk: str) -> bool:
    """True when the newest nudge request is not already superseded.

    A request followed by a newer local turn start is stale: Enter is the Next
    Turn hotkey, so tapping it now would end the new turn before the model's
    orders arrive.
    """
    if not chunk:
        return False
    last_request = max(chunk.rfind(marker) for marker in _NUDGE_REQUESTS)
    if last_request < 0:
        return False
    last_resolved = max(chunk.rfind(marker) for marker in _NUDGE_RESOLVED)
    return last_request > last_resolved


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
    if lua_log is not None and lua_log.is_file():
        lua_offset = resolve_log_offset(lua_offset_path, lua_log)
        with lua_log.open("rb") as handle:
            handle.seek(lua_offset)
            data = handle.read()
            new_lua_offset = handle.tell()
        part = data.decode("utf-8", errors="replace")
        if part:
            chunk_parts.append(part)
        store_log_offset(lua_offset_path, lua_log, new_lua_offset)
    if not any(_chunk_requests_nudge(part) for part in chunk_parts):
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
