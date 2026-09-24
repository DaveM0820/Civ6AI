"""Aggregate live journal command kinds vs command-capabilities-v2 catalog."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES_PATH = REPO_ROOT / "config" / "command-capabilities-v2.json"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from sidecar_journal import read_last_journal_record
BRIDGE_GAP_KINDS = {
    "move_group",
    "attack_target",
    "pillage_or_bombard",
    "airlift_recon_paradrop",
    "air_strike_or_bomb",
    "nuclear_strike",
}


def load_capabilities() -> list[dict]:
    payload = json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))
    return payload.get("capabilities", [])


def load_journals(journal_dir: Path, since: datetime | None) -> list[tuple[Path, dict]]:
    rows: list[tuple[Path, dict]] = []
    for path in sorted(journal_dir.glob("ai_*_player_*_turn_*.json")):
        if since and path.stat().st_mtime < since.timestamp():
            continue
        record = read_last_journal_record(path)
        if record is None:
            continue
        rows.append((path, record))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-dir", type=Path, required=True)
    parser.add_argument("--since", type=str, default=None, help="ISO timestamp; only journals modified after")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    since = datetime.fromisoformat(args.since) if args.since else None
    capabilities = load_capabilities()
    catalog_kinds = {row["kind"] for row in capabilities}
    tested_kinds = {row["kind"] for row in capabilities if row.get("runtime") == "tested"}

    journals = load_journals(args.journal_dir, since)
    kind_counts: Counter[str] = Counter()
    kind_by_turn: dict[str, set[int]] = {}
    blockers: list[dict] = []
    approved_turns: set[int] = set()
    seats_seen: set[int] = set()

    for path, record in journals:
        status = record.get("status")
        private = record.get("private") if isinstance(record.get("private"), dict) else {}
        turn = private.get("turn")
        player_raw = private.get("player_id", "")
        player_num = None
        if isinstance(player_raw, str) and player_raw.startswith("PLAYER_"):
            try:
                player_num = int(player_raw.split("_", 1)[1])
            except ValueError:
                player_num = None
        if player_num is not None:
            seats_seen.add(player_num)
        if turn is not None:
            approved_turns.add(int(turn))

        if status in ("fallback", "timeout_orphan"):
            blockers.append({
                "file": str(path),
                "status": status,
                "turn": turn,
                "player_id": player_raw,
                "message": record.get("message", "")[:240],
                "category": record.get("category"),
            })
            continue
        if status != "approved":
            continue

        commands = record.get("commands") if isinstance(record.get("commands"), list) else []
        validated = record.get("validated") if isinstance(record.get("validated"), dict) else {}
        rejections = validated.get("rejections") if isinstance(validated.get("rejections"), list) else []
        if rejections:
            blockers.append({
                "file": str(path),
                "status": "validation_rejections",
                "turn": turn,
                "player_id": player_raw,
                "rejections": rejections,
            })

        for cmd in commands:
            if not isinstance(cmd, dict):
                continue
            kind = cmd.get("kind")
            if not kind:
                continue
            kind_counts[kind] += 1
            kind_by_turn.setdefault(kind, set()).add(int(turn) if turn is not None else -1)

    observed_kinds = set(kind_counts.keys())
    chat_observed = kind_counts.get("chat", 0) > 0 or any(
        isinstance((r.get("validated") or {}).get("chat_messages"), list)
        and len((r.get("validated") or {}).get("chat_messages")) > 0
        for _, r in journals
    )

    native_kinds = catalog_kinds - {"chat"}
    observed_native = observed_kinds - {"chat"}
    untested_catalog = sorted(native_kinds - tested_kinds)
    not_observed = sorted(native_kinds - observed_native)
    bridge_gaps = sorted(BRIDGE_GAP_KINDS)
    newly_observed = sorted(observed_native - tested_kinds)

    report = {
        "journal_dir": str(args.journal_dir),
        "since": args.since,
        "journal_count": len(journals),
        "approved_journals": sum(1 for _, r in journals if r.get("status") == "approved"),
        "fallback_journals": sum(1 for _, r in journals if r.get("status") == "fallback"),
        "timeout_orphan_journals": sum(1 for _, r in journals if r.get("status") == "timeout_orphan"),
        "turns_with_journals": sorted(approved_turns),
        "seats_seen": sorted(seats_seen),
        "command_kind_counts": dict(kind_counts),
        "catalog_native_kinds": len(native_kinds),
        "tested_in_catalog": len(tested_kinds),
        "observed_native_kinds": len(observed_native),
        "chat_observed": chat_observed,
        "coverage_pct": round(100.0 * len(observed_native) / max(len(native_kinds), 1), 1),
        "newly_observed_untested": newly_observed,
        "not_observed_in_run": not_observed,
        "untested_in_catalog": untested_catalog,
        "bridge_gap_kinds": bridge_gaps,
        "kind_turn_spread": {k: sorted(v) for k, v in sorted(kind_by_turn.items())},
        "blockers": blockers,
    }

    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)

    if report["timeout_orphan_journals"] or report["fallback_journals"]:
        sys.exit(2)
    if blockers:
        sys.exit(1)


if __name__ == "__main__":
    main()
