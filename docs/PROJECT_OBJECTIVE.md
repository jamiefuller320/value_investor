# Project objective & development path

## Ultimate goal

Build a **self-improving automated global value stock portfolio**.

## Realistic interim goal

Ship **high-quality, accurate prompts and decision packs** that support **manual verification and trade actions** — research memos, trade plans, surveillance alerts, and paper-fund decision narratives a human can trust before capital is committed.

---

## North-star stages

Work proceeds stage-by-stage. Do **not** skip ahead into global breadth or full automation until the prior stage’s quality bar is met.

| Stage | Name | Outcome | Exit criteria |
|-------|------|---------|---------------|
| **0** | UK quant core *(current)* | FTSE 350 screen, adaptive weights, research memos, paper funds, post-open automation | Weekly archives accumulating; paper-auto + decision packs usable |
| **1** | Decision-review learning | Automated book learns from its own outcomes after costs | Documented review loop; knobs adjust from reviewed excess returns |
| **2** | Manual-action excellence | Decision packs good enough for routine human trading | Stable prompts: signal → thesis → levels → size → risks; low false confidence |
| **3** | Library-ready global data | Multi-market fundamentals/prices grow *offline* without polluting the live screen | Per-market manifests with coverage & freshness metrics; PIT constituent snapshots |
| **4** | Controlled universe expansion | First non-UK market screened with same quality bar as FTSE 350 | Data-quality and liquidity floors pass; paper track only at first |
| **5** | Self-improving automation | Portfolio rules improve from walk-forward review (evolution only if history is thick) | Cost-aware fitness; frozen screen signals for counterfactual safety |
| **6** | Global automated portfolio | Multi-market automated allocation with human override | Capital at risk only after stages 2–5 proven in paper |

### What “best progress” means now

1. **Deepen FTSE 350 richness** — weekly archives, filings, decision-review on paper-auto (not more names).
2. **Improve manual decision packs** — trade plans, surveillance, research quality, clear “verify before trade” prompts.
3. **Grow data libraries in the background** — progressive multi-market snapshots ready for stage 4, without changing the live screen.
4. **Only then** expand live coverage and tighten automation.

---

## Data-library principle

> **Richness before breadth on the live path; breadth may grow offline.**

The live screener stays on FTSE 350. A separate **data library** progressively fetches and retains constituents + fundamentals for other markets so future incorporation does not start from zero history.

See: `ftse-library` CLI, `src/value_investor/data_library.py`, and `.github/workflows/library-grow.yml` (persists under `docs/data/library/`).

### Library richness ladder (stage 3)

Fundamentals alone are **necessary but not sufficient** for a rich stage-4 expansion. Grow offline in layers:

| Layer | What accumulates | Why |
|-------|------------------|-----|
| **A. Fundamentals** *(current `ftse-library`)* | Constituents + Yahoo-style metrics, coverage/freshness manifests | PIT history and fetch reliability |
| **B. Screen-lite** *(later, L29)* | Offline model scores, signals, data-quality, dated archives | Ranking/stability history comparable to FTSE — the main missing richness |
| **C. Selective research** *(later, L30)* | Memos only for strong_buy / top buy names | Decision-pack depth for eventual manual verification; expensive, so cap tightly |

Do **not** run full FTSE-style research across whole foreign indexes. Prefer B for breadth of history; use C sparingly on the shortlist.

**One index at a time:** policy focus advances `sp500` → `euro_stoxx50` → `asx200` when coverage ≥95% and stale ≤15% among covered names. Graduated markets keep a generous maintenance grow (`maintenance_max_tickers`, default **100** per market per run; once the queue is complete, focus is included too).

### Running the ladder

```bash
ftse-library ladder                    # A grow → B screen-lite → C selective research
ftse-library screen                    # screen-lite only on focus metrics
ftse-library ladder --dry-run-research # shortlist without calling Cursor
```

Artifacts: `docs/data/library/markets/sp500/screen/` (signals, shortlist, history) and optional `screen/research/` memos.

### Research model / subscription budget

Cheapest agent for plan efficiency: **`composer-2.5`** (first-party pool). Billing configured for **Cursor Pro ($20/mo), refresh on the 8th** → surplus day **7th**, library strand **$2/week** (10%).

```bash
ftse-library policy                    # focus + budget + model
ftse-library review-model              # re-pick cheapest (Monday cron)
ftse-library ladder
```

- Screen-lite runs once enough focus metrics exist (≥25 by default).
- Selective research is capped by remaining weekly USD (~$0.40/memo estimate, hard cap 5).

---

## Related parked ideas

Tracked in [`docs/deferred-ideas.json`](deferred-ideas.json) / [`deferred-review.md`](deferred-review.md). Key linked items: decision-review learning (L1), evolutionary stage 2 (L2/N2), modest All-Share (L7), global expansion (N1), UK-primary data (L11), library screen-lite (L29), budget library research (L30), market-aware fetch (L31).
