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
  { id: "trusts", label: "Trusts" },
  { id: "strong-buys", label: "Strong buys" },
  { id: "portfolio", label: "Portfolio" },
  { id: "automation", label: "Automation" },
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

function iiTradabilityBadge(report) {
  const tradable = report.tradable_on_t212 ?? report.tradable_on_ii;
  if (tradable === true) {
    const verified = report.broker_basis === "catalogue_hit" || report.ii_confidence === "verified";
    const label = verified ? "T212" : (report.ii_deal_channel === "phone" ? "phone" : "T212 assumed");
    const title = verified
      ? "Present in Trading 212 instrument catalogue"
      : "Advisory venue allowlist — not a confirmed T212 catalogue hit";
    return `<span class="badge badge-ii-ok" title="${esc(title)}">${esc(label)}</span>`;
  }
  if (tradable === false) {
    const why = report.broker_basis === "unknown_venue" || report.ii_basis === "unknown_venue"
      ? "Not on T212"
      : (report.ii_basis === "phone_only" ? "phone-only venue" : "T212 unclear");
    return `<span class="badge badge-ii-no" title="Advisory — confirm in Trading 212 before acting">${esc(why)}</span>`;
  }
  return "";
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

function decisionPackHtml(report) {
  const pack = report.decision_pack;
  if (!pack) return "";
  const verify = Array.isArray(pack.verify) ? pack.verify : [];
  const verifyList = verify.length
    ? `<ul class="decision-pack-verify">${verify.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`
    : "";
  const gapNote = pack.high_conviction
    ? ""
    : '<p class="small decision-pack-caution">Evidence incomplete or cautious — do not size as high-conviction.</p>';
  return `
    <div class="decision-pack">
      <p class="small decision-pack-title"><strong>Verify before trade</strong></p>
      ${gapNote}
      <p class="small"><strong>Thesis:</strong> ${esc(pack.thesis || "—")}</p>
      <p class="small"><strong>Levels:</strong> ${esc(pack.levels || "—")}</p>
      <p class="small"><strong>Size:</strong> ${esc(pack.size || "—")}</p>
      <p class="small"><strong>Risks:</strong> ${esc(pack.risks || "—")}</p>
      ${verifyList}
    </div>`;
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

  const trustCount = meta.trust_count || (data.trust_reports || []).length || 0;
  const trustCounts = meta.trust_signal_counts || {};
  const trustSegments = Object.entries(trustCounts).sort((a, b) => b[1] - a[1]);

  document.getElementById("panel-overview").innerHTML = `
    ${note}
    <div class="grid">
      <div class="card">
        <h3>Operating companies</h3>
        <div class="stat-value">${total}</div>
      </div>
      <div class="card">
        <h3>Strong buys</h3>
        <div class="stat-value" style="color:var(--strong-buy)">${meta.strong_buy_count || 0}</div>
      </div>
      <div class="card">
        <h3>Trust track</h3>
        <div class="stat-value">${trustCount}</div>
        <div class="small muted">Discount / income screen</div>
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
    ${trustSegments.length ? `
    <div class="card" style="margin-top:1rem">
      <h3>Trust signal distribution</h3>
      <ul class="list-plain small">
        ${trustSegments.map(([s, c]) => `<li>${signalBadge(s)} ${c}</li>`).join("")}
      </ul>
    </div>` : ""}
    <div class="card" style="margin-top:1rem">
      <h3>Week-over-week changes</h3>
      ${diffHtml}
    </div>
  `;
}

function renderTrusts(data) {
  const reports = data.trust_reports || [];
  const panel = document.getElementById("panel-trusts");
  if (!reports.length) {
    panel.innerHTML = `
      <div class="empty-state">
        No investment-trust track results yet. Trusts are screened separately using
        discount to book (NAV proxy), yield, and premium risk.
      </div>`;
    return;
  }

  const rows = reports
    .slice()
    .sort((a, b) => {
      const order = { strong_buy: 0, buy: 1, hold: 2, avoid: 3, insufficient_data: 4 };
      return (order[a.signal] ?? 9) - (order[b.signal] ?? 9) || (b.conviction_score || 0) - (a.conviction_score || 0);
    })
    .map((report) => {
      const metrics = report.key_metrics
        ? Object.entries(report.key_metrics)
            .slice(0, 4)
            .map(([k, v]) => `${esc(k)} ${esc(v)}`)
            .join(" · ")
        : "";
      return `<tr>
        <td><strong>${esc(report.name)}</strong><br><span class="muted small">${esc(report.ticker)}</span></td>
        <td>${signalBadge(report.signal)}</td>
        <td class="small">${report.models_passed}/${report.model_count}</td>
        <td class="small">${metrics || "—"}</td>
        <td class="small">${esc(report.summary || "")}</td>
      </tr>`;
    })
    .join("");

  panel.innerHTML = `
    <p class="muted small" style="margin-top:0">
      Closed-end funds and investment trusts use book value as a NAV proxy
      (Yahoo does not publish LSE trust NAVs). This track is separate from the operating-company Graham models.
    </p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Trust</th>
            <th>Signal</th>
            <th>Models</th>
            <th>Key metrics</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
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
  if (typeof window.IIUnavailable?.mergeServer === "function") {
    window.IIUnavailable.mergeServer(data.unavailable_watch);
  }

  const reports = (data.reports || []).filter((r) => r.signal === "strong_buy" || r.signal === "buy");
  const panel = document.getElementById("panel-strong-buys");
  const blocked = typeof window.IIUnavailable?.tickerSet === "function"
    ? window.IIUnavailable.tickerSet()
    : new Set();
  const active = reports.filter((r) => !blocked.has(String(r.ticker || "").toUpperCase()));
  const watched = typeof window.IIUnavailable?.load === "function"
    ? window.IIUnavailable.load().items
    : [];
  const reportByTicker = new Map((data.reports || []).map((r) => [String(r.ticker).toUpperCase(), r]));

  if (!active.length && !watched.length) {
    panel.innerHTML = '<div class="empty-state">No strong buy or buy recommendations in the latest run.</div>';
    return;
  }

  const strong = active.filter((r) => r.signal === "strong_buy");
  const buys = active.filter((r) => r.signal === "buy");

  const cardHtml = (report) => `
    <div class="card pick-card">
      <h4>${esc(report.name)} <span class="small muted">(${esc(report.ticker)})</span></h4>
      <p>${signalBadge(report.signal)} ${timingBadge(report.timing_signal)} ${iiTradabilityBadge(report)} · Conviction ${pct(report.conviction_score)}${researchOverlayHtml(report)}</p>
      <p class="small">${esc(report.action_note || "")}</p>
      <p class="small"><strong>Trade plan:</strong><br>${tradePlanHtml(report)}</p>
      ${decisionPackHtml(report)}
      <p class="small">${esc(report.summary || "")}</p>
      <p class="pick-actions">
        <button type="button" class="btn" data-chart-ticker="${esc(report.ticker)}">Price chart</button>
        <button type="button" class="btn btn-primary" data-log-ticker="${esc(report.ticker)}">Log action</button>
        <button type="button" class="btn btn-warn" data-unavailable-ticker="${esc(report.ticker)}" title="Bypass this suggested trade — keep watching in case it becomes tradable on Trading 212">Unavailable</button>
      </p>
    </div>`;

  const watchedHtml = watched.length
    ? `<div class="unavailable-watch-block">
        <h3>Watched — unavailable to trade</h3>
        <p class="small muted">Bypassed suggested trades. Still screened when present in the universe; restore if they become actionable on Trading 212.</p>
        ${watched
          .map((item) => {
            const live = reportByTicker.get(item.ticker);
            const name = live?.name || item.name || item.ticker;
            const signal = live ? signalBadge(live.signal) : '<span class="badge badge-watch">watching</span>';
            const ii = live ? iiTradabilityBadge(live) : "";
            return `<div class="card pick-card pick-card-muted">
              <h4>${esc(name)} <span class="small muted">(${esc(item.ticker)})</span></h4>
              <p>${signal} ${ii} <span class="small muted">${esc(item.reason || "unavailable_on_ii")}</span></p>
              <p class="small muted">${live ? esc(live.action_note || "Still on latest screen.") : "Not in the latest published buy tier — kept on watch."}</p>
              <p class="pick-actions">
                ${live ? `<button type="button" class="btn" data-chart-ticker="${esc(item.ticker)}">Price chart</button>` : ""}
                <button type="button" class="btn btn-primary" data-restore-ticker="${esc(item.ticker)}">Restore to suggestions</button>
              </p>
            </div>`;
          })
          .join("")}
      </div>`
    : "";

  panel.innerHTML = `
    <p class="small muted" style="margin-top:0">Mark <strong>Unavailable</strong> to bypass a suggested trade that cannot be actioned on Trading 212. The name stays watched below and is excluded from paper auto-entries until restored.</p>
    ${strong.length ? `<h3>Strong buys</h3>${strong.map(cardHtml).join("")}` : ""}
    ${buys.length ? `<h3>Buys</h3>${buys.map(cardHtml).join("")}` : ""}
    ${!active.length ? '<div class="empty-state">All buy-tier names are on the unavailable watch list.</div>' : ""}
    ${watchedHtml}
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

  panel.querySelectorAll("[data-unavailable-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      const ticker = button.dataset.unavailableTicker;
      const report = byTicker.get(ticker) || { ticker };
      if (typeof window.IIUnavailable?.mark === "function") {
        window.IIUnavailable.mark(report);
      }
      renderStrongBuys(data);
      if (typeof renderPortfolio === "function") renderPortfolio(data);
    });
  });

  panel.querySelectorAll("[data-restore-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      if (typeof window.IIUnavailable?.restore === "function") {
        window.IIUnavailable.restore(button.dataset.restoreTicker);
      }
      renderStrongBuys(data);
      if (typeof renderPortfolio === "function") renderPortfolio(data);
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

