"""Read-only helpers to report sidecar circuit-breaker state (ASCII output).

The sidecar (`sidecar/run_civ6.py`) keeps per-seat hard-failure counts in a
`circuit_breaker.json` file next to its journal / session dirs. Live turns for a
seat are refused once its count reaches the threshold (see
`sidecar.pipeline_v2.CircuitBreaker`). These helpers only read and describe
those files; they never change them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

try:  # keep in sync with the sidecar's breaker threshold
    from sidecar.pipeline_v2 import CircuitBreaker as _CircuitBreaker

    DEFAULT_THRESHOLD = int(_CircuitBreaker(failures={}).threshold)
except Exception:  # pragma: no cover - fallback if sidecar import fails
    DEFAULT_THRESHOLD = 3


def read_failures(path: Path) -> tuple[dict[str, int] | None, str | None]:
    """Return (failures, error). failures is None when the file is missing/unreadable."""
    path = Path(path)
    if not path.is_file():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, ValueError) as error:
        return None, f"unreadable ({type(error).__name__})"
    if not isinstance(payload, dict):
        return None, "unexpected content (not a JSON object)"
    failures: dict[str, int] = {}
    for key, value in payload.items():
        try:
            failures[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return failures, None


def open_players(failures: dict[str, int] | None, threshold: int = DEFAULT_THRESHOLD) -> list[str]:
    if not failures:
        return []
    return sorted(player for player, count in failures.items() if count >= threshold)


def describe(path: Path, threshold: int = DEFAULT_THRESHOLD) -> str:
    """One-line ASCII description of a breaker file."""
    failures, error = read_failures(path)
    if error:
        return f"{path}: {error}"
    if failures is None:
        return f"{path}: not present (no failures recorded)"
    nonzero = {player: count for player, count in sorted(failures.items()) if count > 0}
    if not nonzero:
        return f"{path}: clear (no failures recorded)"
    parts = []
    for player, count in nonzero.items():
        state = "OPEN" if count >= threshold else "closed"
        parts.append(f"{player}={count}/{threshold} {state}")
    return f"{path}: " + ", ".join(parts)


def live_breaker_files(civ6ai_roots: Iterable[Path]) -> list[Path]:
    """Breaker files of live sessions: <root>/sessions/<session_id>/circuit_breaker.json."""
    found: list[Path] = []
    seen: set[str] = set()
    for root in civ6ai_roots:
        sessions = Path(root) / "sessions"
        if not sessions.is_dir():
            continue
        for path in sorted(sessions.glob("*/circuit_breaker.json")):
            key = str(path).lower()
            if key not in seen:
                seen.add(key)
                found.append(path)
    return found
