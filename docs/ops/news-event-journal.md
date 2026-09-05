# News event journal (observe-only)

Starts the calendar clock on **material-event extraction** without touching the live
path. Walks **buy-tier ∪ boundary-watch** `news_manifest.json` headlines, keeps only
issuer-filtered leadership / M&A / contract / strategy events, and joins later
`filings_index.json` rows plus archive forward returns.

This is the headline → event-record analogue of the Comparison-tool qualitative
loop (extract → score against later official text → improve rules). It is **not**
a port of that repo’s website capture / CSS harvest.

## Weekly automation

Sunday `analysis-review.yml` runs a **rolling** refresh after
`ftse-news-phrase-trajectory` (soft-fail, observe-only) and commits the four
artifacts below with the knob/trajectory bootstrap commit. No human checklist
gate — review the markdown when confirmation rates leave `watch`.

## Command

```bash
# Full backfill over buy ∪ boundary cohort (manual / first seed)
ftse-news-event-journal --data-dir docs/data --mode full

# Weekly / Sunday: rolling watermark refresh (also what CI runs)
ftse-news-event-journal --data-dir docs/data --mode rolling
```

Optional: `--tickers AAA.L BBB.L`, `--json`.

## Artifacts

| File | Role |
|------|------|
| `docs/data/news_event_journal.json` | Event records + cohort coverage |
| `docs/data/news_event_rules.json` | Per-type confirmation rates vs later filings |
| `docs/data/news_event_journal_state.json` | Per-ticker watermarks |
| `docs/data/news_event_journal_review.md` | Human-readable summary |

## Method (short)

1. Cohort = `buy`/`strong_buy` from `latest.json` ∪ `trajectory_boundary_watch.json`.
2. For each ticker, walk `research/{TICKER}/sources/news_manifest.json`.
3. Drop headlines that fail `headline_relevant_to_issuer`, plus short-EPIC
   currency/FX homonyms (the `AED` / dirham failure mode).
4. Classify the **title only** with tight role+action / deal / contract /
   strategy patterns. RSS teasers are ignored (they are full of
   ``time to buy`` clickbait). Share buybacks and insider dealing are not M&A.
5. Join the earliest later filing (same ticker, ≤400 days) whose headline or
   on-disk body mentions the event class.
6. Attach archive forward returns at 4/8/12 weeks when history exists.
7. Score each event type `watch` / `promising` / `weak` from confirmation rate.
8. After title+teaser+confirming filing, require size (M&A/contract) and
   likelihood (M&A/strategy). Missing required facts set
   `seek_richer_source` + `richer_source: guardian_open_platform`. That is
   the learning-loop trigger to fetch a licensed body later — nothing is
   fetched in this job. Nothing writes screen weights or judgment prompts.

## What this is not

- Not a news-article HTML crawl (paywalls; N90).
- Not a company-IR website extractor (N86 / Comparison-tool capture loop).
- Not a live overlay that can veto a buy. That waits until later filings and
  returns show the extractor is finding the right facts.

## Related

- [news-phrase-trajectory.md](news-phrase-trajectory.md) — ngram lexicon on the same manifests
- [trajectory-evidence.md](trajectory-evidence.md)
