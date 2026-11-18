# Trading 212 catalogue refresh (L665)

The offline library uses a committed snapshot of which instruments Trading 212
lists as tradable. That snapshot powers `t212_coverage` overlays (ISIN / shortName
joins with venue allowlist fallback). It must stay fresh enough that overlay hits
remain trustworthy.

## Schedule

| Trigger | When |
|---------|------|
| GitHub schedule | Monday **05:00 UTC** (`.github/workflows/t212-catalogue-refresh.yml`) |
| Manual | `workflow_dispatch` on the same workflow |

## Secrets and environment

| Secret / env | Purpose |
|--------------|---------|
| `TRADING212_API_KEY` | API key (repo secret) |
| `TRADING212_API_SECRET` | API secret (repo secret) |
| `TRADING212_ENV=live` | Set in the workflow job; catalogue scope needs **live** |

If either API secret is missing, the workflow **soft-skips** with a clear log line
and exits **0** (no failure email). Ops-monitor still warns via
`check_t212_catalogue_freshness` until a successful refresh lands in git.

## What the workflow runs

Uses existing CLI — no duplicated fetch logic:

1. `ftse-library t212-catalogue --env live --root docs/data/library` — read-only
   `GET /api/v0/equity/metadata/instruments` (+ exchanges when available).
2. `ftse-library t212-overlay --root docs/data/library` — rebuild per-market overlays,
   for every library market and the live FTSE 350 (tickers and names from the
   latest `docs/data/history/run_*.json.gz` screen).

Never calls order or account-trading endpoints.

## What counts as a catalogue hit

A Yahoo ticker is a `catalogue_hit` (listed) when one of these holds:

1. **ISIN.** Our ISIN equals the instrument's, on any Trading 212 venue. It is the same share.
2. **Short name on the ticker's own venue.** The venue comes from the Trading 212 ticker:
   `AAPL_US_EQ` is the US, and a lowercase marker after the symbol names a European line
   (`VODl_EQ` London, `BAYNd_EQ` Xetra, `ABNa_EQ` Amsterdam, `BNp_EQ` Paris).
3. **Short name on another venue,** only when the instrument's ISIN is registered in the
   ticker's home country **and** the company names agree. That keeps Eni (Brussels line),
   Bank of Ireland (London) and BHP (London) while refusing namesakes: `CSL.AX` is not
   Carlisle Companies, `T.TO` is not AT&T, `ALL.AX` is not the Australian-registered
   Atlantic Lithium in London.
4. **Company name,** when the symbols differ. Legal and share-class words are ignored.
   An exact name matches (`Enel` on Xetra is `ENL`, not `ENEL`). One longer catalogue
   name matches only when every extra word is a generic modifier (`Nordea` / `Nordea Bank`)
   and no second catalogue name qualifies. A different brand does not
   (`The Lottery Corporation` is not `Brightstar Lottery`). The joined line's ISIN must be
   from the ticker's home country, so a same name incorporated elsewhere is refused
   (`EQT.ST` is not EQT Corp, `SEB-A.ST` is not Groupe SEB). A repeated venue letter is a
   second line on that venue (`STMpp_EQ` is Paris).

A short-name hit on a foreign venue without that confirmation is not a hit. The ticker falls
through to the venue allowlist (`exchange_allowlist`, assumed), which the strategy book does
not count as listed.

The stock catalogue has no HKD, AUD, or SGD line, and only a token Milan line. A Hong Kong,
Australian, Singapore, or Milan constituent is listed when its company name matches a stock
on another venue. Legal words are ignored. One longer name matches only when every extra
word is a generic modifier and no second catalogue name qualifies. `HSBC Holdings` matches
`HSBC`, and `Alibaba Group` matches `Alibaba`. `APA Group` does not match APA Corporation,
and `The Lottery Corporation` does not match Brightstar Lottery. Other Yahoo markets still
need a home-country ISIN before a foreign short name counts, so `EQT.ST` is not EQT Corp.

Committed paths (only when changed):

- `docs/data/library/t212_coverage/catalogue/**`
- `docs/data/library/t212_coverage/by_market/**`
- `docs/data/library/t212_coverage/summary.json`

## Local drill-down

```bash
export TRADING212_API_KEY=… TRADING212_API_SECRET=… TRADING212_ENV=live
ftse-library t212-catalogue --env live
ftse-library t212-overlay
```

## Ops-monitor staleness

Daily `collect_ops_findings` calls `check_t212_catalogue_freshness`:

| Condition | Severity | Title |
|-----------|----------|-------|
| `fetched_at.json` age ≤ **14 days** | `info` | Trading 212 catalogue fresh |
| Missing / unreadable meta or age **> 14 days** | `warn` | Trading 212 catalogue stale |

`auto_fixable=False` — human adds secrets or dispatches the workflow; no ingest/rememo
spray from the finding alone. Listed in [ops-monitor.md](ops-monitor.md).

Human step when refresh never ran: add **`TRADING212_API_KEY`** and
**`TRADING212_API_SECRET`** to repo secrets, then dispatch the workflow or wait for
the Monday slot.
