"""Candidates tab: join buy tier, gates and input quality without treating gaps as passes."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATES_JS = REPO / "docs" / "v2" / "candidates.js"
DOCS_DATA = REPO / "docs" / "data"

_LOAD = r"""
const fs = require("fs");
const vm = require("vm");
let tab = null;
global.window = {
  DashboardV2Tabs: { register(spec) { tab = spec; } },
};
global.document = undefined;
vm.runInThisContext(
  fs.readFileSync("docs/v2/candidates.js", "utf8"),
  { filename: "candidates.js" }
);
const api = global.window.__dashboardV2Candidates;
"""


def _node(body: str) -> dict:
    if shutil.which("node") is None:
        return {"skipped": True}
    script = _LOAD + body
    result = subprocess.run(
        ["node", "-e", script],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    return json.loads(result.stdout)


def test_candidates_js_syntax_and_boundaries() -> None:
    text = CANDIDATES_JS.read_text(encoding="utf-8")
    assert "latest.json" not in text
    assert "app.js" not in text
    assert "DashboardV2Tabs.register" in text
    assert "__dashboardV2Candidates" in text
    if shutil.which("node") is None:
        return
    subprocess.run(
        ["node", "--check", str(CANDIDATES_JS)],
        cwd=str(REPO),
        check=True,
        capture_output=True,
        text=True,
    )


def test_candidate_join_fixtures() -> None:
    payload = _node(r"""
