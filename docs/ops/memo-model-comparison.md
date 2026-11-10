# Memo model comparison

**Owner decision (2026-11-10):** "Lets do a side by side comparison on a limited number of names." The aim is to compare memo quality between the current memo model and a stronger one before deciding whether to switch.

**Strategy part served:** the memo bind and the research-verdict block (registration [section 2](strategy-book-registration.md) and [section 11](strategy-book-registration.md#11-data-compute-and-the-launch-queue)). A failed verdict blocks the entry (`memo_blocked`) and is a thesis break, so the model that writes the signal-day memo changes which entries the book makes.

**Amended to rule v2 on 2026-11-10, before any memo existed.** Owner: "yes please" to adding an LLM judge and reducing the owner's role to a calibration sample. See [Amendment: rule v2](#amendment-rule-v2-2026-11-10).

**Observe-only.** Nothing here writes the research store, `strategy_book_memo_log.jsonl`, the forward book, a screen row or any decision path. `influences_live` is false. The strategy-book memo job (`strategy_book_memo_job.py`) is not modified or imported for its runner.

## Models

| Role | Model | Estimated $ per memo |
|------|-------|----------------------|
| Incumbent | `composer-2.5` (hard-coded in the memo job; also `policy.json` `research_model`) | 0.40 (registration section 11) |
| Challenger | `grok-4.6`, the strongest `grok-*` with a rate in `agent_model_policy.MODEL_API_RATES` | 1.04 (0.40 scaled by list rates, `model_ab.estimate_model_memo_usd`) |
| Judge (rule v2) | `gpt-5.6-luna` (OpenAI family) | 0.94 per judge call, same scaling |

**Runtime check (2026-11-10).** `Cursor.models.list` with the `CURSOR_API_KEY_V2` key listed `composer-2.5`, `grok-4.5`, `grok-4.6` and a newer `grok-4.7`. `grok-4.7` has no rate in `agent_model_policy`, so it is not the challenger here (queued as L701). The legacy `CURSOR_API_KEY` in the agent VM was rejected ("Invalid User API Key"). The workflow uses `CURSOR_API_KEY_V2` first, as memo-backfill does. Each generation run re-lists the models and fails closed, with no model call, if either id is missing. The ids it saw are stored in `status.json` → `runtime_models`.

## Amendment: rule v2 (2026-11-10)

**Owner decision (2026-11-10):** "yes please" — amend the comparison before any results are seen: add an LLM judge, and reduce the owner's role to rating a calibration sample.

**Integrity check at amendment (11:47 UTC, 2026-11-10).** Generation had never run:

- The comparison PR ([#1354](https://github.com/jamiefuller320/value_investor/pull/1354)) was still open, so `memo-model-comparison.yml` was not on `main` and had no runs (`gh run list --workflow memo-model-comparison.yml` returned "workflow not found on the default branch").
- The store held only `manifest.json`. There was no `status.json`, memo, `results.json`, `review.md` or `ratings.json`.

So no memo, score or result existed when the rule changed, and nobody had seen any. The name selection (rule v1 below) is unchanged.

**How the amendment is enforced.** `ftse-memo-model-comparison amend --apply` wrote `decision_rule_version: "v2"`, an `amendment` block (date, owner quote, the state above), a `judge` block and the judge budget into `manifest.json`. It refuses once any generation output exists. Generation and the judge both refuse, with no model call, unless the manifest says rule v2. So a v1 run cannot happen from this code.

### Judge

- **Model:** `gpt-5.6-luna`, from a third family (OpenAI): not Cursor/Composer and not xAI/Grok. On 2026-11-10 the `CURSOR_API_KEY_V2` model list offered stronger third-family models (`claude-opus-5-5`, `claude-sonnet-5-5`, `gpt-5.5`), but none has a rate in `agent_model_policy.MODEL_API_RATES`. The third-family models that are both listed and rated are `gpt-5.6-luna`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5-mini`, `claude-haiku-4-5`, the three Gemini flash models, `kimi-k2.7-code` and `glm-5.2`. `gpt-5.6-luna` is the newest and highest-rated of the GPT and Claude ones. No rate was added.
- **Runtime check:** each judge run re-lists models with the key and refuses, with no call, unless the judge is listed, has a rate, and its family is neither Cursor, xAI nor either compared model's family (`check_judge_model`).
- **Blind:** the judge sees labels A and B only. There are no model names (any model or vendor name inside memo text is replaced by `[model]`), no cost and no timing.
- **Both orders:** every pair is judged twice: order `AB` shows stored memo A first; order `BA` shows stored memo B first. Each call's labels are mapped back to the stored labels.
- **Same inputs:** the agent's working folder is the pair's generation snapshot. The judge re-checks the snapshot digest and refuses a pair whose sources changed since generation.
- **Rubric:** the owner's 1–15 rubric (`evidence`, `thesis_break`, `verdict_justified`, each 1–5), plus `preferred` A, B or tie.
- **Structured evidence (LLM evidence rule):** JSON with a score, a reason and at least one verbatim quote per score (source `memo` or a path in the snapshot), a preference reason, and the claims it checked. Each call is written to `judgements/<slug>/<order>.json` with the raw reply, the parsed JSON, schema problems, the prompt's SHA-256, and a check of whether each quote it cited appears in the memo or file it named. A reply that fails the schema counts as a failed attempt. Each order gets two attempts.
- **Order consistency:** a preference counts only if both orders pick the same stored memo. Otherwise the pair is a tie. Rubric scores are the mean of the two orders.

### Owner calibration sample

The judge step picks the sample (`calibration.json`, rule in `CALIBRATION_RULE`):

1. every judged pair where the judge's order-consistent preference is A or B and the **mechanical direction** is the other label. Mechanical direction is the memo with fewer hallucination flags, then the higher quote resolution rate; otherwise none;
2. every pair where one memo's verdict **blocks the entry** and the other's does not;
3. if fewer than **4**, top up from the remaining judged pairs: non-tie judge preferences first, then the rest, each in ascending `sha256("<comparison_id>|<slug>|calibration")` order.

`review.md` and `ratings_template.json` cover only the sample. They do not show the judge's scores or why a pair was sampled.

### Decision rule v2 (pre-declared 2026-11-10, before any results)

The outcome is **switch** only if every check holds:

1. At least **10 of 12** pairs are complete: both memos and both judge orders valid.
2. The judge's order-consistent preference favours the challenger on at least **8** pairs and the incumbent on at most **3**. On a book-effect disagreement where the owner has a non-tie preference, the owner's pick replaces the judge's.
3. The judge's mean rubric total (out of 15, mean of both orders) for the challenger beats the incumbent's by at least **1.0**.
4. The challenger's quote resolution rate is **at least** the incumbent's (unchanged).
5. The challenger has **no more** hallucination flags than the incumbent (unchanged).
6. On book-effect disagreements, the challenger is preferred at least as often as the incumbent, using the owner's pick where it governs.
7. 35 memos a week at the challenger's cost per memo fit inside `budget.strategy_book_memo_raise` ($40 a week) (unchanged).
8. **Judge calibration holds:** the sample has at least 4 pairs, all rated, and the owner's preference (A, B or tie) equals the judge's on at least `ceil(0.75 × sample)` of them:

| Sample size | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|-------------|---|---|---|---|---|---|----|----|----|
| Agreements needed | 3 | 4 | 5 | 6 | 6 | 7 | 8 | 9 | 9 |

`decision.json` records `judge_trusted: true` when check 8 holds, so a later comparison (for example the queued `grok-4.7` challenger, L701) can reuse a calibrated judge.

**If calibration holds** (`governing: judge`):

- **keep:** at least 10 pairs are complete, and either the judge prefers the incumbent at least as often, or the challenger has more hallucination flags;
- **inconclusive_keep:** anything else.

**If calibration fails** (`governing: owner_sample`), the owner's ratings on the sample decide. The outcome is **switch** only if the owner's preference is overwhelmingly for the challenger: challenger on at least `ceil(0.75 × sample)` sample pairs, incumbent on none, and a mean owner rubric gain of at least 1.0. Checks 1, 4, 5, 6 and 7 must also hold. Otherwise:

- **keep:** at least 10 pairs are complete, and either the owner prefers the incumbent at least as often on the sample, or the challenger has more hallucination flags;
- **inconclusive_keep:** anything else.

`composer-2.5` stays on keep and inconclusive_keep. A switch still needs owner approval and an `operational_switches` row (see [below](#decision-rule-v1-superseded-2026-11-10)).

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
| `judge_status.json` | each judge run: state, attempts per order, spend line, runtime check | no (do not open before rating) |
| `judgements/<slug>/AB.json`, `BA.json` | judge: raw reply, parsed scores, reasons and quotes, prompt SHA-256, quote check | label-blind, but shows the judge's view (do not open before rating) |
| `judge_results.json` | judge, when every pair is judged: per-pair order-consistent preference and mean scores | no (do not open before rating) |
| `calibration.json` | judge: the sample, the reason each pair is in it, agreements needed | no (do not open before rating) |
| `review.md` | judge: the blind side-by-side doc for the calibration sample | yes |
| `ratings_template.json` | judge: the calibration sample | yes |
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

The comparison has its own budget lines, both recorded in the `weekly_ops` pool as each call is made:

- **Memos:** `status.json` → `spend`, capped at **$22.00**. The estimate is 12 names × ($0.40 + $1.04) = **$17.28**.
- **Judge (rule v2):** `judge_status.json` → `spend`, capped at **$28.00**. The estimate is 12 pairs × 2 orders × $0.94 = **$22.56**.
- **Total:** estimated **$39.84**, capped at **$50.00**.

A judge call reads two memos and the files they cite and writes a structured reply, so it is priced like one memo on the judge model. Charged cost per call is stored in `judge_status.json` when the usage record has it.

Before every memo or judge call the run checks two things:

- that stage's cap;
- that `weekly_ops` would keep at least **$22.00** after the call. That is the strategy-book memo job's weekly high estimate (35 × $0.40 = $14) plus the shared $8 minimum headroom.

A headroom stop is retried on a later weekday. A cap stop is final. A failed memo is retried once (two attempts). On 2026-11-10 `weekly_ops` had $112.50 left of $124.50.

## How to run

The workflow is `memo-model-comparison.yml`:

- **Weekday 10:40 UTC schedule:** runs `generate --apply --if-due`, then `judge --apply --if-due`. Each does nothing once its stage is done or capped, so the pair runs once after merge.
- **Run now:** `gh workflow run memo-model-comparison.yml -f action=generate` (memos, then the judge).
- **Judge only:** `gh workflow run memo-model-comparison.yml -f action=judge`.
- **After the owner's calibration ratings:** `gh workflow run memo-model-comparison.yml -f action=decide` writes `decision.json`.

Local drill-down (needs `CURSOR_API_KEY_V2`):

```bash
ftse-memo-model-comparison --repo-root . generate           # dry run: names and budget
ftse-memo-model-comparison --repo-root . generate --apply   # call the models
ftse-memo-model-comparison --repo-root . judge --apply      # judge every pair in both orders
ftse-memo-model-comparison --repo-root . status             # ops findings
ftse-memo-model-comparison --repo-root . decide [--apply]   # after ratings.json
```

## Owner calibration review

Human task `adhoc-memo-model-comparison-blind-review`. When ops shows **Memo model comparison ready for owner calibration**, read `review.md`. It holds only the calibration sample (at least 4 names). For each name, rate memo A and memo B from 1 to 5 on:

- `evidence`: claims tied to the filings, nothing invented;
- `thesis_break`: says concretely what would make it a do-not-own name;
- `verdict_justified`: verdict and confidence match the evidence.

Then set `preferred` to `A`, `B` or `tie`: the memo you would rather the book act on. Copy `ratings_template.json` to `ratings.json`, fill it in and commit it to main. Do not open `blind_key.json`, `results.json`, `judge_results.json`, `calibration.json`, `judgements/`, `judge_status.json` or the `status.json` cost fields first. Then run the decide dispatch.

## Decision rule v1 (superseded 2026-11-10)

Superseded by [rule v2](#decision-rule-v2-pre-declared-2026-11-10-before-any-results) before any memo existed; kept for the record. `decide()` reports; it never switches anything. Under v1 the outcome was **switch** only if every check held:

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

**If the outcome is switch** (either rule), the owner approves the change. It is then logged as an `operational_switches` row on `docs/data/strategy_book_registration.json`, the same way `spend_enabled` was:

```
switch: memo_model, from: composer-2.5, to: grok-4.6, approved_by: owner, owner_quote, evidence: docs/data/memo_model_comparison/decision.json, budget note, review date
```

The memo runner's model then changes in its own PR. This is an operational switch, not a rule change: section 11 says only "uses the existing research runner" and seals no model. The $0.40 memo estimate in section 11 and `ESTIMATED_MEMO_USD` would be restated at the same time.

## Ops-monitor

`check_memo_model_comparison` runs daily after the strategy-book memo check and reads the store only. Every finding is `auto_fixable=false`. No rememo or ingest follows from a finding.

| Title | Severity | When |
|-------|----------|------|
| **Memo model comparison awaiting generation** | info | Manifest frozen at rule v2, generation not finished; gives the dispatch command and the total estimate |
| **Memo model comparison awaiting judge** | info | All pairs generated, judge not finished; gives the judge dispatch command |
| **Memo model comparison failed** | warn | Manifest not rule v2, a model or judge check failed, a memo or judge call errored, sources changed before judging, or a budget stop |
| **Memo model comparison ready for owner calibration** | info | Every pair judged; reports calibration names rated |
| **Memo model comparison owner calibration stale** | warn | Ready more than 14 days without complete calibration ratings |
| **Memo model comparison decided** | info | Calibration ratings complete; reports the rule v2 outcome, `judge_trusted`, which side governed, and failed checks |

See [ops-monitor.md](ops-monitor.md#full-automation-wiring).
