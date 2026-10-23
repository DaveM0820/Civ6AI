"""Blessed offer-set command_ids from snapshot fixtures (PR2 safety net)."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from sidecar import civ6_adapter
from sidecar import civ6_apply_results
from sidecar import civ6_priorities
from sidecar import civ6_wire

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / "fixtures" / "civ6" / "offer-set"
CIV6_FIXTURES = ROOT / "fixtures" / "civ6"
MAP_FIXTURES = ROOT / "fixtures" / "map_snapshots"
SKIP_NAMES = {
    "ai_player_0_personality.json",
    "ai_player_1_personality.json",
    "ai_player_2_personality.json",
    "ai_player_3_personality.json",
    "ai_player_4_personality.json",
    "seat-experiment-sample.jsonl",
}


def offer_fixture_paths() -> list[Path]:
    paths: list[Path] = []
    for path in sorted(CIV6_FIXTURES.glob("*.json")):
        if path.name in SKIP_NAMES:
            continue
        paths.append(path)
    paths.extend(sorted(MAP_FIXTURES.glob("*.json")))
    return paths


def current_offer_ids(raw: dict) -> list[str]:
    """Same mutations the civ6 runner applies before the model sees the seat."""
    snap = copy.deepcopy(raw)
    if not isinstance(snap, dict):
        return []
    try:
        civ6_adapter.normalize_civ6_snapshot(snap)
        civ6_priorities.inject_legal_commands(snap)
        civ6_wire.prune_settlers_without_sites(snap)
        civ6_apply_results.suppress_failed_offers(snap)
    except Exception:
        pass
    ids: list[str] = []
    for command in snap.get("legal_commands") or []:
        if isinstance(command, dict) and command.get("command_id"):
            ids.append(str(command["command_id"]))
    return sorted(ids)


def golden_path(source: Path) -> Path:
    return GOLDEN_DIR / f"{source.stem}.command_ids.json"


class OfferSetGoldenTests(unittest.TestCase):
    def test_fixture_offer_sets_match_blessed_command_ids(self):
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        self.assertTrue(offer_fixture_paths())
        for source in offer_fixture_paths():
            raw = json.loads(source.read_text(encoding="utf-8"), strict=False)
            if not isinstance(raw, dict):
                continue
            ids = current_offer_ids(raw)
            blessed = golden_path(source)
            payload = json.dumps(ids, indent=2) + "\n"
            if not blessed.is_file():
                blessed.write_text(payload, encoding="utf-8")
            self.assertEqual(
                blessed.read_text(encoding="utf-8"),
                payload,
                msg=f"offer set drifted: {source.name}",
            )
