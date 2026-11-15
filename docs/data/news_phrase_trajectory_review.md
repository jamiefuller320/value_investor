# News phrase ↔ trajectory panel (observe-only)

- Generated: `2026-11-15T10:37:51.014638+00:00`
- Source pool: `buy_boundary`
- Mode: `rolling`
- Cohort tickers: **145** (with news: **100**)
- Articles walked: **11764**
- Phrase observations: **342613**
- Train cutoff: `2026-10-07T06:23:02+00:00`
- Lexicon generation: **6**

## Self-improve delta

- Newly promoted: 1
- Demoted: 0
- Continued promoted: 1

## Top promoted phrases

| rank | phrase | lift 4w | test lift 4w | tickers | n |
|---:|---|---:|---:|---:|---:|
| 49 | `metals` | 0.069112 | 0.014258 | 8 | 30 |

## Top watch candidates (train lift; awaiting test labels)

| rank | phrase | train lift 4w | reason | tickers | n |
|---:|---|---:|---|---:|---:|
| 2 | `breaking` | 0.210931 | insufficient_test_labels | 2 | 4 |
| 4 | `apollo global` | 0.197035 | insufficient_test_labels | 2 | 4 |
| 5 | `global management` | 0.197035 | insufficient_test_labels | 2 | 4 |
| 6 | `apollo global management` | 0.197035 | insufficient_test_labels | 2 | 4 |
| 16 | `aligns` | 0.170775 | insufficient_test_labels | 2 | 4 |
| 3 | `police` | 0.169845 | insufficient_test_labels | 2 | 6 |
| 24 | `agree` | 0.158325 | insufficient_test_labels | 2 | 4 |
| 15 | `stockwatch` | 0.155641 | insufficient_test_labels | 2 | 5 |
| 29 | `golden opportunity` | 0.152449 | insufficient_test_labels | 2 | 4 |
| 30 | `expects record` | 0.151665 | insufficient_test_labels | 2 | 4 |
| 7 | `lse greatland` | 0.148218 | insufficient_test_labels | 2 | 7 |
| 45 | `lse focus gold` | 0.148054 | insufficient_test_labels | 2 | 4 |
| 53 | `strategic progress` | 0.144978 | insufficient_test_labels | 2 | 4 |
| 54 | `stay article` | 0.143618 | insufficient_test_labels | 3 | 4 |
| 55 | `article see` | 0.143618 | insufficient_test_labels | 3 | 4 |

## Coverage notes

- Observe-only: does not modify screen weights or paper knobs.
- Forward returns use archive snapshots (same family as trajectory evidence).
- Promotion requires train lift and non-contradictory test lift when labels exist.
- Memo-grade / non-cohort news remains isolated until a later gated pass.
