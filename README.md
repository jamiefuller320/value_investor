# FTSE Value Investor

Quantitative screener for FTSE 350 constituents (FTSE 100 + FTSE 250) against classic value investment models, with optional Cursor SDK agent analysis for qualitative follow-up.

## What it does

1. **Fetches** the current FTSE 100 and FTSE 250 lists (Wikipedia) and fundamental data (yfinance / LSE `.L` tickers). Default universe is **FTSE 350** (~350 names after dedupe); override with `--universe ftse100|ftse250|ftse350`.
2. **Screens** each company through **20 value models** (five families):

   | Category | Models |
   |----------|--------|
   | Graham | Defensive, Enterprising, Net-Net (NCAV) |
   | Classic value | Schloss, Deep Value, Earnings Yield, FCF Yield, Low P/E + High Yield |
   | GARP | Lynch PEG, Neff PEGY |
   | Quality / moat | Quality Value, Buffett Quality, Economic Moat |
   | Dividend | High Dividend Yield, Dividend Growth |
   | Risk | Earnings Quality, Financial Health |
   | Quantitative | Magic Formula, Acquirer's Multiple, Dreman Contrarian, Piotroski F-Score, Composite Value |

   Model scores are combined with **adaptive weights** (`output/model_weights.json`) that refine over time from archived weekly runs (score → forward-return correlation).
3. **Emits signals** — `strong_buy`, `buy`, `hold`, `avoid`, or `insufficient_data`
4. **Optional agent pass** — Cursor SDK reads the CSV and writes a qualitative memo on top candidates

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Screen full index (takes a few minutes — one yfinance call per company)
ftse-screen

# Dry run on 10 names
ftse-screen --limit 10

# Agent analysis (requires CURSOR_API_KEY)
export CURSOR_API_KEY="cursor_..."
python scripts/agent_analyze.py --limit 20 --top 5

# Email report with per-company signals + reason summaries
export SMTP_HOST="smtp.gmail.com"
export SMTP_USER="you@gmail.com"
export SMTP_PASSWORD="your-app-password"
export EMAIL_TO="you@gmail.com"
ftse-email --dry-run          # preview without sending
ftse-email                    # run screen + email
ftse-email --deep-analysis    # add Cursor deep analysis (top 5 + red flags)

# Deep research memos for every strong buy (5-year financials + 1-year news)
ftse-research --dry-run       # list eligible strong buys
ftse-research                 # initial deep pass (requires CURSOR_API_KEY)
ftse-email --research-docs    # screen + update research + email (weekly rerun appends updates)

# Simulate £1,000 portfolio with 3% per-trade costs from archived runs
ftse-simulate
ftse-simulate --capital 1000 --trade-cost 0.03 --json
ftse-simulate --capital 1000 --monthly-deposit 100 --trade-cost 0.03

# Historical analysis replay (up to 3 years, weekly smoothing)
ftse-historical --output-dir output

# Preflight before the first weekly production run
ftse-preflight
ftse-preflight --require-email --require-agents

# Verify CURSOR_API_KEY authenticates (optional --list-models)
ftse-verify-key
ftse-verify-key --list-models

# Publish dashboard to docs/ for GitHub Pages (after a screen or email run)
ftse-publish
ftse-email --dry-run --publish-dashboard
```

Outputs land in `output/`:

| File | Contents |
|------|----------|
| `latest_signals.csv` | Ranked signals — main artifact |
| `signals_*.csv` | Timestamped snapshot |
| `model_results_*.csv` | Per-model pass/fail detail |
| `agent_analysis.md` | SDK qualitative review |
| `email_report.html` | Email preview (all companies + summaries) |
| `email_report.txt` | Plain-text email preview |
| `research/{TICKER}/research.md` | Per-ticker strong buy research memo |
| `research/{TICKER}/sources/` | Cached financials, news, and screening snapshots |

## GitHub Pages dashboard

A static web dashboard lives in `docs/` and is published by the **Deploy GitHub Pages** workflow when `docs/` changes on `main`.

**Enable (one-time):** Repository **Settings → Pages → Build and deployment → Source: GitHub Actions** (not “Deploy from branch”). The workflow file is `.github/workflows/pages.yml`.

| URL (example) | `https://<user>.github.io/value_investor/` |
|---------------|---------------------------------------------|

