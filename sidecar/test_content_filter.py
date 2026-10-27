import io
import json
import unittest
import urllib.error
from unittest import mock

from sidecar import pipeline_v2 as pipeline


def _ok(model):
    return {"choices": [{"message": {"content": "{}"}}], "model": model}


class ContentFilterFallbackTest(unittest.TestCase):
    def _run(self, outcomes):
        calls = []

        def fake(snap, *, cfg, image_data_url, opener):
            calls.append((image_data_url, (snap.get("_escalation") or {}).get("model")))
            out = outcomes[len(calls) - 1]
            if isinstance(out, Exception):
                raise out
            return {"ok": True}, {"model": out}

        with mock.patch.object(pipeline, "model_provider", return_value="openrouter"), \
             mock.patch("sidecar.lmstudio_client.call_lmstudio_chat", side_effect=fake):
            result = pipeline.call_model({"decision": {"player_id": "PLAYER_1"}}, "", image_data_url="img")
        return result, calls

    def test_retry_without_image(self):
        err = pipeline.BoundaryError("content_filter", "HTTP 400 data_inspection_failed")
        (_, meta), calls = self._run([err, "qwen"])
        self.assertEqual(calls, [("img", None), (None, None)])
        self.assertEqual(meta["content_filter_fallback"], "no_image")

    def test_escalation_model_after_second_filter(self):
        err = pipeline.BoundaryError("api_error", "Input image data may contain inappropriate content")
        (_, meta), calls = self._run([err, err, "haiku"])
        self.assertIsNone(calls[2][0])
        self.assertTrue(calls[2][1])
        self.assertEqual(meta["content_filter_fallback"], "escalation_model")

    def test_other_errors_raise(self):
        with self.assertRaises(pipeline.BoundaryError):
            self._run([pipeline.BoundaryError("api_error", "HTTP 401"), "x"])

    def test_breaker_ignores_content_filter(self):
        breaker = pipeline.CircuitBreaker(failures={})
        for _ in range(5):
            breaker.record_failure("PLAYER_1", "content_filter", "data_inspection_failed")
        self.assertFalse(breaker.open("PLAYER_1"))

    def test_client_categorizes_http_400(self):
        from sidecar import lmstudio_client
        self.assertTrue(lmstudio_client.is_content_filter_text('{"code":"data_inspection_failed"}'))


if __name__ == "__main__":
    unittest.main()
