"""Circuit breaker: dry runs ignore it; live runs still enforce and count it."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sidecar import pipeline_v2 as pipeline
from sidecar import run_civ6

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
import circuit_breaker_state  # noqa: E402

SNAPSHOT = ROOT / "fixtures" / "civ6" / "snapshot-turn-classical-golden.json"


def _player_id() -> str:
    return str(json.loads(SNAPSHOT.read_text(encoding="utf-8-sig"))["decision"]["player_id"])


def _transport_error(*_args, **_kwargs):
    raise pipeline.BoundaryError("transport", "LM Studio transport failed after 3 attempts: refused")


class RunCiv6BreakerTests(unittest.TestCase):
    def _run(self, journal: Path, *extra: str) -> None:
        argv = [
            "run_civ6.py", "--state", str(SNAPSHOT), "--live",
            "--session-id", "dry-run-local", "--journal", str(journal), *extra,
        ]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch("sidecar.run_civ6.pipeline.call_model", side_effect=_transport_error), \
                mock.patch("builtins.print"):
            run_civ6.main()

    def test_no_circuit_breaker_ignores_open_breaker_and_leaves_file_untouched(self):
        player = _player_id()
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "dry_run_journal.jsonl"
            breaker = Path(tmp) / "circuit_breaker.json"
            breaker.write_text(json.dumps({player: 5}) + "\n", encoding="utf-8")
            before = breaker.read_text(encoding="utf-8")
            self._run(journal, "--no-circuit-breaker")  # must not raise circuit_breaker
            self.assertEqual(before, breaker.read_text(encoding="utf-8"))
            last = json.loads(journal.read_text(encoding="utf-8").strip().splitlines()[-1])
            self.assertEqual("fallback", last["status"])
            self.assertEqual("transport", last["category"])

    def test_no_circuit_breaker_does_not_create_breaker_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "dry_run_journal.jsonl"
            self._run(journal, "--no-circuit-breaker")
            self.assertFalse((Path(tmp) / "circuit_breaker.json").exists())

    def test_live_default_still_counts_failures(self):
        player = _player_id()
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "journal.jsonl"
            breaker = Path(tmp) / "circuit_breaker.json"
            breaker.write_text(json.dumps({player: 1}) + "\n", encoding="utf-8")
            self._run(journal)
            self.assertEqual(2, json.loads(breaker.read_text(encoding="utf-8"))[player])

    def test_live_default_still_blocks_when_open(self):
        player = _player_id()
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "journal.jsonl"
            (Path(tmp) / "circuit_breaker.json").write_text(json.dumps({player: 3}) + "\n", encoding="utf-8")
            with self.assertRaises(pipeline.BoundaryError) as ctx:
                self._run(journal)
            self.assertEqual("circuit_breaker", ctx.exception.category)


class BreakerStateTests(unittest.TestCase):
    def test_describe_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "circuit_breaker.json"
            self.assertIn("not present", circuit_breaker_state.describe(path))
            path.write_text("{}\n", encoding="utf-8")
            self.assertIn("clear", circuit_breaker_state.describe(path))
            path.write_text('{"PLAYER_0":1,"PLAYER_2":3}\n', encoding="utf-8")
            text = circuit_breaker_state.describe(path)
            self.assertIn("PLAYER_0=1/3 closed", text)
            self.assertIn("PLAYER_2=3/3 OPEN", text)
            failures, error = circuit_breaker_state.read_failures(path)
            self.assertIsNone(error)
            self.assertEqual(["PLAYER_2"], circuit_breaker_state.open_players(failures))
            path.write_text("not json", encoding="utf-8")
            self.assertIn("unreadable", circuit_breaker_state.describe(path))

    def test_live_breaker_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "civ6ai"
            (root / "sessions" / "game1").mkdir(parents=True)
            (root / "sessions" / "game1" / "circuit_breaker.json").write_text("{}", encoding="utf-8")
            found = circuit_breaker_state.live_breaker_files([root, Path(tmp) / "missing"])
            self.assertEqual([root / "sessions" / "game1" / "circuit_breaker.json"], found)


class PreflightBreakerReportTests(unittest.TestCase):
    def test_preflight_reports_open_live_breaker_without_failing(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("civ6ai_preflight", ROOT / "scripts" / "preflight.py")
        preflight = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(preflight)
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "My Games"
            session = game / "civ6ai" / "sessions" / "g1"
            session.mkdir(parents=True)
            (session / "circuit_breaker.json").write_text('{"PLAYER_1":3}', encoding="utf-8")
            for name in ("old1", "old2"):
                (game / "civ6ai" / "sessions" / name).mkdir()
                (game / "civ6ai" / "sessions" / name / "circuit_breaker.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(preflight, "ROOT", Path(tmp)), \
                    mock.patch.object(preflight, "my_games_roots", lambda: [game]), \
                    mock.patch.object(preflight, "logs_dirs", lambda: []):
                check = preflight._check_circuit_breakers()
        self.assertTrue(check.ok)
        self.assertIn("not present", check.detail)
        self.assertIn("PLAYER_1=3/3 OPEN", check.detail)
        self.assertIn("WARNING: breaker OPEN for PLAYER_1", check.detail)
        self.assertIn("live sessions: 3 breaker file(s), 2 clear", check.detail)
        self.assertNotIn("old1", check.detail)
        check.detail.encode("ascii")


if __name__ == "__main__":
    unittest.main()