const PERF_SIM_TRACK_KEY = "ftseValueInvestor.perfSimTrack.v1";

const PERF_SIM_TRACKS = [
  {
    id: "screen",
    label: "Screen",
    blurb: "Conviction rebalance only — ignores trade-plan limits and stops.",
  },
  {
    id: "overlay",
    label: "Research overlay",
    blurb: "Same as screen but uses adjusted_signal when research is present.",
  },
  {
    id: "static",
    label: "Static levels",
    blurb: "Honours each archive period’s core limit, stop, and target as published.",
  },
  {
    id: "trailing",
    label: "Trailing stop",
    blurb: "Stop trails up with refreshed technicals but never below the original entry stop.",
  },
];

function loadPerfSimTrack() {
  try {
    const saved = localStorage.getItem(PERF_SIM_TRACK_KEY);
    if (PERF_SIM_TRACKS.some((t) => t.id === saved)) return saved;
  } catch {
    /* ignore */
  }
  return "screen";
}

function savePerfSimTrack(trackId) {
  try {
    localStorage.setItem(PERF_SIM_TRACK_KEY, trackId);
  } catch {
    /* ignore */
  }
}

function simTrackPayload(simulation, trackId) {
  if (!simulation) return null;
  if (trackId === "overlay") return simulation.research_overlay || simulation;
  if (trackId === "static") return simulation.static_levels || null;
  if (trackId === "trailing") return simulation.trailing_levels || null;
  return simulation;
}

