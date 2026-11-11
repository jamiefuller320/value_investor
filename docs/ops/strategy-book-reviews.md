# Strategy-book reviews

Plan step 2.4. Observe-only. `influences_live` is false.

## Learning question

For every closed episode on the strategy book: what happened (the entry, the
path, and the exit reason against the registered rule), was the outcome
down to entry timing, the exit rule, a thesis break, a gate miss or market
drift, and which of the five levers would have helped?

The answers are evidence for the version review at the thickness gate, and
at the reviews after that. They are not a reason to change the book between
reviews. This check does not walk, does not write the registration, and does
not run `decision-review --apply`.

## Where it lives

The sealed post-sale queue (`docs/data/post_sale_review_queue.json`) is the
attention list for Lifecycle paper books and the FTSE control. It is not
shaped for strategy-book columns, and putting those columns on it would bury
the primary closes. Strategy-book closes therefore have a sibling store:

| File | What it is |
|---|---|
| `docs/data/strategy_book_review_queue.json` | One row per closed episode. Rebuilt each ops-monitor run. |
| `docs/data/strategy_book_review_labels.json` | Optional Accept history, via the same label helper as the sealed queue. The daily refresh does not create it. |

The stable id of a row is the episode id
(`market:ticker:column:signal_session`). A second run replaces the file. It
does not add a second row for the same id.

## What gets queued

A close is an episode whose status is `closed` or whose `exit_session` is
set. An open episode is counted and skipped.

| Attention | Columns |
|---|---|
| Primary list (`active`) | `primary` only. This is the list to read first. |
| Beside it (`companion`) | Comparison exits (`draft_v0_exit`, `ladder_no_deadline`, `leave_tier`, `alternative`), the `buy_on_signal` control, the gate-rejected shadows, a bench column, and a `lab_` exit column. Each row carries its column. |

Bench flags on a primary episode (`deep_dip`, `revenue_growing`, `fcf_agrees`,
`trend_not_falling`) stay on that primary row. They are not extra cards.

An Accept recorded against `strategy_book_review_labels.json` takes that
primary card off the attention list and leaves the row in `rows`, so the
close is still there for the version review. The daily job does not call the
post-sale comment path. That path can call a model when
`FTSE_POST_SALE_LLM_REPLY` is on. It stays off here. No opinion text is
generated.

## What a row says

Each row carries the column, the exit reason, the fair-cost return, the
matched excess, and the inputs the episode cited. Returns on the observe
store are fractions: 0.12 is 12 percent.

The cause is one of:

| Label | When |
|---|---|
| `thesis_break` | The exit reason is the registered thesis break. |
| `gate_miss` | The column is a gate-rejected shadow. The row is the "what if we had bought it" case. |
| `entry_timing` | A primary episode was labelled recovery, never launched, and then hit the fail-to-launch deadline. |
| `market_drift` | The exit is a price or time rule, the episode return is more than 2 percentage points from flat, and the matched excess is inside 2 percentage points. The basket did the moving. |
| `exit_rule` | The exit reason is in the registered family for that column, and none of the rows above applied. |
| `insufficient_data` | The exit reason or the fair-cost return is missing, or the reason is not in the registered family. Also every provenance miss. |

A provenance miss is still queued, with `provenance_missing` true. Its cause
and its lever scores are `insufficient_data`. A provisional cause is stored
so a person can see what the rules would have said. It is not evidence.

## Five levers

The definitions are the cue-consumer lab's five levers
(`MOM_LEVERS` in `cue_consumer_mft.py`, metric `mft-fair-cost-5lever-v0`).
They are imported, not retyped. `would_have_helped` is `yes`, `no`, or
`insufficient_data`. Missing data is never a yes.

| Lever | How this book scores it |
|---|---|
| Stock choice | On a shadow, a loss beyond 2 points means the skip would have helped, and a gain means it would not. On any other column there is no skipped-name counterfactual, so the score is `insufficient_data`. The fair-cost return is still cited. |
| Buy timing | Nearest-entry counterfactual. A primary or comparison close is scored against the same-name `buy_on_signal` close whose fill is nearest this fill; a control close is scored against the nearest same-name primary. The fill must sit inside the section 3 entry window (`LOW_WINDOW_SESSIONS`, 10 sessions, counted as weekdays because this review has no price calendar). A tie takes the earlier entry. A close that had not exited yet is hindsight and is not a score. None in the window is `insufficient_data`. |
| Buy strategy | The book is a single fixed stake. There is no scale-in counterfactual on the episode, so this lever stays `insufficient_data`. |
| Sell timing | Median of paired alternatives on the same signal that had already closed. Every alternative's delta is cited, with `alternatives_n`, `alternatives_beating_n` and the median delta. `yes` only when that median beats this close by more than 2 points. The lab's same-day bias still applies (`assess_same_day_round_trip`): a same-day exit is a weakness unless it is a thesis break with a reason in the decision log. |
| Sell strategy | Median of paired alternatives, n shown, on the same rule as sell timing. The same-day thesis-break exception is unchanged. |

## Judgment in the round

Each close gets the cue-consumer checklist (`fill_judgment_in_the_round`,
rubric `judgment_in_the_round_v0`). The filler cites the entry snapshot, the
exit reason, the fair-cost return, and the same-day assessment. Cells with
nothing to cite stay unknown. `authorize_judgment_live_influence` is false.
On a provenance miss the trail is still written and marked
`counts_as_evidence: false`.

The filler's buy-rule cell uses the lab's phrase "cue whitelist proposes".
On this book the cite is the strategy-book registration id and the column,
not a cue-lab whitelist hit.

## Point in time

A review uses the episode as the walker left it at the exit, and gate-log
rows for that name dated on or before the exit. A decision-log line, a
review, a floor step, a review input, or a gate-log row dated after the exit
is listed under `hindsight` and is not used as a cite. An undated line is
withheld the same way. A sibling episode that was still open, or that closed
later, is not a counterfactual for this exit.

## Daily check

`collect_ops_findings` calls `check_strategy_book_reviews` after
`check_strategy_book_observe`. All findings are `auto_fixable: false`.

| Title | Severity | When |
|---|---|---|
| Strategy book reviews queued | info | The queue was refreshed. Names primary, companion, open, and provenance counts. Zero closes is a normal info row while the book is young. |
| Strategy book closes missing review | warn | A close older than 2 days has no queue row. That is a blank episode id, or a close the refresh could not keep. It is not reviewed. |
| Strategy book reviews failed | warn | The observe store is missing or unreadable. Nothing is treated as reviewed. |

Ops-monitor commits `docs/data/strategy_book_review_queue.json` (and the
labels file when one exists) on the optional list in
`scripts/gha_commit_ops_monitor.sh`. The forward job still owns the observe
store and the gate log. This check only reads them.

Drill-down, not the daily path:

```bash
ftse-strategy-book-reviews
ftse-strategy-book-reviews --json
```

## What this is not

No new model spend. No mid-run tune. No change to a knob, a fill, or the
sealed registration. The version review is the human step that reads this
store. It is already on the human tasks checklist
(`adhoc-strategy-version-review`). There is no separate daily human review.