const failures = [];
function check(cond, msg) {
  if (!cond) failures.push(msg);
}
function invRow(ticker, extra) {
  return Object.assign({
    ticker: ticker,
    name: ticker + " plc",
    in_buy_tier: true,
    signal: "buy",
    key_filing_bodies: true,
    fcf_basis_bound: true,
    overlay_bound: true,
    memo_recent: true,
    memo_at: "2026-11-01T00:00:00Z",
    memo_age_days: 5,
  }, extra || {});
}
function decline(verdict) {
  return {
    verdict: verdict,
    market: "ftse350",
    sector: "Industrials",
    checks: {
      revenue: {
        evaluable: true,
        fired: verdict === "declining",
        label: "Total Revenue",
        latest_year: 2025,
        change_pct: -0.2,
      },
    },
    reasons: [{ detail: "revenue fell" }],
  };
}
function sector(verdict) {
  return {
    sector: "Industrials",
    sector_verdict: verdict,
    deciding_sector_key: "ftse350:Industrials",
  };
}
const names = {
  "PASS.L": decline("clear"),
  "DEC.L": decline("declining"),
  "SEC.L": decline("clear"),
  "BIND.L": decline("clear"),
  "NOBIND.L": decline("clear"),
  "INSUF.L": decline("insufficient_data"),
  "LIB.AX": Object.assign(decline("clear"), { market: "asx200" }),
};
const sectorNames = {
  "PASS.L": sector("sound"),
  "DEC.L": sector("sound"),
  "SEC.L": sector("headwind"),
  "BIND.L": sector("sound"),
  "NOBIND.L": sector("sound"),
  "INSUF.L": sector("sound"),
};
const base = {
  marketStatus: {
    markets: [
      { market_id: "ftse350", label: "FTSE 350" },
      { market_id: "asx200", label: "S&P/ASX 200" },
    ],
  },
  decisionInv: {
    generated_at: "2026-11-06T00:00:00Z",
    rows: [
      invRow("PASS.L", { tradable_on_t212: true }),
      invRow("DEC.L", { tradable_on_t212: false }),
      invRow("SEC.L"),
      invRow("MISS.L"),
      invRow("BIND.L", { memo_recent: false, memo_age_days: 40 }),
      invRow("NOBIND.L", { overlay_bound: undefined }),
      invRow("INSUF.L"),
      { ticker: "HOLD.L", name: "Held", in_buy_tier: false, signal: "hold" },
    ],
  },
  libraryInv: {
    generated_at: "2026-11-06T00:00:00Z",
    rows: [{
      market_id: "asx200",
      ticker: "LIB.AX",
      name: "Library Co",
      signal: "strong_buy",
      key_filing_bodies: true,
      fcf_basis_bound: true,
      overlay_bound: true,
      memo_recent: true,
      memo_age_days: 3,
    }],
  },
  declineGate: {
    as_of: "2026-11-06",
    generated_at: "2026-11-06T00:00:00Z",
    names: names,
  },
  sectorGate: {
    as_of: "2026-11-06",
    generated_at: "2026-11-06T00:00:00Z",
    names_by_market: {
      ftse350: sectorNames,
      asx200: {
        "LIB.AX": { sector: "Banks", sector_verdict: "sound" },
      },
    },
    sectors: {
      "ftse350:Industrials": {
        verdict: "sound",
        metrics: {
          member_count: 4,
          as_of: "2026-11-06",
          price_below_sma200_share: 0.25,
          sector_return_126d: 0.01,
          earnings_declining_share: 0.1,
          operating_declining_share: 0.1,
        },
        reasons: [{ detail: "No broad headwind." }],
      },
    },
  },
  forwardStatus: null,
};
const rows = api.buildCandidateRows(base);
function row(ticker) {
  return rows.find(function (item) { return item.ticker === ticker; });
}
check(!rows.some(function (item) { return item.ticker === "HOLD.L"; }), "hold out");
const pass = row("PASS.L");
check(!!pass, "pass row");
check(pass.checks.cheap.status === "pass", "cheap");
check(pass.checks.decline.status === "pass", "decline");
check(pass.checks.sector.status === "pass", "sector");
check(pass.checks.inputs.status === "pass", "inputs");
check(pass.checks.entryLow.status === "pending", "entry pending");
check(pass.checks.entryLow.label === api.PENDING_ENTRY, "entry label");
check(pass.t212.label === "listed", "t212 listed");
check(api.passesEveryCheckSoFar(pass) === true, "so far");
check(row("DEC.L").checks.decline.status === "fail", "decline fail");
check(row("DEC.L").t212.label === "not listed", "t212 no");
check(api.passesEveryCheckSoFar(row("DEC.L")) === false, "blocked");
check(row("SEC.L").checks.sector.status === "fail", "sector fail");
check(row("SEC.L").t212.label === "not yet known", "t212 unknown");
check(row("MISS.L").checks.decline.status === "missing", "miss decline");
check(row("MISS.L").checks.sector.status === "missing", "miss sector");
check(row("MISS.L").checks.decline.status !== "pass", "miss not pass");
check(row("INSUF.L").checks.decline.label === "insufficient data", "insuff");
check(row("INSUF.L").checks.decline.status !== "pass", "insuff not pass");
const memo = row("BIND.L").detail.binds.find(function (b) {
  return b.key === "memo_recent";
});
check(row("BIND.L").checks.inputs.status === "fail", "memo fail");
check(memo && memo.status === "fail", "memo cited");
check(row("NOBIND.L").checks.inputs.status === "missing", "overlay missing");
check(row("NOBIND.L").checks.inputs.status !== "pass", "overlay not pass");
check(row("LIB.AX").market === "asx200", "library market");
check(row("LIB.AX").marketLabel === "S&P/ASX 200", "library label");
check(row("LIB.AX").checks.cheap.status === "pass", "library cheap");
check(row("PASS.L").detail.decline.lines.length > 0, "decline values");
check(row("PASS.L").detail.sector.lines.length > 0, "sector metrics");
const ftse = rows.filter(function (item) { return item.market === "ftse350"; });
check(ftse[0].ticker === "PASS.L", "sort " + (ftse[0] && ftse[0].ticker));
const funnel = api.funnelCounts(rows).ftse350;
check(funnel.buyTier === 7, "buy " + funnel.buyTier);
check(funnel.notDeclining === 4, "dec " + funnel.notDeclining);
check(funnel.sectorSound === 3, "sec " + funnel.sectorSound);
check(funnel.inputQuality === 1, "in " + funnel.inputQuality);
check(funnel.entryLow === api.NOT_MEASURED, "entry funnel");
const fwd = {
  generated_at: "2026-11-06T12:00:00Z",
  candidates_session_by_market: { ftse350: "2026-10-30" },
  candidates: [
    {
      market: "ftse350", ticker: "PASS.L", session: "2026-10-30",
      signal: "buy", adjusted_signal: "buy", decline: "clear",
      sector: "sound", gate_as_of: "2026-11-05", f9: "pass",
      price_rule: true, outcome: "filled",
    },
    {
      market: "ftse350", ticker: "DEC.L", session: "2026-10-30",
      signal: "buy", adjusted_signal: null, decline: "declining",
      sector: "sound", gate_as_of: "2026-11-05", f9: "pass",
      price_rule: false, outcome: "price",
    },
    {
      market: "ftse350", ticker: "SEC.L", session: null,
      signal: "buy", adjusted_signal: "buy", decline: null,
      sector: null, gate_as_of: null, f9: null,
      price_rule: null, outcome: "no_chart",
    },
    {
      market: "ftse350", ticker: "BIND.L", session: "2026-10-30",
      signal: "buy", adjusted_signal: "buy", decline: "clear",
      sector: "sound", gate_as_of: "2026-11-05",
      f9: ["memo_recent"], price_rule: true, outcome: "f9",
    },
  ],
};
const withFwd = Object.assign({}, base, { forwardStatus: fwd });
const rowsB = api.buildCandidateRows(withFwd);
function rowB(ticker) {
  return rowsB.find(function (item) { return item.ticker === ticker; });
}
check(rowB("PASS.L").checks.entryLow.status === "pass", "low pass");
check(rowB("PASS.L").detail.entryText.indexOf("would have been filled") !== -1, "filled words");
check(rowB("DEC.L").checks.entryLow.status === "fail", "low fail");
check(rowB("DEC.L").detail.entryText.indexOf("short-term low") !== -1, "price words");
check(rowB("SEC.L").checks.entryLow.status === "missing", "no chart");
check(rowB("SEC.L").detail.entryText.toLowerCase().indexOf("chart") !== -1, "chart words");
check(rowB("MISS.L").checks.entryLow.status === "missing", "off roster");
check(rowB("MISS.L").checks.entryLow.status !== "pass", "off roster not pass");
check(rowB("BIND.L").detail.entryText.indexOf("Memo freshness") !== -1, "f9 words");
const measured = api.funnelCounts(
  rowsB.filter(function (item) { return item.market === "ftse350"; })
);
check(typeof measured.ftse350.entryLow === "number", "entry number");
const codes = [
  "filled", "pending_fill", "late_signal", "memo_not_ready",
  "memo_blocked", "gap_drop", "already_open_skip", "cooldown_skip",
  "no_chart", "no_session_on_or_after_start", "gate", "price", "f9",
  "learning_pool_excluded", "not_in_book_screen", "not_buy_tier",
  "recovery_cap", "research_failed",
];
codes.forEach(function (code) {
  const label = api.outcomeLabel(code);
  check(label && label !== code && label.length > 8, "label " + code);
});
const levels = api.screenPlanLevels({
  last: 1, stop_loss: 2, take_profit: 3, sma50: 4,
});
check(levels.stop_loss == null && levels.take_profit == null, "no exits");
check(levels.last === 1 && levels.sma50 === 4, "keeps screen levels");
const bare = api.buildCandidateRows({
  decisionInv: { rows: [invRow("SOLO.L")] },
  libraryInv: { rows: [] },
  declineGate: null,
  sectorGate: null,
  forwardStatus: null,
  marketStatus: null,
});
check(bare[0].checks.decline.source === "absent", "decline absent");
check(bare[0].checks.decline.status !== "pass", "decline not pass");
check(bare[0].checks.sector.status !== "pass", "sector not pass");
check(bare[0].checks.entryLow.label === api.PENDING_ENTRY, "solo pending");
const bareFunnel = api.funnelCounts(bare).ftse350;
check(bareFunnel.notDeclining === api.NOT_MEASURED, "funnel gap");
check(bareFunnel.entryLow === api.NOT_MEASURED, "funnel entry");
check(bareFunnel.buyTier === 1, "solo buy");
const helpers = {
  esc: function (value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  },
  displayDate: function (value) { return String(value || ""); },
  parseIsoMs: function (value) {
    const parsed = Date.parse(String(value || ""));
    return Number.isFinite(parsed) ? parsed : null;
  },
  nowMs: function () { return Date.parse("2026-11-06T12:00:00Z"); },
  ageLabelFromMs: function () { return "1h"; },
  freshnessDailyStore: function () {
    return { cls: "v2-badge v2-badge-fresh", label: "fresh" };
  },
  freshnessWeeklyStore: function () {
    return { cls: "v2-badge", label: "unknown" };
  },
  freshnessChartBar: function () {
    return { cls: "v2-badge", label: "unknown" };
  },
  fetchJsonSafe: async function () { return { ok: false, data: null }; },
  tsQuery: function (path) { return path; },
};
const html = tab.render(base, helpers);
check(html.indexOf("pending forward job") !== -1, "renders pending");
check(html.indexOf("not yet measured") !== -1, "renders unmeasured");
check(html.indexOf("latest.json") === -1, "no latest");
check(html.indexOf("observe-only") !== -1, "observe only");
check(typeof tab.bind === "function", "bind");
if (failures.length) {
  console.log(JSON.stringify({ ok: false, failures: failures }));
  process.exit(1);
}
console.log(JSON.stringify({ ok: true, failures: [] }));
""")
    if payload.get("skipped"):
        return
    assert payload["ok"] is True
    assert payload["failures"] == []


def test_candidate_join_against_real_stores() -> None:
    for name in (
        "operating_decline_gate.json",
        "sector_headwind_gate.json",
        "decision_input_inventory.json",
        "library_decision_input_inventory.json",
        "market_status.json",
    ):
        assert (DOCS_DATA / name).is_file(), name
    payload = _node(r"""
