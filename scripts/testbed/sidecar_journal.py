"""Read Civ4AI sidecar journal files (JSONL append; one JSON object per line)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_last_journal_record(path: Path | str) -> dict[str, Any] | None:
    """Return the authoritative record: last approved line, else last valid line."""
    journal_path = Path(path)
    if not journal_path.is_file():
        return None
    last_any: dict[str, Any] | None = None
    last_approved: dict[str, Any] | None = None
    for raw in journal_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        last_any = record
        if record.get("status") == "approved":
            last_approved = record
    if last_approved is not None:
        return last_approved
    return last_any
