# Structured verdict slim (Phase B — locked design)

Status: **implemented** (2026-09-13). Design locked; runtime default is structured
verdict slim (**L367 Phase B**) (N119 path under N120 constraint). Parent sequence:
**L367**. Downstream consumer of freed `weekly_ops`: Phase C /
[`pit-decision-autopsy.md`](pit-decision-autopsy.md) (**L368**). Human full-memo
UX remains Phase D / **L366**.

This document freezes the open choices that blocked a “best Phase B” build.
Track excess vs ^FTSE / rules remains adoption truth; Phase B only changes
**what scheduled research spends tokens on**, not paper-auto gates.

---

## 1. Goal

While the primary AI-judgment track still uses
`require_research_accumulate=True` (**N120**):

1. Keep **scheduled** research that can emit fresh `research_verdict` labels
   (especially `accumulate`) for buy-tier / rememo / alumni paths.
2. Stop spending `weekly_ops` on essay sections that paper-auto does **not**
   read (**N119**).
3. Emit a machine schema aligned with Phase C freeze fields
   (`research_revision_id`, structured verdict, `research_rationale_short`).
4. Free envelope for Phase C autopsy + L365 feature thickness — not for more
   prose polish or spray.

Non-goal of Phase B: retiring the accumulate gate, on-demand-only memos, or
filing-derived replacement of the LLM verdict (those are gate-change / L365 /
L366 work).

---

## 2. What stays always-on scheduled

| Path | Today | Phase B lock |
|------|-------|--------------|
| Sunday `--research-docs` | Full initial essay + weekly essay update (`runner.py` caps 12+12) | **Keep schedule + caps**; prompts become structured-verdict slim |
| Weekday FTSE rememo (`ftse-research --weekday-rememo`, cap 3 / catch-up 5) | Force-initial **full** memo when body-lag / ingest improves | **Keep schedule + caps**; rememo becomes force slim initial / slim refresh |
| Admitted-market weekday rememo (`ftse-library rememo`) | Same 3/day equal-support package | **Same** slim behaviour as FTSE rememo |
| Overlay refresh before paper-auto | Binds doc → `research_verdict` / `adjusted_signal` on reports | **Unchanged** (no gate change) |
| Timeline revisions | `revision_id` + `sources_as_of` on every save | **Unchanged** — required for Phase C `research_revision_id` |

Still **not** always-on for Phase B (unchanged doctrine):

- 21-market spray / `research_all_graduated` (**N96** / Phase A adjacency)
- Frontier model A/B as a default Sunday cost (**L88**)
- Gating paper-auto on `memo_quality` (**N27**)
- Pure on-request research as the only path (**N120**)

---

## 3. Exact output schema (machine fields)

Scheduled agent output **must** parse into these fields on `ResearchDocument`
(and then onto live reports via `apply_research_overlay`):

| Field | Type / enum | Required for gate? | Notes |
|-------|-------------|--------------------|-------|
| `research_verdict` | `accumulate` \| `neutral` \| `caution` \| `pass` | **Yes** — AI-judgment eligibility | Parsed by `parse_research_verdict` / `coerce_research_verdict` |
| `research_risk_level` | `low` \| `medium` \| `high` | No (overlay / packs / Phase C) | Keep emitting |
| `research_confidence` | float `0.00`–`1.00` | No | Keep emitting |
| `research_rationale` | string ≤ **240** chars | No for gate; **yes** for Phase C | Becomes freeze `research_rationale_short`; one sentence |
| `risk_tags` | list from `ALLOWED_RISK_TAGS` | No (N27 / project-audit) | Emit via `RiskTags:` line (not essay risks) |

Prompt contract for the RESEARCH VERDICT block (unchanged lines, shorter
surrounding task):

```text
RESEARCH VERDICT
Verdict: accumulate | neutral | caution | pass
Risk: low | medium | high
Confidence: 0.00–1.00
Rationale: <≤240 chars>
RiskTags: <comma-separated allowed tags>
```

On every save, keep existing timeline machinery:

| Artifact | Source |
|----------|--------|
| `research_revision_id` | `revision_id_from_datetime` / revision JSON (`timeline.py`) |
| `research_as_of` | revision `as_of` / doc `updated_at` |
| `sources_as_of` | `build_sources_as_of(...)` |

