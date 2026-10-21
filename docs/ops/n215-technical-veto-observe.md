# N215 soft-band technical veto observe (sealed)

**registration_id:** `n215-soft-band-veto-v0`  
**recipe_id:** `n215-soft-score-recipe-v0`  
**deferred:** N215  
**Mode:** observe-only — never writes strand A / paper books, knobs, or `decision-review --apply`

## Learning question

For each **pre-registered** soft-veto band threshold on sealed **N200** closed episodes (charts with `date ≤ buy_ts`): what is **catch** among deep losers (fair-cost ≤ −10%) vs **miss** among large winners (≥ +10%)? Companion: `risk_score` distribution. Labels only — **no live gate**.

## Frozen recipe (pre-registered)

| Piece | Pin |
|---|---|
| Lookback | 126 trading days |
| Features | twin elev abs/range, near-high dist, 20d return, failed breakout, RSI climax fail + RSI level, death cross, lost-200 |
| Score | Weighted sum of normalized features (weights in registration / store `recipe`) |
| Bands | `PASS` &lt; 0.35 ≤ `WARN` &lt; 0.55 ≤ `SOFT_VETO` &lt; 0.75 ≤ `HARD_CANDIDATE` |
| Fail-closed | Missing chart / &lt;60 bars → `PASS`, `influences_live=false` |

Do **not** retune weights or band cuts on this cohort for admission claims. No grid search; no fit to KLR.

## When it runs

| Trigger | Schedule |
|---|---|
| **Daily ops-monitor** | `check_n215_technical_veto_observe` refreshes store from N200/N210 sealed stores + charts |
| Manual | `ftse-n215-technical-veto --output-dir docs/data` |

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n215_technical_veto_registration.json` | Frozen seal / recipe record |
| `docs/data/n215_technical_veto_observe.json` | Per-episode scores + band catch/miss rollup |
| This doc | Runbook |

Stores commit via ops-monitor `GHA_COMMIT_OPTIONAL`.

## Constraints

- No live veto / soft gate on fills.
- Progressive admission still required before any future hard influence.
- N210 rows are anecdote-only until that book's `volume_gate.met`.
- Hard-rule companion (`I01\|I02`, any-of-six) is diagnostic comparison only.

## Related

- Reentry LQ-B (co-equal): [n215-reentry-observe.md](n215-reentry-observe.md)
- Project store: `technical-veto-adaptive-approaches.md`, `technical-veto-first-pass.md`, `technical-veto-reentry-lq.md`
- Park: **N215**
