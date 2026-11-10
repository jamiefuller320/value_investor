# Strategy reorientation plan

Step-by-step plan for moving the project from a value-screen learning lab
toward an autonomous system that runs the owner's
[investment strategy](../PROJECT_OBJECTIVE.md#investment-strategy-owner-2026-11-03).
Written 2026-11-03 after the autonomy readiness review.

Strategy in one line: buy cheap stocks with no operating decline and no
sector-wide trouble at short-term lows, let a rise run behind a ratcheting
profit floor, and hold mis-timed entries for recovery up to a fixed wait while
the business case still stands (exit amended 2026-11-04; see the
[registration](strategy-book-registration.md#4-exit)).

## Principles

1. **Build what the strategy needs, in its order.** Filters first, because they
   decide what is safe to buy and when a recovery hold must end. Then timing.
   Then proof. Then execution. Then breadth.
2. **New book, not edits.** The strategy runs on a cold-start book. Existing
   books and their histories stay as controls and are never rewritten.
3. **Observe first, then bind.** Each new component ships observe-only, wired
   into daily ops-monitor with a persisted store and a runbook
   ([full automation wiring](../../AGENTS.md#full-automation-wiring-required)).
   It binds a book only at a named phase gate the owner signs off.
4. **One question per instrument.** Every component states what it must prove
   or disprove before it is built.
5. **Stop adding instruments that do not serve a strategy part.** Existing
   observe instruments keep running. New ones need a strategy part in their
   learning question.

## Single track to live (owner, 2026-11-04)

The project settles on one route to live capital, so that improvements arrive
as versions of one book rather than as a new instrument each month.

1. **One track can reach live capital: the strategy book.** That is
   `owner-strategy-book-v0` ([registration](strategy-book-registration.md)) and
   its successor versions. Every other instrument is either a feeder (it
   produces inputs or proposals for the strategy book) or a control (it gives
   the strategy book something to beat). Nothing else is promoted toward live.
2. **Multi-market from v0.** The book reads the FTSE 350 screen and the library
   screens of every graduated market, with the existing per-name input-quality
   gate (F9-B). More markets give more closed episodes for the same rules. The
   live screener stays on the FTSE 350. Library entries need steps 1.8 and 1.9.
3. **The cue-consumer lab (super book) becomes a feeder and a reference.** Its
   aim, training toward better timing, is the right one; its design cannot
   reach live because it tunes itself mid-run and declares its scores
   incomparable. From now on:
   - its lab book keeps running unchanged on the FTSE screen as an outside
     reference ("buy on the weekly cue, hold 63 trading days");
   - the strategy book carries the same policy as its own buy-on-signal
     control on the same universe, which answers whether timing adds anything;
   - its review machinery (post-sale reviews, the judgment-in-the-round trail,
     five-lever scoring) moves onto strategy-book episodes in step 2.4;
   - its tune proposals feed the version review below. Sealed-child spawn,
     novelty distance and cull (N223, N226, N227) are not built while this
     section holds. See [cue-consumer-mft.md](cue-consumer-mft.md#role-under-the-single-track-owner-2026-11-04).
4. **Versions, not ideas.** v0 runs to its thickness gate. The version review
   happens at that gate and then at most once every 26 weeks. Between reviews,
   up to four sealed **bench** challengers (exit variants or entry filters)
   are scored daily on the book's own entries, with a 2.5-standard-error bar
   because several run at once ([registration](strategy-book-registration.md#8-scoring)).
   At each review the owner may promote **at most one** challenger. The
   evidence also includes post-sale reviews, five-lever scores, the selection
   board, the gate-rejected shadows, channel columns (N254), the US rehearsal
   (step 2.5) and demo-account fills. A promoted challenger becomes a new
   `registration_id`; the old version is frozen with its history. New bench
   challengers are sealed only at a review. Ideas that arise between reviews go
   to the deferred store with the tag `strategy-version-review`; they are not
   built as instruments.
5. **No new observe instruments** unless the instrument is a strategy-book
   component or a step in this plan. When step 2.3 starts, the owner decides
   which existing observe instruments to freeze. Candidates: N201, N206, the
   parallel timing lenses (L652) and the super book's unbuilt spawn and cull
   work. Frozen books keep their history.
6. **Execution starts early.** Step 5.1 (Trading 212 demo-account mirroring)
   starts once the forward book is running, not after its gate. It risks no
   capital, and real fills are part of the Phase 3 proof standard.
7. **Data priority.** At signature the strategy book takes the head of the
   launch queue for a narrow scope: filing bodies and memo recency on its
   universe names that already pass parts 1 and 2 (registration question 7).
   Holdings and the running units stay ahead of it.
8. **Learning rate, stated.** Forward evidence is slow. In replays a paired
   difference of about 2 points per trade took roughly a year of multi-market
   entries to read clearly, and longer on the FTSE 350 alone. Four things
   speed it up, in order of effect:
   - **long history first:** the US point-in-time rehearsal (step 2.5) tests
     the rules and candidate filters on 25 years, including four market falls,
     so the forward book confirms instead of searching;
   - **breadth:** library entries (steps 1.8 and 1.9) multiply the number of
     trades;
   - **same-entry comparisons:** bench columns and comparison exits score
     variants on the same trades, which removes most of the market noise;
   - **selection is cross-sectional:** each week offers many names to compare
     side by side, so "which names make the better winners" (the selection
     board) learns faster than "which timing rule is better".
   A slow read is expected, not a failure.

Owner decisions under this section (version reviews, the instrument freeze)
are in the [human tasks checklist](human-tasks-checklist.md#ad-hoc-when-triggered).

## Phases

Each step lists the deferred-store entry it closes, the deliverable, and when
it is done. Phase gates are owner decisions, listed in the
[human tasks checklist](human-tasks-checklist.md#ad-hoc-when-triggered).

### Phase 0 — Brief (done 2026-11-03)

| Step | Deliverable | Done when |
|------|-------------|-----------|
| 0.1 | Strategy written into `PROJECT_OBJECTIVE.md` | Merged |
| 0.2 | This plan | Merged |
| 0.3 | Plain-English glossary of codenames (L666) | `docs/glossary.md` covers every code used in `AGENTS.md` and `PROJECT_OBJECTIVE.md` |

### Phase 1 — Filters and foundations (observe-only)

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 1.1 | **Operating-decline gate v0.** Per-name verdict (`clear` / `declining` / `insufficient_data`) with cited reasons, from multi-year annual statements, interim EPS, FCF and dividend flags, and profit-warning / guidance-cut headlines in the filings index. FTSE 350 plus admitted markets. | N250 | Daily store refreshes; verdict on every FTSE buy-tier name; finding persisted in `ops_status.json` |
| 1.2 | **Sector headwind gate v0.** Per-sector verdict (`sound` / `headwind` / `insufficient_data`) from sector-wide price breadth and trend (daily charts) and breadth of operating decline among sector members. Judged on the sector as a whole. | N251 | Daily store refreshes; verdict on every sector holding a buy-tier name |
| 1.3 | **As-of-only research instruction.** Research prompts tell the agent to use only the supplied files as of the memo date. | L663 | Prompt text and test merged |
| 1.4 | **Scheduled Trading 212 catalogue refresh** plus a staleness finding. | L665 | Weekly workflow runs green with owner-added secrets; overlay refreshed |
| 1.5 | **Interim results in the decline gate**: diagnose interim coverage and read existing interim sources directly (live screen fields unchanged). Only 3 of 248 FTSE screen rows carry interim EPS today. | N250 | Diagnosis committed; gate scores year-on-year interim revenue and EPS where sources allow |
| 1.6 | **Keep prior-year quarters** in the Yahoo quarterly series so year-on-year interim comparisons work (8 buy-tier names already have a short series) | N252 | Interim revenue on those 8 buy-tier names |
| 1.7 | **Extract half-year revenue and EPS** from the 48 buy-tier half-year results bodies, after fixing filing body path resolution | N253 | Interim revenue and EPS on most FTSE buy-tier names |
| 1.8 | **Sector headwind gate on graduated library markets.** Score each sector within its own market: price breadth and trend from that market's charts, operating-decline breadth from the decline store. Library sector labels come from each market's `latest_signals.csv`; record the label on every refresh so later reads are dated. Same thresholds and fail-closed rules as v0. | N251 | Verdict on every sector holding a buy-tier name in a graduated market |
| 1.9 | **Input-quality binds (F9-B) for library names.** Compute `key_filing_bodies`, `fcf_basis_bound`, `overlay_bound` and `memo_recent` for library buy-tier names from their research folders, with the same meanings as `decision_input_inventory.py` (library rows carry no `fcf_basis_overlay`, so the FCF bind needs a library definition stated in the runbook). Report-only store plus finding; no rememo or ingest from the finding. Also the strategy book's **signal-day memo job** (owner, 2026-11-04): each weekday after each market's close, a fresh memo for every name that signalled, passes the other checks and has a memo older than 21 days, plus review-date memos on launched episodes; about 25–35 memos a week (about $10–14; the owner raised the `weekly_ops` cap by $16 a week for it on 2026-11-05) from the `weekly_ops` pool. Scheduled workflow, memo log, `memo_not_ready` finding ([registration section 11](strategy-book-registration.md#11-data-compute-and-the-launch-queue)). | N249 | Four binds on every library buy-tier name in a graduated market; memo job scheduled and logging |

**Phase 1 gate (owner):** review the gate verdicts on a sample of 10 FTSE
buy-tier names (5 flagged, 5 clear) against the cited evidence. Accept,
adjust thresholds once (logged), or reject.

### Phase 2 — Strategy book (observe-only)

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 2.1 | **Registration.** Pinned learning question, multi-market universe, entry-low rule, signal-day memo rule, checkpoint-ladder exit with the fail-to-launch deadline, comparison exits, gate-rejected shadows, selection board, challenger bench, stake, both controls and the gate are frozen before scoring. Draft: [`strategy-book-registration.md`](strategy-book-registration.md). | N249 | Registration committed; owner signs off |
| 2.2 | **Archive replay** of the rules on the daily chart history (about two years, 1,269 tickers), using the value set from archived FTSE and library weekly runs and the Phase 1 gates. Report-only: these names survived to be charted. Includes the buy-on-signal control and report-only channel columns (N254). | N249 | Ladder, comparison-exit, shadow, per-market and control boards published |
| 2.3 | **Forward fixed-stake strategy book** on the daily schedule after open settle, with an episode walker. Floor exits, fail-to-launch sales and thesis breaks scored separately; entry snapshots stored on every episode. Includes the daily close refresh for graduated-market buy tiers, open episodes and benchmark baskets, which runs before the walker. A signal seen after the next close is `late_signal`. Matched excess, Trading 212 listing and regime are recorded on every episode. FTSE names from the start; library names once 1.8 and 1.9 land. | N249 | Book running on closes no more than one session old; ops-monitor finding; dashboard strip |
| 2.4 | **Review layer on strategy-book episodes.** Point the post-sale review queue, the judgment-in-the-round trail and five-lever scoring (from the cue-consumer lab) at strategy-book closes. Reviews and lever scores are inputs to the version review, never mid-run tunes. | N222 | Every closed strategy-book episode reaches the review queue; lever scores published |
| 2.5 | **US point-in-time rehearsal.** Register, then run, the strategy book's rules, comparison exits, shadows, selection board and bench candidates on the licensed survivorship-free US history the historical screen replay already uses (S&P 500 and mid caps, 2000 onward, as-reported fundamentals), with that replay's 2013–2025 confirmation window used once. The window was already revealed for the value screen (hsr-v1) and is held by hsr-v2 and hrs-v2, so the rehearsal registration calls it reused and widens its confirmation bar for the number of tests ([registration](strategy-book-registration.md#c-us-point-in-time-rehearsal--report-only); rehearsal registration: [`strategy-book-us-rehearsal-registration.md`](strategy-book-us-rehearsal-registration.md)). Records the channel columns (N254). Report-only; US evidence about the method. | N249, L536 | Registration committed before data is bought; one licensed month run and deleted under the licence; development and holdout boards committed |

**Phase 2 gate (owner):** the sample-thickness gate fixed in the registration
(48 counted mature episodes, at most 6 per entry week).
If the owner stamps `design-open`, which needs both the median fair-cost episode and the median matched excess above zero, the strategy book becomes the primary learning track, with the matched-30
books as controls. The first version review (see
[single track to live](#single-track-to-live-owner-2026-11-04)) happens at
this gate.

### Phase 3 — Proof and accounting

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 3.1 | **Total-return accounting**: dividends in paper NAV; benchmark matches the universe | L528 | Merged; old marks keep their basis label |
| 3.2 | **New proof standard** for live capital: point-in-time history for parts 1–3; per-episode evidence for parts 4–6; paper implementation checks (fills, costs, data errors); matched excess read on the Trading 212-listed subset; a sterling view of non-sterling episodes. The standard must also require: uncertainty from block resampling by entry week (correlated entries are not independent tests); a stated tail and drawdown limit; spread across market regimes and markets (no single regime or market carrying the result); returns in sterling including FX; and a positive result for a cash-constrained slot book in sterling across markets, not only median episodes. The strategy book's thickness gate is not this standard. Numbers: [below](#step-32-proof-numbers-fixed-at-signature-2026-11-05) | N248 | N13 / N14 revisit triggers rewritten; owner signs off |
| 3.3 | **Non-US point-in-time replay** (UK / Europe) of the filtered value set | L664 | Needs an owner data-licence decision |

#### Step 3.2 proof numbers (fixed at signature 2026-11-05)

Owner, 2026-11-05. These are written now so that no forward result is read before they are set. They are proposed, not derived from data. The owner may change them once in the strategy book's signature note; the seal copies them ([registration section 10](strategy-book-registration.md#10-freeze-and-markers)). After that they change only through a new `registration_id`. All are read on the strategy book's forward episodes: counted mature episodes, `provenance_missing` excluded.

| Requirement | Proposed bar |
|---|---|
| Uncertainty | The 90% interval of the median matched excess, from 10,000 resamples of whole ISO entry weeks, lies wholly above zero |
| Tail loss | The 5th-percentile fair-cost episode return is no worse than −20% |
| Drawdown | The sterling reference slot book's largest peak-to-trough fall is no more than 1.5 times that of the matched buy-tier basket in sterling over the same dates |
| Market spread | The median matched excess stays above zero with the market holding the most mature episodes removed (no `single_market_dependence` flag) |
| Regime spread | The median matched excess is at or above zero in both regime halves (above and below the 200-session average), each with at least 12 counted mature episodes; `regime_unknown` episodes sit out |
| Sterling slot book | The 20-slot reference slot book, in sterling after fair costs and FX, has a positive total return and beats the matched basket in sterling over the same dates |
| Tradable subset | The median matched excess on `t212_listed` episodes is above zero |

Meeting every bar lets the owner consider step 5.5. It does not open live capital by itself.

### Phase 4 — Valuation and research focus

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 4.1 | **Fair-value range and margin of safety** in structured research output; used as the recovery target | L662, N5 | Observe-only field on memos; scored against outcomes |
| 4.2 | **Research aimed at the filters**: memos must cite evidence for or against operating decline and sector headwinds; confidence calibrated on outcomes | N173, N210 | Gate pass share no longer ~90% by default |

### Phase 5 — Execution

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 5.1 | Mirror strategy-book orders onto the **Trading 212 demo account** (limit orders at planned levels); record fills against assumed prices. Starts once step 2.3 is running, before the Phase 2 gate. The book scores on adjusted closes, but broker fills and cash are at raw prices, so this step keeps a separate **raw-price ledger**: raw fill prices, dividends as cash on their pay dates, splits and other corporate actions as explicit events, reconciled to the demo account statement. The ledger also defines what happens on a stale quote or a delisting. | L535 | Measured slippage replaces assumed spread for the book; the raw-price ledger reconciles to the demo account |
| 5.2 | **Read-only live account sync** (cash, positions) and reconciliation finding | N14 | Daily reconciliation green |
| 5.3 | **Supervised order drafts**: system proposes, owner approves each order | N14 | Owner approves N consecutive drafts without edits |
| 5.4 | **Binding kill switch** and position / drawdown limits on the live path | N13 | Tested by drill |
| 5.5 | **Small live capital** under the Phase 3 proof standard | N13 | Owner decision |

### Phase 6 — Breadth

| Step | Deliverable | Deferred |
|------|-------------|----------|
| 6.1 | Markets that graduate after signature join the strategy book by its universe rule; this step covers markets that need new ingest first (for example `sp400`) | — |
| 6.2 | Cross-market, currency-neutral ranking into one deployable book | L200 |
| 6.3 | Extend coverage toward the Trading 212 catalogue (mid / small caps) | L48, L534 |

## Delegation and supervision

Implementation is delegated to coding agents from the Cursor plan. A
supervising agent writes the brief, reviews the result, and owns coherence.
The owner signs phase gates only.

### Work-package brief (supervisor writes)

Every delegated package gets: the strategy part it serves; the learning
question; exact deliverables (module, CLI, ops-monitor check, store path,
runbook, tests); hard constraints (below); files it may touch; the branch name;
and the verification commands to run.

### Hard constraints on every package

- Observe-only unless the brief names a phase gate that has been signed.
  `influences_live` is false. No writes to existing books, knobs or
  `decision-review --apply`.
- Fully wired: daily ops-monitor check, persisted store under `docs/data/`,
  runbook in `docs/ops/` linked from [`ops-monitor.md`](ops-monitor.md),
  findings with `auto_fixable=False` for observe lanes.
- Point-in-time: no field dated after the decision it informs.
- Fail closed: missing data gives `insufficient_data`, never a pass.
- Tests for every verdict path. `pytest` for touched areas and `ruff check`
  green.
- No new codenames without a glossary line.

### Supervisor review checklist

1. **Standards:** constraints above; tests meaningful (not just shape); no
   debug leftovers; follows the module, CLI and store patterns of existing
   observe instruments.
2. **Coherence:** verdict names, thresholds and reasons match the strategy
   table; shared definitions are imported, not re-implemented; one store per
   instrument; plain-English runbook.
3. **Run it:** execute the refresh on committed data and read the output for
   sanity (coverage, flagged names, reasons).
4. **Decide:** approve, request changes (back to the same agent), or reject.

### Model allocation

Owner preference (2026-11-03): use the models included in the Cursor plan
(Composer, Grok) wherever they can do the job. Other models are the
exception, used only when a plan-included model has failed a review round on
the same package, and the status table records why.

| Package type | Model | Why |
|--------------|-------|-----|
| Small, well-specified edits (prompt text, workflow, staleness check, docs) | Composer 2.5 | Plan-included; enough for bounded work |
| Filter and instrument builds (new module, data joins, diagnosis, tests) | Grok 4.7 (high) | Plan-included; stronger reasoning over unfamiliar data shapes |
| Registration design, replay methodology, execution-path design | Grok 4.7 (xhigh) | Plan-included; highest-stakes drafts, then supervisor and owner review |
| Escalation after a failed review round | Claude Sonnet / Opus 5.5 or GPT-5.6 | Only when a plan-included model could not meet the bar |
| Review and integration | Supervising agent | Single owner of coherence across packages |

At most two implementation agents run at once, on separate branches, to keep
merge clashes manageable.

## Status

| Step | Status | Branch / PR | Model |
|------|--------|-------------|-------|
| 0.1, 0.2 | Done | `cursor/autonomy-readiness-review-567c` | Supervisor |
| 1.1 | Merged (one change round: one row label per comparison, freshness counts) | #1274 | Claude Sonnet 5.5 |
| 1.2 | Merged 2026-11-04 (one change round: decline-gate verdicts are the single definition of "declining"; screen fields are a material-threshold fallback) | #1278 | GPT-5.6 |
| 1.3 | Merged (single choke point; no prompt version or rememo trigger affected) | #1273 | Composer 2.5 |
| 1.4 | Merged. Secrets added; first live refresh 2026-11-04 (18,558 instruments) after the commit-pattern fix (#1286). Venue-aware matching and FTSE 350 overlay in #1289 | #1272 | Composer 2.5 |
| N254 | Channel column definitions (`channel_v0`) frozen in the registration; charts store highs and lows; the columns are computed by steps 2.2, 2.3 and 2.5 | #1292 | Supervisor |
| 0.3 | Merged (supervisor corrected two rows) | #1277 | Composer 2.5 |
| 1.5 | Merged. Buy-tier interim coverage did not move (2 of 65): Yahoo series lack the prior-year quarter and half-year bodies are not extracted, hence 1.6 and 1.7 | #1276 | Grok 4.7 |
| 1.6 | Merged 2026-11-04. Writer merges up to 12 quarters; git backfill gave interim revenue to 4 of the 8 buy-tier names (GSK, SHEL, BARC, BP). IAG, BGEO, ATYM, NWG have no prior-year quarter in git. No FTSE verdict change. Two library verdicts moved to declining (FSLR, HRL) | #1281 | Grok 4.7 |
| 1.7 | Merged 2026-11-05. One shared body-path resolver; half-year revenue and EPS pairs with cited lines, re-parsed at each daily gate refresh. FTSE buy-tier interim revenue evaluable 4 → 30 of 65, interim EPS 2 → 33. Interim EPS reads adjusted EPS first (owner, 2026-11-05). Three FTSE names moved to declining (ABF on interim EPS, EWG on EPS, VTY on revenue); Rank stays clear because its underlying EPS rose | this PR | Grok 4.7 (high) |
| 1.8 | Merged 2026-11-05 (#1300, fallbacks #1303). Library buy-tier insufficient_data 323 → 31 of 443. FTSE unchanged | #1300, #1303 | Grok 4.7 |
| 1.9 | Binds merged (#1301): 35 of 378 library buy-tier names pass all four (342 fail memo_recent). Memo job merged (#1304), spend off until signature. Dry-run on the five closes ending 2026-10-30 (latest stored bar in every market; charts are 6 days behind 2026-11-05): 399 buy-tier names on the last close, 73 entry-rule hits across those closes, 0 all-but-memo, 0 memo requests (weekly memo rate 0, below the 15–20 estimate). Gate stores dated 2026-11-05 do not pass an October close. The scheduled job records no request while charts sit behind the 5-day rule. **Memo spend on 2026-11-10 (owner)**, before go-live: `spend_enabled` true with `forward_live` still false, `weekly_ops` memo raise $16 → $40 a week (100 memos), 4-week spend-vs-use review (first 2026-12-08). Still zero requests: the decline and sector stores are rewritten with `as_of` = run date just before the job, so every earlier close fails Part 2 and Part 3 as `store_after_session` ([memo job](strategy-book-memo-job.md#spend-gate)) | #1301, #1304, this PR | Grok 4.7, then supervisor |
| Phase 1 gate | **ACCEPTED with one adjustment, owner, 2026-11-10.** Both gates accepted as they are, including the `>= 50%` sector line; the owner agreed with all ten sampled verdicts. The one adjustment (now spent): funds and investment trusts get `insufficient_data` from the decline gate (`fund_or_trust`), logged as change marker `owner-strategy-book-v0-fund-insufficient-data-v1`, not a new `registration_id`. Only FTSE buy-tier change: GCP.L `declining` → `insufficient_data`. Queued: L704, L705, L706. Record: [`phase1-gate-review-pack.md`](phase1-gate-review-pack.md#owner-decision-2026-11-10). `forward_live` stays false: go-live is a separate owner step. #1346 (bench seal), #1347 (memo spend), #1349 (gate dating, which fixed the verdicts-never-in-force blocker) and #1350 (forward refresh) have merged. Owner, 2026-11-10: forward start and go-live dates aligned, so the go-live edit sets `forward_start` to the go-live date with `forward_live` | this PR | Owner |
| 2.1 | Draft merged (#1280); revised for the single track, multi-market universe, capital view and the checkpoint-ladder exit (#1283). Owner answered the 9 open questions on 2026-11-04 (all defaults) and added the signal-day memo routine. **Signed 2026-11-05**, all proposed numbers unchanged, including the step 3.2 proof numbers (seal `docs/data/strategy_book_registration.json`) | #1280, #1283 | Grok 4.7, then supervisor |
| 2.2, 2.3 | Merged 2026-11-06. Walker (#1309), forward job, close refresh, findings and dashboard strip (#1310, re-landed in #1311). First score store: the archive replay (#1311): buy-tier-only arm 30 mature episodes, median +6.0% fair-cost, +1.1% matched excess; full-strategy arm empty (no dated gate history). Forward book dry-runs until `forward_live` is set after the Phase 1 gate review | #1309, #1311 | Grok 4.7 (xhigh), then supervisor |
| 2.5 | Registration **signed 2026-11-06** (all defaults and runner readings). Runner merged (#1312), Windows fixes (#1314), memory batching. Development committed 2026-11-07 (#1322): 3,802 mature episodes, primary median matched excess −0.11%. **Revealed 2026-11-07** (single reveal, evidence): 4,113 mature confirmation episodes 2013–2025, median matched excess −0.10% (Bonferroni 96⅔% interval −0.55% to +0.23%), fair-cost median +1.7%. Primary `inconclusive` (no bench consequence); both bench candidates `inconclusive`; delisting sensitivity unchanged. Licensed data deletion due 2026-12-07 | #1308, #1312, #1322, this PR | Grok 4.7 (xhigh), then supervisor |
| Bench | **Bench-fill review signed 2026-11-10** (owner): `trend_not_falling` (drop entries whose 6-month channel is falling, L689) sealed into the fourth slot before any forward score; bench full. Exit lab (2026-11-09) sealed nothing ([bench-fill review](strategy-book-bench-fill-review.md), [bench-seal review](strategy-book-bench-seal-review.md)) | this PR | Owner, then supervisor |
| 2.3 forward reliability | Go-live review fixes ([PR #1350](https://github.com/jamiefuller320/value_investor/pull/1350)): session-based weekend skip, partial-bar clip, ops-monitor crash guard. **Owner, 2026-11-10: "A second 17:45 run is fine"** (extra 17:45 UTC weekday forward slot, cron-job.org primary). Partial-bar clip logged as change marker `owner-strategy-book-v0-partial-bar-clip-v1` (bug fix, no rule change; owner: "Yes - log the partial-bar clipping") | #1350 | Supervisor |
