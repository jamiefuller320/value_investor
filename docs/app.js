/* FTSE 100 Value Investor — GitHub Pages dashboard */

const SIGNAL_COLORS = {
  strong_buy: "#1b7f3a",
  buy: "#2e9c4f",
  hold: "#b8860b",
  avoid: "#b33a3a",
  insufficient_data: "#666666",
};

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "screener", label: "Screener" },
  { id: "strong-buys", label: "Strong buys" },
  { id: "portfolio", label: "Portfolio" },
  { id: "performance", label: "Performance" },
  { id: "analysis", label: "Analysis" },
];

let dashboardData = null;

function esc(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(0)}%`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-GB", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    }) + " UTC";
  } catch {
    return iso;
  }
}

function signalBadge(signal) {
  const key = (signal || "insufficient_data").replace(/\s+/g, "_");
  const label = key.replace(/_/g, " ");
  return `<span class="badge badge-${key}">${esc(label)}</span>`;
}

function timingBadge(timing) {
  if (!timing || timing === "insufficient_data") return '<span class="muted">N/A</span>';
  return `<span class="badge badge-${timing}">${esc(timing)}</span>`;
}

function researchOverlayHtml(report) {
  if (!report.research_verdict) return "";
  const verdict = esc(report.research_verdict.replace(/_/g, " "));
  if (report.adjusted_signal && report.adjusted_signal !== report.signal) {
    return `<br><span class="small muted">Research: ${verdict} → ${esc(report.adjusted_signal.replace(/_/g, " "))}</span>`;
  }
  return `<br><span class="small muted">Research: ${verdict}</span>`;
}

function tradePlanHtml(report) {
  const plan = report.trade_plan;
  if (!plan) return '<span class="muted">—</span>';
  const parts = [];
  if (plan.trade_plan_summary) {
    parts.push(esc(plan.trade_plan_summary));
  } else {
    if (plan.core_order) {
      parts.push(`Core: ${esc(plan.core_order)}${plan.core_limit != null ? ` @ £${plan.core_limit.toFixed(2)}` : ""}`);
    }
    if (plan.tactical_limit != null) {
      parts.push(`Tactical limit £${plan.tactical_limit.toFixed(2)}`);
    }
    if (plan.tactical_stop_loss != null && plan.tactical_take_profit != null) {
      parts.push(`Stop £${plan.tactical_stop_loss.toFixed(2)}, target £${plan.tactical_take_profit.toFixed(2)}`);
    }
  }
  return parts.join("<br>") || '<span class="muted">—</span>';
}

function initTabs() {
  const nav = document.getElementById("tabs");
  nav.innerHTML = TABS.map(
    (tab, index) =>
      `<button type="button" class="tab${index === 0 ? " active" : ""}" data-tab="${tab.id}" id="tab-${tab.id}">${tab.label}</button>`
  ).join("");

  nav.addEventListener("click", (event) => {
    const button = event.target.closest("[data-tab]");
    if (!button) return;
    const tabId = button.dataset.tab;
    nav.querySelectorAll(".tab").forEach((el) => el.classList.toggle("active", el === button));
    document.querySelectorAll(".panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === `panel-${tabId}`);
    });
  });
}

function renderOverview(data) {
  const meta = data.meta || {};
  const counts = meta.signal_counts || {};
  const total = meta.company_count || 0;
  const segments = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const bar = segments
    .map(([signal, count]) => {
      const width = total ? (count / total) * 100 : 0;
      return `<span style="width:${width}%;background:${SIGNAL_COLORS[signal] || "#999"}" title="${esc(signal)}: ${count}"></span>`;
    })
    .join("");

  const diff = data.run_diff;
  let diffHtml = '<p class="muted">No prior run to compare yet.</p>';
  if (diff) {
    const sections = [
      ["New strong buys", diff.new_strong_buys],
      ["Persistent strong buys", diff.persistent_strong_buys],
      ["Lost strong buys", diff.lost_strong_buys],
      ["Upgrades", diff.upgrades],
      ["Downgrades", diff.downgrades],
    ];
    diffHtml = sections
      .filter(([, items]) => items && items.length)
      .map(
        ([title, items]) =>
          `<div><strong>${esc(title)}</strong><ul class="list-plain">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>`
      )
      .join("") || '<p class="muted">No signal changes this week.</p>';
  }

  const note = data.note ? `<div class="card"><p>${esc(data.note)}</p></div>` : "";

  document.getElementById("panel-overview").innerHTML = `
    ${note}
    <div class="grid">
      <div class="card">
        <h3>Companies screened</h3>
        <div class="stat-value">${total}</div>
      </div>
      <div class="card">
        <h3>Strong buys</h3>
        <div class="stat-value" style="color:var(--strong-buy)">${meta.strong_buy_count || 0}</div>
      </div>
      <div class="card">
        <h3>Last run</h3>
        <div class="small">${fmtDate(data.run_at)}</div>
        <div class="small muted">Published ${fmtDate(data.generated_at)}</div>
      </div>
    </div>
    <div class="card" style="margin-top:1rem">
      <h3>Signal distribution</h3>
      <div class="signal-bar">${bar}</div>
      <ul class="list-plain small">
        ${segments.map(([s, c]) => `<li>${signalBadge(s)} ${c}</li>`).join("")}
      </ul>
    </div>
    <div class="card" style="margin-top:1rem">
      <h3>Week-over-week changes</h3>
      ${diffHtml}
    </div>
  `;
}

