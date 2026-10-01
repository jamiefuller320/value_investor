# Algo → LLM agree/veto shadow (observe-only)

**Status:** live on weekday paper-auto (observe-only).  
**Principle:** [`llm-live-path-evidence.md`](llm-live-path-evidence.md).  
**Twin capital path:** `still_in_buy_set` remains the algo instrument — this is a
**parallel review/shadow layer**, not a mid-flight Suite A edit.

## Learning question

When the algo proposes sell / hold / rebuy, would an evidence-citing agree/veto
disagree often enough to justify a later **hard veto** on the live capital path?

## What runs

On every `ftse-paper-auto` track pass (after fills are already decided):

1. Extract algo proposals from `plan` (exits / holds / buys / skipped) + trades.
2. Build structured **agree / veto / abstain** cards with reasons + evidence
   citations (screen signal, conviction rank, entry rank, rank drop, research
   verdict, still-buyish).
3. Persist cards; attach a slim copy onto the **rebalance log** entry.
4. **Never** change sells, holds, or buys — `influences_live=false`.

Default judge backend: `evidence_heuristic` (deterministic, cites trail inputs).
Every card carries **`judge_spec_id`** (default `heuristic.v1`) so a later
observe A/B challenger can set a new id + optional `parent_spec_id` without
live influence. Schema is LLM-ready (`judge_backend=llm`) but paper-auto does
**not** call an LLM (N24). A future LLM backend must emit the same evidence
fields. See [`refinement-learning-loops.md`](refinement-learning-loops.md).

## Artifacts

| Path | Role |
|------|------|
| `<track>/llm_agree_veto_shadow.json` | Append-only pass records + cards |
| `<track>/llm_agree_veto_shadow_review.json` | Latest pass review + promotion gate |
| `learning_tracks_llm_agree_veto.json` | Rollup across tracks |
| `rebalance_log.json` → `llm_agree_veto_shadow` | Per-pass trail on the decision log |
| Optional `decision_pack.llm_agree_veto_shadow` | Pack attach helper (observe-only) |

## How to read marks

- **Agree on sell** — shadow concurs the exit looks like a decisive leave-buy-cohort
  (not buyish, or rank drop ≥ gate).
- **Veto on sell** — still buyish with insufficient rank drop (capacity-bump risk).
  Compare to `still_in_buy_set` twin holds — same economic idea, different layer.
- **Abstain** — insufficient evidence; fail-closed (no invented discretion).
- Rollup `veto_sell_count` / `verdict_counts` are **review marks only** — not
  live sell authority.

Primary comparison: disagreement rate on `rules` / `ai_judgment` vs holds the
`still_in_buy_set` twin already takes. Do not back-label prior NAV.

## Promotion gate → hard veto (later)

Hard veto on the live capital path stays **parked (N173)** until roughly:

1. Thick disagreement cohort vs `still_in_buy_set` twin marks (multi-week).
2. Every live-bound card has justifying evidence (`authorize_live_llm_influence`).
3. Explicit cold-start / epoch promotion — **never** a mid-flight Suite A flip.
4. Suite B framing before treating as adoption truth.

Until then: observe marks only; algo twin owns any capital-path churn experiment.

## Ops wiring

| Requirement | How |
|-------------|-----|
| Scheduled trigger | Weekday `ftse-paper-auto` (same pass as exit_shadow / sleeve_episodes) |
| Persisted finding | Ops-monitor observe warn when rollup missing after core tracks acted |
| Runbook | This doc + [`ops-monitor.md`](ops-monitor.md) |
| CLI | Optional — cards are on the rebalance trail; no sole-path CLI required |

Finding title: **LLM agree/veto shadow rollup missing** (`auto_fixable=False`).
