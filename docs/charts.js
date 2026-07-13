/* Price chart popup with trade-plan level markers. */

const CHART_LEVEL_STYLES = {
  last: { color: "#1a1f2e", label: "Last", dash: "" },
  core_limit: { color: "#2b6cb0", label: "Core buy", dash: "6 4" },
  tactical_limit: { color: "#2e9c4f", label: "Tactical buy", dash: "6 4" },
  stop_loss: { color: "#b33a3a", label: "Stop", dash: "4 3" },
  take_profit: { color: "#b8860b", label: "Target", dash: "4 3" },
  sma50: { color: "#7c3aed", label: "SMA 50", dash: "2 3" },
  sma200: { color: "#64748b", label: "SMA 200", dash: "2 3" },
};

function chartPathForReport(report) {
  if (report?.chart_path) return report.chart_path;
  if (!report?.ticker) return null;
  const slug = String(report.ticker).replace(/[^A-Za-z0-9._-]+/g, "_");
  return `data/charts/${slug}.json`;
}

function formatChartPrice(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `£${Number(value).toFixed(2)}`;
}

function estimateLabelWidth(text) {
  // Approximate SVG label width for ~10–11px font.
  return Math.ceil(String(text).length * 6.4);
}

function nudgeLevelLabelYs(entries, minGap = 18) {
  const sorted = [...entries].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i += 1) {
    const prev = sorted[i - 1];
    const current = sorted[i];
    if (current.y - prev.y < minGap) {
      current.y = prev.y + minGap;
    }
  }
  return sorted;
}

function ensureChartDialog() {
  let dialog = document.getElementById("chart-dialog");
  if (dialog) return dialog;
  document.body.insertAdjacentHTML(
    "beforeend",
    `
    <dialog id="chart-dialog" class="memo-dialog chart-dialog">
      <form method="dialog" class="memo-dialog-header">
        <h2 id="chart-title">Price chart</h2>
        <button type="submit" class="btn btn-ghost" aria-label="Close">✕</button>
      </form>
      <div id="chart-body" class="chart-dialog-body"></div>
    </dialog>`
  );
  return document.getElementById("chart-dialog");
}

