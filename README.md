# FTSE 100 Value Investor

Quantitative screener for FTSE 100 constituents against classic value investment models, with optional Cursor SDK agent analysis for qualitative follow-up.

## What it does

1. **Fetches** the current FTSE 100 list (Wikipedia) and fundamental data (yfinance / LSE `.L` tickers).
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
- Searchable screener table (all FTSE 100 names)
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

**Schedule weekly** via GitHub Actions: add repository secrets `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` (optional `CURSOR_API_KEY` for `--deep-analysis`). `.github/workflows/email-report-schedule.yml` dispatches `.github/workflows/email-report.yml` via `workflow_dispatch` every Monday **07:17 UTC** (off the hour). You can also run **Schedule FTSE Email Report** or **FTSE 100 Email Report** manually from the Actions tab.

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

1. **Log an action** from Strong buys / Buys — order type, limit, stop, take-profit, and allocation are prefilled from the technical trade plan when available.
2. **Mark each trade Simulated or Live** with a slider (default Simulated). Filter the book, and flip mode later per row.
3. **Seed simulated buys** from the current screen — up to five diversified buy-tier names with core (+ tactical) legs prefilled for paper evaluation.
4. **Track open vs closed** actions in this browser (`localStorage`), with JSON export/import for backup.
5. **See diversification advice** scoped to the selected book — sector concentration vs a 30% soft cap, and a ranked list blending conviction with sector diversity.
6. **Open a price chart** on buy-tier names — 1y closes with core/tactical buy, stop, target, and SMA levels marked.

Action logs are private to your browser; they are not committed by the weekly workflow. Legacy rows without a mode are treated as live.

## Buy-tier research

`ftse-research` (or `ftse-email --research-docs`) builds a dedicated memo for quality-gated `strong_buy` names first, then fills remaining slots with top `buy` names by conviction (default weekly cap: 8). Hold, avoid, and short-side names are not researched.

1. **First pass** — ingests five years of annual statements (yfinance), one year of headlines (yfinance + Google News RSS), and the quantitative screen snapshot; Cursor agent writes sections on thesis, financials, risks, and news.
2. **Weekly reruns** — refreshes sources, fetches new headlines since the last update, appends a `WEEKLY UPDATE` section, and **revises the research verdict** when material news changes conviction (otherwise repeats the prior verdict).

Memos are stored under `output/research/{TICKER}/` as `research.md` + `research.json`. The weekly GitHub Action enables `--research-docs` when `CURSOR_API_KEY` is configured. Override the cap with `--research-cap N`.

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
│ FTSE 100 list   │────▶│ yfinance metrics │────▶│ Value models    │
│ (Wikipedia)     │     │ per .L ticker    │     │ (18 screens)    │
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
| Different index | Replace `fetch_ftse100_constituents()` or pass a custom ticker CSV |
| Richer data | Swap yfinance for a paid API in `fetch.py` |

## Disclaimer

This tool produces **research signals**, not investment advice. Screens rely on third-party data that may be stale or incomplete. Always verify figures against primary sources before making decisions.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
```
