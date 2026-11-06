"""Book and Proof tabs: missing, stale, and unblended replay summaries."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BOOK = REPO / "docs" / "v2" / "book.js"
PROOF = REPO / "docs" / "v2" / "proof.js"
DATA = REPO / "docs" / "data"
NOW = "2026-11-06T20:00:00Z"
RESULT_KEYS = (
    "archive_buy_tier_only",
    "archive_full_strategy",
    "lookahead_current_gates",
)

# Loads book.js then proof.js against the browser shim and prints one JSON report.
NODE = r"""
const fs = require("fs");
global.window = { DashboardV2Tabs: { register() {} } };
eval(fs.readFileSync(process.env.BOOK, "utf8"));
eval(fs.readFileSync(process.env.PROOF, "utf8"));
const api = global.window.__dashboardV2BookProof;
const NOW = Date.parse(process.env.NOW);
const dataDir = process.env.DATA;

function readJson(name) {
  return JSON.parse(fs.readFileSync(dataDir + "/" + name, "utf8"));
}

const empty = api.replayResults(null, NOW);
const reg = {
  signed_at: "2026-11-05T21:00:00Z",
  forward_live: false,
  step_3_2_proof_numbers: [
    { requirement: "Tail loss", bar: "no worse than -20%" },
  ],
};
const positiveArchive = {
  archive_full_strategy: {
    scoring_date: "2026-10-30",
    episode_count: 3,
    boards: {
      overall: { median_fair_cost: 0.05 },
      matched_excess: { median: 0.01 },
      thickness_gate: { counted: 3, min_counted: 48, ready: false },
    },
  },
};
const bars = api.proofChecklist(reg, positiveArchive);
const missingView = api.bookEpisodesView(null, null, "archive_full_strategy", NOW);
const three = {
  archive_buy_tier_only: {
    scoring_date: "2026-10-30",
    episode_count: 9,
    boards: {
      overall: { median_fair_cost: 0.5 },
      matched_excess: { median: 0.2 },
      thickness_gate: { counted: 16, min_counted: 48, ready: false },
    },
  },
  archive_full_strategy: {
    scoring_date: "2026-10-30",
    episode_count: 2,
    episodes: [
      {
        column: "primary", status: "open", launched: false, held_sessions: 10,
        ticker: "AAA", market: "ftse350", fill_session: "2026-10-01",
        reviews: [], recovery_label: true,
      },
      {
        column: "primary", status: "closed", launched: true,
        exit_reason: "floor_exit", held_sessions: 20, ticker: "BBB",
        market: "asx200", fill_session: "2026-08-01", exit_session: "2026-09-01",
        fair_cost_return: 0.08, floor: 0.05, highest_checkpoint: 0.1, reviews: [],
      },
      {
        column: "buy_on_signal", status: "open", launched: false,
        held_sessions: 1, ticker: "CCC", market: "ftse350",
      },
    ],
    boards: {
      overall: { median_fair_cost: 0.02 },
      capital_view: { recovery_hold_capital_share: null, recovery_share_line: 0.4 },
      floor_exits: { count: 1, median_fair_cost: 0.08 },
      fail_to_launch: { count: 0, median_fair_cost: null },
      thesis_breaks: { count: 0, median_fair_cost: null },
    },
  },
  lookahead_current_gates: {
    scoring_date: "2026-10-30",
    episode_count: 4,
    boards: {
      overall: { median_fair_cost: 0.01 },
      matched_excess: { median: -0.02 },
      thickness_gate: { counted: 15, min_counted: 48, ready: false },
    },
  },
};
const separate = api.replayResults(three, NOW);
const look = api.bookEpisodesView(null, three, "lookahead_current_gates", NOW);
const full = api.bookEpisodesView(null, three, "archive_full_strategy", NOW);
const stale = api.replayResults({
  archive_full_strategy: {
    scoring_date: "2020-01-01",
    episode_count: 1,
    boards: {
      overall: { median_fair_cost: 0.1 },
      thickness_gate: { counted: 1, min_counted: 48, ready: false },
    },
  },
}, NOW);
const staleControls = api.controlRows(null, {
  generated_at: "2020-01-01T00:00:00Z",
  tracks: [{
    track_id: "buy_tier_level",
    role: "active",
    label: "Strand A",
    total_return: null,
    marks: null,
  }],
}, NOW);
const noForward = api.thicknessProgress(null, null, NOW);

const replay = readJson("strategy_book_replay.json");
const registration = readJson("strategy_book_registration.json");
const scoreboard = readJson("assessment_scoreboard.json");
const trv = readJson("total_return_view.json");
const liveResults = api.replayResults(replay, NOW);
const liveThickness = api.thicknessProgress(replay, null, NOW);
const liveBars = api.proofChecklist(registration, replay);
const liveControls = api.controlRows(trv, scoreboard, NOW);

