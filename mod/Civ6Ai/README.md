# Civ6Ai Workshop Mod

Host-authoritative LLM AI pulse for Civilization VI. Pairs with `sidecar/run_civ6.py`.

## Install

1. Run `scripts/testbed/Invoke-Civ6AiSyncAndTest.ps1` (offline tests + mod sync), or `Invoke-Civ6AiModSync.ps1` alone.
2. Enable **Civ6Ai** in Mods → Additional Content, start a **new** game.
3. Place API keys in `civ6ai/host.env` (see `fixtures/civ6/host.env.example`).

## Automated testing

| Script | What it does |
|--------|----------------|
| **`Invoke-Civ6AiSyncAndTest.ps1`** | **Default workflow:** offline tests + mod sync; `-Live` / `-QuickLive` for in-game autotest |
| `Invoke-Civ6AiOfflineTests.ps1` | All `test_civ6*.py` unit tests (no game) |
| `Invoke-Civ6AiConfigure.ps1` | Sync mod, bootstrap `host.env` |
| `Invoke-Civ6AiLaunch.ps1` | Launch via Steam; optional wait for process |
| `Invoke-Civ6AiSmoke.ps1` | Offline tests + configure; `-WithGame` launches Civ6 |
| `Invoke-Civ6AiSeatExperiment.ps1` | Gate 2 harness with `-SeatExperiment` sync + session watch |

```powershell
# Default after Civ6 changes (offline tests + sync mod into game Mods folder)
.\scripts\testbed\Invoke-Civ6AiSyncAndTest.ps1

# In-game autotest after bridge / turn / chat changes
.\scripts\testbed\Invoke-Civ6AiSyncAndTest.ps1 -Live -SidecarLive -KillExisting

# Faster live smoke (5 turns)
.\scripts\testbed\Invoke-Civ6AiSyncAndTest.ps1 -QuickLive -SidecarLive -KillExisting

# CI / dev — offline only
.\scripts\testbed\Invoke-Civ6AiOfflineTests.ps1

# Launch game to main menu
.\scripts\testbed\Invoke-Civ6AiSmoke.ps1 -WithGame -KillExisting
```

## Gate 2 — seat-type experiment

Set `CIV6AI_SEAT_EXPERIMENT=1` in Advanced Setup, or sync with:

```powershell
.\scripts\testbed\Invoke-Civ6AiModSync.ps1 -SeatExperiment
```

1. Queues a distinctive capital build (Monument → Granary → Settler fallback) via sidecar.
2. Logs production at `turn_start`, `post_llm_apply`, and `post_native_ai` (`PlayerTurnActivated`).
3. Writes `civ6ai/sessions/{id}/PLAYER_N/seat-experiment.jsonl`.

Analyze after a 10–20 turn SP game with one managed AI major:

```powershell
python scripts/testbed/civ6_seat_experiment_analyze.py "%USERPROFILE%\Documents\My Games\Sid Meier's Civilization VI\civ6ai\sessions\default\PLAYER_1\seat-experiment.jsonl"
```

Verdict drives architecture: keep AI seats + re-apply production, or hybrid native unit fallback only.

## Gate 0 behavior

- Hooks `PlayerTurnStartComplete` for managed AI majors.
- Writes `civ6ai/sessions/{id}/snapshot.json`, spawns `run_civ6.py`.
- Python mirrors `decision.json` / `apply_commands.json` into `Logs/civ6ai/` for InGame Lua to read.
- On sidecar timeout or I/O failure: empty apply → native Firaxis fallback (no crash).
- Logs to `Logs/Lua.log` with prefix `CIV6AI|`.

## MP

Sidecar runs **host-only**. Clients need the same mod hash; only the host spawns the Python sidecar.
