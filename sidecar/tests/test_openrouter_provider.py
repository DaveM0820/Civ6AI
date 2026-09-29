"""OpenRouter provider: config defaults, request body, and parallel seat jobs."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / "scripts", ROOT / "scripts" / "testbed"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from sidecar import civ6_config, lmstudio_client  # noqa: E402
import civ6_sidecar_jobs as jobs  # noqa: E402

_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith(("CIV6AI_", "CIV4AI_", "LMSTUDIO_", "OPENROUTER_", "OPENAI_"))}


def _load(tmp: Path, data: dict, env: dict | None = None) -> civ6_config.Civ6AiLocalConfig:
    path = tmp / "local.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with mock.patch.dict(os.environ, {**_CLEAN_ENV, **(env or {})}, clear=True):
        return civ6_config.load_local_config(path)


class OpenRouterConfigTests(unittest.TestCase):
    def test_openrouter_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _load(Path(tmp), {"provider": "openrouter"}, {"OPENROUTER_API_KEY": "sk-test"})
        self.assertEqual(cfg.endpoint, "https://openrouter.ai/api/v1")
        self.assertEqual(cfg.model, "qwen/qwen3.7-flash")
        self.assertEqual(cfg.api_key, "sk-test")
        self.assertFalse(cfg.queue_shared_model)
        self.assertEqual(cfg.timeout_seconds, civ6_config.OPENROUTER_TIMEOUT_DEFAULT)
        self.assertEqual(cfg.effective_parallel_seats, civ6_config.OPENROUTER_PARALLEL_DEFAULT)

    def test_local_json_key_and_model_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _load(Path(tmp), {"provider": "openrouter", "api_key": "sk-json", "model": "x/y", "parallel_seats": 3})
        self.assertEqual(cfg.api_key, "sk-json")
        self.assertEqual(cfg.model, "x/y")
        self.assertEqual(cfg.effective_parallel_seats, 3)

    def test_lmstudio_stays_serial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _load(Path(tmp), {"provider": "lmstudio"})
        self.assertEqual(cfg.effective_parallel_seats, 1)
        self.assertTrue(cfg.queue_shared_model)
        self.assertIn("localhost", cfg.endpoint)


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class OpenRouterRequestTests(unittest.TestCase):
    def _cfg(self) -> civ6_config.Civ6AiLocalConfig:
        cfg = civ6_config.Civ6AiLocalConfig(provider="openrouter", endpoint="https://openrouter.ai/api/v1",
                                            model="qwen/qwen3.7-flash", api_key="sk-test", queue_shared_model=False)
        return cfg

    def test_body_and_headers(self) -> None:
        cfg = self._cfg()
        body = lmstudio_client.build_chat_completions_body(snapshot={}, cfg=cfg, system_prompt="s", wire_text="w")
        self.assertEqual(body["reasoning"], {"effort": "low", "exclude": False})
        cfg.reasoning = "off"
        body = lmstudio_client.build_chat_completions_body(snapshot={}, cfg=cfg, system_prompt="s", wire_text="w")
        self.assertEqual(body["reasoning"], {"enabled": False})
        headers = lmstudio_client.request_headers(cfg)
        self.assertEqual(headers["Authorization"], "Bearer sk-test")
        self.assertIn("X-Title", headers)

    def test_missing_key_is_clear(self) -> None:
        cfg = self._cfg()
        cfg.api_key = ""
        with self.assertRaises(Exception) as ctx:
            lmstudio_client.call_lmstudio_chat({}, cfg=cfg, wire_text="w")
        self.assertEqual(getattr(ctx.exception, "category", ""), "missing_key")

    def test_error_payload_is_reported(self) -> None:
        with self.assertRaises(Exception) as ctx:
            lmstudio_client._chat_message_text({"error": {"code": 402, "message": "Insufficient credits"}})
        self.assertIn("402", str(ctx.exception))

    def test_provider_label_in_metadata(self) -> None:
        cfg = self._cfg()
        seen = {}

        def opener(request, timeout=0):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            payload = {"id": "r1", "model": cfg.model, "choices": [{"message": {"content": "x"}}], "usage": {}}
            return _Resp(json.dumps(payload).encode())

        with mock.patch.object(lmstudio_client.pipeline, "parse_model_text", return_value={"ok": True}):
            result, meta = lmstudio_client.call_lmstudio_chat({}, cfg=cfg, wire_text="w", opener=opener,
                                                              image_data_url=None)
        self.assertEqual(meta["provider"], "openrouter")
        self.assertEqual(seen["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer sk-test")


class ParallelJobTests(unittest.TestCase):
    def _make_jobs(self, root: Path, n: int) -> list[Path]:
        paths = []
        for i in range(n):
            pdir = root / "sessions" / "live" / f"PLAYER_{i}"
            pdir.mkdir(parents=True)
            job = pdir / "sidecar_job.json"
            job.write_text(json.dumps({"repo": str(root), "args": []}), encoding="utf-8")
            paths.append(job)
        return paths

    def test_seats_run_concurrently_and_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_jobs(root, 4)
            active = {"now": 0, "peak": 0, "calls": 0}
            lock = threading.Lock()

            def fake_run(job, repo):
                with lock:
                    active["now"] += 1
                    active["calls"] += 1
                    active["peak"] = max(active["peak"], active["now"])
                time.sleep(0.3)
                with lock:
                    active["now"] -= 1

            with mock.patch.object(jobs, "_run_job", side_effect=fake_run):
                started = jobs.process_sidecar_jobs(root, parallel=4)
                again = jobs.process_sidecar_jobs(root, parallel=4)  # in flight: nothing new
                deadline = time.time() + 5
                while time.time() < deadline:
                    with jobs._POOL_LOCK:
                        if not jobs._IN_FLIGHT:
                            break
                    time.sleep(0.05)
            self.assertEqual(started, 4)
            self.assertEqual(again, 0)
            self.assertEqual(active["calls"], 4)
            self.assertGreaterEqual(active["peak"], 2)
            self.assertFalse(list(root.rglob(jobs.CLAIM_NAME)))

    def test_claim_blocks_other_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            [job] = self._make_jobs(root, 1)
            (job.parent / jobs.CLAIM_NAME).write_text("other", encoding="utf-8")
            with mock.patch.object(jobs, "_run_job") as run:
                self.assertEqual(jobs.process_sidecar_jobs(root, parallel=1), 0)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
