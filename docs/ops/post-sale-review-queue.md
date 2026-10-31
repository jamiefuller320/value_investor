# Post-sale review queue (Package M)

Owner alignment loop for **closed exits** across all sealed Lifecycle books
(N200 / N201 / N206 / N210+) **and** FTSE control (`buy_tier_level`), tagged.
Observe-only — `influences_live=false`. Not Package **L** auto-tune.

## Owner job

1. Check that reviews of **relevant charts** are happening (episode + wider TF),
   annotated with factory **opinion** + **learning points** on first open.
2. **Comment** on patterns that might have been missed — do **not** force knobs.
3. Comments are **considered and responded to** (durable note → factory reply in
   history — LLM when enabled, else contextual deterministic) — not silent
   ignore, not auto-apply. Active queue stays **uncommented exits only**.
4. **Accept** = framing matches what I see. Accept / Comment / Duplicate all
   clear the card from active; dialogue lives under durable history.

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

**Active attention filter (Package M):** uncommented exits only — `just_sold`
always; `post_sale` when ≤21d since exit **or** return ≤ −5%. Factory `reply`
events stay in labels history (never re-queued). Coverage counts still include
the full candidate set so sealed/control population stays visible in ops findings.

## Sort + duplicates

Dashboard Lifecycle → Post-sale reviews has **touch-friendly sort chips**
(**Interesting** · Date · Stock · Loss size · Book · Tag). **Default =
Interesting:** identity/quality breaks and other non-mechanical sells rise
above hard-rule mechanical exits (`hold_trading_days` / max-days,
`leave_buy_tier`, control `left_target_set`); newest exit within band. Date =
sell/exit newest first; Stock = name A→Z (ticker when name missing).
Accept/Comment/Duplicate unchanged (clear from active).

| Looks like a duplicate? | What it is |
|---|---|
| Same ticker on N201 **and** N206 (etc.) | **Intentional** — one card per sealed book (+ FTSE control). `book_tag` badge is the model tag; `review_id` differs (`book_id` in fingerprint). |
| Same ticker twice in **one** book, same entry/exit **day** | **Collapsed** via `episode_key` (`book\|TICKER\|entry_day\|exit_day`) — keeps the worse `return_pct`. Fixes board chips with second-level entry jitter. |
| Same `review_id` twice | Already deduped; should not appear. |
| Commented episode still in active | Should not — Comment clears it; factory reply is history-only. |

## Buy / sell decision reasons

Every active card carries structured **bought because** /
**sold because** blocks (`buy_decision` / `sell_decision`):

| Field | Meaning |
|---|---|
| `code` | Machine id (`leave_buy_tier`, `hold_trading_days`, `identity_break_ey_band`, …) or `unknown_unjoinable` |
| `label` | Short human-readable line |
| `source` | Where bound (`episode.*`, `observe.*`, `model_identity.n200`, `rebalance_log.trade_note`, …) |
| `join_ok` | `true` only when a structured trail matched — else fail-closed unknown |

Binding prefers chip / observe `exit_reason` + `entry_detail`, then N200’s
deterministic buy-tier identity, then FTSE control `rebalance_log` trade notes.
Never invents a sell trigger. Factory opinion + LLM reply prompts cite these
fields so comments like “premature sell” can be weighed against the real exit
code (e.g. leave buy-tier vs a tech/timing cue).

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

## Accept / Comment / Duplicate / reply

| Control | Meaning | Effect |
|---|---|---|
| **Accept** | Framing matches | Label + leave active queue |
| **Comment** | Missed pattern | Label + factory reply in **history** + leave active queue |
| **Duplicate** | Same pattern already commented (cross-book / repeat) | Label + leave active queue |

**Uncommented-only active queue:** Accept / Comment / Duplicate must not
bounce back after refresh. Factory replies are written to labels `events`
(and shown under durable history) — they do **not** re-enter `active`.
Blank ``?`` identity cards are fail-closed out of `active`; legacy
`active_replies` are cleared on refresh. Bridge flattens **slim** identity
(+ `episode_key`) onto the command payload. Soft reload and full page
refresh keep clears via session + `localStorage` until labels/queue catch
up (**max 2h** without durable catch-up — then the card resurfaces so a stuck
optimistic clear cannot hide a Q8B remainder while the start gate still counts
it). Cleared **`episode_key`** (calendar day) also stays out when board chips
rewrite entry/exit seconds (new `review_id`, same episode).

