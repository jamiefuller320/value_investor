# Agent token usage

Real token counts and server cost for every Cursor SDK agent run. The
estimated-USD ledger (`budget.estimated_spend_*`, about **$0.40 per memo** and
about **$3.66 per director–worker**) stays the hard `weekly_ops_cap_usd` gate.
This log is the measurement the owner uses to set a token warning. $200 Ultra
cash does not correlate with the plan token allowance.

## What is logged

Each finished run appends one JSON line to `docs/data/agent_usage_log.jsonl`:

| Field | Meaning |
|-------|---------|
| `timestamp` | UTC time the row was written |
| `job` | Stable name (`research_memo`, `gap_fill`, `director_worker`, `engineering`, …) |
| `model` | Model id the caller selected |
| `agent_id` / `run_id` | SDK agent and the client run id when the run returned one |
| `usage_run_id` | Server usage id when `get_usage` returned a per-run row |
| `ticker` / `pool` | Set when the caller knows them (`weekly_ops` or `ad_hoc`) |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `total_tokens`, `reasoning_tokens` | From `TokenUsage` |
| `raw_cost_cents` | Undiscounted model token cost, server-derived. Set even when the run is inside the plan |
| `charged_cents` | Amount actually charged. **0** for plan-included, BYOK, and credit-grant usage |
| `cost_pending` | True when cost is still null |
| `usage_error` | Set when `get_usage` raised. The agent job itself is unchanged |

Appends take an exclusive file lock. A recording failure is logged and, when
`get_usage` ran but failed, stored as `usage_error`. It does not fail the job.
Objects without `get_usage` (tests) and pytest runs are a no-op unless
`FTSE_AGENT_USAGE_RECORD=1`.

`RunResult` from `agent.send(...).wait()` carries `usage: TokenUsage | None`
(token counts only). It does not carry `UsageCost`. Cost comes from
`agent.get_usage()`.

## Raw cost versus charged

`raw_cost_cents` is the undiscounted model token cost. Use it to watch the
plan's token allowance. `charged_cents` is what Cursor billed; plan-included
runs stay at 0, so charged dollars understate allowance draw. The warning
threshold is in **raw USD** (`raw_cost_cents / 100`).

## Lag and backfill

Cost is eventually consistent and can lag after a run ends. The row is written
immediately with `cost_pending: true` when cost is null.

Daily ops-monitor calls `backfill_pending_costs` for pending rows younger than
7 days. The pass resumes the agent and calls `get_usage`:

- `Agent.resume` is the `ResumeAgent` unary. It returns a handle. It does not
  call `send`, so it does not start a model run.
- `get_usage` is the `GetUsage` unary. It is read-only.
- The pass then `close()`s the handle.

If resume fails, the row stays pending and the weekly report records why.
Rows older than 7 days are left pending and counted as skipped. Local agents
reject a client `run-<uuid>` passed as `run_id` (`BadRequestError`); the
recorder calls unfiltered `get_usage` in that case and attributes the latest
turn so a resumed agent is not double-counted.

Drill-down (not the production path):

```bash
PYTHONPATH=src python3 -m value_investor.agent_usage_report --no-backfill
PYTHONPATH=src python3 -m value_investor.agent_usage backfill
```

## Measuring mode

`budget.token_usage_weekly_warning_raw_usd` defaults to **null**. While it is
null, `check_agent_token_usage` emits an info finding **Agent token usage
(measuring)** with week-to-date raw cost, tokens, top jobs, and research-memo
median / p90 raw cost beside the ledger's $0.40 estimate, plus the
estimated-USD ledger total for that ISO week when `budget.week_id` matches.

When the owner sets the threshold, the finding warns at **80%** and **over
100%** of week-to-date raw cost. A separate info finding **Agent token usage
coverage gap** fires when more than 10% of the week's rows have `usage_error`
or are still `cost_pending` after 48 hours.

`auto_fixable` is false. The finding does not rememo, ingest, or change
`weekly_ops_cap_usd`.

The weekly roll-up is `docs/data/agent_usage_weekly.json`: per ISO week and per
plan cycle (`plan_refresh_day_of_month`, same `YYYY-MM-dN` label as
`budget.cycle_id`). Both files are on the ops-monitor optional commit list.
Jobs that run agents outside that commit (weekday rememo, library ingest,
engineering spend, horizon scan, analysis review, learning director, paper
learning review) also keep the JSONL. Hunter-fix commits an allowlisted PR
diff and does not push this log to main.

## Calibration

After 2–3 weeks of measuring, compare each plan cycle's raw cost in
`agent_usage_weekly.json` with the Cursor usage page. Then set
`budget.token_usage_weekly_warning_raw_usd` in `docs/data/library/policy.json`.
Leave the field null until that comparison exists. The 15% estimated-USD
plan-credit warning remains a stand-in until this threshold is set. L52 and
N16 stay open until the calibrated warning has data.

Checklist: [human-tasks-checklist.md](human-tasks-checklist.md).
Ops monitor: [ops-monitor.md](ops-monitor.md).
Estimated-USD stand-in: [cycle-budget-surplus.md](cycle-budget-surplus.md).
