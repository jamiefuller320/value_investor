# Project glossary (plain English)

This page explains internal codes and jargon used in [`AGENTS.md`](../AGENTS.md) and [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) so you can read the project brief without memorizing shorthand. It is **maintained by hand** — when a new code or coined term appears in those two files, add a row here (or move it to **Unresolved** until a canonical definition exists in the repo).

| Term | Plain meaning | Where defined |
|------|---------------|---------------|
| auto-advance | Spare parallel ingest streams automatically start the next queued market when the current spare graduates ingest threshold. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| auto_fixable | Ops-monitor finding flag: automation may run a safe heal path; when false, the finding is observe or email handoff only. | [`ops/ops-monitor.md`](ops/ops-monitor.md) |
| body-lag rememo | Regenerate research memos after new filing bodies land, not before ingest improves source text. | [`AGENTS.md`](../AGENTS.md) |
| buy tier | Screen labels `buy` and `strong_buy` that mark the value set a name must sit in for strategy eligibility. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| buy_tier_level | Frozen paper book that holds the current raw buy-tier universe for lifecycle learning and diagnostics. | [`ops/buy-tier-cohort-labs.md`](ops/buy-tier-cohort-labs.md) |
| capital epoch | A frozen window of capital markers and books; policy experiments start a new epoch instead of rewriting live books mid-flight. | [`AGENTS.md`](../AGENTS.md) |
| checkpoint ladder | Strategy-book exit: after a close at +10% (launch), a profit floor ratchets up behind each checkpoint (+5% at +10%, +10% at +15%, and so on); a close at or below the floor sells. | [`strategy-book-registration.md`](ops/strategy-book-registration.md#4-exit) |
| clash-aware | Engineering capacity rule limiting parallel agent work so concurrent changes do not collide. | [`AGENTS.md`](../AGENTS.md) |
| cold-start | A new sealed book or observe registration that starts fresh history without back-labeling prior marks. | [`AGENTS.md`](../AGENTS.md) |
| collect_ops_findings | Daily ops-monitor step that gathers health checks and persists them for the dashboard and email. | [`ops/ops-monitor.md`](ops/ops-monitor.md) |
| compile-cap drain | Batched engineering workflow to clear compile-capacity backlog without one ticket per ticker. | [`ops/post-run-improvement-clearance.md`](ops/post-run-improvement-clearance.md) |
| counterfactual archives | Stored what-if outcomes for names near buy thresholds, kept for learning without changing live fills. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| decision pack | Structured human-facing bundle: signal, thesis, levels, size, and risks for verify-before-trade. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| decision-review --apply | Command that applies reviewed knob changes to eligible paper books after decision-review learning. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| deferred queue | Wanted-later ideas stored with `ftse-defer`; they wait behind P1 and P2, and are not dropped unless explicitly rejected. | [`ops/priority-queue-wording.md`](ops/priority-queue-wording.md) |
| epoch-0 | First admitted learning package for a market: frozen buy-tier-level book, weekday marks, near-miss watch, and equal-support timing. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| equal-support | After L322 admission, each admitted market gets the same weekday data path: epoch-0 marks, near-miss watch, rememo caps, and maintenance volume. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| euro_depth | Depth-first EU pilot index slice (STOXX 50 plus periphery) used as offline focus for filings and learning. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| episode | One round-trip trade scored at fixed stake after fair costs; floor exits, fail-to-launch sales and thesis breaks are scored separately. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| fair-cost episode % | Primary success metric: cohort median return per episode after fair trading-cost assumptions, not gross or fund NAV. | [`ops/fair-cost-primacy.md`](ops/fair-cost-primacy.md) |
| F3 | Accepted Investment repair priorities on holdings and running sealed units; Data accepts or defers them within P1 capacity. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| F8 | Fail-closed governance: green inventory, repair schedules, or observe metrics alone never apply knobs, fills, or live promotion. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| F9-B | Named-stock capital eligibility: filing body, FCF basis, overlay bind, memo freshness, plus market ingest gates when opening a book—not index membership. | [`AGENTS.md`](../AGENTS.md) |
| fail to launch | Strategy-book exit for a trade that has not closed at +10% within 63 sessions of the fill: sold at the next close whatever the price, to release its capital. | [`strategy-book-registration.md`](ops/strategy-book-registration.md#4-exit) |
| filing_ready | Market-level gate that filing coverage and trajectory are sufficient before treating shard learning as parity-ready. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| filings body | Extracted text from regulatory filings stored for research and bind checks, not just filing metadata counts. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| fixed-stake v0 | Default for new observe models: fixed notional per entry, no fund NAV or cash constraints on day one. | [`ops/fair-cost-primacy.md`](ops/fair-cost-primacy.md) |
| FCF basis | Bound free-cash-flow accounting basis on a name so overlays and decisions use consistent cash-flow definitions. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| ftse-defer | CLI that appends queued deferred ideas and regenerates the human review page without hand-editing JSON. | [`AGENTS.md`](../AGENTS.md) |
| ftse-decision-review | Learning loop that reviews automated paper trades for excess after costs and proposes small knob changes. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| ftse-library | Offline CLI for growing market libraries, screen-lite, research ladder, ingest, and shard learning workflows. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| FTSE 350 | Live UK screener universe kept until stage 4; separate from offline multi-market library growth. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| graduated market | A library market that has reached its ingest threshold (`is_graduated` / `sprint_ingest_complete` in `market_status.json`); its names may enter the strategy book if they pass F9-B. | [`ops/strategy-book-registration.md`](ops/strategy-book-registration.md) |
| green inventory | All required bind fields satisfied on the active Investment-demanded name set; success means maintain, not spray rememo or ingest. | [`AGENTS.md`](../AGENTS.md) |
| head_needs_fat_slot | Boolean ingest-head flag: while true, the cascade head keeps host priority and sized deepen width until parity or exhaustion. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| idle queue | Engineering task queue with no active work; triggers accelerated narrative refresh after merges. | [`AGENTS.md`](../AGENTS.md) |
| ingest cascade | P2 policy that serializes library filing sprint and maintenance across markets with one priority head and spare streams. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| IWB | Indexed-without-body filing gap class; leftover thin or IWB names can be parked so sprint ingest can complete. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| L1 | Deferred idea: decision-review learning on the automated paper book after costs. | [`deferred-review.md`](deferred-review.md) |
| L2 | Deferred idea: evolutionary genomes for stage 2 self-improvement with cost-aware fitness. | [`deferred-review.md`](deferred-review.md) |
| L3 | Deferred idea: wire advisory trade plans into the simulator instead of conviction-only fills. | [`deferred-review.md`](deferred-review.md) |
| L5 | Deferred idea: move trade-plan magic numbers into configuration for tuning. | [`deferred-review.md`](deferred-review.md) |
| L9 | Deferred idea: use Yahoo volume and ATR for technical signals instead of heavier scrapes. | [`deferred-review.md`](deferred-review.md) |
| L11 | Deferred idea: deeper UK-primary fundamentals from paid or official feeds beyond Yahoo gaps. | [`deferred-review.md`](deferred-review.md) |
| L21 | Deferred idea: external cron driving workflow dispatch with in-repo skip guards. | [`deferred-review.md`](deferred-review.md) |
| L24 | Deferred idea: run pytest on pull requests for CI hygiene. | [`deferred-review.md`](deferred-review.md) |
| L27 | Deferred idea: standard verify-before-trade decision packs for stage 2 manual excellence. | [`deferred-review.md`](deferred-review.md) |
| L28 | Deferred idea: multi-currency NAV and FX policy for global paper books. | [`deferred-review.md`](deferred-review.md) |
| L29 | Deferred idea: offline screen-lite archives for library markets (Layer B richness). | [`deferred-review.md`](deferred-review.md) |
| L30 | Deferred idea: selective budget research on library strong-buy candidates (Layer C). | [`deferred-review.md`](deferred-review.md) |
| L33 | Deferred idea: prioritize maintenance refresh by screen signal strength on graduated libraries. | [`deferred-review.md`](deferred-review.md) |
| L44 | Deferred idea: trailing stop sim track with entry-floor hard floor in technical sim. | [`deferred-review.md`](deferred-review.md) |
| L322 | Deferred idea: admit a market to equal learning resource when sprint ingest completes (raw parity or parked leftovers). | [`deferred-review.md`](deferred-review.md) |
| L323 | Deferred idea: split or stagger maintenance ingest across admitted markets inside one long job. | [`deferred-review.md`](deferred-review.md) |
| L460 | Deferred idea: commit observe-instrument JSON stores from ops-monitor in automation. | [`deferred-review.md`](deferred-review.md) |
| L461 | Deferred idea: dashboard panel for observe-utilization warnings with freshness and trajectory. | [`deferred-review.md`](deferred-review.md) |
| L499 | Deferred idea: quiet universe-wide filing cold-store archive lane for optional depth without starving P1. | [`deferred-review.md`](deferred-review.md) |
| L594 | Deferred idea: cold-store option value when multiple strands need different buy-tier shortlists from shared storage. | [`deferred-review.md`](deferred-review.md) |
| launch queue | Ordered wait list for newly sealed strategies so their Data work does not starve holdings or running units. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| Layer A | Offline library fundamentals layer: constituents, metrics, manifests, and point-in-time snapshots. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| Layer B | Offline screen-lite layer: dated model scores and signal history for library markets. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| Layer C | Selective research memos on top buy names with tight caps. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| llm_agree_veto_shadow | Observe-only pattern where an LLM agrees or vetoes algo proposals before any live hard veto. | [`ops/llm-agree-veto-shadow.md`](ops/llm-agree-veto-shadow.md) |
| maintenance ingest threshold | Same completion bar as sprint ingest complete: raw filing parity or exhausted parked thin and IWB leftovers. | [`AGENTS.md`](../AGENTS.md) |
| market_queue | Committed ordered list of index slices progressing through ingest cascade and epoch-0 admission. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| mature episode | A strategy-book episode whose fill is at least 63 sessions old, so it has either closed or launched; only mature episodes count for the decision median and the thickness gate. | [`strategy-book-registration.md`](ops/strategy-book-registration.md#8-scoring) |
| memo freshness | Research memo recency bind field so decisions do not rely on stale write-ups. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| N1 | Queued idea: widen the stock universe first (AIM, Europe, worldwide); held back because data quality, not universe size, is the bottleneck. | [`deferred-review.md`](deferred-review.md) |
| N2 | Deferred idea: evolutionary parallel sims deferred because sparse history overfits before costs. | [`deferred-review.md`](deferred-review.md) |
| N138 | Deferred idea: park off-buy-tier zero-filing memos until a explicit revisit trigger fires. | [`deferred-review.md`](deferred-review.md) |
| N200 | Sealed observe strand B: plain-value identity with technical entry and exit timing brackets on archive history. | [`ops/n200-tech-timing-observe.md`](ops/n200-tech-timing-observe.md) |
| near-miss | Names near buy thresholds tracked on observe-only watch for counterfactual learning without live entries. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| observe-only | Instrument or track that accumulates evidence and dashboards but does not move live capital or apply knobs by itself. | [`AGENTS.md`](../AGENTS.md) |
| ops-monitor | Daily automation that runs health checks, persists findings, and optionally applies safe fixes. | [`ops/ops-monitor.md`](ops/ops-monitor.md) |
| overlay bind | Research overlay present and applied so adjusted signals and accumulate paths are consistent on a name. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| P1 | First spend priority: absolute availability of bind fields on Investment-demanded names in fixed serve order. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| P2 | Second spend priority: offline ingest cascade depth before widening live screen or equal sprint streams. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| paper-auto | Weekday automation that runs paper-fund rebalance and related live learning paths on FTSE. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| Persistent weaknesses | Post-run analysis section rolling gap themes; not an automatic fix-everything engineering backlog. | [`ops/post-run-improvement-clearance.md`](ops/post-run-improvement-clearance.md) |
| PIT | Point-in-time constituent and fundamentals snapshots with dated history for unbiased backtests. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| point-in-time history | Historical records stamped as known on each date so later data cannot leak into past decisions. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| raw_buy_tier | Buy-tier membership from the screen without timing or overlay filters applied. | [`ops/n200-tech-timing-observe.md`](ops/n200-tech-timing-observe.md) |
| readiness gate | Explicit thickness or volume bar that must clear before promoting an experiment to adoption truth. | [`AGENTS.md`](../AGENTS.md) |
| recovery hold | Strategy rule: a position bought too early is held for recovery, not sold on a price drop, until it launches, reaches the fail-to-launch wait, or the thesis breaks. In the strategy book the label marks an 8% drop before launch. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| rememo | Scheduled refresh of existing research memos under caps, distinct from first-time research on new names. | [`ops/structured-verdict-slim.md`](ops/structured-verdict-slim.md) |
| richness before breadth | Live screener stays narrow and high quality while other markets grow offline in the library first. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| screen-lite | Offline quant screen and archived signals for library markets without changing the live FTSE screener. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| sealed unit | Running sealed strategy with its own registration and data SLA, such as strand A buy-tier or N200 observe. | [`AGENTS.md`](../AGENTS.md) |
| shadow judge | Observe-only evaluation path that must not override replay, sealed observe, or ingest-head priority rules. | [`AGENTS.md`](../AGENTS.md) |
| single track to live | Owner decision (2026-11-04): the strategy book is the only route to live capital; other instruments are feeders or controls. | [`ops/strategy-reorientation-plan.md`](ops/strategy-reorientation-plan.md) |
| so-what --apply | Gap-closure workflow that turns analysis themes into pinned ingest or promotion actions when appropriate. | [`ops/so-what-gap-closure.md`](ops/so-what-gap-closure.md) |
| sprint_ingest_complete | Ingest head finished: raw parity on filing counts or thin and IWB leftovers parked with a usable set remaining. | [`ops/market-sharded-learning.md`](ops/market-sharded-learning.md) |
| strategy book | The cold-start observe book that runs the owner's seven-part strategy (`owner-strategy-book-v0` and later versions). | [`ops/strategy-book-registration.md`](ops/strategy-book-registration.md) |
| strand A | The main FTSE paper-trading path: the buy-tier-level book and the matched assessment books. No real money is invested. | [`ops/primary-learning-track.md`](ops/primary-learning-track.md) |
| strong_buy | Strongest screen buy signal within the value set alongside ordinary `buy`. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| thesis break | The reason for owning a name has failed: operating decline, a sector headwind, a screen `avoid` signal, or a research `pass`. Ends any strategy-book position. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |
| three-lane model | Post-run clearance policy: ingest factory lane, engineering queue lane, and narrative refresh lane. | [`ops/post-run-improvement-clearance.md`](ops/post-run-improvement-clearance.md) |
| twin | Parallel book or metric path with frozen registration used to compare policy without editing the live book. | [`AGENTS.md`](../AGENTS.md) |
| version review | The point (at the strategy book's thickness gate, then at most every 26 weeks) where at most one sealed challenger version is chosen from accumulated evidence. | [`ops/strategy-reorientation-plan.md`](ops/strategy-reorientation-plan.md) |
| waiters | Sealed strategies in the launch queue not yet at the head for incremental Data deepen work. | [`ops/data-pillar-priorities.md`](ops/data-pillar-priorities.md) |
| weekly_ops | Orchestrator research spend pool cap for Sunday bundle and ladder selective research. | [`PROJECT_OBJECTIVE.md`](PROJECT_OBJECTIVE.md) |

## Unresolved

Terms referenced in the owner brief list or sibling docs but **not** defined in-repo in a way that satisfies this glossary’s one-sentence bar, or not used in the two source files:

| Term | Notes |
|------|-------|
| L666 | Deferred idea “Plain-English owner brief and codename glossary” exists on branch `cursor/autonomy-readiness-review-567c` but not yet in `docs/deferred-ideas.json` on `main`; this page implements that idea. |
