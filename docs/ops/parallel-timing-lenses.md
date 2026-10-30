# Parallel timing lenses (L652) — observe-only

Package **M** instrument: after stock choice on a shared candidate (from
`cue_consumer_mft` / `entry_blind`), spawn the owner-locked **buy trio** and
(at exit) **sell learning quartet** + **mechanical baseline**. A **favourite**
lens may enter when its rule fires; peers **keep looking daily** until their
own entry or durable abandon. Each lens scores **its own** fixed-stake episode
marks — never one shared NAV. **Concurrence** (count + which lenses) is an
observe companion in a short window around favourite entry (**N241** risk
sizing not_now).

Design lock (project store): `decision-hypothesis-slate-2026-10-30.md` §8–§10
(owner-locked catalog §9, 2026-10-30).

## Learning question

> Do competing buy/sell timing lenses on a shared candidate improve MoM lever
> learning (stock choice vs buy/sell timing vs strategy) versus a single-thesis
> path — without live influence, Package L, or a sealed zoo?

## Owner-locked v0 catalog

| Side | Ids | Notes |
|---|---|---|
| Buy learning (3) | `buy_support_bounce`, `buy_news_improve_path`, `buy_cheap_trend_confirm` | Cap ≤4 |
| Sell learning (4) | `sell_target_reached`, `sell_thesis_break`, `sell_tech_break`, `sell_failed_breakout` | Cap = 4 |
| Sell baseline | `sell_mechanical_leave` | **Beside** the sell cap — scoreboard baseline, not hero |

**`sell_failed_breakout`:** resistance reject / take profits ahead of give-back;
may **arm observe-only buy watch** at next level (**no auto-fill**).

## Stub vs live join (v0)

| Lens / field | Kind |
|---|---|
| `buy_news_improve_path` | **Live join** to L650 `entry_news_polarity` (`improvement_path` as cue — never hard filter) |
| Other buy/sell fire rules | **Deterministic stubs** over judgment/screen cites + `exit_reason` maps |
| Outcome gaps | Deterministic `had_but_ignored` + `missing_that_might_help` (+ cites) |
| LLM | Optional later |

## Outcome review (required)

At enter / abandon / close, each scored lens records:

1. **`had_but_ignored`** — PIT info available but unused / under-weighted (+ cites)
2. **`missing_that_might_help`** — info not available that might have helped (+ cites)

Compose with Package M autopsy / `learning_point_forward`; **never** Package L.

## Concurrence companion

- Count + `lens_ids` that **enter within `concurrence_window_days` (default 1)** of
  favourite entry (or on favourite entry day).
- Late hits outside the window do **not** inflate the count.
- `influences_live=false`; never size/veto/fill (**N241**).

## Surface

- **Primary store:** `docs/data/parallel_timing_lenses.json`
- **Entry blind:** compact `parallel_timing_lenses` field on cards (favourite +
  statuses + concurrence) — Lifecycle → Entry blind
- **Observe utilization:** instrument card on Automation → Queue & hunter

## Automation wiring

| Piece | Detail |
|---|---|
| Trigger | Daily ops-monitor `collect_ops_findings` → `check_parallel_timing_lenses` |
| Store | `docs/data/parallel_timing_lenses.json` (committed with ops-monitor) |
| Finding | **Parallel timing lenses (observe)** — coverage / looking/entered/abandoned; `auto_fixable=false` |
| CLI (optional) | `ftse-parallel-timing-lenses catalog\|refresh\|show` |

## Out of scope (v0)

- Package **L** / live hard filter / sealed zoo per lens (**N238**, **N239**)
- Multi-book NAV compete (**N240**)
- Lens-concurrence risk sizing (**N241**)
- Auto-fill from `sell_failed_breakout` buy watch

## Related

- [entry-blind-review.md](entry-blind-review.md)
- [entry-news-polarity.md](entry-news-polarity.md)
- [cue-consumer-mft.md](cue-consumer-mft.md)
- [ops-monitor.md](ops-monitor.md)
- [fair-cost-primacy.md](fair-cost-primacy.md#fixed-stake-v0-default-new-observe--models)
