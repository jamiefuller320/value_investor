# Strategy book demo mirror

Observe-only copy of the strategy book's **primary** orders onto a Trading 212
**practice** account, plus a raw-price ledger. Plan step 5.1. Learning
question: when those orders are real orders sent just before the fill
session's close, how do the fills (price, time, fill rate, partials,
rejections) differ from the book's assumed close fills and assumed spread,
and does the raw-price ledger reconcile to the demo statement?

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
| A primary episode with this signal is already `open` or `closed` | `already_open` (the entry catch-up handles it, see [Catch-ups](#catch-ups)) |
| Planning time is after that fill session's registered cash close | `missed_fill_session` |
| The near-close send window for the fill session has passed, but the close has not | `missed_send_window` |
| Stake currency and instrument currency have no rule below | `currency_mismatch` |
| Practice-account currency (known only when a key is present) is missing | `account_currency_missing` (`insufficient_data`) |
| Exit, but the ledger holds no shares from our entry fill | `no_demo_position` |
| Instrument no longer in the catalogue, or a held name vanishes from positions with no sell and no corporate-action quantity | `delisted` (event only; no invented cash) |

The overlay is `docs/data/library/t212_coverage/by_market/{market}.json`, the
same catalogue hit the book uses. The mirror does not call the live catalogue
key.

An open primary episode the demo account does not hold is bought by an entry
catch-up, and demo shares the book never filled are sold by an unwind (see
[Catch-ups](#catch-ups)). A `would_place` row that is still unsent when its
fill session closes becomes `missed_fill_session` on the next run.

## Order timing

The book signals on a session close and assumes a **market buy** filled at
the **next** session's close (`fill_session`, registration section 3). The
public API has limit, market, stop and stop-limit orders. It has no
closing-auction order. So the mirror sends shortly before the close instead
(owner, 2026-11-16).

**Send window.** An order is sent only from 40 to 3 minutes before its
session's registered cash close (`session_close` in `strategy_book_rules`;
`send_window` returns `early`, `open` or `closed`). Before the window the
plan row is `waiting` with `wait_reason` `before_send_window` and nothing is
sent. A planned entry or exit whose window has passed before the close is
`not_mirrored` / `missed_send_window`.

The near-close job runs Monday to Friday at these UTC times. Each local close
has at least one slot 15 to 40 minutes before it in both summer and winter:

| UTC | Closes covered |
|---|---|
| 04:40, 05:40 | ASX 16:00 Sydney |
| 15:10, 16:10 | London 16:30, the continent 17:30 CET, Dublin and Lisbon 16:30 local |
| 19:40, 20:40 | New York 16:00 and Toronto 16:00 |

Hong Kong and Singapore have no slot because they have no Trading 212
listing. The forward job (17:45 and 21:30 UTC) still plans, syncs, cancels
and reconciles. It sends only when a row's window happens to be open at that
moment.

**Order we send:** a capped market order, sent as a limit through the signal
close. A buy limit is the signal session's chart close × 1.03; a sell limit
is that close × 0.97, rounded to 0.01 in the instrument's Trading 212
currency. `timeValidity` is `GOOD_TILL_CANCEL`. Quantity is still the stake
divided by the signal close, so the 3% band is not spent on extra shares.

- Buy (entry): positive quantity. Fills at the best price up to the cap.
- Sell (exit): negative quantity. Fills at the best price down to the floor.
- `extendedHours` is left unset, so the order is regular hours only.

The order row keeps `signal_close`, `limit_band`, `sizing_close`,
`send_session` and `instrument_currency`. The plan's `price_basis` is
`signal_session_chart_close_through_band_as_instrument_currency`.

After the fill session's close the mirror cancels any remainder, as before.
An entry that missed its session is bought by an entry catch-up on the next
near-close run, and an exit that missed is sold the same way. See
[Catch-ups](#catch-ups).

**Trade-off.** The band order fills at the market price in the last minutes,
not the closing auction print. Price slippage against the book's close is
the measurement. A move of more than 3% from the signal close before the
send still leaves the order unfilled; the catch-up then buys or sells at
market on the next session, with `sessions_late` recorded.

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
| same (USD/USD, EUR/EUR, GBP/GBP) | | `stake / signal close`, floored to 4 decimal places |
| GBP | GBX | `stake × 100 / signal close`, floored to 4 decimal places |

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
| `orders` | Broker order rows. Keyed by `client_order_ref` = `sbdemo:{episode_id}:{entry\|exit\|entry_catchup\|exit_catchup}`. |
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

Hard cap: **20** new orders per run (`ORDER_CAP`). Order of sending: exit
catch-ups, exits, entry catch-ups, entries. The rest are `capped` and are not sent. The cap is not configurable
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

On-time and catch-up slippage are stored and reported separately for entries
and exits. Exits use the book's `exit_fill` and entry catch-ups use the
book's entry price. The slippage finding states the on-time entry and exit
medians and the catch-up count.

`execution` (in the store and its `summary`) counts on-time entries whose
fill session has closed: `entries_due`, `entries_filled`, `entries_missed`,
`entries_rejected` and `entry_fill_rate`. `missed_book_move_median_pct` is
the book's entry price over the missed limit, minus one: how far the price
ran past the order. It also counts `entry_catchups_sent` and
`exit_catchups_sent`.

## Catch-ups

The demo account has to hold what the book holds. A catch-up is a market
order sent on a later near-close run when the demo account and the book
disagree. It is `POST /api/v0/equity/orders/market`, with no limit price and
no `timeValidity`, and `extendedHours` left unset. It is sent only inside
the send window for that market on that day, so it fills in the last minutes
of a session, not at the next open. A 400 does not create an order.

| Leg | Client reference | When | Reason |
|---|---|---|---|
| Entry catch-up (buy) | `sbdemo:{episode_id}:entry_catchup` | Open primary episode, no `pending_exit`, and the mirror never sent an entry and holds nothing | `missed_entry_order` |
| | | The entry was cancelled or rejected, or only partly filled and the remainder cancelled | `unfilled_entry` |
| Exit catch-up (sell) | `sbdemo:{episode_id}:exit_catchup` | The exit limit was cancelled, rejected or partly filled and shares are still held | `unfilled_exit` |
| | | The book episode is `closed` and the mirror never had an exit order | `missed_exit_order` |
| | | Demo shares exist for a primary signal the book never filled (`memo_not_ready`, `memo_blocked`, `late_signal`, `gap_drop` or `no_next_bar`) | `book_not_filled` |

Entry catch-up quantity is the entry order's quantity minus shares already
held, or, with no entry order, the stake divided by the latest stored chart
close (`sizing_close`). Exit catch-up quantity is all shares the ledger
holds for that episode.

The same run that cancels a limit does not also send the catch-up. A
catch-up uses the same submitting checkpoint as a limit and counts toward
the 20-order cap. `sessions_late` is the number of weekdays after the book's
fill session up to the send day. The fill is tagged `timing: catchup` and
reported apart from the on-time medians.

A rejected catch-up, or one whose result is unknown, is retried on the next
due run. Before an unknown result is retried, a single matching pending
order or a single later fill is adopted so a queued or filled order is not
sent twice. After 5 attempts the row is `stuck` and is not sent again.
Ops-monitor warns **Strategy book demo position stuck**. A catch-up that has
been `waiting` (stamped `waiting_since`) through a full weekday of slots
warns **Strategy book demo catch-up waiting** (the near-close job may not be
firing). Neither finding places,
cancels or repairs anything.

Known edge: a limit that fills between the statement read and the
post-close cancel can make the next entry catch-up overbuy. The
reconciliation then shows a quantity mismatch, and the next exit sells
everything the ledger holds.

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

`strategy-book-demo-near-close.yml` runs
`ftse-strategy-book-demo --apply --place --only-if-due` at the near-close
slots. cron-job.org is the primary trigger (`strategy-book-demo-near-close-10`
for 15:10 and 16:10 UTC, `strategy-book-demo-near-close-40` for 04:40, 05:40,
19:40 and 20:40 UTC, imported by `import-ingest-crons.yml`); the workflow's
own schedule is a backup. `--only-if-due` returns before any API call or
write when no row is due, so idle slots commit nothing. Without the demo
secrets the step prints that nothing was sent and exits 0.

Both workflows share the concurrency group `strategy-book-forward`, so only
one writes the ledger at a time. The ledger is on the forward workflow's
`GHA_COMMIT_OWNED` list and on email-report's exclude list; the near-close
workflow commits only the ledger.

Ops-monitor `check_strategy_book_demo_mirror` reads the ledger and does not
place orders. All findings are `auto_fixable` false:

| Title | Severity | When |
|---|---|---|
| Strategy book demo mirror not configured | info | Ledger missing, or the last run had no demo credentials |
| Strategy book demo orders placed | info | The last run sent at least one order |
| Strategy book demo reconciliation mismatch | warn | Reconciliation status is `mismatch`, or the ledger is unreadable |
| Strategy book demo slippage | info | At least one fill has measured slippage; reports on-time entry and exit medians, catch-ups, the on-time entry fill rate, the median move past missed entries, and the median FX conversion fee |
| Strategy book demo position stuck | warn | A catch-up is still unfilled after 5 attempts |
| Strategy book demo catch-up waiting | warn | A catch-up has been `waiting` through a full weekday of near-close slots without a send |
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
  holiday calendar is queued behind this step.
- The 3% band and the 40-to-3-minute send window (owner, 2026-11-16). Widen
  the band only if missed on-time entries keep showing a median move past the
  order above 3%.
