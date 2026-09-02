# News phrase ↔ trajectory panel (observe-only)

- Generated: `2026-09-02T08:19:36.579084+00:00`
- Source pool: `buy_boundary`
- Mode: `rolling`
- Cohort tickers: **111** (with news: **68**)
- Articles walked: **4242**
- Phrase observations: **129152**
- Train cutoff: `2026-08-14T08:05:23+00:00`
- Lexicon generation: **4**

## Self-improve delta

- Newly promoted: 0
- Demoted: 0
- Continued promoted: 0

## Top promoted phrases

_No phrases cleared the promote gate this run._

## Top watch candidates (train lift; awaiting test labels)

| rank | phrase | train lift 4w | reason | tickers | n |
|---:|---|---:|---|---:|---:|
| 6 | `shrink` | 0.149973 | insufficient_test_labels | 2 | 4 |
| 8 | `income potential` | 0.132828 | insufficient_test_labels | 2 | 5 |
| 9 | `potential making` | 0.132828 | insufficient_test_labels | 2 | 5 |
| 10 | `stability income potential` | 0.132828 | insufficient_test_labels | 2 | 5 |
| 11 | `income potential making` | 0.132828 | insufficient_test_labels | 2 | 5 |
| 12 | `potential making them` | 0.132828 | insufficient_test_labels | 2 | 5 |
| 31 | `lse hochschild` | 0.12667 | insufficient_test_labels | 2 | 4 |
| 32 | `media lse hochschild` | 0.12667 | insufficient_test_labels | 2 | 4 |
| 17 | `streak` | 0.124671 | insufficient_test_labels | 2 | 5 |
| 35 | `uncertain` | 0.124205 | insufficient_test_labels | 2 | 4 |
| 36 | `their portfolios` | 0.124205 | insufficient_test_labels | 2 | 4 |
| 37 | `uncertain times` | 0.124205 | insufficient_test_labels | 2 | 4 |
| 38 | `times dividend` | 0.124205 | insufficient_test_labels | 2 | 4 |
| 39 | `times dividend offer` | 0.124205 | insufficient_test_labels | 2 | 4 |
| 40 | `navigate volatility` | 0.124205 | insufficient_test_labels | 2 | 4 |

## Coverage notes

- Observe-only: does not modify screen weights or paper knobs.
- Forward returns use archive snapshots (same family as trajectory evidence).
- Promotion requires train lift and non-contradictory test lift when labels exist.
- Memo-grade / non-cohort news remains isolated until a later gated pass.
- Archive history is thin (11 snapshots); 12w labels will be sparse until history densifies.
