# Post-sale review queue (Package M)

Owner alignment loop for **closed exits** across all sealed Lifecycle books
(N200 / N201 / N206 / N210+) **and** FTSE control (`buy_tier_level`), tagged.
Observe-only — `influences_live=false`. Not Package **L** auto-tune.

## Owner job

1. Check that reviews of **relevant charts** are happening (episode + wider TF).
2. **Comment** on patterns that might have been missed — do **not** force knobs.
3. Comments are **considered and responded to** (durable note → factory reply
   stub / optional LLM reply text later) — not silent ignore, not auto-apply.
4. **Accept** = framing matches what I see. Accept/Comment also apply to
   **reply** tags.

## Stores

| File | Role |
|---|---|
| `docs/data/post_sale_review_queue.json` | Active queue (ops-monitor refresh) |
| `docs/data/post_sale_review_labels.json` | Durable Accept / Comment / reply history |

Actioned items **clear from the active queue** but remain in labels history.

## Coverage

| Population | Identity | Notes |
|---|---|---|
| Sealed N200/N201/N206/N210 (+ later sealed) | Fair-cost / lifecycle episode | Candidates: `just_sold` + `post_sale` ≤ 84d |
| FTSE control `buy_tier_level` | Board sold cards | Same queue with **FTSE control** tag; epoch-join fail-closed OK |

**Active attention filter (Package M):** `just_sold` + `reply` always; `post_sale`
only when ≤21d since exit **or** return ≤ −5%. Coverage counts still include the
full candidate set so sealed/control population stays visible in ops findings.

## Dual-horizon charts

Every card carries:

- **Episode** — `close_in` sleeve (± just-bought / just-sold clocks)
- **Wider TF** — 180d before entry → 90d after exit (climbing-trend read)

Dashboard Lifecycle → **Post-sale reviews** mounts both; sealed detail’s old
`close_in`-only default is no longer the review surface.

**Tablet / iPad layout:** below ~1180px the dual charts stack (full card
width each). Expanded card detail and each chart mount scroll independently
(`overflow` + `-webkit-overflow-scrolling: touch`) so Safari does not clip
the right edge or fight whole-page pan. Charts keep their readable
`min-width` — swipe inside the chart / card, not hover-only affordances.

## Accept / Comment / reply

| Control | Meaning | Effect |
|---|---|---|
| **Accept** | Framing matches | Label + leave active queue |
| **Comment** | Missed pattern | Label + leave queue + **spawn reply stub** |
| **reply** tag | Factory response | Re-enters queue for owner Accept/Comment |

Factory reply v0 is a **deterministic ack stub**. Optional LLM prose may replace
the stub text later — still observe/alignment only, never Package L episode
debrief auto-tune.

## Dashboard bridge

| Action | Decision |
|---|---|
| `post-sale-review-ack` | Accept |
| `post-sale-review-comment` | Comment (+ text) |

Both batch into workflow `post-sale-review-ack.yml` → commit labels + queue.
Local serve: `POST /api/post-sale-review-action`.

CLI (optional drill-down):

```bash
ftse-post-sale-review refresh
ftse-post-sale-review accept --review-id …
ftse-post-sale-review comment --review-id … --text "…"
```

## Automation wiring

| Piece | Detail |
|---|---|
| Trigger | Daily `collect_ops_findings` → `check_post_sale_review_queue` |
| Findings | **Post-sale review queue (observe)** (info); reply-pending / unreplied Comment warns; empty-trail warn when candidates exist but history empty |
| `auto_fixable` | Always `False` |
| Commit | `post_sale_review_queue.json` (+ labels when present) in ops-monitor `GHA_COMMIT_OPTIONAL` |
| Human gate | Checklist `sunday-post-sale-reviews` beside `sunday-post-sell-cues` |

## Forbidden

- `influences_live` / knob / fill changes
- Silent drop of Comments
- Treating LLM reply as Package L capital influence
- Dumping the full queue onto Daily hub Push (Explore ≤2 cues only elsewhere)
