# News phrase ↔ trajectory panel (offline)

Observe-only module that walks **buy-tier ∪ boundary-watch** names chronologically,
joins open-source headlines (`news_manifest.json`) to archive forward returns, and
builds a walk-forward phrase lexicon. Does **not** write screen weights or paper knobs.

## Weekly automation

Sunday `analysis-review.yml` runs a **rolling** refresh after `ftse-trajectory-evidence`
(soft-fail, observe-only) and commits the four artifacts below with the knob/trajectory
bootstrap commit. No human checklist gate — review the markdown opportunistically when
promotions start appearing.

## Command

```bash
# Full backfill over buy ∪ boundary cohort (manual / first seed)
ftse-news-phrase-trajectory --data-dir docs/data --mode full

# Weekly / Sunday: rolling watermark refresh (also what CI runs)
ftse-news-phrase-trajectory --data-dir docs/data --mode rolling
```

Optional: `--tickers AAA.L BBB.L`, `--train-fraction 0.7`, `--min-train-count 4`,
`--max-phrases 80`, `--json`.

## Artifacts

| File | Role |
|------|------|
| `docs/data/news_phrase_trajectory.json` | Cohort coverage + per-ticker counts + notes |
| `docs/data/news_phrase_lexicon.json` | Ranked phrases with train/test lift and status |
| `docs/data/news_phrase_trajectory_state.json` | Per-ticker watermarks + lexicon generation |
| `docs/data/news_phrase_trajectory_review.md` | Human-readable summary |

## Method (short)

1. Cohort = `buy`/`strong_buy` from `latest.json` ∪ `trajectory_boundary_watch.json` panel.
2. For each ticker, walk `research/{TICKER}/sources/news_manifest.json` from day 0.
3. Extract filtered unigrams/bigrams/trigrams (issuer tokens + stopwords removed).
4. Label with archive forward returns at 4/8/12 snapshot steps (same family as trajectory evidence).
5. Optionally attach nearby trajectory transitions within 14 days after the headline.
6. Walk-forward split (~70/30 by article time): mine on train, score lift on test.
7. Self-improve gate: promote only when train lift clears threshold and test lift does not disagree; otherwise `watch` / `demoted`. Rolling runs bump `lexicon_generation` and refresh watermarks.

## Thin history note

With a short archive (≪ 13 snapshots), 12w labels are sparse and many strong train-lift
phrases stay `watch` (`insufficient_test_labels`). That is intentional — do not loosen
the gate into live scoring. Re-run as Sunday archives densify.

## Isolation / later memo-grade pass

This pilot stays on the buy∪boundary pool so memo-grade breadth does not contaminate
the lexicon. A wider memo-grade news walk (isolated artifact namespace) is deferred until
this panel shows stable out-of-sample usefulness — see deferred idea **L225**.

## Related

- [trajectory-evidence.md](trajectory-evidence.md)
- Research ingest news manifests (Google News RSS + Yahoo; no paid API required)
