# News phrase ↔ trajectory panel (observe-only)

- Generated: `2026-11-08T10:36:47.316790+00:00`
- Source pool: `buy_boundary`
- Mode: `rolling`
- Cohort tickers: **126** (with news: **81**)
- Articles walked: **9269**
- Phrase observations: **268901**
- Train cutoff: `2026-10-05T09:58:03+00:00`
- Lexicon generation: **5**

## Self-improve delta

- Newly promoted: 2
- Demoted: 0
- Continued promoted: 0

## Top promoted phrases

| rank | phrase | lift 4w | test lift 4w | tickers | n |
|---:|---|---:|---:|---:|---:|
| 11 | `aerospace` | 0.153703 | 0.092533 | 3 | 6 |
| 47 | `metals` | 0.069511 | 0.006395 | 7 | 29 |

## Top watch candidates (train lift; awaiting test labels)

| rank | phrase | train lift 4w | reason | tickers | n |
|---:|---|---:|---|---:|---:|
| 3 | `breaking` | 0.210092 | insufficient_test_labels | 2 | 4 |
| 2 | `man` | 0.197401 | insufficient_test_labels | 2 | 5 |
| 5 | `apollo global` | 0.196196 | insufficient_test_labels | 2 | 4 |
| 6 | `global management` | 0.196196 | insufficient_test_labels | 2 | 4 |
| 7 | `apollo global management` | 0.196196 | insufficient_test_labels | 2 | 4 |
| 21 | `lse climbing` | 0.160094 | insufficient_test_labels | 2 | 4 |
| 24 | `agree` | 0.157486 | insufficient_test_labels | 2 | 4 |
| 15 | `stockwatch` | 0.154802 | insufficient_test_labels | 2 | 5 |
| 32 | `golden opportunity` | 0.15161 | insufficient_test_labels | 2 | 4 |
| 33 | `expects record` | 0.150826 | insufficient_test_labels | 2 | 4 |
| 8 | `lse greatland` | 0.147379 | insufficient_test_labels | 2 | 7 |
| 44 | `lse focus gold` | 0.147215 | insufficient_test_labels | 2 | 4 |
| 52 | `stay article` | 0.142779 | insufficient_test_labels | 3 | 4 |
| 53 | `article see` | 0.142779 | insufficient_test_labels | 3 | 4 |
| 54 | `stay article see` | 0.142779 | insufficient_test_labels | 3 | 4 |

## Coverage notes

- Observe-only: does not modify screen weights or paper knobs.
- Forward returns use archive snapshots (same family as trajectory evidence).
- Promotion requires train lift and non-contradictory test lift when labels exist.
- Memo-grade / non-cohort news remains isolated until a later gated pass.