function renderScreener(data) {
  const reports = data.reports || [];
  const panel = document.getElementById("panel-screener");

  panel.innerHTML = `
    <div class="toolbar">
      <input type="search" id="screener-search" placeholder="Search company or ticker…" aria-label="Search">
      <select id="screener-filter" aria-label="Filter by signal">
        <option value="">All signals</option>
        <option value="strong_buy">Strong buy</option>
        <option value="buy">Buy</option>
        <option value="hold">Hold</option>
        <option value="avoid">Avoid</option>
        <option value="insufficient_data">Insufficient data</option>
      </select>
    </div>
    <div class="table-wrap">
      <table id="screener-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Signal</th>
            <th>Timing</th>
            <th>Models</th>
            <th>Conviction</th>
            <th>Summary</th>
            <th></th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  `;

  const tbody = panel.querySelector("tbody");
  const searchInput = panel.querySelector("#screener-search");
  const filterSelect = panel.querySelector("#screener-filter");
  const byTicker = new Map(reports.map((r) => [r.ticker, r]));

  function renderRows() {
    const q = (searchInput.value || "").toLowerCase();
    const filter = filterSelect.value;
    const rows = reports.filter((report) => {
      if (filter && report.signal !== filter) return false;
      const hay = `${report.name} ${report.ticker} ${report.sector || ""}`.toLowerCase();
      return !q || hay.includes(q);
    });

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="muted">No companies match your filters.</td></tr>`;
      return;
    }

    tbody.innerHTML = rows
      .map((report) => {
        const chartBtn =
          report.signal === "strong_buy" || report.signal === "buy"
            ? `<button type="button" class="btn" data-chart-ticker="${esc(report.ticker)}">Chart</button>`
            : "";
        return `
      <tr>
        <td>
          <strong>${esc(report.name)}</strong><br>
          <span class="small muted">${esc(report.ticker)}${report.sector ? ` · ${esc(report.sector)}` : ""}</span>
        </td>
        <td>${signalBadge(report.signal)}${researchOverlayHtml(report)}</td>
        <td>${timingBadge(report.timing_signal)}<br><span class="small muted">${report.rsi_14 != null ? `RSI ${Math.round(report.rsi_14)}` : ""}</span></td>
        <td>${report.models_passed}/${report.model_count}<br><span class="small muted">${report.families_passed}/4 families</span></td>
        <td>${pct(report.conviction_score)}<br><span class="small muted">${esc(report.stability_label || "")}</span></td>
        <td class="small">${esc(report.summary || "")}</td>
        <td>${chartBtn}</td>
      </tr>`;
      })
      .join("");
    bindChartButtons(tbody, byTicker);
  }

  searchInput.addEventListener("input", renderRows);
  filterSelect.addEventListener("change", renderRows);
  renderRows();
}

function renderStrongBuys(data) {
  const reports = (data.reports || []).filter((r) => r.signal === "strong_buy" || r.signal === "buy");
  const panel = document.getElementById("panel-strong-buys");

  if (!reports.length) {
    panel.innerHTML = '<div class="empty-state">No strong buy or buy recommendations in the latest run.</div>';
    return;
  }

  const strong = reports.filter((r) => r.signal === "strong_buy");
  const buys = reports.filter((r) => r.signal === "buy");

  const cardHtml = (report) => `
    <div class="card pick-card">
      <h4>${esc(report.name)} <span class="small muted">(${esc(report.ticker)})</span></h4>
      <p>${signalBadge(report.signal)} ${timingBadge(report.timing_signal)} · Conviction ${pct(report.conviction_score)}${researchOverlayHtml(report)}</p>
      <p class="small">${esc(report.action_note || "")}</p>
      <p class="small"><strong>Trade plan:</strong><br>${tradePlanHtml(report)}</p>
      <p class="small">${esc(report.summary || "")}</p>
      <p class="pick-actions">
        <button type="button" class="btn" data-chart-ticker="${esc(report.ticker)}">Price chart</button>
        <button type="button" class="btn btn-primary" data-log-ticker="${esc(report.ticker)}">Log action</button>
      </p>
    </div>`;

  panel.innerHTML = `
    ${strong.length ? `<h3 style="margin-top:0">Strong buys</h3>${strong.map(cardHtml).join("")}` : ""}
    ${buys.length ? `<h3>Buys</h3>${buys.map(cardHtml).join("")}` : ""}
  `;

  const byTicker = new Map(reports.map((r) => [r.ticker, r]));
  bindChartButtons(panel, byTicker);

  panel.querySelectorAll("[data-log-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      if (typeof window.__openPortfolioActionDialog === "function") {
        window.__openPortfolioActionDialog(button.dataset.logTicker);
      } else {
        const tabs = document.getElementById("tabs");
        const portfolioTab = tabs?.querySelector('[data-tab="portfolio"]');
        if (portfolioTab) portfolioTab.click();
      }
    });
  });
}

const CHART_COLORS = {
  "screen:strong_buy": "#1b7f3a",
  "screen:buy": "#2e9c4f",
  "overlay:strong_buy": "#2b6cb0",
  "overlay:buy": "#6b46c1",
  "research:pass": "#b33a3a",
  "research:downgraded": "#c45c00",
};

function renderWeeklySeriesChart(weeklySeries, horizonDays = 28) {
  if (!weeklySeries || !weeklySeries.length) return "";

  const strategies = ["screen:strong_buy", "overlay:strong_buy", "screen:buy", "overlay:buy"];
  const filtered = weeklySeries.filter(
    (row) => row.horizon_days === horizonDays && strategies.includes(row.strategy)
  );
  if (!filtered.length) {
    return `<p class="small muted">No weekly excess series for the ${horizonDays}-day horizon yet.</p>`;
  }

  const byStrategy = {};
  for (const row of filtered) {
    if (!byStrategy[row.strategy]) byStrategy[row.strategy] = [];
    byStrategy[row.strategy].push(row);
  }

  const weeks = [...new Set(filtered.map((row) => row.week))].sort();
  const width = 640;
  const height = 220;
  const pad = { top: 16, right: 16, bottom: 36, left: 48 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const values = filtered.flatMap((row) => [row.raw_excess_return, row.smoothed_excess_return]);
  const minY = Math.min(-0.05, ...values);
  const maxY = Math.max(0.05, ...values);
  const spanY = maxY - minY || 0.01;

  const xAt = (index) => pad.left + (index / Math.max(weeks.length - 1, 1)) * plotW;
  const yAt = (value) => pad.top + plotH - ((value - minY) / spanY) * plotH;

  const zeroY = yAt(0);
  const gridLines = [-0.04, -0.02, 0, 0.02, 0.04]
    .filter((tick) => tick >= minY && tick <= maxY)
    .map(
      (tick) =>
        `<line x1="${pad.left}" y1="${yAt(tick)}" x2="${width - pad.right}" y2="${yAt(tick)}" stroke="#e2e8f0" stroke-width="1" />`
    )
    .join("");

  const seriesPaths = strategies
    .filter((strategy) => byStrategy[strategy])
    .map((strategy) => {
      const rows = byStrategy[strategy].sort((a, b) => a.week.localeCompare(b.week));
      const points = rows
        .map((row) => {
          const index = weeks.indexOf(row.week);
          return `${xAt(index)},${yAt(row.smoothed_excess_return)}`;
        })
        .join(" ");
      return `<polyline fill="none" stroke="${CHART_COLORS[strategy] || "#666"}" stroke-width="2.5" points="${points}" />`;
    })
    .join("");

  const legend = strategies
    .filter((strategy) => byStrategy[strategy])
    .map(
      (strategy) =>
        `<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:${CHART_COLORS[strategy] || "#666"}"></span>${esc(strategy)}</span>`
    )
    .join("");

  const xLabels = weeks
    .filter((_, index) => index % Math.max(1, Math.ceil(weeks.length / 6)) === 0 || index === weeks.length - 1)
    .map((week) => {
      const index = weeks.indexOf(week);
      return `<text x="${xAt(index)}" y="${height - 8}" text-anchor="middle" class="chart-axis-label">${esc(week)}</text>`;
    })
    .join("");

  return `
    <h4 style="margin-top:1rem">Weekly excess returns (smoothed)</h4>
    <p class="small muted">${horizonDays}-day horizon · dashed line = zero excess vs FTSE</p>
    <div class="chart-wrap">
      <svg viewBox="0 0 ${width} ${height}" class="weekly-chart" role="img" aria-label="Smoothed weekly excess returns by strategy">
        ${gridLines}
        <line x1="${pad.left}" y1="${zeroY}" x2="${width - pad.right}" y2="${zeroY}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="4 4" />
        ${seriesPaths}
        <text x="${pad.left - 8}" y="${yAt(maxY)}" text-anchor="end" class="chart-axis-label">${pct(maxY)}</text>
        <text x="${pad.left - 8}" y="${zeroY}" text-anchor="end" class="chart-axis-label">0%</text>
        <text x="${pad.left - 8}" y="${yAt(minY)}" text-anchor="end" class="chart-axis-label">${pct(minY)}</text>
        ${xLabels}
      </svg>
      <div class="chart-legend">${legend}</div>
    </div>`;
}

