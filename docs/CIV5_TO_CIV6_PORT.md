# Civ5 → Civ6 prompt/play port

Port of David’s local Civ5 LLM improvements into Civ6. Soft coaching only.
**Untested in-game** in this environment (no Civ6 runtime).

## Test suite (sidecar/tests)

| Stage | Ran | Result |
| --- | ---: | --- |
| Before gaps restore | 25 | 7 ok, 2 FAIL, 13 ERROR, 3 skipped |
| After gaps restore (pre-port) | 153 | ~140 ok, 2 FAIL, 8 ERROR, 3 skipped |
| After Civ5→Civ6 ports + settle-policy test fix | 163 | OK (3 skipped) |

## Ported items

| Item | Civ5 source | Civ6 location | Status |
| --- | --- | --- | --- |
| REQUIRED thought rows (`strategicmap.read`, `tacticalmap.read`, `thought.situation`, `thought.strategy`) before event logs/orders; `thought.freethinking` optional | `sidecar/civ5_wire.py` required-command builder | `sidecar/civ6_prompt_coaching.py`, `sidecar/civ6_wire.py` | **ported** |
| Soft advice: issue as many optional commands as wanted (incl. chat) | civ5_wire optional preamble | `civ6_optional_commands_preamble_lines` | **ported** |
| Map orientation (Y south / X wrap example) | civ5_wire axes note | `civ6_map_axes_wrap_guidance` (Civ6 hex Y-south) | **adapted** |
| EMPIRE explored % + ATTENTION if stale exploration &lt;90% | Snapshot + wire ATTENTION | `Civ6Ai_Snapshot.lua` `explored_percent`; `civ6_exploration_attention` | **ported** |
| Unit/city HP % only when &lt;100 | civ5_wire unit lines | `civ6_wounded_hp_label` + Snapshot `health_percent` | **ported** |
| At war: attack options appended on required-order lines (no `| none`, legal targets only) | civ5_wire attack append | `append_attack_options_to_unit_line`, `civ6_attack_option_tokens_for_unit` | **adapted** (Civ6 uses `attack_target` for melee+ranged) |
| Combat damage estimates on attack options | Snapshot `combat_previews` | coaching reads `strategic_summary.combat_previews` | **adapted** / needs Lua fill (see gaps) |
| ATTENTION: retreat &lt;30% HP; focus-fire; leftover move+attack | civ5_wire ATTENTION | `collect_civ6_attention_items` | **ported** |
| Stacking advice | Civ5 1UPT note | Civ6 formation stacking soft coaching | **adapted** |
| Settling: no ranked overlays; soft map coaching when settler present | civ5 settle policy + empty markers | `collect_settle_markers`→`[]`; settler soft-coach in wire | **ported** |
| Promotions required when pending | civ5 promote legal/required | Snapshot `promotion_ready`; wire required promote rows | **adapted** (`promotion_ids` still empty — see gaps) |
| Parser: rangedAttack not dropped | civ5 bind rangedAttack | `_command_matches_unit_property` accepts `rangedAttack` for Civ6 `attack_target` | **ported** |
| Move-retry until plot_occupied full-pass fails | civ5_move_retry / Apply | `Civ6Ai_Apply.lua` multi-pass retry | **ported** (MP sync path unchanged) |
| Bankruptcy / amenities warnings | happiness ATTENTION | gold GPT + amenities net ATTENTION | **adapted** (amenities = Civ6 happiness) |
| Diplomacy deal syntax + DM/chat guidance | civ5 diplo coaching | `civ6_diplomacy_guidance` | **adapted** |
| Context budget + strategic/tactical map windows | `context_budget.py`, `map_situational.py`, `run_civ5.py` | modules restored; `prepare_civ6_situational_maps`; wired in `run_civ6.py` | **ported** |
| Multi-image model attachments | pipeline `normalize_image_attachments` | `pipeline_v2.normalize_image_attachments` + call paths | **ported** |
| CIV6AI_MP_MOVE_SYNC / SP ladder | n/a | unchanged | **preserved** |

## Lua / data fields Civ6 still needs

| Field | Why | Notes |
| --- | --- | --- |
| `strategic_summary.combat_previews[]` (`attacker_unit_id`, `target_x/y`, `damage_to_enemy`, `damage_to_self`, `prediction`) | Decisive victory/defeat labels on attack options | Sidecar ready; Snapshot does not populate yet |
| `your_units[].promotion_ids` | List legal promotions when `promotion_ready` | Currently `{}`; need Civ6 promotion enum/API |
| Per-civ tradeable inventory richness | Diplo haggling inventories | Schema present; Snapshot may under-fill vs Civ5 |
| City defense HP separate from garrison | City HP&lt;100 line fidelity | Partial via city health if exposed |

## Explicitly not committed

- `artifacts/cache/Community-Patch*` / Vox Populi (third-party)
- `cp-overlay/` Civ5 DLL overlay (Civ5-only)
- Runtime `memory/`, sessions, map_images
