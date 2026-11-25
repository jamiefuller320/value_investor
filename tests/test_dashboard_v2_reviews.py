"""Reviews tab: strategy-book closed episodes, not the legacy entry queues."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REVIEWS_JS = REPO / "docs" / "v2" / "reviews.js"
V2_INDEX = REPO / "docs" / "v2" / "index.html"

_LOAD = r"""
const fs = require("fs");
const vm = require("vm");
let tab = null;
global.window = {
  DashboardV2Tabs: { register(spec) { tab = spec; } },
};
global.document = undefined;
vm.runInThisContext(
  fs.readFileSync("docs/v2/reviews.js", "utf8"),
  { filename: "reviews.js" }
);
const api = global.window.__dashboardV2Reviews;
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


def test_reviews_js_does_not_load_legacy_entry_queues() -> None:
    text = REVIEWS_JS.read_text(encoding="utf-8")
    html = V2_INDEX.read_text(encoding="utf-8")
    assert "strategy_book_review_queue.json" in text
    assert "entry_blind_review_queue" not in text
    assert "entry_revisit_review_queue" not in text
    assert "post_sale_review_queue" not in text
    assert 'src="reviews.js?v=' in html
    assert "influences_live" not in text or "influencesLive" in text
    if shutil.which("node") is None:
        return
    subprocess.run(
        ["node", "--check", str(REVIEWS_JS)],
        cwd=str(REPO),
        check=True,
        capture_output=True,
        text=True,
    )


def test_review_view_counts_zero_and_renders_companion() -> None:
    payload = _node(r"""
const NOW = Date.parse("2026-11-17T20:47:00Z");
const helpers = {
  esc: function (s) { return String(s == null ? "" : s); },
  parseIsoMs: function (v) {
    const t = Date.parse(String(v || ""));
    return Number.isFinite(t) ? t : null;
  },
  nowMs: function () { return NOW; },
  displayDate: function (v) { return String(v); },
  ageLabelFromMs: function () { return "10h"; },
  freshnessDailyStore: function (msAge) {
    const h = msAge / 3600000;
    if (h <= 36) return { cls: "v2-badge v2-badge-fresh", label: "fresh" };
    if (h <= 72) return { cls: "v2-badge v2-badge-amber", label: "stale" };
    return { cls: "v2-badge v2-badge-red", label: "old" };
  },
  freshnessChartBar: function () { return { cls: "v2-badge v2-badge-fresh", label: "fresh" }; },
};
const queue = {
  generated_at: "2026-11-17T10:55:01Z",
  scoring_date: "2026-11-17",
  influences_live: false,
  observe_only: true,
  counts: {
    episodes: 114,
    closed: 4,
    primary: 0,
    companion: 1,
    active: 0,
    open_skipped: 110,
    provenance_missing: 0,
    missing: 0,
  },
  active: [],
  companion: [{
    review_id: "sp500:EXPD:buy_on_signal:2026-11-09",
    ticker: "EXPD",
    market: "sp500",
    column: "buy_on_signal",
    column_role: "control",
    attention: "companion",
    signal_session: "2026-11-09",
    fill_session: "2026-11-10",
    exit_session: "2026-11-13",
    exit_reason: "ineligible_runs",
    fair_cost_return_pct: 2.62,
    matched_excess_pct: 2.7,
    attribution: { label: "exit_rule", because: "registered_exit_family_fired", counts_as_evidence: true },
    provenance_missing: false,
    influences_live: false,
    levers: [{ id: "sell_timing", would_have_helped: "insufficient_data", because: "no_paired_close" }],
    cited_inputs: [{ path: "docs/data/charts/EXPD.json" }],
    hindsight: [{}],
  }],
};
const missing = api.reviewView(null);
const view = api.reviewView(queue);
const html = api.renderReviews({
  data: { strategy_book_review: { ok: true, data: queue } },
}, helpers);
const absent = api.renderReviews({ data: {} }, helpers);
console.log(JSON.stringify({
  missingEpisodes: missing.counts.episodes,
  active: view.counts.active,
  cause: api.causeLabel("exit_rule"),
  column: api.columnLabel("buy_on_signal"),
  pct: api.pctText(2.62, null),
  helped: api.helpedText("insufficient_data"),
  htmlHasExpeditors: html.includes("EXPD"),
  htmlHasCause: html.includes("Exit rule"),
  htmlHasZeroPrimary: html.includes(">0<"),
  htmlHasNoPrimarySentence: html.includes("No primary closes"),
  htmlBlocksLab: html.includes("lab and sealed-book queues"),
  htmlNoLegacyFile: !html.includes("entry_blind") && !html.includes("entry_revisit_review"),
  absentMeasured: absent.includes("not yet measured"),
  liveFalse: html.includes("do not influence live capital"),
}));
""")
    if payload.get("skipped"):
        return
    assert payload["missingEpisodes"] is None
    assert payload["active"] == 0
    assert payload["cause"] == "Exit rule"
    assert payload["column"] == "Buy on the signal"
    assert payload["pct"] == "+2.62%"
    assert payload["helped"] == "insufficient data"
    assert payload["htmlHasExpeditors"] is True
    assert payload["htmlHasCause"] is True
    assert payload["htmlHasZeroPrimary"] is True
    assert payload["htmlHasNoPrimarySentence"] is True
    assert payload["htmlBlocksLab"] is True
    assert payload["htmlNoLegacyFile"] is True
    assert payload["absentMeasured"] is True
    assert payload["liveFalse"] is True


