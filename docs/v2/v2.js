/**
 * Strategy dashboard v2 (WP1) — plain browser JS; loads only named sidecar JSON files.
 * Fetch paths are relative to this page URL (/v2/ → ../data/...).
 */
(function () {
  "use strict";

  const V2_VERSION = "wp1-20261106";

  /** @type {Record<string, object>} */
  const pendingHumanTaskAcks = Object.create(null);
  let humanTasksBoardBase = null;

  const DATA_PATHS = {
    strategy_book_registration: "../data/strategy_book_registration.json",
    strategy_book_forward_status: "../data/strategy_book_forward_status.json",
    strategy_book_memo_job: "../data/strategy_book_memo_job.json",
    operating_decline_gate: "../data/operating_decline_gate.json",
    sector_headwind_gate: "../data/sector_headwind_gate.json",
    decision_input_inventory: "../data/decision_input_inventory.json",
    library_decision_input_inventory: "../data/library_decision_input_inventory.json",
    market_status: "../data/market_status.json",
    ops_status: "../data/ops_status.json",
    human_tasks_board: "../data/human_tasks_board.json",
    human_tasks_checklist: "../human_tasks_checklist.json",
    human_task_acks: "../data/human_task_acks.json",
    daily_focus: "../data/daily_focus.json",
  };

  const OPTIONAL_DATA_FILES = new Set(["strategy_book_forward_status.json"]);

  const PLACEHOLDER_TABS = [
    {
      id: "candidates",
      label: "Candidates",
      blurb:
        "Per-market funnel from screen buys through operating performance, sector soundness, input checks and short-term lows — with reasons per row.",
    },
    {
      id: "book",
      label: "Book",
      blurb:
        "Open trades: wait-to-launch, recovery holds, launched floor path, and how each position closed — from the forward book when live; replay labelled until then.",
    },
    {
      id: "proof",
      label: "Proof",
      blurb:
        "Thickness gate, fair-cost and matched-benchmark bars, Phase 3 proof checklist, and comparison rows for paper controls — results kept separate, not blended.",
    },
    {
      id: "reviews",
      label: "Reviews",
      blurb:
        "Post-sale, entry-blind and entry follow-up reviews tied to strategy-book episodes, with the same charts and bridge actions as the legacy dashboard.",
    },
  ];

  function esc(text) {
    const s = text == null ? "" : String(text);
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function tsQuery(path) {
    const joiner = path.includes("?") ? "&" : "?";
    return `${path}${joiner}t=${Date.now()}`;
  }

  /**
   * @param {string} path
   * @returns {Promise<{ ok: boolean, data: object | null, error?: string }>}
   */
  async function fetchJsonSafe(path) {
    const url = tsQuery(path);
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) {
        return { ok: false, data: null, error: `HTTP ${response.status}` };
      }
      const data = await response.json();
      return { ok: true, data };
    } catch (e) {
      const msg = e && e.message ? String(e.message) : String(e);
      return { ok: false, data: null, error: msg };
    }
  }

  function parseIsoMs(value) {
    if (!value) return null;
    const t = Date.parse(String(value));
    return Number.isFinite(t) ? t : null;
  }

  function ageLabelFromMs(ageMs) {
    if (ageMs == null || !Number.isFinite(ageMs)) return "not yet measured";
    const h = ageMs / 3600000;
    if (h < 24) return `${Math.round(h)}h`;
    const d = ageMs / 86400000;
    if (d < 14) return `${d.toFixed(1)}d`;
    return `${Math.round(d)}d`;
  }

  function freshnessDailyStore(msAge) {
    if (msAge == null || !Number.isFinite(msAge)) {
      return { cls: "v2-badge", label: "unknown" };
    }
    const h = msAge / 3600000;
    if (h <= 36) return { cls: "v2-badge v2-badge-fresh", label: "fresh" };
    if (h <= 72) return { cls: "v2-badge v2-badge-amber", label: "stale" };
    return { cls: "v2-badge v2-badge-red", label: "old" };
  }

  // The T212 catalogue refreshes weekly; ops flags it stale after 14 days.
  function freshnessWeeklyStore(msAge) {
    if (msAge == null || !Number.isFinite(msAge)) {
      return { cls: "v2-badge", label: "unknown" };
    }
    const d = msAge / 86400000;
    if (d <= 8) return { cls: "v2-badge v2-badge-fresh", label: "fresh" };
    if (d <= 14) return { cls: "v2-badge v2-badge-amber", label: "stale" };
    return { cls: "v2-badge v2-badge-red", label: "old" };
  }

  function displayDate(value) {
    const s = String(value || "");
    if (!/^\d{4}-\d{2}-\d{2}T/.test(s)) return s;
    const t = Date.parse(s);
    if (!Number.isFinite(t)) return s;
    return (
      new Date(t).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/London",
      }) + " UK time"
    );
  }

  function freshnessChartBar(msAge) {
    if (msAge == null || !Number.isFinite(msAge)) {
      return { cls: "v2-badge", label: "unknown" };
    }
    const d = msAge / 86400000;
    if (d <= 3) return { cls: "v2-badge v2-badge-fresh", label: "fresh" };
    if (d <= 7) return { cls: "v2-badge v2-badge-amber", label: "stale" };
    return { cls: "v2-badge v2-badge-red", label: "old" };
  }

  function nowMs() {
    return Date.now();
  }

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

  function overlayPendingHumanTaskAcks(acksStore) {
    const byId = Object.create(null);
    for (const row of (acksStore && acksStore.acks) || []) {
      if (!row || typeof row !== "object") continue;
      const id = String(row.task_id || "").trim();
      if (id) byId[id] = row;
    }
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
   * @param {{ human_tasks_board?: object, human_task_acks?: object }} bundle
   */
  function syncHumanTasksBoardOverlay(bundle) {
    const base = humanTasksBoardBase || bundle.human_tasks_board;
    if (!base || !Array.isArray(base.tasks)) return bundle;
    prunePendingHumanTaskAcksAgainstDurable(bundle.human_task_acks);
    const acksForBoard = overlayPendingHumanTaskAcks(bundle.human_task_acks);
    bundle.human_tasks_board = (acksForBoard.acks || []).length
      ? mergeHumanTaskAcksIntoBoard(JSON.parse(JSON.stringify(base)), acksForBoard)
      : JSON.parse(JSON.stringify(base));
    return bundle;
  }

  function applyOptimisticHumanTaskAck(payload, bundle) {
    rememberPendingHumanTaskAck(payload);
    return syncHumanTasksBoardOverlay(bundle);
  }

  function revertOptimisticHumanTaskAck(taskId, bundle) {
    clearPendingHumanTaskAck(taskId);
    return syncHumanTasksBoardOverlay(bundle);
  }

  function isLocalDashboardServe() {
    return location.hostname === "127.0.0.1" || location.hostname === "localhost";
  }

  function setHumanTaskStatusEl(button, text) {
    const row = button.closest(".v2-task-actions");
    const el = row && row.querySelector(".v2-task-status");
    if (el) el.textContent = text || "";
  }

  /**
   * Same JSON payload as the legacy dashboard human-task acknowledgement handler.
   * @param {HTMLButtonElement} button
   * @param {object} bundle mutable state bag with human_tasks_board, human_task_acks
   */
  async function acknowledgeHumanTaskFromButton(button, bundle, rerender) {
    if (!button || button.disabled) return;
    let payload = {};
    try {
      payload = JSON.parse(button.getAttribute("data-human-task-ack") || "{}");
    } catch {
      payload = {};
    }
    const taskId = String(payload.task_id || "").trim();
    if (!taskId) {
      setHumanTaskStatusEl(button, "Missing task id");
      return;
    }
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
    applyOptimisticHumanTaskAck(payload, bundle);
    setHumanTaskStatusEl(button, "Submitting…");
    rerender();
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
        setHumanTaskStatusEl(button, "Recorded locally");
        setHumanTaskStatusEl(button, "Sent");
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
        ? await queueFn("human-task-ack", payload, (msg) => setHumanTaskStatusEl(button, msg))
        : await window.DashboardBridge.submitCommand(
            "human-task-ack",
            payload,
            (msg) => setHumanTaskStatusEl(button, msg),
            { wait: false }
          );
      setHumanTaskStatusEl(button, "Sent — syncing…");
      const commandId = queued && queued.id;
      const waitFn =
        commandId && typeof window.DashboardBridge.waitForCommand === "function"
          ? window.DashboardBridge.waitForCommand.bind(window.DashboardBridge)
          : null;
      if (!waitFn) {
        setHumanTaskStatusEl(button, "Sent");
        return;
      }
      try {
        await waitFn(commandId, (msg) => setHumanTaskStatusEl(button, msg));
        setHumanTaskStatusEl(button, "Recorded");
      } catch (waitErr) {
        const msg = waitErr && waitErr.message ? waitErr.message : String(waitErr);
        if (/timed out/i.test(msg)) {
          setHumanTaskStatusEl(
            button,
            "Sent — git sync may still be pending (Run workflow to drain)"
          );
          return;
        }
        revertOptimisticHumanTaskAck(taskId, bundle);
        rerender();
        setHumanTaskStatusEl(button, msg);
        button.disabled = false;
        button.setAttribute("aria-disabled", "false");
      }
    } catch (err) {
      revertOptimisticHumanTaskAck(taskId, bundle);
      rerender();
      const msg = err && err.message ? err.message : String(err);
      setHumanTaskStatusEl(button, msg);
      button.disabled = false;
      button.setAttribute("aria-disabled", "false");
    }
  }

  function humanTaskBucketBadge(bucket, ack) {
    if (bucket === "new_info" || (ack && ack.stale)) {
      return '<span class="v2-badge v2-badge-amber" title="Analysis changed since last acknowledgement">new info</span>';
    }
    if (bucket === "acked" || (ack && ack.acked && !ack.stale)) {
      return '<span class="v2-badge">acknowledged</span>';
    }
    return '<span class="v2-badge v2-badge-amber">open</span>';
  }

  function renderHumanTaskCard(task) {
    const ack = task.ack || {};
    const analysis = task.analysis || {};
    const bucket = task.sort_bucket || (ack.stale ? "new_info" : ack.acked ? "acked" : "unacked");
    const docUrl = task.doc_url;
    const docLink = docUrl
      ? ` <a href="${esc(docUrl)}" target="_blank" rel="noopener">runbook</a>`
      : "";
    const bullets = Array.isArray(analysis.bullets) ? analysis.bullets : [];
    const bulletsHtml = bullets.length
      ? `<ul class="v2-muted" style="margin:0.35rem 0 0;padding-left:1.15rem">${bullets
          .map((b) => `<li>${esc(b)}</li>`)
          .join("")}</ul>`
      : '<p class="v2-muted" style="margin:0.35rem 0 0">No analysis snippet — open the runbook.</p>';
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
      ? `<button type="button" class="v2-btn v2-btn-primary human-task-approve-btn" data-human-task-ack="${esc(
          approvePayload
        )}" title="Observe-only approval record (does not auto-apply)">${esc(task.approval_label || "Approve")}</button>`
      : "";
    return `<details class="v2-task-card" data-task-id="${esc(task.id || "")}">
      <summary>
        <div class="v2-task-head">
          <strong>${esc(task.title || task.id || "Task")}</strong>
          ${humanTaskBucketBadge(bucket, ack)}
        </div>
        <span class="v2-muted">${esc(analysis.headline || task.summary || "")}</span>
      </summary>
      <div class="v2-task-body">
        <p style="margin:0 0 0.35rem">${esc(task.summary || "")}</p>
        ${analysis.headline ? `<p style="margin:0.35rem 0"><strong>${esc(analysis.headline)}</strong></p>` : ""}
        ${bulletsHtml}
        <p class="v2-muted" style="margin:0.5rem 0 0">${docLink}</p>
        <div class="v2-task-actions">
          <button type="button" class="v2-btn${ackEnabled ? " v2-btn-primary" : ""} human-task-ack-btn" data-human-task-ack="${esc(
            payload
          )}" ${ackEnabled ? "" : "disabled"} aria-disabled="${ackEnabled ? "false" : "true"}" title="${esc(
            ackEnabled ? "Record observe-only acknowledgement" : "Already acknowledged for this analysis"
          )}">${esc(ackLabel)}</button>
          ${approveBtn}
          <span class="v2-task-status" aria-live="polite"></span>
        </div>
        <p class="v2-muted" style="margin:0.65rem 0 0;font-size:0.82rem">Acknowledge and Approve are observe-only records — they do not auto-apply settings or capital.</p>
      </div>
    </details>`;
  }

  function collectLatestBars(memoJob) {
    const markets = memoJob && memoJob.markets;
    if (!markets || typeof markets !== "object") return { bars: [], minMs: null, maxMs: null };
    const bars = [];
    let minMs = null;
    let maxMs = null;
    for (const key of Object.keys(markets)) {
      const row = markets[key];
      if (!row || typeof row !== "object") continue;
      const lb = row.latest_bar;
      if (!lb) continue;
      const ms = parseIsoMs(lb);
      if (ms == null) continue;
      bars.push({ market: key, raw: String(lb), ms });
      minMs = minMs == null ? ms : Math.min(minMs, ms);
      maxMs = maxMs == null ? ms : Math.max(maxMs, ms);
    }
    bars.sort((a, b) => a.market.localeCompare(b.market));
    return { bars, minMs, maxMs };
  }

  function sumMemoSignals(memoJob) {
    const markets = memoJob && memoJob.markets;
    if (!markets || typeof markets !== "object") return null;
    let sig = 0;
    let memoNeeded = 0;
    let n = 0;
    for (const key of Object.keys(markets)) {
      const row = markets[key];
      if (!row || typeof row !== "object") continue;
      n += 1;
      const s = row.signals;
      const m = row.memo_needed;
      if (typeof s === "number" && Number.isFinite(s)) sig += s;
      if (typeof m === "number" && Number.isFinite(m)) memoNeeded += m;
    }
    if (!n) return null;
    return { sig, memoNeeded, markets: n };
  }

  function parseT212CatalogueFinding(summary) {
    const s = String(summary || "");
    const m = s.match(/fetched\s+([0-9]{4}-[0-9]{2}-[0-9]{2}T[^)\s]+)/i);
    const m2 = m || s.match(/([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+Z]+)/);
    return m2 ? m2[1].replace(/[.,;:]+$/, "") : null;
  }

  function findT212Finding(opsStatus) {
    const findings = (opsStatus && opsStatus.findings) || [];
    for (const f of findings) {
      if (!f || typeof f !== "object") continue;
      const t = String(f.title || "");
      if (t.toLowerCase().startsWith("trading 212")) return f;
    }
    return null;
  }

  function filterRelevantOpsFindings(opsStatus) {
    const findings = (opsStatus && opsStatus.findings) || [];
    const needles = ["decline gate", "sector headwind", "strategy book", "memo job", "trading 212"];
    return findings.filter((f) => {
      if (!f || typeof f !== "object") return false;
      const t = String(f.title || "").toLowerCase();
      return needles.some((n) => t.includes(n));
    });
  }

  function isFtseBuyTierRow(row) {
    if (!row || typeof row !== "object") return false;
    if (row.in_buy_tier === true) return true;
    const sig = String(row.signal || "").toLowerCase();
    return sig === "buy" || sig === "strong_buy";
  }

  function ftseInputQuality(inv) {
    const rows = (inv && inv.rows) || [];
    const buyRows = rows.filter(isFtseBuyTierRow);
    const total = buyRows.length;
    const checks = ["key_filing_bodies", "fcf_basis_bound", "overlay_bound", "memo_recent"];
    /** @type {Record<string, string[]>} */
    const fails = { key_filing_bodies: [], fcf_basis_bound: [], overlay_bound: [], memo_recent: [] };
    let passAll = 0;
    for (const row of buyRows) {
      let ok = true;
      for (const c of checks) {
        if (!row[c]) {
          ok = false;
          const tk = String(row.ticker || "").trim();
          if (tk) fails[c].push(tk);
        }
      }
      if (ok) passAll += 1;
    }
    return { passAll, total, fails, rows: buyRows.length };
  }

  function libraryInputQuality(inv) {
    const rows = (inv && inv.rows) || [];
    let passAll = 0;
    const fails = { key_filing_bodies: [], fcf_basis_bound: [], overlay_bound: [], memo_recent: [] };
    /** @type {Record<string, { total: number, pass: number }>} */
    const byMarket = Object.create(null);
    for (const row of rows) {
      if (row && row.all_four_green === true) passAll += 1;
      if (!row.key_filing_bodies) fails.key_filing_bodies.push(libraryRowLabel(row));
      if (!row.fcf_basis_bound) fails.fcf_basis_bound.push(libraryRowLabel(row));
      if (!row.overlay_bound) fails.overlay_bound.push(libraryRowLabel(row));
      if (!row.memo_recent) fails.memo_recent.push(libraryRowLabel(row));
      const mid = String((row && row.market_id) || "").trim() || "unknown";
      if (!byMarket[mid]) byMarket[mid] = { total: 0, pass: 0 };
      byMarket[mid].total += 1;
      if (row && row.all_four_green === true) byMarket[mid].pass += 1;
    }
    return { passAll, total: rows.length, fails, byMarket };
  }

  function libraryRowLabel(row) {
    const m = String(row.market_id || "").trim();
    const t = String(row.ticker || "").trim();
    if (m && t) return `${m}:${t}`;
    return t || m || "?";
  }

  function renderNav(activeId) {
    const tabs = [
      { id: "today", label: "Today", placeholder: false },
      { id: "inputs", label: "Inputs", placeholder: false },
      ...PLACEHOLDER_TABS.map((p) => ({ id: p.id, label: p.label, placeholder: true })),
    ];
    return tabs
      .map((t) => {
        if (t.placeholder) {
          return `<a class="v2-nav-link v2-nav-placeholder" href="#${esc(t.id)}" data-v2-nav="${esc(
            t.id
          )}" data-v2-placeholder="1">${esc(t.label)}</a>`;
        }
        const cls = t.id === activeId ? "v2-nav-active" : "";
        return `<a class="v2-nav-link ${cls}" href="#${esc(t.id)}" data-v2-nav="${esc(t.id)}">${esc(
          t.label
        )}</a>`;
      })
      .join("");
  }

  function renderPlaceholder(tab) {
    return `<section class="v2-panel v2-card" aria-labelledby="v2-ph-${esc(tab.id)}">
      <h2 id="v2-ph-${esc(tab.id)}">${esc(tab.label)}</h2>
      <p class="v2-muted" style="margin-top:0.5rem"><strong>Coming in the next build.</strong> ${esc(tab.blurb)}</p>
    </section>`;
  }

  /**
   * @param {object} ctx
   */
  function renderToday(ctx) {
    const reg = ctx.registration;
    const fwd = ctx.forwardStatus;
    const memoJob = ctx.memoJob;
    const decline = ctx.declineGate;
    const sector = ctx.sectorGate;
    const ftseInv = ctx.decisionInv;
    const libInv = ctx.libraryInv;
    const ops = ctx.opsStatus;
    const daily = ctx.dailyFocus;
    const board = ctx.bundle.human_tasks_board;

    const signedAt = reg && reg.signed_at;
    const spendOn = !!(reg && reg.spend_enabled);
    const forwardLive = !!(reg && reg.forward_live);
    const fwdLiveField = fwd && fwd.forward_live;
    const effectiveForwardLive =
      typeof fwdLiveField === "boolean" ? fwdLiveField && forwardLive : forwardLive;

    const memoBars = collectLatestBars(memoJob);
    const n = nowMs();
    const minAge = memoBars.minMs != null ? n - memoBars.minMs : null;
    const maxAge = memoBars.maxMs != null ? n - memoBars.maxMs : null;

    const mature = fwd && fwd.mature_count;
    const thicknessLine =
      typeof mature === "number" && Number.isFinite(mature)
        ? `${mature} of 48 counted mature episodes (cap 6 per entry week; strategy gate needs 48).`
        : "not yet measured";

    const dryRun = !!(fwd && fwd.dry_run);
    const bookMode = effectiveForwardLive
      ? "Live forward book"
      : dryRun
        ? "Observe-only dry run"
        : "Observe-only (forward book not live)";

    const signedLine = signedAt ? esc(displayDate(signedAt)) : "not yet available";

    let dailySourceMs = parseIsoMs(daily && daily.generated_at);
    const opsAt = parseIsoMs(ops && ops.run_at);
    if (dailySourceMs == null) dailySourceMs = opsAt;

    const declineAt = parseIsoMs(decline && (decline.as_of || decline.generated_at));
    const sectorAt = parseIsoMs(sector && (sector.as_of || sector.generated_at));
    const ftseAt = parseIsoMs(ftseInv && ftseInv.generated_at);
    const libAt = parseIsoMs(libInv && (libInv.generated_at || libInv.as_of));
    const memoAt = parseIsoMs(memoJob && (memoJob.generated_at || memoJob.last_run_at));

    const t212 = findT212Finding(ops);
    const t212Fetched = parseT212CatalogueFinding(t212 && t212.summary);
    const t212Ms = parseIsoMs(t212Fetched);

    const t212Age = t212Ms != null ? n - t212Ms : null;
    const dailyAge = dailySourceMs != null ? n - dailySourceMs : null;
    const declineAge = declineAt != null ? n - declineAt : null;
    const sectorAge = sectorAt != null ? n - sectorAt : null;
    const ftseAge = ftseAt != null ? n - ftseAt : null;
    const libAge = libAt != null ? n - libAt : null;
    const memoJobAge = memoAt != null ? n - memoAt : null;

    const chartAgeForBadge = maxAge != null ? maxAge : null;
    const chartBadge = freshnessChartBar(chartAgeForBadge);

    const pushBlock = (() => {
      const ps = daily && daily.push_suggestions;
      const list =
        ps && typeof ps === "object" && Array.isArray(ps.suggestions) ? ps.suggestions : null;
      if (!list || !list.length) {
        return '<p class="v2-muted">No push items for today (or not yet available).</p>';
      }
      return `<ul class="v2-push-list">${list
        .map((s) => {
          const title = esc(s.title || s.id || "Item");
          const why = esc(s.why_now || s.summary || "");
          return `<li><p class="v2-push-title">${title}</p><p class="v2-muted" style="margin:0">${why}</p></li>`;
        })
        .join("")}</ul>
        <p class="v2-muted" style="margin:0.75rem 0 0"><a href="../index.html#automation/daily">Open Daily hub on the engineering dashboard (Accept / Discuss)</a></p>`;
    })();

    const openTasks =
      board && Array.isArray(board.tasks)
        ? board.tasks.filter((t) => t.sort_bucket === "unacked" || t.sort_bucket === "new_info")
        : [];
    const tasksHtml = openTasks.length
      ? openTasks.map((t) => renderHumanTaskCard(t)).join("")
      : '<p class="v2-muted">No open owner tasks in the published board (or not yet available).</p>';

    function line(label, dateStr, ageMs, badgeFn) {
      const b = badgeFn(ageMs);
      const age = ageMs != null && Number.isFinite(ageMs) ? ageLabelFromMs(ageMs) : "not yet measured";
      const dlab = dateStr ? displayDate(dateStr) : "not yet available";
      return `<li><span><strong>${esc(label)}</strong> — ${esc(dlab)}</span> <span class="v2-muted">age ${esc(age)}</span> <span class="${esc(b.cls)}" title="Freshness rule for this source">${esc(b.label)}</span></li>`;
    }

    return `
      <section class="v2-panel">
        <div class="v2-card">
          <h2>Book status</h2>
          <p class="v2-panel-meta">Source: strategy book registration${signedAt ? "" : " — not yet available"}</p>
          <div class="v2-strip">
            <div class="v2-strip-item"><strong>Seal</strong><span>${reg && reg.signed ? "Signed" : "not yet available"}</span></div>
            <div class="v2-strip-item"><strong>Signed at</strong><span>${signedLine}</span></div>
            <div class="v2-strip-item"><strong>Forward book</strong><span>${esc(bookMode)}</span></div>
            <div class="v2-strip-item"><strong>Spend</strong><span>${spendOn ? "On" : "Off"}</span></div>
            <div class="v2-strip-item"><strong>Latest closes (charts)</strong><span>${
              memoBars.minMs != null && memoBars.maxMs != null
                ? `${esc(new Date(memoBars.minMs).toISOString().slice(0, 10))}–${esc(
                    new Date(memoBars.maxMs).toISOString().slice(0, 10)
                  )}`
                : "not yet available"
            }</span></div>
            <div class="v2-strip-item"><strong>Close bar age (min / max)</strong><span>${
              memoBars.minMs != null
                ? `${esc(ageLabelFromMs(minAge))} / ${esc(ageLabelFromMs(maxAge))}`
                : "not yet measured"
            }</span></div>
            <div class="v2-strip-item"><strong>Thickness progress</strong><span>${esc(thicknessLine)}</span></div>
          </div>
        </div>

        <div class="v2-card">
          <h2>Owner decisions due</h2>
          <p class="v2-panel-meta">Human tasks board${board && board.generated_at ? ` · ${esc(board.generated_at)}` : ""}</p>
          <div id="v2-human-tasks">${tasksHtml}</div>
        </div>

        <div class="v2-card">
          <h2>Today&apos;s push items</h2>
          <p class="v2-panel-meta">Daily focus${daily && daily.local_date ? ` · local date ${esc(daily.local_date)}` : ""}</p>
          ${pushBlock}
        </div>

        <div class="v2-card">
          <h2>Input freshness</h2>
          <p class="v2-panel-meta">Relative to this page load; chart bar uses the newest latest_bar across markets</p>
          <ul class="v2-freshness-list">
            ${line("Daily hub / push list", daily && daily.generated_at, dailyAge, freshnessDailyStore)}
            ${line("Operating performance gate", decline && (decline.as_of || decline.generated_at), declineAge, freshnessDailyStore)}
            ${line("Sector headwind gate", sector && (sector.as_of || sector.generated_at), sectorAge, freshnessDailyStore)}
            ${line("FTSE input inventory", ftseInv && ftseInv.generated_at, ftseAge, freshnessDailyStore)}
            ${line("Library input inventory", libInv && (libInv.generated_at || libInv.as_of), libAge, freshnessDailyStore)}
            ${line("Signal-day memo job", memoJob && (memoJob.generated_at || memoJob.last_run_at), memoJobAge, freshnessDailyStore)}
            ${line("Price charts (latest bar)", memoBars.maxMs != null ? String(memoBars.bars.find((b) => b.ms === memoBars.maxMs)?.raw || new Date(memoBars.maxMs).toISOString().slice(0, 10)) : null, chartAgeForBadge, () => chartBadge)}
            ${line(
              "Trading 212 catalogue (ops)",
              t212Fetched || (t212 && t212.summary) || null,
              t212Age,
              freshnessWeeklyStore
            )}
          </ul>
        </div>
      </section>`;
  }

  function renderInputs(ctx) {
    const ftseInv = ctx.decisionInv;
    const libInv = ctx.libraryInv;
    const decline = ctx.declineGate;
    const sector = ctx.sectorGate;
    const memoJob = ctx.memoJob;
    const ms = ctx.marketStatus;
    const ops = ctx.opsStatus;

    const ftse = ftseInputQuality(ftseInv);
    const lib = libraryInputQuality(libInv);

    const libMarketRows = Object.keys(lib.byMarket || {})
      .sort()
      .map((mid) => {
        const s = lib.byMarket[mid];
        return `<tr><td>${esc(mid)}</td><td>${esc(String(s.pass))}</td><td>${esc(String(s.total))}</td></tr>`;
      })
      .join("");

    const fiTitle =
      'title="Filing bodies, free-cash-flow basis, research overlay and a recent memo — four quality checks before names are decision-ready."';

    const ftseFailsHtml = ["key_filing_bodies", "fcf_basis_bound", "overlay_bound", "memo_recent"]
      .map((k) => {
        const arr = ftse.fails[k] || [];
        const label =
          k === "key_filing_bodies"
            ? "Filings have usable bodies"
            : k === "fcf_basis_bound"
              ? "Free cash flow basis bound"
              : k === "overlay_bound"
                ? "Research overlay bound"
                : "Recent research memo";
        return `<li><strong>${esc(label)}</strong> — failing: ${arr.length ? esc(arr.join(", ")) : "none"}</li>`;
      })
      .join("");

    const libFailsHtml = ["key_filing_bodies", "fcf_basis_bound", "overlay_bound", "memo_recent"]
      .map((k) => {
        const arr = lib.fails[k] || [];
        const label =
          k === "key_filing_bodies"
            ? "Filings have usable bodies"
            : k === "fcf_basis_bound"
              ? "Free cash flow basis bound"
              : k === "overlay_bound"
                ? "Research overlay bound"
                : "Recent research memo";
        const shown = arr.length > 24 ? `${arr.slice(0, 24).join(", ")}… (+${arr.length - 24})` : arr.join(", ");
        return `<li><strong>${esc(label)}</strong> — ${arr.length} failing${arr.length ? `: ${esc(shown)}` : ""}</li>`;
      })
      .join("");

    const ds = (decline && decline.summary) || {};
    const declineNames = ds.names;
    const declineLine =
      decline && typeof declineNames === "number"
        ? `Names: clear ${esc(String(ds.clear))}, declining ${esc(String(ds.declining))}, insufficient data ${esc(
            String(ds.insufficient_data)
          )} of ${esc(String(declineNames))}. As of ${esc(String(decline.as_of || decline.generated_at || "not yet available"))}.`
        : "not yet available";

    const ss = (sector && sector.summary) || {};
    const sectorLine =
      sector && typeof ss.sectors === "number"
        ? `Sectors: sound ${esc(String(ss.sound))}, headwind ${esc(String(ss.headwind))}, insufficient data ${esc(
            String(ss.insufficient_data)
          )} of ${esc(String(ss.sectors))}. As of ${esc(String(sector.as_of || sector.generated_at || "not yet available"))}.`
        : "not yet available";

    const sumSig = sumMemoSignals(memoJob);
    const memoSummary = sumSig
      ? `Across ${sumSig.markets} markets: signal-day hits ${esc(String(sumSig.sig))}, memo requests ${esc(
          String(sumSig.memoNeeded)
        )}. Spend ${memoJob && memoJob.spend_enabled ? "on" : "off"}. Last run ${esc(
          String(memoJob.last_run_at || memoJob.generated_at || "not yet available")
        )}.`
      : "not yet available";

    const markets = (ms && ms.markets) || [];
    const mrows = markets
      .map((m) => {
        const mid = esc(String(m.market_id || ""));
        const grad = m.is_graduated ? "Yes" : "No";
        const ing = m.ingest != null ? String(m.ingest) : "";
        return `<tr><td>${mid}</td><td>${esc(grad)}</td><td>${esc(ing)}</td></tr>`;
      })
      .join("");

    const rel = filterRelevantOpsFindings(ops);
    const opsRows = rel.length
      ? rel
          .map((f) => {
            return `<tr><td>${esc(f.title || "")}</td><td>${esc(f.severity || "")}</td><td>${esc(f.summary || "")}</td></tr>`;
          })
          .join("")
      : '<tr><td colspan="3">No matching findings (or not yet available).</td></tr>';

    return `
      <section class="v2-panel">
        <div class="v2-card">
          <h2 ${fiTitle}>Input quality</h2>
          <p class="v2-panel-meta">Investment-demanded checks on filings, cash-flow basis, overlay and memo recency</p>
          <h3>FTSE (screen buy tier)</h3>
          <p class="v2-kv"><strong>Pass all four</strong> — ${esc(String(ftse.passAll))} of ${esc(String(ftse.total || "not yet measured"))}</p>
          <ul class="v2-muted" style="margin:0.35rem 0 0;padding-left:1.1rem">${ftseFailsHtml}</ul>
          <h3>Library (graduated markets)</h3>
          <p class="v2-kv"><strong>Pass all four</strong> — ${esc(String(lib.passAll))} of ${esc(String(lib.total || "not yet measured"))}</p>
          <div class="v2-table-wrap">
            <table class="v2-table">
              <thead><tr><th>Market</th><th>Pass all four</th><th>Buy-tier rows</th></tr></thead>
              <tbody>${libMarketRows || '<tr><td colspan="3">not yet available</td></tr>'}</tbody>
            </table>
          </div>
          <p class="v2-panel-meta" style="margin-top:0.75rem">Failing tickers by check (aggregate)</p>
          <ul class="v2-muted" style="margin:0.35rem 0 0;padding-left:1.1rem">${libFailsHtml}</ul>
        </div>

        <div class="v2-card">
          <h2>Gate coverage</h2>
          <p class="v2-kv"><strong>Operating performance</strong> — ${declineLine}</p>
          <p class="v2-kv"><strong>Sector headwind</strong> — ${sectorLine}</p>
        </div>

        <div class="v2-card">
          <h2>Signal-day memo job</h2>
          <p class="v2-kv">${memoSummary}</p>
        </div>

        <div class="v2-card">
          <h2>Markets (ingest cascade)</h2>
          <p class="v2-panel-meta">${ms && ms.generated_at ? `Generated ${esc(ms.generated_at)}` : "not yet available"}</p>
          <div class="v2-table-wrap">
            <table class="v2-table">
              <thead><tr><th>Market</th><th>Graduated</th><th>Ingest state</th></tr></thead>
              <tbody>${mrows || '<tr><td colspan="3">not yet available</td></tr>'}</tbody>
            </table>
          </div>
        </div>

        <div class="v2-card">
          <h2>Relevant ops findings</h2>
          <p class="v2-panel-meta">${ops && ops.run_at ? `Ops run ${esc(ops.run_at)}` : ""}</p>
          <div class="v2-table-wrap">
            <table class="v2-table">
              <thead><tr><th>Title</th><th>Severity</th><th>Summary</th></tr></thead>
              <tbody>${opsRows}</tbody>
            </table>
          </div>
        </div>
      </section>`;
  }

  function parseHash() {
    const raw = (location.hash || "").replace(/^#/, "").trim();
    const tab = raw.split(/[/?]/)[0] || "today";
    const allowed = new Set(["today", "inputs", "candidates", "book", "proof", "reviews"]);
    return allowed.has(tab) ? tab : "today";
  }

  /**
   * @param {Record<string, ReturnType<typeof fetchJsonSafe> extends Promise<infer R> ? R : never>} results
   */
  function buildBundle(results) {
    const bundle = {
      human_tasks_board: results.human_tasks_board.ok ? results.human_tasks_board.data : null,
      human_task_acks: results.human_task_acks.ok ? results.human_task_acks.data : { acks: [] },
    };
    if (bundle.human_tasks_board) {
      humanTasksBoardBase = JSON.parse(JSON.stringify(bundle.human_tasks_board));
    }
    syncHumanTasksBoardOverlay(bundle);
    return bundle;
  }

  async function loadAll() {
    const keys = Object.keys(DATA_PATHS);
    /** @type {any} */
    const results = {};
    await Promise.all(
      keys.map(async (k) => {
        results[k] = await fetchJsonSafe(DATA_PATHS[k]);
      })
    );
    return results;
  }

  function updateObserveBanner(registration) {
    const el = document.getElementById("v2-observe-banner");
    if (!el) return;
    const forwardLive = !!(registration && registration.forward_live);
    if (forwardLive) {
      el.classList.add("v2-banner-hidden");
      el.innerHTML = "";
      return;
    }
    el.classList.remove("v2-banner-hidden");
    el.innerHTML =
      "<strong>Observe-only.</strong> The forward book is not live for capital — signals and dry-run counts are for review only.";
  }

  function mount() {
    const nav = document.getElementById("v2-nav");
    const root = document.getElementById("v2-root");
    const meta = document.getElementById("v2-meta");
    if (!nav || !root) return;

    /** @type {ReturnType<typeof buildBundle> | null} */
    let bundleRef = null;
    /** @type {Awaited<ReturnType<typeof loadAll>> | null} */
    let dataRef = null;

    function buildViewContext() {
      const dr = dataRef;
      const br = bundleRef;
      if (!dr || !br) return null;
      const registration = dr.strategy_book_registration.ok ? dr.strategy_book_registration.data : null;
      return {
        registration,
        forwardStatus: dr.strategy_book_forward_status.ok ? dr.strategy_book_forward_status.data : null,
        memoJob: dr.strategy_book_memo_job.ok ? dr.strategy_book_memo_job.data : null,
        declineGate: dr.operating_decline_gate.ok ? dr.operating_decline_gate.data : null,
        sectorGate: dr.sector_headwind_gate.ok ? dr.sector_headwind_gate.data : null,
        decisionInv: dr.decision_input_inventory.ok ? dr.decision_input_inventory.data : null,
        libraryInv: dr.library_decision_input_inventory.ok ? dr.library_decision_input_inventory.data : null,
        marketStatus: dr.market_status.ok ? dr.market_status.data : null,
        opsStatus: dr.ops_status.ok ? dr.ops_status.data : null,
        dailyFocus: dr.daily_focus.ok ? dr.daily_focus.data : null,
        bundle: br,
      };
    }

    function bindV2HumanTaskClicks(panelRoot) {
      panelRoot.querySelectorAll(".human-task-ack-btn, .human-task-approve-btn").forEach((btnEl) => {
        btnEl.addEventListener("click", (ev) => {
          ev.preventDefault();
          void acknowledgeHumanTaskFromButton(btnEl, bundleRef, async () => {
            if (parseHash() !== "today") return;
            const ctx = buildViewContext();
            if (!ctx) return;
            updateObserveBanner(ctx.registration);
            const tasksEl = document.getElementById("v2-human-tasks");
            if (tasksEl) {
              tasksEl.innerHTML = (() => {
                const board = ctx.bundle.human_tasks_board;
                const openTasks =
                  board && Array.isArray(board.tasks)
                    ? board.tasks.filter((t) => t.sort_bucket === "unacked" || t.sort_bucket === "new_info")
                    : [];
                return openTasks.length
                  ? openTasks.map((t) => renderHumanTaskCard(t)).join("")
                  : '<p class="v2-muted">No open owner tasks in the published board (or not yet available).</p>';
              })();
              bindV2HumanTaskClicks(tasksEl);
            }
          });
        });
      });
    }

    async function rerender() {
      const tab = parseHash();
      nav.innerHTML = renderNav(tab);
      nav.querySelectorAll("a[data-v2-nav]").forEach((a) => {
        a.addEventListener("click", () => {
          if (!a.hasAttribute("data-v2-placeholder")) {
            requestAnimationFrame(() => {
              void rerender();
            });
          }
        });
      });
      if (!dataRef || !bundleRef) {
        root.innerHTML = `<p class="v2-placeholder">Loading data…</p>`;
        return;
      }

      const ctx = buildViewContext();
      if (!ctx) return;
      updateObserveBanner(ctx.registration);

      if (tab === "today") {
        root.innerHTML = renderToday(ctx);
        const tasksHost = document.getElementById("v2-human-tasks");
        if (tasksHost) bindV2HumanTaskClicks(tasksHost);
      } else if (tab === "inputs") {
        root.innerHTML = renderInputs(ctx);
      } else {
        const ph = PLACEHOLDER_TABS.find((p) => p.id === tab);
        root.innerHTML = ph ? renderPlaceholder(ph) : renderToday(ctx);
        if (!ph) {
          const tasksHost = document.getElementById("v2-human-tasks");
          if (tasksHost) bindV2HumanTaskClicks(tasksHost);
        }
      }

      window.scrollTo(0, 0);
    }

    window.addEventListener("hashchange", () => {
      void rerender();
    });

    void (async () => {
      if (meta) meta.textContent = "Loading strategy data…";
      dataRef = await loadAll();
      bundleRef = buildBundle(dataRef);
      const okCount = Object.values(dataRef).filter((r) => r && r.ok).length;
      if (meta) {
        meta.textContent = `Strategy dashboard v2 · ${V2_VERSION} · ${okCount}/${Object.keys(DATA_PATHS).length} data files loaded`;
      }
      await rerender();
    })();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  // Tests and static analysis: exported path list (optional)
  window.__dashboardV2DataPaths = DATA_PATHS;
  window.__dashboardV2OptionalDataFiles = OPTIONAL_DATA_FILES;
})();
