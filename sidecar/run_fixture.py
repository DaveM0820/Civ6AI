"""Backward-compatible CLI entry point for offline sidecar runs.

The v2 implementation lives in sidecar.run_v2. This module keeps the historical
``python sidecar/run_fixture.py`` command working for README and harness scripts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sidecar import pipeline_v2 as pipeline
from sidecar.run_v2 import main as run_v2_main


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "fixtures" / "map_snapshots" / "p0_t2.json"
DEFAULT_JOURNAL = ROOT / "artifacts" / "ai-result-journal.json"
DEFAULT_PERSONALITY = ROOT / "fixtures" / "ai_player_0000_personality.json"


def _replay_v2_journal(path: Path) -> dict:
    record = None
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                record = pipeline.parse_exact_json(line)
    if not isinstance(record, dict):
        raise pipeline.BoundaryError("replay", "Journal is empty or invalid")
    return {
        "status": "REPLAY_PASS",
        "journal": str(path),
        "record_status": record.get("status"),
        "snapshot_hash": record.get("snapshot_hash"),
        "commands": record.get("commands", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Civ4AI sidecar (v2 compatibility shim)")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--personality", type=Path, default=DEFAULT_PERSONALITY)
    parser.add_argument("--previous-journal", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--replay", type=Path)
    args, remainder = parser.parse_known_args()

    if args.replay is not None:
        print(json.dumps(_replay_v2_journal(args.replay), ensure_ascii=False, indent=2, sort_keys=True))
        return

    argv = ["run_v2"]
    if args.stdio:
        argv.append("--stdio")
    else:
        argv.extend(["--state", str(args.state)])
    argv.extend(["--journal", str(args.journal)])
    if args.personality:
        argv.extend(["--personality", str(args.personality)])
    if args.previous_journal:
        argv.extend(["--previous-journal", str(args.previous_journal)])
    if args.live:
        argv.append("--live")
    argv.extend(remainder)

    old_argv = sys.argv
    try:
        sys.argv = argv
        run_v2_main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    main()
