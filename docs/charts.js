/* Price chart popup with trade-plan level markers. */

const CHART_LEVEL_STYLES = {
  last: { color: "#1a1f2e", label: "Last", dash: "" },
  book_cost: { color: "#0f766e", label: "Book cost", dash: "5 3" },
  core_limit: { color: "#2b6cb0", label: "Core buy", dash: "6 4" },
  tactical_limit: { color: "#2e9c4f", label: "Tactical buy", dash: "6 4" },
  stop_loss: { color: "#b33a3a", label: "Stop", dash: "4 3" },
  take_profit: { color: "#b8860b", label: "Target", dash: "4 3" },
  sma50: { color: "#7c3aed", label: "SMA 50", dash: "2 3" },
  sma200: { color: "#64748b", label: "SMA 200", dash: "2 3" },
};

const CHART_SMA_SERIES = {
  sma50: { key: "sma50_series", color: "#7c3aed", label: "SMA 50" },
  sma200: { key: "sma200_series", color: "#64748b", label: "SMA 200" },
};

/** Calendar-day pad before assessment start so SMA200 is visible entering the window. */
const CLIP_WARMUP_CALENDAR_DAYS = 220;

/** Horizontal trade levels — SMAs prefer series overlays when present. */
const CHART_HORIZONTAL_LEVEL_KEYS = [
  "last",
  "book_cost",
  "core_limit",
  "tactical_limit",
  "stop_loss",
  "take_profit",
];

function chartPathForReport(report) {
  if (report?.chart_path) return report.chart_path;
  if (!report?.ticker) return null;
  const slug = String(report.ticker).replace(/[^A-Za-z0-9._-]+/g, "_");
  return `data/charts/${slug}.json`;
}

function formatChartPrice(value, currency) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const code = String(currency || "GBP").toUpperCase();
  const symbol =
    code === "USD" ? "$" : code === "EUR" ? "€" : code === "AUD" ? "A$" : code === "CAD" ? "C$" : "£";
  return `${symbol}${Number(value).toFixed(2)}`;
}

function estimateLabelWidth(text) {
  // Approximate SVG label width for ~10–11px font.
  return Math.ceil(String(text).length * 6.4);
}

/** Truncate chart / pattern labels; full text goes in SVG <title> / HTML title. */
function truncateChartLabel(text, maxChars = 22) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  if (raw.length <= maxChars) return raw;
  return `${raw.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
}

/**
 * Nudge horizontal-level label Ys so two-line (name + price) stacks do not overlap.
 * Default gap fits ~11px name + ~10px price with a small breathing room.
 */
function nudgeLevelLabelYs(entries, minGap = 28) {
  const sorted = [...entries].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i += 1) {
    const prev = sorted[i - 1];
    const current = sorted[i];
    if (current.y - prev.y < minGap) {
      current.y = prev.y + minGap;
    }
  }
  // Second pass upward so a tall stack near the bottom does not pile on the floor.
  for (let i = sorted.length - 2; i >= 0; i -= 1) {
    const next = sorted[i + 1];
    const current = sorted[i];
    if (next.y - current.y < minGap) {
      current.y = next.y - minGap;
    }
  }
  return sorted;
}

/** Stagger in-plot label Ys (pattern / marker text) inside [minY, maxY]. */
function staggerLabelYs(entries, minGap = 13, minY = 12, maxY = 200) {
  if (!entries.length) return entries;
  const sorted = [...entries].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i += 1) {
    if (sorted[i].y - sorted[i - 1].y < minGap) {
      sorted[i].y = sorted[i - 1].y + minGap;
    }
  }
  if (sorted[sorted.length - 1].y > maxY) {
    const overflow = sorted[sorted.length - 1].y - maxY;
    for (const row of sorted) row.y -= overflow;
  }
  if (sorted[0].y < minY) {
    const shift = minY - sorted[0].y;
    for (const row of sorted) row.y += shift;
  }
  // Final downward clamp if still colliding after upward shift.
  for (let i = 1; i < sorted.length; i += 1) {
    if (sorted[i].y - sorted[i - 1].y < minGap) {
      sorted[i].y = sorted[i - 1].y + minGap;
    }
  }
  return sorted;
}

function tradePlanLevelsFromReport(report) {
  const plan =
    report && typeof report.trade_plan === "object" && report.trade_plan
      ? report.trade_plan
      : report || {};
  const out = {};
  const map = [
    ["core_limit", "core_limit"],
    ["tactical_limit", "tactical_limit"],
    ["stop_loss", "tactical_stop_loss"],
    ["stop_loss", "stop_loss"],
    ["take_profit", "tactical_take_profit"],
    ["take_profit", "take_profit"],
  ];
  for (const [dest, src] of map) {
    if (out[dest] != null) continue;
    const value = plan[src];
    if (value != null && !Number.isNaN(Number(value))) out[dest] = Number(value);
  }
  return out;
}

function mergeChartLevels(payloadLevels, report, overlays) {
  const merged = { ...(payloadLevels || {}) };
  const fromReport = tradePlanLevelsFromReport(report);
  for (const [key, value] of Object.entries(fromReport)) {
    if (merged[key] == null && value != null) merged[key] = value;
  }
  const extra = overlays || {};
  if (extra.book_cost != null && !Number.isNaN(Number(extra.book_cost))) {
    merged.book_cost = Number(extra.book_cost);
  }
  return merged;
}

function hasTradePlanLevels(levels) {
  return ["core_limit", "tactical_limit", "stop_loss", "take_profit"].some(
    (key) => levels?.[key] != null
  );
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

function chartSeriesPolyline(values, xAt, yAt, color, label) {
  if (!Array.isArray(values) || !values.length) return { path: "", legend: "" };
  const segments = [];
  let current = [];
  values.forEach((value, index) => {
    if (value == null || Number.isNaN(Number(value))) {
      if (current.length > 1) segments.push(current);
      current = [];
      return;
    }
    current.push(`${xAt(index)},${yAt(Number(value))}`);
  });
  if (current.length > 1) segments.push(current);
  if (!segments.length) return { path: "", legend: "" };
  const path = segments
    .map(
      (pts) =>
        `<polyline fill="none" stroke="${color}" stroke-width="1.6" stroke-dasharray="3 3" points="${pts.join(
          " "
        )}" />`
    )
    .join("");
  const legend = `<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:${color}"></span>${esc(
    label
  )}</span>`;
  return { path, legend };
}

function dateMarkerLine(dates, markerDate, xAt, pad, label, labelOffset = 0, color = "#0f172a") {
  if (!markerDate || !dates.length) return "";
  let markerIndex = dates.findIndex((date) => date >= markerDate);
  if (markerIndex < 0) markerIndex = dates.length - 1;
  for (let i = 0; i < dates.length; i += 1) {
    if (dates[i] <= markerDate) markerIndex = i;
    else break;
  }
  const mx = xAt(markerIndex);
  const labelY = pad.top + 14 + labelOffset;
  const shortLabel = truncateChartLabel(label, 24);
  return `
    <line x1="${mx}" y1="${pad.top}" x2="${mx}" y2="${pad.top + pad.plotH}"
      stroke="${color}" stroke-width="1.5" stroke-dasharray="5 4" stroke-opacity="0.75" />
    <text x="${mx + 4}" y="${labelY}" class="chart-signal-marker-label" style="fill:${color}"><title>${esc(
      label
    )}</title>${esc(shortLabel)}</text>`;
}

function tradeFillMarker(dates, markerDate, price, xAt, yAt, pad, label, color, labelOffset = 0) {
  if (!markerDate || !dates.length) return "";
  let markerIndex = dates.findIndex((date) => date >= markerDate);
  if (markerIndex < 0) markerIndex = dates.length - 1;
  for (let i = 0; i < dates.length; i += 1) {
    if (dates[i] <= markerDate) markerIndex = i;
    else break;
  }
  const mx = xAt(markerIndex);
  const labelY = pad.top + 14 + labelOffset;
  const hasPrice = price != null && !Number.isNaN(Number(price));
  const my = hasPrice ? yAt(Number(price)) : null;
  const point =
    my != null
      ? `<circle cx="${mx}" cy="${my}" r="5" fill="${color}" stroke="#fff" stroke-width="1.5" />`
      : "";
  const shortLabel = truncateChartLabel(label, 26);
  return `
    <line x1="${mx}" y1="${pad.top}" x2="${mx}" y2="${pad.top + pad.plotH}"
      stroke="${color}" stroke-width="1.5" stroke-dasharray="5 4" stroke-opacity="0.8" />
    ${point}
    <text x="${mx + 6}" y="${labelY}" class="chart-signal-marker-label" style="fill:${color}"><title>${esc(
      label
    )}</title>${esc(shortLabel)}</text>`;
}

function assessmentBandRect(dates, band, xAt, pad) {
  if (!band || !dates.length) return "";
  const start = chartDay(band.start);
  const end = chartDay(band.end);
  if (!start && !end) return "";
  let startIdx = 0;
  let endIdx = dates.length - 1;
  if (start) {
    startIdx = dates.findIndex((date) => chartDay(date) >= start);
    if (startIdx < 0) return "";
  }
  if (end) {
    for (let i = 0; i < dates.length; i += 1) {
      if (chartDay(dates[i]) <= end) endIdx = i;
      else break;
    }
  }
  if (endIdx < startIdx) return "";
  const x1 = xAt(startIdx);
  const x2 = xAt(endIdx);
  const w = Math.max(1, x2 - x1);
  return `<rect x="${x1}" y="${pad.top}" width="${w}" height="${pad.plotH}"
    fill="rgba(15, 23, 42, 0.055)" stroke="none" />
    <text x="${x1 + 4}" y="${pad.top + 12}" class="chart-axis-label" style="fill:#64748b">Assessment</text>`;
}

