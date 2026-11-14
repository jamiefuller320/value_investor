# Strategy book UK/Europe replay registration, v1 (Companies House shares for the cap)

**Status: DRAFT, not sealed. No v1 development score exists.**  
**registration_id:** `strategy-book-uk-replay-v1`  
**Supersedes, before its reveal:** `strategy-book-uk-replay-v0`, sealed 2026-11-12, document [`strategy-book-uk-replay-registration-draft.md`](strategy-book-uk-replay-registration-draft.md) at sha256 `35c45767b651ae8e850eb4231b07e7a68aa537807656dac54e66c2c9375af233`  
**Parent:** `owner-strategy-book-v0` in [`strategy-book-registration.md`](strategy-book-registration.md), signed 2026-11-05  
**Plan step:** 3.3 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md)  
**Deferred idea:** N273 (survivorship gap: failed names with no EODHD share count)  
**Human checklist:** `adhoc-strategy-uk-replay-v1-seal` in [`human-tasks-checklist.md`](human-tasks-checklist.md#ad-hoc-when-triggered)  
**Seal file:** `docs/data/strategy_book_uk_replay_v1_registration.json` (sha256 of this file, owner stamp)

## What this version is

v1 is v0 with one rule changed: where EODHD has no share count for a session, a FTSE 350 leaver that is matched to the Companies House store takes its share count from Companies House. Every other section of the sealed v0 text applies to v1 word for word, with `strategy-book-uk-replay-v1` in place of `strategy-book-uk-replay-v0`. That includes the question, the universe apart from the share count, the part-by-part reading, prices, costs, windows, family, verdicts, dirty flags, kept fields, probe classes, call budget, and the v0 change markers already logged (fetch date, cache path, fetch resilience, Companies House matching, development date, develop scale, shares dict, leap day, cache to reveal, sector probe, prior year visible). If this file and the v0 text disagree, this file wins for v1.

`strategy-book-uk-replay-v1` is an observe instrument. `influences_live` is false. It writes nothing that v0 did not write. No language model chooses an entry, an exit, or a review.

## Why a new id

v0 section 9 says a change to the universe is a new `registration_id`, not an amendment. The share count decides who is in the FTSE 350 rank, so this is a universe change.

**What was seen before this draft.** The v0 development block was committed on 2026-11-13 (run 43445995250). It is superseded by the v0 marker `prior-year-visible-v1`, and its numbers are public in `docs/data/strategy_book_uk_replay.json`: 203 development episodes, median matched excess +0.46%. The reason for v1 is a coverage diagnostic in that block, not its returns: `mean_cap_not_computable_share` was 0.51, and Carillion, Thomas Cook, Debenhams and Intu have EODHD prices but no EODHD fundamentals or share counts, so they could never be ranked. A survivorship-free tape that cannot rank the failures is not survivorship-free where it matters. Intu is not in the Companies House store: it left the FTSE 350 by demotion before it failed, so it is not on the delisting-leaver list. v1 cannot rank it unless question 5 adds it. The holdout has not been read under any id.

Most of the 0.51 is small and long-dead LSE symbols outside any plausible top 350. Companies House shares only reach the FTSE 350 leavers in the store, so v1 is expected to close the failure gap, not to bring the 0.51 down by much. Section 4 reports both.

## 1. The changed rule: shares

v0 section 2 **Shares** stays the first source. The fallback applies only when it finds no row.

| Step | Rule |
|---|---|
| 1. EODHD | As v0: latest `outstandingShares` row with `dateFormatted` on or before the session and `shares` > 0, quarterly preferred, later date wins. |
| 2. Who can fall back | Only a symbol matched to a Companies House record under the v0 matching rule (same listed company; EPIC and leaving date consistent; marker `ch-matching-v1`). An unmatched symbol stays not computable. |
| 3. Which filing | The latest filing in that record whose share count is visible on the session: Companies House filing date plus the 2-day lag. A filing with no filing date uses period end + 180 days, then 2 days, as v0 does for statements. |
| 4. Stale | Not used when the filing's period end is more than 456 days before the session (`STALE_FILING_DAYS`). The cap is then not computable for that month. |
| 5. Which field | `shares_in_issue` from that filing (ordinary shares in issue at the balance-sheet date). If that filing has none, `weighted_average_basic_shares` from the same filing. No other field. A share count is not derived from profit and EPS. An earlier filing is not used in place of a missing field on the latest one. |
| 6. Splits | As v0: a split dated after the period end and on or before the session scales the count by `new/old`. An unparsed split makes the month not computable. |
| 7. Everything after | Pence, FX, the plausibility band, the month-end carry, and the tie break are v0's. |

A share count nulled by the store's value gate is absent, not zero.

**Store freeze.** `docs/data/ch_failed_name_statements.json` as committed at the commit the v1 development run records, frozen from that run to the reveal. This is the same freeze v0 applied to Companies House statements, extended to the share fields. The replay does not call Companies House.

**Statements.** Unchanged from v0 section 3.1. A leaver that now gets a cap is ranked, and from then on its cheapness and decline reads use the Companies House statement fallback v0 already sealed.

## 2. Pre-seal conditions

The owner seals only when both hold. Neither is a score.

1. The share fields are in the store, merged to `main`, with the extraction hand check in [`ch-failed-name-statements.md`](ch-failed-name-statements.md) at 18 of 20 or better on a fixed seed.
2. Coverage is published: how many matched leavers have a share count for every fiscal year from 2012 to the leaving year, how many have at least one, by leaving kind, and for the four named failures.

## 3. Timetable

The v0 call budget and last call day stand: the last EODHD call day is **2026-12-10**.

| Date | Step |
|---|---|
| When section 2 holds | Owner seals v1. No v1 development before the seal. |
| Next day | v1 development walk on the cached tape, if the encrypted cache is still alive; otherwise one `fetch` first (about 87,000 weighted calls, one UTC day). Commit the v1 development block. |
| After that | Owner reads v1 development and gives the v1 reveal stamp. Target **2026-12-03**, as v0. |
| Reveal | One holdout write under v1, with the delisting sensitivity. |
| By 2026-12-10 | Delete temp files and the cache, as v0. |

**v0 after the v1 seal.** v0 keeps its committed development blocks as a record. The v0 reveal stamp is never given and the v0 holdout is never written. If v1 cannot be sealed in time for a reveal by 2026-12-09, the owner chooses between revealing v0 as sealed and revealing nothing; v1 is not revealed unsealed.

## 4. Added outputs

Development and holdout blocks report, per market and pooled, without tickers:

| Field | Meaning |
|---|---|
| `cap_source_counts` | Month-name rows whose cap came from `eodhd`, `ch_shares_in_issue`, or `ch_weighted_shares`. |
| `mean_cap_not_computable_share` | As v0, under v1's rule. |
| `ch_cap_leavers` | Matched leavers ranked in at least one month through the Companies House fallback. |
| `named_failures_ranked` | For Carillion, Thomas Cook, Debenhams and Intu: whether each was in the rank in any of the 12 month-ends before its last EOD date. A yes or no per name, or `not_in_store` for a name with no Companies House record; these are public events, so naming them leaks nothing. |

These are descriptions. They are not tests and do not enter a verdict.

## 5. Freeze and amendments

v0 section 9 applies to v1. The one pre-score adjustment is available on the v1 seal note, and only for the constants in this file.

## 6. Open questions

Each default is what the seal accepts if the owner signs unchanged.

1. **Second field.** Default: weighted-average basic shares from the same filing when shares in issue is absent. Alternative: shares in issue only.
2. **Stale.** Default: 456 days, as statements. Alternative: 730 days, which ranks a name that stopped filing a year earlier (more failures ranked, staler counts).
3. **Who can fall back.** Default: matched leavers only. There is no other Companies House share source in the repo.
4. **No reveal by 2026-12-09.** Default: the owner chooses at that point between revealing v0 and revealing nothing (section 3).
5. **Failures demoted before they failed.** Default: not added; Intu and any other name that left the FTSE 350 by demotion and later failed has no Companies House record and stays not computable when EODHD has no share count. Alternative: add those names to the Companies House store (same extraction and hand check) before the seal, which widens the extraction and moves the seal later.

## Appendix: constants added or changed

| Constant | Value | Status |
|---|---|---|
| `registration_id` | `strategy-book-uk-replay-v1` | New id |
| `supersedes_registration_id` | `strategy-book-uk-replay-v0` | New |
| `CH_SHARES_FALLBACK` | true | Proposed |
| `CH_SHARES_FIELDS` | `shares_in_issue`, then `weighted_average_basic_shares`, same filing | Proposed |
| `CH_SHARES_STALE_DAYS` | 456 | Proposed, equals `STALE_FILING_DAYS` |
| `CH_SHARES_LAG_DAYS` | 2 | Proposed, equals the v0 filing lag |

Every other constant is the v0 appendix value.
