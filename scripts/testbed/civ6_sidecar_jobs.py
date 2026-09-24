"""Process Civ6Ai sidecar job files written by the InGame mod (os.execute is blocked)."""
from __future__ import annotations

import json
import logging
import subprocess
import time
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
        "check": True,
        "timeout": timeout,
    }
    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        from windows_process import hidden_popen_kwargs

        kwargs.update(hidden_popen_kwargs())
    except Exception:
        pass
    subprocess.run(cmd, **kwargs)


def process_sidecar_jobs(civ6ai_roots: list[Path] | Path) -> int:
    """Run pending sidecar_job.json files. Accepts one root or a list of roots."""
    if isinstance(civ6ai_roots, Path):
        roots = [civ6ai_roots]
    else:
        roots = list(civ6ai_roots)
    ran = 0
    seen_jobs: set[str] = set()
    for civ6ai_root in roots:
        sessions = civ6ai_root / "sessions"
        if not sessions.is_dir():
            continue
        for job_path in sorted(sessions.rglob("sidecar_job.json")):
            key = str(job_path.resolve())
            if key in seen_jobs:
                continue
            seen_jobs.add(key)
            if not job_path.is_file():
                continue
            try:
                job = json.loads(job_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as error:
                log.warning("Invalid sidecar job %s: %s", job_path, error)
                continue
            if not isinstance(job, dict):
                continue
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
                continue
            repo = Path(str(job.get("repo") or ""))
            if not repo.is_dir():
                log.warning("Sidecar job missing repo: %s", job_path)
                continue
            try:
                _run_job(job, repo)
                ran += 1
            except Exception as error:
                log.warning("Sidecar job failed %s: %s", job_path, error)
                continue
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
