/* Parallel cash-backed paper funds (browser-local). */

const PAPER_FUND_STORAGE_KEY = "ftseValueInvestor.paperFunds.v1";
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
  return candidates
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

function renderPaperFundsSection(data, pricesByFund) {
  const book = loadPaperBook();
  if (!book.funds.length) {
    return `
      <div class="card paper-funds-card">
        <h3>Paper fund simulations</h3>
        <p>Run parallel cash-backed simulations with an initial pot and optional monthly deposits. Buys can be sized by shares, cash, or % of fund value; marks follow published chart prices.</p>
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
        <p class="small muted">Creates Immediate, Technical cues, and Automated funds with the same cash rules so you can compare them.</p>
      </div>`;
  }

  const active = activePaperFund(book);
  const comparisonRows = book.funds
    .map((fund) => {
      const prices = pricesByFund?.[fund.config.id] || {};
      applyPaperDeposits(fund, paperNowIso());
      const perf = paperPerformance(fund, prices);
      return { fund, perf };
    })
    .sort((a, b) => b.perf.total_return - a.perf.total_return);

  // Persist deposits applied during render comparison
  savePaperBook(book);

  const activePrices = pricesByFund?.[active.config.id] || {};
  const activePerf = paperPerformance(active, activePrices);
  const holdingRows = Object.values(active.holdings || {})
    .map((pos) => {
      const mark = paperPositionMark(pos, activePrices);
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
          pos.take_profit != null ? `Target ${money(pos.take_profit)}` : ""
        }</td>
      </tr>`;
    })
    .join("") || `<tr><td colspan="7" class="muted">No holdings yet.</td></tr>`;

  const tradeRows = (active.trades || [])
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
    .join("") || `<tr><td colspan="7" class="muted">No trades yet.</td></tr>`;

  const compareTable = comparisonRows
    .map(({ fund, perf }) => {
      const selected = fund.config.id === active.config.id ? "selected" : "";
      return `<tr class="${selected}">
        <td>
          <button type="button" class="btn btn-link" data-paper-select="${esc(fund.config.id)}">
            ${esc(fund.config.name)}
          </button>
          <div class="small muted">${esc(PAPER_STRATEGY_LABELS[fund.config.mode] || fund.config.mode)}</div>
        </td>
        <td>${money(perf.portfolio_value)}</td>
        <td>${money(perf.cash)}</td>
        <td>${money(perf.contributed_capital)}</td>
        <td class="${perf.gain >= 0 ? "pos" : "neg"}">${(perf.total_return * 100).toFixed(1)}%</td>
        <td>${perf.positions}</td>
      </tr>`;
    })
    .join("");

  const modeActions =
    active.config.mode === "automated"
      ? `<button type="button" class="btn btn-primary" id="paper-auto-btn">Run automated rebalance</button>`
      : active.config.mode === "technical"
        ? `<button type="button" class="btn btn-primary" id="paper-tech-btn">Run technical pass</button>`
        : `<button type="button" class="btn btn-primary" id="paper-trade-btn">Buy / sell</button>`;

  return `
    <div class="card paper-funds-card">
      <div class="paper-funds-header">
        <div>
          <h3>Paper fund simulations</h3>
          <p class="small muted">Parallel pots share the same starting cash and deposit rules. Performance is mark-to-market vs capital contributed (initial + deposits).</p>
        </div>
        <div class="paper-funds-actions">
          ${modeActions}
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
            </tr>
          </thead>
          <tbody>${compareTable}</tbody>
        </table>
      </div>

      <div class="paper-active-summary grid" style="margin-top:1rem">
        <div>
          <div class="small muted">Active fund</div>
          <strong>${esc(active.config.name)}</strong>
          <div class="small muted">${esc(PAPER_STRATEGY_LABELS[active.config.mode] || active.config.mode)} · cost ${(
            Number(active.config.trade_cost_pct) * 100
          ).toFixed(1)}% · max ${active.config.max_positions} names</div>
        </div>
        <div>
          <div class="small muted">NAV</div>
          <strong>${money(activePerf.portfolio_value)}</strong>
        </div>
        <div>
          <div class="small muted">Cash available</div>
          <strong>${money(activePerf.cash)}</strong>
        </div>
        <div>
          <div class="small muted">Return vs contributed</div>
          <strong class="${activePerf.gain >= 0 ? "pos" : "neg"}">${(activePerf.total_return * 100).toFixed(1)}% (${money(
            activePerf.gain
          )})</strong>
        </div>
      </div>

      <h4 style="margin-top:1rem">Holdings</h4>
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
          <tbody>${holdingRows}</tbody>
        </table>
      </div>

      <h4 style="margin-top:1rem">Recent trades</h4>
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
          <tbody>${tradeRows}</tbody>
        </table>
      </div>
      <p class="small muted">Manual fund: discretionary buys/sells. Technical: stop/target exits and core-limit entries. Automated: equal-weight rebalance into top buy-tier names. All constrained by cash and max positions.</p>
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

async function renderPaperFunds(data) {
  const mount = document.getElementById("paper-funds-root");
  if (!mount) return;
  const book = loadPaperBook();
  let pricesByFund = {};
  if (book.funds.length) {
    mount.innerHTML = `<div class="card"><p class="muted">Loading paper fund marks…</p></div>`;
    pricesByFund = await pricesForBook(book, data);
  }
  const liveMount = document.getElementById("paper-funds-root");
  if (!liveMount) return;
  liveMount.innerHTML = renderPaperFundsSection(data, pricesByFund);
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
      renderPaperFunds(data);
    });
    return;
  }

  document.querySelectorAll("[data-paper-select]").forEach((button) => {
    button.addEventListener("click", () => {
      const book = loadPaperBook();
      book.active_fund_id = button.dataset.paperSelect;
      savePaperBook(book);
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
        const fund = activePaperFund(book);
        if (!fund || fund.config.mode !== "automated") return;
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
        const fund = activePaperFund(book);
        if (!fund || fund.config.mode !== "technical") return;
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
  const fund = activePaperFund(book);
  if (!fund) return;
  const dialog = ensurePaperTradeDialog();
  const form = document.getElementById("paper-trade-form");
  const tickerSelect = form.ticker;
  const buyTier = (data.reports || []).filter((r) => r.signal === "strong_buy" || r.signal === "buy");
  const held = Object.keys(fund.holdings);
  const options = [...new Map([...buyTier.map((r) => [r.ticker, r]), ...held.map((t) => {
    const report = (data.reports || []).find((r) => r.ticker === t);
    return [t, report || { ticker: t, name: fund.holdings[t]?.name || t }];
  }])].values()];

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
