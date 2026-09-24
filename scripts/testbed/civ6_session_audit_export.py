"""Export Civ6 session prompts, map images, and settlement-strategy analysis for human review."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "testbed"))
from civ6_player_timeline import build_player_timeline


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _wire_for_turn(player_dir: Path, turn: int) -> str:
    io_dir = player_dir / "io_logs"
    if not io_dir.is_dir():
        return ""
    turn_pattern = re.compile(rf"^turn = {turn}\s*$", re.MULTILINE)
    for path in sorted(io_dir.glob("*_wire.txt")):
        text = path.read_text(encoding="utf-8-sig")
        if turn_pattern.search(text):
            return text
    for path in sorted(io_dir.glob(f"*_turn_{turn:05d}_wire.txt")):
        if path.is_file():
            return path.read_text(encoding="utf-8-sig")
    paths = sorted(io_dir.glob("*_wire.txt"))
    if paths:
        return paths[-1].read_text(encoding="utf-8-sig")
    return ""


def _settlement_signals(timeline_row: dict[str, Any]) -> dict[str, Any]:
    thought = {
        "situation": timeline_row.get("thought_situation"),
        "strategy": timeline_row.get("thought_strategy"),
    }
    intended = timeline_row.get("intended_commands", [])
    found_cmds = []
    settler_moves = []
    for cmd in intended if isinstance(intended, list) else []:
        if not isinstance(cmd, dict):
            continue
        kind = str(cmd.get("kind", ""))
        fixed = cmd.get("fixed_arguments", {})
        if not isinstance(fixed, dict):
            fixed = {}
        if kind == "found_city":
            found_cmds.append(cmd)
        if kind == "move_unit" and "SETTLER" in str(fixed.get("unit_id", "")).upper():
            settler_moves.append(cmd)
    executed = timeline_row.get("executed_commands", [])
    applied_found = [
        row for row in executed
        if isinstance(row, dict) and row.get("kind") == "found_city" and row.get("ok")
    ]
    input_empire = timeline_row.get("empire")
    cities = None
    known_plots = None
    alerts: list[str] = []
    player_dir_name = timeline_row.get("player_id", "")
    return {
        "thought": thought,
        "found_city_intended": found_cmds,
        "settler_moves_intended": settler_moves,
        "found_city_applied": applied_found,
        "empire_snapshot": input_empire,
        "map_image": timeline_row.get("map_image_path"),
        "status": timeline_row.get("status"),
        "alerts_from_wire": alerts,
        "player_id": player_dir_name,
        "turn": timeline_row.get("turn"),
    }


def export_session_audit(session_dir: Path, output_dir: Path) -> dict[str, Any]:
    session_id = session_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    maps_dir = output_dir / "map_images"
    prompts_dir = output_dir / "prompts"
    maps_dir.mkdir(exist_ok=True)
    prompts_dir.mkdir(exist_ok=True)

    report: dict[str, Any] = {
        "session_id": session_id,
        "session_dir": str(session_dir),
        "players": {},
        "settlement_analysis": [],
    }

    for player_dir in sorted(session_dir.iterdir()):
        if not player_dir.is_dir() or not player_dir.name.startswith("PLAYER_"):
            continue
        player_id = player_dir.name
        timeline = build_player_timeline(player_dir)
        player_report: dict[str, Any] = {"turns": len(timeline), "timeline": []}

        for row in timeline:
            turn = int(row.get("turn", 0))
            wire = _wire_for_turn(player_dir, turn)
            wire_path = prompts_dir / f"{player_id}_turn_{turn:03d}_wire.txt"
            wire_path.write_text(wire, encoding="utf-8")

            map_src = row.get("map_image_path")
            map_dest = None
            if isinstance(map_src, str) and map_src:
                src = Path(map_src)
                if src.is_file():
                    map_dest = maps_dir / f"{player_id}_turn_{turn:03d}.png"
                    shutil.copy2(src, map_dest)

            io_dir = player_dir / "io_logs"
            input_copy = None
            for inp in sorted(io_dir.glob("*_input.json")) if io_dir.is_dir() else []:
                payload = _load_json(inp)
                decision = payload.get("decision", {})
                if int(decision.get("turn", -1)) == turn:
                    input_copy = prompts_dir / f"{player_id}_turn_{turn:03d}_input.json"
                    input_copy.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                    break

            settlement = _settlement_signals(row)
            settlement["wire_path"] = str(wire_path)
            settlement["map_export_path"] = str(map_dest) if map_dest else None
            settlement["input_json_path"] = str(input_copy) if input_copy else None
            if wire:
                for line in wire.splitlines():
                    if line.startswith("alert."):
                        settlement.setdefault("alerts_from_wire", []).append(line.strip())
            report["settlement_analysis"].append(settlement)

            player_report["timeline"].append({
                "turn": turn,
                "status": row.get("status"),
                "thought_situation": row.get("thought_situation"),
                "thought_strategy": row.get("thought_strategy"),
                "wire_path": str(wire_path),
                "map_path": str(map_dest) if map_dest else None,
            })

        report["players"][player_id] = player_report

    archive_maps = session_dir.parent / "map_images" / session_id
    if archive_maps.is_dir():
        archive_dest = output_dir / "map_images_archive"
        if archive_dest.exists():
            shutil.rmtree(archive_dest)
        shutil.copytree(archive_maps, archive_dest)

    report_path = output_dir / "audit_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_lines = [
        f"# Civ6 session audit — {session_id}",
        "",
        "## Settlement strategy (first city / settler turns)",
        "",
    ]
    for item in report["settlement_analysis"]:
        thought = item.get("thought", {}) if isinstance(item.get("thought"), dict) else {}
        thought_strategy = thought.get("strategy") or item.get("thought_strategy")
        if not (
            item.get("found_city_intended")
            or item.get("settler_moves_intended")
            or item.get("found_city_applied")
            or (thought_strategy and "settle" in str(thought_strategy).lower())
        ):
            continue
        md_lines.append(f"### {item['player_id']} turn {item['turn']}")
        situation = thought.get("situation") or item.get("thought_situation")
        if situation:
            md_lines.append(f"- **Situation:** {situation}")
        if thought_strategy:
            md_lines.append(f"- **Strategy:** {thought_strategy}")
        if item.get("alerts_from_wire"):
            md_lines.append("- **Alerts:** " + "; ".join(item["alerts_from_wire"][:5]))
        if item.get("found_city_intended"):
            md_lines.append(f"- **Intended found_city:** {json.dumps(item['found_city_intended'])}")
        if item.get("settler_moves_intended"):
            md_lines.append(f"- **Settler moves:** {len(item['settler_moves_intended'])} options")
        if item.get("found_city_applied"):
            md_lines.append(f"- **Applied found_city:** {json.dumps(item['found_city_applied'])}")
        if item.get("map_export_path"):
            md_lines.append(f"- **Map:** `{item['map_export_path']}`")
        md_lines.append("")

    (output_dir / "settlement_analysis.md").write_text("\n".join(md_lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Civ6 session audit bundle")
    parser.add_argument("session_dir", type=Path, help="sessions/{session_id}")
    parser.add_argument("--output", type=Path, required=True, help="Output directory under artifacts/")
    args = parser.parse_args()
    report = export_session_audit(args.session_dir, args.output)
    print(f"Exported audit for {report['session_id']} -> {args.output}")
    print(f"  players: {list(report['players'].keys())}")
    print(f"  settlement rows: {len(report['settlement_analysis'])}")


if __name__ == "__main__":
    main()
