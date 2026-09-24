"""Locate Civ6 install + My Games Mods / Logs / runtime folders."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

MEIER = "Sid Meier's Civilization VI"
STEAM_APP_HINTS = (
    "CivilizationVI.exe",
    "Base/Binaries/Win64Steam/CivilizationVI.exe",
    "Base/Binaries/Win64EOS/CivilizationVI.exe",
)


def _unique(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def my_games_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        home / "OneDrive" / "Documents" / "My Games" / MEIER,
        home / "Documents" / "My Games" / MEIER,
    ]
    local = os.environ.get("LOCALAPPDATA") or ""
    if local:
        candidates.append(Path(local) / "Firaxis Games" / MEIER)
    return _unique(candidates)


def mods_targets() -> list[Path]:
    return [root / "Mods" / "Civ6Ai" for root in my_games_roots() if "My Games" in str(root)]


def logs_dirs() -> list[Path]:
    roots = my_games_roots()
    out: list[Path] = []
    for root in roots:
        out.append(root / "Logs")
    local = os.environ.get("LOCALAPPDATA") or ""
    if local:
        out.append(Path(local) / "Firaxis Games" / MEIER / "Logs")
    return _unique(out)


def lua_log_candidates() -> list[Path]:
    return [d / "Lua.log" for d in logs_dirs()]


def _steam_library_roots() -> list[Path]:
    roots: list[Path] = []
    program_files = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
    ]
    for base in program_files:
        steam = base / "Steam"
        if steam.is_dir():
            roots.append(steam)
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                text = vdf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                roots.append(Path(match.group(1)))
    # Common extra drive layout David uses.
    for drive in "DEFG":
        roots.append(Path(f"{drive}:/SteamLibrary"))
        roots.append(Path(f"{drive}:/Steam"))
    return _unique(roots)


def find_civ6_install() -> Path | None:
    env = os.environ.get("CIV6_INSTALL") or os.environ.get("CIV6AI_CIV6_INSTALL") or ""
    if env:
        path = Path(env)
        if path.is_dir():
            return path
    for steam in _steam_library_roots():
        common = steam / "steamapps" / "common"
        for name in ("Sid Meier's Civilization VI", "Civilization VI"):
            candidate = common / name
            if candidate.is_dir():
                return candidate
            # Some libraries put the exe one level deeper.
            for hint in STEAM_APP_HINTS:
                exe = candidate / hint
                if exe.is_file():
                    return candidate
    return None


def read_modinfo_version(modinfo: Path) -> str | None:
    if not modinfo.is_file():
        return None
    text = modinfo.read_text(encoding="utf-8-sig", errors="replace")
    match = re.search(r'version\s*=\s*"(\d+)"', text, re.IGNORECASE)
    return match.group(1) if match else None


def installed_mod_dirs() -> list[Path]:
    return [p for p in mods_targets() if p.is_dir()]