Derived report fields (not agent-authored, still required):

| Field | Producer |
|-------|----------|
| `adjusted_signal` | `compute_adjusted_signal(screen_signal, research_verdict)` in `overlay.py` / snapshot merge |
| action-note fragment | `format_research_action_note(...)` |

Schema compatibility: `ResearchDocument` **keeps** essay attributes
(`executive_summary`, `investment_thesis`, `financial_review`, `risks_and_flags`, `news_highlights`) but scheduled Phase B writes leave them
**unchanged** (weekly/rememo) or **empty string** (new slim initial). Do not
break `to_dict` / store / PIT loaders.

New `mode` values:

| Mode | When |
|------|------|
| `structured_verdict` | Slim initial (replaces essay `initial` for scheduled creates) |
| `structured_verdict_update` | Slim weekly / rememo refresh (replaces essay-producing weekly body) |
| legacy `initial` / `weekly_update` / `gap_fill` | Read-only for pre-Phase-B docs; do not emit from scheduled path after cutover |

---

## 4. What is dropped from the scheduled path (essay sections)

Dropped from **scheduled** agent prompts and from **required** parse success:

| Section / heading | Today | Phase B |
|-------------------|-------|---------|
| `EXECUTIVE SUMMARY` | Initial required | **Dropped** from scheduled prompts |
| `INVESTMENT THESIS` | Initial required | **Dropped** |
| `FINANCIAL REVIEW` | Initial + gap-fill rewrite | **Dropped** from scheduled prompts |
| `RISKS AND RED FLAGS` (prose) | Initial + gap-fill rewrite | **Dropped**; tags move to verdict block |
| `NEWS HIGHLIGHTS` | Initial required | **Dropped** |
| `WEEKLY UPDATE` long prose | Weekly required | **Dropped** as a required essay; optional ≤3-line `delta_note` may be stored on the weekly_updates entry for humans, not for the gate |
| Gap-fill rewrite of financial/risks | Sunday `--research-gap-fill` | **Dropped** from default scheduled path (see §6) |

Code anchors for today’s essay contract:

- Prompts: `src/value_investor/research/agent.py` (`_initial_prompt`,
  `_weekly_update_prompt`, `_gap_fill_prompt`)
- Section list: `RESEARCH_SECTIONS` in `src/value_investor/research/document.py`
- Orchestration: `src/value_investor/research/runner.py` (`run_research_for_strong_buys`,
  `_process_ticker`)

---

## 5. Rememo behaviour

Rememo exists to refresh labels when **filing bodies improve** (body-lag /
ingest), not to regenerate essays.

| Rule | Lock |
|------|------|
| Always-on | Keep weekday rememo schedules (FTSE ingest-loop + admitted `ftse-library rememo`) |
| Trigger | Unchanged eligibility (`rememo_reason` / body-lag threshold / ingest improved) |
| Agent work | Call **slim** structured-verdict path (force create or refresh), **not** `_initial_prompt` essay |
| Caps | Keep `DEFAULT_WEEKDAY_REMEMO_CAP=3`, catch-up 5, `$8` weekly_ops headroom guard |
| Spend estimate | Keep recording into `weekly_ops`; **recalibrate** `estimated_memo_usd` after ≥2 weeks of measured slim calls (do not guess a new unit cost in v1) |
| Alumni / Sunday updates | Same slim refresh; never force a full essay “to fill markdown” |

Implementation hook today: `run_weekday_memo_rememo_pass` → `_process_ticker(..., force_initial=True)` in
`src/value_investor/research/weekday_rememo.py`. Phase B changes the agent called
inside `_process_ticker`, not the backlog selector.

---

## 6. Gate compatibility (must not break accumulate)

Primary track wiring (do **not** change in Phase B):

| Knob | Location | Lock |
|------|----------|------|
| `require_research_accumulate=True` | `paper_automation.py` AI-judgment ensure + `paper_automation_cli.py` | Keep |
| `use_adjusted_signal=True` | same | Keep |
| Eligibility | `paper_fund.select_automated_targets` / `simulator._select_targets` | Still require `coerce_research_verdict(...) == "accumulate"` |
| Overlay bind | `research/overlay.py` `apply_research_overlay` | Still requires `doc.research_verdict` |

