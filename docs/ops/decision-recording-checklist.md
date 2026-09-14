# Decision recording checklist

**Status:** active (implements deferred **L386**).  
**Related:** [`pit-decision-autopsy.md`](pit-decision-autopsy.md) (L368 Phase C freeze), [`primary-learning-track.md`](primary-learning-track.md), [`structured-verdict-slim.md`](structured-verdict-slim.md).

Before opening a **new** analysis, counterfactual, or model-dev strand, answer these
four questions in writing (experiment brief, director task, or eng task evidence).
Cheap machine fields beat expensive prose. Prefer over-recording flags at *t*.

```bash
# Validate a recording plan JSON (exit 0 = complete)
ftse-decision-recording validate --plan path/to/plan.json

# Show the locked primary-track answers + freeze field catalog
ftse-decision-recording show-primary

# Observe-only: preview what current AI-judgment rebalance rows can freeze today
ftse-decision-recording preview-freeze \
  --rebalance-log docs/data/paper_automation/ai_judgment/rebalance_log.json
```

Do **not** enable the Phase C freeze writer until `ftse-phase-c-readiness` exits 0
(human gate). This checklist and preview are allowed earlier.

---

## The four questions

| # | Question | What a good answer looks like |
|---|----------|-------------------------------|
| 1 | **Unit of analysis** | One concrete grain: ticker-day decision, transition event, closed exit, cohort week, … |
| 2 | **Must freeze at *t*** | Append-only fields available at decision time (ids, gates, action, structured verdict, revision id, bind/presence flags, confidence/risk if later gates may use them) |
| 3 | **May join later** | Prose, full filing text, forward prices/marks — join by id/as-of, not copied into the freeze |
| 4 | **Must never backfill into *t*** | Later ingest / later-bound overlays / post-decision labels that would create lookahead |

---

## Locked answers — primary AI-judgment learning track

These are the defaults for weekday paper-auto / Phase C autopsy. New strands may
narrow or extend them, but must not contradict the no-lookahead rule.

### 1. Unit of analysis

**One ticker on one AI-judgment rebalance day** — key `(logged_at, ticker)`.

Not: full-portfolio mark alone; not weekly archive row alone; not a closed-exit
cohort (those are separate strands with their own freeze plans).

### 2. Must freeze at *t* (cheap, append-only)

Already on `rebalance_log` / candidates (do not drop):

- `logged_at`, `track_id`, `schema_version`
- `screen_source`, `knob_epoch_started_at`, `gate`, `selection`
- `acted`, `plan`, `trades`
- candidate slim: ticker, name, signal, adjusted_signal, conviction, data quality,
  timing, sector, price, research_verdict (short)
- membership: in buy-tier / candidates / gate-excluded / holdings-before

**Extend** (Phase C `autopsy_freeze` object — design locked, writer gated on readiness):

| Field | Why |
|-------|-----|
| `research_revision_id`, `research_as_of`, `sources_as_of` | PIT identity |
| `research_verdict_structured`, `research_confidence`, `research_risk_level`, `research_rationale_short` | Structured verdict (Phase B producer) |
| `feature_flags.filings_with_body`, `.fcf_basis_bound`, `.eps_overlay_bound`, `.overlay_bound` | Data-vs-logic attribution |
| `taken_action` (`buy` \| `hold` \| `sell` \| `wait`) | Optimality unit |

Optional later (L139): freeze `research_confidence` / risk / unresolved counts when
gates may consume them — already partly covered by structured verdict fields.

### 3. May join later

- Full memo essay sections via PIT revision id
- Raw filing body text
- Forward prices / fund marks (1w / 4w / 8w / 12w)
- Weekly `ARCHIVE_SIGNAL_FIELDS` rows for offline labs only

### 4. Must never backfill into *t*

- Filing bodies fetched **after** `logged_at`
- FCF/EPS overlays bound only on a later report refresh
- Archive-only numerics that were not on the live report the book read
- Any post-hoc “we would have known X” label

**Rule:** freeze what paper-auto could see; join prose later; never rewrite *t*
for scoring fairness.

---

## Template for a new strand

Copy into the experiment brief / task evidence:

```yaml
recording_plan:
  strand_id: "my_new_lab"
  unit_of_analysis: "..."
  freeze_at_t:
    - field: "..."
      source: "rebalance_log|paper_auto|archive|near_miss|new_writer"
  join_later:
    - field: "..."
      join_key: "..."
  never_backfill:
    - "..."
  consumer: "counterfactual|autopsy|cohort_lab|other"
  revisit_when: "..."
```

Validate with `ftse-decision-recording validate --plan …`.

---

## Relation to Phase C

| Artifact | Role |
|----------|------|
| This checklist (L386) | Force the four answers **before** history is needed |
| Phase B structured verdict | Producer of freeze-able verdict fields |
| `ftse-phase-c-readiness` | Gate for enabling the freeze **writer** |
| L368 autopsy | Scorer + data-vs-logic attribution after freezes exist |

`preview-freeze` reports coverage gaps (missing revision ids / feature flags) so
engineering can thicken producers (L365 / Phase B rememo) without turning on the
writer early.
