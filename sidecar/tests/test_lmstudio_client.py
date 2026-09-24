"""Mock-HTTP tests for LM Studio request building and client errors."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from sidecar import lmstudio_client
from sidecar import pipeline_v2 as pipeline
from sidecar.civ6_config import Civ6AiLocalConfig


class _FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _snapshot() -> dict:
    return {
        "schema_version": "civ6ai-input/1",
        "decision": {"turn": 1, "player_id": "PLAYER_0", "phase": "strategic_decision"},
        "legal_commands": [],
        "your_units": [],
        "your_cities": [],
        "personality": {"leader_name": "Pericles"},
        "game": {"map_width": 10, "map_height": 10, "network_multiplayer": False},
        "known_map": {"visibility_mode": "player_visible", "plots": []},
    }


class LmStudioClientTests(unittest.TestCase):
    def test_reasoning_fields_qwen_on_off_only(self):
        on = lmstudio_client.lmstudio_chat_reasoning_fields("qwen/qwen3-vl-8b", "on")
        self.assertEqual({"reasoning": "on"}, on)
        self.assertNotIn("reasoning_effort", on)
        off = lmstudio_client.lmstudio_chat_reasoning_fields("qwen/qwen3-vl-8b", "off")
        self.assertEqual({"reasoning": "off"}, off)
        # Never map "on" into reasoning_effort=
        bad = lmstudio_client.lmstudio_chat_reasoning_fields("qwen/qwen3-vl", "low")
        self.assertEqual({"reasoning": "on"}, bad)
        self.assertNotEqual("on", bad.get("reasoning_effort"))

    def test_build_body_splits_text_and_image(self):
        cfg = Civ6AiLocalConfig(vision=True, reasoning="on", model="qwen/qwen3-vl-8b")
        body = lmstudio_client.build_chat_completions_body(
            snapshot=_snapshot(),
            cfg=cfg,
            image_data_url="data:image/png;base64,AAAA",
            wire_text="hello wire",
            system_prompt="you are a leader",
        )
        self.assertEqual("qwen/qwen3-vl-8b", body["model"])
        self.assertEqual("on", body.get("reasoning"))
        self.assertNotIn("reasoning_effort", body)
        user = body["messages"][1]["content"]
        self.assertIsInstance(user, list)
        self.assertEqual("text", user[0]["type"])
        self.assertEqual("hello wire", user[0]["text"])
        self.assertEqual("image_url", user[1]["type"])
        self.assertIn("data:image/png", user[1]["image_url"]["url"])

    def test_build_body_vision_off_keeps_plain_string(self):
        cfg = Civ6AiLocalConfig(vision=False, model="qwen/qwen3-vl-8b")
        body = lmstudio_client.build_chat_completions_body(
            snapshot=_snapshot(),
            cfg=cfg,
            image_data_url="data:image/png;base64,AAAA",
            wire_text="hello",
            system_prompt="sys",
        )
        self.assertIsInstance(body["messages"][1]["content"], str)

    def test_call_lmstudio_chat_success(self):
        captured: dict = {}

        def opener(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            payload = {
                "id": "chatcmpl-1",
                "model": "qwen/qwen3-vl-8b",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "thought.situation = ok\nthought.strategy = expand\n",
                    }
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
            return _FakeResponse(json.dumps(payload))

        cfg = Civ6AiLocalConfig(
            endpoint="http://127.0.0.1:1234/v1",
            model="qwen/qwen3-vl-8b",
            timeout_seconds=600,
            vision=True,
            reasoning="on",
            queue_shared_model=False,
        )
        with mock.patch.object(pipeline, "build_model_wire_text", return_value="wire"):
            with mock.patch.object(pipeline, "_model_instructions", return_value="sys"):
                result, meta = lmstudio_client.call_lmstudio_chat(
                    _snapshot(),
                    cfg=cfg,
                    image_data_url="data:image/png;base64,AAAA",
                    opener=opener,
                )
        self.assertEqual("http://127.0.0.1:1234/v1/chat/completions", captured["url"])
        self.assertEqual(600, captured["timeout"])
        self.assertEqual("on", captured["body"].get("reasoning"))
        self.assertNotIn("reasoning_effort", captured["body"])
        self.assertEqual("lmstudio", meta["provider"])
        self.assertTrue(meta.get("vision_enabled"))
        self.assertEqual("ok", result.get("thought.situation"))
        self.assertEqual("expand", result.get("thought.strategy"))

    def test_model_unloaded_http_400(self):
        import urllib.error

        def opener(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=__import__("io").BytesIO(b'{"error":"Model unloaded"}'),
            )

        cfg = Civ6AiLocalConfig(queue_shared_model=False, timeout_seconds=30)
        with mock.patch.object(pipeline, "build_model_wire_text", return_value="wire"):
            with mock.patch.object(pipeline, "_model_instructions", return_value="sys"):
                with self.assertRaises(pipeline.BoundaryError) as ctx:
                    lmstudio_client.call_lmstudio_chat(_snapshot(), cfg=cfg, opener=opener)
        self.assertEqual("model_unloaded", ctx.exception.category)
        self.assertIn("no model loaded", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