Hard compatibility rules:

1. Every scheduled success path must leave a non-empty parseable
   `research_verdict` on the saved document (fail the ticker run if missing —
   do not silently ship empty and starve the gate).
2. `coerce_research_verdict` must keep accepting slug **and** `Verdict:` block
   forms (already true in `verdict.py`).
3. Slim docs must still flow through `refresh_dashboard_bundle` /
   weekday paper-auto overlay refresh so `latest.json` reports carry
   `research_verdict` + `adjusted_signal`.
4. Do **not** gate on rationale length, risk tags, memo_quality, or essay
   presence (**N27**).
5. Pre-Phase-B essay memos remain valid PIT joins for Phase C; slim cutover
   is forward-only.

### Sunday gap-fill

Default Sunday `--research-gap-fill` today rewrites essay sections and is a
major `weekly_ops` consumer that does **not** change the accumulate predicate
beyond refreshing the same verdict fields.

**Lock:** remove essay-rewriting gap-fill from the **default** Sunday bundle
once Phase B ships. Optional operator flag may run a **slim** gap-fill that
updates `question_outcomes` + structured verdict only. Full qualitative
gap-fill essays wait for Phase D / on-demand.

---

## 7. Human on-demand full memo stays Phase D / L366

| Surface | Phase B behaviour |
|---------|-------------------|
| Decision packs | Fall back to `research_rationale` + risk tags + screen summary when thesis/risks prose empty (`decision_pack.py` already has rationale fallback) |
| Dashboard “Read memo” | Shows stub / verdict block for new slim docs; legacy essays still render |
| Generate full memo | **Out of scope** — **L366** after always-on slim verdict (or filing replacement) is proven |
| Verify-before-trade | Remains useful for live capital; not the primary learning loop (`primary-learning-track.md`) |

Phase B intentionally thins human narrative. That is accepted under N119 until
L366 restores on-demand prose without starving the gate.

---

## 8. Relation to Phase C freeze fields

Phase C [`pit-decision-autopsy.md`](pit-decision-autopsy.md) §2.1 already
requires:

| Phase C freeze field | Phase B producer |
|----------------------|------------------|
| `research_revision_id` | Existing timeline save (must keep running on slim saves) |
| `research_as_of` | Same |
| `research_verdict_structured` | `ResearchDocument.research_verdict` |
| `research_confidence` | same field |
| `research_risk_level` | same field |
| `research_rationale_short` | `research_rationale` clipped ≤240 at emit/freeze |
| `sources_as_of` | timeline |
| Essay sections | **Join later** only — Phase B stops generating them on schedule |

Phase B success unblocks L368’s “Phase B in flight or done” prerequisite; it
does **not** implement the freeze writer (that is Phase C).

---

## 9. Build sequence + prerequisites

### Prerequisites

1. Design lock (this doc) — done.
2. Phase A adjacency: do not re-enable spray / frontier defaults that burn the
   same envelope Phase B is freeing (formal Phase A checklist can stay ops-only).
3. Tests exist for verdict parse + overlay + accumulate gate
   (`tests/test_research_verdict.py`, paper-fund / automation tests) — extend,
   do not replace.

### Build order

1. **Slim prompt + parser path** in `agent.py` (new helpers; keep essay prompts
   callable for Phase D / manual).
2. **Runner / rememo cutover** — `_process_ticker` and weekday rememo call slim
   path; set `mode` as in §3.
3. **Sunday default** — stop essay gap-fill in `email-report` / orchestrator
   args; keep `--research-docs` on slim.
4. **Render / decision-pack tolerance** — stub markdown + confirmed rationale
   fallback (no pack hard-fail on empty thesis).
5. **Spend telemetry** — tag slim calls; after ≥2 weeks, propose new
   `estimated_memo_usd` (separate small PR).
6. Only then: treat L368 Phase C freeze writer as buildable from a resource
   standpoint (other L368 data prerequisites still apply).

### Explicit non-goals for this build

