# Human tasks checklist

Manual gates for the **primary learning loop**, **knob calibration**, and
**promotion decisions**. Weekday paper-auto and Sunday analysis-review handle
most automation — this list is what still needs a human.

**Dashboard:** Automation tab → **Human tasks** — human gates as click-to-view cards
(analysis snippets from existing ops artifacts, Acknowledge, Approve on promotion
gates). New / changed **content** rises to the top; acknowledged tasks fall to the
bottom (Acknowledge / Approve re-sort and disable the button on click — session
overlay until git sidecar catches up; reload stays acked once `human_task_acks.json`
matches the content fingerprint). Republish timestamps alone do **not** mark an
ack stale. Automated weekday/Sunday CI rows stay in a collapsed list.

**Cadence map:** [`ops-review-cadence.md`](ops-review-cadence.md) — weekly analysis → monthly horizon → quarterly deferred.

**Canonical JSON:** [`docs/human_tasks_checklist.json`](../human_tasks_checklist.json)
— update this file **and** this markdown when adding tasks (see
[maintenance rule](#maintenance)).

## Weekday (Mon–Fri)

| Task | Who | Doc |
|------|-----|-----|
| **Spot-check learning tracks** after paper-auto — post-settle last_run + decision-review coverage of the assessment-model primary (`ai_judgment_fair`) and control (`buy_tier_level`), active calibrated shadows; frozen tracks skipped (ops-monitor 13:15; excess interpretation stays Sunday) | CI | [ops-monitor.md](ops-monitor.md#paper-learning-tracks) |
| Paper-auto + decision-review `--apply` (knob applies need a significant `track_statistics` verdict — `significance_gate_v1`; all active tracks; frozen tracks in `assessment_model.json` skipped; shadows + cohort lab observe-only; endurance ledger) | CI | [decision-review.md](decision-review.md#commands) |
| Admitted epoch-0 **local-open marks** (ASX / EU / US settle; not FTSE paper-auto; census refresh) | CI | [market-sharded-learning.md](market-sharded-learning.md#weekday-epoch-0-local-open) |
| Epoch-0 weekday **cron upsert** on learning admit + `--sync-cron` (timezone buckets; residual human only for unmapped TZ) | CI | [market-sharded-learning.md](market-sharded-learning.md#weekday-epoch-0-local-open) |
| **GHA secret hygiene** scan (skips if no merges / workflow touches in 36h) | CI | [gha-secret-hygiene.md](gha-secret-hygiene.md#automated-daily-check) |
| **Confirm buy-tier level first fill** — ops-monitor fails if the Suite B book acted empty; knobs stay frozen; do not treat NAV as promotion truth | CI | [buy-tier-cohort-labs.md](buy-tier-cohort-labs.md#level-book-live-monday) |
| FTSE **buy-tier level DCA realism** (£500/mo cold-start twin; overlays held-vs-market) | CI | [buy-tier-cohort-labs.md](buy-tier-cohort-labs.md#ftse-dca-realism-twin-buy_tier_level_dca) |
| Dual-path **sleeve episodes** (near-buy → grace-end+~1m widest lifecycle + on_book/off_book/never_funded tags; observe-only) | CI | [dual-path-sleeve-lab.md](dual-path-sleeve-lab.md#artifacts) |
| Admitted-market weekday rememo (3/day per epoch-0 book after maintenance ingest; catch-up 5 if that book exceeds 15) | CI | [market-sharded-learning.md](market-sharded-learning.md#what-enter-learning-means) |
| **Glance Daily hub** before acting on chat / Project notes todos — Automation → Daily (`#automation/daily`); prefer **status skim** (ops warns/fails, scoreboard headline, eng queue, defer triggers, post-run clearance) + **two lanes**: **Push** ≤1–3 (cite facts; P1/P2 for today; fail-closed) and **Explore** (may sit outside North Star / AGENTS; labeled not-today; claim + why + falsify/promote; durable → `ftse-defer`; never displace Push / not unbounded brainstorm); Focus P1/P2 are chips (do not ritual-Accept); **market warning triage** only when deepen/dismiss/park is decision-relevant (zero_body/unmeasured not dismissable; spare stall → park; bare health=warn stays email/monitor; no divert of maintenance capacity); prefer new_info / triggered gates over quiet ack theater; History for Accept vs Discuss; fresh before 04:00 Europe/London (early ops-monitor ~02:30 UTC); policy green ≠ utility; Accept = observe-ack only; Discuss → Project pickup; Accept-streak observe-only | Human | [ops-monitor.md](ops-monitor.md#daily-hub) |
| **Clear engineering parked backlog** when self-heal cannot clear the pause — hourly recover-queue already cancels resolved/superseded gap-closure parks and unparks healed preflight clashes *before* the warning email; when `attention_parked_count=0` and `queue_clearing.pause_active=false`, board rebuild **auto-acks observe-only** (quiet — no `list-parked` triage); human triages remaining oldest `list-parked` tasks only when pause/warning still fires; queue resumes when count &lt; 7 and 30m idle since last clearing action (separate from project-traffic stuck-PR pause) | Human | [ops-monitor.md](ops-monitor.md#engineering-parked-backlog-clearing) |
| **Project traffic** pause / unstick / grounded EOD digest + merges-today / completion monitor (today+yesterday counts, auto vs manual history bars, PR-fix interventions) + PR fix occasion log + automation-waste stop (Composer reburn / Cursor fail loops → park + pause; ops-monitor + weekday 12:30/17:30; ingest_narrow / scoring_narrow / compile_cap_drain independent verify/auto-merge listed in digest; spot-check wide diffs that still need human merge after `narrow_cohesion_bypass`) | CI | [project-traffic.md](project-traffic.md#authority-v1) |

## Sunday

| Task | Who | Doc |
|------|-----|-----|
| Read **analysis review** synthesis (`analysis_review.md`) plus the observe-only **chart-outcome** mix | Human | [analysis-review.md](analysis-review.md#artifacts) |
| Phase C readiness assessment (`phase_c_readiness.json` via `ftse-phase-c-readiness`; observe-only) | CI | [pit-decision-autopsy.md](pit-decision-autopsy.md#automated-readiness-gate) |
| **Start Phase C freeze writer only when READY** — do not begin autopsy build on vibes or `--force-phase-b-done` alone | Human | [pit-decision-autopsy.md](pit-decision-autopsy.md#automated-readiness-gate) |
| **Watch shard epoch-0 + near-miss** — do not fork shard AI-judgment or knob apply until epoch-0 plus the tight groups (buy-not-now, hold-near-buy) have marks; not-buy-tier / never-buy-tier are census, not the sample; FTSE stays the data lead | Human | [market-sharded-learning.md](market-sharded-learning.md#what-enter-learning-means) |
| **Watch ingest capacity** — spare sprint auto-advance is correct; crowded maintenance defaults to **2 markets/slot** (L454); capacity review auto step-down/up or proposes matrix; confirm jobs still finish | CI | [market-sharded-learning.md](market-sharded-learning.md#what-enter-learning-means) |
| Admitted-market equal-support then epoch-0 (`buy_tier_level` after timing stamp so wait stays out of new buys; near-miss watch; exclusion/exit-timing archives; Sunday first-time then focus rememo; admitted rememo and local-open marks are weekday; no AI / no apply) | CI | [market-sharded-learning.md](market-sharded-learning.md#what-enter-learning-means) |
| Review **unified experiment assessment** (`experiment_assessment.json`) — read fail/continue/recommend; failed shadows close promote; acked overlays + ana-* capacity are not do-now; Acknowledge when blocking recommends empty (never auto-promote). Refresh vs live board without reopening N58/N59 | Human | [experiment-assessment.md](experiment-assessment.md#human-gate) |
| Read the **assessment scoreboard** (`assessment_scoreboard.json`; Analysis → Observe model switcher defaults to Strand A · live) — primary vs control + FTAL; **nested (D4):** twins (hold-buffer + graduated), knob_calibration_priors (Acknowledge-and-stop when thin), buy_cross_archive_review (observe-only), and AI-path scoreboard subsection — not peer essays; frozen final records, `policy_changes`. **Approve a promotion** only when the primary verdict is positive on fair costs; N189 / frozen books / N200–N201 alone-scoreboard rules unchanged | Human | [assessment-scoreboard.md](assessment-scoreboard.md#assessment-scoreboard) |
| **Judge saturated decision-review knobs** — when ops-monitor warns *Decision-review knobs saturated at bounds*, read `saturated_knobs`; decide policy change / new epoch / no action. If the only book is evidentiary-demoted `ai_judgment_fair` (anti-C), that call is already no action and the warn is not Push. If that book is later **frozen** (e.g. `ai_judgment_fair` stop 2026-10-31), the warn clears (frozen tracks are not tunable). Another book in the same finding stays a now-card. Do not invent another knob step or `--apply` from the finding alone | Human | [decision-review.md](decision-review.md#saturated-knobs) |
| **Act on met deferred triggers** — when ops-monitor reports *Deferred idea triggers met / unreadable / name frozen books*, pick up (`ftse-defer status <ID> now`), retarget (`ftse-defer set-trigger`), or close (`status done\|drop --note`) each named idea; `ftse-defer triggers` shows the current list | Human | [deferred-triggers.md](deferred-triggers.md#clearing-a-finding) |
| **Review AI path scoreboard** — nest under assessment scoreboard read; agree/veto shadow rollup (disagreement / abstain vs heuristic + `still_in_buy_set`); roadmap phase status; no per-name AI chat; do not hard-veto (**N173**); beachhead stays later (N209/L606); nest neighbor `sunday-post-sell-cues` | Human | [llm-agree-veto-shadow.md](llm-agree-veto-shadow.md#sunday-ai-path-scoreboard) |
| **Scan post-sell cue digest** — thin nest under AI-path / scoreboard: `post_sell_cue_digest.json` timing + selection cues (current-epoch only; epoch_unknown excluded); check epoch join / widen gate still closed; N205 skeleton feed only (not sealed); park via `ftse-defer`; no `--apply` / no new track / no widen past FTSE control without epoch keys; nest neighbor `sunday-post-sale-reviews` | Human | [post-sell-cue-digest.md](post-sell-cue-digest.md) |
| **Work post-sale review queue** — Lifecycle → Post-sale reviews: all sealed + FTSE control; dual-horizon charts; Accept/Comment (+ reply tags); actioned clear from active queue; never knobs/fills / Package L | Human | [post-sale-review-queue.md](post-sale-review-queue.md) |
| **Work entry-blind review queue** — Lifecycle → Entry blind: lab/interesting buys; PIT through buy day only; Accept/Comment; no outcome leakage; never knobs/fills / Package L | Human | [entry-blind-review.md](entry-blind-review.md) |
| **Work entry-revisit queue** — Lifecycle → Entry +28d: after entry_blind Accept/Comment and buy+28d; frozen blind summary + path; never rewrite blind; never knobs/fills / Package L | Human | [entry-blind-review.md](entry-blind-review.md#entry-revisit-buy28d--shipped) |
| Review **entry DCA cadence / adoption plan** — Acknowledge is observe-only (Do not execute DCA from ack); Lifecycle **Start** enables 4× weekly on `graduated_allocation` only, which is frozen (2026-10-07), so `paper_execute_graduated` stays blocked until execute is repointed to `ai_judgment_graduated_fair` (N135); follow `entry_dca_adoption_plan.json`; do not change starter fraction or apply to primary | Human | [position-lifecycle.md](position-lifecycle.md#entry-dca-adoption-plan) |
| Review **dual-path sleeve episodes** when tag cohorts mature (`ready_for_sleeve_timing_analysis`) — stratify by capital_status; do not mix into NAV vs ^FTSE | Human | [dual-path-sleeve-lab.md](dual-path-sleeve-lab.md#evidence-gathered-to-date--validity) |
| Review **hypothesis integrity** when losers breach tolerance or theses break | Human | [hypothesis-integrity.md](hypothesis-integrity.md#human-gate) |
| Triage **analysis_tasks** — persist/publish/apply `system_gaps` flags auto-queue as `eng-sgap-*` (no dispatch); promote remaining produce/clock flags by hand; Phase B rememo is body-lag slim — do **not** promote `thin_memo_counted_as_coverage` as rememo-eligibility widening; scoring stays `eng-20260903-02` / `eng-20260903-03` (observe-only; no `assign_signal()` edits); do not revive cancelled knob counterfactuals | Human | [analysis-review.md](analysis-review.md#manual-promotion-to-engineering) |
| Triage **paper_learning_tasks** + **learning_director_tasks** — watch u4 + exit-shadow; leave L111 as continue; buffered-hold and IMB.L are done; no promote CLI | Human | [paper-learning-review.md](paper-learning-review.md#enacting-proposed-experiments) |
| Full-period knob calibrate on the primary (`ai_judgment_fair`; frozen books excluded) + endurance (no scheduled shadow spawn / warm-start while parent `ai_judgment` is frozen) | CI | [knob-calibration.md](knob-calibration.md#warm-start-zero-datum-forward-only-endurance) |

### Promotion gate (AI judgment knobs)

The Sunday **review** card (`sunday-knob-calibration-priors`) only confirms
readiness signals. When confidence is low/insufficient and
`score_gap_vs_runner_up < 0.005` on every track, **Acknowledge** satisfies that
review — board rebuild may auto-ack observe-only. That is **not** promotion.

Do **not** promote calibration priors to `ai_judgment/config.json` until
(`sunday-assessment-scoreboard`):

1. A shadow has status **recommend** in `experiment_assessment.json` (or **surviving** in `calibration_shadow_endurance.json`). Status **fail** closes this path — do not promote from failed shadows.
2. `ready_for_priors: true` / `ready_for_shadow_bootstrap` look sound in `knob_calibration_priors.json`
3. `score_gap_vs_runner_up ≥ 0.005`
4. `recommended_prior.confidence` is acceptable (not `insufficient` / thin `low`)
5. **Fair-cost view** supports treating excess as deployable (`ftse-trading-costs assess` and/or fair-cost shadows) — 3% stress excess vs ^FTSE alone is not the adoption datum

**Fail-closed (2026-09-29, N171):** calibrated shadows are **not** a promotion
path. While `ai_judgment_calibrated` (+r2/r3) are `experiment_assessment=fail`,
keep the promotion gate on `sunday-assessment-scoreboard` closed. Do not spawn new calibrated ranks, do
not reopen N58/N59, and do not disable shadow dirs mid-week (keep cheap marks;
retirement stays L275/L502). Revisit only after fair-cost Suite B evidence or a
new calibration method — not Suite A stress green.

**Pruned (2026-10-06):** the calibrated-shadow compare, fair-cost promotion,
Suite B twin-spawn and exclusion-spawn cards were retired (their books are
frozen, the scoreboard shows the 3% cost column); the promote gate and the
fair-cost primary/control review merged into `sunday-assessment-scoreboard`.

**Frozen (2026-10-06):** `ai_judgment` and its calibrated shadows are frozen in
`paper_automation/assessment_model.json`. The steps above now apply to the
primary `ai_judgment_fair/config.json` and any future shadow of it — see
[primary-learning-track.md](primary-learning-track.md#assessment-model-and-frozen-tracks).

Survivors are **starting priors for learning-loop refinement** — never auto-apply.
Raw `summary.recommend` (including acked overlays and capacity `ana-*` rows) is **not** a promote signal; see [experiment-assessment.md](experiment-assessment.md#human-gate).

## Monthly

| Task | Who | Doc |
|------|-----|-----|
| Follow **unified ops review cadence** (weekly → monthly → quarterly) | Human | [ops-review-cadence.md](ops-review-cadence.md#sequence) |
| **Horizon scan** — weeder drops near-dups; triage remaining fragments | Human | [horizon-scan.md](horizon-scan.md#when-it-runs) |
| Review **euro_depth filing/memo parity** vs FTSE before AI-gate / Phase 3 | Human | [market-sharded-learning.md](market-sharded-learning.md#depth-first-eu-pilot-aug-2026) |
| **Calibrate token-usage warning** — after 2–3 weeks of measuring, compare week raw cost with the Cursor usage page each plan cycle and set `token_usage_weekly_warning_raw_usd` (leave null until then; estimated-USD cap stays) | Human | [agent-token-usage.md](agent-token-usage.md#calibration) |
| Review **cycle-end Cursor surplus** — assess unused Ultra fraction, apply a 25% provisional weekly_ops bump (15% of plan credit / week is a warning on estimated USD, not a hard cap), keep or revert at the next cycle. Do not raise rememo daily caps or offline memo density from leftover credit | Human | [cycle-budget-surplus.md](cycle-budget-surplus.md#human-gate) |
| Review **common PR fix-request reasons** (`ftse-project-traffic common-issues`) — fix recurring CI / merge-conflict root causes | Human | [project-traffic.md](project-traffic.md#pr-fix-occasion-log) |
| **Review strategy-book memo spend vs use (every 4 weeks)** — from the 2026-11-10 switch-on (first review 2026-12-08; date in `operational_switches` on `docs/data/strategy_book_registration.json`), read the ops-monitor finding **Strategy book memo spend this week** and the weekly requested / budget-skip / spend counts in `docs/data/strategy_book_memo_job.json` against `budget.strategy_book_memo_raise` ($40 a week, 100 memos). Keep, lower or raise it; economise if memos go unused. Memo-to-decision use is not tracked yet, so judge use from fills vs `memo_not_ready` once `forward_live` is on. Set the next review date when you log the decision. No rememo of thin memos without new filing bodies (N138 stays) | Human | [strategy-book-memo-job.md](strategy-book-memo-job.md#spend-review) |

## Quarterly

| Task | Who | Doc |
|------|-----|-----|
| **Deferred ideas** review (`ftse-defer status`) | Human | [deferred-review.md](../deferred-review.md) |

## Ad hoc (when triggered)

| Task | Who | Doc |
|------|-----|-----|
| **Buy-cross archive** / **knob calibration priors** / **matched-30 twins** / frozen hold-buffer & graduated final records — triggered peers nested under `sunday-assessment-scoreboard` (D4); open only when readiness / scoreboard read needs the deep dive; do not spawn live cross; Acknowledge-and-stop on thin priors; matched-30 NAV only vs each other; do not unfreeze B3-frozen 3-name twins | Human | [assessment-scoreboard.md](assessment-scoreboard.md#assessment-scoreboard), [b3-scoreboard-epoch.md](b3-scoreboard-epoch.md#matched-30-pair) |
| **Lock recording plan** before new learning strands — four freeze questions + `ftse-decision-recording validate`; preview-freeze OK; Phase C writer stays readiness-gated | Human | [decision-recording-checklist.md](decision-recording-checklist.md#the-four-questions) |
| **Pin learning question** before registering a further post-hsr alternate (N200/N201/N206/N210 sealed observe-only; dual observe OK; strand A is the paper book and a control; the strategy book is the only route to live capital); respect launch queue; prefer P1/P2 until deliberate | Human | [post-hsr-freeze-extras.md](post-hsr-freeze-extras.md#next-engineering-steps) |
| **Stamp N200/N201 interestingness disposition** (`ack` / `no-design` / `design-open`) when alone-path interestingness fires — thickness volume-gate-ready is pipeline badge only; **no auto-promote** (F8). Owner 2026-10-31: N201 **design-open** stamped on `n201_value_mom_observe.json` (forks locked 2026-11-01) | Human | [n200-tech-timing-observe.md](n200-tech-timing-observe.md#human-volume-gate-review), [n201-value-mom-observe.md](n201-value-mom-observe.md#human-volume-gate-review) |
| **Stamp N206 interestingness disposition** (`ack` / `no-design` / `design-open`) — alone design optional; **no auto-promote**, no assessment-primary crown (F8 / O3). Owner 2026-11-01: **ack** stamped on `n206_plain_ey_observe.json` (no design pack) | Human | [n206-plain-ey-observe.md](n206-plain-ey-observe.md#human-volume-gate-review) |
| **Stamp N210 interestingness disposition** (`ack` / `no-design` / `design-open`) after thickness + interestingness — **no auto-promote** (F8 / B3) | Human | [n210-ai-judgment-observe.md](n210-ai-judgment-observe.md#human-volume-gate-review) |
| **Confirm freeze of cue-consumer MFT Q8B non-mechanical autopsy cohort** — checkpoint **complete** (2026-10-28); `evolutionary_shadows_eligible=true`; lab paper episode walker runs on eligible refresh (lab fills only). Keep as reference if a future named cohort is proposed. Still observe-only; no Package L | Human | [cue-consumer-mft.md](cue-consumer-mft.md#start-gate-q8b) |
| **Sign strategy reorientation phase gates** — Phase 1: **done 2026-11-10, accepted with one adjustment** ([owner decision](phase1-gate-review-pack.md#owner-decision-2026-11-10)): both gates kept as they are; the one adjustment, now spent, makes funds and investment trusts `insufficient_data` in the decline gate (change marker `owner-strategy-book-v0-fund-insufficient-data-v1`). It governs only `forward_live`, which is the next row; Phase 2: sign the strategy-book registration ([strategy-book-registration.md](strategy-book-registration.md)) before scoring, confirming or adjusting once the [step 3.2 proof numbers](strategy-reorientation-plan.md#step-32-proof-numbers-fixed-at-signature-2026-11-05) the seal copies, then its sample-thickness gate before it becomes primary; later: proof standard, demo-to-live execution steps, small live capital. Sign, adjust once (logged), or reject; nothing auto-promotes | Human | [strategy-reorientation-plan.md](strategy-reorientation-plan.md#phases) |
| **Flip strategy-book forward go-live after the Phase 1 gate review** — **Done 2026-11-11 (owner):** `forward_live: true`, `forward_start: "2026-11-10"`, logged in `operational_switches`. Phase 1 was accepted on 2026-11-10, and #1346, #1347, #1349 and #1350 have merged. On the go-live date, set `forward_live: true` **and** `forward_start: "<go-live date>"` on `docs/data/strategy_book_registration.json` in the same commit (owner, 2026-11-10: forward_start will equal the go-live date; recorded in `phase1_gate_decision.forward_start_alignment`). Phase 1 governs go-live, not the signature. Until `forward_live` is true the forward job dry-runs and writes no scored store. Memo spend is already on: the owner set `spend_enabled: true` on 2026-11-10 (logged in `operational_switches`), independent of `forward_live`; its review is the monthly memo spend task. Neither job flips its own flag | Human | [strategy-book-observe.md](strategy-book-observe.md#go-live) |
| **Rate the memo model comparison calibration sample** — rule v2 (owner, 2026-11-10): an LLM judge (`gpt-5.6-luna`) scores every pair blind in both orders, and you rate only a calibration sample of at least 4 names. When ops shows **Memo model comparison ready for owner calibration**, read `docs/data/memo_model_comparison/review.md` (sample only, memos labelled A/B). Copy `ratings_template.json` to `ratings.json` and rate each memo 1–5 on evidence, thesis break and verdict justified, plus a preferred memo (A, B or tie). Commit `ratings.json` to main without opening `blind_key.json`, `results.json`, `judge_results.json`, `calibration.json`, `judgements/`, `judge_status.json` or the `status.json` cost fields. Then run `gh workflow run memo-model-comparison.yml -f action=decide`. Your picks decide whether the judge is trusted and govern any pair where the two verdicts differ on blocking entry. If the pre-declared rule says switch, approve it, log an `operational_switches` row on the registration and change the memo model in its own PR. Otherwise `composer-2.5` stays | Human | [memo-model-comparison.md](memo-model-comparison.md#owner-calibration-review) |
| **Add Trading 212 API secrets** (`TRADING212_API_KEY`, `TRADING212_API_SECRET`, live read key) to GitHub Actions so the scheduled catalogue refresh runs; read-only endpoints, no order permissions | Human | [strategy-reorientation-plan.md](strategy-reorientation-plan.md#phase-1--filters-and-foundations-observe-only) |
| **Strategy book version review** — at the thickness gate, then at most every 26 weeks: read the supervising agent's evidence pack (overall and per-market boards, both controls, the challenger bench, the selection board, the gate-rejected shadows, the US rehearsal, post-sale reviews, lever scores, deferred ideas tagged `strategy-version-review`); promote at most one bench challenger that met its bar (2.5 standard errors on 48 counted mature episodes, same sign in both halves) into a new `registration_id`, or none; retire failed challengers; seal new ones (at most four at once) before their scores are read | Human | [strategy-book-registration.md](strategy-book-registration.md#8-scoring) |
| **Download the Sharadar bundle before 2026-11-09, run the strategy-book US rehearsal, and confirm deletion** — plan step 2.5. Access already held ends 2026-11-09. Before that date, bulk-download every bundle table (`years=full`) to `~/sharadar` (the screen-replay list: fundamentals, stocks, tickers, actions, sp500, daily, metrics, events, descriptions, funds, insiders, holdings, holdings_ticker, holdings_investor). Key in a local environment variable only. Then, including after access ends and before deletion: build both panels and the hsr-v2 and hsr-mid-v2 baseline caches without revealing those holdouts; run development; review; reveal this rehearsal's confirmation once; run the delisting sensitivity. Commit aggregates only. Delete raw and derived files within 30 days (by 2026-12-09 if 2026-11-09 is the cancel date), then `ftse-historical-replay confirm-deleted` and stamp the rehearsal store with `ftse-strategy-book-rehearsal confirm-deleted`. Copy-paste commands for each step are in the runbook; the rules stay in registration section 8. Scoring waits on the strategy-book signature; the download does not | Human | [strategy-book-us-rehearsal-runbook.md](strategy-book-us-rehearsal-runbook.md#before-you-start) |
| **Observe instrument freeze decision** — when strategy-book step 2.3 starts: decide which existing observe instruments to freeze (candidates N201, N206, L652 lenses, the super book's spawn and cull work); frozen books keep history | Human | [strategy-reorientation-plan.md](strategy-reorientation-plan.md#single-track-to-live-owner-2026-11-04) |
| **Approve the dashboard v2 plan** — approved by the owner 2026-11-06: the strategy-led v2 page (`docs/v2/`, beside the old dashboard) and its nothing-lost ledger | Human | [dashboard-v2-plan.md](dashboard-v2-plan.md#7-owner-decisions) |
| **Decide the dashboard v2 cutover** — after four weeks of v2's Today, Candidates, Book and Proof tabs on the forward book with every ledger row marked for v2 ported, decide whether v2 becomes the root page (old page to `docs/legacy/`) and the fate of the Trusts tab and browser sandbox | Human | [dashboard-v2-plan.md](dashboard-v2-plan.md#7-owner-decisions) |
| **Decision packs** before live capital (verify checklist) | Human | [primary-learning-track.md](primary-learning-track.md#success-datums) |
| **Paper-learning review** when churn / exit-timing cohorts mature | Human | [paper-learning-review.md](paper-learning-review.md) |
| **Change primary/control or freeze a learning track** — record via `apply_assessment_model()` / `apply_b3_lock()` (date, reason, `superseded_by`, final NAV; B3 demotion via `policy_changes`); never edit or unfreeze a frozen book — start a twin; do not crown N210/matched-30 until gates | Human | [b3-scoreboard-epoch.md](b3-scoreboard-epoch.md#assessment-model-stamps) |
| **Extend epoch-0 cron timezone map** when admitting a market whose session TZ has no ASX/EU/US bucket (`EPOCH0_WEEKDAY_SLOTS`) | Human (residual) | [market-sharded-learning.md](market-sharded-learning.md#weekday-epoch-0-local-open) |
| **Re-import library ingest crons** after cadence changes — `import-ingest-crons.yml` on main path changes (soft-skip if secrets missing; manual only if deleted) | CI | [euro-depth-sprint.md](euro-depth-sprint.md#register-euro-ingest-crons-after-cadence-changes) |
| **ops-monitor 02:30 early hub** on cron-job.org (live; re-import only if deleted) | CI | [ops-monitor.md](ops-monitor.md#cron-joborg-setup-one-time) |
| **ops-monitor 13:15 catch-up** on cron-job.org (live; re-import only if deleted) | CI | [ops-monitor.md](ops-monitor.md#email-deferral-day-complete-gate) |
| **project-traffic weekday crons** (12:30 + 17:30 UTC) on cron-job.org (live; re-import only if deleted) | CI | [project-traffic.md](project-traffic.md#schedule) |
| **GHA secret-hygiene daily cron** on cron-job.org (live; re-import only if deleted) | CI | [gha-secret-hygiene.md](gha-secret-hygiene.md#automated-daily-check) |
| **dashboard-bridge every-10m cron (all days)** on cron-job.org (live; re-import only if deleted) | CI | [dashboard-bridge.md](dashboard-bridge.md#schedule-primary-vs-backup) |
| **Rotate `CURSOR_API_KEY`** (and review Actions) if Cursor API misuse or secret exposure is suspected | Human | [gha-secret-hygiene.md](gha-secret-hygiene.md#if-cursor_api_key-may-already-be-compromised) |
| **Sync valid Cursor key into GitHub Actions** (`CURSOR_API_KEY_V2` + `CURSOR_API_KEY`) when legacy secret is dead/missing | Human | [gha-secret-hygiene.md](gha-secret-hygiene.md#which-secret-workflows-use) |
| **Override FCF auto policy** only when majority/filing fallback is wrong (or so-what `fcf_bridge_needed` with no filing/company figure) | Human (residual) | [fcf-basis-bridges.md](fcf-basis-bridges.md#when-to-review-residual) |
| **Review ingest deviations** when Automation → Ingest deviations has open rows. Prefer observe-only `signal_triage` (leftover → dismiss, buy → park/hunter via dismiss, strong_buy → approve pin). Do not auto-replace IR URLs | Human | [ingest-deviations.md](ingest-deviations.md#what-needs-a-human) |
| **Historical screen replay data** (hsr-v1 and the mid-cap sibling hsr-mid-v1) — follow the runbook's day-by-day table: the free-sample dry run passed on 2026-10-08; one month of sharadar.com direct Bundle, Full History ($69 monthly, key in a local env var only) outside the repo, every table downloaded on day 1 with `years=full`; keep `build_report.json` out of the repo (licence §8); `build-panel` for both universes (`--universe midcap`) and check the reports, run both developments (baseline and `--variant dividend_units_fixed`), run the rule search and the model-mix search (`ftse-model-mix search`) and commit both selections, reveal each holdout once, run the delisting sensitivity for both and the rule-search and model-mix reveals, then re-run the exploratory `--variant dividend_units_fixed`; commit aggregates and series only, cancel and delete raw and derived data within 30 days, then `ftse-historical-replay confirm-deleted` | Human | [historical-screen-replay.md](historical-screen-replay.md#phase-2--licensed-data-human-gate), [historical-rule-search.md](historical-rule-search.md#running-it-inside-the-phase-2-month), [historical-model-mix.md](historical-model-mix.md#running-it) |

## Maintenance

When you introduce a **new human task** (ops gate, promotion step, review cadence):

1. Add a row to the relevant section **here**.
2. Add a matching entry to [`docs/human_tasks_checklist.json`](../human_tasks_checklist.json)
   (`id`, `title`, `summary`, `doc_path`, optional `doc_anchor`, `automated`).
3. Run `pytest tests/test_human_tasks_checklist.py`.
4. Republish dashboard (`ftse-publish`) or wait for the next workflow so the UI picks up JSON changes.

Agents: follow `.cursor/rules/human-tasks-checklist.mdc`.

See also: [ops-review-cadence.md](ops-review-cadence.md),
[primary-learning-track.md](primary-learning-track.md),
[knob-calibration.md](knob-calibration.md).
