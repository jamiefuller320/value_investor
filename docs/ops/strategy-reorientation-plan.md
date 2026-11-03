# Strategy reorientation plan

Step-by-step plan for moving the project from a value-screen learning lab
toward an autonomous system that runs the owner's
[investment strategy](../PROJECT_OBJECTIVE.md#investment-strategy-owner-2026-11-03).
Written 2026-11-03 after the autonomy readiness review.

Strategy in one line: buy cheap stocks with no operating decline and no
sector-wide trouble at short-term lows, sell at short-term highs, and hold
mis-timed entries for recovery while the business case still stands.

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

**Phase 1 gate (owner):** review the gate verdicts on a sample of 10 FTSE
buy-tier names (5 flagged, 5 clear) against the cited evidence. Accept,
adjust thresholds once (logged), or reject.

### Phase 2 — Strategy book (observe-only)

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 2.1 | **Registration.** Pinned learning question, entry-low and exit-high rules, recovery-hold rules, cap, review date and stake are frozen before scoring. | N249 | Registration committed; owner signs off |
| 2.2 | **Archive replay** of the rules on the daily chart history (about two years, 1,269 tickers), using the value set from archived weekly runs and the Phase 1 gates. Report-only: these names survived to be charted. | N249 | Swing and recovery scoreboards published |
| 2.3 | **Forward fixed-stake strategy book** on the daily schedule after open settle, with an episode walker. Swing and recovery scored separately. | N249 | Book running; ops-monitor finding; dashboard strip |

**Phase 2 gate (owner):** a sample-thickness gate fixed in the registration
(for example 48 closed episodes over 8 weeks). The strategy book then becomes
the primary learning track, with the matched-30 books as controls.

### Phase 3 — Proof and accounting

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 3.1 | **Total-return accounting**: dividends in paper NAV; benchmark matches the universe | L528 | Merged; old marks keep their basis label |
| 3.2 | **New proof standard** for live capital: point-in-time history for parts 1–3; per-episode evidence for parts 4–6; paper implementation checks (fills, costs, data errors) | N248 | N13 / N14 revisit triggers rewritten; owner signs off |
| 3.3 | **Non-US point-in-time replay** (UK / Europe) of the filtered value set | L664 | Needs an owner data-licence decision |

### Phase 4 — Valuation and research focus

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 4.1 | **Fair-value range and margin of safety** in structured research output; used as the recovery target | L662, N5 | Observe-only field on memos; scored against outcomes |
| 4.2 | **Research aimed at the filters**: memos must cite evidence for or against operating decline and sector headwinds; confidence calibrated on outcomes | N173, N210 | Gate pass share no longer ~90% by default |

### Phase 5 — Execution

| Step | Deliverable | Deferred | Done when |
|------|-------------|----------|-----------|
| 5.1 | Mirror strategy-book orders onto the **Trading 212 demo account** (limit orders at planned levels); record fills against assumed prices | L535 | Measured slippage replaces assumed spread for the book |
| 5.2 | **Read-only live account sync** (cash, positions) and reconciliation finding | N14 | Daily reconciliation green |
| 5.3 | **Supervised order drafts**: system proposes, owner approves each order | N14 | Owner approves N consecutive drafts without edits |
| 5.4 | **Binding kill switch** and position / drawdown limits on the live path | N13 | Tested by drill |
| 5.5 | **Small live capital** under the Phase 3 proof standard | N13 | Owner decision |

### Phase 6 — Breadth

| Step | Deliverable | Deferred |
|------|-------------|----------|
| 6.1 | Run the strategy book on admitted markets that pass the input-quality bar | — |
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
| 1.1 | In review (one change round: one row label per comparison, freshness counts) | `cursor/operating-decline-gate-567c` | Claude Sonnet 5.5 |
| 1.2 | In review (one change round: decline-gate verdicts are the single definition of "declining"; screen fields are a material-threshold fallback). Stacked on 1.1 | `cursor/sector-headwind-gate-567c` | GPT-5.6 |
| 1.3 | In review (single choke point; no prompt version or rememo trigger affected) | `cursor/research-as-of-guard-567c` | Composer 2.5 |
| 1.4 | In review; runs once the owner adds `TRADING212_API_KEY` / `TRADING212_API_SECRET`. Committed catalogue is from 2026-07-22 | `cursor/t212-catalogue-refresh-567c` | Composer 2.5 |
| 0.3 | In review (supervisor corrected two rows) | `cursor/codename-glossary-567c` | Composer 2.5 |
| 1.5 | In review. Buy-tier interim coverage did not move (2 of 65): Yahoo series lack the prior-year quarter and half-year bodies are not extracted, hence 1.6 and 1.7. Stacked on 1.1 | `cursor/decline-gate-interim-567c` | Grok 4.7 |
| 1.6, 1.7 | Next | — | Grok 4.7 |
| Phase 1 gate | Waiting on 1.1–1.2 merge and a week of daily refreshes | — | Owner |
