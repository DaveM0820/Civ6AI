"""Replay normalize/validate on civ4ai-autotest io_logs for debugging fallbacks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sidecar import pipeline_v2 as p


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"C:\Users\dmitc\OneDrive\Documents\My Games\beyond the sword\civ4ai-autotest\io_logs"
    )
    seed = sys.argv[2] if len(sys.argv) > 2 else "00233c84"
    max_turn = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    for raw_path in sorted(base.glob(f"ai_seed-{seed}*_raw_output.json")):
        stem = raw_path.stem.replace("_raw_output", "")
        inp = base / (stem + "_input.json")
        if not inp.exists():
            continue
        parts = stem.split("_turn_")
        if len(parts) != 2:
            continue
        turn = int(parts[1])
        if turn > max_turn:
            continue
        player = parts[0].split("_player_")[1]
        inp_data = json.loads(inp.read_text(encoding="utf-8"))
        raw_out = json.loads(raw_path.read_text(encoding="utf-8"))
        status = raw_out.get("status")
        raw_wire = raw_out.get("raw_model_response")
        snap = inp_data.get("snapshot") or inp_data
        unit_cmds = [
            c["command_id"]
            for c in snap.get("legal_commands", [])
            if c.get("kind") not in p.HOST_AUTOMATIC_KINDS
            and "unit" in str(c.get("kind", "")).lower()
            or c.get("command_id", "").startswith("CMD_move")
        ]
        if not isinstance(raw_wire, dict):
            print(f"P{player} t{turn}: {status} no wire")
            continue
        try:
            norm = p.normalize_model_response(snap, raw_wire)
            val = p.validate_model_response(snap, norm)
            cmds = val.get("commands", [])
            rej = [r.get("category") for r in val.get("rejections", [])]
            print(
                f"P{player} t{turn}: io={status} replay_cmds={len(cmds)} "
                f"cmd_ids={[c['command_id'] for c in cmds]} warnings={rej}"
            )
        except Exception as error:
            print(f"P{player} t{turn}: io={status} REPLAY_FAIL {error}")


if __name__ == "__main__":
    main()