function renderPriceChartSvg(payload) {
  const dates = payload.dates || [];
  const closes = payload.closes || [];
  if (!dates.length || dates.length !== closes.length) {
    return `<p class="muted">No price series available.</p>`;
  }

  const levels = payload.levels || {};
  const activeLevels = Object.entries(CHART_LEVEL_STYLES).filter(([key]) => levels[key] != null);
  const longestLabel = activeLevels.reduce((max, [, style]) => {
    const sample = `${style.label}`;
    const priceSample = formatChartPrice(99999.99);
    return Math.max(max, estimateLabelWidth(sample), estimateLabelWidth(priceSample));
  }, 90);
  const rightPad = Math.max(168, longestLabel + 28);
  const width = 620 + rightPad;
  const height = 380;
  const pad = { top: 28, right: rightPad, bottom: 42, left: 22 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const levelValues = Object.values(levels)
    .filter((v) => v != null && !Number.isNaN(Number(v)))
    .map(Number);
  const minClose = Math.min(...closes);
  const maxClose = Math.max(...closes);
  const minY = Math.min(minClose, ...levelValues, minClose * 0.98);
  const maxY = Math.max(maxClose, ...levelValues, maxClose * 1.02);
  const spanY = maxY - minY || 1;

  const xAt = (index) => pad.left + (index / Math.max(dates.length - 1, 1)) * plotW;
  const yAt = (value) => pad.top + plotH - ((value - minY) / spanY) * plotH;

  const linePoints = closes.map((value, index) => `${xAt(index)},${yAt(value)}`).join(" ");
  const areaPoints = `${xAt(0)},${pad.top + plotH} ${linePoints} ${xAt(closes.length - 1)},${pad.top + plotH}`;

  const grid = [0.25, 0.5, 0.75]
    .map((fraction) => {
      const value = minY + spanY * (1 - fraction);
      const y = yAt(value);
      return `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" stroke="#e2e8f0" stroke-width="1" />`;
    })
    .join("");

  const labelEntries = nudgeLevelLabelYs(
    activeLevels.map(([key, style]) => {
      const value = Number(levels[key]);
      return {
        key,
        style,
        value,
        lineY: yAt(value),
        y: yAt(value),
      };
    })
  );

  for (const entry of labelEntries) {
    entry.y = Math.min(pad.top + plotH - 4, Math.max(pad.top + 12, entry.y));
  }

  const levelLines = labelEntries
    .map(({ style, value, lineY, y }) => {
      const labelX = width - pad.right + 12;
      const priceText = formatChartPrice(value);
      return `
        <line x1="${pad.left}" y1="${lineY}" x2="${width - pad.right}" y2="${lineY}"
          stroke="${style.color}" stroke-width="1.6" stroke-dasharray="${style.dash}" />
        <line x1="${width - pad.right}" y1="${lineY}" x2="${labelX - 4}" y2="${y - 2}"
          stroke="${style.color}" stroke-width="1" stroke-opacity="0.4" />
        <text x="${labelX}" y="${y - 5}" class="chart-level-label" fill="${style.color}">${esc(style.label)}</text>
        <text x="${labelX}" y="${y + 9}" class="chart-level-price" fill="${style.color}">${esc(priceText)}</text>`;
    })
    .join("");

  const xLabels = dates
    .map((date, index) => ({ date, index }))
    .filter(({ index }) => index % Math.max(1, Math.ceil(dates.length / 5)) === 0 || index === dates.length - 1)
    .map(
      ({ date, index }) =>
        `<text x="${xAt(index)}" y="${height - 12}" text-anchor="middle" class="chart-axis-label">${esc(date.slice(0, 7))}</text>`
    )
    .join("");

  const legend = activeLevels
    .map(
      ([, style]) =>
        `<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:${style.color}"></span>${esc(style.label)}</span>`
    )
    .join("");

  return `
    <div class="price-chart-wrap">
      <svg viewBox="0 0 ${width} ${height}" width="${width}" class="price-chart" role="img" aria-label="Price chart with trade levels">
        ${grid}
        <polygon points="${areaPoints}" fill="rgba(43,108,176,0.08)"></polygon>
        <polyline fill="none" stroke="#2b6cb0" stroke-width="2.25" points="${linePoints}" />
        ${levelLines}
        <text x="${pad.left}" y="${pad.top + 4}" class="chart-axis-label">${formatChartPrice(maxY)}</text>
        <text x="${pad.left}" y="${pad.top + plotH}" class="chart-axis-label">${formatChartPrice(minY)}</text>
        ${xLabels}
      </svg>
      <div class="chart-legend">${legend}</div>
    </div>`;
}

function levelsTableHtml(levels) {
  const rows = Object.entries(CHART_LEVEL_STYLES)
    .filter(([key]) => levels?.[key] != null)
    .map(
      ([key, style]) =>
        `<tr>
          <td><span class="chart-legend-swatch" style="background:${style.color}"></span> ${esc(style.label)}</td>
          <td>${formatChartPrice(levels[key])}</td>
        </tr>`
    )
    .join("");
  if (!rows) return `<p class="small muted">No trade-plan levels available for this name.</p>`;
  return `
    <div class="table-wrap chart-levels-table">
      <table>
        <thead><tr><th>Level</th><th>Price</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function openPriceChart(report) {
  const dialog = ensureChartDialog();
  const title = document.getElementById("chart-title");
  const body = document.getElementById("chart-body");
  const path = chartPathForReport(report);
  title.textContent = `${report.name || report.ticker} (${report.ticker})`;
  body.innerHTML = "<p class='muted'>Loading chart…</p>";
  dialog.showModal();

  if (!path) {
    body.innerHTML = `<p class="muted">No chart path for this recommendation.</p>`;
    return;
  }

  try {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const planHint = report.trade_plan?.trade_plan_summary
      ? `<p class="small muted">${esc(report.trade_plan.trade_plan_summary)}</p>`
      : "";
    body.innerHTML = `
      <p class="small muted">
        ${esc(payload.period || "1y")} daily closes · as of ${esc((payload.as_of || "").slice(0, 10) || "—")}
        ${payload.signal ? ` · ${esc(String(payload.signal).replace(/_/g, " "))}` : ""}
      </p>
      ${planHint}
      ${renderPriceChartSvg(payload)}
      ${levelsTableHtml(payload.levels || {})}
    `;
  } catch (err) {
    body.innerHTML = `
      <p class="muted">Could not load price chart (${esc(err.message)}).</p>
      <p class="small muted">Charts are published for buy-tier names on the weekly dashboard update.</p>`;
  }
}

function bindChartButtons(root, reportsByTicker) {
  root.querySelectorAll("[data-chart-ticker]").forEach((button) => {
    button.addEventListener("click", () => {
      const ticker = button.dataset.chartTicker;
      const report = reportsByTicker.get(ticker) || { ticker, name: ticker };
      openPriceChart(report);
    });
  });
}
