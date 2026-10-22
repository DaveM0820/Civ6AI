"""Repo-root pytest must not collect `_backup_*` directories."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_conftest():
    spec = importlib.util.spec_from_file_location("repo_conftest", ROOT / "conftest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PytestBackupIgnoreTests(unittest.TestCase):
    def test_backup_dirs_are_ignored_and_real_tests_are_not(self):
        hook = _load_conftest().pytest_ignore_collect
        backup = ROOT / "_backup_old" / "sidecar" / "tests" / "test_civ6_wire_prompt.py"
        real = ROOT / "sidecar" / "tests" / "test_civ6_wire_prompt.py"
        self.assertTrue(hook(collection_path=backup))
        self.assertTrue(hook(path=backup))
        self.assertFalse(hook(collection_path=real))
        self.assertFalse(hook(path=real))
        self.assertFalse(hook())

    def test_pytest_ini_names_the_backup_pattern(self):
        text = (ROOT / "pytest.ini").read_text(encoding="utf-8")
        self.assertIn("_backup_*", text)


if __name__ == "__main__":
    unittest.main()
