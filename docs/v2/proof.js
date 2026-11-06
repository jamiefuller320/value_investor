/* Strategy dashboard v2 — Proof tab (WP3).
 * Summaries come from window.__dashboardV2BookProof (book.js loads first).
 */
(function () {
  "use strict";

  function renderProof(ctx, helpers) {
    const api = window.__dashboardV2BookProof;
    if (!api) {
      return '<section class="v2-card"><h2>Proof</h2><p class="bp-missing">Book summaries did not load.</p></section>';
    }
    const registration = ctx && ctx.registration;
    const replay = api.slot(ctx, "strategy_book_replay");
    const scoreboard = api.slot(ctx, "assessment_scoreboard");
    const trv = api.slot(ctx, "total_return_view");
    const forwardStatus = ctx ? ctx.forwardStatus : null;
    const now = helpers.nowMs();
    const pack = api.replayResults(replay, now);
    const thickness = api.thicknessProgress(replay, forwardStatus, now);
    const checklist = api.proofChecklist(registration, replay);
    const selected = api.state.proofResult;
    const key = pack.results.some(function (row) { return row.key === selected; })
      ? selected
      : api.DEFAULT_RESULT;
    const selectedRow = pack.results.filter(function (row) { return row.key === key; })[0];
    const runAt = registration && registration.first_score_store && registration.first_score_store.run_at;
    const parts = [];

    parts.push(api.observeBanner(helpers, registration));

    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-proof-h">');
    parts.push('<h2 id="bp-proof-h">Is it working?</h2>');
    parts.push("<p>Three archive results, kept apart. " + api.tip(helpers, "Fair-cost episode %", "fairCost")
      + " and " + api.tip(helpers, "matched excess", "matched")
      + " are medians of mature trades. They are not added across results.</p>");
    if (runAt) parts.push(api.metaHtml(helpers, runAt, "daily", "Replay written"));
    parts.push('<div class="bp-grid">');
    pack.results.forEach(function (row) {
      const gate = thickness.byResult[row.key];
      parts.push('<article class="bp-sub"><h3>' + helpers.esc(row.label) + "</h3>");
      parts.push(api.metaHtml(helpers, row.scoringDate, "chart", "Chart session"));
      if (row.lookaheadWarning) parts.push('<p class="bp-warn">' + helpers.esc(row.lookaheadWarning) + "</p>");
      if (row.publishedEmpty) {
        parts.push('<p class="bp-note">Published empty. Medians are insufficient data, not a zero and not a pass.</p>');
      }
      parts.push("<p>Median fair-cost " + api.metricHtml(helpers, row.medianFairCost) + "</p>");
      parts.push("<p>Median matched excess " + api.metricHtml(helpers, row.medianMatchedExcess) + "</p>");
      parts.push("<p>" + api.tip(helpers, "Counted toward 48", "thickness") + " "
        + helpers.esc(gate.text) + " — " + helpers.esc(gate.verdict) + "</p>");
      if (gate.state === "value" && gate.minCounted) {
        const width = Math.max(0, Math.min(100, (gate.counted / gate.minCounted) * 100));
        parts.push('<div class="bp-meter" role="img" aria-label="' + helpers.esc(gate.text) + '"><span style="width:'
          + width.toFixed(1) + '%"></span></div>');
      }
      parts.push('<p class="v2-muted">Archive episodes do not count toward the forward thickness gate.</p>');
      parts.push("</article>");
    });
    parts.push("</div>");
    parts.push("<h3>Forward book</h3>");
    parts.push("<p>" + helpers.esc(thickness.forward.text) + ". " + helpers.esc(thickness.forward.note || "") + "</p>");
    if (thickness.forward.matureCount != null && thickness.forward.counted == null) {
      parts.push('<p class="v2-muted">Forward status reports ' + helpers.esc(String(thickness.forward.matureCount))
        + " mature episodes. The capped count toward 48 is not yet measured.</p>");
    }
    parts.push("</section>");

    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-check-h">');
    parts.push('<h2 id="bp-check-h">Phase 3 proof bars</h2>');
    parts.push(api.metaHtml(helpers, checklist.signedAt, "daily", "Thresholds sealed"));
    parts.push('<p class="v2-muted">' + helpers.esc(checklist.note || "") + "</p>");
    if (!checklist.bars.length) {
      parts.push('<p class="bp-missing">not yet measured</p>');
    } else {
      parts.push('<ul class="bp-check">');
      checklist.bars.forEach(function (bar) {
        const status = bar.status || "not yet measured";
        const cls = status === "met" ? "bp-num" : "bp-missing";
        parts.push("<li><strong>" + helpers.esc(bar.requirement) + "</strong> — "
          + helpers.esc(bar.bar) + ' <span class="' + cls + '">' + helpers.esc(status) + "</span></li>");
      });
      parts.push("</ul>");
    }
    parts.push("</section>");

    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-detail-h">');
    parts.push('<h2 id="bp-detail-h">Boards for one result</h2>');
    parts.push(api.selectorHtml(helpers, "bp-proof-result", key, replay, now));
    if (selectedRow && selectedRow.lookaheadWarning) {
      parts.push('<p class="bp-warn">' + helpers.esc(selectedRow.lookaheadWarning) + "</p>");
    }
    parts.push(api.metaHtml(helpers, selectedRow && selectedRow.scoringDate, "chart", "Chart session"));

    parts.push("<h3>Comparison exits</h3>");
    parts.push("<p>Same entries as the book, different sell rules. The figure is the book's result minus the comparison. Report-only.</p>");
    parts.push('<div class="v2-table-wrap"><table class="v2-table"><thead><tr><th>Exit</th><th>Mature pairs</th><th>Median difference</th><th>Mean difference</th></tr></thead><tbody>');
    api.pairedExits(replay, key).forEach(function (row) {
      parts.push("<tr><td>" + helpers.esc(row.label) + '<br><span class="v2-muted">' + helpers.esc(row.question)
        + "</span></td><td>" + api.metricHtml(helpers, row.count) + "</td><td>"
        + api.metricHtml(helpers, row.medianDifference) + "</td><td>"
        + api.metricHtml(helpers, row.meanDifference) + "</td></tr>");
    });
    parts.push("</tbody></table></div>");

    parts.push("<h3>" + api.tip(helpers, "Challenger bench", "bench") + "</h3>");
    parts.push("<p>A challenger is not promoted from this page. The bar needs 48 counted mature episodes, a difference above 2.5 standard errors, the same sign in both halves, and capital-days no worse than the book.</p>");
    parts.push('<div class="v2-table-wrap"><table class="v2-table"><thead><tr><th>Challenger</th><th>Kept</th><th>Counted mature</th><th>Mean difference</th><th>Bar</th></tr></thead><tbody>');
    api.benchRows(replay, key).forEach(function (row) {
      parts.push("<tr><td>" + helpers.esc(row.label) + "</td><td>" + api.metricHtml(helpers, row.kept)
        + "</td><td>" + api.metricHtml(helpers, row.counted) + "</td><td>"
        + api.metricHtml(helpers, row.meanDifference) + "</td><td>" + helpers.esc(row.verdict) + "</td></tr>");
    });
    parts.push("</tbody></table></div>");

    parts.push("<h3>" + api.tip(helpers, "Gate-rejected shadows", "shadow") + "</h3>");
    parts.push("<p>Scored as if the book had bought names the gates refused. They never count toward the thickness gate.</p>");
    parts.push('<div class="v2-table-wrap"><table class="v2-table"><thead><tr><th>Shadow</th><th>Mature trades</th><th>Median fair-cost</th><th>Launch share</th></tr></thead><tbody>');
    api.shadowRows(replay, key).forEach(function (row) {
      parts.push("<tr><td>" + helpers.esc(row.label) + "</td><td>" + api.metricHtml(helpers, row.count)
        + "</td><td>" + api.metricHtml(helpers, row.medianFairCost) + "</td><td>"
        + api.metricHtml(helpers, row.launchShare) + "</td></tr>");
    });
    parts.push("</tbody></table></div>");

    const selection = api.selectionBoard(replay, key, api.state.selectionFeature);
    parts.push("<h3>" + api.tip(helpers, "Selection board", "selection") + "</h3>");
    if (selection.status !== "measured" || !selection.features.length) {
      parts.push('<p class="bp-missing">' + helpers.esc(selection.status) + "</p>");
    } else {
      const withData = selection.features.filter(function (row) {
        return row.present != null && row.present > 0;
      });
      parts.push('<p class="v2-muted">' + helpers.esc(String(withData.length)) + " of "
        + helpers.esc(String(selection.features.length))
        + " features have a value on a mature trade. The rest are insufficient data and are left out of this list.</p>");
      parts.push('<label class="bp-field">Feature <select name="bp-proof-feature">');
      const options = withData.length ? withData : selection.features;
      options.forEach(function (row) {
        const selectedAttr = row.id === selection.feature ? " selected" : "";
        parts.push('<option value="' + helpers.esc(row.id) + '"' + selectedAttr + ">"
          + helpers.esc(row.label) + "</option>");
      });
      parts.push("</select></label>");
      parts.push('<div class="v2-table-wrap"><table class="v2-table"><thead><tr><th>Fifth</th><th>Trades</th><th>Launch share</th><th>Median fair-cost</th><th>Standard error</th></tr></thead><tbody>');
      selection.rows.forEach(function (row) {
        const label = row.fifth === 1 ? "Lowest fifth" : row.fifth === 5 ? "Highest fifth" : "Fifth " + row.fifth;
        parts.push("<tr><td>" + helpers.esc(label) + "</td><td>" + api.metricHtml(helpers, row.count)
          + "</td><td>" + api.metricHtml(helpers, row.launchShare) + "</td><td>"
          + api.metricHtml(helpers, row.medianFairCost) + "</td><td>"
          + api.metricHtml(helpers, row.standardError) + "</td></tr>");
      });
      parts.push("</tbody></table></div>");
    }
    parts.push("</section>");

    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-controls-h">');
    parts.push('<h2 id="bp-controls-h">Buy-on-signal and leave-tier</h2>');
    parts.push("<p>" + api.tip(helpers, "Buy on the signal", "buyOnSignal") + " and "
      + api.tip(helpers, "leave the buy tier", "leaveTier")
      + " are controls. Each cell is that result's own median. Nothing is averaged across the three results.</p>");
    parts.push('<div class="v2-table-wrap"><table class="v2-table"><thead><tr><th>Result</th><th>Buy on the signal</th><th>Leave the buy tier</th></tr></thead><tbody>');
    api.controlBoardRows(replay).forEach(function (row) {
      const buy = row.buyOnSignal.medianFairCost.text + " (" + row.buyOnSignal.count.text + ")";
      const leave = row.leaveTier.medianFairCost.text + " (" + row.leaveTier.count.text + ")";
      parts.push("<tr><td>" + helpers.esc(row.label)
        + (row.lookaheadWarning ? '<br><span class="v2-muted">Uses gates dated after the trades</span>' : "")
        + "</td><td>" + helpers.esc(buy) + "</td><td>" + helpers.esc(leave) + "</td></tr>");
    });
    parts.push("</tbody></table></div></section>");

    const controls = api.controlRows(trv, scoreboard, now);
    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-paper-h">');
    parts.push('<h2 id="bp-paper-h">Paper controls</h2>');
    parts.push("<p>" + api.tip(helpers, "Older paper books", "paper")
      + " One row each. They are not the strategy book.</p>");
    parts.push(api.metaHtml(helpers, controls.generatedAt || controls.trvUpdatedAt, "daily", "Scoreboard"));
    if (!controls.rows.length) {
      parts.push('<p class="bp-missing">not yet measured</p>');
    } else {
      parts.push('<div class="v2-table-wrap"><table class="v2-table"><thead><tr><th>Kind</th><th>Book</th><th>Role</th><th>Total return</th><th>Excess vs benchmark</th><th>Marks</th><th>As of</th></tr></thead><tbody>');
      controls.rows.forEach(function (row) {
        const asOf = row.asOf ? helpers.displayDate(row.asOf) : "not yet available";
        parts.push("<tr><td>paper control</td><td>" + helpers.esc(row.label) + "</td><td>"
          + helpers.esc(row.roleLabel) + "</td><td>" + helpers.esc(row.totalReturnText) + "</td><td>"
          + helpers.esc(row.excessText) + "</td><td>" + helpers.esc(row.marksText) + "</td><td>"
          + helpers.esc(asOf) + "</td></tr>");
      });
      parts.push("</tbody></table></div>");
    }
    parts.push("</section>");
    return parts.join("");
  }

  function bindProof(root, ctx, helpers) {
    const api = window.__dashboardV2BookProof;
    if (!api) return;
    api.state._proofCtx = ctx;
    api.state._proofHelpers = helpers;
    if (root.dataset.bpProofBound === "1") return;
    root.dataset.bpProofBound = "1";
    root.addEventListener("change", function (ev) {
      const target = ev.target;
      if (!target || !target.name) return;
      if (target.name === "bp-proof-result") {
        api.state.proofResult = target.value;
        api.state.selectionFeature = "";
        root.innerHTML = renderProof(api.state._proofCtx, api.state._proofHelpers);
      } else if (target.name === "bp-proof-feature") {
        api.state.selectionFeature = target.value;
        root.innerHTML = renderProof(api.state._proofCtx, api.state._proofHelpers);
      }
    });
  }

  if (window.__dashboardV2BookProof) {
    window.__dashboardV2BookProof.renderProof = renderProof;
  }

  window.DashboardV2Tabs.register({
    id: "proof",
    label: "Proof",
    dataPaths: {
      total_return_view: "../data/total_return_view.json",
      assessment_scoreboard: "../data/assessment_scoreboard.json",
    },
    render: renderProof,
    bind: bindProof,
  });
})();