**Initial opinion** on every card is structured deterministic v0 (`opinion_source=
deterministic_v0`) with learning points + per-chart captions, plus **L633**
plain-language `buy_strengths` / `buy_weaknesses` / `sell_strengths` /
`sell_weaknesses`, one `learning_point_forward` (super-book lane candidate), and
same-day round-trip soft bias (`same_day_round_trip` /
`same_day_assessment`: `likely_weakness` default; `major_error_reverse` only with
durable cites — not a hard ban). Batch LLM prose upgrade of initial opinions is
deferred (**L627**).

### Pattern marks (chart annotations)

`chart_annotations.marks[]` maps the factory opinion onto drawable dual-horizon
overlays (hold path, same-day band, premature post-exit region, material-loss
path, entry-quality band, wider-range `range_ref`, exit `ma_context`). Dashboard
`charts.js` paints them; client may enrich range/MA labels from loaded closes.
Alignment-only — never live knobs / Package L. Caps ≤8 marks per card (iPad-first).

**Chip / tone colors (legend + in-plot):**

| Tone | Color | Meaning |
|---|---|---|
| `info` | blue | Context / framing (hold path, entry quality, range location, MA context, mechanical leave) |
| `warn` | coral / amber | Caution (same-day round-trip as default weakness; premature-sell post-exit band) |
| `weak` | red | Material loss path (≤ −5%) |
| `good` | green | Same-day reverse cited as major-error recovery |

Each mark carries `id`, `pattern`, `type`, `tone`, `label`, `charts[]`, optional
`t0`/`t1`/`ref`/`anchor`, and always `influences_live=false`. Entry-blind cards
use the entry lens (`entry_quality` / `support_context` / `ma_context`) — typically
all `info` (blue). In-plot labels truncate with a full-text tooltip; collide-avoid
keeps level + pattern text readable on iPad. Pattern chips are **tappable**: short
inline explain (tone blurb + cite / window) expands on tap; second tap or outside
collapses — iPad-friendly, not a prose wall.

**Factory reply** on Comment: opt-in LLM via `FTSE_POST_SALE_LLM_REPLY=1` on the
ack workflow (fail-closed to contextual deterministic). Deterministic path
**considers** the owner Comment (`human_comment_consideration`: agree / partial /
disagree) — never blind-follows into knobs. Still observe/alignment only — never
Package L episode-debrief auto-tune. `learning_point_forward` may feed the
cue-consumer MFT lab intake when that sleeve is running — see
[cue-consumer-mft.md](cue-consumer-mft.md).

### Human chart draw (N229)

iPad-first tools sit **on each chart pane** (toolbar strip adjacent to the
plot — not orphaned in card chrome) for dual-horizon + entry_blind PIT:
**Highlight** (time band), **H-line**, **Trend** (two taps), **Parallel**
(drag primary, then **3 draggable anchors**: start / end / separation; Done
locks). Drawings are **per chart view** (`episode` / `wider_tf` / `pit`) — not
blindly shared across panes. **Drawing before Comment is the intended flow** —
Comment **auto-seals** open Parallel edits and includes non-empty chart drafts
as `post_hoc_human_geometry` (no separate Attach click; Undo/Clear still apply).
Geometry travels on the Comment event + owner dialogue turn (committed labels
JSON — no Supabase). `parallel_pair` encodes `anchors` + signed `separation`
and derived `line_a`/`line_b` for the agent.

Factory / LLM reply receives geometry **only when** schema-valid and
`readable=true` (`src/value_investor/post_hoc_human_geometry.py`). Unread /
invalid → omit + banner; **never invent levels**. Always `post_hoc=true`,
`influences_live=false`, `source=owner` — critique-only; not sealed fill features
or live knobs. Client paints owner marks beside factory `chart_annotations.marks[]`
with a distinct owner tone. Entry-revisit has no marks pane yet (draw there later).

## Dashboard bridge

| Action | Decision |
|---|---|
| `post-sale-review-ack` | Accept |
| `post-sale-review-comment` | Comment (+ text) |
| `post-sale-review-duplicate` | Duplicate (optional note) |

All three batch into workflow `post-sale-review-ack.yml` → commit labels + queue.
Local serve: `POST /api/post-sale-review-action`.

CLI (optional drill-down):

```bash
ftse-post-sale-review refresh
ftse-post-sale-review accept --review-id …
ftse-post-sale-review comment --review-id … --text "…"
ftse-post-sale-review duplicate --review-id …
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

## Related — entry_blind (sibling)

Blind **entry** critique (PIT through buy day; no outcome leakage) lives in a
separate queue: [entry-blind-review.md](entry-blind-review.md). Do not mix
post-sale outcome chrome onto `entry_blind` cards.
