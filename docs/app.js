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
    { id: "lifecycle", label: "Lifecycle" },
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
    activateTab(button.dataset.tab, { updateHash: true });
  });
}

function activateTab(tabId, { updateHash = false } = {}) {
  const nav = document.getElementById("tabs");
  if (!nav || !tabId) return;
  const button = nav.querySelector(`[data-tab="${tabId}"]`);
  if (!button) return;
  nav.querySelectorAll(".tab").forEach((el) => el.classList.toggle("active", el === button));
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${tabId}`);
  });
  if (updateHash) {
    if (tabId === "lifecycle") syncLifecycleHash();
    else if (tabId === "analysis") syncAnalysisHash();
    else if (tabId === "automation") syncAutomationHash();
    else if (tabId === "performance") syncPerformanceHash();
    else if (tabId === "screener") syncScreenerHash();
    else if (location.hash && location.hash !== `#${tabId}`) {
      history.replaceState(null, "", `#${tabId}`);
    }
  }
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

function overallStatusBadge(status) {
  const key = String(status || "ok").toLowerCase();
  const cls = {
    ok: "stage-complete",
    info: "stage-active",
    warn: "stage-pending",
    fail: "stage-fail",
  };
  return `<span class="stage-badge ${cls[key] || "stage-active"}">${esc(key)}</span>`;
}

function renderProgressReport(data) {
  const report = data.progress_report;
  const runbookUrl = githubOpsDocUrl("docs/ops/progress-report.md");
  const bridgeUrl = githubOpsDocUrl("docs/ops/dashboard-bridge.md");
  const generateHelp = `
      <p class="small muted" style="margin-top:0.75rem">
        <strong>Generate fresh report</strong> queues via the Supabase dashboard bridge
        (no browser token). Local serve uses <code>POST /api/progress-report</code>.
        ${bridgeUrl ? `<a href="${esc(bridgeUrl)}" target="_blank" rel="noopener">Bridge runbook</a>` : ""}
        ${runbookUrl ? ` · <a href="${esc(runbookUrl)}" target="_blank" rel="noopener">Progress report runbook</a>` : ""}
      </p>
      <details class="overview-secondary" style="margin-top:0.5rem">
        <summary class="small">Legacy Pages token (optional fallback)</summary>
        <p class="small muted" style="margin:0.35rem 0">
          Only needed if Supabase bridge is disabled. Prefer Actions →
          <code>Dashboard bridge worker</code> → Run workflow to drain the queue.
        </p>
        <button type="button" class="btn" id="progress-report-token-btn" title="Fine-grained PAT fallback">Configure Pages token</button>
      </details>`;
  if (!report) {
    return `
    <div class="card progress-report-card" style="margin-top:1rem" id="progress-report-card">
      <div class="progress-report-header">
        <h3>Progress report</h3>
        <div class="progress-report-actions">
          <button type="button" class="btn btn-primary" id="progress-report-generate-btn">Generate fresh report</button>
          <button type="button" class="btn" id="progress-report-reload-btn">Reload</button>
        </div>
      </div>
      <p class="muted small">No published progress report yet (or the published JSON failed to load).</p>
      <p class="small">
        Click <strong>Generate fresh report</strong> — on GitHub Pages this goes through Supabase,
        then the weekday bridge worker dispatches Actions (same path as Lifecycle Acknowledge).
      </p>
      ${generateHelp}
      <p class="small muted" id="progress-report-status" aria-live="polite"></p>
    </div>`;
  }

  const actionable = report.actionable || {};
  const counts = actionable.counts || {};
  const integration = report.integration || {};
  const role = report.role_coherence || {};
  const progress = report.progress || {};
  const headline = progress.headline || report.headline || "";

  const checkPreview = (bucket) => {
    const rows = (bucket.checks || []).filter((row) => row.severity !== "ok").slice(0, 4);
    if (!rows.length) {
      return '<p class="small muted">No warnings.</p>';
    }
    return `<ul class="list-plain small">${rows
      .map(
        (row) =>
          `<li><strong>[${esc(String(row.severity || "").toUpperCase())}]</strong> ${esc(row.title)} — ${esc(row.summary)}</li>`
      )
      .join("")}</ul>`;
  };

  const deferNow = (actionable.defer_now || []).slice(0, 5);
  const deferHtml = deferNow.length
    ? `<ul class="list-plain small">${deferNow
        .map(
          (row) =>
            `<li><strong>${esc(row.id)}</strong> ${esc(row.title)}${
              row.revisit_when ? ` <span class="muted">(revisit: ${esc(row.revisit_when)})</span>` : ""
            }</li>`
        )
        .join("")}</ul>`
    : '<p class="small muted">None marked <code>now</code>.</p>';

  const soWhat = report.so_what || {};
  const soCounts = soWhat.counts || {};
  const humanGateCount = Number(soCounts.human_gate || 0);
  const autoQueueCount = Number(soCounts.auto_queue || 0);
  const observeCount = Number(soCounts.observe || 0);
  const gateGroups = soWhat.human_gate_groups || [];
  const lpGapGroups = soWhat.learning_path_gap_groups || [];
  const lpGapCount = Number(soCounts.learning_path_gaps || lpGapGroups.length || 0);
  const gates = soWhat.human_gates_preview || [];
  const soWhatDocUrl = githubOpsDocUrl("docs/ops/so-what-gap-closure.md");
  const formatTickerPreview = (tickers, limit = 10) => {
    const names = (tickers || []).map((t) => String(t || "").trim()).filter(Boolean);
    if (!names.length) return "—";
    const shown = names.slice(0, limit);
    const extra = names.length - shown.length;
    return `${shown.join(", ")}${extra > 0 ? ` (+${extra} more)` : ""}`;
  };
  let gatesHtml;
  if (gateGroups.length) {
    gatesHtml = `<ul class="list-plain small so-what-gate-list">${gateGroups
      .map((group) => {
        const docPath = group.human_doc_path || "";
        const docUrl = docPath ? githubOpsDocUrl(docPath) : null;
        const action = group.human_action || group.so_what || group.label || "";
        const count = Number(group.count || (group.tickers || []).length || 0);
        return `<li class="so-what-gate-item so-what-gate-group">
            <div class="so-what-gate-group-head">
              <strong>${esc(String(count))} names</strong>
              <span class="muted so-what-gate-kind">${esc(group.kind || "issue")}</span>
              ${
                docUrl
                  ? `<a class="small" href="${esc(docUrl)}" target="_blank" rel="noopener">Runbook</a>`
                  : ""
              }
            </div>
            <span class="so-what-gate-action">${esc(action)}</span>
            <div class="small muted so-what-gate-tickers">${esc(
              formatTickerPreview(group.tickers_preview || group.tickers || [])
            )}</div>
          </li>`;
      })
      .join("")}</ul>`;
  } else if (gates.length) {
    gatesHtml = `<ul class="list-plain small so-what-gate-list">${gates
      .map((row) => {
        const docPath = row.human_doc_path || "";
        const docUrl = docPath ? githubOpsDocUrl(docPath) : null;
        const action = row.human_action || row.so_what || "";
        return `<li class="so-what-gate-item">
            <strong>${esc(row.ticker || "—")}</strong>
            <span class="so-what-gate-action">${esc(action)}</span>
            ${
              docUrl
                ? `<a class="small" href="${esc(docUrl)}" target="_blank" rel="noopener">Runbook</a>`
                : ""
            }
          </li>`;
      })
      .join("")}</ul>`;
  } else if (humanGateCount > 0) {
    gatesHtml =
      '<p class="small muted">Human gates present — open the full report for the complete list.</p>';
  } else {
    gatesHtml = '<p class="small muted">No human gates right now.</p>';
  }
  const analysisReviewUrl = githubOpsDocUrl("docs/ops/analysis-review.md", "system-gaps-learning-path-integrity");
  let lpGapsHtml = "";
  if (lpGapGroups.length) {
    lpGapsHtml = `<ul class="list-plain small so-what-gate-list">${lpGapGroups
      .map((group) => {
        const flagKind = String(group.kind || "").replace(/^system_gap_/, "");
        const action = group.human_action || group.so_what || group.label || "";
        const closure = group.recommended_closure || "—";
        return `<li class="so-what-gate-item">
            <div class="so-what-gate-group-head">
              <strong>${esc(flagKind || "gap")}</strong>
              <span class="muted so-what-gate-kind">${esc(closure)}</span>
              ${
                analysisReviewUrl
                  ? `<a class="small" href="${esc(analysisReviewUrl)}" target="_blank" rel="noopener">Runbook</a>`
                  : ""
              }
            </div>
            <span class="so-what-gate-action">${esc(action)}</span>
          </li>`;
      })
      .join("")}</ul>`;
  } else if (lpGapCount > 0) {
    lpGapsHtml =
      '<p class="small muted">Learning-path gaps present — open the full progress report markdown.</p>';
  } else {
    lpGapsHtml = '<p class="small muted">No active learning-path gap flags in so-what.</p>';
  }
  const soWhatSection = `
      <section class="so-what-section${humanGateCount > 0 || lpGapCount > 0 ? " so-what-section-attention" : ""}">
        <div class="so-what-section-header">
          <h4>So what? — needs your judgment</h4>
          ${soWhatDocUrl ? `<a class="small" href="${esc(soWhatDocUrl)}" target="_blank" rel="noopener">How this works</a>` : ""}
        </div>
        <p class="small muted" style="margin-top:0">
          Human gates need a policy/filing choice. Same-issue names are grouped into one row.
          Enforcement gaps (<strong>${esc(String(autoQueueCount))}</strong> auto-queued) are handled by the engineering queue without a prompt.
          ${observeCount ? ` · ${esc(String(observeCount))} observe-only` : ""}
          ${lpGapCount ? ` · <strong>${esc(String(lpGapCount))}</strong> learning-path gap(s)` : ""}
        </p>
        <div class="grid so-what-count-grid">
          <div class="setting-row"><span class="setting-label">Human gates</span><span class="setting-value">${esc(String(humanGateCount))}</span></div>
          <div class="setting-row"><span class="setting-label">Auto-queued</span><span class="setting-value">${esc(String(autoQueueCount))}</span></div>
          <div class="setting-row"><span class="setting-label">Observe</span><span class="setting-value">${esc(String(observeCount))}</span></div>
          <div class="setting-row"><span class="setting-label">Learning gaps</span><span class="setting-value">${esc(String(lpGapCount))}</span></div>
        </div>
        ${gatesHtml}
        <div class="so-what-learning-gaps" style="margin-top:0.75rem">
          <h5 class="small" style="margin:0 0 0.35rem">Learning-path gaps (system_gaps)</h5>
          ${lpGapsHtml}
        </div>
      </section>`;

  const lifecycleAcks = report.lifecycle_acks || {};
  const pendingAcks = lifecycleAcks.pending || [];
  const ackedRows = lifecycleAcks.acked || [];
  const pendingAckCount = Number(lifecycleAcks.pending_count || pendingAcks.length || 0);
  const ackedAckCount = Number(lifecycleAcks.acked_count || ackedRows.length || 0);
  const lifecycleDocUrl = githubOpsDocUrl("docs/ops/position-lifecycle.md", "entry-dca-adoption-plan");
  let lifecycleAckList = "";
  if (pendingAcks.length) {
    lifecycleAckList = `<ul class="list-plain small so-what-gate-list">${pendingAcks
      .map((row) => {
        const ack = row.acknowledge || {};
        const payload = JSON.stringify(
          ack.payload || {
            experiment_id: row.experiment_id,
            factor_id: "progress_report",
            kind: "human_ack",
            decision: "ack_observe",
          }
        );
        const enabled = ack.enabled !== false;
        return `<li class="so-what-gate-item">
            <div class="so-what-gate-group-head">
              <strong>${esc(row.experiment_id || "—")}</strong>
              <span class="muted so-what-gate-kind">${esc(row.kind || "experiment")}</span>
              <button type="button" class="btn lifecycle-ack-btn${enabled ? " btn-primary" : ""}"
                data-progress-ack="${esc(payload)}"
                ${enabled ? "" : "disabled"}
                aria-disabled="${enabled ? "false" : "true"}"
                title="${esc(enabled ? "Record observe-only ack via Supabase" : "Already acknowledged")}">
                ${enabled ? "Acknowledge" : "Acknowledged"}
              </button>
            </div>
            <span class="so-what-gate-action">${esc(row.title || "")}</span>
          </li>`;
      })
      .join("")}</ul>`;
  } else {
    lifecycleAckList = '<p class="small muted">No recommend experiments waiting on Acknowledge.</p>';
  }
  let lifecycleAckedList = "";
  if (ackedRows.length) {
    lifecycleAckedList = `<ul class="list-plain small">${ackedRows
      .slice(0, 6)
      .map(
        (row) =>
          `<li><strong>${esc(row.experiment_id || "—")}</strong> ${esc(row.title || "")}
            <span class="muted">· acked ${esc(fmtDate(row.acked_at))}</span></li>`
      )
      .join("")}</ul>`;
  } else {
    lifecycleAckedList = '<p class="small muted">None recorded yet.</p>';
  }
  const lifecycleAckSection = `
      <section class="so-what-section${pendingAckCount > 0 ? " so-what-section-attention" : ""}" style="margin-top:0.75rem">
        <div class="so-what-section-header">
          <h4>Lifecycle observe-acks</h4>
          ${lifecycleDocUrl ? `<a class="small" href="${esc(lifecycleDocUrl)}" target="_blank" rel="noopener">Lifecycle runbook</a>` : ""}
        </div>
        <p class="small muted" style="margin-top:0">
          Same observe-only Acknowledge as the Lifecycle cards — queued through Supabase
          (does not execute DCA or change starter fraction).
          Pending <strong>${esc(String(pendingAckCount))}</strong>
          · acked <strong>${esc(String(ackedAckCount))}</strong>
          ${overallStatusBadge(lifecycleAcks.overall || "ok")}
        </p>
        ${lifecycleAckList}
        <details class="overview-secondary" style="margin-top:0.5rem">
          <summary class="small">Recently acked (${esc(String(ackedAckCount))})</summary>
          ${lifecycleAckedList}
        </details>
        <p class="small muted" id="progress-lifecycle-ack-status" aria-live="polite"></p>
      </section>`;

  return `
    <div class="card progress-report-card" style="margin-top:1rem" id="progress-report-card">
      <div class="progress-report-header">
        <div>
          <h3>Progress report ${overallStatusBadge(report.overall)}</h3>
          <p class="small muted" style="margin:0.15rem 0 0">
            Generated ${esc(fmtDate(report.generated_at))} · focus
            <strong>${esc(progress.current_focus || "—")}</strong>
          </p>
        </div>
        <div class="progress-report-actions">
          <button type="button" class="btn btn-primary" id="progress-report-generate-btn">Generate fresh report</button>
          <button type="button" class="btn" id="progress-report-reload-btn">Reload</button>
          <button type="button" class="btn" id="progress-report-view-btn">View full report</button>
        </div>
      </div>
      <p>${esc(headline)}</p>
      ${soWhatSection}
      ${lifecycleAckSection}
      <div class="grid" style="margin-top:0.75rem">
        <div class="setting-row"><span class="setting-label">Deferred now</span><span class="setting-value">${esc(String(counts.defer_now ?? 0))}</span></div>
        <div class="setting-row"><span class="setting-label">Open fragments</span><span class="setting-value">${esc(String(counts.open_fragments ?? 0))}</span></div>
        <div class="setting-row"><span class="setting-label">Proposed review tasks</span><span class="setting-value">${esc(String(counts.proposed_total ?? 0))}</span></div>
        <div class="setting-row"><span class="setting-label">Engineering open</span><span class="setting-value">${esc(String(counts.engineering_open ?? 0))}</span></div>
        <div class="setting-row"><span class="setting-label">Integration</span><span class="setting-value">${overallStatusBadge(integration.overall)}</span></div>
        <div class="setting-row"><span class="setting-label">Role coherence</span><span class="setting-value">${overallStatusBadge(role.overall)}</span></div>
      </div>
      <details class="overview-secondary" style="margin-top:1rem">
        <summary>Deferred items &amp; join-up checks</summary>
        <div class="automation-grid" style="margin-top:0.75rem">
          <section class="automation-section">
            <h4>Actionable now</h4>
            ${deferHtml}
          </section>
          <section class="automation-section">
            <h4>Integration / join-up</h4>
            ${checkPreview(integration)}
            <h4 style="margin-top:0.75rem">Role coherence</h4>
            ${checkPreview(role)}
          </section>
        </div>
      </details>
      ${generateHelp}
      <p class="small muted" id="progress-report-status" aria-live="polite"></p>
    </div>
  `;
}

const PROGRESS_REPORT_GH_REPO = "jamiefuller320/value_investor";
const PROGRESS_REPORT_WORKFLOW = "progress-report.yml";
const PROGRESS_REPORT_PAT_KEY = "ftse.progressReport.githubPat";
const PROGRESS_REPORT_ACTIONS_URL =
  `https://github.com/${PROGRESS_REPORT_GH_REPO}/actions/workflows/${PROGRESS_REPORT_WORKFLOW}`;

function setProgressReportStatus(message, isError) {
  const el = document.getElementById("progress-report-status");
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("progress-report-status-error", Boolean(isError));
}

function setProgressReportStatusHtml(html, isError) {
  const el = document.getElementById("progress-report-status");
  if (!el) return;
  el.innerHTML = html || "";
  el.classList.toggle("progress-report-status-error", Boolean(isError));
}

function getProgressReportPat() {
  try {
    return String(localStorage.getItem(PROGRESS_REPORT_PAT_KEY) || "").trim();
  } catch {
    return "";
  }
}

function saveProgressReportPat(token) {
  localStorage.setItem(PROGRESS_REPORT_PAT_KEY, String(token || "").trim());
}

function clearProgressReportPat() {
  localStorage.removeItem(PROGRESS_REPORT_PAT_KEY);
}

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function showProgressReportPatPrompt(reason) {
  const hasPat = Boolean(getProgressReportPat());
  setProgressReportStatusHtml(
    `<span>${esc(reason || "GitHub Pages cannot run the CLI.")}</span>
     <div class="progress-report-pat-box">
       <label class="small" for="progress-report-pat-input">
         Fine-grained PAT with <code>Actions: Write</code> on this repo
         (stored only in this browser${hasPat ? " — token already saved" : ""}):
       </label>
       <div class="progress-report-pat-row">
         <input type="password" id="progress-report-pat-input" class="progress-report-pat-input"
           autocomplete="off" spellcheck="false"
           placeholder="${hasPat ? "•••••••• (leave blank to keep saved token)" : "github_pat_…"}" />
         <button type="button" class="btn btn-primary" id="progress-report-pat-save-btn">Save &amp; generate</button>
         <button type="button" class="btn" id="progress-report-pat-actions-btn">Open Actions</button>
         ${hasPat ? '<button type="button" class="btn" id="progress-report-pat-clear-btn">Clear token</button>' : ""}
       </div>
       <p class="small muted" style="margin:0.35rem 0 0">
         Actions: Write can dispatch any workflow in this repo — limit the token to
         <code>${esc(PROGRESS_REPORT_GH_REPO)}</code> and revoke it on shared browsers.
       </p>
     </div>`,
    true
  );
}

/** GitHub Pages sets max-age≈600 on JSON; always bust so refresh sees new reports. */
async function fetchDashboardJson(path) {
  const joiner = path.includes("?") ? "&" : "?";
  const response = await fetch(`${path}${joiner}ts=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function fetchProgressReportJson() {
  return fetchDashboardJson("data/progress_report.json");
}

const DASHBOARD_SIDECARS = [
  ["automation", "data/automation.json"],
  ["project_progress", "data/project_progress.json"],
  ["market_status", "data/market_status.json"],
  ["system_gaps", "data/system_gaps.json"],
  ["progress_report", "data/progress_report.json"],
  ["queue_health", "data/queue_health.json"],
  ["observe_utilization", "data/observe_utilization.json"],
  ["assessment_scoreboard", "data/assessment_scoreboard.json"],
  ["total_return_view", "data/total_return_view.json"],
  ["lifecycle_maturity_trajectory", "data/lifecycle_maturity_trajectory.json"],
  ["n200_tech_timing_observe", "data/n200_tech_timing_observe.json"],
  ["n201_value_mom_observe", "data/n201_value_mom_observe.json"],
  ["n206_plain_ey_observe", "data/n206_plain_ey_observe.json"],
  ["n210_ai_judgment_observe", "data/n210_ai_judgment_observe.json"],
  ["chart_outcome_review", "data/chart_outcome_review.json"],
  ["engineering_tasks", "data/engineering_tasks.json"],
  ["ingest_deviations", "data/ingest_deviations.json"],
  ["human_tasks_checklist", "human_tasks_checklist.json"],
  ["human_tasks_board", "data/human_tasks_board.json"],
  ["human_task_acks", "data/human_task_acks.json"],
  ["lifecycle_board", "data/lifecycle_board.json"],
  ["sealed_lifecycle", "data/sealed_lifecycle.json"],
  ["post_sale_review_queue", "data/post_sale_review_queue.json"],
  ["post_sale_review_labels", "data/post_sale_review_labels.json"],
  ["entry_blind_review_queue", "data/entry_blind_review_queue.json"],
  ["entry_blind_review_labels", "data/entry_blind_review_labels.json"],
  ["entry_revisit_review_queue", "data/entry_revisit_review_queue.json"],
  ["entry_revisit_review_labels", "data/entry_revisit_review_labels.json"],
  ["ui_state_reconciliation", "data/ui_state_reconciliation.json"],
  ["universe_filing_archive_status", "data/universe_filing_archive_status.json"],
  ["daily_focus", "data/daily_focus.json"],
  ["daily_focus_acks", "data/daily_focus_acks.json"],
  ["daily_discuss_inbox", "data/daily_discuss_inbox.json"],
  ["daily_hub_history", "data/daily_hub_history.json"],
  ["pr_fix_occasions", "data/pr_fix_occasions.json"],
];

let dashboardRefreshInFlight = null;
let dashboardLastLoadedAt = 0;
const DASHBOARD_VISIBLE_RELOAD_MS = 45 * 1000;

/** Last network-fetched human-tasks board (pre client ack merge). */
let humanTasksBoardBase = null;
/**
 * Session overlay for acks queued from this page before git sidecar catches up.
 * Keys are task_id; values match human_task_acks.json row shape.
 */
const pendingHumanTaskAcks = Object.create(null);

/** Last network-fetched daily hub (pre client accept/discuss overlay). */
let dailyFocusBase = null;
/**
 * Session overlay for Daily hub Accept before git sidecar / rebuild catch-up.
 * Keys are recommendation_id (preferred) or task_ref.
 */
const pendingDailyAccepts = Object.create(null);
/**
 * Session overlay for Discuss in-flight / queued — blocks double inbox submit.
 * Keys are recommendation_id.
 */
const pendingDailyDiscuss = Object.create(null);
/** In-flight Accept/Discuss race guard (same recommendation, double-click). */
const inflightDailyRecActions = Object.create(null);

function mergeHumanTaskAcksIntoBoard(board, acksStore) {
  if (!board || !Array.isArray(board.tasks)) return board;
  const openAcks = {};
  for (const row of (acksStore && acksStore.acks) || []) {
    if (!row || typeof row !== "object") continue;
    if (String(row.status || "open") !== "open") continue;
    const id = String(row.task_id || "").trim();
    if (id) openAcks[id] = row;
  }
  if (!Object.keys(openAcks).length) return board;

  const tasks = board.tasks.map((task) => {
    const hit = openAcks[String(task.id || "").trim()];
    if (!hit) return task;
    const analysisFp = String((task.analysis && task.analysis.fingerprint) || "");
    const ackFp = String(hit.finding_fingerprint || "");
    const stale = Boolean(analysisFp && ackFp && analysisFp !== ackFp);
    const ack = {
      acked: true,
      stale,
      acked_at: hit.acked_at || null,
      decision: hit.decision || null,
      finding_fingerprint: ackFp || null,
    };
    return {
      ...task,
      ack,
      sort_bucket: stale ? "new_info" : "acked",
    };
  });

  const openRows = tasks.filter((row) => row.sort_bucket === "new_info" || row.sort_bucket === "unacked");
  const ackedRows = tasks.filter((row) => row.sort_bucket === "acked");
  openRows.sort((a, b) => {
    const rank = { new_info: 0, unacked: 1 };
    const ra = rank[a.sort_bucket] ?? 9;
    const rb = rank[b.sort_bucket] ?? 9;
    if (ra !== rb) return ra - rb;
    const ta = String((a.analysis && a.analysis.updated_at) || "");
    const tb = String((b.analysis && b.analysis.updated_at) || "");
    return tb.localeCompare(ta);
  });
  ackedRows.sort((a, b) =>
    String((b.ack && b.ack.acked_at) || "").localeCompare(String((a.ack && a.ack.acked_at) || ""))
  );
  const ordered = openRows.concat(ackedRows);
  const counts = {
    ...(board.counts || {}),
    new_info: ordered.filter((row) => row.sort_bucket === "new_info").length,
    unacked: ordered.filter((row) => row.sort_bucket === "unacked").length,
    acked: ordered.filter((row) => row.sort_bucket === "acked").length,
    human: ordered.length,
  };
  return { ...board, tasks: ordered, counts };
}

function rememberPendingHumanTaskAck(payload) {
  const taskId = String((payload && payload.task_id) || "").trim();
  if (!taskId) return;
  pendingHumanTaskAcks[taskId] = {
    task_id: taskId,
    decision: String((payload && payload.decision) || "ack_observe"),
    status: "open",
    acked_at: new Date().toISOString(),
    finding_fingerprint: String((payload && payload.finding_fingerprint) || ""),
    source: "dashboard_optimistic",
    acked_by: "dashboard",
  };
}

function clearPendingHumanTaskAck(taskId) {
  delete pendingHumanTaskAcks[String(taskId || "").trim()];
}

function prunePendingHumanTaskAcksAgainstDurable(acksStore) {
  // Only drop session pending once git reflects *this* ack fingerprint.
  // A durable open row with a different fp is a stale prior ack — keep pending
  // so re-ack / new analysis stays bottom-sorted and the button stays disabled.
  for (const row of (acksStore && acksStore.acks) || []) {
    if (!row || typeof row !== "object") continue;
    if (String(row.status || "open") !== "open") continue;
    const id = String(row.task_id || "").trim();
    const pending = id ? pendingHumanTaskAcks[id] : null;
    if (!pending) continue;
    const durableFp = String(row.finding_fingerprint || "").trim();
    const pendingFp = String(pending.finding_fingerprint || "").trim();
    if (!pendingFp || !durableFp || durableFp === pendingFp) {
      delete pendingHumanTaskAcks[id];
    }
  }
}

/** Durable sidecar rows plus any session-pending acks not yet in git. */
function overlayPendingHumanTaskAcks(acksStore) {
  const byId = Object.create(null);
  for (const row of (acksStore && acksStore.acks) || []) {
    if (!row || typeof row !== "object") continue;
    const id = String(row.task_id || "").trim();
    if (id) byId[id] = row;
  }
  // Session pending always wins until prune confirms durable catch-up.
  // (Previously we skipped when durable already had status=open, which left
  // stale-fingerprint rows on top with Acknowledge still enabled.)
  for (const id of Object.keys(pendingHumanTaskAcks)) {
    byId[id] = pendingHumanTaskAcks[id];
  }
  return {
    schema_version: 1,
    updated_at: (acksStore && acksStore.updated_at) || null,
    acks: Object.keys(byId).map((id) => byId[id]),
  };
}

/**
 * Re-merge pristine board + durable sidecar + session pending into data.
 * Safe to call from sidecars, optimistic clicks, and renderDashboard so an
 * in-flight reload cannot clobber a just-queued ack.
 */
function syncHumanTasksBoardOverlay(data) {
  if (!data) return data;
  const base = humanTasksBoardBase || data.human_tasks_board;
  if (!base || !Array.isArray(base.tasks)) return data;
  prunePendingHumanTaskAcksAgainstDurable(data.human_task_acks);
  const acksForBoard = overlayPendingHumanTaskAcks(data.human_task_acks);
  data.human_tasks_board = (acksForBoard.acks || []).length
    ? mergeHumanTaskAcksIntoBoard(base, acksForBoard)
    : base;
  return data;
}

function refreshHumanTasksBoardView() {
  if (!dashboardData) return;
  // Never no-op the optimistic re-render: if sidecars have not stamped a base
  // yet, use the in-memory board so Acknowledge still moves the card now.
  if (!humanTasksBoardBase && dashboardData.human_tasks_board) {
    humanTasksBoardBase = dashboardData.human_tasks_board;
  }
  if (!humanTasksBoardBase) return;
  syncHumanTasksBoardOverlay(dashboardData);
  renderAutomation(dashboardData);
}

function applyOptimisticHumanTaskAck(payload) {
  rememberPendingHumanTaskAck(payload);
  refreshHumanTasksBoardView();
}

function revertOptimisticHumanTaskAck(taskId) {
  clearPendingHumanTaskAck(taskId);
  refreshHumanTasksBoardView();
}

function dailyRecOverlayKey(payload) {
  const rid = String((payload && payload.recommendation_id) || "").trim();
  if (rid) return rid;
  return String((payload && (payload.task_ref || payload.focus_id)) || "").trim();
}

function rememberPendingDailyAccept(payload) {
  const key = dailyRecOverlayKey(payload);
  if (!key) return;
  pendingDailyAccepts[key] = {
    recommendation_id: String((payload && payload.recommendation_id) || "").trim() || key,
    task_ref: String((payload && payload.task_ref) || "").trim(),
    decision: "accept",
    status: "open",
    local_date: String((payload && payload.local_date) || "").trim(),
    accepted_at: new Date().toISOString(),
    source: "dashboard_optimistic",
  };
}

function clearPendingDailyAccept(key) {
  delete pendingDailyAccepts[String(key || "").trim()];
}

function rememberPendingDailyDiscuss(payload, status) {
  const key = dailyRecOverlayKey(payload);
  if (!key) return;
  pendingDailyDiscuss[key] = {
    recommendation_id: String((payload && payload.recommendation_id) || "").trim() || key,
    status: status || "inflight",
    local_date: String((payload && payload.local_date) || "").trim(),
    queued_at: new Date().toISOString(),
    source: "dashboard_optimistic",
  };
}

function clearPendingDailyDiscuss(key) {
  delete pendingDailyDiscuss[String(key || "").trim()];
}

function prunePendingDailyAcceptsAgainstDurable(data) {
  const hub = dailyFocusBase || (data && data.daily_focus) || null;
  const localDate = String((hub && hub.local_date) || "").trim();
  const acks = (data && data.daily_focus_acks) || null;
  const durableClosed = new Set(
    ((hub && hub.closed_today) || []).map((x) => String(x || "").trim()).filter(Boolean)
  );
  for (const task of (hub && hub.tasks) || []) {
    if (!task || typeof task !== "object") continue;
    if (task.closed) {
      const ref = String(task.task_ref || "").trim();
      const rid = String(task.recommendation_id || "").trim();
      if (ref) durableClosed.add(ref);
      if (rid) durableClosed.add(rid);
    }
  }
  for (const key of Object.keys(pendingDailyAccepts)) {
    const pending = pendingDailyAccepts[key];
    const taskRef = String((pending && pending.task_ref) || "").trim();
    if (durableClosed.has(key) || (taskRef && durableClosed.has(taskRef))) {
      delete pendingDailyAccepts[key];
      continue;
    }
    let matched = false;
    for (const row of (acks && acks.acks) || []) {
      if (!row || typeof row !== "object") continue;
      if (String(row.status || "open") !== "open") continue;
      if (localDate && String(row.local_date || "") !== localDate) continue;
      const decision = String(row.decision || "ack");
      if (!["ack", "accept", "dismiss", "ack_observe"].includes(decision)) continue;
      const ref = String(row.task_ref || row.focus_id || "").trim();
      const rowRid = String(row.recommendation_id || "").trim();
      if (rowRid === key || key === ref || (taskRef && ref === taskRef)) {
        matched = true;
        break;
      }
    }
    if (matched) delete pendingDailyAccepts[key];
  }
}

/**
 * Hide phantom Cap B date ambers when the hub artifact already matches today.
 * Sticky failure mode: Cap B warn re-embedded into daily_focus while
 * hub.local_date already equals Europe/London today (Pages lag / hub-only write).
 */
function healClearedReconcileTasks(hub, now = new Date()) {
  if (!hub || !Array.isArray(hub.tasks)) return hub;
  let today = "";
  try {
    today = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/London",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(now);
  } catch {
    today = now.toISOString().slice(0, 10);
  }
  const hubDate = String(hub.local_date || "").trim();
  if (!hubDate || hubDate !== today) return hub;
  const healRef = "reconcile:daily_hub_local_date_matches_today";
  let changed = false;
  const tasks = hub.tasks.map((task) => {
    if (!task || typeof task !== "object" || task.closed) return task;
    if (String(task.task_ref || "").trim() !== healRef) return task;
    changed = true;
    return {
      ...task,
      closed: true,
      closed_healed: true,
      closed_reason: "hub_local_date_matches_today",
    };
  });
  if (!changed) return hub;
  const closedToday = new Set(
    (hub.closed_today || []).map((x) => String(x || "").trim()).filter(Boolean)
  );
  closedToday.add(healRef);
  const openTasks = tasks.filter((t) => t && !t.closed);
  const counts = { ...(hub.counts || {}) };
  counts.reconcile = openTasks.filter((t) => t.source === "ui_reconcile").length;
  return {
    ...hub,
    tasks,
    open_task_count: openTasks.length,
    closed_today: Array.from(closedToday),
    counts,
  };
}

/** Mark accepted tasks closed via session pending until durable hub catch-up. */
function applyPendingDailyOverlays(base) {
  if (!base || !Array.isArray(base.tasks)) return base;
  const pendingKeys = Object.keys(pendingDailyAccepts);
  if (!pendingKeys.length) return base;
  const tasks = base.tasks.map((task) => {
    if (!task || typeof task !== "object") return task;
    const rid = String(task.recommendation_id || (task.recommendation && task.recommendation.id) || "").trim();
    const ref = String(task.task_ref || "").trim();
    const hit =
      (rid && pendingDailyAccepts[rid]) ||
      (ref && pendingDailyAccepts[ref]) ||
      null;
    if (!hit) return task;
    return { ...task, closed: true, closed_optimistic: true };
  });
  const closedToday = new Set(
    (base.closed_today || []).map((x) => String(x || "").trim()).filter(Boolean)
  );
  for (const key of pendingKeys) {
    closedToday.add(key);
    const ref = String((pendingDailyAccepts[key] && pendingDailyAccepts[key].task_ref) || "").trim();
    if (ref) closedToday.add(ref);
  }
  const openCount = tasks.filter((t) => t && !t.closed).length;
  return {
    ...base,
    tasks,
    open_task_count: openCount,
    closed_today: Array.from(closedToday),
  };
}

/**
 * Re-merge pristine daily hub + session Accept/Discuss overlays into data.
 * Soft reload / sidecar merge must not re-enable Accept after an optimistic click.
 */
function syncDailyFocusOverlay(data) {
  if (!data) return data;
  let base = dailyFocusBase || data.daily_focus;
  if (!base || !Array.isArray(base.tasks)) return data;
  const healed = healClearedReconcileTasks(base);
  if (healed !== base) {
    dailyFocusBase = healed;
    base = healed;
  }
  prunePendingDailyAcceptsAgainstDurable(data);
  data.daily_focus = applyPendingDailyOverlays(base);
  return data;
}

function refreshDailyHubView() {
  if (!dashboardData) return;
  if (!dailyFocusBase && dashboardData.daily_focus) {
    dailyFocusBase = dashboardData.daily_focus;
  }
  if (!dailyFocusBase) return;
  syncDailyFocusOverlay(dashboardData);
  renderAutomation(dashboardData);
}

function applyOptimisticDailyAccept(payload) {
  rememberPendingDailyAccept(payload);
  refreshDailyHubView();
}

function revertOptimisticDailyAccept(key) {
  clearPendingDailyAccept(key);
  refreshDailyHubView();
}

function dailyRecRowState(recId) {
  const id = String(recId || "").trim();
  const accepted = !!(id && pendingDailyAccepts[id]);
  const discuss = id ? pendingDailyDiscuss[id] : null;
  const discussInflight = !!(discuss && discuss.status === "inflight");
  const discussQueued = !!(discuss && (discuss.status === "queued" || discuss.status === "inflight"));
  return {
    accepted,
    discussLocked: discussQueued,
    // Accept stays available after Discuss succeeds; only lock during Discuss in-flight.
    acceptDisabled: accepted || discussInflight,
    discussDisabled: accepted || discussQueued,
  };
}

function disableDailyRecRowButtons(button, { accept = true, discuss = true } = {}) {
  const block = button && button.closest && button.closest(".daily-rec-block");
  if (!block) {
    if (button && accept) {
      button.disabled = true;
      button.setAttribute("aria-disabled", "true");
    }
    return block;
  }
  if (accept) {
    block.querySelectorAll("[data-daily-accept]").forEach((btn) => {
      btn.disabled = true;
      btn.setAttribute("aria-disabled", "true");
    });
  }
  if (discuss) {
    block.querySelectorAll("[data-daily-discuss]").forEach((btn) => {
      btn.disabled = true;
      btn.setAttribute("aria-disabled", "true");
    });
  }
  block.querySelectorAll("[data-daily-option]").forEach((btn) => {
    btn.disabled = true;
    btn.setAttribute("aria-disabled", "true");
  });
  return block;
}

function enableDailyRecRowButtons(button, { accept = true, discuss = true } = {}) {
  const block = button && button.closest && button.closest(".daily-rec-block");
  if (!block) {
    if (button && accept) {
      button.disabled = false;
      button.setAttribute("aria-disabled", "false");
    }
    return;
  }
  if (accept) {
    block.querySelectorAll("[data-daily-accept]").forEach((btn) => {
      btn.disabled = false;
      btn.setAttribute("aria-disabled", "false");
    });
  }
  if (discuss) {
    block.querySelectorAll("[data-daily-discuss]").forEach((btn) => {
      btn.disabled = false;
      btn.setAttribute("aria-disabled", "false");
    });
  }
  block.querySelectorAll("[data-daily-option]").forEach((btn) => {
    btn.disabled = false;
    btn.setAttribute("aria-disabled", "false");
  });
}

function setHumanTaskAckStatus(taskId, text) {
  const id = String(taskId || "").trim();
  if (!id) return;
  const panel = document.getElementById("panel-automation");
  if (!panel) return;
  const escape =
    (window.CSS && typeof window.CSS.escape === "function" && window.CSS.escape.bind(window.CSS)) ||
    ((value) => String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"'));
  const card = panel.querySelector(`.human-task-card[data-task-id="${escape(id)}"]`);
  const el = card && card.querySelector(".human-task-ack-status");
  if (el) el.textContent = text || "";
}

function sidecarGeneratedAtMs(payload) {
  if (!payload || typeof payload !== "object") return NaN;
  const ms = Date.parse(String(payload.generated_at || ""));
  return Number.isFinite(ms) ? ms : NaN;
}

/** Email-report excludes project_progress.json (L484), so the sidecar can lag
 *  the Sunday publish embed. Do not hide a newer embed's generated_at. */
function shouldOverlayDashboardSidecar(key, existing, sidecar) {
  if (!sidecar) return false;
  if (key !== "project_progress" || !existing) return true;
  const sidecarMs = sidecarGeneratedAtMs(sidecar);
  const embedMs = sidecarGeneratedAtMs(existing);
  if (Number.isFinite(sidecarMs) && Number.isFinite(embedMs) && sidecarMs < embedMs) {
    return false;
  }
  return true;
}

async function applyDashboardSidecars(data) {
  const rows = await Promise.all(
    DASHBOARD_SIDECARS.map(async ([key, path]) => [key, await loadOptionalDashboardJson(path)])
  );
  for (const [key, payload] of rows) {
    if (!shouldOverlayDashboardSidecar(key, data[key], payload)) continue;
    data[key] = payload;
  }
  // Acks sidecar is source of truth; board JSON can lag when the ack workflow
  // only committed human_task_acks.json (weekend drain / commit race).
  // Session pending overlay covers the gap between Supabase queue and Pages git.
  if (data.human_tasks_board) {
    // Keep the network board pristine so later sync/re-render can re-merge.
    humanTasksBoardBase = data.human_tasks_board;
    syncHumanTasksBoardOverlay(data);
  }
  // Daily hub Accept/Discuss: keep network daily_focus pristine; session overlay
  // marks accepted rows closed so soft reload cannot re-enable the buttons.
  if (data.daily_focus) {
    dailyFocusBase = data.daily_focus;
    syncDailyFocusOverlay(data);
  }
  // Post-sale Accept/Comment/Duplicate: keep cleared across soft reload until
  // labels sidecar / queue rebuild catches up (same pattern as daily hub).
  if (data.post_sale_review_queue) {
    syncPostSaleQueueOverlay(data);
  }
  // Entry-blind Accept/Comment/Duplicate — same overlay class as post-sale (#1196/#1205).
  if (data.entry_blind_review_queue) {
    syncEntryBlindQueueOverlay(data);
  }
  return data;
}

function isLocalDashboardServe() {
  return location.hostname === "127.0.0.1" || location.hostname === "localhost";
}

async function refreshLocalMarketStatus() {
  if (!isLocalDashboardServe()) return false;
  try {
    const response = await fetch("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function reloadDashboard({ silent, rebuild } = {}) {
  if (dashboardRefreshInFlight) return dashboardRefreshInFlight;
  dashboardRefreshInFlight = (async () => {
    try {
      if (rebuild) await refreshLocalMarketStatus();
      if (!silent) {
        const meta = document.getElementById("run-meta");
        if (meta && !dashboardData) meta.textContent = "Loading dashboard…";
      }
      const data = await fetchDashboardJson("data/latest.json");
      await applyDashboardSidecars(data);
      renderDashboard(data);
      dashboardLastLoadedAt = Date.now();
      return data;
    } finally {
      dashboardRefreshInFlight = null;
    }
  })();
  return dashboardRefreshInFlight;
}

function bindDashboardAutoRefresh() {
  if (window.__dashboardAutoRefreshBound) return;
  window.__dashboardAutoRefreshBound = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (Date.now() - dashboardLastLoadedAt < DASHBOARD_VISIBLE_RELOAD_MS) return;
    void reloadDashboard({ silent: true, rebuild: true });
  });
  window.addEventListener("focus", () => {
    if (Date.now() - dashboardLastLoadedAt < DASHBOARD_VISIBLE_RELOAD_MS) return;
    void reloadDashboard({ silent: true, rebuild: true });
  });
  if (window.DashboardBridge) {
    void window.DashboardBridge.init().then((ready) => {
      if (!ready) return;
      window.DashboardBridge.onArtifactUpdated(() => {
        void reloadDashboard({ silent: true, rebuild: true });
      });
    });
  }
}

async function openProgressReportMarkdown() {
  const dialog = document.getElementById("memo-dialog");
  const title = document.getElementById("memo-title");
  const body = document.getElementById("memo-body");
  title.textContent = "Progress report";
  body.innerHTML = "<p class='muted'>Loading report…</p>";
  dialog.showModal();
  try {
    const response = await fetch(`data/progress_report.md?ts=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("progress_report.md not found");
    const markdown = await response.text();
    body.innerHTML = marked.parse(markdown);
  } catch (err) {
    body.innerHTML = `<p class="muted">Could not load progress report (${esc(err.message)}).</p>`;
  }
}

async function reloadProgressReportIntoDashboard() {
  setProgressReportStatus("Reloading published dashboard…");
  try {
    const data = await reloadDashboard({ silent: true, rebuild: true });
    const report = (data || {}).progress_report || {};
    setProgressReportStatus(`Reloaded · generated ${fmtDate(report.generated_at)}`);
  } catch (err) {
    setProgressReportStatus(`Reload failed: ${err.message}`, true);
  }
}

async function githubApiFetch(path, { method = "GET", token, body } = {}) {
  return fetch(`https://api.github.com${path}`, {
    method,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

async function dispatchProgressReportWorkflow(token) {
  const response = await githubApiFetch(
    `/repos/${PROGRESS_REPORT_GH_REPO}/actions/workflows/${PROGRESS_REPORT_WORKFLOW}/dispatches`,
    {
      method: "POST",
      token,
      body: { ref: "main", inputs: { force: "true" } },
    }
  );
  if (response.status === 204) return;
  let detail = `HTTP ${response.status}`;
  try {
    const payload = await response.json();
    detail = payload.message || detail;
  } catch {
    /* ignore */
  }
  if (response.status === 401 || response.status === 403) {
    throw new Error(`GitHub auth failed (${detail}). Check the PAT scopes.`);
  }
  if (response.status === 404) {
    throw new Error(
      `Workflow ${PROGRESS_REPORT_WORKFLOW} not found on main yet, or PAT lacks access.`
    );
  }
  throw new Error(detail);
}

async function waitForProgressReportWorkflowRun(token, notBeforeMs, onStatus) {
  const deadline = Date.now() + 8 * 60 * 1000;
  let run = null;
  while (Date.now() < deadline) {
    const response = await githubApiFetch(
      `/repos/${PROGRESS_REPORT_GH_REPO}/actions/workflows/${PROGRESS_REPORT_WORKFLOW}/runs?event=workflow_dispatch&per_page=5`,
      { token }
    );
    if (!response.ok) throw new Error(`Could not list workflow runs (HTTP ${response.status})`);
    const payload = await response.json();
    run = (payload.workflow_runs || []).find(
      (row) => Date.parse(row.created_at) >= notBeforeMs - 5000
    );
    if (run) break;
    if (onStatus) onStatus("Waiting for Actions run to start…");
    await sleepMs(4000);
  }
  if (!run) throw new Error("Timed out waiting for the progress-report workflow to start");

  while (Date.now() < deadline) {
    const response = await githubApiFetch(
      `/repos/${PROGRESS_REPORT_GH_REPO}/actions/runs/${run.id}`,
      { token }
    );
    if (!response.ok) throw new Error(`Could not read workflow run (HTTP ${response.status})`);
    run = await response.json();
    if (run.status === "completed") {
      if (run.conclusion !== "success") {
        throw new Error(
          `Actions run ${run.conclusion || "failed"} — see ${run.html_url || PROGRESS_REPORT_ACTIONS_URL}`
        );
      }
      return run;
    }
    if (onStatus) onStatus(`Actions running (${run.status})…`);
    await sleepMs(8000);
  }
  throw new Error("Timed out waiting for the progress-report workflow to finish");
}

async function waitForPublishedProgressReport(previousGeneratedAt, onStatus) {
  const prev = previousGeneratedAt ? Date.parse(previousGeneratedAt) : 0;
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    try {
      const report = await fetchProgressReportJson();
      const next = report.generated_at ? Date.parse(report.generated_at) : 0;
      if (next && (!prev || next > prev)) {
        return report;
      }
    } catch {
      /* Pages may briefly 404 mid-deploy */
    }
    if (onStatus) onStatus("Workflow finished — waiting for GitHub Pages deploy…");
    await sleepMs(10000);
  }
  throw new Error(
    "Report commit may be done, but Pages has not published the new JSON yet. Try Reload in a minute."
  );
}

async function generateProgressReportViaGithubActions(token) {
  const previousGeneratedAt =
    dashboardData && dashboardData.progress_report
      ? dashboardData.progress_report.generated_at
      : null;
  const startedAt = Date.now();
  setProgressReportStatus("Dispatching progress-report workflow…");
  await dispatchProgressReportWorkflow(token);
  await waitForProgressReportWorkflowRun(token, startedAt, setProgressReportStatus);
  setProgressReportStatus("Workflow succeeded — waiting for Pages…");
  const report = await waitForPublishedProgressReport(previousGeneratedAt, setProgressReportStatus);
  setProgressReportStatus("Published — refreshing dashboard…");
  await reloadDashboard({ silent: true });
  setProgressReportStatus(
    `Generated ${fmtDate(report.generated_at)} · overall ${String(report.overall || "").toUpperCase()}`
  );
}

async function generateProgressReportViaBridge(onStatus) {
  const previousGeneratedAt =
    dashboardData && dashboardData.progress_report
      ? dashboardData.progress_report.generated_at
      : null;
  await window.DashboardBridge.submitCommand(
    "progress-report",
    { force: true },
    onStatus
  );
  setProgressReportStatus("Workflow finished — waiting for Pages…");
  const report = await waitForPublishedProgressReport(previousGeneratedAt, onStatus);
  setProgressReportStatus("Published — refreshing dashboard…");
  await reloadDashboard({ silent: true, rebuild: true });
  setProgressReportStatus(
    `Generated ${fmtDate(report.generated_at)} · overall ${String(report.overall || "").toUpperCase()}`
  );
}

async function generateProgressReportFromUi() {
  const btn = document.getElementById("progress-report-generate-btn");
  if (btn) btn.disabled = true;
  setProgressReportStatus("Generating fresh report…");
  try {
    const response = await fetch("/api/progress-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (response.ok) {
      const payload = await response.json();
      if (!payload.ok || !payload.report) {
        throw new Error(payload.error || "Generate API returned no report");
      }
      await reloadDashboard({ silent: true, rebuild: true });
      setProgressReportStatus(
        `Generated ${fmtDate(payload.report.generated_at)} · overall ${String(payload.report.overall || "").toUpperCase()}`
      );
      return;
    }
    if (response.status === 404 || response.status === 405) {
      throw new Error("API_UNAVAILABLE");
    }
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.error || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  } catch (err) {
    const unavailable = String(err.message) === "API_UNAVAILABLE" || err instanceof TypeError;
    if (!unavailable) {
      setProgressReportStatus(`Generate failed: ${err.message}`, true);
      return;
    }
    if (window.DashboardBridge) {
      try {
        const bridgeReady = await window.DashboardBridge.init();
        if (bridgeReady) {
          await generateProgressReportViaBridge(setProgressReportStatus);
          return;
        }
      } catch (bridgeErr) {
        if (String(bridgeErr.message) !== "BRIDGE_DISABLED") {
          const msg = String(bridgeErr.message || bridgeErr);
          if (/timed out waiting for dashboard command/i.test(msg)) {
            setProgressReportStatus(
              "Queued in Supabase, but the GitHub bridge worker has not picked it up yet. Run Actions → Dashboard bridge worker → Run workflow, then Reload.",
              true
            );
            return;
          }
          setProgressReportStatus(`Bridge generate failed: ${msg}`, true);
          return;
        }
      }
    }
    const token = getProgressReportPat();
    if (!token) {
      showProgressReportPatPrompt(
        "Supabase bridge unavailable. Prefer enabling data/dashboard_config.json, or save a legacy PAT as a last resort."
      );
      return;
    }
    try {
      await generateProgressReportViaGithubActions(token);
    } catch (remoteErr) {
      setProgressReportStatus(
        `Remote generate failed: ${remoteErr.message}`,
        true
      );
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function handleProgressReportPatSave() {
  const input = document.getElementById("progress-report-pat-input");
  const typed = input ? String(input.value || "").trim() : "";
  const token = typed || getProgressReportPat();
  if (!token) {
    setProgressReportStatus("Paste a fine-grained PAT with Actions: Write first.", true);
    return;
  }
  if (typed) saveProgressReportPat(typed);
  void generateProgressReportFromUi();
}

function bindProgressReportActions() {
  const panel = document.getElementById("panel-overview");
  if (!panel || panel.dataset.progressReportBound === "1") return;
  panel.dataset.progressReportBound = "1";
  panel.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target || !panel.contains(target)) return;
    if (target.id === "progress-report-generate-btn") {
      event.preventDefault();
      void generateProgressReportFromUi();
    } else if (target.id === "progress-report-reload-btn") {
      event.preventDefault();
      void reloadProgressReportIntoDashboard();
    } else if (target.id === "progress-report-view-btn") {
      event.preventDefault();
      void openProgressReportMarkdown();
    } else if (target.id === "progress-report-token-btn") {
      event.preventDefault();
      showProgressReportPatPrompt("Legacy fallback only — prefer Supabase Generate / Dashboard bridge worker.");
    } else if (target.id === "progress-report-pat-save-btn") {
      event.preventDefault();
      handleProgressReportPatSave();
    } else if (target.id === "progress-report-pat-actions-btn") {
      event.preventDefault();
      window.open(PROGRESS_REPORT_ACTIONS_URL, "_blank", "noopener");
    } else if (target.id === "progress-report-pat-clear-btn") {
      event.preventDefault();
      clearProgressReportPat();
      setProgressReportStatus("Cleared saved Pages generate token.");
    } else if (target.hasAttribute("data-progress-ack")) {
      event.preventDefault();
      void acknowledgeLifecycleExperimentFromProgressReport(target);
    } else if (target.dataset.marketId) {
      event.preventDefault();
      openMarketStatusCard(target.dataset.marketId);
    } else if (target.dataset.systemGapId) {
      event.preventDefault();
      openSystemGapCard(target.dataset.systemGapId);
    }
  });
}

window.__generateProgressReport = generateProgressReportFromUi;
window.__reloadProgressReport = reloadProgressReportIntoDashboard;
window.__openProgressReport = openProgressReportMarkdown;

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

  const stalled = Boolean(ingest.stalled);
  const ingestHtml =
    ingest.summary && stalled
      ? `
    <div class="card overview-alert-card" style="margin-top:1rem">
      <h3>Ingest bottleneck</h3>
      <p class="small">${esc(ingest.summary)}</p>
      <p class="small"><strong>Status:</strong> stalled (zero_body_buy_tier=${esc(String(ingest.zero_body_buy_tier ?? "—"))})</p>
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
          <h4>Next actions</h4>
          ${list(appraisal.next_actions)}
          <h4 style="margin-top:1rem">Gaps</h4>
          ${list(appraisal.gaps)}
        </section>
        <section class="automation-section">
          <h4>Strengths</h4>
          ${list(appraisal.strengths)}
        </section>
      </div>
      <details class="overview-secondary" style="margin-top:0.75rem">
        <summary>North-star stages</summary>
        <div style="margin-top:0.5rem">${stageRows}</div>
      </details>
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

const MARKET_INGEST_LABELS = {
  live: "live ingest",
  sprint: "sprint",
  maintenance: "maintenance",
  queued: "queued",
  idle: "idle",
};

/** Learning-path roles (ops taxonomy) — distinct from ingest capacity chips. */
const MARKET_ROLE_META = {
  live: {
    label: "live screen",
    cls: "mrole-live",
    title: "FTSE live screener / P1 paper path — not library maintenance success",
  },
  focus: {
    label: "focus",
    cls: "mrole-focus",
    title: "Ladder focus — research target + weekly-paper slot (N94 capacity-1)",
  },
  admitted: {
    label: "admitted",
    cls: "mrole-admitted",
    title: "L322 equal-resource package (epoch-0) — not AI judgment; not a graduated synonym",
  },
  queue: {
    label: "queue",
    cls: "mrole-queue",
    title: "On market_queue — eligible for parallel sprint; not yet admitted",
  },
  graduated: {
    label: "graduated",
    cls: "mrole-graduated",
    title: "Sprint complete / Layer A — breadth ≠ admission (may still be not admitted)",
  },
  ftse_equivalent: {
    label: "FTSE-eq",
    cls: "mrole-ftse-eq",
    title: "FTSE-equivalent depth measurement — parallel ingest, not live expansion",
  },
  sprint: {
    label: "sprint role",
    cls: "mrole-sprint",
    title: "Active deepen sprint (fat or spare stream)",
  },
};

const MARKET_INGEST_TITLES = {
  live: "Live FTSE ingest capacity (P1) — distinct from learning-role chips",
  sprint: "Active deepen sprint stream",
  maintenance: "Steady-state FTSE-volume maintenance — not admission / not live-screen success",
  queued: "Waiting on market_queue for a sprint slot",
  idle: "No active ingest stream",
};

function spareSprintLabel(spare) {
  if (!spare || typeof spare !== "object") return "";
  const parts = Object.keys(spare)
    .sort((a, b) => Number(a) - Number(b))
    .map((key) => `${key}=${spare[key]}`)
    .filter((part) => part.includes("=") && !part.endsWith("="));
  return parts.length ? ` · spare sprint ${esc(parts.join(" · "))}` : "";
}

function marketIngestBadge(ingest, stream) {
  const key = String(ingest || "idle");
  const cls = {
    live: "mingest-live",
    sprint: "mingest-sprint",
    maintenance: "mingest-maintenance",
    queued: "mingest-queued",
    idle: "mingest-idle",
  };
  let label = MARKET_INGEST_LABELS[key] || key;
  if (key === "sprint" && stream) {
    label = `sprint ${stream}`;
  }
  const title = MARKET_INGEST_TITLES[key] || key;
  return `<span class="stage-badge market-ingest-badge ${cls[key] || "mingest-idle"}" title="${esc(title)}">${esc(label)}</span>`;
}

function marketRoleBadge(roleKey) {
  const meta = MARKET_ROLE_META[roleKey];
  if (!meta) return "";
  return `<span class="stage-badge market-role-badge ${meta.cls}" title="${esc(meta.title)}">${esc(meta.label)}</span>`;
}

/**
 * Learning-role chips for a market row.
 * Axes are independent: ingest capacity ≠ learning admission ≠ live screen.
 * Show primary published `role` plus modifiers that add information.
 */
function marketLearningRoleChips(row) {
  if (!row) return "";
  const chips = [];
  const role = String(row.role || "");
  const seen = new Set();
  const push = (key) => {
    if (!key || seen.has(key) || !MARKET_ROLE_META[key]) return;
    seen.add(key);
    chips.push(marketRoleBadge(key));
  };
  if (role && role !== "other") push(role);
  else if (row.is_live) push("live");
  if (row.is_focus) push("focus");
  if (row.is_admitted) push("admitted");
  // Graduated without admission is the conflation operators mis-read — surface it.
  if (row.is_graduated && !row.is_admitted) push("graduated");
  if (row.is_queue && !row.is_admitted && role !== "sprint") push("queue");
  if (row.is_ftse_equivalent) push("ftse_equivalent");
  return chips.join("");
}

function marketStatusBadgeLegend() {
  return `<p class="small muted market-status-legend">
    <span class="market-status-legend-axis"><strong>Ingest</strong> (capacity)
      ${marketIngestBadge("live")}
      ${marketIngestBadge("sprint")}
      ${marketIngestBadge("maintenance")}
      ${marketIngestBadge("queued")}</span>
    <span class="market-status-legend-axis"><strong>Learning role</strong> (path)
      ${marketRoleBadge("live")}
      ${marketRoleBadge("focus")}
      ${marketRoleBadge("admitted")}
      ${marketRoleBadge("queue")}
      ${marketRoleBadge("graduated")}
      ${marketRoleBadge("ftse_equivalent")}</span>
    <span class="market-status-legend-axis"><strong>Learning gate</strong>
      Start → Bodies → Sprint → Admit → Epoch-0 → Parity → Live</span>
    <span class="market-status-legend-note">graduated ≠ admitted · maintenance ≠ live screen · live FTSE is live-path, not self catch-up</span>
  </p>`;
}

function learningBookLine(row) {
  const label = (row && row.learning_phase_label) || "Not started";
  return `Learning · ${label}`;
}

function renderLearningGateIndicator(gate, { compact = false } = {}) {
  if (!gate || !Array.isArray(gate.steps) || !gate.steps.length) return "";
  const steps = gate.steps
    .map((step) => {
      const status = String(step.status || "pending");
      return `<li class="learning-gate-step is-${esc(status)}" title="${esc(
        `${step.label} (${step.gate || ""}) — ${status}`
      )}"><span class="learning-gate-dot" aria-hidden="true"></span><span class="learning-gate-label">${esc(
        step.label
      )}</span></li>`;
    })
    .join("");
  const next = gate.next_gate || {};
  const note = compact
    ? `${next.name || "Next gate"}: ${next.criteria || ""} Timeframe: ${next.timeframe || ""}`
    : gate.annotation || "";
  return `<div class="learning-gate" data-current="${esc(gate.current_id || "")}">
    <ol class="learning-gate-track" aria-label="Start through FTSE-parity to live-ready">${steps}</ol>
    <p class="small muted learning-gate-note">${esc(note)}</p>
  </div>`;
}

const ADMISSION_FLAG_LABELS = {
  no_ingest_in_window: "no recent ingest",
  awaiting_first_ingest: "awaiting first ingest",
  runtime_cutoff: "runtime cutoff",
  ingest_errors: "ingest errors",
  zero_improve_stall: "0-improve stall",
  unmeasured_stuck: "unmeasured stuck",
  zero_body_stuck: "zero-body stuck",
  stale_buy_tier_screen: "stale screen",
  no_observe_benchmark: "no benchmark",
};

function _signedDelta(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "0";
  return n > 0 ? `+${n}` : String(n);
}

function sprintProgressLine(progress) {
  if (!progress) return "";
  const remaining = progress.remaining || {};
  const delta = progress.gap_delta || {};
  const runs = Number(progress.run_count || 0);
  const ingestBits = [
    `${progress.window_days || 2}d: ${runs} run${runs === 1 ? "" : "s"}`,
    `${esc(String(progress.improved ?? 0))} improved`,
    `${esc(String(progress.targets ?? 0))} tgt`,
  ];
  if (delta.indexed_without_body) {
    ingestBits.push(`IWB ${_signedDelta(delta.indexed_without_body)}`);
  } else if (delta.filing_gaps) {
    ingestBits.push(`gaps ${_signedDelta(delta.filing_gaps)}`);
  }
  const remainBits = [
    remaining.unmeasured ? `unmeas ${remaining.unmeasured}` : "",
    remaining.zero_body ? `zero ${remaining.zero_body}` : "",
    remaining.thin ? `thin ${remaining.thin}` : "",
    remaining.indexed_without_body ? `IWB ${remaining.indexed_without_body}` : "",
  ].filter(Boolean);
  const remainLine = progress.admission_ready
    ? '<div class="small muted market-tile-sprint-remain">to admit: filing bar met</div>'
    : remainBits.length
      ? `<div class="small muted market-tile-sprint-remain">to admit: ${esc(remainBits.join(" · "))}</div>`
      : '<div class="small muted market-tile-sprint-remain">to admit: waiting on filing snapshot</div>';
  const flags = progress.admission_warnings || [];
  const flagHtml = flags.length
    ? `<div class="market-tile-flags">${flags
        .slice(0, 3)
        .map((flag) => {
          const high = String(flag.severity || "") === "high";
          const label = ADMISSION_FLAG_LABELS[flag.id] || flag.id;
          return `<span class="admission-flag${high ? " admission-flag-high" : ""}">${esc(
            label
          )}</span>`;
        })
        .join("")}${
        flags.length > 3
          ? `<span class="admission-flag">+${flags.length - 3}</span>`
          : ""
      }</div>`
    : "";
  return `<div class="market-tile-sprint">
      <div class="small market-tile-sprint-ingest">${ingestBits.join(" · ")}</div>
      ${remainLine}
      ${flagHtml}
    </div>`;
}

function renderSprintProgressCard(progress) {
  if (!progress) return "";
  const remaining = progress.remaining || {};
  const before = progress.gaps_before || {};
  const after = progress.gaps_after || {};
  const delta = progress.gap_delta || {};
  const flags = progress.admission_warnings || [];
  const improved = (progress.improved_tickers || []).slice(0, 8);
  const flagHtml = flags.length
    ? `<ul class="list-plain small">${flags
        .map((flag) => {
          const high = String(flag.severity || "") === "high";
          const label = ADMISSION_FLAG_LABELS[flag.id] || flag.id;
          return `<li><span class="admission-flag${
            high ? " admission-flag-high" : ""
          }">${esc(label)}</span> ${esc(flag.summary || "")}</li>`;
        })
        .join("")}</ul>`
    : '<p class="muted small">No admission-progress flags. Remaining filing work is the sprint itself.</p>';
  return `
    <h4 class="small" style="margin-top:1rem">Last ${esc(String(progress.window_days || 2))} days ingest</h4>
    ${settingRow("Runs", esc(String(progress.run_count ?? 0)))}
    ${settingRow("Targets / improved", `${esc(String(progress.targets ?? 0))} tgt · ${esc(String(progress.improved ?? 0))} improved`)}
    ${settingRow("Last ingest", `<span class="small">${esc(fmtDate(progress.last_run_at))}</span>`)}
    ${
      improved.length
        ? settingRow("Improved names", `<span class="small">${improved.map((t) => esc(t)).join(", ")}</span>`)
        : ""
    }
    ${settingRow(
      "Gap change",
      esc(
        `unmeas ${before.unmeasured ?? 0}→${after.unmeasured ?? 0} (${_signedDelta(delta.unmeasured)}) · zero ${before.zero_body ?? 0}→${after.zero_body ?? 0} (${_signedDelta(delta.zero_body)}) · thin ${before.thin ?? 0}→${after.thin ?? 0} (${_signedDelta(delta.thin)}) · IWB ${before.indexed_without_body ?? 0}→${after.indexed_without_body ?? 0} (${_signedDelta(delta.indexed_without_body)})`
      )
    )}
    ${settingRow(
      "Remaining to admit",
      esc(
        progress.admission_ready
          ? "sprint_ingest_complete (raw parity or leftover thin/IWB parked)"
          : `unmeas ${remaining.unmeasured ?? 0} · zero ${remaining.zero_body ?? 0} · thin ${remaining.thin ?? 0} · IWB ${remaining.indexed_without_body ?? 0}`
      )
    )}
    <h4 class="small" style="margin-top:1rem">Admission flags</h4>
    ${flagHtml}
  `;
}

function marketHealthBadge(health) {
  return overallStatusBadge(health);
}

function marketSignalBar(counts) {
  const entries = Object.entries(counts || {});
  const total = entries.reduce((sum, [, count]) => sum + Number(count || 0), 0);
  if (!total) {
    return '<div class="signal-bar market-tile-bar"><span class="market-tile-bar-empty"></span></div>';
  }
  const segments = entries
    .sort((a, b) => b[1] - a[1])
    .map(([signal, count]) => {
      const width = (Number(count) / total) * 100;
      return `<span style="width:${width}%;background:${SIGNAL_COLORS[signal] || "#999"}" title="${esc(signal)}: ${count}"></span>`;
    })
    .join("");
  return `<div class="signal-bar market-tile-bar">${segments}</div>`;
}

function marketSignalSummary(row) {
  const counts = row.signal_counts || {};
  const parts = [
    ["buy", _intOrZero(counts.strong_buy) + _intOrZero(counts.buy)],
    ["hold", _intOrZero(counts.hold)],
    ["avoid", _intOrZero(counts.avoid)],
  ].filter(([, count]) => count > 0);
  if (!parts.length) return '<span class="muted">No screen yet</span>';
  return parts.map(([label, count]) => `${esc(label)} ${count}`).join(" · ");
}

function _intOrZero(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function coverageLabel(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(0)}%`;
}

function findSystemGapFlag(flagId) {
  const flags = ((dashboardData || {}).system_gaps || {}).flags || [];
  return flags.find((row) => row.id === flagId) || null;
}

function systemGapSeverityBadge(severity) {
  const key = String(severity || "info");
  const cls = key === "high" ? "badge-action" : key === "medium" ? "badge-watch" : "badge-info";
  return `<span class="badge ${cls}">${esc(key)}</span>`;
}

function openSystemGapCard(flagId) {
  const dialog = document.getElementById("system-gaps-dialog");
  const title = document.getElementById("system-gaps-title");
  const body = document.getElementById("system-gaps-body");
  if (!dialog || !title || !body) return;
  const row = findSystemGapFlag(flagId);
  if (!row) {
    title.textContent = "System gap";
    body.innerHTML = `<p class="muted">No flag for <code>${esc(flagId)}</code>.</p>`;
    dialog.showModal();
    return;
  }
  title.textContent = row.title || row.id;
  const docUrl = githubOpsDocUrl("docs/ops/analysis-review.md", "system-gaps-learning-path-integrity");
  body.innerHTML = `
    <p class="small muted" style="margin-top:0">${esc(row.id)} · ${esc(row.layer || "—")}</p>
    <div class="market-card-badges">
      ${systemGapSeverityBadge(row.severity)}
      <span class="badge badge-info">${esc(row.layer || "layer")}</span>
    </div>
    <p>${esc(row.summary || "")}</p>
    <p class="small muted">
      Persist/publish/apply high flags auto-queue as <code>eng-sgap-*</code>
      (no agent dispatch). Produce / learning-clock flags stay on
      <code>ftse-analysis-review promote</code>.
    </p>
    ${docUrl ? `<p class="small"><a href="${esc(docUrl)}" target="_blank" rel="noopener">System-gaps runbook</a></p>` : ""}
  `;
  dialog.showModal();
}

function renderLearningCompletenessCard(data) {
  const payload = data.learning_data_completeness;
  const docUrl = githubOpsDocUrl("docs/ops/post-run-improvement-clearance.md");
  if (!payload || payload.score == null) {
    return `
    <section class="card learning-completeness-section" id="learning-completeness-card">
      <div class="market-status-header">
        <h3>Learning data completeness</h3>
      </div>
      <p class="muted small">Score not published yet — needs <code>system_gaps.json</code> from Sunday analysis-review.</p>
    </section>`;
  }
  const score = Number(payload.score);
  const band = String(payload.band || "partial");
  const bandCls =
    band === "strong" ? "badge-info" : band === "weak" ? "badge-action" : "badge-watch";
  const components = payload.components || {};
  const rows = Object.entries(components)
    .map(([key, row]) => {
      const pct = Number(row.score_pct);
      const bar = Number.isFinite(pct)
        ? `<div class="signal-bar" style="height:6px;margin-top:4px"><span style="width:${pct}%;background:var(--accent)"></span></div>`
        : "";
      return `<div class="setting-row" style="flex-direction:column;align-items:stretch">
        <div style="display:flex;justify-content:space-between;gap:0.5rem">
          <span class="setting-label">${esc(key.replace(/_/g, " "))}</span>
          <span class="setting-value">${Number.isFinite(pct) ? `${pct}%` : "—"}</span>
        </div>
        ${bar}
        <span class="small muted">${esc(row.detail || "")}</span>
      </div>`;
    })
    .join("");
  return `
    <section class="card learning-completeness-section" id="learning-completeness-card">
      <div class="market-status-header">
        <h3>Learning data completeness</h3>
        <p class="small muted" style="margin:0">
          Composite wiring + bodies + gap penalty (not memo prose length).
          ${payload.assessed_at ? ` · ${esc(fmtDate(payload.assessed_at))}` : ""}
        </p>
      </div>
      <div style="display:flex;align-items:baseline;gap:0.75rem;margin:0.5rem 0">
        <div class="stat-value">${esc(String(score))}</div>
        <span class="badge ${bandCls}">${esc(band)}</span>
      </div>
      <p class="small">${esc(payload.summary || "")}</p>
      <div class="grid" style="margin-top:0.75rem">${rows}</div>
      ${docUrl ? `<p class="small" style="margin:0.75rem 0 0"><a href="${esc(docUrl)}" target="_blank" rel="noopener">Clearance policy</a></p>` : ""}
    </section>`;
}

/** Map published sidecars → mild pillar stress for the Overview system map (L596). */
function resolveSystemMapStress(data) {
  const ingest = ((data.project_progress || {}).ingest_bottleneck) || {};
  const gaps = data.system_gaps || {};
  const flags = Array.isArray(gaps.flags) ? gaps.flags : [];
  const highGaps = Number(gaps.high_flag_count || flags.filter((f) => f.severity === "high").length || 0);
  const health = resolveQueueHealth(data) || {};
  const opsOverall = String(((health.ops_monitor || {}).overall) || health.overall || "").toLowerCase();
  const mergeState = String(((health.merge_lane || {}).state) || "").toLowerCase();

  const dataNotes = [];
  let dataLevel = "ok";
  if (ingest.stalled) {
    dataLevel = "high";
    dataNotes.push(ingest.summary || "Ingest bottleneck stalled");
  } else if (ingest.summary && /thin|backlog|rate.?limit|timeout/i.test(String(ingest.summary))) {
    dataLevel = "medium";
    dataNotes.push(ingest.summary);
  }

  const investNotes = [];
  let investLevel = "ok";
  if (highGaps > 0) {
    investLevel = "high";
    investNotes.push(`${highGaps} high learning-path gap flag${highGaps === 1 ? "" : "s"}`);
  } else if (flags.length > 0) {
    investLevel = "medium";
    investNotes.push(`${flags.length} learning-path gap flag${flags.length === 1 ? "" : "s"}`);
  }

  const platformNotes = [];
  let platformLevel = "ok";
  if (opsOverall === "fail" || mergeState === "blocked" || mergeState === "fail") {
    platformLevel = "high";
    platformNotes.push(
      opsOverall === "fail"
        ? `Ops monitor ${opsOverall}`
        : `Merge lane ${mergeState || "blocked"}`
    );
  } else if (opsOverall === "warn" || mergeState === "warn" || mergeState === "attention") {
    platformLevel = "medium";
    platformNotes.push(
      opsOverall === "warn" ? `Ops monitor ${opsOverall}` : `Merge lane ${mergeState}`
    );
  }

  return {
    data: { level: dataLevel, notes: dataNotes },
    investment: { level: investLevel, notes: investNotes },
    platform: { level: platformLevel, notes: platformNotes },
  };
}

function systemMapStressBadge(level) {
  if (level === "high") return '<span class="badge badge-ii-no" title="Elevated pressure">stress</span>';
  if (level === "medium") return '<span class="badge badge-hold" title="Watch">watch</span>';
  return '<span class="badge badge-ii-ok" title="No published stress signal">ok</span>';
}

function renderSystemMapCard(data) {
  const stress = resolveSystemMapStress(data);
  const archUrl = githubOpsDocUrl("docs/architecture.md");
  const objectiveUrl = githubOpsDocUrl("docs/PROJECT_OBJECTIVE.md");
  const pillar = (key, title, blurb, nodes) => {
    const row = stress[key] || { level: "ok", notes: [] };
    const noteHtml = row.notes.length
      ? `<p class="small system-map-stress-note">${esc(row.notes[0])}</p>`
      : "";
    return `
      <div class="system-map-pillar system-map-pillar-${esc(row.level)}" data-pillar="${esc(key)}">
        <div class="system-map-pillar-header">
          <strong>${esc(title)}</strong>
          ${systemMapStressBadge(row.level)}
        </div>
        <p class="small muted" style="margin:0.25rem 0 0.5rem">${esc(blurb)}</p>
        <ul class="list-plain small system-map-node-list">
          ${nodes.map((n) => `<li>${esc(n)}</li>`).join("")}
        </ul>
        ${noteHtml}
      </div>`;
  };

  return `
    <section class="card system-map-section" id="system-map-card">
      <div class="market-status-header">
        <h3>System map</h3>
        <p class="small muted" style="margin:0">
          Topology only — observe, not capital control.
          ${archUrl ? ` · <a href="${esc(archUrl)}" target="_blank" rel="noopener">architecture.md</a>` : ""}
          ${objectiveUrl ? ` · <a href="${esc(objectiveUrl)}" target="_blank" rel="noopener">PROJECT_OBJECTIVE</a>` : ""}
        </p>
      </div>
      <div class="system-map-pipeline" aria-label="Live pipeline">
        <span class="system-map-stage">ftse-screen</span>
        <span class="system-map-arrow" aria-hidden="true">→</span>
        <span class="system-map-stage">ftse-research</span>
        <span class="system-map-arrow" aria-hidden="true">→</span>
        <span class="system-map-stage">deep analysis</span>
        <span class="system-map-arrow" aria-hidden="true">→</span>
        <span class="system-map-stage">gap-fill</span>
        <span class="system-map-arrow" aria-hidden="true">→</span>
        <span class="system-map-stage">ftse-publish</span>
      </div>
      <p class="small muted" style="margin:0.35rem 0 0.75rem">
        Same spine as <code>docs/architecture.md</code>; offline <code>ftse-library</code> does not touch the live FTSE 350 screen.
      </p>
      <div class="system-map-pillars">
        ${pillar(
          "data",
          "Data",
          "Inventory, filings/FCF bind, ingest sprint — never owns Investment knobs (F8).",
          ["ingest-loop / library", "filings · FCF · overlay bind", "gap-closure · sprint markets"]
        )}
        ${pillar(
          "investment",
          "Investment",
          "Strand A capital path + sealed observe (N200 / N201); reads Data screens.",
          ["strand A · decision-review", "N200 / N201 observe", "LLM agree/veto shadow"]
        )}
        ${pillar(
          "platform",
          "Platform",
          "Schedules, findings, heal paths — ops-monitor → dashboard / eng queue.",
          ["ops-monitor · automation", "dashboard bridge", "eng queue · email"]
        )}
      </div>
      <p class="small muted" style="margin:0.75rem 0 0">
        Stress badges use published sidecars (ingest bottleneck, learning-path gaps, queue/ops health) — not live telemetry.
      </p>
    </section>`;
}

function renderSystemGapsCard(data) {
  const payload = data.system_gaps;
  const docUrl = githubOpsDocUrl("docs/ops/analysis-review.md", "system-gaps-learning-path-integrity");
  if (!payload) {
    return `
    <section class="card system-gaps-section" id="system-gaps-card">
      <div class="market-status-header">
        <h3>Learning-path gaps</h3>
      </div>
      <p class="muted small">System-gap snapshot not published yet. Sunday analysis-review writes <code>docs/data/system_gaps.json</code>.</p>
      ${docUrl ? `<p class="small"><a href="${esc(docUrl)}" target="_blank" rel="noopener">Runbook</a></p>` : ""}
    </section>`;
  }
  const flags = payload.flags || [];
  const high = Number(payload.high_flag_count || 0);
  const attention = high > 0 ? " system-gaps-section-attention" : "";
  const tiles = flags.length
    ? flags
        .map((row) => {
          const sev = String(row.severity || "info");
          return `
      <button type="button" class="system-gap-tile severity-${esc(sev)}" data-system-gap-id="${esc(row.id)}" aria-haspopup="dialog">
        <div class="market-tile-header">
          <strong>${esc(row.title || row.id)}</strong>
          ${systemGapSeverityBadge(row.severity)}
        </div>
        <div class="small muted">${esc(row.layer || "—")} · ${esc(row.id)}</div>
        <div class="small">${esc(row.summary || "")}</div>
      </button>`;
        })
        .join("")
    : `<p class="muted small">No learning-path integrity flags. File existence and unused budget are still not proof the book is fed.</p>`;
  return `
    <section class="card system-gaps-section${attention}" id="system-gaps-card">
      <div class="market-status-header">
        <h3>Learning-path gaps</h3>
        <p class="small muted" style="margin:0">
          ${esc(String(payload.flag_count ?? flags.length))} flags ·
          ${esc(String(high))} high
          ${payload.assessed_at ? ` · ${esc(fmtDate(payload.assessed_at))}` : ""}
          · click a flag for the detail card
        </p>
      </div>
      <div class="system-gaps-grid">${tiles}</div>
      ${docUrl ? `<p class="small" style="margin:0.75rem 0 0"><a href="${esc(docUrl)}" target="_blank" rel="noopener">Why this card exists</a></p>` : ""}
    </section>`;
}

function findMarketStatusRow(marketId) {
  const rows = ((dashboardData || {}).market_status || {}).markets || [];
  return rows.find((row) => row.market_id === marketId) || null;
}

function openMarketStatusCard(marketId) {
  const dialog = document.getElementById("market-status-dialog");
  const title = document.getElementById("market-status-title");
  const body = document.getElementById("market-status-body");
  if (!dialog || !title || !body) return;
  const row = findMarketStatusRow(marketId);
  if (!row) {
    title.textContent = "Market status";
    body.innerHTML = `<p class="muted">No status row for <code>${esc(marketId)}</code>.</p>`;
    dialog.showModal();
    return;
  }
  title.textContent = row.label || row.market_id;
  body.innerHTML = renderMarketStatusCard(row);
  dialog.showModal();
}

function renderMarketStatusCard(row) {
  const counts = row.signal_counts || {};
  const segments = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const filing = row.filing_health || {};
  const blockers = row.phase_blockers || [];
  const roleChips = marketLearningRoleChips(row);
  const filingRows = [];
  if (row.filing_health) {
    filingRows.push(settingRow("Buy-tier measured", esc(String(filing.buy_tier_count ?? "—"))));
    filingRows.push(
      settingRow(
        "Filing gaps",
        esc(
          `unmeasured ${filing.unmeasured_buy_tier ?? 0} · zero-body ${filing.zero_body_buy_tier ?? 0} · thin ${filing.thin_body_buy_tier ?? 0} · indexed-no-body ${filing.indexed_without_body ?? 0}`
        )
      )
    );
    if (filing.bodies_median != null) {
      filingRows.push(settingRow("Bodies (median)", esc(String(filing.bodies_median))));
    }
    const gapTickers = [
      ...(filing.zero_body_tickers || []).map((t) => `${t} (zero-body)`),
      ...(filing.thin_body_tickers || []).map((t) => `${t} (thin)`),
      ...(filing.unmeasured_tickers || []).map((t) => `${t} (unmeasured)`),
    ].slice(0, 10);
    if (gapTickers.length) {
      filingRows.push(
        settingRow("Gap names", `<span class="small">${gapTickers.map((t) => esc(t)).join(", ")}</span>`)
      );
    }
  }
  const blockerHtml = blockers.length
    ? `<ul class="list-plain small">${blockers.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`
    : '<p class="muted small">No learning-phase blockers recorded.</p>';
  return `
    <p class="small muted" style="margin-top:0">${esc(row.exchange || "—")} · ${esc(row.currency || "—")} · ${esc(row.market_id)}</p>
    <div class="market-card-badges">
      ${marketIngestBadge(row.ingest, row.ingest_stream)}
      ${marketHealthBadge(row.health)}
      <span class="stage-badge stage-active">${esc(learningBookLine(row))}</span>
      ${roleChips}
      ${row.ingest_exhausted ? '<span class="stage-badge mingest-queued" title="Sprint leftovers parked after exhaustion">exhausted leftovers</span>' : ""}
    </div>
    <p class="small muted" style="margin:0 0 0.75rem">Ingest = capacity · Learning role = path. Graduated ≠ admitted; maintenance ≠ live screen.</p>
    ${typeof renderLearningGateIndicator === "function" ? renderLearningGateIndicator(row.learning_gate) : ""}
    ${typeof renderHeldVsMarketChart === "function" ? renderHeldVsMarketChart(row.held_vs_market) : ""}
    ${row.ingest_reason ? `<p class="small">${esc(row.ingest_reason)}</p>` : ""}
    ${settingRow("Role", esc(row.role || "—"))}
    ${
      row.is_admitted
        ? settingRow(
            "Admitted learning",
            `${marketRoleBadge("admitted")} · epoch-0 package · no AI / no knob apply`
          )
        : ""
    }
    ${
      row.paper_instrument
        ? settingRow("Paper instrument", esc(String(row.paper_instrument)))
        : ""
    }
    ${
      row.epoch0 && row.epoch0.present
        ? settingRow(
            "Epoch-0 book",
            esc(
              `${row.epoch0.holdings ?? "—"} names · NAV ${
                row.epoch0.nav != null ? Number(row.epoch0.nav).toFixed(0) : "—"
              } · last ${fmtDate(row.epoch0.last_run_at)}`
            )
          )
        : ""
    }
    ${
      row.near_miss
        ? settingRow(
            "Near-miss watch",
            esc(
              `buy-not-now ${row.near_miss.buy_tier_not_now_count ?? 0} · hold-near-buy ${
                row.near_miss.hold_near_buy_count ?? 0
              } (census: not-buy-tier ${row.near_miss.not_buy_tier_count ?? 0} · never-buy-tier ${
                row.near_miss.never_buy_tier_count ?? 0
              })`
            )
          )
        : ""
    }
    ${
      row.equal_support
        ? settingRow(
            "Equal-support rememo",
            esc(`${row.equal_support.rememo_eligible_count ?? 0} buy-tier names over body-lag`)
          )
        : ""
    }
    ${
      row.equal_support && row.equal_support.first_time_memo_count != null
        ? settingRow(
            "First-time memos",
            `<span title="True unique-ticker misses after sibling-home join (exact Yahoo ticker). Empty local screen/research is not unresearched when memo_home_market already holds research.md.">${esc(
              String(row.equal_support.first_time_memo_count)
            )} missing (sibling homes already count)</span>`
          )
        : ""
    }
    ${
      row.shared_maintenance
        ? settingRow(
            "Shared maintenance cron",
            '<span class="stage-badge mingest-maintenance" title="On shared FTSE-volume maintenance cron">maint on</span>'
          )
        : ""
    }
    ${settingRow("Coverage", `${esc(coverageLabel(row.coverage_pct))} · ${esc(String(row.ticker_count ?? "—"))} names`)}
    ${settingRow("Fresh / stale", `${esc(String(row.fresh ?? "—"))} fresh · ${esc(String(row.stale ?? 0))} stale`)}
    ${settingRow("Last screen", `<span class="small">${esc(fmtDate(row.last_screen_at))}</span>`)}
    ${settingRow("Last metrics", `<span class="small">${esc(fmtDate(row.last_metrics_refresh))}</span>`)}
    ${settingRow("Buy-tier shortlist", esc(String(row.shortlist_count ?? "—")))}
    <p><button type="button" class="btn" data-open-lifecycle="${esc(row.market_id)}">Open lifecycle board</button></p>
    <h4 class="small" style="margin-top:1rem">Buy / hold / avoid</h4>
    ${marketSignalBar(counts)}
    <ul class="list-plain small">
      ${
        segments.length
          ? segments.map(([signal, count]) => `<li>${signalBadge(signal)} ${count}</li>`).join("")
          : "<li class='muted'>No screen-lite or live signal mix yet.</li>"
      }
    </ul>
    ${
      filingRows.length
        ? `<h4 class="small" style="margin-top:1rem">Filing health</h4>${filingRows.join("")}`
        : ""
    }
    ${
      row.sprint_progress
        ? renderSprintProgressCard(row.sprint_progress)
        : ""
    }
    <h4 class="small" style="margin-top:1rem">Learning phase</h4>
    ${blockerHtml}
    ${
      (row.expected_epoch0_blockers || []).length
        ? `<p class="small muted">Weekly-paper slot still on euro_depth only — expected for admitted epoch-0 (do not fork shard AI yet).</p>`
        : ""
    }
  `;
}

function renderMarketStatusGrid(data) {
  const payload = data.market_status;
  if (!payload || !(payload.markets || []).length) {
    return `
    <div class="card market-status-section" id="market-status-grid">
      <h3>Market status</h3>
      <p class="muted small">Market status not published yet. Run <code>ftse-publish</code> to assemble the grid.</p>
    </div>`;
  }
  const summary = payload.summary || {};
  const tiles = (payload.markets || [])
    .map((row) => {
      const health = row.health || "ok";
      return `
      <button type="button" class="market-tile health-${esc(health)}" data-market-id="${esc(row.market_id)}" aria-haspopup="dialog">
        <div class="market-tile-header">
          <strong>${esc(row.label)}</strong>
          <span class="market-tile-chips">
            ${marketIngestBadge(row.ingest, row.ingest_stream)}
            ${marketLearningRoleChips(row)}
          </span>
        </div>
        <div class="small muted market-tile-phase">${esc(learningBookLine(row))}${row.shared_maintenance ? " · maint cron" : ""}</div>
        ${typeof renderLearningGateIndicator === "function" ? renderLearningGateIndicator(row.learning_gate, { compact: true }) : ""}
        <div class="market-tile-body">
        ${marketSignalBar(row.signal_counts)}
        <div class="small market-tile-signals">${marketSignalSummary(row)}</div>
        ${typeof renderHeldVsMarketSparkline === "function" ? renderHeldVsMarketSparkline(row.held_vs_market) : ""}
        </div>
        <div class="small muted market-tile-meta">Coverage ${esc(coverageLabel(row.coverage_pct))}${
          row.near_miss
            ? ` · watch ${esc(String(row.near_miss.buy_tier_not_now_count ?? 0))}/${esc(
                String(row.near_miss.hold_near_buy_count ?? 0)
              )}`
            : ""
        }${
          row.epoch0 && row.epoch0.present
            ? ` · epoch-0 ${esc(String(row.epoch0.holdings ?? "—"))} pos`
            : ""
        }${
          row.equal_support && row.equal_support.first_time_memo_count != null
            ? ` · first-memo ${esc(String(row.equal_support.first_time_memo_count))}`
            : ""
        }</div>
        ${sprintProgressLine(row.sprint_progress)}
      </button>`;
    })
    .join("");
  return `
    <section class="card market-status-section" id="market-status-grid">
      <div class="market-status-header">
        <h3>Market status</h3>
        <p class="small muted" style="margin:0">
          ${esc(String(summary.sprint_count ?? 0))} sprint ·
          ${esc(String(summary.maintenance_count ?? 0))} maintenance ·
          ${esc(String(summary.admitted_count ?? 0))} admitted ·
          ${esc(String(summary.live_count ?? 0))} live
          ${
            summary.should_run_library_maintenance
              ? " · shared maintenance cron on"
              : ""
          }
          ${spareSprintLabel(summary.spare_sprint)}
          ${payload.generated_at ? ` · ${esc(fmtDate(payload.generated_at))}` : ""}
          · click a market for the detail card
        </p>
      </div>
      ${marketStatusBadgeLegend()}
      <div class="market-status-grid">${tiles}</div>
    </section>`;
}

function equalizeMarketTileHeights() {
  const tiles = document.querySelectorAll(".market-status-grid .market-tile");
  if (!tiles.length) return;
  tiles.forEach((tile) => {
    tile.style.minHeight = "";
    tile.style.height = "auto";
  });
  let max = 0;
  tiles.forEach((tile) => {
    max = Math.max(max, tile.offsetHeight);
  });
  const px = `${Math.ceil(max)}px`;
  tiles.forEach((tile) => {
    tile.style.height = "";
    tile.style.minHeight = px;
  });
}

function bindMarketTileEqualize() {
  if (window.__marketTileEqualizeBound) return;
  window.__marketTileEqualizeBound = true;
  window.addEventListener("resize", () => {
    window.clearTimeout(window.__marketTileEqualizeTimer);
    window.__marketTileEqualizeTimer = window.setTimeout(equalizeMarketTileHeights, 50);
  });
}

function renderDailyHubPulseStrip(data) {
  const hub = (data && data.daily_focus) || null;
  const recon = (data && data.ui_state_reconciliation) || null;
  const focusLines = ((hub && hub.focus_lines) || []).slice(0, 3);
  const focusHtml = focusLines.length
    ? `<ul class="list-plain daily-pulse-focus">${focusLines
        .map((l) => `<li>${esc(l.title || "")}</li>`)
        .join("")}</ul>`
    : '<p class="small muted">No focus lines yet.</p>';
  const reconOverall = recon ? String(recon.overall || "ok") : "—";
  const reconCls =
    reconOverall === "fail"
      ? "badge-ii-no"
      : reconOverall === "warn"
        ? "badge-watch"
        : reconOverall === "ok"
          ? "badge-buy"
          : "badge-neutral";
  const warnN = recon ? Number((recon.summary || {}).warn || 0) : 0;
  const hist = (data && data.daily_hub_history) || null;
  const histSummary = (hist && hist.summary) || {};
  const wallStale = isDailyHubStale(hub);
  return `<div class="card daily-hub-pulse">
    <h3>Daily hub</h3>
    <p class="small muted" style="margin-top:0">
      Europe/London · refresh before 04:00 ·
      <span class="badge ${reconCls}">reconcile ${esc(reconOverall)}${
        warnN ? ` · ${warnN} drift` : ""
      }</span>
      ${
        wallStale
          ? ' · <span class="badge badge-watch">hub stale</span>'
          : ""
      }
    </p>
    ${focusHtml}
    <p class="small"><a href="#automation/daily">Open daily hub</a>
      · History: ${esc(String(histSummary.dev_closed_7d ?? 0))} closes ·
      ${esc(String(histSummary.candidate_count ?? 0))} candidates
      · policy green ≠ utility</p>
  </div>`;
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

  const bottleneck = (data.project_progress || {}).ingest_bottleneck || {};
  const showIngestHealth = !bottleneck.stalled;

  document.getElementById("panel-overview").innerHTML = `
    ${note}
    ${renderDailyHubPulseStrip(data)}
    ${renderMarketStatusGrid(data)}
    ${renderLearningCompletenessCard(data)}
    ${renderSystemGapsCard(data)}
    ${renderSystemMapCard(data)}
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
    ${renderProgressReport(data)}
    ${renderProjectProgress(data)}
    <details class="card overview-secondary" style="margin-top:1rem">
      <summary><strong>Screen context</strong> — signal mix, trusts, week-over-week</summary>
      <div style="margin-top:0.75rem">
        <h4 class="small">Signal distribution</h4>
        <div class="signal-bar">${bar}</div>
        <ul class="list-plain small">
          ${segments.map(([s, c]) => `<li>${signalBadge(s)} ${c}</li>`).join("")}
        </ul>
        ${
          trustSegments.length
            ? `<h4 class="small" style="margin-top:0.75rem">Trust signal distribution</h4>
        <ul class="list-plain small">
          ${trustSegments.map(([s, c]) => `<li>${signalBadge(s)} ${c}</li>`).join("")}
        </ul>`
            : ""
        }
        <h4 class="small" style="margin-top:0.75rem">Week-over-week changes</h4>
        ${diffHtml}
      </div>
    </details>
    ${showIngestHealth ? renderIngestHealth(data) : ""}
  `;
  bindProgressReportActions();
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

const SCREENER_FILTER_IDS = [
  "",
  "strong_buy",
  "buy",
  "hold",
  "avoid",
  "insufficient_data",
];
const SCREENER_FILTER_LABELS = {
  "": "All",
  strong_buy: "Strong buy",
  buy: "Buy",
  hold: "Hold",
  avoid: "Avoid",
  insufficient_data: "Insufficient",
};
let screenerFilterId = "";

function normalizeScreenerFilter(value) {
  const key = String(value || "");
  return SCREENER_FILTER_IDS.includes(key) ? key : "";
}

function renderScreenerSubnav(activeId, reports) {
  const active = normalizeScreenerFilter(activeId);
  const counts = Object.create(null);
  for (const id of SCREENER_FILTER_IDS) counts[id] = 0;
  counts[""] = (reports || []).length;
  for (const row of reports || []) {
    const sig = String(row.signal || "");
    if (Object.prototype.hasOwnProperty.call(counts, sig)) counts[sig] += 1;
  }
  return `<nav class="paper-subnav screener-subnav" aria-label="Screener signal filters">
    ${SCREENER_FILTER_IDS.map((id) => {
      const label = SCREENER_FILTER_LABELS[id] || id;
      const n = counts[id] ?? 0;
      return `<button type="button" class="paper-subtab${
        id === active ? " active" : ""
      }" data-screener-filter="${esc(id)}">${esc(label)} <span class="small muted">${n}</span></button>`;
    }).join("")}
  </nav>`;
}

function syncScreenerHash() {
  const filter = normalizeScreenerFilter(screenerFilterId);
  if (!filter) {
    history.replaceState(null, "", "#screener");
    return;
  }
  history.replaceState(null, "", `#screener/${filter}`);
}

function renderScreener(data) {
  const reports = data.reports || [];
  const panel = document.getElementById("panel-screener");
  screenerFilterId = normalizeScreenerFilter(screenerFilterId);

  panel.innerHTML = `
    ${renderScreenerSubnav(screenerFilterId, reports)}
    <div class="toolbar">
      <input type="search" id="screener-search" placeholder="Search company or ticker…" aria-label="Search">
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
  const byTicker = new Map(reports.map((r) => [r.ticker, r]));

  function renderRows() {
    const q = (searchInput.value || "").toLowerCase();
    const filter = normalizeScreenerFilter(screenerFilterId);
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
        <td>${report.models_passed}/${report.model_count}<br><span class="small muted">${report.families_passed}/${report.family_count || 5} families</span></td>
        <td>${pct(report.conviction_score)}<br><span class="small muted">${esc(report.stability_label || "")}${report.weeks_at_signal ? ` · ${report.weeks_at_signal}w` : ""}</span></td>
        <td class="small">${esc(report.summary || "")}</td>
        <td>${chartBtn}</td>
      </tr>`;
      })
      .join("");
    bindChartButtons(tbody, byTicker);
  }

  if (!panel.dataset.screenerBound) {
    panel.dataset.screenerBound = "1";
    panel.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-screener-filter]");
      if (!btn) return;
      event.preventDefault();
      screenerFilterId = normalizeScreenerFilter(btn.dataset.screenerFilter);
      syncScreenerHash();
      if (dashboardData) renderScreener(dashboardData);
    });
  }

  searchInput.addEventListener("input", renderRows);
  renderRows();
}

function chartOutcomePct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const number = Number(value) * 100;
  const formatted = `${number >= 0 ? "+" : ""}${number.toFixed(1)}%`;
  return formatted;
}

function chartOutcomeBadge(outcome) {
  const key = String(outcome || "insufficient_data").replace(/\s+/g, "_");
  const badgeClass = {
    well_timed: "badge-strong_buy",
    intact_positive: "badge-buy",
    giveback: "badge-hold",
    underwater: "badge-wait",
    flat: "badge-neutral",
    terrible: "badge-avoid",
    insufficient_data: "badge-insufficient_data",
  }[key] || "badge-neutral";
  return `<span class="badge ${badgeClass}">${esc(key.replace(/_/g, " "))}</span>`;
}

function renderChartOutcomeReview(data, { compact = false } = {}) {
  const review = data.chart_outcome_review;
  if (!review || !review.verdict || review.verdict === "empty") return "";
  const counts = review.counts || {};
  const stats = review.stats || {};
  const wellTimed = review.well_timed || [];
  const weakest = review.weakest || [];
  const verdictClass =
    review.verdict === "has_terrible"
      ? "chart-outcome-verdict is-warn"
      : "chart-outcome-verdict";
  const nameBtn = (row) =>
    `<button type="button" class="btn btn-ghost chart-outcome-name" data-chart-ticker="${esc(row.ticker)}">${esc(row.ticker)}</button>`;
  const wellTimedList = wellTimed.length
    ? wellTimed
        .slice(0, compact ? 3 : 6)
        .map(
          (row) =>
            `<li>${nameBtn(row)} ${chartOutcomePct(row.return_since)} ${chartOutcomeBadge(row.outcome)}</li>`
        )
        .join("")
    : "<li class='muted'>None this pass.</li>";
  const weakestList = weakest.length
    ? weakest
        .slice(0, compact ? 3 : 6)
        .map(
          (row) =>
            `<li>${nameBtn(row)} ${chartOutcomePct(row.return_since)} ${chartOutcomeBadge(row.outcome)}</li>`
        )
        .join("")
    : "<li class='muted'>None this pass.</li>";
  const samplesInner = `<div class="chart-outcome-columns">
        <div>
          <h4>Well timed</h4>
          <ul class="chart-outcome-list">${wellTimedList}</ul>
        </div>
        <div>
          <h4>Weakest open returns</h4>
          <ul class="chart-outcome-list">${weakestList}</ul>
        </div>
      </div>`;
  const samples = compact
    ? `<details class="overview-secondary chart-outcome-samples" style="margin-top:0.75rem">
        <summary>Sample names (observe path — not a paper/epoch grade)</summary>
        ${samplesInner}
      </details>`
    : samplesInner;
  const asOf = review.as_of || review.generated_at || review.reviewed_at;
  const daysNote =
    stats.median_days_since != null
      ? `Median days since recommendation: ${esc(String(stats.median_days_since))}.`
      : stats.days_since_median != null
        ? `Median days since recommendation: ${esc(String(stats.days_since_median))}.`
        : "";
  const docUrl = githubOpsDocUrl("docs/ops/chart-outcome-review.md");
  return `
    <div class="card chart-outcome-card">
      <h3>Chart outcomes since recommendation</h3>
      <p class="small muted" style="margin-top:0">
        Observe-only path labels on frozen buy-tier entry levels — <strong>not</strong> paper-book excess,
        epoch <code>beat_market</code>, or fair Suite B adoption truth.
        ${asOf ? `As of ${esc(fmtDate(asOf))}.` : ""}
        ${daysNote}
        ${docUrl ? `<a href="${esc(docUrl)}" target="_blank" rel="noopener">Chart outcome review</a>` : ""}
      </p>
      <p class="${verdictClass}">${esc(review.verdict_label || review.verdict)}</p>
      <p class="small">${esc(review.headline || "")}</p>
      <div class="chart-outcome-stats">
        <div><span class="stat-value">${counts.well_timed ?? 0}</span><span class="small muted">Well timed</span></div>
        <div><span class="stat-value">${counts.giveback ?? 0}</span><span class="small muted">Target then fade</span></div>
        <div><span class="stat-value">${counts.underwater ?? 0}</span><span class="small muted">Underwater</span></div>
        <div><span class="stat-value">${counts.stop_hit ?? 0}</span><span class="small muted">Stop hits</span></div>
        <div><span class="stat-value">${counts.terrible ?? 0}</span><span class="small muted">Terrible</span></div>
        <div><span class="stat-value">${chartOutcomePct(stats.median_return)}</span><span class="small muted">Median open return <span title="Not the success grade — longer path + paper excess matter">(path)</span></span></div>
      </div>
      ${samples}
      <p class="small muted" style="margin-bottom:0">
        Success contract: intact thesis over the longer path — not this first open-return mix (N58: do not retune timing from a mixed pass).
        Short-term underwater is expected while the hypothesis stands.
        ${compact ? "Open a name on Strong buys for the price chart." : "Click a ticker to open its price chart."}
      </p>
    </div>`;
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
    ${renderChartOutcomeReview(data)}
    <p class="small muted" style="margin-top:1rem">Mark <strong>Unavailable</strong> to bypass a suggested trade that cannot be actioned on Trading 212. The name stays watched below and is excluded from paper auto-entries until restored.</p>
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

/** Shared horizon presentation for historical siblings (strategy / overlay / signal backtest).
 * Same spirit as model attribution (#873) — do not re-touch attribution meta. */
function historicalHorizonMeta(source) {
  const meta = (source && source.horizon_presentation_meta) || {};
  return {
    primary_horizon_days: meta.primary_horizon_days ?? 28,
    secondary_horizon_days: Array.isArray(meta.secondary_horizon_days)
      ? meta.secondary_horizon_days
      : [84],
    noise_horizon_days: Array.isArray(meta.noise_horizon_days) ? meta.noise_horizon_days : [7],
    cohort: meta.cohort || "screen_and_overlay_signals",
    return_basis: meta.return_basis || "excess_vs_ftse",
  };
}

function partitionByHorizon(rows, meta) {
  const primaryH = Number(meta.primary_horizon_days);
  const secondarySet = new Set((meta.secondary_horizon_days || []).map(Number));
  const noiseSet = new Set((meta.noise_horizon_days || []).map(Number));
  const list = Array.isArray(rows) ? rows : [];
  return {
    primary: list.filter((r) => Number(r.horizon_days) === primaryH),
    secondary: list.filter((r) => secondarySet.has(Number(r.horizon_days))),
    noise: list.filter((r) => noiseSet.has(Number(r.horizon_days))),
    other: list.filter((r) => {
      const h = Number(r.horizon_days);
      return h !== primaryH && !secondarySet.has(h) && !noiseSet.has(h);
    }),
    primaryH,
    secondarySet,
    noiseSet,
  };
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

  const meta = historicalHorizonMeta(historical);
  const strategyAll = historical.strategy_horizons.filter((row) => keyStrategies.has(row.strategy));
  const strategyParts = partitionByHorizon(strategyAll, meta);
  const strategyRowHtml = (row) => `<tr>
        <td>${signalBadge(row.strategy.replace(/^[^:]+:/, ""))}<br><span class="small muted">${esc(row.strategy)}</span></td>
        <td>${pct(row.smoothed_excess_return)}</td>
        <td>${pct(row.raw_excess_return)}</td>
        <td>${row.count}</td>
        <td>${row.observation_weeks}</td>
      </tr>`;

  const strategyPrimaryTable = strategyParts.primary.length
    ? `<h4 style="margin-top:1rem">Strategy horizons — primary ${strategyParts.primaryH}d (FTSE excess)</h4>
      <p class="small muted" style="margin-top:0">
        Cohort: screen/overlay/research key signals · Return: excess vs ^FTSE (smoothed).
        Primary ${strategyParts.primaryH}d matches weight-learning / attribution spirit; not paper P&amp;L.
      </p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Strategy</th><th>Smoothed excess</th><th>Raw excess</th><th>N</th><th>Weeks</th></tr></thead>
          <tbody>${strategyParts.primary
            .slice()
            .sort((a, b) => a.strategy.localeCompare(b.strategy))
            .map(strategyRowHtml)
            .join("")}</tbody>
        </table>
      </div>`
    : "";

  const strategySecondary = (meta.secondary_horizon_days || [])
    .map((h) => {
      const subset = strategyParts.secondary.filter((r) => Number(r.horizon_days) === Number(h));
      if (!subset.length) return "";
      return `<h4 style="margin-top:1rem">Strategy horizons — secondary ${Number(h)}d</h4>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Strategy</th><th>Smoothed excess</th><th>Raw excess</th><th>N</th><th>Weeks</th></tr></thead>
          <tbody>${subset
            .slice()
            .sort((a, b) => a.strategy.localeCompare(b.strategy))
            .map(strategyRowHtml)
            .join("")}</tbody>
        </table>
      </div>`;
    })
    .join("");

  const strategyNoise = strategyParts.noise.length
    ? `<details class="overview-secondary" style="margin-top:1rem">
        <summary>Noise check — ${[...strategyParts.noiseSet].join("/")}d strategy excess (demoted)</summary>
        <p class="small muted">Short mark-to-mark horizons are diagnostics only; they are not the success metric.</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Horizon</th><th>Strategy</th><th>Smoothed excess</th><th>Raw excess</th><th>N</th><th>Weeks</th></tr></thead>
            <tbody>${strategyParts.noise
              .slice()
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
              .join("")}</tbody>
          </table>
        </div>
      </details>`
    : "";

  const overlayParts = partitionByHorizon(historical.overlay_comparison || [], meta);
  const overlayRowHtml = (row) => `<tr>
        <td>${pct(row.smoothed_screen_excess)}</td>
        <td>${pct(row.smoothed_overlay_excess)}</td>
        <td>${row.downgrade_count}</td>
        <td>${row.sample_count}</td>
      </tr>`;
  const overlayPrimary = overlayParts.primary.length
    ? `<h4 style="margin-top:1rem">Screen vs research overlay — primary ${overlayParts.primaryH}d</h4>
      <p class="small muted" style="margin-top:0">
        Cohort: buy-tier (buy ∪ strong_buy) · Return: smoothed excess vs ^FTSE · investment-horizon framing (not a 7d grade).
      </p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Screen (smoothed)</th><th>Overlay (smoothed)</th><th>Downgrades</th><th>N</th></tr></thead>
          <tbody>${overlayParts.primary.map(overlayRowHtml).join("")}</tbody>
        </table>
      </div>`
    : "";
  const overlaySecondary = (meta.secondary_horizon_days || [])
    .map((h) => {
      const subset = overlayParts.secondary.filter((r) => Number(r.horizon_days) === Number(h));
      if (!subset.length) return "";
      return `<h4 style="margin-top:1rem">Screen vs overlay — secondary ${Number(h)}d</h4>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Screen (smoothed)</th><th>Overlay (smoothed)</th><th>Downgrades</th><th>N</th></tr></thead>
          <tbody>${subset.map(overlayRowHtml).join("")}</tbody>
        </table>
      </div>`;
    })
    .join("");
  const overlayNoise = overlayParts.noise.length
    ? `<details class="overview-secondary" style="margin-top:1rem">
        <summary>Noise check — ${[...overlayParts.noiseSet].join("/")}d overlay comparison (demoted)</summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Horizon</th><th>Screen</th><th>Overlay</th><th>Downgrades</th><th>N</th></tr></thead>
            <tbody>${overlayParts.noise
              .map(
                (row) => `<tr>
              <td>${row.horizon_days}d</td>
              <td>${pct(row.smoothed_screen_excess)}</td>
              <td>${pct(row.smoothed_overlay_excess)}</td>
              <td>${row.downgrade_count}</td>
              <td>${row.sample_count}</td>
            </tr>`
              )
              .join("")}</tbody>
          </table>
        </div>
      </details>`
    : "";

  return `
    <p class="small muted">
      ${esc(historical.note || "")}
      · ${historical.run_count} runs · ${historical.max_years}y window · ${historical.smoothing_weeks}w smoothing
    </p>
    <p class="small">Window: ${windowLabel}</p>
    ${renderWeeklySeriesChart(historical.weekly_series, 28)}
    ${renderWeeklySeriesChart(historical.weekly_series, 84)}
    ${strategyPrimaryTable}
    ${strategySecondary}
    ${strategyNoise}
    ${overlayPrimary}
    ${overlaySecondary}
    ${overlayNoise}
    ${renderModelAttributionPanel(historical)}`;
}

/** Model attribution: primary = score → FTSE-excess on overlay buy-tier at 28d (weight-learning horizon). */
function modelAttributionMeta(historical) {
  const meta = historical?.model_attribution_meta || {};
  return {
    primary_horizon_days: meta.primary_horizon_days ?? 28,
    secondary_horizon_days: Array.isArray(meta.secondary_horizon_days)
      ? meta.secondary_horizon_days
      : [84],
    noise_horizon_days: Array.isArray(meta.noise_horizon_days) ? meta.noise_horizon_days : [7],
    success_definition:
      meta.success_definition || "higher_model_score_higher_ftse_excess_on_buy_tier",
    cohort: meta.cohort || "overlay_buy_tier",
    return_basis: meta.return_basis || "excess_vs_ftse",
    statistic: meta.statistic || "pearson",
    aligned_with_weight_learning_horizon: meta.aligned_with_weight_learning_horizon !== false,
    exit_join: meta.exit_join || { status: "not_computed" },
  };
}

function modelAttributionCorrCell(row) {
  const corr = row.smoothed_correlation != null ? row.smoothed_correlation : row.raw_correlation;
  return corr != null ? corr.toFixed(2) : "—";
}

function modelAttributionTableRows(rows) {
  return rows
    .map(
      (row) => `<tr>
        <td>${esc(row.model_id)}</td>
        <td>${modelAttributionCorrCell(row)}</td>
        <td>${row.sample_count}</td>
        <td>${row.observation_weeks != null ? row.observation_weeks : "—"}</td>
      </tr>`
    )
    .join("");
}

function renderModelAttributionHorizonTable(title, blurb, rows) {
  if (!rows.length) return "";
  return `<h4 style="margin-top:1rem">${esc(title)}</h4>
      <p class="small muted" style="margin-top:0">${esc(blurb)}</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Model</th><th>Correlation</th><th>N</th><th>Weeks</th></tr></thead>
          <tbody>${modelAttributionTableRows(rows)}</tbody>
        </table>
      </div>`;
}

function renderModelAttributionPanel(historical) {
  const rows = historical.model_attribution || [];
  if (!rows.length) return "";

  const meta = modelAttributionMeta(historical);
  const primaryH = meta.primary_horizon_days;
  const secondarySet = new Set(meta.secondary_horizon_days.map(Number));
  const noiseSet = new Set(meta.noise_horizon_days.map(Number));

  const primaryRows = rows.filter((r) => Number(r.horizon_days) === primaryH);
  const secondaryRows = rows.filter((r) => secondarySet.has(Number(r.horizon_days)));
  const noiseRows = rows.filter((r) => noiseSet.has(Number(r.horizon_days)));
  // Any horizon not classified (future horizons) — show after primary, before noise.
  const otherRows = rows.filter((r) => {
    const h = Number(r.horizon_days);
    return h !== primaryH && !secondarySet.has(h) && !noiseSet.has(h);
  });

  const successLabel =
    "Success: higher model score → higher FTSE-excess forward return on overlay buy-tier (buy ∪ strong_buy).";
  const horizonNote = meta.aligned_with_weight_learning_horizon
    ? `Primary horizon ${primaryH}d matches weight-learning DEFAULT_HORIZON_DAYS.`
    : `Primary horizon ${primaryH}d.`;
  const cohortLabel = `Cohort: ${meta.cohort.replace(/_/g, " ")} · Return: ${meta.return_basis.replace(
    /_/g,
    " "
  )} · Statistic: ${meta.statistic}`;

  const noiseBlock = noiseRows.length
    ? `<details class="overview-secondary" style="margin-top:1rem">
        <summary>Noise check — ${[...noiseSet].join("/")}d score→return (demoted)</summary>
        <p class="small muted">${esc(
          "Short mark-to-mark correlations are shown for diagnostics only; they are not the success metric."
        )}</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Model</th><th>Horizon</th><th>Correlation</th><th>N</th><th>Weeks</th></tr></thead>
            <tbody>${noiseRows
              .map(
                (row) => `<tr>
              <td>${esc(row.model_id)}</td>
              <td>${row.horizon_days}d</td>
              <td>${modelAttributionCorrCell(row)}</td>
              <td>${row.sample_count}</td>
              <td>${row.observation_weeks != null ? row.observation_weeks : "—"}</td>
            </tr>`
              )
              .join("")}</tbody>
          </table>
        </div>
      </details>`
    : "";

  let mainBlocks = "";
  if (primaryRows.length) {
    mainBlocks += renderModelAttributionHorizonTable(
      `Model attribution — primary ${primaryH}d (score → FTSE excess, buy-tier)`,
      `${successLabel} ${horizonNote} Correlation is not paper P&L.`,
      primaryRows
    );
    mainBlocks += meta.secondary_horizon_days
      .map((h) => {
        const subset = secondaryRows.filter((r) => Number(r.horizon_days) === Number(h));
        if (!subset.length) {
          return `<p class="small muted" style="margin-top:0.75rem">${Number(
            h
          )}d secondary horizon: not enough archive depth yet for buy-tier excess pairs.</p>`;
        }
        return renderModelAttributionHorizonTable(
          `Model attribution — secondary ${Number(h)}d`,
          "Same success definition when forward exit snapshots exist.",
          subset
        );
      })
      .join("");
    if (otherRows.length) {
      mainBlocks += renderModelAttributionHorizonTable(
        "Model attribution — other horizons",
        cohortLabel,
        otherRows
      );
    }
  } else {
    // Thin archive: state the preferred primary horizon, then show non-noise rows without burying them in slice(0,8).
    const available = rows.filter((r) => !noiseSet.has(Number(r.horizon_days)));
    mainBlocks += `<p class="small muted" style="margin-top:1rem">No ${primaryH}d buy-tier excess pairs yet (${esc(
      horizonNote
    )}). Showing available non-noise horizons.</p>`;
    if (available.length) {
      mainBlocks += renderModelAttributionHorizonTable(
        "Model attribution — available horizons",
        successLabel,
        available
      );
    }
  }

  const exitStatus = meta.exit_join?.status || "not_computed";
  const exitNote =
    exitStatus === "not_computed"
      ? `<p class="small muted" style="margin-top:0.75rem">Paper-exit score-quintile attribution: reserved join hook (<code>model_attribution_meta.exit_join</code>) — not computed until closed cohort readiness.</p>`
      : "";

  return `${mainBlocks}${noiseBlock}
      <p class="small muted" style="margin-top:0.5rem">${esc(cohortLabel)}</p>
      ${exitNote}`;
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

const PERFORMANCE_SECTION_IDS = ["signals", "sim", "historical"];
let performanceSectionId = "signals";

function normalizePerformanceSection(value) {
  const key = String(value || "").toLowerCase();
  if (key === "signal" || key === "backtest") return "signals";
  if (key === "simulation" || key === "sims") return "sim";
  if (key === "history" || key === "hist") return "historical";
  if (PERFORMANCE_SECTION_IDS.includes(key)) return key;
  return "signals";
}

function renderPerformanceSubnav(activeId) {
  const active = normalizePerformanceSection(activeId);
  const labels = {
    signals: "Signals",
    sim: "Simulation",
    historical: "Historical",
  };
  return `<nav class="paper-subnav performance-subnav" aria-label="Performance sections">
    ${PERFORMANCE_SECTION_IDS.map(
      (id) =>
        `<button type="button" class="paper-subtab${
          id === active ? " active" : ""
        }" data-performance-section="${id}">${esc(labels[id])}</button>`
    ).join("")}
  </nav>`;
}

function syncPerformanceHash() {
  const section = normalizePerformanceSection(performanceSectionId);
  if (section === "signals") {
    history.replaceState(null, "", "#performance");
    return;
  }
  history.replaceState(null, "", `#performance/${section}`);
}

function renderPerformance(data) {
  const backtest = data.backtest;
  const simulation = data.simulation;
  const historical = data.historical_analysis;
  const panel = document.getElementById("panel-performance");
  performanceSectionId = normalizePerformanceSection(performanceSectionId);
  const section = performanceSectionId;

  let backtestHtml = '<div class="empty-state">Backtest needs at least two archived weekly runs.</div>';
  if (backtest && backtest.horizons && backtest.horizons.length) {
    const btMeta = historicalHorizonMeta(backtest);
    const btParts = partitionByHorizon(backtest.horizons, btMeta);
    const btRow = (h) => `<tr>
              <td>${signalBadge(h.signal)}</td>
              <td>${pct(h.avg_return)}</td>
              <td>${pct(h.benchmark_return)}</td>
              <td>${pct(h.excess_return)}</td>
              <td>${h.count}</td>
            </tr>`;
    const btPrimary = btParts.primary.length
      ? `<h4 style="margin-top:0.75rem">Primary ${btParts.primaryH}d — excess vs ^FTSE</h4>
      <p class="small muted" style="margin-top:0">
        Cohort: universe signal buckets (not buy-tier-only) · Return: average excess vs ^FTSE.
        Primary ${btParts.primaryH}d; 7d is demoted below.
      </p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Signal</th><th>Avg return</th><th>Benchmark</th><th>Excess</th><th>N</th></tr></thead>
          <tbody>${btParts.primary.map(btRow).join("")}</tbody>
        </table>
      </div>`
      : "";
    const btSecondary = (btMeta.secondary_horizon_days || [])
      .map((days) => {
        const subset = btParts.secondary.filter((r) => Number(r.horizon_days) === Number(days));
        if (!subset.length) return "";
        return `<h4 style="margin-top:0.75rem">Secondary ${Number(days)}d</h4>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Signal</th><th>Avg return</th><th>Benchmark</th><th>Excess</th><th>N</th></tr></thead>
          <tbody>${subset.map(btRow).join("")}</tbody>
        </table>
      </div>`;
      })
      .join("");
    const btNoise = btParts.noise.length
      ? `<details class="overview-secondary" style="margin-top:0.75rem">
        <summary>Noise check — ${[...btParts.noiseSet].join("/")}d signal backtest (demoted)</summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Horizon</th><th>Signal</th><th>Avg return</th><th>Benchmark</th><th>Excess</th><th>N</th></tr></thead>
            <tbody>${btParts.noise
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
              .join("")}</tbody>
          </table>
        </div>
      </details>`
      : "";
    backtestHtml = `
      <p class="small muted">${esc(backtest.note || "")} · ${backtest.run_count} archived runs</p>
      ${btPrimary}
      ${btSecondary}
      ${btNoise}`;
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
    ${renderPerformanceSubnav(section)}
    <div class="performance-section-pane" data-performance-pane="signals" ${
      section === "signals" ? "" : "hidden"
    }>
      <div class="card">
        <h3>Signal backtest</h3>
        ${backtestHtml}
      </div>
    </div>
    <div class="performance-section-pane" data-performance-pane="sim" ${
      section === "sim" ? "" : "hidden"
    }>
      <div class="card">
        <h3>Portfolio simulation (£1,000)</h3>
        ${simHtml}
      </div>
    </div>
    <div class="performance-section-pane" data-performance-pane="historical" ${
      section === "historical" ? "" : "hidden"
    }>
      <div class="card">
        <h3>Historical analysis</h3>
        <p class="small muted">Point-in-time replay of screen signals, research verdicts, and model scores with weekly smoothing.</p>
        ${renderHistoricalAnalysis(historical)}
      </div>
    </div>
  `;

  if (!panel.dataset.performanceBound) {
    panel.dataset.performanceBound = "1";
    panel.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-performance-section]");
      if (!btn) return;
      event.preventDefault();
      performanceSectionId = normalizePerformanceSection(btn.dataset.performanceSection);
      syncPerformanceHash();
      if (dashboardData) renderPerformance(dashboardData);
    });
  }

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

/** Format a fractional return as ±X.X% (or "—" when missing). */
function fmtSignedPct(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value) * 100;
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

/**
 * Deterministic one-line “story” for a paper track from its week rows
 * (oldest→newest). Uses excess, trajectory, cost drag, marks, and epoch —
 * no LLM.
 */
function paperTrackStory(weeks) {
  const rows = Array.isArray(weeks) ? weeks : [];
  if (!rows.length) return "No weekly marks yet.";

  const latest = rows[rows.length - 1] || {};
  const excesses = rows
    .map((row) => row.excess_after_costs)
    .filter((v) => v != null && !Number.isNaN(Number(v)))
    .map(Number);
  const latestExcess =
    latest.excess_after_costs != null && !Number.isNaN(Number(latest.excess_after_costs))
      ? Number(latest.excess_after_costs)
      : excesses.length
        ? excesses[excesses.length - 1]
        : null;

  const parts = [];
  if (rows.length < 2 || excesses.length < 2) {
    if (latestExcess == null) {
      parts.push("Too early to call — waiting on excess marks.");
    } else if (latestExcess >= 0.005) {
      parts.push(`Beating ^FTSE (${fmtSignedPct(latestExcess)}) on thin history.`);
    } else if (latestExcess <= -0.005) {
      parts.push(`Lagging ^FTSE (${fmtSignedPct(latestExcess)}) on thin history.`);
    } else {
      parts.push(`Near flat vs ^FTSE (${fmtSignedPct(latestExcess)}); thin history.`);
    }
  } else {
    const first = excesses[0];
    const last = excesses[excesses.length - 1];
    const delta = last - first;
    let level;
    if (last >= 0.005) level = `Beating ^FTSE (${fmtSignedPct(last)})`;
    else if (last <= -0.005) level = `Lagging ^FTSE (${fmtSignedPct(last)})`;
    else level = `Near flat vs ^FTSE (${fmtSignedPct(last)})`;

    let traj;
    if (delta >= 0.005) traj = "excess improving across weeks";
    else if (delta <= -0.005) traj = "excess softening across weeks";
    else traj = "excess roughly stable";
    parts.push(`${level}; ${traj}.`);
  }

  const cost = latest.cost_drag != null ? Number(latest.cost_drag) : null;
  if (cost != null && !Number.isNaN(cost) && cost >= 0.005) {
    parts.push(`Cost drag ${fmtSignedPct(cost).replace("+", "")} is material.`);
  }

  const epoch =
    latest.epoch_excess_after_costs != null &&
    !Number.isNaN(Number(latest.epoch_excess_after_costs))
      ? Number(latest.epoch_excess_after_costs)
      : null;
  if (
    epoch != null &&
    latestExcess != null &&
    Math.abs(epoch - latestExcess) >= 0.01
  ) {
    parts.push(`Epoch excess ${fmtSignedPct(epoch)} diverges from book total.`);
  }

  const marks = latest.equity_marks;
  if (marks != null && Number(marks) > 0 && Number(marks) < 4) {
    parts.push(`Only ${marks} equity mark(s) — sample still thin.`);
  }

  const trades = rows
    .map((row) => row.trade_count)
    .filter((v) => v != null && !Number.isNaN(Number(v)))
    .map(Number);
  if (trades.length >= 2) {
    const tradeDelta = trades[trades.length - 1] - trades[0];
    if (tradeDelta >= 8) parts.push("Trade count rising — watch churn.");
    else if (tradeDelta === 0 && trades[trades.length - 1] === 0) {
      parts.push("No trades logged across the window.");
    }
  }

  return parts.join(" ");
}

/** Group flattened track-week rows into { trackKey, label, id, isPrimary, weeks }[]. */
function groupPaperTracksById(trackWeekRows) {
  const byId = new Map();
  for (const row of trackWeekRows) {
    const key = String(row.track_id || row.track_label || "unknown");
    if (!byId.has(key)) {
      byId.set(key, {
        trackKey: key,
        track_id: row.track_id || key,
        track_label: row.track_label || row.track_id || key,
        is_primary: Boolean(row.is_primary),
        weeks: [],
      });
    }
    const group = byId.get(key);
    if (row.is_primary) group.is_primary = true;
    if (row.track_label) group.track_label = row.track_label;
    group.weeks.push(row);
  }
  return Array.from(byId.values());
}

function renderSundayReview(data) {
  const review = data.sunday_review;
  if (!review) {
    return `
      <section class="automation-section automation-section-full sunday-review-section analysis-section" id="analysis-sunday">
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

  const regimeDeltaSpan = (current, prior, { pct = false, digits = 1 } = {}) => {
    if (current == null || prior == null || Number.isNaN(Number(current)) || Number.isNaN(Number(prior))) {
      return "";
    }
    const delta = Number(current) - Number(prior);
    if (Math.abs(delta) < 1e-12) {
      return ` <span class="regime-delta regime-delta-flat small muted">Δ0</span>`;
    }
    const cls = delta > 0 ? "text-positive" : "text-negative";
    const label = pct
      ? `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(digits)}pp`
      : `${delta > 0 ? "+" : ""}${delta.toFixed(digits)}`;
    return ` <span class="regime-delta ${cls} small">Δ${esc(label)}</span>`;
  };
  const regimeChangedClass = (current, prior) => {
    if (prior == null) return "";
    return String(current ?? "") === String(prior ?? "") ? "regime-unchanged" : "regime-changed";
  };

  const regimeRows = history
    .map((snap, index) => {
      const regime = snap.regime || {};
      const excl = snap.exclusion?.summary || {};
      // history is newest-first; prior week is the next row.
      const prior = history[index + 1] || null;
      const priorRegime = (prior && prior.regime) || {};
      const priorExcl = (prior && prior.exclusion && prior.exclusion.summary) || {};
      const step = regime.recommended_exclusion_step || review.recommended_exclusion_step || "—";
      const priorStep =
        priorRegime.recommended_exclusion_step ||
        (prior ? review.recommended_exclusion_step : null) ||
        null;
      return `<tr>
        <td><strong>${esc(snap.week_ending || "—")}</strong><br><span class="small muted">${esc(fmtDate(snap.reviewed_at))}</span></td>
        <td class="${regimeChangedClass(step, prior ? priorStep : null)}">${esc(step)}${
          prior && String(step) !== String(priorStep ?? "")
            ? ` <span class="regime-delta small muted">was ${esc(priorStep ?? "—")}</span>`
            : prior
              ? ` <span class="regime-delta regime-delta-flat small muted">same</span>`
              : ""
        }</td>
        <td class="${alphaClass(excl.cumulative_exclusion_alpha)}">${pctOrDash(excl.cumulative_exclusion_alpha)}${regimeDeltaSpan(
          excl.cumulative_exclusion_alpha,
          priorExcl.cumulative_exclusion_alpha,
          { pct: true }
        )}</td>
        <td class="${regimeChangedClass(regime.positive_alpha_rate, priorRegime.positive_alpha_rate)}">${pctOrDash(regime.positive_alpha_rate)}${regimeDeltaSpan(
          regime.positive_alpha_rate,
          priorRegime.positive_alpha_rate,
          { pct: true }
        )}</td>
        <td class="${regimeChangedClass(regime.exclusion_week_pairs, priorRegime.exclusion_week_pairs)}">${regime.exclusion_week_pairs ?? "—"}${regimeDeltaSpan(
          regime.exclusion_week_pairs,
          priorRegime.exclusion_week_pairs,
          { pct: false, digits: 0 }
        )}</td>
        <td class="${alphaClass(regime.primary_excess_after_costs)}">${pctOrDash(regime.primary_excess_after_costs)}${regimeDeltaSpan(
          regime.primary_excess_after_costs,
          priorRegime.primary_excess_after_costs,
          { pct: true }
        )}</td>
        <td class="${regimeChangedClass(Boolean(regime.beat_market), prior ? Boolean(priorRegime.beat_market) : null)}">${regime.beat_market ? '<span class="badge badge-buy">yes</span>' : '<span class="badge badge-avoid">no</span>'}</td>
        <td class="${regimeChangedClass(Boolean(regime.ready_for_shadow_spawn), prior ? Boolean(priorRegime.ready_for_shadow_spawn) : null)}">${regime.ready_for_shadow_spawn ? '<span class="badge badge-buy">yes</span>' : '<span class="badge badge-neutral">no</span>'}</td>
        <td class="small ${regimeChangedClass((regime.flags || []).slice(0, 2).join(", "), (priorRegime.flags || []).slice(0, 2).join(", "))}">${esc((regime.flags || []).slice(0, 2).join(", ") || "—")}</td>
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
        <p class="small muted">Δ columns are week-over-week vs the prior Sunday snapshot (newest rows first). Unchanged filter/gate cells stay muted.</p>
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
  // Track then week (oldest→newest within each track) so per-track trends scan cleanly.
  trackWeekRows.sort((a, b) => {
    const trackA = String(a.track_id || a.track_label || "");
    const trackB = String(b.track_id || b.track_label || "");
    const byTrack = trackA.localeCompare(trackB);
    if (byTrack !== 0) return byTrack;
    return String(a.week_ending || "").localeCompare(String(b.week_ending || ""));
  });

  const paperTrackGroups = groupPaperTracksById(trackWeekRows);
  const paperTrackTable = paperTrackGroups.length
    ? `<div class="paper-tracks-by-week" role="list">
        ${paperTrackGroups
          .map((group) => {
            const latest = group.weeks[group.weeks.length - 1] || {};
            const story = paperTrackStory(group.weeks);
            const weekCount = group.weeks.length;
            const primaryBadge = group.is_primary
              ? `<span class="badge badge-info">primary</span>`
              : "";
            const excessCls = alphaClass(latest.excess_after_costs);
            const weekRows = group.weeks
              .map(
                (row) => `<tr>
                  <td>${esc(row.week_ending || "—")}</td>
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
            return `<details class="paper-track-details overview-secondary" role="listitem">
              <summary class="paper-track-summary">
                <span class="paper-track-summary-inner">
                  <span class="paper-track-summary-main">
                    <strong>${esc(group.track_label)}</strong>
                    ${primaryBadge}
                    <span class="small muted">${esc(group.track_id)}</span>
                  </span>
                  <span class="paper-track-summary-metrics">
                    <span class="${excessCls}">${fmtSignedPct(latest.excess_after_costs)} excess</span>
                    <span class="small muted">· ${weekCount} week${weekCount === 1 ? "" : "s"}</span>
                    <span class="small muted">· thru ${esc(latest.week_ending || "—")}</span>
                  </span>
                  <span class="paper-track-story small">${esc(story)}</span>
                </span>
              </summary>
              <div class="table-wrap paper-track-week-table">
                <table class="eng-queue-table sunday-review-table">
                  <thead>
                    <tr>
                      <th>Week</th>
                      <th>Excess vs ^FTSE</th>
                      <th>Benchmark</th>
                      <th>Cost drag</th>
                      <th>Trades</th>
                      <th>Marks</th>
                      <th>min_conv</th>
                      <th>Epoch excess</th>
                    </tr>
                  </thead>
                  <tbody>${weekRows}</tbody>
                </table>
              </div>
            </details>`;
          })
          .join("")}
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
    <section class="automation-section automation-section-full sunday-review-section analysis-section" id="analysis-sunday">
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

      <details class="analysis-block overview-secondary">
        <summary>
          <strong>Exclusion ladder</strong>
          <span class="small muted">— ${esc(String(weekly.length))} week pair${weekly.length === 1 ? "" : "s"} · step ${esc(exclusion.recommended_step_id || review.recommended_exclusion_step || "u4")} · expand for table</span>
        </summary>
        <p class="small muted">Forward equal-weight returns per archived week pair (gross of costs).</p>
        ${exclusionTable}
      </details>

      <details class="analysis-block overview-secondary">
        <summary>
          <strong>Regime snapshots</strong>
          <span class="small muted">— ${esc(String(history.length))} week${history.length === 1 ? "" : "s"} · expand for filter / book / ops columns</span>
        </summary>
        <p class="small muted">
          One row per publish week. Filter health: step, cumul. excl. α, +α rate, pairs.
          Book health: primary excess + beat mkt. Ops gates: shadow ready + flags.
          Flat filter/gate columns with only primary excess moving means the live book is slipping while the exclusion case is unchanged.
        </p>
        ${regimeTable}
      </details>

      <h3>Paper tracks by week</h3>
      <p class="small muted">One summary row per track (story from <strong>price-only</strong> excess vs ^FTSE / cost / marks). Expand a track for week-by-week detail — weeks oldest→newest. Canonical assessment is <strong>total return vs FTAL.L</strong> on Observe (not this price-only table, not dual-suite A/B).</p>
      ${paperTrackTable}

      <details class="analysis-block overview-secondary">
        <summary>
          <strong>Experiments</strong>
          <span class="small muted">— ${esc(String(experiments.length))} in ledger · expand for gate table</span>
        </summary>
        <p class="small muted">Unified assessment ledger — new shadows and tracks appear automatically when spawned.</p>
        ${experimentTable}
      </details>
    </section>`;
}

const ANALYSIS_SECTION_IDS = ["observe", "sunday", "charts", "deep", "postrun", "memos"];
let analysisSectionId = "observe";

/**
 * Investment model switcher catalog (Analysis → Observe).
 * ≤1 live capital path (F5). Observe seals may be many; append here when sealed.
 * Pattern for future models: { id, label, shortLabel, mode: "live"|"observe",
 * registrationId, deferredId, opsDoc, emptyHint }.
 */
const INVESTMENT_MODELS = [
  {
    id: "strand-a",
    label: "Strand A",
    shortLabel: "A · live",
    mode: "live",
    modeLabel: "Live capital",
    registrationId: null,
    deferredId: null,
    opsDoc: "docs/ops/assessment-scoreboard.md",
    emptyHint: "Assessment scoreboard publishes with daily ops-monitor.",
    blurb:
      "Sole live / capital path until promote (F5). Assessment scoreboard + paper tracks — not an observe seal.",
  },
  {
    id: "n200",
    label: "N200 tech timing",
    shortLabel: "N200 · observe",
    mode: "observe",
    modeLabel: "Observe-only",
    registrationId: "strand-b-plain-value-tech-timing-v0",
    deferredId: "N200",
    opsDoc: "docs/ops/n200-tech-timing-observe.md",
    emptyHint: "N200 observe store not published yet (check_n200_tech_timing_observe).",
    blurb:
      "Sealed observe: buy-tier identity + ±14d entry/exit brackets. Alone scoreboards — never auto-promotes (F8).",
  },
  {
    id: "n201",
    label: "N201 short-horizon",
    shortLabel: "N201 · observe",
    mode: "observe",
    modeLabel: "Observe-only",
    registrationId: "strand-c-short-horizon-value-mom-v0",
    deferredId: "N201",
    opsDoc: "docs/ops/n201-value-mom-observe.md",
    emptyHint: "N201 observe store not published yet (check_n201_value_mom_observe).",
    blurb:
      "Sealed observe (launch-queue waiter): plain EY + 12–1 mom + financial_health, fixed stake. Alone scoreboards — never auto-promotes (F8).",
  },
  {
    id: "n206",
    label: "N206 plain EY",
    shortLabel: "N206 · observe",
    mode: "observe",
    modeLabel: "Observe-only",
    registrationId: "strand-d-plain-ey-identity-v0",
    deferredId: "N206",
    opsDoc: "docs/ops/n206-plain-ey-observe.md",
    emptyHint: "N206 observe store not published yet (check_n206_plain_ey_observe).",
    blurb:
      "Sealed observe: patient plain EY top-30% + financial_health, fixed stake, no momentum filter. Alone-first — influences_live false; never auto-promotes or crowns an assessment primary (F8).",
  },
  {
    id: "n210",
    label: "N210 AI judgment",
    shortLabel: "N210 · observe",
    mode: "observe",
    modeLabel: "Observe-only",
    registrationId: "strand-e-ai-judgment-fixed-stake-v0",
    deferredId: "N210",
    opsDoc: "docs/ops/n210-ai-judgment-observe.md",
    emptyHint: "N210 observe store not published yet (check_n210_ai_judgment_observe).",
    blurb:
      "B3 sealed observe (launch-queue waiter): fixed-stake AI/filter judgment; fair-cost episode % primary. Shadow only — never assessment primary crown; matched-30 untouched (F8).",
  },
];

const INVESTMENT_MODEL_IDS = new Set(INVESTMENT_MODELS.map((m) => m.id));
let investmentModelId = "strand-a";

function normalizeInvestmentModel(value) {
  const key = String(value || "")
    .toLowerCase()
    .replace(/_/g, "-");
  if (key === "a" || key === "strand-a" || key === "live" || key === "strand_a") return "strand-a";
  if (key === "b" || key === "n200" || key === "strand-b" || key === "tech-timing") return "n200";
  if (key === "c" || key === "n201" || key === "strand-c" || key === "value-mom") return "n201";
  if (
    key === "d" ||
    key === "n206" ||
    key === "strand-d" ||
    key === "plain-ey" ||
    key === "plain_ey"
  ) {
    return "n206";
  }
  if (
    key === "e" ||
    key === "n210" ||
    key === "strand-e" ||
    key === "ai-judgment" ||
    key === "ai_judgment"
  ) {
    return "n210";
  }
  if (INVESTMENT_MODEL_IDS.has(key)) return key;
  return "strand-a";
}

/** True only for explicit model hash tokens — not Analysis section ids like sunday/charts. */
function isInvestmentModelHashToken(value) {
  const key = String(value || "")
    .toLowerCase()
    .replace(/_/g, "-");
  if (!key || ANALYSIS_SECTION_IDS.includes(key)) return false;
  return (
    INVESTMENT_MODEL_IDS.has(key) ||
    key === "a" ||
    key === "live" ||
    key === "strand-a" ||
    key === "strand_a" ||
    key === "b" ||
    key === "strand-b" ||
    key === "tech-timing" ||
    key === "c" ||
    key === "strand-c" ||
    key === "value-mom" ||
    key === "d" ||
    key === "strand-d" ||
    key === "plain-ey" ||
    key === "plain_ey" ||
    key === "e" ||
    key === "strand-e" ||
    key === "ai-judgment" ||
    key === "ai_judgment"
  );
}

function investmentModelMeta(modelId) {
  const id = normalizeInvestmentModel(modelId);
  return INVESTMENT_MODELS.find((m) => m.id === id) || INVESTMENT_MODELS[0];
}

function normalizeAnalysisSection(value) {
  const key = String(value || "").toLowerCase();
  if (key === "chart" || key === "chart-outcomes" || key === "charts") return "charts";
  if (key === "post-run" || key === "postrun" || key === "post_run") return "postrun";
  if (key === "memo" || key === "memos" || key === "research") return "memos";
  if (ANALYSIS_SECTION_IDS.includes(key)) return key;
  return "observe";
}

function renderAnalysisSubnav(activeId) {
  const active = normalizeAnalysisSection(activeId);
  const labels = {
    observe: "Observe",
    sunday: "Sunday",
    charts: "Charts",
    deep: "Deep",
    postrun: "Post-run",
    memos: "Memos",
  };
  return `<nav class="paper-subnav analysis-subnav" aria-label="Analysis sections">
    ${ANALYSIS_SECTION_IDS.map(
      (id) =>
        `<button type="button" class="paper-subtab${
          id === active ? " active" : ""
        }" data-analysis-section="${id}">${esc(labels[id])}</button>`
    ).join("")}
  </nav>
  <p class="small muted analysis-ia-contract" style="margin:0.35rem 0 0.75rem">
    Analysis is a review surface — use the <strong>model switcher</strong> under Observe to flip
    Strand A (live capital) vs sealed observe models (N200 / N201 / N210). ≤1 live path (F5);
    observe views never imply a second capital book. Dense Sunday tables default-collapsed;
    full pipeline cards also live on Automation → Queue.
  </p>`;
}

function syncAnalysisHash() {
  const section = normalizeAnalysisSection(analysisSectionId);
  if (section === "observe") {
    const model = normalizeInvestmentModel(investmentModelId);
    if (model === "strand-a") {
      history.replaceState(null, "", "#analysis");
      return;
    }
    history.replaceState(null, "", `#analysis/observe/${model}`);
    return;
  }
  history.replaceState(null, "", `#analysis/${section}`);
}

function jumpToAnalysisSection(sectionId, { updateHash = true } = {}) {
  analysisSectionId = normalizeAnalysisSection(sectionId);
  const panel = document.getElementById("panel-analysis");
  if (!panel) return;
  panel.querySelectorAll(".analysis-subnav .paper-subtab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.analysisSection === analysisSectionId);
  });
  const target = panel.querySelector(`#analysis-${analysisSectionId}`);
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  if (updateHash) syncAnalysisHash();
}

function jumpToInvestmentModel(modelId, { updateHash = true, scroll = true } = {}) {
  investmentModelId = normalizeInvestmentModel(modelId);
  analysisSectionId = "observe";
  if (dashboardData) {
    renderAnalysis(dashboardData);
  }
  if (scroll) {
    window.requestAnimationFrame(() => {
      const panel = document.getElementById("panel-analysis");
      const target = panel?.querySelector("#analysis-observe");
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  if (updateHash) syncAnalysisHash();
}

function bindAnalysisPanel(panel) {
  if (!panel || panel.dataset.analysisBound === "1") return;
  panel.dataset.analysisBound = "1";
  panel.addEventListener("click", (event) => {
    const modelBtn = event.target.closest("[data-investment-model]");
    if (modelBtn) {
      event.preventDefault();
      jumpToInvestmentModel(modelBtn.dataset.investmentModel);
      return;
    }
    const sub = event.target.closest("[data-analysis-section]");
    if (sub) {
      event.preventDefault();
      jumpToAnalysisSection(sub.dataset.analysisSection);
      return;
    }
    const lifecycleJump = event.target.closest("[data-lifecycle-jump]");
    if (lifecycleJump) {
      event.preventDefault();
      lifecycleSubpage = normalizeLifecycleSubpage(
        lifecycleJump.dataset.lifecycleJump || "positions"
      );
      activateTab("lifecycle", { updateHash: true });
      if (dashboardData) renderLifecycle(dashboardData);
      syncLifecycleHash();
      return;
    }
    const tabJump = event.target.closest("[data-tab-jump]");
    if (tabJump) {
      event.preventDefault();
      activateTab(tabJump.dataset.tabJump, { updateHash: true });
    }
  });
}

function renderInvestmentModelSwitcher(activeModelId) {
  const active = normalizeInvestmentModel(activeModelId);
  const meta = investmentModelMeta(active);
  const buttons = INVESTMENT_MODELS.map((m) => {
    const modeClass = m.mode === "live" ? "model-mode-live" : "model-mode-observe";
    const badge =
      m.mode === "live"
        ? `<span class="badge badge-buy model-mode-badge">live</span>`
        : `<span class="badge badge-info model-mode-badge">observe</span>`;
    return `<button type="button" class="paper-subtab investment-model-tab ${modeClass}${
      m.id === active ? " active" : ""
    }" data-investment-model="${esc(m.id)}" title="${esc(m.blurb)}">${esc(
      m.shortLabel
    )} ${badge}</button>`;
  }).join("");
  const runbookUrl = meta.opsDoc ? githubOpsDocUrl(meta.opsDoc) : "";
  return `
    <div class="investment-model-switcher" role="group" aria-label="Investment model">
      <div class="investment-model-switcher-head">
        <h3 class="investment-model-switcher-title">Investment model</h3>
        <p class="small muted" style="margin:0">
          Switch scoreboards — <strong>one live capital path</strong> (Strand A);
          N200 / N201 / N206 / N210 are sealed observe-only (alone-first; never auto-promote).
        </p>
      </div>
      <nav class="paper-subnav investment-model-subnav" aria-label="Investment models">
        ${buttons}
      </nav>
      <p class="small investment-model-active-blurb">
        <span class="badge ${meta.mode === "live" ? "badge-buy" : "badge-info"}">${esc(
          meta.modeLabel
        )}</span>
        ${esc(meta.blurb)}
        ${
          meta.registrationId
            ? ` · <code>${esc(meta.registrationId)}</code>`
            : ""
        }
        ${
          runbookUrl
            ? ` · <a href="${esc(runbookUrl)}" target="_blank" rel="noopener">runbook</a>`
            : ""
        }
      </p>
    </div>`;
}

function renderAnalysisObserveForModel(data, modelId) {
  const id = normalizeInvestmentModel(modelId);
  if (id === "n200") {
    return `
      ${renderInvestmentModelCompanionStrip(data, "n200")}
      ${renderModelLifecycleMonitor(data, "n200")}
      ${renderN200PipelineHealthSection(data, { compact: false })}
      ${renderObservePathScoreboardPanel(data, "n200")}
      <p class="small muted">
        Compact Automation strip remains on
        <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue &amp; hunter</button>.
      </p>`;
  }
  if (id === "n201") {
    return `
      ${renderInvestmentModelCompanionStrip(data, "n201")}
      ${renderModelLifecycleMonitor(data, "n201")}
      ${renderN201PipelineHealthSection(data, { compact: false })}
      ${renderObservePathScoreboardPanel(data, "n201")}
      <p class="small muted">
        Compact Automation strip remains on
        <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue &amp; hunter</button>.
      </p>`;
  }
  if (id === "n206") {
    return `
      ${renderInvestmentModelCompanionStrip(data, "n206")}
      ${renderModelLifecycleMonitor(data, "n206")}
      ${renderN206PipelineHealthSection(data, { compact: false })}
      ${renderObservePathScoreboardPanel(data, "n206")}
      <p class="small muted">
        Compact Automation strip remains on
        <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue &amp; hunter</button>.
      </p>`;
  }
  if (id === "n210") {
    return `
      ${renderInvestmentModelCompanionStrip(data, "n210")}
      ${renderModelLifecycleMonitor(data, "n210")}
      ${renderN210PipelineHealthSection(data, { compact: false })}
      ${renderObservePathScoreboardPanel(data, "n210")}
      <p class="small muted">
        Compact Automation strip remains on
        <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue &amp; hunter</button>.
      </p>`;
  }
  // Strand A — live capital path surfaces.
  return `
    ${renderInvestmentModelCompanionStrip(data, "strand-a")}
    ${renderModelLifecycleMonitor(data, "strand-a")}
    ${renderAssessmentScoreboardPanel(data)}
    ${renderTotalReturnVsPricePanel(data)}
    ${renderPaperTrackBucketsPanel(data)}
    ${renderObserveUtilizationSection(data, { compact: true })}`;
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
  if (postRun && (postRun.executive_summary || postRun.full_text || postRun.persistent_weaknesses)) {
    const clearanceUrl = githubOpsDocUrl("docs/ops/post-run-improvement-clearance.md");
    const sectionCard = (title, body, { noteHtml = "", collapsed = false } = {}) => {
      if (!body) return "";
      const content = `<p>${esc(body).replace(/\n/g, "<br>")}</p>`;
      if (collapsed) {
        return `<details class="overview-secondary post-run-section" style="margin-top:0.75rem">
          <summary><strong>${esc(title)}</strong></summary>
          ${noteHtml}
          ${content}
        </details>`;
      }
      return `<div class="card post-run-section" style="margin-top:0.75rem">
        <h3 style="margin-top:0">${esc(title)}</h3>
        ${noteHtml}
        ${content}
      </div>`;
    };
    const weaknessesNote = `<p class="small muted" style="margin-top:0">
      Theme rollup across accumulated gap-fill / model suggestions — <strong>not</strong> an engineering backlog.
      Do not “fix every bullet.” Clearance uses ingest factory → eng queue → narrative refresh
      (${clearanceUrl ? `<a href="${esc(clearanceUrl)}" target="_blank" rel="noopener">post-run clearance policy</a>` : "ops clearance policy"}).
      Actionable tickets live on <strong>Automation → Engineering queue</strong>.
    </p>`;
    postRunHtml = `
      <section class="analysis-section" id="analysis-postrun">
      <h2 style="margin-top:0">Post-run improvement review</h2>
      <p class="small muted" style="margin-top:0">
        Structured snapshot from the last Sunday email / deep-analysis pass — presentation for humans.
        Does not rewrite learning books or auto-dispatch from this panel alone.
      </p>
      ${sectionCard("Executive summary", postRun.executive_summary)}
      ${sectionCard("Persistent weaknesses", postRun.persistent_weaknesses, {
        noteHtml: weaknessesNote,
      })}
      ${sectionCard("This week’s findings", postRun.this_week_findings)}
      ${sectionCard("Improvement plan", postRun.improvement_plan)}
      ${sectionCard("Defer", postRun.defer, { collapsed: true })}
      ${
        postRun.full_text
          ? `<details class="overview-secondary" style="margin-top:0.75rem">
          <summary>Full text (archive)</summary>
          <p class="small muted">Raw narrative kept for search; structured sections above are primary.</p>
          <p>${esc(postRun.full_text).replace(/\n/g, "<br>")}</p>
        </details>`
          : ""
      }
      </section>`;
  } else {
    postRunHtml = `<section class="analysis-section" id="analysis-postrun"><h2>Post-run improvement review</h2><div class="empty-state">No post-run review published yet.</div></section>`;
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

  const chartBlock =
    renderChartOutcomeReview(data, { compact: true }) ||
    '<div class="empty-state">Chart outcome review not published yet. Run <code>ftse-chart-outcomes</code> after buy-tier charts exist.</div>';

  panel.innerHTML = `
    ${renderAnalysisSubnav(analysisSectionId)}
    <section class="analysis-section" id="analysis-observe">
      ${renderInvestmentModelSwitcher(investmentModelId)}
      <div class="investment-model-view" data-active-model="${esc(
        normalizeInvestmentModel(investmentModelId)
      )}">
        ${renderAnalysisObserveForModel(data, investmentModelId)}
      </div>
    </section>
    ${renderSundayReview(data)}
    <section class="analysis-section" id="analysis-charts">
      <h2>Buy-tier chart outcomes</h2>
      ${chartBlock}
    </section>
    <section class="analysis-section" id="analysis-deep">
      <h2>Portfolio deep analysis</h2>
      ${deepHtml}
    </section>
    ${postRunHtml}
    <section class="analysis-section" id="analysis-memos">
      <h2>Strong buy research memos</h2>
      ${researchHtml}
    </section>
  `;

  panel.querySelectorAll("[data-memo-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.memoIndex);
      openMemo(research[index]);
    });
  });
  bindChartButtons(panel, new Map((data.reports || []).map((r) => [r.ticker, r])));
  bindAnalysisPanel(panel);
  // Re-apply section highlight after re-render (hash may already target a section).
  panel.querySelectorAll(".analysis-subnav .paper-subtab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.analysisSection === analysisSectionId);
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

function signedReturnClass(value) {
  if (value == null || Number.isNaN(Number(value))) return "";
  return Number(value) >= 0 ? "text-positive" : "text-negative";
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
        <strong>Churn ops window</strong> (${lookback}d) — not an investment thesis horizon.
        Cost-drag tint uses Suite A stress-native thresholds (~6% round-trip); canonical performance is the assessment scoreboard (total return vs FTAL.L), not Suite B price-only excess.
        Observe-only rollups from weekday decision-review.
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

function renderIngestDeviationsSection(payload) {
  const rawItems = (payload && payload.open_items) || (payload && payload.items) || [];
  const openItems = rawItems.filter((row) => !row.status || row.status === "open");
  const openCount = Number(payload && payload.open_count != null ? payload.open_count : openItems.length);
  const reviewed = (payload && payload.recent_reviewed) || [];
  const updated = payload && payload.updated_at ? fmtDate(payload.updated_at) : "—";

  const openHtml = openItems.length
    ? `<ul class="human-tasks-list">${openItems
        .map((row) => {
          const approve = (row.reprocess || {}).approve || "";
          const dismiss = (row.reprocess || {}).dismiss || "";
          const triage = row.signal_triage || {};
          const triageAction = triage.proposed_action || "";
          const triageHuman = triage.human_action || "";
          const triageSignal = triage.signal || "";
          const triageHtml = triageAction
            ? `<div class="small"><span class="badge badge-neutral" title="Observe-only; does not auto-apply">signal triage</span> ${esc(triageAction)}${triageHuman ? ` → <code>${esc(triageHuman)}</code>` : ""}${triageSignal ? ` <span class="muted">(${esc(triageSignal)})</span>` : ""}${triage.rationale ? `<div class="muted">${esc(triage.rationale)}</div>` : ""}</div>`
            : "";
          return `<li class="human-task-item ingest-deviation-open">
            <strong>${esc(row.ticker || row.id || "Deviation")}</strong>
            <span class="badge badge-watch">${esc(row.kind || "open")}</span>
            <span class="small muted">${esc(row.market_id || "")}</span>
            <div class="small muted">${esc(row.summary || "")}</div>
            ${triageHtml}
            ${
              approve
                ? `<div class="small"><strong>Reprocess</strong> <code>${esc(approve)}</code></div>`
                : ""
            }
            ${
              dismiss
                ? `<div class="small muted">Dismiss <code>${esc(dismiss)}</code></div>`
                : ""
            }
          </li>`;
        })
        .join("")}</ul>`
    : '<p class="muted">No open ingest deviations. Post-ingest will add a row when IR retries fail or a weekday cap leaves IWB with no gain.</p>';

  const reviewedHtml = reviewed.length
    ? `<details class="ingest-deviations-reviewed"><summary class="small">Recently reviewed (${reviewed.length})</summary>
        <ul class="human-tasks-list">${reviewed
          .map(
            (row) => `<li class="human-task-item human-task-auto">
              <strong>${esc(row.ticker || row.id || "")}</strong>
              <span class="badge badge-neutral">${esc(row.status || "")}</span>
              <div class="small muted">${esc(row.summary || "")}</div>
            </li>`
          )
          .join("")}</ul></details>`
    : "";

  return `
    <section class="automation-section automation-section-full ingest-deviations-section">
      <h2>Ingest deviations</h2>
      <p class="small muted" style="margin-top:0">
        Auto-recorded after library deepen. Observe-only signal triage:
        leftover → dismiss, buy → park/hunter, strong_buy → pin (never auto-applied).
        URL replacement stays a judged allowlist edit; approve writes a 7-day intensive pin
        for the next euro slot (Pages cannot dispatch).
        ${openCount ? ` <strong>${esc(String(openCount))} open</strong>.` : ""}
        Updated ${esc(updated)}.
      </p>
      ${openHtml}
      ${reviewedHtml}
    </section>`;
}

function renderHumanTasksChecklistSection(checklist, board) {
  const runbookUrl = humanTaskDocUrl(checklist || board || {}, {
    doc_path: (checklist && checklist.runbook_path) || (board && board.runbook_path) || "docs/ops/human-tasks-checklist.md",
  });
  const updated =
    (board && board.generated_at) ||
    (checklist && checklist.updated_at) ||
    (board && board.checklist_updated_at);

  if (board && Array.isArray(board.tasks)) {
    const counts = board.counts || {};
    const tasks = board.tasks || [];
    const automated = board.automated_tasks || [];
    const cardsHtml = tasks.length
      ? `<div class="human-tasks-list human-tasks-cards">${tasks
          .map((task) => renderHumanTaskCard(task))
          .join("")}</div>`
      : '<p class="muted">No open human gates in the checklist.</p>';
    const autoHtml = automated.length
      ? `<details class="human-tasks-automated"><summary class="small">Automated CI (${automated.length})</summary>
          <ul class="human-tasks-list">${automated
            .map((task) => {
              const docUrl = task.doc_url || humanTaskDocUrl(board, task);
              const docLink = docUrl
                ? ` <a href="${esc(docUrl)}" target="_blank" rel="noopener" class="small">runbook</a>`
                : "";
              return `<li class="human-task-item human-task-auto">
                <strong>${esc(task.title || task.id || "Task")}</strong>
                <span class="badge badge-neutral">automated</span>${docLink}
                <div class="small muted">${esc(task.summary || "")}</div>
              </li>`;
            })
            .join("")}</ul></details>`
      : "";
    return `
      <section class="automation-section automation-section-full human-tasks-section">
        <h2>Human tasks</h2>
        <p class="small muted" style="margin-top:0">
          Click a row for analysis, Acknowledge, and Approve on promotion gates.
          New / changed analysis rises to the top; acknowledged tasks fall to the bottom.
          ${runbookUrl ? `<a href="${esc(runbookUrl)}" target="_blank" rel="noopener">Full checklist</a>` : ""}
          ${updated ? ` · updated ${esc(fmtDate(updated))}` : ""}
          · <span class="badge badge-watch">${esc(String(counts.new_info || 0))} new</span>
          <span class="badge badge-neutral">${esc(String(counts.unacked || 0))} open</span>
          <span class="badge badge-neutral">${esc(String(counts.acked || 0))} acked</span>
        </p>
        ${cardsHtml}
        ${autoHtml}
      </section>`;
  }

  if (!checklist || !Array.isArray(checklist.sections) || !checklist.sections.length) {
    return `
      <section class="automation-section automation-section-full human-tasks-section">
        <h2>Human tasks</h2>
        <p class="muted">Checklist not published yet.</p>
      </section>`;
  }

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

function humanTaskBucketBadge(bucket, ack) {
  if (bucket === "new_info" || (ack && ack.stale)) {
    return '<span class="badge badge-buy" title="Analysis changed since last ack">new info</span>';
  }
  if (bucket === "acked" || (ack && ack.acked && !ack.stale)) {
    return '<span class="badge badge-neutral">acked</span>';
  }
  return '<span class="badge badge-watch">open</span>';
}

function renderHumanTaskCard(task) {
  const ack = task.ack || {};
  const analysis = task.analysis || {};
  const bucket = task.sort_bucket || (ack.stale ? "new_info" : ack.acked ? "acked" : "unacked");
  const docUrl = task.doc_url;
  const docLink = docUrl
    ? `<a href="${esc(docUrl)}" target="_blank" rel="noopener" class="small">runbook</a>`
    : "";
  const bullets = Array.isArray(analysis.bullets) ? analysis.bullets : [];
  const bulletsHtml = bullets.length
    ? `<ul class="human-task-analysis-list">${bullets
        .map((b) => `<li>${esc(b)}</li>`)
        .join("")}</ul>`
    : '<p class="small muted">No published analysis snippet yet — open the runbook.</p>';
  const ackEnabled = !(ack.acked && !ack.stale);
  const ackLabel = ack.acked && !ack.stale ? "Acknowledged" : "Acknowledge";
  const payload = JSON.stringify({
    task_id: task.id,
    decision: "ack_observe",
    finding_fingerprint: analysis.fingerprint || "",
  });
  const approvePayload = JSON.stringify({
    task_id: task.id,
    decision: "approve",
    finding_fingerprint: analysis.fingerprint || "",
  });
  const approveBtn = task.approval_gate
    ? `<button type="button" class="btn btn-primary human-task-approve-btn" data-human-task-ack="${esc(
        approvePayload
      )}" title="Record observe-only approval (does not auto-apply)">${esc(
        task.approval_label || "Approve"
      )}</button>`
    : "";
  return `<details class="human-task-card human-task-item sort-${esc(bucket)}" data-task-id="${esc(
    task.id || ""
  )}">
    <summary class="human-task-card-toggle">
      <span class="human-task-card-head">
        <strong>${esc(task.title || task.id || "Task")}</strong>
        ${humanTaskBucketBadge(bucket, ack)}
        <span class="badge badge-neutral">${esc(task.cadence || task.section_id || "")}</span>
        ${
          analysis.updated_at
            ? `<span class="small muted">${esc(fmtDate(analysis.updated_at))}</span>`
            : ""
        }
      </span>
      <span class="small muted human-task-card-headline">${esc(
        analysis.headline || task.summary || ""
      )}</span>
    </summary>
    <div class="human-task-card-panel">
      <p class="small">${esc(task.summary || "")}</p>
      <h4 class="small" style="margin:0.5rem 0 0.25rem">Analysis</h4>
      ${
        analysis.headline
          ? `<p class="small"><strong>${esc(analysis.headline)}</strong></p>`
          : ""
      }
      ${bulletsHtml}
      <p class="small muted" style="margin-top:0.5rem">${docLink}</p>
      <p class="human-task-actions">
        <button type="button" class="btn human-task-ack-btn${ackEnabled ? " btn-primary" : ""}" data-human-task-ack="${esc(
          payload
        )}" ${ackEnabled ? "" : "disabled"} aria-disabled="${ackEnabled ? "false" : "true"}" title="${esc(
          ackEnabled
            ? "Record observe-only ack via Supabase"
            : "Already acknowledged for this analysis"
        )}">${esc(ackLabel)}</button>
        ${approveBtn}
        <span class="small muted human-task-ack-status" aria-live="polite"></span>
      </p>
      <p class="small muted">Ack / Approve are observe-only records — they never auto-apply knobs, crons, or capital.</p>
    </div>
  </details>`;
}

function bindHumanTasksSection() {
  const panel = document.getElementById("panel-automation");
  if (!panel || panel.dataset.boundHumanTasks === "1") return;
  panel.dataset.boundHumanTasks = "1";
  panel.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-human-task-ack]");
    if (btn && panel.contains(btn)) {
      event.preventDefault();
      void acknowledgeHumanTaskFromCard(btn);
    }
  });
}

async function acknowledgeHumanTaskFromCard(button) {
  if (!button || button.disabled) return;
  const statusEl =
    button.parentElement && button.parentElement.querySelector(".human-task-ack-status");
  let payload = {};
  try {
    payload = JSON.parse(button.getAttribute("data-human-task-ack") || "{}");
  } catch {
    payload = {};
  }
  if (!payload.task_id) {
    if (statusEl) statusEl.textContent = "Missing task id";
    return;
  }
  const taskId = String(payload.task_id).trim();
  // Optimistic first: disable + bottom-sort before any await so in-flight
  // dashboard reloads / bridge latency cannot leave the card looking open.
  button.disabled = true;
  button.setAttribute("aria-disabled", "true");
  applyOptimisticHumanTaskAck(payload);
  setHumanTaskAckStatus(taskId, "Submitting…");
  try {
    if (isLocalDashboardServe()) {
      const response = await fetch("/api/human-task-ack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body.ok === false) {
        throw new Error(body.error || `HTTP ${response.status}`);
      }
      setHumanTaskAckStatus(taskId, "Recorded locally");
      await reloadDashboard({ silent: true });
      return;
    }
    if (!window.DashboardBridge) {
      throw new Error("Dashboard bridge unavailable");
    }
    const bridgeReady = await window.DashboardBridge.init();
    if (!bridgeReady) throw new Error("Dashboard bridge not configured");
    const queueFn =
      typeof window.DashboardBridge.queueCommand === "function"
        ? window.DashboardBridge.queueCommand.bind(window.DashboardBridge)
        : null;
    const queued = queueFn
      ? await queueFn("human-task-ack", payload, (msg) => setHumanTaskAckStatus(taskId, msg))
      : await window.DashboardBridge.submitCommand(
          "human-task-ack",
          payload,
          (msg) => setHumanTaskAckStatus(taskId, msg),
          { wait: false }
        );
    setHumanTaskAckStatus(taskId, "Acknowledged — syncing to git…");
    // Soft refresh must keep session overlay until git sidecar catch-up.
    syncHumanTasksBoardOverlay(dashboardData);
    const commandId = queued && queued.id;
    const waitFn =
      commandId && typeof window.DashboardBridge.waitForCommand === "function"
        ? window.DashboardBridge.waitForCommand.bind(window.DashboardBridge)
        : null;
    if (!waitFn) {
      await reloadDashboard({ silent: true, rebuild: true });
      return;
    }
    try {
      await waitFn(commandId, (msg) => setHumanTaskAckStatus(taskId, msg));
      setHumanTaskAckStatus(taskId, "Recorded");
      await reloadDashboard({ silent: true, rebuild: true });
    } catch (waitErr) {
      const msg = waitErr && waitErr.message ? waitErr.message : String(waitErr);
      if (/timed out/i.test(msg)) {
        // Command still pending — keep optimistic bottom sort.
        syncHumanTasksBoardOverlay(dashboardData);
        if (dashboardData) renderAutomation(dashboardData);
        setHumanTaskAckStatus(
          taskId,
          "Queued — card moved; git sync still pending (Run workflow to drain)"
        );
        return;
      }
      revertOptimisticHumanTaskAck(taskId);
      setHumanTaskAckStatus(taskId, msg);
      const card = document.querySelector(
        `#panel-automation .human-task-card[data-task-id="${
          (window.CSS && CSS.escape && CSS.escape(taskId)) || taskId
        }"]`
      );
      const btn =
        card &&
        card.querySelector(
          `.human-task-ack-btn[data-human-task-ack], .human-task-approve-btn[data-human-task-ack]`
        );
      if (btn) btn.disabled = false;
    }
  } catch (err) {
    revertOptimisticHumanTaskAck(taskId);
    const msg = err && err.message ? err.message : String(err);
    setHumanTaskAckStatus(taskId, msg);
    if (statusEl && statusEl.isConnected) statusEl.textContent = msg;
    button.disabled = false;
    const card = document.querySelector(
      `#panel-automation .human-task-card[data-task-id="${
        (window.CSS && CSS.escape && CSS.escape(taskId)) || taskId
      }"]`
    );
    const btn =
      card &&
      card.querySelector(
        `.human-task-ack-btn[data-human-task-ack], .human-task-approve-btn[data-human-task-ack]`
      );
    if (btn) btn.disabled = false;
  }
}

function resolveObserveUtilization(data) {
  if (data.observe_utilization) return data.observe_utilization;
  const health = resolveQueueHealth(data);
  return health?.observe_utilization || null;
}

function resolveLifecycleMaturity(data) {
  if (data.lifecycle_maturity_trajectory) return data.lifecycle_maturity_trajectory;
  const health = resolveQueueHealth(data);
  return health?.lifecycle_maturity_trajectory || null;
}

function resolveN200PipelineHealth(data) {
  if (data.n200_pipeline_health) return data.n200_pipeline_health;
  const health = resolveQueueHealth(data);
  if (health?.n200_pipeline_health) return health.n200_pipeline_health;
  // Fallback: project a minimal client-side view from the observe sidecar.
  const store = data.n200_tech_timing_observe;
  if (!store || typeof store !== "object") return null;
  const phase = store.phase || {};
  const volume = store.volume_gate || {};
  const levers = store.per_lever_scoreboards || {};
  const entrySb = store.entry_lever_scoreboard || {};
  const exitSb = store.exit_lever_scoreboard || {};
  return {
    observe_only: true,
    influences_live: false,
    not_alpha_signal: true,
    not_capital_ready: true,
    registration_id: store.registration_id,
    deferred_id: store.deferred_id || "N200",
    headline: "N200 observe store loaded (client projection).",
    disclaimer:
      "Phase floor, volume gate, and per-lever scoreboards measure factory mechanism / lever quality — not alpha or capital readiness (F8). Lever wins are independent of path P&L. Observe-only.",
    store_present: true,
    store_generated_at: store.generated_at || null,
    phase: {
      entries_per_week: phase.entries_per_week,
      floor: phase.floor,
      floor_met: !!phase.floor_met,
    },
    volume_gate: {
      met: !!volume.met,
      episodes: store.completed_entry_episodes ?? 0,
      weeks: store.calendar_weeks_spanned ?? 0,
      min_episodes: volume.min_episodes,
      min_weeks: volume.min_weeks,
    },
    per_lever: {
      present: !!(levers.entry_verdict || entrySb.verdict),
      independent_of_path_pnl: true,
      cost_basis: levers.cost_basis || entrySb.cost_basis || "fair_market_table",
      not_capital_ready: true,
      entry_verdict: levers.entry_verdict || entrySb.verdict || null,
      exit_verdict: levers.exit_verdict || exitSb.verdict || null,
      entry_margin_vs_best_alt:
        levers.entry_margin_vs_best_alt ?? entrySb.margin_vs_best_alt ?? null,
      exit_margin_vs_best_alt:
        levers.exit_margin_vs_best_alt ?? exitSb.margin_vs_best_alt ?? null,
      detail: "Client projection from observe sidecar.",
    },
    freshness: { state: "unknown", detail: "Awaiting queue-health embed for freshness." },
    pipeline: {
      functioning: null,
      ops_check_ok: null,
      ops_run_at: null,
      detail: "Refresh with ops-monitor / queue health for full pipeline status.",
    },
    ops_doc: store.ops_doc || "docs/ops/n200-tech-timing-observe.md",
  };
}

function n200LeverBadge(verdict) {
  const key = String(verdict || "").toLowerCase();
  if (key === "win" || key === "tie") {
    return `<span class="badge badge-ii-yes">${esc(key)}</span>`;
  }
  if (key === "lose") {
    return `<span class="badge badge-ii-no">${esc(key)}</span>`;
  }
  if (key === "insufficient") {
    return `<span class="badge">${esc(key)}</span>`;
  }
  return `<span class="badge">${esc("—")}</span>`;
}

function n200GateBadge(met, { yes = "met", no = "not met" } = {}) {
  if (met === true) {
    return `<span class="badge badge-ii-yes">${esc(yes)}</span>`;
  }
  if (met === false) {
    return `<span class="badge badge-ii-no">${esc(no)}</span>`;
  }
  return `<span class="badge">${esc("—")}</span>`;
}

function renderN200PipelineHealthSection(data, { compact = false } = {}) {
  const payload = resolveN200PipelineHealth(data);
  const runbookUrl = githubOpsDocUrl("docs/ops/n200-tech-timing-observe.md");
  const sectionAttrs = compact
    ? ' class="automation-section automation-section-full n200-pipeline-health-section analysis-observe-compact"'
    : ' class="automation-section automation-section-full n200-pipeline-health-section"';
  if (!payload) {
    return `
      <section${sectionAttrs}>
        <h2>N200 pipeline health</h2>
        <p class="muted small">Observe store not published yet. Refreshes with daily ops-monitor (<code>check_n200_tech_timing_observe</code>).</p>
      </section>`;
  }
  const phase = payload.phase || {};
  const volume = payload.volume_gate || {};
  const freshness = payload.freshness || {};
  const pipeline = payload.pipeline || {};
  const entriesPw =
    phase.entries_per_week == null || !Number.isFinite(Number(phase.entries_per_week))
      ? "—"
      : String(Number(phase.entries_per_week));
  const floor =
    phase.floor == null || !Number.isFinite(Number(phase.floor))
      ? "—"
      : String(Number(phase.floor));
  const functioningBadge =
    pipeline.functioning === true
      ? `<span class="badge badge-ii-yes">functioning</span>`
      : pipeline.functioning === false
        ? `<span class="badge badge-ii-no">attention</span>`
        : `<span class="badge">unknown</span>`;
  const disclaimer = esc(
    payload.disclaimer ||
      "Phase floor = mechanism throughput, not alpha or capital readiness (F8)."
  );
  const metaLine = `<p class="small muted">Store ${esc(fmtDate(payload.store_generated_at))}
        · projection ${esc(fmtDate(payload.generated_at))}
        · ops ${esc(fmtDate(pipeline.ops_run_at))}
        · ${esc(payload.registration_id || "strand-b-plain-value-tech-timing-v0")}
      </p>`;
  const perLever = payload.per_lever || {};
  const entryVerdict = perLever.entry_verdict;
  const exitVerdict = perLever.exit_verdict;
  const fmtMargin = (v) => {
    if (v == null || !Number.isFinite(Number(v))) return "—";
    const n = Number(v);
    const pct = (n * 100).toFixed(2);
    return `${n >= 0 ? "+" : ""}${pct}pp`;
  };
  if (compact) {
    return `
      <section${sectionAttrs}>
        <h2>N200 pipeline health ${observeFreshnessBadge(freshness.state)} ${functioningBadge}</h2>
        <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
        ${metaLine}
        <p class="small muted" style="margin:0.35rem 0 0">
          Phase ${esc(entriesPw)}/${esc(floor)} ${n200GateBadge(!!phase.floor_met)}
          · volume ${n200GateBadge(!!volume.met)}
          (${esc(String(volume.episodes ?? "—"))} ep / ${esc(String(volume.weeks ?? "—"))} wk)
          · entry ${n200LeverBadge(entryVerdict)}
          · exit ${n200LeverBadge(exitVerdict)}
        </p>
        <p class="small muted" style="margin-bottom:0">
          Compact strip — full readout on
          <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue &amp; hunter</button>.
          Lever ≠ path P&L; not a promote signal (F8).
        </p>
      </section>`;
  }
  return `
    <section${sectionAttrs}>
      <h2>N200 / learning-factory pipeline ${observeFreshnessBadge(freshness.state)} ${functioningBadge}</h2>
      <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
      ${metaLine}
      <p class="small muted">${disclaimer}
        ${runbookUrl ? ` <a href="${esc(runbookUrl)}" target="_blank" rel="noopener">N200 runbook</a>` : ""}
      </p>
      <div class="grid n200-pipeline-grid" style="margin-top:0.75rem">
        <div class="card n200-pipeline-card">
          <h3>Phase floor ${n200GateBadge(!!phase.floor_met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(entriesPw)}<span class="n200-floor-den">/${esc(floor)}</span></div>
          </div>
          <p class="small muted">Entries/week vs sealed floor (O6). Throughput health only.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Volume gate ${n200GateBadge(!!volume.met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(String(volume.episodes ?? "—"))}<span class="n200-floor-den"> ep</span></div>
          </div>
          ${settingRow("Weeks", esc(String(volume.weeks ?? "—")))}
          ${settingRow(
            "Minimums",
            `≥${esc(String(volume.min_episodes ?? 24))} ep and ≥${esc(String(volume.min_weeks ?? 8))} wk`
          )}
          <p class="small muted">Review gate — not auto-promote.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Entry lever ${n200LeverBadge(entryVerdict)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value n200-lever-verdict">${esc(entryVerdict || "—")}</div>
          </div>
          ${settingRow("Margin vs best ±14d", esc(fmtMargin(perLever.entry_margin_vs_best_alt)))}
          ${settingRow("Cost basis", esc(perLever.cost_basis || "fair_market_table"))}
          <p class="small muted">Best-feasible at fair costs; independent of path P&L.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Exit lever ${n200LeverBadge(exitVerdict)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value n200-lever-verdict">${esc(exitVerdict || "—")}</div>
          </div>
          ${settingRow("Margin vs best ±14d", esc(fmtMargin(perLever.exit_margin_vs_best_alt)))}
          ${settingRow("Cost basis", esc(perLever.cost_basis || "fair_market_table"))}
          <p class="small muted">Best-feasible at fair costs; independent of path P&L.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Pipeline ${functioningBadge}</h3>
          ${settingRow("Store freshness", `${observeFreshnessBadge(freshness.state)} · ${esc(freshness.detail || "")}`)}
          ${settingRow(
            "Ops check",
            pipeline.ops_check_ok === true
              ? n200GateBadge(true, { yes: "ok" })
              : pipeline.ops_check_ok === false
                ? n200GateBadge(false, { no: pipeline.ops_finding_present ? "failed" : "absent" })
                : "—"
          )}
          ${settingRow("Last store refresh", esc(fmtDate(payload.store_generated_at)))}
          <p class="small muted">${esc(pipeline.detail || "")}</p>
        </div>
      </div>
      <p class="small muted" style="margin-top:0.75rem;margin-bottom:0">
        Observe-only strand B. Phase/lever green ≠ alpha or capital-ready. Never writes books/knobs (F8).
      </p>
    </section>`;
}

function resolveN206PipelineHealth(data) {
  if (data.n206_pipeline_health) return data.n206_pipeline_health;
  const health = resolveQueueHealth(data);
  if (health?.n206_pipeline_health) return health.n206_pipeline_health;
  const store = data.n206_plain_ey_observe;
  if (!store || typeof store !== "object") return null;
  const phase = store.phase || {};
  const volume = store.volume_gate || {};
  const path = store.path_scoreboard || {};
  return {
    observe_only: true,
    influences_live: false,
    not_alpha_signal: true,
    not_capital_ready: true,
    not_assessment_primary: true,
    alone_first: true,
    independent_of_fund_nav: true,
    launch_queue_waiter: true,
    data_deepen_requested: false,
    registration_id: store.registration_id,
    deferred_id: store.deferred_id || "N206",
    headline: "N206 observe store loaded (client projection).",
    disclaimer:
      "Phase floor and volume gate measure factory mechanism throughput — not alpha or capital readiness (F8). Fixed-stake episode % is independent of fund NAV. Alone-first. Observe-only; not assessment primary.",
    store_present: true,
    store_generated_at: store.generated_at || null,
    phase: {
      entries_per_week: phase.entries_per_week,
      floor: phase.floor,
      floor_met: !!phase.floor_met,
    },
    volume_gate: {
      met: !!volume.met,
      episodes: store.completed_entry_episodes ?? 0,
      weeks: store.calendar_weeks_spanned ?? 0,
      min_episodes: volume.min_episodes,
      min_weeks: volume.min_weeks,
    },
    path_scoreboard: path,
    freshness: { state: "unknown", detail: "Awaiting queue-health embed for freshness." },
    pipeline: {
      functioning: null,
      ops_check_ok: null,
      ops_run_at: null,
      detail: "Refresh with ops-monitor / queue health for full pipeline status.",
    },
    ops_doc: store.ops_doc || "docs/ops/n206-plain-ey-observe.md",
  };
}

function renderN206PipelineHealthSection(data, { compact = false } = {}) {
  const payload = resolveN206PipelineHealth(data);
  const runbookUrl = githubOpsDocUrl("docs/ops/n206-plain-ey-observe.md");
  const sectionAttrs = compact
    ? ' class="automation-section automation-section-full n206-pipeline-health-section analysis-observe-compact"'
    : ' class="automation-section automation-section-full n206-pipeline-health-section"';
  if (!payload) {
    return `
      <section${sectionAttrs}>
        <h2>N206 pipeline health</h2>
        <p class="muted small">Observe store not published yet. Refreshes with daily ops-monitor (<code>check_n206_plain_ey_observe</code>).</p>
      </section>`;
  }
  const phase = payload.phase || {};
  const volume = payload.volume_gate || {};
  const freshness = payload.freshness || {};
  const pipeline = payload.pipeline || {};
  const path = payload.path_scoreboard || {};
  const entriesPw =
    phase.entries_per_week == null || !Number.isFinite(Number(phase.entries_per_week))
      ? "—"
      : String(Number(phase.entries_per_week));
  const floor =
    phase.floor == null || !Number.isFinite(Number(phase.floor))
      ? "—"
      : String(Number(phase.floor));
  const functioningBadge =
    pipeline.functioning === true
      ? `<span class="badge badge-ii-yes">functioning</span>`
      : pipeline.functioning === false
        ? `<span class="badge badge-ii-no">attention</span>`
        : `<span class="badge">unknown</span>`;
  const waiterBadge = payload.launch_queue_waiter
    ? `<span class="badge badge-hold">existing panels</span>`
    : "";
  const disclaimer = esc(
    payload.disclaimer ||
      "Phase floor = mechanism throughput, not alpha or capital readiness (F8)."
  );
  const metaLine = `<p class="small muted">Store ${esc(fmtDate(payload.store_generated_at))}
        · projection ${esc(fmtDate(payload.generated_at))}
        · ops ${esc(fmtDate(pipeline.ops_run_at))}
        · ${esc(payload.registration_id || "strand-d-plain-ey-identity-v0")}
      </p>`;
  const pathMedian = path.smooth_ret_cohort_median;
  if (compact) {
    return `
      <section${sectionAttrs}>
        <h2>N206 pipeline health ${observeFreshnessBadge(freshness.state)} ${functioningBadge} ${waiterBadge}</h2>
        <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
        ${metaLine}
        <p class="small muted" style="margin:0.35rem 0 0">
          Phase ${esc(entriesPw)}/${esc(floor)} ${n200GateBadge(!!phase.floor_met)}
          · volume ${n200GateBadge(!!volume.met)}
          (${esc(String(volume.episodes ?? "—"))} ep / ${esc(String(volume.weeks ?? "—"))} wk)
          · path median ${pctOrDash(pathMedian)}
        </p>
        <p class="small muted" style="margin-bottom:0">
          Compact strip — full readout on Analysis model switcher (N206). Not a promote signal and not assessment primary (F8).
        </p>
      </section>`;
  }
  return `
    <section${sectionAttrs}>
      <h2>N206 / plain earnings yield ${observeFreshnessBadge(freshness.state)} ${functioningBadge} ${waiterBadge}</h2>
      <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
      ${metaLine}
      <p class="small muted">${disclaimer}
        ${runbookUrl ? ` <a href="${esc(runbookUrl)}" target="_blank" rel="noopener">N206 runbook</a>` : ""}
      </p>
      <div class="grid n200-pipeline-grid n206-pipeline-grid" style="margin-top:0.75rem">
        <div class="card n200-pipeline-card">
          <h3>Phase floor ${n200GateBadge(!!phase.floor_met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(entriesPw)}<span class="n200-floor-den">/${esc(floor)}</span></div>
          </div>
          <p class="small muted">Entries/week vs sealed floor. Throughput health only.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Volume gate ${n200GateBadge(!!volume.met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(String(volume.episodes ?? "—"))}<span class="n200-floor-den"> ep</span></div>
          </div>
          ${settingRow("Weeks", esc(String(volume.weeks ?? "—")))}
          ${settingRow(
            "Minimums",
            `≥${esc(String(volume.min_episodes ?? 48))} ep and ≥${esc(String(volume.min_weeks ?? 8))} wk`
          )}
          <p class="small muted">Review gate — not auto-promote.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Path median (fair)</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${pctOrDash(pathMedian)}</div>
          </div>
          ${settingRow("n episodes", esc(String(path.n ?? volume.episodes ?? "—")))}
          ${settingRow("Stress median (report-only)", pctOrDash(path.smooth_ret_cohort_median_stress_report_only))}
          <p class="small muted">Fixed-stake episode %; independent of fund NAV.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Pipeline ${functioningBadge}</h3>
          ${settingRow("Store freshness", `${observeFreshnessBadge(freshness.state)} · ${esc(freshness.detail || "")}`)}
          ${settingRow(
            "Ops check",
            pipeline.ops_check_ok === true
              ? n200GateBadge(true, { yes: "ok" })
              : pipeline.ops_check_ok === false
                ? n200GateBadge(false, { no: pipeline.ops_finding_present ? "failed" : "absent" })
                : "—"
          )}
          ${settingRow("Last store refresh", esc(fmtDate(payload.store_generated_at)))}
          <p class="small muted">${esc(pipeline.detail || "")}</p>
        </div>
      </div>
      <p class="small muted" style="margin-top:0.75rem;margin-bottom:0">
        Observe-only strand D (patient plain EY). influences_live false. Phase green ≠ alpha or capital-ready. Not assessment primary. Never writes books/knobs (F8).
      </p>
    </section>`;
}

function resolveN201PipelineHealth(data) {
  if (data.n201_pipeline_health) return data.n201_pipeline_health;
  const health = resolveQueueHealth(data);
  if (health?.n201_pipeline_health) return health.n201_pipeline_health;
  const store = data.n201_value_mom_observe;
  if (!store || typeof store !== "object") return null;
  const phase = store.phase || {};
  const volume = store.volume_gate || {};
  const path = store.path_scoreboard || {};
  return {
    observe_only: true,
    influences_live: false,
    not_alpha_signal: true,
    not_capital_ready: true,
    independent_of_fund_nav: true,
    launch_queue_waiter: true,
    registration_id: store.registration_id,
    deferred_id: store.deferred_id || "N201",
    headline: "N201 observe store loaded (client projection).",
    disclaimer:
      "Phase floor and volume gate measure factory mechanism throughput — not alpha or capital readiness (F8). Fixed-stake episode % is independent of fund NAV. Observe-only.",
    store_present: true,
    store_generated_at: store.generated_at || null,
    phase: {
      entries_per_week: phase.entries_per_week,
      floor: phase.floor,
      floor_met: !!phase.floor_met,
    },
    volume_gate: {
      met: !!volume.met,
      episodes: store.completed_entry_episodes ?? 0,
      weeks: store.calendar_weeks_spanned ?? 0,
      min_episodes: volume.min_episodes,
      min_weeks: volume.min_weeks,
    },
    path_scoreboard: path,
    freshness: { state: "unknown", detail: "Awaiting queue-health embed for freshness." },
    pipeline: {
      functioning: null,
      ops_check_ok: null,
      ops_run_at: null,
      detail: "Refresh with ops-monitor / queue health for full pipeline status.",
    },
    ops_doc: store.ops_doc || "docs/ops/n201-value-mom-observe.md",
  };
}

function renderN201PipelineHealthSection(data, { compact = false } = {}) {
  const payload = resolveN201PipelineHealth(data);
  const runbookUrl = githubOpsDocUrl("docs/ops/n201-value-mom-observe.md");
  const sectionAttrs = compact
    ? ' class="automation-section automation-section-full n201-pipeline-health-section analysis-observe-compact"'
    : ' class="automation-section automation-section-full n201-pipeline-health-section"';
  if (!payload) {
    return `
      <section${sectionAttrs}>
        <h2>N201 pipeline health</h2>
        <p class="muted small">Observe store not published yet. Refreshes with daily ops-monitor (<code>check_n201_value_mom_observe</code>).</p>
      </section>`;
  }
  const phase = payload.phase || {};
  const volume = payload.volume_gate || {};
  const freshness = payload.freshness || {};
  const pipeline = payload.pipeline || {};
  const path = payload.path_scoreboard || {};
  const entriesPw =
    phase.entries_per_week == null || !Number.isFinite(Number(phase.entries_per_week))
      ? "—"
      : String(Number(phase.entries_per_week));
  const floor =
    phase.floor == null || !Number.isFinite(Number(phase.floor))
      ? "—"
      : String(Number(phase.floor));
  const functioningBadge =
    pipeline.functioning === true
      ? `<span class="badge badge-ii-yes">functioning</span>`
      : pipeline.functioning === false
        ? `<span class="badge badge-ii-no">attention</span>`
        : `<span class="badge">unknown</span>`;
  const waiterBadge = payload.launch_queue_waiter
    ? `<span class="badge badge-hold">launch-queue waiter</span>`
    : "";
  const disclaimer = esc(
    payload.disclaimer ||
      "Phase floor = mechanism throughput, not alpha or capital readiness (F8)."
  );
  const metaLine = `<p class="small muted">Store ${esc(fmtDate(payload.store_generated_at))}
        · projection ${esc(fmtDate(payload.generated_at))}
        · ops ${esc(fmtDate(pipeline.ops_run_at))}
        · ${esc(payload.registration_id || "strand-c-short-horizon-value-mom-v0")}
      </p>`;
  const pathMedian = path.smooth_ret_cohort_median;
  if (compact) {
    return `
      <section${sectionAttrs}>
        <h2>N201 pipeline health ${observeFreshnessBadge(freshness.state)} ${functioningBadge} ${waiterBadge}</h2>
        <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
        ${metaLine}
        <p class="small muted" style="margin:0.35rem 0 0">
          Phase ${esc(entriesPw)}/${esc(floor)} ${n200GateBadge(!!phase.floor_met)}
          · volume ${n200GateBadge(!!volume.met)}
          (${esc(String(volume.episodes ?? "—"))} ep / ${esc(String(volume.weeks ?? "—"))} wk)
          · path median ${pctOrDash(pathMedian)}
        </p>
        <p class="small muted" style="margin-bottom:0">
          Compact strip — full readout on Analysis model switcher (N201) or
          <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue</button>.
          Not a promote signal (F8).
        </p>
      </section>`;
  }
  return `
    <section${sectionAttrs}>
      <h2>N201 / short-horizon value-mom ${observeFreshnessBadge(freshness.state)} ${functioningBadge} ${waiterBadge}</h2>
      <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
      ${metaLine}
      <p class="small muted">${disclaimer}
        ${runbookUrl ? ` <a href="${esc(runbookUrl)}" target="_blank" rel="noopener">N201 runbook</a>` : ""}
      </p>
      <div class="grid n200-pipeline-grid n201-pipeline-grid" style="margin-top:0.75rem">
        <div class="card n200-pipeline-card">
          <h3>Phase floor ${n200GateBadge(!!phase.floor_met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(entriesPw)}<span class="n200-floor-den">/${esc(floor)}</span></div>
          </div>
          <p class="small muted">Entries/week vs sealed floor. Throughput health only.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Volume gate ${n200GateBadge(!!volume.met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(String(volume.episodes ?? "—"))}<span class="n200-floor-den"> ep</span></div>
          </div>
          ${settingRow("Weeks", esc(String(volume.weeks ?? "—")))}
          ${settingRow(
            "Minimums",
            `≥${esc(String(volume.min_episodes ?? 48))} ep and ≥${esc(String(volume.min_weeks ?? 8))} wk`
          )}
          <p class="small muted">Review gate — not auto-promote.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Path median (fair)</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${pctOrDash(pathMedian)}</div>
          </div>
          ${settingRow("n episodes", esc(String(path.n ?? volume.episodes ?? "—")))}
          ${settingRow("Stress median (report-only)", pctOrDash(path.smooth_ret_cohort_median_stress_report_only))}
          <p class="small muted">Fixed-stake episode %; independent of fund NAV.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Pipeline ${functioningBadge}</h3>
          ${settingRow("Store freshness", `${observeFreshnessBadge(freshness.state)} · ${esc(freshness.detail || "")}`)}
          ${settingRow(
            "Ops check",
            pipeline.ops_check_ok === true
              ? n200GateBadge(true, { yes: "ok" })
              : pipeline.ops_check_ok === false
                ? n200GateBadge(false, { no: pipeline.ops_finding_present ? "failed" : "absent" })
                : "—"
          )}
          ${settingRow("Last store refresh", esc(fmtDate(payload.store_generated_at)))}
          <p class="small muted">${esc(pipeline.detail || "")}</p>
        </div>
      </div>
      <p class="small muted" style="margin-top:0.75rem;margin-bottom:0">
        Observe-only strand C (launch-queue waiter). Phase green ≠ alpha or capital-ready. Never writes books/knobs (F8).
      </p>
    </section>`;
}

function resolveN210PipelineHealth(data) {
  if (data.n210_pipeline_health) return data.n210_pipeline_health;
  const health = resolveQueueHealth(data);
  if (health?.n210_pipeline_health) return health.n210_pipeline_health;
  const store = data.n210_ai_judgment_observe;
  if (!store || typeof store !== "object") return null;
  const phase = store.phase || {};
  const volume = store.volume_gate || {};
  const path = store.path_scoreboard || {};
  const completed = store.completed_entry_episodes ?? 0;
  const openEp = store.open_entry_episodes ?? path.open_entry_episodes ?? 0;
  const pipelineStatus = store.pipeline_status || null;
  return {
    observe_only: true,
    influences_live: false,
    not_alpha_signal: true,
    not_capital_ready: true,
    not_assessment_primary: true,
    independent_of_fund_nav: true,
    launch_queue_waiter: true,
    b3_epoch: true,
    registration_id: store.registration_id,
    deferred_id: store.deferred_id || "N210",
    headline: "N210 observe store loaded (client projection).",
    disclaimer:
      "Phase floor and volume gate measure factory mechanism throughput — not alpha or capital readiness (F8). Fixed-stake episode % is independent of fund NAV. Open episodes with 0 completed is honest thin-marks state. Observe-only; not assessment primary.",
    store_present: true,
    store_generated_at: store.generated_at || null,
    pipeline_status: pipelineStatus,
    stub_gone: pipelineStatus === "episode_walker_active",
    walker_active: pipelineStatus === "episode_walker_active",
    phase: {
      entries_per_week: phase.entries_per_week,
      floor: phase.floor,
      floor_met: !!phase.floor_met,
    },
    volume_gate: {
      met: !!volume.met,
      episodes: completed,
      open_episodes: openEp,
      weeks: store.calendar_weeks_spanned ?? 0,
      min_episodes: volume.min_episodes,
      min_weeks: volume.min_weeks,
    },
    path_scoreboard: path,
    freshness: { state: "unknown", detail: "Awaiting queue-health embed for freshness." },
    pipeline: {
      functioning: null,
      ops_check_ok: null,
      ops_run_at: null,
      detail: "Refresh with ops-monitor / queue health for full pipeline status.",
    },
    ops_doc: store.ops_doc || "docs/ops/n210-ai-judgment-observe.md",
  };
}

function renderN210PipelineHealthSection(data, { compact = false } = {}) {
  const payload = resolveN210PipelineHealth(data);
  const runbookUrl = githubOpsDocUrl("docs/ops/n210-ai-judgment-observe.md");
  const sectionAttrs = compact
    ? ' class="automation-section automation-section-full n210-pipeline-health-section analysis-observe-compact"'
    : ' class="automation-section automation-section-full n210-pipeline-health-section"';
  if (!payload) {
    return `
      <section${sectionAttrs}>
        <h2>N210 pipeline health</h2>
        <p class="muted small">Observe store not published yet. Refreshes with daily ops-monitor (<code>check_n210_ai_judgment_observe</code>).</p>
      </section>`;
  }
  const phase = payload.phase || {};
  const volume = payload.volume_gate || {};
  const freshness = payload.freshness || {};
  const pipeline = payload.pipeline || {};
  const path = payload.path_scoreboard || {};
  const entriesPw =
    phase.entries_per_week == null || !Number.isFinite(Number(phase.entries_per_week))
      ? "—"
      : String(Number(phase.entries_per_week));
  const floor =
    phase.floor == null || !Number.isFinite(Number(phase.floor))
      ? "—"
      : String(Number(phase.floor));
  const functioningBadge =
    pipeline.functioning === true
      ? `<span class="badge badge-ii-yes">functioning</span>`
      : pipeline.functioning === false
        ? `<span class="badge badge-ii-no">attention</span>`
        : `<span class="badge">unknown</span>`;
  const waiterBadge = payload.launch_queue_waiter
    ? `<span class="badge badge-hold">launch-queue waiter</span>`
    : "";
  const walkerBadge = payload.walker_active
    ? `<span class="badge badge-info">walker active</span>`
    : payload.stub_gone === false
      ? `<span class="badge">stub</span>`
      : "";
  const disclaimer = esc(
    payload.disclaimer ||
      "Phase floor = mechanism throughput, not alpha or capital readiness (F8)."
  );
  const metaLine = `<p class="small muted">Store ${esc(fmtDate(payload.store_generated_at))}
        · projection ${esc(fmtDate(payload.generated_at))}
        · ops ${esc(fmtDate(pipeline.ops_run_at))}
        · ${esc(payload.registration_id || "strand-e-ai-judgment-fixed-stake-v0")}
      </p>`;
  const pathMedian = path.smooth_ret_cohort_median;
  const openEp = volume.open_episodes ?? path.open_entry_episodes ?? 0;
  const completedEp = volume.episodes ?? path.completed_entry_episodes ?? 0;
  if (compact) {
    return `
      <section${sectionAttrs}>
        <h2>N210 pipeline health ${observeFreshnessBadge(freshness.state)} ${functioningBadge} ${walkerBadge} ${waiterBadge}</h2>
        <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
        ${metaLine}
        <p class="small muted" style="margin:0.35rem 0 0">
          Phase ${esc(entriesPw)}/${esc(floor)} ${n200GateBadge(!!phase.floor_met)}
          · volume ${n200GateBadge(!!volume.met)}
          (${esc(String(completedEp))} done / ${esc(String(openEp))} open / ${esc(String(volume.weeks ?? "—"))} wk)
          · path median ${pctOrDash(pathMedian)}
        </p>
        <p class="small muted" style="margin-bottom:0">
          Compact strip — full readout on Analysis model switcher (N210) or
          <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue</button>.
          Not assessment primary; not a promote signal (F8 / B3).
        </p>
      </section>`;
  }
  return `
    <section${sectionAttrs}>
      <h2>N210 / AI-judgment fixed-stake ${observeFreshnessBadge(freshness.state)} ${functioningBadge} ${walkerBadge} ${waiterBadge}</h2>
      <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
      ${metaLine}
      <p class="small muted">${disclaimer}
        ${runbookUrl ? ` <a href="${esc(runbookUrl)}" target="_blank" rel="noopener">N210 runbook</a>` : ""}
      </p>
      <div class="grid n200-pipeline-grid n210-pipeline-grid" style="margin-top:0.75rem">
        <div class="card n200-pipeline-card">
          <h3>Phase floor ${n200GateBadge(!!phase.floor_met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(entriesPw)}<span class="n200-floor-den">/${esc(floor)}</span></div>
          </div>
          <p class="small muted">Entries/week vs sealed floor. Throughput health only.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Volume gate ${n200GateBadge(!!volume.met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(String(completedEp))}<span class="n200-floor-den"> done</span></div>
          </div>
          ${settingRow("Open episodes", esc(String(openEp)))}
          ${settingRow("Weeks", esc(String(volume.weeks ?? "—")))}
          ${settingRow(
            "Minimums",
            `≥${esc(String(volume.min_episodes ?? 48))} ep and ≥${esc(String(volume.min_weeks ?? 8))} wk`
          )}
          <p class="small muted">0 completed + open &gt; 0 is honest thin marks — review gate, not auto-promote.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Path median (fair)</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${pctOrDash(pathMedian)}</div>
          </div>
          ${settingRow("n completed", esc(String(path.n ?? completedEp ?? "—")))}
          ${settingRow("Buy-tier excess (report-only)", pctOrDash(path.unfiltered_buy_tier_excess_report_only))}
          <p class="small muted">Fixed-stake episode %; independent of fund NAV. Null OK until closes.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Pipeline ${functioningBadge}</h3>
          ${settingRow("Status", esc(payload.pipeline_status || "—"))}
          ${settingRow("Store freshness", `${observeFreshnessBadge(freshness.state)} · ${esc(freshness.detail || "")}`)}
          ${settingRow(
            "Ops check",
            pipeline.ops_check_ok === true
              ? n200GateBadge(true, { yes: "ok" })
              : pipeline.ops_check_ok === false
                ? n200GateBadge(false, { no: pipeline.ops_finding_present ? "failed" : "absent" })
                : "—"
          )}
          ${settingRow("Last store refresh", esc(fmtDate(payload.store_generated_at)))}
          <p class="small muted">${esc(pipeline.detail || "")}</p>
        </div>
      </div>
      <p class="small muted" style="margin-top:0.75rem;margin-bottom:0">
        Observe-only strand E (B3 judgment shadow; launch-queue waiter). Not assessment primary. Phase green ≠ alpha or capital-ready. Matched-30 pots untouched. Never writes books/knobs (F8).
      </p>
    </section>`;
}

/**
 * Per-model lifecycle monitor on Analysis → Observe.
 * Strand A → live Lifecycle tab pointer (+ maturity snapshot).
 * N200 / N201 / N206 / N210 → each model’s own sealed store (phase / volume / path / episodes / markers).
 * Never swaps Strand A’s board under an observe label (F5 / F8).
 */
function renderModelLifecycleMonitor(data, modelId) {
  const id = normalizeInvestmentModel(modelId);
  if (id === "strand-a") return renderStrandALifecycleMonitor(data);
  return renderObserveLifecycleMonitor(data, id);
}

function renderStrandALifecycleMonitor(data) {
  const maturity = resolveLifecycleMaturity(data);
  const markets = Array.isArray(maturity?.markets) ? maturity.markets : [];
  const live =
    markets.find((row) => row && (row.is_live || row.market_id === "ftse350")) || null;
  const metrics = live?.metrics || {};
  const early =
    live?.primary_value != null
      ? `${Number(live.primary_value).toFixed(1)}%`
      : metrics.early_share != null
        ? `${(Number(metrics.early_share) * 100).toFixed(1)}%`
        : "—";
  const held = metrics.held_count != null ? String(metrics.held_count) : "—";
  const sold = metrics.sold_count != null ? String(metrics.sold_count) : "—";
  return `
    <section class="automation-section automation-section-full model-lifecycle-monitor model-lifecycle-monitor-live" data-lifecycle-model="strand-a">
      <h2>Lifecycle monitor · Strand A
        <span class="badge badge-buy model-mode-badge">live</span>
      </h2>
      <p class="small muted" style="margin-top:0">
        Sole live capital path (F5). Position board and maturity mix live on the
        <button type="button" class="link-btn" data-tab-jump="lifecycle">Lifecycle</button> tab —
        not an observe seal. N200 / N201 / N206 / N210 each have their own sealed stores under this switcher.
      </p>
      <div class="grid n200-pipeline-grid model-lifecycle-stage-grid" style="margin-top:0.75rem">
        <div class="card n200-pipeline-card">
          <h3>Live board</h3>
          <p class="small" style="margin:0.35rem 0">
            <button type="button" class="link-btn" data-tab-jump="lifecycle">Open Positions</button>
            ·
            <button type="button" class="link-btn" data-lifecycle-jump="maturity">Maturity mix</button>
          </p>
          <p class="small muted">Holding-state columns for FTSE live books — Acknowledge / Start stay observe-gated.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>FTSE maturity snapshot</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(early)}</div>
          </div>
          ${settingRow("Held", esc(held))}
          ${settingRow("Sold (book)", esc(sold))}
          <p class="small muted">${esc(
            live?.primary_label || "Early share % — lower = more mature (observe maturity mix)"
          )}</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Capital path</h3>
          ${settingRow("Mode", '<span class="badge badge-buy">live</span>')}
          ${settingRow("Promote", "Human gate only — never auto (F8)")}
          <p class="small muted">Assessment scoreboard below is the Strand A promote readout.</p>
        </div>
      </div>
    </section>`;
}

function _observeLifecycleStore(data, modelId) {
  if (modelId === "n201") {
    return {
      store: data.n201_value_mom_observe || null,
      health: resolveN201PipelineHealth(data),
      label: "N201",
      registrationFallback: "strand-c-short-horizon-value-mom-v0",
      emptyHint:
        "N201 observe store not published yet (check_n201_value_mom_observe). Launch-queue waiter — thin data is expected until P1 capacity allows deepen.",
    };
  }
  if (modelId === "n206") {
    return {
      store: data.n206_plain_ey_observe || null,
      health: resolveN206PipelineHealth(data),
      label: "N206",
      registrationFallback: "strand-d-plain-ey-identity-v0",
      emptyHint:
        "N206 observe store not published yet (check_n206_plain_ey_observe). Existing panels only — no filing sprint.",
    };
  }
  if (modelId === "n210") {
    return {
      store: data.n210_ai_judgment_observe || null,
      health: resolveN210PipelineHealth(data),
      label: "N210",
      registrationFallback: "strand-e-ai-judgment-fixed-stake-v0",
      emptyHint:
        "N210 observe store not published yet (check_n210_ai_judgment_observe). Walker may show open episodes with 0 completed — thin marks OK (F8 / B3).",
    };
  }
  return {
    store: data.n200_tech_timing_observe || null,
    health: resolveN200PipelineHealth(data),
    label: "N200",
    registrationFallback: "strand-b-plain-value-tech-timing-v0",
    emptyHint:
      "N200 observe store not published yet (check_n200_tech_timing_observe).",
  };
}

function _formatObserveLeverCell(lever) {
  if (lever == null || lever === "") return "—";
  if (typeof lever === "string" || typeof lever === "number" || typeof lever === "boolean") {
    return String(lever);
  }
  if (typeof lever === "object") {
    const verdict = lever.verdict;
    if (verdict) return String(verdict);
    if (lever.control_offset_days != null) return `off ${lever.control_offset_days}`;
    return "—";
  }
  return "—";
}

function renderObserveLifecycleEpisodeRows(store, modelId) {
  let sample = Array.isArray(store?.episodes_sample) ? store.episodes_sample : [];
  let openOnly = false;
  if (!sample.length && modelId === "n210") {
    sample = Array.isArray(store?.open_episodes_sample) ? store.open_episodes_sample : [];
    openOnly = sample.length > 0;
  }
  if (!sample.length) {
    return `<tr><td colspan="5" class="muted small">No episodes_sample yet — waiting on sealed refresh.</td></tr>`;
  }
  return sample
    .slice(0, 12)
    .map((ep) => {
      if (!ep || typeof ep !== "object") return "";
      if (modelId === "n201" || modelId === "n206" || modelId === "n210") {
        const statusNote = openOnly
          ? ep.status || "open"
          : ep.exit_reason || ep.eligibility || ep.status || "—";
        return `<tr>
          <td><code>${esc(ep.ticker || "—")}</code></td>
          <td>${esc(ep.market_id || "—")}</td>
          <td>${esc(String(ep.hold_trading_days ?? "—"))}</td>
          <td class="${signedReturnClass(ep.return_pct)}">${
            openOnly ? esc("open") : pctOrDash(ep.return_pct)
          }</td>
          <td class="small muted">${esc(statusNote)}</td>
        </tr>`;
      }
      return `<tr>
        <td><code>${esc(ep.ticker || "—")}</code></td>
        <td>${esc(String(ep.hold_days ?? "—"))}</td>
        <td class="${signedReturnClass(ep.control_return)}">${pctOrDash(ep.control_return)}</td>
        <td>${esc(_formatObserveLeverCell(ep.entry_lever))}</td>
        <td>${esc(_formatObserveLeverCell(ep.exit_lever))}</td>
      </tr>`;
    })
    .join("");
}

function renderObserveLifecycleMarkers(store) {
  const markers = Array.isArray(store?.change_markers) ? store.change_markers : [];
  if (!markers.length) {
    return `<p class="muted small">No change_markers on store yet.</p>`;
  }
  const items = markers
    .map((m) => {
      if (!m || typeof m !== "object") return "";
      return `<li>
        <code>${esc(m.marker_id || m.id || "—")}</code>
        <span class="muted"> · ${esc(fmtDate(m.at))} · ${esc(m.lever || "")}</span>
        <div class="small muted">${esc(m.summary || m.reason || "")}</div>
      </li>`;
    })
    .join("");
  return `<ul class="list-plain model-lifecycle-markers">${items}</ul>`;
}

function renderObserveLifecycleMonitor(data, modelId, { stagesOnly = false } = {}) {
  const id = normalizeInvestmentModel(modelId);
  const meta = investmentModelMeta(id);
  const pack = _observeLifecycleStore(data, id);
  const store = pack.store;
  const health = pack.health;
  if (!store && !health) {
    if (stagesOnly) {
      return `
        <div class="sealed-life-stages model-lifecycle-monitor model-lifecycle-monitor-empty" data-lifecycle-model="${esc(
          id
        )}">
          <p class="muted small">${esc(pack.emptyHint || meta.emptyHint)}</p>
        </div>`;
    }
    return `
      <section class="automation-section automation-section-full model-lifecycle-monitor model-lifecycle-monitor-empty" data-lifecycle-model="${esc(
        id
      )}">
        <h2>Lifecycle monitor · ${esc(pack.label)}
          <span class="badge badge-info model-mode-badge">observe</span>
        </h2>
        <div class="empty-state">
          <p class="muted small">${esc(pack.emptyHint || meta.emptyHint)}</p>
        </div>
      </section>`;
  }
  const phase = (health && health.phase) || (store && store.phase) || {};
  const volume = (health && health.volume_gate) || {};
  const path =
    (health && health.path_scoreboard) || (store && store.path_scoreboard) || {};
  const episodes =
    volume.episodes ?? store?.completed_entry_episodes ?? null;
  const weeks = volume.weeks ?? store?.calendar_weeks_spanned ?? null;
  const entriesPw =
    phase.entries_per_week == null || !Number.isFinite(Number(phase.entries_per_week))
      ? "—"
      : String(Number(phase.entries_per_week));
  const floor =
    phase.floor == null || !Number.isFinite(Number(phase.floor))
      ? "—"
      : String(Number(phase.floor));
  const pathPrimary =
    id === "n201" || id === "n206" || id === "n210"
      ? path.smooth_ret_cohort_median
      : path.control_smooth_ret_cohort_median ?? path.smooth_ret_cohort_median;
  const registration =
    store?.registration_id || health?.registration_id || pack.registrationFallback;
  const waiter =
    (id === "n201" || id === "n206" || id === "n210") &&
    (health?.launch_queue_waiter || store?.launch_queue?.enqueued)
      ? `<span class="badge badge-hold">launch-queue waiter</span>`
      : "";
  const walkerBadge =
    id === "n210" && (health?.walker_active || store?.pipeline_status === "episode_walker_active")
      ? `<span class="badge badge-info">walker active</span>`
      : "";
  const openEp =
    volume.open_episodes ?? store?.open_entry_episodes ?? path.open_entry_episodes ?? 0;
  const thinSample =
    (id === "n201" || id === "n210") &&
    ((Array.isArray(store?.episodes_sample) && store.episodes_sample.length > 0) ||
      (id === "n210" && Number(openEp) > 0)) &&
    (episodes == null || Number(episodes) < (volume.min_episodes || 48));
  const thinNote = thinSample
    ? id === "n210"
      ? `<p class="small muted model-lifecycle-waiter-note">Thin marks OK — ${esc(
          String(openEp)
        )} open / ${esc(String(episodes ?? 0))} completed while walker runs; scoreboards stay alone-first; not assessment primary (F8 / B3).</p>`
      : `<p class="small muted model-lifecycle-waiter-note">Sample may look thin while N201 waits behind holdings / N200 on the launch queue — scoreboards stay alone-first (F8).</p>`
    : "";
  const episodeHead =
    id === "n201" || id === "n210"
      ? `<tr><th>Ticker</th><th>Market</th><th>Hold (td)</th><th>Return %</th><th>Exit / note</th></tr>`
      : `<tr><th>Ticker</th><th>Hold (d)</th><th>Control ret</th><th>Entry lever</th><th>Exit lever</th></tr>`;
  const completedSampleLen = Array.isArray(store?.episodes_sample)
    ? store.episodes_sample.length
    : 0;
  const openSampleLen = Array.isArray(store?.open_episodes_sample)
    ? store.open_episodes_sample.length
    : 0;
  const sampleLen =
    id === "n210" && completedSampleLen === 0 ? openSampleLen : completedSampleLen;
  const totalEp = episodes != null ? String(episodes) : "—";
  const sampleCaption =
    id === "n210" && completedSampleLen === 0 && openSampleLen > 0
      ? `showing ${sampleLen} open (0 completed yet)`
      : `showing ${sampleLen} of ${totalEp} completed`;
  const stageGrid = `
      <div class="grid n200-pipeline-grid model-lifecycle-stage-grid" style="margin-top:0.75rem">
        <div class="card n200-pipeline-card">
          <h3>Phase ${n200GateBadge(!!phase.floor_met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(entriesPw)}<span class="n200-floor-den">/${esc(
              floor
            )}</span></div>
          </div>
          <p class="small muted">Entries/week vs sealed floor — mechanism only.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Volume ${n200GateBadge(volume.met)}</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value">${esc(String(totalEp))}<span class="n200-floor-den"> ep</span></div>
          </div>
          ${
            id === "n210"
              ? settingRow("Open episodes", esc(String(openEp)))
              : ""
          }
          ${settingRow("Weeks", esc(String(weeks ?? "—")))}
          ${settingRow(
            "Gate",
            `≥${esc(String(volume.min_episodes ?? (id === "n201" || id === "n206" || id === "n210" ? 48 : 24)))} ep · ≥${esc(
              String(volume.min_weeks ?? 8)
            )} wk`
          )}
          <p class="small muted">Review gate — not promote.</p>
        </div>
        <div class="card n200-pipeline-card">
          <h3>Path (fair)</h3>
          <div class="observe-primary-row">
            <div class="observe-primary-value ${signedReturnClass(
              pathPrimary
            )}">${pctOrDash(pathPrimary)}</div>
          </div>
          ${settingRow(
            "Primary",
            esc(path.success_metric_id || store?.success_metric_id || "smooth_ret_cohort_median")
          )}
          <p class="small muted">Cohort median at fair costs — alone scoreboard.</p>
        </div>
      </div>`;
  if (stagesOnly) {
    return `
      <div class="sealed-life-stages model-lifecycle-monitor" data-lifecycle-model="${esc(id)}">
        <div class="sealed-life-stages-head">
          <span class="small muted">Phase / volume / path from sealed store <code>${esc(
            registration
          )}</code></span>
          ${walkerBadge}
          ${waiter}
        </div>
        ${thinNote}
        ${stageGrid}
      </div>`;
  }
  return `
    <section class="automation-section automation-section-full model-lifecycle-monitor" data-lifecycle-model="${esc(
      id
    )}">
      <h2>Lifecycle monitor · ${esc(pack.label)}
        <span class="badge badge-info model-mode-badge">observe</span>
        ${walkerBadge}
        ${waiter}
      </h2>
      <p class="small muted" style="margin-top:0">
        Bound to <code>${esc(registration)}</code> sealed store — not Strand A’s Lifecycle board.
        Phase / volume / path are this registration’s alone scoreboards; never auto-promote (F8).
      </p>
      ${thinNote}
      ${stageGrid}
      <div class="model-lifecycle-episodes" style="margin-top:0.85rem">
        <h3>Episodes sample
          <span class="small muted">${esc(sampleCaption)}</span>
        </h3>
        <div class="table-wrap">
          <table class="learning-tracks-table model-lifecycle-episode-table">
            <thead>${episodeHead}</thead>
            <tbody>${renderObserveLifecycleEpisodeRows(store, id)}</tbody>
          </table>
        </div>
      </div>
      <div class="model-lifecycle-markers-wrap" style="margin-top:0.85rem">
        <h3>Change markers</h3>
        ${renderObserveLifecycleMarkers(store)}
      </div>
      <p class="small muted" style="margin-top:0.75rem;margin-bottom:0">
        Observe-only. Pipeline cards below add freshness / ${
          id === "n200" ? "per-lever detail" : "ops status"
        }. Does not write books or knobs.
      </p>
    </section>`;
}

/** Freshness / lever extras for sealed lifecycle collation (same queue_health / store SSoT). */
function renderSealedLifecycleExtras(data, modelId) {
  const id = normalizeInvestmentModel(modelId);
  const health =
    id === "n210"
      ? resolveN210PipelineHealth(data)
      : id === "n206"
        ? resolveN206PipelineHealth(data)
        : id === "n201"
          ? resolveN201PipelineHealth(data)
          : resolveN200PipelineHealth(data);
  if (!health) {
    return `<p class="small muted sealed-life-extras">Pipeline health not published yet.</p>`;
  }
  const freshness = health.freshness || {};
  const pipeline = health.pipeline || {};
  const functioningBadge =
    pipeline.functioning === true
      ? `<span class="badge badge-ii-yes">functioning</span>`
      : pipeline.functioning === false
        ? `<span class="badge badge-ii-no">attention</span>`
        : `<span class="badge">unknown</span>`;
  const waiter =
    (id === "n201" || id === "n206" || id === "n210") && health.launch_queue_waiter
      ? `<span class="badge badge-hold">launch-queue waiter</span>`
      : "";
  const walker =
    id === "n210" && health.walker_active
      ? `<span class="badge badge-info">walker active</span>`
      : "";
  let leverLine = "";
  if (id === "n200") {
    const perLever = health.per_lever || {};
    leverLine = ` · entry ${n200LeverBadge(perLever.entry_verdict)} · exit ${n200LeverBadge(
      perLever.exit_verdict
    )}`;
  }
  return `
    <p class="small muted sealed-life-extras" style="margin:0.5rem 0 0">
      Pipeline ${observeFreshnessBadge(freshness.state)} ${functioningBadge}${waiter}${walker}${leverLine}
      · store ${esc(fmtDate(health.store_generated_at))}
    </p>`;
}

/**
 * Collate Observe diagnostics onto Lifecycle → Sealed models (one composition per book).
 * Reads the same observe stores / queue_health helpers as Analysis — no divergent numbers.
 * Chip board below remains the episode scan; full path table stays on Analysis → Observe.
 */
function renderSealedLifecycleCollation(data, modelId) {
  const id = normalizeInvestmentModel(modelId);
  if (id !== "n200" && id !== "n201" && id !== "n206" && id !== "n210") return "";
  const short = String(id).toUpperCase();
  return `
    <div class="sealed-life-collation" data-sealed-collation="${esc(id)}">
      ${renderInvestmentModelCompanionStrip(data, id)}
      ${renderObserveLifecycleMonitor(data, id, { stagesOnly: true })}
      ${renderSealedLifecycleExtras(data, id)}
      <p class="small muted sealed-life-collation-more" style="margin:0.45rem 0 0.85rem">
        Full path table + pipeline cards on
        <button type="button" class="link-btn" data-sealed-observe-jump="${esc(
          id
        )}">Analysis → Observe · ${esc(short)}</button>
        · compact strip on
        <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue</button>.
        Same stores — observe-only; never auto-promote (F8).
      </p>
    </div>`;
}

function _observeSealStartedAt(store) {
  const markers = Array.isArray(store?.change_markers) ? store.change_markers : [];
  for (const m of markers) {
    if (m && m.at) return m.at;
  }
  return store?.sealed_at || store?.generated_at || null;
}

function _formatRunningDuration(startedAt, asOf) {
  if (!startedAt) return "—";
  try {
    const start = new Date(startedAt);
    const end = asOf ? new Date(asOf) : new Date();
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "—";
    const days = Math.max(0, Math.floor((end.getTime() - start.getTime()) / 86400000));
    if (days < 14) return `${days}d`;
    const weeks = Math.floor(days / 7);
    return `${weeks}w (${days}d)`;
  } catch {
    return "—";
  }
}

function _meanEpisodeCloseDelta(store, modelId) {
  const sample = Array.isArray(store?.episodes_sample) ? store.episodes_sample : [];
  const values = [];
  for (const ep of sample) {
    if (!ep || typeof ep !== "object") continue;
    const raw =
      modelId === "n201" || modelId === "n206" || modelId === "n210"
        ? ep.return_pct
        : ep.control_return ?? ep.return_pct ?? ep.smooth_ret;
    if (raw == null || !Number.isFinite(Number(raw))) continue;
    values.push(Number(raw));
  }
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/**
 * Companion diagnostics (time running / volume / avg close delta) from existing
 * observe stores — graceful empty when fields missing (O3 design guidance).
 */
function renderInvestmentModelCompanionStrip(data, modelId) {
  const id = normalizeInvestmentModel(modelId);
  if (id === "strand-a") {
    const board = data.assessment_scoreboard;
    const tracks = Array.isArray(board?.tracks) ? board.tracks : [];
    const primary = tracks.find((t) => t.role === "primary") || tracks[0];
    const marks =
      primary?.statistics?.n_marks ??
      primary?.n_marks ??
      primary?.marks ??
      null;
    return `
      <div class="investment-model-companion" aria-label="Strand A companion diagnostics">
        <div class="investment-model-companion-grid">
          <div class="investment-model-companion-cell">
            <div class="small muted">Mode</div>
            <div class="investment-model-companion-value"><span class="badge badge-buy">live capital</span></div>
          </div>
          <div class="investment-model-companion-cell">
            <div class="small muted">Primary track</div>
            <div class="investment-model-companion-value"><code>${esc(
              board?.primary_track || primary?.track_id || "—"
            )}</code></div>
          </div>
          <div class="investment-model-companion-cell">
            <div class="small muted">Marks (if published)</div>
            <div class="investment-model-companion-value">${esc(
              marks == null ? "—" : String(marks)
            )}</div>
          </div>
          <div class="investment-model-companion-cell">
            <div class="small muted">TR excess vs ${esc(board?.benchmark || "FTAL.L")}</div>
            <div class="investment-model-companion-value">${pctOrDash(
              primary?.excess_total_return
            )}</div>
          </div>
        </div>
        <p class="small muted" style="margin:0.35rem 0 0">Sole live path (F5). Observe models are separate tabs — never a second capital book.</p>
      </div>`;
  }

  const store =
    id === "n210"
      ? data.n210_ai_judgment_observe
      : id === "n206"
        ? data.n206_plain_ey_observe
      : id === "n201"
        ? data.n201_value_mom_observe
        : data.n200_tech_timing_observe;
  const health =
    id === "n210"
      ? resolveN210PipelineHealth(data)
      : id === "n206"
        ? resolveN206PipelineHealth(data)
      : id === "n201"
        ? resolveN201PipelineHealth(data)
        : resolveN200PipelineHealth(data);
  if (!store && !health) {
    const meta = investmentModelMeta(id);
    return `
      <div class="investment-model-companion empty-state">
        <p class="muted small">${esc(meta.emptyHint)}</p>
      </div>`;
  }
  const volume = (health && health.volume_gate) || (store && store.volume_gate) || {};
  const episodes =
    volume.episodes ?? store?.completed_entry_episodes ?? null;
  const openEp =
    volume.open_episodes ?? store?.open_entry_episodes ?? null;
  const weeks = volume.weeks ?? store?.calendar_weeks_spanned ?? null;
  const minEp = volume.min_episodes;
  const started = _observeSealStartedAt(store);
  const running = _formatRunningDuration(started, store?.generated_at);
  const path = (health && health.path_scoreboard) || store?.path_scoreboard || {};
  const cohortMedian =
    id === "n201" || id === "n206" || id === "n210"
      ? path.smooth_ret_cohort_median
      : path.control_smooth_ret_cohort_median ?? path.smooth_ret_cohort_median;
  const sampleMean = _meanEpisodeCloseDelta(store, id);
  const volumeLabel =
    episodes == null
      ? "—"
      : minEp != null
        ? `${episodes} / ${minEp} ep`
        : `${episodes} ep`;
  const openClosedLabel =
    id === "n210"
      ? `${openEp == null ? "—" : openEp} open · ${episodes == null ? "—" : episodes} done`
      : null;
  const fourthCell =
    id === "n210"
      ? `
        <div class="investment-model-companion-cell">
          <div class="small muted">Open vs completed</div>
          <div class="investment-model-companion-value">${esc(openClosedLabel)}</div>
          <div class="small muted">${
            health?.walker_active || store?.pipeline_status === "episode_walker_active"
              ? "walker active · stub gone"
              : "pipeline status"
          }</div>
        </div>`
      : `
        <div class="investment-model-companion-cell">
          <div class="small muted">Sample avg close Δ</div>
          <div class="investment-model-companion-value ${signedReturnClass(
            sampleMean
          )}">${pctOrDash(sampleMean)}</div>
          <div class="small muted">episodes_sample mean (diagnostic)</div>
        </div>`;
  return `
    <div class="investment-model-companion" aria-label="${esc(id)} companion diagnostics">
      <div class="investment-model-companion-grid">
        <div class="investment-model-companion-cell">
          <div class="small muted">Time running</div>
          <div class="investment-model-companion-value">${esc(running)}</div>
          <div class="small muted">since seal ${esc(fmtDate(started))}</div>
        </div>
        <div class="investment-model-companion-cell">
          <div class="small muted">Volume toward gate</div>
          <div class="investment-model-companion-value">${esc(volumeLabel)} ${n200GateBadge(
            volume.met
          )}</div>
          <div class="small muted">${esc(String(weeks ?? "—"))} wk spanned</div>
        </div>
        <div class="investment-model-companion-cell">
          <div class="small muted">Cohort median (fair)</div>
          <div class="investment-model-companion-value ${signedReturnClass(
            cohortMedian
          )}">${pctOrDash(cohortMedian)}</div>
          <div class="small muted">path scoreboard primary</div>
        </div>
        ${fourthCell}
      </div>
      <p class="small muted" style="margin:0.35rem 0 0">
        Companion diagnostics for trend-vs-luck — not promotion truth (O3 alone-first / F8)${
          id === "n210" ? "; not assessment primary (B3)." : "."
        }
      </p>
    </div>`;
}

function renderObservePathScoreboardPanel(data, modelId) {
  const id = normalizeInvestmentModel(modelId);
  const store =
    id === "n210"
      ? data.n210_ai_judgment_observe
      : id === "n206"
        ? data.n206_plain_ey_observe
      : id === "n201"
        ? data.n201_value_mom_observe
        : data.n200_tech_timing_observe;
  const path = store?.path_scoreboard;
  if (!path || typeof path !== "object") {
    return `
      <section class="automation-section observe-path-scoreboard-section">
        <h3>Path scoreboard</h3>
        <p class="muted small">No path_scoreboard on observe store yet.</p>
      </section>`;
  }
  if (id === "n210") {
    return `
      <section class="automation-section observe-path-scoreboard-section">
        <h3>Path scoreboard (N210 · alone)</h3>
        <p class="small muted" style="margin-top:0">${esc(path.note || "")}</p>
        <div class="table-wrap">
          <table class="learning-tracks-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>Fair-cost cohort median</td><td class="${signedReturnClass(
                path.smooth_ret_cohort_median
              )}">${pctOrDash(path.smooth_ret_cohort_median)}</td></tr>
              <tr><td>Unfiltered buy-tier median (report-only)</td><td>${pctOrDash(
                path.unfiltered_buy_tier_smooth_ret_cohort_median_report_only
              )}</td></tr>
              <tr><td>Buy-tier excess (report-only)</td><td class="${signedReturnClass(
                path.unfiltered_buy_tier_excess_report_only
              )}">${pctOrDash(path.unfiltered_buy_tier_excess_report_only)}</td></tr>
              <tr><td>Stress 3%/side median (report-only)</td><td>${pctOrDash(
                path.smooth_ret_cohort_median_stress_report_only
              )}</td></tr>
              <tr><td>Completed / open</td><td>${esc(
                String(path.completed_entry_episodes ?? path.n ?? "—")
              )} / ${esc(String(path.open_entry_episodes ?? "—"))}</td></tr>
            </tbody>
          </table>
        </div>
      </section>`;
  }
  if (id === "n206") {
    return `
      <section class="automation-section observe-path-scoreboard-section">
        <h3>Path scoreboard (N206 · alone)</h3>
        <p class="small muted" style="margin-top:0">${esc(path.note || "")}</p>
        <div class="table-wrap">
          <table class="learning-tracks-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>Fair-cost cohort median</td><td class="${signedReturnClass(
                path.smooth_ret_cohort_median
              )}">${pctOrDash(path.smooth_ret_cohort_median)}</td></tr>
              <tr><td>Cash excess (report-only)</td><td class="${signedReturnClass(
                path.cash_excess_report_only
              )}">${pctOrDash(path.cash_excess_report_only)}</td></tr>
              <tr><td>Stress 3%/side median (report-only)</td><td>${pctOrDash(
                path.smooth_ret_cohort_median_stress_report_only
              )}</td></tr>
              <tr><td>n</td><td>${esc(String(path.n ?? "—"))}</td></tr>
            </tbody>
          </table>
        </div>
      </section>`;
  }
  if (id === "n201") {
    return `
      <section class="automation-section observe-path-scoreboard-section">
        <h3>Path scoreboard (N201 · alone)</h3>
        <p class="small muted" style="margin-top:0">${esc(path.note || "")}</p>
        <div class="table-wrap">
          <table class="learning-tracks-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>Fair-cost cohort median</td><td class="${signedReturnClass(
                path.smooth_ret_cohort_median
              )}">${pctOrDash(path.smooth_ret_cohort_median)}</td></tr>
              <tr><td>Patient-hold median (report-only)</td><td>${pctOrDash(
                path.patient_hold_smooth_ret_cohort_median_report_only
              )}</td></tr>
              <tr><td>Patient-hold excess (report-only)</td><td class="${signedReturnClass(
                path.patient_hold_excess_report_only
              )}">${pctOrDash(path.patient_hold_excess_report_only)}</td></tr>
              <tr><td>Stress 3%/side median (report-only)</td><td>${pctOrDash(
                path.smooth_ret_cohort_median_stress_report_only
              )}</td></tr>
              <tr><td>n</td><td>${esc(String(path.n ?? "—"))}</td></tr>
            </tbody>
          </table>
        </div>
      </section>`;
  }
  return `
    <section class="automation-section observe-path-scoreboard-section">
      <h3>Path scoreboard (N200 · alone)</h3>
      <p class="small muted" style="margin-top:0">${esc(path.note || "")}</p>
      <div class="table-wrap">
        <table class="learning-tracks-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>Control cell</td><td><code>${esc(path.control_cell || "—")}</code></td></tr>
            <tr><td>Fair-cost cohort median</td><td class="${signedReturnClass(
              path.control_smooth_ret_cohort_median
            )}">${pctOrDash(path.control_smooth_ret_cohort_median)}</td></tr>
            <tr><td>Stress median (report-only)</td><td>${pctOrDash(
              path.control_smooth_ret_cohort_median_stress_report_only
            )}</td></tr>
            <tr><td>Diagnostic best cell</td><td><code>${esc(
              path.diagnostic_best_cell || "—"
            )}</code> · ${pctOrDash(path.diagnostic_best_median)}</td></tr>
          </tbody>
        </table>
      </div>
    </section>`;
}

function observeFreshnessBadge(state) {
  const key = String(state || "unknown").toLowerCase();
  const labels = {
    fresh: "fresh",
    lagging: "lagging ops",
    stale: "stale",
    missing: "missing",
    degraded: "degraded",
    unknown: "unknown",
  };
  const cls = {
    fresh: "observe-fresh-ok",
    lagging: "observe-fresh-warn",
    stale: "observe-fresh-stale",
    missing: "observe-fresh-stale",
    degraded: "observe-fresh-stale",
    unknown: "observe-fresh-unknown",
  };
  return `<span class="observe-fresh-badge ${cls[key] || "observe-fresh-unknown"}">${esc(labels[key] || key)}</span>`;
}

function observeTrajectoryBadge(traj) {
  const direction = String(traj?.direction || "unknown").toLowerCase();
  const delta = traj?.delta;
  const deltaBit =
    delta == null ? "" : ` ${_signedDelta(delta)}`;
  const labels = {
    improving: `Better${deltaBit}`,
    worsening: `Worse${deltaBit}`,
    flat: `Flat${deltaBit || " · 0"}`,
    unknown: "No prior cycle",
  };
  const cls = {
    improving: "observe-traj-better",
    worsening: "observe-traj-worse",
    flat: "observe-traj-flat",
    unknown: "observe-traj-unknown",
  };
  return `<span class="observe-traj-badge ${cls[direction] || "observe-traj-unknown"}" title="${esc(traj?.label || "")}">${esc(labels[direction] || direction)}</span>`;
}

function renderObserveHistorySparkline(history, instrumentId) {
  const points = Array.isArray(history) ? history : [];
  const values = points
    .map((row) => {
      const cell = row?.[instrumentId];
      const v = cell?.primary_value;
      return v == null ? null : Number(v);
    })
    .filter((v) => v != null && Number.isFinite(v));
  if (values.length < 2) {
    return `<p class="small muted">Trajectory needs a second cycle (builds on each ops / queue refresh).</p>`;
  }
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = Math.max(max - min, 1);
  const w = Math.max(values.length * 14, 80);
  const h = 36;
  const coords = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * (w - 4) + 2;
      const y = h - 4 - ((v - min) / span) * (h - 8);
      return `${x},${y}`;
    })
    .join(" ");
  return `
    <svg class="observe-sparkline" viewBox="0 0 ${w} ${h}" role="img" aria-label="Trajectory sparkline">
      <polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${coords}"></polyline>
    </svg>`;
}

function renderObserveInstrumentCard(inst, history) {
  if (!inst) return "";
  const metrics = inst.metrics || {};
  const freshness = inst.freshness || {};
  const traj = inst.trajectory || {};
  const warnBadge = inst.warn_active
    ? `<span class="badge badge-ii-no">warn</span>`
    : `<span class="badge badge-ii-ok">quiet</span>`;
  let metricRows = "";
  if (inst.id === "buy_tier_flip_lag") {
    const stages = metrics.blocking_stage_counts || {};
    const stageBits = Object.keys(stages)
      .sort()
      .map((key) => `${key}=${stages[key]}`)
      .join(" · ");
    const sample = Array.isArray(metrics.warn_sample) ? metrics.warn_sample : [];
    const sampleHtml = sample.length
      ? `<ul class="list-plain small observe-flip-sample">${sample
          .map((row) => {
            const home = row.memo_home_market;
            const local = row.market_id;
            const sibling =
              row.has_memo && home && local && home !== local
                ? ` · sibling memo @ ${home}`
                : row.has_memo
                  ? ` · memo @ ${home || local || "home"}`
                  : " · no memo";
            return `<li><code>${esc(row.ticker || "—")}</code> ${esc(
              row.market_id || ""
            )} · ${esc(row.blocking_stage || "—")} (${esc(
              String(row.hours_since_flip ?? "—")
            )}h)${esc(sibling)}</li>`;
          })
          .join("")}</ul>`
      : "";
    metricRows = `
      ${settingRow("Warn cohort", esc(String(metrics.warn_not_usable ?? "—")))}
      ${settingRow("Open / cohort", esc(`${metrics.open_not_usable ?? "—"} / ${metrics.cohort_count ?? "—"}`))}
      ${settingRow("Usable in window", esc(String(metrics.usable_in_window ?? "—")))}
      ${settingRow(
        "Blocking stages",
        esc(stageBits || "—")
      )}
      ${settingRow(
        "Sibling vs true no-memo",
        `<span title="Factory has_memo joins research_home_market (exact Yahoo ticker). Empty local home is not unresearched when a sibling holds the essay. Dual-list suffixes stay distinct.">${esc(
          String(metrics.sibling_home_open_count ?? "—")
        )} sibling-home open · ${esc(String(metrics.true_no_memo_open_count ?? "—"))} true no-memo</span>`
      )}
      ${sampleHtml}`;
  } else if (inst.id === "decision_input_inventory") {
    const gaps = metrics.gap_counts || {};
    const gapBits = ["key_filing_bodies", "fcf_basis_bound", "overlay_bound", "memo_recent"]
      .map((key) => (gaps[key] != null ? `${key.replace(/_/g, " ")} ${gaps[key]}` : ""))
      .filter(Boolean)
      .join(" · ");
    metricRows = `
      ${settingRow("Dominant gap", esc(`${metrics.dominant_gap_field || "—"} · ${metrics.dominant_gap_count ?? "—"}`))}
      ${settingRow("Fully ready / inventory", esc(`${metrics.fully_ready_count ?? "—"} / ${metrics.inventory_count ?? "—"}`))}
      ${settingRow(
        "P1 slim flags",
        `<span title="Live-path bind fields weekday paper-auto can see: key filing bodies, FCF overlay, overlay bind, memo recency.">${esc(
          gapBits || "—"
        )}</span>`
      )}
      ${settingRow("Verdict", esc(String(metrics.verdict || "—")))}`;
  } else if (inst.id === "cue_consumer_mft") {
    const levers = Array.isArray(metrics.mom_levers) ? metrics.mom_levers : [];
    const leverBits = levers
      .map((row) => {
        const score =
          row.mom_score == null || row.mom_score === ""
            ? "—"
            : String(row.mom_score);
        return `${row.id || "?"}:${score}`;
      })
      .join(" · ");
    const med = metrics.path_median_fair_cost_pct;
    const medBit =
      typeof med === "number" && Number.isFinite(med)
        ? `${(med * 100).toFixed(1)}%`
        : "—";
    metricRows = `
      ${settingRow("Pipeline", esc(String(metrics.pipeline_status || "—")))}
      ${settingRow(
        "Open / closed",
        esc(`${metrics.open_lab_episodes ?? "—"} / ${metrics.closed_lab_episodes ?? "—"}`)
      )}
      ${settingRow(
        "Walker",
        esc(
          `${metrics.walker_status || "—"} · cues_accepted=${metrics.cues_accepted ?? "—"}`
        )
      )}
      ${settingRow("Path median (fair-cost)", esc(medBit))}
      ${settingRow(
        "Q8B cohort",
        esc(
          `proposed=${metrics.q8b_proposed_n ?? "—"} · frozen=${metrics.q8b_frozen_n ?? "—"} · eligible=${metrics.evolutionary_shadows_eligible ?? "—"}`
        )
      )}
      ${settingRow(
        "MoM levers",
        `<span title="Month-on-month fair-cost levers (diagnostic until volume).">${esc(
          leverBits || "—"
        )}</span>`
      )}
      ${settingRow(
        "Judgment fill",
        esc(String(metrics.judgment_fill_status || "—"))
      )}
      <p class="small muted">Observe-only super book · influences_live=false · declared incomparable · never Package L</p>`;
  } else if (inst.id === "parallel_timing_lenses") {
    const conc =
      metrics.concurrence_mean == null || metrics.concurrence_mean === ""
        ? "—"
        : String(metrics.concurrence_mean);
    metricRows = `
      ${settingRow(
        "Candidates",
        esc(
          `buy ${metrics.buy_candidates ?? "—"} · sell ${metrics.sell_candidates ?? "—"} · n=${metrics.candidate_count ?? "—"}`
        )
      )}
      ${settingRow(
        "Lens statuses",
        esc(
          `looking ${metrics.lenses_looking ?? "—"} · entered ${metrics.lenses_entered ?? "—"} · abandoned ${metrics.lenses_abandoned ?? "—"}`
        )
      )}
      ${settingRow("Concurrence mean", esc(conc))}
      ${settingRow("Buy watches armed", esc(String(metrics.buy_watch_armed ?? "—")))}
      <p class="small muted">L652 observe · fixed-stake v0 · concurrence companion only · N241 not_now · never Package L</p>`;
  } else if (inst.id === "lab_learning_progress") {
    const levers = Array.isArray(metrics.mom_levers) ? metrics.mom_levers : [];
    const leverBits = levers
      .map((row) => {
        const score =
          row.mom_score == null || row.mom_score === ""
            ? "—"
            : String(row.mom_score);
        return `${row.id || "?"}:${score}`;
      })
      .join(" · ");
    const med = metrics.lab_median_fair_cost_pct;
    const medBit =
      typeof med === "number" && Number.isFinite(med)
        ? `${(med * 100).toFixed(1)}%`
        : "—";
    const enteredBy = metrics.entered_by_lens || {};
    const enteredBits = Object.keys(enteredBy)
      .sort()
      .map((key) => `${key}=${enteredBy[key]}`)
      .join(" · ");
    const conc =
      metrics.concurrence_mean == null || metrics.concurrence_mean === ""
        ? "—"
        : String(metrics.concurrence_mean);
    const ddDepth =
      metrics.drawdown_depth_median == null || metrics.drawdown_depth_n === 0
        ? "—"
        : `${metrics.drawdown_depth_median} (n=${metrics.drawdown_depth_n})`;
    const ddDur =
      metrics.drawdown_duration_days_median == null ||
      metrics.drawdown_duration_n === 0
        ? "—"
        : `${metrics.drawdown_duration_days_median}d (n=${metrics.drawdown_duration_n})`;
    const bands = Array.isArray(metrics.concurrence_fair_cost_bands)
      ? metrics.concurrence_fair_cost_bands
      : [];
    const bandBits = bands
      .map((row) => {
        const fc = row.median_fair_cost_episode_pct;
        const fcBit =
          typeof fc === "number" && Number.isFinite(fc)
            ? `${(fc * 100).toFixed(1)}%`
            : "—";
        return `c=${row.concurrence}:${fcBit}(n=${row.n})`;
      })
      .join(" · ");
    const had = metrics.had_but_ignored_theme_counts || {};
    const miss = metrics.missing_that_might_help_theme_counts || {};
    const hadBits = Object.keys(had)
      .map((key) => `${key}=${had[key]}`)
      .join(" · ");
    const missBits = Object.keys(miss)
      .map((key) => `${key}=${miss[key]}`)
      .join(" · ");
    const gapNote = metrics.outcome_gap_note
      ? esc(String(metrics.outcome_gap_note))
      : null;
    metricRows = `
      ${settingRow(
        "Lab (MFT)",
        esc(
          `open/closed ${metrics.lab_open ?? "—"} / ${metrics.lab_closed ?? "—"} · median fair-cost ${medBit} · shadows ${metrics.evolutionary_shadows_eligible ?? "—"}`
        )
      )}
      ${settingRow(
        "MoM levers",
        `<span title="Month-on-month fair-cost levers (diagnostic until volume).">${esc(
          leverBits || "—"
        )}</span>`
      )}
      ${settingRow(
        "Lenses (L652)",
        esc(
          `looking ${metrics.lenses_looking ?? "—"} · entered ${metrics.lenses_entered ?? "—"} · abandoned ${metrics.lenses_abandoned ?? "—"} · concurrence ${conc}`
        )
      )}
      ${settingRow(
        "Entered by lens",
        esc(enteredBits || "—")
      )}
      ${settingRow(
        "Drawdown (depth / duration)",
        esc(`${ddDepth} / ${ddDur}`)
      )}
      ${settingRow(
        "Concurrence × outcome",
        `<span title="${esc(
          metrics.concurrence_outcome_note || ""
        )}">${esc(
          bandBits || `concurrence ${conc} only`
        )}</span><div class="small muted">${esc(
          metrics.concurrence_outcome_note || ""
        )}</div>`
      )}
      ${settingRow(
        "Had but ignored",
        gapNote && !hadBits
          ? gapNote
          : esc(hadBits || "—")
      )}
      ${settingRow(
        "Missing that might help",
        gapNote && !missBits
          ? gapNote
          : esc(missBits || "—")
      )}
      <p class="small muted">Weekly learning strip · Package M · fair-cost primary · influences_live=false · N241 not_now · never Package L</p>`;
  } else {
    metricRows = `
      ${settingRow("Dominant gap", esc(`${metrics.dominant_gap_field || "—"} · ${metrics.dominant_gap_count ?? "—"}`))}
      ${settingRow("Fully ready / inventory", esc(`${metrics.fully_ready_count ?? "—"} / ${metrics.inventory_count ?? "—"}`))}
      ${settingRow("Verdict", esc(String(metrics.verdict || "—")))}`;
  }
  const findingBit = inst.finding_summary
    ? `<p class="small muted observe-finding-summary">${esc(String(inst.finding_summary).slice(0, 280))}${String(inst.finding_summary).length > 280 ? "…" : ""}</p>`
    : "";
  return `
    <div class="card observe-instrument-card">
      <h3>${esc(inst.title || inst.id)} ${warnBadge} ${observeFreshnessBadge(freshness.state)}</h3>
      <p class="small muted" style="margin-top:0.2rem">${esc(inst.primary_label || "")}</p>
      <div class="observe-primary-row">
        <div class="observe-primary-value">${esc(String(inst.primary_value ?? "—"))}</div>
        <div class="observe-primary-traj">
          ${observeTrajectoryBadge(traj)}
          <div class="small muted">${esc(traj.label || "")}</div>
        </div>
      </div>
      ${metricRows}
      ${settingRow("Data freshness", `${observeFreshnessBadge(freshness.state)} · ${esc(freshness.detail || "")}`)}
      ${renderObserveHistorySparkline(history, inst.id)}
      ${findingBit}
    </div>`;
}

function renderObserveUtilizationSection(data, { compact = false } = {}) {
  const payload = resolveObserveUtilization(data);
  const runbookUrl = githubOpsDocUrl("docs/ops/ops-monitor.md");
  const sectionAttrs = compact
    ? ' class="automation-section automation-section-full observe-utilization-section analysis-observe-compact"'
    : ' class="automation-section automation-section-full observe-utilization-section"';
  if (!payload) {
    return `
      <section${sectionAttrs}>
        <h2>Observe utilization</h2>
        <p class="muted small">Flip-lag / decision-input dashboard not published yet. Refreshes with ops monitor / queue health.</p>
      </section>`;
  }
  const instruments = Array.isArray(payload.instruments) ? payload.instruments : [];
  const history = Array.isArray(payload.history) ? payload.history : [];
  const traj = payload.trajectory_summary || {};
  const staleBanner =
    payload.surface_freshness === "stale" || payload.surface_freshness === "degraded"
      ? `<div class="observe-stale-banner" role="status">Surface ${esc(payload.surface_freshness)} — treat absolute counts as outdated; prefer trajectory only when history points look continuous.</div>`
      : payload.surface_freshness === "lagging"
        ? `<div class="observe-lag-banner" role="status">Instrument JSON lags ops_status (commit-path anomaly — raw stores should land with ops-monitor). Prefer trajectory only if history looks continuous.</div>`
        : "";
  const metaLine = `<p class="small muted">Updated ${esc(fmtDate(payload.generated_at))}
        · ops ${esc(fmtDate(payload.ops_run_at))}
        · history ${esc(String(traj.history_points ?? history.length))} pts
        · traj ↑${esc(String(traj.improving ?? 0))} / ↓${esc(String(traj.worsening ?? 0))} / →${esc(String(traj.flat ?? 0))}
      </p>`;
  // Analysis tab: compact strip only — full instrument cards stay on Automation (no duplicate wall).
  if (compact) {
    return `
      <section${sectionAttrs}>
        <h2>Observe utilization ${observeFreshnessBadge(payload.surface_freshness)}</h2>
        <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
        ${metaLine}
        ${staleBanner}
        <p class="small muted" style="margin-bottom:0">
          Compact strip — full instrument cards on
          <button type="button" class="link-btn" data-tab-jump="automation">Automation → Queue &amp; hunter</button>.
          Observe-only — no auto rememo / eng spray.
        </p>
      </section>`;
  }
  const cards = instruments.map((inst) => renderObserveInstrumentCard(inst, history)).join("");
  return `
    <section${sectionAttrs}>
      <h2>Observe utilization ${observeFreshnessBadge(payload.surface_freshness)}</h2>
      <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
      ${metaLine}
      ${staleBanner}
      <p class="small muted">Observe-only instruments (flip-lag + decision-input + cue_consumer_mft L640 + parallel timing lenses L652 + lab learning progress strip). Flip-lag factory <code>has_memo</code> joins sibling <code>memo_home_market</code> — empty local home is not unresearched. Trajectory = delta vs last dashboard cycle (lower warn/gap is better on P1 cards; MFT / L652 / lab-learning cards are activity / learning-volume). ${runbookUrl ? `<a href="${esc(runbookUrl)}" target="_blank" rel="noopener">Ops runbook</a>` : ""}</p>
      <div class="grid observe-instrument-grid" style="margin-top:0.75rem">
        ${cards || '<p class="muted">No instruments in snapshot.</p>'}
      </div>
    </section>`;
}

function renderLifecycleMaturityHistorySparkline(history, marketId) {
  const points = Array.isArray(history) ? history : [];
  const values = points
    .map((row) => {
      const cell = row?.[marketId];
      const v = cell?.primary_value;
      return v == null ? null : Number(v);
    })
    .filter((v) => v != null && Number.isFinite(v));
  if (values.length < 2) {
    return `<p class="small muted">Trajectory needs a second cycle (ops / queue / board refresh).</p>`;
  }
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = Math.max(max - min, 1);
  const w = Math.max(values.length * 14, 80);
  const h = 36;
  const coords = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * (w - 4) + 2;
      const y = h - 4 - ((v - min) / span) * (h - 8);
      return `${x},${y}`;
    })
    .join(" ");
  return `
    <svg class="observe-sparkline" viewBox="0 0 ${w} ${h}" role="img" aria-label="Early-share trajectory">
      <polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${coords}"></polyline>
    </svg>`;
}

function _pctLabel(v, digits = 0) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return `${(Number(v) * 100).toFixed(digits)}%`;
}

function renderLifecycleMaturityMarketCard(row, history) {
  if (!row) return "";
  const metrics = row.metrics || {};
  const freshness = row.freshness || {};
  const traj = row.trajectory || {};
  const shares = metrics.shares || {};
  const uw = metrics.uw_rate_by_column || {};
  const med = metrics.median_days_by_column || {};
  const focusBit = row.is_focus
    ? marketRoleBadge("focus")
    : row.is_live
      ? marketRoleBadge("live")
      : "";
  const truncBit = metrics.shown_truncated
    ? `<p class="small muted">UW / median age use shown cards (board cap); shares use full column counts.</p>`
    : "";
  return `
    <div class="card lifecycle-maturity-card">
      <h3>${esc(row.title || row.market_id)} ${focusBit} ${observeFreshnessBadge(freshness.state)}</h3>
      <p class="small muted" style="margin-top:0.2rem">${esc(row.track_label || row.track_id || "")} · ${esc(row.primary_label || "")}</p>
      <div class="observe-primary-row">
        <div class="observe-primary-value">${esc(row.primary_value != null ? `${Number(row.primary_value).toFixed(0)}%` : "—")}</div>
        <div class="observe-primary-traj">
          ${observeTrajectoryBadge(traj)}
          <div class="small muted">${esc(traj.label || "")}</div>
        </div>
      </div>
      ${settingRow("Held mix", esc(`JB ${_pctLabel(shares.just_bought)} · G ${_pctLabel(shares.growth)} · NS ${_pctLabel(shares.near_sell)} · n=${metrics.held_count ?? "—"}`))}
      ${settingRow("Median days", esc(`held ${metrics.median_days_held ?? "—"} · JB ${med.just_bought ?? "—"} · G ${med.growth ?? "—"} · NS ${med.near_sell ?? "—"}`))}
      ${settingRow("UW by stage", esc(`JB ${_pctLabel(uw.just_bought)} · G ${_pctLabel(uw.growth)} · NS ${_pctLabel(uw.near_sell)} · held ${_pctLabel(metrics.uw_rate_held)}`))}
      ${settingRow("Data freshness", `${observeFreshnessBadge(freshness.state)} · ${esc(freshness.detail || "")}`)}
      ${renderLifecycleMaturityHistorySparkline(history, row.id || row.market_id)}
      ${truncBit}
    </div>`;
}

function renderLifecycleMaturitySection(data, { marketId = null, compact = false } = {}) {
  const payload = resolveLifecycleMaturity(data);
  const runbookUrl = githubOpsDocUrl("docs/ops/ops-monitor.md");
  if (!payload) {
    return `
      <section class="automation-section automation-section-full lifecycle-maturity-section">
        <h2>Lifecycle maturity mix</h2>
        <p class="muted small">Trajectory twin not published yet. Refreshes with ops monitor / queue health / board refresh. Observe-only — separate from beat_market, exit_shadow, and observe utilization.</p>
      </section>`;
  }
  let markets = Array.isArray(payload.markets) ? payload.markets : [];
  if (marketId) {
    const focused = markets.filter((row) => row.market_id === marketId);
    if (focused.length) markets = focused;
  }
  const history = Array.isArray(payload.history) ? payload.history : [];
  const traj = payload.trajectory_summary || {};
  const staleBanner =
    payload.surface_freshness === "stale" || payload.surface_freshness === "degraded" || payload.surface_freshness === "missing"
      ? `<div class="observe-stale-banner" role="status">Surface ${esc(payload.surface_freshness)} — treat absolute mix counts as outdated; prefer trajectory only when history looks continuous.</div>`
      : payload.surface_freshness === "lagging"
        ? `<div class="observe-lag-banner" role="status">Maturity store / board lags ops_status (commit-path anomaly). Prefer trajectory only if history looks continuous.</div>`
        : "";
  const cards = markets.map((row) => renderLifecycleMaturityMarketCard(row, history)).join("");
  const note = compact
    ? `<p class="small muted">Per-market early-share trajectory (lower = more mature). Prefer Better/Worse over raw mix %. Not beat_market / exit P&amp;L.</p>`
    : `<p class="small muted">Observe-only L463 twin — held-column shares, median age, UW-by-stage. Prefer trajectory (Better/Worse + sparkline) over raw mix counts. Separated from cumulative beat_market, exit_shadow, L462 WoW, N153 FX, observe utilization, and decision-review. ${runbookUrl ? `<a href="${esc(runbookUrl)}" target="_blank" rel="noopener">Ops runbook</a>` : ""}</p>`;
  return `
    <section class="automation-section automation-section-full lifecycle-maturity-section">
      <h2>Lifecycle maturity mix ${observeFreshnessBadge(payload.surface_freshness)}</h2>
      <p class="small" style="margin-top:0">${esc(payload.headline || "—")}</p>
      <p class="small muted">Updated ${esc(fmtDate(payload.generated_at))}
        · board ${esc(fmtDate(payload.board_generated_at))}
        · history ${esc(String(traj.history_points ?? history.length))} pts
        · traj ↑${esc(String(traj.improving ?? 0))} / ↓${esc(String(traj.worsening ?? 0))} / →${esc(String(traj.flat ?? 0))}
      </p>
      ${staleBanner}
      ${note}
      <div class="grid observe-instrument-grid lifecycle-maturity-grid" style="margin-top:0.75rem">
        ${cards || '<p class="muted">No admitted / live markets in maturity snapshot.</p>'}
      </div>
    </section>`;
}

function queueLaneBadge(state) {
  const key = String(state || "unknown").toLowerCase();
  const labels = {
    idle: "idle",
    running: "running",
    active: "active",
    blocked: "blocked",
    unknown: "unknown",
  };
  const cls = {
    idle: "queue-lane-idle",
    running: "queue-lane-active",
    active: "queue-lane-active",
    blocked: "queue-lane-blocked",
    unknown: "queue-lane-unknown",
  };
  return `<span class="queue-lane-badge ${cls[key] || "queue-lane-unknown"}">${esc(labels[key] || key)}</span>`;
}

function resolveQueueHealth(data) {
  if (data.queue_health) return data.queue_health;
  const auto = data.automation || {};
  return auto.queue_health || null;
}

function completionDayLabel(day) {
  if (!day || typeof day !== "object") return "—";
  const total = Number(day.merged_total || 0);
  const auto = Number(day.merged_auto || 0);
  const manual = Number(day.merged_manual || 0);
  const fixes = Number(day.fix_interventions || 0);
  const fixBits = [];
  if (Number(day.fix_ci_check || 0)) fixBits.push(`${day.fix_ci_check} CI`);
  if (Number(day.fix_merge_conflict || 0)) fixBits.push(`${day.fix_merge_conflict} merge`);
  if (Number(day.fix_ci_and_merge || 0)) fixBits.push(`${day.fix_ci_and_merge} both`);
  const fixDetail = fixBits.length ? ` (${fixBits.join(", ")})` : "";
  return `${total} merged · ${auto} auto / ${manual} manual · ${fixes} fix intervention${fixes === 1 ? "" : "s"}${fixDetail}`;
}

function renderCompletionHistoryChart(monitor) {
  const history = Array.isArray(monitor?.history) ? monitor.history : [];
  if (!history.length) {
    return `<p class="small muted">No completion history yet.</p>`;
  }
  const maxMerged = Math.max(1, ...history.map((d) => Number(d.merged_total || 0)));
  const maxFix = Math.max(1, ...history.map((d) => Number(d.fix_interventions || 0)));
  const chartH = 120;
  const labelH = 18;
  const gap = 4;
  const barW = 18;
  const groupW = barW + 10;
  const width = Math.max(history.length * groupW + 8, 200);
  const bars = history
    .map((day, idx) => {
      const x = 6 + idx * groupW;
      const auto = Number(day.merged_auto || 0);
      const manual = Number(day.merged_manual || 0);
      const fixes = Number(day.fix_interventions || 0);
      const autoH = (auto / maxMerged) * chartH;
      const manualH = (manual / maxMerged) * chartH;
      const fixH = (fixes / maxFix) * chartH;
      const manualY = chartH - manualH;
      const autoY = manualY - autoH;
      const dateLabel = String(day.date || "").slice(5);
      const title = `${day.date}: ${auto} auto, ${manual} manual, ${fixes} interventions`;
      return `
        <g class="completion-bar-group" transform="translate(${x},0)">
          <title>${esc(title)}</title>
          <rect class="completion-bar-manual" x="0" y="${manualY}" width="${barW}" height="${Math.max(manualH, 0)}" rx="1"></rect>
          <rect class="completion-bar-auto" x="0" y="${autoY}" width="${barW}" height="${Math.max(autoH, 0)}" rx="1"></rect>
          <rect class="completion-bar-fix" x="${barW + 1}" y="${chartH - fixH}" width="3" height="${Math.max(fixH, fixes ? 2 : 0)}" rx="1"></rect>
          <text class="completion-bar-label" x="${barW / 2}" y="${chartH + labelH - 4}" text-anchor="middle">${esc(dateLabel)}</text>
        </g>`;
    })
    .join("");
  return `
    <div class="completion-chart-wrap">
      <svg class="completion-history-svg" viewBox="0 0 ${width} ${chartH + labelH + gap}" role="img" aria-label="Task completion history">
        ${bars}
      </svg>
      <div class="completion-chart-legend small muted">
        <span><i class="completion-swatch auto"></i> Auto merge</span>
        <span><i class="completion-swatch manual"></i> Manual merge</span>
        <span><i class="completion-swatch fix"></i> Fix interventions</span>
      </div>
    </div>`;
}

function renderTaskCompletionMonitor(health) {
  const monitor = health?.completion_monitor;
  if (!monitor || typeof monitor !== "object") return "";
  const today = monitor.today || {};
  const yesterday = monitor.yesterday || {};
  const days = Number(monitor.history_days || (monitor.history || []).length || 14);
  return `
    <div class="card completion-monitor-card" style="margin-top:0.75rem">
      <h3>Task / PR completion</h3>
      <p class="small muted" style="margin-top:0.25rem">UTC day buckets from engineering merges and PR-fix occasions (CI / merge conflict interventions).</p>
      <div class="grid completion-readout-grid" style="margin-top:0.75rem">
        <div class="completion-readout">
          <div class="completion-readout-label">Today (${esc(String(today.date || "—"))})</div>
          <div class="completion-readout-value">${esc(String(today.merged_total ?? 0))}</div>
          <p class="small muted">${esc(completionDayLabel(today))}</p>
        </div>
        <div class="completion-readout">
          <div class="completion-readout-label">Yesterday (${esc(String(yesterday.date || "—"))})</div>
          <div class="completion-readout-value">${esc(String(yesterday.merged_total ?? 0))}</div>
          <p class="small muted">${esc(completionDayLabel(yesterday))}</p>
        </div>
      </div>
      <h4 style="margin:1rem 0 0.35rem">Last ${esc(String(days))} days</h4>
      ${renderCompletionHistoryChart(monitor)}
    </div>`;
}

function renderQueueHealthMonitor(data) {
  const health = resolveQueueHealth(data);
  const runbookUrl = githubOpsDocUrl("docs/ops/dashboard-bridge.md");
  if (!health) {
    return `
      <section class="automation-section automation-section-full queue-health-section">
        <h2>Queue &amp; hunter monitor</h2>
        <p class="muted small">Queue health snapshot not published yet. Runs with ops monitor / engineering queue refresh.</p>
      </section>`;
  }

  const merge = health.merge_lane || {};
  const agent = health.agent_lane || {};
  const clearing = health.queue_clearing || {};
  const ops = health.ops_monitor || {};
  const monitor = health.completion_monitor || {};
  const todayCount = monitor.today
    ? Number(monitor.today.merged_total || 0)
    : Array.isArray(health.merges_today)
      ? health.merges_today.length
      : 0;
  const yesterdayCount = monitor.yesterday ? Number(monitor.yesterday.merged_total || 0) : 0;
  const todayFixes = monitor.today ? Number(monitor.today.fix_interventions || 0) : 0;

  return `
    <section class="automation-section automation-section-full queue-health-section">
      <h2>Queue &amp; hunter monitor ${overallStatusBadge(health.overall)}</h2>
      <p class="small" style="margin-top:0">${esc(health.headline || "—")}</p>
      <p class="small muted">Updated ${esc(fmtDate(health.generated_at))}
        ${runbookUrl ? ` · <a href="${esc(runbookUrl)}" target="_blank" rel="noopener">Bridge runbook</a>` : ""}
      </p>
      <div class="grid queue-health-grid" style="margin-top:0.75rem">
        <div class="card queue-health-lane">
          <h3>Merge lane ${queueLaneBadge(merge.state)}</h3>
          <p class="small">${esc(merge.detail || "—")}</p>
          ${settingRow("PR open", esc(String(merge.pr_open_count ?? 0)))}
        </div>
        <div class="card queue-health-lane">
          <h3>Agent / hunter lane ${queueLaneBadge(agent.state)}</h3>
          <p class="small">${esc(agent.detail || "—")}</p>
          ${settingRow("Should dispatch", agent.should_dispatch ? "yes" : "no")}
          ${agent.next_task_id ? settingRow("Next task", `<code>${esc(agent.next_task_id)}</code>`) : ""}
          ${clearing.pause_active ? settingRow("Backlog pause", `<span class="badge badge-ii-no">active</span> (${esc(String(clearing.attention_parked_count ?? 0))} parked)`) : ""}
          ${(health.traffic_control || {}).pause_active ? settingRow("Traffic pause", `<span class="badge badge-ii-no">active</span> (${esc(String((health.traffic_control || {}).stuck_pr_count ?? 0))} stuck)`) : ""}
          ${settingRow(
            "Merges today / yesterday",
            `${esc(String(todayCount))} / ${esc(String(yesterdayCount))}`
          )}
          ${settingRow("Fix interventions today", esc(String(todayFixes)))}
          ${Array.isArray(health.merges_today) && health.merges_today.length
            ? settingRow(
                "Verified today",
                esc(String(health.verified_merges_today_count ?? health.merges_today.filter((r) => r.independently_verified).length))
              )
            : ""}
        </div>
        <div class="card queue-health-lane">
          <h3>Ops monitor ${ops.overall ? overallStatusBadge(ops.overall) : ""}</h3>
          <p class="small muted">${ops.run_at ? `Last run ${esc(fmtDate(ops.run_at))}` : "No ops_status yet"}</p>
          ${settingRow("Dispatch signal", ops.should_dispatch_engineering ? "ready" : "hold")}
        </div>
      </div>
      ${renderTaskCompletionMonitor(health)}
      ${renderObserveUtilizationSection({ queue_health: health, observe_utilization: health.observe_utilization })}
      ${renderN200PipelineHealthSection({
        queue_health: health,
        n200_pipeline_health: health.n200_pipeline_health,
        n200_tech_timing_observe: data.n200_tech_timing_observe,
      })}
      ${renderN201PipelineHealthSection({
        queue_health: health,
        n201_pipeline_health: health.n201_pipeline_health,
        n201_value_mom_observe: data.n201_value_mom_observe,
      }, { compact: true })}
      ${renderN206PipelineHealthSection({
        queue_health: health,
        n206_pipeline_health: health.n206_pipeline_health,
        n206_plain_ey_observe: data.n206_plain_ey_observe,
      }, { compact: true })}
      ${renderN210PipelineHealthSection({
        queue_health: health,
        n210_pipeline_health: health.n210_pipeline_health,
        n210_ai_judgment_observe: data.n210_ai_judgment_observe,
      }, { compact: true })}
      ${Array.isArray(health.merges_today) && health.merges_today.length ? `
      <div class="card" style="margin-top:0.75rem">
        <h3>Engineering merges today</h3>
        <ul class="small" style="margin:0.5rem 0 0;padding-left:1.2rem">
          ${health.merges_today.slice(0, 12).map((row) => {
            const pr = row.pr_number ? `#${row.pr_number}` : "";
            const href = row.pr_url || "";
            const label = `${row.merge_class || "human"}${row.independently_verified ? "/verified" : "/human"}`;
            const link = href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(pr || row.task_id || "PR")}</a>` : esc(pr || row.task_id || "");
            return `<li><code>${esc(label)}</code> ${link} — ${esc(row.title || "")}</li>`;
          }).join("")}
        </ul>
      </div>` : ""}
      <p class="small muted" style="margin-top:0.75rem">
        Auto-merge is <strong>event-driven</strong> (green CI → merge workflow), not a background merger.
        Narrow ingest/scoring PRs (≤8 safe paths + tests) pass an independent deterministic verify gate before merge.
        The agent lane runs when the hourly queue dispatches <code>engineering-agent</code>.
        Project traffic pauses new PRs when monitored branches are CI-red or conflicted
        (<a href="${esc(githubOpsDocUrl("docs/ops/project-traffic.md") || "#")}" target="_blank" rel="noopener">runbook</a>).
      </p>
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
    ai_judgment: "AI judgment (primary · stress)",
    ai_judgment_fair: "AI judgment (fair · Suite B)",
    rules_fair: "Rules (fair · Suite B)",
    ai_judgment_calibrated: "AI judgment calibrated (shadow)",
    momentum_grace: "Momentum grace",
    technical: "Technical (levels baseline)",
    buy_tier_level: "Buy-tier level (Suite B cohort)",
    buy_tier_level_dca: "Buy-tier level DCA (Suite B)",
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

function statsVerdictLabel(verdict) {
  const key = String(verdict || "");
  if (key === "positive") return "ahead of market (90%)";
  if (key === "negative") return "behind market (90%)";
  if (key === "indistinguishable_from_noise") return "not distinguishable from noise";
  return key || "—";
}

function formatCi90(ci) {
  if (!Array.isArray(ci) || ci.length < 2) return "—";
  const lo = ci[0];
  const hi = ci[1];
  if (lo == null || hi == null) return "—";
  return `${pctOrDash(lo)} … ${pctOrDash(hi)}`;
}

function renderAssessmentScoreboardPanel(data) {
  const board = data.assessment_scoreboard;
  const docUrl = githubOpsDocUrl("docs/ops/assessment-scoreboard.md");
  if (!board || !Array.isArray(board.tracks) || !board.tracks.length) {
    return `
      <section class="automation-section assessment-scoreboard-section">
        <h2>Assessment scoreboard</h2>
        <p class="muted">No assessment_scoreboard.json yet — ops-monitor writes total return vs FTAL.L plus track-statistics intervals.</p>
      </section>`;
  }
  const cmp = board.primary_vs_control || {};
  const tracks = board.tracks || [];
  const frozen = board.frozen_tracks || [];
  const twins = board.twins || [];
  const trackRows = tracks
    .map((row) => {
      const stats = row.statistics || {};
      const role = row.role || "";
      const roleBadge =
        role === "primary"
          ? ' <span class="badge badge-buy">primary</span>'
          : role === "control"
            ? ' <span class="badge badge-info">control</span>'
            : role === "twin"
              ? ' <span class="badge badge-hold">twin</span>'
              : "";
      const gate = row.ai_gate || {};
      const gateBit =
        gate.binds == null
          ? "—"
          : gate.binds
            ? "binds"
            : "does not bind";
      return `<tr>
        <td><strong>${esc(row.label || row.track_id || "—")}</strong>${roleBadge}<br><span class="small muted">${esc(row.track_id || "")} · ${esc(row.basis || "")}</span></td>
        <td>${pctOrDash(row.total_return)}</td>
        <td>${pctOrDash(row.benchmark_total_return)}</td>
        <td class="${signedReturnClass(row.excess_total_return)}">${pctOrDash(row.excess_total_return)}</td>
        <td>${pctOrDash(row.excess_total_return_at_stress_cost)}</td>
        <td><span class="small">${esc(statsVerdictLabel(stats.verdict))}</span><br><span class="small muted" title="Price-NAV vs price index; uncertainty band, not the total-return level">${esc(formatCi90(stats.ci90))}</span></td>
        <td class="small">${esc(gateBit)}</td>
      </tr>`;
    })
    .join("");
  const frozenHtml = frozen.length
    ? `<details class="overview-secondary" style="margin-top:0.75rem">
        <summary>Frozen Suite A stress books (final records)</summary>
        <p class="small muted">assessment_model.json frozen tracks — not scored as adoption truth.</p>
        <ul class="list-plain small">${frozen
          .map(
            (row) =>
              `<li><code>${esc(row.track_id || "—")}</code> · lifetime TR ${pctOrDash(
                row.lifetime_total_return
              )} · frozen ${esc(fmtDate(row.frozen_at))}</li>`
          )
          .join("")}</ul>
      </details>`
    : "";
  const twinHtml = twins.length
    ? `<details class="overview-secondary" style="margin-top:0.75rem">
        <summary>Twins vs parent (${esc(String(twins.length))})</summary>
        <ul class="list-plain small">${twins
          .map((row) => {
            const confound = (row.parent_knobs_changed || []).length
              ? ` · CONFOUNDED (${(row.parent_knobs_changed || []).join(", ")})`
              : "";
            return `<li><code>${esc(row.track_id || "—")}</code> vs ${esc(
              row.parent_track || "—"
            )} · Δ ${pctOrDash(row.difference)}${esc(confound)}</li>`;
          })
          .join("")}</ul>
      </details>`
    : "";
  return `
    <section class="automation-section assessment-scoreboard-section">
      <h2>Assessment scoreboard</h2>
      <p class="small muted" style="margin-top:0">
        Single fair-cost table. <strong>Level</strong> = total return (dividends credited) vs ${esc(
          board.benchmark || "FTAL.L"
        )}.
        <strong>Interval</strong> = 90% band on annualised <em>price-only</em> active return (track statistics) — knob apply needs a significant verdict (significance_gate_v1).
        Dual-suite A/B excess vs ^FTSE is legacy context.
        ${docUrl ? `<a href="${esc(docUrl)}" target="_blank" rel="noopener">Scoreboard runbook</a>` : ""}
        ${board.generated_at ? ` · Updated ${esc(fmtDate(board.generated_at))}` : ""}
      </p>
      <p>${esc(board.headline || "")}</p>
      <div class="learning-tracks-headline">
        <span>Primary <code>${esc(board.primary_track || "—")}</code></span>
        <span>Control <code>${esc(board.control_track || "—")}</code></span>
        <span>Common-window Δ ${pctOrDash(cmp.difference)}</span>
      </div>
      <div class="table-wrap">
        <table class="learning-tracks-table assessment-scoreboard-table">
          <thead>
            <tr>
              <th>Track</th>
              <th>Total return</th>
              <th>${esc(board.benchmark || "FTAL.L")}</th>
              <th>TR excess</th>
              <th>TR @ 3% stress</th>
              <th>Price-only 90% band</th>
              <th>AI gate</th>
            </tr>
          </thead>
          <tbody>${trackRows}</tbody>
        </table>
      </div>
      ${twinHtml}
      ${frozenHtml}
    </section>`;
}

function renderTotalReturnVsPricePanel(data) {
  const view = data.total_return_view;
  if (!view || !view.tracks || typeof view.tracks !== "object") return "";
  const assessed = Array.isArray(view.assessed_tracks) ? view.assessed_tracks : Object.keys(view.tracks);
  const rows = assessed
    .map((tid) => {
      const entry = view.tracks[tid] || {};
      const scored = entry.clean_epoch || entry.lifetime || {};
      const published = entry.published_excess_after_costs;
      const tr = scored.excess_total_return;
      return `<tr>
        <td><code>${esc(tid)}</code></td>
        <td>${pctOrDash(published)}</td>
        <td>${pctOrDash(tr)}</td>
        <td>${pctOrDash(scored.total_return)}</td>
        <td class="small muted">${esc(entry.clean_epoch ? "clean epoch" : "lifetime")}</td>
      </tr>`;
    })
    .join("");
  if (!rows) return "";
  return `
    <section class="automation-section total-return-view-section">
      <h3>Total return vs price-only excess</h3>
      <p class="small muted" style="margin-top:0">
        Published paper excess is price NAV vs ^FTSE. Total-return excess credits dividends vs ${esc(
          (view.benchmarks || {}).total_return || "FTAL.L"
        )}. Cite the total-return column for performance; the price-only column is the statistics/significance input.
      </p>
      <div class="table-wrap">
        <table class="learning-tracks-table">
          <thead>
            <tr>
              <th>Track</th>
              <th>Published excess (price)</th>
              <th>TR excess</th>
              <th>Total return</th>
              <th>Window</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`;
}

function renderPaperTrackBucketsPanel(data) {
  const dual = data.learning_tracks_dual_suite || {};
  const buckets = data.paper_track_buckets || {
    note: dual.note,
    suite_a_stress: {
      label: (dual.suite_a || {}).label,
      score_on: "cost_drag_and_trade_count",
      is_adoption_truth: false,
      primary_excess_after_costs: (dual.suite_a || {}).primary_excess_after_costs,
    },
    suite_b_adoption: {
      label: (dual.suite_b || {}).label,
      score_on: "fair_excess_vs_ftse_and_fair_rules",
      ai_excess_after_costs: (dual.suite_b || {}).ai_excess_after_costs,
    },
    suite_b_identity: {
      label: "Suite B — identity / membership floor",
      warning:
        "Positive buy_tier_level excess is the unfiltered membership floor, not fair-policy adoption.",
    },
  };
  if (!dual.suite_a && !data.paper_track_buckets) return "";
  const a = buckets.suite_a_stress || {};
  const b = buckets.suite_b_adoption || {};
  const ident = buckets.suite_b_identity || {};
  return `
    <details class="overview-secondary analysis-block" style="margin-top:0.75rem">
      <summary><strong>Legacy Suite A/B buckets</strong> — not the assessment scoreboard</summary>
      <p class="small muted">${esc(buckets.note || "")}</p>
      <ul class="list-plain small">
        <li><strong>${esc(a.label || "Suite A")}</strong> — score on ${esc(
          a.score_on || "cost_drag"
        )}; adoption=${a.is_adoption_truth ? "yes" : "no"}; stress excess ${pctOrDash(
          a.primary_excess_after_costs
        )}</li>
        <li><strong>${esc(b.label || "Suite B adoption")}</strong> — score on ${esc(
          b.score_on || "fair excess"
        )}; pair ${esc((data.learning_tracks_dual_suite || {}).suite_b?.ai_track_id || "primary")} vs ${esc(
          (data.learning_tracks_dual_suite || {}).suite_b?.control_track_id || "control"
        )}; excess ${pctOrDash(b.ai_excess_after_costs)} (price-only vs ^FTSE)</li>
        <li><strong>${esc(ident.label || "Identity floor")}</strong> — ${esc(
          ident.warning || "membership floor, not adoption"
        )}</li>
      </ul>
    </details>`;
}

/** Dual-suite scoreboard: Suite B pair follows the assessment model; Suite A is the frozen churn lab. */
function learningTrackIsSuiteB(trackId, trackConfigs) {
  const cfg = (trackConfigs || {})[trackId] || {};
  if (cfg.is_suite_b || cfg.is_fair_cost_lab || cfg.is_cohort_lab) return true;
  const id = String(trackId || "");
  if (id.endsWith("_fair")) return true;
  if (id === "buy_tier_level" || id === "buy_tier_level_dca" || id === "buy_tier_level_native") {
    return true;
  }
  return false;
}

function learningTrackSuiteOrder(suite, trackConfigs, reviewIds) {
  const preferredA = ["technical", "rules", "ai_judgment", "momentum_grace", "graduated_allocation"];
  const preferredB = [
    "ai_judgment_fair",
    "rules_fair",
    "buy_tier_level",
    "buy_tier_level_dca",
    "buy_tier_level_native",
  ];
  const preferred = suite === "B" ? preferredB : preferredA;
  const ids = reviewIds.filter((id) =>
    suite === "B" ? learningTrackIsSuiteB(id, trackConfigs) : !learningTrackIsSuiteB(id, trackConfigs)
  );
  const shadowIds = ids
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
  const ordered = [];
  for (const id of preferred) {
    if (!ids.includes(id) || ordered.includes(id)) continue;
    ordered.push(id);
    if (suite === "A" && id === "ai_judgment") {
      for (const shadowId of shadowIds) {
        if (!ordered.includes(shadowId)) ordered.push(shadowId);
      }
    }
  }
  for (const id of ids) {
    if (!ordered.includes(id)) ordered.push(id);
  }
  return ordered;
}

function renderLearningTrackRows(trackOrder, review, funds, trackConfigs) {
  return trackOrder
    .map((id) => {
      const row = review.reviews[id];
      if (!row) return "";
      const label = learningTrackLabel(id, trackConfigs);
      const m = row.metrics || {};
      const fund = funds[id] || {};
      const cfg = trackConfigs[id] || {};
      const primary = row.is_primary_learning_track
        ? ' <span class="badge badge-buy" title="Primary learning track flag (Suite A stress) — not flipped by Suite B scoreboard (N145)">primary</span>'
        : "";
      const suiteBadge = learningTrackIsSuiteB(id, trackConfigs)
        ? ' <span class="badge badge-info" title="Suite B fair / cohort lab">Suite B</span>'
        : ' <span class="badge badge-neutral" title="Suite A 3% stress lab">Suite A</span>';
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
        <td><strong>${esc(label)}</strong>${primary}${suiteBadge}${shadowBadge}${confBadge}<br><span class="small muted">${esc(id)}</span>${
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
}

function renderLearningTracksSuiteTable(title, blurb, headlineHtml, rowsHtml) {
  return `
    <h3 style="margin-top:1rem">${esc(title)}</h3>
    <p class="small muted" style="margin-top:0">${esc(blurb)}</p>
    ${headlineHtml || ""}
    <div class="table-wrap">
      <table class="learning-tracks-table">
        <thead>
          <tr>
            <th>Track</th>
            <th>NAV</th>
            <th>Return (price)</th>
            <th>Excess vs ^FTSE (price)</th>
            <th>Epoch return</th>
            <th>Epoch excess</th>
            <th>Trades</th>
            <th>Positions</th>
            <th>Recent marks</th>
          </tr>
        </thead>
        <tbody>${rowsHtml || '<tr><td colspan="9" class="muted">No tracks in this suite.</td></tr>'}</tbody>
      </table>
    </div>`;
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
  const dual = data.learning_tracks_dual_suite || {};
  const suiteAMeta = dual.suite_a || {};
  const suiteBMeta = dual.suite_b || {};
  const technicalMissing = !review.reviews.technical;
  const reviewIds = Object.keys(review.reviews);
  const orderA = learningTrackSuiteOrder("A", trackConfigs, reviewIds);
  const orderB = learningTrackSuiteOrder("B", trackConfigs, reviewIds);
  const rowsA = renderLearningTrackRows(orderA, review, funds, trackConfigs);
  const rowsB = renderLearningTrackRows(orderB, review, funds, trackConfigs);

  const fairExcess =
    suiteBMeta.ai_excess_after_costs != null
      ? suiteBMeta.ai_excess_after_costs
      : (review.reviews.ai_judgment_fair || {}).metrics?.excess_after_costs;
  const fairBeatMarket =
    suiteBMeta.beat_market != null
      ? suiteBMeta.beat_market
      : fairExcess != null
        ? Number(fairExcess) > 0
        : null;
  const fairBeatControl =
    suiteBMeta.beat_control != null
      ? suiteBMeta.beat_control
      : (() => {
          const rulesEx = (review.reviews.rules_fair || {}).metrics?.excess_after_costs;
          if (fairExcess == null || rulesEx == null) return null;
          return Number(fairExcess) > Number(rulesEx);
        })();
  const yesNo = (v) => (v == null ? "—" : v ? "Yes" : "No");

  const suiteBPair = `${suiteBMeta.ai_track_id || "primary"} vs ${suiteBMeta.control_track_id || "control"}`;
  const suiteBHeadline = `
    <div class="learning-tracks-headline">
      <span><strong>Legacy Suite B pair</strong> (assessment model: ${esc(suiteBPair)})</span>
      <span>Price-only excess vs ^FTSE: <strong>${fairExcess != null ? pct(fairExcess) : "—"}</strong>${
        (suiteBMeta.excess_basis || {}).ai === "since_zero_datum" && (suiteBMeta.zero_datum_started_at || {}).ai
          ? ` <span class="small muted" title="Forward-only: warm-start seed before this date is diagnostic (L533)">since ${esc(String(suiteBMeta.zero_datum_started_at.ai).slice(0, 10))}</span>`
          : ""
      } — not total-return vs FTAL.L</span>
      <span>Beat ^FTSE: ${esc(yesNo(fairBeatMarket))}</span>
      <span>Beat control (price-only): ${esc(yesNo(fairBeatControl))}</span>
    </div>`;

  const stressExcess =
    suiteAMeta.primary_excess_after_costs != null
      ? suiteAMeta.primary_excess_after_costs
      : review.primary_excess_after_costs;
  const frozenNote = (dual.frozen_tracks || []).length
    ? ` Frozen: ${(dual.frozen_tracks || []).join(", ")}.`
    : "";
  const suiteAHeadline = `
    <div class="learning-tracks-headline">
      <span><strong>Suite A stress / churn lab</strong> — frozen final records, not promotion truth</span>
      <span>Primary AI excess (3%): <strong>${stressExcess != null ? pct(stressExcess) : "—"}</strong></span>
      <span>Stress beat market: ${esc(yesNo(review.beat_market))}</span>
      <span>Stress beat rules: ${esc(yesNo(review.beat_control))}</span>
      <span>Verdict: <strong>${esc(review.verdict || "—")}</strong></span>
    </div>
    ${frozenNote ? `<p class="small muted">${esc(dual.note || "")}${esc(frozenNote)}</p>` : ""}`;

  const assess = dual.fair_assess_suite_a;
  const assessTracks = (assess && assess.tracks) || {};
  const assessRows = Object.entries(assessTracks)
    .map(([tid, row]) => {
      const relief = row.cost_drag_relief;
      return `<tr>
        <td><code>${esc(tid)}</code></td>
        <td>${pctOrDash(row.recorded_cost_drag)}</td>
        <td>${pctOrDash(row.fair_cost_drag)}</td>
        <td>${relief == null ? "—" : pctOrDash(relief)}</td>
        <td>${row.trade_count ?? "—"}</td>
      </tr>`;
    })
    .join("");
  const assessBlock = assessRows
    ? `<details class="overview-secondary" style="margin-top:1rem">
        <summary>Suite A friction under fair T212 rates (observe — does not rebuild excess)</summary>
        <p class="small muted">First-order cost_drag relief only. Adoption excess stays on Suite B fair twin books.</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Track</th><th>Recorded drag</th><th>Fair drag</th><th>Relief</th><th>Trades</th></tr></thead>
            <tbody>${assessRows}</tbody>
          </table>
        </div>
      </details>`
    : "";

  const docDual = githubOpsDocUrl(
    "docs/ops/market-trading-costs.md",
    "test-and-adoption-strategy-dual-suite"
  );
  const docPrimary = githubOpsDocUrl("docs/ops/primary-learning-track.md");

  return `<section class="automation-section learning-tracks-section">
    <h2>Learning tracks (server)</h2>
    <p class="small muted" style="margin-top:0">
      Weekday paper-auto books from CI — not the browser local sandbox.
      <strong>Canonical assessment</strong> is the scoreboard above (total return vs FTAL.L + statistics interval).
      Suite A/B dual-suite tables are retired to the collapsed archive below (price-only vs ^FTSE).
      ${docDual ? `<a href="${esc(docDual)}" target="_blank" rel="noopener">Dual-suite costs</a>` : ""}
      ${docPrimary ? ` · <a href="${esc(docPrimary)}" target="_blank" rel="noopener">Primary learning track</a>` : ""}
    </p>
    ${
      technicalMissing
        ? `<p class="small muted">Technical server track not published yet (L108) — use <strong>Performance → Simulation → Static/Trailing</strong> for archived level sims, or <strong>Portfolio → Technical</strong> for the browser sandbox.</p>`
        : ""
    }
    <details class="overview-secondary learning-tracks-dual-suite-archive" style="margin-top:0.75rem">
      <summary><strong>Legacy Suite A/B track tables</strong> — not the assessment scoreboard</summary>
      <p class="small muted">
        Price-only return / excess vs ^FTSE. Suite A 3% stress books are frozen final records — do not promote on stress excess alone (N145).
        Suite B pair follows the assessment model but promotion cites the scoreboard (total return vs FTAL.L).
      </p>
      ${renderLearningTracksSuiteTable(
        suiteBMeta.label || "Suite B — fair adoption scoreboard",
        suiteBMeta.blurb ||
          "Fair T212-shaped twins and cohort labs. Price-only excess vs ^FTSE — promotion cites the assessment scoreboard (total return vs FTAL.L).",
        suiteBHeadline,
        rowsB ||
          '<tr><td colspan="9" class="muted">No Suite B fair / cohort tracks published yet.</td></tr>'
      )}
      ${renderLearningTracksSuiteTable(
        suiteAMeta.label || "Suite A — stress / churn lab",
        suiteAMeta.blurb ||
          "Live FTSE books at 3% per-side stress (frozen final records). Use for cost drag / trade count / hold stability — not promotion.",
        suiteAHeadline,
        rowsA
      )}
      ${assessBlock}
    </details>
  </section>`;
}

const AUTOMATION_SECTION_IDS = ["daily", "tracks", "human", "queue", "ops", "settings"];
let automationSectionId = "daily";

function normalizeAutomationSection(value) {
  const key = String(value || "").toLowerCase();
  if (key === "learning" || key === "learning-tracks") return "tracks";
  if (key === "tasks" || key === "human-tasks") return "human";
  if (key === "hunter" || key === "eng" || key === "engineering") return "queue";
  if (key === "reconcile" || key === "health") return "ops";
  if (key === "config" || key === "achievements") return "settings";
  if (key === "hub" || key === "today") return "daily";
  if (AUTOMATION_SECTION_IDS.includes(key)) return key;
  return "daily";
}

function automationIlluminationFor(sectionId, data) {
  const hub = data && data.daily_focus;
  const hints = (hub && hub.illumination_hints) || {};
  const key = `automation.${sectionId}`;
  const hint = hints[key] || {};
  if (sectionId === "human") {
    const counts = ((data && data.human_tasks_board) || {}).counts || {};
    const newInfo = Number(counts.new_info || 0) > 0 || !!hint.new_info;
    const attn =
      Number(counts.new_info || 0) + Number(counts.unacked || 0) > 0 || !!hint.attention;
    return { new_info: newInfo, attention: attn };
  }
  if (sectionId === "tracks") {
    const board = data && data.assessment_scoreboard;
    const dual = data && data.learning_tracks_dual_suite;
    const attn = !(board && board.tracks) || !dual || !!hint.attention;
    return { new_info: false, attention: attn };
  }
  if (sectionId === "queue") {
    const obs = resolveObserveUtilization(data) || {};
    const fresh = String(obs.surface_freshness || "");
    const attn =
      ["stale", "degraded", "missing", "lagging"].includes(fresh) || !!hint.attention;
    return { new_info: false, attention: attn };
  }
  if (sectionId === "ops") {
    const recon = (data && data.ui_state_reconciliation) || {};
    const archive = (data && data.universe_filing_archive_status) || {};
    const lastBadge = String(((archive.last_run || {}).badge) || "");
    const archiveAttn = ["fail", "warn"].includes(lastBadge);
    const attn =
      String(recon.overall || "ok") !== "ok" || archiveAttn || !!hint.attention;
    return { new_info: false, attention: attn };
  }
  if (sectionId === "daily") {
    const stale = isDailyHubStale(hub);
    const openN = Number((hub && hub.open_task_count) || 0);
    const newInfo = !!hint.new_info || openN > 0;
    const attn = stale || !!hint.attention || openN > 0;
    return { new_info: newInfo, attention: attn };
  }
  return { new_info: !!hint.new_info, attention: !!hint.attention };
}

function renderIllumChips(illum) {
  if (!illum) return "";
  // Amber wins when both fire so urgency is not soft-washed.
  if (illum.attention) {
    return '<span class="illum-chip illum-attn badge badge-watch" title="Attention needed">attn</span>';
  }
  if (illum.new_info) {
    return '<span class="illum-chip illum-new badge badge-buy" title="New information">new</span>';
  }
  return "";
}

function renderAutomationSubnav(activeId, data) {
  const active = normalizeAutomationSection(activeId);
  const labels = {
    daily: "Daily",
    tracks: "Tracks",
    human: "Human",
    queue: "Queue",
    ops: "Ops",
    settings: "Settings",
  };
  return `<nav class="paper-subnav analysis-subnav automation-subnav" aria-label="Automation sections">
    ${AUTOMATION_SECTION_IDS.map((id) => {
      const illum = automationIlluminationFor(id, data);
      return `<button type="button" class="paper-subtab${
        id === active ? " active" : ""
      }" data-automation-section="${id}">${renderIllumChips(illum)}${esc(labels[id])}</button>`;
    }).join("")}
  </nav>
  <p class="small muted analysis-ia-contract" style="margin:0.35rem 0 0.75rem">
    Daily hub is the morning cockpit (Europe/London, refresh before 04:00).
    Green chip = unread delta (not “healthy”); amber = attention. Policy green ≠ utility.
  </p>`;
}

function syncAutomationHash() {
  const section = normalizeAutomationSection(automationSectionId);
  if (section === "daily") {
    history.replaceState(null, "", "#automation");
    return;
  }
  history.replaceState(null, "", `#automation/${section}`);
}

function jumpToAutomationSection(sectionId, { updateHash = true } = {}) {
  automationSectionId = normalizeAutomationSection(sectionId);
  const panel = document.getElementById("panel-automation");
  if (!panel) return;
  panel.querySelectorAll(".automation-subnav .paper-subtab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.automationSection === automationSectionId);
  });
  panel.querySelectorAll(".automation-section-pane").forEach((pane) => {
    const id = pane.getAttribute("data-automation-pane");
    pane.hidden = id !== automationSectionId;
  });
  if (updateHash) syncAutomationHash();
}

function bindAutomationPanel(panel) {
  if (!panel || panel.dataset.automationBound === "1") return;
  panel.dataset.automationBound = "1";
  panel.addEventListener("click", (event) => {
    const sub = event.target.closest("[data-automation-section]");
    if (sub && panel.contains(sub)) {
      event.preventDefault();
      jumpToAutomationSection(sub.dataset.automationSection);
      return;
    }
    const acceptBtn = event.target.closest("[data-daily-accept]");
    if (acceptBtn && panel.contains(acceptBtn)) {
      event.preventDefault();
      void acceptDailyRecommendation(acceptBtn);
      return;
    }
    const optionBtn = event.target.closest("[data-daily-option]");
    if (optionBtn && panel.contains(optionBtn)) {
      event.preventDefault();
      void applyDailyRecOption(optionBtn);
      return;
    }
    const discussBtn = event.target.closest("[data-daily-discuss]");
    if (discussBtn && panel.contains(discussBtn)) {
      event.preventDefault();
      void discussDailyRecommendation(discussBtn);
      return;
    }
    const tickBtn = event.target.closest("[data-daily-focus-ack]");
    if (tickBtn && panel.contains(tickBtn)) {
      event.preventDefault();
      void acknowledgeDailyFocusLine(tickBtn);
      return;
    }
    const copyBtn = event.target.closest("[data-copy-discuss-prompt]");
    if (copyBtn && panel.contains(copyBtn)) {
      event.preventDefault();
      const text = copyBtn.getAttribute("data-copy-discuss-prompt") || "";
      const labelDefault = copyBtn.getAttribute("data-copy-label") || "Copy";
      void (async () => {
        const ok = await copyTextToClipboard(text);
        // Short paste phrases also surface the inline selectable panel.
        if (/^discuss daily recommendation `/.test(text)) {
          showDailyDiscussPastePhrase(copyBtn, text, { copied: ok, queued: false });
        }
        copyBtn.textContent = ok ? "Copied" : "Select below";
        setTimeout(() => {
          copyBtn.textContent = labelDefault;
        }, 1500);
      })();
    }
  });
}

function renderUiReconcileBadge(data) {
  const recon = (data && data.ui_state_reconciliation) || null;
  if (!recon) {
    return `<span class="badge badge-neutral" title="Reconciliation not published yet">reconcile: —</span>`;
  }
  const overall = String(recon.overall || "ok");
  const fresh = String(recon.surface_freshness || "unknown");
  const warnN = Number((recon.summary || {}).warn || 0);
  const failN = Number((recon.summary || {}).fail || 0);
  const cls =
    overall === "fail"
      ? "badge-ii-no"
      : overall === "warn"
        ? "badge-watch"
        : "badge-buy";
  const label =
    overall === "ok"
      ? `reconcile ok · ${fresh}`
      : `reconcile ${overall} · ${warnN} warn / ${failN} fail`;
  return `<button type="button" class="link-btn" data-automation-section="ops" title="Open Automation → Ops">
    <span class="badge ${cls}">${esc(label)}</span>
  </button>`;
}

function renderPrFixCommonIssuesPanel(data) {
  const occasions = (data && data.pr_fix_occasions) || null;
  if (!occasions) {
    return `<section class="automation-section automation-section-full pr-fix-common-issues" id="pr-fix-common-issues">
      <h2>PR fix common issues</h2>
      <p class="muted">No <code>pr_fix_occasions.json</code> yet — log fixes with <code>ftse-project-traffic record-fix</code>.</p>
    </section>`;
  }
  const common = occasions.common_issues || {};
  const byReason = Array.isArray(common.by_reason) ? common.by_reason : [];
  const n = Array.isArray(occasions.occasions) ? occasions.occasions.length : 0;
  const rows = byReason
    .slice(0, 8)
    .map((row) => {
      const reason = row.failure_reason || row.reason || row.key || "—";
      const prs = Array.isArray(row.recent_prs) ? row.recent_prs.slice(0, 4).join(", ") : "—";
      return `<tr>
        <td class="small">${esc(reason)}</td>
        <td>${row.count ?? "—"}</td>
        <td class="small muted">${esc(prs)}</td>
      </tr>`;
    })
    .join("");
  const docUrl = githubOpsDocUrl("docs/ops/project-traffic.md", "pr-fix-occasion-log");
  return `<section class="automation-section automation-section-full pr-fix-common-issues" id="pr-fix-common-issues">
    <h2>PR fix common issues</h2>
    <p class="small muted" style="margin-top:0">
      Top recurring fix-request reasons from <code>pr_fix_occasions.json</code>
      (${n} occasions). Monthly checklist also surfaces this on the Human tab.
      ${docUrl ? `<a href="${esc(docUrl)}" target="_blank" rel="noopener">Occasion log runbook</a>` : ""}
      ${occasions.updated_at ? ` · Updated ${esc(fmtDate(occasions.updated_at))}` : ""}
    </p>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>Reason</th><th>Count</th><th>Recent PRs</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="3" class="muted">No common-issue rollup yet.</td></tr>'}</tbody>
      </table>
    </div>
  </section>`;
}

function renderUiReconcileTable(data) {
  const recon = (data && data.ui_state_reconciliation) || null;
  if (!recon) {
    return `<section class="automation-section automation-section-full" id="automation-ops">
      <h2>UI ↔ system reconciliation</h2>
      <p class="muted">Not published yet — waits for next ops-monitor cycle.</p>
    </section>`;
  }
  const rows = (recon.checks || [])
    .map((c) => {
      const st = String(c.status || "ok");
      const badge =
        st === "fail"
          ? "badge-ii-no"
          : st === "warn"
            ? "badge-watch"
            : "badge-buy";
      return `<tr>
        <td><code>${esc(c.id || "")}</code></td>
        <td>${esc(c.title || "")}</td>
        <td><span class="badge ${badge}">${esc(st)}</span></td>
        <td class="small">${esc(c.drift_class || "—")}</td>
        <td class="small">${esc(c.detail || "")}</td>
        <td class="small">${c.runbook ? `<code>${esc(c.runbook)}</code>` : "—"}</td>
      </tr>`;
    })
    .join("");
  const banner =
    String(recon.overall || "ok") !== "ok"
      ? `<div class="observe-stale-banner" role="status">UI state reconciliation drift — observe-only; do not eng-spray from this banner alone.</div>`
      : "";
  return `<section class="automation-section automation-section-full" id="automation-ops">
    <h2>UI ↔ system reconciliation</h2>
    <p class="small muted" style="margin-top:0">
      Dashboard health (Cap B). ${renderUiReconcileBadge(data)}
      · generated ${esc(fmtDate(recon.generated_at))} · TZ ${esc(recon.timezone || "Europe/London")}
    </p>
    ${banner}
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>Id</th><th>Check</th><th>Status</th><th>Drift</th><th>Detail</th><th>Runbook</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="6" class="muted">No checks</td></tr>'}</tbody>
    </table></div>
  </section>`;
}

function archiveStatusBadgeClass(badge) {
  const key = String(badge || "").toLowerCase();
  if (key === "fail" || key === "error") return "badge-ii-no";
  if (key === "warn" || key === "missing") return "badge-watch";
  if (key === "ok") return "badge-buy";
  return "badge-neutral";
}

function renderArchiveClashChips(flags) {
  if (!flags || typeof flags !== "object") return "";
  const chips = [];
  const iso = flags.isolation_ok;
  if (iso === true) {
    chips.push(`<span class="badge badge-buy" title="capacity_isolation.isolation_ok">isolation_ok</span>`);
  } else if (iso === false) {
    chips.push(`<span class="badge badge-ii-no" title="capacity_isolation.isolation_ok">isolation fail</span>`);
  } else {
    chips.push(`<span class="badge badge-neutral" title="capacity_isolation missing">isolation —</span>`);
  }
  if (flags.shared_critical_path) {
    chips.push(`<span class="badge badge-ii-no" title="shared_critical_path">shared quota</span>`);
  }
  if (flags.fourth_equal_sprint_stream) {
    chips.push(`<span class="badge badge-ii-no" title="fourth_equal_sprint_stream">4th sprint</span>`);
  } else if (flags.fourth_equal_sprint_stream === false) {
    chips.push(`<span class="badge badge-buy" title="not a fourth equal sprint">no 4th sprint</span>`);
  }
  if (flags.focus_pressure) {
    chips.push(`<span class="badge badge-watch" title="focus_pressure_reasons">focus pressure</span>`);
  }
  if (flags.gate_decision) {
    const gateCls =
      String(flags.gate_decision) === "allow"
        ? "badge-buy"
        : String(flags.gate_decision) === "suspend"
          ? "badge-watch"
          : "badge-neutral";
    chips.push(
      `<span class="badge ${gateCls}" title="archive_lane_gate">gate ${esc(flags.gate_decision)}</span>`
    );
  }
  return chips.join(" ");
}

function renderColdStoreArchiveStatusPanel(data) {
  const status = (data && data.universe_filing_archive_status) || null;
  if (!status) {
    return `<section class="automation-section automation-section-full cold-store-archive-status" id="cold-store-archive-status">
      <h2>Cold-store archive pack</h2>
      <p class="muted">Status panel not published yet — waits for next archive pack / ops-monitor cycle.</p>
    </section>`;
  }
  const last = status.last_run || {};
  const widen = status.next_widen_step || {};
  const caps = status.current_caps || {};
  const hours =
    last.hours_since != null && Number.isFinite(Number(last.hours_since))
      ? `${Number(last.hours_since).toFixed(Number(last.hours_since) >= 10 ? 0 : 1)}h ago`
      : "—";
  const mode =
    last.mode || (last.dry_run === true ? "dry" : last.dry_run === false ? "apply" : "—");
  const outcomeLabel = last.outcome || "missing";
  const errN = Number(last.error_count || 0);
  const errors = Array.isArray(last.errors) ? last.errors : [];
  const errLine =
    errN > 0
      ? `<p class="small cold-store-archive-errors" role="status"><span class="badge badge-ii-no">${esc(String(errN))} fail</span> ${esc(errors[0] || "see bottleneck review")}</p>`
      : "";
  const capsLine = [
    caps.max_units != null ? `units≤${caps.max_units}` : null,
    caps.max_http_fetches != null ? `http≤${caps.max_http_fetches}` : null,
    caps.max_tickers_per_unit != null ? `tickers/unit≤${caps.max_tickers_per_unit}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const runbook = status.runbook
    ? `<a href="${esc(status.runbook)}" target="_blank" rel="noopener">runbook</a>`
    : "";
  return `<section class="automation-section automation-section-full cold-store-archive-status" id="cold-store-archive-status">
    <h2>Cold-store archive pack <span class="badge ${archiveStatusBadgeClass(last.badge)}">${esc(outcomeLabel)}</span></h2>
    <p class="small muted" style="margin-top:0">
      Quiet lane status (observe-only; no eng spray). ${runbook}
      · panel ${esc(fmtDate(status.generated_at))}
    </p>
    <div class="cold-store-archive-grid">
      <div class="setting-row">
        <span class="setting-label">Last run</span>
        <span class="setting-value small">${esc(fmtDate(last.at))} · ${esc(hours)} · <code>${esc(mode)}</code></span>
      </div>
      <div class="setting-row">
        <span class="setting-label">Throughput</span>
        <span class="setting-value small">${esc(
          `attempted ${last.units_attempted ?? "—"} / completed ${last.units_completed ?? "—"} / objects ${last.objects_written ?? "—"}`
        )}</span>
      </div>
      <div class="setting-row">
        <span class="setting-label">Clash / isolation</span>
        <span class="setting-value small cold-store-archive-chips">${renderArchiveClashChips(status.clash_flags)}</span>
      </div>
      <div class="setting-row">
        <span class="setting-label">Pilot caps</span>
        <span class="setting-value small">${esc(capsLine || "—")}</span>
      </div>
      <div class="setting-row setting-row-widen">
        <span class="setting-label">Next widen</span>
        <span class="setting-value small"><strong>${esc(widen.label || "Hold pilot caps")}</strong>
          <span class="muted"> — ${esc(widen.detail || status.note || "")}</span></span>
      </div>
    </div>
    ${errLine}
  </section>`;
}

function renderDailyRecommendationBlock(rec, task) {
  if (!rec || typeof rec !== "object") return "";
  const acceptPayload = JSON.stringify({
    recommendation_id: rec.id,
    task_ref: (task && task.task_ref) || rec.task_id,
    accept_action: rec.accept_action || {},
    local_date: (dashboardData && dashboardData.daily_focus && dashboardData.daily_focus.local_date) || "",
  });
  const discussPayload = JSON.stringify({
    recommendation_id: rec.id,
    recommendation: {
      id: rec.id,
      task_id: rec.task_id,
      summary: rec.summary,
      rationale: rec.rationale,
      accept_action: rec.accept_action,
      discuss_prompt: rec.discuss_prompt,
      priority: rec.priority,
      options: rec.options || [],
    },
    local_date: (dashboardData && dashboardData.daily_focus && dashboardData.daily_focus.local_date) || "",
  });
  const options = Array.isArray(rec.options) ? rec.options : [];
  const optionsHtml = options.length
    ? `<div class="daily-rec-options" role="group" aria-label="Close options">
        <p class="small muted" style="margin:0.25rem 0">Choose an option in-card (no chat required for Accept / Defer / Park):</p>
        <ul class="daily-rec-option-list">${options
          .map((opt, idx) => {
            const normalized = normalizeDailyRecOption(opt, rec, task, idx);
            if (!normalized || !normalized.label) return "";
            const optPayload = JSON.stringify({
              recommendation_id: rec.id,
              task_ref: (task && task.task_ref) || rec.task_id,
              option_id: normalized.id,
              accept_action: normalized.action,
              preferred_option: normalized.preferredOption || normalized.id,
              local_date:
                (dashboardData &&
                  dashboardData.daily_focus &&
                  dashboardData.daily_focus.local_date) ||
                "",
              discuss_fallback: {
                recommendation_id: rec.id,
                recommendation: {
                  id: rec.id,
                  task_id: rec.task_id,
                  summary: rec.summary,
                  rationale: rec.rationale,
                  accept_action: rec.accept_action,
                  discuss_prompt: rec.discuss_prompt,
                  priority: rec.priority,
                  options: rec.options || [],
                },
                local_date:
                  (dashboardData &&
                    dashboardData.daily_focus &&
                    dashboardData.daily_focus.local_date) ||
                  "",
              },
            });
            const kind = String((normalized.action && normalized.action.kind) || "");
            const isPrimary = kind === "human-task-ack" || kind === "focus-ack";
            const btnClass = isPrimary && normalized.id === "accept" ? "btn btn-primary" : "btn";
            return `<li><button type="button" class="${btnClass} daily-rec-option-btn" data-daily-option="${esc(
              optPayload
            )}" title="${esc(normalized.label)}">${esc(normalized.label)}</button></li>`;
          })
          .join("")}</ul>
      </div>`
    : "";
  const pastePhrase = dailyDiscussPastePhrase(rec.id || "");
  const rowState = dailyRecRowState(rec.id || "");
  const acceptDisabledAttr = rowState.acceptDisabled
    ? ' disabled aria-disabled="true"'
    : ' aria-disabled="false"';
  const discussDisabledAttr = rowState.discussDisabled
    ? ' disabled aria-disabled="true"'
    : ' aria-disabled="false"';
  const statusSeed = rowState.accepted
    ? "Accepted"
    : rowState.discussLocked
      ? "Discuss queued — paste phrase above"
      : "";
  return `<div class="daily-rec-block" data-recommendation-id="${esc(rec.id || "")}">
    <h4 class="small" style="margin:0.6rem 0 0.25rem">Recommendation</h4>
    <p class="small"><strong>${esc(rec.summary || "")}</strong></p>
    <p class="small muted">${esc(rec.rationale || "")}</p>
    ${optionsHtml}
    <p class="daily-rec-actions">
      <button type="button" class="btn btn-primary" data-daily-accept="${esc(
        acceptPayload
      )}"${acceptDisabledAttr}>Accept</button>
      <button type="button" class="btn" data-daily-discuss="${esc(
        discussPayload
      )}" title="Copy paste phrase and queue Project inbox"${discussDisabledAttr}>Discuss</button>
      <button type="button" class="btn link-btn" data-copy-discuss-prompt="${esc(
        pastePhrase
      )}" data-copy-label="Copy paste phrase" title="Copy short Project chat phrase">Copy paste phrase</button>
      <button type="button" class="btn link-btn" data-copy-discuss-prompt="${esc(
        rec.discuss_prompt || pastePhrase
      )}" data-copy-label="Copy full prompt" title="Copy full discuss_prompt including rationale">Copy full prompt</button>
      <span class="small muted daily-rec-status" aria-live="polite">${esc(statusSeed)}</span>
    </p>
    <div class="daily-discuss-paste" hidden>
      <p class="small" style="margin:0.35rem 0 0.15rem"><strong>Paste into Project chat:</strong></p>
      <pre class="daily-discuss-paste-phrase" tabindex="0"></pre>
      <p class="small muted daily-discuss-paste-hint" style="margin:0.25rem 0 0"></p>
    </div>
    <p class="small muted">Discuss: click Discuss to copy <code>${esc(
      pastePhrase
    )}</code> and queue the inbox — then paste that phrase in Project chat. Prefer in-card options above when they close the task.</p>
  </div>`;
}

/** Normalize legacy string options or structured {id,label,action} rows. */
function normalizeDailyRecOption(opt, rec, task, idx) {
  if (opt && typeof opt === "object" && !Array.isArray(opt)) {
    const action = opt.action && typeof opt.action === "object" ? opt.action : null;
    if (!action) return null;
    return {
      id: String(opt.id || `opt-${idx}`),
      label: String(opt.label || opt.id || "").trim(),
      action,
      preferredOption: String(opt.id || ""),
    };
  }
  const label = String(opt || "").trim();
  if (!label) return null;
  const lower = label.toLowerCase();
  const defaultAccept = (rec && rec.accept_action) || {};
  if (/^accept\b/.test(lower) || lower.includes("acknowledge")) {
    return { id: `accept-${idx}`, label, action: defaultAccept, preferredOption: "accept" };
  }
  if (lower.includes("approve")) {
    const payload = Object.assign({}, (defaultAccept && defaultAccept.payload) || {}, {
      decision: "approve",
    });
    return {
      id: `approve-${idx}`,
      label,
      action: { kind: "human-task-ack", payload },
      preferredOption: "approve",
    };
  }
  if (lower.includes("defer") || lower.includes("park for today") || lower.includes("dismiss")) {
    if ((defaultAccept && defaultAccept.kind) === "human-task-ack") {
      const payload = Object.assign({}, defaultAccept.payload || {}, { decision: "defer" });
      return {
        id: `defer-${idx}`,
        label,
        action: { kind: "human-task-ack", payload },
        preferredOption: "defer",
      };
    }
    if ((defaultAccept && defaultAccept.kind) === "focus-ack") {
      const payload = Object.assign({}, defaultAccept.payload || {}, { decision: "dismiss" });
      return {
        id: `park-${idx}`,
        label,
        action: { kind: "focus-ack", payload },
        preferredOption: "park",
      };
    }
  }
  if (lower.includes("runbook") || lower.startsWith("open ")) {
    const href =
      (task && task.review_detail && task.review_detail.doc_url) ||
      (task && task.human_task && task.human_task.doc_url) ||
      (task && task.href) ||
      ((defaultAccept && defaultAccept.payload && defaultAccept.payload.href) || "#overview");
    return {
      id: `link-${idx}`,
      label,
      action: { kind: "link_only", payload: { href } },
      preferredOption: "runbook",
    };
  }
  if (lower.includes("discuss") || lower.includes("rewrite") || lower.includes("park")) {
    return {
      id: `discuss-${idx}`,
      label,
      action: { kind: "discuss", payload: { preferred_option: label } },
      preferredOption: "discuss",
    };
  }
  return {
    id: `discuss-${idx}`,
    label,
    action: { kind: "discuss", payload: { preferred_option: label } },
    preferredOption: "discuss",
  };
}

function renderDailyHubReviewDetail(task) {
  const detail =
    (task && task.review_detail) ||
    (task &&
      task.human_task &&
      task.human_task.analysis && {
        headline: task.human_task.analysis.headline,
        updated_at: task.human_task.analysis.updated_at,
        bullets: task.human_task.analysis.bullets,
        doc_url: task.human_task.doc_url,
        cadence: task.human_task.cadence,
        source_keys: task.human_task.analysis.source_keys,
        fingerprint: task.human_task.analysis.fingerprint,
        observe_only: true,
      });
  if (!detail || typeof detail !== "object") return "";
  const bullets = Array.isArray(detail.bullets)
    ? detail.bullets.map((b) => String(b || "").trim()).filter(Boolean)
    : [];
  const headline = String(detail.headline || "").trim();
  const docUrl = String(detail.doc_url || "").trim();
  if (!headline && !bullets.length && !docUrl) return "";
  const metaBits = [];
  if (detail.cadence) metaBits.push(String(detail.cadence));
  if (detail.updated_at) metaBits.push(`updated ${fmtDate(detail.updated_at)}`);
  if (Array.isArray(detail.source_keys) && detail.source_keys.length) {
    metaBits.push(detail.source_keys.slice(0, 4).join(", "));
  }
  return `<div class="daily-hub-review-detail" role="group" aria-label="Review detail">
    <h4 class="small" style="margin:0.45rem 0 0.2rem">Review detail</h4>
    ${headline ? `<p class="small"><strong>${esc(headline)}</strong></p>` : ""}
    ${
      bullets.length
        ? `<ul class="daily-review-bullets">${bullets
            .slice(0, 8)
            .map((b) => `<li class="small">${esc(b)}</li>`)
            .join("")}</ul>`
        : ""
    }
    ${
      docUrl
        ? `<p class="small"><a href="${esc(docUrl)}" target="_blank" rel="noopener noreferrer">Open related runbook / review</a></p>`
        : ""
    }
    ${
      metaBits.length
        ? `<p class="small muted" style="margin:0.2rem 0 0">${esc(metaBits.join(" · "))}</p>`
        : ""
    }
  </div>`;
}

function londonLocalDate(now = new Date()) {
  // en-CA → YYYY-MM-DD in Europe/London.
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/London",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(now);
  } catch {
    return now.toISOString().slice(0, 10);
  }
}

function isDailyHubStale(hub, now = new Date()) {
  if (!hub) return false;
  if (hub.stale_for_local_date) return true;
  const artifactDate = String(hub.local_date || "").trim();
  if (!artifactDate) return false;
  return artifactDate !== londonLocalDate(now);
}

function renderDailyHubStatusChips(status, { compact = false } = {}) {
  if (!status || typeof status !== "object") return "";
  const ready = !!status.ready;
  const state = String(status.state || "");
  let chip = "";
  if (ready || state === "ready") {
    chip = `<span class="badge badge-buy daily-status-chip" title="Ready to progress">Ready</span>`;
  } else if (state === "waiting" || (status.waiting_on && status.waiting_on.length)) {
    chip = `<span class="badge badge-watch daily-status-chip" title="Waiting on blocker">Waiting</span>`;
  } else if (state === "blocked") {
    chip = `<span class="badge badge-ii-no daily-status-chip">Blocked</span>`;
  } else if (state === "in_progress") {
    chip = `<span class="badge badge-neutral daily-status-chip">In progress</span>`;
  } else if (state) {
    chip = `<span class="badge badge-neutral daily-status-chip">${esc(state.replace(/_/g, " "))}</span>`;
  }
  if (compact) return chip;
  const next = Array.isArray(status.next_steps) && status.next_steps.length
    ? `<div class="small daily-status-next"><span class="muted">Next:</span> ${esc(status.next_steps[0])}</div>`
    : "";
  const waitingBits = (Array.isArray(status.waiting_on) ? status.waiting_on : [])
    .map((w) => (w && (w.detail || w.ref)) || "")
    .filter(Boolean);
  const waiting = waitingBits.length
    ? `<div class="small muted daily-status-waiting">Waiting on: ${esc(waitingBits.join("; "))}</div>`
    : "";
  return `${chip}${next}${waiting}`;
}

/**
 * Compose Daily hub assessment into one prose blurb.
 * Structured fields stay in JSON; UI only shows what is relevant (no "not stated").
 */
function formatDailyHubAssessmentProse(assessment, status, opts) {
  const options = opts || {};
  const skipWhere = String(options.skipWhere || "").trim();
  const where =
    (assessment && assessment.where_we_are) ||
    (status && status.label) ||
    "";
  const stageLabel = (assessment && assessment.stage_label) || "";
  const duration = (assessment && assessment.stage_duration) || "";
  const since = (assessment && assessment.stage_since) || "";
  const waitingFor =
    (assessment && assessment.waiting_for) ||
    ((Array.isArray(status && status.waiting_on) ? status.waiting_on : [])
      .map((w) => (w && (w.detail || w.ref)) || "")
      .filter(Boolean)
      .join("; "));
  const how =
    (assessment && assessment.how_achieved) ||
    (Array.isArray(status && status.next_steps) && status.next_steps[0]) ||
    "";
  const nextAll = Array.isArray(status && status.next_steps)
    ? status.next_steps.filter(Boolean)
    : [];
  const sentences = [];
  const whereTrim = String(where || "").trim();
  if (whereTrim && whereTrim !== skipWhere) {
    sentences.push(/[.!?]$/.test(whereTrim) ? whereTrim : `${whereTrim}.`);
  }
  // Skip bare "proposed" + "duration unknown" — that is seed noise, not status.
  const stageBits = [];
  if (stageLabel && stageLabel !== "proposed") stageBits.push(stageLabel);
  if (duration && duration !== "duration unknown") stageBits.push(duration);
  if (since) stageBits.push(`since ${since}`);
  if (stageBits.length) {
    sentences.push(`In stage: ${stageBits.join(" · ")}.`);
  }
  const waitTrim = String(waitingFor || "").trim();
  if (waitTrim) {
    sentences.push(
      /^waiting\b/i.test(waitTrim)
        ? /[.!?]$/.test(waitTrim)
          ? waitTrim
          : `${waitTrim}.`
        : `Waiting for ${waitTrim}.`
    );
  }
  const howTrim = String(how || "").trim();
  if (howTrim) {
    sentences.push(/[.!?]$/.test(howTrim) ? howTrim : `${howTrim}.`);
  }
  if (nextAll.length > 1) {
    const rest = nextAll.slice(howTrim ? 1 : 0).filter(Boolean);
    if (rest.length) {
      sentences.push(`Next: ${rest.join(" · ")}.`);
    }
  }
  return sentences.join(" ").trim();
}

function renderDailyHubAssessment(task) {
  const assessment =
    (task && task.assessment) ||
    (task && task.status && task.status.assessment) ||
    null;
  const status = (task && task.status) || null;
  if (!assessment && !status) return "";
  // Prefer a coherent paragraph; fall back to where/summary so the card still
  // answers "why is this on the list?" when stage/waiting/how are empty.
  let prose = formatDailyHubAssessmentProse(assessment, status, {});
  if (!prose) {
    const fallback = String(
      (assessment && assessment.where_we_are) ||
        (task && task.summary) ||
        (status && status.label) ||
        ""
    ).trim();
    if (fallback) {
      prose = /[.!?]$/.test(fallback) ? fallback : `${fallback}.`;
    }
  }
  if (!prose) return "";
  const durationTitle =
    assessment && assessment.stage_since
      ? `since ${assessment.stage_since}`
      : "no stage_since — builder does not invent dates";
  return `<div class="daily-hub-assessment" role="group" aria-label="Task assessment" title="${esc(
    durationTitle
  )}">
    <p class="daily-assess-prose">${esc(prose)}</p>
  </div>`;
}

function renderDailyHubHistorySession(data) {
  const hist = (data && data.daily_hub_history) || null;
  if (!hist) {
    return `<div class="daily-hub-session daily-hub-history" id="daily-hub-history">
      <h3>History</h3>
      <p class="muted small">daily_hub_history.json not published yet — next early / morning ops-monitor rebuild will seed it.</p>
    </div>`;
  }
  const sessions = Array.isArray(hist.sessions) ? hist.sessions : [];
  const summary = hist.summary || {};
  const candidates = Array.isArray(hist.automation_candidates)
    ? hist.automation_candidates
    : [];
  const rows = [];
  for (const session of sessions) {
    const entries = Array.isArray(session.entries) ? session.entries : [];
    for (const entry of entries) {
      // Default filter: development only (hide routine ops_gate / surface / auto).
      if (String(entry.work_class || "dev") !== "dev") continue;
      const outcome = String(entry.outcome || "");
      const outcomeLabel =
        outcome === "accept_followed"
          ? "Accept followed"
          : outcome === "discuss_resolved"
            ? "Discuss resolved"
            : outcome === "dismissed"
              ? "Dismissed"
              : outcome || "closed";
      const outcomeCls =
        outcome === "accept_followed"
          ? "badge-buy"
          : outcome === "discuss_resolved"
            ? "badge-watch"
            : "badge-neutral";
      const streak = Number((entry.automation_signal || {}).family_accept_streak || 0);
      rows.push(`<tr>
        <td class="small">${esc(entry.local_date || session.local_date || "")}</td>
        <td>${esc(entry.title || entry.task_ref || "")}</td>
        <td><span class="badge ${outcomeCls}">${esc(outcomeLabel)}</span>${
          entry.had_discuss ? ' <span class="badge badge-neutral" title="Went through Discuss">had discuss</span>' : ""
        }</td>
        <td class="small muted">${esc(entry.task_family || "")}${
          streak ? ` · streak ${esc(String(streak))}` : ""
        }</td>
      </tr>`);
    }
  }
  const threshold = Number(summary.accept_streak_threshold || 5);
  const windowDays = Number(summary.accept_streak_window_days || 30);
  const candidateBar =
    candidates.length > 0
      ? `<div class="daily-hub-accept-streak" role="status">
        <strong>Accept-streak hint</strong> (observe-only · never auto-flips checklist):
        ${candidates
          .map(
            (c) =>
              `<span class="badge badge-watch">${esc(c.task_family || "")}: ${esc(
                String(c.accept_streak || 0)
              )}/${esc(String(windowDays))}d Accept, 0 Discuss</span>`
          )
          .join(" ")}
        — review for possible <code>automated: true</code> later (N169 not_now).
      </div>`
      : `<div class="daily-hub-accept-streak muted small" role="status">
        Accept-streak hint: none yet (needs ≥${esc(String(threshold))} Accepts with 0 Discuss in ${esc(
          String(windowDays)
        )}d on a stable task family). Observe-only — does not auto-flip checklist.
      </div>`;
  return `<div class="daily-hub-session daily-hub-history" id="daily-hub-history">
    <h3>History <span class="badge badge-neutral">dev completed</span></h3>
    <p class="small muted" style="margin-top:0">
      Operator memory of development closes ·
      ${esc(String(summary.dev_closed_7d ?? 0))} closed / 7d ·
      ${esc(String(summary.accept_followed_7d ?? 0))} Accept followed ·
      ${esc(String(summary.discuss_resolved_7d ?? 0))} Discuss resolved ·
      ${esc(String(summary.candidate_count ?? 0))} automation candidates
      · generated ${esc(fmtDate(hist.generated_at))}
    </p>
    <div class="table-wrap"><table class="data-table daily-hub-history-table">
      <thead><tr><th>Date</th><th>Title</th><th>Outcome</th><th>Family</th></tr></thead>
      <tbody>${
        rows.length
          ? rows.join("")
          : '<tr><td colspan="4" class="muted">No completed development tasks in retention window.</td></tr>'
      }</tbody>
    </table></div>
    ${candidateBar}
  </div>`;
}

function renderDailyHubTaskCard(task) {
  const closed = !!task.closed;
  const bucket = task.sort_bucket || task.source || "";
  const rec = task.recommendation || null;
  const status = task.status || null;
  const tickPayload = JSON.stringify({
    task_ref: task.task_ref,
    focus_id: (task.close_payload && task.close_payload.focus_id) || task.task_ref,
    decision: "ack",
    local_date: (dashboardData && dashboardData.daily_focus && dashboardData.daily_focus.local_date) || "",
  });
  const closeBtn =
    task.closeable && !closed
      ? `<button type="button" class="btn" data-daily-focus-ack="${esc(
          tickPayload
        )}" title="Ack / close for local date">✓</button>`
      : closed
        ? '<span class="badge badge-neutral">closed</span>'
        : "";
  // Human tasks still use existing ack path via Accept → human-task-ack.
  const humanHint =
    task.close_action === "human-task-ack"
      ? '<span class="badge badge-watch" title="Accept runs human-task-ack">human ack</span>'
      : "";
  const triageAction = String(task.triage_action || (rec && rec.triage_action) || "").trim();
  const triageHint = triageAction
    ? `<span class="badge ${
        triageAction === "deepen"
          ? "badge-buy"
          : triageAction === "dismiss"
            ? "badge-neutral"
            : "badge-watch"
      }" title="Market warning triage action">${esc(triageAction)}</span>${
        task.prefer_discuss || (rec && rec.prefer_discuss)
          ? '<span class="badge badge-watch" title="Fat-slot / rate-limit judgment — Discuss preferred">Discuss</span>'
          : ""
      }${
        task.dismissable === false
          ? '<span class="badge badge-sell" title="Policy: cannot dismiss or park">no dismiss</span>'
          : ""
      }`
    : "";
  const workClass =
    task.work_class
      ? `<span class="badge badge-neutral" title="work_class">${esc(task.work_class)}</span>`
      : "";
  return `<details class="human-task-card daily-hub-card sort-${esc(bucket)}" data-task-ref="${esc(
    task.task_ref || ""
  )}" ${closed ? "" : "open"}>
    <summary class="human-task-card-toggle">
      <span class="human-task-card-head">
        <strong>${esc(task.title || task.task_ref || "Task")}</strong>
        <span class="badge badge-neutral">${esc(task.source || "")}</span>
        <span class="badge badge-neutral">P${esc(String(task.priority ?? ""))}</span>
        ${workClass}
        ${humanHint}
        ${triageHint}
        ${renderDailyHubStatusChips(status, { compact: true })}
      </span>
      ${closeBtn}
    </summary>
    <div class="human-task-card-panel">
      <p class="small">${esc(task.summary || "")}</p>
      ${renderDailyHubAssessment(task)}
      ${renderDailyHubReviewDetail(task)}
      ${
        task.href
          ? `<p class="small"><a href="${esc(task.href)}">${esc(task.href)}</a></p>`
          : ""
      }
      ${renderDailyRecommendationBlock(rec, task)}
    </div>
  </details>`;
}

function renderDailyHubStatusReport(hub) {
  const report = (hub && hub.status_report) || null;
  const rows = (report && report.rows) || [];
  if (!rows.length) {
    return `<h4 class="small" style="margin:0.35rem 0">Status</h4>
      <p class="muted small">Status report not in payload yet — next ops-monitor rebuild will embed it.</p>`;
  }
  const lis = rows
    .map(
      (r) =>
        `<li><strong>${esc(r.label || r.id || "")}</strong>
        <span class="small">${esc(r.value || "")}</span></li>`
    )
    .join("");
  return `<h4 class="small" style="margin:0.35rem 0">Status <span class="badge badge-neutral">grounded</span></h4>
    <ul class="list-plain daily-status-list">${lis}</ul>`;
}

function renderDailyHubLaneBlock(hub, lane) {
  const key = lane === "explore" ? "explore_suggestions" : "push_suggestions";
  const block = (hub && hub[key]) || null;
  const suggestions = (block && block.suggestions) || [];
  const title = lane === "explore" ? "Explore (not-today)" : "Push (today)";
  const badge =
    lane === "explore"
      ? '<span class="badge badge-watch">explore · not-today</span>'
      : '<span class="badge badge-neutral">push · ≤3</span>';
  if (!suggestions.length) {
    const empty =
      lane === "push"
        ? esc(block && block.empty_message ? block.empty_message : "No forced push — factory green.")
        : "No explore cards (empty OK).";
    return `<h4 class="small" style="margin:0.75rem 0 0.35rem">${esc(title)} ${badge}</h4>
      <p class="muted small">${empty}</p>`;
  }
  const lis = suggestions
    .map((s) => {
      if (lane === "explore") {
        return `<li><strong>${esc(s.claim || s.title || "")}</strong> ${badge}
          <div class="small">Why: ${esc(s.why_matters || "")}</div>
          <div class="small muted">Falsify/promote: ${esc(s.falsify_or_promote || "")}</div>
          <div class="small muted">${esc(s.defer_hint || "ftse-defer add|fragment")}</div></li>`;
      }
      const cite = s.cite || {};
      return `<li><strong>${esc(s.title || "")}</strong> ${badge}
        <div class="small">${esc(s.why_now || "")}</div>
        <div class="small muted">Cite: ${esc(cite.kind || "")} ${esc(cite.ref || "")}</div></li>`;
    })
    .join("");
  return `<h4 class="small" style="margin:0.75rem 0 0.35rem">${esc(title)} ${badge}</h4>
    <ul class="list-plain daily-lane-list">${lis}</ul>`;
}

function renderDailyHubLaterBlock(hub) {
  const rows =
    (hub && hub.later_suggestions) ||
    (hub && hub.push_suggestions && hub.push_suggestions.later_suggestions) ||
    [];
  const badge = '<span class="badge badge-watch">later · not Push</span>';
  if (!rows.length) {
    return "";
  }
  const lis = rows
    .map((row) => {
      return `<li><strong>${esc(row.title || "")}</strong> ${badge}
        <div class="small">Outstanding: ${esc(row.gap || "")}</div>
        <div class="small muted">Already done: ${esc(row.done || "")}</div></li>`;
    })
    .join("");
  return `<h4 class="small" style="margin:0.75rem 0 0.35rem">Later <span class="badge badge-watch">gap only</span></h4>
    <ul class="list-plain daily-lane-list">${lis}</ul>`;
}

function renderDailyHubPanel(data) {
  const hub = (data && data.daily_focus) || null;
  if (!hub) {
    return `<section class="automation-section automation-section-full daily-hub-section" id="automation-daily">
      <h2>Daily hub</h2>
      <p class="muted">daily_focus.json not published yet — next early ops-monitor (~02:30 UTC) or morning rebuild will seed it.</p>
    </section>`;
  }
  const wallStale = isDailyHubStale(hub);
  const todayLondon = londonLocalDate();
  const staleBanner = wallStale
    ? `<div class="observe-stale-banner" role="status">Daily hub stale for local date ${esc(
        hub.local_date || ""
      )} — wall clock is ${esc(todayLondon)} ${esc(
        hub.timezone || "Europe/London"
      )}. Refresh target is before ${esc(hub.refresh_deadline_local || "04:00")} (early ops-monitor ~02:30 UTC).</div>`
    : "";
  const focusHtml = (hub.focus_lines || [])
    .map((line) => {
      const task = (hub.tasks || []).find((t) => t.task_ref === line.id) || {};
      const status = task.status || line.status || null;
      const assess = task.assessment || (status && status.assessment) || line.assessment || null;
      const summary = String(line.summary || "").trim();
      const prose = formatDailyHubAssessmentProse(assess, status, {
        skipWhere: summary,
      });
      const proseBit = prose
        ? `<div class="small daily-assess-focus-prose">${esc(prose)}</div>`
        : "";
      return `<li><strong>${esc(line.title || "")}</strong>
        <span class="badge badge-neutral">${esc(line.source || "focus")}</span>
        ${renderDailyHubStatusChips(status, { compact: true })}
        <div class="small muted">${esc(summary)}</div>
        ${proseBit}</li>`;
    })
    .join("");
  const openTasks = (hub.tasks || []).filter((t) => !t.closed);
  // Push/Explore already rendered in lane blocks — keep triage/human/reconcile here.
  const triageTasks = openTasks.filter(
    (t) => t.sort_bucket !== "push" && t.sort_bucket !== "explore" && t.sort_bucket !== "later"
  );
  const cards = triageTasks.map(renderDailyHubTaskCard).join("");
  const counts = hub.counts || {};
  const hist = (data && data.daily_hub_history) || null;
  const histSummary = (hist && hist.summary) || {};
  return `<section class="automation-section automation-section-full daily-hub-section" id="automation-daily">
    <h2>Daily hub</h2>
    <p class="small muted" style="margin-top:0">
      Collated morning board · local date <strong>${esc(hub.local_date || "")}</strong>
      (${esc(hub.timezone || "Europe/London")}) · refresh before ${esc(
        hub.refresh_deadline_local || "04:00"
      )}
      · ${renderUiReconcileBadge(data)}
      · open ${esc(String(hub.open_task_count ?? openTasks.length))}
      · push ${esc(String(counts.push || 0))} /
        later ${esc(String(counts.later || 0))} /
        explore ${esc(String(counts.explore || 0))} /
        warn ${esc(String(counts.market_warnings || 0))} /
        new ${esc(String(counts.human_new_info || 0))} /
        unacked ${esc(String(counts.human_unacked || 0))}
      · generated ${esc(fmtDate(hub.generated_at))}
      ${wallStale ? ' · <span class="badge badge-watch">stale vs wall clock</span>' : ""}
    </p>
    ${staleBanner}
    <div class="daily-hub-aim muted small">Aim: policy green ≠ utility — Focus tracks P1 live-path bind (holdings ∪ strand A ∪ N200; N201 waiter honest) and P2 offline ingest maintenance / clash-aware eng (chips only — no ritual Focus Accept). Two lanes: <strong>Push</strong> (execution, cited, ≤3) and <strong>Explore</strong> (labeled not-today; may sit outside North Star; claim + why + falsify). Market warning triage: deepen / dismiss / park only when actionable — do not ritual-clear bare health=warn or divert offline ingest / maintenance capacity.</div>
    <div class="daily-hub-session daily-hub-today" id="daily-hub-today">
      <h3>Today</h3>
      ${renderDailyHubStatusReport(hub)}
      <h4 class="small" style="margin:0.35rem 0">Focus <span class="badge badge-neutral">chips</span></h4>
      ${
        focusHtml
          ? `<ul class="list-plain daily-focus-list">${focusHtml}</ul>`
          : '<p class="muted">No focus lines — sync Project notes Today bullets into project_daily_seed.json.</p>'
      }
      ${renderDailyHubLaneBlock(hub, "push")}
      ${renderDailyHubLaterBlock(hub)}
      ${renderDailyHubLaneBlock(hub, "explore")}
      <h4 class="small" style="margin:0.75rem 0 0.35rem">Prioritized tasks</h4>
      ${cards || '<p class="muted">No open daily tasks.</p>'}
    </div>
    ${renderDailyHubHistorySession(data)}
    <p class="small muted">History: ${esc(String(histSummary.dev_closed_7d ?? 0))} dev closes · ${esc(
      String(histSummary.candidate_count ?? 0)
    )} candidates (7d window in summary).</p>
  </section>`;
}

/** Canonical Project-chat pickup phrase — keep in sync with ops/design docs. */
function dailyDiscussPastePhrase(recommendationId) {
  const id = String(recommendationId || "").trim() || "rec-unknown";
  return `discuss daily recommendation \`${id}\``;
}

function setDailyRecStatus(button, text) {
  const liveBlock =
    button && button.isConnected && button.closest
      ? button.closest(".daily-rec-block")
      : null;
  if (liveBlock) {
    const el = liveBlock.querySelector(".daily-rec-status");
    if (el) el.textContent = text || "";
    return;
  }
  // Optimistic Accept re-render detaches the clicked button — recover via rec id.
  if (!button || !button.getAttribute) return;
  try {
    const raw =
      button.getAttribute("data-daily-accept") ||
      button.getAttribute("data-daily-discuss") ||
      "{}";
    const payload = JSON.parse(raw);
    const rid =
      dailyRecOverlayKey(payload) ||
      String((payload.recommendation && payload.recommendation.id) || "").trim();
    if (!rid) return;
    const panel = document.getElementById("panel-automation");
    if (!panel) return;
    const escape =
      (window.CSS && typeof window.CSS.escape === "function" && window.CSS.escape.bind(window.CSS)) ||
      ((value) => String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"'));
    const block = panel.querySelector(
      `.daily-rec-block[data-recommendation-id="${escape(rid)}"]`
    );
    const el = block && block.querySelector(".daily-rec-status");
    if (el) el.textContent = text || "";
  } catch {
    /* ignore */
  }
}

function showDailyDiscussPastePhrase(button, phrase, { copied = false, queued = false } = {}) {
  const block = button && button.closest(".daily-rec-block");
  if (!block) return;
  const panel = block.querySelector(".daily-discuss-paste");
  const phraseEl = block.querySelector(".daily-discuss-paste-phrase");
  const hintEl = block.querySelector(".daily-discuss-paste-hint");
  if (!panel || !phraseEl) return;
  phraseEl.textContent = phrase;
  panel.hidden = false;
  const bits = [];
  if (copied) bits.push("Copied to clipboard");
  else bits.push("Select the phrase below and copy (clipboard unavailable)");
  if (queued) bits.push("inbox queued");
  bits.push("paste into Project chat");
  if (hintEl) hintEl.textContent = bits.join(" · ");
  try {
    const range = document.createRange();
    range.selectNodeContents(phraseEl);
    const sel = window.getSelection();
    if (sel) {
      sel.removeAllRanges();
      sel.addRange(range);
    }
  } catch {
    /* selection is best-effort */
  }
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value) return false;
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      /* fall through */
    }
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return !!ok;
  } catch {
    return false;
  }
}

async function queueDailyBridgeAction(action, payload, onStatus) {
  if (isLocalDashboardServe()) {
    const path =
      action === "daily-discuss" ? "/api/daily-discuss" : "/api/daily-focus-ack";
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) {
      throw new Error(body.error || `HTTP ${response.status}`);
    }
    if (onStatus) onStatus("Recorded locally");
    return body;
  }
  if (!window.DashboardBridge) throw new Error("Dashboard bridge unavailable");
  const bridgeReady = await window.DashboardBridge.init();
  if (!bridgeReady) throw new Error("Dashboard bridge not configured");
  const queueFn =
    typeof window.DashboardBridge.queueCommand === "function"
      ? window.DashboardBridge.queueCommand.bind(window.DashboardBridge)
      : null;
  if (queueFn) return queueFn(action, payload, onStatus);
  return window.DashboardBridge.submitCommand(action, payload, onStatus, { wait: false });
}

async function acknowledgeDailyFocusLine(button) {
  if (!button || button.disabled) return;
  let payload = {};
  try {
    payload = JSON.parse(button.getAttribute("data-daily-focus-ack") || "{}");
  } catch {
    payload = {};
  }
  button.disabled = true;
  try {
    await queueDailyBridgeAction("daily-focus-ack", payload, null);
    button.textContent = "✓";
    await reloadDashboard({ silent: true });
  } catch (err) {
    button.disabled = false;
    button.title = String(err && err.message ? err.message : err);
  }
}

async function acceptDailyRecommendation(button) {
  if (!button || button.disabled) return;
  let payload = {};
  try {
    payload = JSON.parse(button.getAttribute("data-daily-accept") || "{}");
  } catch {
    payload = {};
  }
  await runDailyRecommendationAction(button, payload);
}

async function applyDailyRecOption(button) {
  if (!button || button.disabled) return;
  let payload = {};
  try {
    payload = JSON.parse(button.getAttribute("data-daily-option") || "{}");
  } catch {
    payload = {};
  }
  const action = (payload.accept_action && payload.accept_action.kind) || "";
  if (action === "discuss") {
    const fallback = payload.discuss_fallback || {
      recommendation_id: payload.recommendation_id,
      local_date: payload.local_date || "",
    };
    // Prefer attaching chosen option into discuss recommendation note path.
    if (fallback.recommendation && payload.preferred_option) {
      const pref = String(payload.preferred_option || "");
      const existing = String(fallback.recommendation.summary || "");
      if (pref && !existing.includes(`[option:${pref}]`)) {
        fallback.recommendation = Object.assign({}, fallback.recommendation, {
          summary: `${existing} [option:${pref}]`.trim(),
          preferred_option: pref,
        });
      }
    }
    // Reuse Discuss button path by synthesizing a temporary attribute carrier.
    button.setAttribute("data-daily-discuss", JSON.stringify(fallback));
    await discussDailyRecommendation(button);
    return;
  }
  await runDailyRecommendationAction(button, {
    recommendation_id: payload.recommendation_id,
    task_ref: payload.task_ref,
    accept_action: payload.accept_action || {},
    local_date: payload.local_date || "",
  });
}

async function runDailyRecommendationAction(button, payload) {
  if (!button || button.disabled) return;
  payload = payload || {};
  const action = (payload.accept_action && payload.accept_action.kind) || "";
  const actionPayload = (payload.accept_action && payload.accept_action.payload) || {};
  const recKey = dailyRecOverlayKey(payload);
  if (recKey && (inflightDailyRecActions[recKey] || pendingDailyAccepts[recKey])) return;
  if (recKey) inflightDailyRecActions[recKey] = "accept";

  // Optimistic first: disable Accept+Discuss and overlay-close before any await
  // so soft reload / bridge latency cannot leave the row clickable.
  disableDailyRecRowButtons(button, { accept: true, discuss: true });
  const block = button.closest && button.closest(".daily-rec-block");
  if (block) {
    block.querySelectorAll("[data-daily-option]").forEach((btn) => {
      btn.disabled = true;
      btn.setAttribute("aria-disabled", "true");
    });
  }
  setDailyRecStatus(button, "Applying…");
  if (action !== "link_only" && action !== "discuss") {
    applyOptimisticDailyAccept(payload);
  }

  try {
    if (action === "human-task-ack") {
      const htPayload = {
        task_id: actionPayload.task_id,
        decision: actionPayload.decision || "ack_observe",
        finding_fingerprint: actionPayload.finding_fingerprint || "",
      };
      // Mirror human-task card: optimistic board sort before bridge await.
      applyOptimisticHumanTaskAck(htPayload);
      if (isLocalDashboardServe()) {
        const response = await fetch("/api/human-task-ack", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(htPayload),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok || body.ok === false) {
          throw new Error(body.error || `HTTP ${response.status}`);
        }
      } else {
        if (!window.DashboardBridge) throw new Error("Dashboard bridge unavailable");
        const bridgeReady = await window.DashboardBridge.init();
        if (!bridgeReady) throw new Error("Dashboard bridge not configured");
        const queueFn =
          typeof window.DashboardBridge.queueCommand === "function"
            ? window.DashboardBridge.queueCommand.bind(window.DashboardBridge)
            : null;
        if (queueFn) {
          await queueFn("human-task-ack", htPayload, (msg) => setDailyRecStatus(button, msg));
        } else {
          await window.DashboardBridge.submitCommand(
            "human-task-ack",
            htPayload,
            (msg) => setDailyRecStatus(button, msg),
            { wait: false }
          );
        }
      }
      const decisionLabel = String(htPayload.decision || "ack_observe");
      setDailyRecStatus(
        button,
        decisionLabel === "defer"
          ? "Deferred → human-task-ack"
          : decisionLabel === "approve"
            ? "Approved → human-task-ack"
            : "Accepted → human-task-ack"
      );
      await reloadDashboard({ silent: true });
    } else if (action === "focus-ack") {
      const focusDecision =
        String(actionPayload.decision || "accept").trim() || "accept";
      await queueDailyBridgeAction(
        "daily-focus-ack",
        {
          focus_id: actionPayload.focus_id || payload.task_ref,
          task_ref: actionPayload.focus_id || payload.task_ref,
          recommendation_id: payload.recommendation_id,
          decision: focusDecision,
          local_date: payload.local_date || "",
        },
        (msg) => setDailyRecStatus(button, msg)
      );
      setDailyRecStatus(
        button,
        focusDecision === "dismiss" ? "Dismissed for today" : "Accepted for today"
      );
      await reloadDashboard({ silent: true });
    } else if (action === "link_only") {
      const href = actionPayload.href || "#overview";
      if (href.startsWith("#automation/")) {
        const section = href.replace("#automation/", "") || "daily";
        jumpToAutomationSection(section);
      } else if (href.startsWith("#")) {
        activateTab(href.replace("#", "").split("/")[0] || "overview", { updateHash: true });
      } else if (/^https?:\/\//i.test(href)) {
        window.open(href, "_blank", "noopener,noreferrer");
      } else {
        window.location.href = href;
      }
      setDailyRecStatus(button, "Opened link");
      enableDailyRecRowButtons(button, { accept: true, discuss: true });
      if (block) {
        block.querySelectorAll("[data-daily-option]").forEach((btn) => {
          btn.disabled = false;
          btn.setAttribute("aria-disabled", "false");
        });
      }
      return;
    } else {
      await queueDailyBridgeAction(
        "daily-focus-ack",
        {
          task_ref: payload.task_ref,
          recommendation_id: payload.recommendation_id,
          decision: "accept",
          local_date: payload.local_date || "",
        },
        (msg) => setDailyRecStatus(button, msg)
      );
      setDailyRecStatus(button, "Accepted");
      await reloadDashboard({ silent: true });
    }
  } catch (err) {
    if (action === "human-task-ack" && actionPayload.task_id) {
      revertOptimisticHumanTaskAck(actionPayload.task_id);
    }
    if (recKey) revertOptimisticDailyAccept(recKey);
    else enableDailyRecRowButtons(button, { accept: true, discuss: true });
    if (block) {
      block.querySelectorAll("[data-daily-option]").forEach((btn) => {
        btn.disabled = false;
        btn.setAttribute("aria-disabled", "false");
      });
    }
    setDailyRecStatus(button, String(err && err.message ? err.message : err));
  } finally {
    if (recKey) delete inflightDailyRecActions[recKey];
  }
}

async function discussDailyRecommendation(button) {
  if (!button || button.disabled) return;
  let payload = {};
  try {
    payload = JSON.parse(button.getAttribute("data-daily-discuss") || "{}");
  } catch {
    payload = {};
  }
  const recId =
    payload.recommendation_id ||
    (payload.recommendation && payload.recommendation.id) ||
    "";
  const recKey = dailyRecOverlayKey({
    recommendation_id: recId,
    local_date: payload.local_date || "",
  });
  if (recKey && (inflightDailyRecActions[recKey] || pendingDailyAccepts[recKey])) return;
  if (recKey && pendingDailyDiscuss[recKey] && pendingDailyDiscuss[recKey].status !== "failed") {
    return;
  }
  if (recKey) inflightDailyRecActions[recKey] = "discuss";

  // Short canonical phrase for Project chat (not the full discuss_prompt).
  const pastePhrase = dailyDiscussPastePhrase(recId);
  // Optimistic first: lock Accept+Discuss before clipboard / bridge await.
  disableDailyRecRowButtons(button, { accept: true, discuss: true });
  if (recKey) rememberPendingDailyDiscuss(payload, "inflight");
  setDailyRecStatus(button, "Copying paste phrase…");
  let copied = false;
  try {
    copied = await copyTextToClipboard(pastePhrase);
    showDailyDiscussPastePhrase(button, pastePhrase, { copied, queued: false });
    setDailyRecStatus(
      button,
      copied ? "Paste phrase copied — queuing inbox…" : "Paste phrase shown — queuing inbox…"
    );
    await queueDailyBridgeAction("daily-discuss", payload, (msg) => setDailyRecStatus(button, msg));
    if (recKey) rememberPendingDailyDiscuss(payload, "queued");
    showDailyDiscussPastePhrase(button, pastePhrase, { copied, queued: true });
    setDailyRecStatus(
      button,
      copied
        ? `Copied — paste into Project chat: ${pastePhrase}`
        : `Select & paste into Project chat: ${pastePhrase}`
    );
    // Keep Discuss locked for the session (prevents double inbox queue).
    // Re-enable Accept so the operator can still accept after discussing.
    enableDailyRecRowButtons(button, { accept: true, discuss: false });
    disableDailyRecRowButtons(button, { accept: false, discuss: true });
  } catch (err) {
    if (recKey) clearPendingDailyDiscuss(recKey);
    enableDailyRecRowButtons(button, { accept: true, discuss: true });
    showDailyDiscussPastePhrase(button, pastePhrase, { copied, queued: false });
    setDailyRecStatus(button, String(err && err.message ? err.message : err));
  } finally {
    if (recKey) delete inflightDailyRecActions[recKey];
  }
}

function renderAutomationSettingsSection(data, auto) {
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

  return `
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
    </div>`;
}

function renderAutomation(data) {
  const panel = document.getElementById("panel-automation");
  if (!panel) return;
  bindHumanTasksSection();
  bindAutomationPanel(panel);
  const auto = data.automation;
  if (!auto) {
    panel.innerHTML =
      '<div class="empty-state">Automation status not published yet. Run <code>ftse-library automation-status</code> or wait for the next ladder / publish.</div>';
    return;
  }

  const engineeringQueue = resolveEngineeringQueue(data);
  const section = normalizeAutomationSection(automationSectionId);

  panel.innerHTML = `
    ${renderAutomationSubnav(section, data)}
    <div class="automation-section-pane" data-automation-pane="daily" ${
      section === "daily" ? "" : "hidden"
    }>
      ${renderDailyHubPanel(data)}
    </div>
    <div class="automation-section-pane" data-automation-pane="tracks" ${
      section === "tracks" ? "" : "hidden"
    }>
      ${renderAssessmentScoreboardPanel(data)}
      ${renderTotalReturnVsPricePanel(data)}
      ${renderLearningTracksPanel(data)}
      ${renderKnobBootstrapPanel(data)}
      ${renderChurnCounterfactualPanel(data)}
    </div>
    <div class="automation-section-pane" data-automation-pane="human" ${
      section === "human" ? "" : "hidden"
    }>
      ${renderIngestDeviationsSection(data.ingest_deviations)}
      ${renderHumanTasksChecklistSection(data.human_tasks_checklist, data.human_tasks_board)}
    </div>
    <div class="automation-section-pane" data-automation-pane="queue" ${
      section === "queue" ? "" : "hidden"
    }>
      ${renderQueueHealthMonitor(data)}
      ${renderEngineeringQueueSection(engineeringQueue)}
    </div>
    <div class="automation-section-pane" data-automation-pane="ops" ${
      section === "ops" ? "" : "hidden"
    }>
      ${renderPrFixCommonIssuesPanel(data)}
      ${renderColdStoreArchiveStatusPanel(data)}
      ${renderUiReconcileTable(data)}
    </div>
    <div class="automation-section-pane" data-automation-pane="settings" ${
      section === "settings" ? "" : "hidden"
    }>
      ${renderAutomationSettingsSection(data, auto)}
    </div>
  `;
}

let lifecycleMarketId = null;
let lifecycleTrackId = null;
let lifecycleSubpage = "positions";
let sealedLifecycleModelId = "n200";
/** Sealed observe board: heat map (default zoom-out) or one-line list. */
let sealedLifecycleViewMode = "heatmap";
let sealedLifecycleDetailKey = null;
/** Per-phase cell/chip order: name | pnl | time. */
let sealedLifecycleSortMode = "name";
const SEALED_LIFECYCLE_SORT_MODES = ["name", "pnl", "time"];
const SEALED_LIFECYCLE_SORT_LABELS = {
  name: "Name",
  pnl: "% P&L",
  time: "Time in phase",
};

const LIFECYCLE_CHIP_SORT_KEY = "ftseValueInvestor.lifecycleChipSort.v1";
const LIFECYCLE_CHIP_SORT_DIR_KEY = "ftseValueInvestor.lifecycleChipSortDir.v1";
const LIFECYCLE_CHIP_SORT_MODES = ["board", "alpha", "stage"];
const LIFECYCLE_CHIP_SORT_DIRS = ["asc", "desc"];

function loadLifecycleChipSort() {
  try {
    const saved = localStorage.getItem(LIFECYCLE_CHIP_SORT_KEY);
    if (LIFECYCLE_CHIP_SORT_MODES.includes(saved)) return saved;
  } catch {
    /* ignore */
  }
  return "board";
}

function saveLifecycleChipSort(mode) {
  try {
    localStorage.setItem(LIFECYCLE_CHIP_SORT_KEY, mode);
  } catch {
    /* ignore */
  }
}

function loadLifecycleChipSortDir() {
  try {
    const saved = localStorage.getItem(LIFECYCLE_CHIP_SORT_DIR_KEY);
    if (LIFECYCLE_CHIP_SORT_DIRS.includes(saved)) return saved;
  } catch {
    /* ignore */
  }
  return null;
}

function saveLifecycleChipSortDir(dir) {
  try {
    localStorage.setItem(LIFECYCLE_CHIP_SORT_DIR_KEY, dir);
  } catch {
    /* ignore */
  }
}

let lifecycleChipSort = loadLifecycleChipSort();
let lifecycleChipSortDir = loadLifecycleChipSortDir();

function resolveLifecycleChipSortDir(mode, dir) {
  if (LIFECYCLE_CHIP_SORT_DIRS.includes(dir)) return dir;
  // Time in stage defaults to longest-first (desc); other modes ascending.
  return mode === "stage" ? "desc" : "asc";
}

function sortLifecycleCards(shown, mode, dir) {
  const rows = Array.isArray(shown) ? shown.slice() : [];
  const descending = dir === "desc";
  if (mode === "alpha") {
    rows.sort((a, b) =>
      String(a.ticker || "").localeCompare(String(b.ticker || ""), undefined, {
        sensitivity: "base",
      })
    );
    return descending ? rows.reverse() : rows;
  }
  if (mode === "stage") {
    rows.sort((a, b) => {
      const ad = a.days_in_column;
      const bd = b.days_in_column;
      const aMissing = ad == null || Number.isNaN(Number(ad));
      const bMissing = bd == null || Number.isNaN(Number(bd));
      if (aMissing && bMissing) {
        return String(a.ticker || "").localeCompare(String(b.ticker || ""), undefined, {
          sensitivity: "base",
        });
      }
      if (aMissing) return 1;
      if (bMissing) return -1;
      // Ascending = shortest in stage first; descending = longest first.
      const delta = Number(ad) - Number(bd);
      if (delta !== 0) return descending ? -delta : delta;
      return String(a.ticker || "").localeCompare(String(b.ticker || ""), undefined, {
        sensitivity: "base",
      });
    });
    return rows;
  }
  return descending ? rows.reverse() : rows;
}

const LIFECYCLE_SUBPAGE_IDS = new Set(["positions", "maturity", "reviews", "post-sale"]);

const SEALED_LIFECYCLE_MODELS = ["n200", "n201", "n206", "n210"];

function normalizeSealedLifecycleModel(value) {
  const key = String(value || "").toLowerCase();
  return SEALED_LIFECYCLE_MODELS.includes(key) ? key : "n200";
}

function normalizeLifecycleSubpage(value) {
  const key = String(value || "").toLowerCase();
  if (key === "maturity" || key === "maturity-mix") return "maturity";
  if (key === "sealed" || key === "sealed-models") return "sealed";
  if (key === "reviews" || key === "post-sale" || key === "post-sale-reviews") {
    return "reviews";
  }
  if (key === "entry-blind" || key === "entry_blind" || key === "entryblind") {
    return "entry-blind";
  }
  if (
    key === "entry-revisit" ||
    key === "entry_revisit" ||
    key === "entryrevisit" ||
    key === "buy28" ||
    key === "buy-28"
  ) {
    return "entry-revisit";
  }
  if (key === "positions" || key === "board" || key === "tiles") return "positions";
  return "positions";
}

function parseDashboardHash() {
  const raw = String(location.hash || "").replace(/^#/, "").trim();
  if (!raw) return null;
  const parts = raw.split("/").filter(Boolean);
  const tab = parts[0] || null;
  if (tab === "analysis") {
    // Support #analysis/observe/<modelId> and #analysis/<modelId> shorthand.
    let subpage = parts[1] || "observe";
    let model = null;
    if (isInvestmentModelHashToken(subpage)) {
      model = normalizeInvestmentModel(subpage);
      subpage = "observe";
    } else if (parts[2] && isInvestmentModelHashToken(parts[2])) {
      model = normalizeInvestmentModel(parts[2]);
    }
    return {
      tab: "analysis",
      subpage: normalizeAnalysisSection(subpage),
      model,
      market: null,
      track: null,
    };
  }
  if (tab === "automation") {
    return {
      tab: "automation",
      subpage: normalizeAutomationSection(parts[1] || "daily"),
      market: null,
      track: null,
    };
  }
  if (tab === "performance") {
    return {
      tab: "performance",
      subpage: normalizePerformanceSection(parts[1] || "signals"),
      market: null,
      track: null,
    };
  }
  if (tab === "screener") {
    return {
      tab: "screener",
      subpage: normalizeScreenerFilter(parts[1] || ""),
      market: null,
      track: null,
    };
  }
  if (tab !== "lifecycle") {
    return { tab, subpage: null, market: parts[1] || null, track: parts[2] || null };
  }
  let rest = parts.slice(1);
  let subpage = "positions";
  if (rest[0] === "sealed" || rest[0] === "sealed-models") {
    return {
      tab: "lifecycle",
      subpage: "sealed",
      market: null,
      track: null,
      sealedModel: rest[1] || null,
    };
  }
  if (rest[0] === "maturity" || rest[0] === "maturity-mix") {
    subpage = "maturity";
    rest = rest.slice(1);
  } else if (rest[0] === "positions") {
    subpage = "positions";
    rest = rest.slice(1);
  } else if (rest[0] && LIFECYCLE_SUBPAGE_IDS.has(rest[0])) {
    subpage = rest[0];
    rest = rest.slice(1);
  }
  return {
    tab: "lifecycle",
    subpage,
    market: rest[0] || null,
    track: rest[1] || null,
  };
}

function syncLifecycleHash() {
  if (lifecycleSubpage === "sealed") {
    const model = normalizeSealedLifecycleModel(sealedLifecycleModelId);
    history.replaceState(null, "", `#lifecycle/sealed/${model}`);
    return;
  }
  if (lifecycleSubpage === "reviews") {
    history.replaceState(null, "", "#lifecycle/reviews");
    return;
  }
  if (lifecycleSubpage === "maturity") {
    history.replaceState(null, "", "#lifecycle/maturity");
    return;
  }
  if (!lifecycleMarketId) {
    history.replaceState(null, "", "#lifecycle");
    return;
  }
  const parts = ["lifecycle", lifecycleMarketId];
  if (lifecycleTrackId) parts.push(lifecycleTrackId);
  history.replaceState(null, "", `#${parts.join("/")}`);
}

function applyDashboardHash() {
  const parsed = parseDashboardHash();
  if (!parsed || !parsed.tab) return;
  if (parsed.tab === "lifecycle") {
    if (parsed.subpage) lifecycleSubpage = normalizeLifecycleSubpage(parsed.subpage);
    if (parsed.sealedModel) {
      sealedLifecycleModelId = normalizeSealedLifecycleModel(parsed.sealedModel);
    }
    if (parsed.market) lifecycleMarketId = parsed.market;
    if (parsed.track) lifecycleTrackId = parsed.track;
  }
  if (parsed.tab === "analysis" && parsed.subpage) {
    analysisSectionId = normalizeAnalysisSection(parsed.subpage);
  }
  if (parsed.tab === "analysis" && parsed.model) {
    investmentModelId = normalizeInvestmentModel(parsed.model);
  }
  if (parsed.tab === "automation" && parsed.subpage) {
    automationSectionId = normalizeAutomationSection(parsed.subpage);
  }
  if (parsed.tab === "performance" && parsed.subpage) {
    performanceSectionId = normalizePerformanceSection(parsed.subpage);
  }
  if (parsed.tab === "screener") {
    screenerFilterId = normalizeScreenerFilter(parsed.subpage || "");
  }
  activateTab(parsed.tab);
  if (parsed.tab === "analysis" && dashboardData) {
    // Re-render so model-bound Observe panels match hash before scroll.
    if (parsed.model) renderAnalysis(dashboardData);
    // Defer scroll until panel is visible / laid out.
    window.requestAnimationFrame(() => jumpToAnalysisSection(analysisSectionId, { updateHash: false }));
  }
  if (parsed.tab === "automation" && dashboardData) {
    window.requestAnimationFrame(() => jumpToAutomationSection(automationSectionId, { updateHash: false }));
  }
  if (parsed.tab === "performance" && dashboardData) {
    renderPerformance(dashboardData);
  }
  if (parsed.tab === "screener" && dashboardData) {
    renderScreener(dashboardData);
  }
}

function openLifecycleBoard(marketId) {
  if (marketId) lifecycleMarketId = marketId;
  lifecycleTrackId = null;
  lifecycleSubpage = "positions";
  activateTab("lifecycle", { updateHash: true });
  const dialog = document.getElementById("market-status-dialog");
  if (dialog && dialog.open) dialog.close();
  if (dashboardData) renderLifecycle(dashboardData);
}

function renderLifecycleSubnav() {
  const sub =
    lifecycleSubpage === "maturity"
      ? "maturity"
      : lifecycleSubpage === "sealed"
        ? "sealed"
        : lifecycleSubpage === "reviews"
          ? "reviews"
          : lifecycleSubpage === "entry-blind" || lifecycleSubpage === "entry_blind"
            ? "entry-blind"
            : lifecycleSubpage === "entry-revisit" || lifecycleSubpage === "entry_revisit"
              ? "entry-revisit"
              : "positions";
  return `<nav class="paper-subnav lifecycle-subnav" aria-label="Lifecycle sections">
    <button type="button" class="paper-subtab${
      sub === "positions" ? " active" : ""
    }" data-lifecycle-subpage="positions">Positions</button>
    <button type="button" class="paper-subtab${
      sub === "maturity" ? " active" : ""
    }" data-lifecycle-subpage="maturity">Maturity mix</button>
    <button type="button" class="paper-subtab${
      sub === "sealed" ? " active" : ""
    }" data-lifecycle-subpage="sealed">Sealed models</button>
    <button type="button" class="paper-subtab${
      sub === "reviews" ? " active" : ""
    }" data-lifecycle-subpage="reviews">Post-sale reviews</button>
    <button type="button" class="paper-subtab${
      sub === "entry-blind" ? " active" : ""
    }" data-lifecycle-subpage="entry-blind">Entry blind</button>
    <button type="button" class="paper-subtab${
      sub === "entry-revisit" ? " active" : ""
    }" data-lifecycle-subpage="entry-revisit">Entry +28d</button>
  </nav>`;
}

function lifecycleStatusChip(status) {
  const key = String(status || "planned").toLowerCase();
  const cls = {
    observing: "stage-complete",
    continue: "stage-active",
    recommend: "stage-complete",
    proposed: "stage-pending",
    planned: "stage-pending",
    deferred: "stage-pending",
    fail: "stage-fail",
  };
  return `<span class="stage-badge ${cls[key] || "stage-active"}">${esc(key)}</span>`;
}

function findLifecycleExperiment(factorId) {
  const columns = ((dashboardData || {}).lifecycle_board || {}).columns || [];
  for (const col of columns) {
    const hit = (col.experiments || []).find((row) => row.factor_id === factorId);
    if (hit) return { column: col, experiment: hit };
  }
  return null;
}

function renderLifecycleExperimentCard(factorId) {
  const found = findLifecycleExperiment(factorId);
  if (!found) {
    return `<p class="muted">No experiment card for <code>${esc(factorId)}</code>.</p>`;
  }
  const row = found.experiment;
  const progress = row.progress || {};
  const initiation = row.initiation || {};
  const ledger = row.assessment_status || progress.ledger_status;
  const recommend = String(ledger || "") === "recommend";
  const ready = Boolean(initiation.ready_to_initiate);
  const waiting = initiation.waiting_for
    ? `<p>${esc(initiation.waiting_for)}</p>`
    : "<p class=\"muted small\">No further gate recorded.</p>";
  const evidenceRows = Array.isArray(initiation.evidence) ? initiation.evidence : [];
  const evidenceHtml = evidenceRows.length
    ? `<ul class="lifecycle-evidence-list">${evidenceRows
        .map((item) => {
          const ok = Boolean(item && item.ok);
          const current = item && item.current ? " current" : "";
          return `<li class="${ok ? "ok" : "fail"}${current}"><span class="lifecycle-evidence-mark">${
            ok ? "✓" : "·"
          }</span> ${esc(item.label || item.id || "gate")}${
            item.detail ? ` <span class="muted">(${esc(String(item.detail))})</span>` : ""
          }</li>`;
        })
        .join("")}</ul>`
    : "";
  const acknowledge = initiation.acknowledge || {};
  const ackEnabled = Boolean(acknowledge.enabled);
  const ackPayload = JSON.stringify(acknowledge.payload || {});
  const start = initiation.start || {};
  const startEnabled = Boolean(start.enabled);
  const startPayload = JSON.stringify(start.payload || {});
  // Planned/deferred factors can inherit assessment_status=recommend from a shared
  // experiment (e.g. prior_cycle_outcome → entry_dca_overlay). Hide Acknowledge/Start
  // there — those actions belong to human_ack / optional_execute / waiting cards only.
  const initKind = String(initiation.kind || "");
  const showActionBtns =
    recommend && ["human_ack", "optional_execute", "waiting"].includes(initKind);
  const ackLabel = acknowledge.label || "Acknowledge";
  const startLabel = start.label || "Start";
  const startAlready =
    !startEnabled && /already started/i.test(String(start.disabled_reason || initiation.label || ""));
  const actionBtns = showActionBtns
    ? `<p class="lifecycle-start-row">
        <button type="button" class="btn lifecycle-ack-btn${ackEnabled ? " btn-primary" : ""}" data-lifecycle-ack="${esc(
          ackPayload
        )}" ${ackEnabled ? "" : "disabled"} aria-disabled="${ackEnabled ? "false" : "true"}" title="${esc(
          ackEnabled ? "Record observe-only ack via Supabase" : acknowledge.disabled_reason || "Ack not available"
        )}">${esc(ackLabel)}</button>
        <button type="button" class="btn lifecycle-start-btn${startEnabled ? " btn-primary" : ""}${
          startAlready ? " lifecycle-start-done" : ""
        }" data-lifecycle-start="${esc(
          startPayload
        )}" ${startEnabled ? "" : "disabled"} aria-disabled="${startEnabled ? "false" : "true"}" title="${esc(
          startEnabled
            ? "Start graduated entry DCA execute via Supabase"
            : start.disabled_reason || "Not ready"
        )}">${esc(startLabel)}</button>
        <span class="small muted lifecycle-start-status" aria-live="polite">${
          startAlready ? esc(start.disabled_reason || "Already started") : ""
        }</span>
      </p>
      ${
        ackEnabled || startEnabled || startAlready
          ? ""
          : `<p class="small muted">${esc(
              start.disabled_reason || acknowledge.disabled_reason || "Actions blocked until gates clear"
            )}</p>`
      }`
    : recommend && (initKind === "planned" || initKind === "deferred")
      ? `<p class="small muted">Acknowledge / Start stay on collecting factors — this chip is ${esc(
          initKind
        )}${initiation.waiting_for ? `: ${esc(String(initiation.waiting_for))}` : ""}.</p>`
      : "";
  const recommendHeading = startAlready
    ? "Execute already started"
    : ready
      ? "Ready for next human step"
      : "Not ready to initiate";
  const recommendBlock = recommend
    ? `<div class="lifecycle-init-box ${ready || startAlready ? "ready" : "waiting"}">
        <p class="small" style="margin-top:0"><strong>${esc(recommendHeading)}</strong></p>
        <p>${esc(initiation.label || (ready ? "Ready" : "Waiting"))}</p>
        ${waiting}
        ${
          startAlready
            ? `<p class="small muted">Sibling factors (entry_dca_cadence, add_cadence, entry_kind_tag) share one Start — no need to click again.</p>`
            : ""
        }
        ${
          initiation.recommendation
            ? `<p class="lifecycle-recommendation"><strong>Recommendation:</strong> ${esc(
                initiation.recommendation.replace(/^Recommendation:\s*/i, "")
              )}</p>`
            : ""
        }
        ${evidenceHtml ? `<h5 class="small">Evidence</h5>${evidenceHtml}` : ""}
        ${
          initiation.do_not
            ? `<p class="small muted">Do not: ${esc(initiation.do_not)}</p>`
            : ""
        }
        ${
          initiation.adoption_stage
            ? `<p class="small muted">Adoption stage <code>${esc(initiation.adoption_stage)}</code></p>`
            : ""
        }
        ${actionBtns}
        <p class="small muted">Recommend is observe-only — never auto-applied.</p>
      </div>`
    : `<div class="lifecycle-init-box waiting">
        <p class="small" style="margin-top:0"><strong>${esc(initiation.label || "Collecting")}</strong></p>
        ${initiation.waiting_for ? `<p>${esc(initiation.waiting_for)}</p>` : ""}
        ${
          initiation.recommendation
            ? `<p class="lifecycle-recommendation"><strong>Recommendation:</strong> ${esc(
                initiation.recommendation.replace(/^Recommendation:\s*/i, "")
              )}</p>`
            : ""
        }
        ${evidenceHtml ? `<h5 class="small">Evidence</h5>${evidenceHtml}` : ""}
        ${
          initiation.do_not
            ? `<p class="small muted">Do not: ${esc(initiation.do_not)}</p>`
            : ""
        }
      </div>`;
  return `
    <p class="small muted" style="margin-top:0">${esc(found.column.label || found.column.id)} · ${esc(
      row.lifecycle_stage || ""
    )} · <code>${esc(row.experiment || row.factor_id)}</code></p>
    <div class="market-card-badges">
      ${lifecycleStatusChip(row.status)}
      ${ledger ? lifecycleStatusChip(ledger) : ""}
      ${row.model_independent ? '<span class="badge badge-ii-ok">model-independent</span>' : ""}
      ${row.human_ack_required ? '<span class="badge badge-watch">human ack</span>' : ""}
    </div>
    <h4 class="small">Aim</h4>
    <p>${esc(row.aim || row.question || "—")}</p>
    <h4 class="small">Progress</h4>
    <p>${esc(progress.summary || "No ledger row yet.")}</p>
    ${row.artifact ? `<p class="small muted">Artifact <code>${esc(row.artifact)}</code></p>` : ""}
    ${row.assessment_title ? `<p class="small muted">${esc(row.assessment_title)}</p>` : ""}
    <h4 class="small">${recommend ? "Recommend — initiate?" : "Next step"}</h4>
    ${recommendBlock}
  `;
}


function openLifecycleExperimentCard(factorId) {
  const dialog = document.getElementById("lifecycle-experiment-dialog");
  const title = document.getElementById("lifecycle-experiment-title");
  const body = document.getElementById("lifecycle-experiment-body");
  if (!dialog || !title || !body) return;
  const found = findLifecycleExperiment(factorId);
  title.textContent = found
    ? found.experiment.factor_id || found.experiment.experiment || "Lifecycle experiment"
    : "Lifecycle experiment";
  body.innerHTML = renderLifecycleExperimentCard(factorId);
  const ackBtn = body.querySelector("[data-lifecycle-ack]");
  if (ackBtn) {
    ackBtn.addEventListener("click", () => {
      void acknowledgeLifecycleExperimentFromCard(ackBtn);
    });
  }
  const startBtn = body.querySelector("[data-lifecycle-start]");
  if (startBtn) {
    startBtn.addEventListener("click", () => {
      void startLifecycleExperimentFromCard(startBtn);
    });
  }
  dialog.showModal();
}

async function acknowledgeLifecycleExperimentFromProgressReport(button) {
  const statusEl = document.getElementById("progress-lifecycle-ack-status");
  const setStatus = (msg, isError) => {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("progress-report-status-error", Boolean(isError));
  };
  let payload = {};
  try {
    payload = JSON.parse(button.getAttribute("data-progress-ack") || "{}");
  } catch (err) {
    setStatus("Invalid ack payload", true);
    return;
  }
  if (!payload.experiment_id) {
    setStatus("Missing experiment id", true);
    return;
  }
  button.disabled = true;
  setStatus("Acknowledging…");
  try {
    const local = await fetch("/api/lifecycle-experiment-ack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (local.ok) {
      const body = await local.json();
      if (!body.ok) throw new Error(body.error || "Ack API failed");
      setStatus("Ack recorded — refreshing report…");
      try {
        const regen = await fetch("/api/progress-report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (regen.ok) {
          await reloadDashboard({ silent: true, rebuild: true });
          setStatus("Observe-ack recorded · progress report refreshed");
          return;
        }
      } catch {
        /* fall through to dashboard reload */
      }
      await reloadDashboard({ silent: true, rebuild: true });
      setStatus("Observe-ack recorded — click Generate fresh report to refresh this checklist");
      return;
    }
    if (local.status !== 404 && local.status !== 405) {
      let detail = `HTTP ${local.status}`;
      try {
        const body = await local.json();
        detail = body.error || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
  } catch (err) {
    if (!(err instanceof TypeError) && String(err.message) !== "API_UNAVAILABLE") {
      if (!String(err.message).includes("Failed to fetch")) {
        setStatus(`Ack failed: ${err.message}`, true);
        button.disabled = false;
        return;
      }
    }
  }
  if (!window.DashboardBridge) {
    setStatus("Supabase bridge unavailable", true);
    button.disabled = false;
    return;
  }
  try {
    const bridgeReady = await window.DashboardBridge.init();
    if (!bridgeReady) throw new Error("BRIDGE_DISABLED");
    await window.DashboardBridge.submitCommand(
      "lifecycle-experiment-ack",
      payload,
      (msg) => setStatus(msg || "Queued via Supabase…")
    );
    setStatus("Ack dispatched — queueing progress-report refresh…");
    await window.DashboardBridge.submitCommand(
      "progress-report",
      { force: true },
      (msg) => setStatus(msg || "Queued progress-report…")
    );
    setStatus("Waiting for Pages to publish refreshed report…");
    const previousGeneratedAt =
      dashboardData && dashboardData.progress_report
        ? dashboardData.progress_report.generated_at
        : null;
    await waitForPublishedProgressReport(previousGeneratedAt, setStatus);
    await reloadDashboard({ silent: true, rebuild: true });
    setStatus("Observe-ack recorded · progress report refreshed via Supabase");
  } catch (err) {
    const msg = String(err.message || err);
    if (/timed out waiting for dashboard command/i.test(msg)) {
      setStatus(
        "Queued in Supabase — run Actions → Dashboard bridge worker → Run workflow, then Reload.",
        true
      );
    } else {
      setStatus(`Bridge ack failed: ${msg}`, true);
    }
    button.disabled = false;
  }
}

async function acknowledgeLifecycleExperimentFromCard(button) {
  const statusEl = button.parentElement
    ? button.parentElement.querySelector(".lifecycle-start-status")
    : null;
  const setStatus = (msg, isError) => {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("error", Boolean(isError));
  };
  let payload = {};
  try {
    payload = JSON.parse(button.getAttribute("data-lifecycle-ack") || "{}");
  } catch (err) {
    setStatus("Invalid ack payload", true);
    return;
  }
  if (!payload.experiment_id) {
    setStatus("Missing experiment id", true);
    return;
  }
  button.disabled = true;
  setStatus("Acknowledging…");
  try {
    const local = await fetch("/api/lifecycle-experiment-ack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (local.ok) {
      const body = await local.json();
      if (!body.ok) throw new Error(body.error || "Ack API failed");
      setStatus("Ack recorded — refreshing…");
      await reloadDashboard({ silent: true, rebuild: true });
      openLifecycleExperimentCard(payload.factor_id || "");
      setStatus("Observe-ack recorded");
      return;
    }
    if (local.status !== 404 && local.status !== 405) {
      let detail = `HTTP ${local.status}`;
      try {
        const body = await local.json();
        detail = body.error || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
  } catch (err) {
    if (!(err instanceof TypeError) && String(err.message) !== "API_UNAVAILABLE") {
      if (!String(err.message).includes("Failed to fetch")) {
        setStatus(`Ack failed: ${err.message}`, true);
        button.disabled = false;
        return;
      }
    }
  }
  if (!window.DashboardBridge) {
    setStatus("Supabase bridge unavailable", true);
    button.disabled = false;
    return;
  }
  try {
    const bridgeReady = await window.DashboardBridge.init();
    if (!bridgeReady) throw new Error("BRIDGE_DISABLED");
    await window.DashboardBridge.submitCommand(
      "lifecycle-experiment-ack",
      payload,
      (msg) => setStatus(msg || "Queued via Supabase…")
    );
    setStatus("Bridge finished — refreshing…");
    await reloadDashboard({ silent: true, rebuild: true });
    openLifecycleExperimentCard(payload.factor_id || "");
    setStatus("Observe-ack recorded via Supabase");
  } catch (err) {
    setStatus(`Bridge ack failed: ${err.message}`, true);
    button.disabled = false;
  }
}

async function startLifecycleExperimentFromCard(button) {
  const statusEl = button.parentElement
    ? button.parentElement.querySelector(".lifecycle-start-status")
    : null;
  const setStatus = (msg, isError) => {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("error", Boolean(isError));
  };
  const alreadyStartedMessage = (raw) => {
    const text = String(raw || "");
    const match = text.match(/already started[^(]*(\([^)]*\))?/i);
    if (!match && !/already_started/i.test(text)) return null;
    const when = match && match[1] ? ` ${match[1]}` : "";
    return `Already started${when} — shared across entry_dca_cadence / add_cadence / entry_kind_tag. No re-start needed.`;
  };
  let payload = {};
  try {
    payload = JSON.parse(button.getAttribute("data-lifecycle-start") || "{}");
  } catch (err) {
    setStatus("Invalid start payload", true);
    return;
  }
  if (!payload.experiment_id) {
    setStatus("Missing experiment id", true);
    return;
  }
  if (button.disabled || button.getAttribute("aria-disabled") === "true") {
    const reason = button.getAttribute("title") || "Start not available";
    const friendly = alreadyStartedMessage(reason) || reason;
    setStatus(friendly, !alreadyStartedMessage(reason));
    return;
  }
  button.disabled = true;
  button.setAttribute("aria-disabled", "true");
  setStatus("Starting execute…");
  const finishAlreadyStarted = async (detail) => {
    const friendly = alreadyStartedMessage(detail) || String(detail || "Already started");
    setStatus(friendly, false);
    button.textContent = "Started";
    button.title = friendly;
    try {
      await reloadDashboard({ silent: true, rebuild: true });
      openLifecycleExperimentCard(payload.factor_id || "");
    } catch {
      /* board refresh optional */
    }
  };
  try {
    const local = await fetch("/api/lifecycle-experiment-start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (local.ok) {
      const body = await local.json();
      if (!body.ok) throw new Error(body.error || "Start API failed");
      if (body.already_started) {
        await finishAlreadyStarted(body.message || body.started_at);
        return;
      }
      setStatus("Execute started — refreshing…");
      await reloadDashboard({ silent: true, rebuild: true });
      openLifecycleExperimentCard(payload.factor_id || "");
      setStatus("Graduated entry DCA execute started");
      button.textContent = "Started";
      return;
    }
    if (local.status !== 404 && local.status !== 405) {
      let detail = `HTTP ${local.status}`;
      try {
        const body = await local.json();
        detail = body.error || detail;
      } catch {
        /* ignore */
      }
      const friendly = alreadyStartedMessage(detail);
      if (friendly) {
        await finishAlreadyStarted(detail);
        return;
      }
      throw new Error(detail);
    }
  } catch (err) {
    if (!(err instanceof TypeError) && String(err.message) !== "API_UNAVAILABLE") {
      // fall through to bridge only on missing local API
      if (!String(err.message).includes("Failed to fetch")) {
        const friendly = alreadyStartedMessage(err.message);
        if (friendly) {
          await finishAlreadyStarted(err.message);
          return;
        }
        setStatus(`Start execute failed: ${err.message}`, true);
        button.disabled = false;
        button.setAttribute("aria-disabled", "false");
        return;
      }
    }
  }
  if (!window.DashboardBridge) {
    setStatus("Supabase bridge unavailable — open local dashboard or check Pages bridge config", true);
    button.disabled = false;
    button.setAttribute("aria-disabled", "false");
    return;
  }
  try {
    const bridgeReady = await window.DashboardBridge.init();
    if (!bridgeReady) throw new Error("BRIDGE_DISABLED");
    const result = await window.DashboardBridge.submitCommand(
      "lifecycle-experiment-start",
      payload,
      (msg) => setStatus(msg || "Queued via Supabase…")
    );
    const resultMsg = (result && (result.message || result.status_message)) || "";
    if (alreadyStartedMessage(resultMsg)) {
      await finishAlreadyStarted(resultMsg);
      return;
    }
    setStatus("Bridge finished — refreshing…");
    await reloadDashboard({ silent: true, rebuild: true });
    openLifecycleExperimentCard(payload.factor_id || "");
    setStatus("Graduated entry DCA execute started via Supabase");
    button.textContent = "Started";
  } catch (err) {
    const friendly = alreadyStartedMessage(err && err.message);
    if (friendly) {
      await finishAlreadyStarted(err.message);
      return;
    }
    const raw = String((err && err.message) || "unknown error");
    let hint = raw;
    if (raw === "BRIDGE_DISABLED") {
      hint = "Bridge disabled in this browser — check dashboard_bridge_config.js";
    } else if (/timed out/i.test(raw)) {
      hint = "Timed out waiting for GitHub worker — try Actions → lifecycle-experiment-start, or wait for the ~10m bridge cron";
    }
    setStatus(`Could not start execute: ${hint}`, true);
    button.disabled = false;
    button.setAttribute("aria-disabled", "false");
  }
}



function lifecycleExperimentChipButton(row) {
  const status = row.assessment_status || row.status;
  const title = row.aim || row.question || row.experiment || row.factor_id;
  const initiation = row.initiation || {};
  const recommend = String(row.assessment_status || "") === "recommend";
  const readyHint = recommend
    ? initiation.ready_to_initiate
      ? " · ready for next human step"
      : " · not ready to initiate"
    : "";
  return `<button type="button" class="lifecycle-exp-chip" data-lifecycle-experiment="${esc(
    row.factor_id || ""
  )}" title="${esc(title)}${esc(readyHint)}">${esc(row.factor_id || row.experiment || "experiment")} ${lifecycleStatusChip(
    status
  )}${
    recommend
      ? `<span class="lifecycle-exp-ready ${initiation.ready_to_initiate ? "ready" : "waiting"}">${
          initiation.ready_to_initiate ? "next step" : "waiting"
        }</span>`
      : ""
  }</button>`;
}

function lifecycleExperimentGroupKey(row) {
  return String(row.experiment || row.factor_id || "").trim() || String(row.factor_id || "experiment");
}

function lifecyclePickPrimaryExperimentRow(group) {
  const rows = Array.isArray(group) ? group : [];
  const score = (row) => {
    let n = 0;
    if (String(row.status || "") === "observing") n += 4;
    if (String(row.assessment_status || "") === "recommend") n += 2;
    if (row.initiation && row.initiation.ready_to_initiate) n += 1;
    return n;
  };
  return [...rows].sort((a, b) => score(b) - score(a) || String(a.factor_id || "").localeCompare(String(b.factor_id || "")))[0];
}

function lifecycleCollapsedExperimentChip(group) {
  const primary = lifecyclePickPrimaryExperimentRow(group);
  if (!primary) return "";
  if (group.length < 2) return lifecycleExperimentChipButton(primary);
  const siblings = group
    .map((row) => row.factor_id)
    .filter((id) => id && id !== primary.factor_id);
  const title = `${primary.experiment || primary.factor_id} · factors: ${group
    .map((row) => row.factor_id)
    .filter(Boolean)
    .join(", ")}`;
  const status = primary.assessment_status || primary.status;
  const initiation = primary.initiation || {};
  const recommend = String(primary.assessment_status || "") === "recommend";
  const readyHint = recommend
    ? initiation.ready_to_initiate
      ? " · ready for next human step"
      : " · not ready to initiate"
    : "";
  return `<button type="button" class="lifecycle-exp-chip lifecycle-exp-collapsed" data-lifecycle-experiment="${esc(
    primary.factor_id || ""
  )}" title="${esc(title)}${esc(readyHint)}">${esc(primary.experiment || primary.factor_id || "experiment")} ${lifecycleStatusChip(
    status
  )}<span class="lifecycle-exp-siblings" title="${esc(siblings.join(", "))}">×${group.length}</span>${
    recommend
      ? `<span class="lifecycle-exp-ready ${initiation.ready_to_initiate ? "ready" : "waiting"}">${
          initiation.ready_to_initiate ? "next step" : "waiting"
        }</span>`
      : ""
  }</button>`;
}

function lifecycleExperimentChips(experiments) {
  const rows = Array.isArray(experiments) ? experiments : [];
  // Collapse shared-experiment Start chips (e.g. entry_dca_overlay siblings) into one control.
  const groups = new Map();
  for (const row of rows) {
    const key = lifecycleExperimentGroupKey(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const chipParts = [];
  const leftoverPlanned = [];
  for (const group of groups.values()) {
    if (group.length > 1) {
      chipParts.push(lifecycleCollapsedExperimentChip(group));
      continue;
    }
    const row = group[0];
    if (String(row.status || "") === "observing") {
      chipParts.push(lifecycleExperimentChipButton(row));
    } else {
      leftoverPlanned.push(row);
    }
  }
  const planned = leftoverPlanned.length
    ? `<details class="lifecycle-planned"><summary class="small muted">${leftoverPlanned.length} planned / deferred</summary><ul class="list-plain small">${leftoverPlanned
        .map(
          (row) =>
            `<li>${lifecycleExperimentChipButton(row)}<div class="small muted">${esc(row.question || "")}${
              row.initiation && row.initiation.waiting_for
                ? ` — waiting: ${esc(row.initiation.waiting_for)}`
                : row.revisit_when
                  ? ` <span class="muted">(${esc(row.revisit_when)})</span>`
                  : ""
            }</div></li>`
        )
        .join("")}</ul></details>`
    : "";
  return `${chipParts.join("")}${planned}`;
}

function lifecyclePnlText(card) {
  if (!card) return "";
  if (card.realized_exit_pnl_pct != null && card.realized_exit_pnl_pct !== "") {
    return `exit P&L ${(Number(card.realized_exit_pnl_pct) * 100).toFixed(1)}%`;
  }
  if (card.unrealized_pnl_pct != null && card.unrealized_pnl_pct !== "") {
    return `P&L ${(Number(card.unrealized_pnl_pct) * 100).toFixed(1)}%`;
  }
  return "";
}

function lifecycleTickerCard(card) {
  const conv =
    card.conviction_score != null ? `${Math.round(Number(card.conviction_score) * 100)}%` : "";
  const pnl = lifecyclePnlText(card);
  const band = card.tenure_band ? ` tenure-${esc(card.tenure_band)}` : "";
  const days =
    card.days_in_column != null
      ? `<span class="lifecycle-tenure-days" title="${esc(card.tenure_basis || "stage clock")}">${esc(
          String(card.days_in_column)
        )}d</span>`
      : "";
  return `<button type="button" class="lifecycle-card${band}" data-lifecycle-ticker="${esc(
    card.ticker
  )}" title="Open assessment and price chart">
    <div class="lifecycle-card-head">
      <strong>${esc(card.ticker)}</strong>
      <span>${card.signal ? signalBadge(card.signal) : ""}${days}</span>
    </div>
    <div class="small muted">${esc(card.name || "")}</div>
    <div class="small">${esc(card.column_reason || card.lifecycle_phase || "")}${
      conv ? ` · conv ${esc(conv)}` : ""
    }${pnl ? ` · ${esc(pnl)}` : ""}</div>
  </button>`;
}

function findLifecycleTickerCard(ticker) {
  const board = (dashboardData || {}).lifecycle_board;
  if (!board || !ticker) return null;
  const market = findLifecycleMarket(board, lifecycleMarketId);
  const track = findLifecycleTrack(market, lifecycleTrackId);
  const cols = mergeLifecycleColumns(market, track);
  for (const col of board.columns || []) {
    const packed = cols[col.id] || {};
    const hit = (packed.shown || []).find((row) => row.ticker === ticker);
    if (hit) return { column: col, card: hit };
  }
  return null;
}

function findLifecycleReport(ticker) {
  const reports = (dashboardData || {}).reports || [];
  return reports.find((row) => row.ticker === ticker) || null;
}

function findResearchMemo(ticker) {
  const research = (dashboardData || {}).research || [];
  const key = String(ticker || "").toUpperCase();
  return (
    research.find((row) => String(row.ticker || "").toUpperCase() === key) || null
  );
}

function findChartOutcomeRow(ticker) {
  const review = (dashboardData || {}).chart_outcome_review || {};
  const rows = Array.isArray(review.rows) ? review.rows : [];
  const hit = rows.find((row) => row.ticker === ticker);
  if (hit) return hit;
  for (const list of [review.well_timed || [], review.weakest || []]) {
    const slim = list.find((row) => row.ticker === ticker);
    if (slim) return slim;
  }
  return null;
}

function lifecycleChartOutcomeHtml(row) {
  if (!row) return "";
  const bits = [
    row.return_since != null ? `return ${chartOutcomePct(row.return_since)}` : "",
    row.max_drawdown != null ? `max DD ${chartOutcomePct(row.max_drawdown)}` : "",
    row.target_hit ? "target hit" : "",
    row.stop_hit ? "stop hit" : "",
    row.days_to_target != null ? `${row.days_to_target}d to target` : "",
  ].filter(Boolean);
  return `
    <div class="lifecycle-ticker-outcome">
      <h4 class="small">Chart outcome since recommendation</h4>
      <p>${chartOutcomeBadge(row.outcome)}${
        bits.length ? ` <span class="small muted">${esc(bits.join(" · "))}</span>` : ""
      }</p>
    </div>`;
}

function renderLifecycleTickerCard(ticker) {
  const found = findLifecycleTickerCard(ticker);
  const card = (found && found.card) || { ticker };
  const report = findLifecycleReport(ticker) || {};
  const outcome = findChartOutcomeRow(ticker);
  const signal = report.signal || card.signal;
  const timing = report.timing_signal || card.timing_signal;
  const conviction =
    report.conviction_score != null ? report.conviction_score : card.conviction_score;
  const columnLabel = found && found.column ? found.column.label || found.column.id : "";
  const pnl = lifecyclePnlText(card);
  const tenure =
    card.days_in_column != null
      ? `${card.days_in_column}d in stage${card.tenure_band ? ` (${card.tenure_band})` : ""}`
      : "";
  const metaBits = [
    columnLabel,
    card.column_reason || card.lifecycle_phase || "",
    tenure,
    pnl,
    card.opened_at ? `opened ${(card.opened_at || "").slice(0, 10)}` : "",
    card.sold_at ? `sold ${(card.sold_at || "").slice(0, 10)}` : "",
  ].filter(Boolean);
  const models =
    report.models_passed != null
      ? `${report.models_passed}/${report.model_count || "?"} models · ${
          report.families_passed ?? "?"
        }/${report.family_count || 5} families`
      : "";
  const rsi = report.rsi_14 != null ? `RSI ${Math.round(report.rsi_14)}` : "";
  const stability = [report.stability_label, report.weeks_at_signal ? `${report.weeks_at_signal}w at signal` : ""]
    .filter(Boolean)
    .join(" · ");
  const hasReport = Boolean(report.ticker);
  const memo = findResearchMemo(ticker);
  const memoBtn = memo
    ? `<button type="button" class="btn btn-primary" data-lifecycle-open-memo="${esc(
        ticker
      )}">Read memo</button>`
    : "";
  return `
    <p class="small muted" style="margin-top:0">${esc(metaBits.join(" · ") || "Lifecycle board name")}</p>
    <div class="market-card-badges">
      ${signal ? signalBadge(signal) : ""}
      ${timing ? timingBadge(timing) : ""}
      ${iiTradabilityBadge(report)}
      ${conviction != null ? `<span class="badge badge-neutral">Conviction ${pct(conviction)}</span>` : ""}
    </div>
    ${
      report.research_verdict
        ? `<p class="small muted">Research: ${esc(String(report.research_verdict).replace(/_/g, " "))}${
            report.adjusted_signal && report.adjusted_signal !== report.signal
              ? ` → ${esc(String(report.adjusted_signal).replace(/_/g, " "))}`
              : ""
          }</p>`
        : ""
    }
    ${
      hasReport
        ? `<p class="small">${esc(report.action_note || "")}</p>
           <p class="small muted">${esc([models, rsi, stability].filter(Boolean).join(" · "))}</p>
           <p class="small"><strong>Trade plan:</strong><br>${tradePlanHtml(report)}</p>
           ${decisionPackHtml(report)}
           <p class="small">${esc(report.summary || "")}</p>`
        : `<p class="small muted">No live-screen report for this ticker in the published dashboard payload (common for sold / cooldown names).</p>`
    }
    ${
      memoBtn
        ? `<p class="lifecycle-memo-actions pick-actions">${memoBtn}<span class="small muted">Opens the published research memo dialog.</span></p>`
        : `<p class="small muted">No published research memo for this ticker.</p>`
    }
    ${lifecycleChartOutcomeHtml(outcome)}
    <h4 class="small">Price chart</h4>
    <p class="small muted" style="margin-top:0">
      Same Latest screen / Initial recommendation levels as the screener chart.
    </p>
    <div class="lifecycle-ticker-chart" data-lifecycle-chart-mount="${esc(ticker)}"></div>
  `;
}

function openLifecycleTickerCard(ticker) {
  const dialog = document.getElementById("lifecycle-ticker-dialog");
  const title = document.getElementById("lifecycle-ticker-title");
  const body = document.getElementById("lifecycle-ticker-body");
  if (!dialog || !title || !body || !ticker) return;
  const report = findLifecycleReport(ticker) || {};
  const found = findLifecycleTickerCard(ticker);
  const card = (found && found.card) || {};
  const name = report.name || card.name || ticker;
  title.textContent = `${name} (${ticker})`;
  body.innerHTML = renderLifecycleTickerCard(ticker);
  dialog.showModal();
  const mount = body.querySelector("[data-lifecycle-chart-mount]");
  if (mount && typeof mountPriceChart === "function") {
    void mountPriceChart(mount, report.ticker ? report : { ticker, name }, {
      book_cost: card.avg_cost,
      opened_at: card.opened_at,
      sold_at: card.sold_at,
      exit_price: card.exit_price,
      close_in: card.close_in,
    });
  }
}

function lifecycleTenureLegend(scale) {
  const bands = (scale && scale.bands) || [];
  if (!bands.length) return "";
  const items = bands
    .map(
      (band) =>
        `<span class="lifecycle-tenure-swatch tenure-${esc(band.id)}">${esc(band.label)}</span>`
    )
    .join("");
  return `<div class="lifecycle-tenure-legend" aria-label="Time in stage">
    <span class="small muted">Time in stage</span>
    ${items}
    <span class="small muted">${esc(scale.note || "")}</span>
  </div>`;
}

function mergeLifecycleColumns(market, track) {
  const occupied = new Set(track && track.occupied_tickers ? track.occupied_tickers : []);
  const removed = (track && track.screen_occupied) || {};
  const screen = (market && market.screen_columns) || {};
  const position = (track && (track.position_columns || track.columns)) || {};
  const screenIds = ["not_buy_tier", "not_now", "near_buy"];
  const positionIds = ["just_bought", "growth", "near_sell", "just_sold", "post_sale"];
  const merged = {};
  screenIds.forEach((id) => {
    const packed = screen[id] || {};
    const shown = (packed.shown || []).filter((card) => !occupied.has(card.ticker));
    const count = Math.max(0, (packed.count || 0) - (removed[id] || 0));
    merged[id] = { count, shown, truncated: Math.max(0, count - shown.length) };
  });
  positionIds.forEach((id) => {
    const packed = position[id] || {};
    merged[id] = {
      count: packed.count || 0,
      shown: packed.shown || [],
      truncated: packed.truncated || 0,
    };
  });
  return merged;
}

function findLifecycleMarket(board, marketId) {
  const markets = (board && board.markets) || [];
  return markets.find((row) => row.market_id === marketId) || markets[0] || null;
}

function findLifecycleTrack(market, trackId) {
  const tracks = (market && market.tracks) || [];
  if (trackId) {
    const hit = tracks.find((row) => row.track_id === trackId);
    if (hit) return hit;
  }
  return tracks.find((row) => row.is_default) || tracks[0] || null;
}

function sealedLifecyclePct(chip) {
  if (!chip || chip.return_pct == null || chip.return_pct === "") return "—";
  const n = Number(chip.return_pct) * 100;
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

function sealedLifecycleChipTitle(chip) {
  if (chip.return_basis === "open_mark") {
    return "Open mark stored on the observe row. Not the sealed cohort median.";
  }
  if (chip.return_basis === "open_unmarked") {
    return "Open episode. No stored mark. Not the sealed cohort median.";
  }
  if (chip.return_basis === "fair_cost_episode") {
    return "Episode fair-cost return. Not the sealed cohort median.";
  }
  return "No episode return stored.";
}

function sealedLifecycleDateLabel(raw) {
  if (!raw) return "—";
  const text = String(raw);
  return text.length >= 10 ? text.slice(0, 10) : text;
}

function sealedLifecycleHoldDays(chip) {
  if (!chip || !chip.entry_run_at || !chip.exit_run_at) return null;
  const entry = Date.parse(chip.entry_run_at);
  const exit = Date.parse(chip.exit_run_at);
  if (!Number.isFinite(entry) || !Number.isFinite(exit) || exit < entry) return null;
  return Math.round((exit - entry) / 86400000);
}

function sealedLifecycleReturnLabel(chip) {
  if (chip.return_basis === "open_mark") return "Open mark";
  if (chip.return_basis === "fair_cost_episode") return "Fair-cost episode";
  if (chip.return_basis === "open_unmarked") return "No stored mark";
  return "Return";
}

function sealedLifecycleEpisodeKey(chip) {
  return [
    chip.ticker || "",
    chip.entry_run_at || "",
    chip.exit_run_at || "",
    chip.phase || "",
  ].join("|");
}

function sealedLifecycleClamp01(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function sealedLifecycleMixRgb(a, b, t) {
  const u = sealedLifecycleClamp01(t);
  return [
    Math.round(a[0] + (b[0] - a[0]) * u),
    Math.round(a[1] + (b[1] - a[1]) * u),
    Math.round(a[2] + (b[2] - a[2]) * u),
  ];
}

function sealedLifecycleRgbCss(rgb, alpha) {
  if (alpha == null) return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
}

/** Fill = P&amp;L size. Neutral when open with no stored mark. Caps at ±15%. */
function sealedLifecycleHeatFill(chip) {
  const neutral = [232, 234, 238];
  if (chip.return_pct == null || chip.return_pct === "" || chip.return_basis === "open_unmarked") {
    return sealedLifecycleRgbCss(neutral, 0.95);
  }
  const ret = Number(chip.return_pct);
  if (!Number.isFinite(ret)) return sealedLifecycleRgbCss(neutral, 0.95);
  const mag = sealedLifecycleClamp01(Math.abs(ret) / 0.15);
  if (ret >= 0) {
    const rgb = sealedLifecycleMixRgb(neutral, [46, 160, 90], Math.max(0.25, mag));
    return sealedLifecycleRgbCss(rgb, 0.92);
  }
  const rgb = sealedLifecycleMixRgb(neutral, [179, 58, 58], Math.max(0.25, mag));
  return sealedLifecycleRgbCss(rgb, 0.92);
}

/** Border = time in phase. Short → cool green; long → warm red. Soft-cap 60d. */
function sealedLifecycleHeatBorder(chip) {
  const days = Number(chip.days_in_phase);
  const t = sealedLifecycleClamp01((Number.isFinite(days) ? days : 0) / 60);
  const rgb = sealedLifecycleMixRgb([46, 160, 90], [179, 58, 58], t);
  return sealedLifecycleRgbCss(rgb, 0.95);
}

function sealedLifecycleTinyPct(chip) {
  if (chip.return_pct == null || chip.return_pct === "" || chip.return_basis === "open_unmarked") {
    return "";
  }
  const n = Number(chip.return_pct) * 100;
  if (!Number.isFinite(n)) return "";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(0)}%`;
}

function sealedLifecycleOverlays(chip) {
  return {
    opened_at: chip.entry_run_at || null,
    sold_at: chip.exit_run_at || null,
    close_in: chip.close_in || null,
  };
}

function sealedLifecycleChip(chip) {
  const ticker = String(chip.ticker || "");
  const pct = sealedLifecyclePct(chip);
  const pctClass =
    chip.return_pct == null
      ? ""
      : Number(chip.return_pct) > 0
        ? " text-positive"
        : Number(chip.return_pct) < 0
          ? " text-negative"
          : "";
  const openClass = chip.return_basis === "open_mark" ? " is-open-mark" : "";
  const days = chip.days_in_phase == null ? "—" : `${chip.days_in_phase}d`;
  const key = sealedLifecycleEpisodeKey(chip);
  const selected = sealedLifecycleDetailKey === key;
  return `<div class="sealed-life-row${selected ? " is-expanded" : ""}">
    <button type="button" class="sealed-life-chip${openClass}" data-sealed-ticker="${esc(
      ticker
    )}" data-sealed-key="${esc(key)}" aria-pressed="${selected ? "true" : "false"}" title="${esc(
      `${sealedLifecycleChipTitle(chip)} Click for assessment-window detail card.`
    )}">
      <span class="sealed-life-ticker">${esc(ticker)}</span>
      <span class="sealed-life-days">${esc(days)}</span>
      <span class="sealed-life-pct${pctClass}">${esc(pct)}</span>
    </button>
  </div>`;
}

function sealedLifecycleHeatCell(chip) {
  const ticker = String(chip.ticker || "");
  const key = sealedLifecycleEpisodeKey(chip);
  const selected = sealedLifecycleDetailKey === key;
  const tiny = sealedLifecycleTinyPct(chip);
  const fill = sealedLifecycleHeatFill(chip);
  const border = sealedLifecycleHeatBorder(chip);
  const days = chip.days_in_phase == null ? "—" : `${chip.days_in_phase}d`;
  const closeIn = chip.close_in ? esc(JSON.stringify(chip.close_in)) : "";
  const label = tiny ? `${ticker} ${tiny}` : ticker;
  return `<button type="button" class="sealed-heat-cell${
    selected ? " is-selected" : ""
  }" style="--sealed-heat-fill:${fill};--sealed-heat-border:${border}" data-sealed-heat-key="${esc(
    key
  )}" data-sealed-ticker="${esc(ticker)}" data-sealed-entry="${esc(
    chip.entry_run_at || ""
  )}" data-sealed-exit="${esc(chip.exit_run_at || "")}" data-sealed-close-in="${closeIn}" data-return-basis="${esc(
    chip.return_basis || ""
  )}" title="${esc(
    `${ticker} · ${days} in phase · ${sealedLifecyclePct(chip)} · ${sealedLifecycleChipTitle(chip)}`
  )}">
    <span class="sealed-heat-ticker">${esc(label)}</span>
  </button>`;
}

function findSealedLifecycleChip(model, key) {
  if (!model || !key) return null;
  const columns = model.columns || {};
  for (const phase of ["just_bought", "holding", "just_sold", "post_sale"]) {
    const chips = (columns[phase] && columns[phase].chips) || [];
    for (const chip of chips) {
      if (sealedLifecycleEpisodeKey(chip) === key) return chip;
    }
  }
  return null;
}

function sealedLifecycleCloseInCaption(chip) {
  const window = chip && chip.close_in;
  if (!window) return "Assessment window not stored on this episode.";
  const before = window.days_before;
  const after = window.days_after;
  const label =
    before != null && after != null && Number(before) === Number(after)
      ? `Sleeve ± ${before}d`
      : "Sleeve window";
  const start = sealedLifecycleDateLabel(window.start);
  const end = window.end ? sealedLifecycleDateLabel(window.end) : "latest (open — no post-sale end)";
  return `${label}: ${start} → ${end}. Same close-in clip as the live lifecycle board (#1129).`;
}

function renderSealedLifecycleDetail(model) {
  const chip = findSealedLifecycleChip(model, sealedLifecycleDetailKey);
  if (!chip) {
    return `<div class="sealed-life-detail empty"><p class="small muted">Click a heat cell or chip list line to open one episode detail card with the assessment-window price chart (buy–sell ± just-bought / just-sold days). The board stays a scan — cards are not drawn on every name.</p></div>`;
  }
  const ticker = String(chip.ticker || "");
  const holdDays = sealedLifecycleHoldDays(chip);
  const pct = sealedLifecyclePct(chip);
  const pctClass =
    chip.return_pct == null
      ? ""
      : Number(chip.return_pct) > 0
        ? " text-positive"
        : Number(chip.return_pct) < 0
          ? " text-negative"
          : "";
  const phaseDays = chip.days_in_phase == null ? "—" : `${chip.days_in_phase}d`;
  const phaseLabel = String(chip.phase || "").replace(/_/g, " ");
  return `<div class="sealed-life-detail" data-sealed-detail="1">
    <article class="sealed-life-detail-card" data-sealed-detail-card="1">
      <header class="sealed-life-detail-head">
        <div>
          <h4 class="sealed-life-detail-title">${esc(ticker)}</h4>
          <p class="small muted" style="margin:0.15rem 0 0">${esc(phaseLabel)} · ${esc(
            chip.status || "—"
          )} · ${esc(phaseDays)} in phase</p>
        </div>
        <button type="button" class="btn" data-sealed-detail-close="1">Close</button>
      </header>
      <dl class="sealed-life-card-grid">
        <div><dt>Entry</dt><dd>${esc(sealedLifecycleDateLabel(chip.entry_run_at))}</dd></div>
        <div><dt>Exit</dt><dd>${esc(sealedLifecycleDateLabel(chip.exit_run_at))}</dd></div>
        <div><dt>${esc(sealedLifecycleReturnLabel(chip))}</dt><dd class="${pctClass}">${esc(pct)}</dd></div>
        <div><dt>Hold days</dt><dd>${esc(holdDays == null ? "—" : `${holdDays}d`)}</dd></div>
      </dl>
      <p class="small muted sealed-life-card-note">${esc(sealedLifecycleCloseInCaption(chip))}</p>
      <h5 class="small sealed-life-chart-heading">Assessment-window price</h5>
      <div class="sealed-life-detail-chart" data-sealed-chart-mount="${esc(ticker)}"></div>
    </article>
  </div>`;
}

/** Mount Sleeve ±14d chart from in-memory cache or published data/charts — no heavy live fetch. */
async function mountSealedLifecycleDetailChart(chip) {
  const mount = document.querySelector("[data-sealed-chart-mount]");
  if (!mount || !chip) return;
  const ticker = String(chip.ticker || "");
  const overlays = sealedLifecycleOverlays(chip);
  const report = { ticker };
  const paint = (payload) => {
    if (typeof showPriceChart !== "function") {
      mount.innerHTML = `<p class="muted">Chart renderer unavailable.</p>`;
      return;
    }
    showPriceChart(mount, payload, report, overlays, "close_in");
  };
  if (typeof cachedPriceChart === "function") {
    const cached = cachedPriceChart(ticker);
    if (cached) {
      paint(cached);
      return;
    }
  }
  const path =
    typeof chartPathForReport === "function" ? chartPathForReport(report) : null;
  if (!path) {
    mount.innerHTML = `<p class="muted">No published chart path for ${esc(
      ticker
    )}.</p><p class="small muted">Sealed pages only reuse the dashboard’s published <code>data/charts/</code> series (same as the live lifecycle board). They do not pull a new price history.</p>`;
    return;
  }
  mount.innerHTML = `<p class="muted">Loading assessment window…</p>`;
  try {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (typeof rememberPriceChart === "function") rememberPriceChart(ticker, payload);
    paint(payload);
  } catch (err) {
    mount.innerHTML = `<p class="muted">No published price series for ${esc(
      ticker
    )} (${esc(err.message)}).</p><p class="small muted">Fail closed — sealed pages do not invent or remotely fetch a new series. Charts appear when <code>${esc(
      path
    )}</code> is already on the dashboard.</p>`;
  }
}

function afterRenderSealedLifecycle(data) {
  const board = (data && data.sealed_lifecycle) || {};
  const models = Array.isArray(board.models) ? board.models : [];
  const model =
    models.find((row) => row.model_id === sealedLifecycleModelId) || models[0] || null;
  const chip = findSealedLifecycleChip(model, sealedLifecycleDetailKey);
  if (!chip) return;
  const detail = document.querySelector("[data-sealed-detail-card]");
  if (detail && typeof detail.scrollIntoView === "function") {
    detail.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  void mountSealedLifecycleDetailChart(chip);
}

function normalizeSealedLifecycleSortMode(mode) {
  return SEALED_LIFECYCLE_SORT_MODES.includes(mode) ? mode : "name";
}

/** True when the chip has a numeric fair-cost / open-mark percent to sort on. */
function sealedLifecycleHasSortablePnl(chip) {
  if (!chip || chip.return_pct == null || chip.return_pct === "") return false;
  if (chip.return_basis === "open_unmarked") return false;
  return Number.isFinite(Number(chip.return_pct));
}

/**
 * Sort chips inside one phase. Same key applied to every column.
 * name: A→Z. pnl: high→low with unmarked/missing last. time: short→long days in phase.
 */
function sortSealedLifecycleChips(chips, mode) {
  const rows = Array.isArray(chips) ? chips.slice() : [];
  const sortMode = normalizeSealedLifecycleSortMode(mode);
  rows.sort((a, b) => {
    const tickerCmp = String(a.ticker || "").localeCompare(String(b.ticker || ""));
    if (sortMode === "name") return tickerCmp;
    if (sortMode === "pnl") {
      const aOk = sealedLifecycleHasSortablePnl(a);
      const bOk = sealedLifecycleHasSortablePnl(b);
      if (aOk !== bOk) return aOk ? -1 : 1;
      if (aOk && bOk) {
        const diff = Number(b.return_pct) - Number(a.return_pct);
        if (diff !== 0) return diff;
      }
      return tickerCmp;
    }
    // time
    const aDays = Number(a.days_in_phase);
    const bDays = Number(b.days_in_phase);
    const aNum = Number.isFinite(aDays) ? aDays : Number.POSITIVE_INFINITY;
    const bNum = Number.isFinite(bDays) ? bDays : Number.POSITIVE_INFINITY;
    if (aNum !== bNum) return aNum - bNum;
    return tickerCmp;
  });
  return rows;
}

function renderSealedLifecycleHeatBoard(model, phases) {
  const columns = model.columns || {};
  const sortMode = normalizeSealedLifecycleSortMode(sealedLifecycleSortMode);
  return phases
    .map(([id, label]) => {
      const packed = columns[id] || { count: 0, chips: [], label };
      const ordered = sortSealedLifecycleChips(packed.chips || [], sortMode);
      const cells = ordered.map(sealedLifecycleHeatCell).join("");
      return `<section class="sealed-life-col sealed-heat-col" data-sealed-phase="${esc(id)}">
        <header class="lifecycle-col-header">
          <h3>${esc(packed.label || label)}</h3>
          <span class="lifecycle-count">${packed.count ?? ordered.length}</span>
        </header>
        <div class="sealed-heat-grid">${cells || '<p class="small muted">None</p>'}</div>
      </section>`;
    })
    .join("");
}

function renderSealedLifecycleListBoard(model, phases) {
  const columns = model.columns || {};
  const sortMode = normalizeSealedLifecycleSortMode(sealedLifecycleSortMode);
  return phases
    .map(([id, label]) => {
      const packed = columns[id] || { count: 0, chips: [], label };
      const ordered = sortSealedLifecycleChips(packed.chips || [], sortMode);
      const chips = ordered.map(sealedLifecycleChip).join("");
      return `<section class="sealed-life-col" data-sealed-phase="${esc(id)}">
        <header class="lifecycle-col-header">
          <h3>${esc(packed.label || label)}</h3>
          <span class="lifecycle-count">${packed.count ?? ordered.length}</span>
        </header>
        <div class="sealed-life-chips">${chips || '<p class="small muted">None</p>'}</div>
      </section>`;
    })
    .join("");
}

function renderSealedLifecycle(data) {
  const board = (data && data.sealed_lifecycle) || {};
  const models = Array.isArray(board.models) ? board.models : [];
  sealedLifecycleModelId = normalizeSealedLifecycleModel(sealedLifecycleModelId);
  if (sealedLifecycleViewMode !== "list" && sealedLifecycleViewMode !== "heatmap") {
    sealedLifecycleViewMode = "heatmap";
  }
  sealedLifecycleSortMode = normalizeSealedLifecycleSortMode(sealedLifecycleSortMode);
  const model =
    models.find((row) => row.model_id === sealedLifecycleModelId) || models[0] || null;
  if (model) sealedLifecycleModelId = model.model_id;
  const pills = models
    .map((row) => {
      const active = model && row.model_id === model.model_id ? " active" : "";
      const count = row.chip_count != null ? row.chip_count : "";
      return `<button type="button" class="tab${active}" data-sealed-model="${esc(
        row.model_id
      )}">${esc(row.label || row.model_id)} <span class="small muted">${esc(
        String(count)
      )}</span></button>`;
    })
    .join("");
  if (!model) {
    return `${renderLifecycleSubnav()}
      <div class="empty-state">Sealed lifecycle pages are not published yet. They refresh with the N200, N201, N206, and N210 observe stores (<code>data/sealed_lifecycle.json</code>).</div>`;
  }
  const phases = [
    ["just_bought", "Just bought"],
    ["holding", "Holding"],
    ["just_sold", "Just sold"],
    ["post_sale", "Post sale"],
  ];
  const heatActive = sealedLifecycleViewMode === "heatmap";
  const boardHtml = heatActive
    ? renderSealedLifecycleHeatBoard(model, phases)
    : renderSealedLifecycleListBoard(model, phases);
  const medianNumber = Number(model.cohort_median);
  const median = Number.isFinite(medianNumber)
    ? `${medianNumber > 0 ? "+" : ""}${(medianNumber * 100).toFixed(2)}%`
    : "—";
  const viewToggle = `<div class="sealed-life-view-toggle" role="group" aria-label="Sealed lifecycle view">
      <button type="button" class="tab${heatActive ? " active" : ""}" data-sealed-view="heatmap">Heat map</button>
      <button type="button" class="tab${!heatActive ? " active" : ""}" data-sealed-view="list">Chip list</button>
    </div>`;
  const sortToggle = `<div class="sealed-life-sort-toggle" role="group" aria-label="Sort sealed episodes in each phase">
      ${SEALED_LIFECYCLE_SORT_MODES.map(
        (mode) =>
          `<button type="button" class="tab${
            sealedLifecycleSortMode === mode ? " active" : ""
          }" data-sealed-sort="${esc(mode)}">${esc(SEALED_LIFECYCLE_SORT_LABELS[mode])}</button>`
      ).join("")}
    </div>`;
  const blurb = heatActive
    ? `Zoomed-out heat map for high-volume sealed books. Fill = fair-cost episode % (open unmarked stays neutral). Border = days in this phase (cool/short → warm/long). Click one cell for a detail card with the Sleeve ±14d assessment-window chart (same close-in clip as the live board). Chip list remains one click away — cards are not drawn on every name.`
    : `One-line chip scan: ticker, days in this column, episode percent. Click a line for the same assessment-window detail card. Prefer the heat map when a phase is dense.`;
  const sortHint =
    sealedLifecycleSortMode === "pnl"
      ? "Sort: % P&L high→low in each phase; unmarked opens last."
      : sealedLifecycleSortMode === "time"
        ? "Sort: days in phase short→long in each phase."
        : "Sort: ticker name A→Z in each phase.";
  return `${renderLifecycleSubnav()}
    <section class="card sealed-life-section">
      <div class="market-status-header">
        <div>
          <h3>${esc(model.label || "")} ${esc(model.title || "")}</h3>
          <p class="small muted" style="margin:0.25rem 0 0">
            <code>${esc(model.registration_id || "")}</code>
            · observe only · influences_live false
            · as of ${esc((model.as_of || model.generated_at || "").slice(0, 10) || "—")}
          </p>
        </div>
        <div class="sealed-life-toolbar">
          ${viewToggle}
          ${sortToggle}
        </div>
      </div>
      <div class="tabs sealed-life-models">${pills}</div>
      ${renderSealedLifecycleCollation(data, model.model_id)}
      <p class="small muted">Episode board — chip % is fair-cost episode return (or stored open mark), not the cohort median ${esc(
        median
      )} above. ${blurb}</p>
      <p class="small muted sealed-heat-legend">Legend: fill profit←neutral→loss · border short/cool←→long/warm · caps ±15% fill, 60d border. ${esc(
        sortHint
      )}</p>
      <div class="sealed-life-board${heatActive ? " is-heatmap" : " is-list"}">${boardHtml}</div>
      ${renderSealedLifecycleDetail(model)}
    </section>`;
}

let postSaleReviewSort = "interesting";
let postSaleReviewExpandedId = null;
/** Session + localStorage overlay: clears survive iPad refresh until labels git. */
const PENDING_POST_SALE_STORAGE_KEY = "ftse.pendingPostSaleActions.v1";
/**
 * Max age for optimistic clears without durable labels catch-up.
 * Longer windows left Q8B gate remaining pointing at cards the owner could not
 * see (pending hid them; bridge/GHA never wrote Accept/Comment/Duplicate).
 */
const PENDING_POST_SALE_MAX_AGE_MS = 2 * 60 * 60 * 1000;
const pendingPostSaleActions = Object.create(null);
/** Identity-only keys for bridge payload (avoid oversized repository_dispatch). */
const POST_SALE_BRIDGE_SNAPSHOT_KEYS = [
  "book_id",
  "book_tag",
  "model_id",
  "ticker",
  "name",
  "entry_at",
  "exit_at",
  "hold_days",
  "exit_kind",
  "return_pct",
  "basis_label",
  "framing",
  "registration_id",
  "population",
  "buy_decision",
  "sell_decision",
  "buy_reason",
  "sell_reason",
  "decision_reasons_join_ok",
  "exit_reason",
  "entry_reason",
  "entry_detail",
  "episode_key",
  "parent_review_id",
  "avg_cost",
  "exit_price",
  "opened_at",
  "sold_at",
];

function loadPendingPostSaleActionsFromStorage() {
  try {
    const raw = localStorage.getItem(PENDING_POST_SALE_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return;
    const cutoff = Date.now() - PENDING_POST_SALE_MAX_AGE_MS;
    for (const [rid, row] of Object.entries(parsed)) {
      if (!rid || !row || typeof row !== "object") continue;
      const at = Number(row.at) || 0;
      if (!at || at < cutoff) continue;
      pendingPostSaleActions[rid] = row;
    }
  } catch {
    /* ignore quota / private mode */
  }
}

/** Drop optimistic clears that never landed in labels (resurfaces stuck cards). */
function pruneStalePendingPostSaleActions() {
  const cutoff = Date.now() - PENDING_POST_SALE_MAX_AGE_MS;
  let changed = false;
  for (const rid of Object.keys(pendingPostSaleActions)) {
    const row = pendingPostSaleActions[rid];
    const at = row && typeof row === "object" ? Number(row.at) || 0 : 0;
    if (!at || at < cutoff) {
      delete pendingPostSaleActions[rid];
      changed = true;
    }
  }
  if (changed) persistPendingPostSaleActions();
}

function persistPendingPostSaleActions() {
  try {
    localStorage.setItem(
      PENDING_POST_SALE_STORAGE_KEY,
      JSON.stringify(pendingPostSaleActions)
    );
  } catch {
    /* ignore quota / private mode */
  }
}

loadPendingPostSaleActionsFromStorage();

function slimPostSaleBridgeSnapshot(item) {
  const src = item && typeof item === "object" ? item : {};
  const out = {};
  for (const key of POST_SALE_BRIDGE_SNAPSHOT_KEYS) {
    if (src[key] != null && src[key] !== "") out[key] = src[key];
  }
  return out;
}

function rememberPendingPostSaleAction(reviewId, decision, meta) {
  const rid = String(reviewId || "").trim();
  if (!rid) return;
  const info = meta && typeof meta === "object" ? meta : {};
  const slim = slimPostSaleBridgeSnapshot(info.item || info.snapshot || {});
  pendingPostSaleActions[rid] = {
    decision: String(decision || "accept"),
    at: Date.now(),
    text: String(info.text || "").trim(),
    snapshot: slim,
    episode_key: String(slim.episode_key || info.episode_key || "").trim(),
  };
  persistPendingPostSaleActions();
}

function postSaleActionedEpisodeKeys(labels) {
  const out = new Set();
  const store = labels && typeof labels === "object" ? labels : {};
  for (const ev of Array.isArray(store.events) ? store.events : []) {
    if (!ev || typeof ev !== "object") continue;
    const kind = String(ev.kind || "").toLowerCase();
    if (kind !== "accept" && kind !== "comment" && kind !== "duplicate") continue;
    const snap = ev.snapshot && typeof ev.snapshot === "object" ? ev.snapshot : {};
    const ep = String(snap.episode_key || "").trim();
    if (ep) {
      out.add(ep);
      continue;
    }
    const book = String(snap.book_id || snap.book_tag || "").trim();
    const ticker = String(snap.ticker || "").trim().toUpperCase();
    const entryDay = String(snap.entry_at || "").trim().slice(0, 10);
    const exitDay = String(snap.exit_at || "").trim().slice(0, 10);
    if (book && ticker && entryDay && exitDay) {
      out.add([book, ticker, entryDay, exitDay].join("|"));
    }
  }
  for (const row of Object.values(pendingPostSaleActions)) {
    if (!row || typeof row !== "object") continue;
    const ep = String(row.episode_key || (row.snapshot && row.snapshot.episode_key) || "").trim();
    if (ep) out.add(ep);
  }
  return out;
}

function prunePendingPostSaleActions(data) {
  const labels = (data && data.post_sale_review_labels) || {};
  const actioned = new Set(
    (Array.isArray(labels.actioned_review_ids) ? labels.actioned_review_ids : [])
      .map((id) => String(id || "").trim())
      .filter(Boolean)
  );
  for (const ev of Array.isArray(labels.events) ? labels.events : []) {
    if (!ev || typeof ev !== "object") continue;
    const kind = String(ev.kind || "").toLowerCase();
    if (kind === "accept" || kind === "comment" || kind === "duplicate") {
      const rid = String(ev.review_id || "").trim();
      if (rid) actioned.add(rid);
    }
  }
  let changed = false;
  for (const rid of Object.keys(pendingPostSaleActions)) {
    if (actioned.has(rid)) {
      delete pendingPostSaleActions[rid];
      changed = true;
    }
  }
  if (changed) persistPendingPostSaleActions();
}

function postSaleReviewCardUsable(item) {
  if (!item || typeof item !== "object") return false;
  const ticker = String(item.ticker || "").trim();
  if (!ticker || ticker === "?") return false;
  const book = String(item.book_tag || item.book_id || "").trim();
  if (!book || book === "?") return false;
  return true;
}

function buildOptimisticPostSaleReplyCard(parentId, pending) {
  const slim =
    pending && pending.snapshot && typeof pending.snapshot === "object"
      ? pending.snapshot
      : {};
  if (!postSaleReviewCardUsable(slim)) return null;
  const text = String((pending && pending.text) || "").trim();
  if (!text) return null;
  const replyId = `pending-reply:${parentId}`;
  return {
    ...slim,
    review_id: replyId,
    parent_review_id: parentId,
    tag: "reply",
    owner_comment: text,
    reply_text: "Factory reply pending — waiting for git commit…",
    dialogue: [
      { kind: "comment", text, source: "owner" },
      {
        kind: "reply",
        text: "Factory reply pending — waiting for git commit…",
        source: "pending",
      },
    ],
    influences_live: false,
    observe_only: true,
    pending_optimistic: true,
  };
}

function syncPostSaleQueueOverlay(data) {
  if (!data || !data.post_sale_review_queue) return;
  pruneStalePendingPostSaleActions();
  prunePendingPostSaleActions(data);
  const queue = data.post_sale_review_queue;
  if (!Array.isArray(queue.active)) return;
  const labels = data.post_sale_review_labels || {};
  const actioned = new Set(
    (Array.isArray(labels.actioned_review_ids) ? labels.actioned_review_ids : [])
      .map((id) => String(id || "").trim())
      .filter(Boolean)
  );
  const pending = new Set(Object.keys(pendingPostSaleActions));
  const clearedEpisodes = postSaleActionedEpisodeKeys(labels);
  // Active = genuine uncommented exits only. Drop reply:* cards (legacy publish
  // or optimistic stubs) — factory replies belong in durable history.
  queue.active = queue.active.filter((row) => {
    if (!row || typeof row !== "object") return false;
    if (String(row.tag || "").toLowerCase() === "reply") return false;
    if (String(row.review_id || "").startsWith("pending-reply:")) return false;
    if (String(row.review_id || "").startsWith("reply:")) return false;
    const rid = String(row.review_id || "").trim();
    if (!rid) return false;
    if (pending.has(rid) || actioned.has(rid)) return false;
    const ep = String(row.episode_key || "").trim();
    if (ep && clearedEpisodes.has(ep)) return false;
    return postSaleReviewCardUsable(row);
  });
  queue.active_count = queue.active.length;
  queue.new_count = queue.active.length;
  queue.reply_count = 0;
  const byBook = {};
  for (const row of queue.active) {
    const key = String(row.book_tag || row.book_id || "?");
    byBook[key] = (byBook[key] || 0) + 1;
  }
  queue.by_book = byBook;
}

function postSalePatternMarks(item) {
  const annotations = (item && item.chart_annotations) || {};
  return Array.isArray(annotations.marks) ? annotations.marks : [];
}

/** N229 — in-progress owner drawings keyed by reviewId → chartKey → elements. */
const humanChartDrafts = Object.create(null);

function humanDraftKey(reviewId) {
  return String(reviewId || "").trim();
}

function getHumanChartDraft(reviewId, chartKey) {
  const rid = humanDraftKey(reviewId);
  if (!rid) return [];
  const byChart = humanChartDrafts[rid];
  if (!byChart || typeof byChart !== "object") return [];
  const rows = byChart[String(chartKey || "")];
  return Array.isArray(rows) ? rows.slice() : [];
}

function setHumanChartDraft(reviewId, chartKey, elements) {
  const rid = humanDraftKey(reviewId);
  if (!rid) return;
  if (!humanChartDrafts[rid]) humanChartDrafts[rid] = Object.create(null);
  humanChartDrafts[rid][String(chartKey || "")] = Array.isArray(elements)
    ? elements.slice()
    : [];
}

function clearHumanChartDrafts(reviewId) {
  const rid = humanDraftKey(reviewId);
  if (rid) delete humanChartDrafts[rid];
}

function collectHumanGeometryForComment(reviewId) {
  const rid = humanDraftKey(reviewId);
  const byChart = humanChartDrafts[rid];
  if (!byChart) return [];
  const out = [];
  const drawnAt = new Date().toISOString();
  for (const [chart, elements] of Object.entries(byChart)) {
    if (!Array.isArray(elements) || !elements.length) continue;
    out.push({
      geometry_id:
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `geo-${Date.now()}-${chart}`,
      review_id: rid,
      chart,
      drawn_at: drawnAt,
      post_hoc: true,
      elements: elements.slice(),
      readable: true,
      influences_live: false,
      source: "owner",
    });
  }
  return out;
}

/** Chart mount nodes for a review (post-sale dual-horizon + entry-blind PIT). */
function chartBodiesForReview(reviewId) {
  const rid = String(reviewId || "").trim();
  if (!rid) return [];
  const escId =
    typeof CSS !== "undefined" && CSS.escape ? CSS.escape(rid) : rid.replace(/"/g, '\\"');
  return [
    ...document.querySelectorAll(`[data-psr-chart][data-psr-id="${escId}"]`),
    ...document.querySelectorAll(`[data-ebr-chart][data-ebr-id="${escId}"]`),
  ];
}

/**
 * Auto-seal in-progress Parallel edits into humanChartDrafts before Comment.
 * Drawing-before-Comment is the intended flow — unfinished overlays must not be dropped.
 */
function sealOpenHumanDrawEdits(reviewId) {
  if (typeof commitParallelEdit !== "function") return;
  for (const body of chartBodiesForReview(reviewId)) {
    if (body && body._humanDraw && body._humanDraw.parallelEdit) {
      commitParallelEdit(body, { quiet: true });
    }
  }
}

/**
 * Comment payload builder: seal open edits, then collect non-empty drafts.
 * Never gated on an Attach checkbox — Comment must not drop in-memory drawings.
 */
function geometryPayloadForComment(reviewId) {
  sealOpenHumanDrawEdits(reviewId);
  return collectHumanGeometryForComment(reviewId);
}

function humanDraftPatternMarks(reviewId) {
  const geometries = collectHumanGeometryForComment(reviewId);
  if (typeof humanGeometryElementsToMarks === "function") {
    return humanGeometryElementsToMarks(geometries, null);
  }
  return [];
}

function renderHumanDrawToolbar(reviewId, chartKey, { attrPrefix } = {}) {
  const rid = esc(String(reviewId || ""));
  const ck = esc(String(chartKey || ""));
  const n = getHumanChartDraft(reviewId, chartKey).length;
  // data-psr-draw-* by default; entry_blind uses data-ebr-draw-*.
  const p = attrPrefix === "ebr" ? "ebr" : "psr";
  return `<div class="psr-human-draw psr-human-draw--on-chart" data-human-draw-toolbar="${rid}" data-human-draw-chart="${ck}">
    <div class="psr-human-draw-tools" role="group" aria-label="Owner chart draw tools for this pane">
      <button type="button" class="btn psr-draw-tool" data-human-draw-tool="highlight" data-${p}-draw-rid="${rid}" data-${p}-draw-chart="${ck}" title="Tap start then end for a time band">Highlight</button>
      <button type="button" class="btn psr-draw-tool" data-human-draw-tool="hline" data-${p}-draw-rid="${rid}" data-${p}-draw-chart="${ck}" title="Tap once for a horizontal level">H-line</button>
      <button type="button" class="btn psr-draw-tool" data-human-draw-tool="line" data-${p}-draw-rid="${rid}" data-${p}-draw-chart="${ck}" title="Tap two points for a trend line">Trend</button>
      <button type="button" class="btn psr-draw-tool" data-human-draw-tool="parallel" data-${p}-draw-rid="${rid}" data-${p}-draw-chart="${ck}" title="Drag primary line, then drag 3 anchors (start / end / separation)">Parallel</button>
      <button type="button" class="btn psr-draw-tool" data-human-draw-tool="undo" data-${p}-draw-rid="${rid}" data-${p}-draw-chart="${ck}" title="Remove last drawing on this chart">Undo</button>
      <button type="button" class="btn psr-draw-tool" data-human-draw-tool="clear" data-${p}-draw-rid="${rid}" data-${p}-draw-chart="${ck}" title="Clear drawings on this chart">Clear</button>
    </div>
    <p class="small muted psr-human-draw-status" data-human-draw-status>Draw off · ${n} on this view · auto-attaches with Comment</p>
  </div>`;
}

function renderChartWithDrawTools(reviewId, chartKey, chartMountHtml, { attrPrefix } = {}) {
  return `<div class="psr-chart-draw-wrap" data-psr-chart-draw-wrap="${esc(
    String(chartKey || "")
  )}">
    ${renderHumanDrawToolbar(reviewId, chartKey, { attrPrefix })}
    ${chartMountHtml}
  </div>`;
}

const PATTERN_MARK_TONE_BLURB = {
  info: "Context — framing / location / MA, not a live signal.",
  warn: "Caution — same-day weakness or premature-sell band to weigh.",
  weak: "Material loss path (≤ −5%) — outcome context only.",
  good: "Cited recovery (e.g. same-day reverse) — still observe-only.",
};

function patternMarkExplainText(row) {
  if (!row || typeof row !== "object") return "";
  const label = String(row.label || row.pattern || "mark").trim();
  const bits = [label];
  const tone = String(row.tone || "info");
  const blurb = PATTERN_MARK_TONE_BLURB[tone];
  if (blurb) bits.push(blurb);
  if (row.cite) bits.push(`Cite: ${String(row.cite)}`);
  if (row.pattern && String(row.pattern) !== label) bits.push(`Pattern: ${row.pattern}`);
  if (row.type) bits.push(`Mark: ${row.type}`);
  if (row.t0 || row.t1) {
    const span = [row.t0, row.t1].filter(Boolean).join(" → ");
    if (span) bits.push(`Window: ${span}`);
  }
  if (row.ref) bits.push(`Ref: ${row.ref}`);
  if (row.anchor) bits.push(`Anchor: ${row.anchor}`);
  bits.push("influences_live=false");
  return bits.join("\n");
}

function renderPatternMarkChips(marks, chartKey) {
  if (!Array.isArray(marks) || !marks.length) return "";
  const filtered = marks.filter((row) => {
    if (!row || typeof row !== "object") return false;
    if (!chartKey) return true;
    const charts = Array.isArray(row.charts) ? row.charts : ["episode", "wider_tf"];
    return charts.includes(chartKey) || (chartKey === "pit" && charts.includes("episode"));
  });
  if (!filtered.length) return "";
  return `<ul class="psr-pattern-marks" aria-label="Factory pattern marks">
    ${filtered
      .map((row, index) => {
        const tone = String(row.tone || "info");
        const label = String(row.label || row.pattern || "mark");
        const markId = String(row.id || row.pattern || `mark-${index}`);
        const explain = patternMarkExplainText(row);
        return `<li class="psr-pattern-mark-wrap">
          <button type="button" class="psr-pattern-mark psr-pattern-${esc(
            tone
          )}" data-psr-pattern-chip="${esc(markId)}" aria-expanded="false" title="${esc(
            "Tap for short explanation"
          )}">${esc(label)}</button>
          <div class="psr-pattern-mark-explain" hidden data-psr-pattern-explain="${esc(
            markId
          )}">${esc(explain).replace(/\n/g, "<br>")}</div>
        </li>`;
      })
      .join("")}
  </ul>`;
}

function collapsePatternMarkExplains(exceptBtn) {
  document.querySelectorAll("[data-psr-pattern-chip][aria-expanded='true']").forEach((btn) => {
    if (exceptBtn && btn === exceptBtn) return;
    btn.setAttribute("aria-expanded", "false");
    const wrap = btn.closest(".psr-pattern-mark-wrap");
    const panel = wrap && wrap.querySelector("[data-psr-pattern-explain]");
    if (panel) panel.hidden = true;
  });
}

function bindPatternMarkChipsOnce() {
  if (window.__ftsePatternMarkChipsBound) return;
  window.__ftsePatternMarkChipsBound = true;
  document.addEventListener("click", (ev) => {
    const chip = ev.target.closest("[data-psr-pattern-chip]");
    if (chip) {
      ev.preventDefault();
      ev.stopPropagation();
      const open = chip.getAttribute("aria-expanded") === "true";
      collapsePatternMarkExplains(chip);
      const wrap = chip.closest(".psr-pattern-mark-wrap");
      const panel = wrap && wrap.querySelector("[data-psr-pattern-explain]");
      if (!panel) return;
      if (open) {
        chip.setAttribute("aria-expanded", "false");
        panel.hidden = true;
      } else {
        chip.setAttribute("aria-expanded", "true");
        panel.hidden = false;
      }
      return;
    }
    if (!ev.target.closest(".psr-pattern-mark-wrap")) {
      collapsePatternMarkExplains();
    }
  });
}

function postSaleReviewOverlays(item) {
  const rid = item && item.review_id;
  return {
    close_in: item.close_in || (item.charts && item.charts.episode) || null,
    wider_tf: item.wider_tf || (item.charts && item.charts.wider_tf) || null,
    opened_at: item.opened_at || item.entry_at || null,
    sold_at: item.sold_at || item.exit_at || null,
    book_cost: item.avg_cost != null ? item.avg_cost : null,
    exit_price: item.exit_price != null ? item.exit_price : null,
    pattern_marks: postSalePatternMarks(item),
    human_pattern_marks: humanDraftPatternMarks(rid),
    pattern_chart_key: "episode",
  };
}

const POST_SALE_REVIEW_SORT_OPTIONS = [
  { id: "interesting", label: "Interesting" },
  { id: "exit_at", label: "Date" },
  { id: "ticker", label: "Stock" },
  { id: "loss_size", label: "Loss size" },
  { id: "book", label: "Book" },
  { id: "tag", label: "Tag" },
];

const POST_SALE_MECHANICAL_SELL_CODES = new Set([
  "hold_trading_days",
  "leave_buy_tier",
  "left_target_set",
]);

function normalizePostSaleReviewSort(value) {
  const key = String(value || "interesting");
  if (key === "name" || key === "stock") return "ticker";
  if (key === "interest" || key === "priority") return "interesting";
  if (POST_SALE_REVIEW_SORT_OPTIONS.some((row) => row.id === key)) return key;
  return "interesting";
}

function postSaleReviewStockName(item) {
  const name = String((item && item.name) || "").trim();
  const ticker = String((item && item.ticker) || "").trim();
  return name || ticker || "";
}

function postSaleSellReasonCode(item) {
  const sell =
    item && item.sell_decision && typeof item.sell_decision === "object"
      ? item.sell_decision
      : null;
  const candidates = [
    sell && sell.code,
    item && item.exit_reason,
    item && item.sell_reason_code,
    item && item.sell_reason,
  ];
  for (const raw of candidates) {
    const text = String(raw || "").trim();
    if (text) return text;
  }
  return "";
}

function postSaleSellInterestRank(item) {
  // 0 = identity/quality break; 1 = other non-mechanical; 2 = max-days / leave cohort.
  const code = postSaleSellReasonCode(item);
  const lowered = code.toLowerCase();
  if (
    POST_SALE_MECHANICAL_SELL_CODES.has(code) ||
    lowered.includes("hold_trading_days") ||
    lowered.includes("max_days") ||
    lowered === "leave_buy_cohort"
  ) {
    return 2;
  }
  if (code.startsWith("identity_break_") || code.startsWith("quality_break_")) {
    return 0;
  }
  return 1;
}

function sortPostSaleReviewItems(items, sortBy) {
  const rows = Array.isArray(items) ? items.slice() : [];
  const key = normalizePostSaleReviewSort(sortBy);
  rows.sort((a, b) => {
    if (key === "interesting") {
      const ir = postSaleSellInterestRank(a) - postSaleSellInterestRank(b);
      if (ir) return ir;
      const ar = a.tag === "reply" ? 0 : 1;
      const br = b.tag === "reply" ? 0 : 1;
      if (ar !== br) return ar - br;
      return String(b.exit_at || "").localeCompare(String(a.exit_at || ""));
    }
    if (key === "book") {
      const bookCmp = String(a.book_tag || a.book_id || "").localeCompare(
        String(b.book_tag || b.book_id || "")
      );
      if (bookCmp) return bookCmp;
      return String(b.exit_at || "").localeCompare(String(a.exit_at || ""));
    }
    if (key === "tag") {
      const ar = a.tag === "reply" ? 0 : 1;
      const br = b.tag === "reply" ? 0 : 1;
      if (ar !== br) return ar - br;
      return String(b.exit_at || "").localeCompare(String(a.exit_at || ""));
    }
    if (key === "loss_size") {
      const ap = Number(a.return_pct);
      const bp = Number(b.return_pct);
      const an = Number.isFinite(ap) ? ap : 0;
      const bn = Number.isFinite(bp) ? bp : 0;
      if (an !== bn) return an - bn;
      return String(b.exit_at || "").localeCompare(String(a.exit_at || ""));
    }
    if (key === "ticker") {
      const nameCmp = postSaleReviewStockName(a).localeCompare(
        postSaleReviewStockName(b),
        undefined,
        { sensitivity: "base" }
      );
      if (nameCmp) return nameCmp;
      return String(a.ticker || "").localeCompare(String(b.ticker || ""));
    }
    // Date = sell/exit date, newest first
    const dateCmp = String(b.exit_at || "").localeCompare(String(a.exit_at || ""));
    if (dateCmp) return dateCmp;
    return String(a.book_tag || a.book_id || "").localeCompare(
      String(b.book_tag || b.book_id || "")
    );
  });
  return rows;
}

function renderPostSaleLearningPoints(points) {
  const rows = Array.isArray(points) ? points.filter(Boolean) : [];
  if (!rows.length) return "";
  return `<ul class="psr-learning-points small">${rows
    .map((p) => `<li>${esc(String(p))}</li>`)
    .join("")}</ul>`;
}

function postSaleReasonLabelBroken(label) {
  const text = String(label || "").trim();
  if (!text) return true;
  // Owner noise: unknown/unjoinable chips that render as "? -" / "?".
  if (text === "?" || text === "? -" || text === "?—" || /^[?？]\s*[-–—]?\s*$/.test(text)) {
    return true;
  }
  return false;
}

function renderPostSaleDecisionReasons(item) {
  const buy = item && item.buy_decision && typeof item.buy_decision === "object"
    ? item.buy_decision
    : null;
  const sell = item && item.sell_decision && typeof item.sell_decision === "object"
    ? item.sell_decision
    : null;
  const buyLabel = buy && buy.label
    ? String(buy.label)
    : item && item.buy_reason
      ? String(item.buy_reason)
      : "Unknown — unjoinable (no structured trail)";
  const sellLabel = sell && sell.label
    ? String(sell.label)
    : item && item.sell_reason
      ? String(item.sell_reason)
      : "Unknown — unjoinable (no structured trail)";
  const buyOk = buy ? !!buy.join_ok : false;
  const sellOk = sell ? !!sell.join_ok : false;
  const buyCode = buy && buy.code ? String(buy.code) : "";
  const sellCode = sell && sell.code ? String(sell.code) : "";
  const buySrc = buy && buy.source ? String(buy.source) : "";
  const sellSrc = sell && sell.source ? String(sell.source) : "";
  const rows = [];
  if (!postSaleReasonLabelBroken(buyLabel)) {
    rows.push(`<div class="psr-decision-row${buyOk ? "" : " is-unknown"}">
      <span class="psr-decision-side">Bought because</span>
      <span class="psr-decision-label">${esc(buyLabel)}</span>
      <span class="small muted psr-decision-meta">${esc(
        [buyCode && buyOk ? buyCode : "", buySrc].filter(Boolean).join(" · ") || "unjoinable"
      )}</span>
    </div>`);
  }
  if (!postSaleReasonLabelBroken(sellLabel)) {
    rows.push(`<div class="psr-decision-row${sellOk ? "" : " is-unknown"}">
      <span class="psr-decision-side">Sold because</span>
      <span class="psr-decision-label">${esc(sellLabel)}</span>
      <span class="small muted psr-decision-meta">${esc(
        [sellCode && sellOk ? sellCode : "", sellSrc].filter(Boolean).join(" · ") || "unjoinable"
      )}</span>
    </div>`);
  }
  if (!rows.length) return "";
  return `<div class="psr-decision-reasons" aria-label="Buy and sell decision reasons">${rows.join(
    ""
  )}</div>`;
}

function renderPostSaleDialogue(item) {
  const turns = Array.isArray(item.dialogue) ? item.dialogue : [];
  const ownerComment = String((item && item.owner_comment) || "").trim();
  const replyText = String((item && item.reply_text) || "").trim();
  if (!turns.length && !(ownerComment || replyText || (item && item.llm_opinion))) {
    return "";
  }
  const blocks = [];
  let sawComment = false;
  let sawReply = false;
  if (turns.length) {
    for (const turn of turns) {
      if (!turn || typeof turn !== "object") continue;
      const kind = String(turn.kind || turn.role || "note");
      if (kind === "comment" || kind === "owner") sawComment = true;
      if (kind === "reply") sawReply = true;
      const label =
        kind === "initial_opinion"
          ? "Factory opinion"
          : kind === "comment" || kind === "owner"
            ? "Owner comment"
            : kind === "reply"
              ? "Factory reply"
              : kind;
      const source = turn.source ? ` · ${esc(String(turn.source))}` : "";
      const points =
        kind === "initial_opinion" ? renderPostSaleLearningPoints(turn.learning_points) : "";
      blocks.push(`<div class="psr-dialogue-turn psr-dialogue-${esc(kind)}">
        <p class="small"><strong>${esc(label)}</strong><span class="muted">${source}</span></p>
        <p class="small psr-dialogue-text">${esc(turn.text || "—")}</p>
        ${points}
      </div>`);
    }
    // If rebuild reseeded dialogue to opinion-only, still surface stored fields.
    if (!sawComment && ownerComment) {
      blocks.push(`<div class="psr-dialogue-turn psr-dialogue-comment">
        <p class="small"><strong>Owner comment</strong></p>
        <p class="small psr-dialogue-text">${esc(ownerComment)}</p>
      </div>`);
    }
    if (!sawReply && replyText) {
      blocks.push(`<div class="psr-dialogue-turn psr-dialogue-reply">
        <p class="small"><strong>Factory reply</strong></p>
        <p class="small psr-dialogue-text">${esc(replyText)}</p>
      </div>`);
    }
  } else {
    if (item.llm_opinion) {
      blocks.push(`<div class="psr-dialogue-turn psr-dialogue-initial_opinion">
        <p class="small"><strong>Factory opinion</strong><span class="muted"> · ${esc(
          item.opinion_source || "deterministic_v0"
        )}</span></p>
        <p class="small psr-dialogue-text">${esc(item.llm_opinion)}</p>
        ${renderPostSaleLearningPoints(item.learning_points)}
      </div>`);
    }
    if (ownerComment) {
      blocks.push(`<div class="psr-dialogue-turn psr-dialogue-comment">
        <p class="small"><strong>Owner comment</strong></p>
        <p class="small psr-dialogue-text">${esc(ownerComment)}</p>
      </div>`);
    }
    if (replyText) {
      blocks.push(`<div class="psr-dialogue-turn psr-dialogue-reply">
        <p class="small"><strong>Factory reply</strong></p>
        <p class="small psr-dialogue-text">${esc(replyText)}</p>
      </div>`);
    }
  }
  return `<div class="psr-dialogue" aria-label="Post-sale review dialogue">${blocks.join("")}</div>`;
}

function renderPostSaleReviewCard(item, expanded) {
  const tag = String(item.tag || "new");
  const tagCls = tag === "reply" ? "psr-tag-reply" : "psr-tag-new";
  const pct = item.return_pct;
  const pctText = pct == null || pct === "" ? "n/a" : `${Number(pct).toFixed(2)}%`;
  const exitDay = String(item.exit_at || "").slice(0, 10) || "—";
  const hold =
    item.hold_days != null && item.hold_days !== "" ? `${item.hold_days}d hold` : "";
  const bookLabel = String(item.book_tag || item.book_id || "?");
  const showName =
    item.name && String(item.name).trim() && String(item.name).trim() !== String(item.ticker || "");
  const annotations = item.chart_annotations || {};
  const patternMarks = postSalePatternMarks(item);
  const episodeNote = annotations.episode
    ? `<p class="small muted psr-chart-annotation">${esc(annotations.episode)}</p>`
    : "";
  const widerNote = annotations.wider_tf
    ? `<p class="small muted psr-chart-annotation">${esc(annotations.wider_tf)}</p>`
    : "";
  const framing = String(item.framing || "")
    .split("\n")
    .map((line) => `<div>${esc(line)}</div>`)
    .join("");
  let ownerComment = String(item.owner_comment || "").trim();
  if (!ownerComment && Array.isArray(item.dialogue)) {
    for (const turn of item.dialogue) {
      if (!turn || typeof turn !== "object") continue;
      const kind = String(turn.kind || turn.role || "").toLowerCase();
      if (kind === "comment" || kind === "owner") {
        ownerComment = String(turn.text || "").trim();
        if (ownerComment) break;
      }
    }
  }
  const commentPreview =
    tag === "reply" && ownerComment
      ? `<p class="small psr-comment-preview"><strong>Your comment</strong> — ${esc(
          ownerComment.length > 180 ? `${ownerComment.slice(0, 177)}…` : ownerComment
        )}</p>`
      : "";
  const collapsedReasons = !expanded ? renderPostSaleDecisionReasons(item) : "";
  const detail = expanded
    ? `<div class="psr-card-detail">
        ${renderPostSaleDecisionReasons(item)}
        <pre class="psr-framing small">${framing}</pre>
        ${renderPostSaleDialogue(item)}
        <p class="small muted">Episode window + wider TF — owner verifies both (pattern marks map factory opinion onto the chart). Draw tools are per-view; Attach with Comment (N229). Mini dialogue: opinion → Comment → reply. influences_live=false.</p>
        <div class="psr-dual-charts">
          <div>
            <h4 class="small">Episode</h4>
            ${episodeNote}
            ${renderPatternMarkChips(patternMarks, "episode")}
            ${renderChartWithDrawTools(
              item.review_id,
              "episode",
              `<div class="psr-chart" data-psr-chart="episode" data-psr-id="${esc(
                item.review_id
              )}"></div>`
            )}
          </div>
          <div>
            <h4 class="small">Wider TF</h4>
            ${widerNote}
            ${renderPatternMarkChips(patternMarks, "wider_tf")}
            ${renderChartWithDrawTools(
              item.review_id,
              "wider_tf",
              `<div class="psr-chart" data-psr-chart="wider" data-psr-id="${esc(
                item.review_id
              )}"></div>`
            )}
          </div>
        </div>
        <div class="psr-actions">
          <button type="button" class="btn btn-primary" data-psr-accept="${esc(
            item.review_id
          )}" data-psr-tag="${esc(tag)}">Accept</button>
          <button type="button" class="btn" data-psr-duplicate="${esc(
            item.review_id
          )}" data-psr-tag="${esc(tag)}" title="Same pattern already commented (e.g. other book)">Duplicate</button>
          <label class="small psr-comment-label">Comment
            <input type="text" class="psr-comment-input" data-psr-comment-input="${esc(
              item.review_id
            )}" placeholder="Missed pattern…" />
          </label>
          <span class="small muted psr-attach-draw-hint" data-psr-attach-draw-hint="${esc(
            item.review_id
          )}" title="In-memory chart drafts seal into the Comment payload automatically">
            Drawings auto-attach with Comment
          </span>
          <button type="button" class="btn" data-psr-comment="${esc(
            item.review_id
          )}" data-psr-tag="${esc(tag)}">Comment</button>
        </div>
        <p class="small muted" data-psr-status="${esc(item.review_id)}" aria-live="polite"></p>
      </div>`
    : "";
  return `<article class="psr-card${expanded ? " is-expanded" : ""}" data-psr-card="${esc(
    item.review_id
  )}" data-psr-book="${esc(bookLabel)}" data-psr-ticker="${esc(item.ticker || "")}">
    <button type="button" class="psr-card-head" data-psr-expand="${esc(item.review_id)}">
      <span class="psr-tag ${tagCls}">${esc(tag)}</span>
      <span class="psr-book" title="Sealed book / control track">${esc(bookLabel)}</span>
      <strong class="psr-ticker">${esc(item.ticker || "?")}</strong>
      ${
        showName
          ? `<span class="small muted psr-stock-name">${esc(String(item.name).trim())}</span>`
          : ""
      }
      <span class="small muted psr-exit-date">${esc(exitDay)}${
        hold ? ` · ${esc(hold)}` : ""
      }</span>
      <span class="psr-pct">${esc(pctText)}</span>
      <span class="small muted">${esc(item.basis_label || "")}</span>
    </button>
    ${commentPreview}
    ${collapsedReasons}
    ${detail}
  </article>`;
}

function renderPostSaleReviews(data) {
  const queue = data.post_sale_review_queue;
  if (!queue || !Array.isArray(queue.active)) {
    return `${renderLifecycleSubnav()}
      <div class="empty-state">Post-sale review queue not published yet. Wait for ops-monitor or run <code>ftse-post-sale-review refresh</code>.</div>`;
  }
  syncPostSaleQueueOverlay(data);
  const sortBy = normalizePostSaleReviewSort(
    postSaleReviewSort || queue.sort_default || "interesting"
  );
  postSaleReviewSort = sortBy;
  const items = sortPostSaleReviewItems(
    (queue.active || []).filter(postSaleReviewCardUsable),
    sortBy
  );
  let sortOptions = Array.isArray(queue.sort_options) && queue.sort_options.length
    ? queue.sort_options.slice()
    : POST_SALE_REVIEW_SORT_OPTIONS.slice();
  // Stale published queue JSON may omit Interesting until ops-monitor refresh.
  if (!sortOptions.some((row) => normalizePostSaleReviewSort(row && row.id) === "interesting")) {
    sortOptions = [{ id: "interesting", label: "Interesting" }, ...sortOptions];
  }
  const sortToggle = `<div class="psr-sort-toggle" role="group" aria-label="Sort post-sale reviews">
      ${sortOptions
        .map((row) => {
          const id = normalizePostSaleReviewSort(row.id);
          const label = String(row.label || id);
          return `<button type="button" class="tab${
            id === sortBy ? " active" : ""
          }" data-psr-sort="${esc(id)}" aria-pressed="${
            id === sortBy ? "true" : "false"
          }">${esc(label)}</button>`;
        })
        .join("")}
    </div>`;
  const sortHint =
    sortBy === "interesting"
      ? "Interesting first: identity/quality breaks, then other non-mechanical, then max-days / leave-buy-cohort."
      : sortBy === "ticker"
        ? "Sorted by stock name (A→Z; ticker when name missing)."
        : sortBy === "loss_size"
          ? "Sorted by episode return (worst first)."
          : sortBy === "book"
            ? "Sorted by sealed book / FTSE control tag."
            : sortBy === "tag"
              ? "Sorted reply tags first, then by exit date."
              : "Sorted by sell/exit date (newest first).";
  const cards = items.length
    ? items
        .map((item) =>
          renderPostSaleReviewCard(item, postSaleReviewExpandedId === item.review_id)
        )
        .join("")
    : `<p class="muted">Active queue empty — all exits Accept/Comment/Duplicate’d, or no recent sealed/control sells.</p>`;
  const byBook = Object.entries(queue.by_book || {})
    .map(([k, v]) => `${esc(k)} ${v}`)
    .join(" · ");
  const labels = data.post_sale_review_labels || {};
  const historyEvents = Array.isArray(labels.events) ? labels.events.slice() : [];
  historyEvents.reverse();
  const historyRows = historyEvents.slice(0, 40);
  const historyHtml = historyRows.length
    ? `<div class="psr-history">
        <h4 class="small">Durable history (Accept / Comment / reply — outside active)</h4>
        <ul class="psr-history-list small">
          ${historyRows
            .map((ev) => {
              const kind = String(ev.kind || "?");
              const snap = ev.snapshot || {};
              const ticker = snap.ticker || "";
              const book = snap.book_tag || snap.book_id || "";
              const when = String(ev.acted_at || "").replace("T", " ").slice(0, 19);
              const text = String(ev.text || "").trim();
              const textBit = text
                ? ` — ${esc(text.length > 160 ? `${text.slice(0, 157)}…` : text)}`
                : "";
              return `<li><span class="psr-tag psr-tag-${esc(
                kind === "reply" ? "reply" : "new"
              )}">${esc(kind)}</span> <span class="psr-book">${esc(
                book || "?"
              )}</span> <strong>${esc(
                ticker || ev.review_id || "?"
              )}</strong> <span class="muted">${esc(when)}</span>${textBit}</li>`;
            })
            .join("")}
        </ul>
      </div>`
    : `<p class="small muted">No Accept/Comment history yet.</p>`;
  return `${renderLifecycleSubnav()}
    <section class="card lifecycle-board-section post-sale-review-section">
      <div class="market-status-header">
        <div>
          <h3>Post-sale reviews</h3>
          <p class="small muted" style="margin:0.25rem 0 0">
            ${esc(
              queue.product_claim ||
                "Sealed Lifecycle exits + FTSE control — Accept/Comment alignment only."
            )}
          </p>
        </div>
        <div class="lifecycle-board-controls psr-sort-controls">
          <span class="small muted psr-sort-label">Sort</span>
          ${sortToggle}
        </div>
      </div>
      <p class="small muted">
        Active (uncommented) ${queue.active_count ?? items.length}
        · actioned history ${queue.actioned_count ?? "—"}
        · candidates ${queue.coverage?.candidate_exits ?? "—"}
        ${byBook ? `· ${byBook}` : ""}
      </p>
      <p class="small muted">${esc(sortHint)} Same ticker on N200/N201/N206/… is one card per sealed book — book badge is the model tag, not a duplicate review_id. Commented / Accepted / Duplicate’d exits stay in durable history only.</p>
      <p class="small muted">${esc(queue.attention_note || "")}</p>
      <p class="small muted">Package M · influences_live=false · no Package L auto-tune · charts annotated with factory opinion, learning points, and pattern marks</p>
      <div class="psr-queue" id="psr-queue">${cards}</div>
      ${historyHtml}
    </section>`;
}

async function afterRenderPostSaleReviews(data) {
  const queue = data.post_sale_review_queue;
  if (!queue || !postSaleReviewExpandedId) return;
  const item = (queue.active || []).find(
    (row) => row.review_id === postSaleReviewExpandedId
  );
  if (!item) return;
  const root = document.getElementById("psr-queue");
  if (!root) return;
  const episode = root.querySelector(
    `[data-psr-chart="episode"][data-psr-id="${CSS.escape(item.review_id)}"]`
  );
  const wider = root.querySelector(
    `[data-psr-chart="wider"][data-psr-id="${CSS.escape(item.review_id)}"]`
  );
  if (typeof mountDualHorizonCharts === "function") {
    await mountDualHorizonCharts(
      episode,
      wider,
      { ticker: item.ticker, name: item.name || item.ticker },
      postSaleReviewOverlays(item)
    );
  }
  wireHumanChartDrawOnBody(episode, item.review_id, "episode");
  wireHumanChartDrawOnBody(wider, item.review_id, "wider_tf");
}

function wireHumanChartDrawOnBody(body, reviewId, chartKey) {
  if (!body || typeof enableHumanChartDraw !== "function") return;
  enableHumanChartDraw(body, {
    reviewId,
    chartKey,
    getElements: () => getHumanChartDraft(reviewId, chartKey),
    onChange: ({ element }) => {
      if (!element) return;
      const cur = getHumanChartDraft(reviewId, chartKey);
      cur.push(element);
      setHumanChartDraft(reviewId, chartKey, cur);
      // Refresh overlays so the new mark paints beside factory marks.
      if (body._chartState) {
        const overlays = body._chartState.overlays || {};
        overlays.human_pattern_marks = humanDraftPatternMarks(reviewId);
        body._chartState.overlays = overlays;
        if (typeof paintPriceChart === "function") paintPriceChart(body);
      }
      const toolbar = body.parentElement && body.parentElement.querySelector(
        `[data-human-draw-toolbar][data-human-draw-chart="${CSS.escape(chartKey)}"]`
      );
      const status = toolbar && toolbar.querySelector("[data-human-draw-status]");
      if (status) {
        status.textContent = `Draw off · ${cur.length} on this view · auto-attaches with Comment`;
      }
      if (typeof setHumanChartDrawTool === "function") setHumanChartDrawTool(body, null);
      toolbar &&
        toolbar.querySelectorAll(".psr-draw-tool.is-active").forEach((btn) => {
          btn.classList.remove("is-active");
        });
    },
  });
}

function bindHumanDrawToolbarsOnce() {
  if (window.__ftseHumanDrawToolsBound) return;
  window.__ftseHumanDrawToolsBound = true;
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-human-draw-tool]");
    if (!btn) return;
    const tool = btn.getAttribute("data-human-draw-tool");
    const rid = btn.getAttribute("data-psr-draw-rid") || btn.getAttribute("data-ebr-draw-rid");
    const chartKey =
      btn.getAttribute("data-psr-draw-chart") || btn.getAttribute("data-ebr-draw-chart");
    if (!rid || !chartKey) return;
    ev.preventDefault();
    ev.stopPropagation();
    const chartSel =
      chartKey === "wider_tf"
        ? `[data-psr-chart="wider"][data-psr-id="${CSS.escape(rid)}"]`
        : chartKey === "pit"
          ? `[data-ebr-chart="pit"][data-ebr-id="${CSS.escape(rid)}"]`
          : `[data-psr-chart="episode"][data-psr-id="${CSS.escape(rid)}"], [data-ebr-chart="pit"][data-ebr-id="${CSS.escape(rid)}"]`;
    const body = document.querySelector(chartSel);
    const toolbar = btn.closest("[data-human-draw-toolbar]");
    if (tool === "parallel-done") {
      if (body && typeof commitParallelEdit === "function") {
        commitParallelEdit(body);
      }
      toolbar &&
        toolbar.querySelectorAll(".psr-draw-tool.is-active").forEach((el) => {
          el.classList.remove("is-active");
        });
      if (body && typeof setHumanChartDrawTool === "function") {
        setHumanChartDrawTool(body, null);
      }
      return;
    }
    if (tool === "undo") {
      if (body && body._humanDraw && body._humanDraw.parallelEdit) {
        body._humanDraw.parallelEdit = null;
        if (typeof clearParallelEditLayer === "function") clearParallelEditLayer(body);
        if (typeof syncParallelDoneButton === "function") syncParallelDoneButton(body);
      }
      const cur = getHumanChartDraft(rid, chartKey);
      cur.pop();
      setHumanChartDraft(rid, chartKey, cur);
      if (body && body._chartState) {
        body._chartState.overlays = body._chartState.overlays || {};
        body._chartState.overlays.human_pattern_marks = humanDraftPatternMarks(rid);
        if (typeof paintPriceChart === "function") paintPriceChart(body);
      }
      const status = toolbar && toolbar.querySelector("[data-human-draw-status]");
      if (status) status.textContent = `Draw off · ${cur.length} on this view · auto-attaches with Comment`;
      return;
    }
    if (tool === "clear") {
      if (body && body._humanDraw) {
        body._humanDraw.parallelEdit = null;
        if (typeof clearParallelEditLayer === "function") clearParallelEditLayer(body);
        if (typeof syncParallelDoneButton === "function") syncParallelDoneButton(body);
      }
      setHumanChartDraft(rid, chartKey, []);
      if (body && body._chartState) {
        body._chartState.overlays = body._chartState.overlays || {};
        body._chartState.overlays.human_pattern_marks = humanDraftPatternMarks(rid);
        if (typeof paintPriceChart === "function") paintPriceChart(body);
      }
      const status = toolbar && toolbar.querySelector("[data-human-draw-status]");
      if (status) status.textContent = "Draw off · 0 on this view · auto-attaches with Comment";
      return;
    }
    if (!body) return;
    toolbar &&
      toolbar.querySelectorAll(".psr-draw-tool.is-active").forEach((el) => {
        el.classList.remove("is-active");
      });
    const active = body._humanDraw && body._humanDraw.tool === tool;
    if (active) {
      if (typeof setHumanChartDrawTool === "function") setHumanChartDrawTool(body, null);
      return;
    }
    btn.classList.add("is-active");
    if (typeof setHumanChartDrawTool === "function") setHumanChartDrawTool(body, tool);
  });
}

async function submitPostSaleReviewAction({ reviewId, decision, text, tag, item }) {
  const statusEl = document.querySelector(`[data-psr-status="${CSS.escape(reviewId)}"]`);
  const setStatus = (msg) => {
    if (statusEl) statusEl.textContent = msg || "";
  };
  const statusVerb =
    decision === "comment"
      ? "Recording comment…"
      : decision === "duplicate"
        ? "Recording duplicate…"
        : "Recording Accept…";
  setStatus(statusVerb);
  const snap = slimPostSaleBridgeSnapshot(item && typeof item === "object" ? item : {});
  // Optimistic clear first so soft reload / bridge latency cannot bounce the card.
  // Persist to localStorage so iPad full refresh during GHA lag cannot resurrect it.
  rememberPendingPostSaleAction(reviewId, decision, { text: text || "", item: snap });
  // Flatten identity onto the payload — GHA batch reads flat keys; nested
  // snapshot alone previously spawned blank ``?`` reply cards. Slim keys keep
  // repository_dispatch under GitHub's client_payload size limit when batched.
  const payload = {
    ...snap,
    review_id: reviewId,
    decision,
    text: text || "",
    tag: tag || "new",
    snapshot: snap,
  };
  if (decision === "comment") {
    // Prefer auto-seal of non-empty drafts; never drop in-memory geometry on Comment.
    const geometries = geometryPayloadForComment(reviewId);
    if (geometries.length) {
      payload.post_hoc_human_geometry = geometries;
    }
  }
  try {
    if (window.DashboardBridge && (await window.DashboardBridge.init())) {
      const action =
        decision === "comment"
          ? "post-sale-review-comment"
          : decision === "duplicate"
            ? "post-sale-review-duplicate"
            : "post-sale-review-ack";
      await window.DashboardBridge.queueCommand(action, payload);
      setStatus("Queued — waiting for git commit…");
    } else {
      const response = await fetch("/api/post-sale-review-action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body.ok === false) {
        throw new Error(body.error || `HTTP ${response.status}`);
      }
      setStatus("Saved locally.");
    }
    if (decision === "comment") clearHumanChartDrafts(reviewId);
    if (dashboardData) syncPostSaleQueueOverlay(dashboardData);
    if (postSaleReviewExpandedId === reviewId) postSaleReviewExpandedId = null;
    renderLifecycle(dashboardData);
  } catch (err) {
    delete pendingPostSaleActions[String(reviewId || "").trim()];
    persistPendingPostSaleActions();
    setStatus(`Failed: ${err.message || err}`);
    if (dashboardData) renderLifecycle(dashboardData);
  }
}

let entryBlindReviewSort = "interesting";
let entryBlindReviewExpandedId = null;

/** Session + localStorage overlay — entry_blind clears survive iPad refresh (#1196/#1205 class). */
const PENDING_ENTRY_BLIND_STORAGE_KEY = "ftse.pendingEntryBlindActions.v1";
const PENDING_ENTRY_BLIND_MAX_AGE_MS = 2 * 60 * 60 * 1000;
const pendingEntryBlindActions = Object.create(null);
const ENTRY_BLIND_BRIDGE_SNAPSHOT_KEYS = [
  "book_id",
  "book_tag",
  "model_id",
  "ticker",
  "name",
  "entry_at",
  "opened_at",
  "family_id",
  "episode_key",
  "stage",
  "buy_decision",
  "buy_reason",
  "entry_news_polarity",
  "parallel_timing_lenses",
  "framing",
  "population",
  "registration_id",
  "decision_reasons_join_ok",
  "avg_cost",
];

function loadPendingEntryBlindActionsFromStorage() {
  try {
    const raw = localStorage.getItem(PENDING_ENTRY_BLIND_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return;
    const cutoff = Date.now() - PENDING_ENTRY_BLIND_MAX_AGE_MS;
    for (const [rid, row] of Object.entries(parsed)) {
      if (!rid || !row || typeof row !== "object") continue;
      const at = Number(row.at) || 0;
      if (!at || at < cutoff) continue;
      pendingEntryBlindActions[rid] = row;
    }
  } catch {
    /* ignore quota / private mode */
  }
}

function persistPendingEntryBlindActions() {
  try {
    localStorage.setItem(
      PENDING_ENTRY_BLIND_STORAGE_KEY,
      JSON.stringify(pendingEntryBlindActions)
    );
  } catch {
    /* ignore */
  }
}

function pruneStalePendingEntryBlindActions() {
  const cutoff = Date.now() - PENDING_ENTRY_BLIND_MAX_AGE_MS;
  let changed = false;
  for (const rid of Object.keys(pendingEntryBlindActions)) {
    const row = pendingEntryBlindActions[rid];
    const at = row && typeof row === "object" ? Number(row.at) || 0 : 0;
    if (!at || at < cutoff) {
      delete pendingEntryBlindActions[rid];
      changed = true;
    }
  }
  if (changed) persistPendingEntryBlindActions();
}

loadPendingEntryBlindActionsFromStorage();

function slimEntryBlindBridgeSnapshot(item) {
  const src = item && typeof item === "object" ? item : {};
  const out = {};
  for (const key of ENTRY_BLIND_BRIDGE_SNAPSHOT_KEYS) {
    if (src[key] != null && src[key] !== "") out[key] = src[key];
  }
  if (!out.episode_key && (out.family_id || src.family_id)) {
    out.episode_key = out.family_id || src.family_id;
  }
  if (!out.stage) out.stage = "entry_blind";
  out.outcome_fields_stripped = true;
  return out;
}

function rememberPendingEntryBlindAction(reviewId, decision, meta) {
  const rid = String(reviewId || "").trim();
  if (!rid) return;
  const info = meta && typeof meta === "object" ? meta : {};
  const slim = slimEntryBlindBridgeSnapshot(info.item || info.snapshot || {});
  pendingEntryBlindActions[rid] = {
    decision: String(decision || "accept"),
    at: Date.now(),
    text: String(info.text || "").trim(),
    snapshot: slim,
    episode_key: String(
      slim.episode_key || slim.family_id || info.episode_key || ""
    ).trim(),
  };
  persistPendingEntryBlindActions();
}

function entryBlindActionedFamilyKeys(labels) {
  const out = new Set();
  const store = labels && typeof labels === "object" ? labels : {};
  for (const ev of Array.isArray(store.events) ? store.events : []) {
    if (!ev || typeof ev !== "object") continue;
    const kind = String(ev.kind || "").toLowerCase();
    if (kind !== "accept" && kind !== "comment" && kind !== "duplicate") continue;
    const snap = ev.snapshot && typeof ev.snapshot === "object" ? ev.snapshot : {};
    const ep = String(snap.episode_key || snap.family_id || "").trim();
    if (ep) out.add(ep);
  }
  for (const row of Object.values(pendingEntryBlindActions)) {
    if (!row || typeof row !== "object") continue;
    const ep = String(
      row.episode_key || (row.snapshot && (row.snapshot.episode_key || row.snapshot.family_id)) || ""
    ).trim();
    if (ep) out.add(ep);
  }
  return out;
}

function prunePendingEntryBlindActions(data) {
  const labels = (data && data.entry_blind_review_labels) || {};
  const actioned = new Set(
    (Array.isArray(labels.actioned_review_ids) ? labels.actioned_review_ids : [])
      .map((id) => String(id || "").trim())
      .filter(Boolean)
  );
  for (const ev of Array.isArray(labels.events) ? labels.events : []) {
    if (!ev || typeof ev !== "object") continue;
    const kind = String(ev.kind || "").toLowerCase();
    if (kind === "accept" || kind === "comment" || kind === "duplicate") {
      const rid = String(ev.review_id || "").trim();
      if (rid) actioned.add(rid);
    }
  }
  let changed = false;
  for (const rid of Object.keys(pendingEntryBlindActions)) {
    if (actioned.has(rid)) {
      delete pendingEntryBlindActions[rid];
      changed = true;
    }
  }
  if (changed) persistPendingEntryBlindActions();
}

function entryBlindReviewCardUsable(item) {
  if (!item || typeof item !== "object") return false;
  const ticker = String(item.ticker || "").trim();
  if (!ticker || ticker === "?") return false;
  const book = String(item.book_tag || item.book_id || "").trim();
  if (!book || book === "?") return false;
  return true;
}

function syncEntryBlindQueueOverlay(data) {
  if (!data || !data.entry_blind_review_queue) return;
  pruneStalePendingEntryBlindActions();
  prunePendingEntryBlindActions(data);
  const queue = data.entry_blind_review_queue;
  if (!Array.isArray(queue.active)) return;
  const labels = data.entry_blind_review_labels || {};
  const actioned = new Set(
    (Array.isArray(labels.actioned_review_ids) ? labels.actioned_review_ids : [])
      .map((id) => String(id || "").trim())
      .filter(Boolean)
  );
  const pending = new Set(Object.keys(pendingEntryBlindActions));
  const clearedFamilies = entryBlindActionedFamilyKeys(labels);
  queue.active = queue.active.filter((row) => {
    if (!row || typeof row !== "object") return false;
    if (String(row.tag || "").toLowerCase() === "reply") return false;
    if (String(row.review_id || "").startsWith("pending-reply:")) return false;
    if (String(row.review_id || "").startsWith("reply:")) return false;
    const rid = String(row.review_id || "").trim();
    if (!rid) return false;
    if (pending.has(rid) || actioned.has(rid)) return false;
    const ep = String(row.episode_key || row.family_id || "").trim();
    if (ep && clearedFamilies.has(ep)) return false;
    return entryBlindReviewCardUsable(row);
  });
  queue.active_count = queue.active.length;
  queue.new_count = queue.active.filter(
    (row) => String(row.tag || "new").toLowerCase() !== "reply"
  ).length;
  queue.reply_count = 0;
  const byBook = {};
  for (const row of queue.active) {
    const key = String(row.book_tag || row.book_id || "?");
    byBook[key] = (byBook[key] || 0) + 1;
  }
  queue.by_book = byBook;
}

function renderEntryBlindBuyReason(item) {
  const buy = item && item.buy_decision && typeof item.buy_decision === "object"
    ? item.buy_decision
    : null;
  if (!buy) {
    return `<p class="small muted">Bought because: unknown (fail-closed)</p>`;
  }
  const join = buy.join_ok ? "" : " · unjoinable";
  return `<p class="small"><strong>Bought because</strong> — ${esc(
    buy.label || "?"
  )} <span class="muted">[${esc(buy.code || "?")}${join}]</span></p>`;
}

function renderEntryBlindNewsPolarity(item, { expanded } = {}) {
  const pol =
    item && item.entry_news_polarity && typeof item.entry_news_polarity === "object"
      ? item.entry_news_polarity
      : null;
  if (!pol) {
    return `<p class="small muted">News polarity — no_usable_news (fail-closed)</p>`;
  }
  const label = String(pol.label || "no_usable_news");
  const cites = Array.isArray(pol.cites) ? pol.cites : [];
  const asof = pol.asof ? String(pol.asof).slice(0, 10) : "";
  const muted = label === "no_usable_news" || !pol.join_ok;
  const head = muted
    ? `<p class="small muted"><strong>News polarity</strong> — ${esc(label)}${
        asof ? ` · asof ${esc(asof)}` : ""
      }</p>`
    : `<p class="small"><strong>News polarity</strong> — ${esc(label)} <span class="muted">[${
        cites.length
      } cite${cites.length === 1 ? "" : "s"}${asof ? ` · asof ${esc(asof)}` : ""}]</span></p>`;
  if (!expanded || !cites.length || label === "no_usable_news") {
    return head;
  }
  const rows = cites
    .slice(0, 5)
    .map((c) => {
      if (!c || typeof c !== "object") return "";
      const title = String(c.title || "").trim() || "(untitled)";
      const bits = [];
      if (c.valence_hint) bits.push(String(c.valence_hint));
      if (c.event_type) bits.push(String(c.event_type));
      if (c.freshness) bits.push(String(c.freshness));
      if (c.age_days != null && c.age_days !== "") bits.push(`${c.age_days}d`);
      const meta = bits.length ? ` <span class="muted">(${esc(bits.join(" · "))})</span>` : "";
      return `<li class="small">${esc(title)}${meta}</li>`;
    })
    .filter(Boolean)
    .join("");
  return `${head}<ul class="psr-news-cites small">${rows}</ul>`;
}

function renderEntryBlindTimingLenses(item, { expanded } = {}) {
  const lenses =
    item && item.parallel_timing_lenses && typeof item.parallel_timing_lenses === "object"
      ? item.parallel_timing_lenses
      : null;
  if (!lenses || !lenses.present) {
    return `<p class="small muted">Timing lenses — none on this card yet (L652 observe)</p>`;
  }
  const fav = String(lenses.favourite_lens_id || "—");
  const conc =
    lenses.concurrence_count != null && lenses.concurrence_count !== ""
      ? String(lenses.concurrence_count)
      : "—";
  const head = `<p class="small"><strong>Timing lenses</strong> — fav ${esc(
    fav
  )} <span class="muted">[looking ${esc(String(lenses.looking_n ?? "—"))} · entered ${esc(
    String(lenses.entered_n ?? "—")
  )} · abandoned ${esc(String(lenses.abandoned_n ?? "—"))} · concurrence ${esc(conc)}]</span></p>`;
  if (!expanded) return head;
  const statuses =
    lenses.lens_statuses && typeof lenses.lens_statuses === "object" ? lenses.lens_statuses : {};
  const rows = Object.keys(statuses)
    .map((id) => `<li class="small">${esc(id)} — ${esc(String(statuses[id]))}</li>`)
    .join("");
  const concIds = Array.isArray(lenses.concurrence_lens_ids)
    ? lenses.concurrence_lens_ids.map((id) => esc(String(id))).join(", ")
    : "";
  return `${head}${
    rows ? `<ul class="psr-news-cites small">${rows}</ul>` : ""
  }<p class="small muted">Concurrence window lenses: ${
    concIds || "—"
  }. Observe-only; influences_live=false; N241 risk sizing not_now.</p>`;
}

function renderEntryBlindReviewCard(item, expanded) {
  const tag = String(item.tag || "new");
  const tagCls = tag === "reply" ? "psr-tag-reply" : "psr-tag-new";
  const entryDay = String(item.entry_at || "").slice(0, 10) || "—";
  const bookLabel = String(item.book_tag || item.book_id || "?");
  const showName =
    item.name && String(item.name).trim() && String(item.name).trim() !== String(item.ticker || "");
  const framing = String(item.framing || "")
    .split("\n")
    .map((line) => `<div>${esc(line)}</div>`)
    .join("");
  const pitMarks = postSalePatternMarks(item);
  const pitNote =
    item.chart_annotations && item.chart_annotations.pit
      ? `<p class="small muted psr-chart-annotation">${esc(item.chart_annotations.pit)}</p>`
      : "";
  const collapsed = !expanded
    ? `${renderEntryBlindBuyReason(item)}${renderEntryBlindNewsPolarity(item, {
        expanded: false,
      })}${renderEntryBlindTimingLenses(item, { expanded: false })}`
    : "";
  const detail = expanded
    ? `<div class="psr-card-detail">
        ${renderEntryBlindBuyReason(item)}
        ${renderEntryBlindNewsPolarity(item, { expanded: true })}
        ${renderEntryBlindTimingLenses(item, { expanded: true })}
        <pre class="psr-framing small">${framing}</pre>
        <p class="small muted">Stage entry_blind — PIT through buy day only. Pattern marks: entry quality / range / MA. Owner draw tools (N229) bind to this PIT view. News polarity = L650 observe cites (90d hard window; no fade). Timing lenses = L652 parallel observe (favourite vs peers; concurrence companion). No post-fill path / no realized %. influences_live=false.</p>
        <div class="psr-dual-charts">
          <div>
            <h4 class="small">PIT (to buy day)</h4>
            ${pitNote}
            ${renderPatternMarkChips(pitMarks, "pit")}
            ${renderChartWithDrawTools(
              item.review_id,
              "pit",
              `<div class="psr-chart" data-ebr-chart="pit" data-ebr-id="${esc(
                item.review_id
              )}"></div>`,
              { attrPrefix: "ebr" }
            )}
          </div>
        </div>
        <div class="psr-actions">
          <button type="button" class="btn btn-primary" data-ebr-accept="${esc(
            item.review_id
          )}" data-ebr-tag="${esc(tag)}">Accept</button>
          <button type="button" class="btn" data-ebr-duplicate="${esc(
            item.review_id
          )}" data-ebr-tag="${esc(tag)}" title="Same pattern already commented">Duplicate</button>
          <label class="small psr-comment-label">Comment
            <input type="text" class="psr-comment-input" data-ebr-comment-input="${esc(
              item.review_id
            )}" placeholder="Missed entry pattern…" />
          </label>
          <span class="small muted psr-attach-draw-hint" data-ebr-attach-draw-hint="${esc(
            item.review_id
          )}" title="In-memory chart drafts seal into the Comment payload automatically">
            Drawings auto-attach with Comment
          </span>
          <button type="button" class="btn" data-ebr-comment="${esc(
            item.review_id
          )}" data-ebr-tag="${esc(tag)}">Comment</button>
        </div>
        <p class="small muted" data-ebr-status="${esc(item.review_id)}" aria-live="polite"></p>
      </div>`
    : "";
  return `<article class="psr-card${expanded ? " is-expanded" : ""}" data-ebr-card="${esc(
    item.review_id
  )}">
    <button type="button" class="psr-card-head" data-ebr-expand="${esc(item.review_id)}">
      <span class="psr-tag ${tagCls}">${esc(tag)}</span>
      <span class="psr-book">${esc(bookLabel)}</span>
      <strong class="psr-ticker">${esc(item.ticker || "?")}</strong>
      ${
        showName
          ? `<span class="small muted psr-stock-name">${esc(String(item.name).trim())}</span>`
          : ""
      }
      <span class="small muted psr-exit-date">bought ${esc(entryDay)}</span>
      <span class="small muted">entry_blind</span>
    </button>
    ${collapsed}
    ${detail}
  </article>`;
}

function renderEntryBlindReviews(data) {
  const queue = data.entry_blind_review_queue;
  if (!queue || !Array.isArray(queue.active)) {
    return `${renderLifecycleSubnav()}
      <div class="empty-state">Entry-blind queue not published yet. Wait for ops-monitor or run <code>ftse-entry-blind-review refresh</code>.</div>`;
  }
  const sortBy = String(entryBlindReviewSort || queue.sort_default || "interesting");
  entryBlindReviewSort = sortBy;
  const items = Array.isArray(queue.active) ? queue.active.slice() : [];
  const sortOptions =
    Array.isArray(queue.sort_options) && queue.sort_options.length
      ? queue.sort_options
      : [
          { id: "interesting", label: "Interesting" },
          { id: "entry_at", label: "Date" },
          { id: "ticker", label: "Stock" },
          { id: "book", label: "Book" },
          { id: "tag", label: "Tag" },
        ];
  const sortToggle = `<div class="psr-sort-toggle" role="group" aria-label="Sort entry-blind reviews">
      ${sortOptions
        .map((row) => {
          const id = String(row.id || "");
          return `<button type="button" class="tab${
            id === sortBy ? " active" : ""
          }" data-ebr-sort="${esc(id)}" aria-pressed="${
            id === sortBy ? "true" : "false"
          }">${esc(row.label || id)}</button>`;
        })
        .join("")}
    </div>`;
  const cards = items.length
    ? items
        .map((item) =>
          renderEntryBlindReviewCard(item, entryBlindReviewExpandedId === item.review_id)
        )
        .join("")
    : `<p class="muted">Active entry_blind queue empty — Accept/Comment’d, or no recent lab/interesting buys in cap.</p>`;
  return `${renderLifecycleSubnav()}
    <section class="card lifecycle-board-section post-sale-review-section entry-blind-review-section">
      <div class="market-status-header">
        <div>
          <h3>Entry blind</h3>
          <p class="small muted" style="margin:0.25rem 0 0">
            ${esc(
              queue.product_claim ||
                "Blind entry critique — PIT through buy day; no outcome leakage."
            )}
          </p>
        </div>
        <div class="lifecycle-board-controls psr-sort-controls">
          <span class="small muted psr-sort-label">Sort</span>
          ${sortToggle}
        </div>
      </div>
      <p class="small muted">
        Active ${queue.active_count ?? items.length}
        · new ${queue.new_count ?? "—"}
        · reply ${queue.reply_count ?? "—"}
        · actioned ${queue.actioned_count ?? "—"}
        · candidates ${queue.coverage?.candidate_buys ?? "—"}
      </p>
      <p class="small muted">${esc(queue.attention_note || "")}</p>
      <p class="small muted">Package M · stage entry_blind · influences_live=false · no Package L</p>
      <div class="psr-queue" id="ebr-queue">${cards}</div>
    </section>`;
}

async function afterRenderEntryBlindReviews(data) {
  const queue = data.entry_blind_review_queue;
  if (!queue || !entryBlindReviewExpandedId) return;
  const item = (queue.active || []).find(
    (row) => row.review_id === entryBlindReviewExpandedId
  );
  if (!item) return;
  const root = document.getElementById("ebr-queue");
  if (!root) return;
  const pit = root.querySelector(
    `[data-ebr-chart="pit"][data-ebr-id="${CSS.escape(item.review_id)}"]`
  );
  const charts = item.charts || {};
  const pitWin = charts.pit || null;
  if (typeof mountDualHorizonCharts === "function" && pit) {
    await mountDualHorizonCharts(
      pit,
      null,
      { ticker: item.ticker, name: item.name || item.ticker },
      {
        close_in: pitWin
          ? { start: pitWin.start, end: pitWin.end, markers: [] }
          : null,
        wider_tf: null,
        opened_at: item.entry_at || null,
        sold_at: null,
        book_cost: item.avg_cost != null ? item.avg_cost : null,
        exit_price: null,
        pattern_marks: postSalePatternMarks(item),
        human_pattern_marks: humanDraftPatternMarks(item.review_id),
        pattern_chart_key: "pit",
      }
    );
  }
  wireHumanChartDrawOnBody(pit, item.review_id, "pit");
}

async function submitEntryBlindReviewAction({ reviewId, decision, text, tag, item }) {
  const statusEl = document.querySelector(`[data-ebr-status="${CSS.escape(reviewId)}"]`);
  const setStatus = (msg) => {
    if (statusEl) statusEl.textContent = msg || "";
  };
  setStatus(
    decision === "comment"
      ? "Recording comment…"
      : decision === "duplicate"
        ? "Recording duplicate…"
        : "Recording Accept…"
  );
  const snap = slimEntryBlindBridgeSnapshot(item && typeof item === "object" ? item : {});
  // Optimistic clear + localStorage before bridge await (same class as post-sale #1196/#1205).
  rememberPendingEntryBlindAction(reviewId, decision, { text: text || "", item: snap });
  const payload = {
    ...snap,
    review_id: reviewId,
    decision,
    text: text || "",
    tag: tag || "new",
    snapshot: snap,
  };
  if (decision === "comment") {
    // Prefer auto-seal of non-empty drafts; never drop in-memory geometry on Comment.
    const geometries = geometryPayloadForComment(reviewId);
    if (geometries.length) {
      payload.post_hoc_human_geometry = geometries;
    }
  }
  try {
    // Must use DashboardBridge.queueCommand — ftseDashboardBridge.enqueue was a dead path
    // on hosted dashboard, so Comment never hit entry-blind-review-ack.yml.
    if (window.DashboardBridge && (await window.DashboardBridge.init())) {
      const action =
        decision === "comment"
          ? "entry-blind-review-comment"
          : decision === "duplicate"
            ? "entry-blind-review-duplicate"
            : "entry-blind-review-ack";
      await window.DashboardBridge.queueCommand(action, payload);
      setStatus("Queued — waiting for git commit…");
    } else {
      const response = await fetch("/api/entry-blind-review-action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body.ok === false) {
        throw new Error(body.error || `HTTP ${response.status}`);
      }
      setStatus("Saved locally.");
    }
    if (decision === "comment") clearHumanChartDrafts(reviewId);
    if (dashboardData) syncEntryBlindQueueOverlay(dashboardData);
    if (entryBlindReviewExpandedId === reviewId) entryBlindReviewExpandedId = null;
    if (dashboardData) renderLifecycle(dashboardData);
  } catch (err) {
    delete pendingEntryBlindActions[String(reviewId || "").trim()];
    persistPendingEntryBlindActions();
    setStatus(`Failed: ${err.message || err}`);
    if (dashboardData) renderLifecycle(dashboardData);
  }
}

function bindEntryBlindReviewsOnce() {
  if (window.__ftseEntryBlindBound) return;
  window.__ftseEntryBlindBound = true;
  document.addEventListener("click", (ev) => {
    const sortBtn = ev.target.closest("[data-ebr-sort]");
    if (sortBtn) {
      entryBlindReviewSort = String(sortBtn.getAttribute("data-ebr-sort") || "interesting");
      if (dashboardData) renderLifecycle(dashboardData);
      return;
    }
    const expand = ev.target.closest("[data-ebr-expand]");
    if (expand) {
      const rid = expand.getAttribute("data-ebr-expand");
      entryBlindReviewExpandedId =
        entryBlindReviewExpandedId === rid ? null : rid;
      if (dashboardData) renderLifecycle(dashboardData);
      return;
    }
    const accept = ev.target.closest("[data-ebr-accept]");
    if (accept) {
      const rid = accept.getAttribute("data-ebr-accept");
      const item = (
        ((dashboardData || {}).entry_blind_review_queue || {}).active || []
      ).find((row) => row.review_id === rid);
      void submitEntryBlindReviewAction({
        reviewId: rid,
        decision: "accept",
        tag: accept.getAttribute("data-ebr-tag") || "new",
        item,
      });
      return;
    }
    const dup = ev.target.closest("[data-ebr-duplicate]");
    if (dup) {
      const rid = dup.getAttribute("data-ebr-duplicate");
      const item = (
        ((dashboardData || {}).entry_blind_review_queue || {}).active || []
      ).find((row) => row.review_id === rid);
      void submitEntryBlindReviewAction({
        reviewId: rid,
        decision: "duplicate",
        tag: dup.getAttribute("data-ebr-tag") || "new",
        item,
      });
      return;
    }
    const comment = ev.target.closest("[data-ebr-comment]");
    if (comment) {
      const rid = comment.getAttribute("data-ebr-comment");
      const input = document.querySelector(
        `[data-ebr-comment-input="${CSS.escape(rid)}"]`
      );
      const text = input ? String(input.value || "").trim() : "";
      if (!text) {
        const statusEl = document.querySelector(`[data-ebr-status="${CSS.escape(rid)}"]`);
        if (statusEl) statusEl.textContent = "Comment text required.";
        return;
      }
      const item = (
        ((dashboardData || {}).entry_blind_review_queue || {}).active || []
      ).find((row) => row.review_id === rid);
      void submitEntryBlindReviewAction({
        reviewId: rid,
        decision: "comment",
        text,
        tag: comment.getAttribute("data-ebr-tag") || "new",
        item,
      });
    }
  });
}

let entryRevisitReviewExpandedId = null;
let entryRevisitReviewsBound = false;

function renderEntryRevisitReviewCard(item, expanded) {
  const tag = String(item.tag || "new");
  const tagCls = tag === "reply" ? "psr-tag-reply" : "psr-tag-new";
  const entryDay = String(item.entry_at || "").slice(0, 10) || "—";
  const bookLabel = String(item.book_tag || item.book_id || "?");
  const path = item.path_status && typeof item.path_status === "object" ? item.path_status : {};
  const status = String(path.status || item.episode_status_at_plus28 || "—");
  const ret = path.fair_cost_return_pct_to_plus28;
  const retBit =
    typeof ret === "number" && Number.isFinite(ret)
      ? `${(ret * 100).toFixed(1)}% to +28d`
      : "path % n/a";
  const blindId = String(item.blind_review_id || item.parent_review_id || "—");
  const framing = String(item.framing || "")
    .split("\n")
    .map((line) => `<div>${esc(line)}</div>`)
    .join("");
  const detail = expanded
    ? `<div class="psr-card-detail">
        <pre class="psr-framing small">${framing}</pre>
        <p class="small muted">Stage entry_revisit — fixed buy+28d. Blind Accept/Comment immutable. influences_live=false. Chart draw tools: not on this stage (no marks[] pane yet — use entry_blind PIT / post-sale dual-horizon).</p>
        <p class="small">Blind parent <code>${esc(blindId)}</code> · ${esc(status)} · ${esc(retBit)}</p>
        <div class="psr-actions">
          <button type="button" class="btn btn-primary" data-err-accept="${esc(
            item.review_id
          )}" data-err-tag="${esc(tag)}">Accept</button>
          <button type="button" class="btn" data-err-duplicate="${esc(
            item.review_id
          )}" data-err-tag="${esc(tag)}">Duplicate</button>
          <label class="small psr-comment-label">Comment
            <input type="text" class="psr-comment-input" data-err-comment-input="${esc(
              item.review_id
            )}" placeholder="Calibrate blind critique…" />
          </label>
          <button type="button" class="btn" data-err-comment="${esc(
            item.review_id
          )}" data-err-tag="${esc(tag)}">Comment</button>
        </div>
        <p class="small muted" data-err-status="${esc(item.review_id)}" aria-live="polite"></p>
      </div>`
    : `<p class="small muted">${esc(status)} · ${esc(retBit)} · blind ${esc(blindId.slice(0, 8))}</p>`;
  return `<article class="psr-card${expanded ? " is-expanded" : ""}" data-err-card="${esc(
    item.review_id
  )}">
    <button type="button" class="psr-card-head" data-err-expand="${esc(item.review_id)}">
      <span class="psr-tag ${tagCls}">${esc(tag)}</span>
      <span class="psr-book">${esc(bookLabel)}</span>
      <strong class="psr-ticker">${esc(item.ticker || "?")}</strong>
      <span class="small muted psr-exit-date">bought ${esc(entryDay)}</span>
      <span class="small muted">entry_revisit</span>
    </button>
    ${detail}
  </article>`;
}

function renderEntryRevisitReviews(data) {
  const queue = data.entry_revisit_review_queue;
  if (!queue) {
    return `${renderLifecycleSubnav()}
      <div class="empty-state">Entry-revisit queue not published yet. Wait for ops-monitor or run <code>ftse-entry-revisit-review refresh</code>.</div>`;
  }
  const active = Array.isArray(queue.active) ? queue.active : [];
  const cards = active.length
    ? active
        .map((item) =>
          renderEntryRevisitReviewCard(item, entryRevisitReviewExpandedId === item.review_id)
        )
        .join("")
    : `<p class="muted">Active entry_revisit queue empty — none due past buy+28d with entry_blind Accept/Comment, or all actioned.</p>`;
  return `
    ${renderLifecycleSubnav()}
    <section class="card lifecycle-board-section post-sale-review-section entry-revisit-review-section">
      <div class="section-head">
        <div>
          <h3>Entry revisit (buy+28d)</h3>
          <p class="small muted">Package M · after entry_blind · frozen blind summary + path through +28d · influences_live=false</p>
        </div>
        <div class="small muted">active ${esc(String(queue.active_count ?? active.length))} · actioned ${esc(
          String(queue.actioned_count ?? 0)
        )}</div>
      </div>
      <div class="psr-card-list">${cards}</div>
    </section>`;
}

function afterRenderEntryRevisitReviews(_data) {
  /* no chart mount in thin v0 — path status is textual */
}

async function submitEntryRevisitReviewAction({ reviewId, decision, text = "", tag = "new", item }) {
  const statusEl = document.querySelector(`[data-err-status="${CSS.escape(reviewId)}"]`);
  if (statusEl) statusEl.textContent = "Saving…";
  try {
    const snapshot = item || {};
    if (typeof queueDashboardCommand === "function" && !window.FTSE_LOCAL_DASHBOARD) {
      await queueDashboardCommand(
        decision === "comment"
          ? "entry-revisit-review-comment"
          : decision === "duplicate"
            ? "entry-revisit-review-duplicate"
            : "entry-revisit-review-ack",
        {
          review_id: reviewId,
          decision,
          text,
          tag,
          snapshot,
        }
      );
      setStatus("Queued entry-revisit action.");
    } else {
      const response = await fetch("/api/entry-revisit-review-action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_id: reviewId,
          decision,
          text,
          tag,
          snapshot,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body.ok === false) {
        throw new Error(body.error || `HTTP ${response.status}`);
      }
      if (dashboardData && body.queue_path) {
        /* local serve refreshes queue file; reload soft */
      }
      setStatus("Saved locally.");
    }
    if (dashboardData && dashboardData.entry_revisit_review_queue) {
      const q = dashboardData.entry_revisit_review_queue;
      q.active = (q.active || []).filter((row) => row.review_id !== reviewId);
      q.active_count = (q.active || []).length;
    }
    entryRevisitReviewExpandedId = null;
    renderLifecycle(dashboardData);
  } catch (err) {
    if (statusEl) statusEl.textContent = `Failed: ${err.message || err}`;
    setStatus(`Failed: ${err.message || err}`);
  }
}

function bindEntryRevisitReviewsOnce() {
  if (entryRevisitReviewsBound) return;
  entryRevisitReviewsBound = true;
  const panel = document.getElementById("panel-lifecycle");
  if (!panel) return;
  panel.addEventListener("click", (ev) => {
    const expand = ev.target.closest("[data-err-expand]");
    if (expand) {
      const rid = expand.getAttribute("data-err-expand");
      entryRevisitReviewExpandedId =
        entryRevisitReviewExpandedId === rid ? null : rid;
      if (dashboardData) renderLifecycle(dashboardData);
      return;
    }
    const accept = ev.target.closest("[data-err-accept]");
    if (accept) {
      const rid = accept.getAttribute("data-err-accept");
      const item = (
        ((dashboardData || {}).entry_revisit_review_queue || {}).active || []
      ).find((row) => row.review_id === rid);
      void submitEntryRevisitReviewAction({
        reviewId: rid,
        decision: "accept",
        tag: accept.getAttribute("data-err-tag") || "new",
        item,
      });
      return;
    }
    const dup = ev.target.closest("[data-err-duplicate]");
    if (dup) {
      const rid = dup.getAttribute("data-err-duplicate");
      const item = (
        ((dashboardData || {}).entry_revisit_review_queue || {}).active || []
      ).find((row) => row.review_id === rid);
      void submitEntryRevisitReviewAction({
        reviewId: rid,
        decision: "duplicate",
        tag: dup.getAttribute("data-err-tag") || "new",
        item,
      });
      return;
    }
    const comment = ev.target.closest("[data-err-comment]");
    if (comment) {
      const rid = comment.getAttribute("data-err-comment");
      const input = document.querySelector(
        `[data-err-comment-input="${CSS.escape(rid)}"]`
      );
      const text = input ? String(input.value || "").trim() : "";
      if (!text) {
        const statusEl = document.querySelector(`[data-err-status="${CSS.escape(rid)}"]`);
        if (statusEl) statusEl.textContent = "Comment text required.";
        return;
      }
      const item = (
        ((dashboardData || {}).entry_revisit_review_queue || {}).active || []
      ).find((row) => row.review_id === rid);
      void submitEntryRevisitReviewAction({
        reviewId: rid,
        decision: "comment",
        text,
        tag: comment.getAttribute("data-err-tag") || "new",
        item,
      });
    }
  });
}

function renderLifecycle(data) {
  const panel = document.getElementById("panel-lifecycle");
  if (!panel) return;
  bindLifecyclePanel();
  bindPatternMarkChipsOnce();
  bindHumanDrawToolbarsOnce();
  bindEntryBlindReviewsOnce();
  bindEntryRevisitReviewsOnce();
  lifecycleSubpage = normalizeLifecycleSubpage(lifecycleSubpage);

  if (lifecycleSubpage === "maturity") {
    panel.innerHTML = `
      ${renderLifecycleSubnav()}
      ${renderLifecycleMaturitySection(data)}
    `;
    return;
  }

  if (lifecycleSubpage === "sealed") {
    panel.innerHTML = renderSealedLifecycle(data);
    afterRenderSealedLifecycle(data);
    return;
  }

  if (lifecycleSubpage === "reviews") {
    panel.innerHTML = renderPostSaleReviews(data);
    afterRenderPostSaleReviews(data);
    return;
  }

  if (lifecycleSubpage === "entry-blind") {
    panel.innerHTML = renderEntryBlindReviews(data);
    afterRenderEntryBlindReviews(data);
    return;
  }

  if (lifecycleSubpage === "entry-revisit") {
    panel.innerHTML = renderEntryRevisitReviews(data);
    afterRenderEntryRevisitReviews(data);
    return;
  }

  const board = data.lifecycle_board;
  if (!board || !(board.columns || []).length) {
    panel.innerHTML = `
      ${renderLifecycleSubnav()}
      <div class="empty-state">Lifecycle board not published yet. Run <code>ftse-publish</code> or refresh the local dashboard so <code>data/lifecycle_board.json</code> is rebuilt.</div>
    `;
    return;
  }
  const markets = board.markets || [];
  if (!markets.length) {
    panel.innerHTML = `
      ${renderLifecycleSubnav()}
      <div class="empty-state">No market screens or paper books available for the lifecycle board.</div>
    `;
    return;
  }
  if (!lifecycleMarketId || !markets.some((row) => row.market_id === lifecycleMarketId)) {
    lifecycleMarketId = board.default_market_id || markets[0].market_id;
  }
  const market = findLifecycleMarket(board, lifecycleMarketId);
  const track = findLifecycleTrack(market, lifecycleTrackId);
  lifecycleTrackId = track ? track.track_id : null;
  const colDefs = board.columns || [];
  const trackColumns = mergeLifecycleColumns(market, track);

  const marketOptions = markets
    .map(
      (row) =>
        `<option value="${esc(row.market_id)}"${row.market_id === market.market_id ? " selected" : ""}>${esc(row.label || row.market_id)}</option>`
    )
    .join("");
  const marketPills = markets
    .filter((row) => row.is_live || row.is_focus || row.is_admitted)
    .map((row) => {
      const active = row.market_id === market.market_id ? " active" : "";
      return `<button type="button" class="tab${active}" data-lifecycle-market="${esc(row.market_id)}">${esc(row.label || row.market_id)}</button>`;
    })
    .join("");
  const trackPills = (market.tracks || [])
    .map((row) => {
      const active = track && row.track_id === track.track_id ? " active" : "";
      return `<button type="button" class="tab${active}" data-lifecycle-track="${esc(row.track_id)}">${esc(row.track_label || row.track_id)} <span class="small muted">${row.holdings_count ?? 0}</span></button>`;
    })
    .join("");

  const sortMode = LIFECYCLE_CHIP_SORT_MODES.includes(lifecycleChipSort)
    ? lifecycleChipSort
    : "board";
  lifecycleChipSort = sortMode;
  const sortDir = resolveLifecycleChipSortDir(sortMode, lifecycleChipSortDir);
  const sortOptions = [
    { id: "board", label: "Board order" },
    { id: "alpha", label: "A–Z" },
    { id: "stage", label: "Time in stage" },
  ]
    .map(
      (row) =>
        `<option value="${esc(row.id)}"${row.id === sortMode ? " selected" : ""}>${esc(row.label)}</option>`
    )
    .join("");
  const sortDirOptions = [
    { id: "asc", label: "Ascending" },
    { id: "desc", label: "Descending" },
  ]
    .map(
      (row) =>
        `<option value="${esc(row.id)}"${row.id === sortDir ? " selected" : ""}>${esc(row.label)}</option>`
    )
    .join("");

  const columnsHtml = colDefs
    .map((col) => {
      const packed = trackColumns[col.id] || { count: 0, shown: [], truncated: 0 };
      const shown = sortLifecycleCards(packed.shown || [], sortMode, sortDir);
      const cards = shown.map(lifecycleTickerCard).join("");
      const more = packed.truncated
        ? `<p class="small muted lifecycle-truncated">+${packed.truncated} more</p>`
        : "";
      return `<section class="lifecycle-col" data-column="${esc(col.id)}">
        <header class="lifecycle-col-header">
          <h3>${esc(col.label)}</h3>
          <span class="lifecycle-count">${packed.count ?? 0}</span>
        </header>
        <p class="small muted lifecycle-col-q">${esc(col.question || "")}</p>
        <div class="lifecycle-exps">${lifecycleExperimentChips(col.experiments)}</div>
        <div class="lifecycle-cards">${cards || '<p class="small muted">None</p>'}${more}</div>
      </section>`;
    })
    .join("");

  const counts = market.column_counts || {};
  const countBits = colDefs
    .map((col) => `${esc(col.label)} ${counts[col.id] ?? 0}`)
    .join(" · ");

  panel.innerHTML = `
    ${renderLifecycleSubnav()}
    <section class="card lifecycle-board-section">
      <div class="market-status-header">
        <div>
          <h3>Position lifecycle</h3>
          <p class="small muted" style="margin:0.25rem 0 0">
            ${esc(board.note || "One market at a time — screen names plus the selected paper book.")}
          </p>
        </div>
        <div class="lifecycle-board-controls">
          <label class="small">Market
            <select id="lifecycle-market-select">${marketOptions}</select>
          </label>
          <label class="small">Sort chips
            <select id="lifecycle-chip-sort">${sortOptions}</select>
          </label>
          <label class="small">Order
            <select id="lifecycle-chip-sort-dir">${sortDirOptions}</select>
          </label>
        </div>
      </div>
      <div class="tabs lifecycle-market-pills">${marketPills}</div>
      <div class="tabs lifecycle-track-pills">${trackPills}</div>
      <p class="small muted">${esc(market.label || market.market_id)} · ${esc(track ? track.track_label : "screen")} · ${esc(countBits)}</p>
      ${lifecycleTenureLegend(board.tenure)}
      <div class="lifecycle-board">${columnsHtml}</div>
    </section>
  `;
}

function bindLifecyclePanel() {
  const panel = document.getElementById("panel-lifecycle");
  if (panel && !panel.dataset.lifecycleBound) {
    panel.dataset.lifecycleBound = "1";
    panel.addEventListener("click", (event) => {
      const sortBtn = event.target.closest("[data-psr-sort]");
      if (sortBtn) {
        event.preventDefault();
        postSaleReviewSort = normalizePostSaleReviewSort(sortBtn.dataset.psrSort);
        renderLifecycle(dashboardData);
        return;
      }
      const subpageBtn = event.target.closest("[data-lifecycle-subpage]");
      if (subpageBtn) {
        event.preventDefault();
        lifecycleSubpage = normalizeLifecycleSubpage(subpageBtn.dataset.lifecycleSubpage);
        syncLifecycleHash();
        renderLifecycle(dashboardData);
        return;
      }
      const expandBtn = event.target.closest("[data-psr-expand]");
      if (expandBtn) {
        event.preventDefault();
        const rid = expandBtn.dataset.psrExpand;
        postSaleReviewExpandedId =
          postSaleReviewExpandedId === rid ? null : rid || null;
        renderLifecycle(dashboardData);
        return;
      }
      const acceptBtn = event.target.closest("[data-psr-accept]");
      if (acceptBtn) {
        event.preventDefault();
        const reviewId = acceptBtn.dataset.psrAccept;
        const tag = acceptBtn.dataset.psrTag || "new";
        const item = (
          ((dashboardData || {}).post_sale_review_queue || {}).active || []
        ).find((row) => row.review_id === reviewId);
        submitPostSaleReviewAction({
          reviewId,
          decision: "accept",
          text: "",
          tag,
          item,
        });
        return;
      }
      const duplicateBtn = event.target.closest("[data-psr-duplicate]");
      if (duplicateBtn) {
        event.preventDefault();
        const reviewId = duplicateBtn.dataset.psrDuplicate;
        const tag = duplicateBtn.dataset.psrTag || "new";
        const item = (
          ((dashboardData || {}).post_sale_review_queue || {}).active || []
        ).find((row) => row.review_id === reviewId);
        submitPostSaleReviewAction({
          reviewId,
          decision: "duplicate",
          text: "",
          tag,
          item,
        });
        return;
      }
      const commentBtn = event.target.closest("[data-psr-comment]");
      if (commentBtn) {
        event.preventDefault();
        const reviewId = commentBtn.dataset.psrComment;
        const tag = commentBtn.dataset.psrTag || "new";
        const input = panel.querySelector(
          `[data-psr-comment-input="${CSS.escape(reviewId)}"]`
        );
        const text = input ? String(input.value || "").trim() : "";
        if (!text) {
          const statusEl = panel.querySelector(
            `[data-psr-status="${CSS.escape(reviewId)}"]`
          );
          if (statusEl) statusEl.textContent = "Comment text required.";
          return;
        }
        const item = (
          ((dashboardData || {}).post_sale_review_queue || {}).active || []
        ).find((row) => row.review_id === reviewId);
        submitPostSaleReviewAction({
          reviewId,
          decision: "comment",
          text,
          tag,
          item,
        });
        return;
      }
      const sealedObserveJump = event.target.closest("[data-sealed-observe-jump]");
      if (sealedObserveJump) {
        event.preventDefault();
        const model = normalizeInvestmentModel(sealedObserveJump.dataset.sealedObserveJump);
        activateTab("analysis", { updateHash: false });
        jumpToInvestmentModel(model, { updateHash: true, scroll: true });
        return;
      }
      const tabJump = event.target.closest("[data-tab-jump]");
      if (tabJump) {
        event.preventDefault();
        activateTab(tabJump.dataset.tabJump, { updateHash: true });
        return;
      }
      const sealedModelBtn = event.target.closest("[data-sealed-model]");
      if (sealedModelBtn) {
        event.preventDefault();
        sealedLifecycleModelId = normalizeSealedLifecycleModel(sealedModelBtn.dataset.sealedModel);
        sealedLifecycleDetailKey = null;
        lifecycleSubpage = "sealed";
        syncLifecycleHash();
        renderLifecycle(dashboardData);
        return;
      }
      const sealedViewBtn = event.target.closest("[data-sealed-view]");
      if (sealedViewBtn) {
        event.preventDefault();
        const mode = sealedViewBtn.dataset.sealedView === "list" ? "list" : "heatmap";
        sealedLifecycleViewMode = mode;
        renderLifecycle(dashboardData);
        return;
      }
      const sealedSortBtn = event.target.closest("[data-sealed-sort]");
      if (sealedSortBtn) {
        event.preventDefault();
        sealedLifecycleSortMode = normalizeSealedLifecycleSortMode(
          sealedSortBtn.dataset.sealedSort
        );
        renderLifecycle(dashboardData);
        return;
      }
      const sealedDetailClose = event.target.closest("[data-sealed-detail-close]");
      if (sealedDetailClose) {
        event.preventDefault();
        sealedLifecycleDetailKey = null;
        renderLifecycle(dashboardData);
        return;
      }
      const sealedHeat = event.target.closest("[data-sealed-heat-key]");
      if (sealedHeat) {
        event.preventDefault();
        const key = sealedHeat.dataset.sealedHeatKey || null;
        sealedLifecycleDetailKey = sealedLifecycleDetailKey === key ? null : key;
        renderLifecycle(dashboardData);
        return;
      }
      const sealedChip = event.target.closest(".sealed-life-chip[data-sealed-key]");
      if (sealedChip) {
        event.preventDefault();
        const key = sealedChip.dataset.sealedKey || null;
        sealedLifecycleDetailKey = sealedLifecycleDetailKey === key ? null : key;
        renderLifecycle(dashboardData);
        return;
      }
      const marketBtn = event.target.closest("[data-lifecycle-market]");
      if (marketBtn) {
        event.preventDefault();
        lifecycleMarketId = marketBtn.dataset.lifecycleMarket;
        lifecycleTrackId = null;
        syncLifecycleHash();
        renderLifecycle(dashboardData);
        return;
      }
      const trackBtn = event.target.closest("[data-lifecycle-track]");
      if (trackBtn) {
        event.preventDefault();
        lifecycleTrackId = trackBtn.dataset.lifecycleTrack;
        syncLifecycleHash();
        renderLifecycle(dashboardData);
        return;
      }
      const expBtn = event.target.closest("[data-lifecycle-experiment]");
      if (expBtn) {
        event.preventDefault();
        openLifecycleExperimentCard(expBtn.dataset.lifecycleExperiment);
        return;
      }
      const tickerBtn = event.target.closest("[data-lifecycle-ticker]");
      if (tickerBtn) {
        event.preventDefault();
        openLifecycleTickerCard(tickerBtn.dataset.lifecycleTicker);
      }
    });
    panel.addEventListener("change", (event) => {
      if (event.target.id === "lifecycle-chip-sort") {
        const next = event.target.value;
        lifecycleChipSort = LIFECYCLE_CHIP_SORT_MODES.includes(next) ? next : "board";
        saveLifecycleChipSort(lifecycleChipSort);
        renderLifecycle(dashboardData);
        return;
      }
      if (event.target.id === "lifecycle-chip-sort-dir") {
        const next = event.target.value;
        lifecycleChipSortDir = LIFECYCLE_CHIP_SORT_DIRS.includes(next) ? next : "asc";
        saveLifecycleChipSortDir(lifecycleChipSortDir);
        renderLifecycle(dashboardData);
        return;
      }
      if (event.target.id !== "lifecycle-market-select") return;
      lifecycleMarketId = event.target.value;
      lifecycleTrackId = null;
      syncLifecycleHash();
      renderLifecycle(dashboardData);
    });
  }
  if (window.__lifecycleOpenBound) return;
  window.__lifecycleOpenBound = true;
  document.addEventListener("click", (event) => {
    const memoBtn = event.target.closest("[data-lifecycle-open-memo]");
    if (memoBtn) {
      event.preventDefault();
      const memo = findResearchMemo(memoBtn.dataset.lifecycleOpenMemo);
      if (memo) void openMemo(memo);
      return;
    }
    const btn = event.target.closest("[data-open-lifecycle]");
    if (!btn) return;
    event.preventDefault();
    openLifecycleBoard(btn.dataset.openLifecycle);
  });
  window.addEventListener("hashchange", () => {
    applyDashboardHash();
    if (dashboardData) renderLifecycle(dashboardData);
  });
}

function renderDashboard(data) {
  dashboardData = data;
  // Re-apply session pending over whatever merge the in-flight reload built.
  // Without this, a fetch that started before Acknowledge can clobber the
  // optimistic bottom-sort and re-enable the button on render.
  if (humanTasksBoardBase) syncHumanTasksBoardOverlay(data);
  if (dailyFocusBase) syncDailyFocusOverlay(data);
  const meta = data.meta || {};
  const trustCount = meta.trust_count || (data.trust_reports || []).length || 0;
  document.getElementById("run-meta").textContent = data.run_at
    ? `${meta.universe_label || "FTSE"} · ${meta.company_count || 0} companies · ${trustCount} trusts · ${meta.strong_buy_count || 0} strong buys · ${fmtDate(data.run_at)}`
  : "Awaiting first published screening run";

  const parsed = parseDashboardHash();
  if (parsed && parsed.tab === "lifecycle") {
    if (parsed.subpage) lifecycleSubpage = normalizeLifecycleSubpage(parsed.subpage);
    if (parsed.sealedModel) {
      sealedLifecycleModelId = normalizeSealedLifecycleModel(parsed.sealedModel);
    }
    if (parsed.market) lifecycleMarketId = parsed.market;
    if (parsed.track) lifecycleTrackId = parsed.track;
  }
  if (parsed && parsed.tab === "analysis" && parsed.subpage) {
    analysisSectionId = normalizeAnalysisSection(parsed.subpage);
  }
  if (parsed && parsed.tab === "automation" && parsed.subpage) {
    automationSectionId = normalizeAutomationSection(parsed.subpage);
  }
  if (parsed && parsed.tab === "performance" && parsed.subpage) {
    performanceSectionId = normalizePerformanceSection(parsed.subpage);
  }
  if (parsed && parsed.tab === "screener") {
    screenerFilterId = normalizeScreenerFilter(parsed.subpage || "");
  }

  renderOverview(data);
  renderLifecycle(data);
  renderScreener(data);
  renderTrusts(data);
  renderStrongBuys(data);
  renderPortfolio(data);
  renderAutomation(data);
  renderPerformance(data);
  renderAnalysis(data);
  equalizeMarketTileHeights();
  if (parsed && parsed.tab) activateTab(parsed.tab);
  if (parsed && parsed.tab === "analysis" && parsed.subpage && parsed.subpage !== "observe") {
    window.requestAnimationFrame(() => jumpToAnalysisSection(analysisSectionId, { updateHash: false }));
  }
  if (parsed && parsed.tab === "automation" && parsed.subpage && parsed.subpage !== "daily") {
    window.requestAnimationFrame(() =>
      jumpToAutomationSection(automationSectionId, { updateHash: false })
    );
  }
}

async function loadOptionalDashboardJson(path) {
  try {
    return await fetchDashboardJson(path);
  } catch {
    return null;
  }
}

async function loadDashboard() {
  try {
    await reloadDashboard();
  } catch (err) {
    document.getElementById("run-meta").textContent = `Failed to load dashboard data: ${err.message}`;
    document.getElementById("panel-overview").innerHTML =
      '<div class="empty-state">Could not load <code>data/latest.json</code>. Run <code>ftse-publish</code> after a screen, or wait for the weekly GitHub workflow.</div>';
  }
}

initTabs();
bindDashboardAutoRefresh();
bindMarketTileEqualize();
loadDashboard();
window.__loadDashboard = loadDashboard;
window.__reloadDashboard = reloadDashboard;
