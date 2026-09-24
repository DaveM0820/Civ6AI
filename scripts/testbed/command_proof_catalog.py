"""Harvest in-game legal command catalogs and build state-aware proof plans."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES_PATH = ROOT / "config" / "command-capabilities-v2.json"
SAVES_PATH = ROOT / "config" / "command-proof-saves.json"
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

# Prefer stable proof targets over movement routes when multiple legal rows exist.
_KIND_PICK_PATTERNS: dict[str, list[str]] = {
    "unit_posture_mission": ["MISSION_SLEEP", "MISSION_FORTIFY", "MISSION_SENTRY", "MISSION_SKIP"],
    "found_city": ["MISSION_FOUND"],
    "worker_build": ["MISSION_BUILD"],
    "choose_research": ["TECH_FEUDALISM", "TECH_BANKING"],
    "change_commerce": ["COMMERCE_RESEARCH_PERCENT_100", "COMMERCE_GOLD_PERCENT_0"],
    "propose_deal": ["PROPOSAL_OPEN_BORDERS", "PROPOSAL_DEFENSIVE_PACT", "PROPOSAL_PEACE"],
    "respond_to_deal": ["DIPLO_ACCEPT", "DIPLO_REJECT"],
    "counteroffer": ["COUNTER_"],
    "cancel_deal": ["DEAL_"],
}


def _pick_command_row(kind: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    patterns = _KIND_PICK_PATTERNS.get(kind, [])
    for pattern in patterns:
        for row in rows:
            if pattern in row.get("command_id", ""):
                return row
    return rows[0]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("expected object in " + str(path))
    return value


def _latest_journal(journal_dir: Path) -> Path | None:
    candidates = sorted(journal_dir.glob("ai_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def harvest_from_journal(journal_path: Path, save_path: str | None = None) -> dict[str, Any]:
    record = read_last_journal_record(journal_path)
    if record is None:
        raise ValueError("empty journal in " + str(journal_path))
    private = record.get("private", {})
    legal = private.get("legal_commands", {})
    if not isinstance(legal, dict):
        legal = {}
    kinds: dict[str, list[dict[str, Any]]] = {}
    for command_id, row in legal.items():
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        if not isinstance(kind, str):
            continue
        kinds.setdefault(kind, []).append(
            {
                "command_id": command_id,
                "runtime_status": row.get("runtime_status"),
                "fixed_arguments": row.get("fixed_arguments", {}),
                "affected_ids": row.get("affected_ids", []),
            }
        )
    kind_counts = {kind: len(rows) for kind, rows in kinds.items()}
    return {
        "harvested_at": datetime.now(timezone.utc).isoformat(),
        "source_journal": str(journal_path),
        "game_uuid": private.get("game_uuid", record.get("private", {}).get("game_uuid")),
        "turn": private.get("turn"),
        "player_id": private.get("player_id"),
        "save_path": save_path,
        "total_commands": sum(kind_counts.values()),
        "kind_counts": kind_counts,
        "kinds": kinds,
    }


def harvest_journal_dir(journal_dir: Path, save_path: str | None = None) -> dict[str, Any]:
    journal_path = _latest_journal(journal_dir)
    if journal_path is None:
        raise FileNotFoundError("no ai_*.json journal in " + str(journal_dir))
    return harvest_from_journal(journal_path, save_path)


def _requirement_for_kind(saves_config: dict[str, Any], kind: str) -> dict[str, Any] | None:
    requirements = saves_config.get("kind_requirements", {})
    row = requirements.get(kind)
    if isinstance(row, dict):
        return row
    return None


def build_plan(
    catalog: dict[str, Any],
    capabilities_path: Path = CAPABILITIES_PATH,
    saves_path: Path = SAVES_PATH,
    target_kinds: list[str] | None = None,
) -> dict[str, Any]:
    capabilities = _load_json(capabilities_path)
    saves_config = _load_json(saves_path)
    bridge_gap = set(saves_config.get("bridge_gap_kinds", [])) | BRIDGE_GAP_KINDS
    all_kinds = [row["kind"] for row in capabilities.get("capabilities", []) if isinstance(row, dict) and row.get("kind")]
    if target_kinds:
        wanted = [kind for kind in target_kinds if kind in all_kinds]
    else:
        wanted = [kind for kind in all_kinds if kind != "chat"]
    legal_kinds = set(catalog.get("kinds", {}).keys())
    applicable: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for kind in wanted:
        if kind in bridge_gap:
            skipped.append(
                {
                    "kind": kind,
                    "status": "bridge_gap",
                    "reason": "No native v2_to_legacy bridge yet",
                }
            )
            continue
        if kind not in legal_kinds:
            requirement = _requirement_for_kind(saves_config, kind)
            skipped.append(
                {
                    "kind": kind,
                    "status": "not_legal_in_save",
                    "reason": "Command kind not in harvested legal catalog for this save state",
                    "required_save": requirement.get("save_slug") if requirement else None,
                    "requires": requirement.get("requires") if requirement else None,
                }
            )
            continue
        rows = catalog["kinds"].get(kind, [])
        if not rows:
            skipped.append({"kind": kind, "status": "empty_catalog", "reason": "Kind key present but no command rows"})
            continue
        pick = _pick_command_row(kind, rows)
        applicable.append(
            {
                "kind": kind,
                "command_id": pick["command_id"],
                "status": "applicable",
                "reason": "Legal in harvested catalog",
                "alternatives": [row["command_id"] for row in rows[1:6]],
            }
        )
    return {
        "catalog_source": catalog.get("source_journal"),
        "game_uuid": catalog.get("game_uuid"),
        "turn": catalog.get("turn"),
        "save_path": catalog.get("save_path"),
        "legal_kind_count": len(legal_kinds),
        "wanted_kind_count": len(wanted),
        "applicable": applicable,
        "skipped": skipped,
        "applicable_count": len(applicable),
        "skipped_count": len(skipped),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Civ4 AI command proof catalog utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    harvest_parser = sub.add_parser("harvest", help="Harvest legal catalog from a journal or journal dir")
    harvest_parser.add_argument("--journal", type=Path)
    harvest_parser.add_argument("--journal-dir", type=Path)
    harvest_parser.add_argument("--save-path")
    harvest_parser.add_argument("--out", type=Path, required=True)

    plan_parser = sub.add_parser("plan", help="Build applicable/skipped proof plan from a catalog")
    plan_parser.add_argument("--catalog", type=Path, required=True)
    plan_parser.add_argument("--out", type=Path)
    plan_parser.add_argument("--kinds", nargs="*", help="Optional subset of kinds to plan")

    args = parser.parse_args()
    if args.command == "harvest":
        if args.journal:
            catalog = harvest_from_journal(args.journal, args.save_path)
        elif args.journal_dir:
            catalog = harvest_journal_dir(args.journal_dir, args.save_path)
        else:
            print("harvest requires --journal or --journal-dir", file=sys.stderr)
            sys.exit(2)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"catalog": str(args.out), "legal_kind_count": len(catalog.get("kinds", {})), "total_commands": catalog.get("total_commands")}, indent=2))
        return
    if args.command == "plan":
        catalog = _load_json(args.catalog)
        plan = build_plan(catalog, target_kinds=args.kinds or None)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(plan, indent=2))
        return


if __name__ == "__main__":
    main()
