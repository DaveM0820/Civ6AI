"""Replay normalize/validate on Civ VI autotest io_logs for debugging fallbacks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sidecar import pipeline_v2 as pipeline


def replay_io_logs(io_dir: Path, max_turn: int | None = None) -> list[dict]:
    results: list[dict] = []
    for raw_path in sorted(io_dir.glob("*_raw_output.json")):
        stem = raw_path.stem.replace("_raw_output", "")
        inp = io_dir / (stem + "_input.json")
        if not inp.is_file():
            continue
        inp_data = json.loads(inp.read_text(encoding="utf-8-sig"))
        raw_out = json.loads(raw_path.read_text(encoding="utf-8-sig"))
        snap = inp_data.get("snapshot") or inp_data
        decision = inp_data.get("decision", {})
        turn = int(decision.get("turn", -1))
        if max_turn is not None and turn > max_turn:
            continue
        status = raw_out.get("status")
        raw_wire = raw_out.get("raw_model_response")
        row = {"turn": turn, "io_status": status, "replay_status": None, "commands": [], "error": None}
        if not isinstance(raw_wire, dict):
            row["error"] = "no raw_model_response"
            results.append(row)
            continue
        try:
            norm = pipeline.normalize_model_response(snap, raw_wire)
            val = pipeline.validate_model_response(snap, norm)
            cmds = val.get("commands", [])
            row["replay_status"] = "ok"
            row["commands"] = [c.get("command_id") for c in cmds if isinstance(c, dict)]
        except Exception as error:
            row["replay_status"] = "fail"
            row["error"] = str(error)
        results.append(row)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Civ VI io_log validation")
    parser.add_argument("io_dir", type=Path, help="PLAYER_N/io_logs directory")
    parser.add_argument("--max-turn", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = replay_io_logs(args.io_dir, args.max_turn)
    if args.json:
        print(json.dumps(results, indent=2))
        return
    for row in results:
        print(
            f"t{row['turn']}: io={row['io_status']} replay={row['replay_status']} "
            f"cmds={row['commands']} err={row['error']}"
        )


if __name__ == "__main__":
    main()
