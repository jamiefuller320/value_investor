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
| **0** | UK quant core | FTSE 350 screen, adaptive weights, research memos, paper funds, post-open automation | Weekly archives accumulating; paper-auto + decision packs usable |
| **1** | Decision-review learning | Automated book learns from its own outcomes after costs | Documented review loop; knobs adjust from reviewed excess returns (`ftse-decision-review`) |
| **2** | Manual-action excellence *(current)* | Decision packs good enough for routine human trading | Stable packs: signal → thesis → levels → size → risks; low false confidence (`decision_pack`) |
| **3** | Library-ready global data | Multi-market fundamentals/prices grow *offline* without polluting the live screen | Per-market manifests with coverage & freshness metrics; PIT constituent snapshots |
| **4** | Controlled universe expansion | First non-UK market screened with same quality bar as FTSE 350 | Data-quality and liquidity floors pass; paper track only at first |
| **5** | Self-improving automation | Portfolio rules improve from walk-forward review (evolution only if history is thick) | Cost-aware fitness; frozen screen signals for counterfactual safety |
| **6** | Global automated portfolio | Multi-market automated allocation with human override | Capital at risk only after stages 2–5 proven in paper |

### What “best progress” means now

1. **Use verify-before-trade packs** — email + Strong Buys dashboard; tighten research prompts when gaps show up.
2. **Keep decision-review learning running** — accumulate equity marks until knobs apply.
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
| **A. Fundamentals** *(current `ftse-library`)* | Constituents + Yahoo-style metrics, coverage/freshness manifests; dated PIT snapshots with decreasing resolution (dense ~400d → monthly → quarterly kept long-term) | PIT history and fetch reliability; coarse history stays cheap for future trend features |
| **B. Screen-lite** *(later, L29)* | Offline model scores, signals, data-quality, dated archives; same dense→monthly→quarterly retention as Layer A (including `signal_history.csv` row thinning) | Ranking/stability history comparable to FTSE — the main missing richness |
| **C. Selective research** *(later, L30)* | Memos only for strong_buy / top buy names; weekly **red-flag gap-fill loop** re-opens FINANCIAL REVIEW / RISKS for names called out in deep-analysis email red flags, seeks alternate evidence when local filings are thin, and parks research-model improvement suggestions | Decision-pack depth for eventual manual verification; expensive, so cap tightly |

Prefer B for breadth of history; use C on buy-tier shortlists (hard cap raised while Cursor research remains cheap). Do **not** memo every name in an index.

**Tradable north star (offline):** expand index slices toward stocks available on **Trading 212** (Invest / Stocks ISA catalogue). Index-slice queue:

`sp500` → `euro_stoxx50` → `asx200` → `ftse_smallcap` → `nasdaq100` → `dax` → `cac40` → `tsx60`

(FTSE 350 live screen unchanged; FTSE SmallCap ≈ All-Share gap vs 350.) Advance focus when coverage ≥95% and stale ≤15%. Graduated markets get **full-universe** maintenance (`maintenance_max_tickers: "full"`). Selective research round-robins buy-tier names across focus + graduated markets (`research_all_graduated`). Rating-priority maintenance is **L33**.

**Broker coverage:** `docs/data/library/t212_coverage/` is the tradable overlay. Fetch the official instrument book with `ftse-library t212-catalogue` (env: `TRADING212_API_KEY`, `TRADING212_API_SECRET`, optional `TRADING212_ENV=demo|live`), then join library tickers via `ftse-library t212-overlay` (ISIN / shortName catalogue hits; venue allowlist fallback). Advisory only — does not filter screens. Dashboard **Unavailable** bypass keeps unactionable names on a watched list and excludes them from suggested trades / paper auto-entries. Optional FIRDS MIC filter remains enrichment only (`ftse-library firds-filter`).

**Offline ladder slices:** `aim` → `ibex35` → `ftse_mib` → `aex` → `bel20` → `hang_seng` → `sti` → `us_adr_asia` → `atx` → `psi20` → `smi` → `omxs30` → `iseq20` (see `t212_coverage/policy.json`). Confirm tradability with `ftse-library t212-align` once the catalogue is fetched.

### Running the ladder

```bash
ftse-library ladder                    # A grow → B screen-lite → C selective research
ftse-library screen                    # screen-lite only on focus metrics
ftse-library ladder --dry-run-research # shortlist without calling Cursor
```

Artifacts: `docs/data/library/markets/sp500/screen/` (signals, shortlist, history) and optional `screen/research/` memos.

### Research model / usage budget

Cheapest agent for plan efficiency: **`composer-2.5`** (first-party pool). Cursor **subscription** (Pro **$20/mo**, refresh **8th** → surplus **7th**) is metadata only — included credits can be far below on-demand usage. Library research is capped by a **usage envelope of £30/week** (`weekly_usage_gbp` × `gbp_usd_rate` ≈ **$38.10**), with **`enforce_weekly_research_cap=true`**. When the envelope is spent, ladder selective research is skipped and the budget flag is **`constraining`** (dashboard + `ftse-library policy`).

```bash
ftse-library policy                    # focus + usage budget + flag
ftse-library policy --weekly-usage-gbp 30 --enforce-weekly-research-cap
ftse-library review-model              # re-pick cheapest (Monday cron)
ftse-library ladder
```

- Screen-lite runs once enough focus metrics exist (≥25 by default).
- Selective research is limited by the weekly usage envelope and `research_hard_cap` 50; buy-tier memos round-robin across graduated markets.

---

## Related parked ideas

Tracked in [`docs/deferred-ideas.json`](deferred-ideas.json) / [`deferred-review.md`](deferred-review.md). Key linked items: evolutionary stage 2 (L2/N2), global expansion (N1), UK-primary data (L11). Broker north star is **Trading 212** (catalogue + overlay under `t212_coverage/`). Implemented: trailing-stop sim track with entry floor (L44) + Performance submenu, trade-plan config/ATR (L5/L9), sim level gates (L3), verify-before-trade packs (L27), CI pytest (L24), decision-review (L1), orchestrator cron (L21), multi-currency paper NAV (L28), library screen-lite/research ladder.
