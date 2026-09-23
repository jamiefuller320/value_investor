# Dual-path sleeve lab (observe-only)

Parallel **capital book** + **widest sleeve observe path** with capital-status
tags. Implements the recording half of deferred **L443** / **L444**
(schema **v2**: near-buy → grace-end + ~1 month).

Does **not** change live paper allocation, knobs, or decision-review `--apply`.

## Paths

| Path | Job | Success metric |
|------|-----|----------------|
| **Capital book** (existing paper tracks) | Monthly deposits (optional config) + rotation | NAV excess vs ^FTSE after fair costs |
| **Sleeve episodes** (this lab) | Every near-buy / buy-tier crossing opens an episode | Sleeve return / timing **by** `capital_status` |

## Markers (widest freeze, schema v2)

| Marker | Definition |
|--------|------------|
| **Earliest entry** | First paper-auto pass the name is **near-buy** (`hold` + conviction ≥ `0.28` pre_buy floor) **or** `buy` / `strong_buy` — whichever comes first |
| **Latest experimental exit** | Momentum-grace end + `post_grace_extra_days` (~30d / ~1 month). **Fallback** if grace never arms: left the wide zone (near-buy ∪ buy-tier) for `exit_confirm_screens` consecutive passes, then + `post_grace_extra_days`. Hard `avoid` closes immediately |
| **Sub-markers** (stamped, not gates) | `first_near_buy_at`, `first_buy_tier_at`, `grace_started_at`, `grace_ended_at`, `experimental_exit_due_at` — for nested counterfactuals later (**L446**) |
| **Best policy** | Nested counterfactual *inside* the wide episode — not the recording gate |

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

`PaperFundConfig.monthly_deposit` already exists. The FTSE **realism experiment**
is a cold-start twin:

| Book | `monthly_deposit` | Role |
|------|-------------------|------|
| `buy_tier_level` | `0` | Recycling epoch-0 (Overview primary held line) |
| `buy_tier_level_dca` | `500` | New capital epoch — household DCA realism |

Do **not** silently turn deposits on for stress primary books mid-flight. Prefer
this dedicated twin (or a fair-lab twin) with a documented epoch reset.

Overview FTSE held-vs-market overlays the DCA twin as branch series (held +
deposit-matched ^FTSE). See [`buy-tier-cohort-labs.md`](buy-tier-cohort-labs.md#ftse-dca-realism-twin-buy_tier_level_dca).

## Evidence gathered to date — validity

| Prior evidence | Effect of this lab |
|----------------|--------------------|
| Paper NAV / excess vs ^FTSE / decision-review | **Unchanged** — observe-only additive store |
| Exit shadow / exit-timing / entry DCA / hypothesis | **Unchanged** — separate strands continue |
| Momentum grace / rules churn history | **Still valid** for what it measured (capital-path under then-current rules) |
| Reinterpreting old NAV as dual-path sleeve tags | **Invalid** — do not back-label |
| v1 episodes (buy-tier open → leave-tier × confirms) | **Prior cohort** — v2 widens the window; do not merge without schema_version |

Forward sleeve episodes are a **new cohort clock**. Thickness gates
(`ready_for_sleeve_timing_analysis`) require ≥15 closed episodes per
`capital_status` tag before promoting timing conclusions.

## Related

- [`buy-tier-cohort-labs.md`](buy-tier-cohort-labs.md) — wide `buy_tier_level` capital cohort
- [`decision-recording-checklist.md`](decision-recording-checklist.md) — freeze at *t*, join forward
- [`exit-timing-cohorts.md`](exit-timing-cohorts.md) — hold/swap observe cohorts
- [`primary-learning-track.md`](primary-learning-track.md) — adoption = fair excess vs market
