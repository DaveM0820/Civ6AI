"""Tests for Civ6Ai local config loading (LM Studio defaults + env)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sidecar import civ6_config


class Civ6ConfigTests(unittest.TestCase):
    def test_example_config_loads(self):
        cfg = civ6_config.load_local_config(civ6_config.EXAMPLE_CONFIG, apply_env=False)
        self.assertEqual("lmstudio", cfg.provider)
        self.assertTrue(cfg.endpoint.startswith("http"))
        self.assertGreaterEqual(cfg.timeout_seconds, 600)
        self.assertTrue(cfg.vision)
        self.assertIn(cfg.reasoning, {"on", "off"})
        self.assertEqual(240000, cfg.max_prompt_chars)

    def test_normalize_reasoning_never_on_as_effort(self):
        self.assertEqual("on", civ6_config.normalize_reasoning("on"))
        self.assertEqual("on", civ6_config.normalize_reasoning("low"))
        self.assertEqual("on", civ6_config.normalize_reasoning("xhigh"))
        self.assertEqual("off", civ6_config.normalize_reasoning("off"))
        self.assertEqual("off", civ6_config.normalize_reasoning("none"))

    def test_env_overrides(self):
        with mock.patch.dict(
            os.environ,
            {
                "CIV6AI_MODEL_PROVIDER": "lmstudio",
                "LMSTUDIO_BASE_URL": "http://127.0.0.1:9999/v1",
                "LMSTUDIO_MODEL": "qwen/test-vl",
                "CIV6AI_LMSTUDIO_TIMEOUT_SECONDS": "120",
                "CIV6AI_LMSTUDIO_VISION": "0",
                "CIV6AI_LMSTUDIO_REASONING": "off",
            },
            clear=False,
        ):
            cfg = civ6_config.load_local_config()
        self.assertEqual("http://127.0.0.1:9999/v1", cfg.endpoint)
        self.assertEqual("qwen/test-vl", cfg.model)
        self.assertEqual(120, cfg.timeout_seconds)
        self.assertFalse(cfg.vision)
        self.assertEqual("off", cfg.reasoning)

    def test_local_json_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "civ6ai.local.json"
            path.write_text(
                json.dumps({
                    "provider": "lmstudio",
                    "endpoint": "http://localhost:5555/v1",
                    "model": "local-model",
                    "timeout_seconds": 90,
                    "vision": True,
                    "reasoning": "off",
                }),
                encoding="utf-8",
            )
            cfg = civ6_config.load_local_config(path, apply_env=False)
            self.assertEqual("http://localhost:5555/v1", cfg.endpoint)
            self.assertEqual("local-model", cfg.model)
            self.assertEqual(90, cfg.timeout_seconds)
            self.assertEqual("off", cfg.reasoning)

    def test_apply_config_sets_env_without_reasoning_effort_on(self):
        cfg = civ6_config.Civ6AiLocalConfig(reasoning="on", vision=True)
        with mock.patch.dict(os.environ, {}, clear=False):
            civ6_config.apply_config_to_environ(cfg)
            self.assertEqual("on", os.environ.get("CIV6AI_LMSTUDIO_REASONING_EFFORT"))
            self.assertNotEqual("on", os.environ.get("CIV4AI_OPENAI_REASONING_EFFORT", "low"))
            self.assertEqual("low", os.environ.get("CIV4AI_OPENAI_REASONING_EFFORT"))
            self.assertEqual("1", os.environ.get("CIV6AI_LMSTUDIO_VISION"))

    def test_seat_model_and_effort_precedence(self):
        self.assertEqual("off", civ6_config.normalize_reasoning_effort("off"))
        self.assertEqual("low", civ6_config.normalize_reasoning_effort("on"))
        self.assertEqual("xhigh", civ6_config.normalize_reasoning_effort("xhigh"))
        self.assertNotEqual("on", civ6_config.normalize_reasoning_effort("on"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "civ6ai.local.json"
            path.write_text(json.dumps({
                "provider": "lmstudio",
                "model": "base-model",
                "reasoning": "off",
                "reasoning_effort": "medium",
                "seat_models": {
                    "1": {"model": "seat-one", "reasoning_effort": "high"},
                    "PLAYER_3": {"model": "seat-three", "reasoning_effort": "low"},
                },
            }), encoding="utf-8")
            cfg = civ6_config.load_local_config(path, apply_env=False)
        self.assertEqual("medium", cfg.reasoning_effort)
        self.assertEqual("on", cfg.reasoning)
        self.assertEqual(("base-model", "medium"), civ6_config.resolve_seat_runtime(cfg, "PLAYER_0"))
        self.assertEqual(("seat-one", "high"), civ6_config.resolve_seat_runtime(cfg, "PLAYER_1"))
        self.assertEqual(("seat-three", "low"), civ6_config.resolve_seat_runtime(cfg, 3))
        with mock.patch.dict(os.environ, {
            "CIV6AI_MODEL_PLAYER_1": "from-env",
            "CIV6AI_REASONING_EFFORT_PLAYER_1": "xhigh",
            "CIV6AI_REASONING_EFFORT": "low",
        }, clear=False):
            loaded = civ6_config.load_local_config(path, apply_env=True)
            self.assertEqual("low", loaded.reasoning_effort)
            self.assertEqual(("from-env", "xhigh"), civ6_config.resolve_seat_runtime(loaded, "PLAYER_1"))
        cfg_hi = civ6_config.Civ6AiLocalConfig(reasoning="on", reasoning_effort="xhigh")
        with mock.patch.dict(os.environ, {}, clear=False):
            civ6_config.apply_config_to_environ(cfg_hi)
            self.assertEqual("xhigh", os.environ.get("CIV6AI_REASONING_EFFORT"))
            self.assertEqual("high", os.environ.get("CIV4AI_OPENAI_REASONING_EFFORT"))
            self.assertNotEqual("on", os.environ.get("CIV4AI_OPENAI_REASONING_EFFORT"))

    def test_seat_prompt_budget_precedence(self):
        cfg = civ6_config.Civ6AiLocalConfig(
            max_prompt_chars=240000,
            seat_models={"1": {"max_prompt_chars": 24000}, "PLAYER_3": {"max_prompt_chars": 0}},
        )
        self.assertEqual(240000, civ6_config.resolve_seat_prompt_chars(cfg, "PLAYER_0"))
        self.assertEqual(24000, civ6_config.resolve_seat_prompt_chars(cfg, "PLAYER_1"))
        self.assertEqual(0, civ6_config.resolve_seat_prompt_chars(cfg, 3))
        applied = civ6_config.apply_seat_runtime(cfg, {"decision": {"player_id": "PLAYER_1"}})
        self.assertEqual(24000, applied.max_prompt_chars)
        self.assertEqual(cfg.model, applied.model)
        with mock.patch.dict(os.environ, {"CIV6AI_MAX_PROMPT_CHARS_PLAYER_1": "18000"}, clear=False):
            self.assertEqual(18000, civ6_config.resolve_seat_prompt_chars(cfg, "PLAYER_1"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "civ6ai.local.json"
            path.write_text(json.dumps({"max_prompt_chars": 26000}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"CIV6AI_MAX_PROMPT_CHARS": "21000"}, clear=False):
                loaded = civ6_config.load_local_config(path, apply_env=True)
            self.assertEqual(21000, loaded.max_prompt_chars)


if __name__ == "__main__":
    unittest.main()