/** Package M autopsy pattern marks — tone colors (iPad-readable, not live signals). */
const PATTERN_MARK_TONES = {
  warn: { fill: "rgba(180, 83, 9, 0.16)", stroke: "#b45309", text: "#9a3412" },
  weak: { fill: "rgba(179, 58, 58, 0.15)", stroke: "#b33a3a", text: "#9f1239" },
  info: { fill: "rgba(3, 105, 161, 0.12)", stroke: "#0369a1", text: "#0c4a6e" },
  good: { fill: "rgba(46, 156, 79, 0.13)", stroke: "#2e9c4f", text: "#166534" },
  // Owner post-hoc geometry (N229) — distinct from factory tones.
  owner: { fill: "rgba(124, 58, 237, 0.14)", stroke: "#6d28d9", text: "#5b21b6" },
};

function patternMarkTone(tone) {
  return PATTERN_MARK_TONES[tone] || PATTERN_MARK_TONES.info;
}

function chartKeyForRangeMode(rangeMode, overlays) {
  if (rangeMode === "wider_tf") return "wider_tf";
  if (rangeMode === "close_in") {
    return (overlays && overlays.pattern_chart_key) || "episode";
  }
  return "full";
}

function filterPatternMarks(marks, chartKey) {
  if (!Array.isArray(marks) || !marks.length) return [];
  if (!chartKey || chartKey === "full") return marks.slice();
  return marks.filter((row) => {
    if (!row || typeof row !== "object") return false;
    const charts = Array.isArray(row.charts) ? row.charts : ["episode", "wider_tf"];
    if (charts.includes(chartKey)) return true;
    // entry_blind pit maps to close_in sleeve; accept episode aliases.
    if (chartKey === "pit" && (charts.includes("episode") || charts.includes("pit"))) {
      return true;
    }
    if (chartKey === "episode" && charts.includes("pit")) return true;
    return false;
  });
}

function dateIndexOnOrBefore(dates, isoDay) {
  const target = chartDay(isoDay);
  if (!target || !dates.length) return -1;
  let idx = -1;
  for (let i = 0; i < dates.length; i += 1) {
    const day = chartDay(dates[i]);
    if (!day) continue;
    if (day <= target) idx = i;
    else break;
  }
  if (idx < 0) {
    const ahead = dates.findIndex((date) => chartDay(date) >= target);
    return ahead;
  }
  return idx;
}

function resolvePatternMarkPrice(mark, payload) {
  if (!mark) return null;
  if (mark.price != null && !Number.isNaN(Number(mark.price))) return Number(mark.price);
  const anchor = String(mark.anchor || "");
  if (anchor === "entry_price" && payload._entry_price != null) {
    return Number(payload._entry_price);
  }
  if (anchor === "exit_price" && payload._exit_price != null) {
    return Number(payload._exit_price);
  }
  return null;
}

function enrichPatternMarkLabel(mark, dates, closes, payload) {
  const base = String((mark && mark.label) || "").trim() || "Pattern";
  const type = String((mark && mark.type) || "");
  const ref = String((mark && mark.ref) || "");
  if (!dates.length || !closes.length) return base;

  if (type === "range_ref") {
    const nums = closes
      .map((v) => (v == null || Number.isNaN(Number(v)) ? null : Number(v)))
      .filter((v) => v != null);
    if (nums.length < 3) return base;
    const lo = Math.min(...nums);
    const hi = Math.max(...nums);
    const span = hi - lo || 1;
    let price = null;
    if (ref === "exit" && payload._exit_price != null) price = Number(payload._exit_price);
    else if (payload._entry_price != null) price = Number(payload._entry_price);
    if (price == null || Number.isNaN(price)) return base;
    const pctile = Math.round(((price - lo) / span) * 100);
    const where =
      pctile <= 20 ? "near range low" : pctile >= 80 ? "near range high" : `~${pctile}th %ile`;
    return `${base}: ${where}`;
  }

  if (type === "ma_context") {
    const day =
      chartDay(mark.t0) ||
      (ref === "exit" ? chartDay(payload._sold_at) : chartDay(payload._opened_at));
    const idx = dateIndexOnOrBefore(dates, day);
    if (idx < 0) return base;
    const close = closes[idx] != null ? Number(closes[idx]) : null;
    const sma50 = Array.isArray(payload.sma50_series)
      ? Number(payload.sma50_series[idx])
      : null;
    const sma200 = Array.isArray(payload.sma200_series)
      ? Number(payload.sma200_series[idx])
      : null;
    const bits = [];
    if (close != null && !Number.isNaN(close) && sma50 != null && !Number.isNaN(sma50)) {
      bits.push(close >= sma50 ? "≥ SMA50" : "< SMA50");
    }
    if (close != null && !Number.isNaN(close) && sma200 != null && !Number.isNaN(sma200)) {
      bits.push(close >= sma200 ? "≥ SMA200" : "< SMA200");
    }
    return bits.length ? `${base}: ${bits.join(", ")}` : base;
  }
  return base;
}

function renderPatternMarksSvg(marks, dates, closes, xAt, yAt, pad, payload) {
  if (!Array.isArray(marks) || !marks.length || !dates.length) {
    return { svg: "", legend: "" };
  }
  const parts = [];
  const legendBits = [];
  const pendingLabels = [];
  // Leave room for Bought/Sold marker text (drawn later in the same top strip).
  const tradeReserve = 36;
  const labelMinY = pad.top + 12;
  const labelMaxY = pad.top + Math.min(pad.plotH - 8, tradeReserve + marks.length * 13);
  const plotRight = pad.left + (typeof pad.plotW === "number" ? pad.plotW : 400);

  marks.forEach((mark, index) => {
    if (!mark || typeof mark !== "object") return;
    const tone = patternMarkTone(mark.tone);
    const label = enrichPatternMarkLabel(mark, dates, closes, payload);
    const shortLabel = truncateChartLabel(label, 20);
    const type = String(mark.type || "region");
    legendBits.push(
      `<span class="chart-legend-item chart-pattern-legend" title="${esc(label)}"><span class="chart-legend-swatch" style="background:${
        tone.stroke
      }"></span>${esc(shortLabel)}</span>`
    );

    if (
      type === "region" ||
      type === "post_exit_band" ||
      type === "entry_band" ||
      type === "range_ref"
    ) {
      let startIdx = 0;
      let endIdx = dates.length - 1;
      if (mark.t0) {
        const idx = dateIndexOnOrBefore(dates, mark.t0);
        if (idx >= 0) startIdx = idx;
      }
      if (mark.t1) {
        const idx = dateIndexOnOrBefore(dates, mark.t1);
        if (idx >= 0) endIdx = idx;
      }
      if (type === "range_ref") {
        // Full visible assessment window — shade lightly + label only.
        startIdx = 0;
        endIdx = dates.length - 1;
      }
      if (endIdx < startIdx) return;
      const x1 = xAt(startIdx);
      const x2 = xAt(endIdx);
      const w = Math.max(4, x2 - x1);
      const ownerCls = String(mark.source || "") === "owner" ? " chart-human-mark" : "";
      parts.push(`<rect x="${x1}" y="${pad.top}" width="${w}" height="${pad.plotH}"
        fill="${tone.fill}" stroke="${tone.stroke}" stroke-width="1" stroke-dasharray="3 3"
        stroke-opacity="0.55" class="chart-pattern-mark${ownerCls}" data-pattern="${esc(
          String(mark.pattern || "")
        )}" />`);
      pendingLabels.push({
        kind: "band",
        x: x1 + 4,
        y: labelMinY + tradeReserve + index * 2,
        maxX: Math.min(x1 + w - 4, plotRight - 4),
        tone,
        label,
        shortLabel,
      });
      return;
    }

    if (type === "hline") {
      const price = resolvePatternMarkPrice(mark, payload);
      if (price == null || Number.isNaN(price)) return;
      const y = yAt(price);
      const xRight = dates.length ? xAt(dates.length - 1) : pad.left;
      const ownerCls = String(mark.source || "") === "owner" ? " chart-human-mark" : "";
      parts.push(`<line x1="${pad.left}" y1="${y}" x2="${xRight}" y2="${y}"
        stroke="${tone.stroke}" stroke-width="1.4" stroke-dasharray="4 3"
        stroke-opacity="0.85" class="chart-pattern-mark${ownerCls}" />`);
      pendingLabels.push({
        kind: "hline",
        x: pad.left + 4,
        y: Math.max(labelMinY, y - 5),
        maxX: plotRight - 4,
        tone,
        label,
        shortLabel,
      });
      return;
    }

    if (type === "trend_line") {
      const t0 = chartDay(mark.t0);
      const t1 = chartDay(mark.t1);
      const y0 = mark.y0 != null ? Number(mark.y0) : null;
      const y1 = mark.y1 != null ? Number(mark.y1) : null;
      if (!t0 || !t1 || y0 == null || Number.isNaN(y0) || y1 == null || Number.isNaN(y1)) {
        return;
      }
      const i0 = dateIndexOnOrBefore(dates, t0);
      const i1 = dateIndexOnOrBefore(dates, t1);
      if (i0 < 0 || i1 < 0) return;
      const ownerCls = String(mark.source || "") === "owner" ? " chart-human-mark" : "";
      parts.push(`<line x1="${xAt(i0)}" y1="${yAt(y0)}" x2="${xAt(i1)}" y2="${yAt(y1)}"
        stroke="${tone.stroke}" stroke-width="2" stroke-opacity="0.9"
        class="chart-pattern-mark${ownerCls}" />`);
      pendingLabels.push({
        kind: "hline",
        x: xAt(Math.min(i0, i1)) + 4,
        y: Math.max(labelMinY, Math.min(yAt(y0), yAt(y1)) - 5),
        maxX: plotRight - 4,
        tone,
        label,
        shortLabel,
      });
      return;
    }

    if (type === "ma_context" || type === "callout") {
      const day =
        chartDay(mark.t0) ||
        chartDay(payload._sold_at) ||
        chartDay(payload._opened_at) ||
        chartDay(dates[dates.length - 1]);
      const idx = dateIndexOnOrBefore(dates, day);
      if (idx < 0) return;
      const mx = xAt(idx);
      const close = closes[idx] != null ? Number(closes[idx]) : null;
      const my =
        close != null && !Number.isNaN(close) ? yAt(close) : pad.top + pad.plotH * 0.35;
      parts.push(`<circle cx="${mx}" cy="${my}" r="4.5" fill="${tone.stroke}" stroke="#fff"
        stroke-width="1.25" class="chart-pattern-mark" />`);
      const preferLeft = mx > pad.left + (plotRight - pad.left) * 0.62;
      pendingLabels.push({
        kind: "callout",
        x: preferLeft ? mx - 6 : mx + 6,
        anchor: preferLeft ? "end" : "start",
        y: Math.max(labelMinY, my - 10),
        maxX: plotRight - 4,
        tone,
        label,
        shortLabel,
      });
    }
  });

  staggerLabelYs(pendingLabels, 13, labelMinY, Math.max(labelMinY + 13, labelMaxY));
  for (const row of pendingLabels) {
    let x = row.x;
    const approxW = estimateLabelWidth(row.shortLabel);
    if (row.anchor === "end") {
      x = Math.max(pad.left + 4 + approxW, Math.min(x, row.maxX));
    } else {
      x = Math.min(x, Math.max(pad.left + 4, row.maxX - approxW));
      x = Math.max(pad.left + 4, x);
    }
    const anchor = row.anchor === "end" ? ` text-anchor="end"` : "";
    parts.push(`<text x="${x}" y="${row.y}" class="chart-pattern-mark-label"${anchor} style="fill:${
      row.tone.text
    }"><title>${esc(row.label)}</title>${esc(row.shortLabel)}</text>`);
  }
  return {
    svg: parts.join(""),
    legend: legendBits.join(""),
  };
}

