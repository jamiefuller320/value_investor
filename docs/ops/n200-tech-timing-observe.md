# N200 tech-timing observe (sealed)

**registration_id:** `strand-b-plain-value-tech-timing-v0`  
**deferred:** N200  
**Mode:** observe-only — never writes strand A books, knobs, or `decision-review --apply`

## Learning question

On threshold-eligible names, does **raw buy-tier** identity with calendar **±14d** entry/exit timing brackets beat default timing (offset 0) on cost-aware **`smooth_ret_cohort_median`**?

## Seal defaults (O2–O6)

| ID | Choice |
|---|---|
| O2 identity | `raw_buy_tier` |
| O3 volume gate | ≥24 completed entry episodes **and** ≥8 calendar weeks |
| O4 smoother | `smooth_ret_cohort_median` |
| O5 primacy | Absolute smoothed return **primary**; control excess **report-only** |
| O6 phase floor | 5 entries/week (illustrative) |

Amend only via logged change marker or new registration.

## When it runs

| Trigger | Schedule |
|---|---|
| **Daily ops-monitor** | `check_n200_tech_timing_observe` refreshes store |
| Manual | `ftse-n200-tech-timing --output-dir docs/data` |

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n200_tech_timing_registration.json` | Frozen seal record |
| `docs/data/n200_tech_timing_observe.json` | Bracket scoreboard + markers + phase/volume |
| This doc | Runbook |

Stores commit via ops-monitor `GHA_COMMIT_OPTIONAL`.

## Scoreboards

1. **Path** — control cell `entry_+0__exit_+0` absolute median (primary).
2. **Per-lever** — entry offsets with control exit; exit offsets with control entry (independent of path P&L).
3. **Phase** — entries/week vs sealed floor.
4. **Diagnostics** — full cell matrix + best-cell (not a promote signal; F8).

## Constraints

- No live strand A writes; no `--apply`.
- No new screen extras (F4).
- F9 binds when present on archive rows; else `row_fields_or_pass` for MVP archive (still fail-closed for capital).
- N201 remains define-only / not sealed.

## Related

- Project store: `alternate-strand-learning-questions.md`, `lifecycle-learning-flow.md`
- Post-hsr policy: `docs/ops/post-hsr-freeze-extras.md`
