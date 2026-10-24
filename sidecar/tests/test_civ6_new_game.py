"""Host-side new-game detection, stale PID records and the helper watchdog."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "testbed"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import civ6_new_game as ng  # noqa: E402

_spec = importlib.util.spec_from_file_location("civ6ai_start_live_ng", ROOT / "scripts" / "start_live.py")
start_live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(start_live)
_wspec = importlib.util.spec_from_file_location("civ6ai_watchdog", ROOT / "scripts" / "live_watchdog.py")
watchdog = importlib.util.module_from_spec(_wspec)
_wspec.loader.exec_module(watchdog)


def _blob(session, turn, player=0, kind="snapshot", seed=None):
    game = {"map_width": 10}
    if seed is not None:
        game["map_seed"] = seed
    return {"kind": kind, "id": f"{session}_{player}_{turn}_{kind}", "session": session, "player": player,
            "turn": turn, "live": True, "payload": json.dumps({"game": game, "decision": {"turn": turn}})}


class NewGameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mem = self.root / "memory"
        self.mem.mkdir()
        os.environ["CIV6AI_MEMORY_DIR"] = str(self.mem)
        (self.root / "runtime.json").write_text(json.dumps({"session_id": "S1"}), encoding="utf-8")
        self._pending = []
        import civ6_host_channel

        self._orig = civ6_host_channel.clear_pending_apply_lua
        civ6_host_channel.clear_pending_apply_lua = lambda: self._pending.append(1)

    def tearDown(self):
        import civ6_host_channel

        civ6_host_channel.clear_pending_apply_lua = self._orig
        os.environ.pop("CIV6AI_MEMORY_DIR", None)
        self.tmp.cleanup()

    def _seat_files(self, session, turn):
        d = self.root / "sessions" / session / "PLAYER_0"
        d.mkdir(parents=True, exist_ok=True)
        (d / "snapshot.json").write_text(json.dumps({"decision": {"turn": turn}}), encoding="utf-8")
        (d / "decision.json").write_text("{}", encoding="utf-8")
        (self.mem / f"{session}_PLAYER_0.json").write_text("{}", encoding="utf-8")
        (self.mem / session).mkdir(exist_ok=True)

    def test_turn_back_to_one_resets_same_session_and_keeps_t1(self):
        self._seat_files("S1", 51)
        blobs, active = ng.track_game(self.root, [_blob("S1", 1)], "S1")
        self.assertEqual(active, "S1")
        self.assertEqual([b["turn"] for b in blobs], [1])
        seat = self.root / "sessions" / "S1" / "PLAYER_0"
        self.assertFalse((seat / "decision.json").exists())
        self.assertFalse((self.mem / "S1_PLAYER_0.json").exists())
        self.assertFalse((self.mem / "S1").exists())
        self.assertEqual(self._pending, [1])
        self.assertEqual(ng.load_tracker(self.root)["sessions"]["S1"]["last_turn"], 1)

    def test_normal_turns_do_not_reset(self):
        self._seat_files("S1", 5)
        ng.track_game(self.root, [_blob("S1", 6)], "S1")
        ng.track_game(self.root, [_blob("S1", 7)], "S1")
        self.assertTrue((self.mem / "S1_PLAYER_0.json").exists())
        self.assertEqual(self._pending, [])
        self.assertEqual(ng.load_tracker(self.root)["sessions"]["S1"]["last_turn"], 7)

    def test_reload_of_older_save_is_not_a_new_game(self):
        ng.track_game(self.root, [_blob("S1", 30)], "S1")
        self._seat_files("S1", 30)
        ng.track_game(self.root, [_blob("S1", 25)], "S1")
        self.assertTrue((self.mem / "S1_PLAYER_0.json").exists())

    def test_other_session_is_adopted(self):
        blobs, active = ng.track_game(self.root, [_blob("S0", 1)], "S1")
        self.assertEqual(active, "S0")
        self.assertEqual(len(blobs), 1)
        runtime = json.loads((self.root / "runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(runtime["session_id"], "S0")

    def test_adopted_session_with_old_game_on_disk_resets(self):
        self._seat_files("S0", 51)
        _blobs, active = ng.track_game(self.root, [_blob("S0", 1)], "S1")
        self.assertEqual(active, "S0")
        self.assertFalse((self.mem / "S0_PLAYER_0.json").exists())

    def test_seed_change_is_new_game_and_same_seed_is_not(self):
        ng.track_game(self.root, [_blob("S1", 1, seed=11)], "S1")
        ng.track_game(self.root, [_blob("S1", 9, seed=11)], "S1")
        self._seat_files("S1", 9)
        ng.track_game(self.root, [_blob("S1", 1, seed=11)], "S1")  # reload of T1 save: same game
        self.assertTrue((self.mem / "S1_PLAYER_0.json").exists())
        ng.track_game(self.root, [_blob("S1", 4, seed=22)], "S1")
        self.assertFalse((self.mem / "S1_PLAYER_0.json").exists())

    def test_current_game_blobs_drops_old_backlog(self):
        blobs = [_blob("S0", 50), _blob("S0", 51), _blob("S1", 1), _blob("S1", 1, player=1)]
        self.assertEqual([b["session"] for b in ng.current_game_blobs(blobs)], ["S1", "S1"])
        same = [_blob("S1", 50), _blob("S1", 1)]
        self.assertEqual([b["turn"] for b in ng.current_game_blobs(same)], [1])

    def test_current_game_offset(self):
        lines = [
            "CIV6AI|blob|begin|snapshot|a|1|1|0|50|S0\n",
            "noise\n",
            "CIV6AI|blob|begin|snapshot|b|1|1|0|1|S1\n",
        ]
        data = "".join(lines).encode()
        self.assertEqual(ng.current_game_offset(data), len((lines[0] + lines[1]).encode()))
        self.assertIsNone(ng.current_game_offset(data, max_turn=0))
        self.assertIsNone(ng.current_game_offset(b"nothing\n"))


class WorkerRecordTests(unittest.TestCase):
    def test_stale_record_has_no_live_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "live_workers.json"
            pid_file.write_text(json.dumps({"workers": [{"name": "a", "pid": 11}, {"name": "b", "pid": 12}]}))
            self.assertEqual(start_live.recorded_live_workers(pid_file, alive=lambda pid: False), [])
            live = start_live.recorded_live_workers(pid_file, alive=lambda pid: pid == 12)
            self.assertEqual([w["name"] for w in live], ["b"])

    def test_watchdog_respawns_dead_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "live_workers.json"
            workers = [{"name": "watchdog", "pid": os.getpid(), "cmd": ["x"]},
                       {"name": "lua_bridge", "pid": 99, "cmd": ["py", "bridge"]},
                       {"name": "job_poller", "pid": 98, "cmd": ["py", "poller"]}]
            pid_file.write_text(json.dumps({"workers": workers}))
            spawned = []
            result = watchdog.check_once(pid_file, {}, alive=lambda pid: pid == 98,
                                         spawn=lambda cmd: spawned.append(cmd) or 1234)
            self.assertEqual(result, "ok")
            self.assertEqual(spawned, [["py", "bridge"]])
            saved = json.loads(pid_file.read_text())["workers"]
            self.assertEqual(saved[1]["pid"], 1234)
            self.assertEqual(saved[1]["respawns"], 1)
            pid_file.unlink()
            self.assertEqual(watchdog.check_once(pid_file, {}), "stop")


if __name__ == "__main__":
    unittest.main()
