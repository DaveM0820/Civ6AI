"""WP-C: apply-result feedback, chat parse, settle facts, turn report."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sidecar import civ6_apply_results as results
from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_turn_report
from sidecar import civ6_wire
from sidecar import pipeline_v2 as pipeline
from sidecar import run_civ6


def _snap(**extra):
    base = {
        "schema_version": "civ6ai-input/1",
        "decision": {"turn": 37, "player_id": "PLAYER_1"},
        "your_units": [
            {"unit_id": "UNIT_WARRIOR_1", "unit_type_id": "UNIT_WARRIOR", "plot_id": "PLOT_6_10",
             "movement": {"current": 2, "maximum": 2}},
            {"unit_id": "UNIT_SETTLER_1", "unit_type_id": "UNIT_SETTLER", "plot_id": "PLOT_18_16",
             "settle": {
                 "here_ok": True,
                 "here_reason": "",
                 "coast": True,
                 "fresh_water": True,
                 "sites": [{"x": 18, "y": 16, "dist": 0}, {"x": 19, "y": 15, "dist": 1}],
             }},
        ],
        "your_cities": [],
        "your_empire": {"team_id": "TEAM_1"},
        "known_other_cities": [],
        "visible_other_units": [],
        "known_players": [
            {"player_id": "PLAYER_0", "leader_id": "LEADER_GILGAMESH", "leader_name": "Gilgamesh",
             "civilization_id": "CIVILIZATION_SUMERIA", "relation": {"met": True}},
        ],
        "legal_commands": [],
        "history": {"command_results": [], "public_events": [], "thought_memory": [], "remembered": []},
        "advciv": {"recommendations": []},
    }
    base.update(extra)
    return base


class ApplyResultFeedbackTests(unittest.TestCase):
    def test_snapshot_command_results_labelled_by_decision_turn(self):
        snap = _snap()
        snap["history"]["command_results"] = [{
            "decision_turn": 36,
            "apply_turn": 37,
            "unit": "UNIT_WARRIOR_1",
            "kind": "move_unit",
            "ok": True,
            "reason": "arrived",
            "effect": "moved",
            "x": 6,
            "y": 10,
        }]
        added = results.inject_command_results(snap, None)
        self.assertGreater(added, 0)
        blob = "\n".join(results.thoughts_lines(snap))
        self.assertIn("Your T36 orders", blob)
        self.assertIn("applied T37", blob)

    def test_already_there_is_no_effect(self):
        snap = _snap()
        items = results.build_command_results(snap, [{
            "kind": "move_unit",
            "ok": True,
            "reason": "already_there",
            "fixed_arguments": {"unit_id": "UNIT_WARRIOR_1", "target_x": 6, "target_y": 10},
        }], 36)
        self.assertEqual(items[0]["kind"], results.KIND_NO_EFFECT)
        self.assertIn("no effect", items[0]["summary"])

    def test_unresolved_token_recorded_as_dropped(self):
        snap = _snap()
        results.record_dropped(snap, ["dropped: unresolved token archer_1.command=MoveTo(1,1)"])
        blob = "\n".join(results.thoughts_lines(snap))
        self.assertIn("dropped:", blob)
        self.assertIn("archer_1", blob)


class RepeatFailureTests(unittest.TestCase):
    def test_repeat_no_path_is_dropped(self):
        snap = _snap()
        snap["history"]["command_results"] = [{
            "kind": results.KIND_FAILED,
            "turn": 36,
            "summary": "warrior_1 MoveTo(9,9): FAILED — the game found no route to that tile (water, mountains, or closed borders in the way)",
            "reason": "no_path",
            "order_kind": "move_unit",
            "unit": "warrior_1",
        }]
        commands = [{
            "kind": "move_unit",
            "command_id": "CMD_w",
            "arguments": {"unit_id": "UNIT_WARRIOR_1", "target_x": 9, "target_y": 9},
        }]
        kept, dropped = results.filter_repeat_failures(snap, commands)
        self.assertEqual(kept, [])
        self.assertTrue(dropped)
        self.assertIn("T36", dropped[0])
        self.assertIn("no_path", dropped[0])


class ChatRobustnessTests(unittest.TestCase):
    def test_chat_gilgamesh_resolves(self):
        snap = _snap()
        self.assertEqual(pipeline._resolve_chat_recipient("Gilgamesh", snap), "PLAYER_0")
        self.assertEqual(pipeline._resolve_chat_recipient("Sumeria", snap), "PLAYER_0")
        self.assertEqual(pipeline._resolve_chat_recipient("player.PLAYER_0", snap), "PLAYER_0")
        self.assertEqual(pipeline._resolve_chat_recipient("LeaderName.Gilgamesh", snap), "PLAYER_0")

    def test_chat_leadername_dot_key_expands(self):
        snap = _snap()
        nested = pipeline.expand_flat_response({"chat.LeaderName.Gilgamesh": "A private word."}, snap)
        chats = nested.get("chat_messages") or []
        self.assertEqual(chats[0]["target"], "player")
        full = {
            **snap,
            "legal_commands": [],
            "known_map": {"plots": []},
            "your_empire": {"team_id": "TEAM_1"},
            "known_other_cities": [],
            "visible_other_units": [],
            "personality": {"leader_id": "LEADER_TEST", "leader_name": "Test"},
            "game": {},
            "advciv": {"recommendations": []},
        }
        out = pipeline.normalize_model_response(full, {
            "thought": {"situation": "s", "strategy": "t"},
            "decision_summary": "ok",
            "commands": [],
            "chat_messages": chats,
            "recommendation_decisions": [],
        })
        self.assertEqual(out["chat_messages"][0]["target_player_id"], "PLAYER_0")

    def test_long_chat_survives_past_240(self):
        text = ("Hello rivals. " * 40).strip()
        self.assertGreater(len(text), 240)
        trimmed = pipeline.trim_chat_text(text)
        self.assertGreater(len(trimmed), 240)
        self.assertLessEqual(len(trimmed), pipeline.CHAT_TEXT_MAX_LENGTH)

    def test_near_duplicate_public_chat_is_dropped(self):
        snap = _snap(decision={"turn": 4, "player_id": "PLAYER_1"})
        snap["history"]["public_events"] = [
            {"turn": 1, "kind": "CHAT_PUBLIC", "text": "Greetings from the Sumerian shore, I am glad to meet you all.",
             "affected_ids": ["PLAYER_1"]},
            {"turn": 2, "kind": "CHAT_PUBLIC", "text": "Greetings from the Sumerian shore, I am glad to meet you all!",
             "affected_ids": ["PLAYER_1"]},
            {"turn": 3, "kind": "CHAT_PUBLIC", "text": "Greetings from the Sumerian shore, I am glad to meet you all.",
             "affected_ids": ["PLAYER_1"]},
        ]
        chats = [{"target": "all", "text": "Greetings from the Sumerian shore, I am glad to meet you all."}]
        kept, dropped = results.filter_repeat_public_chat(snap, chats)
        self.assertEqual(kept, [])
        self.assertTrue(any("near-repeat" in note for note in dropped))


class PromptBoundAndSettleTests(unittest.TestCase):
    def test_journal_window_skips_milestones_for_civ6(self):
        memory = {
            "thoughts": [{"turn": t, "situation": f"sit {t} " + ("x" * 80), "strategy": f"plan {t}"} for t in range(1, 40)],
            "remembered": [],
        }
        snap = _snap(decision={"turn": 40, "player_id": "PLAYER_1"})
        pipeline.inject_thought_history(snap, memory)
        turns = [int(e["turn"]) for e in snap["history"]["thought_memory"]]
        self.assertNotIn(10, turns)
        self.assertNotIn(20, turns)
        self.assertEqual(turns, [35, 36, 37, 38, 39])

    def test_thoughts_section_char_budget(self):
        snap = _snap()
        snap["history"]["thought_memory"] = [
            {"turn": t, "situation": "A" * 400, "strategy": "B" * 400} for t in range(30, 40)
        ]
        blob = "\n".join(civ6_wire._thoughts_section(snap))
        self.assertLessEqual(len(blob), pipeline.JOURNAL_WIRE_CHAR_BUDGET + 800)

    def test_remember_near_dupe_and_cap(self):
        memory = {}
        pipeline.append_remembered(memory, 18, ["Scout the eastern peninsula for settle sites."], max_notes=6, max_new=1, near_dupe=0.7)
        pipeline.append_remembered(memory, 19, ["Scout the eastern peninsula for settle sites soon."], max_notes=6, max_new=1, near_dupe=0.7)
        self.assertEqual(len(memory["remembered"]), 1)
        pipeline.append_remembered(memory, 20, ["note a", "note b"], max_notes=6, max_new=1, near_dupe=0.7)
        self.assertEqual(sum(1 for n in memory["remembered"] if n["turn"] == 20), 1)

    def test_settle_facts_and_capital_coaching(self):
        snap = _snap()
        lines = coaching.settler_fact_lines("settler_1", snap["your_units"][1], snap)
        blob = "\n".join(lines)
        self.assertIn("coast", blob)
        self.assertIn("fresh water", blob)
        self.assertIn("FoundCity legal here", blob)
        self.assertIn("(19,15)", blob)
        advice = "\n".join(civ6_wire._advice_section(snap))
        self.assertIn("found the capital", advice.lower())
        wire = civ6_wire.build_civ6_model_wire_text(snap)
        self.assertNotIn("chat.LeaderName", wire)
        self.assertIn("chat.Gilgamesh", wire)

    def test_parse_repair_retries_once(self):
        calls = []

        def retry(prompt: str) -> str:
            calls.append(prompt)
            return json.dumps({
                "thought": {"situation": "ok", "strategy": "move"},
                "decision_summary": "ok",
                "scout_1.command": "MoveTo(1,2)",
            })

        parsed, retried = pipeline.parse_model_text_with_repair("not json at all {{{", retry)
        self.assertTrue(retried)
        self.assertEqual(len(calls), 1)
        self.assertIn("not valid JSON", calls[0])
        self.assertTrue(pipeline.reply_has_game_orders(parsed))

    def test_utf8_emit_does_not_raise_on_cp1252(self):
        record = {"note": "approx ≈ value"}
        buf = io.BytesIO()
        fake = mock.Mock()
        fake.buffer = buf
        with mock.patch("sidecar.run_civ6.sys.stdout", fake):
            run_civ6.emit_json_line(record)
        self.assertIn(b"approx", buf.getvalue())

    def test_turn_report_written(self):
        snap = _snap()
        record = {"status": "approved", "validated": {"chat_messages": []}, "commands": [{"command_id": "CMD_1"}]}
        report = civ6_turn_report.build_turn_report(
            snapshot=snap, record=record, timings={"wall_ms": 12, "llm_ms": 8}, wire_text="abc", dropped=["x"],
        )
        self.assertEqual(report["turn"], 37)
        self.assertEqual(report["commands_given"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = civ6_turn_report.write_turn_report(Path(tmp), report)
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["timings"]["llm_ms"], 8)


if __name__ == "__main__":
    unittest.main()