def test_reviews_tab_shows_primary_learning_point_and_withholds_a_blank() -> None:
    payload = _node(r"""
const helpers = {
  esc: function (s) { return String(s == null ? "" : s); },
  parseIsoMs: function () { return null; },
  nowMs: function () { return 0; },
  displayDate: function (v) { return String(v || ""); },
  ageLabelFromMs: function () { return "0h"; },
  freshnessDailyStore: function () { return { cls: "v2-badge", label: "fresh" }; },
  freshnessChartBar: function () { return { cls: "v2-badge", label: "fresh" }; },
};
const queue = {
  generated_at: "2026-11-25T06:00:00Z",
  scoring_date: "2026-11-24",
  influences_live: false,
  observe_only: true,
  counts: { episodes: 2, closed: 2, primary: 2, companion: 0, active: 2, open_skipped: 0, provenance_missing: 0, missing: 0 },
  active: [{
    review_id: "nasdaq100:GOOG:primary:2026-11-19",
    ticker: "GOOG",
    market: "nasdaq100",
    column: "primary",
    column_role: "primary",
    attention: "primary",
    fill_session: "2026-11-20",
    exit_session: "2026-11-24",
    exit_reason: "thesis_break",
    fair_cost_return_pct: 4.415,
    matched_excess_pct: 0.378,
    attribution: { label: "thesis_break", because: "registered_thesis_break", counts_as_evidence: true },
    provenance_missing: false,
    influences_live: false,
    levers: [],
    cited_inputs: [],
    hindsight: [],
  }, {
    review_id: "ftse350:ZZZ.L:primary:2026-01-01",
    ticker: "ZZZ.L",
    market: "ftse350",
    column: "primary",
    column_role: "primary",
    attention: "primary",
    fill_session: "2026-01-02",
    exit_session: "2026-01-06",
    exit_reason: "thesis_break",
    fair_cost_return_pct: null,
    matched_excess_pct: null,
    attribution: { label: "insufficient_data", because: "exit_reason_or_return_missing", counts_as_evidence: false },
    provenance_missing: false,
    influences_live: false,
    levers: [],
    cited_inputs: [],
    hindsight: [],
  }],
  companion: [],
};
const notes = {
  influences_live: false,
  observe_only: true,
  counts: { notes: 2, grounded: 1, fail_closed: 1 },
  notes: [
    {
      episode_id: "nasdaq100:GOOG:primary:2026-11-19",
      learning_point_status: "grounded",
      learning_point: "GOOG: the registered thesis break fired on 2026-11-23 (sector verdict headwind).",
      missing_inputs: [],
    },
    {
      episode_id: "ftse350:ZZZ.L:primary:2026-01-01",
      learning_point_status: "insufficient_data",
      learning_point: null,
      missing_inputs: ["decision_log.reasons"],
    },
  ],
};
const html = api.renderReviews({
  data: {
    strategy_book_review: { ok: true, data: queue },
    strategy_book_post_sale_notes: { ok: true, data: notes },
  },
}, helpers);
const bare = api.renderReviews({
  data: { strategy_book_review: { ok: true, data: queue } },
}, helpers);
console.log(JSON.stringify({
  showsPoint: html.includes("sector verdict headwind"),
  showsWithheld: html.includes("Learning point withheld"),
  showsMissing: html.includes("decision_log.reasons"),
  notesDoNotInfluence: html.includes("Post-sale notes do not influence live capital"),
  noInventedWhenFileMissing: bare.includes("Learning point: not yet measured"),
  bareHasNoHeadwind: !bare.includes("headwind"),
  path: api.QUEUE_PATH,
}));
""")
    if payload.get("skipped"):
        return
    assert payload["showsPoint"] is True
    assert payload["showsWithheld"] is True
    assert payload["showsMissing"] is True
    assert payload["notesDoNotInfluence"] is True
    assert payload["noInventedWhenFileMissing"] is True
    assert payload["bareHasNoHeadwind"] is True