function renderHistoricalAnalysis(historical) {
  if (!historical || !historical.strategy_horizons || !historical.strategy_horizons.length) {
    return `<div class="empty-state">${esc(historical?.note || "Historical analysis needs at least two archived weekly runs within the 3-year window.")}</div>`;
  }

  const windowLabel =
    historical.window_start && historical.window_end
      ? `${fmtDate(historical.window_start)} → ${fmtDate(historical.window_end)}`
      : "—";

  const keyStrategies = new Set([
    "screen:strong_buy",
    "screen:buy",
    "overlay:strong_buy",
    "overlay:buy",
    "research:pass",
    "research:downgraded",
  ]);

  const strategyRows = historical.strategy_horizons
    .filter((row) => keyStrategies.has(row.strategy))
    .sort((a, b) => a.horizon_days - b.horizon_days || a.strategy.localeCompare(b.strategy))
    .map(
      (row) => `<tr>
        <td>${row.horizon_days}d</td>
        <td>${signalBadge(row.strategy.replace(/^[^:]+:/, ""))}<br><span class="small muted">${esc(row.strategy)}</span></td>
        <td>${pct(row.smoothed_excess_return)}</td>
        <td>${pct(row.raw_excess_return)}</td>
        <td>${row.count}</td>
        <td>${row.observation_weeks}</td>
      </tr>`
    )
    .join("");

  const overlayRows = (historical.overlay_comparison || [])
    .map(
      (row) => `<tr>
        <td>${row.horizon_days}d</td>
        <td>${pct(row.smoothed_screen_excess)}</td>
        <td>${pct(row.smoothed_overlay_excess)}</td>
        <td>${row.downgrade_count}</td>
        <td>${row.sample_count}</td>
      </tr>`
    )
    .join("");

  const modelRows = (historical.model_attribution || [])
    .slice(0, 8)
    .map((row) => {
      const corr = row.smoothed_correlation != null ? row.smoothed_correlation : row.raw_correlation;
      return `<tr>
        <td>${esc(row.model_id)}</td>
        <td>${row.horizon_days}d</td>
        <td>${corr != null ? corr.toFixed(2) : "—"}</td>
        <td>${row.sample_count}</td>
      </tr>`;
    })
    .join("");

  return `
    <p class="small muted">
      ${esc(historical.note || "")}
      · ${historical.run_count} runs · ${historical.max_years}y window · ${historical.smoothing_weeks}w smoothing
    </p>
    <p class="small">Window: ${windowLabel}</p>
    ${renderWeeklySeriesChart(historical.weekly_series, 28)}
    ${renderWeeklySeriesChart(historical.weekly_series, 84)}
    <div class="table-wrap">
      <table>
        <thead><tr><th>Horizon</th><th>Strategy</th><th>Smoothed excess</th><th>Raw excess</th><th>N</th><th>Weeks</th></tr></thead>
        <tbody>${strategyRows}</tbody>
      </table>
    </div>
    ${
      overlayRows
        ? `<h4 style="margin-top:1rem">Screen vs research overlay (buy cohort)</h4>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Horizon</th><th>Screen (smoothed)</th><th>Overlay (smoothed)</th><th>Downgrades</th><th>N</th></tr></thead>
          <tbody>${overlayRows}</tbody>
        </table>
      </div>`
        : ""
    }
    ${
      modelRows
        ? `<h4 style="margin-top:1rem">Model attribution (score→return correlation)</h4>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Model</th><th>Horizon</th><th>Correlation</th><th>N</th></tr></thead>
          <tbody>${modelRows}</tbody>
        </table>
      </div>`
        : ""
    }`;
}

