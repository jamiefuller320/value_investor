/* Portfolio actions + diversification advice (browser-local). */

const PORTFOLIO_STORAGE_KEY = "ftseValueInvestor.portfolioActions.v1";
const TARGET_SECTOR_CAP = 0.3;
const MAX_POSITIONS = 8;
const CONVICTION_WEIGHT = 0.55;
const DIVERSITY_WEIGHT = 0.45;

function createActionId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `action-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadPortfolioActions() {
  try {
    const raw = localStorage.getItem(PORTFOLIO_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function savePortfolioActions(actions) {
  localStorage.setItem(PORTFOLIO_STORAGE_KEY, JSON.stringify(actions));
}

function actionableReports(data) {
  return (data.reports || []).filter((r) => r.signal === "strong_buy" || r.signal === "buy");
}

function reportByTicker(data, ticker) {
  return (data.reports || []).find((r) => r.ticker === ticker) || null;
}

function suggestedOrdersFromPlan(plan) {
  if (!plan) {
    return {
      leg: "combined",
      order_type: "limit",
      limit_price: "",
      stop_loss: "",
      take_profit: "",
      allocation_pct: "",
      core_order: "",
      core_limit: "",
      tactical_limit: "",
    };
  }
  return {
    leg: "core",
    order_type: plan.core_order || "limit",
    limit_price: plan.core_limit != null ? plan.core_limit : "",
    stop_loss: plan.tactical_stop_loss != null ? plan.tactical_stop_loss : "",
    take_profit: plan.tactical_take_profit != null ? plan.tactical_take_profit : "",
    allocation_pct: plan.core_allocation_pct != null ? plan.core_allocation_pct : "",
    core_order: plan.core_order || "",
    core_limit: plan.core_limit != null ? plan.core_limit : "",
    tactical_limit: plan.tactical_limit != null ? plan.tactical_limit : "",
    tactical_allocation_pct: plan.tactical_allocation_pct != null ? plan.tactical_allocation_pct : "",
    trade_plan_summary: plan.trade_plan_summary || "",
  };
}

function applyLegDefaults(form, plan, leg) {
  if (!plan) return;
  if (leg === "tactical") {
    form.order_type.value = plan.tactical_order || "limit";
    form.limit_price.value = plan.tactical_limit != null ? plan.tactical_limit : "";
    form.allocation_pct.value = plan.tactical_allocation_pct != null ? plan.tactical_allocation_pct : "";
  } else if (leg === "core") {
    form.order_type.value = plan.core_order || "market";
    form.limit_price.value = plan.core_limit != null ? plan.core_limit : "";
    form.allocation_pct.value = plan.core_allocation_pct != null ? plan.core_allocation_pct : "";
  } else {
    form.order_type.value = plan.core_order || "limit";
    form.limit_price.value =
      plan.core_limit != null ? plan.core_limit : plan.tactical_limit != null ? plan.tactical_limit : "";
    form.allocation_pct.value = "1";
  }
  form.stop_loss.value = plan.tactical_stop_loss != null ? plan.tactical_stop_loss : "";
  form.take_profit.value = plan.tactical_take_profit != null ? plan.tactical_take_profit : "";
}

function normalizeHoldings(actions, data) {
  const openActions = actions.filter((a) => (a.status || "open") === "open" && a.ticker);
  const byTicker = {};
  for (const action of openActions) {
    const report = reportByTicker(data, action.ticker) || {};
    const entry = byTicker[action.ticker] || {
      ticker: action.ticker,
      name: action.name || report.name || action.ticker,
      sector: action.sector || report.sector || "Unknown",
      weight: 0,
    };
    if (action.quantity != null && Number(action.quantity) > 0) {
      entry.weight += Number(action.quantity);
    } else if (action.allocation_pct != null && Number(action.allocation_pct) > 0) {
      entry.weight += Number(action.allocation_pct);
    } else {
      entry.weight += 1;
    }
    byTicker[action.ticker] = entry;
  }
  const holdings = Object.values(byTicker);
  const total = holdings.reduce((sum, h) => sum + h.weight, 0);
  if (!holdings.length) return [];
  if (total <= 0) {
    const equal = 1 / holdings.length;
    return holdings.map((h) => ({ ...h, weight: equal }));
  }
  return holdings.map((h) => ({ ...h, weight: h.weight / total }));
}

function computeSectorWeights(holdings) {
  const weights = {};
  for (const holding of holdings) {
    const sector = holding.sector || "Unknown";
    weights[sector] = (weights[sector] || 0) + holding.weight;
  }
  return Object.fromEntries(Object.entries(weights).sort((a, b) => b[1] - a[1]));
}

function diversityScore(sector, weights, sectorCap = TARGET_SECTOR_CAP) {
  const current = weights[sector || "Unknown"] || 0;
  if (current >= sectorCap) return 0;
  return Math.max(0, 1 - current / sectorCap);
}

function adviseDiversification(actions, data) {
  const holdings = normalizeHoldings(actions, data);
  const weights = computeSectorWeights(holdings);
  const held = new Set(holdings.map((h) => h.ticker));
  const warnings = [];

  if (holdings.length >= MAX_POSITIONS) {
    warnings.push(
      `Open book already has ${holdings.length} names (soft cap ${MAX_POSITIONS}). Prefer replacing or trimming before adding.`
    );
  }
  for (const [sector, weight] of Object.entries(weights)) {
    if (weight >= TARGET_SECTOR_CAP) {
      warnings.push(
        `${sector} is ${(weight * 100).toFixed(0)}% of the book (cap ${(TARGET_SECTOR_CAP * 100).toFixed(0)}%). Favour other sectors next.`
      );
    }
  }

  const underweight = Object.entries(weights)
    .filter(([, weight]) => weight < TARGET_SECTOR_CAP * 0.5)
    .sort((a, b) => a[1] - b[1])
    .map(([sector]) => sector);

  const candidates = actionableReports(data).filter((r) => !held.has(r.ticker));
  for (const report of candidates) {
    const sector = report.sector || "Unknown";
    if (!(sector in weights) && !underweight.includes(sector)) {
      underweight.push(sector);
    }
  }

  const ranked = candidates
    .map((report) => {
      const sector = report.sector || "Unknown";
      const diversity = diversityScore(sector, weights);
      const conviction = Math.max(0, Math.min(1, Number(report.conviction_score) || 0));
      const combined = CONVICTION_WEIGHT * conviction + DIVERSITY_WEIGHT * diversity;
      let rationale;
      if (diversity >= 0.75) {
        rationale = `Adds ${sector} exposure while the book is light there`;
      } else if (diversity >= 0.35) {
        rationale = `Acceptable ${sector} add — sector not yet at the ${(TARGET_SECTOR_CAP * 100).toFixed(0)}% cap`;
      } else if (diversity > 0) {
        rationale = `Increases ${sector} toward the concentration cap — size carefully`;
      } else {
        rationale = `Would deepen an already heavy ${sector} sleeve — deprioritise`;
      }
      return {
        ticker: report.ticker,
        name: report.name,
        sector: report.sector,
        signal: report.signal,
        conviction_score: conviction,
        diversity_score: diversity,
        combined_score: combined,
        rationale,
      };
    })
    .sort((a, b) => b.combined_score - a.combined_score || b.conviction_score - a.conviction_score)
    .slice(0, 5);

  let summary;
  if (!holdings.length) {
    summary =
      "No actioned holdings yet. Log fills from Strong buys / Buys, then use this panel to prefer underweight sectors on the next recommendation.";
  } else if (warnings.length && ranked.length) {
    summary = `${holdings.length} open name(s). Address concentration first: next best diversified candidate is ${ranked[0].name} (${ranked[0].ticker}).`;
  } else if (ranked.length) {
    summary = `${holdings.length} open name(s) across ${Object.keys(weights).length} sector(s). Next diversified pick: ${ranked[0].name} (${ranked[0].ticker}) — ${ranked[0].rationale}.`;
  } else {
    summary = `${holdings.length} open name(s). No unused buy-tier candidates available to improve diversification this week.`;
  }

  return {
    holdings,
    sector_weights: weights,
    concentration_warnings: warnings,
    underweight_sectors: underweight.slice(0, 6),
    ranked_candidates: ranked,
    summary,
  };
}

function moneyInputValue(value) {
  if (value === "" || value == null) return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function renderActionDialog(data, preselectTicker = "") {
  const candidates = actionableReports(data);
  const options = candidates
    .map(
      (r) =>
        `<option value="${esc(r.ticker)}" ${r.ticker === preselectTicker ? "selected" : ""}>${esc(r.name)} (${esc(r.ticker)}) · ${esc(r.signal.replace(/_/g, " "))}</option>`
    )
    .join("");

  return `
    <dialog id="action-dialog" class="memo-dialog action-dialog">
      <form method="dialog" class="memo-dialog-header">
        <h2>Log actioned recommendation</h2>
        <button type="submit" class="btn btn-ghost" aria-label="Close">✕</button>
      </form>
      <form id="action-form" class="action-form">
        <p class="small muted">Stored only in this browser (localStorage). Export a backup if you switch devices.</p>
        <label>
          Recommendation
          <select name="ticker" required ${candidates.length ? "" : "disabled"}>
            <option value="">Select a buy-tier name…</option>
            ${options}
          </select>
        </label>
        <div class="form-grid">
          <label>
            Leg
            <select name="leg">
              <option value="core">Core</option>
              <option value="tactical">Tactical</option>
              <option value="combined">Combined</option>
            </select>
          </label>
          <label>
            Order type
            <select name="order_type">
              <option value="market">Market</option>
              <option value="limit">Limit</option>
            </select>
          </label>
          <label>
            Limit (£)
            <input name="limit_price" type="number" step="0.01" min="0" placeholder="Optional">
          </label>
          <label>
            Stop loss (£)
            <input name="stop_loss" type="number" step="0.01" min="0" placeholder="Optional">
          </label>
          <label>
            Take profit (£)
            <input name="take_profit" type="number" step="0.01" min="0" placeholder="Optional">
          </label>
          <label>
            Allocation (0–1)
            <input name="allocation_pct" type="number" step="0.01" min="0" max="1" placeholder="e.g. 0.60">
          </label>
          <label>
            Quantity (shares)
            <input name="quantity" type="number" step="1" min="0" placeholder="Optional">
          </label>
          <label>
            Status
            <select name="status">
              <option value="open">Open</option>
              <option value="filled">Filled / open position</option>
              <option value="closed">Closed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
        </div>
        <label>
          Notes
          <textarea name="notes" rows="2" placeholder="Broker, fill quality, thesis reminder…"></textarea>
        </label>
        <p id="action-plan-hint" class="small muted"></p>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary" ${candidates.length ? "" : "disabled"}>Save action</button>
          <button type="button" class="btn" id="action-cancel">Cancel</button>
        </div>
      </form>
    </dialog>
  `;
}

function bindActionDialog(data, onSaved) {
  const existing = document.getElementById("action-dialog");
  if (existing) existing.remove();

  document.body.insertAdjacentHTML("beforeend", renderActionDialog(data));
  const dialog = document.getElementById("action-dialog");
  const form = document.getElementById("action-form");
  const hint = document.getElementById("action-plan-hint");

  function syncFromTicker() {
    const ticker = form.ticker.value;
    const report = reportByTicker(data, ticker);
    const plan = report?.trade_plan || null;
    applyLegDefaults(form, plan, form.leg.value);
    if (plan?.trade_plan_summary) {
      hint.textContent = `Suggested: ${plan.trade_plan_summary}`;
    } else if (report) {
      hint.textContent = "No structured trade plan for this name — enter levels manually.";
    } else {
      hint.textContent = "";
    }
  }

  form.ticker.addEventListener("change", syncFromTicker);
  form.leg.addEventListener("change", syncFromTicker);
  document.getElementById("action-cancel").addEventListener("click", () => dialog.close());

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const ticker = form.ticker.value;
    const report = reportByTicker(data, ticker);
    if (!report) return;

    const status = form.status.value === "filled" ? "open" : form.status.value;
    const action = {
      id: createActionId(),
      ticker,
      name: report.name,
      sector: report.sector || null,
      signal_at_action: report.signal,
      run_at: data.run_at || null,
      acted_at: new Date().toISOString(),
      status,
      side: "buy",
      leg: form.leg.value,
      order_type: form.order_type.value,
      limit_price: moneyInputValue(form.limit_price.value),
      stop_loss: moneyInputValue(form.stop_loss.value),
      take_profit: moneyInputValue(form.take_profit.value),
      allocation_pct: moneyInputValue(form.allocation_pct.value),
      quantity: moneyInputValue(form.quantity.value),
      notes: (form.notes.value || "").trim(),
      suggested: suggestedOrdersFromPlan(report.trade_plan),
    };

    const actions = loadPortfolioActions();
    actions.unshift(action);
    savePortfolioActions(actions);
    dialog.close();
    onSaved();
  });

  return {
    open(ticker = "") {
      if (ticker) form.ticker.value = ticker;
      syncFromTicker();
      dialog.showModal();
    },
  };
}

function exportActions() {
  const blob = new Blob([JSON.stringify(loadPortfolioActions(), null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `ftse-portfolio-actions-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

