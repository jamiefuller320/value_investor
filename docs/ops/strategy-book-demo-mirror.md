# Strategy book demo mirror

Observe-only copy of the strategy book's **primary** orders onto a Trading 212
**practice** account, plus a raw-price ledger. Plan step 5.1. Learning
question: when those orders are real limit orders, how do the fills (price,
time, fill rate, partials, rejections) differ from the book's assumed close
fills and assumed spread, and does the raw-price ledger reconcile to the demo
statement?

The book keeps scoring on adjusted closes. This ledger does not feed the book,
its scores, the registration, or any knob. `influences_live` is false.

Registration (read, not edited): [strategy-book-registration.md](strategy-book-registration.md)
sections 3 (entry and fill), 4 (exit), 6 (limits), 7 (costs) and 8 (scoring).
Plan: [strategy-reorientation-plan.md](strategy-reorientation-plan.md) step 5.1
and principle 6 (execution starts early). Phase 3 step 3.2 uses these fills as
the paper implementation check. Ops row: [ops-monitor.md](ops-monitor.md).

## What is mirrored

Each run reads `docs/data/strategy_book_observe.json` and writes
`docs/data/strategy_book_demo_ledger.json`.

A row is a candidate when it is one of:

- an observe **event** with `kind` `pending_fill` (the forward walker records
  the signal here; the episode does not exist until the next close fills it)
- an episode whose `status` is `pending_fill`, if a later walker writes one
- an **open** episode with `pending_exit` set (exit signalled, sale not filled)

Only the **primary** column is sent. Comparison, control, bench and shadow
columns are stored as `not_mirrored` / `not_primary`.

A primary row is sent only when all of the following are true. Anything else
is `not_mirrored` or `insufficient_data`, and no price or quantity is invented:

| Gate | Reason |
|---|---|
| Book `t212_listed` is false, or the overlay is not a `catalogue_hit` | `not_listed` |
| Book `t212_listed` is `unknown`, or the overlay `updated_at` is missing or older than 35 days on the signal date | `t212_unknown` |
| Catalogue hit but no Trading 212 ticker | `unmapped_instrument` |
| Signal-session chart close missing | `insufficient_data` (`no_signal_close` or `no_chart`) |
| Chart has not reached the signal session | `stale_quote` |
| A primary episode with this signal is already `open` or `closed` | `already_open` (no backfill) |
| Planning time is after that fill session's registered cash close | `missed_fill_session` |
| Stake currency and instrument currency have no rule below | `currency_mismatch` |
| Practice-account currency (known only when a key is present) is missing | `account_currency_missing` (`insufficient_data`) |
| Exit, but the ledger holds no shares from our entry fill | `no_demo_position` |
| Instrument no longer in the catalogue, or a held name vanishes from positions with no sell and no corporate-action quantity | `delisted` (event only; no invented cash) |

The overlay is `docs/data/library/t212_coverage/by_market/{market}.json`, the
same catalogue hit the book uses. The mirror does not call the live catalogue
key.

Already-open primary episodes are not backfilled. The mirror starts from
signals that are still pending. A `would_place` row that is still unsent when
its fill session closes becomes `missed_fill_session` on the next run.

## Order timing

The book signals on a session close and assumes a fill at the **next**
session's close (`fill_session`). The forward job runs at 17:45 UTC (after
London and the continent) and 21:30 UTC (after New York and Toronto), which is
**after** the signal session and **before** the next session's close.

The public API has limit, market, stop and stop-limit orders. It has no
closing-auction order. A market order sent at 17:45 would rest until the next
open and fill at the open, not the close.

**Order we send:** limit, `timeValidity` `GOOD_TILL_CANCEL`, price = the
signal session's chart close, in the instrument's Trading 212 currency.

- Buy (entry): positive quantity. Fills at the limit or lower.
- Sell (exit): negative quantity. Limit is the exit-signal session's close.
  Fills at the limit or higher.
- `extendedHours` is left unset, so the order is regular hours only.

`DAY` is not used. A DAY order expires at midnight in the exchange zone. Placed
after the London close, it can die before the next session opens. GTC stays
live through the next session, including the close.

