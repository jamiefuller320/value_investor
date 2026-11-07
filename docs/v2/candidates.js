/* Strategy dashboard v2 — Candidates tab (strategy parts 1–4).
 * Observe-only: reads published stores, never writes. Absent data is missing, never a pass.
 * Registers on window.DashboardV2Tabs. Pure join helpers hang off window.__dashboardV2Candidates.
 */
(function () {
  "use strict";

  const FTSE_MARKET = "ftse350";
  const PAGE_SIZE = 200;
  const NOT_MEASURED = "not yet measured";
  const PENDING_ENTRY = "pending forward job";
  const CHECK_ORDER = ["cheap", "decline", "sector", "inputs", "entryLow"];
  const BUY_SIGNALS = { buy: true, strong_buy: true };

  const TIPS = {
    buyTier:
      "Screen labels buy and strong buy that mark the value set a name must sit in for strategy eligibility.",
    ftse350:
      "Live UK screener universe kept until stage 4; separate from offline multi-market library growth.",
    f9:
      "Named-stock capital eligibility: filing body, FCF basis, overlay bind, memo freshness, plus market ingest gates when opening a book—not index membership.",
    filingsBody:
      "Extracted text from regulatory filings stored for research and bind checks, not just filing metadata counts.",
    fcfBasis:
      "Bound free-cash-flow accounting basis on a name so overlays and decisions use consistent cash-flow definitions.",
    overlayBind:
      "Research overlay present and applied so adjusted signals and accumulate paths are consistent on a name.",
    memoFreshness: "Research memo recency bind field so decisions do not rely on stale write-ups.",
    strongBuy: "Strongest screen buy signal within the value set alongside ordinary buy.",
    shortTermLow:
      "Buy only at a short-term price low: momentum washed out, and the close is the lowest in 10 sessions. Membership of the buy tier is not itself the buy.",
  };

  const BIND_DEFS = [
    { key: "key_filing_bodies", label: "Filings body", tip: TIPS.filingsBody },
    { key: "fcf_basis_bound", label: "FCF basis", tip: TIPS.fcfBasis },
    { key: "overlay_bound", label: "Overlay bind", tip: TIPS.overlayBind },
    { key: "memo_recent", label: "Memo freshness", tip: TIPS.memoFreshness },
  ];

  const CHECK_HEADS = [
    { key: "cheap", label: "Cheap", tip: TIPS.buyTier },
    { key: "decline", label: "Not declining", tip: "No sign of declining operating performance. Missing data does not pass." },
    { key: "sector", label: "Sector sound", tip: "The sector as a whole is not in a broad price or earnings decline." },
    { key: "inputs", label: "Input quality", tip: TIPS.f9 },
    { key: "entryLow", label: "Short-term low", tip: TIPS.shortTermLow },
  ];

  const DECLINE_CHECK_LABELS = {
    revenue: "Revenue",
    interim_revenue: "Interim revenue",
    operating_margin: "Operating margin",
    eps_annual: "Annual earnings per share",
    eps_interim: "Interim earnings per share",
    fcf: "Free cash flow",
    dividend: "Dividend",
    profit_warning: "Profit warning or guidance cut",
  };

  /** Plain-English labels for forward-job outcome codes. Unknown codes stay unclassified. */
  const OUTCOME_LABELS = {
    filled: "A buy would have been filled on this signal",
    pending_fill: "A buy is waiting for the next session",
    late_signal: "The signal arrived after the next session had already closed, so it was not bought",
    memo_not_ready: "No fresh research memo was ready in time, so it was not bought",
    memo_blocked: "The research memo blocked the buy",
    gap_drop: "The next trading session was too far after the signal, so the buy was dropped",
    already_open_skip: "This name is already held, so no second buy was opened",
    cooldown_skip: "The cooling-off period after a sale has not ended, so no new buy was opened",
    no_chart: "No usable price chart",
    no_session_on_or_after_start: "No trading session on or after the book started",
    not_buy_tier: "Not in the buy tier on that session",
    gate: "Stopped by the operating-performance or sector check",
    f9: "Input quality checks failed",
    price: "Not at a short-term low",
    not_in_universe: "Not in the book's universe on that session",
    research_failed: "Research said the reason for owning it had failed, so it was not bought",
    not_graduated: "This market has not reached its ingest threshold, so the book cannot buy it",
    stale_chart: "The price chart is too old",
    thinned: "The price history is too sparse",
    chart_not_daily: "The price history is not a daily series",
    recovery_cap:
      "The checks passed, but new buys were blocked because too many open trades are still waiting to get going",
    learning_pool_excluded:
      "The screen lists this name, but the book's universe leaves it out because this market's learning set excludes it",
    not_in_book_screen: "The screen lists this name, but the book's saved universe does not include it",
    no_next_bar: "There is no later price bar to fill a buy",
    insufficient_data: "Not enough data to pass the checks",
  };

  // Last close and moving averages only. Stop, target and the old buy limits
  // are the screen's trade plan; charts.js would label the stop and target as exits.
  const SCREEN_PLAN_LEVELS = ["last", "sma50", "sma200"];

  const ui = {
    market: FTSE_MARKET,
    onlyPassing: false,
    limit: PAGE_SIZE,
    expanded: Object.create(null),
    charts: Object.create(null),
  };

  let viewCache = null;

  function outcomeLabel(code) {
    const key = String(code || "").trim();
    if (!key) return "No forward-job result for this name";
    if (Object.prototype.hasOwnProperty.call(OUTCOME_LABELS, key)) return OUTCOME_LABELS[key];
    return "Forward job recorded an unclassified result (" + key + ")";
  }

  function screenPlanLevels(levels) {
    const src = levels && typeof levels === "object" ? levels : {};
    const out = {};
    for (let i = 0; i < SCREEN_PLAN_LEVELS.length; i += 1) {
      const key = SCREEN_PLAN_LEVELS[i];
      if (src[key] != null) out[key] = src[key];
    }
    return out;
  }

  function asTickerMap(value) {
    const map = Object.create(null);
    if (!value) return map;
    if (Array.isArray(value)) {
      for (let i = 0; i < value.length; i += 1) {
        const row = value[i];
        if (row && row.ticker) map[String(row.ticker).trim()] = row;
      }
      return map;
    }
    if (typeof value === "object") {
      const keys = Object.keys(value);
      for (let i = 0; i < keys.length; i += 1) {
        const row = value[keys[i]];
        if (!row || typeof row !== "object") continue;
        map[keys[i]] = row;
        if (row.ticker) map[String(row.ticker).trim()] = row;
      }
    }
    return map;
  }

  function marketLabel(marketStatus, marketId) {
    const markets = marketStatus && Array.isArray(marketStatus.markets) ? marketStatus.markets : [];
    for (let i = 0; i < markets.length; i += 1) {
      const row = markets[i];
      if (row && row.market_id === marketId && row.label) return String(row.label);
    }
    if (marketId === FTSE_MARKET) return "FTSE 350";
    return String(marketId || "");
  }

  function indexForward(forwardStatus) {
    if (!forwardStatus || !Array.isArray(forwardStatus.candidates)) return null;
    const map = new Map();
    const rows = forwardStatus.candidates;
    for (let i = 0; i < rows.length; i += 1) {
      const row = rows[i];
      if (!row || typeof row !== "object") continue;
      const market = String(row.market || "").trim();
      const ticker = String(row.ticker || "").trim();
      if (!market || !ticker) continue;
      map.set(market + "|" + ticker, row);
      map.set(market + "|" + ticker.toUpperCase(), row);
    }
    return map;
  }

  function indexSector(sectorGate) {
    if (!sectorGate || typeof sectorGate !== "object") return null;
    const out = Object.create(null);
    const byMarket = sectorGate.names_by_market;
    if (byMarket && typeof byMarket === "object") {
      const markets = Object.keys(byMarket);
      for (let i = 0; i < markets.length; i += 1) {
        out[markets[i]] = asTickerMap(byMarket[markets[i]]);
      }
    }
    const ftseNames = asTickerMap(sectorGate.names);
    if (!out[FTSE_MARKET]) out[FTSE_MARKET] = ftseNames;
    else {
      const keys = Object.keys(ftseNames);
      for (let i = 0; i < keys.length; i += 1) {
        if (!out[FTSE_MARKET][keys[i]]) out[FTSE_MARKET][keys[i]] = ftseNames[keys[i]];
      }
    }
    return out;
  }

  function lookupSectorEntry(sectorIndex, market, ticker) {
    if (!sectorIndex) return null;
    const bucket = sectorIndex[market];
    if (!bucket) return null;
    return bucket[ticker] || bucket[String(ticker).toUpperCase()] || null;
  }

  function lookupSectorRecord(sectorGate, entry, market) {
    if (!sectorGate || !entry) return null;
    const sectors = sectorGate.sectors;
    if (!sectors || typeof sectors !== "object") return null;
    const key = entry.deciding_sector_key || (market && entry.sector ? market + ":" + entry.sector : "");
    if (key && sectors[key]) return sectors[key];
    if (entry.sector && sectors[market + ":" + entry.sector]) return sectors[market + ":" + entry.sector];
    return null;
  }

  function classifyCheap(invRow) {
    const signal = String(invRow.signal || "").trim().toLowerCase();
    if (BUY_SIGNALS[signal]) {
      return { status: "pass", label: "pass", source: "present", signal: signal };
    }
    if (signal) return { status: "fail", label: "fail", source: "present", signal: signal };
    if (invRow.in_buy_tier === true) {
      return { status: "pass", label: "pass", source: "present", signal: "" };
    }
    return { status: "missing", label: "missing", source: "present", signal: "" };
  }

  function classifyDecline(entry, gatePresent) {
    if (!gatePresent) return { status: "missing", label: "missing", source: "absent" };
    if (!entry || typeof entry !== "object") {
      return { status: "missing", label: "missing", source: "present" };
    }
    const verdict = String(entry.verdict || "");
    if (verdict === "clear") return { status: "pass", label: "pass", source: "present" };
    if (verdict === "declining") return { status: "fail", label: "fail", source: "present" };
    if (verdict === "insufficient_data") {
      return { status: "missing", label: "insufficient data", source: "present" };
    }
    return { status: "missing", label: "missing", source: "present" };
  }

  function classifySector(entry, gatePresent) {
    if (!gatePresent) return { status: "missing", label: "missing", source: "absent" };
    if (!entry || typeof entry !== "object") {
      return { status: "missing", label: "missing", source: "present" };
    }
    const verdict = String(entry.sector_verdict || entry.verdict || "");
    if (verdict === "sound") return { status: "pass", label: "pass", source: "present" };
    if (verdict === "headwind") return { status: "fail", label: "fail", source: "present" };
    if (verdict === "insufficient_data") {
      return { status: "missing", label: "insufficient data", source: "present" };
    }
    return { status: "missing", label: "missing", source: "present" };
  }

  function classifyInputs(invRow) {
    const binds = [];
    for (let i = 0; i < BIND_DEFS.length; i += 1) {
      const def = BIND_DEFS[i];
      const value = invRow ? invRow[def.key] : undefined;
      let status = "missing";
      if (value === true) status = "pass";
      else if (value === false) status = "fail";
      binds.push({ key: def.key, label: def.label, tip: def.tip, status: status });
    }
    let status = "pass";
    let label = "pass";
    if (binds.some(function (bind) { return bind.status === "fail"; })) {
      status = "fail";
      label = "fail";
    } else if (binds.some(function (bind) { return bind.status === "missing"; })) {
      status = "missing";
      label = "missing";
    }
    return { status: status, label: label, source: invRow ? "present" : "absent", binds: binds };
  }

  function classifyEntry(forwardMap, market, ticker) {
    if (forwardMap === null) {
      return { status: "pending", label: PENDING_ENTRY, source: "absent", forward: null };
    }
    const row = forwardMap.get(market + "|" + ticker) || forwardMap.get(market + "|" + String(ticker).toUpperCase()) || null;
    if (!row) return { status: "missing", label: "missing", source: "present", forward: null };
    if (row.price_rule === true) return { status: "pass", label: "pass", source: "present", forward: row };
    if (row.price_rule === false || row.outcome === "price") {
      return { status: "fail", label: "fail", source: "present", forward: row };
    }
    return { status: "missing", label: "missing", source: "present", forward: row };
  }

  const WHY_PLAIN = {
    interim_revenue_missing: "No interim revenue comparison",
    operating_income_missing_or_stale: "Operating income is missing or too old",
    revenue_missing_or_stale: "Revenue is missing or too old",
    financials_missing: "No financial statements",
    financials_fetched_after_as_of: "Statements were fetched after the as-of date",
    eps_missing_or_stale: "Earnings per share are missing or too old",
  };

  function plainWhy(why) {
    const text = clip(why);
    if (!text) return "";
    return WHY_PLAIN[text] || text;
  }

  function formatPct(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "";
    const pct = n * 100;
    const digits = Math.abs(pct) >= 10 ? 0 : 1;
    const body = Math.abs(pct).toFixed(digits);
    if (pct > 0) return "+" + body + "%";
    if (pct < 0) return "−" + body + "%";
    return "0%";
  }

  function formatPp(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "";
    const pp = n * 100;
    const digits = Math.abs(pp) >= 10 ? 0 : 1;
    const body = Math.abs(pp).toFixed(digits);
    if (pp > 0) return "+" + body + " percentage points";
    if (pp < 0) return "−" + body + " percentage points";
    return "0 percentage points";
  }

  function formatNum(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "";
    const abs = Math.abs(n);
    const sign = n < 0 ? "−" : "";
    if (abs >= 1e9) return sign + (abs / 1e9).toFixed(2) + "bn";
    if (abs >= 1e6) return sign + (abs / 1e6).toFixed(1) + "m";
    if (abs >= 1000) return sign + String(Math.round(abs));
    const rounded = Math.round(abs * 100) / 100;
    return sign + String(rounded);
  }

  function clip(text) {
    const s = String(text == null ? "" : text).replace(/\s+/g, " ").trim();
    if (s.length <= 220) return s;
    return s.slice(0, 217) + "...";
  }

  function declineCheckLine(name, check) {
    const fallback = DECLINE_CHECK_LABELS[name] || name;
    const rawLabel = check && check.label ? String(check.label) : "";
    const label = rawLabel && rawLabel.length <= 80 ? rawLabel : fallback;
    if (!check || typeof check !== "object") return { label: label, value: "missing" };
    if (check.evaluable === false) {
      const why = plainWhy(check.why);
      return { label: label, value: why || "not evaluable" };
    }
    const bits = [];
    if (check.latest_year != null) bits.push("latest year " + check.latest_year);
    if (check.change_pct != null && formatPct(check.change_pct)) bits.push("change " + formatPct(check.change_pct));
    if (check.prior_change_pct != null && formatPct(check.prior_change_pct)) {
      bits.push("prior change " + formatPct(check.prior_change_pct));
    }
    if (check.change_pp != null && formatPp(check.change_pp)) bits.push("margin change " + formatPp(check.change_pp));
    if (check.latest_margin != null && formatPct(check.latest_margin)) bits.push("margin " + formatPct(check.latest_margin));
    if (check.latest != null && check.prior != null) {
      bits.push(formatNum(check.latest) + " vs " + formatNum(check.prior));
    }
    if (check.period_end) bits.push("period ending " + String(check.period_end).slice(0, 10));
    if (check.fired === true) bits.push("decline signal");
    else if (check.fired === false) bits.push("no decline signal");
    if (!bits.length && check.scanned_items != null) bits.push(check.scanned_items + " filings scanned");
    return { label: label, value: bits.length ? bits.join("; ") : "evaluated" };
  }

  function declineDetail(entry, gate, rowMarket) {
    if (!gate) {
      return { asOf: null, storedMarket: null, lines: [], reasons: ["Operating-performance check is not available yet."] };
    }
    if (!entry) {
      return {
        asOf: gate.as_of || gate.generated_at || null,
        storedMarket: null,
        lines: [],
        reasons: ["No operating-performance row for this name. Missing, not a pass."],
      };
    }
    const lines = [];
    const checks = entry.checks && typeof entry.checks === "object" ? entry.checks : {};
    const names = Object.keys(checks);
    for (let i = 0; i < names.length; i += 1) {
      lines.push(declineCheckLine(names[i], checks[names[i]]));
    }
    const reasons = [];
    const raw = Array.isArray(entry.reasons) ? entry.reasons : [];
    for (let i = 0; i < raw.length && reasons.length < 8; i += 1) {
      const reason = raw[i];
      if (!reason) continue;
      const text = typeof reason === "string" ? reason : reason.detail || reason.code || "";
      if (text) reasons.push(clip(text));
    }
    if (String(entry.verdict || "") === "insufficient_data" && !reasons.length) {
      reasons.push("Not enough operating data to judge. This is not a pass.");
    }
    let storedMarket = entry.market ? String(entry.market) : null;
    if (storedMarket && rowMarket && storedMarket === rowMarket) storedMarket = null;
    return {
      asOf: gate.as_of || gate.generated_at || null,
      storedMarket: storedMarket,
      lines: lines,
      reasons: reasons,
    };
  }

  function sectorMetricLines(metrics) {
    if (!metrics || typeof metrics !== "object") return ["Sector figures are missing."];
    const lines = [];
    if (metrics.member_count != null) lines.push("Members in the sector: " + metrics.member_count);
    if (metrics.as_of) lines.push("Figures dated " + String(metrics.as_of).slice(0, 10));
    if (metrics.price_below_sma200_share != null && formatPct(metrics.price_below_sma200_share)) {
      lines.push("Share of members below their 200-day average: " + formatPct(metrics.price_below_sma200_share));
    }
    if (metrics.sector_return_63d != null && formatPct(metrics.sector_return_63d)) {
      lines.push("63-session sector return: " + formatPct(metrics.sector_return_63d));
    }
    if (metrics.sector_return_126d != null && formatPct(metrics.sector_return_126d)) {
      lines.push("126-session sector return: " + formatPct(metrics.sector_return_126d));
    }
    if (metrics.earnings_declining_share != null && formatPct(metrics.earnings_declining_share)) {
      lines.push("Share with declining earnings: " + formatPct(metrics.earnings_declining_share));
    }
    if (metrics.operating_declining_share != null && formatPct(metrics.operating_declining_share)) {
      lines.push("Share with declining operating performance: " + formatPct(metrics.operating_declining_share));
    }
    if (!lines.length) lines.push("Sector figures are missing.");
    return lines;
  }

  function sectorDetail(entry, record, gate) {
    if (!gate) {
      return { asOf: null, name: "", lines: [], reasons: ["Sector check is not available yet."] };
    }
    if (!entry) {
      return {
        asOf: gate.as_of || gate.generated_at || null,
        name: "",
        lines: [],
        reasons: ["No sector row for this name. Missing, not a pass."],
      };
    }
    const reasons = [];
    const raw = record && Array.isArray(record.reasons) ? record.reasons : [];
    for (let i = 0; i < raw.length && reasons.length < 6; i += 1) {
      const reason = raw[i];
      const text = reason && (reason.detail || reason.code);
      if (text) reasons.push(clip(text));
    }
    if (String(entry.sector_verdict || "") === "insufficient_data" && !reasons.length) {
      reasons.push("Not enough sector data to judge. This is not a pass.");
    }
    const metrics = record && record.metrics;
    return {
      asOf: (metrics && metrics.as_of) || gate.as_of || gate.generated_at || null,
      name: entry.sector ? String(entry.sector) : "",
      lines: sectorMetricLines(metrics),
      reasons: reasons,
    };
  }

  function entryNarrative(entryCheck) {
    if (!entryCheck || entryCheck.status === "pending") {
      return "Short-term low is pending the forward job, so it is not yet measured.";
    }
    const row = entryCheck.forward;
    if (!row) return "This name is not on the forward job's candidate list. Missing, not a pass.";
    const parts = [outcomeLabel(row.outcome)];
    if (row.session) parts.push("Session " + String(row.session).slice(0, 10) + ".");
    if (row.price_rule === true) parts.push("The short-term low fired.");
    else if (row.price_rule === false) parts.push("The short-term low did not fire.");
    else parts.push("The short-term low was not measured for this name.");
    if (row.f9 === "pass") parts.push("The forward job recorded input quality as passing on that session.");
    else if (Array.isArray(row.f9) && row.f9.length) {
      const names = row.f9.map(function (key) {
        for (let i = 0; i < BIND_DEFS.length; i += 1) {
          if (BIND_DEFS[i].key === key) return BIND_DEFS[i].label;
        }
        return String(key);
      });
      parts.push("The forward job recorded failing input checks: " + names.join(", ") + ".");
    }
    return parts.join(" ");
  }

  function countPasses(checks) {
    let passCount = 0;
    let measuredCount = 0;
    for (let i = 0; i < CHECK_ORDER.length; i += 1) {
      const status = checks[CHECK_ORDER[i]].status;
      if (status === "pending") continue;
      measuredCount += 1;
      if (status === "pass") passCount += 1;
    }
    return { passCount: passCount, measuredCount: measuredCount };
  }

  function t212Of(invRow) {
    if (invRow && invRow.tradable_on_t212 === true) return { status: "listed", label: "listed" };
    if (invRow && invRow.tradable_on_t212 === false) return { status: "not_listed", label: "not listed" };
    return { status: "unknown", label: "not yet known" };
  }

  function buildOneRow(invRow, market, label, lookups) {
    const ticker = String((invRow && invRow.ticker) || "").trim();
    const declineEntry = lookups.declineMap ? lookups.declineMap[ticker] || lookups.declineMap[ticker.toUpperCase()] || null : null;
    const sectorEntry = lookupSectorEntry(lookups.sectorIndex, market, ticker);
    const sectorRecord = lookupSectorRecord(lookups.sectorGate, sectorEntry, market);
    const cheap = classifyCheap(invRow || {});
    const decline = classifyDecline(declineEntry, lookups.declinePresent);
    const sector = classifySector(sectorEntry, lookups.sectorPresent);
    const inputs = classifyInputs(invRow);
    const entryLow = classifyEntry(lookups.forwardMap, market, ticker);
    const checks = { cheap: cheap, decline: decline, sector: sector, inputs: inputs, entryLow: entryLow };
    const counts = countPasses(checks);
    const sectorName = (sectorEntry && sectorEntry.sector) || (declineEntry && declineEntry.sector) || "";
    const bindFlags = {};
    for (let i = 0; i < inputs.binds.length; i += 1) {
      const bind = inputs.binds[i];
      bindFlags[bind.key] = bind.status === "pass" ? true : bind.status === "fail" ? false : null;
    }
    return {
      market: market,
      marketLabel: label,
      ticker: ticker,
      name: invRow && invRow.name ? String(invRow.name) : "",
      sector: sectorName ? String(sectorName) : "",
      signal: cheap.signal || String((invRow && invRow.signal) || "").toLowerCase(),
      checks: checks,
      passCount: counts.passCount,
      measuredCount: counts.measuredCount,
      t212: t212Of(invRow),
      bindFlags: bindFlags,
      detail: {
        signal: cheap.signal,
        decline: declineDetail(declineEntry, lookups.declineGate, market),
        sector: sectorDetail(sectorEntry, sectorRecord, lookups.sectorGate),
        binds: inputs.binds,
        memoAt: invRow && invRow.memo_at ? String(invRow.memo_at) : null,
        memoAgeDays: invRow && invRow.memo_age_days != null ? invRow.memo_age_days : null,
        entryText: entryNarrative(entryLow),
        outcome: entryLow.forward ? entryLow.forward.outcome || null : null,
        session: entryLow.forward && entryLow.forward.session ? String(entryLow.forward.session).slice(0, 10) : null,
      },
    };
  }

  function compareRows(a, b) {
    const aFtse = a.market === FTSE_MARKET ? 0 : 1;
    const bFtse = b.market === FTSE_MARKET ? 0 : 1;
    if (aFtse !== bFtse) return aFtse - bFtse;
    if (a.marketLabel !== b.marketLabel) return a.marketLabel < b.marketLabel ? -1 : 1;
    if (b.passCount !== a.passCount) return b.passCount - a.passCount;
    if (a.ticker !== b.ticker) return a.ticker < b.ticker ? -1 : 1;
    return 0;
  }

  /**
   * Join buy-tier inventories with the operating, sector and (when present) forward roster.
   * @param {object} ctx
   * @returns {object[]}
   */
  function buildCandidateRows(ctx) {
    const source = ctx || {};
    const declineGate = source.declineGate || null;
    const sectorGate = source.sectorGate || null;
    const decisionInv = source.decisionInv || null;
    const libraryInv = source.libraryInv || null;
    const declineMap = declineGate ? asTickerMap(declineGate.names) : null;
    const lookups = {
      declineGate: declineGate,
      declineMap: declineMap,
      declinePresent: !!(declineGate && declineGate.names),
      sectorGate: sectorGate,
      sectorIndex: indexSector(sectorGate),
      sectorPresent: !!(sectorGate && (sectorGate.names_by_market || sectorGate.names || sectorGate.sectors)),
      forwardMap: indexForward(source.forwardStatus),
    };
    const rows = [];
    const ftseRows = decisionInv && Array.isArray(decisionInv.rows) ? decisionInv.rows : [];
    const ftseLabel = marketLabel(source.marketStatus, FTSE_MARKET);
    for (let i = 0; i < ftseRows.length; i += 1) {
      const row = ftseRows[i];
      if (!row || row.in_buy_tier !== true || !row.ticker) continue;
      rows.push(buildOneRow(row, FTSE_MARKET, ftseLabel, lookups));
    }
    const libRows = libraryInv && Array.isArray(libraryInv.rows) ? libraryInv.rows : [];
    for (let i = 0; i < libRows.length; i += 1) {
      const row = libRows[i];
      if (!row || !row.ticker) continue;
      const market = String(row.market_id || "").trim();
      if (!market || market === FTSE_MARKET) continue;
      rows.push(buildOneRow(row, market, marketLabel(source.marketStatus, market), lookups));
    }
    rows.sort(compareRows);
    return rows;
  }

  function oneFunnel(list) {
    const market = list[0].market;
    const label = list[0].marketLabel;
    let pool = list.slice();
    return {
      market: market,
      label: label,
      listed: list.length,
      buyTier: reduce("cheap"),
      notDeclining: reduce("decline"),
      sectorSound: reduce("sector"),
      inputQuality: reduce("inputs"),
      entryLow: reduce("entryLow"),
    };

    function reduce(key) {
      if (pool === null) return NOT_MEASURED;
      if (key === "entryLow" && list.some(function (row) { return row.checks.entryLow.status === "pending"; })) {
        pool = null;
        return NOT_MEASURED;
      }
      if (!pool.length) return 0;
      if (pool.every(function (row) { return row.checks[key].source === "absent"; })) {
        pool = null;
        return NOT_MEASURED;
      }
      const passed = pool.filter(function (row) { return row.checks[key].status === "pass"; });
      pool = passed;
      return passed.length;
    }
  }

  /**
   * Sequential survivor counts per market. A step whose source is absent is
   * "not yet measured", never 0. Later steps stay unmeasured after that.
   * @param {object[]} rows
   * @returns {Record<string, object>}
   */
  function funnelCounts(rows) {
    const grouped = Object.create(null);
    const order = [];
    const list = Array.isArray(rows) ? rows : [];
    for (let i = 0; i < list.length; i += 1) {
      const row = list[i];
      if (!row || !row.market) continue;
      if (!grouped[row.market]) {
        grouped[row.market] = [];
        order.push(row.market);
      }
      grouped[row.market].push(row);
    }
    const out = Object.create(null);
    for (let i = 0; i < order.length; i += 1) {
      out[order[i]] = oneFunnel(grouped[order[i]]);
    }
    return out;
  }

  function passesEveryCheckSoFar(row) {
    if (!row || !row.checks) return false;
    for (let i = 0; i < CHECK_ORDER.length; i += 1) {
      const key = CHECK_ORDER[i];
      const status = row.checks[key].status;
      if (key === "entryLow" && status === "pending") return true;
      if (status !== "pass") return false;
    }
    return true;
  }

  function unmeasuredFunnel(market, label) {
    return {
      market: market,
      label: label,
      listed: NOT_MEASURED,
      buyTier: NOT_MEASURED,
      notDeclining: NOT_MEASURED,
      sectorSound: NOT_MEASURED,
      inputQuality: NOT_MEASURED,
      entryLow: NOT_MEASURED,
    };
  }

  function zeroFunnel(market, label, entryPending) {
    return {
      market: market,
      label: label,
      listed: 0,
      buyTier: 0,
      notDeclining: 0,
      sectorSound: 0,
      inputQuality: 0,
      entryLow: entryPending ? NOT_MEASURED : 0,
    };
  }

  function tipSpan(helpers, text, title) {
    const esc = helpers.esc;
    return '<span class="v2-cand-tip" title="' + esc(title) + '">' + esc(text) + "</span>";
  }

  function verdictClass(status) {
    if (status === "pass") return "v2-cand-verdict v2-cand-pass";
    if (status === "fail") return "v2-cand-verdict v2-cand-fail";
    if (status === "pending") return "v2-cand-verdict v2-cand-pending";
    return "v2-cand-verdict v2-cand-missing";
  }

  function sourceIso(store) {
    if (!store || typeof store !== "object") return { asOf: null, generated: null };
    return {
      asOf: store.as_of || null,
      generated: store.generated_at || store.as_of || null,
    };
  }

  function freshnessItem(helpers, label, iso) {
    const esc = helpers.esc;
    const ms = helpers.parseIsoMs(iso);
    const age = ms == null ? null : helpers.nowMs() - ms;
    const badge = helpers.freshnessDailyStore(age);
    const shown = iso ? helpers.displayDate(iso) : "not yet available";
    return (
      "<li><span><strong>" +
      esc(label) +
      "</strong> — " +
      esc(shown) +
      '</span> <span class="' +
      esc(badge.cls) +
      '">' +
      esc(badge.label) +
      "</span></li>"
    );
  }

  function sourceStrip(ctx, helpers) {
    const parts = [
      freshnessItem(helpers, "FTSE screen buys", sourceIso(ctx.decisionInv).generated),
      freshnessItem(helpers, "Library screen buys", sourceIso(ctx.libraryInv).generated),
      freshnessItem(helpers, "Operating check", sourceIso(ctx.declineGate).generated),
      freshnessItem(helpers, "Sector check", sourceIso(ctx.sectorGate).generated),
    ];
    if (ctx.forwardStatus && Array.isArray(ctx.forwardStatus.candidates)) {
      const iso = ctx.forwardStatus.generated_at || ctx.forwardStatus.as_of || null;
      parts.push(freshnessItem(helpers, "Short-term low", iso));
    } else {
      parts.push(
        '<li><span><strong>Short-term low</strong> — ' +
          helpers.esc(PENDING_ENTRY) +
          '</span> <span class="v2-badge">unknown</span></li>'
      );
    }
    return '<ul class="v2-freshness-list v2-cand-sources">' + parts.join("") + "</ul>";
  }

  function formatCount(value) {
    return value === NOT_MEASURED ? NOT_MEASURED : String(value);
  }

  function renderSources(ctx, helpers) {
    const decline = sourceIso(ctx.declineGate);
    const sector = sourceIso(ctx.sectorGate);
    const ftse = sourceIso(ctx.decisionInv);
    const lib = sourceIso(ctx.libraryInv);
    const fwd = ctx.forwardStatus;
    const fwdIso = fwd && (fwd.generated_at || fwd.as_of) ? fwd.generated_at || fwd.as_of : null;
    return (
      '<div class="v2-card">' +
      "<h2>Where this list comes from</h2>" +
      '<p class="v2-panel-meta">Each check uses the store dated below. A missing store is not treated as a pass.</p>' +
      '<ul class="v2-freshness-list">' +
      freshnessItem(helpers, "FTSE screen buys and input quality", ftse.generated) +
      freshnessItem(helpers, "Library screen buys and input quality", lib.generated) +
      freshnessItem(helpers, "Operating performance (as of " + (decline.asOf ? helpers.displayDate(decline.asOf) : "not yet available") + ")", decline.generated) +
      freshnessItem(helpers, "Sector soundness (as of " + (sector.asOf ? helpers.displayDate(sector.asOf) : "not yet available") + ")", sector.generated) +
      (fwd
        ? freshnessItem(helpers, "Short-term low (forward job)", fwdIso)
        : '<li><span><strong>Short-term low</strong> — ' +
          helpers.esc(PENDING_ENTRY) +
          '</span> <span class="v2-badge">unknown</span></li>') +
      "</ul></div>"
    );
  }

  function marketsFor(ctx, rows) {
    const ftseKnown = !!(ctx.decisionInv && Array.isArray(ctx.decisionInv.rows));
    const seen = Object.create(null);
    const rest = [];
    for (let i = 0; i < rows.length; i += 1) {
      const market = rows[i].market;
      if (!market || market === FTSE_MARKET || seen[market]) continue;
      seen[market] = rows[i].marketLabel || marketLabel(ctx.marketStatus, market);
      rest.push(market);
    }
    rest.sort(function (a, b) {
      const la = seen[a];
      const lb = seen[b];
      if (la !== lb) return la < lb ? -1 : 1;
      return a < b ? -1 : 1;
    });
    const markets = [
      {
        id: FTSE_MARKET,
        label: marketLabel(ctx.marketStatus, FTSE_MARKET),
        known: ftseKnown,
      },
    ];
    for (let i = 0; i < rest.length; i += 1) {
      markets.push({ id: rest[i], label: seen[rest[i]], known: true });
    }
    return markets;
  }

  function funnelForMarket(ctx, rows, market, label) {
    const list = [];
    for (let i = 0; i < rows.length; i += 1) {
      if (rows[i].market === market) list.push(rows[i]);
    }
    const ftseKnown = !!(ctx.decisionInv && Array.isArray(ctx.decisionInv.rows));
    const libraryKnown = !!(ctx.libraryInv && Array.isArray(ctx.libraryInv.rows));
    const entryPending = !ctx.forwardStatus || !Array.isArray(ctx.forwardStatus.candidates);
    if (!list.length) {
      if ((market === FTSE_MARKET && ftseKnown) || (market !== FTSE_MARKET && libraryKnown)) {
        return zeroFunnel(market, label, entryPending);
      }
      return unmeasuredFunnel(market, label);
    }
    const funnels = funnelCounts(list);
    return funnels[market] || unmeasuredFunnel(market, label);
  }

  function renderFunnel(helpers, funnel) {
    const steps = [
      { label: "Buy tier", tip: TIPS.buyTier, value: funnel.buyTier },
      { label: "Not declining", tip: CHECK_HEADS[1].tip, value: funnel.notDeclining },
      { label: "Sector sound", tip: CHECK_HEADS[2].tip, value: funnel.sectorSound },
      { label: "Input quality", tip: TIPS.f9, value: funnel.inputQuality },
      { label: "Short-term low", tip: TIPS.shortTermLow, value: funnel.entryLow },
    ];
    const parts = [];
    for (let i = 0; i < steps.length; i += 1) {
      const step = steps[i];
      const unmeasured = step.value === NOT_MEASURED;
      parts.push(
        '<div class="v2-cand-step' +
          (unmeasured ? " v2-cand-step-open" : "") +
          '"><span class="v2-cand-step-label">' +
          tipSpan(helpers, step.label, step.tip) +
          '</span><strong class="' +
          (unmeasured ? "v2-cand-unmeasured" : "v2-cand-count") +
          '">' +
          helpers.esc(formatCount(step.value)) +
          "</strong></div>"
      );
      if (i < steps.length - 1) parts.push('<span class="v2-cand-arrow" aria-hidden="true">→</span>');
    }
    return '<div class="v2-cand-funnel" role="group" aria-label="Buy-tier funnel">' + parts.join("") + "</div>";
  }

  function signalPhrase(signal) {
    if (signal === "strong_buy") return "strong buy";
    if (signal === "buy") return "buy";
    if (!signal) return "not recorded";
    return String(signal).replace(/_/g, " ");
  }

  function renderDetail(helpers, row) {
    const esc = helpers.esc;
    const decline = row.detail.decline;
    const sector = row.detail.sector;
    const declineLines = decline.lines
      .map(function (line) {
        return "<li><strong>" + esc(line.label) + "</strong> — " + esc(line.value) + "</li>";
      })
      .join("");
    const declineReasons = decline.reasons
      .map(function (text) {
        return "<li>" + esc(text) + "</li>";
      })
      .join("");
    const sectorLines = sector.lines
      .map(function (text) {
        return "<li>" + esc(text) + "</li>";
      })
      .join("");
    const sectorReasons = sector.reasons
      .map(function (text) {
        return "<li>" + esc(text) + "</li>";
      })
      .join("");
    const binds = row.detail.binds
      .map(function (bind) {
        return (
          "<li>" +
          tipSpan(helpers, bind.label, bind.tip) +
          " — " +
          esc(bind.status === "pass" ? "present" : bind.status === "fail" ? "missing" : "not recorded") +
          "</li>"
        );
      })
      .join("");
    const memoAge =
      row.detail.memoAgeDays == null || row.detail.memoAgeDays === ""
        ? "not recorded"
        : String(row.detail.memoAgeDays) + " days";
    const memoAt = row.detail.memoAt ? helpers.displayDate(row.detail.memoAt) : "not recorded";
    const storedNote =
      decline.storedMarket && decline.storedMarket !== row.market
        ? '<p class="v2-muted">The operating check is stored once per name (under ' +
          esc(marketLabel(viewCache && viewCache.ctx && viewCache.ctx.marketStatus, decline.storedMarket)) +
          ").</p>"
        : "";
    const chartState = ui.charts[rowKey(row)];
    const chartHtml = chartState && chartState.html ? chartState.html : "";
    return (
      '<div class="v2-cand-detail">' +
      "<h3>Cheap</h3>" +
      "<p>Screen signal: " +
      esc(signalPhrase(row.detail.signal)) +
      ". " +
      tipSpan(helpers, "Buy tier", TIPS.buyTier) +
      " is the value set the book can hold.</p>" +
      "<h3>Not declining</h3>" +
      "<p class=\"v2-panel-meta\">As of " +
      esc(decline.asOf ? helpers.displayDate(decline.asOf) : "not yet available") +
      "</p>" +
      storedNote +
      (declineLines ? "<ul>" + declineLines + "</ul>" : "") +
      (declineReasons ? "<ul>" + declineReasons + "</ul>" : "") +
      "<h3>Sector sound</h3>" +
      "<p class=\"v2-panel-meta\">" +
      esc(sector.name || "Sector not recorded") +
      " · as of " +
      esc(sector.asOf ? helpers.displayDate(sector.asOf) : "not yet available") +
      "</p>" +
      (sectorLines ? "<ul>" + sectorLines + "</ul>" : "") +
      (sectorReasons ? "<ul>" + sectorReasons + "</ul>" : "") +
      "<h3>" +
      tipSpan(helpers, "Input quality", TIPS.f9) +
      "</h3>" +
      "<ul>" +
      binds +
      "</ul>" +
      "<p>Memo age: " +
      esc(memoAge) +
      ". Last memo: " +
      esc(memoAt) +
      ".</p>" +
      "<h3>" +
      tipSpan(helpers, "Short-term low", TIPS.shortTermLow) +
      "</h3>" +
      "<p>" +
      esc(row.detail.entryText) +
      "</p>" +
      '<div class="v2-cand-chart" data-cand-chart="' +
      esc(rowKey(row)) +
      '">' +
      (chartHtml
        ? chartHtml
        : '<button type="button" class="v2-cand-chart-btn" data-cand-action="chart" data-cand-key="' +
          esc(rowKey(row)) +
          '">Show chart</button>') +
      "</div></div>"
    );
  }

  function rowKey(row) {
    return row.market + "|" + row.ticker;
  }

  function renderTable(helpers, rows) {
    const esc = helpers.esc;
    const shown = rows.slice(0, ui.limit);
    const head = CHECK_HEADS.map(function (col) {
      return "<th>" + tipSpan(helpers, col.label, col.tip) + "</th>";
    }).join("");
    const body = shown
      .map(function (row) {
        const key = rowKey(row);
        const open = !!ui.expanded[key];
        const cells = CHECK_ORDER.map(function (name) {
          const check = row.checks[name];
          return (
            '<td><span class="' +
            verdictClass(check.status) +
            '">' +
            esc(check.label) +
            "</span></td>"
          );
        }).join("");
        const main =
          "<tr>" +
          "<td><button type=\"button\" class=\"v2-cand-expand\" data-cand-action=\"toggle\" data-cand-key=\"" +
          esc(key) +
          '" aria-expanded="' +
          (open ? "true" : "false") +
          '">' +
          esc(row.ticker) +
          "</button></td>" +
          "<td>" +
          esc(row.name || "—") +
          "</td>" +
          "<td>" +
          esc(row.sector || "—") +
          "</td>" +
          cells +
          "<td>" +
          esc(String(row.passCount) + " of " + String(row.measuredCount)) +
          "</td>" +
          "<td>" +
          esc(row.t212.label) +
          "</td></tr>";
        const detail = open
          ? '<tr class="v2-cand-detail-row"><td colspan="10">' + renderDetail(helpers, row) + "</td></tr>"
          : "";
        return main + detail;
      })
      .join("");
    const more =
      rows.length > shown.length
        ? '<button type="button" class="v2-cand-more" data-cand-action="more">Show more (' +
          esc(String(shown.length)) +
          " of " +
          esc(String(rows.length)) +
          ")</button>"
        : "";
    const empty = rows.length
      ? ""
      : '<p class="v2-muted">No names match. A check that cannot be computed is not counted as a pass.</p>';
    return (
      '<div class="v2-table-wrap"><table class="v2-table v2-cand-table"><thead><tr>' +
      "<th>Ticker</th><th>Name</th><th>Sector</th>" +
      head +
      '<th>Passed</th><th>' +
      tipSpan(helpers, "Listed", "On the Trading 212 catalogue, where that is already known. Unknown is not treated as unlisted.") +
      "</th>" +
      "</tr></thead><tbody>" +
      (body || '<tr><td colspan="10">No names to show.</td></tr>') +
      "</tbody></table></div>" +
      more +
      empty
    );
  }

  function renderHtml() {
    const ctx = viewCache.ctx;
    const helpers = viewCache.helpers;
    const rows = viewCache.rows;
    const markets = marketsFor(ctx, rows);
    if (!markets.some(function (m) { return m.id === ui.market; })) ui.market = markets[0].id;
    const current = markets.filter(function (m) { return m.id === ui.market; })[0] || markets[0];
    const funnel = funnelForMarket(ctx, rows, current.id, current.label);
    const marketRows = rows.filter(function (row) { return row.market === current.id; });
    const visible = ui.onlyPassing ? marketRows.filter(passesEveryCheckSoFar) : marketRows;
    const passing = marketRows.filter(passesEveryCheckSoFar).length;
    const options = markets
      .map(function (m) {
        const count = rows.filter(function (row) { return row.market === m.id; }).length;
        const suffix = m.known || count ? " (" + count + ")" : " (" + NOT_MEASURED + ")";
        return (
          '<option value="' +
          helpers.esc(m.id) +
          '"' +
          (m.id === current.id ? " selected" : "") +
          ">" +
          helpers.esc(m.label) +
          helpers.esc(suffix) +
          "</option>"
        );
      })
      .join("");
    const sessionMap = ctx.forwardStatus && ctx.forwardStatus.candidates_session_by_market;
    const session = sessionMap && sessionMap[current.id] ? String(sessionMap[current.id]) : "";
    const sessionLine = session
      ? '<p class="v2-panel-meta">Forward job\'s latest session for this market: ' + helpers.esc(session) + "</p>"
      : "";
    const headingTip = current.id === FTSE_MARKET ? TIPS.ftse350 : "Library market from the buy-tier inventory.";
    return (
      '<section class="v2-panel v2-cand">' +
      '<div class="v2-card v2-cand-intro">' +
      "<h2>Which names could the book buy now?</h2>" +
      "<p>A name has to be cheap, not declining, in a sound sector, with complete input quality, and at a short-term low. This list is observe-only. It does not place trades or change the book.</p>" +
      '<p class="v2-muted">Names that fail a check, or have no row for it, stay out. Missing is not a pass.</p>' +
      "</div>" +
      renderSources(ctx, helpers) +
      '<div class="v2-card">' +
      "<h2>" +
      tipSpan(helpers, current.label, headingTip) +
      "</h2>" +
      '<div class="v2-cand-toolbar"><label>Market <select data-cand-market>' +
      options +
      "</select></label>" +
      '<label class="v2-cand-filter"><input type="checkbox" data-cand-filter' +
      (ui.onlyPassing ? " checked" : "") +
      "> Only names passing every check so far</label></div>" +
      '<p class="v2-panel-meta">Each count is how many ' +
      tipSpan(helpers, "buy tier", TIPS.buyTier) +
      " names are still in after that step. " +
      helpers.esc(String(passing)) +
      " of " +
      helpers.esc(String(marketRows.length)) +
      " pass every check measured so far.</p>" +
      sourceStrip(ctx, helpers) +
      renderFunnel(helpers, funnel) +
      sessionLine +
      "</div>" +
      '<div class="v2-card">' +
      "<h2>Names</h2>" +
      sourceStrip(ctx, helpers) +
      '<p class="v2-panel-meta">Sorted by how many checks they pass. Open a ticker for the cited reasons. ' +
      "Showing " +
      helpers.esc(String(Math.min(visible.length, ui.limit))) +
      " of " +
      helpers.esc(String(visible.length)) +
      ".</p>" +
      renderTable(helpers, visible) +
      "</div></section>"
    );
  }

  function cssAttr(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  function chartUrl(ticker) {
    const token = String(ticker || "");
    if (!/^[A-Za-z0-9._-]+$/.test(token)) return null;
    return "../data/charts/" + token + ".json";
  }

  function chartsReady() {
    return typeof window.renderPriceChartSvg === "function";
  }

  let chartsLoader = null;
  function loadChartsScript() {
    if (chartsReady()) return Promise.resolve();
    if (chartsLoader) return chartsLoader;
    chartsLoader = new Promise(function (resolve) {
      if (typeof document === "undefined" || !document || !document.head) {
        resolve();
        return;
      }
      const script = document.createElement("script");
      script.src = "../charts.js";
      script.onload = function () { resolve(); };
      script.onerror = function () { resolve(); };
      document.head.appendChild(script);
    });
    return chartsLoader;
  }

  function chartCaption(helpers, payload) {
    const esc = helpers.esc;
    const iso = payload && (payload.as_of || payload.levels_as_of);
    const ms = helpers.parseIsoMs(iso);
    const age = ms == null ? null : helpers.nowMs() - ms;
    const badge = helpers.freshnessChartBar ? helpers.freshnessChartBar(age) : { cls: "v2-badge", label: "unknown" };
    const when = iso ? helpers.displayDate(iso) : "not yet available";
    return (
      '<p class="v2-panel-meta">Screen plan · price chart as of ' +
      esc(when) +
      ' <span class="' +
      esc(badge.cls) +
      '">' +
      esc(badge.label) +
      "</span>. The old screen stop and target are not the strategy's exits and are not drawn.</p>"
    );
  }

  function paint(root) {
    root.innerHTML = renderHtml();
    wire(root);
  }

  function findRow(key) {
    const rows = viewCache.rows;
    for (let i = 0; i < rows.length; i += 1) {
      if (rowKey(rows[i]) === key) return rows[i];
    }
    return null;
  }

  function showChart(root, key) {
    const row = findRow(key);
    const helpers = viewCache.helpers;
    if (!row) return;
    const host = root.querySelector('[data-cand-chart="' + cssAttr(key) + '"]');
    if (host) host.innerHTML = '<p class="v2-muted">Loading chart…</p>';
    const url = chartUrl(row.ticker);
    if (!url) {
      ui.charts[key] = { html: '<p class="v2-muted">no chart yet</p>' };
      paint(root);
      return;
    }
    // charts.js calls the global esc from the old dashboard. v2 does not load that file.
    if (typeof helpers.esc === "function") window.esc = helpers.esc;
    loadChartsScript().then(function () {
      return helpers.fetchJsonSafe(url);
    }).then(function (result) {
      if (!result || !result.ok || !result.data) {
        ui.charts[key] = { html: '<p class="v2-muted">no chart yet</p>' };
      } else if (!chartsReady()) {
        ui.charts[key] = { html: '<p class="v2-muted">no chart yet</p>' };
      } else {
        let svg = "";
        try {
          svg = window.renderPriceChartSvg(result.data, screenPlanLevels(result.data.levels));
        } catch (err) {
          svg = "";
        }
        ui.charts[key] = {
          html: svg
            ? chartCaption(helpers, result.data) + '<div class="v2-cand-svg">' + svg + "</div>"
            : '<p class="v2-muted">no chart yet</p>',
        };
      }
      paint(root);
    });
  }

  function wire(root) {
    const market = root.querySelector("[data-cand-market]");
    if (market) {
      market.addEventListener("change", function () {
        ui.market = market.value;
        ui.limit = PAGE_SIZE;
        ui.expanded = Object.create(null);
        paint(root);
      });
    }
    const filter = root.querySelector("[data-cand-filter]");
    if (filter) {
      filter.addEventListener("change", function () {
        ui.onlyPassing = !!filter.checked;
        ui.limit = PAGE_SIZE;
        paint(root);
      });
    }
    const buttons = root.querySelectorAll("[data-cand-action]");
    for (let i = 0; i < buttons.length; i += 1) {
      buttons[i].addEventListener("click", function (event) {
        const target = event.currentTarget;
        const action = target.getAttribute("data-cand-action");
        const key = target.getAttribute("data-cand-key");
        if (action === "more") {
          ui.limit += PAGE_SIZE;
          paint(root);
          return;
        }
        if (action === "toggle" && key) {
          ui.expanded[key] = !ui.expanded[key];
          paint(root);
          return;
        }
        if (action === "chart" && key) showChart(root, key);
      });
    }
  }

  function render(ctx, helpers) {
    viewCache = { ctx: ctx || {}, helpers: helpers, rows: buildCandidateRows(ctx || {}) };
    return renderHtml();
  }

  function bind(root, ctx, helpers) {
    if (!root) return;
    viewCache = { ctx: ctx || {}, helpers: helpers, rows: buildCandidateRows(ctx || {}) };
    wire(root);
  }

  const api = {
    PAGE_SIZE: PAGE_SIZE,
    NOT_MEASURED: NOT_MEASURED,
    PENDING_ENTRY: PENDING_ENTRY,
    OUTCOME_LABELS: OUTCOME_LABELS,
    buildCandidateRows: buildCandidateRows,
    funnelCounts: funnelCounts,
    outcomeLabel: outcomeLabel,
    passesEveryCheckSoFar: passesEveryCheckSoFar,
    screenPlanLevels: screenPlanLevels,
  };

  window.__dashboardV2Candidates = api;

  if (window.DashboardV2Tabs && typeof window.DashboardV2Tabs.register === "function") {
    window.DashboardV2Tabs.register({
      id: "candidates",
      label: "Candidates",
      render: render,
      bind: bind,
    });
  }
})();
