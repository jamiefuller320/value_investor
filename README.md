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
```

Outputs land in `output/`:

| File | Contents |
|------|----------|
| `latest_signals.csv` | Ranked signals — main artifact |
| `signals_*.csv` | Timestamped snapshot |
| `model_results_*.csv` | Per-model pass/fail detail |
| `agent_analysis.md` | SDK qualitative review |

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
