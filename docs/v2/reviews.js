/* Strategy dashboard v2 — Reviews tab (WP6).
 * Closed strategy-book episodes from strategy_book_review_queue.json.
 * Entry-blind and buy+28d stay on the legacy lab queues; this tab does not load them.
 * Observe-only. influences_live is displayed from the store and this page does not write.
 */
(function () {
  "use strict";

  const QUEUE_PATH = "../data/strategy_book_review_queue.json";
  const NOTES_PATH = "../data/strategy_book_post_sale_notes.json";
  const PAGE_SIZE = 12;
  const NOT_MEASURED = "not yet measured";
  const INSUFFICIENT = "insufficient data";

  const COLUMN_LABELS = {
    primary: "Strategy book",
    buy_on_signal: "Buy on the signal",
    draft_v0_exit: "First-draft exit",
    ladder_no_deadline: "Floor without the 63-session wait",
    leave_tier: "Leave the buy tier",
    alternative: "Alternative exit",
    decline_rejected_shadow: "Refused for operating decline",
    sector_rejected_shadow: "Refused for a sector headwind",
    deep_dip: "Deep dip",
    revenue_growing: "Revenue growing",
    fcf_agrees: "Free cash flow agrees",
    trend_not_falling: "Trend not falling",
  };

  const ROLE_LABELS = {
    primary: "Book",
    control: "Control",
    comparison: "Comparison",
    shadow: "Shadow",
    bench: "Challenger",
  };

  const EXIT_LABELS = {
    floor_exit: "Floor exit",
    fail_to_launch: "Sold at the 63-session wait",
    thesis_break: "Thesis break",
    ineligible_runs: "Left the buy tier",
    time_cap: "Time cap",
    hold_63: "Held 63 sessions",
    recovery_target: "Recovery target",
    review_cap: "Review cap",
    review_insufficient: "Review with insufficient data",
    swing_high: "Swing high",
    delisted: "Delisted",
  };

  const CAUSE_LABELS = {
    thesis_break: "Thesis break",
    gate_miss: "Gate miss",
    entry_timing: "Entry timing",
    market_drift: "Market drift",
    exit_rule: "Exit rule",
    insufficient_data: INSUFFICIENT,
  };

  const LEVER_LABELS = {
    stock_choice: "Stock choice",
    buy_timing: "Buy timing",
    buy_strategy: "Buy strategy",
    sell_timing: "Sell timing",
    sell_strategy: "Sell strategy",
  };

  const state = {
    expanded: Object.create(null),
    charts: Object.create(null),
    primaryLimit: PAGE_SIZE,
    companionLimit: PAGE_SIZE,
  };

  let viewCache = null;

  function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function num(value) {
    if (value == null || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function labelOf(map, key) {
    const id = String(key || "");
    if (!id) return INSUFFICIENT;
    if (Object.prototype.hasOwnProperty.call(map, id)) return map[id];
    return id.replace(/_/g, " ");
  }

  function pctText(pct, fraction) {
    const direct = num(pct);
    const fromFraction = direct == null && num(fraction) != null ? num(fraction) * 100 : null;
    const n = direct != null ? direct : fromFraction;
    if (n == null) return INSUFFICIENT;
    const body = Math.abs(n).toFixed(2) + "%";
    if (n < 0) return "−" + body;
    if (n > 0) return "+" + body;
    return body;
  }

  function helpedText(value) {
    const key = String(value || "");
    if (key === "yes") return "Would have helped";
    if (key === "no") return "Would not have helped";
    if (key === "insufficient_data") return INSUFFICIENT;
    return INSUFFICIENT;
  }

  function countField(counts, key) {
    if (!isObject(counts) || !(key in counts)) return null;
    return num(counts[key]);
  }

  function countText(value) {
    return value == null ? NOT_MEASURED : String(Math.round(value));
  }

  function slotQueue(ctx) {
    const row = ctx && ctx.data && ctx.data.strategy_book_review;
    if (!row || row.ok !== true || !isObject(row.data)) return null;
    return row.data;
  }

  function notesIndex(ctx) {
    const row = ctx && ctx.data && ctx.data.strategy_book_post_sale_notes;
    if (!row || row.ok !== true || !isObject(row.data)) return null;
    const list = Array.isArray(row.data.notes) ? row.data.notes : [];
    const map = Object.create(null);
    list.forEach(function (note) {
      if (!isObject(note)) return;
      const id = String(note.episode_id || note.note_id || "");
      if (id) map[id] = note;
    });
    const counts = isObject(row.data.counts) ? row.data.counts : {};
    return {
      present: true,
      map: map,
      influencesLive: row.data.influences_live === true,
      grounded: countField(counts, "grounded"),
      failClosed: countField(counts, "fail_closed"),
    };
  }

  function learningHtml(helpers, notes, row) {
    if (row.attention !== "primary") return "";
    if (!notes) {
      return '<p class="v2-rev-learn">Learning point: ' + helpers.esc(NOT_MEASURED) + ".</p>";
    }
    const note = notes.map[row.id];
    if (!note) {
      return '<p class="v2-rev-learn">Learning point: ' + helpers.esc(NOT_MEASURED) + ".</p>";
    }
    const text = note.learning_point ? String(note.learning_point) : "";
    if (note.learning_point_status !== "grounded" || !text) {
      const missing = Array.isArray(note.missing_inputs) ? note.missing_inputs.filter(Boolean) : [];
      const gap = missing.length ? " Missing inputs: " + missing.join(", ") + "." : "";
      return '<p class="v2-rev-learn">Learning point withheld.' + helpers.esc(gap) + "</p>";
    }
    return '<p class="v2-rev-learn"><strong>Learning point.</strong> ' + helpers.esc(text) + "</p>";
  }

  function slimRow(row) {
    if (!isObject(row)) return null;
    const attribution = isObject(row.attribution) ? row.attribution : {};
    const levers = Array.isArray(row.levers) ? row.levers : [];
    const hindsight = Array.isArray(row.hindsight) ? row.hindsight.length : 0;
    const cited = Array.isArray(row.cited_inputs) ? row.cited_inputs.length : 0;
    return {
      id: String(row.review_id || row.episode_id || ""),
      ticker: row.ticker ? String(row.ticker) : "",
      market: row.market ? String(row.market) : "",
      column: row.column ? String(row.column) : "",
      columnLabel: labelOf(COLUMN_LABELS, row.column),
      role: row.column_role ? String(row.column_role) : "",
      roleLabel: labelOf(ROLE_LABELS, row.column_role),
      attention: row.attention ? String(row.attention) : "",
      signalSession: row.signal_session ? String(row.signal_session).slice(0, 10) : "",
      fillSession: row.fill_session ? String(row.fill_session).slice(0, 10) : "",
      exitSession: row.exit_session ? String(row.exit_session).slice(0, 10) : "",
      exitLabel: labelOf(EXIT_LABELS, row.exit_reason),
      fairCostText: pctText(row.fair_cost_return_pct, row.fair_cost_return),
      excessText: pctText(row.matched_excess_pct, row.matched_excess),
      cause: attribution.label ? String(attribution.label) : "",
      causeLabel: labelOf(CAUSE_LABELS, attribution.label),
      causeBecause: attribution.because ? String(attribution.because).replace(/_/g, " ") : "",
      countsAsEvidence: attribution.counts_as_evidence === true,
      provenanceMissing: row.provenance_missing === true,
      evidenceStatus: row.evidence_status ? String(row.evidence_status) : "",
      influencesLive: row.influences_live === true,
      memoVerdict: row.memo_verdict ? String(row.memo_verdict) : "",
      hindsight: hindsight,
      cited: cited,
      levers: levers.map(function (lever) {
        if (!isObject(lever)) return null;
        return {
          id: lever.id ? String(lever.id) : "",
          label: labelOf(LEVER_LABELS, lever.id),
          helped: helpedText(lever.would_have_helped),
          because: lever.because ? String(lever.because).replace(/_/g, " ") : "",
        };
      }).filter(Boolean),
    };
  }

  function reviewView(queue) {
    if (!isObject(queue)) {
      return {
        present: false,
        generatedAt: null,
        scoringDate: null,
        influencesLive: false,
        counts: {
          episodes: null,
          closed: null,
          primary: null,
          companion: null,
          active: null,
          openSkipped: null,
          provenanceMissing: null,
          missing: null,
        },
        primary: [],
        companion: [],
      };
    }
    const counts = isObject(queue.counts) ? queue.counts : {};
    const primary = (Array.isArray(queue.active) ? queue.active : []).map(slimRow).filter(Boolean);
    const companion = (Array.isArray(queue.companion) ? queue.companion : []).map(slimRow).filter(Boolean);
    return {
      present: true,
      generatedAt: queue.generated_at || null,
      scoringDate: queue.scoring_date || null,
      influencesLive: queue.influences_live === true,
      observeOnly: queue.observe_only !== false,
      counts: {
        episodes: countField(counts, "episodes"),
        closed: countField(counts, "closed"),
        primary: countField(counts, "primary"),
        companion: countField(counts, "companion"),
        active: countField(counts, "active"),
        openSkipped: countField(counts, "open_skipped"),
        provenanceMissing: countField(counts, "provenance_missing"),
        missing: countField(counts, "missing"),
      },
      primary: primary,
      companion: companion,
    };
  }

  function metaHtml(helpers, iso, rule, caption) {
    const ms = helpers.parseIsoMs(iso);
    const age = ms == null ? null : helpers.nowMs() - ms;
    const badge = rule === "daily"
      ? helpers.freshnessDailyStore(age)
      : helpers.freshnessChartBar(age);
    const shown = iso ? helpers.displayDate(iso) : "not yet available";
    return '<p class="v2-panel-meta">' + helpers.esc(caption) + " " + helpers.esc(shown)
      + ' <span class="v2-muted">age ' + helpers.esc(helpers.ageLabelFromMs(age)) + "</span> "
      + '<span class="' + helpers.esc(badge.cls) + '">' + helpers.esc(badge.label) + "</span></p>";
  }

  function stat(helpers, label, value) {
    return '<div class="v2-rev-stat"><span class="v2-muted">' + helpers.esc(label)
      + '</span><strong>' + helpers.esc(countText(value)) + "</strong></div>";
  }

  function cardHtml(helpers, row, notes) {
    const open = !!state.expanded[row.id];
    const chart = state.charts[row.id];
    const evidence = row.provenanceMissing || row.countsAsEvidence === false
      ? '<p class="v2-rev-warn">Not evidence. Provenance is missing, or the cause is not counted.</p>'
      : "";
    const levers = row.levers.map(function (lever) {
      return "<li><strong>" + helpers.esc(lever.label) + "</strong> — "
        + helpers.esc(lever.helped)
        + (lever.because ? ' <span class="v2-muted">(' + helpers.esc(lever.because) + ")</span>" : "")
        + "</li>";
    }).join("");
    const detail = open
      ? '<div class="v2-rev-detail">'
        + evidence
        + "<p>Filled " + helpers.esc(row.fillSession || "not yet available")
        + ". Signal session " + helpers.esc(row.signalSession || "not yet available") + ".</p>"
        + (row.causeBecause ? "<p>Why this cause: " + helpers.esc(row.causeBecause) + ".</p>" : "")
        + (row.memoVerdict ? "<p>Research memo at entry: " + helpers.esc(row.memoVerdict) + ".</p>" : "")
        + "<p>Cited inputs: " + helpers.esc(String(row.cited))
        + ". Lines dated after the exit, kept out of the score: " + helpers.esc(String(row.hindsight)) + ".</p>"
        + (levers ? "<h4>Five levers</h4><ul>" + levers + "</ul>" : "<p>" + helpers.esc(INSUFFICIENT) + "</p>")
        + '<div class="v2-rev-chart" data-rev-chart="' + helpers.esc(row.id) + '">'
        + (chart ? chart : '<button type="button" class="v2-rev-btn" data-rev-action="chart" data-rev-id="'
          + helpers.esc(row.id) + '">Show price chart</button>')
        + "</div></div>"
      : "";
    return '<article class="v2-rev-card">'
      + '<button type="button" class="v2-rev-toggle" data-rev-action="toggle" data-rev-id="'
      + helpers.esc(row.id) + '" aria-expanded="' + (open ? "true" : "false") + '">'
      + "<strong>" + helpers.esc(row.ticker || "Unknown") + "</strong> "
      + '<span class="v2-muted">' + helpers.esc(row.market || "") + "</span>"
      + '<span class="v2-rev-pill">' + helpers.esc(row.roleLabel) + "</span>"
      + "</button>"
      + "<p>" + helpers.esc(row.columnLabel) + " · " + helpers.esc(row.exitLabel)
      + " · exit " + helpers.esc(row.exitSession || "not yet available") + "</p>"
      + "<p>Fair-cost return " + helpers.esc(row.fairCostText)
      + " · matched excess " + helpers.esc(row.excessText)
      + " · cause " + helpers.esc(row.causeLabel) + "</p>"
      + learningHtml(helpers, notes, row)
      + detail
      + "</article>";
  }

  function listHtml(helpers, rows, limit, listName, notes) {
    if (!rows.length) {
      return '<p class="v2-muted">None in this list.</p>';
    }
    const shown = rows.slice(0, limit);
    const more = rows.length > shown.length
      ? '<p><button type="button" class="v2-rev-btn" data-rev-action="more" data-rev-list="'
        + helpers.esc(listName) + '">Show more ('
        + helpers.esc(String(rows.length - shown.length)) + " left)</button></p>"
      : "";
    return shown.map(function (row) { return cardHtml(helpers, row, notes); }).join("") + more;
  }

  function renderReviews(ctx, helpers) {
    const queue = slotQueue(ctx);
    const notes = notesIndex(ctx);
    const view = reviewView(queue);
    const parts = [];
    parts.push('<section class="v2-panel v2-rev">');
    parts.push('<div class="v2-card">');
    parts.push("<h2>Which closed trades should I look at?</h2>");
    parts.push('<div class="v2-rev-observe" role="status"><strong>Observe-only.</strong> '
      + "These reviews are evidence for the version review. They do not change the book or place a trade."
      + (view.influencesLive
        ? " The published file is marked as influencing live capital. This page still does not send orders."
        : " The published file says these reviews do not influence live capital.")
      + (notes && notes.influencesLive
        ? " The post-sale notes file is marked as influencing live capital. This page still does not send orders."
        : notes
          ? " Post-sale notes do not influence live capital."
          : "")
      + "</div>");
    if (!view.present) {
      parts.push('<p class="v2-rev-missing">Closed-episode reviews: ' + helpers.esc(NOT_MEASURED) + ".</p>");
    } else {
      parts.push(metaHtml(helpers, view.generatedAt, "daily", "Queue written"));
      parts.push(metaHtml(helpers, view.scoringDate, "chart", "Book session"));
      parts.push('<div class="v2-rev-stats">');
      parts.push(stat(helpers, "Episodes walked", view.counts.episodes));
      parts.push(stat(helpers, "Closed", view.counts.closed));
      parts.push(stat(helpers, "Primary attention", view.counts.active));
      parts.push(stat(helpers, "Beside the book", view.counts.companion));
      parts.push(stat(helpers, "Open, skipped", view.counts.openSkipped));
      parts.push(stat(helpers, "Missing a review", view.counts.missing));
      if (notes) {
        parts.push(stat(helpers, "Learning points", notes.grounded));
        parts.push(stat(helpers, "Points withheld", notes.failClosed));
      }
      parts.push("</div>");
    }
    parts.push("</div>");

    parts.push('<div class="v2-card">');
    parts.push("<h2>Primary closes</h2>");
    parts.push("<p>The attention list is the strategy book's own closed trades. Comparison exits, the buy-on-signal control, shadows and challengers stay in the next list.</p>");
    if (!view.present) {
      parts.push('<p class="v2-rev-missing">' + helpers.esc(NOT_MEASURED) + "</p>");
    } else if (!view.primary.length) {
      parts.push("<p>No primary closes are on the attention list. Open trades are counted above and skipped until they close.</p>");
    } else {
      parts.push(listHtml(helpers, view.primary, state.primaryLimit, "primary", notes));
    }
    parts.push("</div>");

    parts.push('<div class="v2-card">');
    parts.push("<h2>Beside the book</h2>");
    parts.push("<p>Controls, comparison exits, gate-rejected shadows and challengers. They are not the book's own trades, and they are not averaged into the primary list.</p>");
    if (!view.present) {
      parts.push('<p class="v2-rev-missing">' + helpers.esc(NOT_MEASURED) + "</p>");
    } else if (!view.companion.length) {
      parts.push("<p>No companion closes in this refresh.</p>");
    } else {
      parts.push(listHtml(helpers, view.companion, state.companionLimit, "companion", notes));
    }
    parts.push("</div>");

    parts.push('<div class="v2-card">');
    parts.push("<h2>New trades: entry blind and the 28-day follow-up</h2>");
    parts.push("<p>Entry-blind reviews and the buy-plus-28-day follow-up are still the lab and sealed-book queues on the engineering dashboard. They have not been pointed at strategy-book episodes, so this tab does not treat them as the strategy book.</p>");
    parts.push('<p class="v2-rev-links"><a href="../index.html#lifecycle/entry-blind">Entry blind on the engineering dashboard</a>'
      + '<a href="../index.html#lifecycle/entry-revisit">Buy plus 28 days on the engineering dashboard</a></p>');
    parts.push("<p class=\"v2-muted\">Pattern marks and drawing tools stay on those lab cards. A price chart here is the published series only, without the old screen stop and target.</p>");
    parts.push("</div>");
    parts.push("</section>");
    return parts.join("");
  }

  function chartUrl(ticker) {
    const token = String(ticker || "");
    if (!/^[A-Za-z0-9._-]+$/.test(token)) return null;
    return "../data/charts/" + token + ".json";
  }

  function findRow(id) {
    const view = viewCache && viewCache.view;
    if (!view) return null;
    const rows = view.primary.concat(view.companion);
    for (let i = 0; i < rows.length; i += 1) {
      if (rows[i].id === id) return rows[i];
    }
    return null;
  }

  function paint(root) {
    root.innerHTML = renderReviews(viewCache.ctx, viewCache.helpers);
    wire(root);
  }

  function showChart(root, id) {
    const row = findRow(id);
    const helpers = viewCache.helpers;
    if (!row) return;
    const host = root.querySelector('[data-rev-chart="' + id.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"]');
    if (host) host.innerHTML = '<p class="v2-muted">Loading chart…</p>';
    const url = chartUrl(row.ticker);
    if (!url || typeof helpers.fetchJsonSafe !== "function") {
      state.charts[id] = '<p class="v2-muted">no chart yet</p>';
      paint(root);
      return;
    }
    if (typeof helpers.esc === "function") window.esc = helpers.esc;
    helpers.fetchJsonSafe(url).then(function (result) {
      if (!result || !result.ok || !result.data || typeof window.renderPriceChartSvg !== "function") {
        state.charts[id] = '<p class="v2-muted">no chart yet</p>';
      } else {
        const levels = result.data.levels || {};
        const keep = {};
        ["last", "sma50", "sma200"].forEach(function (key) {
          if (levels[key] != null) keep[key] = levels[key];
        });
        let svg = "";
        try {
          svg = window.renderPriceChartSvg(result.data, keep);
        } catch (err) {
          svg = "";
        }
        const iso = result.data.as_of || result.data.levels_as_of;
        state.charts[id] = (svg || '<p class="v2-muted">no chart yet</p>')
          + metaHtml(helpers, iso, "chart", "Price chart");
      }
      paint(root);
    });
  }

  function wire(root) {
    if (root.dataset.v2RevBound === "1") return;
    root.dataset.v2RevBound = "1";
    root.addEventListener("click", function (ev) {
      const button = ev.target && ev.target.closest ? ev.target.closest("[data-rev-action]") : null;
      if (!button) return;
      const action = button.getAttribute("data-rev-action");
      const id = button.getAttribute("data-rev-id") || "";
      if (action === "toggle" && id) {
        state.expanded[id] = !state.expanded[id];
        paint(root);
      } else if (action === "more") {
        const list = button.getAttribute("data-rev-list");
        if (list === "primary") state.primaryLimit += PAGE_SIZE;
        else state.companionLimit += PAGE_SIZE;
        paint(root);
      } else if (action === "chart" && id) {
        showChart(root, id);
      }
    });
  }

  function render(ctx, helpers) {
    const queue = slotQueue(ctx);
    viewCache = { ctx: ctx || {}, helpers: helpers, view: reviewView(queue) };
    return renderReviews(ctx, helpers);
  }

  function bind(root, ctx, helpers) {
    if (!root) return;
    const queue = slotQueue(ctx);
    viewCache = { ctx: ctx || {}, helpers: helpers, view: reviewView(queue) };
    wire(root);
  }

  window.__dashboardV2Reviews = {
    reviewView: reviewView,
    columnLabel: function (key) { return labelOf(COLUMN_LABELS, key); },
    causeLabel: function (key) { return labelOf(CAUSE_LABELS, key); },
    pctText: pctText,
    helpedText: helpedText,
    renderReviews: renderReviews,
    QUEUE_PATH: QUEUE_PATH,
  };

  window.DashboardV2Tabs.register({
    id: "reviews",
    label: "Reviews",
    dataPaths: {
      strategy_book_review: QUEUE_PATH,
      strategy_book_post_sale_notes: NOTES_PATH,
    },
    render: render,
    bind: bind,
  });
})();
