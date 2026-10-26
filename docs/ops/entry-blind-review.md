# Entry-blind review queue (Package M) — v0

Thin observe-only instrument: **blind entry critique** for lab / interesting
buys. PIT chart clipped at buy day + buy decision reasons. Accept / Comment /
Duplicate — same labels pattern as post-sale reviews, **separate** stores so
outcome fields cannot leak onto the card.

`influences_live=false`. Not Package **L**. Alignment-only.

## Learning question

> Given only information available at / just after the buy (decision reasons,
> PIT chart — **no** subsequent path or eventual exit), was this a sound entry
> under the intended entry lens / policy?

## Owner job

1. Open Lifecycle → **Entry blind**.
2. Review PIT chart (through buy day only) + **bought because** reasons.
3. **Accept** if the blind framing matches; **Comment** on missed entry-lens
   patterns; **Duplicate** for same-pattern cross-book noise.
4. Never force knobs / fills from this queue.

## Stores

| File | Role |
|---|---|
| `docs/data/entry_blind_review_queue.json` | Active queue (ops-monitor refresh) |
| `docs/data/entry_blind_review_labels.json` | Durable Accept / Comment / reply history |

## Coverage (v0)

| Population | Notes |
|---|---|
| Cue-consumer MFT lab buys | Preferred when the lab exposes open / recent buys |
| Sealed `just_bought` (capped) | Interim interesting feed until lab fills; active cap 12 |

**Hard rules:** strip `return_pct` / exit / sell chrome; PIT `end` = buy day;
`family_id = book\|TICKER\|entry_day`.

## Parked (not in v0)

| Stage / stream | Status |
|---|---|
| `entry_revisit` at buy+28d | Later (observe scaffold clock noted only) |
| `exit_blind` / `exit_revisit` | Deferred |
| Missed-opp auto digest | Deferred |
| Full four-stage automation | Deferred |

## Dashboard bridge

| Action | Decision |
|---|---|
| `entry-blind-review-ack` | Accept |
| `entry-blind-review-comment` | Comment (+ text) |
| `entry-blind-review-duplicate` | Duplicate |

Batch into workflow `entry-blind-review-ack.yml`. Local serve:
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
| Trigger | Daily `collect_ops_findings` → `check_entry_blind_review_queue` |
| Findings | **Entry-blind review queue (observe)** (info); reply-pending / unreplied Comment warns |
| `auto_fixable` | Always `False` |
| Commit | `entry_blind_review_queue.json` (+ labels) in ops-monitor `GHA_COMMIT_OPTIONAL` |
| Human gate | Checklist `sunday-entry-blind-reviews` beside post-sale reviews |

## Forbidden

- Showing post-buy marks, realized %, exit reason, or sell decision on the card
- `influences_live` / knob / fill changes
- Treating Accept as Package L fuel
- Enabling exit stages or missed-opp spray from this slice
