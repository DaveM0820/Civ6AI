# Goals — Civ6 LLM AI

Milestones toward live LAN MP with LLM unit commands (David + friend).

## M0 — Re-confirm single-player works

- SP QuickLive shows `apply|probe|move|ok` or `apply|script_move|ok` in Lua.log
- Sidecar can inject pending Apply and see `inbox|apply_ready` / `apply|ok|…`
- With `CIV6AI_MP_MOVE_SYNC` **off**, SP Apply ladder unchanged after M2 land
- Workspace seeded; mod working copy under `mod/Civ6Ai`

## M1 — Same mod on friend’s PC

- Identical Civ6Ai mod version on both PCs (`scripts/install_mod.py` / `.ps1`)
- Both join a LAN session; managed AI seats configured on host only
- No requirement yet for LLM moves to sync — baseline connectivity + mod parity

## M2 — Sync MVP for unit moves

- Host sidecar issues `move_unit` for managed seats
- Flag `CIV6AI_MP_MOVE_SYNC=1`: all-client GameCore move via chat broadcast
  (see `docs/MP_SYNC_TRANSPORT.md`)
- Units land on the **same plots** on host and friend
- No new OOS after turn 1 for MVP move set
- Explicit: do not treat `local_player_swap_blocked_mp` as success
- In-game probe hook: `CIV6AI|mp_sync_probe|player|unit|x|y`
- **Untested in this environment** — David verifies on two PCs

## M3 — LAN soak against probe criteria

- Multi-turn soak per `docs/civ6_lan_probe.md` (~20 turns)
- Pass: no new OOS lines after turn 1; host `bridge|inbox_apply_done` +
  `apply|ok|move_unit`; plot parity both clients
- Document which transport actually passed (chat-bus GameCore vs fallback)

## M4 — More operations

- Beyond MVP moves: attacks, builds/improvements, city production, research, etc.
  as the sync path allows (extend broadcast kinds or switch to engine-synced ops)
- Harden install + version sync between PCs
- Keep SP regression green while expanding MP surface

## Out of scope (for now)

- Replacing civ5-llm-ai or civ4ai trees
- Overwriting live Mods without an explicit install script run
- Claiming MP works without a two-PC probe
