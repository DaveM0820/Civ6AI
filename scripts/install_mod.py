#!/usr/bin/env python3
"""Copy DEST\\mod\\Civ6Ai -> OneDrive and Documents My Games Mods\\Civ6Ai."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "mod" / "Civ6Ai"
MEIER = "Sid Meier's Civilization VI"
TARGETS = [
    Path.home() / "OneDrive" / "Documents" / "My Games" / MEIER / "Mods" / "Civ6Ai",
    Path.home() / "Documents" / "My Games" / MEIER / "Mods" / "Civ6Ai",
]


def copy_tree(src: Path, dst: Path) -> int:
    n = 0
    if dst.exists():
        shutil.rmtree(dst)
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


def main() -> int:
    if not SRC.is_dir():
        print(f"ERROR: missing {SRC}", file=sys.stderr)
        return 1
    for t in TARGETS:
        t.parent.mkdir(parents=True, exist_ok=True)
        n = copy_tree(SRC, t)
        print(f"Installed {n} files -> {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
