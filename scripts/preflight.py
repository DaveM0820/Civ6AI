#!/usr/bin/env python3
"""Civ6Ai preflight for a real Windows + LM Studio end-to-end test.

Checks Python deps, LM Studio reachability / loaded model, tiny text + image
calls, Civ6 install + Mods/runtime folders, and that the installed mod matches
the repo version. Prints a PASS/FAIL checklist.

Cannot fully verify Civ6 or LM Studio in CI — David must run this on his PC.
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from civ6_paths import (  # noqa: E402
    find_civ6_install,
    installed_mod_dirs,
    logs_dirs,
    lua_log_candidates,
    mods_targets,
    my_games_roots,
    read_modinfo_version,
)
from sidecar.civ6_config import (  # noqa: E402
    EXAMPLE_CONFIG,
    LOCAL_CONFIG,
    apply_config_to_environ,
    load_local_config,
)
from sidecar import lmstudio_client  # noqa: E402
from sidecar import pipeline_v2 as pipeline  # noqa: E402

# 1x1 PNG
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class Check:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = False
        self.detail = ""

    def pass_(self, detail: str = "") -> None:
        self.ok = True
        self.detail = detail

    def fail(self, detail: str) -> None:
        self.ok = False
        self.detail = detail


def _check_deps() -> Check:
    check = Check("Python deps (jsonschema, Pillow)")
    missing: list[str] = []
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        missing.append("jsonschema")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    if missing:
        check.fail("missing: " + ", ".join(missing) + " — run: pip install -r requirements.txt")
    else:
        check.pass_("ok")
    return check


def _check_config() -> tuple[Check, object]:
    check = Check("Local config (LM Studio defaults)")
    cfg = load_local_config()
    apply_config_to_environ(cfg)
    src = "civ6ai.local.json" if LOCAL_CONFIG.is_file() else "example + env"
    check.pass_(
        f"provider={cfg.provider} endpoint={cfg.endpoint} model={cfg.model} "
        f"timeout={cfg.timeout_seconds}s vision={cfg.vision} reasoning={cfg.reasoning} ({src})"
    )
    return check, cfg


def _check_lmstudio_reachable(cfg) -> Check:
    check = Check("LM Studio reachable (/v1/models)")
    try:
        models = lmstudio_client.list_loaded_models(cfg, timeout_seconds=8.0)
    except pipeline.BoundaryError as error:
        check.fail(str(error))
        return check
    except Exception as error:
        check.fail(f"{type(error).__name__}: {error}")
        return check
    if not models:
        check.fail("reachable but no models listed — load a Qwen vision model in LM Studio")
        return check
    ids = [str(m.get("id") or m.get("name") or "?") for m in models[:5]]
    check.pass_(f"{len(models)} model(s): {', '.join(ids)}")
    return check


def _tiny_snapshot() -> dict:
    return {
        "schema_version": "civ6ai-input/1",
        "decision": {"turn": 1, "player_id": "PLAYER_0", "phase": "strategic_decision"},
        "legal_commands": [],
        "your_units": [],
        "your_cities": [],
        "personality": {"leader_name": "Pericles", "civilization_id": "CIVILIZATION_GREECE"},
        "game": {"map_width": 20, "map_height": 20, "network_multiplayer": False},
        "known_map": {"visibility_mode": "player_visible", "plots": []},
    }


def _check_text_call(cfg) -> Check:
    check = Check("LM Studio tiny text completion")
    snapshot = _tiny_snapshot()

    class _Fake:  # unused — real HTTP
        pass

    try:
        result, meta = lmstudio_client.call_lmstudio_chat(
            snapshot,
            cfg=cfg,
            image_data_url=None,
            wire_text="Reply with exactly: thought.situation = preflight\nthought.strategy = ok\n",
        )
        check.pass_(f"model={meta.get('model')} latency_ms={meta.get('latency_ms')}")
        _ = result
    except pipeline.BoundaryError as error:
        check.fail(f"{error.category}: {error}")
    except Exception as error:
        check.fail(f"{type(error).__name__}: {error}")
    return check


def _check_image_call(cfg) -> Check:
    check = Check("LM Studio tiny image completion")
    if not cfg.vision:
        check.pass_("skipped (vision=false in config)")
        return check
    snapshot = _tiny_snapshot()
    data_url = "data:image/png;base64," + base64.b64encode(_TINY_PNG).decode("ascii")
    try:
        _result, meta = lmstudio_client.call_lmstudio_chat(
            snapshot,
            cfg=cfg,
            image_data_url=data_url,
            wire_text="A 1x1 PNG is attached. Reply with: thought.situation = saw_image\nthought.strategy = ok\n",
        )
        check.pass_(f"vision_enabled={meta.get('vision_enabled')} latency_ms={meta.get('latency_ms')}")
    except pipeline.BoundaryError as error:
        check.fail(f"{error.category}: {error}")
    except Exception as error:
        check.fail(f"{type(error).__name__}: {error}")
    return check


def _check_civ6_install() -> Check:
    check = Check("Civ6 install path (Steam libraries)")
    install = find_civ6_install()
    if install is None:
        check.fail(
            "not found — set CIV6_INSTALL to the game root "
            "(e.g. D:\\SteamLibrary\\steamapps\\common\\Sid Meier's Civilization VI)"
        )
    else:
        check.pass_(str(install))
    return check


def _check_runtime_folders() -> Check:
    check = Check("My Games / Logs runtime folders")
    games = [str(p) for p in my_games_roots() if p.is_dir()]
    logs = [str(p) for p in logs_dirs() if p.is_dir()]
    if not games and not logs:
        check.fail("no My Games or Logs folders yet — launch Civ6 once to create them")
    else:
        check.pass_(f"games={games or ['(none)']} logs={logs or ['(none)']}")
    return check


def _check_mod_installed() -> Check:
    check = Check("Civ6Ai mod installed + version match")
    repo_version = read_modinfo_version(ROOT / "mod" / "Civ6Ai" / "Civ6Ai.modinfo")
    installed = installed_mod_dirs()
    if not installed:
        targets = ", ".join(str(p) for p in mods_targets())
        check.fail(f"mod not found under Mods — run: python scripts/install_mod.py  (targets: {targets})")
        return check
    mismatches: list[str] = []
    details: list[str] = []
    for path in installed:
        ver = read_modinfo_version(path / "Civ6Ai.modinfo")
        details.append(f"{path} version={ver}")
        if repo_version and ver and ver != repo_version:
            mismatches.append(f"{path} has {ver}, repo has {repo_version}")
    if mismatches:
        check.fail("; ".join(mismatches) + " — re-run install_mod.py")
    else:
        check.pass_(" | ".join(details) + (f" (repo={repo_version})" if repo_version else ""))
    return check


def _check_example_config_present() -> Check:
    check = Check("Documented config example present")
    if EXAMPLE_CONFIG.is_file():
        check.pass_(str(EXAMPLE_CONFIG.relative_to(ROOT)))
    else:
        check.fail(f"missing {EXAMPLE_CONFIG}")
    return check


def main() -> int:
    print("Civ6Ai preflight")
    print("=" * 60)
    checks: list[Check] = []
    checks.append(_check_deps())
    cfg_check, cfg = _check_config()
    checks.append(cfg_check)
    checks.append(_check_example_config_present())
    checks.append(_check_lmstudio_reachable(cfg))
    # Only attempt model calls when LM Studio looked reachable.
    if checks[-1].ok:
        checks.append(_check_text_call(cfg))
        checks.append(_check_image_call(cfg))
    else:
        skip_text = Check("LM Studio tiny text completion")
        skip_text.fail("skipped — LM Studio not reachable")
        skip_img = Check("LM Studio tiny image completion")
        skip_img.fail("skipped — LM Studio not reachable")
        checks.extend([skip_text, skip_img])
    checks.append(_check_civ6_install())
    checks.append(_check_runtime_folders())
    checks.append(_check_mod_installed())

    failed = 0
    for check in checks:
        mark = "PASS" if check.ok else "FAIL"
        if not check.ok:
            failed += 1
        print(f"[{mark}] {check.name}")
        if check.detail:
            print(f"       {check.detail}")

    print("=" * 60)
    lua = [str(p) for p in lua_log_candidates()]
    print("Lua.log candidates:", "; ".join(lua) if lua else "(none)")
    print("Config example:", EXAMPLE_CONFIG)
    print("Local config (optional):", LOCAL_CONFIG, "(gitignored)")
    if failed:
        print(f"RESULT: FAIL ({failed}/{len(checks)} checks failed)")
        print("Fix FAILs above, then re-run: python scripts/preflight.py")
        return 1
    print(f"RESULT: PASS ({len(checks)}/{len(checks)})")
    print("Next: see docs/REAL_TEST.md (SP M0 first).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