function renderPerformance(data) {
  const backtest = data.backtest;
  const simulation = data.simulation;
  const historical = data.historical_analysis;
  const panel = document.getElementById("panel-performance");

  let backtestHtml = '<div class="empty-state">Backtest needs at least two archived weekly runs.</div>';
  if (backtest && backtest.horizons && backtest.horizons.length) {
    backtestHtml = `
      <p class="small muted">${esc(backtest.note || "")} · ${backtest.run_count} archived runs</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Horizon</th><th>Signal</th><th>Avg return</th><th>Benchmark</th><th>Excess</th><th>N</th></tr></thead>
          <tbody>
            ${backtest.horizons
              .map(
                (h) => `<tr>
              <td>${h.horizon_days}d</td>
              <td>${signalBadge(h.signal)}</td>
              <td>${pct(h.avg_return)}</td>
              <td>${pct(h.benchmark_return)}</td>
              <td>${pct(h.excess_return)}</td>
              <td>${h.count}</td>
            </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>`;
  }

  let simHtml = '<div class="empty-state">Simulation needs at least two archived weekly runs.</div>';
  if (simulation && simulation.final_value != null) {
    const overlay = simulation.research_overlay;
    const rows = [
      {
        label: "Screen only",
        data: simulation,
      },
    ];
    if (overlay) {
      rows.push({ label: "Research overlay", data: overlay });
    }

    const tableRows = rows
      .map(
        ({ label, data }) => `<tr>
          <td><strong>${esc(label)}</strong></td>
          <td>£${Number(data.final_value).toFixed(2)}</td>
          <td>${pct(data.total_return)}</td>
          <td>${pct(data.excess_return)}</td>
          <td>${data.trade_count}</td>
        </tr>`
      )
      .join("");

    const holdings = Object.entries(simulation.holdings || {})
      .map(([ticker, shares]) => `<li>${esc(ticker)}: ${shares} shares</li>`)
      .join("");

    simHtml = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Strategy</th><th>Final value</th><th>Return</th><th>vs FTSE</th><th>Trades</th></tr></thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
      <p class="small muted">${esc(simulation.comparison_note || simulation.note || "")}</p>
      <p class="small">Costs: £${Number(simulation.total_costs || 0).toFixed(2)} (${pct(simulation.trade_cost_pct)} per trade) · ${simulation.periods} periods</p>
      ${holdings ? `<p><strong>Screen holdings</strong><ul class="list-plain">${holdings}</ul></p>` : ""}`;
  }

  panel.innerHTML = `
    <div class="card">
      <h3>Signal backtest</h3>
      ${backtestHtml}
    </div>
    <div class="card" style="margin-top:1rem">
      <h3>Portfolio simulation (£1,000)</h3>
      ${simHtml}
    </div>
    <div class="card" style="margin-top:1rem">
      <h3>Historical analysis</h3>
      <p class="small muted">Point-in-time replay of screen signals, research verdicts, and model scores with weekly smoothing.</p>
      ${renderHistoricalAnalysis(historical)}
    </div>
  `;
}

