# Strategy-book dashboard data map

Tree read: `main` at `747b414426` (2026-11-06). Stores under `docs/data/` were generated around 2026-11-06 02:32 UTC unless noted. Open work that is **not** on main: PR **#1311** (`cursor/strategy-book-reland-567c`, opened 2026-11-06), which stacks the walker/forward job (`origin/cursor/strategy-book-walker-567c`, merged to that branch via #1309/#1310) and commits the first archive score store.

`Exists` column: **Y** = file on main today; **branch** = written or fetched only on PR #1311; **N** = no writer produces it yet.

Registration id: `owner-strategy-book-v0`. Seal on main: `docs/data/strategy_book_registration.json` (`signed` true, `signed_at` 2026-11-05T21:00:00Z, `spend_enabled` false, `first_score_store_committed` false). On the PR the same file adds `forward_live: false`, `first_score_store_committed: true`, and `first_score_store.path = docs/data/strategy_book_replay.json`.

Plan status (`docs/ops/strategy-reorientation-plan.md`): steps 1.1–1.9 and 2.1 signed/merged. **2.2 and 2.3 core are “building”** on the plan table (the plan on main has not yet recorded #1311). 2.5 US rehearsal registration is a draft on the PR (`strategy-book-us-rehearsal-v0`, `status: draft_awaiting_owner_signature`, `results_store_written_by_this_package: false`).

---

## 1. Cheap (raw screen `buy` / `strong_buy`)

| Store / field | Exists | Example | Notes |
|---|---|---|---|
| `docs/data/latest.json` → `reports[].signal` | Y | 248 FTSE rows; `run_at` 2026-11-01T07:33:21Z; signals hold 123, avoid 60, **buy 48, strong_buy 17** (65 buy-tier). Also `adjusted_signal`, `sector`, `rsi_14` (first row 33.22), `timing_signal` | Screen bundle from `ftse-publish` (`publish.py`). This is the live FTSE value set. `rsi_14` here is the chart-build series, not the walker’s prefix RSI. |
| `decision_input_inventory.json` → `rows[].signal` | Y | 65 rows, all buy-tier; `screen_run_at` same as latest. Sample `SCT.L` signal `buy`, `adjusted_signal` `buy` | FTSE holdings ∪ buy-tier only. Not the full 248. |
| `library_decision_input_inventory.json` → `rows[].signal` | Y | **378** graduated-market buy-tier rows; sample `AAI.AX` `strong_buy`, `adjusted_signal` `buy`, `signal_as_of` 2026-11-05 | One row per buy-tier name. `market_id` set (asx200, …). 21 graduated markets. |
| `operating_decline_gate.json` → `names[].signal` | Y | 773 scored names; signals hold 281, buy 280, strong_buy 131, avoid 81. FTSE buy-tier inside this file: 65 | Signal copied onto the gate row. Includes non-buy-tier. |
| `sector_headwind_gate.json` → `summary.buy_tier_names` | Y | **443** buy-tier names counted per market (65 FTSE + 378 library; a cross-listing counts in each market) | `as_of` 2026-11-06. `names_by_market[market][ticker]` does not repeat `signal`; membership is the buy-tier set used for sector counts. |
| Replay episodes `snapshot.signal` | branch | Lookahead primary example `BTRW.L` snapshot `signal=buy`, `rsi_14=31.48` | Only after #1311. See scoring section. |

Part 1 is renderable today from `latest.json` (FTSE) plus `library_decision_input_inventory.json` (library buy tier). No strategy-book “eligible today” list is written.

---

## 2. Operating-decline gate

| Store / field | Exists | Example | Notes |
|---|---|---|---|
| `operating_decline_gate.json` | Y | `schema_version` 3, `generated_at` 2026-11-06T02:32:59Z, `as_of` 2026-11-06, `observe_only` true, `influences_live` false | Writer: `operating_decline_gate.py`. CLI: `ftse-operating-decline-gate`. Ops-monitor `check_operating_decline_gate`. |
| `summary` | Y | names 773, clear 540, declining 200, insufficient_data 33; **FTSE buy-tier covered 62/65**; declining buy-tier 9; interim revenue 30/65, interim EPS 33/65; fiscal years 2026:157, 2025:584 | `buy_tier_*` counts are FTSE only. |
| `names[TICKER]` | Y | keys: `market`, `sector`, `signal`, `verdict`, `reasons[]`, `checks`. Sample `0001.HK`. Verdicts: clear 540, declining 200, insufficient_data 33. Markets include ftse350 248, sp500 177, asx200 55, … | Checks: `revenue`, `interim_revenue`, `operating_margin`, `eps_annual`, `eps_interim`, `fcf`, `dividend`, `profit_warning`. Each check: `evaluable`, `fired`, `strength` or `why`, plus numbers (`change_pct`, `latest_year`, …). ~1.0 MB. |
| Point-in-time history of verdicts | N | — | One overwritten snapshot. A verdict applies only to sessions **after** `as_of`. Archive full-strategy walk is empty for this reason (below). |
| Replay `decline_rejected_shadow` | branch | Lookahead: 64 shadow episodes; mature board count 8, median fair-cost +5.6%, launch share 0.375. Buy-tier-only archive (no gates): shadow count 0 | Column id `decline_rejected_shadow`. |

FTSE buy-tier verdict mix on the current store: **clear 53, declining 9, insufficient_data 3**.

---

## 3. Sector headwind gate

| Store / field | Exists | Example | Notes |
|---|---|---|---|
| `sector_headwind_gate.json` | Y | schema 1, `generated_at` 2026-11-06T02:33:01Z, `as_of` 2026-11-06, `strategy_part` `"3. Sector sound"` | Writer: `sector_headwind_gate.py`. CLI: `ftse-sector-headwind-gate`. |
| `summary` | Y | 22 markets, **211 sectors: sound 71, headwind 25, insufficient_data 115**. Buy-tier 443: headwind 78, insufficient_data 31. Basis: own_market sound 309 / headwind 59 / insufficient 29; regional sound 25 / headwind 19 / insufficient 2. Earnings-growth fallback used on sound 265 + headwind 76 + insufficient 29 | `by_market` also present. Regional sector rows: 31 (sound 16, headwind 8, insufficient 7). |
| `universe` | Y | `included` starts ftse350, asx200, aex, … `admitted_library_markets` 21 names. Regions: uk, europe, north_america, asia_pacific | `not_scored` records skips (`not_graduated` / missing screen). `euro_depth` is not graduated. |
| `names` (FTSE) and `names_by_market` | Y | FTSE 248 names. Row keys: `market`, `sector`, `sector_verdict`, `sector_basis`, `own_market_verdict`, `screen_date`, `earnings_fallback_used`, `deciding_sector_key`, `region`. Sample `AEP.L`: sector Agriculture/Commodities, `sector_verdict` insufficient_data, `sector_basis` regional, `region` uk, `screen_date` 2026-11-01. All-market verdicts: sound 1174, insufficient_data 298, headwind 259. Basis: own_market 1565, regional 166. **FTSE verdicts: sound 234, headwind 12, insufficient_data 2** | 22 markets in `names_by_market`. `sectors` dict (242 keys) holds `verdict`, `reasons`, `metrics`, `members`, `buy_tier_members`, `earnings_fallback_used`. |
| `docs/data/sector_label_history.jsonl` | Y (append-only log; not fully summarised) | Promised by the sector runbook | Forward book reads `sector_label_as_of`. Not a dashboard sidecar. |
| Replay `sector_basis` / `sector_rejected_shadow` | branch | Lookahead primary episodes: `sector_basis` is **null on all 184** (gates not in force on archive dates; lookahead still did not stamp basis on the episode in this run). Shadow column: 39 episodes; mature board count 5, median fair-cost −5.5%, launch share 0.4 | Boards `sector_fallback.basis` and `.earnings_breadth` exist but split on episode fields that are empty in this replay. |

---

## 4. Entry at a short-term low (RSI(14) < 35 and 10-session low)

| Store / field | Exists | Example | Notes |
|---|---|---|---|
| Walker signal | code on main; scores on branch | Rules in `strategy_book_rules.py` / `strategy_book_signals.py` (`price_flags`). Episode snapshot stores `rsi_14` | Not a column on the screen row the book trusts. `latest.json` `rsi_14` is a different computation path (`compute_indicators`, 200-bar minimum). |
| `strategy_book_memo_job.json` signal counts | Y | `generated_at` 2026-11-06T02:33:01Z, `spend_enabled` false, `new_log_rows` 0. 22 markets, each `latest_bar` **2026-10-30**, `sessions` [], `suppressed_stale` [2026-10-30], `buy_tier` 0, `signals` 0, `all_but_memo` 0, `memo_needed` 0. `weeks` {} | Charts are behind the 5-day fill rule, so the scheduled job records no entry-rule hits. Schema: `schema_version` 1, `estimated_memo_usd` 0.4, `weekly_estimate` {low, high}, `data_commit`, `last_run_at`, `last_run_by_market` (22), `markets`, `errors`, `observe_only`, `influences_live`. |
| Replay event counts | branch | **archive_buy_tier_only** (price rule, no gates): `filled` 757, `already_open_skip` 1550, `no_chart` 29, `no_next_bar` 11, `buy_on_signal` 313, episodes 2096, scoring_date 2026-10-30. **lookahead_current_gates**: filled 287, episodes 839, insufficient_data events 33. **archive_full_strategy**: filled 0, episodes 0 | Three results must not be averaged. Full strategy is empty because decline/sector stores dated 2026-11-06 are not in force for sessions through 2026-10-30. |
| `strategy_book_forward_status.json` | branch (writer; file not in the PR diff) | Fields the forward job builds even on dry-run: `signals`, `entries_that_would_open`, `filled`, `pending_fill`, `late_signal`, `memo_not_ready`, `memo_blocked`, `blocked_reasons`, `phase_span_sessions`, `mature_count`, `thickness_ready`, `freshness.state` (`dry_run` while `forward_live` is false), `scoring_date`, `generated_at` | Written by `strategy_book_forward.py` when that job runs. `forward_live` is false, so it does **not** write `strategy_book_observe.json`. PR app.js already fetches this path. |

---

## 5. Exit: +10% launch, ratcheting floor, comparison exits

| Store / field | Exists | Example | Notes |
|---|---|---|---|
| Episode exit fields | branch (inside `strategy_book_replay_episodes.json.gz`) | Lookahead primary 184: open 156, closed 28. Exit reasons: floor_exit 24, fail_to_launch 7, thesis_break 2, still open 151. Example open `ftse350:ABDN.L:primary:2026-10-21`: fill 2026-10-22, entry 218.8, `launched` false, `floor` null, `fair_cost_return` +0.46%, `stake` 100, currency GBP, `mature` false. Closed example `BTRW.L`: `exit_reason` thesis_break, `highest_checkpoint` 0.1, `floor` 0.05, `recovery_label` false | Episode keys include `exit_reason`, `exit_session`, `exit_fill`, `highest_checkpoint`, `floor`, `floor_history`, `launched`, `launch_session`, `launch_index`, `gap_shortfall`, `fair_cost_return`, `gross_return`, `stress_return`, `matched_excess`, `column`. Columns per name: `primary`, `draft_v0_exit`, `ladder_no_deadline`, `leave_tier`, plus shadows. |
| Boards on `strategy_book_replay.json` | branch | Lookahead `floor_exits`: count 8, median fair-cost +7.4%, checkpoints {0.2:1, 0.15:4, 0.1:2, 0.5:1}. `paired_exits` keys: `draft_v0_exit`, `ladder_no_deadline`. `controls.leave_tier`: count 5, median fair-cost +1.5%. Buy-tier-only (no gates) floor exits: count 16, median +7.9%; controls buy-on-signal count 104, median +1.3% vs primary median difference +4.7 pp | Summary file **853 KB** (slot-book `skipped_ids` inflate `capital_view`). Episodes are **not** in the summary (`episode_count` only). Detail: `strategy_book_replay_episodes.json.gz` **3.7 MB**, same three result keys, each with `episodes`, `events`, `boards`, `counts`. |
| `strategy_book_observe.json` (forward book, the one that can meet the thickness gate) | N as a file; writer on branch, gated | Payload shape matches `walk_book()` plus `forward_live`, `start_date`, `generated_at`, `data_commit`, optional `disposition`, `change_markers` | Written only when `forward_live` and apply. Seal on the PR has `forward_live: false`. |
| Interim 26-week paired read | branch (board key, not published) | `boards.interim_read.published` is false until the forward book has run 26 weeks | Ops finding is specified in the observe runbook on the branch, not firing on main. |

Checkpoint ladder constants live in `strategy_book_rules.py` (`EXIT_FLOOR=floor_exit`, launch +10%, floors +5% after +10%, …, +75% after +100%).

---

## 6. Recovery hold, 63-session fail-to-launch, thesis break

| Store / field | Exists | Example | Notes |
|---|---|---|---|
| `fail_to_launch` board | branch | Lookahead: count 7, median fair-cost −8.4%, share below fill 0.71. Buy-tier-only: count 13, median −6.8%, share below fill 0.69 | Label `fail_to_launch` at session index 63. |
| `thesis_breaks` board | branch | Key present on all three results. Lookahead primary closed thesis breaks: 2 (`exit_reason` `thesis_break`) | `by_reason` uses `declining`, `headwind`, `screen_avoid`, `research_failed`. |
| `recovery_label` on episodes | branch | Lookahead primary: recovery_label true 59, false 125. Board `recovery_label` has count, launch_share, median_fair_cost. `reviews` on the thesis-break example: `[]` | Review indexes 63 / 126 / 189 are code (`REVIEW_INDEXES`). Memo job reads `strategy_book_observe.json` episodes for review memos; that file does not exist, so review memos are empty. |
| `launch` board | branch | Lookahead mature 15, launched 8, launch_share 0.53, median sessions to launch 10. Buy-tier-only: mature 30, launched 17, share 0.57 | |
| Decision log | branch | `decision_log[]`: `{session, index, close, entry_fill, action, launched, floor, download_as_of}` | Per episode in the gzip, not the summary. |

---

## 7. Limits: review dates, time cap, recovery-hold share

| Store / field | Exists | Example | Notes |
|---|---|---|---|
| `review_and_time_cap` board | branch | Keys `review_insufficient_data`, `time_cap` (`EXIT_TIME_CAP`, session 252), `review_cap` | Present; this replay’s chart window (~2 years, scoring 2026-10-30) is short, so time-cap counts are the place to read, not assumed non-zero. |
| Recovery-hold share | branch, partial | `capital_view.recovery_hold_capital_share` lookahead 0.38; `unlaunched_capital_share` 0.62; `long_hold_capital_share` 0.087; `cap_would_block_days` **0**; `recovery_share_line` 0.40 | `CAP_BLOCKS_ENTRIES` is false, so the 40% line is drawn and counted, not a block. Session-level `recovery_share_samples` are on the in-memory walk, **not** copied into the replay summary (`_view` keeps episodes/events/boards/counts/scoring_date/cap_would_block_days only, and the committed summary drops episodes). |
| `strategy_book_memo_log.jsonl` | N (path absent on main) | Job is wired; `new_log_rows` 0 | Would hold signal-day and review-date memo requests. Spend off, charts stale. |
| Review-date queue | N until observe store exists | Memo job documents fixture shape `episodes[].reviews[{index, session}]` | |

---

## Scoring

| Store / field | Exists | Example | Notes |
|---|---|---|---|
| Fixed-stake fair-cost episode % | branch | Stake **100** local units. Lookahead `boards.overall`: mature count 15, **median fair-cost +5.56%**, mean −0.51%. Buy-tier-only: mature 30, **median +5.98%**, mean +2.12%. Costs on the example: buy 0.525%, sell 0.025% | `decision_return_floor` is null until `mature` (63 sessions). Open unlaunched marks use latest close. |
| Matched excess vs same-market buy tier | branch | Lookahead: median **+0.22%**, mean −3.7%, SE 0.036, share above 0 0.53, fallback baskets 1. Buy-tier-only: median **+1.06%**, mean −1.5%, SE 0.006, share above 0 0.60, fallback baskets 4. Example `ABDN.L` matched_excess +0.64%, basket source `buy_tier`, count 67, fallback false | Basket members are embedded on each episode (large). Summary board is the cheap read. |
| Phase 2 thickness gate | branch | Lookahead: mature 15, counted 15, cap 6/week, min 48, span_sessions 73, span_met true, **ready false**. Buy-tier-only: mature 30, counted_before_cap 30, **counted 16** after the per-week cap, ready false. `per_week` has 3 weeks | Forward book only is allowed to pass. These archive numbers are not the gate. `provenance_missing` 0. |
| Phase 3 proof numbers | Y as sealed text; **N as measurements** | Seal `step_3_2_proof_numbers`: uncertainty (90% interval of median matched excess from 10,000 entry-week resamples wholly above 0); tail (5th percentile fair-cost ≥ −20%); drawdown (sterling 20-slot book ≤ 1.5× matched basket); market spread (median excess > 0 with largest market removed); regime spread (both halves ≥ 0 with ≥ 12 counted each); sterling slot book positive and ahead of the basket; tradable subset median excess > 0 | No module writes a proof-result object. `single_market_dependence` is a boolean on the replay boards (a piece of the market-spread test, not the full Phase 3 pack). |
| Bench challengers | branch | `boards.bench` keys `deep_dip`, `revenue_growing`, `fcf_agrees` (slot left for a fourth). Lookahead `deep_dip`: kept 9 of 15 mature, mean difference +8.3 pp, SE 0.034, counted_mature 9, `promotion_bar.count_met` false (needs 48 and 2.5 SE and both halves). Episode `bench` example: `{deep_dip: true, revenue_growing: false, fcf_agrees: false}` | `INITIAL_BENCH` in `strategy_book_rules.py`. |
| Gate-rejected shadows | branch | See parts 2 and 3. Buy-tier-only shadows are 0 (gates off). Lookahead has both columns | `insufficient_data` does not open a shadow. |
| Selection board | branch | `boards.selection_fifths` features include `composite_score`, `signal_rank`, `weeks_at_signal`, `conviction_score`, `fcf_yield`, `ev_ebit`, `earnings_yield_pe`, `roic_proxy`, plus price features on the snapshot (`return_20`, `return_126`, `rsi_14`, `fall_from_high_252`, `range_pos_126`). Fifths are `{fifth, count, launch_share, median_fair_cost, capital_days_return, standard_error}` for `whole` and halves. **composite_score fifths are count 0** on this replay (feature missing → episode sits out) | `selection_coverage` is the coverage companion. Snapshot also copies the whole screen `fields` dict (trade-plan levels, overlays). |
| Signal-day memo job | Y (summary); log N | See part 4. Spend off. Ops finding: “Strategy book memo job refreshed”, signals 0, charts stale at 2026-10-30 | CLI `ftse-strategy-book-memo`. Module `strategy_book_memo_job.py`. Does not write episodes. |
| F9-B binds | Y | FTSE inventory: **64/65 all four true**; only gap `SCT.L` `memo_recent` false (memo_age_days 24.6, memo_at 2026-10-12). Gap counts: bodies 0, fcf 0, overlay 0, memo 1. Verdict `P1 green-enough`. Library: **33/378 all four**; gaps memo_recent 345, overlay 52, bodies 4, fcf 4. `generated_at` 2026-11-06T02:32:22Z. Row fields include the four booleans plus `memo_age_days`, `research_verdict`, `adjusted_signal`, filings counts. Library adds `fcf_basis_source`, `fcf_screen_ttm`, `market_id`, `all_four_green` | Writers: `decision_input_inventory.py` via `ftse-ingest-audit --decision-inputs`; `library_decision_input_inventory.py` via `ftse-ingest-audit --library-decision-inputs`. These snapshots are **not** a history. Replay episodes are all `f9_status: f9_unverified` (archive has no memos). |
| Trading 212 listing | partial | Ops finding **“Trading 212 catalogue fresh”**: age 1.32 days, fetched **2026-11-04T18:57:35Z**, limit 14d. Replay `t212_listed` is **`unknown` on all 184 lookahead primary episodes**; `t212_fetched_at` null; tradable board lists 0 listed / 0 not_listed / all unknown | Catalogue files live under `docs/data/library/t212_coverage/` (not opened; bulk library dir). No root-level `docs/data/*t212*` summary. Episode field exists in the walker; this replay did not resolve listings. A dated catalogue older than 35 days is defined as `unknown`. |
| Regime / cash-flow agreement boards | branch | Lookahead regime: above 12 (median fair-cost +6.1%, excess +0.24%), below 3 (median −19.3%). `cash_flow_agreement` keys `agrees` / `disagrees` / `missing`. Example episode `adjusted_signal` `hold`, `regime` `above` | Report-only. |
| Capital view | branch | Lookahead capital-days return +26.5% (this is capital-days, not the learning question). Slot book and buy-and-hold objects are inside `capital_view` (large `skipped_ids`). Recovery holds’ fair-cost sum −3.39 | 20 slots, seed 20261104, 15 random orders. |
| US rehearsal scores | N | Registration draft names `docs/data/strategy_book_us_rehearsal.json` and says this package does not write it | Blocked on owner signature and a Sharadar download. |
| `total_return_view.json` | Y, **not the strategy book** | schema 1, `updated_at` 2026-11-06T02:32:51Z. Tracks `ai_judgment` vs control; pair `ai_judgment_matched30_fair` vs `buy_tier_matched30_fair` from 2026-10-15, total returns +1.38% vs +0.50%. Benchmark `^FTSE` / `FTAL.L` | Paper-fund NAV. Writer `total_return_view.py`, refreshed by ops-monitor. Do not plot it as strategy-book episode %. |
| `market_status.json` | Y | schema 3, `generated_at` 2026-11-05T22:50:43Z, 24 markets. **Graduated (21):** asx200, aex, aim, atx, bel20, cac40, dax, euro_stoxx50, ftse_mib, ftse_smallcap, hang_seng, ibex35, iseq20, nasdaq100, omxs30, psi20, sp500, tsx60, smi, sti, us_adr_asia. `ftse350` is live, `is_graduated` false. `euro_depth` is focus/sprint, not graduated (replay `skipped_ungraduated: ["euro_depth"]`) | Per-market row keys include `market_id`, `is_graduated`, `ingest`, `filing_health`, `health`, `currency`, signal mix. CLI: `ftse-library market-status`. Also copied into `latest.json` by `ftse-publish`. |

Replay file top-level keys (branch): `registration_id`, `influences_live`, `archive_buy_tier_only`, `archive_full_strategy`, `lookahead_current_gates`, `buy_on_signal` (episode_count only), `alternative` (episode_count only), `no_chart` (29, e.g. asx200 `CSL.AX`), `skipped_ungraduated`, `markets` (22), `detail_store`. No `generated_at` on the summary. Each result: `boards`, `counts`, `scoring_date` (2026-10-30), `cap_would_block_days`, `episode_count`. Board keys (28): `overall`, `matched_excess`, `launch`, `floor_exits`, `fail_to_launch`, `thesis_breaks`, `review_and_time_cap`, `recovery_label`, `by_market`, `single_market_dependence`, `paired_exits`, `interim_read`, `stress`, `shadows`, `selection_fifths`, `selection_coverage`, `channels`, `bench`, `controls`, `capital_view`, `sector_fallback`, `cash_flow_agreement`, `tradable`, `regime`, `memo_readiness`, `late_signals`, `thickness_gate`, `provenance_missing`.

`by_market` on the lookahead result collapsed to **`other`** (no market has 10 mature episodes). `memo_readiness` / `late_signals` are filled-count maps, not memo outcomes (`late` empty). `channels.hl_basis` is on the board; episode `channels` includes `hl_basis`, `ch126_*`, `ch252_*` style keys.

---

## Ops findings on main (`ops_status.json`)

`run_at` 2026-11-06T02:32:01Z, `overall` warn, 36 findings. Relevant ones (category `research` unless noted):

| Title | Severity | What it says today |
|---|---|---|
| Operating-decline gate refreshed (observe) | info | as_of 2026-11-06: 773 names, clear 540, declining 200, insufficient_data 33; FTSE buy-tier covered 62/65, declining 9 |
| Sector headwind gate refreshed (observe) | info | 22 markets, 211 sectors: sound 71, headwind 25, insufficient_data 115 |
| Sector headwind gate coverage gap | warn | Buy-tier sectors still thin (Agriculture/Commodities; several library markets mostly insufficient_data) |
| Sector headwind gate fallback reliance (observe) | info | Buy-tier by basis and by earnings-fallback (matches the summary above) |
| Strategy book memo job refreshed | info | Spend off. Signals 0. Every market chart stale, latest bar 2026-10-30 |
| Trading 212 catalogue fresh | info | Age 1.32 days, fetched 2026-11-04 |

No finding yet for thickness-gate ready, forward-book freshness, or archive-replay publish. Those titles are specified on the branch observe runbook (`Strategy book thickness gate ready for review`, and forward/close-refresh findings) and are not in today’s `ops_status.json`.

---

## Writers and CLIs

On **main** (`pyproject.toml`):

| Store | Module | CLI |
|---|---|---|
| `operating_decline_gate.json` | `operating_decline_gate.py` | `ftse-operating-decline-gate` |
| `sector_headwind_gate.json` | `sector_headwind_gate.py` | `ftse-sector-headwind-gate` |
| `strategy_book_memo_job.json` (+ jsonl when a row is logged) | `strategy_book_memo_job.py` | `ftse-strategy-book-memo` (drill-down; scheduled via ops-monitor) |
| `decision_input_inventory.json` | `decision_input_inventory.py` | `ftse-ingest-audit --decision-inputs` |
| `library_decision_input_inventory.json` | `library_decision_input_inventory.py` | `ftse-ingest-audit --library-decision-inputs` |
| `total_return_view.json` | `total_return_view.py` | no script; ops-monitor `refresh_total_return_view` |
| `market_status.json` | `market_status.py` | `ftse-library market-status`; also `ftse-publish` |
| `ops_status.json` | `ops_monitor.py` | `ftse-ops-monitor` |
| `strategy_book_registration.json` | hand seal, not a generator | — |
| Replay / observe **code** | `strategy_book_replay.py`, `strategy_book_observe.py`, `strategy_book_signals.py`, `strategy_book_rules.py` | `ftse-strategy-book-replay`, `ftse-strategy-book-observe` |

`ftse-strategy-book-replay --persist` writes `docs/data/strategy_book_replay.json`. On main it refuses the real tree unless the seal is signed (it is signed), but **nobody has committed the output on main**. The committed score store is PR #1311, and that PR’s writer splits episodes into `strategy_book_replay_episodes.json.gz` (`detail_store`).

On **PR #1311 / walker branch only**:

| Path | Module | When |
|---|---|---|
| `strategy_book_replay.json` + `strategy_book_replay_episodes.json.gz` | `strategy_book_replay_cli.py` | Already committed in the PR (step 2.2) |
| `strategy_book_closes.json` | `strategy_book_prices.py` | Close refresh; `closes_through` per market. CLI `ftse-strategy-book-prices` |
| `strategy_book_forward_status.json` | `strategy_book_forward.py` | Every forward run, including dry-run. CLI `ftse-strategy-book-forward` / `ftse-strategy-book` |
| `strategy_book_observe.json` | same | Only if `registration.forward_live` and apply |
| `strategy_book_gate_log.jsonl` | same | Appended with the observe store |
| `strategy_book_us_rehearsal.json` | not written | Draft registration only |

Remote branches matching the search, and whether they add stores:

- `origin/cursor/strategy-book-reland-567c` — **the open PR**. Commits the replay summary + gzip, US rehearsal registration, forward job, prices module, dashboard sidecar for forward status. Last commits: “Commit the first strategy-book score store: step 2.2 archive replay”; “Split the strategy-book replay store into a summary and gzipped episode detail”.
- `origin/cursor/strategy-book-walker-567c` and `origin/cursor/strategy-book-forward-567c` — same forward/prices code, **no** replay JSON (that landed on reland). Merged into the reland branch.
- `origin/cursor/sign-strategy-book-567c` — seal + US rehearsal registration draft, no score store.
- `origin/cursor/strategy-book-registration-567c`, `strategy-book-amendment-567c`, `strategy-book-amendment-2-567c` — older doc branches, already represented on main. No new stores vs main.
- `origin/cursor/n210-episode-walker-9a07` — N210 AI-judgment walker, not this book.
- Other `replay` / `episode` branches (`historical-screen-replay-9155`, `exclusion-ladder-replay-c0f4`, `dual-path-sleeve-episodes-389f`, …) are different instruments.

Open PRs (`gh pr list --state open --limit 30`): **only #1311**, “Re-land US rehearsal registration and forward job; first strategy-book score store (archive replay)”.

---

## Gaps (a new page would need these; nobody writes them yet)

1. **Forward episode store** `strategy_book_observe.json` — schema is implemented, persist is behind `forward_live: false`. No open episodes, review dates, `late_signal` fills, or `signal_seen_at` on disk.
2. **Gate log** `strategy_book_gate_log.jsonl` — same gate.
3. **Close-refresh state** `strategy_book_closes.json` — writer is on the branch, no committed file. Today’s charts stop at 2026-10-30, which is why the memo job is idle.
4. **`strategy_book_forward_status.json`** — the only strategy payload the PR’s dashboard actually fetches, and it is produced by a job that is not on main yet. Until that job runs, the fetch 404s.
5. **Memo log** `strategy_book_memo_log.jsonl` — writer exists, zero rows, file absent. Spend stays off until go-live.
6. **Phase 3 proof block** — bars are sealed text only. No bootstrap interval, no 5th percentile, no sterling slot-vs-basket drawdown.
7. **Dated gate history.** Full-strategy archive result is empty. A page that shows “would this name pass today” must use the live gate stores, and must label lookahead replay as painted-back current gates.
8. **Trading 212 per name on the book.** Replay marks every episode `unknown`. The catalogue is under `docs/data/library/t212_coverage/` with no small root-level board. Ops only publishes freshness.
9. **Selection fifths are mostly empty** where the snapshot feature is missing (`composite_score` fifths count 0). Coverage has to be read from `selection_coverage`, not assumed.
10. **Recovery-share time series** is not in the committed replay summary (only `cap_would_block_days`, which is 0).
11. **US rehearsal results** `strategy_book_us_rehearsal.json` — named, not written; registration unsigned.
12. **Eligible-today roster** (parts 1–3 and F9-B all true, plus RSI/10-session low) — no store. The page can join the four live files, but the price rule is only inside the walker.
13. **`by_market` board** is a single `other` bucket until a market has 10 mature episodes.

---

## Publish / fetch

`ftse-publish` (`publish.py` `publish_dashboard`) builds **`docs/data/latest.json`** as the screen bundle: `reports`, backtest, paper automation, and copies of `automation`, `project_progress`, `market_status`, `lifecycle_board`, `human_tasks_board`, and similar. It does **not** read `operating_decline_gate`, `sector_headwind_gate`, `strategy_book_*`, or the decision-input inventories. Those files are committed beside it by ops-monitor (`GHA_COMMIT_OPTIONAL`) or by `ftse-ingest-audit`.

GitHub Pages serves the `docs/` directory. `docs/app.js` `fetchDashboardJson` loads `data/latest.json` plus `DASHBOARD_SIDECARS` (lines 593–629): `market_status`, `total_return_view`, observe stores for N200/N201/N206/N210, and others. **None of the strategy-book or gate stores are in that list on main.** `market_status` and `total_return_view` are already fetched. Gate JSON, both inventories, the memo-job summary, and (once #1311 merges) the replay summary are already valid Pages URLs: `data/<file>.json`.

Cheapest page: add sidecar entries and fetch them directly. Do not merge them into `latest.json` (already ~6 MB; the replay summary is another 853 KB and the episode gzip is 3.7 MB). Suggested split:

- Boards and counts: `data/strategy_book_replay.json` (after #1311). Read `lookahead_current_gates.boards` and `archive_buy_tier_only.boards` separately. Skip embedding `capital_view.slot_book.skipped_ids` in the first paint if the payload feels heavy.
- Episode table: `data/strategy_book_replay_episodes.json.gz` on demand (browser `DecompressionStream`, or a summary-only page that never fetches it).
- Live gates and F9-B: `data/operating_decline_gate.json` (~1.0 MB), `data/sector_headwind_gate.json` (~1.3 MB), `data/decision_input_inventory.json` (38 KB), `data/library_decision_input_inventory.json` (403 KB). For a name list, prefer `summary` plus `names` / `rows` and do not pull `checks` until a row is opened (decline checks dominate the 1 MB).
- Job health: `data/strategy_book_memo_job.json` (10 KB) now; `data/strategy_book_forward_status.json` when the forward job exists. PR #1311 already adds that one key to `DASHBOARD_SIDECARS` and a `renderStrategyBookObserveSection` that reads `data.strategy_book_forward_status` only. The observe runbook on that branch says the score store is not rendered.

`total_return_view` stays on the existing pages; it is a different book.
