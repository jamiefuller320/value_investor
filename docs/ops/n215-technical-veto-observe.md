# N215 soft-band technical veto observe (sealed)

**registration_id:** `n215-soft-band-veto-v0`  
**recipe_id:** `n215-soft-score-recipe-v0`  
**deferred:** N215  
**Mode:** observe-only — never writes strand A / paper books, knobs, or `decision-review --apply`

## Learning question

For each **pre-registered** soft-veto band threshold on sealed **N200** closed episodes (charts with `date ≤ buy_ts`): what is **catch** among deep losers (fair-cost ≤ −10%) vs **miss** among large winners (≥ +10%)? Companion: `risk_score` distribution. Labels only — **no live gate**.

### Companion alone rule — grind mid-range-60

**rule_id:** `n215-grind-mid60-pass-v0` (frozen 2026-10-22)

> On sealed closed buys that soft-band labels **PASS**, does blocking entries whose close sits at or above the **midpoint of the prior 60 trading-day range** catch deep losers alone, with acceptable large-winner miss and positive alone net fair-cost benefit?

| Piece | Pin |
|---|---|
| Fire | `soft_band == PASS` **and** `mid_range_60 ≥ 0.50` |
| Feature | `(close_t0 − min_60) / (max_60 − min_60)` PIT |
| Alone-benefit primary | **N200** |
| Discovery / report-only | **N206** (do not retune thr on N206) |
| Soft weights | **Unchanged** — companion, not recipe v1 |
| Live | **False** |

Store path: `rollup.companion_grind_mid60`. Project store: `technical-veto-grind-mid60.md`.

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
| **Daily ops-monitor** | `check_n215_technical_veto_observe` refreshes store from N200/N206/N210 sealed stores + charts |
| Manual | `ftse-n215-technical-veto --output-dir docs/data` |

## Artifacts

| Path | Role |
|---|---|
| `docs/data/n215_technical_veto_registration.json` | Frozen seal / recipe record |
| `docs/data/n215_technical_veto_observe.json` | Per-episode scores + band catch/miss + `companion_grind_mid60` |
| This doc | Runbook |

Stores commit via ops-monitor `GHA_COMMIT_OPTIONAL`.

## Constraints

- No live veto / soft gate on fills.
- Progressive admission still required before any future hard influence.
- N210 rows are anecdote-only until that book's `volume_gate.met`.
- N206 rows feed companion grind mid60 report-only; soft-band primary catch/miss stays N200.
- Hard-rule companion (`I01\|I02`, any-of-six) is diagnostic comparison only.
- Grind mid60 companion is observe-only — never a live skip until progressive alone admit.

## Related

- Reentry LQ-B (co-equal): [n215-reentry-observe.md](n215-reentry-observe.md)
- Project store: `technical-veto-adaptive-approaches.md`, `technical-veto-first-pass.md`, `technical-veto-reentry-lq.md`
- Park: **N215**
