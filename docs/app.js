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
  const openQs = Array.isArray(pack.unresolved_questions) ? pack.unresolved_questions : [];
  const openList = openQs.length
    ? `<p class="small"><strong>Open questions:</strong></p><ul class="decision-pack-verify">${openQs
        .map((item) => `<li>${esc(item)}</li>`)
        .join("")}</ul>`
    : "";
  const grade = pack.memo_quality_grade
    ? pack.memo_quality_score != null
      ? ` · memo ${esc(pack.memo_quality_grade)} (${Number(pack.memo_quality_score).toFixed(2)})`
      : ` · memo ${esc(pack.memo_quality_grade)}`
    : "";
  const gapNote = pack.high_conviction
    ? ""
    : '<p class="small decision-pack-caution">Evidence incomplete or cautious — do not size as high-conviction.</p>';
  return `
    <div class="decision-pack">
      <p class="small decision-pack-title"><strong>Verify before trade</strong>${grade}</p>
      ${gapNote}
      <p class="small"><strong>Thesis:</strong> ${esc(pack.thesis || "—")}</p>
      <p class="small"><strong>Levels:</strong> ${esc(pack.levels || "—")}</p>
      <p class="small"><strong>Size:</strong> ${esc(pack.size || "—")}</p>
      <p class="small"><strong>Risks:</strong> ${esc(pack.risks || "—")}</p>
      ${openList}
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

function stageStatusBadge(status) {
  const labels = {
    complete: "complete",
    in_progress: "in progress",
    not_started: "not started",
  };
  const cls = {
    complete: "stage-complete",
    in_progress: "stage-active",
    not_started: "stage-pending",
  };
  const key = status || "in_progress";
  return `<span class="stage-badge ${cls[key] || "stage-active"}">${esc(labels[key] || key)}</span>`;
}

function renderProjectProgress(data) {
  const progress = data.project_progress;
  if (!progress) {
    return "";
  }

  const appraisal = progress.appraisal || {};
  const ingest = progress.ingest_bottleneck || {};
  const stages = progress.stages || [];

  const stageRows = stages
    .map(
      (stage) => `
      <div class="setting-row">
        <span class="setting-label"><strong>${esc(stage.id)}</strong> ${esc(stage.name)}</span>
        <span class="setting-value">${stageStatusBadge(stage.status)}</span>
      </div>
      <div class="small muted" style="margin:-0.35rem 0 0.65rem 0">${esc(stage.focus || "")}</div>`
    )
    .join("");

  const list = (items) =>
    (items || []).length
      ? `<ul class="list-plain small">${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`
      : '<p class="muted small">—</p>';

  const ingestHtml = ingest.summary
    ? `
    <div class="card" style="margin-top:1rem">
      <h3>Ingest bottleneck</h3>
      <p class="small">${esc(ingest.summary)}</p>
      ${ingest.stalled ? `<p class="small"><strong>Status:</strong> stalled (zero_body_buy_tier=${esc(String(ingest.zero_body_buy_tier ?? "—"))})</p>` : '<p class="small muted">No active stall detected in latest health log.</p>'}
      <h4 class="small" style="margin-top:0.75rem">Recommended fixes</h4>
      ${list(ingest.fixes)}
      <h4 class="small" style="margin-top:0.75rem">Commands</h4>
      <ul class="list-plain small">${(ingest.commands || []).map((cmd) => `<li><code>${esc(cmd)}</code></li>`).join("")}</ul>
    </div>`
    : "";

  return `
    <div class="card" style="margin-top:1rem">
      <h3>Project progress</h3>
      <p class="small muted" style="margin-top:0">Current focus: <strong>${esc(progress.current_focus || "—")}</strong> · Updated ${esc(fmtDate(progress.generated_at))}</p>
      <p>${esc(progress.headline || "")}</p>
      <div class="automation-grid" style="margin-top:0.75rem">
        <section class="automation-section">
          <h4>North-star stages</h4>
          ${stageRows}
        </section>
        <section class="automation-section">
          <h4>Strengths</h4>
          ${list(appraisal.strengths)}
          <h4 style="margin-top:1rem">Gaps</h4>
          ${list(appraisal.gaps)}
          <h4 style="margin-top:1rem">Next actions</h4>
          ${list(appraisal.next_actions)}
        </section>
      </div>
    </div>
    ${ingestHtml}
  `;
}

function renderIngestHealth(data) {
  const ingest = data.ingest_improvement;
  const progress = data.project_progress || {};
  const bottleneck = progress.ingest_bottleneck || {};
  const health = bottleneck.health || {};

  if (!ingest && !health.buy_tier_count) {
    return "";
  }

  const rows = [];
  if (health.buy_tier_count != null) {
    rows.push(
      `<div class="setting-row"><span class="setting-label">Buy-tier measured</span><span class="setting-value">${esc(String(health.measured_tickers ?? "—"))} / ${esc(String(health.buy_tier_count ?? "—"))}</span></div>`
    );
    rows.push(
      `<div class="setting-row"><span class="setting-label">Zero-body tickers</span><span class="setting-value">${esc(String(health.zero_body_buy_tier ?? "—"))}</span></div>`
    );
    if ((health.unmeasured_buy_tier || 0) > 0) {
      rows.push(
        `<div class="setting-row"><span class="setting-label">Unmeasured</span><span class="setting-value">${esc(String(health.unmeasured_buy_tier))}</span></div>`
      );
    }
  }
  if (ingest) {
    rows.push(
      `<div class="setting-row"><span class="setting-label">Last ingest pass</span><span class="setting-value">${esc(String(ingest.improved ?? 0))} improved · ${esc(String((ingest.targets || []).length))} targets</span></div>`
    );
    if (ingest.run_at) {
      rows.push(
        `<div class="setting-row"><span class="setting-label">Run at</span><span class="setting-value small">${esc(fmtDate(ingest.run_at))}</span></div>`
      );
    }
  }

  const zeroList = (health.zero_body_tickers || []).slice(0, 8);
  const zeroHtml = zeroList.length
    ? `<p class="small muted">Zero-body: ${zeroList.map((t) => esc(t)).join(", ")}</p>`
    : "";

  return `
    <div class="card" style="margin-top:1rem">
      <h3>Ingest health</h3>
      ${rows.join("")}
      ${zeroHtml}
    </div>
  `;
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
    ${renderProjectProgress(data)}
    ${renderIngestHealth(data)}
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
  {
    id: "momentum_grace",
    label: "Momentum grace",
    blurb: "Screen rules plus a bounded hold when value downgrades but price trend stays strong.",
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
  if (trackId === "momentum_grace") return simulation.momentum_grace || null;
  return simulation;
}

function renderSimTrackDetail(track, data, simulation) {
  if (!data || data.final_value == null) {
    return `<div class="empty-state">No results for ${esc(track.label)} yet. Needs archived runs with enough history${
      track.id === "static" || track.id === "trailing" ? " and trade-plan fields" : ""
    }.</div>`;
  }
  const zeroTradeLevels =
    (track.id === "static" || track.id === "trailing") && Number(data.trade_count || 0) === 0;
  const levelCallout = zeroTradeLevels
    ? `<div class="callout callout-warn" style="margin:0.75rem 0">
        <strong>No trades in this window.</strong>
        ${esc(
          data.note ||
            "Static/trailing tracks only enter when spot is at or below the published core limit. The screen track uses market-style rebalance and may trade while these stay in cash."
        )}
      </div>`
    : "";
  const holdings = Object.entries(data.holdings || {})
    .map(([ticker, shares]) => `<li>${esc(ticker)}: ${shares} shares</li>`)
    .join("");
  return `
    <p class="small muted">${esc(track.blurb)}</p>
    ${levelCallout}
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
      if (track.id === "momentum_grace") return !!simulation.momentum_grace;
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

function memoQualityBadge(item) {
  const quality = item.memo_quality || {};
  const grade = quality.grade;
  if (!grade) return '<span class="muted">—</span>';
  const score = quality.source_quality_score;
  const label = score != null ? `${grade} (${Number(score).toFixed(2)})` : grade;
  return `<span class="badge badge-${esc(grade)}">${esc(label)}</span>`;
}

function renderSundayReview(data) {
  const review = data.sunday_review;
  if (!review) {
    return `
      <section class="automation-section automation-section-full sunday-review-section">
        <h2>Sunday review</h2>
        <p class="muted">No Sunday review tables published yet — run <code>ftse-publish</code> after analysis-review.</p>
      </section>`;
  }

  const current = review.current || {};
  const exclusion = current.exclusion || {};
  const weekly = exclusion.weekly || [];
  const history = review.history || [];
  const experiments = current.experiments || [];

  const alphaClass = (value) => {
    if (value == null || Number.isNaN(Number(value))) return "";
    return Number(value) >= 0 ? "text-positive" : "text-negative";
  };

  const exclusionRows = weekly
    .map((row) => {
      const alpha = row.exclusion_alpha;
      const vsBench = row.filtered_vs_benchmark;
      return `<tr>
        <td class="small">${esc(fmtDate(row.week_start))}<br><span class="muted">→ ${esc(fmtDate(row.week_end))}</span></td>
        <td>${pctOrDash(row.baseline_ew_return)}</td>
        <td>${pctOrDash(row.filtered_ew_return)}</td>
        <td>${pctOrDash(row.benchmark_return)}</td>
        <td class="${alphaClass(alpha)}">${pctOrDash(alpha)}</td>
        <td class="${alphaClass(vsBench)}">${pctOrDash(vsBench)}</td>
        <td>${row.filtered_pool_size ?? "—"} / ${row.baseline_pool_size ?? "—"}</td>
        <td>${pctOrDash(row.bottom_quartile_exclude_rate)}</td>
        <td>${pctOrDash(row.top_quartile_retain_rate)}</td>
      </tr>`;
    })
    .join("");

  const exclusionTable = weekly.length
    ? `<div class="table-wrap">
        <table class="eng-queue-table sunday-review-table">
          <thead>
            <tr>
              <th>Week pair</th>
              <th>Baseline EW</th>
              <th>Filtered EW</th>
              <th>^FTSE</th>
              <th>Exclusion α</th>
              <th>Filtered − mkt</th>
              <th>Pool (filt/base)</th>
              <th>Bottom-Q excl</th>
              <th>Top-Q retain</th>
            </tr>
          </thead>
          <tbody>${exclusionRows}</tbody>
        </table>
      </div>`
    : `<p class="muted">No exclusion week-pairs yet — needs ≥2 archived runs and <code>ftse-exclusion-universe-archive</code>.</p>`;

  const regimeRows = history
    .map((snap) => {
      const regime = snap.regime || {};
      const excl = snap.exclusion?.summary || {};
      return `<tr>
        <td><strong>${esc(snap.week_ending || "—")}</strong><br><span class="small muted">${esc(fmtDate(snap.reviewed_at))}</span></td>
        <td>${esc(regime.recommended_exclusion_step || review.recommended_exclusion_step || "—")}</td>
        <td class="${alphaClass(excl.cumulative_exclusion_alpha)}">${pctOrDash(excl.cumulative_exclusion_alpha)}</td>
        <td>${pctOrDash(regime.positive_alpha_rate)}</td>
        <td>${regime.exclusion_week_pairs ?? "—"}</td>
        <td class="${alphaClass(regime.primary_excess_after_costs)}">${pctOrDash(regime.primary_excess_after_costs)}</td>
        <td>${regime.beat_market ? '<span class="badge badge-buy">yes</span>' : '<span class="badge badge-avoid">no</span>'}</td>
        <td>${regime.ready_for_shadow_spawn ? '<span class="badge badge-buy">yes</span>' : '<span class="badge badge-neutral">no</span>'}</td>
        <td class="small">${esc((regime.flags || []).slice(0, 2).join(", ") || "—")}</td>
      </tr>`;
    })
    .join("");

  const regimeTable = history.length
    ? `<div class="table-wrap">
        <table class="eng-queue-table sunday-review-table">
          <thead>
            <tr>
              <th>Week ending</th>
              <th>Step</th>
              <th>Cumul. excl. α</th>
              <th>+α rate</th>
              <th>Pairs</th>
              <th>Primary excess</th>
              <th>Beat mkt</th>
              <th>Shadow ready</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>${regimeRows}</tbody>
        </table>
      </div>`
    : `<p class="muted">Regime history fills as <code>ftse-publish</code> runs each week.</p>`;

  const trackWeekRows = [];
  for (const snap of history) {
    for (const track of snap.paper_tracks || []) {
      trackWeekRows.push({
        week_ending: snap.week_ending,
        ...track,
      });
    }
  }
  trackWeekRows.sort((a, b) => String(b.week_ending).localeCompare(String(a.week_ending)));

  const paperTrackTableRows = trackWeekRows
    .map(
      (row) => `<tr>
        <td>${esc(row.week_ending || "—")}</td>
        <td><strong>${esc(row.track_label || row.track_id)}</strong><br><span class="small muted">${esc(row.track_id || "")}</span></td>
        <td class="${alphaClass(row.excess_after_costs)}">${pctOrDash(row.excess_after_costs)}</td>
        <td>${pctOrDash(row.benchmark_return)}</td>
        <td>${pctOrDash(row.cost_drag)}</td>
        <td>${row.trade_count ?? "—"}</td>
        <td>${row.equity_marks ?? "—"}</td>
        <td>${row.min_conviction != null ? Number(row.min_conviction).toFixed(2) : "—"}</td>
        <td class="${alphaClass(row.epoch_excess_after_costs)}">${pctOrDash(row.epoch_excess_after_costs)}</td>
      </tr>`
    )
    .join("");

  const paperTrackTable = trackWeekRows.length
    ? `<div class="table-wrap">
        <table class="eng-queue-table sunday-review-table">
          <thead>
            <tr>
              <th>Week</th>
              <th>Track</th>
              <th>Excess vs ^FTSE</th>
              <th>Benchmark</th>
              <th>Cost drag</th>
              <th>Trades</th>
              <th>Marks</th>
              <th>min_conv</th>
              <th>Epoch excess</th>
            </tr>
          </thead>
          <tbody>${paperTrackTableRows}</tbody>
        </table>
      </div>`
    : `<p class="muted">Paper track weekly snapshots appear after publish archives learning marks.</p>`;

  const experimentStatusBadge = (status) => {
    const value = status || "proposed";
    if (value === "recommend") return `<span class="badge badge-buy">${esc(value)}</span>`;
    if (value === "fail") return `<span class="badge badge-avoid">${esc(value)}</span>`;
    if (value === "continue") return `<span class="badge badge-info">${esc(value)}</span>`;
    return `<span class="badge badge-neutral">${esc(value)}</span>`;
  };

  const experimentRows = experiments
    .map(
      (row) => `<tr>
        <td><code>${esc(row.experiment_id || "—")}</code><br><span class="small muted">${esc(row.kind || "")}</span></td>
        <td>${experimentStatusBadge(row.status)}</td>
        <td>${esc(row.pipeline || "—")}</td>
        <td class="small">${esc((row.title || "").slice(0, 80))}${(row.title || "").length > 80 ? "…" : ""}</td>
        <td class="${alphaClass(row.gate_excess_after_costs)}">${pctOrDash(row.gate_excess_after_costs)}</td>
        <td>${row.gate_marks ?? "—"}</td>
        <td class="small muted">${esc(fmtDate(row.initiated_at))}</td>
      </tr>`
    )
    .join("");

  const experimentTable = experiments.length
    ? `<div class="table-wrap">
        <table class="eng-queue-table sunday-review-table">
          <thead>
            <tr>
              <th>Experiment</th>
              <th>Status</th>
              <th>Pipeline</th>
              <th>Title</th>
              <th>Gate excess</th>
              <th>Marks</th>
              <th>Initiated</th>
            </tr>
          </thead>
          <tbody>${experimentRows}</tbody>
        </table>
      </div>`
    : `<p class="muted">No experiments in the unified assessment ledger.</p>`;

  const summary = review.experiment_summary || {};
  const readiness = review.readiness || {};
  const headline = current.analysis_headline
    ? `<p class="small">${esc(current.analysis_headline)}${current.analysis_headline.length >= 400 ? "…" : ""}</p>`
    : "";

  return `
    <section class="automation-section automation-section-full sunday-review-section">
      <h2>Sunday review</h2>
      <p class="small muted" style="margin-top:0">
        Week-by-week tables from analysis-review JSON — exclusion ladder, paper tracks, regime flags, and experiments.
        Updated ${esc(fmtDate(review.generated_at))} · week ending <strong>${esc(review.week_ending || "—")}</strong>
        · ladder step <strong>${esc(review.recommended_exclusion_step || "—")}</strong>
      </p>
      <div class="settings-grid" style="margin-bottom:1rem">
        ${settingRow("Exclusion priors ready", readiness.ready_for_priors ? "yes" : "no")}
        ${settingRow("Shadow spawn ready", readiness.ready_for_shadow_spawn ? "yes" : "no")}
        ${settingRow("Experiments", `${summary.total ?? experiments.length ?? 0} total · ${summary.recommend ?? 0} recommend`)}
      </div>
      ${headline}

      <h3>Exclusion ladder — week pairs (${esc(exclusion.recommended_step_id || review.recommended_exclusion_step || "u4")})</h3>
      <p class="small muted">Forward equal-weight returns per archived week pair (gross of costs).</p>
      ${exclusionTable}

      <h3>Regime snapshots by week</h3>
      <p class="small muted">One row per publish week — cumulative exclusion alpha, primary excess, readiness flags.</p>
      ${regimeTable}

      <h3>Paper tracks by week</h3>
      <p class="small muted">Learning-track excess vs ^FTSE and cost drag from each archived dashboard snapshot.</p>
      ${paperTrackTable}

      <h3>Experiments</h3>
      <p class="small muted">Unified assessment ledger — new shadows and tracks appear automatically when spawned.</p>
      ${experimentTable}
    </section>`;
}

function renderAnalysis(data) {
  const deep = data.deep_analysis;
  const postRun = data.post_run_review;
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

  let postRunHtml = "";
  if (postRun && (postRun.full_text || postRun.executive_summary)) {
    const body = esc(postRun.full_text || postRun.executive_summary || "").replace(/\n/g, "<br>");
    postRunHtml = `
      <h2 style="margin-top:1.5rem">Post-run improvement review</h2>
      <p class="small muted" style="margin-top:0">
        Snapshot from the last Sunday email / deep-analysis pass — narrative weaknesses and plan items,
        not live engineering tickets. Actionable work lives on the
        <strong>Automation</strong> tab → Engineering queue (compile may be idle until the next review).
      </p>
      <div class="card">
        <p>${body}</p>
      </div>`;
  }

  let researchHtml = '<div class="empty-state">No per-ticker research memos published yet.</div>';
  if (research.length) {
    researchHtml = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Company</th><th>Verdict</th><th>Sources</th><th>Version</th><th>Summary</th><th></th></tr></thead>
          <tbody>
            ${research
              .map(
                (item, index) => `
              <tr>
                <td><strong>${esc(item.name)}</strong><br><span class="small muted">${esc(item.ticker)}</span></td>
                <td>${item.research_verdict ? `<span class="badge badge-${esc(item.research_verdict)}">${esc(item.research_verdict)}</span>` : '<span class="muted">—</span>'}</td>
                <td>${memoQualityBadge(item)}</td>
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
    ${renderSundayReview(data)}
    <h2 class="small muted" style="margin-top:1.5rem">Portfolio deep analysis</h2>
    ${deepHtml}
    ${postRunHtml}
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

function engStatusBadge(status) {
  const value = String(status || "open");
  const labels = {
    open: "open",
    pr_open: "pr open",
    parked: "parked",
    failed: "failed",
    merged: "merged",
    completed: "completed",
    cancelled: "cancelled",
  };
  const classes = {
    open: "badge-info",
    pr_open: "badge-watch",
    parked: "badge-watch",
    failed: "badge-ii-no",
    merged: "badge-ii-ok",
    completed: "badge-ii-ok",
    cancelled: "muted",
  };
  const cls = classes[value] || "badge-info";
  return `<span class="badge ${cls}">${esc(labels[value] || value)}</span>`;
}

function resolveEngineeringQueue(data) {
  const auto = data.automation || {};
  if (auto.engineering_queue) return auto.engineering_queue;
  const raw = data.engineering_tasks;
  if (!raw || !Array.isArray(raw.tasks)) return null;
  const tasks = raw.tasks;
  const countStatus = (wanted) =>
    tasks.filter((row) => String(row.status || "open") === wanted).length;
  const pick = (wanted) =>
    tasks
      .filter((row) => wanted.has(String(row.status || "open")))
      .map((row) => ({
        id: row.id,
        area: row.area,
        title: row.title,
        priority: row.priority,
        priority_score: row.priority_score,
        status: row.status,
        source: row.source,
        pr_url: row.pr_url,
        pr_number: row.pr_number,
        branch_name: row.branch_name,
      }))
      .sort((a, b) => Number(b.priority_score || 0) - Number(a.priority_score || 0));
  const open = new Set(["open", "pr_open"]);
  const attention = new Set(["parked", "failed"]);
  const openTasks = pick(open);
  const nextTask = openTasks.find((row) => row.status === "open") || openTasks[0] || null;
  return {
    compiled_at: raw.compiled_at,
    task_count: Number(raw.task_count || tasks.length),
    status: {
      open_count: countStatus("open"),
      pr_open_count: countStatus("pr_open"),
      parked_count: countStatus("parked"),
      merged_count: tasks.filter((row) =>
        ["merged", "completed"].includes(String(row.status || ""))
      ).length,
      failed_count: countStatus("failed"),
      next_task_id: nextTask ? nextTask.id : null,
      in_flight_branch: openTasks.find((row) => row.status === "pr_open")?.branch_name || null,
      in_flight_pr: openTasks.find((row) => row.status === "pr_open")?.pr_number || null,
      spend_since_checkpoint_usd: null,
      spend_checkpoint_usd: null,
      spend_blocked: null,
    },
    queued_tasks: openTasks,
    attention_tasks: pick(attention),
  };
}

function humanTaskDocUrl(checklist, task) {
  if (!checklist || !task) return null;
  const base = String(checklist.repo_docs_base || "").replace(/\/$/, "");
  const path = String(task.doc_path || "").replace(/^\//, "");
  if (!base || !path) return null;
  const anchor = task.doc_anchor ? `#${task.doc_anchor}` : "";
  return `${base}/${path}${anchor}`;
}

function githubOpsDocUrl(path, anchor) {
  const base = "https://github.com/jamiefuller320/value_investor/blob/main";
  const clean = String(path || "").replace(/^\//, "");
  if (!clean) return null;
  return anchor ? `${base}/${clean}#${anchor}` : `${base}/${clean}`;
}

function pctOrDash(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function numOrDash(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

function renderChurnCounterfactualPanel(data) {
  const churn = data.churn_health;
  const counterfactual = data.buffered_hold_counterfactual;
  if (!churn && !counterfactual) {
    return `
      <section class="automation-section automation-section-full churn-counterfactual-section">
        <h2>Churn &amp; counterfactual</h2>
        <p class="muted">No churn health or buffered-hold counterfactual published yet — runs after weekday decision-review.</p>
      </section>`;
  }

  const lookback =
    churn?.lookback_days ?? counterfactual?.lookback_days ?? 7;
  const asOf = churn?.generated_at || counterfactual?.as_of;
  const docChurn = githubOpsDocUrl("docs/ops/paper-learning-review.md");
  const docCf = githubOpsDocUrl("docs/ops/decision-review.md", "rebalance-decision-log");

  const trackLabels = {
    rules: "Rules (control)",
    ai_judgment: "AI judgment (primary)",
    ai_judgment_calibrated: "AI judgment calibrated (shadow)",
    momentum_grace: "Momentum grace",
    technical: "Technical",
  };
  const trackLabel = (trackId) =>
    trackLabels[trackId] || learningTrackLabel(trackId, data.learning_track_configs || {});

  const alerts = churn?.alerts || [];
  const alertsHtml = alerts.length
    ? `<ul class="churn-alerts">
        ${alerts
          .map(
            (alert) => `
          <li class="churn-alert severity-${esc(alert.severity || "info")}">
            <strong>${esc(alert.title || "Alert")}</strong>
            <span class="small muted"> · ${esc(alert.track || "—")}</span>
            <div class="small">${esc(alert.summary || "")}</div>
          </li>`
          )
          .join("")}
      </ul>`
    : `<p class="small muted">No churn alerts in the ${lookback}-day window.</p>`;

  const churnTracks = churn?.tracks || {};
  const churnRows = Object.entries(churnTracks)
    .map(([trackId, row]) => {
      const windowKey = Object.keys(row).find((key) => key.startsWith("trades_last_"));
      const window = (windowKey && row[windowKey]) || {};
      const review = row.decision_review || {};
      const guards = row.guards || {};
      const state = row.rebalance_state || {};
      const costDrag = review.cost_drag;
      const costClass =
        costDrag != null && Number(costDrag) >= 0.06 ? "text-negative" : "";
      return `<tr>
        <td><strong>${esc(trackLabel(trackId))}</strong><br><span class="small muted">${esc(trackId)}</span></td>
        <td class="${costClass}">${pctOrDash(costDrag)}</td>
        <td>${review.trade_count ?? "—"}</td>
        <td>${window.full_exits ?? "—"}</td>
        <td>${window.adjacent_flip_count ?? "—"}</td>
        <td>${state.buffered_holdings ?? "—"}</td>
        <td>${guards.exit_confirm_screens ?? "—"}</td>
        <td>${row.last_run?.buffer_holds_planned ?? "—"}</td>
      </tr>`;
    })
    .join("");

  const cfTracks = counterfactual?.tracks || {};
  const cfRows = Object.entries(cfTracks)
    .map(([trackId, row]) => {
      const comparison = row.comparison || {};
      const variants = row.variants || {};
      const v1 = variants["1"] || variants[1] || {};
      const v2 = variants["2"] || variants[2] || {};
      const tradeDelta = comparison.trade_count_delta_lower_minus_higher;
      const costDelta = comparison.cost_drag_delta_lower_minus_higher;
      const returnDelta = comparison.return_delta_lower_minus_higher;
      const hasSignal =
        tradeDelta != null &&
        (Math.abs(Number(tradeDelta)) > 0 ||
          Math.abs(Number(costDelta || 0)) > 0.0001 ||
          Math.abs(Number(returnDelta || 0)) > 0.0001);
      const signalBadge = hasSignal
        ? '<span class="badge badge-buy">discriminatory</span>'
        : '<span class="badge badge-neutral">flat</span>';
      const ctx = row.churn_context || {};
      return `<tr>
        <td><strong>${esc(trackLabel(trackId))}</strong> ${signalBadge}<br><span class="small muted">${esc(trackId)}</span></td>
        <td>${ctx.log_entries_in_window ?? "—"}</td>
        <td>${ctx.full_exits_in_window ?? "—"}</td>
        <td>${ctx.buffered_holdings ?? "—"}</td>
        <td>${pctOrDash(v1.simulated_cost_drag)}</td>
        <td>${pctOrDash(v2.simulated_cost_drag)}</td>
        <td>${numOrDash(costDelta, 4)}</td>
        <td>${numOrDash(returnDelta, 4)}</td>
        <td>${tradeDelta ?? "—"}</td>
      </tr>`;
    })
    .join("");

  const cfSummary = counterfactual?.summary || {};
  const flatTracks = Object.entries(cfSummary)
    .filter(([, row]) => {
      const cmp = row.comparison || {};
      return (
        Number(cmp.trade_count_delta_lower_minus_higher || 0) === 0 &&
        Math.abs(Number(cmp.cost_drag_delta_lower_minus_higher || 0)) < 0.0001
      );
    })
    .map(([trackId]) => trackLabel(trackId));

  const noteHtml =
    flatTracks.length && cfRows
      ? `<p class="small muted churn-note">exit_confirm_screens 1 vs 2 is <strong>flat</strong> for ${esc(
          flatTracks.join(", ")
        )} in the ${lookback}-day window — wait for more live log entries before tuning churn guards.</p>`
      : "";

  return `
    <section class="automation-section automation-section-full churn-counterfactual-section">
      <h2>Churn &amp; counterfactual</h2>
      <p class="small muted" style="margin-top:0">
        Observe-only rollups from weekday decision-review (${lookback}-day lookback).
        ${asOf ? `Updated ${esc(fmtDate(asOf))}.` : ""}
        ${docChurn ? `<a href="${esc(docChurn)}" target="_blank" rel="noopener">Paper learning review</a>` : ""}
        ${docCf ? ` · <a href="${esc(docCf)}" target="_blank" rel="noopener">Rebalance log replay</a>` : ""}
      </p>

      <h3>Churn alerts</h3>
      ${alertsHtml}

      <h3>Churn health by track</h3>
      <div class="table-wrap">
        <table class="churn-counterfactual-table">
          <thead>
            <tr>
              <th>Track</th>
              <th>Cost drag</th>
              <th>Trades (review)</th>
              <th>Full exits (${lookback}d)</th>
              <th>Side flips</th>
              <th>Buffered</th>
              <th>exit_confirm</th>
              <th>Buffer holds (last run)</th>
            </tr>
          </thead>
          <tbody>${churnRows || '<tr><td colspan="8" class="muted">No churn health tracks.</td></tr>'}</tbody>
        </table>
      </div>

      <h3>Buffered-hold counterfactual (exit_confirm 1 vs 2)</h3>
      <p class="small muted">Lower screen count exits sooner (more churn); higher count buffers longer. Observe-only — does not change live config.</p>
      ${noteHtml}
      <div class="table-wrap">
        <table class="churn-counterfactual-table">
          <thead>
            <tr>
              <th>Track</th>
              <th>Log entries</th>
              <th>Full exits</th>
              <th>Buffered now</th>
              <th>Cost drag (confirm=1)</th>
              <th>Cost drag (confirm=2)</th>
              <th>Δ cost drag</th>
              <th>Δ return</th>
              <th>Δ trades</th>
            </tr>
          </thead>
          <tbody>${cfRows || '<tr><td colspan="9" class="muted">No counterfactual tracks in lookback window yet (rules needs fresh weekday logs).</td></tr>'}</tbody>
        </table>
      </div>
    </section>`;
}

function renderHumanTasksChecklistSection(checklist) {
  if (!checklist || !Array.isArray(checklist.sections) || !checklist.sections.length) {
    return `
      <section class="automation-section automation-section-full human-tasks-section">
        <h2>Human tasks</h2>
        <p class="muted">Checklist not published yet.</p>
      </section>`;
  }

  const runbookUrl = humanTaskDocUrl(checklist, {
    doc_path: checklist.runbook_path || "docs/ops/human-tasks-checklist.md",
  });

  const sectionsHtml = checklist.sections
    .map((section) => {
      const tasksHtml = (section.tasks || [])
        .map((task) => {
          const docUrl = humanTaskDocUrl(checklist, task);
          const docLink = docUrl
            ? ` <a href="${esc(docUrl)}" target="_blank" rel="noopener" class="small">runbook</a>`
            : "";
          const autoBadge = task.automated
            ? ' <span class="badge badge-neutral" title="Handled by CI">automated</span>'
            : ' <span class="badge badge-watch" title="Requires human review">human</span>';
          return `<li class="human-task-item${task.automated ? " human-task-auto" : ""}">
            <strong>${esc(task.title || task.id || "Task")}</strong>${autoBadge}${docLink}
            <div class="small muted">${esc(task.summary || "")}</div>
          </li>`;
        })
        .join("");
      return `<div class="human-tasks-cadence">
        <h3>${esc(section.title || section.id || "Tasks")}</h3>
        <ul class="human-tasks-list">${tasksHtml}</ul>
      </div>`;
    })
    .join("");

  return `
    <section class="automation-section automation-section-full human-tasks-section">
      <h2>Human tasks</h2>
      <p class="small muted" style="margin-top:0">
        Manual gates for learning-loop promotion and Sunday review.
        ${runbookUrl ? `<a href="${esc(runbookUrl)}" target="_blank" rel="noopener">Full checklist</a>` : ""}
        ${checklist.updated_at ? ` · updated ${esc(checklist.updated_at)}` : ""}
      </p>
      ${sectionsHtml}
    </section>`;
}

function renderEngineeringQueueSection(queue) {
  if (!queue) {
    return `
      <section class="automation-section automation-section-full">
        <h2>Engineering queue</h2>
        <p class="muted">Queue status not published yet.</p>
      </section>`;
  }

  const status = queue.status || {};
  const queued = queue.queued_tasks || [];
  const attention = queue.attention_tasks || [];
  const idle = Number(status.open_count || 0) === 0 && Number(status.pr_open_count || 0) === 0;
  const spendHtml =
    status.spend_since_checkpoint_usd != null && status.spend_checkpoint_usd != null
      ? settingRow(
          "Ad hoc spend checkpoint",
          status.spend_blocked
            ? `<span class="badge badge-ii-no">blocked</span> · $${esc(String(status.spend_since_checkpoint_usd))} / $${esc(String(status.spend_checkpoint_usd))}`
            : esc(`$${status.spend_since_checkpoint_usd} / $${status.spend_checkpoint_usd}`)
        )
      : "";

  const summaryHtml = `
    ${settingRow("Open / PR open", esc(`${status.open_count ?? 0} / ${status.pr_open_count ?? 0}`))}
    ${settingRow("Parked / failed / merged", esc(`${status.parked_count ?? 0} / ${status.failed_count ?? 0} / ${status.merged_count ?? 0}`))}
    ${settingRow("Next task", esc(status.next_task_id || (idle ? "— (idle)" : "—")))}
    ${status.in_flight_pr ? settingRow("In-flight PR", `<a href="https://github.com/jamiefuller320/value_investor/pull/${esc(String(status.in_flight_pr))}" target="_blank" rel="noopener">#${esc(String(status.in_flight_pr))}</a>`) : ""}
    ${spendHtml}
    ${settingRow("Compiled", esc(fmtDate(queue.compiled_at)))}
    ${queue.queue_ui_updated_at ? settingRow("Queue UI", esc(fmtDate(queue.queue_ui_updated_at))) : ""}
  `;

  const taskRows = (tasks) =>
    tasks
      .map((task) => {
        const prCell = task.pr_url
          ? `<a href="${esc(task.pr_url)}" target="_blank" rel="noopener">#${esc(String(task.pr_number || "PR"))}</a>`
          : "—";
        return `
          <tr>
            <td><code>${esc(task.id || "—")}</code></td>
            <td>${engStatusBadge(task.status)}</td>
            <td>${esc(task.area || "—")}</td>
            <td>${esc(String(task.priority_score ?? "—"))}</td>
            <td>${prCell}</td>
            <td>${esc(task.title || "")}</td>
          </tr>`;
      })
      .join("");

  const queuedHtml = queued.length
    ? `<div class="table-wrap">
        <table class="eng-queue-table">
          <thead>
            <tr>
              <th>Task</th>
              <th>Status</th>
              <th>Area</th>
              <th>Score</th>
              <th>PR</th>
              <th>Title</th>
            </tr>
          </thead>
          <tbody>${taskRows(queued)}</tbody>
        </table>
      </div>`
    : `<p class="muted">${idle ? "Queue idle — no open or in-flight engineering tasks." : "No queued tasks."}</p>`;

  const attentionHtml = attention.length
    ? `<h3>Needs attention</h3>
       <div class="table-wrap">
         <table class="eng-queue-table">
           <thead>
             <tr>
               <th>Task</th>
               <th>Status</th>
               <th>Area</th>
               <th>Score</th>
               <th>PR</th>
               <th>Title</th>
             </tr>
           </thead>
           <tbody>${taskRows(attention)}</tbody>
         </table>
       </div>`
    : "";

  return `
    <section class="automation-section automation-section-full">
      <h2>Engineering queue</h2>
      <p class="small muted" style="margin-top:0">
        Supervised dev-agent tasks from post-run compile and ops monitor.
        Hourly weekday dispatch via <code>engineering-queue.yml</code>.
      </p>
      ${summaryHtml}
      <h3>Queued items</h3>
      ${queuedHtml}
      ${attentionHtml}
    </section>`;
}

function formatTrackKnobs(trackConfigs, trackId) {
  const cfg = (trackConfigs || {})[trackId];
  if (!cfg || !cfg.selection) return "";
  const s = cfg.selection;
  const parts = [];
  if (s.max_positions != null) parts.push(`max_pos=${s.max_positions}`);
  if (s.min_conviction != null) parts.push(`min_conv=${Number(s.min_conviction).toFixed(2)}`);
  if (s.sector_cap != null) parts.push(`sector=${Number(s.sector_cap).toFixed(2)}`);
  if (s.skip_timing_wait != null) parts.push(`skip_wait=${s.skip_timing_wait ? "Y" : "N"}`);
  return parts.join(" · ");
}

function learningTrackLabel(trackId, trackConfigs) {
  const cfg = (trackConfigs || {})[trackId] || {};
  if (cfg.track_label) return cfg.track_label;
  const defaults = {
    rules: "Rules (control)",
    ai_judgment: "AI judgment (primary)",
    ai_judgment_calibrated: "AI judgment calibrated (shadow)",
    momentum_grace: "Momentum grace",
    technical: "Technical (levels baseline)",
  };
  if (defaults[trackId]) return defaults[trackId];
  const rankMatch = /^ai_judgment_calibrated_r(\d+)$/.exec(trackId || "");
  if (rankMatch) {
    return `AI judgment calibrated shadow (rank ${rankMatch[1]})`;
  }
  return trackId;
}

function formatKnobDict(knobs) {
  if (!knobs || typeof knobs !== "object") return "";
  const bits = [];
  if (knobs.max_positions != null) bits.push(`pos=${knobs.max_positions}`);
  if (knobs.min_conviction != null) bits.push(`conv=${Number(knobs.min_conviction).toFixed(2)}`);
  if (knobs.sector_cap != null) bits.push(`sect=${Number(knobs.sector_cap).toFixed(2)}`);
  if (knobs.skip_timing_wait != null) bits.push(`skipWait=${knobs.skip_timing_wait ? "Y" : "N"}`);
  if (knobs.exit_confirm_screens != null) bits.push(`exitConfirm=${knobs.exit_confirm_screens}`);
  return bits.join(" · ");
}

function renderKnobBootstrapPanel(data) {
  const priors = data.knob_calibration_priors;
  const endurance = data.calibration_shadow_endurance;
  if (!priors && !endurance) {
    return `
      <section class="automation-section automation-section-full knob-bootstrap-section">
        <h2>Knob bootstrap lab</h2>
        <p class="muted">No full-period calibration priors or shadow endurance published yet — Sunday analysis-review writes these after <code>ftse-knob-calibrate</code>.</p>
      </section>`;
  }

  const docUrl = githubOpsDocUrl("docs/ops/knob-calibration.md", "competing-calibrated-shadows");
  const aiRow =
    (priors && priors.scope === "knob_calibration_multi"
      ? (priors.tracks || {}).ai_judgment
      : priors) || {};
  const readiness = aiRow.readiness || {};
  const bootstrap = aiRow.bootstrap_priors || [];
  const rankingMode = aiRow.ranking_mode || priors?.ranking_mode || "—";
  const calibratedAt = aiRow.calibrated_at || priors?.calibrated_at;
  const readyBootstrap = readiness.ready_for_shadow_bootstrap;
  const readyPriors = readiness.ready_for_priors;
  const acted = readiness.acted_entries;
  const scoreGap = readiness.score_gap_vs_runner_up;

  const readyBadge = (value, label) =>
    value
      ? `<span class="badge badge-buy">${esc(label)}</span>`
      : `<span class="badge badge-neutral">${esc(label)} no</span>`;

  const priorRows = bootstrap
    .map((row) => {
      const wl = row.winner_loser || {};
      const catchRate = wl.catch_rate;
      const excludeRate = wl.exclude_rate;
      return `<tr>
        <td>r${esc(String(row.rank ?? "—"))}<br><span class="small muted">${esc(row.shadow_track_id || "")}</span></td>
        <td><span class="small">${esc(formatKnobDict(row.knobs) || "—")}</span></td>
        <td>${numOrDash(row.full_period_score, 4)}</td>
        <td>${esc(row.confidence || "—")}</td>
        <td>${catchRate == null ? "—" : pctOrDash(catchRate)}</td>
        <td>${excludeRate == null ? "—" : pctOrDash(excludeRate)}</td>
        <td class="small muted">${esc((wl.top_buy_tier_caught || []).slice(0, 4).join(", ") || "—")}</td>
        <td class="small muted">${esc((wl.bottom_buy_tier_avoided || []).slice(0, 4).join(", ") || "—")}</td>
      </tr>`;
    })
    .join("");

  const shadows = (endurance && endurance.shadows) || [];
  const survivors = (endurance && endurance.survivors) || [];
  const statusBadge = (status) => {
    const value = status || "observing";
    if (value === "surviving") return `<span class="badge badge-buy">${esc(value)}</span>`;
    if (value === "failed") return `<span class="badge badge-avoid">${esc(value)}</span>`;
    return `<span class="badge badge-hold">${esc(value)}</span>`;
  };
  const enduranceRows = shadows
    .map((row) => {
      const metrics = row.metrics || {};
      const excess = metrics.excess_after_costs;
      const excessHtml =
        excess == null
          ? "—"
          : `<span class="${Number(excess) >= 0 ? "text-positive" : "text-negative"}">${(Number(excess) * 100).toFixed(1)}%</span>`;
      return `<tr>
        <td><strong>r${esc(String(row.rank ?? "—"))}</strong> ${statusBadge(row.status)}<br><span class="small muted">${esc(row.shadow_track_id || "")}</span></td>
        <td><span class="small">${esc(formatKnobDict(row.knobs) || "—")}</span></td>
        <td>${excessHtml}</td>
        <td>${numOrDash(row.excess_vs_primary, 4)}</td>
        <td>${numOrDash(row.excess_vs_rules, 4)}</td>
        <td>${metrics.equity_marks ?? "—"}</td>
        <td>${numOrDash(row.full_period_score, 4)}</td>
      </tr>`;
    })
    .join("");

  const survivorNote = survivors.length
    ? `<p class="small">Survivors ready for human learning-loop prior review: <strong>${esc(
        survivors.map((row) => row.shadow_track_id).join(", ")
      )}</strong> — do not auto-apply.</p>`
    : `<p class="small muted">No survivors yet — keep observing forward marks on competing shadows.</p>`;

  return `
    <section class="automation-section automation-section-full knob-bootstrap-section">
      <h2>Knob bootstrap lab</h2>
      <p class="small muted" style="margin-top:0">
        Full-period retrospective priors seed competing calibrated shadows; endurance decides what may become a learning-loop starting prior.
        ${calibratedAt ? `Calibrated ${esc(fmtDate(calibratedAt))}.` : ""}
        ${endurance?.updated_at ? `Endurance ${esc(fmtDate(endurance.updated_at))}.` : ""}
        ${docUrl ? `<a href="${esc(docUrl)}" target="_blank" rel="noopener">Knob calibration</a>` : ""}
      </p>
      <div class="learning-tracks-headline">
        <span>Ranking: <strong>${esc(rankingMode)}</strong></span>
        <span>Acted logs: <strong>${acted ?? "—"}</strong></span>
        <span>Score gap: <strong>${numOrDash(scoreGap, 4)}</strong></span>
        <span>${readyBadge(readyBootstrap, "bootstrap ready")}</span>
        <span>${readyBadge(readyPriors, "priors ready")}</span>
      </div>

      <h3>Bootstrap priors (retrospective)</h3>
      <div class="table-wrap">
        <table class="knob-bootstrap-table">
          <thead>
            <tr>
              <th>Rank / shadow</th>
              <th>Knobs</th>
              <th>Full-period score</th>
              <th>Confidence</th>
              <th>Catch rate</th>
              <th>Exclude rate</th>
              <th>Caught winners</th>
              <th>Avoided losers</th>
            </tr>
          </thead>
          <tbody>${priorRows || '<tr><td colspan="8" class="muted">No bootstrap_priors in published calibration artifact.</td></tr>'}</tbody>
        </table>
      </div>

      <h3>Forward endurance (competing shadows)</h3>
      ${survivorNote}
      <div class="table-wrap">
        <table class="knob-bootstrap-table">
          <thead>
            <tr>
              <th>Shadow</th>
              <th>Knobs</th>
              <th>Excess vs ^FTSE</th>
              <th>Δ vs primary</th>
              <th>Δ vs rules</th>
              <th>Marks</th>
              <th>Retrospective score</th>
            </tr>
          </thead>
          <tbody>${enduranceRows || '<tr><td colspan="7" class="muted">No calibrated shadows in endurance ledger yet.</td></tr>'}</tbody>
        </table>
      </div>
    </section>`;
}

function renderLearningTracksPanel(data) {
  const review =
    data.learning_tracks_review ||
    (data.paper_automation || {}).learning_tracks_review;
  if (!review || !review.reviews) {
    return `<section class="automation-section learning-tracks-section">
      <h2>Learning tracks (server)</h2>
      <p class="muted">No learning-track review published yet — runs after weekday paper-auto + decision-review.</p>
    </section>`;
  }

  const funds = data.learning_track_funds || {};
  const trackConfigs = data.learning_track_configs || {};
  const technicalMissing = !review.reviews.technical;
  const baseOrder = ["technical", "rules", "ai_judgment", "momentum_grace"];
  const shadowIds = Object.keys(review.reviews)
    .filter(
      (id) =>
        id === "ai_judgment_calibrated" ||
        /^ai_judgment_calibrated_r\d+$/.test(id) ||
        (trackConfigs[id] || {}).is_calibration_shadow
    )
    .sort((a, b) => {
      const rank = (id) => {
        if (id === "ai_judgment_calibrated") return 1;
        const match = /^ai_judgment_calibrated_r(\d+)$/.exec(id);
        return match ? Number(match[1]) : 99;
      };
      return rank(a) - rank(b);
    });
  const trackOrder = [];
  for (const id of baseOrder) {
    trackOrder.push(id);
    if (id === "ai_judgment") {
      for (const shadowId of shadowIds) trackOrder.push(shadowId);
    }
  }
  for (const id of Object.keys(review.reviews)) {
    if (!trackOrder.includes(id)) trackOrder.push(id);
  }

  const rows = trackOrder
    .map((id) => {
      const row = review.reviews[id];
      if (!row) return "";
      const label = learningTrackLabel(id, trackConfigs);
      const m = row.metrics || {};
      const fund = funds[id] || {};
      const cfg = trackConfigs[id] || {};
      const primary = row.is_primary_learning_track ? ' <span class="badge badge-buy">primary</span>' : "";
      const shadowBadge = cfg.is_calibration_shadow
        ? ` <span class="badge badge-hold" title="Frozen calibration priors — decision-review apply disabled">calibrated shadow</span>`
        : "";
      const confidence =
        (cfg.calibration_provenance || {}).confidence ||
        (cfg.calibration_provenance || {}).recommended_prior?.confidence;
      const confBadge =
        confidence && cfg.is_calibration_shadow
          ? ` <span class="badge badge-neutral" title="Calibration prior confidence">${esc(confidence)} conf</span>`
          : "";
      const knobsHtml = formatTrackKnobs(trackConfigs, id);
      const excess = m.excess_after_costs;
      const excessHtml =
        excess == null
          ? "—"
          : `<span class="${excess >= 0 ? "text-positive" : "text-negative"}">${(Number(excess) * 100).toFixed(1)}%</span>`;
      const epoch = m.epoch || {};
      const epochReturn =
        epoch.total_return != null
          ? `<span class="small">${pct(epoch.total_return)}</span>`
          : '<span class="small muted">—</span>';
      const epochExcess = epoch.excess_after_costs;
      const epochExcessHtml =
        epochExcess == null
          ? '<span class="small muted">—</span>'
          : `<span class="small ${epochExcess >= 0 ? "text-positive" : "text-negative"}">${(Number(epochExcess) * 100).toFixed(1)}%</span>`;
      const curve = Array.isArray(fund.equity_curve) ? fund.equity_curve : [];
      const spark =
        curve.length >= 2
          ? curve
              .map((pt) => Number(pt.nav || pt.value || 0))
              .filter((v) => v > 0)
              .slice(-12)
          : [];
      const sparkHtml =
        spark.length >= 2
          ? `<span class="small muted" title="Recent NAV marks">${spark
              .map((v) => `£${v.toFixed(0)}`)
              .join(" → ")}</span>`
          : '<span class="small muted">—</span>';
      return `<tr>
        <td><strong>${esc(label)}</strong>${primary}${shadowBadge}${confBadge}<br><span class="small muted">${esc(id)}</span>${
          knobsHtml ? `<br><span class="small muted">${esc(knobsHtml)}</span>` : ""
        }</td>
        <td>${m.portfolio_value != null ? `£${Number(m.portfolio_value).toFixed(2)}` : "—"}</td>
        <td>${m.total_return != null ? pct(m.total_return) : "—"}</td>
        <td>${excessHtml}</td>
        <td>${epochReturn}</td>
        <td>${epochExcessHtml}</td>
        <td>${m.trade_count ?? "—"}</td>
        <td>${m.positions ?? fund.holdings_count ?? "—"}</td>
        <td>${sparkHtml}</td>
      </tr>`;
    })
    .join("");

  const verdict = review.verdict || "—";
  const beatMarket = review.beat_market ? "Yes" : "No";
  const beatControl = review.beat_control ? "Yes" : "No";
  const primaryExcess = review.primary_excess_after_costs;

  return `<section class="automation-section learning-tracks-section">
    <h2>Learning tracks (server)</h2>
    <p class="small muted" style="margin-top:0">
      Weekday paper-auto books published from CI — not the browser local sandbox.
      Primary success = AI judgment excess vs ^FTSE after costs; rules is control; technical is timing/levels baseline.
      Competing calibrated shadows run frozen knob priors alongside primary AI judgment (no auto-promotion).
    </p>
    ${
      technicalMissing
        ? `<p class="small muted">Technical server track not published yet (L108) — use <strong>Performance → Static/Trailing</strong> for archived level sims, or <strong>Portfolio → Technical</strong> for the browser sandbox.</p>`
        : ""
    }
    <div class="learning-tracks-headline">
      <span>Verdict: <strong>${esc(verdict)}</strong></span>
      <span>AI excess vs ^FTSE: <strong>${primaryExcess != null ? pct(primaryExcess) : "—"}</strong></span>
      <span>Beat market: ${esc(beatMarket)}</span>
      <span>Beat rules control: ${esc(beatControl)}</span>
    </div>
    <div class="table-wrap">
      <table class="learning-tracks-table">
        <thead>
          <tr>
            <th>Track</th>
            <th>NAV</th>
            <th>Return</th>
            <th>Excess vs ^FTSE</th>
            <th>Epoch return</th>
            <th>Epoch excess</th>
            <th>Trades</th>
            <th>Positions</th>
            <th>Recent marks</th>
          </tr>
        </thead>
        <tbody>${rows || '<tr><td colspan="9" class="muted">No track reviews in bundle.</td></tr>'}</tbody>
      </table>
    </div>
  </section>`;
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
  const engineeringQueue = resolveEngineeringQueue(data);

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
    ${renderLearningTracksPanel(data)}
    ${renderKnobBootstrapPanel(data)}
    ${renderChurnCounterfactualPanel(data)}
    ${renderHumanTasksChecklistSection(data.human_tasks_checklist)}
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
          "Weekly ops (orchestrator)",
          esc(
            `$${budget.estimated_spend_weekly_ops_usd_this_week ?? "—"} / $${budget.weekly_ops_cap_usd ?? "—"} · remaining $${budget.remaining_weekly_ops_usd ?? "—"} · enforce=${budget.enforce_weekly_ops_cap ? "on" : "off"}`
          )
        )}
        ${settingRow(
          "Ad hoc checkpoint",
          esc(
            `$${budget.spend_since_checkpoint_usd ?? "—"} / $${budget.spend_checkpoint_usd ?? "—"}`
          )
        )}
        ${settingRow(
          "Budget flag",
          budget.constraining
            ? `<span class="badge badge-ii-no">${esc(budget.budget_flag || "constraining")}</span>${budget.budget_note ? ` · <span class="small muted">${esc(budget.budget_note)}</span>` : ""}`
            : budget.near_limit
              ? `<span class="badge badge-watch">${esc(budget.budget_flag || "near_limit")}</span>`
              : esc(budget.budget_flag || (budget.enforce_weekly_ops_cap ? "enforced" : "unconstrained"))
        )}
        ${settingRow("Refresh / surplus day", esc(`${budget.plan_refresh_day_of_month ?? "—"} / day before`))}
        ${settingRow("Spend this week / cycle", esc(`$${budget.estimated_spend_usd_this_week ?? "—"} / $${budget.estimated_spend_usd_this_cycle ?? "—"}`))}

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
    ${renderEngineeringQueueSection(engineeringQueue)}
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
    if (!data.project_progress) {
      try {
        const progressResp = await fetch("data/project_progress.json");
        if (progressResp.ok) data.project_progress = await progressResp.json();
      } catch {
        /* optional sidecar */
      }
    }
    if (!data.engineering_tasks && !(data.automation || {}).engineering_queue) {
      try {
        const engResp = await fetch("data/engineering_tasks.json");
        if (engResp.ok) data.engineering_tasks = await engResp.json();
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