const helpers = {
  esc: (s) => String(s == null ? "" : s),
  tsQuery: (p) => p,
  displayDate: (v) => "DATE:" + v,
  ageLabelFromMs: () => "7d",
  freshnessDailyStore: () => ({ cls: "v2-badge v2-badge-fresh", label: "fresh" }),
  freshnessWeeklyStore: () => ({ cls: "v2-badge", label: "fresh" }),
  freshnessChartBar: () => ({ cls: "v2-badge v2-badge-red", label: "old" }),
  nowMs: () => NOW,
};
const ctx = {
  registration: registration,
  forwardStatus: null,
  data: {
    strategy_book_replay: { ok: true, data: replay },
    strategy_book_observe: { ok: false, data: null, error: "HTTP 404" },
    assessment_scoreboard: { ok: true, data: scoreboard },
    total_return_view: { ok: true, data: trv },
  },
};
const bookHtml = api.renderBook(ctx, helpers);
const proofHtml = api.renderProof(ctx, helpers);
const buy = liveResults.results.find((row) => row.key === "archive_buy_tier_only");

const report = {
  emptyTexts: empty.results.map((row) => row.medianFairCost.text),
  emptyWarning: empty.results.map((row) => row.lookaheadWarning),
  emptyBlended: empty.blended,
  emptyCombined: empty.combinedMedian,
  emptySummed: empty.summedEpisodeCount,
  bar: bars.bars[0],
  barStatus: bars.status,
  missingView: {
    status: missingView.status,
    forwardNote: missingView.forwardNote,
    source: missingView.source,
  },
  separateCounts: separate.results.map((row) => row.episodeCount),
  separateMedians: separate.results.map((row) => row.medianFairCost.value),
  separateWarnings: separate.results.map((row) => row.lookaheadWarning),
  separateBlended: separate.blended,
  lookMedian: look.medianFairCost.value,
  lookWarning: look.lookaheadWarning,
  lookEpisodes: look.episodes,
  waitingLeft: full.episodes.waiting[0].sessionsLeftOf63,
  floorExits: full.episodes.floorExit.length,
  waitingNames: full.episodes.waiting.map((row) => row.ticker),
  otherColumns: full.otherColumns,
  staleBand: stale.results.find((row) => row.key === "archive_full_strategy").freshness.band,
  staleMissing: stale.results.find((row) => row.key === "archive_buy_tier_only").medianFairCost.text,
  nullReturn: staleControls.rows[0].totalReturnText,
  nullKind: staleControls.rows[0].kind,
  staleControlBand: staleControls.freshness.band,
  forwardText: noForward.forward.text,
  forwardCounted: noForward.forward.counted,
  live: {
    thickness: Object.fromEntries(liveResults.results.map((row) => [row.key, liveThickness.byResult[row.key].counted])),
    medians: Object.fromEntries(liveResults.results.map((row) => [row.key, row.medianFairCost.value])),
    excess: Object.fromEntries(liveResults.results.map((row) => [row.key, row.medianMatchedExcess.value])),
    texts: Object.fromEntries(liveResults.results.map((row) => [row.key, {
      fair: row.medianFairCost.text,
      excess: row.medianMatchedExcess.text,
      thickness: row.thickness.text,
      verdict: row.thickness.verdict,
      episodes: row.episodeCount,
    }])),
    warnings: Object.fromEntries(liveResults.results.map((row) => [row.key, row.lookaheadWarning])),
    blended: liveResults.blended,
    summed: liveResults.summedEpisodeCount,
    bars: liveBars.bars.map((row) => ({ requirement: row.requirement, status: row.status, passed: row.passed })),
    barStatus: liveBars.status,
    controls: liveControls.rows.map((row) => ({
      kind: row.kind,
      role: row.roleLabel,
      label: row.label,
      total: row.totalReturnText,
      book: row.isStrategyBook,
    })),
    forward: liveThickness.forward.text,
  },
  html: {
    bookObserve: bookHtml.includes("Observe-only"),
    bookForward: bookHtml.includes("not yet written — forward book not live"),
    bookEmpty: bookHtml.includes("published an empty board"),
    bookDate: bookHtml.includes("DATE:"),
    bookLoad: bookHtml.includes("Load episode table"),
    proofObserve: proofHtml.includes("Observe-only"),
    proofPaper: proofHtml.includes("paper control"),
    proofMissing: proofHtml.includes("not yet measured"),
    proofLookahead: proofHtml.includes("gates dated after the trades"),
    proofBuy: proofHtml.includes("Buy tier only"),
    proofFull: proofHtml.includes("Full strategy"),
    proofBuyMedian: proofHtml.includes(buy.medianFairCost.text),
    proofDate: proofHtml.includes("DATE:"),
  },
};
console.log(JSON.stringify(report));
"""


def _node_bin() -> str:
    path = shutil.which("node")
    if path is None:
        raise RuntimeError("node is not on PATH")
    return path


def _report() -> dict:
    proc = subprocess.run(
        [_node_bin(), "-e", NODE],
        cwd=str(REPO),
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "BOOK": str(BOOK),
            "PROOF": str(PROOF),
            "DATA": str(DATA),
            "NOW": NOW,
        },
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def test_node_syntax_check() -> None:
    node = _node_bin()
    for path in (BOOK, PROOF):
        subprocess.run([node, "--check", str(path)], cwd=str(REPO), check=True)


def test_sources_do_not_load_latest_or_app() -> None:
    for path in (BOOK, PROOF):
        text = path.read_text(encoding="utf-8")
        assert "latest.json" not in text
        assert "app.js" not in text
        assert "episode table needs a newer browser" in BOOK.read_text(encoding="utf-8") or path == PROOF
    assert "DecompressionStream" in BOOK.read_text(encoding="utf-8")


def test_missing_stale_and_unblended_fixtures() -> None:
    report = _report()
    assert report["emptyTexts"] == ["not yet measured"] * 3
    assert report["emptyBlended"] is None
    assert report["emptyCombined"] is None
    assert report["emptySummed"] is None
    assert report["emptyWarning"][2]
    assert "after the trades" in report["emptyWarning"][2]
    assert report["emptyWarning"][0] is None
    assert report["emptyWarning"][1] is None

    bar = report["bar"]
    assert bar["status"] == "not yet measured"
    assert bar["passed"] is None
    assert bar["measured"] is None
    assert report["barStatus"] == "not yet measured"

    assert report["missingView"]["status"] == "not yet measured"
    assert report["missingView"]["forwardNote"] == "not yet written — forward book not live"
    assert report["missingView"]["source"] == "missing"
    assert report["forwardText"] == "not yet measured"
    assert report["forwardCounted"] is None

    assert report["separateCounts"] == [9, 2, 4]
    assert report["separateMedians"] == [0.5, 0.02, 0.01]
    assert report["separateBlended"] is None
    assert sum(report["separateCounts"]) != report["separateMedians"][0]
    assert report["lookMedian"] == 0.01
    assert report["lookEpisodes"] is None
    assert "after the trades" in report["lookWarning"]
    assert report["waitingLeft"] == 53
    assert report["floorExits"] == 1
    assert report["waitingNames"] == ["AAA"]
    assert "CCC" not in report["waitingNames"]
    assert report["otherColumns"]["buy_on_signal"] == 1

    assert report["staleBand"] == "old"
    assert report["staleMissing"] == "not yet measured"
    assert report["nullReturn"] != "0.00%"
    assert report["nullReturn"] != "0"
    assert "not yet" in report["nullReturn"] or "insufficient" in report["nullReturn"]
    assert report["nullKind"] == "paper control"
    assert report["staleControlBand"] == "old"


def test_live_stores_stay_separate_and_match_thickness() -> None:
    report = _report()["live"]
    replay = json.loads((DATA / "strategy_book_replay.json").read_text(encoding="utf-8"))
    registration = json.loads(
        (DATA / "strategy_book_registration.json").read_text(encoding="utf-8")
    )
    assert report["blended"] is None
    assert report["summed"] is None
    assert list(report["thickness"]) == list(RESULT_KEYS)
    for key in RESULT_KEYS:
        gate = replay[key]["boards"]["thickness_gate"]["counted"]
        median = replay[key]["boards"]["overall"]["median_fair_cost"]
        excess = replay[key]["boards"]["matched_excess"]["median"]
        assert report["thickness"][key] == gate
        assert report["medians"][key] == median
        assert report["excess"][key] == excess
    assert report["warnings"]["lookahead_current_gates"]
    assert "after the trades" in report["warnings"]["lookahead_current_gates"]
    assert report["warnings"]["archive_buy_tier_only"] is None
    assert report["warnings"]["archive_full_strategy"] is None
    assert report["barStatus"] == "not yet measured"
    assert len(report["bars"]) == len(registration["step_3_2_proof_numbers"])
    for bar in report["bars"]:
        assert bar["status"] == "not yet measured"
        assert bar["passed"] is not True
    assert report["forward"] == "not yet measured"
    assert report["controls"]
    for row in report["controls"]:
        assert row["kind"] == "paper control"
        assert row["book"] is False


def test_rendered_tabs_label_sources_and_gaps() -> None:
    html = _report()["html"]
    assert html["bookObserve"] is True
    assert html["bookForward"] is True
    assert html["bookEmpty"] is True
    assert html["bookDate"] is True
    assert html["bookLoad"] is True
    assert html["proofObserve"] is True
    assert html["proofPaper"] is True
    assert html["proofMissing"] is True
    assert html["proofLookahead"] is True
    assert html["proofBuy"] is True
    assert html["proofFull"] is True
    assert html["proofBuyMedian"] is True
    assert html["proofDate"] is True
