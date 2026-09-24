# MP sync transport — unit moves (M2)

How an LLM move order issued on the **host** can be applied **identically on every
client** without Out-Of-Sync (OOS). Companion to `MP_UNIT_COMMANDS.md` and
`civ6_lan_probe.md`.

**Status:** design + flagged implementation landed in-repo. **Not verified in Civ6.**
David must confirm on two PCs (see verification steps below).

---

## Problem (root cause)

Civ6 multiplayer is lockstep: each PC runs the same simulation. A mutation that
happens on one machine only produces checksum mismatch → `Out Of Sync` in
`OOSLog.log`.

Today’s Apply ladder (`Civ6Ai_Apply._MoveUnit`):

1. InGame `UnitManager.RequestOperation(MOVE_TO)` (probe)
2. GameCore `ExposedMembers.Civ6Ai.MoveUnitForPlayer` (`script_move`)
3. SP-only local-player swap → in network MP returns `local_player_swap_blocked_mp`

The bridge / sidecar run **host-only** (`Civ6Ai_Config.ShouldRunBridge` +
`Network.IsSessionHost`). Host-only GameCore/UI mutation therefore moves the unit
on the host and not on the friend → OOS risk. SP success does **not** imply MP
safety.

---

## Options investigated

Evidence levels: **strong** (in this repo’s Lua), **medium** (repo docs + community
practice), **weak** (named only / unproven), **speculation**.

| # | Option | Mechanism | Evidence | MP / no-OOS outlook | Notes |
|---|--------|-----------|----------|---------------------|-------|
| 1 | Host-only InGame `RequestOperation` | Host Apply rung 1 | **Strong** (code; SP probe ok) | **Fails design** if host-only | UI-context op; AI seats often need local player |
| 2 | Host-only GameCore `MoveUnitForPlayer` | `UnitManager.RequestOperation` / `MoveUnit` in Gameplay | **Strong** as SP fallback API | **Fails design** if host-only | Same process bridge; clients never see call |
| 3 | SP local-player swap | `SetLocalPlayerAndObserver` | **Strong** blocked in MP | **No** | Marker: `local_player_swap_blocked_mp` |
| 4 | **All-client GameCore move** (chosen) | Every client runs the same `MoveUnitForPlayer` | **Medium** as strategy (docs + MP-safe coding rules); **strong** that identical Gameplay mutations are required | Intended M2 path | Needs a mid-game **intent** bus |
| 4a | Intent via `Network.SendChat` + `Events.MultiplayerChat` | Encode `CIV6AI\|mp_move\|…`; all InGame listeners execute GameCore move | **Strong** channel exists in `Civ6Ai_Chat.lua`; **medium** that chat timing is sim-safe enough for moves | MVP under flag | Chat is not a Firaxis unit opcode; timing risk |
| 4b | `EXECUTE_SCRIPT` broadcast | Docs name an engine script-exec broadcast | **Weak / speculation** — **no** binding or call site in seed Lua | Unknown | Treat as hypothesis to probe later, not assumed API |
| 5 | Engine-synced player/unit ops (`Game.Send*` / `UI.RequestPlayerOperation`) | Ops that the net stack replicates | **Weak** (research backlog Phase D); not used for AI seats in seed | Attractive if proven for non-local seats | Prefer if LAN shows chat bus OOSes |
| 6 | Host Apply + forced resync | Host mutates; engine reloads state | **Weak** (docs fallback) | Last resort | Not for soak |
| 7 | Community Extension / CE fork | Custom DLL hooks | **Weak** (docs fallback; plan: don’t bundle) | Unknown / heavy | Fallback if stock Lua cannot stay in sync |
| 8 | Per-client sidecar Apply | Friend also applies LLM JSON | **Rejected** | Would diverge | Host-only sidecar is intentional |

Community constraint (CivFanatics): gameplay-changing Lua must run from **synced**
contexts on every machine (same events, no UI-only triggers, no `math.random`).
`LuaEvents` / `ExposedMembers` alone do **not** cross the network — they only
bridge contexts **inside one process**.