The expected fill session is the next weekday after the signal. The order must
be placed while `now` is still at or before that session's registered cash
close (`session_close` in `strategy_book_rules`). After that close the mirror
cancels any remainder. An entry that missed the session is not chased: the
book does not fill a later bar. An exit that missed the session is chased,
because the demo account has to get flat. See [Exit catch-up](#exit-catch-up).

**Trade-off.** The limit can fill at the open or at any print through the
session, not only at the close. A gap the wrong way (buy: close above the
signal close) never fills, while the book still assumes a fill at that close.
Both results are the measurement: fill time, fill price, and misses. A job
that sends the order a few minutes before the cash close would track the
close more tightly. That is queued ("Send strategy-book demo limits shortly
before the fill-session close"), not built: this step's trigger is the
existing forward workflow.

**Holiday.** The next weekday is not an exchange holiday calendar. A bank
holiday can be treated as the fill session and the remainder cancelled that
evening. That case is queued ("Use an exchange holiday calendar for the
strategy-book demo fill window").

## Quantity and currency

Stake is the book's fixed 100 units of the market's listing currency
(`STAKE_UNITS`, `costs_for_market`). Episode percent does not use the stake.
The broker order does.

| Stake currency | Instrument currency | Shares |
|---|---|---|
| same (USD/USD, EUR/EUR, GBP/GBP) | | `stake / limit`, floored to 4 decimal places |
| GBP | GBX | `stake × 100 / limit`, floored to 4 decimal places |

London chart files are labelled `GBP`, but the stored closes are pence, the
same unit as Trading 212 `GBX` (4imprint around 4066, ME Group around 103).
The limit is that chart number. It is not divided or multiplied by 100. A
100× unit guess would either never trade or buy about 100× too much. If the
units ever diverge, the order is wrong in a way this job will not silently
"fix".

Trading 212 accepts fractional quantity (their limit-order example is `0.1`).
We send the floored fraction so the cash outlay stays at or under the stake.
A zero after flooring is `quantity_below_minimum`. Trading 212 limits the
decimals per instrument and answers too many with
`/api-errors/quantity-precision-mismatch` ("invalid quantity precision 3" for
4imprint on 2026-11-11). The mirror floors to that many decimals and sends
once more in the same run. The row keeps `quantity_requested`,
`precision_retried` and `precision_detail`. A row rejected for precision before
this retry existed is sent once more while its fill window is open. Any
other rejection is final for that reference (whole-share resizing is queued
as "Resize a rejected strategy-book demo order to whole shares"). A dashboard
strip for the measured slippage is queued as "Show strategy-book demo slippage
on the observe dashboard". The assumed half-spread is not replaced. The
deferred idea "Mirror paper fills onto T212 demo account for measured
execution" stays open.

The account-summary currency is checked only when a demo key is present and
placement is on. The API documents that orders execute only in the account's
primary currency and that multi-currency wallets are not supported: the cash
side of every order is the account currency, and Trading 212 converts a
foreign-currency instrument at its own rate. So a GBP practice account sends
US and euro primary entries too (owner, 2026-11-11). Before that, only GBX
names were sent, and US entries such as CRM and FIS had no measured
execution. The order is still sized and priced in the instrument currency
(100 USD of a US name at the signal close in dollars), so price slippage is in
the instrument currency. The plan and order rows carry `fx_conversion` and
`account_currency`. GBP to GBX is not a conversion.

The fill keeps `fx_rate` (`walletImpact.fxRate`), `fx_fee` (the
`CURRENCY_CONVERSION` rows of `walletImpact.taxes`) and `fx_fee_pct` (fee over
the absolute cash impact). The conversion fee is reported apart from price
slippage (`fx_fee_count`, `fx_fee_median_pct`) and does not replace the book's
assumed half-spread. If Trading 212 rejects a converted order, the rejection
is final for that reference like any other, and ops-monitor warns
**Strategy book demo FX order rejected** with the broker's detail.

## Stale quote, delisting, partial, rejection, cancel

There is no pre-trade quote endpoint on the metadata API. "Stale quote" means
the chart does not yet contain the signal session's close. We do not fetch a
live quote and we do not invent one.

| Broker result | Ledger |
|---|---|
| `PARTIALLY_FILLED` | One fill per history `fill.id`. Remainder stays working until the fill session closes, then `DELETE /api/v0/equity/orders/{id}` cancels it. Slippage uses the filled quantity only. |
| `REJECTED`, or HTTP 400 | `rejected`. The same client reference is not sent again, except one floored resend after a quantity-precision rejection. |
| `CANCELLED`, or our post-close cancel | `cancelled`. No fill is invented. A partial keeps the shares already filled. An exit remainder is then flattened by a market catch-up on the next run. |
| HTTP 401 / 403 | Stop the run. The row is `auth_blocked` and may be tried on a later run (the order was not accepted). |
| HTTP 429 | The request was refused before it ran. The transport waits for `x-ratelimit-reset` (5 s when absent, at most 30 s) and retries up to 3 times. Still refused: `rate_limited`, plan `would_place` with reason `rate_limited`, sent again on the next run. |
| Network error, HTTP 408 or 5xx | `submit_unknown`, with the error text in `detail`. See the unknown-result rule below. |
| Position disappears with no sell and no corporate-action quantity | `delisting` event. Quantity is not zeroed and no cash value is invented, so reconciliation stays a mismatch until a real event explains it. |

History fill types other than `TRADE` (`STOCK_SPLIT`, `SPIN_OFF`, and the
other types on `GET /api/v0/equity/history/orders`) are corporate-action
events. `STOCK_SPLIT` is stored as `split`.

## Raw-price ledger

One store, `docs/data/strategy_book_demo_ledger.json`. `schema_version` 1.
`influences_live` false. `base_url` is `https://demo.trading212.com`.

| Array | Contents |
|---|---|
| `plans` | One row per candidate this run. Includes `observe_data_commit`, `planned_at`, action, reason, limit, quantity, side, currencies, `client_order_ref`. |
| `orders` | Broker order rows. Keyed by `client_order_ref` = `sbdemo:{episode_id}:{entry\|exit}`. |
| `fills` | Trade fills with raw price, quantity, time, wallet impact, taxes, FX rate and conversion fee for converted fills, and slippage versus the book's adjusted close. |
| `ledger` | Raw-price events: `fill`, `dividend`, `split`, `corporate_action`, `transaction`, `delisting`. |
| `reconciliation` | `match`, `mismatch`, `insufficient_data`, or `skipped`. |

Dividend events use `GET /api/v0/equity/history/dividends`: cash `amount` in
the account currency, `paidOn` as the pay date, `grossAmountPerShare` in the
instrument currency. No pay date or reference means the cash is not invented;
reconciliation is `insufficient_data`.

Transactions (`WITHDRAW`, `DEPOSIT`, `FEE`, `TRANSFER`, and the other types on
`GET /api/v0/equity/history/transactions`) are copied with the broker amount
and currency.

Client references are local. The beta limit endpoint is **not idempotent**:
the same POST can create two orders. The mirror writes `submitting` to the
ledger **before** the POST. A later run will not POST that reference again.
If the POST's result is unknown, the row becomes `submit_unknown`. The next
run settles it only when both `GET /api/v0/equity/orders` and the order
history read cleanly:

- exactly one pending order matching ticker, side, limit and quantity is
  adopted (`placed`);
- otherwise exactly one later fill matching ticker, side and quantity is
  adopted (`filled`);
- otherwise, if no history row for that ticker and side is newer than the
  send, the row becomes `not_placed` (the original error moves to
  `unknown_detail`) and the reference is sent again while its fill window is
  open;
- any other history row for that ticker and side leaves it `submit_unknown`.

Calls are paced per endpoint at the published limits plus 0.25 s: 5 s for
the account summary and the pending-order list, 2 s for limit orders, 1.2 s
for market orders, 3 s for each history list, and 1 s for positions and
cancels. The lock holds only after this
workflow commits the ledger. The mirror step exits 0 once a `submitting` row
exists so that commit still runs. It exits 1 only when the resolved host is
not the demo host, and that check happens before any POST.

Hard cap: **20** new orders per run (`ORDER_CAP`). Exits are sent before
entries. The rest are `capped` and are not sent. The cap is not configurable
upward.

## Slippage

For a fill whose episode is already `open` or `closed`:

- Entry assumed price: `return_entry_fill`, else `entry_fill_first_seen`
  (the book's adjusted close).
- Exit assumed price: `exit_fill` once the episode is closed.
- Buy slippage percent: `raw_fill / book_close − 1` (positive means we paid more).
- Sell slippage percent: `1 − raw_fill / book_close` (positive means we sold for less).
- `vs_half_spread` is that percent minus the market's assumed half-spread
  (`costs_for_market`, 0.025% on FTSE 350). Stamp and FX stay in the fill's
  tax lines; they are not folded into this percent.

Until the book has recorded the fill close, slippage is `insufficient_data`.
Nothing here writes the half-spread back into the book. That replacement is
the rest of step 5.1's "done when" and waits on measured fills.

On-time exit slippage and catch-up exit slippage are stored and reported
separately. Both use the book's `exit_fill` (the adjusted close). The
slippage finding states the on-time exit count and the catch-up count.

## Exit catch-up

The demo account has to track the book's holdings. An entry that does not
fill is cancelled and left alone: the book never fills that name on a later
bar, so a later buy would be a position the book does not have. An exit is
the opposite. Once the book has sold, demo shares that are still held are a
position the book does not have. Leaving them makes every later
reconciliation fail, and the gap never closes.

When an exit limit is cancelled, rejected, or only partly filled after its
fill session, and the ledger still holds shares for that episode, the **next**
run sends a market sell for the remaining shares. The same run that cancels
the limit does not also send the market order. The client reference is
`sbdemo:{episode_id}:exit_catchup`. It uses the same submitting checkpoint as
a limit, it counts toward the 20-order cap, and catch-up sells are sent
before limit exits, which are sent before entries.

The same market sell is sent when the book episode is already `closed` and
the mirror never had an exit order (the signal was gone by planning time).
That row's reason is `missed_exit_order`. A cancelled or partial limit uses
reason `unfilled_exit`.

The order is `POST /api/v0/equity/orders/market` with a negative quantity.
`extendedHours` is left unset. There is no limit price and no `timeValidity`.
The published API queues a market order placed while the market is closed
until the next open. A 400 does not create an order.

`sessions_late` is the number of weekdays after the book's exit session, up
to the day the catch-up is sent. The same evening is 0. The fill is tagged
`timing: catchup` and its slippage is against `exit_fill`, not mixed into
the on-time exit median.

A rejected catch-up, or one whose result is unknown, is retried on the next
run. Before an unknown result is retried, a single matching pending order or
a single later sell fill is adopted so a queued or filled sell is not sent
twice. After 5 attempts the row is `stuck` and is not sent again. Ops-monitor
warns **Strategy book demo position stuck**. That finding does not place,
cancel, or repair anything.

## Reconciliation

When placement runs, the job reads positions, pending orders, historical
orders, dividends and transactions.

- Share quantity by instrument: ledger fills (buy plus, sell minus) plus
  split / corporate-action quantities, versus `GET /api/v0/equity/positions`.
- Each history fill id, dividend reference and transaction reference on our
  names must appear in the ledger with the same quantity, price or cash.
- Cash by currency: sum of ledger wallet nets, dividend amounts and
  transaction amounts, versus the same figures on the statement.

`match` means no difference. `mismatch` is the ops warn. Dry-run (no demo
key) stores `skipped` and does not call the API. Missing broker fields are
`insufficient_data`, not a guessed match. A history order with no fill block
and a status that is not filled (a cancelled or rejected limit) is not a fill
and is skipped; a filled order without a `fill.id` is still a gap.

## Safety

- Order HTTP goes to `https://demo.trading212.com` only. Any other host,
  including `https://live.trading212.com`, raises before a socket is opened.
  Redirects are refused.
- Credentials are read only from `TRADING212_DEMO_API_KEY` and
  `TRADING212_DEMO_API_SECRET`. The catalogue key
  (`TRADING212_API_KEY` / `TRADING212_API_SECRET`, live) is not read.
- The catalogue client (`t212_client.py`) is unchanged and still does not
  place orders.
- No key, or `--place` without `--apply`: plan rows with action `would_place`.
  Nothing is sent. Placement without `--apply` is refused so a send cannot
  happen before the `submitting` row is on disk.
- No model calls.

## Automation

`strategy-book-forward.yml` runs `ftse-strategy-book-demo` after the forward
walk. With both demo secrets and a real (not workflow dry-run) walk, it passes
`--apply --place`. With either secret missing, it plans only and exits 0.
The ledger is on that workflow's `GHA_COMMIT_OWNED` list and on email-report's
exclude list, so this workflow is the only writer.

Ops-monitor `check_strategy_book_demo_mirror` reads the ledger and does not
place orders. All findings are `auto_fixable` false:

| Title | Severity | When |
|---|---|---|
| Strategy book demo mirror not configured | info | Ledger missing, or the last run had no demo credentials |
| Strategy book demo orders placed | info | The last run sent at least one order |
| Strategy book demo reconciliation mismatch | warn | Reconciliation status is `mismatch`, or the ledger is unreadable |
| Strategy book demo slippage | info | At least one fill has measured slippage; also reports the median FX conversion fee |
| Strategy book demo position stuck | warn | A market exit catch-up is still held after 5 attempts |
| Strategy book demo FX order rejected | warn | Trading 212 rejected an order that converts from the account currency |

## Owner setup

Create an API key on a Trading 212 **practice** account (not the live
catalogue key) with orders and portfolio scopes. Add GitHub Actions secrets
`TRADING212_DEMO_API_KEY` and `TRADING212_DEMO_API_SECRET`. Human task
`adhoc-t212-demo-mirror-secrets`.

CLI, for a drill-down only:

```bash
ftse-strategy-book-demo --repo-root .
ftse-strategy-book-demo --repo-root . --apply --place
```

## Owner decisions still open

- Confirm the practice account's currency. The current book is London-first;
  GBX orders assume a GBP practice account.
- Confirm the limit unit on the first two names: chart closes 4066 (FOUR.L)
  and 103.4 (MEGP.L) are sent as GBX because that is the pence scale in the
  chart file and on the overlay.
- The cap of 20 and the next-weekday fill window are safety choices. A
  holiday calendar and a pre-close send are queued behind this step.
