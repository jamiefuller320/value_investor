# Refinement learning loops (ops)

**Status:** thin scaffold landed (observe-only).  
**Project design:** Project store `docs/refinement-learning-loops.md`.  
**Principle:** Project `principles/post-graduation-refinement.md`.  
**Parents:** [`experiment-assessment.md`](experiment-assessment.md) ·
[`llm-agree-veto-shadow.md`](llm-agree-veto-shadow.md) ·
[`position-lifecycle.md`](position-lifecycle.md) ·
[`llm-live-path-evidence.md`](llm-live-path-evidence.md).

## What shipped

| Piece | Role |
|-------|------|
| `judge_spec_id` on agree/veto cards | Default `heuristic.v1`; optional `parent_spec_id` for later A/B |
| `parent_id` / `refinement_of` / `superseded_by` on assessment rows | Planned lineage fields; preserved across refresh |
| Graduation → refinement hook | On assessment refresh, policy table opens the next **observe** child when a parent graduates |
| `docs/data/refinement_lanes.json` | Durable mark of opened lanes (not a dashboard registry) |

**Applied** means the refinement lane is **spawned and marked** (assessment row +
lanes sidecar). It does **not** switch live capital or rewrite graduated books.

## Graduation → refinement auto-hook

`refresh_experiment_assessment` calls `apply_graduation_refinements()` after
acks + DCA adoption plan evaluation.

```text
parent graduates / adoption success
        │
        ▼
 policy table (refinement_progression.REFINEMENT_POLICY)
        │
        ├─ gates pass? ──no──► skip (fail-closed; record reason)
        │
        ▼ yes
 spawn child experiment row
   parent_id = parent
   refinement_of = parent
   observe_only = true
   influences_live = false
        │
        ▼
 mark lane in refinement_lanes.json (idempotent)
```

### Policy (first instruments)

| Parent | Child opened | Gate |
|--------|--------------|------|
| `entry_dca_overlay` | `entry_dca_timing_shift_overlay` (Q1) | Human-acked **or** `paper_execute_graduated` ready **or** execute started, with cadence readiness |
| `entry_dca_timing_shift_overlay` | `entry_dca_tranche_count_overlay` (Q2) | Fail-closed until `forward_evidence.timing_shift_marks_thick` |
| Sell / churn gates | *(none)* | `still_in_buy_set` twin already open — satisfied, no duplicate book |
| `llm_agree_veto_shadow` | `llm_agree_veto_judge_ab` | Fail-closed until multi-track veto-on-sell disagreement theme |

LLM challenger still requires evidence schema + `influences_live=false`. Hard
veto / live prompt swap stays parked (N173 / L510).

## Progression triggers (when to open the next instrument)

1. **DCA timing-shift (Q1)** — after overlay ack / execute-stage readiness /
   completed-window cadence readiness. Counterfactual overlay cadences only;
   never mid-flight edit of `graduated_allocation` or primary.
2. **DCA tranche count (Q2)** — only after Q1 lane has thick timing-shift marks.
3. **Sell-gate refinement** — do not open a new book; read `still_in_buy_set`.
4. **Judge-spec A/B** — only after `learning_tracks_llm_agree_veto` shows a
   concrete disagreement theme (≥2 tracks with veto-on-sell, ≥3 veto_sell total).

## Commands

```bash
# Rebuild ledger (also runs graduation → refinement hook)
ftse-experiment-assess refresh --data-dir docs/data --paper-root docs/data/paper_automation

# Inspect opened lanes
python3 -c "import json; from pathlib import Path; \
  print(json.dumps(json.loads(Path('docs/data/refinement_lanes.json').read_text()), indent=2))"
```

## Do not

- Mid-flight rewrite of a graduated live book from a refinement child
- Treat opened lanes as live capital authority
- Auto-open LLM judge A/B without disagreement theme (fail-closed)
- Build a second refinement-registry dashboard — lineage stays on assessment rows
