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

import circuit_breaker_state  # noqa: E402
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

# 16x16 PNG. A 1x1 probe is rejected by Qwen on OpenRouter (min edge > 10).
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAIklEQVR4nGNUClViIAUwkaSaYVQDcYCJSHVwMKqBGECyBgAHjAC5/GhsnwAAAABJRU5ErkJggg=="
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
    if getattr(cfg, "provider", "") == "openrouter":
        return _check_openrouter_ready(cfg)
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


def _check_openrouter_ready(cfg) -> Check:
    check = Check("OpenRouter key + model")
    if not cfg.api_key:
        check.fail("no OpenRouter key: set OPENROUTER_API_KEY or api_key in config/civ6ai.local.json")
        return check
    try:
        models = lmstudio_client.list_loaded_models(cfg, timeout_seconds=20.0)
    except Exception as error:
        check.fail(f"{type(error).__name__}: {error}")
        return check
    row = next((m for m in models if str(m.get("id")) == cfg.model), None)
    if row is None:
        check.fail(f"model {cfg.model} not in OpenRouter's model list")
        return check
    mods = (row.get("architecture") or {}).get("input_modalities") or []
    if cfg.vision and "image" not in mods:
        check.fail(f"{cfg.model} does not accept images; set vision=false or pick a vision model")
        return check
    check.pass_(f"{cfg.model} listed, inputs={','.join(mods)}, parallel seats={cfg.effective_parallel_seats}")
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
            wire_text="A small PNG is attached. Reply with: thought.situation = saw_image\nthought.strategy = ok\n",
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


def _norm_path(value: str) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").lower()


def read_paths_lua(path: Path) -> dict[str, str]:
    """Parse simple `Key = "value"` / `Key = 123` lines of an installed Civ6Ai_Paths.lua."""
    import re

    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = re.match(r'\s*([A-Za-z_]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(-?\d+))\s*,?', line)
        if match:
            values[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
    return values


def _check_live_config(mod_dirs: list[Path] | None = None, civ6ai_root: Path | None = None) -> Check:
    """Installed mod must point at this repo with live sidecar on, matching runtime.json."""
    check = Check("Live config (installed Civ6Ai_Paths.lua + runtime.json)")
    mod_dirs = installed_mod_dirs() if mod_dirs is None else mod_dirs
    if civ6ai_root is None:
        roots = my_games_roots()
        civ6ai_root = roots[0] / "civ6ai" if roots else None
    fix = " -- run: python scripts/install_mod.py"
    if not mod_dirs:
        check.fail("mod not installed" + fix)
        return check
    repo = _norm_path(str(ROOT))
    problems: list[str] = []
    sessions: set[str] = set()
    detail = ""
    for mod_dir in mod_dirs:
        values = read_paths_lua(mod_dir / "InGame" / "Civ6Ai_Paths.lua")
        where = str(mod_dir)
        if _norm_path(values.get("Repo", "")) != repo:
            problems.append(f"{where}: Repo={values.get('Repo', '')!r} (expected this repo)")
        if values.get("SidecarLive") != "1":
            problems.append(f"{where}: SidecarLive is not 1")
        sessions.add(values.get("SessionId", ""))
        seats = values.get("ManagedSeats", "") or "all"
        detail = (
            f"managed_seats={seats} session={values.get('SessionId', '')} "
            f"sidecar_timeout={values.get('SidecarTimeoutSeconds', '')}s"
        )
    runtime: dict = {}
    runtime_path = civ6ai_root / "runtime.json" if civ6ai_root else None
    if runtime_path is None or not runtime_path.is_file():
        problems.append("runtime.json missing")
    else:
        try:
            runtime = json.loads(runtime_path.read_text(encoding="utf-8-sig"))
        except ValueError:
            problems.append(f"{runtime_path}: unreadable")
        if runtime and _norm_path(runtime.get("repo", "")) != repo:
            problems.append(f"runtime.json repo={runtime.get('repo')!r} (expected this repo)")
        if runtime and str(runtime.get("sidecar_live", "0")) not in ("1", "true", "True"):
            problems.append("runtime.json sidecar_live is not 1")
        if runtime and len(sessions) == 1 and runtime.get("session_id") not in sessions:
            problems.append(f"runtime.json session_id={runtime.get('session_id')!r} does not match Civ6Ai_Paths.lua")
    if len(sessions) > 1:
        problems.append("installed mod copies have different SessionId values")
    if problems:
        check.fail("; ".join(problems) + fix)
    else:
        check.pass_(detail)
    return check


def _check_circuit_breakers() -> Check:
    """Report sidecar circuit-breaker counts (informational; never fails preflight).

    Live seats are refused once their count reaches the threshold; dry runs
    ignore the breaker. To reset, set the file contents to {} (or delete it).
    """
    check = Check("Sidecar circuit breaker state")
    dry_run_path = ROOT / "runtime" / "logs" / "circuit_breaker.json"
    lines = [
        circuit_breaker_state.describe(dry_run_path)
        + " (legacy dry-run file; ignored by start_live.py --dry-run, not used by live seats)"
    ]
    roots = [game / "civ6ai" for game in my_games_roots()] + [logs / "civ6ai" for logs in logs_dirs()]
    live_paths = circuit_breaker_state.live_breaker_files(roots)
    if not live_paths:
        lines.append("live sessions: no circuit_breaker.json found")
    opened: list[str] = []
    clear = 0
    for path in live_paths:
        failures, error = circuit_breaker_state.read_failures(path)
        if not error and not any(count > 0 for count in (failures or {}).values()):
            clear += 1  # summarized below; old sessions would otherwise flood the output
            continue
        lines.append(circuit_breaker_state.describe(path))
        for player in circuit_breaker_state.open_players(failures):
            opened.append(f"{player} in {path}")
    if live_paths:
        lines.append(f"live sessions: {len(live_paths)} breaker file(s), {clear} clear")
    detail = "\n       ".join(lines)
    if opened:
        detail += (
            "\n       WARNING: breaker OPEN for " + "; ".join(opened)
            + " -- live sidecar calls for that seat are refused until reset (set the file to {})"
        )
    check.pass_(detail)
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
    checks.append(_check_live_config())
    checks.append(_check_circuit_breakers())

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
