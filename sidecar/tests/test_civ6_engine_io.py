"""Civ6 prompt inputs/outputs line up with what the Civ6 Lua can apply."""
import unittest

from sidecar import civ6_adapter, civ6_wire, pipeline_v2 as pipeline


def _legal(command_id, kind, fixed):
    return {
        "command_id": command_id,
        "kind": kind,
        "description": kind,
        "fixed_arguments": fixed,
        "parameter_domains": {},
        "affected_ids": [fixed.get("unit_id") or fixed.get("city_id") or command_id],
        "runtime_status": "implemented_untested",
    }


# Kinds Civ6Ai_Apply._ApplyCommand executes (anything else returns unsupported_kind).
APPLY_KINDS = {
    "set_research_tech", "set_research_civic", "move_unit", "queue_production",
    "unit_skip", "unit_posture_fortify", "found_city", "attack_target",
}


class Civ6EngineIoTests(unittest.TestCase):
    def _snapshot(self):
        snap = civ6_adapter.build_classical_golden_snapshot()
        unit_id = next(u["unit_id"] for u in snap["your_units"] if "SPEARMAN" in u["unit_type_id"])
        snap["legal_commands"].append(_legal(
            "CMD_attack_spear_17_22", "attack_target",
            {"unit_id": unit_id, "target_x": 17, "target_y": 22, "target_kind": "unit", "ranged": False},
        ))
        snap["legal_commands"].append(_legal(
            "CMD_civic_CIVIC_CRAFTSMANSHIP", "set_research_civic", {"civic_id": "CIVIC_CRAFTSMANSHIP"},
        ))
        return snap

    def test_attack_and_civic_rows_render_and_bind(self):
        snap = self._snapshot()
        wire = civ6_wire.build_civ6_model_wire_text(snap)
        self.assertIn("AttackTo(17,22)", wire)
        self.assertIn("CIVIC_CRAFTSMANSHIP", wire)
        response = {
            "commands.required.count": 4,
            "1.strategicmap.read": "x", "2.tacticalmap.read": "x",
            "3.thought.situation": "x", "4.thought.strategy": "y",
            "5.spearman_1.command": "AttackTo(17,22)",
            "6.legal.research.civic": "CIVIC_CRAFTSMANSHIP",
        }
        normalized = pipeline.normalize_model_response(snap, response)
        ids = {c["command_id"] for c in normalized["commands"]}
        self.assertIn("CMD_attack_spear_17_22", ids)
        self.assertIn("CMD_civic_CIVIC_CRAFTSMANSHIP", ids)

    def test_lua_legal_kinds_are_all_applied(self):
        """Every kind Civ6Ai_Snapshot offers must have a branch in Civ6Ai_Apply._ApplyCommand."""
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai" / "InGame"
        snapshot_lua = (root / "Civ6Ai_Snapshot.lua").read_text(encoding="utf-8")
        apply_lua = (root / "Civ6Ai_Apply.lua").read_text(encoding="utf-8")
        offered = set(re.findall(r'kind\s*=\s*"([a-z_]+)"', snapshot_lua))
        applied = set(re.findall(r'command\.kind\s*==\s*"([a-z_]+)"', apply_lua))
        self.assertTrue(offered)
        self.assertLessEqual(offered, applied)
        self.assertLessEqual(applied, APPLY_KINDS)
        for kind in ("attack_target", "set_research_civic", "move_unit", "queue_production"):
            self.assertIn(kind, offered)

    def test_remember_round_trip(self):
        snap = civ6_adapter.build_classical_golden_snapshot()
        normalized = pipeline.normalize_model_response(snap, {
            "1.thought.situation": "x", "2.thought.strategy": "y",
            "3.remember": "Cleopatra promised open borders (duration 5 turns)",
        })
        self.assertEqual(normalized["remember"], ["Cleopatra promised open borders (duration 5 turns)"])
        turn = int(snap["decision"]["turn"])
        memory = pipeline.append_remembered({}, turn, normalized["remember"])
        self.assertEqual(memory["remembered"][0]["expires_turn"], turn + 5)
        self.assertEqual(memory["remembered"][0]["text"], "Cleopatra promised open borders")
        pipeline.inject_thought_history(snap, memory)
        wire = civ6_wire.build_civ6_model_wire_text(snap)
        self.assertIn("Cleopatra promised open borders", wire)
        snap["decision"]["turn"] = turn + 6
        pipeline.inject_thought_history(snap, memory)
        self.assertEqual(snap["history"]["remembered"], [])

    def test_placeholders_are_not_prompted(self):
        snap = civ6_adapter.build_classical_golden_snapshot()
        snap["game"]["era_id"] = "ERA_UNKNOWN"
        snap["game"]["difficulty_id"] = "UNKNOWN"
        wire = civ6_wire.build_civ6_model_wire_text(snap)
        self.assertNotIn("ERA_UNKNOWN", wire)
        self.assertNotIn("difficulty = UNKNOWN", wire)

    def test_lua_shaped_fields_pass_input_schema(self):
        from sidecar import civ6_adapter as adapter
        snap = self._snapshot()
        unit = next(u for u in snap["your_units"] if "SPEARMAN" in u["unit_type_id"])
        unit["unit_class_id"] = "FORMATION_CLASS_LAND_COMBAT"
        unit["strength"] = {"current": 25, "maximum": 25, "change_per_turn": 0}
        snap["civ6"]["research_civic"] = {"civic_id": "CIVIC_CRAFTSMANSHIP", "progress": 3, "turns_left": 5}
        snap["game"]["era_id"] = "UNKNOWN"
        adapter.normalize_civ6_snapshot(snap)
        adapter.validate_civ6_snapshot(snap)
        wire = civ6_wire.build_civ6_model_wire_text(snap)
        self.assertIn("empire.research.civic = CIVIC_CRAFTSMANSHIP", wire)

    def test_civ6_system_instructions_do_not_contradict_json(self):
        snap = civ6_adapter.build_classical_golden_snapshot()
        self.assertEqual(pipeline._model_response_instructions(snap), "")


if __name__ == "__main__":
    unittest.main()