function renderSimTrackDetail(track, data, simulation) {
  if (!data || data.final_value == null) {
    return `<div class="empty-state">No results for ${esc(track.label)} yet. Needs archived runs with enough history${
      track.id === "static" || track.id === "trailing" ? " and trade-plan fields" : ""
    }.</div>`;
  }
  const holdings = Object.entries(data.holdings || {})
    .map(([ticker, shares]) => `<li>${esc(ticker)}: ${shares} shares</li>`)
    .join("");
  return `
    <p class="small muted">${esc(track.blurb)}</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Final value</th><th>Return</th><th>vs FTSE</th><th>Trades</th><th>Costs</th></tr></thead>
        <tbody>
          <tr>
            <td>£${Number(data.final_value).toFixed(2)}</td>
            <td>${pct(data.total_return)}</td>
            <td>${pct(data.excess_return)}</td>
            <td>${data.trade_count ?? "—"}</td>
            <td>£${Number(data.total_costs || 0).toFixed(2)}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="small">${data.periods ?? simulation.periods ?? "—"} periods · ${pct(data.trade_cost_pct ?? simulation.trade_cost_pct)} per trade</p>
    ${data.note ? `<p class="small muted">${esc(data.note)}</p>` : ""}
    ${holdings ? `<p><strong>Holdings</strong><ul class="list-plain">${holdings}</ul></p>` : ""}`;
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
    const activeId = loadPerfSimTrack();
    const available = PERF_SIM_TRACKS.filter((track) => {
      if (track.id === "screen") return true;
      if (track.id === "overlay") return !!simulation.research_overlay;
      if (track.id === "static") return !!simulation.static_levels;
      if (track.id === "trailing") return !!simulation.trailing_levels;
      return false;
    });
    const selected =
      available.find((t) => t.id === activeId) || available[0] || PERF_SIM_TRACKS[0];
    const trackData = simTrackPayload(simulation, selected.id);
    const comparisonRows = available
      .map((track) => {
        const row = simTrackPayload(simulation, track.id);
        if (!row || row.final_value == null) return "";
        return `<tr>
          <td><strong>${esc(track.label)}</strong></td>
          <td>£${Number(row.final_value).toFixed(2)}</td>
          <td>${pct(row.total_return)}</td>
          <td>${pct(row.excess_return)}</td>
          <td>${row.trade_count ?? "—"}</td>
        </tr>`;
      })
      .join("");

    simHtml = `
      <nav class="paper-subnav sim-subnav" aria-label="Simulation tracks">
        ${available
          .map(
            (track) =>
              `<button type="button" class="paper-subtab${
                track.id === selected.id ? " active" : ""
              }" data-sim-track="${track.id}">${esc(track.label)}</button>`
          )
          .join("")}
      </nav>
      <div id="sim-track-detail">
        ${renderSimTrackDetail(selected, trackData, simulation)}
      </div>
      <details class="sim-compare-details">
        <summary>Compare all tracks</summary>
        <div class="table-wrap" style="margin-top:0.75rem">
          <table>
            <thead><tr><th>Track</th><th>Final value</th><th>Return</th><th>vs FTSE</th><th>Trades</th></tr></thead>
            <tbody>${comparisonRows}</tbody>
          </table>
        </div>
        <p class="small muted">${esc(simulation.comparison_note || simulation.note || "")}</p>
      </details>`;
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

  panel.querySelectorAll("[data-sim-track]").forEach((button) => {
    button.addEventListener("click", () => {
      const trackId = button.dataset.simTrack;
      savePerfSimTrack(trackId);
      const track = PERF_SIM_TRACKS.find((t) => t.id === trackId);
      const detail = panel.querySelector("#sim-track-detail");
      if (!track || !detail) return;
      panel.querySelectorAll("[data-sim-track]").forEach((el) => {
        el.classList.toggle("active", el === button);
      });
      detail.innerHTML = renderSimTrackDetail(
        track,
        simTrackPayload(simulation, trackId),
        simulation
      );
    });
  });
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

function settingRow(label, value) {
  return `<div class="setting-row"><span class="setting-label">${esc(label)}</span><span class="setting-value">${value}</span></div>`;
}

function boolLabel(value) {
  if (value === true) return '<span class="badge badge-ii-ok">on</span>';
  if (value === false) return '<span class="badge badge-ii-no">off</span>';
  return '<span class="muted">—</span>';
}

function renderAutomation(data) {
  const panel = document.getElementById("panel-automation");
  if (!panel) return;
  const auto = data.automation;
  if (!auto) {
    panel.innerHTML =
      '<div class="empty-state">Automation status not published yet. Run <code>ftse-library automation-status</code> or wait for the next ladder / publish.</div>';
    return;
  }

  const settings = auto.settings || {};
  const paper = settings.paper || {};
  const library = settings.library || {};
  const budget = library.budget || {};
  const ladder = library.ladder || {};
  const fg = library.focus_graduation || {};
  const workflows = settings.workflows || {};
  const achievements = auto.achievements || {};
  const timeline = achievements.timeline || [];
  const lastLadder = achievements.last_ladder || {};
  const paperLast = achievements.paper_last_run || {};
  const milestones = achievements.milestones || {};

  const graduated = (library.graduated_markets || [])
    .map((g) => esc(g.market))
    .join(", ") || "—";

  const workflowHtml = Object.values(workflows)
    .map(
      (wf) => `
      <div class="setting-row">
        <span class="setting-label">${esc(wf.name || wf.workflow || "Workflow")}</span>
        <span class="setting-value small">${esc(wf.cadence || wf.cron || "—")}</span>
      </div>`
    )
    .join("");

  const timelineHtml = timeline.length
    ? `<ol class="automation-timeline">
        ${timeline
          .map(
            (event) => `
          <li class="automation-event kind-${esc(event.kind || "other")}">
            <div class="automation-event-when">${esc(fmtDate(event.at))}</div>
            <div class="automation-event-body">
              <strong>${esc(event.title || event.kind || "Event")}</strong>
              <div class="small muted">${esc(event.detail || "")}</div>
            </div>
          </li>`
          )
          .join("")}
      </ol>`
    : '<p class="muted">No dated automation achievements recorded yet.</p>';

  const milestoneBits = [];
  if (milestones.ladder_complete?.completed_at) {
    milestoneBits.push(
      `<li><strong>Initial queue complete</strong> — ${esc(fmtDate(milestones.ladder_complete.completed_at))} · focus ${esc(milestones.ladder_complete.focus_market || "—")}</li>`
    );
  }
  if (milestones.l34_slices?.completed_at) {
    milestoneBits.push(
      `<li><strong>L34 next slices</strong> — ${esc(fmtDate(milestones.l34_slices.completed_at))} · ${esc((milestones.l34_slices.new_markets || []).join(", "))} · ${esc(String(milestones.l34_slices.research_memos_created ?? "—"))} memos</li>`
    );
  }

  panel.innerHTML = `
    <p class="small muted" style="margin-top:0">${esc(auto.note || "Current automation settings and dated achievements.")} Updated ${esc(fmtDate(auto.generated_at))}.</p>

    <div class="automation-grid">
      <section class="automation-section">
        <h2>Current settings</h2>
        <h3>Paper automation</h3>
        ${settingRow("Enabled", boolLabel(paper.enabled))}
        ${settingRow("Timezone", esc(paper.timezone || "—"))}
        ${settingRow("Market open / settle", esc(`${paper.market_open || "—"} + ${paper.settle_minutes_after_open ?? "—"} min`))}
        ${settingRow("Weekdays only", boolLabel(paper.weekdays_only))}
        ${settingRow("Auto rebalance", boolLabel(paper.auto_rebalance))}
        ${settingRow("Surveil holdings / watchlist", `${boolLabel(paper.surveil_paper_holdings)} / ${boolLabel(paper.surveil_watchlist)}`)}
        ${settingRow("Max positions", esc(paper.max_positions ?? "—"))}
        ${settingRow("Initial cash / trade cost", esc(`${paper.initial_cash ?? "—"} / ${paper.trade_cost_pct ?? "—"}`))}

        <h3>Library ladder</h3>
        ${settingRow("Enabled", boolLabel(ladder.enabled))}
        ${settingRow("Focus market", esc(library.focus_market || "—"))}
        ${settingRow("Queue complete", boolLabel(library.queue_complete))}
        ${settingRow("Graduated markets", `<span class="small">${graduated}</span>`)}
        ${settingRow("Auto-advance", boolLabel(fg.auto_advance))}
        ${settingRow("Coverage / stale floors", esc(`${fg.min_coverage_pct ?? "—"} / ${fg.max_stale_pct ?? "—"}`))}
        ${settingRow("Maintenance", `${boolLabel(fg.maintenance_enabled)} · max=${esc(fg.maintenance_max_tickers ?? "—")}`)}
        ${settingRow("Research hard cap", esc(ladder.research_hard_cap ?? "—"))}
        ${settingRow("Research all graduated", boolLabel(ladder.research_all_graduated))}
        ${settingRow("Research model", esc((library.research_model || {}).model_id || "—"))}

        <h3>Budget</h3>
        ${settingRow("Plan (subscription)", esc(`${budget.plan_name || "—"} · $${budget.plan_monthly_usd ?? "—"}/mo`))}
        ${settingRow(
          "Weekly usage allocation",
          esc(
            budget.allocation_basis === "usage_weekly_gbp"
              ? `£${budget.weekly_usage_gbp ?? "—"}/week × ${budget.gbp_usd_rate ?? "—"} → $${budget.weekly_library_usd ?? "—"} · enforce=${budget.enforce_weekly_research_cap ? "on" : "off"}`
              : `$${budget.weekly_library_usd ?? "—"} · enforce=${budget.enforce_weekly_research_cap ? "on" : "off"}`
          )
        )}
        ${settingRow(
          "Budget flag",
          budget.constraining
            ? `<span class="badge badge-ii-no">${esc(budget.budget_flag || "constraining")}</span>${budget.budget_note ? ` · <span class="small muted">${esc(budget.budget_note)}</span>` : ""}`
            : budget.near_limit
              ? `<span class="badge badge-watch">${esc(budget.budget_flag || "near_limit")}</span>`
              : esc(budget.budget_flag || (budget.enforce_weekly_research_cap ? "enforced" : "unconstrained"))
        )}
        ${settingRow("Refresh / surplus day", esc(`${budget.plan_refresh_day_of_month ?? "—"} / day before`))}
        ${settingRow("Spend this week / cycle", esc(`$${budget.estimated_spend_usd_this_week ?? "—"} / $${budget.estimated_spend_usd_this_cycle ?? "—"} (remaining $${budget.remaining_weekly_usd ?? "—"})`))}

        <h3>Scheduled workflows</h3>
        ${workflowHtml || '<p class="muted">No workflow schedules recorded.</p>'}
      </section>

      <section class="automation-section">
        <h2>Achievements</h2>
        ${
          milestoneBits.length
            ? `<h3>Milestones</h3><ul class="list-plain">${milestoneBits.join("")}</ul>`
            : ""
        }
        <h3>Latest ladder snapshot</h3>
        ${
          lastLadder.run_at
            ? `${settingRow("Run at", esc(fmtDate(lastLadder.run_at)))}
               ${settingRow("Focus", esc(lastLadder.focus_market || "—"))}
               ${settingRow("Shortlist / research", esc(`${(lastLadder.layers || {}).screen_shortlist ?? "—"} / created ${(lastLadder.layers || {}).research_created ?? "—"}`))}`
            : '<p class="muted">No ladder snapshot yet.</p>'
        }
        <h3>Latest paper run</h3>
        ${
          paperLast.generated_at || paperLast.acted != null
            ? `${settingRow("When", esc(fmtDate(paperLast.generated_at || (paperLast.gate || {}).local_time)))}
               ${settingRow("Acted", boolLabel(!!paperLast.acted))}
               ${settingRow("Trades", esc(paperLast.trade_count ?? "—"))}
               <p class="small muted">${esc(paperLast.note || "")}</p>`
            : '<p class="muted">No paper automation run recorded yet.</p>'
        }
        <h3>Dated record</h3>
        ${timelineHtml}
      </section>
    </div>
  `;
}

function renderDashboard(data) {
  dashboardData = data;
  const meta = data.meta || {};
  const trustCount = meta.trust_count || (data.trust_reports || []).length || 0;
  document.getElementById("run-meta").textContent = data.run_at
    ? `${meta.universe_label || "FTSE"} · ${meta.company_count || 0} companies · ${trustCount} trusts · ${meta.strong_buy_count || 0} strong buys · ${fmtDate(data.run_at)}`
  : "Awaiting first published screening run";

  renderOverview(data);
  renderScreener(data);
  renderTrusts(data);
  renderStrongBuys(data);
  renderPortfolio(data);
  renderAutomation(data);
  renderPerformance(data);
  renderAnalysis(data);
}

async function loadDashboard() {
  try {
    const response = await fetch("data/latest.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!data.automation) {
      try {
        const autoResp = await fetch("data/automation.json");
        if (autoResp.ok) data.automation = await autoResp.json();
      } catch {
        /* optional sidecar */
      }
    }
    renderDashboard(data);
  } catch (err) {
    document.getElementById("run-meta").textContent = `Failed to load dashboard data: ${err.message}`;
    document.getElementById("panel-overview").innerHTML =
      '<div class="empty-state">Could not load <code>data/latest.json</code>. Run <code>ftse-publish</code> after a screen, or wait for the weekly GitHub workflow.</div>';
  }
}

initTabs();
loadDashboard();
