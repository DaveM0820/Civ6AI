"""Process Civ6Ai sidecar job files written by the InGame mod (os.execute is blocked)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def decision_suppresses_sidecar(player_dir: Path) -> bool:
    """Only skip sidecar when an approved decision matches the current snapshot turn."""
    decision_path = player_dir / "decision.json"
    if not decision_path.is_file() or decision_path.stat().st_size == 0:
        return False
    payload = _read_json(decision_path)
    if payload is None:
        return False
    if payload.get("status") == "fallback":
        return False
    if payload.get("status") != "approved":
        return False
    snapshot_path = player_dir / "snapshot.json"
    if not snapshot_path.is_file():
        return True
    snapshot = _read_json(snapshot_path)
    if snapshot is None:
        return True
    snap_turn = snapshot.get("decision", {}).get("turn")
    metrics = payload.get("metrics")
    decision_turn = metrics.get("turn") if isinstance(metrics, dict) else None
    if snap_turn is None or decision_turn is None:
        return True
    try:
        return int(snap_turn) == int(decision_turn)
    except (TypeError, ValueError):
        return True


def _run_job(job: dict[str, Any], repo: Path) -> None:
    import sys

    python = str(job.get("python") or "python")
    script = str(job.get("script") or "sidecar/run_civ6.py")
    args = job.get("args")
    if not isinstance(args, list):
        args = []
    script_path = repo / script
    cmd = [python, str(script_path), *[str(arg) for arg in args]]
    timeout = int(job.get("timeout_seconds") or 0)
    if timeout <= 0:
        try:
            from sidecar.civ6_config import load_local_config

            timeout = int(load_local_config().timeout_seconds)
        except Exception:
            timeout = 600
    kwargs: dict[str, Any] = {
        "cwd": str(repo),
        "timeout": timeout,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        from windows_process import hidden_popen_kwargs

        kwargs.update(hidden_popen_kwargs())
    except Exception:
        pass
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        # Keep the reason: a bare "exit status 1" hid a schema rejection that turned
        # every seat's turn into an empty apply.
        tail = (result.stderr or "").strip()[-2000:]
        session_dir = None
        if "--session-dir" in args:
            index = args.index("--session-dir")
            if index + 1 < len(args):
                session_dir = Path(str(args[index + 1]))
        if session_dir is not None and session_dir.is_dir():
            try:
                (session_dir / "sidecar_stderr.txt").write_text(tail + "\n", encoding="utf-8")
            except OSError:
                pass
        last = tail.splitlines()[-1] if tail else ""
        raise subprocess.CalledProcessError(result.returncode, cmd, output=None, stderr=last or tail)


CLAIM_NAME = "sidecar_job.claim"
_POOL_LOCK = threading.Lock()
_POOL: ThreadPoolExecutor | None = None
_POOL_SIZE = 0
_IN_FLIGHT: set[str] = set()


def claim_sidecar_slot(player_dir: Path) -> Path | None:
    """Cross-process claim so the poller and the Lua bridge never run one seat twice."""
    return _try_claim(player_dir)


def release_sidecar_slot(claim: Path | None) -> None:
    if claim is None:
        return
    claim.unlink(missing_ok=True)


def parallel_seat_limit() -> int:
    """Seats that may call the model at once (OpenRouter runs them side by side)."""
    raw = os.environ.get("CIV6AI_PARALLEL_SEATS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    try:
        from sidecar.civ6_config import load_local_config

        return max(1, load_local_config().effective_parallel_seats)
    except Exception:
        return 1


def _claim_stale_seconds() -> float:
    try:
        from sidecar.civ6_config import load_local_config

        return float(load_local_config().timeout_seconds) + 120.0
    except Exception:
        return 720.0


def _try_claim(player_dir: Path) -> Path | None:
    """Cross-process claim so the poller and the Lua bridge never run one job twice."""
    claim = player_dir / CLAIM_NAME
    try:
        if claim.is_file() and time.time() - claim.stat().st_mtime > _claim_stale_seconds():
            claim.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        fd = os.open(str(claim), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    except OSError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {time.time():.0f}\n")
    return claim


def _pending_jobs(roots: list[Path]) -> list[Path]:
    jobs: list[Path] = []
    seen: set[str] = set()
    for civ6ai_root in roots:
        sessions = civ6ai_root / "sessions"
        if not sessions.is_dir():
            continue
        for job_path in sorted(sessions.rglob("sidecar_job.json")):
            key = str(job_path.resolve())
            if key in seen:
                continue
            seen.add(key)
            if job_path.is_file():
                jobs.append(job_path)
    return jobs


def _process_one(job_path: Path) -> bool:
    """Run one seat job end to end. Returns True when the model job ran."""
    try:
        job = json.loads(job_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        log.warning("Invalid sidecar job %s: %s", job_path, error)
        return False
    if not isinstance(job, dict):
        return False
    player_dir = job_path.parent
    args = job.get("args")
    if not isinstance(args, list):
        args = []
    output_path = None
    for index, arg in enumerate(args):
        if arg == "--output" and index + 1 < len(args):
            output_path = Path(str(args[index + 1]))
            break
    is_chat_job = output_path is not None and output_path.name == "decision_chat.json"
    decision_path = output_path if is_chat_job else player_dir / "decision.json"
    if not is_chat_job and decision_suppresses_sidecar(player_dir):
        job_path.unlink(missing_ok=True)
        return False
    repo = Path(str(job.get("repo") or ""))
    if not repo.is_dir():
        log.warning("Sidecar job missing repo: %s", job_path)
        return False
    ran = False
    try:
        _run_job(job, repo)
        ran = True
    except Exception as error:
        log.warning("Sidecar job failed %s: %s", job_path, error)
        return False
    finally:
        if decision_path.is_file() and decision_path.stat().st_size > 0:
            job_path.unlink(missing_ok=True)
    try:
        from civ6_pending_apply import publish_from_player_dir

        time.sleep(1.0)
        publish_from_player_dir(player_dir, chat=is_chat_job)
    except Exception as error:
        log.warning("Pending apply publish failed %s: %s", player_dir, error)
    return ran


def _claimed_run(job_path: Path, claim: Path) -> bool:
    try:
        return _process_one(job_path)
    finally:
        claim.unlink(missing_ok=True)
        with _POOL_LOCK:
            _IN_FLIGHT.discard(str(job_path.resolve()))


def _pool(size: int) -> ThreadPoolExecutor:
    global _POOL, _POOL_SIZE
    if _POOL is None or _POOL_SIZE != size:
        _POOL = ThreadPoolExecutor(max_workers=size, thread_name_prefix="civ6ai-seat")
        _POOL_SIZE = size
    return _POOL


def process_sidecar_jobs(civ6ai_roots: list[Path] | Path, *, parallel: int | None = None) -> int:
    """Run pending sidecar_job.json files. Accepts one root or a list of roots.

    With one seat at a time (LM Studio) jobs run in order and this call blocks.
    With parallel seats (OpenRouter) each job starts on a worker thread as soon as
    it appears and this call returns the number of jobs it started.
    """
    roots = [civ6ai_roots] if isinstance(civ6ai_roots, Path) else list(civ6ai_roots)
    limit = parallel if parallel is not None else parallel_seat_limit()
    started = 0
    for job_path in _pending_jobs(roots):
        key = str(job_path.resolve())
        with _POOL_LOCK:
            if key in _IN_FLIGHT:
                continue
        claim = _try_claim(job_path.parent)
        if claim is None:
            continue
        if limit <= 1:
            try:
                if _process_one(job_path):
                    started += 1
            finally:
                claim.unlink(missing_ok=True)
            continue
        with _POOL_LOCK:
            _IN_FLIGHT.add(key)
        _pool(limit).submit(_claimed_run, job_path, claim)
        started += 1
    return started


def discover_civ6ai_roots(primary: Path) -> list[Path]:
    """Watch Documents and OneDrive civ6ai folders (game may write to either)."""
    primary_key = str(primary)
    try:
        if primary.exists():
            primary_key = str(primary.resolve())
    except OSError:
        pass
    if "My Games" not in primary_key or "Civilization VI" not in primary_key:
        return [primary]
    home = Path.home()
    candidates = [
        primary,
        home / "Documents/My Games/Sid Meier's Civilization VI/civ6ai",
        home / "OneDrive/Documents/My Games/Sid Meier's Civilization VI/civ6ai",
    ]
    roots: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            key = str(path.resolve()) if path.exists() else str(path)
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_dir() or path == primary:
            roots.append(path)
    if not roots:
        roots.append(primary)
    return roots