- Changing `require_research_accumulate` or AI-judgment knobs
- Filing-derived verdict replacement (L365 feeder, not Phase B)
- On-demand generate-memo UX (L366)
- Shard / multi-market autopsy (N122 / L370)

---

## 10. Open choices

**None blocking.** Locked defaults:

| Topic | Lock |
|-------|------|
| Empty vs omit essay fields | Keep keys; empty string on new slim initials |
| Optional weekly `delta_note` | Allowed ≤3 lines on `weekly_updates` entry; not required; not a gate input |
| Gap-fill default | Off essay path; slim optional only |
| Unit cost | Keep `$0.4` estimate until measured |
| RiskTags location | On verdict block (not risks essay) |

Revisit only if slim prompts fail to produce stable `accumulate` coverage on
buy-tier for ≥2 consecutive Sundays (then investigate prompt/sources — do not
silently restore essays as the first fix).

---

## 11. Success KPIs (Phase B “good enough”)

On the live FTSE path, after cutover:

| KPI | Target |
|-----|--------|
| Gate coverage | AI-judgment buy-tier still has non-trivial `research_verdict=accumulate` share (no collapse vs pre-cutover 4-week baseline; investigate if accumulate count drops &gt;25% week-on-week for 2 weeks) |
| Overlay bind | ≥ same overlay_bound rate on holdings/buy-tier as pre-cutover (verdict present → `adjusted_signal` computed) |
| Essay spend | Scheduled agent prompts no longer require `RESEARCH_SECTIONS` essay headings; Sunday default does not rewrite financial/risks essays |
| Envelope | Measurable drop in estimated tokens/`weekly_ops` per scheduled research call vs pre-cutover (directionally down within 2 weeks; exact % after telemetry) |
| Phase C readiness | Slim saves still write `revision_id` + structured verdict fields Phase C freezes |
| Safety | Zero change to `require_research_accumulate` / `use_adjusted_signal`; zero `assign_signal` edits |

Stop/revisit if accumulate coverage collapses or overlay bind regresses — fix
slim prompt/sources before touching the gate.

---

## 12. Ready to lock? Blockers?

**Yes — design locked; Phase B code path is implemented.**

Scheduled research defaults to structured-verdict modes (`structured=True` on
initial / weekly / gap-fill agents). Sunday no longer enables essay gap-fill by
default. Essay path remains via `structured=False` for Phase D / legacy tests.
Phase C start is gated by `ftse-phase-c-readiness` (see
[`pit-decision-autopsy.md`](pit-decision-autopsy.md#automated-readiness-gate)).

Post-cutover watch:

- Human decision packs look thinner until L366 — accepted.
- Recalibrate `estimated_memo_usd` after a few slim Sundays (L52).
- Confirm accumulate coverage and overlay bind do not regress.

---

## 13. Code path index

| Concern | Path |
|---------|------|
| Essay vs verdict prompts | `src/value_investor/research/agent.py` |
| Section schema / markdown | `src/value_investor/research/document.py` |
| Verdict parse / `adjusted_signal` | `src/value_investor/research/verdict.py` |
| Sunday/alumni orchestration | `src/value_investor/research/runner.py` |
| Weekday rememo | `src/value_investor/research/weekday_rememo.py` |
| Overlay → reports | `src/value_investor/research/overlay.py`, `overlay_refresh.py` |
| Revisions / PIT | `src/value_investor/research/timeline.py` |
| Accumulate gate | `src/value_investor/paper_fund.py` (`select_automated_targets`), `paper_automation.py` (AI-judgment ensure) |
| Sim parity | `src/value_investor/simulator.py` |
| Rebalance slim | `src/value_investor/rebalance_log.py` (`slim_candidate`) |
| Decision-pack thesis fallback | `src/value_investor/decision_pack.py` |
| Spend / caps | `src/value_investor/agent_model_policy.py` (`weekly_ops`, `estimated_memo_usd≈0.4`) |
| Sunday wire | `.github/workflows/email-report.yml` (`--research-docs --research-gap-fill`) |
| Weekday rememo wire | `.github/workflows/ingest-loop.yml`, `library-ingest-maintenance.yml` |