def test_review_queue_nan_tokens_parse_and_list_companion() -> None:
    """The published queue contains bare NaN. The loader must still show the rows.

    Companion length follows the published file. An inline two-row queue locks
    the list contract so a later queue refresh does not fail CI. influences_live
    stays false.
    """
    payload = _node(r"""
global.document = { readyState: "loading", addEventListener() {} };
vm.runInThisContext(fs.readFileSync("docs/v2/v2.js", "utf8"), { filename: "v2.js" });
const raw = fs.readFileSync("docs/data/strategy_book_review_queue.json", "utf8");
let parsed = null;
let error = "";
try {
  parsed = global.window.__dashboardV2ParseJson(raw);
} catch (err) {
  error = String(err && err.message ? err.message : err);
}
const view = parsed ? api.reviewView(parsed) : null;
const kept = global.window.__dashboardV2ParseJson('{"note":"NaN is a word","value": NaN}');
const fixtureRaw = '{"influences_live":false,"counts":{"companion":2,"active":0},"active":[],"companion":[{"review_id":"a","ticker":"AAA","fair_cost_return_pct":NaN},{"review_id":"b","ticker":"BBB","fair_cost_return_pct":1.5}]}';
const fixture = global.window.__dashboardV2ParseJson(fixtureRaw);
const fixtureView = api.reviewView(fixture);
console.log(JSON.stringify({
  error: error,
  companion: view ? view.companion.length : null,
  rawCount: parsed && Array.isArray(parsed.companion) ? parsed.companion.length : null,
  counted: parsed && parsed.counts ? parsed.counts.companion : null,
  active: view ? view.counts.active : null,
  activeCount: parsed && parsed.counts ? parsed.counts.active : null,
  influences: parsed ? parsed.influences_live : null,
  keptNote: kept.note,
  keptValue: kept.value,
  fixtureCompanion: fixtureView.companion.length,
  fixtureInfluences: fixture.influences_live,
  fixtureNan: fixture.companion[0].fair_cost_return_pct,
}));
""")
    if payload.get("skipped"):
        return
    assert payload["error"] == ""
    assert payload["rawCount"] >= 1
    assert payload["companion"] == payload["rawCount"]
    assert payload["companion"] == payload["counted"]
    assert payload["active"] == payload["activeCount"]
    assert payload["influences"] is False
    assert payload["keptNote"] == "NaN is a word"
    assert payload["keptValue"] is None
    assert payload["fixtureCompanion"] == 2
    assert payload["fixtureInfluences"] is False
    assert payload["fixtureNan"] is None
