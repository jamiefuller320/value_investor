# Entry news polarity cite on buy-day (L650) — observe-only

Thin Package **M** instrument: join offline news stores into a **PIT polarity
label + durable cites** on `entry_blind` cards so humans can agree/disagree while
reviewing buys at cheap valuations. **Never** a live hard filter, strand-A gate,
Package L knob, or fill weight.

Design lock (project store): `entry-news-rebound-signal-2026-10-30.md`.

## Learning question

> At historically cheap valuations, does PIT news/RNS evidence of *structural
> deterioration* vs *encouraging improvement/path* improve entry judgment versus
> cheapness + technicals alone — as observe-only evidence?

## Labels (locked)

| Label | Meaning |
|---|---|
| `structural_negative` | PIT evidence of lasting deterioration |
| `improvement_path` | PIT evidence of encouraging path / repair / catalyst |
| `mixed_or_unclear` | Conflicting, weak, or unclassifiable issuer headlines |
| `no_usable_news` | Fail-closed: no PIT usable issuer news in the window |

## Recency lock (v0 — no influence-fade)

1. **Hard PIT lookback** ending at buy-day: `DEFAULT_LOOKBACK_DAYS = 90`
   calendar days. Items outside the window are unused; if nothing remains →
   `no_usable_news`.
2. **No continuous fade score** drives the polarity enum or any fill weight.
3. Cite metadata only: `age_days` + freshness band `recent` (≤14d) /
   `medium` (≤45d) / `stale` (rest of window) for human review.
4. Exponential / parametric influence-fade into live or lab sizing is **parked**
   (deferred **L651**). Revisit when entry_blind polarity disagreement marks are
   thick enough to test fade vs hard window.

## Join sources (no new crawlers)

| Source | Role |
|---|---|
| `research/{TICKER}/sources/news_manifest.json` | PIT headlines |
| `news_phrase_lexicon.json` (L225) | Phrase hit metadata (lift ≠ valence) |
| `news_event_journal.json` (N90/N86) | Event type join when `published_at ≤ buy day` |

Live `classify_headline` on PIT titles runs even when the committed journal is
stale. Lexicon `promoted`/`demoted` alone never flips the label.

## Surface

- **Primary:** `entry_news_polarity` field on each `entry_blind` card
  (Lifecycle → Entry blind), sibling of `buy_decision`.
- Collapsed: one polarity line; expanded: cite titles + event/freshness meta.
- Fail-closed: missing → show `no_usable_news`; never invent filing/news facts.

## Automation wiring

| Piece | Detail |
|---|---|
| Trigger | Daily ops-monitor `collect_ops_findings` → `check_entry_blind_review_queue` (binds field + writes panel) then `check_entry_news_polarity` |
| Stores | On-card field inside `docs/data/entry_blind_review_queue.json`; cohort rollup `docs/data/entry_news_polarity.json` |
| Finding | **Entry news polarity (observe)** — coverage counts; `auto_fixable=false` |
| CLI (optional) | `ftse-entry-news-polarity show --ticker X --asof YYYY-MM-DD` / `refresh` |

Lexicon / journal panels still refresh on Sunday `analysis-review.yml`
(`ftse-news-phrase-trajectory`, `ftse-news-event-journal`). L650 **consumes**
them; it does not re-crawl.

## Out of scope (v0)

- Live news APIs / sentiment sprawl
- Auto-veto (**N237**)
- MFT B-cell for catalyst/news (**N236** — parked until L650 cohort is thick)
- Restoring `NEWS HIGHLIGHTS` into scheduled memos as a capital path
- Parametric / exponential influence-fade (**L651**)

## Related

- [entry-blind-review.md](entry-blind-review.md)
- [news-phrase-trajectory.md](news-phrase-trajectory.md)
- [news-event-journal.md](news-event-journal.md)
- [ops-monitor.md](ops-monitor.md)
