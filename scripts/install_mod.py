#!/usr/bin/env python3
"""Copy mod/Civ6Ai into both possible Civ6 Mods folders, with timestamped backups."""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "mod" / "Civ6Ai"
MEIER = "Sid Meier's Civilization VI"


def mods_targets() -> list[Path]:
    home = Path.home()
    return [
        home / "OneDrive" / "Documents" / "My Games" / MEIER / "Mods" / "Civ6Ai",
        home / "Documents" / "My Games" / MEIER / "Mods" / "Civ6Ai",
    ]


def copy_tree(src: Path, dst: Path) -> int:
    n = 0
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        if "__pycache__" in f.parts or f.suffix == ".pyc":
            continue
        out = dst / f.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
        n += 1
    return n


def backup_existing(dst: Path) -> Path | None:
    if not dst.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = dst.with_name(f"{dst.name}.bak-{stamp}")
    if backup.exists():
        shutil.rmtree(backup)
    shutil.move(str(dst), str(backup))
    return backup


def main() -> int:
    if not SRC.is_dir():
        print(f"ERROR: missing {SRC}", file=sys.stderr)
        return 1
    installed = 0
    for t in mods_targets():
        parent = t.parent
        # Only install into trees that already exist OR create Mods under My Games if Documents exists.
        my_games = parent.parent  # .../My Games/Civ6
        docs_root = my_games.parent  # .../My Games
        if not docs_root.exists() and not my_games.exists():
            print(f"Skip (My Games path missing): {t}")
            continue
        parent.mkdir(parents=True, exist_ok=True)
        backup = backup_existing(t)
        if backup is not None:
            print(f"Backup -> {backup}")
        n = copy_tree(SRC, t)
        installed += 1
        print(f"Installed {n} files -> {t}")
    if installed == 0:
        print(
            "WARNING: no Mods targets were writable. Create "
            f"Documents/My Games/{MEIER}/Mods manually, then re-run.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