async function openMemo(item) {
  const dialog = document.getElementById("memo-dialog");
  const title = document.getElementById("memo-title");
  const body = document.getElementById("memo-body");
  title.textContent = `${item.name} (${item.ticker})`;
  body.innerHTML = "<p class='muted'>Loading memo…</p>";
  dialog.showModal();
  try {
    const response = await fetch(item.memo_path);
    if (!response.ok) throw new Error("Memo not found");
    const markdown = await response.text();
    body.innerHTML = marked.parse(markdown);
  } catch (err) {
    body.innerHTML = `<p class="muted">Could not load research memo (${esc(err.message)}).</p>`;
  }
}

function renderAnalysis(data) {
  const deep = data.deep_analysis;
  const research = data.research || [];
  const panel = document.getElementById("panel-analysis");

  let deepHtml = '<div class="empty-state">Deep analysis not available for this run (requires CURSOR_API_KEY in CI).</div>';
  if (deep) {
    deepHtml = `
      <div class="card">
        <h3>Executive intro</h3>
        <p>${esc(deep.executive_intro || "").replace(/\n/g, "<br>")}</p>
      </div>
      <div class="card" style="margin-top:1rem">
        <h3>Top picks analysis</h3>
        <p>${esc(deep.top_picks_analysis || "").replace(/\n/g, "<br>")}</p>
      </div>
      <div class="card" style="margin-top:1rem">
        <h3>Red flags</h3>
        <p>${esc(deep.red_flags || "").replace(/\n/g, "<br>")}</p>
      </div>`;
  }

  let researchHtml = '<div class="empty-state">No per-ticker research memos published yet.</div>';
  if (research.length) {
    researchHtml = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Company</th><th>Verdict</th><th>Version</th><th>Summary</th><th></th></tr></thead>
          <tbody>
            ${research
              .map(
                (item, index) => `
              <tr>
                <td><strong>${esc(item.name)}</strong><br><span class="small muted">${esc(item.ticker)}</span></td>
                <td>${item.research_verdict ? `<span class="badge badge-${esc(item.research_verdict)}">${esc(item.research_verdict)}</span>` : '<span class="muted">—</span>'}</td>
                <td>v${item.version || 1}<br><span class="small muted">${fmtDate(item.updated_at)}</span></td>
                <td class="small">${esc((item.executive_summary || "").slice(0, 240))}${(item.executive_summary || "").length > 240 ? "…" : ""}</td>
                <td><button type="button" class="btn btn-primary" data-memo-index="${index}">Read memo</button></td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>`;
  }

  panel.innerHTML = `
    <h2 class="small muted" style="margin-top:0">Portfolio deep analysis</h2>
    ${deepHtml}
    <h2 style="margin-top:1.5rem">Strong buy research memos</h2>
    ${researchHtml}
  `;

  panel.querySelectorAll("[data-memo-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.memoIndex);
      openMemo(research[index]);
    });
  });
}

function renderDashboard(data) {
  dashboardData = data;
  const meta = data.meta || {};
  document.getElementById("run-meta").textContent = data.run_at
    ? `${meta.universe_label || "FTSE"} · ${meta.company_count || 0} companies · ${meta.strong_buy_count || 0} strong buys · ${fmtDate(data.run_at)}`
  : "Awaiting first published screening run";

  renderOverview(data);
  renderScreener(data);
  renderStrongBuys(data);
  renderPortfolio(data);
  renderPerformance(data);
  renderAnalysis(data);
}

async function loadDashboard() {
  try {
    const response = await fetch("data/latest.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderDashboard(data);
  } catch (err) {
    document.getElementById("run-meta").textContent = `Failed to load dashboard data: ${err.message}`;
    document.getElementById("panel-overview").innerHTML =
      '<div class="empty-state">Could not load <code>data/latest.json</code>. Run <code>ftse-publish</code> after a screen, or wait for the weekly GitHub workflow.</div>';
  }
}

initTabs();
loadDashboard();