function volumeBarsSvg(volumes, xAt, volPad, plotW) {
  if (!Array.isArray(volumes) || !volumes.length) return "";
  const nums = volumes
    .map((v) => (v == null || Number.isNaN(Number(v)) ? null : Number(v)))
    .filter((v) => v != null && v >= 0);
  if (!nums.length) return "";
  const maxV = Math.max(...nums, 1);
  const barW = Math.max(1, (plotW / Math.max(volumes.length, 1)) * 0.7);
  return volumes
    .map((raw, index) => {
      if (raw == null || Number.isNaN(Number(raw))) return "";
      const value = Number(raw);
      const h = (value / maxV) * volPad.plotH;
      const x = xAt(index) - barW / 2;
      const y = volPad.top + volPad.plotH - h;
      return `<rect x="${x}" y="${y}" width="${barW}" height="${Math.max(0.5, h)}"
        fill="rgba(100, 116, 139, 0.45)" />`;
    })
    .join("");
}

function renderPriceChartSvg(payload, levelsOverride) {
  const dates = payload.dates || [];
  const closes = payload.closes || [];
  if (!dates.length || dates.length !== closes.length) {
    return `<p class="muted">No price series available.</p>`;
  }

  const currency = payload.currency || "GBP";
  const showVolume = Boolean(payload._show_volume);
  const volumes = Array.isArray(payload.volumes) ? payload.volumes : [];
  const levels = { ...(levelsOverride || payload.levels || {}) };
  const smaSeriesPresent = Object.values(CHART_SMA_SERIES).some((meta) =>
    Array.isArray(payload[meta.key])
  );
  const activeLevels = CHART_HORIZONTAL_LEVEL_KEYS.filter((key) => levels[key] != null).map(
    (key) => [key, CHART_LEVEL_STYLES[key]]
  );
  // Fall back to point-in-time SMA lines only when series overlays are absent.
  if (!smaSeriesPresent) {
    for (const key of ["sma50", "sma200"]) {
      if (levels[key] != null) activeLevels.push([key, CHART_LEVEL_STYLES[key]]);
    }
  }
  const longestLabel = activeLevels.reduce((max, [, style]) => {
    const sample = `${style.label}`;
    const priceSample = formatChartPrice(99999.99, currency);
    return Math.max(max, estimateLabelWidth(sample), estimateLabelWidth(priceSample));
  }, 90);
  const rightPad = Math.max(168, longestLabel + 28);
  const width = 620 + rightPad;
  const volPane = showVolume ? 72 : 0;
  const patternCount = Array.isArray(payload._pattern_marks) ? payload._pattern_marks.length : 0;
  // Extra top strip so pattern + Bought/Sold labels are not clipped by the viewBox.
  const topPad = 28 + Math.min(36, patternCount * 6);
  const height = 380 + volPane + (topPad - 28);
  const pad = { top: topPad, right: rightPad, bottom: 42 + volPane, left: 22, plotH: 0, plotW: 0 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  pad.plotH = plotH;
  pad.plotW = plotW;
  const volPad = showVolume
    ? { top: pad.top + plotH + 10, plotH: Math.max(28, volPane - 18) }
    : null;

  const seriesValues = Object.values(CHART_SMA_SERIES).flatMap((meta) =>
    Array.isArray(payload[meta.key])
      ? payload[meta.key].filter((v) => v != null && !Number.isNaN(Number(v))).map(Number)
      : []
  );
  const levelValues = activeLevels.map(([key]) => Number(levels[key]));
  const entryPrice =
    payload._entry_price != null && !Number.isNaN(Number(payload._entry_price))
      ? Number(payload._entry_price)
      : null;
  const exitPrice =
    payload._exit_price != null && !Number.isNaN(Number(payload._exit_price))
      ? Number(payload._exit_price)
      : null;
  const fillValues = [entryPrice, exitPrice].filter((v) => v != null);
  const minClose = Math.min(...closes);
  const maxClose = Math.max(...closes);
  const minY = Math.min(minClose, ...levelValues, ...seriesValues, ...fillValues, minClose * 0.98);
  const maxY = Math.max(maxClose, ...levelValues, ...seriesValues, ...fillValues, maxClose * 1.02);
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

  const levelLabelMinY = pad.top + 14;
  const levelLabelMaxY = pad.top + plotH - 14;
  for (const entry of labelEntries) {
    entry.y = Math.min(levelLabelMaxY, Math.max(levelLabelMinY, entry.y));
  }
  // Re-nudge after clamp so stacked labels near the floor/ceiling stay readable.
  nudgeLevelLabelYs(labelEntries, 28);
  for (const entry of labelEntries) {
    entry.y = Math.min(levelLabelMaxY, Math.max(levelLabelMinY, entry.y));
  }

  const levelLines = labelEntries
    .map(({ style, value, lineY, y }) => {
      const labelX = width - pad.right + 12;
      const priceText = formatChartPrice(value, currency);
      const tip = `${style.label}: ${priceText}`;
      return `
        <line x1="${pad.left}" y1="${lineY}" x2="${width - pad.right}" y2="${lineY}"
          stroke="${style.color}" stroke-width="1.6" stroke-dasharray="${style.dash}" />
        <line x1="${width - pad.right}" y1="${lineY}" x2="${labelX - 4}" y2="${y - 2}"
          stroke="${style.color}" stroke-width="1" stroke-opacity="0.4" />
        <text x="${labelX}" y="${y - 5}" class="chart-level-label" fill="${style.color}"><title>${esc(
          tip
        )}</title>${esc(style.label)}</text>
        <text x="${labelX}" y="${y + 9}" class="chart-level-price" fill="${style.color}"><title>${esc(
          tip
        )}</title>${esc(priceText)}</text>`;
    })
    .join("");

  const smaPlots = Object.values(CHART_SMA_SERIES).map((meta) =>
    chartSeriesPolyline(payload[meta.key], xAt, yAt, meta.color, meta.label)
  );
  const smaPaths = smaPlots.map((row) => row.path).join("");
  const smaLegend = smaPlots.map((row) => row.legend).join("");

  const openedAt = (payload._opened_at || "").slice(0, 10);
  const soldAt = (payload._sold_at || "").slice(0, 10);
  const signalSince = (payload.signal_since || payload.levels_as_of || "").slice(0, 10);
  let signalMarker = "";
  let labelOffset = 0;
  if (openedAt) {
    const buyLabel =
      entryPrice != null
        ? `Bought ${openedAt} · ${formatChartPrice(entryPrice, currency)}`
        : `Bought ${openedAt}`;
    signalMarker += tradeFillMarker(
      dates,
      openedAt,
      entryPrice,
      xAt,
      yAt,
      pad,
      buyLabel,
      "#2e9c4f",
      labelOffset
    );
    labelOffset += 16;
  }
  if (soldAt) {
    const sellLabel =
      exitPrice != null
        ? `Sold ${soldAt} · ${formatChartPrice(exitPrice, currency)}`
        : `Sold ${soldAt}`;
    signalMarker += tradeFillMarker(
      dates,
      soldAt,
      exitPrice,
      xAt,
      yAt,
      pad,
      sellLabel,
      "#b33a3a",
      labelOffset
    );
    labelOffset += 16;
  }
  if (signalSince && signalSince !== openedAt && signalSince !== soldAt) {
    signalMarker += dateMarkerLine(
      dates,
      signalSince,
      xAt,
      pad,
      `Signal since ${signalSince}`,
      labelOffset,
      "#0f172a"
    );
  }

  const xLabels = dates
    .map((date, index) => ({ date, index }))
    .filter(({ index }) => index % Math.max(1, Math.ceil(dates.length / 5)) === 0 || index === dates.length - 1)
    .map(
      ({ date, index }) =>
        `<text x="${xAt(index)}" y="${height - 12}" text-anchor="middle" class="chart-axis-label">${esc(date.slice(0, 7))}</text>`
    )
    .join("");

  const volumeLegend = showVolume
    ? `<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#64748b"></span>Volume</span>`
    : "";
  const legend = `${activeLevels
    .map(
      ([, style]) =>
        `<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:${style.color}"></span>${esc(style.label)}</span>`
    )
    .join("")}${smaLegend}${volumeLegend}`;
  const band = assessmentBandRect(dates, payload.assessment_band, xAt, pad);
  const patternDrawn = renderPatternMarksSvg(
    payload._pattern_marks || [],
    dates,
    closes,
    xAt,
    yAt,
    pad,
    payload
  );
  const volumeSvg =
    showVolume && volPad ? volumeBarsSvg(volumes, xAt, volPad, plotW) : "";
  const volumeDivider = showVolume
    ? `<line x1="${pad.left}" y1="${pad.top + plotH + 4}" x2="${width - pad.right}" y2="${
        pad.top + plotH + 4
      }" stroke="#e2e8f0" stroke-width="1" />`
    : "";
  const patternLegend = patternDrawn.legend
    ? `<div class="chart-pattern-legend-row" aria-label="Factory pattern marks">${patternDrawn.legend}</div>`
    : "";

  return `
    <div class="price-chart-wrap">
      <svg viewBox="0 0 ${width} ${height}" width="${width}" class="price-chart" role="img" aria-label="Price chart with trade levels and factory pattern marks">
        ${band}
        ${patternDrawn.svg}
        ${grid}
        <polygon points="${areaPoints}" fill="rgba(43,108,176,0.08)"></polygon>
        <polyline fill="none" stroke="#2b6cb0" stroke-width="2.25" points="${linePoints}" />
        ${smaPaths}
        ${signalMarker}
        ${levelLines}
        <text x="${pad.left}" y="${pad.top + 4}" class="chart-axis-label">${formatChartPrice(maxY, currency)}</text>
        <text x="${pad.left}" y="${pad.top + plotH}" class="chart-axis-label">${formatChartPrice(minY, currency)}</text>
        ${volumeDivider}
        ${volumeSvg}
        ${xLabels}
      </svg>
      <div class="chart-legend">${legend}</div>
      ${patternLegend}
    </div>`;
}

