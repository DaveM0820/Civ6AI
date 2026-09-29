"""Tests for scripts/start_live.py --dry-run pass/fail evaluation (offline)."""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_spec = importlib.util.spec_from_file_location("civ6ai_start_live", ROOT / "scripts" / "start_live.py")
start_live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(start_live)


def _fallback_record() -> dict:
    return {
        "status": "fallback",
        "category": "transport",
        "message": "LM Studio transport failed after 3 attempts: <urlopen error [WinError 10061] refused>",
        "commands": [],
        "model": None,
        "response": None,
    }


def _approved_record(commands: int = 1) -> dict:
    return {
        "status": "approved",
        "commands": [{"command_id": f"CMD_{i}", "kind": "set_research_tech"} for i in range(commands)],
        "model": {"model": "qwen/qwen3-vl-8b", "provider": "lmstudio", "usage": {}},
        "validated": {"rejections": []},
    }


def _stdout(record: dict) -> str:
    return "some log line\n" + json.dumps(record) + "\n"


class EvaluateDryRunTests(unittest.TestCase):
    def test_transport_fallback_fails_with_reason(self):
        ok, reason = start_live.evaluate_dry_run(0, _stdout(_fallback_record()))
        self.assertFalse(ok)
        self.assertIn("status=fallback", reason)
        self.assertIn("category=transport", reason)
        self.assertIn("10061", reason)

    def test_transport_category_fails_even_if_status_looks_ok(self):
        record = _approved_record()
        record["category"] = "transport"
        ok, _reason = start_live.evaluate_dry_run(0, _stdout(record))
        self.assertFalse(ok)

    def test_approved_real_reply_passes(self):
        ok, reason = start_live.evaluate_dry_run(0, _stdout(_approved_record(2)))
        self.assertTrue(ok, reason)
        self.assertIn("commands=2", reason)

    def test_approved_without_model_meta_fails(self):
        record = _approved_record()
        record["model"] = None
        ok, _reason = start_live.evaluate_dry_run(0, _stdout(record))
        self.assertFalse(ok)

    def test_approved_without_commands_fails(self):
        ok, reason = start_live.evaluate_dry_run(0, _stdout(_approved_record(0)))
        self.assertFalse(ok)
        self.assertIn("no commands", reason)

    def test_no_record_fails(self):
        ok, reason = start_live.evaluate_dry_run(0, "nothing useful\n")
        self.assertFalse(ok)
        self.assertIn("no decision record", reason)

    def test_crash_fails_with_stderr_tail(self):
        ok, reason = start_live.evaluate_dry_run(1, "", "Traceback...\nBoundaryError: boom\n")
        self.assertFalse(ok)
        self.assertIn("code 1", reason)
        self.assertIn("boom", reason)


class DryRunCommandTests(unittest.TestCase):
    def _cfg(self):
        return SimpleNamespace(
            endpoint="http://localhost:1234/v1", model="m", vision=True, timeout_seconds=600,
        )

    def _run(self, fake_run, log_dir: Path):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(start_live, "run_hidden", fake_run), \
                mock.patch.object(start_live, "LOG_DIR", log_dir), \
                mock.patch.object(start_live, "apply_config_to_environ", lambda cfg: None), \
                mock.patch.object(start_live, "_build_env", lambda cfg: {}), \
                redirect_stdout(out), redirect_stderr(err):
            code = start_live._dry_run(self._cfg(), ROOT / "fixtures" / "civ6" / "x.json", timeout_seconds=30)
        return code, out.getvalue()

    def test_fallback_exits_nonzero_with_ascii_fail_line(self):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["timeout"] = kwargs.get("timeout")
            return subprocess.CompletedProcess(cmd, 0, _stdout(_fallback_record()), "")

        with tempfile.TemporaryDirectory() as tmp:
            code, out = self._run(fake_run, Path(tmp))
        self.assertEqual(1, code)
        fail_lines = [line for line in out.splitlines() if line.startswith("DRY-RUN FAIL:")]
        self.assertEqual(1, len(fail_lines), out)
        self.assertIn("category=transport", fail_lines[0])
        out.encode("ascii")  # console-safe
        self.assertIn("--no-circuit-breaker", seen["cmd"])
        self.assertEqual(30, seen["timeout"])

    def test_approved_exits_zero(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, _stdout(_approved_record()), "")

        with tempfile.TemporaryDirectory() as tmp:
            code, out = self._run(fake_run, Path(tmp))
        self.assertEqual(0, code)
        self.assertIn("DRY-RUN PASS:", out)

    def test_timeout_exits_nonzero(self):
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

        with tempfile.TemporaryDirectory() as tmp:
            code, out = self._run(fake_run, Path(tmp))
        self.assertEqual(1, code)
        self.assertIn("DRY-RUN FAIL: sidecar did not finish", out)

    def test_reports_existing_breaker_as_ignored(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, _stdout(_fallback_record()), "")

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "circuit_breaker.json").write_text('{"PLAYER_0":1}\n', encoding="utf-8")
            code, out = self._run(fake_run, Path(tmp))
            self.assertEqual('{"PLAYER_0":1}\n', (Path(tmp) / "circuit_breaker.json").read_text(encoding="utf-8"))
        self.assertEqual(1, code)
        self.assertIn("PLAYER_0=1/3 closed", out)
        self.assertIn("ignored by dry run", out)


if __name__ == "__main__":
    unittest.main()
