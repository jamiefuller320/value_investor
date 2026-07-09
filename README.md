# FTSE 100 Value Investor

Quantitative screener for FTSE 100 constituents against classic value investment models, with optional Cursor SDK agent analysis for qualitative follow-up.

## What it does

1. **Fetches** the current FTSE 100 list (Wikipedia) and fundamental data (yfinance / LSE `.L` tickers).
2. **Screens** each company through **18 value models**:

   | Category | Models |
   |----------|--------|
   | Graham | Defensive, Enterprising, Net-Net (NCAV) |
   | Classic value | Schloss, Deep Value, Earnings Yield, FCF Yield, Low P/E + High Yield |
   | GARP | Lynch PEG, Neff PEGY |
   | Quality / moat | Quality Value, Buffett Quality, Economic Moat |
   | Dividend | High Dividend Yield, Dividend Growth |
   | Quantitative | Magic Formula, Acquirer's Multiple, Dreman Contrarian, Piotroski F-Score, Composite Value |
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

# Simulate £1,000 portfolio with 3% per-trade costs from archived runs
ftse-simulate
ftse-simulate --capital 1000 --trade-cost 0.03 --json

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

## GitHub Pages dashboard

A static web dashboard lives in `docs/` and is published automatically after each weekly workflow run.

**Enable:** Repository **Settings → Pages → Build and deployment → Source: Deploy from branch `main` / folder `/docs`**.

| URL (example) | `https://<user>.github.io/value_investor/` |
|---------------|---------------------------------------------|

The dashboard shows:

- Signal overview and week-over-week changes
- Searchable screener table (all FTSE 100 names)
- Strong buys with trade plans
- Backtest and portfolio simulation results
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

**Schedule weekly** via GitHub Actions: add repository secrets `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` (optional `CURSOR_API_KEY` for `--deep-analysis`). The workflow in `.github/workflows/email-report.yml` runs every Monday 07:00 UTC, or trigger manually from the Actions tab.

Reports include:
- **Data quality scores** per company (downgrades thin-data signals)
- **Technical timing** — RSI, 50/200-day MAs, MACD with accumulate/neutral/wait signals
- **Conviction & stability** (weeks at signal, new vs persistent picks)
- **Week-over-week signal changes** (new and persistent strong buys)
- **Signal backtest** vs FTSE 100 (after 2+ archived weekly runs)
- **Portfolio simulation** — £1,000 pot, 3% per trade, rebalanced on top conviction picks
- **Deep analysis** on top 5 picks when `CURSOR_API_KEY` is set

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
