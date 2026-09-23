# Dual-path sleeve lab (observe-only)

Parallel **capital book** + **widest sleeve observe path** with capital-status
tags. Implements the recording half of deferred **L443** / **L444**.

Does **not** change live paper allocation, knobs, or decision-review `--apply`.

## Paths

| Path | Job | Success metric |
|------|-----|----------------|
| **Capital book** (existing paper tracks) | Monthly deposits (optional config) + rotation | NAV excess vs ^FTSE after fair costs |
| **Sleeve episodes** (this lab) | Every buy-tier crossing opens an episode | Sleeve return / timing **by** `capital_status` |

## Markers (widest freeze)

### v1 (shipping)

| Marker | Definition |
|--------|------------|
| **Earliest entry** | First paper-auto pass the name is `buy` / `strong_buy` |
| **Latest experimental exit** | Left buy-tier for `exit_confirm_screens` (default 2) consecutive passes, or hard `avoid` |
| **Best policy** | Nested counterfactual *inside* the wide episode — not the recording gate |

### v2 planned — near-buy → grace-end+1m (**L439**)

For **maximum** entry/exit timing assessment, widen the observe envelope further
(still nested-counterfactual friendly):

| Marker | Planned definition |
|--------|--------------------|
| **Earliest entry** | First print on the **near-buy** watch: `hold` (or equivalent) with conviction ≥ trajectory `pre_buy` floor (**0.28**), i.e. hold-near-buy — same cut as equal-support near-miss |
| **Sub-markers (stamp, do not gate)** | `first_near_buy_at`, `first_buy_tier_at`, `grace_started_at`, `grace_ended_at` |
| **Latest experimental exit** | Momentum-grace **end + ~1 calendar month** (grace default 6 weeks → ~10 weeks post leave-buy-tier when grace arms). **Fallback** if grace never arms: leave buy-tier × confirms + 1 month, or hard `avoid` |
| **Volume guard** | Cap new opens per pass (already `max_new_episodes_per_pass`); prefer conviction-ranked near-buy intake |

Capital tags stay as in v1: `on_book` only when the paper book actually funds the name
(usually at/after buy-tier). Near-buy-only episodes are almost always `never_funded`
until they graduate — that is intended for early-entry counterfactuals.

Do **not** shrink v1 recording while v2 is unfinished; widen by adding markers,
not by replacing buy-tier opens mid-cohort.

## Capital status tags

| Tag | Meaning |
|-----|---------|
| `on_book` | Crossed threshold and received (or currently holds) paper capital |
| `off_book` | Was on-book; capital sold while the experimental episode was still open — **marks continue** to latest exit |
| `never_funded` | Crossed threshold; never received paper capital — full lifecycle still recorded |

Always stratify sleeve stats by tag. Never mix `never_funded` paper marks into the market scoreboard.

## Artifacts

Per track under `docs/data/paper_automation/{track}/`:

- `sleeve_episodes.json` — open + closed episodes
- `sleeve_episodes_review.json` — counts + readiness by tag

Rollup: `docs/data/paper_automation/learning_tracks_sleeve_episodes.json`

Weekday `ftse-paper-auto` runs the pass on every track after rebalance (alongside
exit_shadow / exit_timing / entry DCA).

```bash
# Manual refresh (marks / opens from current screen + fund)
ftse-sleeve-episodes --output-dir docs/data/paper_automation --tracks all

# Single track
ftse-sleeve-episodes --output-dir docs/data/paper_automation --tracks ai_judgment_fair
```

## Monthly deposits

`PaperFundConfig.monthly_deposit` already exists. Enabling e.g. `500` on a
**Suite B** book is optional and **starts a new capital epoch** — do not silently
turn it on for stress primary books mid-flight. Prefer a fair-lab twin or a
documented epoch reset when deposits begin.

## Evidence gathered to date — validity

| Prior evidence | Effect of this lab |
|----------------|--------------------|
| Paper NAV / excess vs ^FTSE / decision-review | **Unchanged** — observe-only additive store |
| Exit shadow / exit-timing / entry DCA / hypothesis | **Unchanged** — separate strands continue |
| Momentum grace / rules churn history | **Still valid** for what it measured (capital-path under then-current rules) |
| Reinterpreting old NAV as dual-path sleeve tags | **Invalid** — do not back-label |

Forward sleeve episodes are a **new cohort clock**. Thickness gates
(`ready_for_sleeve_timing_analysis`) require ≥15 closed episodes per
`capital_status` tag before promoting timing conclusions.

## Related

- [`buy-tier-cohort-labs.md`](buy-tier-cohort-labs.md) — wide `buy_tier_level` capital cohort
- [`decision-recording-checklist.md`](decision-recording-checklist.md) — freeze at *t*, join forward
- [`exit-timing-cohorts.md`](exit-timing-cohorts.md) — hold/swap observe cohorts
- [`primary-learning-track.md`](primary-learning-track.md) — adoption = fair excess vs market
