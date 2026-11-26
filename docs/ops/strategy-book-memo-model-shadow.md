# Outcome-scored memo model shadow (L703)

**Strategy part served:** the memo bind on the strategy book. The blind judge
comparison scores memo quality. This shadow scores the entry effect against
what the name did.

**Learning question:** on real strategy-book signals, does `composer-2.5` or
`grok-4.6` block the names that lose over 63 sessions and pass the names that
do not?

**Observe-only.** `influences_live` is false. The shadow does not write the
research store, `strategy_book_memo_log.jsonl`, the forward book, or
`policy.json`'s research model. It does not change a fill. It does not rememo
a live name. `authorize_live_llm_influence` is called on every score and
fail-closes.

## Models

| Role | Model | What it does here |
|------|-------|-------------------|
| Incumbent, and the live model | `composer-2.5` | Writes a shadow memo. Stays the live memo model. |
| Comparison challenger | `grok-4.6` | Writes a shadow memo. Does not become the live model. |

`docs/data/memo_model_comparison/decision.json` on this book is
`inconclusive_keep` (`judge_trusted` false, governing `owner_sample`).
`composer-2.5` stays. A later `switch` in that file is not applied here. A
missing or unreadable decision is fail-closed: no score and no model call.

The challenger call is refused if `strongest_configured_grok()` is not
`grok-4.6`.

## Signals

Real strategy-book signals only:

1. Primary episodes in `docs/data/strategy_book_observe.json`.
2. Forward-status candidates whose outcome is `pending_fill`, `filled`,
   `memo_not_ready`, or `memo_blocked`.
3. Signal-day rows already requested on `docs/data/strategy_book_memo_log.jsonl`.

The first row for a market, ticker, and signal session wins, so a filled
episode keeps its fill date.

## Shadow memos

The weekday forward workflow (`strategy-book-forward.yml`, 17:45 and 21:30 UTC)
runs `ftse-strategy-book-memo-model-shadow --apply --request-memos`. A memo is
requested only when it would still be in force at the fill close:

- the fill session's cash close is still ahead, or
- there is no fill yet and the signal is the market's latest completed session.

Each model runs in a temporary copy of that name's `sources/` folder. The
working directory is that copy. The runner does not open `ResearchStore` and
drops any path under the live research tree. One attempt per signal and model
is kept. The cap is 3 signals a run and $24 in the ISO week
(`weekly_ops`, with the memo job's $8 headroom). A missing key, a model that
is not listed, or a failed quote check does not invent a verdict.

Memos are appended to
`docs/data/strategy_book_memo_model_shadow_memos.jsonl`.

## Score (`l703-outcome-score-v1`)

The 63-session outcome is the memo-free shadow's outcome: fair-cost return at
63 sessions after the fill, or the realized exit if it came first. The same
helper writes the 10- and 20-session early marks onto each signal. This store
does not write `strategy_book_memo_free_shadow.json`.

| Effect | Meaning | Hit when |
|--------|---------|----------|
| `block` | The research verdict would block the entry (`pass`, `sell`, `avoid`, `exit`) | 63-session return is negative |
| `pass` | The entry would be allowed (`accumulate`, `neutral`, `caution`) | 63-session return is zero or positive |

A score also needs all of these. Otherwise the hit is null and the effect is
not used:

- the comparison decision is readable and its outcome is `keep`,
  `inconclusive_keep`, or `switch` (a switch is still not applied);
- a rationale and at least one evidence quote that was found in the cited file;
- `finished_at` at or before the fill close;
- memo age at that close of at most 21 days;
- a numeric 63-session outcome.

Below 8 scored names a model's hit rate stays null (`insufficient_data`).

Names the book has open in November 2026 are younger than 63 sessions, so the
hit stays null until that outcome exists. That is fail-closed, not a zero.

## Automation

| Piece | Where |
|-------|--------|
| Scheduled trigger | `strategy-book-forward.yml` writes the store and requests memos. `check_strategy_book_memo_model_shadow` runs inside daily `collect_ops_findings` and only reads the store. |
| Persisted finding | `docs/data/ops_status.json`, `auto_fixable` false. Info when `generated_at` is at or after the latest 21:30 UTC weekday slot. Warn when the store is missing, older than that slot, or unreadable, and when the decision evidence is missing or the store claims a live effect. |
| Runbook | This file, the row in [ops-monitor.md](ops-monitor.md), and the short note in [strategy-book-observe.md](strategy-book-observe.md#outcome-scored-memo-model-shadow-l703). |

## CLI

Drill-down only. The workflow is the production path.

```bash
ftse-strategy-book-memo-model-shadow --repo-root .                         # counts only
ftse-strategy-book-memo-model-shadow --repo-root . --apply                  # rewrite scores
ftse-strategy-book-memo-model-shadow --repo-root . --apply --request-memos  # also request
```

Module: `src/value_investor/strategy_book_memo_model_shadow.py`.
Store: `docs/data/strategy_book_memo_model_shadow.json`.
