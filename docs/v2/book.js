/* Strategy dashboard v2 — Book tab (WP3).
 * Pure summaries live on window.__dashboardV2BookProof so Proof and tests share them.
 * Page-relative sidecar JSON only. The legacy dashboard bundle is not loaded.
 */
(function () {
  "use strict";

  const RESULT_ORDER = [
    "archive_buy_tier_only",
    "archive_full_strategy",
    "lookahead_current_gates",
  ];
  const DEFAULT_RESULT = "archive_full_strategy";
  const THICKNESS_MIN = 48;
  const RECOVERY_LINE = 0.4;
  const FAIL_TO_LAUNCH = 63;
  const REVIEW_INDEXES = [63, 126, 189];
  const PAGE_SIZE = 25;
  const EPISODE_PATH = "../data/strategy_book_replay_episodes.json.gz";
  const FORWARD_NOTE = "not yet written — forward book not live";
  const LOOKAHEAD_WARNING =
    "This result uses gates dated after the trades. It is report-only and is not averaged with the other two results.";

  const RESULT_COPY = {
    archive_buy_tier_only: {
      label: "Buy tier only",
      detail:
        "Historical buy tier, the short-term-low entry, and the floor exit. No operating-decline gate and no sector gate. A rehearsal of timing, not the full strategy.",
    },
    archive_full_strategy: {
      label: "Full strategy",
      detail:
        "Buy tier, short-term-low entry, floor exit, plus a decline verdict and a sector verdict dated before each trade. Published empty until those dated verdicts exist.",
    },
    lookahead_current_gates: {
      label: "Today's gates painted back",
      detail: "Today's gate verdicts painted backward onto older trades.",
    },
  };

  const TIPS = {
    fairCost:
      "Fair-cost episode %: cohort median return per trade after fair trading costs, not a fund value.",
    matched:
      "Matched excess: a trade's return minus holding an equal-weight basket of the same market's buy tier over the same dates.",
    mature:
      "Mature episode: the fill is at least 63 sessions old, so the trade has either closed or reached +10%.",
    thickness:
      "Thickness gate: at least 48 counted mature episodes on the forward book, at most 6 per entry week. Archive episodes do not count.",
    recovery:
      "Recovery hold: an 8% drop before the trade reaches +10%. The label does not sell. The share of capital in these holds is reported against a 40% line.",
    thesis:
      "Thesis break: operating decline, a sector headwind, a screen avoid signal, or research saying pass. It ends the position.",
    floor:
      "Checkpoint ladder: after a close at +10%, a profit floor ratchets up. A close at or below the floor sells.",
    bench:
      "Challenger bench: up to four sealed variants scored on the same entries. One that clears its bar can be promoted at a version review.",
    shadow:
      "Gate-rejected shadow: entries the operating-decline or sector gate refused, scored as if bought, so the gates themselves are tested.",
    selection:
      "Selection board: entries ranked into fifths by a snapshot feature, with launch rate and return per fifth.",
    observe:
      "Observe-only: evidence for review. It does not move live capital or apply changes by itself.",
    strand:
      "Strand A: the main FTSE paper-trading path. No real money is invested. It is a control, not this book.",
    buyOnSignal:
      "Buy-on-signal control: buys when a name becomes eligible, with no short-term-low test, and holds about 63 sessions. Asks whether timing adds anything.",
    leaveTier:
      "Leave-tier control: sells when the name leaves the buy tier. That is how the older paper books exit. This strategy does not.",
    strategyBook:
      "Strategy book: the cold-start book that runs the seven-part strategy. It is the only route to live capital.",
    paper:
      "Paper control: an older simulated book kept for comparison. It is not the strategy book and it is not added to the book's results.",
  };

  const FEATURE_LABELS = {
    composite_score: "Screen score",
    signal_rank: "Rank inside the buy tier",
    weeks_at_signal: "Weeks already at this signal",
    conviction_score: "Conviction score",
    models_passed: "Models passed",
    data_quality_score: "Data quality score",
    fcf_yield: "Free-cash-flow yield",
    ev_ebit: "Enterprise value / EBIT",
    earnings_yield_pe: "Earnings yield",
    roic_proxy: "Return on capital",
    profit_margins: "Profit margin",
    debt_to_equity: "Debt to equity",
    revenue_growth: "Revenue growth",
    earnings_growth: "Earnings growth",
    market_cap: "Market cap",
    vol_60: "60-session volatility",
    close_vs_sma200: "Close versus the 200-session average",
    fall_from_high_252: "Fall from the one-year high",
    return_126: "126-session return",
    range_pos_126: "Position in the 126-session range",
    return_20: "20-session return",
    rsi_14: "RSI (14 sessions)",
    memo_age_days: "Research memo age",
    ch126_slope_pct_yr: "6-month channel slope",
    ch126_r2: "6-month channel fit",
    ch126_z: "Position in the 6-month channel",
    ch126_lower: "6-month channel lower band",
    ch126_upper: "6-month channel upper band",
    ch252_slope_pct_yr: "12-month channel slope",
    ch252_r2: "12-month channel fit",
    ch252_z: "Position in the 12-month channel",
    ch252_lower: "12-month channel lower band",
    ch252_upper: "12-month channel upper band",
    bb20_pct_b: "Bollinger %B (20 sessions)",
    bb20_width_pct: "Bollinger band width",
    dc20_pos: "Position in the 20-session range",
    dc55_pos: "Position in the 55-session range",
    support_dist_pct: "Distance from support",
    resistance_dist_pct: "Distance from resistance",
    sma50_dist_pct: "Distance from the 50-session average",
    sma200_dist_pct: "Distance from the 200-session average",
    hi252_dist_pct: "Distance from the one-year high",
    lo252_dist_pct: "Distance from the one-year low",
  };

  const BENCH_LABELS = {
    deep_dip: "Deeper dip — signal close at least 8% under the close 20 sessions earlier",
    revenue_growing: "Revenue still growing on the latest annual change",
    fcf_agrees: "Cash-flow check also calls the name cheap",
  };

  const MARKET_LABELS = {
    ftse350: "FTSE 350",
    asx200: "ASX 200",
    aex: "AEX",
    aim: "AIM",
    atx: "ATX",
    bel20: "BEL 20",
    cac40: "CAC 40",
    dax: "DAX",
    euro_stoxx50: "EURO STOXX 50",
    ftse_mib: "FTSE MIB",
    ftse_smallcap: "FTSE Small Cap",
    hang_seng: "Hang Seng",
    ibex35: "IBEX 35",
    iseq20: "ISEQ 20",
    nasdaq100: "Nasdaq 100",
    omxs30: "OMX Stockholm 30",
    psi20: "PSI 20",
    sp500: "S&P 500",
    tsx60: "TSX 60",
    smi: "SMI",
    sti: "Straits Times",
    us_adr_asia: "US-listed Asia names",
    euro_depth: "Euro depth",
  };

  const EXIT_LABELS = {
    floor_exit: "Floor exit",
    fail_to_launch: "Sold at the 63-session wait",
    thesis_break: "Thesis break",
    time_cap: "Time cap (252 sessions)",
    review_insufficient_data: "Review found insufficient data",
    review_cap: "Sold at the review cap",
    swing_high: "Sold at the short-term high",
    recovery_target: "Sold back at the entry price",
    hold_63: "Held for 63 sessions",
    ineligible_runs: "Left the eligible set",
  };

  const THESIS_REASONS = {
    declining: "Operating decline",
    headwind: "Sector headwind",
    screen_avoid: "Screen says avoid",
    research_failed: "Research says pass",
    unspecified: "Reason not recorded",
  };

  const state = {
    bookResult: DEFAULT_RESULT,
    proofResult: DEFAULT_RESULT,
    episodePayload: null,
    episodeError: null,
    episodeLoading: false,
    episodePage: 1,
    episodeFilter: "waiting",
    selectionFeature: "",
    pageSize: PAGE_SIZE,
  };

  function isObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function num(value) {
    if (value == null || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function parseMs(value) {
    if (!value) return null;
    const t = Date.parse(String(value));
    return Number.isFinite(t) ? t : null;
  }

  function normalizeKey(key) {
    return RESULT_ORDER.indexOf(key) >= 0 ? key : DEFAULT_RESULT;
  }

  function marketLabel(id) {
    const key = String(id || "");
    if (MARKET_LABELS[key]) return MARKET_LABELS[key];
    if (!key) return "Unknown market";
    return key.replace(/_/g, " ");
  }

  function featureLabel(key) {
    if (FEATURE_LABELS[key]) return FEATURE_LABELS[key];
    return String(key || "Feature").replace(/_/g, " ");
  }

  function formatPct(value, withSign) {
    const n = Number(value) * 100;
    if (!Number.isFinite(n)) return "insufficient data";
    const body = Math.abs(n).toFixed(2) + "%";
    if (n < 0) return "−" + body;
    if (withSign && n > 0) return "+" + body;
    return body;
  }

  function formatCount(value) {
    const n = num(value);
    if (n == null) return "insufficient data";
    return String(Math.round(n));
  }

  /**
   * Missing source → "not yet measured". Present source, null metric → "insufficient data".
   * A stored number, including 0, is shown as that number.
   */
  function metric(value, kind, sourcePresent) {
    if (!sourcePresent) {
      return { state: "missing", value: null, text: "not yet measured" };
    }
    const n = num(value);
    if (n == null) {
      return { state: "insufficient", value: null, text: "insufficient data" };
    }
    if (kind === "pct") return { state: "value", value: n, text: formatPct(n, true) };
    if (kind === "share") return { state: "value", value: n, text: formatPct(n, false) };
    if (kind === "count") return { state: "value", value: n, text: formatCount(n) };
    return { state: "value", value: n, text: String(n) };
  }

  function freshness(iso, nowMs, rule) {
    const ms = parseMs(iso);
    if (ms == null) {
      return { band: "unknown", label: "unknown", ageMs: null, iso: iso || null };
    }
    const age = (nowMs == null ? Date.now() : nowMs) - ms;
    let band = "old";
    if (rule === "daily") {
      const hours = age / 3600000;
      band = hours <= 36 ? "fresh" : hours <= 72 ? "stale" : "old";
    } else if (rule === "weekly") {
      const days = age / 86400000;
      band = days <= 8 ? "fresh" : days <= 14 ? "stale" : "old";
    } else {
      const days = age / 86400000;
      band = days <= 3 ? "fresh" : days <= 7 ? "stale" : "old";
    }
    return { band: band, label: band, ageMs: age, iso: String(iso) };
  }

  function slot(ctx, key) {
    const row = ctx && ctx.data && ctx.data[key];
    if (!row || row.ok !== true || !isObject(row.data)) return null;
    return row.data;
  }

  function resultPresent(replay, key) {
    return isObject(replay) && isObject(replay[key]);
  }

  function thicknessOf(result, sourcePresent) {
    const gate = isObject(result) && isObject(result.boards) ? result.boards.thickness_gate : null;
    if (!sourcePresent || !isObject(gate)) {
      return {
        counted: null,
        minCounted: THICKNESS_MIN,
        matureEpisodes: null,
        ready: null,
        spanSessions: null,
        spanMet: null,
        cap: 6,
        text: "not yet measured",
        verdict: "not yet measured",
        state: "missing",
      };
    }
    const counted = num(gate.counted);
    const minCounted = num(gate.min_counted);
    const ready = gate.ready === true ? true : gate.ready === false ? false : null;
    const min = minCounted == null ? THICKNESS_MIN : minCounted;
    return {
      counted: counted,
      minCounted: min,
      matureEpisodes: num(gate.mature_episodes),
      ready: ready,
      spanSessions: num(gate.span_sessions),
      spanMet: gate.span_met === true ? true : gate.span_met === false ? false : null,
      cap: num(gate.cap) == null ? 6 : num(gate.cap),
      provenanceExcluded: num(gate.provenance_missing_excluded),
      text: counted == null ? "insufficient data" : formatCount(counted) + " of " + formatCount(min),
      verdict: ready === true ? "met" : counted == null ? "insufficient data" : "not met",
      state: counted == null ? "insufficient" : "value",
      archiveDoesNotCount: true,
    };
  }

  function overallMedian(result, sourcePresent) {
    const overall = isObject(result) && isObject(result.boards) ? result.boards.overall : null;
    return metric(overall && overall.median_fair_cost, "pct", sourcePresent && isObject(overall));
  }

  function excessMedian(result, sourcePresent) {
    const board = isObject(result) && isObject(result.boards) ? result.boards.matched_excess : null;
    return metric(board && board.median, "pct", sourcePresent && isObject(board));
  }

  function summariseResult(replay, key, nowMs) {
    const copy = RESULT_COPY[key];
    const present = resultPresent(replay, key);
    const result = present ? replay[key] : null;
    const scoringDate = present ? result.scoring_date || result.generated_at || null : null;
    const episodeCount = present ? num(result.episode_count) : null;
    if (present && episodeCount == null && Array.isArray(result.episodes)) {
      /* full payload, summary field not yet added */
    }
    const count = present
      ? episodeCount != null
        ? episodeCount
        : Array.isArray(result.episodes)
          ? result.episodes.length
          : null
      : null;
    return {
      key: key,
      label: copy.label,
      detail: copy.detail,
      present: present,
      scoringDate: scoringDate,
      freshness: freshness(scoringDate, nowMs, "chart"),
      episodeCount: count,
      episodeCountText: present ? (count == null ? "insufficient data" : formatCount(count)) : "not yet measured",
      publishedEmpty: present && count === 0,
      medianFairCost: overallMedian(result, present),
      medianMatchedExcess: excessMedian(result, present),
      thickness: thicknessOf(result, present),
      lookaheadWarning: key === "lookahead_current_gates" ? LOOKAHEAD_WARNING : null,
    };
  }

  function replayResults(replay, nowMs) {
    const clock = nowMs == null ? Date.now() : nowMs;
    return {
      results: RESULT_ORDER.map(function (key) {
        return summariseResult(replay, key, clock);
      }),
      blended: null,
      combinedMedian: null,
      summedEpisodeCount: null,
    };
  }

  function thicknessProgress(replay, forwardStatus, nowMs) {
    const clock = nowMs == null ? Date.now() : nowMs;
    const results = replayResults(replay, clock).results;
    const byResult = {};
    results.forEach(function (row) {
      byResult[row.key] = row.thickness;
    });
    let forward;
    if (!isObject(forwardStatus)) {
      forward = {
        status: "not yet measured",
        counted: null,
        matureCount: null,
        ready: null,
        minCounted: THICKNESS_MIN,
        text: "not yet measured",
        note: FORWARD_NOTE,
      };
    } else {
      const counted = num(forwardStatus.counted);
      const matureCount = num(forwardStatus.mature_count);
      const ready = forwardStatus.thickness_ready === true
        ? true
        : forwardStatus.thickness_ready === false
          ? false
          : null;
      forward = {
        status: counted == null && matureCount == null ? "not yet measured" : "measured",
        counted: counted,
        matureCount: matureCount,
        ready: ready,
        minCounted: THICKNESS_MIN,
        text: counted == null ? "not yet measured" : formatCount(counted) + " of " + THICKNESS_MIN,
        note: counted == null
          ? "The forward status has no capped count toward 48."
          : "Counted on the forward book.",
      };
    }
    return { forward: forward, byResult: byResult, blended: null };
  }

  function measurementFor(measurements, requirement) {
    if (!measurements) return null;
    const rows = Array.isArray(measurements)
      ? measurements
      : Array.isArray(measurements.bars)
        ? measurements.bars
        : [];
    for (let i = 0; i < rows.length; i += 1) {
      if (rows[i] && rows[i].requirement === requirement) return rows[i];
    }
    return null;
  }

  function proofChecklist(registration, replay) {
    const bars = registration && Array.isArray(registration.step_3_2_proof_numbers)
      ? registration.step_3_2_proof_numbers
      : [];
    if (!bars.length) {
      return {
        status: "not yet measured",
        bars: [],
        signedAt: registration && registration.signed_at ? registration.signed_at : null,
        note: "Sealed proof bars are not in the registration store.",
      };
    }
    const measurements = (registration && registration.step_3_2_measurements)
      || (replay && replay.step_3_2_measurements)
      || null;
    const out = bars.map(function (bar) {
      const found = measurementFor(measurements, bar && bar.requirement);
      const measured = found && (found.value != null ? found.value : found.measured);
      const hasValue = !(measured == null || measured === "");
      if (!hasValue || found.passed === true && measured == null) {
        return {
          requirement: bar.requirement || "Proof bar",
          bar: bar.bar || "not yet measured",
          measured: null,
          status: "not yet measured",
          passed: null,
        };
      }
      const passed = found.passed === true ? true : found.passed === false ? false : null;
      return {
        requirement: bar.requirement || "Proof bar",
        bar: bar.bar || "",
        measured: measured,
        status: passed === true ? "met" : passed === false ? "not met" : "measured",
        passed: passed,
      };
    });
    const anyPassed = out.some(function (row) {
      return row.passed === true;
    });
    const allMeasured = out.every(function (row) {
      return row.status !== "not yet measured";
    });
    return {
      status: !allMeasured ? "not yet measured" : anyPassed && out.every(function (row) { return row.passed === true; }) ? "met" : "measured",
      bars: out,
      signedAt: registration.signed_at || null,
      note: "Phase 3 reads the forward book. An archive replay is not a measurement of these bars.",
    };
  }

  function paperRole(track) {
    const id = String((track && track.track_id) || "");
    if (id === "buy_tier_level") return "strand A";
    if (id === "buy_tier_level_dca") return "strand A deposit twin";
    if (track && track.role === "primary") return "assessment primary";
    if (track && track.role === "control") return "matched control";
    return "paper book";
  }

  function controlRowFromTrack(track) {
    const total = metric(track.total_return, "pct", true);
    const excess = metric(track.excess_total_return, "pct", "excess_total_return" in track);
    const marks = metric(track.marks, "count", "marks" in track);
    return {
      kind: "paper control",
      isStrategyBook: false,
      trackId: track.track_id || null,
      role: track.role || null,
      roleLabel: paperRole(track),
      label: track.label || paperRole(track),
      totalReturn: total.value,
      totalReturnText: total.text,
      excessTotalReturn: excess.value,
      excessText: excess.state === "missing" ? "not yet measured" : excess.text,
      marks: marks.value,
      marksText: marks.state === "missing" ? "not yet measured" : marks.text,
      asOf: track.end || track.as_of || null,
      source: "assessment scoreboard",
    };
  }

  function controlRows(trv, scoreboard, nowMs) {
    const clock = nowMs == null ? Date.now() : nowMs;
    if (!isObject(scoreboard) && !isObject(trv)) {
      return {
        status: "not yet measured",
        rows: [],
        generatedAt: null,
        trvUpdatedAt: null,
        freshness: freshness(null, clock, "daily"),
      };
    }
    const rows = [];
    const seen = {};
    const tracks = isObject(scoreboard) && Array.isArray(scoreboard.tracks) ? scoreboard.tracks : [];
    tracks.forEach(function (track) {
      if (!isObject(track)) return;
      const id = String(track.track_id || "");
      if (id) seen[id] = true;
      rows.push(controlRowFromTrack(track));
    });
    const twins = isObject(scoreboard) && Array.isArray(scoreboard.twins) ? scoreboard.twins : [];
    twins.forEach(function (twin) {
      if (!isObject(twin)) return;
      const id = String(twin.track_id || "");
      if (id && seen[id]) return;
      rows.push({
        kind: "paper control",
        isStrategyBook: false,
        trackId: id || null,
        role: "twin",
        roleLabel: "twin",
        label: twin.label || "Paper twin",
        totalReturn: num(twin.twin_return),
        totalReturnText: num(twin.twin_return) == null ? "not yet measured" : formatPct(twin.twin_return, true),
        excessTotalReturn: null,
        excessText: "not yet measured",
        marks: num(twin.common_days),
        marksText: num(twin.common_days) == null ? "not yet measured" : formatCount(twin.common_days) + " common days",
        asOf: twin.window_end || null,
        source: "assessment scoreboard",
      });
    });
    if (!rows.length && isObject(trv) && isObject(trv.tracks)) {
      Object.keys(trv.tracks).forEach(function (id) {
        const track = trv.tracks[id];
        if (!isObject(track)) return;
        const excess = num(track.published_excess_after_costs);
        rows.push({
          kind: "paper control",
          isStrategyBook: false,
          trackId: id,
          role: null,
          roleLabel: paperRole({ track_id: id }),
          label: paperRole({ track_id: id }),
          totalReturn: null,
          totalReturnText: "not yet measured",
          excessTotalReturn: excess,
          excessText: excess == null ? "not yet measured" : formatPct(excess, true),
          marks: null,
          marksText: "not yet measured",
          asOf: null,
          source: "total return view",
        });
      });
    }
    const generatedAt = isObject(scoreboard) ? scoreboard.generated_at || null : null;
    const trvUpdatedAt = isObject(trv) ? trv.updated_at || null : null;
    return {
      status: rows.length ? "measured" : "not yet measured",
      rows: rows,
      generatedAt: generatedAt,
      trvUpdatedAt: trvUpdatedAt,
      freshness: freshness(generatedAt || trvUpdatedAt, clock, "daily"),
    };
  }

  function capitalView(result) {
    return isObject(result) && isObject(result.boards) && isObject(result.boards.capital_view)
      ? result.boards.capital_view
      : null;
  }

  function recoveryHoldOf(result, sourcePresent, nowMs) {
    const capital = capitalView(result);
    const present = sourcePresent && isObject(capital);
    const latest = metric(capital && capital.recovery_hold_capital_share, "share", present);
    const lineRaw = present ? num(capital.recovery_share_line) : null;
    const line = lineRaw == null ? RECOVERY_LINE : lineRaw;
    const series = present && Array.isArray(capital.recovery_hold_share_series)
      ? capital.recovery_hold_share_series
      : null;
    return {
      latest: latest.value,
      latestText: latest.text,
      line: line,
      lineText: formatPct(line, false),
      series: series && series.length ? series : null,
      seriesText: series && series.length ? "measured" : "not yet measured",
      scoringDate: sourcePresent && result ? result.scoring_date || result.generated_at || null : null,
      freshness: freshness(
        sourcePresent && result ? result.scoring_date || result.generated_at || null : null,
        nowMs,
        "chart"
      ),
    };
  }

  function exitBoard(result, sourcePresent, boardKey) {
    const board = isObject(result) && isObject(result.boards) ? result.boards[boardKey] : null;
    const present = sourcePresent && isObject(board);
    return {
      count: metric(board && board.count, "count", present),
      medianFairCost: metric(board && board.median_fair_cost, "pct", present),
      byReason: present && isObject(board.by_reason) ? board.by_reason : null,
      shareBelowFill: metric(board && board.share_below_fill, "share", present && board.share_below_fill != null),
      matureOnly: true,
    };
  }

  function checkpointText(episode) {
    if (!episode.launched) return "Not launched — waiting to reach +10%";
    const checkpoint = num(episode.highest_checkpoint);
    const floor = num(episode.floor);
    if (checkpoint == null && floor == null) return "Launched — checkpoint not yet measured";
    const reached = checkpoint == null ? "checkpoint not yet measured" : "+" + Math.round(checkpoint * 100) + "% reached";
    const floorText = floor == null ? "floor not yet measured" : "floor +" + Math.round(floor * 100) + "%";
    return reached + ", " + floorText;
  }

  function reviewText(episode) {
    const held = num(episode.held_sessions);
    const reviews = Array.isArray(episode.reviews) ? episode.reviews : [];
    if (!episode.launched) {
      return {
        text: "Reviews apply after +10%. Until then the 63-session wait is the clock.",
        reviews: reviews,
      };
    }
    if (held == null) return { text: "not yet measured", reviews: reviews };
    const next = REVIEW_INDEXES.filter(function (index) {
      return index > held;
    })[0];
    if (next == null) {
      return { text: "Past the last review at session 189. The time cap is session 252.", reviews: reviews };
    }
    return {
      text: "Next review at session " + next + " (" + (next - held) + " sessions away).",
      reviews: reviews,
    };
  }

  function slimEpisode(episode) {
    const launched = episode.launched === true;
    const held = num(episode.held_sessions);
    const sessionsLeft = launched || held == null ? null : Math.max(0, FAIL_TO_LAUNCH - held);
    const reason = episode.exit_reason || null;
    return {
      ticker: episode.ticker || "",
      market: episode.market || "",
      marketLabel: marketLabel(episode.market),
      status: episode.status || null,
      launched: launched,
      fillSession: episode.fill_session || null,
      exitSession: episode.exit_session || null,
      sessionsHeld: held,
      sessionsLeftOf63: sessionsLeft,
      sessionsLeftText: launched
        ? "Launched — the 63-session wait does not apply"
        : held == null
          ? "not yet measured"
          : String(sessionsLeft) + " sessions left of 63",
      checkpointText: checkpointText(episode),
      floor: num(episode.floor),
      highestCheckpoint: num(episode.highest_checkpoint),
      reviewText: reviewText(episode).text,
      reviews: Array.isArray(episode.reviews) ? episode.reviews : [],
      recoveryLabel: episode.recovery_label === true,
      exitReason: reason,
      exitLabel: reason ? EXIT_LABELS[reason] || reason.replace(/_/g, " ") : null,
      fairCost: num(episode.fair_cost_return),
      fairCostText: num(episode.fair_cost_return) == null ? "insufficient data" : formatPct(episode.fair_cost_return, true),
      entryWeek: episode.entry_week || null,
    };
  }

  function groupEpisodes(episodes) {
    const grouped = {
      waiting: [],
      launched: [],
      floorExit: [],
      failToLaunch: [],
      thesisBreak: [],
      other: [],
      pending: [],
    };
    const otherColumns = {};
    (episodes || []).forEach(function (episode) {
      if (!isObject(episode)) return;
      const column = episode.column || "primary";
      if (column !== "primary") {
        otherColumns[column] = (otherColumns[column] || 0) + 1;
        return;
      }
      const slim = slimEpisode(episode);
      if (episode.status === "pending_fill") {
        grouped.pending.push(slim);
        return;
      }
      if (episode.status !== "closed") {
        if (slim.launched) grouped.launched.push(slim);
        else grouped.waiting.push(slim);
        return;
      }
      if (episode.exit_reason === "floor_exit") grouped.floorExit.push(slim);
      else if (episode.exit_reason === "fail_to_launch") grouped.failToLaunch.push(slim);
      else if (episode.exit_reason === "thesis_break") grouped.thesisBreak.push(slim);
      else grouped.other.push(slim);
    });
    grouped.waiting.sort(function (a, b) {
      return (a.sessionsLeftOf63 == null ? 999 : a.sessionsLeftOf63) - (b.sessionsLeftOf63 == null ? 999 : b.sessionsLeftOf63);
    });
    grouped.launched.sort(function (a, b) {
      return (b.floor == null ? -1 : b.floor) - (a.floor == null ? -1 : a.floor);
    });
    return { groups: grouped, otherColumns: otherColumns };
  }

  function isObserveStore(value) {
    return isObject(value) && !RESULT_ORDER.some(function (key) { return key in value; })
      && (Array.isArray(value.episodes) || isObject(value.boards));
  }

  function bookEpisodesView(forwardStatus, replay, resultKey, nowMs) {
    const clock = nowMs == null ? Date.now() : nowMs;
    const key = normalizeKey(resultKey);
    const forwardLive = !!(isObject(forwardStatus) && forwardStatus.forward_live === true);
    const useForward = isObserveStore(replay) && (forwardLive || (isObject(forwardStatus) && forwardStatus.wrote_observe === true) || replay.forward_live === true);
    const header = {
      forwardLive: forwardLive,
      forwardNote: useForward ? null : FORWARD_NOTE,
      resultKey: useForward ? null : key,
      blended: null,
      combinedMedian: null,
    };
    if (!useForward && !resultPresent(replay, key)) {
      return Object.assign(header, {
        source: isObject(replay) ? "replay" : "missing",
        status: "not yet measured",
        label: RESULT_COPY[key].label,
        detail: RESULT_COPY[key].detail,
        lookaheadWarning: key === "lookahead_current_gates" ? LOOKAHEAD_WARNING : null,
        scoringDate: null,
        freshness: freshness(null, clock, "chart"),
        episodeCount: null,
        publishedEmpty: false,
        recoveryHold: recoveryHoldOf(null, false, clock),
        closedMature: {
          floorExit: exitBoard(null, false, "floor_exits"),
          failToLaunch: exitBoard(null, false, "fail_to_launch"),
          thesisBreak: exitBoard(null, false, "thesis_breaks"),
        },
        episodes: null,
        otherColumns: null,
      });
    }
    const result = useForward ? replay : replay[key];
    const present = true;
    const grouped = Array.isArray(result.episodes) ? groupEpisodes(result.episodes) : null;
    const count = num(result.episode_count);
    const episodeCount = count != null ? count : grouped ? result.episodes.length : null;
    return Object.assign(header, {
      source: useForward ? "forward" : "replay",
      status: "measured",
      label: useForward ? "Forward book" : RESULT_COPY[key].label,
      detail: useForward
        ? "Episodes walked forward from the seal. Not an archive replay."
        : RESULT_COPY[key].detail,
      lookaheadWarning: !useForward && key === "lookahead_current_gates" ? LOOKAHEAD_WARNING : null,
      scoringDate: result.scoring_date || result.generated_at || null,
      freshness: freshness(result.scoring_date || result.generated_at || null, clock, "chart"),
      episodeCount: episodeCount,
      publishedEmpty: episodeCount === 0,
      medianFairCost: overallMedian(result, present),
      medianMatchedExcess: excessMedian(result, present),
      recoveryHold: recoveryHoldOf(result, present, clock),
      closedMature: {
        floorExit: exitBoard(result, present, "floor_exits"),
        failToLaunch: exitBoard(result, present, "fail_to_launch"),
        thesisBreak: exitBoard(result, present, "thesis_breaks"),
      },
      episodes: grouped ? grouped.groups : null,
      otherColumns: grouped ? grouped.otherColumns : null,
      alsoReportedSeparately: useForward ? RESULT_ORDER.slice() : RESULT_ORDER.filter(function (item) { return item !== key; }),
    });
  }

  function paginate(rows, page, pageSize) {
    const list = Array.isArray(rows) ? rows : [];
    const size = pageSize > 0 ? pageSize : PAGE_SIZE;
    const pages = Math.max(1, Math.ceil(list.length / size) || 1);
    const current = Math.min(Math.max(1, page || 1), pages);
    const start = (current - 1) * size;
    return { page: current, pages: pages, total: list.length, rows: list.slice(start, start + size) };
  }

  function filteredEpisodes(view, filter) {
    if (!view || !view.episodes) return [];
    const groups = view.episodes;
    if (filter === "waiting") return groups.waiting;
    if (filter === "launched") return groups.launched;
    if (filter === "floor") return groups.floorExit;
    if (filter === "wait63") return groups.failToLaunch;
    if (filter === "thesis") return groups.thesisBreak;
    if (filter === "other") return groups.other;
    if (filter === "open") return groups.waiting.concat(groups.launched);
    if (filter === "closed") return groups.floorExit.concat(groups.failToLaunch, groups.thesisBreak, groups.other);
    return groups.waiting.concat(groups.launched, groups.floorExit, groups.failToLaunch, groups.thesisBreak, groups.other);
  }

  function boardsOf(replay, key) {
    if (!resultPresent(replay, key)) return null;
    return isObject(replay[key].boards) ? replay[key].boards : null;
  }

  function pairedExits(replay, key) {
    const boards = boardsOf(replay, key);
    const present = isObject(boards) && isObject(boards.paired_exits);
    function one(id, label, question) {
      const row = present ? boards.paired_exits[id] : null;
      const rowPresent = present && isObject(row);
      return {
        id: id,
        label: label,
        question: question,
        count: metric(row && row.n, "count", rowPresent),
        medianDifference: metric(row && row.median_difference, "pct", rowPresent),
        meanDifference: metric(row && row.mean_difference, "pct", rowPresent),
        standardError: metric(row && row.standard_error, "pct", rowPresent),
        sharePrimaryBetter: metric(row && row.share_primary_better, "share", rowPresent && row.share_primary_better != null),
      };
    }
    return [
      one("draft_v0_exit", "First-draft exit", "Is the floor better than selling the short-term high?"),
      one("ladder_no_deadline", "Floor without the 63-session wait", "What does the 63-session deadline add?"),
    ];
  }

  function benchRows(replay, key) {
    const boards = boardsOf(replay, key);
    const bench = boards && isObject(boards.bench) ? boards.bench : null;
    const ids = bench ? Object.keys(bench) : ["deep_dip", "revenue_growing", "fcf_agrees"];
    return ids.map(function (id) {
      const row = bench && isObject(bench[id]) ? bench[id] : null;
      const present = !!row;
      const bar = present && isObject(row.promotion_bar) ? row.promotion_bar : null;
      const counted = metric(row && row.counted_mature, "count", present);
      const difference = metric(row && row.mean_difference, "pct", present);
      const empty = present && counted.value === 0 && difference.state !== "value";
      return {
        id: id,
        label: BENCH_LABELS[id] || featureLabel(id),
        kept: metric(row && row.kept, "count", present),
        counted: counted,
        meanDifference: difference,
        standardError: metric(row && row.standard_error, "pct", present),
        minCounted: bar && num(bar.min_counted) != null ? num(bar.min_counted) : THICKNESS_MIN,
        verdict: !present ? "not yet measured" : empty ? "insufficient data" : bar && bar.met === true ? "met" : "not met",
        passed: present && bar && bar.met === true ? true : null,
      };
    });
  }

  function shadowRows(replay, key) {
    const boards = boardsOf(replay, key);
    const shadows = boards && isObject(boards.shadows) ? boards.shadows : null;
    return [
      ["decline_rejected_shadow", "Refused for operating decline"],
      ["sector_rejected_shadow", "Refused for a sector headwind"],
    ].map(function (pair) {
      const row = shadows && isObject(shadows[pair[0]]) ? shadows[pair[0]] : null;
      const present = !!row;
      return {
        id: pair[0],
        label: pair[1],
        count: metric(row && row.count, "count", present),
        medianFairCost: metric(row && row.median_fair_cost, "pct", present),
        launchShare: metric(row && row.launch_share, "share", present && row.launch_share != null),
      };
    });
  }

  function controlBoardRows(replay) {
    return RESULT_ORDER.map(function (key) {
      const boards = boardsOf(replay, key);
      const controls = boards && isObject(boards.controls) ? boards.controls : null;
      function side(id) {
        const row = controls && isObject(controls[id]) ? controls[id] : null;
        const present = !!row;
        return {
          count: metric(row && row.count, "count", present),
          medianFairCost: metric(row && row.median_fair_cost, "pct", present),
          differenceVsPrimary: metric(row && row.median_difference_vs_primary, "pct", present && row.median_difference_vs_primary != null),
        };
      }
      return {
        key: key,
        label: RESULT_COPY[key].label,
        lookaheadWarning: key === "lookahead_current_gates" ? LOOKAHEAD_WARNING : null,
        buyOnSignal: side("buy_on_signal"),
        leaveTier: side("leave_tier"),
      };
    });
  }

  function selectionBoard(replay, key, featureKey) {
    const boards = boardsOf(replay, key);
    const fifths = boards && isObject(boards.selection_fifths) ? boards.selection_fifths : null;
    const coverage = boards && isObject(boards.selection_coverage) ? boards.selection_coverage : null;
    if (!fifths) {
      return { status: resultPresent(replay, key) ? "insufficient data" : "not yet measured", features: [], feature: null, rows: [] };
    }
    const features = Object.keys(fifths).map(function (id) {
      const cov = coverage && isObject(coverage[id]) ? coverage[id] : null;
      return {
        id: id,
        label: featureLabel(id),
        present: cov ? num(cov.present) : null,
        mature: cov ? num(cov.mature) : null,
      };
    });
    const withData = features.filter(function (row) {
      return row.present != null && row.present > 0;
    });
    if (!withData.length) {
      return {
        status: "insufficient data",
        features: features,
        featuresWithData: 0,
        feature: null,
        rows: [],
      };
    }
    const chosen = withData.some(function (row) { return row.id === featureKey; })
      ? featureKey
      : withData[0].id;
    const block = chosen && isObject(fifths[chosen]) ? fifths[chosen] : null;
    const whole = block && Array.isArray(block.whole) ? block.whole : [];
    return {
      status: "measured",
      features: features,
      featuresWithData: withData.length,
      feature: chosen,
      featureLabel: chosen ? featureLabel(chosen) : null,
      rows: whole.map(function (row) {
        const present = isObject(row);
        return {
          fifth: row && row.fifth,
          count: metric(row && row.count, "count", present),
          launchShare: metric(row && row.launch_share, "share", present && row.launch_share != null),
          medianFairCost: metric(row && row.median_fair_cost, "pct", present),
          standardError: metric(row && row.standard_error, "pct", present && row.standard_error != null),
        };
      }),
    };
  }

  function tip(helpers, label, key) {
    const title = TIPS[key] || "";
    if (!title) return helpers.esc(label);
    return '<abbr class="bp-tip" title="' + helpers.esc(title) + '">' + helpers.esc(label) + "</abbr>";
  }

  function metaHtml(helpers, iso, rule, caption) {
    const ageMs = parseMs(iso);
    const age = ageMs == null ? null : helpers.nowMs() - ageMs;
    const badge = rule === "daily"
      ? helpers.freshnessDailyStore(age)
      : rule === "weekly"
        ? helpers.freshnessWeeklyStore(age)
        : helpers.freshnessChartBar(age);
    const shown = iso ? helpers.displayDate(iso) : "not yet available";
    const prefix = caption ? helpers.esc(caption) + " " : "As of ";
    return '<p class="v2-panel-meta">' + prefix + helpers.esc(shown)
      + ' <span class="v2-muted">age ' + helpers.esc(helpers.ageLabelFromMs(age)) + "</span> "
      + '<span class="' + helpers.esc(badge.cls) + '">' + helpers.esc(badge.label) + "</span></p>";
  }

  function observeBanner(helpers, registration) {
    const live = !!(registration && registration.forward_live === true);
    return '<div class="bp-observe" role="status"><strong>Observe-only.</strong> '
      + tip(helpers, live ? "The forward book is live on paper." : "The forward book is not live.", "observe")
      + " These figures are for review and do not move capital.</div>";
  }

  function metricHtml(helpers, item) {
    const cls = !item || item.state !== "value" ? "bp-missing" : "bp-num";
    const text = item && item.text ? item.text : "not yet measured";
    return '<span class="' + cls + '">' + helpers.esc(text) + "</span>";
  }

  function resultChoices(replay, nowMs) {
    return replayResults(replay, nowMs).results;
  }

  function selectorHtml(helpers, name, selected, replay, nowMs) {
    const rows = resultChoices(replay, nowMs);
    return '<fieldset class="bp-choices"><legend>Which replay result</legend>'
      + rows.map(function (row) {
        const id = name + "-" + row.key;
        const checked = row.key === selected ? " checked" : "";
        const warn = row.lookaheadWarning ? " — uses gates dated after the trades" : "";
        return '<label class="bp-choice" for="' + helpers.esc(id) + '">'
          + '<input type="radio" name="' + helpers.esc(name) + '" id="' + helpers.esc(id) + '" value="'
          + helpers.esc(row.key) + '"' + checked + "> "
          + "<span><strong>" + helpers.esc(row.label) + "</strong> — "
          + helpers.esc(row.episodeCountText) + " episodes" + helpers.esc(warn) + "</span></label>";
      }).join("")
      + '<p class="v2-muted">The three results stay separate. They are not added together.</p></fieldset>';
  }

  function episodeRowsHtml(helpers, rows) {
    if (!rows.length) {
      return '<p class="v2-muted">No trades in this group.</p>';
    }
    const body = rows.map(function (row) {
      const name = helpers.esc(row.ticker || "Unknown")
        + ' <span class="v2-muted">' + helpers.esc(row.marketLabel) + "</span>";
      const when = row.status === "closed"
        ? helpers.esc(row.exitLabel || "Closed") + " · " + metricHtml(helpers, { state: row.fairCost == null ? "insufficient" : "value", text: row.fairCostText })
        : helpers.esc(row.launched ? row.checkpointText : row.sessionsLeftText);
      const review = helpers.esc(row.reviewText || "not yet measured");
      const recovery = row.recoveryLabel ? "Recovery hold" : "—";
      return "<tr><td>" + name + "</td><td>" + helpers.esc(row.fillSession || "not yet measured")
        + "</td><td>" + when + "</td><td>" + review + "</td><td>" + recovery + "</td></tr>";
    }).join("");
    return '<div class="v2-table-wrap"><table class="v2-table"><thead><tr>'
      + "<th>Name</th><th>Filled</th><th>Where it stands</th><th>Review</th><th>Recovery</th>"
      + "</tr></thead><tbody>" + body + "</tbody></table></div>";
  }

  function renderBook(ctx, helpers) {
    const registration = ctx && ctx.registration;
    const replay = slot(ctx, "strategy_book_replay");
    const observe = slot(ctx, "strategy_book_observe");
    const forwardStatus = ctx ? ctx.forwardStatus : null;
    const now = helpers.nowMs();
    const showForward = isObserveStore(observe);
    const selected = normalizeKey(state.bookResult);
    const sourcePayload = showForward ? observe : state.episodePayload || replay;
    const view = bookEpisodesView(
      showForward ? Object.assign({}, forwardStatus || {}, { forward_live: true, wrote_observe: true }) : forwardStatus,
      sourcePayload,
      selected,
      now
    );
    const runAt = registration && registration.first_score_store && registration.first_score_store.run_at;
    const parts = [];
    parts.push(observeBanner(helpers, registration));
    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-book-h">');
    parts.push('<h2 id="bp-book-h">What the book holds</h2>');
    if (showForward) {
      parts.push(metaHtml(helpers, observe.generated_at || observe.scoring_date, observe.generated_at ? "daily" : "chart", "Forward book"));
      parts.push('<p class="bp-kicker">' + tip(helpers, "Forward book", "strategyBook") + " — one live walk, not an archive replay.</p>");
    } else {
      parts.push('<p class="bp-note">' + helpers.esc(FORWARD_NOTE) + "</p>");
      parts.push(selectorHtml(helpers, "bp-book-result", selected, replay, now));
      parts.push("<p>" + helpers.esc(view.detail || "") + "</p>");
      if (view.lookaheadWarning) parts.push('<p class="bp-warn">' + helpers.esc(view.lookaheadWarning) + "</p>");
      parts.push(metaHtml(helpers, view.scoringDate, "chart", "Chart session"));
      if (runAt) parts.push(metaHtml(helpers, runAt, "daily", "Replay written"));
      if (!replay) {
        parts.push('<p class="bp-missing">Archive replay: not yet measured.</p>');
      } else if (view.publishedEmpty) {
        parts.push('<p class="bp-note">This result published an empty board. That is not a zero return and it is not a pass. Dated decline and sector verdicts are not in force for these sessions, so the full strategy archive has no trades yet.</p>');
      }
      if (replay && Array.isArray(replay.no_chart) && replay.no_chart.length) {
        parts.push('<p class="v2-muted">' + helpers.esc(String(replay.no_chart.length))
          + " names had no price chart and are not trades.</p>");
      }
      if (replay && Array.isArray(replay.skipped_ungraduated) && replay.skipped_ungraduated.length) {
        const skipped = replay.skipped_ungraduated.map(function (id) {
          return marketLabel(id);
        }).join(", ");
        parts.push('<p class="v2-muted">Not in this replay (not a graduated market): ' + helpers.esc(skipped) + ".</p>");
      }
    }
    parts.push("</section>");

    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-recovery-h">');
    parts.push('<h2 id="bp-recovery-h">' + tip(helpers, "Recovery-hold share", "recovery") + "</h2>");
    parts.push(metaHtml(helpers, view.recoveryHold.scoringDate, "chart", "Chart session"));
    parts.push('<p class="bp-stat">Latest share ' + metricHtml(helpers, { state: view.recoveryHold.latest == null ? "insufficient" : "value", text: view.recoveryHold.latestText })
      + ' <span class="v2-muted">against the ' + helpers.esc(view.recoveryHold.lineText) + " line</span></p>");
    parts.push('<p class="v2-muted">Daily samples: ' + helpers.esc(view.recoveryHold.seriesText) + ". The replay summary does not keep a time series.</p>");
    parts.push("</section>");

    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-open-h">');
    parts.push('<h2 id="bp-open-h">Open trades</h2>');
    parts.push("<p>Waiting to launch shows sessions left of 63. Launched trades show the checkpoint reached and the current floor. Review dates are session 63, 126 and 189 after the fill, and only once a trade has reached +10%.</p>");
    if (!view.episodes) {
      parts.push('<p class="bp-missing">Each open trade is not yet measured here. Load the episode table to list them. Summary exit counts below are mature trades only.</p>');
    } else {
      const waiting = view.episodes.waiting.length;
      const launched = view.episodes.launched.length;
      parts.push('<p class="bp-stat">' + helpers.esc(String(waiting)) + " waiting to launch · "
        + helpers.esc(String(launched)) + " launched</p>");
    }
    parts.push("</section>");

    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-closed-h">');
    parts.push('<h2 id="bp-closed-h">Closed trades, by how they ended</h2>');
    parts.push(metaHtml(helpers, view.scoringDate, "chart", "Chart session"));
    parts.push("<p class=\"v2-muted\">Mature trades only (fill at least 63 sessions before the scoring date). Floor exits, the 63-session wait, and thesis breaks are kept separate.</p>");
    parts.push('<div class="bp-grid">');
    [
      ["Floor exit", view.closedMature.floorExit, "floor"],
      ["Sold at the 63-session wait", view.closedMature.failToLaunch, "recovery"],
      ["Thesis break", view.closedMature.thesisBreak, "thesis"],
    ].forEach(function (item) {
      const board = item[1];
      const countItem = view.publishedEmpty
        ? { state: "insufficient", text: "insufficient data" }
        : board.count;
      parts.push('<article class="bp-sub"><h3>' + tip(helpers, item[0], item[2]) + "</h3>");
      parts.push("<p>Trades " + metricHtml(helpers, countItem) + "</p>");
      parts.push("<p>Median fair-cost " + metricHtml(helpers, board.medianFairCost) + "</p>");
      if (board.byReason && Object.keys(board.byReason).length) {
        const reasons = Object.keys(board.byReason).map(function (reason) {
          return (THESIS_REASONS[reason] || reason) + " " + board.byReason[reason];
        }).join(" · ");
        parts.push('<p class="v2-muted">' + helpers.esc(reasons) + "</p>");
      }
      parts.push("</article>");
    });
    parts.push("</div></section>");

    parts.push('<section class="v2-card bp-panel" aria-labelledby="bp-table-h">');
    parts.push('<h2 id="bp-table-h">Episode table</h2>');
    if (showForward && view.episodes) {
      parts.push(renderEpisodeBrowser(helpers, view));
    } else if (showForward) {
      parts.push('<p class="bp-missing">The forward store has no per-trade rows yet.</p>');
    } else if (!replay) {
      parts.push('<p class="bp-missing">not yet measured</p>');
    } else {
      parts.push('<p><button type="button" class="bp-btn" data-bp-book-action="load-episodes"'
        + (state.episodeLoading ? " disabled" : "") + ">Load episode table</button></p>");
      parts.push('<p class="v2-muted">Loads the archived trades for the result selected above. Comparison exits, controls and shadows stay out of this list.</p>');
      if (state.episodeLoading) parts.push('<p class="bp-note">Loading episode table…</p>');
      if (state.episodeError) parts.push('<p class="bp-warn">' + helpers.esc(state.episodeError) + "</p>");
      if (view.episodes) parts.push(renderEpisodeBrowser(helpers, view));
    }
    parts.push("</section>");
    return parts.join("");
  }

  function renderEpisodeBrowser(helpers, view) {
    const filters = [
      ["waiting", "Waiting to launch", view.episodes.waiting.length],
      ["launched", "Launched", view.episodes.launched.length],
      ["floor", "Floor exit", view.episodes.floorExit.length],
      ["wait63", "63-session wait", view.episodes.failToLaunch.length],
      ["thesis", "Thesis break", view.episodes.thesisBreak.length],
      ["other", "Other exits", view.episodes.other.length],
    ];
    const filter = state.episodeFilter || "waiting";
    const rows = filteredEpisodes(view, filter);
    const page = paginate(rows, state.episodePage, state.pageSize);
    state.episodePage = page.page;
    const chips = filters.map(function (item) {
      const pressed = item[0] === filter ? "true" : "false";
      const cls = item[0] === filter ? "bp-btn bp-btn-on" : "bp-btn";
      return '<button type="button" class="' + cls + '" data-bp-book-action="filter" data-bp-filter="'
        + item[0] + '" aria-pressed="' + pressed + '">' + helpers.esc(item[1]) + " (" + item[2] + ")</button>";
    }).join("");
    let pager = "";
    if (page.pages > 1) {
      const prev = Math.max(1, page.page - 1);
      const next = Math.min(page.pages, page.page + 1);
      pager = '<p class="bp-pager"><button type="button" class="bp-btn" data-bp-book-action="page" data-bp-page="'
        + prev + '">Previous</button> <span>Page ' + page.page + " of " + page.pages
        + " · " + page.total + ' trades</span> <button type="button" class="bp-btn" data-bp-book-action="page" data-bp-page="'
        + next + '">Next</button></p>';
    } else {
      pager = '<p class="v2-muted">' + page.total + " trades</p>";
    }
    return '<div class="bp-filters">' + chips + "</div>" + pager + episodeRowsHtml(helpers, page.rows) + pager;
  }

  async function loadEpisodes(helpers) {
    if (typeof DecompressionStream !== "function") {
      state.episodeError = "episode table needs a newer browser";
      state.episodeLoading = false;
      return;
    }
    try {
      const response = await fetch(helpers.tsQuery(EPISODE_PATH), { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      if (!response.body || typeof response.body.pipeThrough !== "function") {
        throw new Error("episode table needs a newer browser");
      }
      const stream = response.body.pipeThrough(new DecompressionStream("gzip"));
      const text = await new Response(stream).text();
      // The writer emits Python NaN inside snapshot fields. Browsers reject that.
      // Those fields are missing, not zero.
      const strict = text.replace(/:\s*NaN\b/g, ":null");
      state.episodePayload = JSON.parse(strict);
      state.episodePage = 1;
    } catch (err) {
      const message = err && err.message ? String(err.message) : String(err);
      state.episodeError = message.indexOf("newer browser") >= 0 ? "episode table needs a newer browser" : message;
      state.episodePayload = null;
    } finally {
      state.episodeLoading = false;
    }
  }

  function bindBook(root, ctx, helpers) {
    state._bookCtx = ctx;
    state._bookHelpers = helpers;
    if (root.dataset.bpBookBound === "1") return;
    root.dataset.bpBookBound = "1";
    root.addEventListener("change", function (ev) {
      const target = ev.target;
      if (!target || target.name !== "bp-book-result") return;
      state.bookResult = normalizeKey(target.value);
      state.episodePage = 1;
      root.innerHTML = renderBook(state._bookCtx, state._bookHelpers);
    });
    root.addEventListener("click", function (ev) {
      const button = ev.target && ev.target.closest ? ev.target.closest("[data-bp-book-action]") : null;
      if (!button || !root.contains(button)) return;
      const action = button.getAttribute("data-bp-book-action");
      if (action === "load-episodes") {
        ev.preventDefault();
        if (state.episodeLoading) return;
        state.episodeLoading = true;
        state.episodeError = null;
        root.innerHTML = renderBook(state._bookCtx, state._bookHelpers);
        void loadEpisodes(state._bookHelpers).then(function () {
          root.innerHTML = renderBook(state._bookCtx, state._bookHelpers);
        });
      } else if (action === "page") {
        state.episodePage = Number(button.getAttribute("data-bp-page")) || 1;
        root.innerHTML = renderBook(state._bookCtx, state._bookHelpers);
      } else if (action === "filter") {
        state.episodeFilter = button.getAttribute("data-bp-filter") || "waiting";
        state.episodePage = 1;
        root.innerHTML = renderBook(state._bookCtx, state._bookHelpers);
      }
    });
  }

  const api = {
    RESULT_ORDER: RESULT_ORDER,
    DEFAULT_RESULT: DEFAULT_RESULT,
    FORWARD_NOTE: FORWARD_NOTE,
    LOOKAHEAD_WARNING: LOOKAHEAD_WARNING,
    state: state,
    replayResults: replayResults,
    thicknessProgress: thicknessProgress,
    proofChecklist: proofChecklist,
    controlRows: controlRows,
    bookEpisodesView: bookEpisodesView,
    paginate: paginate,
    pairedExits: pairedExits,
    benchRows: benchRows,
    shadowRows: shadowRows,
    controlBoardRows: controlBoardRows,
    selectionBoard: selectionBoard,
    freshness: freshness,
    metric: metric,
    tip: tip,
    metaHtml: metaHtml,
    observeBanner: observeBanner,
    metricHtml: metricHtml,
    selectorHtml: selectorHtml,
    featureLabel: featureLabel,
    marketLabel: marketLabel,
    slot: slot,
    renderBook: renderBook,
  };
  window.__dashboardV2BookProof = api;

  window.DashboardV2Tabs.register({
    id: "book",
    label: "Book",
    dataPaths: {
      strategy_book_replay: "../data/strategy_book_replay.json",
      strategy_book_observe: "../data/strategy_book_observe.json",
    },
    optionalDataFiles: ["strategy_book_observe.json"],
    render: renderBook,
    bind: bindBook,
  });
})();
