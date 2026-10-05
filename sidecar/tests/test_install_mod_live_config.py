"""Tests for scripts/install_mod.py live-config generation (offline, temp dirs only)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("civ6ai_install_mod", ROOT / "scripts" / "install_mod.py")
install_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_mod)


def _settings(root: Path, **kw) -> dict:
    base = dict(
        civ6ai_root=root / "My Games" / "Sid Meier's Civilization VI" / "civ6ai",
        log_dir=root / "Logs",
        managed_seats="1",
        session_id="live-test",
        sidecar_timeout=600,
        python="C:\\Users\\me\\miniconda3\\python.exe",
        repo=Path("C:\\Users\\me\\Civ6AI"),
    )
    base.update(kw)
    return install_mod.live_settings(**base)


class LiveConfigRenderTests(unittest.TestCase):
    def test_paths_lua_has_repo_live_seats_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = _settings(Path(tmp))
        text = install_mod.render_paths_lua(s)
        self.assertIn('Repo = "C:/Users/me/Civ6AI"', text)
        self.assertIn('Python = "C:/Users/me/miniconda3/python.exe"', text)
        self.assertIn("SidecarLive = 1", text)
        self.assertIn("Autotest = 1", text)
        self.assertIn('ManagedSeats = "1"', text)
        self.assertIn('SessionId = "live-test"', text)
        self.assertIn("SidecarTimeoutSeconds = 600", text)
        self.assertIn("Sid Meier's Civilization VI/civ6ai", text)  # apostrophe kept, slashes forward
        self.assertNotIn("\\", text)
        text.encode("ascii")

    def test_seat_list_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = _settings(Path(tmp), managed_seats="1, 2,2")
        self.assertIn('ManagedSeats = "1,2"', install_mod.render_paths_lua(s))

    def test_quotes_escaped(self):
        self.assertEqual('"a\\"b"', install_mod._lua_str('a"b'))

    def test_empty_seats_means_all(self):
        self.assertEqual("", install_mod.normalize_seats(""))
        self.assertEqual("", install_mod.normalize_seats(" , "))

    def test_bad_seats_rejected(self):
        with self.assertRaises(ValueError):
            install_mod.normalize_seats("x")

    def test_timeout_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = _settings(Path(tmp), sidecar_timeout=5)
        self.assertEqual(30, s["sidecar_timeout_seconds"])

    def test_no_autotest_writes_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = _settings(Path(tmp), autotest=False)
        self.assertIn("Autotest = 0", install_mod.render_paths_lua(s))
        args = install_mod.parse_args(["--no-autotest"])
        self.assertFalse(args.autotest)


class LiveConfigWriteTests(unittest.TestCase):
    def test_runtime_json_written_with_backup_and_session_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = _settings(Path(tmp), managed_seats="1,2")
            root = Path(s["root"])
            root.mkdir(parents=True)
            (root / "runtime.json").write_text('{"repo": "C:/old/civ4ai", "autotest": 1}', encoding="utf-8")
            mirror = Path(tmp) / "Logs" / "civ6ai"
            backup = install_mod.write_runtime_json(root, s, [mirror])
            self.assertIsNotNone(backup)
            self.assertIn("civ4ai", backup.read_text(encoding="utf-8"))
            data = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual("C:/Users/me/Civ6AI", data["repo"])
            self.assertEqual("live-test", data["session_id"])
            self.assertEqual(1, data["sidecar_live"])
            self.assertEqual(1, data["autotest"])
            self.assertEqual(600, data["sidecar_timeout_seconds"])
            for base in (root, mirror):
                self.assertTrue((base / "sessions" / "live-test" / "PLAYER_1").is_dir())
                self.assertTrue((base / "sessions" / "live-test" / "PLAYER_2").is_dir())

    def test_empty_seats_skips_player_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = _settings(Path(tmp), managed_seats="")
            root = Path(s["root"])
            install_mod.write_runtime_json(root, s)
            self.assertTrue((root / "sessions" / "live-test").is_dir())
            self.assertEqual([], list((root / "sessions" / "live-test").glob("PLAYER_*")))
            self.assertEqual("", json.loads((root / "runtime.json").read_text(encoding="utf-8"))["managed_seats"])

    def test_main_installs_live_config_into_targets_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            target = tmp / "My Games" / "Sid Meier's Civilization VI" / "Mods" / "Civ6Ai"
            target.parent.mkdir(parents=True)
            civ6ai_root = tmp / "My Games" / "Sid Meier's Civilization VI" / "civ6ai"
            repo_stub = (ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Paths.lua").read_text(encoding="utf-8")
            with mock.patch.object(install_mod, "mods_targets", lambda: [target]), \
                    mock.patch.object(install_mod, "default_civ6ai_root", lambda: civ6ai_root), \
                    mock.patch.object(install_mod, "default_log_dir", lambda: tmp / "Logs"), \
                    mock.patch("builtins.print"):
                code = install_mod.main(["--managed-seats", "1", "--sidecar-timeout", "900", "--session-id", "live-x"])
            self.assertEqual(0, code)
            paths_lua = (target / "InGame" / "Civ6Ai_Paths.lua").read_text(encoding="utf-8")
            self.assertIn("SidecarTimeoutSeconds = 900", paths_lua)
            self.assertIn('SessionId = "live-x"', paths_lua)
            self.assertIn("SidecarLive = 1", paths_lua)
            self.assertIn("Autotest = 1", paths_lua)
            self.assertFalse((target / "Gameplay" / "Civ6Ai_Runtime.lua").exists())
            self.assertTrue((target / "Civ6Ai.modinfo").is_file())
            self.assertEqual("live-x", json.loads((civ6ai_root / "runtime.json").read_text(encoding="utf-8"))["session_id"])
            # repo stub untouched
            self.assertEqual(repo_stub, (ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Paths.lua").read_text(encoding="utf-8"))

    def test_stub_only_keeps_stubs_and_skips_runtime_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            target = tmp / "My Games" / "Sid Meier's Civilization VI" / "Mods" / "Civ6Ai"
            target.parent.mkdir(parents=True)
            civ6ai_root = tmp / "civ6ai"
            with mock.patch.object(install_mod, "mods_targets", lambda: [target]), \
                    mock.patch.object(install_mod, "default_civ6ai_root", lambda: civ6ai_root), \
                    mock.patch("builtins.print"):
                code = install_mod.main(["--stub-only"])
            self.assertEqual(0, code)
            self.assertIn('Repo = ""', (target / "InGame" / "Civ6Ai_Paths.lua").read_text(encoding="utf-8"))
            self.assertFalse((civ6ai_root / "runtime.json").exists())


class BackupLocationTests(unittest.TestCase):
    def test_backups_go_outside_mods_and_legacy_ones_are_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            games = Path(tmp) / "My Games" / "Sid Meier's Civilization VI"
            target = games / "Mods" / "Civ6Ai"
            (target).mkdir(parents=True)
            (target / "Civ6Ai.modinfo").write_text("new", encoding="utf-8")
            legacy = games / "Mods" / "Civ6Ai.bak-20260101-000000"
            legacy.mkdir()
            (legacy / "Civ6Ai.modinfo").write_text("old", encoding="utf-8")
            moved = install_mod.relocate_legacy_backups(target)
            self.assertEqual(1, len(moved))
            self.assertFalse(legacy.exists())
            self.assertEqual(games / "Civ6Ai_mod_backups", moved[0].parent)
            backup = install_mod.backup_existing(target)
            self.assertEqual(games / "Civ6Ai_mod_backups", backup.parent)
            self.assertFalse(target.exists())
            self.assertEqual([], [p for p in (games / "Mods").iterdir()])


class PreflightLiveConfigTests(unittest.TestCase):
    def _preflight(self):
        spec = importlib.util.spec_from_file_location("civ6ai_preflight_lc", ROOT / "scripts" / "preflight.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_generated_config_passes_and_stub_fails(self):
        preflight = self._preflight()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mod = tmp / "Mods" / "Civ6Ai"
            (mod / "InGame").mkdir(parents=True)
            (mod / "Gameplay").mkdir(parents=True)
            root = tmp / "civ6ai"
            s = _settings(tmp, repo=ROOT)
            s["root"] = str(root)
            install_mod.write_mod_live_config(mod, s)
            install_mod.write_runtime_json(root, s)
            check = preflight._check_live_config([mod], root)
            self.assertTrue(check.ok, check.detail)
            self.assertIn("managed_seats=1", check.detail)
            # stale runtime.json from another repo -> FAIL
            (root / "runtime.json").write_text('{"repo": "C:/Users/me/civ4ai", "sidecar_live": 1, "session_id": "live-test"}', encoding="utf-8")
            check = preflight._check_live_config([mod], root)
            self.assertFalse(check.ok)
            self.assertIn("civ4ai", check.detail)
            # repo stub Paths.lua -> FAIL
            stub = (ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Paths.lua").read_text(encoding="utf-8")
            (mod / "InGame" / "Civ6Ai_Paths.lua").write_text(stub, encoding="utf-8")
            check = preflight._check_live_config([mod], root)
            self.assertFalse(check.ok)
            self.assertIn("SidecarLive is not 1", check.detail)
            self.assertIn("install_mod.py", check.detail)


if __name__ == "__main__":
    unittest.main()
