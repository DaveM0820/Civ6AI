"""Repo-root pytest collection. Skip leftover `_backup_*` trees.

Those directories are old copies of this repo. Collecting them imports a second
copy of the same tests and errors. The unittest suite does not walk them.
"""
from __future__ import annotations

from pathlib import Path


def _backup_dir(candidate) -> bool:
    if candidate is None:
        return False
    return any(part.startswith("_backup_") for part in Path(str(candidate)).parts)


def pytest_ignore_collect(collection_path=None, config=None, path=None):
    if _backup_dir(collection_path) or _backup_dir(path):
        return True
    return False
