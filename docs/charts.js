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

function renderPriceChartSvg(payload, levelsOverride) {
  const dates = payload.dates || [];
  const closes = payload.closes || [];
  if (!dates.length || dates.length !== closes.length) {
    return `<p class="muted">No price series available.</p>`;
  }

  const levels = { ...(levelsOverride || payload.levels || {}) };
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

  const markerDate = (payload.signal_since || payload.levels_as_of || "").slice(0, 10);
  let signalMarker = "";
  if (markerDate) {
    let markerIndex = dates.findIndex((date) => date >= markerDate);
    if (markerIndex < 0) markerIndex = dates.length - 1;
    // Prefer the last date on/before the marker when the series overshoots.
    for (let i = 0; i < dates.length; i += 1) {
      if (dates[i] <= markerDate) markerIndex = i;
      else break;
    }
    const mx = xAt(markerIndex);
    signalMarker = `
      <line x1="${mx}" y1="${pad.top}" x2="${mx}" y2="${pad.top + plotH}"
        stroke="#0f172a" stroke-width="1.5" stroke-dasharray="5 4" stroke-opacity="0.75" />
      <text x="${mx + 4}" y="${pad.top + 14}" class="chart-signal-marker-label">Signal since ${esc(markerDate)}</text>`;
  }

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
        ${signalMarker}
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

function crossingDirectionLabel(direction) {
  if (direction === "up") return "broke above";
  if (direction === "down") return "broke below";
  return "—";
}

function crossingsTableHtml(crossings) {
  if (!Array.isArray(crossings) || !crossings.length) return "";
  const rows = crossings
    .map((row) => {
      const style = CHART_LEVEL_STYLES[row.key] || { color: "#64748b" };
      return `<tr>
        <td><span class="chart-legend-swatch" style="background:${style.color}"></span> ${esc(row.label || row.key)}</td>
        <td>${formatChartPrice(row.price)}</td>
        <td>${row.date ? esc(row.date) : "—"}</td>
        <td>${esc(crossingDirectionLabel(row.direction))}</td>
      </tr>`;
    })
    .join("");
  return `
    <div class="table-wrap chart-crossings-table">
      <h3 class="chart-crossings-heading">Initial levels crossed</h3>
      <p class="small muted">First daily close after the recommendation that crossed each frozen level.</p>
      <table>
        <thead><tr><th>Level</th><th>Initial</th><th>First crossed</th><th>Direction</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function displayLevelsForSource(payload, source) {
  const current = payload.levels || {};
  if (source !== "initial" || !payload.initial_levels) return current;
  return {
    ...payload.initial_levels,
    last: current.last ?? payload.initial_levels.last,
  };
}

function renderChartBody(payload, report, source) {
  const levels = displayLevelsForSource(payload, source);
  const levelsAsOf = (payload.levels_as_of || payload.as_of || "").slice(0, 10);
  const initialAsOf = (payload.initial_levels_as_of || payload.signal_since || "").slice(0, 10);
  const signalSince = (payload.signal_since || "").slice(0, 10);
  const usingInitial = source === "initial" && payload.initial_levels;
  const planHint = !usingInitial && report.trade_plan?.trade_plan_summary
    ? `<p class="small muted">${esc(report.trade_plan.trade_plan_summary)}</p>`
    : "";
  const asOfLabel = usingInitial ? initialAsOf : levelsAsOf;
  const levelsHint = asOfLabel
    ? `<p class="small muted">${
        usingInitial
          ? `Trade levels / SMAs frozen at the initial recommendation (${esc(asOfLabel)}). Last is the latest close so you can see what has played out.`
          : `Trade levels / SMAs from the latest screen (${esc(levelsAsOf)}).`
      }${
        signalSince
          ? ` Vertical line marks current signal since ${esc(signalSince)}.`
          : ""
      }</p>`
    : "";
  const hasInitial = Boolean(payload.initial_levels);
  const toggle = `
    <div class="chart-level-toggle" role="group" aria-label="Level source">
      <button type="button" class="btn chart-toggle${source === "current" ? " is-active" : ""}" data-level-source="current">Latest screen</button>
      <button type="button" class="btn chart-toggle${source === "initial" ? " is-active" : ""}" data-level-source="initial"${hasInitial ? "" : " disabled"} title="${
        hasInitial ? "Show levels from the first week of this signal" : "No initial recommendation snapshot yet"
      }">Initial recommendation</button>
    </div>`;
  return `
    <p class="small muted">
      ${esc(payload.period || "1y")} daily closes · as of ${esc((payload.as_of || "").slice(0, 10) || "—")}
      ${payload.signal ? ` · ${esc(String(payload.signal).replace(/_/g, " "))}` : ""}
    </p>
    ${toggle}
    ${planHint}
    ${levelsHint}
    ${renderPriceChartSvg(payload, levels)}
    ${levelsTableHtml(levels)}
    ${hasInitial ? crossingsTableHtml(payload.level_crossings || []) : ""}
  `;
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
    const defaultSource = "current";
    const render = (source) => {
      body.innerHTML = renderChartBody(payload, report, source);
      body.querySelectorAll("[data-level-source]").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.disabled) return;
          render(button.dataset.levelSource);
        });
      });
    };
    render(defaultSource);
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

const HELD_VS_MARKET_KIND_STYLE = {
  held: { dash: "", width: 2.25 },
  market: { dash: "5 4", width: 1.8 },
  branch: { dash: "3 3", width: 1.8 },
};

function formatHeldMoney(value, currency) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const amount = Number(value);
  const symbol =
    currency === "USD" ? "$" : currency === "EUR" ? "€" : currency === "AUD" ? "A$" : "£";
  return `${symbol}${amount.toFixed(0)}`;
}

function heldVsMarketSeriesList(payload) {
  const series = Array.isArray(payload?.series) ? payload.series : [];
  if (series.length) return series;
  return [
    { id: "held", kind: "held", label: "Held book", color: "#2b6cb0" },
    { id: "market", kind: "market", label: "Market equivalent", color: "#64748b" },
  ];
}

function heldVsMarketPointValue(point, seriesRow) {
  const kind = seriesRow.kind || seriesRow.id;
  if (kind === "held" || seriesRow.id === "held") return point.held;
  if (kind === "market" || seriesRow.id === "market") return point.market;
  const branchId = String(seriesRow.id || "").replace(/^branch:/, "");
  const branches = point.branches || {};
  return branches[branchId];
}

function renderHeldVsMarketPolylines(payload, { width, height, pad }) {
  const points = (payload.points || []).filter((row) => row && row.date);
  const series = heldVsMarketSeriesList(payload);
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const values = [];
  for (const row of points) {
    for (const seriesRow of series) {
      const value = Number(heldVsMarketPointValue(row, seriesRow));
      if (Number.isFinite(value)) values.push(value);
    }
  }
  const minY = values.length ? Math.min(...values) * 0.995 : 0;
  const maxY = values.length ? Math.max(...values) * 1.005 : 1;
  const spanY = maxY - minY || 1;
  const xAt = (index) => pad.left + (index / Math.max(points.length - 1, 1)) * plotW;
  const yAt = (value) => pad.top + plotH - ((value - minY) / spanY) * plotH;
  const polylines = series
    .map((seriesRow) => {
      const pairs = points
        .map((row, index) => {
          const value = Number(heldVsMarketPointValue(row, seriesRow));
          if (!Number.isFinite(value)) return null;
          return `${xAt(index)},${yAt(value)}`;
        })
        .filter(Boolean);
      if (pairs.length < 2) return "";
      const style = HELD_VS_MARKET_KIND_STYLE[seriesRow.kind] || HELD_VS_MARKET_KIND_STYLE.branch;
      const color = seriesRow.color || (seriesRow.kind === "market" ? "#64748b" : "#2b6cb0");
      return `<polyline fill="none" stroke="${color}" stroke-width="${style.width}" stroke-dasharray="${style.dash}" points="${pairs.join(" ")}" />`;
    })
    .join("");
  return { polylines, minY, maxY, xAt, points, series };
}

function heldVsMarketLastCaption(payload, { showExcess = true } = {}) {
  const last = payload?.last || {};
  const currency = payload?.currency;
  if (last.held == null) return "";
  const excess = last.excess_pct;
  const excessHtml =
    showExcess && excess != null
      ? ` · <span class="${excess >= 0 ? "text-positive" : "text-negative"}">${(Number(excess) * 100).toFixed(1)}%</span>`
      : "";
  const marketHtml =
    last.market != null ? ` · mkt ${esc(formatHeldMoney(last.market, currency))}` : "";
  return `<div class="small held-vs-market-spark-caption">Held ${esc(
    formatHeldMoney(last.held, currency)
  )}${marketHtml}${excessHtml}</div>`;
}

/** Short epoch-0 books label every day; longer densified series keep a sparse axis. */
const HELD_VS_MARKET_LABEL_ALL_MAX = 16;

function formatHeldVsMarketDateLabel(date, { compact = false } = {}) {
  const text = String(date || "").slice(0, 10);
  if (!compact) return text;
  return text.length >= 10 ? text.slice(5) : text;
}

function heldVsMarketLabelIndexes(pointCount, { labelAllMax = HELD_VS_MARKET_LABEL_ALL_MAX } = {}) {
  if (pointCount <= 0) return [];
  if (pointCount === 1) return [0];
  if (pointCount <= labelAllMax) {
    return Array.from({ length: pointCount }, (_, index) => index);
  }
  const step = Math.max(1, Math.ceil(pointCount / 4));
  const indexes = [];
  for (let index = 0; index < pointCount; index += step) {
    indexes.push(index);
  }
  if (indexes[indexes.length - 1] !== pointCount - 1) {
    indexes.push(pointCount - 1);
  }
  return indexes;
}

function heldVsMarketDateLabels(points, xAt, { y, compact = false, width = null } = {}) {
  const lastIndex = points.length - 1;
  return heldVsMarketLabelIndexes(points.length)
    .map((index) => {
      const date = points[index] && points[index].date;
      if (!date) return "";
      let x = xAt(index);
      let anchor = "middle";
      if (index === 0) {
        anchor = "start";
        // Keep the first glyph inside the viewBox even when the plot starts at pad.left.
        x = width != null ? Math.min(Math.max(2, x), width - 2) : Math.max(0, x);
      } else if (index === lastIndex) {
        anchor = "end";
        // Pin to the viewBox edge so end-anchored text cannot spill past the SVG.
        x = width != null ? width - 2 : x;
      }
      const label = formatHeldVsMarketDateLabel(date, { compact });
      return `<text x="${x}" y="${y}" text-anchor="${anchor}" class="chart-axis-label held-vs-market-date-label">${esc(
        label
      )}</text>`;
    })
    .filter(Boolean)
    .join("");
}

function renderHeldVsMarketSparkline(payload) {
  const points = payload?.points || [];
  if (!payload || payload.status !== "ok") {
    const reason = payload?.reason || "No marks yet";
    return `<div class="held-vs-market-spark empty"><span class="muted small">${esc(reason)}</span></div>`;
  }
  if (points.length < 2) {
    const day = (payload.last && payload.last.date) || (points[0] && points[0].date) || "";
    return `<div class="held-vs-market-spark empty">
      ${heldVsMarketLastCaption(payload, { showExcess: false })}
      <div class="muted small">${day ? `Opened ${esc(day)} · ` : ""}path after next mark</div>
    </div>`;
  }
  const width = 220;
  const height = 58;
  // Inset the plot so end-anchored MM-DD labels stay inside the tile button.
  const pad = { top: 4, right: 18, bottom: 16, left: 14 };
  const drawn = renderHeldVsMarketPolylines(payload, { width, height, pad });
  const xLabels = heldVsMarketDateLabels(drawn.points, drawn.xAt, {
    y: height - 3,
    compact: true,
    width,
  });
  return `
    <div class="held-vs-market-spark">
      <svg viewBox="0 0 ${width} ${height}" class="held-vs-market-spark-svg" role="img" aria-label="Held book vs market equivalent">
        ${drawn.polylines}
        ${xLabels}
      </svg>
      ${heldVsMarketLastCaption(payload)}
    </div>`;
}

function renderHeldVsMarketChart(payload) {
  if (!payload) {
    return `<p class="muted small">Held vs market series not published yet.</p>`;
  }
  const points = payload.points || [];
  const currency = payload.currency;
  const last = payload.last || {};
  const note = payload.note
    ? `<p class="small muted">${esc(payload.note)}</p>`
    : `<p class="small muted">Held-stock value vs the same capital in ${esc(payload.benchmark_ticker || "the local index")}. Knob-changed branches overlay here when applied.</p>`;
  if (payload.status !== "ok" || points.length < 2) {
    return `
      <div class="held-vs-market-chart">
        <h4 class="small" style="margin-top:1rem">Held vs market</h4>
        ${note}
        <p class="muted small">${esc(payload.reason || "Need two dated marks before a path can plot. Last print is still shown.")}</p>
        ${
          last.held != null
            ? heldVsMarketLastCaption(payload, { showExcess: false }) +
              (last.date ? `<p class="muted small">${esc(last.date)}</p>` : "")
            : ""
        }
      </div>`;
  }
  const width = 620;
  const height = 220;
  const pad = { top: 18, right: 28, bottom: 36, left: 48 };
  const drawn = renderHeldVsMarketPolylines(payload, { width, height, pad });
  const xLabels = heldVsMarketDateLabels(drawn.points, drawn.xAt, {
    y: height - 12,
    // Same compact MM-DD as the tile; full ISO stays in the caption under the chart.
    compact: true,
    width,
  });
  const legend = drawn.series
    .map((seriesRow) => {
      const pending = seriesRow.status === "pending" ? " (pending)" : "";
      return `<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:${esc(
        seriesRow.color || "#64748b"
      )}"></span>${esc(seriesRow.label || seriesRow.id)}${esc(pending)}</span>`;
    })
    .join("");
  const source = payload.source === "observe_sim" ? "observe sim" : payload.paper_instrument || "paper book";
  return `
    <div class="held-vs-market-chart">
      <h4 class="small" style="margin-top:1rem">Held vs market</h4>
      ${note}
      <p class="small muted" style="margin-top:0">${esc(source)} · ${esc(payload.held_path || "marks")} / ${esc(
        payload.market_path || "none"
      )}${payload.branch_ready ? " · branch-ready" : ""}</p>
      <div class="price-chart-wrap held-vs-market-wrap">
        <svg viewBox="0 0 ${width} ${height}" class="price-chart held-vs-market-svg" role="img" aria-label="Held book versus market equivalent">
          <text x="${pad.left}" y="${pad.top}" class="chart-axis-label">${esc(formatHeldMoney(drawn.maxY, currency))}</text>
          <text x="${pad.left}" y="${height - pad.bottom}" class="chart-axis-label">${esc(formatHeldMoney(drawn.minY, currency))}</text>
          ${drawn.polylines}
          ${xLabels}
        </svg>
        <div class="chart-legend">${legend}</div>
      </div>
      <p class="small">
        Last held ${esc(formatHeldMoney(last.held, currency))}
        ${last.market != null ? ` vs market ${esc(formatHeldMoney(last.market, currency))}` : ""}
        ${
          last.excess_pct != null
            ? ` · excess ${(Number(last.excess_pct) * 100).toFixed(1)}%`
            : ""
        }
        ${last.date ? ` · ${esc(last.date)}` : ""}
      </p>
    </div>`;
}
