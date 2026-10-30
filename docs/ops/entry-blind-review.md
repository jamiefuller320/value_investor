# Entry-blind review queue (Package M) — v0

Thin observe-only instrument: **blind entry critique** for lab / interesting
buys. PIT chart clipped at buy day + buy decision reasons + **L650 entry news
polarity cites** (hard 90d PIT lookback; fail-closed `no_usable_news`) +
**L652 parallel timing lens** compact summary (favourite / looking-entered-
abandoned / concurrence). Accept / Comment / Duplicate — same labels pattern as
post-sale reviews, **separate** stores so outcome fields cannot leak onto the
card.

`influences_live=false`. Not Package **L**. Alignment-only.

## Learning question

> Given only information available at / just after the buy (decision reasons,
> PIT chart — **no** subsequent path or eventual exit), was this a sound entry
> under the intended entry lens / policy?

## Owner job

1. Open Lifecycle → **Entry blind**.
2. Review PIT chart (through buy day only) + **bought because** reasons +
   **news polarity** line (agree/disagree on structural vs improvement cites) +
   **timing lenses** line (L652 favourite vs peers / concurrence — observe only)
   — factory **pattern marks** (entry quality / range location / MA context) sit
   on the chart so critique is pictorial, not prose-only. Entry-lens chips are
   normally **blue (`info`)** context marks — see tone table in
   [post-sale-review-queue.md](post-sale-review-queue.md#pattern-marks-chart-annotations).
3. **Accept** if the blind framing matches; **Comment** on missed entry-lens
   patterns; **Duplicate** for same-pattern cross-book noise.
4. Never force knobs / fills from this queue.

## Stores

| File | Role |
|---|---|
| `docs/data/entry_blind_review_queue.json` | Active queue (ops-monitor refresh); cards carry `entry_news_polarity` + `parallel_timing_lenses` |
| `docs/data/entry_blind_review_labels.json` | Durable Accept / Comment / reply history |
| `docs/data/entry_news_polarity.json` | L650 cohort rollup (usable / label counts) |
| `docs/data/parallel_timing_lenses.json` | L652 lens episodes / concurrence (bound onto cards) |

News polarity detail: [entry-news-polarity.md](entry-news-polarity.md).  
Timing lenses detail: [parallel-timing-lenses.md](parallel-timing-lenses.md).

## Coverage (v0)

| Population | Notes |
|---|---|
| Cue-consumer MFT lab buys | Preferred when the lab exposes open / recent buys |
| Sealed `just_bought` (capped) | Interim interesting feed until lab fills; active cap 12 |

**Hard rules:** strip `return_pct` / exit / sell chrome; PIT `end` = buy day;
`family_id = book\|TICKER\|entry_day`.

## Entry revisit (buy+28d) — shipped

Stage id: **`entry_revisit`**. Unlocks when `entry_blind` is Accept/Comment-actioned
**and** `asof >= buy_day + 28` calendar days (locked). Shows frozen blind
summary + path through buy+28d (`still_open` | `already_exited`). Separate
`review_id` — never rewrites sealed blind Accept/Comment. Not an exit autopsy.

| File | Role |
|---|---|
| `docs/data/entry_revisit_review_queue.json` | Active revisit queue |
| `docs/data/entry_revisit_review_labels.json` | Durable Accept / Comment / reply history |

Lifecycle → **Entry +28d**. CLI: `ftse-entry-revisit-review`. Ops finding:
**Entry-revisit review queue (observe)** (`auto_fixable=false`).

## Parked

| Stage / stream | Status |
|---|---|
| `exit_blind` / `exit_revisit` | Deferred (L642) |
| Missed-opp auto digest | Deferred (L641/L644) |
| Full four-stage automation | Deferred |

## Dashboard bridge

| Action | Decision |
|---|---|
| `entry-blind-review-ack` | Accept |
| `entry-blind-review-comment` | Comment (+ text) |
| `entry-blind-review-duplicate` | Duplicate |

Batch into workflow `entry-blind-review-ack.yml` via **`DashboardBridge.queueCommand`**
(same bridge as post-sale — not a dead `ftseDashboardBridge.enqueue` path). Optimistic
clear + `localStorage` overlay (`ftse.pendingEntryBlindActions.v1`) keeps Accept/Comment
cleared across iPad soft reload until labels/git catch up. Local serve:
`POST /api/entry-blind-review-action`.

CLI (optional):

```bash
ftse-entry-blind-review refresh
ftse-entry-blind-review accept --review-id …
ftse-entry-blind-review comment --review-id … --text "…"
ftse-entry-blind-review duplicate --review-id …
```

## Automation wiring

| Piece | Detail |
|---|---|
| Trigger | Daily `collect_ops_findings` → `check_entry_blind_review_queue` + `check_entry_revisit_review_queue` |
| Findings | **Entry-blind review queue (observe)**; **Entry-revisit review queue (observe)**; reply-pending / unreplied Comment warns |
| `auto_fixable` | Always `False` |
| Commit | blind + revisit queue/labels in ops-monitor `GHA_COMMIT_OPTIONAL` |
| Human gate | Checklist `sunday-entry-blind-reviews` + `sunday-entry-revisit-reviews` |

## Forbidden

- Showing post-buy marks, realized %, exit reason, or sell decision on the card
- `influences_live` / knob / fill changes
- Treating Accept as Package L fuel
- Enabling exit stages or missed-opp spray from this slice
