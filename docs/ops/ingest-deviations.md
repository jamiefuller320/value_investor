# Ingest deviations

Post-ingest check after a library weekday deepen. Safe steps run automatically;
URL replacement and intensive pins stay on a human deviation list.

**Dashboard:** Automation tab → **Ingest deviations**.

## What is automatic

After each `ftse-library ingest-loop` (euro sprint included):

1. Failed IR allowlist fetches are marked `unfetchable` so the next pass skips them.
2. A **deviation** is recorded when a deepened ticker:
   - exhausts IR retries (`ir_exhausted`), or
   - hits the weekday ticker cap with **no** coverage gain and leftover
     indexed-without-body rows (`blocker_no_improve`).
3. If a later deepen **improves** that ticker, the open row is auto-resolved.
4. Each open row gets an observe-only **`signal_triage`** label from the latest
   library screen (never auto-applied):

| Screen / leftover | Proposed action | Human command |
|-------------------|-----------------|---------------|
| Parked leftover / not buy-tier / missing signal (not `strong_buy`) | `dismiss` | `dismiss` |
| Plain `buy` | `park_hunter` | `dismiss` (rely on exhaustion park + source hunter) |
| `strong_buy` (even if parked) | `pin_intensive` | `approve` |

The check does **not**:

- invent replacement IR URLs (wrong-issuer vs official IR is judgment)
- auto-pin every blocker (that would starve the 24-name weekday batch)
- auto-approve or auto-dismiss from `signal_triage` (observe-only until the
  shadow matches human choices for several weeks — N151)
- tighten discovery or lengthen the euro slot

Stall / zero-improve **follow-up dispatch** is unchanged
(`ingest-gap-closure-followup`). Productive leftover-IWB still waits for the
next deepen.

## What needs a human

Open rows on the Automation tab. Prefer the `signal_triage` hint, then:

| Action | Command | Effect |
|--------|---------|--------|
| Reprocess (intensive pin) | `ftse-library ingest-deviations approve <id>` | Writes a 7-day pin to `docs/data/library_ingest_pins.json`. The next scheduled euro slot skips discovery and the 320s cap for that ticker. |
| Dismiss | `ftse-library ingest-deviations dismiss <id>` | Closes the row for 7 days. Same evidence will not reopen until the cooldown lapses. |

GitHub Pages is static — the dashboard cannot dispatch workflows. Approve
locally (or in an agent session), commit the pin + store, and let the next
cron pick it up.

List (includes signal triage):

```bash
ftse-library ingest-deviations list
```

Replacing an allowlist URL is still a code/data edit to
`docs/data/research_ir_urls.json` (and the builtin fallback in
`src/value_investor/research/filings.py` when the ticker is seeded there).
Approve a pin after the URL swap if the weekday cap was the blocker.

## Artifacts

| Path | Role |
|------|------|
| [`docs/data/ingest_deviations.json`](../data/ingest_deviations.json) | Open / reviewed rows (euro ingest commits this; `open_items[].signal_triage` is observe-only) |
| [`docs/data/library_ingest_pins.json`](../data/library_ingest_pins.json) | Dated intensive pins |
| [`docs/data/research_ir_urls.json`](../data/research_ir_urls.json) | Manual IR URL allowlist |

## Related

- [euro-depth-sprint.md](euro-depth-sprint.md)
- [human-tasks-checklist.md](human-tasks-checklist.md#ad-hoc-when-triggered)
- [library-ingest-escalation.md](library-ingest-escalation.md) (maintenance stagger when 3+ books)