function load(name) {
  const path = "docs/data/" + name;
  return JSON.parse(fs.readFileSync(path, "utf8"));
}
const decline = load("operating_decline_gate.json");
const sector = load("sector_headwind_gate.json");
const inv = load("decision_input_inventory.json");
const lib = load("library_decision_input_inventory.json");
const marketStatus = load("market_status.json");
const rows = api.buildCandidateRows({
  declineGate: decline,
  sectorGate: sector,
  decisionInv: inv,
  libraryInv: lib,
  forwardStatus: null,
  marketStatus: marketStatus,
});
const ftse = rows.filter(function (row) { return row.market === "ftse350"; });
let falsePass = 0;
const missingDecline = [];
const missingSector = [];
const storedElsewhere = [];
rows.forEach(function (row) {
  const d = decline.names[row.ticker];
  if (!d) missingDecline.push(row.market + ":" + row.ticker);
  else if (d.market !== row.market) {
    storedElsewhere.push(row.market + ":" + row.ticker + "@" + d.market);
  }
  if ((!d || d.verdict !== "clear") && row.checks.decline.status === "pass") {
    falsePass += 1;
  }
  const bucket = (sector.names_by_market || {})[row.market] || {};
  const s = bucket[row.ticker];
  if (!s) missingSector.push(row.market + ":" + row.ticker);
  const sectorOk = s && s.sector_verdict === "sound";
  if (!sectorOk && row.checks.sector.status === "pass") falsePass += 1;
  ["key_filing_bodies", "fcf_basis_bound", "overlay_bound", "memo_recent"]
    .forEach(function (key) {
      if (row.bindFlags[key] !== true && row.checks.inputs.status === "pass") {
        falsePass += 1;
      }
    });
  if (row.checks.entryLow.label !== api.PENDING_ENTRY) falsePass += 1;
  if (row.checks.entryLow.status === "pass") falsePass += 1;
  const signal = String(row.signal || "").toLowerCase();
  const cheapOk = signal === "buy" || signal === "strong_buy";
  if (!cheapOk && row.checks.cheap.status === "pass") falsePass += 1;
});
const funnels = api.funnelCounts(rows);
const summary = {};
Object.keys(funnels).forEach(function (market) {
  const item = funnels[market];
  summary[market] = {
    label: item.label,
    listed: item.listed,
    buyTier: item.buyTier,
    notDeclining: item.notDeclining,
    sectorSound: item.sectorSound,
    inputQuality: item.inputQuality,
    entryLow: item.entryLow,
  };
});
const euro = [];
Object.keys(decline.names).forEach(function (ticker) {
  const entry = decline.names[ticker];
  const signal = String(entry.signal || "");
  if (entry.market !== "euro_depth") return;
  if (signal !== "buy" && signal !== "strong_buy") return;
  euro.push(ticker);
});
const t212 = { listed: 0, notListed: 0, unknown: 0 };
rows.forEach(function (row) {
  if (row.t212.status === "listed") t212.listed += 1;
  else if (row.t212.status === "not_listed") t212.notListed += 1;
  else t212.unknown += 1;
});
console.log(JSON.stringify({
  ok: falsePass === 0 && ftse.length > 0,
  ftseBuy: ftse.length,
  falsePass: falsePass,
  rows: rows.length,
  missingDecline: missingDecline,
  missingSector: missingSector,
  storedElsewhere: storedElsewhere.length,
  euroDepthBuyNotInInventory: euro.length,
  t212: t212,
  funnels: summary,
}));
if (falsePass !== 0 || ftse.length === 0) process.exit(1);
""")
    if payload.get("skipped"):
        return
    assert payload["ftseBuy"] > 0
    assert payload["falsePass"] == 0
    ftse = payload["funnels"]["ftse350"]
    assert ftse["buyTier"] > 0
    assert ftse["entryLow"] == "not yet measured"
    artifact = Path("/opt/cursor/artifacts")
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "candidates-funnel.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
