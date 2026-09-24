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
        cfg = civ6_config.load_local_config(apply_env=False)
        self.assertEqual("lmstudio", cfg.provider)
        self.assertTrue(cfg.endpoint.startswith("http"))
        self.assertGreaterEqual(cfg.timeout_seconds, 600)
        self.assertTrue(cfg.vision)
        self.assertIn(cfg.reasoning, {"on", "off"})

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
                "CIV6AI_MP_MOVE_SYNC": "1",
            },
            clear=False,
        ):
            cfg = civ6_config.load_local_config()
        self.assertEqual("http://127.0.0.1:9999/v1", cfg.endpoint)
        self.assertEqual("qwen/test-vl", cfg.model)
        self.assertEqual(120, cfg.timeout_seconds)
        self.assertFalse(cfg.vision)
        self.assertEqual("off", cfg.reasoning)
        self.assertTrue(cfg.mp_move_sync)

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
            with mock.patch.dict(os.environ, {}, clear=False):
                # Clear relevant env so file wins
                for key in list(os.environ):
                    if "LMSTUDIO" in key or key.startswith("CIV6AI_"):
                        os.environ.pop(key, None)
                cfg = civ6_config.load_local_config(path)
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
            self.assertEqual("1", os.environ.get("CIV6AI_LMSTUDIO_VISION"))


if __name__ == "__main__":
    unittest.main()