---

## Recommendation (M2)

**Primary (implemented behind flag):** all-client GameCore `MoveUnitForPlayer`, with
move **intent** delivered by `Network.SendChat` and received on every client via
`Events.MultiplayerChat`.

Why this over alternatives:

- Matches the required property: **identical mutation on every PC**.
- Reuses a network channel already proven in this mod (`Network.SendChat`,
  `Events.MultiplayerChat`, `CIV6AI|` prefix filtering in chat).
- Does not depend on an unverified `EXECUTE_SCRIPT` API.
- Keeps the SP Apply ladder untouched when the flag is off or the session is SP.

**Honest caveats:**

- Chat is a UX/network message, not a documented unit-command opcode. Arrival
  order vs other sim work could still OOS — **LAN probe is mandatory**.
- `UnitManager` from GameCore is already used for SP `script_move`; community
  guidance prefers InGame for UI ops. We accept that tension under an explicit MP
  flag and will revisit if probe fails.
- Seat type (AI vs human — Gate 2) remains a separate open question.

**Fallback if OOS on unit moves:** CE / custom engine path, or re-probe
engine-synced ops (`Game.Send*` / player operations for non-local seats). Host-only
Apply + forced resync is last resort only.

---

## Flag and wire format

| Item | Value |
|------|--------|
| Flag | `CIV6AI_MP_MOVE_SYNC=1` via `GameConfiguration`, or `Civ6Ai_Paths.MpMoveSync = 1`, or Runtime |
| Module | `mod/Civ6Ai/InGame/Civ6Ai_MpSync.lua` |
| Active when | flag on **and** `GameConfiguration.IsNetworkMultiplayer()` |
| SP | Existing RequestOperation → GameCore → local-swap ladder **unchanged** |

Wire (public chat, ignored by LLM chat handler because of `CIV6AI|` prefix):

```text
CIV6AI|mp_move|<seq>|<playerID>|<unitNumericId>|<x>|<y>
```

LAN / inbox probe (host inbox or chat):

```text
CIV6AI|mp_sync_probe|<playerID>|<unitNumericId>|<x>|<y>
```

Host path: validate unit exists → `BroadcastMove` → `Network.SendChat` → host
`ExecuteMove` immediately; clients execute on `MultiplayerChat`; seq dedupes echo.

---

## Log markers (LAN)

| Marker | Where | Meaning |
|--------|-------|---------|
| `mp_sync\|ready\|enabled=…\|active=…` | both | Module initialized |
| `config\|…\|mp_move_sync=true` | both | Flag seen |
| `apply\|mp_sync\|enqueue\|…` | host | Intent broadcast |
| `apply\|mp_sync\|exec\|ok\|…` | **both** | GameCore move applied |
| `apply\|mp_sync\|ok\|…` then `apply\|ok\|move_unit` | host | Apply recorded success |
| `apply\|mp_sync\|probe\|…` | both | Probe hook fired |
| `local_player_swap_blocked_mp` | — | Must **not** be treated as success |

---

## What David must verify (two PCs)

Cannot be claimed from this environment (no Civ6).

1. **M0** — SP still shows `apply|probe|move|ok` or `apply|script_move|ok` with flag **off**.
2. **M1** — Identical mod on both PCs (`scripts/install_mod.py`).
3. **M2 probe** — LAN game, flag **on**, managed AI seats on host only:
   - Inject `CIV6AI|mp_sync_probe|<player>|<unit>|<x>|<y>` on host (inbox or chat).
   - Both Lua.logs: `apply|mp_sync|exec|ok|…` with same plot.
   - No new `Out Of Sync` in either `OOSLog.log`.
4. **M2 live** — Host sidecar Apply for a move; host shows `apply|ok|move_unit` and
   `apply|mp_sync|…`; friend shows `exec|ok`; unit plots match; no new OOS after turn 1
   (`docs/civ6_lan_probe.md`).

If probe OOSes: do **not** paper over it — capture OOSLog diffs and evaluate fallback
(engine-synced ops or CE).
