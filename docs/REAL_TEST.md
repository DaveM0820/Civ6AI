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
4. In LM Studio: start the local server, load the vision model, enable vision.
5. Install the mod into both Mods folders (backs up existing to
   `My Games\...\Civ6Ai_mod_backups`, outside `Mods` so Civ6 never sees a duplicate mod):
   ```powershell
   python scripts\install_mod.py
   # options: --managed-seats 1   (LLM seats; human is seat 0 in SP; default 1)
   #          --sidecar-timeout 600  (seconds per LLM decision; default config timeout_seconds)
   #          --session-id live-...  (default live-<timestamp>)
   ```
   This also generates the installed `Civ6Ai_Paths.lua` (repo path,
   python, `SidecarLive=1`, managed seats, session, timeout) and
   `My Games\...\civ6ai\runtime.json` for the host bridge (old file backed up).
   Re-run it whenever you move the repo or want different seats. `--stub-only` skips this.
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
| `CIV6_INSTALL` | Force Civ6 install root if auto-detect misses |

## 1) Dry-run (no Civ6) — do this first

Runs the full sidecar pipeline against a recorded Civ6 snapshot + **real** LM Studio.

```powershell
python scripts\start_live.py --dry-run
# or a specific snapshot:
python scripts\start_live.py --dry-run --state fixtures\civ6\snapshot-turn-classical-golden.json
```

Pass: exit code 0 and a final `DRY-RUN PASS: model=... commands=N` line;
`runtime/logs/dry_run_journal.jsonl` written; no `model_unloaded` / empty completion errors.
Any fallback / transport error (e.g. LM Studio not running) prints
`DRY-RUN FAIL: <reason>` and exits 1. Use `--timeout <seconds>` to cap the wait.
Dry runs neither enforce nor update the sidecar circuit breaker; `preflight.py`
reports breaker counts (reset a live seat by setting its `circuit_breaker.json` to `{}`).

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

### M2 — AI seat orders over the synced channel

No flag: in a network game the host's AI-seat orders always go through the
synced order channel. Humans are never managed seats in a network game.
1. Host: `python scripts\start_live.py`  
2. Play turns; the host's AI chat panel shows "All AI orders are in" before you end the turn  
3. Watch:
   - Lua.log: `CIV6AI|orders|queued|...`, `CIV6AI|orders|queue_apply|...`, `CIV6AI|orders|result|...`  
   - `CIV6AI|orders|sync|...|verdict=match` (each PC reports its checksum every turn)  
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

Only after SP works: try LAN.

## Seat timing (single player, model-driven AI seats)

Civ6 single player runs seats one after another: P0 (the local seat) plays turn N,
ends it, then AI seats 1..4 run their turn N, then P0 turn N+1 starts. The mod
snapshots every managed seat at its own activation, but the host (lua log bridge
-> sidecar -> LM Studio) answers seat by seat, so an AI seat's answer for turn N
arrives while P0 is on turn N+1. The rule:

- **Local seat (P0):** the snapshot, the answer and the apply all happen inside
  P0's turn N (PendingApply entry turn must equal the current game turn). Orders use
  the UI operations path.
- **AI seats (1..4):** snapshot at the turn-N start, after the seat's queued
  orders ran (the seat does not wait there, `bridge|seat_async`). The answer is
  published as a PendingApply entry `"<player>:turn"` with `turn = N`; the bridge
  sends it as soon as it lands (`bridge|seat_decision_sent|...|snapshot_turn=N`)
  as one batch on the synced order channel for turn N+1. Every PC keeps it as the
  seat's order queue (`orders|queued|player=P|for_turn=N+1`) and plays it at the
  seat's turn N+1 start with full movement, with retry passes
  (`orders|queue_apply`), then ends the turn of the units the model left in place
  (builders, traders and religious units stay with the game's AI). Only then is
  the turn N+1 snapshot taken. Commands without a gameplay route (city production,
  policies, governors) fail one by one with a plain reason.
- **Barrier (autotest):** before P0 ends turn N+1, autotest waits until every AI
  seat's turn-N answer has been sent or given up on (`autotest|seat_barrier_wait`
  ... `seat_barrier_done`), bounded by sidecar timeout x (pending seats + 1). The
  host's AI chat panel says the same thing to a human player ("All AI orders are
  in"). A seat with no orders when its turn starts is played by the game's AI.
- **No replays:** each entry carries session, player, turn, kind and an apply id.
  Lua applies an entry only for the matching session and player, only for the turn
  allowed above, and only once per apply id. The file stays on disk, so include()
  re-reading it is harmless. Seats never share an entry.
- **New game = new session:** `scripts/start_live.py` (default) rotates the session
  id in the installed `Civ6Ai_Paths.lua` and `runtime.json`.
  It also archives per-player transient files (decisions, apply files, snapshots,
  markers) into `sessions/<id>/_archive_<stamp>/` and moves the Lua.log offsets to
  the end. Start it **before** starting the new game. Use `--keep-session` only
  to restart helpers for the game already running.

**Planning with full movement.** Because an AI seat's orders play at its next turn start, its snapshot reports every unit's full movement (`UnitMovesForPlayer(..., planning)`), and `legal_commands` are checked against full movement too. Untested: whether the game's AI can still move a seat's units between `PlayerTurnStartComplete` and the queue running.

**Turn timer must be off.** In Advanced Setup set the MP_helper "Smart-Timer" option to off/None. With "Smart-Timer: Classic" the game ends the local seat's turn after ~60 s regardless of the model, so answers (1-2 min per seat) arrive stale (`pending_apply_stale_turn`, `inbox_wait_abandoned`). `start_live --keep-session` no longer clears queued PendingApply answers, and Enter nudges are only sent while the local seat's turn is still active.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `model_unloaded` / HTTP 400 | Load the model in LM Studio; match `model` id in config |
| Empty completions with images | Keep `vision: true`; confirm multimodal content (preflight image check) |
| Context overflow | Leave `context_budget: true`; shrink map / lower overview size |
| Desktop covered in consoles | Use `start_live.py` (pythonw + CREATE_NO_WINDOW); never raw `python` loops in Explorer |
| Mod version mismatch | Re-run `install_mod.py` (backs up old Mods\Civ6Ai) |
| Civ6 path not found | Set `CIV6_INSTALL` to Steam common folder (incl. `D:\SteamLibrary\...`) |
