# News phrase ↔ trajectory panel (observe-only)

- Generated: `2026-11-22T10:38:15.691641+00:00`
- Source pool: `buy_boundary`
- Mode: `rolling`
- Cohort tickers: **145** (with news: **100**)
- Articles walked: **12072**
- Phrase observations: **355526**
- Train cutoff: `2026-10-12T10:03:01+00:00`
- Lexicon generation: **7**

## Self-improve delta

- Newly promoted: 1
- Demoted: 0
- Continued promoted: 1

## Top promoted phrases

| rank | phrase | lift 4w | test lift 4w | tickers | n |
|---:|---|---:|---:|---:|---:|
| 2 | `gold` | 0.070784 | 0.065236 | 11 | 116 |
| 50 | `metals` | 0.069383 | 0.014766 | 8 | 30 |

## Top watch candidates (train lift; awaiting test labels)

| rank | phrase | train lift 4w | reason | tickers | n |
|---:|---|---:|---|---:|---:|
| 1 | `breaking` | 0.211202 | insufficient_test_labels | 2 | 4 |
| 4 | `apollo global` | 0.197306 | insufficient_test_labels | 2 | 4 |
| 5 | `global management` | 0.197306 | insufficient_test_labels | 2 | 4 |
| 6 | `apollo global management` | 0.197306 | insufficient_test_labels | 2 | 4 |
| 17 | `aligns` | 0.171046 | insufficient_test_labels | 2 | 4 |
| 3 | `police` | 0.170116 | insufficient_test_labels | 2 | 6 |
| 25 | `agree` | 0.158596 | insufficient_test_labels | 2 | 4 |
| 15 | `stockwatch` | 0.155912 | insufficient_test_labels | 2 | 5 |
| 29 | `golden opportunity` | 0.15272 | insufficient_test_labels | 2 | 4 |
| 31 | `expects record` | 0.151936 | insufficient_test_labels | 2 | 4 |
| 7 | `lse greatland` | 0.148489 | insufficient_test_labels | 2 | 7 |
| 47 | `lse focus gold` | 0.148325 | insufficient_test_labels | 2 | 4 |
| 54 | `strategic progress` | 0.145249 | insufficient_test_labels | 2 | 4 |
| 22 | `lse valuation` | 0.144274 | insufficient_test_labels | 2 | 5 |
| 55 | `stay article` | 0.143889 | insufficient_test_labels | 3 | 4 |

## Coverage notes

- Observe-only: does not modify screen weights or paper knobs.
- Forward returns use archive snapshots (same family as trajectory evidence).
- Promotion requires train lift and non-contradictory test lift when labels exist.
- Memo-grade / non-cohort news remains isolated until a later gated pass.