The weekly email workflow commits updated data to `docs/data/` (and research memos to `docs/research/`), which triggers a Pages redeploy.

The dashboard shows:

- Signal overview and week-over-week changes
- Searchable screener table (all screened names)
- Strong buys with trade plans
- Backtest and portfolio simulation results
- **Historical analysis** — point-in-time replay of screen + research with weekly smoothing
- Deep analysis and per-ticker research memos (when published)

```bash
ftse-screen --limit 10
ftse-publish                  # writes docs/data/latest.json
# or
ftse-email --dry-run --publish-dashboard
```

## Email agent

`ftse-email` runs the full screener, builds a **brief reason summary per company** from model pass/fail data, and emails an HTML + plain-text report via SMTP.

Configure SMTP in `.env` (see `.env.example`). For Gmail, use an [app password](https://support.google.com/accounts/answer/185833).

**Schedule weekly** via GitHub Actions: add repository secrets `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` (optional `CURSOR_API_KEY` for `--deep-analysis`). `.github/workflows/email-report-schedule.yml` dispatches `.github/workflows/email-report.yml` via `workflow_dispatch` every Monday **07:17 UTC** (off the hour). You can also run **Schedule FTSE Email Report** or **FTSE Email Report** manually from the Actions tab.

## Storage and retention

Artifacts are kept lean for larger universes:

- **Compact JSON** for dashboard and summary files (no pretty-print indent)
- **Gzip** for local history snapshots (`output/history/run_*.json.gz`, `models_*.json.gz`) and research revision archives
- **3-year retention** for local history, timestamped CSV/JSON copies, and research news batches
- **Dashboard archives** keep the newest 8 dated snapshots in `docs/data/archive/` (not unbounded git growth)
- Research index in `latest.json` stores a short summary blurb; full memos remain in `docs/research/*.md`

## Alternate data sources

When yfinance returns errors or leaves key fundamentals blank, a curated fallback cascade fills gaps:

1. Yahoo `quoteSummary` JSON modules
2. Yahoo chart meta (last price)
3. Stooq UK daily CSV (last close)

This is **not** an open web crawl — only stable CSV/JSON endpoints are used. Recovered fields are recorded in `data_sources` on each company row.

Reports include:
- **Data quality scores** per company (downgrades thin-data signals)
- **Technical timing** — RSI, 50/200-day MAs, MACD with accumulate/neutral/wait signals
- **Conviction & stability** (weeks at signal, new vs persistent picks)
- **Week-over-week signal changes** (new and persistent strong buys)
- **Signal backtest** vs FTSE 100 (after 2+ archived weekly runs)
- **Portfolio simulation** — £1,000 pot, 3% per trade, rebalanced on top conviction picks
- **Historical analysis** — 3-year replay of screen + research recommendations with 4-week smoothing
- **Deep analysis** on top 5 picks when `CURSOR_API_KEY` is set
- **Buy-tier research** — per-ticker memos for strong buys and a capped set of top buys, from five years of financials and one year of news, with weekly update sections and **verdict revisions** when material news changes conviction
- **Portfolio actions (dashboard)** — log when you act on a recommendation with limit/stop levels prefilled from the trade plan; diversification steer ranks unused buy-tier names toward a balanced book (browser-local storage)
- **Price charts** — popup charts on buy-tier recommendations with core/tactical buy, stop, target, and SMA levels marked

## Dashboard portfolio

The GitHub Pages **Portfolio** tab lets you:

1. **Run parallel paper funds** — nominate initial cash and an optional monthly deposit, then create three side-by-side pots. The Portfolio tab splits **Paper simulations** from the **Action log**. Within simulations, use sub-pages for **Overview**, **Immediate**, **Technical**, and **Automated**. The Automated page explains the decision rules and previews the next rebalance (sells, trims, buys, waits) before you run it.
2. **Log an action** from Strong buys / Buys — order type, limit, stop, take-profit, and allocation are prefilled from the technical trade plan when available (intent log; does not move paper-fund cash).
3. **Mark each logged trade Simulated or Live** with a slider (default Simulated). Filter the book, and flip mode later per row.
4. **Seed simulated buys** from the current screen — up to five diversified buy-tier names with core (+ tactical) legs prefilled for paper evaluation.
5. **Track open vs closed** action intents in this browser (`localStorage`), with JSON export/import for backup.
6. **See diversification advice** scoped to the selected book — sector concentration vs a 30% soft cap, and a ranked list blending conviction with sector diversity.
7. **Open a price chart** on buy-tier names — 1y closes with core/tactical buy, stop, target, and SMA levels marked.

Action logs and paper funds are private to your browser; they are not committed by the weekly workflow. Legacy action rows without a mode are treated as live.

### Paper fund modes

| Mode | Behaviour |
|------|-----------|
| Immediate buy/sell | Manual trades against the pot (shares / £ / % NAV). |
| Follow technical cues | One-click pass: exit on stop or take-profit; enter unused buy-tier names at core limit (~10% NAV) when timing is not `wait`. The Technical page previews those exits/entries before you run the pass. |
| Automated stock picking | Rules-based equal-weight rebalance into top conviction buy-tier names (skips `timing_signal=wait`). Can run **independently** after London open settle (~75 min after 08:00, ≈ 09:15) via browser toggle and/or weekday GitHub Action `FTSE Paper Automation`. Surveils paper holdings plus live action-log names for stop/target/timing alerts. |

### Independent daily automation

```bash
# Add real/live owned tickers for surveillance (optional)
ftse-paper-auto --add-watch BP.L --add-watch SHEL.L

# Primary learning track: AI-judgment book + rules control
ftse-paper-auto --reports docs/data/latest.json --tracks all
ftse-paper-auto --reports docs/data/latest.json --tracks all --force
ftse-decision-review --tracks all --apply
ftse-paper-auto --surveillance-only
```

State lands in `docs/data/paper_automation/` (rules control) and `ai_judgment/` (primary). Success = excess after costs vs FTSE — see `docs/ops/primary-learning-track.md`. The workflow `.github/workflows/paper-auto.yml` schedules weekdays at **08:17 UTC** (≈ 09:17 Europe/London in BST) so early open volatility can settle before acting.

Weekly strategy simulation (`ftse-simulate`) remains available for archived-run backtests and now accepts `--monthly-deposit` so returns are measured against capital contributed.

## Project objective

Ultimate goal: a **self-improving automated global value portfolio**.  
Realistic interim goal: **hands-off learning from AI paper decisions vs market datums**, plus accurate decision packs when capital is at risk.

See [`docs/PROJECT_OBJECTIVE.md`](docs/PROJECT_OBJECTIVE.md) for staged exit criteria. Near-term priority is FTSE 350 data richness and paper decision quality — not wider live coverage.

## Offline multi-market data libraries

Other markets accumulate constituents + fundamentals **offline** without changing the live FTSE 350 screen. Growth is **one focus index at a time** (default `sp500` → then `euro_stoxx50` → `asx200`).

```bash
ftse-library policy                    # Pro $20, refresh day 8, focus + graduation
ftse-library ladder                    # grow → maintain graduated → screen → research → graduate
ftse-library graduate --dry-run        # check floors without advancing
ftse-library ladder --dry-run-research
ftse-library review-model
```

Budget: **Cursor Pro** subscription ($20/mo, refresh **8th**, surplus **7th**) is metadata; library research uses a **£30/week usage envelope** with **`enforce_weekly_research_cap`** (flagged `constraining` when spent). Focus auto-advances when coverage/stale floors are met; graduated markets get a light maintenance grow. Policy: `docs/data/library/policy.json`.

## Parked ideas (periodic review)

Deferred / “useful later” recommendations live in [`docs/deferred-ideas.json`](docs/deferred-ideas.json) and render to [`docs/deferred-review.md`](docs/deferred-review.md).

```bash
# Agents (and humans) append parked ideas:
ftse-defer add --category later --title "…" --summary "…" --revisit-when "…"
ftse-defer list
ftse-defer status L3 done
ftse-defer render
```

Cloud agents are instructed via `AGENTS.md` to call `ftse-defer add` whenever they park an idea.


`ftse-research` (or `ftse-email --research-docs`) builds a dedicated memo for quality-gated `strong_buy` names first, then fills remaining slots with top `buy` names by conviction (default weekly cap: 12). Hold, avoid, and short-side names are not researched.

1. **First pass** — for each memo ticker, ingests:
   - **Primary filings** under `sources/filings/` — RNS / results announcements (annual + interim when discoverable) via Google News + optional [Ticker.app](https://developers.ticker.app/) RNS API (`TICKER_API_KEY` / `RNS_API_KEY`); body text saved when a direct publisher URL is available
   - **Secondary Yahoo context** — five years of annual statements (+ cached quarterly income) in `financials_annual.json` (not mixed into the filings store)
   - One year of headlines (yfinance + Google News RSS) and the quantitative screen snapshot  
   The Cursor agent prefers filing bodies for FINANCIAL REVIEW and falls back to Yahoo only when needed.
2. **Weekly reruns** — refreshes filings + news, appends a `WEEKLY UPDATE` section, and **revises the research verdict** when material news/filings change conviction (otherwise repeats the prior verdict).

Memos are stored under `output/research/{TICKER}/` as `research.md` + `research.json`. The weekly GitHub Action enables `--research-docs` when `CURSOR_API_KEY` is configured. Active buy-tier names use `--research-cap N`; names that later drop off the pick list keep receiving weekly updates (oldest memos first) up to `--alumni-cap N` so decision history stays rich — disable with `--no-continue-alumni`. Optional repo secret `TICKER_API_KEY` improves RNS body coverage for memo names.

## First weekly run checklist

Before the scheduled Monday workflow (or your first manual `ftse-email`):

1. **Repository secrets** — `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO`; optional `CURSOR_API_KEY` for deep analysis and research updates.
2. **GitHub Pages** — Settings → Pages → Source: **GitHub Actions** (see `.github/workflows/pages.yml`).
3. **Preflight** — `ftse-preflight --require-email` (CI runs this automatically). Warnings about missing history are normal on week 1. If you set `CURSOR_API_KEY`, confirm it with `ftse-verify-key` before enabling `--deep-analysis` / `--research-docs`.
4. **Seed a screen locally** (optional but recommended) — `ftse-screen` then `ftse-email --dry-run --publish-dashboard` to verify outputs before Monday.
5. **Research memos** — on first buy-tier signals, run `ftse-research` or `ftse-email --research-docs` so conviction overlays and historical replay have point-in-time verdicts.
6. **Week 2+** — backtest, simulation, and historical analysis activate once two weekly snapshots exist in `output/history/`.

```bash
ftse-preflight --require-email
ftse-screen
ftse-email --dry-run --publish-dashboard
# with agents:
ftse-email --dry-run --publish-dashboard --deep-analysis --research-docs
```

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ FTSE 350 list   │────▶│ yfinance metrics │────▶│ Value models    │
│ (100 + 250)     │     │ per .L ticker    │     │ (18 screens)    │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                         │
                        ┌──────────────────┐     ┌─────────▼────────┐
                        │ agent_analyze.py │◀────│ Signal ranking   │
                        │ (Cursor SDK)     │     │ → CSV output     │
                        └──────────────────┘     └──────────────────┘
```

## Cursor SDK integration

The agent script uses the **one-shot** `Agent.prompt(...)` pattern — right for a scheduled job that screens, then asks for a memo:

```python
from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

result = Agent.prompt(prompt, AgentOptions(
    api_key=os.environ["CURSOR_API_KEY"],
    model="composer-2.5",
    local=LocalAgentOptions(cwd=os.getcwd()),
))
```

For a multi-turn research workflow (e.g. "now pull the annual report for the #1 pick"), switch to `Agent.create()` + `agent.send()` so conversation context carries across prompts.

**Runtime:** this project defaults to **local** agents (`local=LocalAgentOptions(cwd=...)`) so the agent reads `output/latest_signals.csv` from your machine. For CI/cloud-only runs, pass `cloud=CloudAgentOptions(repos=[...])` instead — but commit signals to the repo or attach them in the prompt, since the cloud VM won't have your local `output/` folder.

## Extending

| Goal | Where to edit |
|------|---------------|
| Add a model | `src/value_investor/models/` — subclass `ValueModel`, register in `models/__init__.py` |
| Change signal thresholds | `src/value_investor/signals.py` → `assign_signal()` |
| Different index | Pass `--universe ftse100|ftse250|ftse350` or replace `fetch_universe_constituents()` |
| Richer data | Swap yfinance for a paid API in `fetch.py` |

## Disclaimer

This tool produces **research signals**, not investment advice. Screens rely on third-party data that may be stale or incomplete. Always verify figures against primary sources before making decisions.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
```
