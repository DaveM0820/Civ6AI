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
5. Install the mod into both Mods folders (backs up existing to
   `My Games\...\Civ6Ai_mod_backups`, outside `Mods` so Civ6 never sees a duplicate mod):
   ```powershell
   python scripts\install_mod.py
   # options: --managed-seats 1   (LLM seats; human is seat 0 in SP; default 1)
   #          --sidecar-timeout 600  (seconds per LLM decision; default config timeout_seconds)
   #          --session-id live-...  (default live-<timestamp>)
   ```
   This also generates the installed `Civ6Ai_Paths.lua` / `Civ6Ai_Runtime.lua` (repo path,
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
| `CIV6AI_MP_MOVE_SYNC` | `1` enables M2 chat-bus move sync |
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

## Seat timing (single player, model-driven AI seats)

Civ6 single player runs seats one after another: P0 (the local seat) plays turn N,
ends it, then AI seats 1..4 run their turn N, then P0 turn N+1 starts. The mod
snapshots every managed seat at its own activation, but the host (lua log bridge
-> sidecar -> LM Studio) answers seat by seat, so an AI seat's answer for turn N
arrives while P0 is on turn N+1. The rule:

- **Local seat (P0):** the snapshot, the answer and the apply all happen inside
  P0's turn N (PendingApply entry turn must equal the current game turn). Orders use
  the UI operations path.
- **AI seats (1..4):** snapshot at the turn-N activation (the seat does not wait
  there, `bridge|seat_async`). The answer is published as a PendingApply entry
  `"<player>:turn"` with `turn = N`. At the seat's next activation (turn N+1) the
  bridge applies that entry first (`bridge|pending_apply|...|turn=N|game_turn=N+1`,
  then `pending_apply_ok`), through the GameCore routes
  (`ExposedMembers.Civ6Ai.*ForPlayer`: move, research, civic, skip/fortify, found
  city). Then it takes the turn N+1 snapshot. Commands without a GameCore route
  (production, attack) fail one by one with `*_requires_local_player`.
- **Barrier (autotest):** before P0 ends turn N+1, autotest waits until every AI
  seat's turn-N answer has been delivered (`autotest|seat_barrier_wait` ...
  `seat_barrier_done`), bounded by sidecar timeout x (pending seats + 1). So the
  answers are ready when the AI seats activate. A sidecar failure or an empty
  answer is still published as an empty entry, so the barrier never waits on a
  seat that will not answer.
- **No replays:** each entry carries session, player, turn, kind and an apply id.
  Lua applies an entry only for the matching session and player, only for the turn
  allowed above, and only once per apply id. The file stays on disk, so include()
  re-reading it is harmless. Seats never share an entry.
- **New game = new session:** `scripts/start_live.py` (default) rotates the session
  id in the installed `Civ6Ai_Paths.lua` / `Civ6Ai_Runtime.lua` and `runtime.json`.
  It also archives per-player transient files (decisions, apply files, snapshots,
  markers) into `sessions/<id>/_archive_<stamp>/` and moves the Lua.log offsets to
  the end. Start it **before** starting the new game. Use `--keep-session` only
  to restart helpers for the game already running.

Caveat: the Firaxis AI also plays AI seats. If it moved a unit before the bridge
applied, the move fails with `no_moves_left` and the next snapshot shows the real
state.

**AI-seat unit hold.** The Firaxis AI spends a seat's moves the moment its turn starts, long before the model answers. For model-driven AI seats GameCore `FinishMoves` their movable units (not builders/traders/religious) at `PlayerTurnStarted` and `PlayerTurnStartComplete` (`gamecore|hold_units|...|phase=complete|count=N`) and `RestoreMovement` a held unit once when its model move arrives. Snapshots read unit moves through GameCore (`UnitMovesForPlayer`): held units report full moves and the local seat no longer reads the UI cache's stale 0 at turn start, so `legal_commands` includes moves again.

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
