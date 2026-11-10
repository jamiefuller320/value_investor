# Memo model comparison

**Owner decision (2026-11-10):** "Lets do a side by side comparison on a limited number of names." The aim is to compare memo quality between the current memo model and a stronger one before deciding whether to switch.

**Strategy part served:** the memo bind and the research-verdict block (registration [section 2](strategy-book-registration.md) and [section 11](strategy-book-registration.md#11-data-compute-and-the-launch-queue)). A failed verdict blocks the entry (`memo_blocked`) and is a thesis break, so the model that writes the signal-day memo changes which entries the book makes.

**Observe-only.** Nothing here writes the research store, `strategy_book_memo_log.jsonl`, the forward book, a screen row or any decision path. `influences_live` is false. The strategy-book memo job (`strategy_book_memo_job.py`) is not modified or imported for its runner.

## Models

| Role | Model | Estimated $ per memo |
|------|-------|----------------------|
| Incumbent | `composer-2.5` (hard-coded in the memo job; also `policy.json` `research_model`) | 0.40 (registration section 11) |
| Challenger | `grok-4.6`, the strongest `grok-*` with a rate in `agent_model_policy.MODEL_API_RATES` | 1.04 (0.40 scaled by list rates, `model_ab.estimate_model_memo_usd`) |

**Runtime check (2026-11-10).** `Cursor.models.list` with the `CURSOR_API_KEY_V2` key listed `composer-2.5`, `grok-4.5`, `grok-4.6` and a newer `grok-4.7`. `grok-4.7` has no rate in `agent_model_policy`, so it is not the challenger here (queued as L701). The legacy `CURSOR_API_KEY` in the agent VM was rejected ("Invalid User API Key"). The workflow uses `CURSOR_API_KEY_V2` first, as memo-backfill does. Each generation run re-lists the models and fails closed, with no model call, if either id is missing. The ids it saw are stored in `status.json` → `runtime_models`.

## Names (rule v1, frozen 2026-11-10)

`ftse-memo-model-comparison select --before 2026-11-10 --apply` wrote `docs/data/memo_model_comparison/manifest.json`. It refuses to overwrite an existing manifest, so the set is fixed before any memo exists.

**Rule v1.**

- **Markets:** FTSE 350, plus the three graduated library markets with the most candidates (ties broken by market id).
- **Session:** each market's newest chart bar before the selection date, with the gate verdicts in force on that session.
- **Candidate:** a buy-tier row (`buy` or `strong_buy`) on that session's screen that meets all of these:
  - its research home is that market (library names deduplicated with `research_home_market`);
  - its filings index has key filing bodies on disk at selection time;
  - it has a 14-day RSI on the session.
- **Quotas:** FTSE 4, then 3, 3 and 2 for the library markets.
- **Contrast slot:** in each market, one slot goes to a gate-flagged candidate (operating decline not `clear`, or sector not `sound`). A scored `declining` or `headwind` verdict is preferred over `insufficient_data`.
- **Other slots:** unflagged candidates nearest the entry rule. Primary entry first, then the alternative entry, then lowest RSI, then ticker.
- **Short buckets** fill from the other bucket.

The bodies test reads the index as it is at selection time, not the strategy book's point-in-time bind. On 2026-11-10 the FTSE filings indexes had been re-scanned that morning, so the point-in-time bind would have excluded every FTSE name for the 2026-11-06 session even though the bodies were on disk. That dating issue is logged as a deferred fragment.

The pool held 65 candidates on FTSE 350 (session 2026-11-06), 128 on S&P 500, 31 on ASX 200 and 29 on Nasdaq 100 (sessions 2026-11-09).

| Market | Ticker | Name | Bucket | Signal | Decline / sector | Primary / alt entry | RSI | Bodies |
|--------|--------|------|--------|--------|------------------|---------------------|-----|--------|
| ftse350 | SCT.L | Softcat plc | near_entry | buy | clear / sound | yes / yes | 29.73 | 67 |
| ftse350 | VLX.L | Volex plc | near_entry | buy | clear / sound | yes / yes | 32.29 | 59 |
| ftse350 | KLR.L | Keller Group plc | near_entry | buy | clear / sound | no / yes | 35.75 | 78 |
| ftse350 | BP.L | BP p.l.c. | gate_flagged | buy | clear / headwind | no / yes | 37.3 | 23 |
| sp500 | FIS | FIS | near_entry | strong_buy | clear / sound | yes / yes | 29.44 | 21 |
| sp500 | SNDK | SNDK | near_entry | buy | clear / sound | no / yes | 30.01 | 22 |
| sp500 | ADM | ADM | gate_flagged | buy | declining / sound | yes / yes | 22.94 | 51 |
| asx200 | PLS.AX | PLS.AX | near_entry | buy | clear / sound | no / no | 42.15 | 24 |
| asx200 | AAI.AX | AAI.AX | near_entry | strong_buy | clear / sound | no / no | 50.77 | 61 |
| asx200 | WDS.AX | WDS.AX | gate_flagged | buy | declining / headwind | no / yes | 37.69 | 169 |
| nasdaq100 | STX | STX | near_entry | buy | clear / sound | no / yes | 31.96 | 69 |
| nasdaq100 | FANG | FANG | gate_flagged | strong_buy | declining / headwind | yes / yes | 33.17 | 23 |

Five names were on the primary entry (RSI below 35 at a 10-session low) and ten on the alternative. ASX had no unflagged name near entry, so its two `near_entry` slots are the nearest available.

## Same inputs

For each name, one run:

1. Copies the name's research `sources/` folder (the folder the production memo reads) to `output/memo_model_comparison/<slug>/sources`. The copy is git-ignored and not committed. A SHA-256 over every relative path and file is stored on both memos.
2. Calls `run_initial_research_agent` (the research runner's structured-verdict prompt) once per model on that copy, with:
   - the same `as_of_date` (the first generation date, kept on retries);
   - the same comparison appendix asking for `EVIDENCE` quotes with paths, `NUMBERS` copied from a cited file, and `THESIS BREAKS`.
3. Sets each agent's working folder to the snapshot folder. Neither model can read the existing research memo or anything else in the repo.

The appendix is the only difference from the production prompt, and both models get it. It exists so citations can be checked. Both memos use the initial prompt, not the weekly-update prompt, so neither model is anchored on an earlier memo written by the incumbent.

If a later run finds a different snapshot digest for a name with only one memo written, both memos are discarded and regenerated, so a pair never mixes inputs.

## Store

`docs/data/memo_model_comparison/`:

| File | Writer | Blind? |
|------|--------|--------|
| `manifest.json` | `select --apply` (once) | yes |
| `status.json` | each generation run: state, per-pair inputs digest, attempts, cost/latency/tokens, spend line, runtime model ids | no (cost reveals the model) |
| `memos/<slug>/A.json`, `B.json` | generation: verdict, rationale, risk tags, book effect, raw text, automated checks | yes (no model id, cost or timing) |
| `review.md` | generation, when all pairs are done: the blind side-by-side doc | yes |
| `ratings_template.json` | generation | yes |
| `ratings.json` | **the owner only** (excluded from every workflow commit) | — |
| `blind_key.json` | generation: which model is A and B per name (a deterministic coin flip per name) | **no — do not open before rating** |
| `results.json` | generation: unblinded automated comparison | **no** |
| `decision.json` | `decide --apply` | no |

`email-report` excludes the whole folder from its `docs/data` overlay.

## Automated checks (per memo)

- **Verdict, risk and confidence.** Verdict agreement and **book-effect agreement**: whether `core_sell_reason` would block entry on the verdict (`pass`, `sell`, `avoid`, `exit`).
- **Cited evidence:**
  - count;
  - how many cite a filing body;
  - whether each cited path resolves inside the snapshot;
  - whether the quote appears in that file (whitespace, quote marks and case normalised).
- **Numeric claims.** Each `NUMBERS` value is searched for in the cited file, ignoring thousands separators.
- **Hallucination flags:**
  - unresolved path;
  - quote not found in a resolved file;
  - number not found in a resolved file.

  Years after the as-of date are listed (`future_year_mentions`) but not flagged, because filings cite targets.
- **Thesis-break reasons** (listed), length (characters and words), tokens, charged cost when the usage record has it, the estimate, and latency.

## Spend

The comparison has its own budget line, `status.json` → `spend`, capped at **$22.00**. The estimate is 12 names × ($0.40 + $1.04) = **$17.28**, recorded in the `weekly_ops` pool as each memo is called.

Before every call the run checks two things:

- the comparison cap;
- that `weekly_ops` would keep at least **$22.00** after the call. That is the strategy-book memo job's weekly high estimate (35 × $0.40 = $14) plus the shared $8 minimum headroom.

A headroom stop is retried on a later weekday. A cap stop is final. A failed memo is retried once (two attempts). On 2026-11-10 `weekly_ops` had $112.50 left of $124.50.

## How to run

The workflow is `memo-model-comparison.yml`:

- **Weekday 10:40 UTC schedule:** runs `generate --apply --if-due`. It does nothing once the store is ready for review or capped, so it runs once after merge.
- **Run now:** `gh workflow run memo-model-comparison.yml -f action=generate`
- **After the owner's ratings:** `gh workflow run memo-model-comparison.yml -f action=decide` writes `decision.json`.

Local drill-down (needs `CURSOR_API_KEY_V2`):

```bash
ftse-memo-model-comparison --repo-root . generate           # dry run: names and budget
ftse-memo-model-comparison --repo-root . generate --apply   # call the models
ftse-memo-model-comparison --repo-root . status             # ops findings
ftse-memo-model-comparison --repo-root . decide [--apply]   # after ratings.json
```

## Owner blind review

Human task `adhoc-memo-model-comparison-blind-review`. Read `review.md`. For each name, rate memo A and memo B from 1 to 5 on:

- `evidence`: claims tied to the filings, nothing invented;
- `thesis_break`: says concretely what would make it a do-not-own name;
- `verdict_justified`: verdict and confidence match the evidence.

Then set `preferred` to `A`, `B` or `tie`: the memo you would rather the book act on. Copy `ratings_template.json` to `ratings.json`, fill it in and commit it to main. Do not open `blind_key.json`, `results.json` or `status.json` cost fields first.

## Decision rule (pre-declared 2026-11-10)

`decide()` reports; it never switches anything. The outcome is **switch** only if every check holds:

1. At least **10 of 12** pairs are complete.
2. The owner prefers the challenger on at least **8** names and the incumbent on at most **3** (ties count for neither).
3. The challenger's mean rubric total (out of 15) beats the incumbent's by at least **1.0**.
4. The challenger's quote resolution rate is **at least** the incumbent's.
5. The challenger has **no more** hallucination flags than the incumbent.
6. Where the two verdicts differ on blocking entry, the owner prefers the challenger's memo at least as often as the incumbent's.
7. 35 memos a week at the challenger's cost per memo (charged when recorded, otherwise the $1.04 estimate) fits inside `budget.strategy_book_memo_raise` ($40 a week).

The other outcomes:

- **keep**: at least 10 pairs are complete, and either the owner prefers the incumbent at least as often, or the challenger has more hallucination flags.
- **inconclusive_keep**: anything else. `composer-2.5` stays and the larger rerun (L702) becomes due.

**If the outcome is switch**, the owner approves the change. It is then logged as an `operational_switches` row on `docs/data/strategy_book_registration.json`, the same way `spend_enabled` was:

```
switch: memo_model, from: composer-2.5, to: grok-4.6, approved_by: owner, owner_quote, evidence: docs/data/memo_model_comparison/decision.json, budget note, review date
```

The memo runner's model then changes in its own PR. This is an operational switch, not a rule change: section 11 says only "uses the existing research runner" and seals no model. The $0.40 memo estimate in section 11 and `ESTIMATED_MEMO_USD` would be restated at the same time.

## Ops-monitor

`check_memo_model_comparison` runs daily after the strategy-book memo check and reads the store only. Every finding is `auto_fixable=false`. No rememo or ingest follows from a finding.

| Title | Severity | When |
|-------|----------|------|
| **Memo model comparison awaiting generation** | info | Manifest frozen, generation not finished; gives the dispatch command and estimate |
| **Memo model comparison failed** | warn | Model check failed, a model is missing, a memo errored, or a budget stop |
| **Memo model comparison ready for owner review** | info | All pairs done; reports names rated |
| **Memo model comparison owner review stale** | warn | Ready more than 14 days without complete ratings |
| **Memo model comparison decided** | info | Ratings complete; reports the rule's outcome and failed checks |

See [ops-monitor.md](ops-monitor.md#full-automation-wiring).