function levelsTableHtml(levels, { smaAsSeries = false, currency = "GBP" } = {}) {
  const keys = Object.keys(CHART_LEVEL_STYLES).filter((key) => {
    if (levels?.[key] == null) return false;
    if (smaAsSeries && (key === "sma50" || key === "sma200")) return true;
    return true;
  });
  const rows = keys
    .map((key) => {
      const style = CHART_LEVEL_STYLES[key];
      const note =
        smaAsSeries && (key === "sma50" || key === "sma200")
          ? ` <span class="muted small">(path)</span>`
          : "";
      return `<tr>
          <td><span class="chart-legend-swatch" style="background:${style.color}"></span> ${esc(
            style.label
          )}${note}</td>
          <td>${formatChartPrice(levels[key], currency)}</td>
        </tr>`;
    })
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

function crossingsTableHtml(crossings, currency) {
  if (!Array.isArray(crossings) || !crossings.length) return "";
  const rows = crossings
    .map((row) => {
      const style = CHART_LEVEL_STYLES[row.key] || { color: "#64748b" };
      return `<tr>
        <td><span class="chart-legend-swatch" style="background:${style.color}"></span> ${esc(row.label || row.key)}</td>
        <td>${formatChartPrice(row.price, currency)}</td>
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
    book_cost: current.book_cost ?? payload.initial_levels.book_cost,
  };
}

function chartDay(value) {
  return String(value || "").slice(0, 10);
}

function shiftCalendarDays(isoDay, deltaDays) {
  const day = chartDay(isoDay);
  if (!day || !Number.isFinite(deltaDays) || deltaDays === 0) return day;
  const stamp = new Date(`${day}T12:00:00Z`);
  if (Number.isNaN(stamp.getTime())) return day;
  stamp.setUTCDate(stamp.getUTCDate() + deltaDays);
  return stamp.toISOString().slice(0, 10);
}

/** Keep closes inside [start − warm-up, end]. Missing edges stay open.
 * Warm-up (default 0) pads before assessment start so SMA200 is visible.
 * Sets ``assessment_band`` to the unpadded window for shading.
 */
function clipPriceSeries(payload, range, options) {
  const source = payload || {};
  const dates = Array.isArray(source.dates) ? source.dates : [];
  const closes = Array.isArray(source.closes) ? source.closes : [];
  const start = chartDay(range && range.start);
  const end = chartDay(range && range.end);
  if ((!start && !end) || !dates.length) return source;
  const warmupRaw = options && options.warmupCalendarDays;
  const warmup =
    warmupRaw == null || warmupRaw === ""
      ? 0
      : Number(warmupRaw);
  const padDays = Number.isFinite(warmup) && warmup > 0 ? warmup : 0;
  const clipStart = start && padDays ? shiftCalendarDays(start, -padDays) : start;
  const indexes = [];
  dates.forEach((date, index) => {
    const day = chartDay(date);
    if (!day) return;
    if (clipStart && day < clipStart) return;
    if (end && day > end) return;
    indexes.push(index);
  });
  const take = (values) => {
    if (!Array.isArray(values) || values.length !== dates.length) return values;
    return indexes.map((index) => values[index]);
  };
  const next = {
    ...source,
    dates: indexes.map((index) => dates[index]),
    closes: indexes.map((index) => (index < closes.length ? closes[index] : null)),
  };
  if (Array.isArray(source.volumes)) next.volumes = take(source.volumes);
  for (const meta of Object.values(CHART_SMA_SERIES)) {
    if (Array.isArray(source[meta.key])) next[meta.key] = take(source[meta.key]);
  }
  if (start || end) {
    next.assessment_band = { start: start || null, end: end || null };
  }
  return next;
}

function closeInRangeLabel(range) {
  const before = Number(range && range.days_before);
  const after = Number(range && range.days_after);
  if (Number.isFinite(before) && Number.isFinite(after) && before === after) {
    return `Sleeve ± ${before}d`;
  }
  const bits = [];
  if (Number.isFinite(before)) bits.push(`−${before}d`);
  if (Number.isFinite(after)) bits.push(`+${after}d`);
  return bits.length ? `Sleeve ${bits.join(" / ")}` : "Sleeve window";
}

function widerTfRangeLabel(range) {
  const before = Number(range && range.days_before);
  const after = Number(range && range.days_after);
  if (Number.isFinite(before) && Number.isFinite(after)) {
    return `Wider −${before}d / +${after}d`;
  }
  return "Wider TF";
}

function chartRangeToggle(rangeMode, closeIn, widerTf) {
  if (!closeIn || (!closeIn.start && !closeIn.end)) return "";
  const label = closeInRangeLabel(closeIn);
  const mode =
    rangeMode === "close_in"
      ? "close_in"
      : rangeMode === "wider_tf" && widerTf
        ? "wider_tf"
        : "full";
  const widerBtn =
    widerTf && (widerTf.start || widerTf.end)
      ? `<button type="button" class="btn chart-toggle${
          mode === "wider_tf" ? " is-active" : ""
        }" data-chart-range="wider_tf">${esc(widerTfRangeLabel(widerTf))}</button>`
      : "";
  return `
    <div class="chart-level-toggle chart-range-toggle" role="group" aria-label="Chart range">
      <button type="button" class="btn chart-toggle${mode === "full" ? " is-active" : ""}" data-chart-range="full">Full history</button>
      <button type="button" class="btn chart-toggle${mode === "close_in" ? " is-active" : ""}" data-chart-range="close_in">${esc(
        label
      )}</button>
      ${widerBtn}
    </div>`;
}

function chartVolumeToggle(showVolume, hasVolume) {
  const active = showVolume ? " is-active" : "";
  const disabled = hasVolume ? "" : " disabled";
  const title = hasVolume
    ? "Show volume bars (observe aid; default off on dual-horizon cards)"
    : "No volume series in chart payload yet";
  return `
    <div class="chart-level-toggle chart-volume-toggle" role="group" aria-label="Volume display">
      <button type="button" class="btn chart-toggle${active}" data-chart-volume="1"${disabled} title="${esc(
        title
      )}" aria-pressed="${showVolume ? "true" : "false"}">Volume</button>
    </div>`;
}

function renderChartBody(payload, report, source, overlays, rangeMode, showVolume) {
  const baseLevels = displayLevelsForSource(payload, source);
  const levels = mergeChartLevels(baseLevels, report, overlays);
  const levelsAsOf = (payload.levels_as_of || payload.as_of || "").slice(0, 10);
  const initialAsOf = (payload.initial_levels_as_of || payload.signal_since || "").slice(0, 10);
  const signalSince = (payload.signal_since || "").slice(0, 10);
  const closeIn = overlays && overlays.close_in ? overlays.close_in : null;
  const widerTf = overlays && overlays.wider_tf ? overlays.wider_tf : null;
  const range =
    rangeMode === "close_in" && closeIn
      ? "close_in"
      : rangeMode === "wider_tf" && widerTf
        ? "wider_tf"
        : "full";
  const warmupDays = Number(
    payload.clip_warmup_calendar_days != null
      ? payload.clip_warmup_calendar_days
      : CLIP_WARMUP_CALENDAR_DAYS
  );
  const clipOpts =
    range === "close_in" || range === "wider_tf"
      ? { warmupCalendarDays: Number.isFinite(warmupDays) ? warmupDays : CLIP_WARMUP_CALENDAR_DAYS }
      : undefined;
  const view =
    range === "close_in"
      ? clipPriceSeries(payload, closeIn, clipOpts)
      : range === "wider_tf"
        ? clipPriceSeries(payload, widerTf, clipOpts)
        : payload;
  const openedAt = (overlays && overlays.opened_at ? String(overlays.opened_at) : "").slice(0, 10);
  const soldAt = (overlays && overlays.sold_at ? String(overlays.sold_at) : "").slice(0, 10);
  const entryPrice =
    overlays && overlays.book_cost != null && !Number.isNaN(Number(overlays.book_cost))
      ? Number(overlays.book_cost)
      : null;
  const exitPrice =
    overlays && overlays.exit_price != null && !Number.isNaN(Number(overlays.exit_price))
      ? Number(overlays.exit_price)
      : null;
  const usingInitial = source === "initial" && payload.initial_levels;
  const planHint = !usingInitial && report.trade_plan?.trade_plan_summary
    ? `<p class="small muted">${esc(report.trade_plan.trade_plan_summary)}</p>`
    : "";
  const smaAsSeries = Boolean(payload.sma50_series || payload.sma200_series);
  const asOfLabel = usingInitial ? initialAsOf : levelsAsOf;
  const tradeLevelsPresent = hasTradePlanLevels(levels);
  const levelsBasis = String(payload.levels_basis || "");
  const currency = payload.currency || "GBP";
  const volumeOn = Boolean(showVolume);
  const chartKey = chartKeyForRangeMode(range, overlays);
  const factoryMarks = filterPatternMarks(
    overlays && Array.isArray(overlays.pattern_marks) ? overlays.pattern_marks : [],
    chartKey
  );
  const humanMarks = filterPatternMarks(
    overlays && Array.isArray(overlays.human_pattern_marks)
      ? overlays.human_pattern_marks
      : [],
    chartKey
  );
  // Compose factory + owner layers; owner marks keep source=owner / tone=owner.
  const patternMarks = factoryMarks.concat(humanMarks);
  let levelsHint = "";
  if (asOfLabel) {
    const basisLine =
      levelsBasis === "prospective"
        ? " Prospective buy / target / stop from current technicals (not yet held)."
        : usingInitial
          ? ` Trade levels frozen at the initial recommendation (${esc(asOfLabel)}). Last is the latest close so you can see what has played out.`
          : ` Trade levels from the latest screen (${esc(levelsAsOf)}).`;
    const fillBits = [];
    if (openedAt) {
      fillBits.push(
        entryPrice != null
          ? `Bought marker ${esc(openedAt)} @ ${esc(formatChartPrice(entryPrice, currency))}`
          : `Bought marker ${esc(openedAt)}`
      );
    }
    if (soldAt) {
      fillBits.push(
        exitPrice != null
          ? `Sold marker ${esc(soldAt)} @ ${esc(formatChartPrice(exitPrice, currency))}`
          : `Sold marker ${esc(soldAt)}`
      );
    }
    levelsHint = `<p class="small muted">${basisLine.trim()}${
      smaAsSeries
        ? " SMA 50 / SMA 200 plot as rolling overlays (not flat point-in-time lines)."
        : " SMA values are point-in-time until the next chart publish adds rolling paths."
    }${
      signalSince ? ` Vertical line marks signal since ${esc(signalSince)}.` : ""
    }${fillBits.length ? ` ${fillBits.join(". ")}.` : ""}</p>`;
  }
  if (!tradeLevelsPresent) {
    levelsHint += `<p class="small muted">No core/tactical buy or target/stop available. ${
      levels.book_cost != null
        ? "Book cost from the paper holding is shown."
        : "Avoid names stay without an entry plan; other screen names get prospective levels on the next chart refresh."
    }</p>`;
  }
  if (factoryMarks.length || humanMarks.length) {
    const bits = [];
    if (factoryMarks.length) bits.push(`factory ${factoryMarks.length}`);
    if (humanMarks.length) bits.push(`owner ${humanMarks.length}`);
    levelsHint += `<p class="small muted">Pattern marks (${bits.join(" + ")}) — Package M alignment only; owner drawings are post-hoc critique, not live knobs.</p>`;
  }
  const hasInitial = Boolean(payload.initial_levels);
  const toggle = `
    <div class="chart-level-toggle" role="group" aria-label="Level source">
      <button type="button" class="btn chart-toggle${source === "current" ? " is-active" : ""}" data-level-source="current">Latest screen</button>
      <button type="button" class="btn chart-toggle${source === "initial" ? " is-active" : ""}" data-level-source="initial"${hasInitial ? "" : " disabled"} title="${
        hasInitial ? "Show levels from the first week of this signal" : "No initial recommendation snapshot yet"
      }">Initial recommendation</button>
    </div>`;
  const chartPayload = {
    ...view,
    _opened_at: openedAt || null,
    _sold_at: soldAt || null,
    _entry_price: entryPrice,
    _exit_price: exitPrice,
    _show_volume: volumeOn,
    _pattern_marks: patternMarks,
  };
  const closeCount = Array.isArray(view.dates) ? view.dates.length : 0;
  const clipRange = range === "wider_tf" ? widerTf : closeIn;
  const band = view.assessment_band || null;
  const assessmentCount =
    band && Array.isArray(view.dates)
      ? view.dates.filter((date) => {
          const day = chartDay(date);
          if (!day) return false;
          if (band.start && day < chartDay(band.start)) return false;
          if (band.end && day > chartDay(band.end)) return false;
          return true;
        }).length
      : closeCount;
  const padNote =
    (range === "close_in" || range === "wider_tf") && clipOpts
      ? ` Includes ~${esc(String(clipOpts.warmupCalendarDays))}d MA warm-up before the band.`
      : "";
  const rangeCaption =
    (range === "close_in" || range === "wider_tf") && clipRange
      ? `<p class="small muted">${range === "wider_tf" ? "Wider TF" : "Episode"} assessment ${esc(
          chartDay(clipRange.start) || "…"
        )} → ${esc(chartDay(clipRange.end) || "latest")}. ${assessmentCount} close${
          assessmentCount === 1 ? "" : "s"
        } in band · ${closeCount} plotted.${padNote}</p>`
      : "";
  const hasVolume = Array.isArray(payload.volumes) && payload.volumes.some((v) => v != null);
  const chartHtml =
    (range === "close_in" || range === "wider_tf") && closeCount === 0
      ? `<p class="muted">No closes in this window yet.</p>`
      : renderPriceChartSvg(chartPayload, levels);
  return `
    <p class="small muted">
      ${esc(view.period || payload.period || "2y")} daily closes · as of ${esc((payload.as_of || "").slice(0, 10) || "—")}
      ${payload.signal ? ` · ${esc(String(payload.signal).replace(/_/g, " "))}` : ""}
      ${payload.market ? ` · ${esc(payload.market)}` : ""}
    </p>
    <div class="chart-toolbar">
      ${chartRangeToggle(range, closeIn, widerTf)}
      ${chartVolumeToggle(volumeOn, hasVolume)}
    </div>
    ${rangeCaption}
    ${toggle}
    ${planHint}
    ${levelsHint}
    ${chartHtml}
    ${levelsTableHtml(levels, { smaAsSeries, currency })}
    ${hasInitial ? crossingsTableHtml(payload.level_crossings || [], currency) : ""}
  `;
}

const priceChartCache = new Map();

function cachedPriceChart(ticker) {
  if (!ticker) return null;
  const hit = priceChartCache.get(String(ticker));
  if (!hit || !Array.isArray(hit.dates) || !hit.dates.length) return null;
  return hit;
}

function rememberPriceChart(ticker, payload) {
  if (!ticker || !payload || !Array.isArray(payload.dates) || !payload.dates.length) return;
  priceChartCache.set(String(ticker), payload);
}

function paintPriceChart(body) {
  const state = body && body._chartState;
  if (!state) return;
  // Preserve parallel edit across full SVG rebuild.
  const priorParallel =
    body._humanDraw && body._humanDraw.parallelEdit
      ? JSON.parse(JSON.stringify(body._humanDraw.parallelEdit))
      : null;
  const priorTool = body._humanDraw ? body._humanDraw.tool : null;
  body.innerHTML = renderChartBody(
    state.payload,
    state.report || {},
    state.levelSource,
    state.overlays || {},
    state.rangeMode,
    state.showVolume
  );
  body._plotMetrics = computePriceChartPlotMetrics(state);
  if (body._humanDraw && body._humanDraw.enabled) {
    if (priorParallel) body._humanDraw.parallelEdit = priorParallel;
    if (priorTool) body._humanDraw.tool = priorTool;
    bindHumanChartDraw(body);
    if (priorTool === "parallel" && priorParallel) {
      paintParallelEditOverlay(body);
    }
  }
}

function bindPriceChartBody(body) {
  if (!body || body.dataset.levelToggleBound) return;
  body.dataset.levelToggleBound = "1";
  body.addEventListener("click", (event) => {
    const state = body._chartState;
    if (!state) return;
    const levelButton = event.target.closest("[data-level-source]");
    if (levelButton && !levelButton.disabled && body.contains(levelButton)) {
      event.preventDefault();
      state.levelSource = levelButton.dataset.levelSource || "current";
      paintPriceChart(body);
      return;
    }
    const volumeButton = event.target.closest("[data-chart-volume]");
    if (volumeButton && !volumeButton.disabled && body.contains(volumeButton)) {
      event.preventDefault();
      state.showVolume = !state.showVolume;
      paintPriceChart(body);
      return;
    }
    const rangeButton = event.target.closest("[data-chart-range]");
    if (!rangeButton || rangeButton.disabled || !body.contains(rangeButton)) return;
    event.preventDefault();
    state.rangeMode = rangeButton.dataset.chartRange || "full";
    paintPriceChart(body);
  });
}

function showPriceChart(body, payload, report, overlays, rangeMode) {
  if (!body) return;
  body._chartState = {
    payload,
    report: report || {},
    overlays: overlays || {},
    levelSource: "current",
    rangeMode: rangeMode || "full",
    // Volume stays in payload for LLM/autopsy; UI default off (iPad dual-horizon).
    showVolume: false,
  };
  bindPriceChartBody(body);
  paintPriceChart(body);
}

async function mountPriceChart(body, report, overlays, rangeMode) {
  if (!body) return;
  const path = chartPathForReport(report);
  body.innerHTML = "<p class='muted'>Loading chart…</p>";
  if (!path) {
    body.innerHTML = `<p class="muted">No chart path for this recommendation.</p>`;
    return;
  }

  try {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    rememberPriceChart(report && report.ticker, payload);
    const startMode =
      rangeMode ||
      (overlays && overlays.wider_tf ? "wider_tf" : "full");
    showPriceChart(body, payload, report, overlays, startMode);
  } catch (err) {
    body.innerHTML = `
      <p class="muted">Could not load price chart (${esc(err.message)}).</p>
      <p class="small muted">Charts are published for live-screen and lifecycle board names on dashboard update.</p>`;
  }
}

/** Post-sale review cards: episode + wider TF side by side (neither hidden). */
async function mountDualHorizonCharts(episodeBody, widerBody, report, overlays) {
  const path = chartPathForReport(report);
  const load = async (body, mode) => {
    if (!body) return;
    body.innerHTML = "<p class='muted'>Loading chart…</p>";
    if (!path) {
      body.innerHTML = `<p class="muted">No chart path for this ticker.</p>`;
      return;
    }
    try {
      const response = await fetch(path);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      rememberPriceChart(report && report.ticker, payload);
      showPriceChart(body, payload, report, overlays || {}, mode);
    } catch (err) {
      body.innerHTML = `<p class="muted">Could not load chart (${esc(err.message)}).</p>`;
    }
  };
  await Promise.all([load(episodeBody, "close_in"), load(widerBody, "wider_tf")]);
}

function openCachedPriceChart(ticker, overlays) {
  const payload = cachedPriceChart(ticker);
  if (!payload) return false;
  const dialog = ensureChartDialog();
  const title = document.getElementById("chart-title");
  const body = document.getElementById("chart-body");
  if (!dialog || !title || !body) return false;
  title.textContent = String(ticker || "");
  dialog.showModal();
  showPriceChart(body, payload, { ticker }, overlays || {}, "close_in");
  return true;
}

async function openPriceChart(report) {
  const dialog = ensureChartDialog();
  const title = document.getElementById("chart-title");
  const body = document.getElementById("chart-body");
  title.textContent = `${report.name || report.ticker} (${report.ticker})`;
  dialog.showModal();
  await mountPriceChart(body, report);
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
  return `<div class="small held-vs-market-spark-caption">
    <div>Held ${esc(formatHeldMoney(last.held, currency))}${marketHtml}${excessHtml}</div>
    <div class="muted" title="Sleeve MTM vs frictionless local price index from the same start — not fair book excess after costs or Learning-tracks beat_market">Sleeve vs price index (not fair book excess)</div>
  </div>`;
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

/** N229 — human post-hoc geometry draw helpers (iPad-first). */

function humanGeometryElementsToMarks(geometries, chartKey) {
  if (!Array.isArray(geometries) || !geometries.length) return [];
  const marks = [];
  for (const geo of geometries) {
    if (!geo || typeof geo !== "object" || geo.readable === false) continue;
    const chart = String(geo.chart || chartKey || "");
    if (chartKey && chart && chart !== chartKey && !(chartKey === "pit" && chart === "episode")) {
      // Keep when no filter key, else match chart binding.
      if (chartKey !== "full") continue;
    }
    const gid = String(geo.geometry_id || "draft");
    (geo.elements || []).forEach((el, index) => {
      if (!el || typeof el !== "object") return;
      const etype = String(el.type || "");
      const mid = `owner:${gid}:${index}`;
      if (etype === "highlight") {
        marks.push({
          id: mid,
          pattern: "owner_highlight",
          type: "region",
          charts: [chart || chartKey || "episode"],
          label: "Owner highlight",
          tone: "owner",
          cite: "post_hoc_human_geometry",
          t0: el.t0,
          t1: el.t1,
          source: "owner",
          post_hoc: true,
          influences_live: false,
        });
      } else if (etype === "line") {
        marks.push({
          id: mid,
          pattern: "owner_line",
          type: "trend_line",
          charts: [chart || chartKey || "episode"],
          label: "Owner line",
          tone: "owner",
          cite: "post_hoc_human_geometry",
          t0: el.t0,
          t1: el.t1,
          y0: el.y0,
          y1: el.y1,
          source: "owner",
          post_hoc: true,
          influences_live: false,
        });
      } else if (etype === "parallel_pair") {
        ["line_a", "line_b"].forEach((key, pi) => {
          const line = el[key];
          if (!line || typeof line !== "object") return;
          marks.push({
            id: `${mid}:${key}`,
            pattern: "owner_parallel",
            type: "trend_line",
            charts: [chart || chartKey || "episode"],
            label: pi === 0 ? "Owner parallel a" : "Owner parallel b",
            tone: "owner",
            cite: "post_hoc_human_geometry",
            t0: line.t0,
            t1: line.t1,
            y0: line.y0,
            y1: line.y1,
            source: "owner",
            post_hoc: true,
            influences_live: false,
          });
        });
      }
    });
  }
  return marks;
}

function computePriceChartPlotMetrics(state) {
  if (!state || !state.payload) return null;
  const overlays = state.overlays || {};
  const payload = state.payload;
  const closeIn = overlays.close_in || null;
  const widerTf = overlays.wider_tf || null;
  const rangeMode = state.rangeMode || "full";
  const range =
    rangeMode === "close_in" && closeIn
      ? "close_in"
      : rangeMode === "wider_tf" && widerTf
        ? "wider_tf"
        : "full";
  const warmupDays = Number(
    payload.clip_warmup_calendar_days != null
      ? payload.clip_warmup_calendar_days
      : CLIP_WARMUP_CALENDAR_DAYS
  );
  const clipOpts =
    range === "close_in" || range === "wider_tf"
      ? { warmupCalendarDays: Number.isFinite(warmupDays) ? warmupDays : CLIP_WARMUP_CALENDAR_DAYS }
      : undefined;
  const view =
    range === "close_in"
      ? clipPriceSeries(payload, closeIn, clipOpts)
      : range === "wider_tf"
        ? clipPriceSeries(payload, widerTf, clipOpts)
        : payload;
  const dates = Array.isArray(view.dates) ? view.dates : [];
  const closes = Array.isArray(view.closes) ? view.closes : [];
  if (!dates.length || dates.length !== closes.length) return null;

  const patternCount = (
    (overlays.pattern_marks || []).length + (overlays.human_pattern_marks || []).length
  );
  const topPad = 28 + Math.min(36, patternCount * 6);
  const showVolume = Boolean(state.showVolume);
  const volPane = showVolume ? 72 : 0;
  const rightPad = 168;
  const width = 620 + rightPad;
  const height = 380 + volPane + (topPad - 28);
  const pad = { top: topPad, right: rightPad, bottom: 42 + volPane, left: 22 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  pad.plotH = plotH;
  pad.plotW = plotW;
  const minClose = Math.min(...closes.map(Number).filter((v) => !Number.isNaN(v)));
  const maxClose = Math.max(...closes.map(Number).filter((v) => !Number.isNaN(v)));
  if (!Number.isFinite(minClose) || !Number.isFinite(maxClose)) return null;
  const minY = minClose * 0.98;
  const maxY = maxClose * 1.02;
  const spanY = maxY - minY || 1;
  const xAt = (index) => pad.left + (index / Math.max(dates.length - 1, 1)) * plotW;
  const yAt = (value) => pad.top + plotH - ((value - minY) / spanY) * plotH;
  const chartKey = chartKeyForRangeMode(range, overlays);
  return {
    dates,
    closes,
    pad,
    width,
    height,
    minY,
    maxY,
    spanY,
    xAt,
    yAt,
    chartKey,
    range,
  };
}

function chartClientToData(body, clientX, clientY) {
  const metrics = body && body._plotMetrics;
  const svg = body && body.querySelector("svg.price-chart");
  if (!metrics || !svg || !metrics.dates.length) return null;
  const rect = svg.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const vbX = ((clientX - rect.left) / rect.width) * metrics.width;
  const vbY = ((clientY - rect.top) / rect.height) * metrics.height;
  const { pad, dates, minY, spanY, plotW, plotH } = {
    pad: metrics.pad,
    dates: metrics.dates,
    minY: metrics.minY,
    spanY: metrics.spanY,
    plotW: metrics.pad.plotW,
    plotH: metrics.pad.plotH,
  };
  if (vbX < pad.left || vbX > pad.left + plotW || vbY < pad.top || vbY > pad.top + plotH) {
    return null;
  }
  const frac = (vbX - pad.left) / Math.max(plotW, 1);
  const index = Math.max(
    0,
    Math.min(dates.length - 1, Math.round(frac * Math.max(dates.length - 1, 1)))
  );
  const price = minY + ((pad.top + plotH - vbY) / Math.max(plotH, 1)) * spanY;
  return {
    index,
    t: chartDay(dates[index]),
    y: Number(price.toFixed(4)),
    vbX,
    vbY,
  };
}

function enableHumanChartDraw(body, options) {
  if (!body) return;
  const opts = options && typeof options === "object" ? options : {};
  const prior = body._humanDraw || {};
  body._humanDraw = {
    enabled: true,
    chartKey: String(opts.chartKey || prior.chartKey || "episode"),
    reviewId: String(opts.reviewId || prior.reviewId || ""),
    tool: prior.tool || null,
    pending: Array.isArray(prior.pending) ? prior.pending : [],
    parallelEdit: prior.parallelEdit || null,
    onChange: typeof opts.onChange === "function" ? opts.onChange : prior.onChange || null,
    getElements: typeof opts.getElements === "function" ? opts.getElements : prior.getElements || (() => []),
  };
  if (body._chartState) paintPriceChart(body);
}

function setHumanChartDrawTool(body, tool) {
  if (!body || !body._humanDraw) return;
  const draw = body._humanDraw;
  // Switching away from parallel with an unfinished edit commits if valid.
  if (draw.tool === "parallel" && tool !== "parallel" && draw.parallelEdit) {
    commitParallelEdit(body, { quiet: true });
  }
  draw.tool = tool || null;
  draw.pending = [];
  if (tool !== "parallel") draw.parallelEdit = null;
  const status = body.parentElement && body.parentElement.querySelector("[data-human-draw-status]");
  if (status) {
    if (tool === "parallel") {
      status.textContent = "Parallel: drag primary start→end, then drag 3 anchors";
    } else if (tool) {
      status.textContent = `Draw: ${tool} — tap chart (iPad)`;
    } else {
      status.textContent = "Draw off";
    }
  }
  syncParallelDoneButton(body);
  if (tool === "parallel") {
    // Ensure overlay layer exists after tool select.
    const svg = body.querySelector("svg.price-chart");
    if (svg) ensureParallelEditLayer(svg);
  } else {
    clearParallelEditLayer(body);
  }
}

function parallelElementFromAnchors(start, end, sep) {
  if (!start || !end || !sep || !start.t || !end.t || !sep.t) return null;
  if (start.y == null || end.y == null || sep.y == null) return null;
  const t0 = start.t;
  const t1 = end.t;
  const y0 = Number(start.y);
  const y1 = Number(end.y);
  const ys = Number(sep.y);
  if (!Number.isFinite(y0) || !Number.isFinite(y1) || !Number.isFinite(ys)) return null;
  if (t0 === t1 && y0 === y1) return null;
  let yOnPrimary = y0;
  if (t0 !== t1) {
    if (sep.t <= t0) yOnPrimary = y0;
    else if (sep.t >= t1) yOnPrimary = y1;
    else {
      // Approximate fraction by vbX when available, else midpoint.
      if (
        start.vbX != null &&
        end.vbX != null &&
        sep.vbX != null &&
        end.vbX !== start.vbX
      ) {
        const frac = (sep.vbX - start.vbX) / (end.vbX - start.vbX);
        yOnPrimary = y0 + (y1 - y0) * Math.max(0, Math.min(1, frac));
      } else {
        yOnPrimary = (y0 + y1) / 2;
      }
    }
  }
  const separation = ys - yOnPrimary;
  return {
    type: "parallel_pair",
    anchors: {
      start: { t: t0, y: y0 },
      end: { t: t1, y: y1 },
      separation: { t: sep.t, y: ys },
    },
    separation,
    line_a: { t0, y0, t1, y1 },
    line_b: { t0, y0: y0 + separation, t1, y1: y1 + separation },
  };
}

function clearParallelEditLayer(body) {
  const svg = body && body.querySelector("svg.price-chart");
  if (!svg) return;
  const layer = svg.querySelector("g.chart-human-parallel-edit");
  if (layer) layer.remove();
}

function ensureParallelEditLayer(svg) {
  let layer = svg.querySelector("g.chart-human-parallel-edit");
  if (layer) return layer;
  layer = document.createElementNS("http://www.w3.org/2000/svg", "g");
  layer.setAttribute("class", "chart-human-parallel-edit");
  layer.innerHTML = `
    <line class="psr-par-line-a" stroke="#6d28d9" stroke-width="2" stroke-opacity="0.95" />
    <line class="psr-par-line-b" stroke="#7c3aed" stroke-width="2" stroke-dasharray="5 4" stroke-opacity="0.9" />
    <circle class="psr-par-anchor" data-anchor="start" r="11" fill="#6d28d9" stroke="#fff" stroke-width="2" />
    <circle class="psr-par-anchor" data-anchor="end" r="11" fill="#6d28d9" stroke="#fff" stroke-width="2" />
    <circle class="psr-par-anchor" data-anchor="separation" r="11" fill="#a855f7" stroke="#fff" stroke-width="2" />
  `;
  svg.appendChild(layer);
  return layer;
}

function dataPointToVb(body, point) {
  const metrics = body && body._plotMetrics;
  if (!metrics || !point || !point.t) return null;
  const idx = dateIndexOnOrBefore(metrics.dates, point.t);
  if (idx < 0) return null;
  return { vbX: metrics.xAt(idx), vbY: metrics.yAt(Number(point.y)) };
}

function ensureParallelSeparationAnchor(body, edit, startVb, endVb) {
  if (!edit || edit.sep || !body || !body._plotMetrics) return;
  const metrics = body._plotMetrics;
  const defaultSepPx = Math.max(
    18,
    (metrics.pad && metrics.pad.plotH ? metrics.pad.plotH : 200) * 0.08
  );
  const spanY = metrics.spanY || 1;
  const sepPrice =
    Number(edit.start.y) +
    (Number(edit.end.y) - Number(edit.start.y)) * 0.5 -
    (defaultSepPx / Math.max(metrics.pad.plotH, 1)) * spanY;
  const midIdx = Math.round(
    ((edit.start.index != null ? edit.start.index : 0) +
      (edit.end.index != null ? edit.end.index : 0)) /
      2
  );
  const midT =
    chartDay(metrics.dates[Math.max(0, Math.min(metrics.dates.length - 1, midIdx))]) ||
    edit.start.t;
  const midX = (startVb.vbX + endVb.vbX) / 2;
  edit.sep = {
    t: midT,
    y: Number(sepPrice.toFixed(4)),
    index: midIdx,
    vbX: midX,
    vbY: metrics.yAt(sepPrice),
  };
}

function paintParallelEditOverlay(body) {
  const draw = body && body._humanDraw;
  const edit = draw && draw.parallelEdit;
  const svg = body && body.querySelector("svg.price-chart");
  if (!edit || !svg || !edit.start || !edit.end) {
    clearParallelEditLayer(body);
    return;
  }
  const layer = ensureParallelEditLayer(svg);
  const startVb = dataPointToVb(body, edit.start) || { vbX: edit.start.vbX, vbY: edit.start.vbY };
  const endVb = dataPointToVb(body, edit.end) || { vbX: edit.end.vbX, vbY: edit.end.vbY };
  if (!startVb || !endVb || startVb.vbX == null || endVb.vbX == null) return;
  edit.start.vbX = startVb.vbX;
  edit.start.vbY = startVb.vbY;
  edit.end.vbX = endVb.vbX;
  edit.end.vbY = endVb.vbY;
  if (edit.phase === "editing" && !edit.sep) {
    ensureParallelSeparationAnchor(body, edit, startVb, endVb);
  }
  if (edit.sep) {
    const sepVb = dataPointToVb(body, edit.sep);
    if (sepVb) {
      edit.sep.vbX = sepVb.vbX;
      edit.sep.vbY = sepVb.vbY;
    }
  }
  const el = edit.sep ? parallelElementFromAnchors(edit.start, edit.end, edit.sep) : null;
  const a = el ? el.line_a : { t0: edit.start.t, y0: edit.start.y, t1: edit.end.t, y1: edit.end.y };
  const b = el ? el.line_b : null;
  const lineA = layer.querySelector(".psr-par-line-a");
  const lineB = layer.querySelector(".psr-par-line-b");
  if (lineA && a) {
    const a0 = dataPointToVb(body, { t: a.t0, y: a.y0 }) || startVb;
    const a1 = dataPointToVb(body, { t: a.t1, y: a.y1 }) || endVb;
    if (a0 && a1) {
      lineA.setAttribute("x1", a0.vbX);
      lineA.setAttribute("y1", a0.vbY);
      lineA.setAttribute("x2", a1.vbX);
      lineA.setAttribute("y2", a1.vbY);
    }
  }
  if (lineB && b) {
    lineB.style.display = "";
    const b0 = dataPointToVb(body, { t: b.t0, y: b.y0 });
    const b1 = dataPointToVb(body, { t: b.t1, y: b.y1 });
    if (b0 && b1) {
      lineB.setAttribute("x1", b0.vbX);
      lineB.setAttribute("y1", b0.vbY);
      lineB.setAttribute("x2", b1.vbX);
      lineB.setAttribute("y2", b1.vbY);
    }
  } else if (lineB) {
    lineB.style.display = "none";
  }
  const setAnchor = (name, pt) => {
    const node = layer.querySelector(`[data-anchor="${name}"]`);
    if (!node) return;
    if (!pt || pt.vbX == null) {
      node.style.display = "none";
      return;
    }
    node.style.display = "";
    node.setAttribute("cx", pt.vbX);
    node.setAttribute("cy", pt.vbY);
  };
  setAnchor("start", edit.start);
  setAnchor("end", edit.end);
  setAnchor("separation", edit.sep);
  syncParallelDoneButton(body);
}

function syncParallelDoneButton(body) {
  const toolbar =
    body &&
    body.parentElement &&
    body.parentElement.querySelector("[data-human-draw-toolbar]");
  if (!toolbar) return;
  let done = toolbar.querySelector("[data-human-draw-tool='parallel-done']");
  const draw = body._humanDraw;
  const editing = draw && draw.tool === "parallel" && draw.parallelEdit && draw.parallelEdit.sep;
  if (editing) {
    if (!done) {
      done = document.createElement("button");
      done.type = "button";
      done.className = "btn psr-draw-tool psr-draw-done";
      done.setAttribute("data-human-draw-tool", "parallel-done");
      done.setAttribute("data-psr-draw-rid", draw.reviewId);
      done.setAttribute("data-psr-draw-chart", draw.chartKey);
      done.setAttribute("data-ebr-draw-rid", draw.reviewId);
      done.setAttribute("data-ebr-draw-chart", draw.chartKey);
      done.textContent = "Done";
      done.title = "Lock parallel with 3 anchors";
      const tools = toolbar.querySelector(".psr-human-draw-tools");
      if (tools) tools.appendChild(done);
    }
    done.hidden = false;
  } else if (done) {
    done.hidden = true;
  }
}

function commitParallelEdit(body, { quiet } = {}) {
  const draw = body && body._humanDraw;
  if (!draw || !draw.parallelEdit) return false;
  const edit = draw.parallelEdit;
  const element = parallelElementFromAnchors(edit.start, edit.end, edit.sep);
  draw.parallelEdit = null;
  draw.pending = [];
  clearParallelEditLayer(body);
  syncParallelDoneButton(body);
  if (!element) {
    if (!quiet) {
      const status =
        body.parentElement && body.parentElement.querySelector("[data-human-draw-status]");
      if (status) status.textContent = "Parallel unread — need 3 valid anchors";
    }
    return false;
  }
  if (draw.onChange) {
    draw.onChange({ chartKey: draw.chartKey, element, reviewId: draw.reviewId });
  }
  return true;
}

function hitParallelAnchor(body, clientX, clientY) {
  const draw = body && body._humanDraw;
  const edit = draw && draw.parallelEdit;
  const svg = body && body.querySelector("svg.price-chart");
  if (!edit || !svg || !edit.sep) return null;
  const rect = svg.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const metrics = body._plotMetrics;
  const vbX = ((clientX - rect.left) / rect.width) * metrics.width;
  const vbY = ((clientY - rect.top) / rect.height) * metrics.height;
  const hitR = 18;
  const candidates = [
    ["start", edit.start],
    ["end", edit.end],
    ["separation", edit.sep],
  ];
  let best = null;
  let bestDist = hitR;
  for (const [name, pt] of candidates) {
    if (!pt || pt.vbX == null) continue;
    const d = Math.hypot(pt.vbX - vbX, pt.vbY - vbY);
    if (d <= bestDist) {
      bestDist = d;
      best = name;
    }
  }
  return best;
}

function bindHumanChartDraw(body) {
  const draw = body && body._humanDraw;
  if (!draw || !draw.enabled) return;
  const svg = body.querySelector("svg.price-chart");
  if (!svg || svg.dataset.humanDrawBound === "1") return;
  svg.dataset.humanDrawBound = "1";
  svg.classList.add("chart-human-draw-enabled");

  // Restore overlay after repaint if an edit session is live.
  if (draw.tool === "parallel" && draw.parallelEdit) {
    paintParallelEditOverlay(body);
  }

  let dragAnchor = null;
  let placingPrimary = false;

  const onPointerDown = (event) => {
    if (!draw.tool) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const tool = draw.tool;
    if (tool === "parallel") {
      event.preventDefault();
      event.stopPropagation();
      // Drag existing anchors when editing.
      if (draw.parallelEdit && draw.parallelEdit.sep) {
        const hit = hitParallelAnchor(body, event.clientX, event.clientY);
        if (hit) {
          dragAnchor = hit;
          try {
            svg.setPointerCapture(event.pointerId);
          } catch {
            /* ignore */
          }
          return;
        }
      }
      // Start placing primary (drag start→end).
      const point = chartClientToData(body, event.clientX, event.clientY);
      if (!point || !point.t) return;
      placingPrimary = true;
      dragAnchor = null;
      draw.parallelEdit = {
        start: { ...point },
        end: { ...point },
        sep: null,
        phase: "placing",
      };
      paintParallelEditOverlay(body);
      try {
        svg.setPointerCapture(event.pointerId);
      } catch {
        /* ignore */
      }
      const status =
        body.parentElement && body.parentElement.querySelector("[data-human-draw-status]");
      if (status) status.textContent = "Parallel: drag to set primary end";
      return;
    }

    const point = chartClientToData(body, event.clientX, event.clientY);
    if (!point || !point.t) return;
    event.preventDefault();
    event.stopPropagation();
    draw.pending.push(point);
    const finish = (element) => {
      draw.pending = [];
      if (draw.onChange) draw.onChange({ chartKey: draw.chartKey, element, reviewId: draw.reviewId });
    };
    if (tool === "highlight") {
      if (draw.pending.length >= 2) {
        const a = draw.pending[0];
        const b = draw.pending[1];
        let t0 = a.t;
        let t1 = b.t;
        if (t1 < t0) {
          const tmp = t0;
          t0 = t1;
          t1 = tmp;
        }
        finish({ type: "highlight", t0, t1, y0: null, y1: null });
      }
      return;
    }
    if (tool === "hline") {
      const p = draw.pending[0];
      const dates = (body._plotMetrics && body._plotMetrics.dates) || [];
      const t0 = chartDay(dates[0]) || p.t;
      const t1 = chartDay(dates[dates.length - 1]) || p.t;
      finish({ type: "line", t0, y0: p.y, t1, y1: p.y });
      return;
    }
    if (tool === "line") {
      if (draw.pending.length >= 2) {
        const a = draw.pending[0];
        const b = draw.pending[1];
        finish({ type: "line", t0: a.t, y0: a.y, t1: b.t, y1: b.y });
      }
    }
  };

  const onPointerMove = (event) => {
    if (draw.tool !== "parallel" || !draw.parallelEdit) return;
    const point = chartClientToData(body, event.clientX, event.clientY);
    if (!point || !point.t) return;
    event.preventDefault();
    if (placingPrimary) {
      draw.parallelEdit.end = { ...point };
      paintParallelEditOverlay(body);
      return;
    }
    if (dragAnchor === "start") {
      draw.parallelEdit.start = { ...point };
      paintParallelEditOverlay(body);
    } else if (dragAnchor === "end") {
      draw.parallelEdit.end = { ...point };
      paintParallelEditOverlay(body);
    } else if (dragAnchor === "separation") {
      draw.parallelEdit.sep = { ...point };
      paintParallelEditOverlay(body);
    }
  };

  const onPointerUp = (event) => {
    if (draw.tool !== "parallel" || !draw.parallelEdit) {
      placingPrimary = false;
      dragAnchor = null;
      return;
    }
    event.preventDefault();
    if (placingPrimary) {
      placingPrimary = false;
      draw.parallelEdit.phase = "editing";
      ensureParallelSeparationAnchor(
        body,
        draw.parallelEdit,
        { vbX: draw.parallelEdit.start.vbX, vbY: draw.parallelEdit.start.vbY },
        { vbX: draw.parallelEdit.end.vbX, vbY: draw.parallelEdit.end.vbY }
      );
      paintParallelEditOverlay(body);
      const status =
        body.parentElement && body.parentElement.querySelector("[data-human-draw-status]");
      if (status) {
        status.textContent =
          "Parallel: drag 3 anchors (start / end / separation) · Done to lock";
      }
      dragAnchor = null;
      return;
    }
    dragAnchor = null;
  };

  svg.addEventListener("pointerdown", onPointerDown, { passive: false });
  svg.addEventListener("pointermove", onPointerMove, { passive: false });
  svg.addEventListener("pointerup", onPointerUp, { passive: false });
  svg.addEventListener("pointercancel", onPointerUp, { passive: false });
}
