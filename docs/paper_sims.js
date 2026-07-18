/* Parallel cash-backed paper funds (browser-local). */

const PAPER_FUND_STORAGE_KEY = "ftseValueInvestor.paperFunds.v1";
const PAPER_AUTO_SETTINGS_KEY = "ftseValueInvestor.paperAutoSettings.v1";
const PAPER_STRATEGY_LABELS = {
  manual: "Immediate buy/sell",
  technical: "Follow technical cues",
  automated: "Automated stock picking",
};

function paperFundId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `fund-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadPaperAutoSettings() {
  try {
    const raw = localStorage.getItem(PAPER_AUTO_SETTINGS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return {
      independent: Boolean(parsed.independent),
      settle_minutes_after_open: Number(parsed.settle_minutes_after_open ?? 75),
      market_open: parsed.market_open || "08:00",
      last_auto_run_day: parsed.last_auto_run_day || null,
    };
  } catch {
    return {
      independent: false,
      settle_minutes_after_open: 75,
      market_open: "08:00",
      last_auto_run_day: null,
    };
  }
}

function savePaperAutoSettings(settings) {
  localStorage.setItem(PAPER_AUTO_SETTINGS_KEY, JSON.stringify(settings));
}

function londonParts(dateObj = new Date()) {
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const parts = Object.fromEntries(fmt.formatToParts(dateObj).map((p) => [p.type, p.value]));
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    weekday: parts.weekday,
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    dayKey: `${parts.year}-${parts.month}-${parts.day}`,
  };
}

function browserSessionGate(settings, now = new Date()) {
  const local = londonParts(now);
  const weekdayOk = !["Sat", "Sun"].includes(local.weekday);
  const [openH, openM] = String(settings.market_open || "08:00")
    .split(":")
    .map((n) => Number(n));
  const settleMins = Number(settings.settle_minutes_after_open || 75);
  const openTotal = openH * 60 + openM;
  const settleTotal = openTotal + settleMins;
  const nowTotal = local.hour * 60 + local.minute;
  const afterSettle = weekdayOk && nowTotal >= settleTotal;
  let reason = "ok";
  if (!settings.independent) reason = "independent auto disabled";
  else if (!weekdayOk) reason = "non-trading day";
  else if (nowTotal < openTotal) reason = "before market open";
  else if (!afterSettle) {
    reason = `waiting for open settle (${settleMins} min after ${settings.market_open} Europe/London)`;
  }
  return {
    dayKey: local.dayKey,
    can_act: Boolean(settings.independent && weekdayOk && afterSettle),
    after_settle: afterSettle,
    reason,
    local_label: `${local.dayKey} ${String(local.hour).padStart(2, "0")}:${String(local.minute).padStart(2, "0")} Europe/London`,
  };
}

function paperNowIso() {
  return new Date().toISOString();
}

function paperParseDate(value) {
  if (!value) return new Date();
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? new Date() : d;
}

function paperMonthIndex(dateObj) {
  return dateObj.getUTCFullYear() * 12 + (dateObj.getUTCMonth() + 1);
}

function loadPaperBook() {
  try {
    const raw = localStorage.getItem(PAPER_FUND_STORAGE_KEY);
    if (!raw) return { version: 1, active_fund_id: null, funds: [] };
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.funds)) {
      return { version: 1, active_fund_id: null, funds: [] };
    }
    return parsed;
  } catch {
    return { version: 1, active_fund_id: null, funds: [] };
  }
}

function savePaperBook(book) {
  localStorage.setItem(PAPER_FUND_STORAGE_KEY, JSON.stringify(book));
}

function createEmptyFund({ name, mode, initialCash, monthlyDeposit, tradeCostPct, maxPositions, createdAt }) {
  const when = createdAt || paperNowIso();
  const id = paperFundId();
  return {
    config: {
      id,
      name,
      mode,
      initial_cash: Number(initialCash),
      monthly_deposit: Number(monthlyDeposit) || 0,
      trade_cost_pct: Number(tradeCostPct) || 0,
      max_positions: Number(maxPositions) || 5,
      created_at: when,
    },
    cash: Number(initialCash),
    contributed_capital: Number(initialCash),
    deposits_applied: 0,
    holdings: {},
    trades: [],
    equity_curve: [
      {
        at: when,
        portfolio_value: Number(initialCash),
        cash: Number(initialCash),
        contributed_capital: Number(initialCash),
        positions: 0,
        note: "Fund opened",
      },
    ],
    last_mark_at: when,
  };
}

function createParallelPaperBook({ initialCash, monthlyDeposit, tradeCostPct, maxPositions }) {
  const when = paperNowIso();
  const funds = ["manual", "technical", "automated"].map((mode) =>
    createEmptyFund({
      name: PAPER_STRATEGY_LABELS[mode],
      mode,
      initialCash,
      monthlyDeposit,
      tradeCostPct,
      maxPositions,
      createdAt: when,
    })
  );
  return {
    version: 1,
    active_fund_id: funds[0].config.id,
    funds,
  };
}

function paperFundById(book, id) {
  return (book.funds || []).find((f) => f.config.id === id) || null;
}

function activePaperFund(book) {
  if (book.active_fund_id) {
    const found = paperFundById(book, book.active_fund_id);
    if (found) return found;
  }
  return book.funds[0] || null;
}

function applyPaperDeposits(fund, asOfIso) {
  const monthly = Number(fund.config.monthly_deposit) || 0;
  if (monthly <= 0) return 0;
  const created = paperParseDate(fund.config.created_at);
  const target = paperParseDate(asOfIso);
  const expected = Math.max(0, paperMonthIndex(target) - paperMonthIndex(created));
  const missing = expected - (fund.deposits_applied || 0);
  if (missing <= 0) return 0;
  const total = missing * monthly;
  fund.cash += total;
  fund.contributed_capital += total;
  fund.deposits_applied = (fund.deposits_applied || 0) + missing;
  return total;
}

function paperPositionMark(position, prices) {
  const live = prices?.[position.ticker];
  if (live != null && Number(live) > 0) return Number(live);
  return Number(position.avg_cost) || 0;
}

function paperNav(fund, prices) {
  let equity = 0;
  for (const pos of Object.values(fund.holdings || {})) {
    equity += Number(pos.shares) * paperPositionMark(pos, prices);
  }
  return Number(fund.cash) + equity;
}

function paperPerformance(fund, prices) {
  const value = paperNav(fund, prices);
  const contributed = Number(fund.contributed_capital) || 0;
  const gain = value - contributed;
  return {
    portfolio_value: value,
    cash: Number(fund.cash),
    contributed_capital: contributed,
    gain,
    total_return: contributed > 0 ? gain / contributed : 0,
    positions: Object.keys(fund.holdings || {}).length,
    trade_count: (fund.trades || []).length,
  };
}

function resolvePaperShares({ sizingMode, amount, price, nav, cash, tradeCostPct, side }) {
  const amt = Number(amount);
  const px = Number(price);
  const costPct = Number(tradeCostPct) || 0;
  if (!(amt > 0) || !(px > 0)) return 0;
  let shares;
  if (sizingMode === "shares") {
    shares = amt;
  } else if (sizingMode === "cash") {
    const gross = side === "buy" ? amt / (1 + costPct) : costPct < 1 ? amt / (1 - costPct) : amt;
    shares = gross / px;
  } else {
    let pctAmount = amt;
    if (pctAmount > 1.0000001) pctAmount /= 100;
    const notional = Number(nav) * pctAmount;
    const gross = side === "buy" ? notional / (1 + costPct) : costPct < 1 ? notional / (1 - costPct) : notional;
    shares = gross / px;
  }
  if (side === "buy") {
    const maxGross = Number(cash) / (1 + costPct);
    shares = Math.min(shares, maxGross / px);
  }
  return Math.max(0, shares);
}

function recordPaperMark(fund, prices, note) {
  const when = paperNowIso();
  const point = {
    at: when,
    portfolio_value: Math.round(paperNav(fund, prices) * 100) / 100,
    cash: Math.round(Number(fund.cash) * 100) / 100,
    contributed_capital: Math.round(Number(fund.contributed_capital) * 100) / 100,
    positions: Object.keys(fund.holdings || {}).length,
    note: note || "",
  };
  fund.equity_curve = fund.equity_curve || [];
  fund.equity_curve.push(point);
  fund.last_mark_at = when;
  return point;
}

function paperBuy(fund, { ticker, price, sizingMode, amount, name, sector, stopLoss, takeProfit, note, prices }) {
  applyPaperDeposits(fund, paperNowIso());
  const priceMap = { ...(prices || {}), [ticker]: Number(price) };
  const nav = paperNav(fund, priceMap);
  const shares = resolvePaperShares({
    sizingMode,
    amount,
    price,
    nav,
    cash: fund.cash,
    tradeCostPct: fund.config.trade_cost_pct,
    side: "buy",
  });
  if (!(shares > 0)) throw new Error("Insufficient cash for this buy");
  if (!fund.holdings[ticker] && Object.keys(fund.holdings).length >= fund.config.max_positions) {
    throw new Error(`Max positions (${fund.config.max_positions}) reached`);
  }
  const gross = shares * Number(price);
  const cost = gross * Number(fund.config.trade_cost_pct || 0);
  const spent = gross + cost;
  if (spent > fund.cash + 1e-9) throw new Error("Insufficient cash for this buy");
  fund.cash -= spent;
  const existing = fund.holdings[ticker];
  if (existing) {
    const total = existing.shares + shares;
    existing.avg_cost = (existing.avg_cost * existing.shares + Number(price) * shares) / total;
    existing.shares = total;
    if (stopLoss != null && stopLoss !== "") existing.stop_loss = Number(stopLoss);
    if (takeProfit != null && takeProfit !== "") existing.take_profit = Number(takeProfit);
    if (name) existing.name = name;
    if (sector) existing.sector = sector;
  } else {
    fund.holdings[ticker] = {
      ticker,
      shares,
      avg_cost: Number(price),
      name: name || ticker,
      sector: sector || "",
      stop_loss: stopLoss != null && stopLoss !== "" ? Number(stopLoss) : null,
      take_profit: takeProfit != null && takeProfit !== "" ? Number(takeProfit) : null,
      opened_at: paperNowIso(),
    };
  }
  const trade = {
    id: paperFundId(),
    fund_id: fund.config.id,
    acted_at: paperNowIso(),
    ticker,
    side: "buy",
    sizing_mode: sizingMode,
    shares,
    price: Number(price),
    gross,
    cost,
    net_cash: -spent,
    note: note || "",
    name: name || ticker,
  };
  fund.trades.unshift(trade);
  return trade;
}

function paperSell(fund, { ticker, price, sizingMode, amount, note, prices }) {
  const position = fund.holdings[ticker];
  if (!position || !(position.shares > 0)) throw new Error(`No open position in ${ticker}`);
  const priceMap = { ...(prices || {}), [ticker]: Number(price) };
  const nav = paperNav(fund, priceMap);
  let shares = resolvePaperShares({
    sizingMode,
    amount,
    price,
    nav,
    cash: fund.cash,
    tradeCostPct: fund.config.trade_cost_pct,
    side: "sell",
  });
  shares = Math.min(shares, position.shares);
  if (!(shares > 0)) throw new Error("Sell quantity is zero");
  const gross = shares * Number(price);
  const cost = gross * Number(fund.config.trade_cost_pct || 0);
  const proceeds = gross - cost;
  fund.cash += proceeds;
  position.shares -= shares;
  if (position.shares <= 1e-9) delete fund.holdings[ticker];
  const trade = {
    id: paperFundId(),
    fund_id: fund.config.id,
    acted_at: paperNowIso(),
    ticker,
    side: "sell",
    sizing_mode: sizingMode,
    shares,
    price: Number(price),
    gross,
    cost,
    net_cash: proceeds,
    note: note || "",
    name: position.name || ticker,
  };
  fund.trades.unshift(trade);
  return trade;
}

function candidatePrice(row) {
  for (const key of ["price", "last", "close", "mark"]) {
    if (row[key] != null && Number(row[key]) > 0) return Number(row[key]);
  }
  const plan = row.trade_plan || {};
  for (const key of ["core_limit", "tactical_limit"]) {
    if (plan[key] != null && Number(plan[key]) > 0) return Number(plan[key]);
  }
  return null;
}

function chartPathForTicker(ticker) {
  if (!ticker) return null;
  const slug = String(ticker).replace(/[^A-Za-z0-9._-]+/g, "_");
  return `data/charts/${slug}.json`;
}

async function fetchLastPrice(ticker, report) {
  const fromPlan = candidatePrice(report || { ticker, trade_plan: report?.trade_plan });
  const path = report?.chart_path || chartPathForTicker(ticker);
  if (!path) return fromPlan;
  try {
    const res = await fetch(path);
    if (!res.ok) return fromPlan;
    const payload = await res.json();
    const last = payload?.levels?.last ?? (payload?.closes || []).at(-1);
    if (last != null && Number(last) > 0) return Number(last);
  } catch {
    /* ignore */
  }
  return fromPlan;
}

async function buildPriceMap(tickers, data) {
  const prices = {};
  const unique = [...new Set(tickers.filter(Boolean))];
  await Promise.all(
    unique.map(async (ticker) => {
      const report = (data.reports || []).find((r) => r.ticker === ticker);
      const price = await fetchLastPrice(ticker, report);
      if (price != null && price > 0) prices[ticker] = price;
    })
  );
  return prices;
}

function selectAutoTargets(candidates, maxPositions) {
  const actionable =
    typeof window.IIUnavailable?.filterActionable === "function"
      ? window.IIUnavailable.filterActionable(candidates)
      : candidates;
  return actionable
    .filter((row) => (row.signal === "strong_buy" || row.signal === "buy") && row.timing_signal !== "wait")
    .filter((row) => candidatePrice(row) != null)
    .sort((a, b) => Number(b.conviction_score || 0) - Number(a.conviction_score || 0))
    .slice(0, maxPositions);
}

async function enrichCandidatesWithPrices(data) {
  const buyTier = (data.reports || []).filter((r) => r.signal === "strong_buy" || r.signal === "buy");
  const prices = await buildPriceMap(
    buyTier.map((r) => r.ticker),
    data
  );
  return buyTier.map((row) => ({
    ...row,
    price: prices[row.ticker] ?? candidatePrice(row),
  }));
}

async function runAutomatedPaperRebalance(fund, data) {
  const when = paperNowIso();
  applyPaperDeposits(fund, when);
  const candidates = await enrichCandidatesWithPrices(data);
  const targets = selectAutoTargets(candidates, fund.config.max_positions);
  const targetSet = new Set(targets.map((t) => t.ticker));
  const priceMap = Object.fromEntries(
    candidates.filter((c) => c.price != null).map((c) => [c.ticker, Number(c.price)])
  );
  // Also mark current holdings
  Object.assign(priceMap, await buildPriceMap(Object.keys(fund.holdings), data));

  for (const ticker of Object.keys(fund.holdings)) {
    if (targetSet.has(ticker)) continue;
    const price = priceMap[ticker] || fund.holdings[ticker].avg_cost;
    paperSell(fund, {
      ticker,
      price,
      sizingMode: "shares",
      amount: fund.holdings[ticker].shares,
      note: "Automated exit — left target set",
      prices: priceMap,
    });
  }

  if (!targets.length) {
    recordPaperMark(fund, priceMap, "Automated rebalance (no targets)");
    return;
  }

  const nav = paperNav(fund, priceMap);
  const targetEach = nav / targets.length;

  for (const row of targets) {
    const price = Number(row.price);
    if (!(price > 0)) continue;
    const current = fund.holdings[row.ticker];
    let currentValue = current ? current.shares * price : 0;
    if (current && currentValue > targetEach * 1.02) {
      paperSell(fund, {
        ticker: row.ticker,
        price,
        sizingMode: "cash",
        amount: currentValue - targetEach,
        note: "Automated trim",
        prices: priceMap,
      });
      const refreshed = fund.holdings[row.ticker];
      currentValue = refreshed ? refreshed.shares * price : 0;
    }
    const shortfall = targetEach - currentValue;
    if (shortfall <= 0.01 || fund.cash <= 0.01) continue;
    try {
      paperBuy(fund, {
        ticker: row.ticker,
        price,
        sizingMode: "cash",
        amount: Math.min(shortfall, fund.cash),
        name: row.name,
        sector: row.sector,
        stopLoss: row.trade_plan?.tactical_stop_loss,
        takeProfit: row.trade_plan?.tactical_take_profit,
        note: "Automated buy",
        prices: priceMap,
      });
    } catch {
      /* cash / max positions */
    }
  }
  recordPaperMark(fund, priceMap, "Automated rebalance");
}

async function runTechnicalPaperPass(fund, data) {
  const when = paperNowIso();
  applyPaperDeposits(fund, when);
  const candidates = await enrichCandidatesWithPrices(data);
  const priceMap = Object.fromEntries(
    candidates.filter((c) => c.price != null).map((c) => [c.ticker, Number(c.price)])
  );
  Object.assign(priceMap, await buildPriceMap(Object.keys(fund.holdings), data));
  const exited = new Set();

  for (const [ticker, position] of Object.entries({ ...fund.holdings })) {
    const price = priceMap[ticker];
    if (!(price > 0)) continue;
    if (position.stop_loss != null && price <= position.stop_loss) {
      paperSell(fund, {
        ticker,
        price,
        sizingMode: "shares",
        amount: position.shares,
        note: "Technical stop hit",
        prices: priceMap,
      });
      exited.add(ticker);
      continue;
    }
    if (position.take_profit != null && price >= position.take_profit) {
      paperSell(fund, {
        ticker,
        price,
        sizingMode: "shares",
        amount: position.shares,
        note: "Technical take-profit hit",
        prices: priceMap,
      });
      exited.add(ticker);
    }
  }

  const openings = selectAutoTargets(candidates, fund.config.max_positions * 2);
  for (const row of openings) {
    if (Object.keys(fund.holdings).length >= fund.config.max_positions || fund.cash <= 0) break;
    if (fund.holdings[row.ticker] || exited.has(row.ticker)) continue;
    const plan = row.trade_plan || {};
    const price = Number(plan.core_limit) > 0 ? Number(plan.core_limit) : Number(row.price);
    if (!(price > 0)) continue;
    try {
      paperBuy(fund, {
        ticker: row.ticker,
        price,
        sizingMode: "pct_nav",
        amount: 0.1,
        name: row.name,
        sector: row.sector,
        stopLoss: plan.tactical_stop_loss,
        takeProfit: plan.tactical_take_profit,
        note: "Technical entry at core limit",
        prices: priceMap,
      });
    } catch {
      /* ignore */
    }
  }
  recordPaperMark(fund, priceMap, "Technical pass");
}

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `£${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pctLabel(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function loadPaperSubpage() {
  const value = localStorage.getItem("ftseValueInvestor.paperFundPage.v1");
  if (["overview", "manual", "technical", "automated"].includes(value)) return value;
  return "overview";
}

function savePaperSubpage(page) {
  localStorage.setItem("ftseValueInvestor.paperFundPage.v1", page);
}

function fundByMode(book, mode) {
  return (book.funds || []).find((f) => f.config.mode === mode) || null;
}

function ensurePaperTradeDialog() {
  let dialog = document.getElementById("paper-trade-dialog");
  if (dialog) return dialog;
  document.body.insertAdjacentHTML(
    "beforeend",
    `<dialog id="paper-trade-dialog" class="memo-dialog">
      <form method="dialog" class="memo-dialog-header">
        <h2 id="paper-trade-title">Paper trade</h2>
        <button type="submit" class="btn btn-ghost" aria-label="Close">✕</button>
      </form>
      <form id="paper-trade-form" class="action-form">
        <label>Ticker
          <select name="ticker" required></select>
        </label>
        <label>Side
          <select name="side_select">
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label>Sizing
          <select name="sizing_mode">
            <option value="cash">Cash value (£)</option>
            <option value="shares">Share volume</option>
            <option value="pct_nav">% of fund value</option>
          </select>
        </label>
        <label id="paper-amount-label">Amount
          <input name="amount" type="number" step="any" min="0" required>
        </label>
        <label>Price (£)
          <input name="price" type="number" step="any" min="0" required>
        </label>
        <label>Stop loss (£)
          <input name="stop_loss" type="number" step="any" min="0">
        </label>
        <label>Take profit (£)
          <input name="take_profit" type="number" step="any" min="0">
        </label>
        <label>Notes
          <input name="notes" type="text" maxlength="240">
        </label>
        <p class="small muted" id="paper-trade-hint"></p>
        <div class="form-actions">
          <button type="button" class="btn" id="paper-trade-cancel">Cancel</button>
          <button type="submit" class="btn btn-primary">Execute</button>
        </div>
      </form>
    </dialog>`
  );
  return document.getElementById("paper-trade-dialog");
}

function holdingsTableHtml(fund, prices) {
  const rows = Object.values(fund.holdings || {})
    .map((pos) => {
      const mark = paperPositionMark(pos, prices);
      const value = pos.shares * mark;
      const pnl = (mark - pos.avg_cost) * pos.shares;
      return `<tr>
        <td><strong>${esc(pos.name || pos.ticker)}</strong><br><span class="small muted">${esc(pos.ticker)}</span></td>
        <td>${Number(pos.shares).toFixed(4)}</td>
        <td>${money(pos.avg_cost)}</td>
        <td>${money(mark)}</td>
        <td>${money(value)}</td>
        <td class="${pnl >= 0 ? "pos" : "neg"}">${money(pnl)}</td>
        <td class="small">${pos.stop_loss != null ? `Stop ${money(pos.stop_loss)}<br>` : ""}${
          pos.take_profit != null ? `Target ${money(pos.take_profit)}` : "—"
        }</td>
      </tr>`;
    })
    .join("");
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Shares</th>
            <th>Avg cost</th>
            <th>Mark</th>
            <th>Value</th>
            <th>P&amp;L</th>
            <th>Levels</th>
          </tr>
        </thead>
        <tbody>${rows || `<tr><td colspan="7" class="muted">No holdings yet.</td></tr>`}</tbody>
      </table>
    </div>`;
}

function tradesTableHtml(fund) {
  const rows = (fund.trades || [])
    .slice(0, 12)
    .map(
      (t) => `<tr>
        <td class="small">${fmtDate(t.acted_at)}</td>
        <td>${esc(t.side)}</td>
        <td>${esc(t.name || t.ticker)}</td>
        <td>${Number(t.shares).toFixed(4)} @ ${money(t.price)}</td>
        <td>${esc(t.sizing_mode)}</td>
        <td>${money(t.net_cash)}</td>
        <td class="small">${esc(t.note || "")}</td>
      </tr>`
    )
    .join("");
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>Side</th>
            <th>Name</th>
            <th>Fill</th>
            <th>Sizing</th>
            <th>Cash</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>${rows || `<tr><td colspan="7" class="muted">No trades yet.</td></tr>`}</tbody>
      </table>
    </div>`;
}

function fundStatsHtml(fund, prices) {
  const perf = paperPerformance(fund, prices);
  return `
    <div class="paper-active-summary grid">
      <div>
        <div class="small muted">NAV</div>
        <strong>${money(perf.portfolio_value)}</strong>
      </div>
      <div>
        <div class="small muted">Cash available</div>
        <strong>${money(perf.cash)}</strong>
      </div>
      <div>
        <div class="small muted">Contributed</div>
        <strong>${money(perf.contributed_capital)}</strong>
      </div>
      <div>
        <div class="small muted">Return vs contributed</div>
        <strong class="${perf.gain >= 0 ? "pos" : "neg"}">${pctLabel(perf.total_return)} (${money(perf.gain)})</strong>
      </div>
    </div>`;
}

function buildAutomatedPlan(fund, candidates) {
  const targets = selectAutoTargets(candidates, fund.config.max_positions);
  const targetSet = new Set(targets.map((t) => t.ticker));
  const priceMap = Object.fromEntries(
    candidates.filter((c) => c.price != null).map((c) => [c.ticker, Number(c.price)])
  );
  for (const [ticker, pos] of Object.entries(fund.holdings || {})) {
    if (priceMap[ticker] == null && pos.avg_cost > 0) priceMap[ticker] = Number(pos.avg_cost);
  }

  const nav = paperNav(fund, priceMap);
  let cash = Number(fund.cash);
  const exits = [];
  for (const [ticker, position] of Object.entries(fund.holdings || {})) {
    if (targetSet.has(ticker)) continue;
    const price = priceMap[ticker] || position.avg_cost;
    const value = Number(position.shares) * Number(price || 0);
    exits.push({
      action: "sell",
      ticker,
      name: position.name || ticker,
      reason: "No longer in the top conviction target set",
      shares: position.shares,
      price,
      value,
    });
    cash += value * (1 - Number(fund.config.trade_cost_pct || 0));
  }

  const remaining = Object.fromEntries(
    Object.entries(fund.holdings || {}).filter(([ticker]) => targetSet.has(ticker))
  );
  const navAfterExits = (() => {
    const temp = { cash, holdings: remaining };
    return paperNav(temp, priceMap);
  })();
  const targetEach = targets.length ? navAfterExits / targets.length : 0;
  const trims = [];
  const buys = [];
  const holds = [];
  const skipped = [];

  for (const row of targets) {
    const price = Number(row.price);
    if (!(price > 0)) {
      skipped.push({ ticker: row.ticker, name: row.name || row.ticker, reason: "No usable price mark" });
      continue;
    }
    const current = remaining[row.ticker];
    let currentValue = current ? current.shares * price : 0;
    if (current && currentValue > targetEach * 1.02) {
      const excess = currentValue - targetEach;
      trims.push({
        action: "trim",
        ticker: row.ticker,
        name: row.name || row.ticker,
        reason: `Overweight vs equal-weight sleeve (${money(targetEach)} target)`,
        value: excess,
        price,
        conviction_score: row.conviction_score,
        signal: row.signal,
      });
      cash += excess * (1 - Number(fund.config.trade_cost_pct || 0));
      currentValue = targetEach;
    }
    const shortfall = targetEach - currentValue;
    if (Math.abs(shortfall) <= 0.01 * Math.max(1, targetEach)) {
      holds.push({
        action: "hold",
        ticker: row.ticker,
        name: row.name || row.ticker,
        reason: "Already near equal-weight target",
        value: currentValue,
        target_value: targetEach,
        conviction_score: row.conviction_score,
        signal: row.signal,
      });
      continue;
    }
    if (shortfall <= 0) continue;
    const budget = Math.min(shortfall, cash);
    if (budget <= 0.01) {
      skipped.push({
        ticker: row.ticker,
        name: row.name || row.ticker,
        reason: "Insufficient cash after higher-conviction fills",
        target_value: targetEach,
        conviction_score: row.conviction_score,
        signal: row.signal,
      });
      continue;
    }
    buys.push({
      action: "buy",
      ticker: row.ticker,
      name: row.name || row.ticker,
      reason: currentValue <= 0 ? "New sleeve" : "Top-up to equal weight",
      value: budget,
      price,
      target_value: targetEach,
      conviction_score: row.conviction_score,
      signal: row.signal,
    });
    cash -= budget;
  }

  const waitlisted = candidates
    .filter((row) => (row.signal === "strong_buy" || row.signal === "buy") && row.timing_signal === "wait")
    .sort((a, b) => Number(b.conviction_score || 0) - Number(a.conviction_score || 0))
    .slice(0, 8)
    .map((row) => ({
      ticker: row.ticker,
      name: row.name || row.ticker,
      signal: row.signal,
      conviction_score: row.conviction_score,
      reason: "timing_signal=wait — skipped until timing improves",
    }));

  const rules = [
    "Universe: only strong_buy / buy names from the latest screen.",
    "Timing filter: names with timing_signal=wait are excluded from new buys.",
    `Ranking: highest conviction_score first, keep at most ${fund.config.max_positions} names.`,
    "Sizing: equal-weight sleeves of current NAV after exits; buys limited by remaining cash.",
    `Costs: ${(Number(fund.config.trade_cost_pct) * 100).toFixed(1)}% applied on each buy and sell.`,
  ];

  let summary = "No eligible buy-tier targets right now — the next rebalance would stay in cash / existing names that still qualify.";
  if (targets.length) {
    const parts = [`Next rebalance would target ${targets.length} equal-weight sleeve(s)`];
    if (exits.length) parts.push(`sell ${exits.length} name(s) that left the set`);
    if (trims.length) parts.push(`trim ${trims.length} overweight sleeve(s)`);
    if (buys.length) parts.push(`deploy cash into ${buys.length} buy(s)`);
    if (holds.length) parts.push(`leave ${holds.length} near-target holding(s)`);
    summary = `${parts.join("; ")}.`;
  }

  return {
    rules,
    nav,
    cash: fund.cash,
    max_positions: fund.config.max_positions,
    target_sleeve_value: targetEach,
    targets,
    anticipated_exits: exits,
    anticipated_trims: trims,
    anticipated_buys: buys,
    anticipated_holds: holds,
    skipped,
    waitlisted,
    summary,
  };
}

function planMovesTable(title, rows, emptyText) {
  if (!rows.length) {
    return `<div class="paper-plan-block"><h5>${esc(title)}</h5><p class="small muted">${esc(emptyText)}</p></div>`;
  }
  const body = rows
    .map((row) => {
      const detail =
        row.value != null
          ? money(row.value)
          : row.shares != null
            ? `${Number(row.shares).toFixed(4)} sh`
            : "—";
      return `<tr>
        <td><strong>${esc(row.name || row.ticker)}</strong><br><span class="small muted">${esc(row.ticker)}${
          row.signal ? ` · ${esc(row.signal)}` : ""
        }</span></td>
        <td>${esc(row.action || "—")}</td>
        <td>${detail}</td>
        <td class="small">${esc(row.reason || "")}${
          row.conviction_score != null ? `<br>Conviction ${pctLabel(row.conviction_score)}` : ""
        }</td>
      </tr>`;
    })
    .join("");
  return `
    <div class="paper-plan-block">
      <h5>${esc(title)}</h5>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Action</th><th>Size</th><th>Why</th></tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </div>`;
}

function technicalNarrativeHtml(fund, plan) {
  const lastTech = (fund.trades || [])
    .filter((t) => String(t.note || "").toLowerCase().includes("technical"))
    .slice(0, 6);
  const lastTechHtml = lastTech.length
    ? `<ul class="list-plain small">${lastTech
        .map(
          (t) =>
            `<li><strong>${esc(t.side)}</strong> ${esc(t.name || t.ticker)} — ${esc(t.note)} (${fmtDate(t.acted_at)})</li>`
        )
        .join("")}</ul>`
    : `<p class="small muted">No technical trades yet — run a pass to create the first decision trail.</p>`;

  return `
    <div class="paper-narrative">
      <h4>How the technical model decides</h4>
      <ol class="paper-rules">
        ${plan.rules.map((rule) => `<li>${esc(rule)}</li>`).join("")}
      </ol>
      <p><strong>Anticipated next move:</strong> ${esc(plan.summary)}</p>
      <p class="small muted">NAV ${money(plan.nav)} · cash ${money(plan.cash)} · new entries ≈ ${(
        Number(plan.buy_pct_nav) * 100
      ).toFixed(0)}% of NAV each.</p>
      ${planMovesTable("Would exit on stop/target", plan.anticipated_exits, "No stop/target exits on current marks.")}
      ${planMovesTable("Would enter near core limit", plan.anticipated_buys, "No new technical entries available.")}
      ${planMovesTable("Would hold", plan.anticipated_holds, "No open holdings to hold.")}
      ${planMovesTable("Deferred", plan.deferred || [], "Nothing deferred.")}
      <h5>Recent technical decisions</h5>
      ${lastTechHtml}
    </div>`;
}

function buildTechnicalPlan(fund, candidates) {
  const priceMap = Object.fromEntries(
    candidates.filter((c) => c.price != null).map((c) => [c.ticker, Number(c.price)])
  );
  for (const [ticker, pos] of Object.entries(fund.holdings || {})) {
    if (priceMap[ticker] == null && pos.avg_cost > 0) priceMap[ticker] = Number(pos.avg_cost);
  }
  const buyPct = 0.1;
  const exits = [];
  const holds = [];
  for (const [ticker, position] of Object.entries(fund.holdings || {})) {
    const price = priceMap[ticker];
    if (!(price > 0)) {
      holds.push({
        action: "hold",
        ticker,
        name: position.name || ticker,
        reason: "No mark available to evaluate stop/target",
      });
      continue;
    }
    if (position.stop_loss != null && price <= position.stop_loss) {
      exits.push({
        action: "sell",
        ticker,
        name: position.name || ticker,
        reason: `Stop hit (mark ${money(price)} ≤ stop ${money(position.stop_loss)})`,
        shares: position.shares,
        price,
        value: position.shares * price,
      });
      continue;
    }
    if (position.take_profit != null && price >= position.take_profit) {
      exits.push({
        action: "sell",
        ticker,
        name: position.name || ticker,
        reason: `Take-profit hit (mark ${money(price)} ≥ target ${money(position.take_profit)})`,
        shares: position.shares,
        price,
        value: position.shares * price,
      });
      continue;
    }
    holds.push({
      action: "hold",
      ticker,
      name: position.name || ticker,
      reason: "Between stop and target (or levels not set)",
      value: position.shares * price,
    });
  }

  const exited = new Set(exits.map((e) => e.ticker));
  const openSlots = Math.max(0, fund.config.max_positions - (Object.keys(fund.holdings || {}).length - exited.size));
  const nav = paperNav(fund, priceMap);
  const entries = [];
  const deferred = [];
  if (openSlots <= 0 || fund.cash <= 0) {
    deferred.push({ ticker: "—", name: "New entries", reason: "No open slots or cash available after exits" });
  } else {
    const ranked = selectAutoTargets(candidates, fund.config.max_positions * 2);
    for (const row of ranked) {
      if (entries.length >= openSlots) break;
      if (fund.holdings[row.ticker] || exited.has(row.ticker)) continue;
      if (row.timing_signal === "wait") {
        deferred.push({
          ticker: row.ticker,
          name: row.name || row.ticker,
          reason: "timing_signal=wait",
          conviction_score: row.conviction_score,
          signal: row.signal,
        });
        continue;
      }
      const plan = row.trade_plan || {};
      const price = Number(plan.core_limit) > 0 ? Number(plan.core_limit) : Number(row.price);
      if (!(price > 0)) {
        deferred.push({
          ticker: row.ticker,
          name: row.name || row.ticker,
          reason: "No core limit / mark for entry",
        });
        continue;
      }
      entries.push({
        action: "buy",
        ticker: row.ticker,
        name: row.name || row.ticker,
        reason: `Core-limit entry (~${(buyPct * 100).toFixed(0)}% NAV)${
          plan.core_limit != null ? ` at ${money(price)}` : " at last mark"
        }`,
        value: Math.min(nav * buyPct, fund.cash),
        price,
        conviction_score: row.conviction_score,
        signal: row.signal,
      });
    }
  }

  const rules = [
    "Exits first: full sell if last mark ≤ stop loss or ≥ take-profit.",
    "Entries next: unused buy-tier names (timing ≠ wait) at core limit when available.",
    `Position size for new entries: about ${(buyPct * 100).toFixed(0)}% of current NAV, capped by cash.`,
    "Names exited in the same pass are not re-bought immediately.",
    `Hard cap: ${fund.config.max_positions} open names.`,
  ];
  const parts = [];
  if (exits.length) parts.push(`exit ${exits.length} holding(s) on stop/target`);
  if (entries.length) parts.push(`enter ${entries.length} new name(s) near core limit`);
  if (holds.length) parts.push(`keep ${holds.length} holding(s) between levels`);
  const summary = parts.length
    ? `Next technical pass would ${parts.join("; ")}.`
    : "Next technical pass would make no trades on the current marks and screen.";

  return {
    rules,
    nav,
    cash: fund.cash,
    buy_pct_nav: buyPct,
    anticipated_exits: exits,
    anticipated_buys: entries,
    anticipated_holds: holds,
    deferred: deferred.slice(0, 8),
    summary,
  };
}

function ownedSurveillanceHtml(fund, prices, data) {
  const rows = [];
  for (const pos of Object.values(fund.holdings || {})) {
    const mark = paperPositionMark(pos, prices);
    let severity = "info";
    let message = "No stop/target breach; continue monitoring";
    if (pos.stop_loss != null && mark <= pos.stop_loss) {
      severity = "action";
      message = `Mark ${money(mark)} at/under stop ${money(pos.stop_loss)}`;
    } else if (pos.take_profit != null && mark >= pos.take_profit) {
      severity = "action";
      message = `Mark ${money(mark)} at/over take-profit ${money(pos.take_profit)}`;
    }
    const report = (data?.reports || []).find((r) => r.ticker === pos.ticker);
    if (report?.timing_signal === "wait" && severity === "info") {
      severity = "watch";
      message = "Technical timing is wait — avoid adding size";
    }
    rows.push({
      ticker: pos.ticker,
      name: pos.name || pos.ticker,
      source: "paper",
      severity,
      message,
      mark,
    });
  }

  // Live/real owned intents from the action log
  try {
    const actions = JSON.parse(localStorage.getItem("ftseValueInvestor.portfolioActions.v1") || "[]");
    const liveOpen = (Array.isArray(actions) ? actions : []).filter(
      (a) => (a.status || "open") === "open" && (a.execution_mode == null || a.execution_mode === "live")
    );
    for (const action of liveOpen) {
      const report = (data?.reports || []).find((r) => r.ticker === action.ticker);
      const mark = prices?.[action.ticker] ?? report?.trade_plan?.core_limit ?? null;
      let severity = "info";
      let message = "Live book name under surveillance";
      if (action.stop_loss != null && mark != null && Number(mark) <= Number(action.stop_loss)) {
        severity = "action";
        message = `Mark ${money(mark)} at/under stop ${money(action.stop_loss)}`;
      } else if (action.take_profit != null && mark != null && Number(mark) >= Number(action.take_profit)) {
        severity = "action";
        message = `Mark ${money(mark)} at/over take-profit ${money(action.take_profit)}`;
      } else if (report?.timing_signal === "wait") {
        severity = "watch";
        message = "Technical timing is wait";
      } else if (report?.signal === "avoid" || report?.signal === "hold") {
        severity = "watch";
        message = `Screen signal is now ${report.signal}`;
      }
      rows.push({
        ticker: action.ticker,
        name: action.name || action.ticker,
        source: "live",
        severity,
        message,
        mark,
      });
    }
  } catch {
    /* ignore */
  }

  const body = rows
    .map(
      (r) => `<tr>
        <td><strong>${esc(r.name)}</strong><br><span class="small muted">${esc(r.ticker)} · ${esc(r.source)}</span></td>
        <td><span class="badge badge-${esc(r.severity)}">${esc(r.severity)}</span></td>
        <td>${r.mark != null ? money(r.mark) : "—"}</td>
        <td class="small">${esc(r.message)}</td>
      </tr>`
    )
    .join("");

  return `
    <div class="paper-narrative">
      <h4>Owned-stock surveillance</h4>
      <p class="small muted">Daily checks across automated paper holdings and live action-log names (stops, targets, timing, signal drift).</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Severity</th><th>Mark</th><th>Note</th></tr></thead>
          <tbody>${body || `<tr><td colspan="4" class="muted">No paper or live holdings to surveil yet.</td></tr>`}</tbody>
        </table>
      </div>
    </div>`;
}

function independentAutoControlsHtml(settings, gate, serverAuto) {
  const serverNote = serverAuto
    ? `<p class="small">Server last run: ${esc(serverAuto.note || "—")} · ${esc(
        serverAuto.generated_at ? fmtDate(serverAuto.generated_at) : "n/a"
      )} · acted=${esc(String(!!serverAuto.acted))}</p>`
    : `<p class="small muted">No server automation report in latest.json yet. Enable the weekday GitHub Action <code>FTSE Paper Automation</code> (runs ~09:17 London).</p>`;

  return `
    <div class="paper-narrative paper-auto-settings">
      <h4>Independent daily automation</h4>
      <p>When enabled, the automated pot can rebalance on its own after early open volatility settles (default 75 minutes after 08:00 Europe/London ≈ 09:15). A weekday GitHub Action does the same server-side against published screen data.</p>
      <form id="paper-auto-settings-form" class="paper-bootstrap-form">
        <label class="paper-check">
          <input type="checkbox" name="independent" ${settings.independent ? "checked" : ""}>
          Run independently in this browser (once per day after settle)
        </label>
        <label>Market open (London)
          <input name="market_open" type="time" value="${esc(settings.market_open || "08:00")}">
        </label>
        <label>Settle minutes after open
          <input name="settle_minutes_after_open" type="number" min="0" max="240" step="5" value="${esc(
            String(settings.settle_minutes_after_open ?? 75)
          )}">
        </label>
        <button type="submit" class="btn btn-primary">Save auto settings</button>
      </form>
      <p class="small">Session gate: <strong>${esc(gate.reason)}</strong> · ${esc(gate.local_label)}</p>
      ${serverNote}
    </div>`;
}

function automatedNarrativeHtml(fund, plan) {
  const lastAuto = (fund.trades || []).filter((t) => String(t.note || "").startsWith("Automated")).slice(0, 6);
  const lastAutoHtml = lastAuto.length
    ? `<ul class="list-plain small">${lastAuto
        .map(
          (t) =>
            `<li><strong>${esc(t.side)}</strong> ${esc(t.name || t.ticker)} — ${esc(t.note)} (${fmtDate(t.acted_at)})</li>`
        )
        .join("")}</ul>`
    : `<p class="small muted">No automated trades yet — run a rebalance to create the first decision trail.</p>`;

  const targetRows = (plan.targets || [])
    .map(
      (t, index) => `<tr>
        <td>${index + 1}</td>
        <td><strong>${esc(t.name || t.ticker)}</strong><br><span class="small muted">${esc(t.ticker)}</span></td>
        <td>${signalBadge(t.signal)}</td>
        <td>${pctLabel(t.conviction_score)}</td>
        <td>${money(t.price)}</td>
        <td>${money(plan.target_sleeve_value)}</td>
      </tr>`
    )
    .join("");

  return `
    <div class="paper-narrative">
      <h4>How the automated model decides</h4>
      <ol class="paper-rules">
        ${plan.rules.map((rule) => `<li>${esc(rule)}</li>`).join("")}
      </ol>
      <p><strong>Anticipated next move:</strong> ${esc(plan.summary)}</p>
      <p class="small muted">Sleeve target ≈ ${money(plan.target_sleeve_value)} from NAV ${money(plan.nav)} with ${money(
        plan.cash
      )} cash on hand (max ${plan.max_positions} positions).</p>

      <h5>Current target set</h5>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Name</th>
              <th>Signal</th>
              <th>Conviction</th>
              <th>Mark</th>
              <th>Sleeve target</th>
            </tr>
          </thead>
          <tbody>${
            targetRows || `<tr><td colspan="6" class="muted">No eligible targets on the current screen.</td></tr>`
          }</tbody>
        </table>
      </div>

      ${planMovesTable("Would sell", plan.anticipated_exits, "No exits — every holding still qualifies.")}
      ${planMovesTable("Would trim", plan.anticipated_trims, "No trims needed.")}
      ${planMovesTable("Would buy / top up", plan.anticipated_buys, "No buys — sleeves are funded or cash is exhausted.")}
      ${planMovesTable("Would hold near target", plan.anticipated_holds, "No near-target holds.")}
      ${planMovesTable("Skipped / deferred", [...(plan.skipped || []), ...(plan.waitlisted || [])], "Nothing deferred.")}

      <h5>Recent automated decisions</h5>
      ${lastAutoHtml}
    </div>`;
}

function modeIntro(mode) {
  if (mode === "manual") {
    return {
      title: "Immediate buy/sell",
      blurb:
        "You choose every trade. Size by share volume, cash value, or % of current fund NAV. The pot cannot spend more cash than it holds, and new names are blocked once max positions are reached.",
      bullets: [
        "Best for discretionary paper trading against the same capital rules as the other sims.",
        "Marks use published chart last prices when available.",
        "Monthly deposits credit into cash automatically when you apply deposits or trade after month-end.",
      ],
    };
  }
  if (mode === "technical") {
    return {
      title: "Follow technical cues",
      blurb:
        "A one-click pass reads stop / take-profit levels on open holdings and looks for core-limit entries on unused buy-tier names when timing is not wait.",
      bullets: [
        "Exits first: full sell if last price ≤ stop or ≥ take-profit.",
        "Entries next: ~10% of NAV at core limit (or last price), attaching the trade-plan stop/target.",
        "Names stopped out in the same pass are not immediately re-bought.",
      ],
    };
  }
  return {
    title: "Automated stock picking",
    blurb:
      "Fully rules-based: rank buy-tier names by conviction, skip timing=wait, hold up to max positions, and equal-weight the sleeves with cash as the hard constraint. Can run independently after the London open settle window.",
    bullets: [
      "Sells anything that drops out of the top conviction set.",
      "Trims overweight sleeves, then tops up / opens underweight sleeves.",
      "Independent mode waits ~75 minutes after 08:00 Europe/London so early volatility can settle, then acts once per day.",
      "Surveillance watches paper holdings and live action-log names for stop/target/timing alerts.",
    ],
  };
}

function renderBootstrapCard() {
  return `
    <div class="card paper-funds-card">
      <h3>Paper fund simulations</h3>
      <p>Create three parallel pots with the same starting cash and deposit rules, then work each strategy on its own sub-page.</p>
      <form id="paper-bootstrap-form" class="paper-bootstrap-form">
        <label>Initial cash (£)
          <input name="initial_cash" type="number" min="0" step="any" value="1000" required>
        </label>
        <label>Monthly deposit (£)
          <input name="monthly_deposit" type="number" min="0" step="any" value="100">
        </label>
        <label>Trade cost
          <input name="trade_cost_pct" type="number" min="0" max="0.2" step="0.001" value="0.03">
        </label>
        <label>Max positions
          <input name="max_positions" type="number" min="1" max="20" step="1" value="5">
        </label>
        <button type="submit" class="btn btn-primary">Create three parallel funds</button>
      </form>
      <p class="small muted">Funds: Immediate buy/sell · Follow technical cues · Automated stock picking. All stay in this browser unless you export JSON.</p>
    </div>`;
}

function renderOverviewPage(book, pricesByFund) {
  const rows = book.funds
    .map((fund) => {
      const prices = pricesByFund?.[fund.config.id] || {};
      applyPaperDeposits(fund, paperNowIso());
      const perf = paperPerformance(fund, prices);
      return { fund, perf };
    })
    .sort((a, b) => b.perf.total_return - a.perf.total_return);

  savePaperBook(book);
  const sample = book.funds[0]?.config || {};

  return `
    <div class="card paper-funds-card">
      <div class="paper-funds-header">
        <div>
          <h3>Simulation overview</h3>
          <p class="small muted">Shared capital template: ${money(sample.initial_cash)} start · ${money(
            sample.monthly_deposit || 0
          )}/month · ${(Number(sample.trade_cost_pct) * 100).toFixed(1)}% costs · max ${
            sample.max_positions
          } positions. Open a strategy sub-page for its controls.</p>
        </div>
        <div class="paper-funds-actions">
          <button type="button" class="btn" id="paper-deposit-btn">Apply deposits</button>
          <button type="button" class="btn" id="paper-refresh-marks-btn">Refresh marks</button>
          <button type="button" class="btn" id="paper-export-btn">Export funds</button>
          <button type="button" class="btn" id="paper-reset-btn">Reset funds</button>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Fund</th>
              <th>NAV</th>
              <th>Cash</th>
              <th>Contributed</th>
              <th>Return</th>
              <th>Positions</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${rows
              .map(
                ({ fund, perf }) => `<tr>
                <td>
                  <strong>${esc(fund.config.name)}</strong>
                  <div class="small muted">${esc(PAPER_STRATEGY_LABELS[fund.config.mode] || fund.config.mode)}</div>
                </td>
                <td>${money(perf.portfolio_value)}</td>
                <td>${money(perf.cash)}</td>
                <td>${money(perf.contributed_capital)}</td>
                <td class="${perf.gain >= 0 ? "pos" : "neg"}">${pctLabel(perf.total_return)}</td>
                <td>${perf.positions}</td>
                <td><button type="button" class="btn" data-paper-page="${esc(fund.config.mode)}">Open</button></td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
      <div class="paper-mode-cards grid" style="margin-top:1rem">
        ${["manual", "technical", "automated"]
          .map((mode) => {
            const intro = modeIntro(mode);
            return `<div class="paper-mode-card">
              <h4>${esc(intro.title)}</h4>
              <p class="small">${esc(intro.blurb)}</p>
              <button type="button" class="btn btn-primary" data-paper-page="${esc(mode)}">Go to controls</button>
            </div>`;
          })
          .join("")}
      </div>
    </div>`;
}

function renderModePage(mode, fund, prices, plan, data) {
  const intro = modeIntro(mode);
  const settings = loadPaperAutoSettings();
  const gate = browserSessionGate(settings);
  const actions =
    mode === "manual"
      ? `<button type="button" class="btn btn-primary" id="paper-trade-btn">Buy / sell</button>
         <button type="button" class="btn" id="paper-deposit-btn">Apply deposits</button>
         <button type="button" class="btn" id="paper-refresh-marks-btn">Refresh marks</button>`
      : mode === "technical"
        ? `<button type="button" class="btn btn-primary" id="paper-tech-btn">Run technical pass</button>
           <button type="button" class="btn" id="paper-deposit-btn">Apply deposits</button>
           <button type="button" class="btn" id="paper-refresh-marks-btn">Refresh marks</button>`
        : `<button type="button" class="btn btn-primary" id="paper-auto-btn">Run automated rebalance</button>
           <button type="button" class="btn" id="paper-deposit-btn">Apply deposits</button>
           <button type="button" class="btn" id="paper-refresh-marks-btn">Refresh marks</button>`;

  return `
    <div class="card paper-funds-card">
      <div class="paper-funds-header">
        <div>
          <h3>${esc(intro.title)}</h3>
          <p>${esc(intro.blurb)}</p>
          <ul class="list-plain small paper-bullets">
            ${intro.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}
          </ul>
        </div>
        <div class="paper-funds-actions">${actions}</div>
      </div>
      ${fundStatsHtml(fund, prices)}
      ${mode === "automated" ? independentAutoControlsHtml(settings, gate, data?.paper_automation) : ""}
      ${mode === "automated" ? ownedSurveillanceHtml(fund, prices, data) : ""}
      ${mode === "automated" && plan ? automatedNarrativeHtml(fund, plan) : ""}
      ${mode === "technical" && plan ? technicalNarrativeHtml(fund, plan) : ""}
      <h4 style="margin-top:1.25rem">Holdings</h4>
      ${holdingsTableHtml(fund, prices)}
      <h4 style="margin-top:1rem">Recent trades</h4>
      ${tradesTableHtml(fund)}
    </div>`;
}

function paperSubnavHtml(activePage) {
  const items = [
    { id: "overview", label: "Overview" },
    { id: "manual", label: "Immediate" },
    { id: "technical", label: "Technical" },
    { id: "automated", label: "Automated" },
  ];
  return `
    <nav class="paper-subnav" aria-label="Paper fund simulators">
      ${items
        .map(
          (item) =>
            `<button type="button" class="paper-subtab${item.id === activePage ? " active" : ""}" data-paper-page="${item.id}">${esc(
              item.label
            )}</button>`
        )
        .join("")}
    </nav>`;
}

function renderPaperFundsSection(data, pricesByFund, modePlan) {
  const book = loadPaperBook();
  if (!book.funds.length) return renderBootstrapCard();

  const page = loadPaperSubpage();
  let body = "";
  if (page === "overview") {
    body = renderOverviewPage(book, pricesByFund);
  } else {
    const fund = fundByMode(book, page) || activePaperFund(book);
    if (!fund) {
      body = renderOverviewPage(book, pricesByFund);
    } else {
      book.active_fund_id = fund.config.id;
      applyPaperDeposits(fund, paperNowIso());
      savePaperBook(book);
      const prices = pricesByFund?.[fund.config.id] || {};
      body = renderModePage(fund.config.mode, fund, prices, modePlan, data);
    }
  }

  return `
    <div class="paper-funds-shell">
      <div class="paper-funds-title-row">
        <div>
          <h3 class="paper-section-title">Paper fund simulations</h3>
          <p class="small muted">Each simulator has its own page for controls and holdings. Overview compares performance across pots.</p>
        </div>
      </div>
      ${paperSubnavHtml(page)}
      ${body}
    </div>`;
}

async function pricesForBook(book, data) {
  const out = {};
  for (const fund of book.funds || []) {
    const tickers = Object.keys(fund.holdings || {});
    out[fund.config.id] = await buildPriceMap(tickers, data);
  }
  return out;
}

async function candidatesForPlan(fund, data, holdingPrices) {
  const candidates = await enrichCandidatesWithPrices(data);
  for (const [ticker, price] of Object.entries(holdingPrices || {})) {
    if (!candidates.find((c) => c.ticker === ticker)) {
      const report = (data.reports || []).find((r) => r.ticker === ticker) || {
        ticker,
        name: fund.holdings[ticker]?.name || ticker,
        signal: "hold",
      };
      candidates.push({ ...report, price });
    }
  }
  return candidates;
}

async function maybeRunIndependentAuto(data) {
  const settings = loadPaperAutoSettings();
  const gate = browserSessionGate(settings);
  if (!gate.can_act) return false;
  if (settings.last_auto_run_day === gate.dayKey) return false;
  const book = loadPaperBook();
  const fund = fundByMode(book, "automated");
  if (!fund) return false;
  book.active_fund_id = fund.config.id;
  await runAutomatedPaperRebalance(fund, data);
  settings.last_auto_run_day = gate.dayKey;
  savePaperAutoSettings(settings);
  savePaperBook(book);
  return true;
}

async function renderPaperFunds(data) {
  const mount = document.getElementById("paper-funds-root");
  if (!mount) return;
  const book = loadPaperBook();
  let pricesByFund = {};
  let modePlan = null;
  if (book.funds.length) {
    // Independent browser auto-run once/day after London open settle.
    try {
      const ran = await maybeRunIndependentAuto(data);
      if (ran) {
        /* fund state updated; continue to render */
      }
    } catch (err) {
      console.warn("Independent paper auto failed", err);
    }
    mount.innerHTML = `<div class="card"><p class="muted">Loading paper fund marks…</p></div>`;
    pricesByFund = await pricesForBook(loadPaperBook(), data);
    const page = loadPaperSubpage();
    if (page === "automated" || page === "technical") {
      const fund = fundByMode(loadPaperBook(), page);
      if (fund) {
        const candidates = await candidatesForPlan(fund, data, pricesByFund[fund.config.id] || {});
        modePlan = page === "automated" ? buildAutomatedPlan(fund, candidates) : buildTechnicalPlan(fund, candidates);
      }
    }
  }
  const liveMount = document.getElementById("paper-funds-root");
  if (!liveMount) return;
  liveMount.innerHTML = renderPaperFundsSection(data, pricesByFund, modePlan);
  bindPaperFunds(data);
}

function bindPaperFunds(data) {
  const bootstrap = document.getElementById("paper-bootstrap-form");
  if (bootstrap) {
    bootstrap.addEventListener("submit", (event) => {
      event.preventDefault();
      const fd = new FormData(bootstrap);
      const book = createParallelPaperBook({
        initialCash: Number(fd.get("initial_cash")),
        monthlyDeposit: Number(fd.get("monthly_deposit") || 0),
        tradeCostPct: Number(fd.get("trade_cost_pct") || 0),
        maxPositions: Number(fd.get("max_positions") || 5),
      });
      savePaperBook(book);
      savePaperSubpage("overview");
      renderPaperFunds(data);
    });
    return;
  }

  const autoSettingsForm = document.getElementById("paper-auto-settings-form");
  if (autoSettingsForm) {
    autoSettingsForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const fd = new FormData(autoSettingsForm);
      const prev = loadPaperAutoSettings();
      savePaperAutoSettings({
        independent: Boolean(fd.get("independent")),
        settle_minutes_after_open: Number(fd.get("settle_minutes_after_open") || 75),
        market_open: String(fd.get("market_open") || "08:00"),
        last_auto_run_day: prev.last_auto_run_day,
      });
      renderPaperFunds(data);
    });
  }

  document.querySelectorAll("[data-paper-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const page = button.dataset.paperPage;
      savePaperSubpage(page);
      const book = loadPaperBook();
      const fund = fundByMode(book, page);
      if (fund) {
        book.active_fund_id = fund.config.id;
        savePaperBook(book);
      }
      renderPaperFunds(data);
    });
  });

  const depositBtn = document.getElementById("paper-deposit-btn");
  if (depositBtn) {
    depositBtn.addEventListener("click", () => {
      const book = loadPaperBook();
      for (const fund of book.funds) applyPaperDeposits(fund, paperNowIso());
      savePaperBook(book);
      renderPaperFunds(data);
    });
  }

  const refreshBtn = document.getElementById("paper-refresh-marks-btn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      const book = loadPaperBook();
      const pricesByFund = await pricesForBook(book, data);
      for (const fund of book.funds) {
        applyPaperDeposits(fund, paperNowIso());
        recordPaperMark(fund, pricesByFund[fund.config.id] || {}, "Mark refresh");
      }
      savePaperBook(book);
      renderPaperFunds(data);
    });
  }

  const resetBtn = document.getElementById("paper-reset-btn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      if (!window.confirm("Delete all paper funds in this browser?")) return;
      localStorage.removeItem(PAPER_FUND_STORAGE_KEY);
      savePaperSubpage("overview");
      renderPaperFunds(data);
    });
  }

  const exportBtn = document.getElementById("paper-export-btn");
  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(loadPaperBook(), null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "paper-funds.json";
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  const autoBtn = document.getElementById("paper-auto-btn");
  if (autoBtn) {
    autoBtn.addEventListener("click", async () => {
      autoBtn.disabled = true;
      try {
        const book = loadPaperBook();
        const fund = fundByMode(book, "automated");
        if (!fund) return;
        book.active_fund_id = fund.config.id;
        await runAutomatedPaperRebalance(fund, data);
        savePaperBook(book);
        await renderPaperFunds(data);
      } finally {
        autoBtn.disabled = false;
      }
    });
  }

  const techBtn = document.getElementById("paper-tech-btn");
  if (techBtn) {
    techBtn.addEventListener("click", async () => {
      techBtn.disabled = true;
      try {
        const book = loadPaperBook();
        const fund = fundByMode(book, "technical");
        if (!fund) return;
        book.active_fund_id = fund.config.id;
        await runTechnicalPaperPass(fund, data);
        savePaperBook(book);
        await renderPaperFunds(data);
      } finally {
        techBtn.disabled = false;
      }
    });
  }

  const tradeBtn = document.getElementById("paper-trade-btn");
  if (tradeBtn) {
    tradeBtn.addEventListener("click", () => openPaperTradeDialog(data));
  }
}

async function openPaperTradeDialog(data) {
  const book = loadPaperBook();
  const fund = fundByMode(book, "manual") || activePaperFund(book);
  if (!fund) return;
  book.active_fund_id = fund.config.id;
  savePaperBook(book);
  const dialog = ensurePaperTradeDialog();
  const form = document.getElementById("paper-trade-form");
  const tickerSelect = form.ticker;
  const buyTier = (data.reports || []).filter((r) => r.signal === "strong_buy" || r.signal === "buy");
  const held = Object.keys(fund.holdings);
  const options = [
    ...new Map(
      [
        ...buyTier.map((r) => [r.ticker, r]),
        ...held.map((t) => {
          const report = (data.reports || []).find((r) => r.ticker === t);
          return [t, report || { ticker: t, name: fund.holdings[t]?.name || t }];
        }),
      ]
    ).values(),
  ];

  tickerSelect.innerHTML = options
    .map((r) => `<option value="${esc(r.ticker)}">${esc(r.name || r.ticker)} (${esc(r.ticker)})</option>`)
    .join("");

  const syncPrice = async () => {
    const ticker = form.ticker.value;
    const report = (data.reports || []).find((r) => r.ticker === ticker);
    const price = await fetchLastPrice(ticker, report);
    if (price != null) form.price.value = price;
    const plan = report?.trade_plan;
    if (plan?.tactical_stop_loss != null) form.stop_loss.value = plan.tactical_stop_loss;
    if (plan?.tactical_take_profit != null) form.take_profit.value = plan.tactical_take_profit;
    const hint = document.getElementById("paper-trade-hint");
    hint.textContent = `Cash available ${money(fund.cash)} · NAV ${money(
      paperNav(fund, { [ticker]: Number(form.price.value) || 0 })
    )} · sizing: shares, £ cash, or % of NAV`;
  };

  form.side_select.value = "buy";
  form.sizing_mode.value = "cash";
  form.amount.value = "";
  form.notes.value = "";
  form.ticker.onchange = syncPrice;
  form.onsubmit = (event) => {
    event.preventDefault();
    try {
      const ticker = form.ticker.value;
      const report = (data.reports || []).find((r) => r.ticker === ticker);
      const side = form.side_select.value;
      const payload = {
        ticker,
        price: Number(form.price.value),
        sizingMode: form.sizing_mode.value,
        amount: Number(form.amount.value),
        name: report?.name || fund.holdings[ticker]?.name || ticker,
        sector: report?.sector || fund.holdings[ticker]?.sector || "",
        stopLoss: form.stop_loss.value,
        takeProfit: form.take_profit.value,
        note: form.notes.value.trim(),
        prices: {},
      };
      if (side === "buy") paperBuy(fund, payload);
      else paperSell(fund, payload);
      recordPaperMark(fund, { [ticker]: payload.price }, "Manual trade");
      savePaperBook(book);
      dialog.close();
      renderPaperFunds(data);
    } catch (err) {
      window.alert(err.message || String(err));
    }
  };

  document.getElementById("paper-trade-cancel").onclick = () => dialog.close();
  await syncPrice();
  dialog.showModal();
}

window.renderPaperFunds = renderPaperFunds;

