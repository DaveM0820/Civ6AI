"""Build priorities: legal command injection, prompt block, reply parsing, binding."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from sidecar import civ6_adapter, civ6_command_wire, civ6_economy, civ6_priorities as prio
from sidecar import pipeline_v2 as pipeline

ROOT = Path(__file__).resolve().parents[2]
MINIMAL = ROOT / "fixtures" / "civ6" / "snapshot-turn-runtime-minimal.json"


def _snapshot(levels=None, cities=None):
    raw = json.loads(MINIMAL.read_text(encoding="utf-8"))
    snap = civ6_adapter.upgrade_runtime_snapshot(raw)
    civ6_adapter.normalize_civ6_snapshot(snap)
    if cities is not None:
        base = (snap.get("your_cities") or [{}])[0]
        snap["your_cities"] = [dict(base, city_id=f"CITY_{n}", name=f"C{n}") for n in range(cities)]
    if levels is not None:
        snap.setdefault("civ6", {})["priorities"] = [{"id": i, "level": l} for i, l in levels.items()]
    return snap


class PrioritiesModelTests(unittest.TestCase):
    def test_not_injected_without_mod_support(self):
        snap = _snapshot()
        snap.get("civ6", {}).pop("priorities", None)
        self.assertEqual(0, prio.inject_legal_commands(snap))
        self.assertEqual([], prio.prompt_lines(snap))

    def test_inject_and_validate(self):
        snap = _snapshot({})
        added = prio.inject_legal_commands(snap)
        self.assertEqual(len(prio.CATEGORIES) * 4, added)
        civ6_adapter.validate_civ6_snapshot(snap)
        self.assertEqual(0, prio.inject_legal_commands(snap))

    def test_parse(self):
        war = prio.BY_KEY["war"]["id"]
        wanted, problems = prio.parse_reply("war:2, science_victory:all_in, bogus:1")
        self.assertEqual(2, wanted[war])
        self.assertEqual(3, wanted[prio.BY_KEY["science_victory"]["id"]])
        self.assertIn("unknown_priority:bogus", problems)
        self.assertEqual(({}, []), prio.parse_reply("none"))
        self.assertEqual((None, []), prio.parse_reply("keep"))
        wanted, problems = prio.parse_reply("war:1, peace:1")
        self.assertEqual([war], list(wanted))
        self.assertIn("too_many_postures", problems)

    def test_plan_offs_first(self):
        war, peace = prio.BY_KEY["war"]["id"], prio.BY_KEY["peace"]["id"]
        sci = prio.BY_KEY["science_victory"]["id"]
        plan = prio.plan_commands({peace: 1, sci: 2}, {war: 2, sci: 2})
        self.assertEqual([prio.command_id(peace, 0), prio.command_id(war, 2)], plan)

    def test_wire_binds_to_legal_commands(self):
        peace, war = prio.BY_KEY["peace"]["id"], prio.BY_KEY["war"]["id"]
        snap = _snapshot({peace: 1}, cities=3)
        prio.inject_legal_commands(snap)
        lines = "\n".join(prio.prompt_lines(snap))
        self.assertIn("Current: custom (peace:1)", lines)
        wire = civ6_command_wire.expand_civ6_command_wire(copy.deepcopy(snap), {"7.priorities": "war:2"})
        ids = [v for k, v in sorted(wire.items()) if k.startswith("cmd.")]
        self.assertIn(prio.command_id(peace, 0), ids)
        self.assertIn(prio.command_id(war, 2), ids)
        self.assertLess(ids.index(prio.command_id(peace, 0)), ids.index(prio.command_id(war, 2)))
        resp = pipeline.normalize_model_response(snap, {"decision_summary": "shift to war", "7.priorities": "war:2"})
        validated = pipeline.validate_model_response(snap, resp)
        ok = [c["command_id"] for c in validated["commands"]]
        self.assertIn(prio.command_id(war, 2), ok)

    def test_early_lock_hides_presets_ignores_reply_and_sets_early_levels(self):
        peace, war = prio.BY_KEY["peace"]["id"], prio.BY_KEY["war"]["id"]
        snap = _snapshot({war: 2}, cities=2)
        prio.inject_legal_commands(snap)
        lines = "\n".join(prio.prompt_lines(snap))
        self.assertIn("Fixed until you own 3 cities", lines)
        self.assertNotIn("EXPANSION PACE", lines)
        self.assertNotIn("Available presets", lines)
        wire = civ6_command_wire.expand_civ6_command_wire(copy.deepcopy(snap), {"7.priorities": "war:3"})
        self.assertFalse([v for k, v in wire.items() if k.startswith("cmd.") and "PRIO" in str(v)])
        ids = [p["command_id"] for p in prio.early_lock_packets(snap)]
        self.assertEqual(ids[0], prio.command_id(war, 0))
        self.assertIn(prio.command_id(prio.BY_KEY["expansion"]["id"], 3), ids)
        self.assertIn(prio.command_id(peace, 1), ids)
        self.assertEqual([], prio.early_lock_packets(_snapshot({war: 2}, cities=3)))

    def test_pace_scales_with_speed(self):
        self.assertEqual(25, prio.pace_turn(25, "GAMESPEED_ONLINE"))
        self.assertEqual(50, prio.pace_turn(25, "GAMESPEED_STANDARD"))

    def test_presets_are_era_gated_and_expand_to_priorities(self):
        snap = _snapshot({}, cities=3)
        ancient = "\n".join(prio.prompt_lines(snap))
        self.assertIn("- expansion:", ancient)
        self.assertNotIn("- wonder_push:", ancient)
        self.assertNotIn("- science:", ancient)
        snap["your_empire"] = {"research": {"known_tech_ids": ["TECH_WRITING"]}}
        self.assertIn("- science:", "\n".join(prio.prompt_lines(snap)))
        snap["game"] = dict(snap.get("game") or {}, era_id="ERA_CLASSICAL")
        self.assertIn("- wonder_push:", "\n".join(prio.prompt_lines(snap)))
        wanted, problems = prio.parse_reply("expansion")
        self.assertEqual([], problems)
        self.assertEqual(3, wanted[prio.BY_KEY["expansion"]["id"]])
        self.assertEqual("expansion", prio.matching_preset(wanted))
        for preset in prio.PRESETS:
            levels, problems = prio.parse_reply(preset["set"])
            self.assertEqual([], problems, preset["key"])
            self.assertTrue(levels, preset["key"])

    def test_prompt_says_priorities_steer_production_when_queue_is_absent(self):
        from sidecar import civ6_wire
        snap = _snapshot({})
        self.assertEqual(civ6_wire.CIV6_PRIORITY_PRODUCTION_POLICY, civ6_wire.native_fallback_policy(snap))
        snap["legal_commands"] = [{
            "kind": "queue_production",
            "fixed_arguments": {"city_id": "CITY_0", "build_id": "UNIT_WARRIOR"},
        }]
        self.assertEqual(civ6_wire.CIV6_NATIVE_FALLBACK_POLICY, civ6_wire.native_fallback_policy(snap))

    def test_human_seat_is_not_told_to_order_production(self):
        from sidecar import civ6_wire
        snap = _snapshot()
        snap.get("civ6", {}).pop("priorities", None)
        snap["legal_commands"] = [
            c for c in snap.get("legal_commands") or []
            if not (isinstance(c, dict) and c.get("kind") == "queue_production")
        ]
        self.assertEqual(civ6_wire.CIV6_HUMAN_SEAT_POLICY, civ6_wire.native_fallback_policy(snap))
        text = civ6_wire.build_civ6_response_instructions(snap)
        self.assertNotIn("cityName.production =", text)
        self.assertNotIn("leave cityName.production", text)
        notes = civ6_economy.attention_items({
            "your_cities": [{"city_id": "CITY_1", "name": "Utrecht", "production": {"item_id": "NONE"}}],
        })
        self.assertIn("This seat does not take production orders", notes[0])
        self.assertIn("Nothing will be queued for you", notes[0])


if __name__ == "__main__":
    unittest.main()