function importActions(file, onDone) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result || "[]"));
      if (!Array.isArray(parsed)) throw new Error("Expected a JSON array");
      savePortfolioActions(parsed);
      onDone();
    } catch (err) {
      alert(`Could not import actions: ${err.message}`);
    }
  };
  reader.readAsText(file);
}

function renderPortfolio(data) {
  const panel = document.getElementById("panel-portfolio");
  if (!panel) return;

  const actions = loadPortfolioActions();
  const advice = adviseDiversification(actions, data);
  const openActions = actions.filter((a) => (a.status || "open") === "open");
  const closedActions = actions.filter((a) => (a.status || "open") !== "open");

  const sectorBars = Object.entries(advice.sector_weights)
    .map(
      ([sector, weight]) => `
      <div class="sector-row">
        <div class="sector-label"><span>${esc(sector)}</span><span>${(weight * 100).toFixed(0)}%</span></div>
        <div class="sector-meter"><span style="width:${Math.min(100, weight * 100)}%"></span></div>
      </div>`
    )
    .join("");

  const rankedRows = advice.ranked_candidates.length
    ? advice.ranked_candidates
        .map(
          (c) => `<tr>
            <td><strong>${esc(c.name)}</strong><br><span class="small muted">${esc(c.ticker)}${c.sector ? ` · ${esc(c.sector)}` : ""}</span></td>
            <td>${signalBadge(c.signal)}</td>
            <td>${pct(c.conviction_score)}</td>
            <td>${pct(c.diversity_score)}</td>
            <td class="small">${esc(c.rationale)}</td>
            <td><button type="button" class="btn btn-primary" data-log-ticker="${esc(c.ticker)}">Log</button></td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="6" class="muted">No unused buy-tier candidates to rank.</td></tr>`;

  const actionRows = (list) =>
    list.length
      ? list
          .map(
            (a) => `<tr>
              <td>
                <strong>${esc(a.name || a.ticker)}</strong><br>
                <span class="small muted">${esc(a.ticker)}${a.sector ? ` · ${esc(a.sector)}` : ""}</span>
              </td>
              <td>${signalBadge(a.signal_at_action || "buy")}<br><span class="small muted">${esc(a.leg || "")} · ${esc(a.order_type || "")}</span></td>
              <td class="small">
                ${a.limit_price != null ? `Limit £${Number(a.limit_price).toFixed(2)}<br>` : ""}
                ${a.stop_loss != null ? `Stop £${Number(a.stop_loss).toFixed(2)}<br>` : ""}
                ${a.take_profit != null ? `Target £${Number(a.take_profit).toFixed(2)}` : ""}
              </td>
              <td class="small">${fmtDate(a.acted_at)}</td>
              <td>
                <select data-status-id="${esc(a.id)}" aria-label="Status for ${esc(a.ticker)}">
                  <option value="open" ${(a.status || "open") === "open" ? "selected" : ""}>Open</option>
                  <option value="closed" ${a.status === "closed" ? "selected" : ""}>Closed</option>
                  <option value="cancelled" ${a.status === "cancelled" ? "selected" : ""}>Cancelled</option>
                </select>
              </td>
              <td><button type="button" class="btn" data-delete-id="${esc(a.id)}">Delete</button></td>
            </tr>`
          )
          .join("")
      : `<tr><td colspan="6" class="muted">None.</td></tr>`;

  panel.innerHTML = `
    <div class="toolbar">
      <button type="button" class="btn btn-primary" id="log-action-btn">Log action</button>
      <button type="button" class="btn" id="export-actions-btn">Export JSON</button>
      <label class="btn file-btn">
        Import JSON
        <input type="file" id="import-actions-input" accept="application/json,.json" hidden>
      </label>
    </div>

    <div class="card">
      <h3>Diversification steer</h3>
      <p>${esc(advice.summary)}</p>
      ${
        advice.concentration_warnings.length
          ? `<ul class="list-plain small">${advice.concentration_warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`
          : ""
      }
      ${
        advice.underweight_sectors.length
          ? `<p class="small muted">Underweight / open sectors: ${advice.underweight_sectors.map(esc).join(", ")}</p>`
          : ""
      }
      ${sectorBars ? `<div class="sector-stack">${sectorBars}</div>` : ""}
      <h4 style="margin-top:1rem">Next diversified candidates</h4>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Signal</th>
              <th>Conviction</th>
              <th>Diversity</th>
              <th>Why</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${rankedRows}</tbody>
        </table>
      </div>
      <p class="small muted">Score blends conviction (${(CONVICTION_WEIGHT * 100).toFixed(0)}%) with sector diversification (${(DIVERSITY_WEIGHT * 100).toFixed(0)}%). Soft sector cap ${(TARGET_SECTOR_CAP * 100).toFixed(0)}%.</p>
    </div>

    <div class="card" style="margin-top:1rem">
      <h3>Open actions (${openActions.length})</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Order</th>
              <th>Levels</th>
              <th>Acted</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${actionRows(openActions)}</tbody>
        </table>
      </div>
    </div>

    <div class="card" style="margin-top:1rem">
      <h3>Closed / cancelled (${closedActions.length})</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Order</th>
              <th>Levels</th>
              <th>Acted</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${actionRows(closedActions)}</tbody>
        </table>
      </div>
    </div>
  `;

  const dialogApi = bindActionDialog(data, () => renderPortfolio(data));

  panel.querySelector("#log-action-btn").addEventListener("click", () => dialogApi.open());
  panel.querySelector("#export-actions-btn").addEventListener("click", exportActions);
  panel.querySelector("#import-actions-input").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    importActions(file, () => renderPortfolio(data));
    event.target.value = "";
  });

  panel.querySelectorAll("[data-log-ticker]").forEach((button) => {
    button.addEventListener("click", () => dialogApi.open(button.dataset.logTicker));
  });

  panel.querySelectorAll("[data-status-id]").forEach((select) => {
    select.addEventListener("change", () => {
      const actionsNow = loadPortfolioActions().map((action) =>
        action.id === select.dataset.statusId ? { ...action, status: select.value } : action
      );
      savePortfolioActions(actionsNow);
      renderPortfolio(data);
    });
  });

  panel.querySelectorAll("[data-delete-id]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!confirm("Delete this action log entry?")) return;
      savePortfolioActions(loadPortfolioActions().filter((a) => a.id !== button.dataset.deleteId));
      renderPortfolio(data);
    });
  });

  // Expose opener for Strong buys tab buttons.
  window.__openPortfolioActionDialog = (ticker) => {
    const tabs = document.getElementById("tabs");
    const portfolioTab = tabs?.querySelector('[data-tab="portfolio"]');
    if (portfolioTab) portfolioTab.click();
    dialogApi.open(ticker || "");
  };
}
