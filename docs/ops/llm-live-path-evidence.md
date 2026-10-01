# LLM live-path evidence (required)

**Status:** active project principle (2026-10-01).  
**Related:** [`llm-agree-veto-shadow.md`](llm-agree-veto-shadow.md), [`primary-learning-track.md`](primary-learning-track.md), deferred **N173**.

## Rule

Any LLM step that can influence a **live** capital or decision path (sell, hold,
rebuy, size, promote, knob apply) **must** record durable justifying evidence in
the decision trail:

- Structured reasons (machine-readable, not only free prose)
- Cited inputs / evidence (screen signal, rank, research verdict, memo ids, …)

**No silent LLM discretion.** Missing or stale evidence fail-closes influence
(no effect on fills) — it must not invent a silent override.

This applies to **any** LLM live-path decision making, not only sells.

## Shadow first

Prefer **algo propose → LLM agree/veto** as an **observe-only** parallel review
layer before any hard veto:

| Layer | Role | Live fills? |
|-------|------|-------------|
| Algo gates / twins (e.g. `still_in_buy_set`) | Deterministic capital-path instruments | Yes (on that twin / book only) |
| `llm_agree_veto_shadow` | Agree/veto cards with evidence on the trail | **Never** (until promotion gate) |

See [`llm-agree-veto-shadow.md`](llm-agree-veto-shadow.md).

## Fail-closed hook

```python
from value_investor.llm_agree_veto_shadow import (
    authorize_live_llm_influence,
    has_justifying_evidence,
)

# Future hard-veto path — returns False unless evidence + explicit live flag.
if authorize_live_llm_influence(card):
    ...  # only then may influence fills
```

Today’s paper-auto writer always sets `influences_live=false` / `observe_only=true`.

## Where agents / humans see this

- Root [`AGENTS.md`](../../AGENTS.md#llm-live-path-evidence-required)
- This ops principle
- Project store `principles/llm-live-path-evidence.md` + `preferences.md`
