# Real end-to-end test on David's Windows PC (LM Studio + Civ6)

**Untested in this environment** (no Civ6 binary, no LM Studio). David must run the
commands below on his machine.

Local LLM: LM Studio OpenAI-compatible server (`http://localhost:1234/v1`), Qwen-family
vision model (text + map image).

## 0) One-time setup

1. Clone / pull this branch.
2. Install Python deps:
   ```powershell
   cd <repo>
   python -m pip install -r requirements.txt
   ```
3. Copy config and edit model id to match what LM Studio shows as loaded:
   ```powershell
   copy config\civ6ai.local.example.json config\civ6ai.local.json
   notepad config\civ6ai.local.json
   ```
   Defaults:
   - `endpoint`: `http://localhost:1234/v1`
   - `model`: your Qwen VL id
   - `timeout_seconds`: `600`
   - `vision`: `true`
   - `reasoning`: `on` (sent as LM Studio `reasoning=on|off` — **never** `reasoning_effort=on`)
   - `mp_move_sync`: `false` for SP
4. In LM Studio: start the local server, load the vision model, enable vision.
5. Install the mod into both Mods folders (backs up existing):
   ```powershell
   python scripts\install_mod.py
   ```
6. Preflight (must be all PASS before a live game):
   ```powershell
   python scripts\preflight.py
   ```

### Env overrides (optional)

| Env | Purpose |
| --- | --- |
| `LMSTUDIO_BASE_URL` | Override endpoint |
| `LMSTUDIO_MODEL` | Override model id |
| `CIV6AI_LMSTUDIO_TIMEOUT_SECONDS` | Request timeout (default 600) |
| `CIV6AI_LMSTUDIO_VISION` | `1`/`0` |
| `CIV6AI_LMSTUDIO_REASONING` | `on`/`off` |
| `CIV6AI_MP_MOVE_SYNC` | `1` enables M2 chat-bus move sync |
| `CIV6_INSTALL` | Force Civ6 install root if auto-detect misses |

## 1) Dry-run (no Civ6) — do this first

Runs the full sidecar pipeline against a recorded Civ6 snapshot + **real** LM Studio.

```powershell
python scripts\start_live.py --dry-run
# or a specific snapshot:
python scripts\start_live.py --dry-run --state fixtures\civ6\snapshot-turn-classical-golden.json
```

Pass: JSON decision printed; `runtime/logs/dry_run_journal.jsonl` written; no
`model_unloaded` / empty completion errors.

## 2) SP live test (M0)

1. `python scripts\preflight.py` → all PASS  
2. `python scripts\install_mod.py`  
3. Start workers (**hidden** children — no console spam):
   ```powershell
   python scripts\start_live.py
   ```
4. Launch Civ6 → enable **Civ6Ai** mod → Single Player Quick Live / new game with
   managed AI seat(s) as documented in-game.
5. Watch logs:
   - `%LOCALAPPDATA%\Firaxis Games\Sid Meier's Civilization VI\Logs\Lua.log`
     - expect `apply|ok|…`, `bridge|…`, `inbox|apply_ready`
   - `runtime/logs/job_poller.log`, `runtime/logs/lua_bridge.log`
6. Stop workers when done:
   ```powershell
   python scripts\stop_live.py
   ```

### SP pass criteria

- Sidecar produces a decision each turn for the managed seat  
- Lua.log shows apply success (`apply|ok|move_unit` or `apply|script_move|ok` / probe)  
- No desktop flooded with console windows  
- Game remains playable (no hard freeze from timeouts)

## 3) Two-PC LAN (M1 → M3)

See also `docs/GOALS.md`, `docs/MP_SYNC_TRANSPORT.md`, `docs/civ6_lan_probe.md`.

### M1 — same mod on both PCs

1. Same commit / same `install_mod.py` on host + friend  
2. Preflight PASS on host (friend needs mod install; LM Studio only on host)  
3. Both join LAN; managed seats configured on **host only**

### M2 — move sync MVP

1. On **both** PCs set `mp_move_sync: true` in `config/civ6ai.local.json` **or**
   `CIV6AI_MP_MOVE_SYNC=1` / Paths `MpMoveSync = 1`  
2. Host: `python scripts\start_live.py`  
3. Play turns with LLM `move_unit`  
4. Watch:
   - Lua.log: `CIV6AI|mp_sync_…`, `apply|ok|move_unit`  
   - `OOSLog` / multiplayer OOS lines after turn 1  

### M2/M3 pass criteria

- Units land on the **same plots** host + friend  
- No new OOS after turn 1 for the MVP move set  
- Do **not** treat `local_player_swap_blocked_mp` as success  

## 4) What David must run first (checklist)

```text
[ ] LM Studio running, Qwen vision model LOADED
[ ] python scripts/preflight.py          → all PASS
[ ] python scripts/start_live.py --dry-run → decision JSON OK
[ ] python scripts/install_mod.py
[ ] python scripts/start_live.py         → hidden workers
[ ] Civ6 SP with Civ6Ai enabled          → watch Lua.log
[ ] python scripts/stop_live.py
```

Only after SP works: enable `mp_move_sync` and try LAN.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `model_unloaded` / HTTP 400 | Load the model in LM Studio; match `model` id in config |
| Empty completions with images | Keep `vision: true`; confirm multimodal content (preflight image check) |
| Context overflow | Leave `context_budget: true`; shrink map / lower overview size |
| Desktop covered in consoles | Use `start_live.py` (pythonw + CREATE_NO_WINDOW); never raw `python` loops in Explorer |
| Mod version mismatch | Re-run `install_mod.py` (backs up old Mods\Civ6Ai) |
| Civ6 path not found | Set `CIV6_INSTALL` to Steam common folder (incl. `D:\SteamLibrary\...`) |
