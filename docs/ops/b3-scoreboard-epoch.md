# B3 scoreboard epoch — evidentiary demotion + dual shadow

**Locked:** 2026-10-15 (owner forks **B** + **B3**).  
**Epoch id:** `b3-scoreboard-evidence-v1`  
**Registration:** `docs/data/b3_scoreboard_epoch_registration.json`

## What locked

1. **Demote** `ai_judgment_fair` (3-name sleeve) as *evidentiary* / adoption
   primary. Continuity NAV may continue; **not** filter-skill truth.
2. **Freeze** underpowered 3-name twins `ai_judgment_hold5_fair` and
   `ai_judgment_graduated_fair` (history kept; no rewrite).
3. **Cold-start dual shadow** (neither crowns assessment primary until gates):
   - **N210** fixed-stake AI/filter judgment observe — primary judgment metric =
     fair-cost episode % ([n210-ai-judgment-observe.md](n210-ai-judgment-observe.md))
   - **Matched-30 fund pair** — `ai_judgment_matched30_fair` vs
     `buy_tier_matched30_fair` (fund NAV **only** vs each other)
4. **Anti-C:** do **not** enlarge `max_positions` / `sector_cap` on the live
   3-name book mid-flight.
5. **No back-label** of prior 3-name NAV as evidence for the new epoch.
6. Align **F4** / **F8** / **O3 alone-first** / fixed-stake v0 defaults.

## Assessment model stamps

| Field | Value |
|-------|-------|
| `primary_track` | Still `ai_judgment_fair` (product continuity) |
| Policy | `evidentiary_demotion_ai_judgment_fair_v1` in `policy_changes` |
| Frozen | hold5 + graduated twins → superseded by `ai_judgment_matched30_fair` |
| Twins (shadow) | `ai_judgment_matched30_fair`, `buy_tier_matched30_fair` |

Do **not** switch `primary_track` / `control_track` to the matched-30 pair or
N210 until volume/mark gates clear. Trailing “primary trails control” remains
a **known underpowered** observe signal (**F8**).

## Matched-30 pair

| Track | Parent | Construction |
|-------|--------|--------------|
| `ai_judgment_matched30_fair` | `ai_judgment_fair` | AI/filter knobs; `max_positions=30`; `sector_cap=0.2` |
| `buy_tier_matched30_fair` | `buy_tier_level` | Raw buy-tier; same N / sector_cap |

Both are churn-policy twins (decision-review `--apply` skips). Spawn:
`ftse-trading-costs spawn-matched30-twins` (idempotent). Full
`buy_tier_level` stays strand-A / diversified diagnostic — **not** the paired
filter control for the 30-name sleeve.

## Apply helper

```bash
python -c "from value_investor.b3_epoch import apply_b3_lock; print(apply_b3_lock())"
```

Idempotent per policy id / freeze / spawn / N210 refresh.

## Human gates

- `adhoc-assessment-model-change` — still the freeze/switch path
- `adhoc-n210-volume-gate-review` — judgment observe volume
- `sunday-matched30-twins` — matched pair NAV (not vs full buy-tier as skill)
- `sunday-assessment-scoreboard` — demoted 3-name primary wording. The trail warn is not Push while the demotion stamp is present; outstanding crown waits on volume gates (Later chip).

## Related

- [assessment-scoreboard.md](assessment-scoreboard.md)
- [primary-learning-track.md](primary-learning-track.md)
- [fair-cost-primacy.md](fair-cost-primacy.md)
- [n210-ai-judgment-observe.md](n210-ai-judgment-observe.md)
