# PIT decision autopsy (Phase C — locked design)

Status: **design locked** (2026-09-13). Implementation still deferred as **L368**,
funded by memo resource retarget **L367** Phase C. Feeder features: **L365**.

Parent loop: [`primary-learning-track.md`](primary-learning-track.md#decision-learning-loop-target).

Before any **new** strand (not just Phase C), lock the four anticipation questions
with [`decision-recording-checklist.md`](decision-recording-checklist.md) /
`ftse-decision-recording` (**L386**). This autopsy doc is the primary-track
freeze schema; the checklist is the gate that forces the same discipline on
other labs.

This document freezes the open choices that blocked a “best Phase C” build.
Track excess vs ^FTSE / rules remains adoption truth; autopsy is the
**improvement signal**, not a second promotion yardstick.

---

## 1. Goal

For each AI-judgment rebalance row at time *t*:

1. Freeze (or faithfully join) the **information set** used.
2. Later score whether the **taken action** was optimal vs alternatives.
3. Attribute misses to **data gaps** vs **logic gaps**.
4. Emit **engineering tasks** that prioritize ingest/overlays/gates.

---

## 2. Information pack schema

Artifact (per track, append-only): `decision_autopsy_pack.json` (name may gain a
date shard later). One **decision row** per `(logged_at, ticker)`.

### 2.1 Frozen at decision time *t* (required)

From existing `rebalance_log.json` / `slim_candidate` (do not drop):

| Field | Source |
|-------|--------|
| `logged_at`, `track_id`, `schema_version` | log entry |
| `screen_source`, `knob_epoch_started_at`, `gate`, `selection` | log entry |
| `acted`, `plan`, `trades` | log entry |
| slim candidate fields | `slim_candidate`: `ticker`, `name`, `signal`, `adjusted_signal`, `conviction_score`, `data_quality_score`, `timing_signal`, `sector`, `price`, `research_verdict` (≤120), optional `trade_plan` (`tactical_stop_loss` / `tactical_take_profit` / `core_stop_loss` / `core_take_profit`) |
| membership | `in_screen_buy_tier` / `in_candidates` / `in_gate_excluded` / `in_holdings_before` |

**Extend freeze** (add to slim or a parallel `autopsy_freeze` object written in the
same paper-auto pass — prefer parallel object so knob replay stays stable):

| Field | Meaning |
|-------|---------|
| `research_revision_id` | PIT revision id at/before `logged_at` (empty if legacy-only) |
| `research_as_of` | revision `as_of` / doc `updated_at` used |
| `research_verdict_structured` | enum from `ResearchVerdict`: `accumulate` \| `neutral` \| `caution` \| `pass` |
| `research_confidence` | float if present on `ResearchDocument` |
| `research_risk_level` | `low` \| `medium` \| `high` if present |
| `research_rationale_short` | ≤240 chars from structured rationale (not essay sections) |
| `sources_as_of` | copy of revision `sources_as_of` (news/financials cutoffs, snapshot path) |
| `feature_flags.filings_with_body` | bool — ≥1 filing body on disk at *t* |
| `feature_flags.fcf_basis_bound` | bool — FCF basis overlay bound on the report at *t* |
| `feature_flags.eps_overlay_bound` | bool — EPS overlay bound at *t* |
| `feature_flags.overlay_bound` | bool — research overlay present on the live report the book read |
| `fcf_basis_status` | string/enum if already on report; else omit |
| `taken_action` | `buy` \| `hold` \| `sell` \| `wait` (derived from plan/trades/timing/gates) |

### 2.2 Join later (allowed; not required in freeze)

| Join | API / source | Use |
|------|----------------|-----|
| Full PIT memo sections | `get_research_as_of` + `load_revision` for `revision_id` | Human deep-dive only |
| Forward marks | price series / fund marks | Optimality scoring |
| Archive signal row | `ARCHIVE_SIGNAL_FIELDS` weekly slim | Offline cohort labs only |

### 2.3 Explicitly out of v1 freeze

- Full memo essay sections (`executive_summary`, thesis, financial review, …)
- Raw filing body text
- New archive-only FCF numerics that were **not** on the live report at *t*
  (no lookahead via later ingest)

**Rule:** freeze what paper-auto could see; join prose later; never backfill
missing filings into *t* after the fact for scoring fairness.

---

## 3. Freeze vs join policy

| Layer | Policy |
|-------|--------|
| Gate replay | Frozen in `rebalance_log` (already) |
| Structured research identity | **Freeze** `research_revision_id` + structured verdict fields at *t* |
| Feature presence | **Freeze** flags (+ status enums if on report) at *t* |
| Memo prose | **Join later** via PIT revision |
| Forward P&L | **Join later** |
| `ARCHIVE_SIGNAL_FIELDS` | Do **not** block Phase C on expanding archive slim first; extend live freeze flags instead. Optionally add FCF/EPS bind columns to archive **later** (L365) for offline labs |

Implementation note: `get_research_as_of` returns a `ResearchDocument` only —
autopsy freeze must also resolve `revision_id` / `sources_as_of` from the timeline
(`list_revision_metas` / `load_revision`) in the same paper-auto pass.

---

## 4. Optimality definition

| Choice | Lock |
|--------|------|
| Cost suite | **Suite B fair T212** (`ai_judgment_fair` / fair cost stamp). Suite A 3% stress is optional side report for churn robustness only — not primary optimality. |
| Horizons | Reuse exit-shadow windows: **1w / 4w / 8w / 12w** (7 / 28 / 56 / 84 days). |
| Primary mark | **4w** after-cost excess vs not-taking the action (or vs ^FTSE-relative alternate); **12w** confirmation. |
| Unit of analysis | One ticker on one AI-judgment rebalance day. |
| Action set | `buy`, `hold`, `sell`, `wait` (wait = gated/skipped/timing wait). |
| Alternates | (a) buy-tier + accumulate gated out → score `wait` vs counterfactual `buy`; (b) held → `hold` vs `sell`; (c) bought → `buy` vs `wait`; (d) sold → `sell` vs `hold`. |
| Optimal | Alternate with best primary-mark after-cost outcome; tie → prefer lower turnover. |
| Non-goals | Does not auto-apply knobs; does not rewrite `assign_signal()` (N3); does not replace track-level decision-review adoption metrics. |

Reuse machinery where possible: `rebalance_log` counterfactual helpers, exit-shadow
windows, fair-cost book marks.

---

## 5. Data vs logic attribution

Apply in order (first match wins for auto-queue):

1. **`data_gap`** if any freeze flag shows foundation missing when it mattered:
   - `filings_with_body == false` on a name that received accumulate / buy
   - `fcf_basis_bound == false` when FCF basis is part of live overlay policy
   - `overlay_bound == false` but gate required research accumulate
   - missing `research_revision_id` while accumulate gate was on
2. **`logic_gap`** if required features were present (`feature_flags` green) and
   the taken action still loses to an alternate on the primary mark by a
   minimum margin (implementation default: **100 bps** after costs at 4w —
   tunable, observe-only at first).
3. **`ambiguous`** otherwise (thin marks, corporate actions, missing prices,
   conflicting flags).

**Policy:** prefer classifying as `data_gap` when both data and logic could apply
(fix the information set first — aligns with L365 / P1).

**Human residual:** `ambiguous` rows are observe-only review candidates; they do
**not** auto-promote to engineering until a human confirms. No new checklist row
until the autopsy emitter ships.

---

## 6. Engineering queue contract

Emit `EngineeringTask`-shaped rows (see `engineering_tasks.py`), not a new queue.

| Field | Lock |
|-------|------|
| `id` | `eng-autopsy-{yyyyMmDd}-{ticker}-{short_hash}` |
| `source` | `pit_autopsy` |
| `area` | `ingest` for `data_gap`; `overlay` or `gates` for `logic_gap` |
| `priority_score` | start **70** (`data_gap`) / **65** (`logic_gap`); clamp like other eng tasks |
| `evidence` | must include `logged_at`, `ticker`, `taken_action`, `attribution`, `feature_flags`, primary-mark delta vs best alternate |
| `acceptance_criteria` | concrete and testable (e.g. “bind FCF basis on REPORT for TICKER in weekday paper-auto overlay”) |
| Auto-merge | **false** |
| `blocked_paths` | include screen core / `assign_signal` paths when `area=gates` |

Optional path: write `ana-sgap-*` analysis tasks first, then promote — same as
system-gaps — if that keeps triage in one place. Prefer direct `eng-autopsy-*`
for clear `data_gap` ingest items.

---

## 7. Success KPIs (Phase C “good enough”)

Phase C is succeeding when, on the AI-judgment track:

| KPI | Target |
|-----|--------|
| Freeze completeness | ≥ **80%** of acted rebalance ticker-rows in the last 8 weeks have `research_revision_id` or explicit legacy fallback **and** populated `feature_flags` |
| Attribution coverage | ≥ **50%** of suboptimal rows (primary mark) get non-`ambiguous` attribution |
| Actionability | ≥ **1** eng task / month from autopsy accepted into the eng queue with clear acceptance criteria |
| Safety | Zero auto knob applies / zero `assign_signal` edits from autopsy |
| Adoption truth unchanged | Promotion still requires track excess after **fair** costs vs ^FTSE and rules |

Stop/revisit if KPIs stall after 12 weeks of complete freezes — revisit
optimality margin and alternate set before adding narrative features.

---

## 8. Build sequence (when prerequisites clear)

1. **Freeze writer** in weekday paper-auto (parallel `autopsy_freeze`, no gate change).
2. **Scorer** (Suite B, 1/4/8/12w) as observe-only artifact.
3. **Attributor** + eng-task emitter (`data_gap` first).
4. Only then: dashboard/email surfaces; human ambiguous triage checklist row.

### Automated readiness gate

Phase C readiness is deliberate and automated: a fixed checklist of evidence
checks (not a vibe), scored by `ftse-phase-c-readiness` and written every
Sunday by `analysis-review.yml` to `docs/data/phase_c_readiness.json`
(observe-only — Sunday never fails on `NOT READY`).

```bash
ftse-phase-c-readiness
ftse-phase-c-readiness --json-out docs/data/phase_c_readiness.json
```

Exit code `0` only when all required checks pass (Phase B slim evidenced,
≥8 weeks AI-judgment `rebalance_log` with buy-tier/candidates, non-trivial
feature coverage). Use `--force-phase-b-done` only as an operator override for
dry-runs — it does not invent rebalance history or feature coverage. Do **not**
start the freeze writer until exit `0` (human gate).

### Prerequisites (from L368)

- L367 Phase B structured-verdict slim in flight or done (N119 / N120 path;
  design locked in [`structured-verdict-slim.md`](structured-verdict-slim.md)).
- ≥ **8 weeks** stable `screen_buy_tier` / `candidates` on AI-judgment `rebalance_log`.
- L365 feeder progress far enough that `feature_flags` are not almost always false
  on FTSE holdings / buy-tier (otherwise attribution collapses to trivial data_gaps).

---

## 9. Non-goals

- Multi-market / shard Phase C autopsy before FTSE proves out (see **N122**). Equal-support
  parallel *data* collection on admitted epoch-0 books remains in scope for later
  (**L370**); that is not AI-judgment autopsy.

- Replacing narrative memos for humans (that is L366, after always-on structured verdict).
- Full-universe memo PIT replay (N39).
- Gating paper-auto on `memo_quality` (N27).
- Routing paper-auto or decision-review through an LLM (N24).
