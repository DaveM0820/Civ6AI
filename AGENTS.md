# AGENTS.md — rules for coding agents on Civ6AI

This repo is public. Future agents may be smaller/cheaper models: follow these
rules literally. Verify paths and callers before editing.

## Project

- Civ6Ai = a Civ6 Lua mod under `mod/Civ6Ai/` plus a Python sidecar under `sidecar/` that builds prompts from game snapshots, calls a local LLM, parses orders, and hands them back to Lua to Apply.
- Local LLM default: LM Studio OpenAI-compatible server at `http://localhost:1234/v1` (see `config/civ6ai.local.example.json`, `sidecar/civ6_config.py`, `sidecar/lmstudio_client.py`).
- Goal: LLM-controlled civs in Civ6 LAN multiplayer with a friend, with unit commands that do not desync (OOS).
- Before changing related areas, read: `docs/GOALS.md`, `docs/MP_SYNC_TRANSPORT.md`, `docs/REAL_TEST.md`, `docs/CIV5_TO_CIV6_PORT.md`, `docs/MP_UNIT_COMMANDS.md`.
- Layout: `mod/Civ6Ai/` (Lua/XML), `sidecar/` (wire/adapter/map/runner/tests), `scripts/` (install, preflight, live start/stop), `config/`, `fixtures/`, `schemas/`, `docs/`.

## Honesty

- You cannot run Civ6 or LM Studio in the cloud VM. Never claim in-game, LAN, or live-LLM behavior works.
- Label everything **untested in-game** unless David reported a real test on his PC.
- Never invent Civ6 Lua API functions. If unsure a function exists or is callable from a given context (gameplay vs UI), say so, cite where you saw it (repo code, Firaxis files, docs), and guard the call with a nil check and a logged fallback.
- Report exact test commands and pass/fail counts you actually ran. Do not summarize failures as passes.

## Scope and workflow

- Do only the task asked. No drive-by refactors, renames, reformatting of unrelated files, or dependency upgrades.
- Read the relevant files fully before editing. Search for all callers before changing a function signature.
- Keep changes small and reviewable; one PR per task; clear PR description with what changed, what was tested offline, and what David must test on his PC.
- Run offline tests before finishing:
  ```bash
  PYTHONPATH=. python3 -m unittest discover -s sidecar/tests -v
  ```
- Add or update tests for any wire / prompt / parse / config change (`sidecar/tests/`, golden fixtures under `fixtures/civ6/` when prompts change).
- Fix root causes in durable code. No one-off hacks or special-casing a single save or turn.
- Do not delete files or tests to make the suite pass.
- Prefer soft coaching in prompts over hard rules (see Prompt design rules).

## Safety and privacy (repo is PUBLIC)

- Never commit secrets, API keys, `.env` files, personal absolute paths with usernames beyond documented defaults, session logs, saves, raw prompt/response dumps, or large generated images.
- Never commit third-party source (e.g. Vox Populi / Community Patch DLL, civ6-mcp) into the repo.
- Keep `.gitignore` covering `sessions/`, `logs/`, `map_images/`, `memory/`, `runtime/`, `__pycache__/`, `config/civ6ai.local.json`, and Community Patch / Vox Populi cache paths.
- Copy `config/civ6ai.local.example.json` → `config/civ6ai.local.json` for local machine settings; do not commit the local copy.

## Windows / David's PC

- David runs Windows. Any process scripts launch must be hidden: `pythonw` or `creationflags=CREATE_NO_WINDOW` (`scripts/windows_process.py`). Never open visible console/PowerShell windows; many windows make his desktop unusable.
- Use `scripts/start_live.py` / `scripts/stop_live.py` (and `.ps1` wrappers) for live workers; prefer those over ad-hoc `python` loops in Explorer.
- Paths contain spaces and an apostrophe (`Sid Meier's Civilization VI`); always use `pathlib` and never build shell strings with unquoted paths.
- Civ6 may live in any Steam library (e.g. `D:\SteamLibrary`). Detection helpers: `scripts/civ6_paths.py`. Override with `CIV6_INSTALL` if needed.
- My Games may be under `OneDrive\Documents` or `Documents`; install into both Mods folders when present (`scripts/install_mod.py`).
- Console encoding may be cp1252; do not print non-ASCII symbols in scripts meant for Windows consoles.

## Multiplayer sync rules

- Anything that changes game state in MP must execute identically on every client (e.g. the `CIV6AI_MP_MOVE_SYNC` path in `mod/Civ6Ai/InGame/Civ6Ai_MpSync.lua`) or it will desync (OOS). Never apply game-state changes on the host only.
- The single-player local-player swap is blocked in network MP (`local_player_swap_blocked_mp`); do not try to re-enable it.
- Keep the single-player Apply ladder working when MP flags are off.
- New MP behavior goes behind a config flag, default **off** until David verifies on two PCs (`mp_move_sync` in local config / `CIV6AI_MP_MOVE_SYNC` / `Civ6Ai_Paths.MpMoveSync`).
- LAN pass criteria: no new `OOSLog` lines after turn 1, identical unit positions on both PCs, host log shows `apply|ok|move_unit`. See `docs/civ6_lan_probe.md` and `docs/REAL_TEST.md`.

## LM Studio rules

- Send reasoning as `on`/`off` only; never send `reasoning_effort=on` (LM Studio rejects it). Implementation: `sidecar/lmstudio_client.py` / `sidecar/civ6_config.py`.
- Multimodal: separate `text` and `image_url` content parts in chat messages.
- Use long timeouts (~600s) with retries; seats share one model via a queue/lock; clear error on model unloaded (`model_unloaded`).
- Always fit the prompt inside the loaded model's context window (`sidecar/context_budget.py`, situational maps in `sidecar/map_situational.py`); never rely on server-side truncation.
- Preflight before live play: `python scripts/preflight.py`. Dry-run without Civ6: `python scripts/start_live.py --dry-run`.

## Prompt design rules

- Prompt guidance is soft coaching, not hard rules. Do not add ranked “best move” hints or tile rankings; give the model facts and let it decide.
- Required commands are numbered and counted; the model may issue as many optional commands as it likes (`sidecar/civ6_prompt_coaching.py`, `sidecar/civ6_wire.py`).
- Only list legal options (legal targets, legal moves); never show an option the engine will reject.
- Keep terminology consistent between the prompt, the parser, and the Lua Apply layer; when you add a command, update all three plus tests and capabilities JSON under `config/` when applicable.
- State map orientation (which axis is N/S/E/W) and wrap behavior accurately for Civ6 hex grids.
- No ranked settle overlays on the map (`collect_settle_markers` stays empty); coach settlers via soft text only.

## Commit hygiene

- Use descriptive commit messages.
- Do not force-push to `main`.
- Do not merge PRs yourself.
- Do not commit `config/civ6ai.local.json`, `runtime/`, session dumps, or third-party caches.
