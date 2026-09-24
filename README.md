# Civ6AI

LLM-driven **Civilization VI** mod: Lua gameplay mod (`mod/Civ6Ai`) plus a Python
sidecar that renders game state / map, calls a local LLM (e.g. LM Studio), and
feeds validated orders back for the mod to Apply.

**Primary goal:** LAN multiplayer with LLM-controlled civs (host runs the sidecar;
friend has the same mod).

**Working today (SP):** Apply / probe path (`apply|probe|move|ok`,
`apply|script_move|ok`).

**Active workstream:** MP unit-command sync without OOS. See
`docs/MP_SYNC_TRANSPORT.md` and `docs/MP_UNIT_COMMANDS.md`.

## Layout

```
mod/Civ6Ai/     # Civ6 Lua/XML mod
sidecar/        # Python wire, adapter, map render, runner, tests
docs/           # Goals, MP notes, research copies, LAN probe
scripts/        # install_mod helpers
```

## Install mod

```powershell
python .\scripts\install_mod.py
# or
powershell -File .\scripts\install_mod.ps1
```

Copies `mod\Civ6Ai` into your Civ6 `Mods\Civ6Ai` folders (Documents / OneDrive
My Games paths). Prefer a non-OneDrive Mods folder if file locking is an issue.

## Sidecar (high level)

- `sidecar/run_civ6.py` — entry
- `sidecar/civ6_wire.py` / `civ6_adapter.py` — prompt + state adaptation
- `sidecar/map_render_civ6.py` — map image for the model

Point the LLM client at your local server (e.g. LM Studio). Do not commit API keys;
use env vars (`.env` is gitignored).

## Milestones

See `docs/GOALS.md` (M0 SP → M1 same mod → M2 move sync → M3 LAN soak → M4 more ops).

### M2 flag (unit move sync)

In network MP, set **`CIV6AI_MP_MOVE_SYNC=1`** (GameConfiguration) or
`MpMoveSync = 1` in generated `Civ6Ai_Paths.lua`. When active, `move_unit` uses
all-client GameCore apply via a `Network.SendChat` bus — **not verified in-game
here**. SP with the flag off keeps the existing ladder.

LAN probe: `docs/civ6_lan_probe.md`. Pass = no new OOS, identical unit plots,
host `apply|ok|move_unit`.

## Tests

From repo root (after `pip install -r requirements.txt`):

```bash
PYTHONPATH=. python3 -m unittest discover -s sidecar/tests -v
```

Shared fixtures/schemas/testbed modules from the incubator tree are included so the
Civ6 sidecar suite can run offline. See `docs/CIV5_TO_CIV6_PORT.md` for Civ5→Civ6
prompt ports and before/after counts.

**In-game Civ6 play and MP sync remain unverified here** (no Civ6 binary in CI).

## Public repo note

This repository is public. Do not commit session logs, `map_images/`, `.env`,
Community Patch / Vox Populi caches, or machine-specific secrets. `.gitignore`
already covers the common runtime paths.

