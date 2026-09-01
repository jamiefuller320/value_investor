CHURN SUMMARY
Hold-buffer guards (`exit_confirm_screens=2`, `reentry_cooldown_screens=1`, `min_rebalance_notional_gbp=10.0`) are live on all three focus tracks, but the 7-day window shows no guard activation: `buffered_holdings=0`, empty `exit_streak` and `reentry_cooldown` on rules/ai_judgment/momentum_grace, `duplicate_day_skip=false`, and `adjacent_flip_count=0` everywhere. Recent activity is quiet (rules 0 trades, momentum_grace 0, ai_judgment 2), yet lifetime cost drag remains elevated on rules (30.51%, 51 trades) and primary ai_judgment (22.98%, 34 trades), with watch alerts on both; momentum_grace is the outlier at 2.91% drag and 5 lifetime trades. The buffered-hold counterfactual replay for rules and ai_judgment shows zero differentiation between `exit_confirm_screens=1` vs `2` (`trade_count_delta_lower_minus_higher=0`, `cost_drag_delta_lower_minus_higher=0.0`). The single biggest operational learning gap is insufficient post-guard epoch evidence on the primary track: ai_judgment epoch started 2026-08-26 with only 3 equity marks, `post_apply_trade_count=0`, and `enough_epoch_history=false`, so churn improvement cannot yet be attributed to guards rather than pre-epoch history.

PER-TRACK DIAGNOSIS
**rules (control)**
- Lifetime `cost_drag=0.3051`, `trade_count=51`; epoch-scoped drag is lower at `0.1277` over 16 epoch trades (`learning_track_epoch_datum.post_apply_trade_count=16`, `enough_epoch_history=true`).
- Guards: `exit_confirm_screens=2`, `reentry_cooldown_screens=1`, `min_rebalance_notional_gbp=10.0`.
- `rebalance_state.exit_streak={}`, `reentry_cooldown={}`, `buffered_holdings=0`.
- Last run: `trade_count=0`, `duplicate_day_skip=false`, `buffer_holds_planned=0`, `reentry_skips_planned=0`.
- 7d trades: `total=0`; `adjacent_flip_count=0`, `adjacent_side_flips=[]`.
- Buffered-hold replay (screens 1 vs 2): `trade_count_delta_lower_minus_higher=0`, `cost_drag_delta_lower_minus_higher=0.0`; both variants `simulated_trade_count=3`, `simulated_cost_drag=0.0291`; `churn_context.full_exits_in_window=0`, `log_entries_in_window=4`.

**ai_judgment (primary)**
- Lifetime `cost_drag=0.2298`, `trade_count=34`; beats control on excess (`excess_after_costs=-0.1924` vs rules `-0.2826`) but `beat_market=false`, verdict `underperforming`.
- Guards: same as rules (`exit_confirm_screens=2`, `reentry_cooldown_screens=1`, `min_rebalance_notional_gbp=10.0`).
- `rebalance_state.exit_streak={}`, `reentry_cooldown={}`, `buffered_holdings=0`.
- Last run: `trade_count=0`, `duplicate_day_skip=false`, `buffer_holds_planned=0`.
- 7d trades: `total=2` (1 buy, 1 trim); `adjacent_flip_count=0`.
- Buffered-hold replay: identical 1 vs 2 outcome — `trade_count_delta_lower_minus_higher=0`, `cost_drag_delta_lower_minus_higher=0.0`; both variants `simulated_trade_count=3`, `simulated_cost_drag=0.0291`; `churn_context.full_exits_in_window=0`.
- Epoch datum: `epoch_started_at=2026-08-26`, `epoch_nav=821.98`, `epoch_return=0.0`, `post_apply_trade_count=0`, `equity_marks=3`, `benchmark_span_available=true`, `enough_epoch_history=false`.

**momentum_grace (experimental)**
- Lifetime `cost_drag=0.0291`, `trade_count=5`; `excess_after_costs=-0.0219`.
- Guards: `exit_confirm_screens=2`, `reentry_cooldown_screens=1`, `min_rebalance_notional_gbp=10.0`; `use_momentum_grace=true`, `min_conviction=0.0`.
- `rebalance_state.exit_streak={}`, `reentry_cooldown={}`, `buffered_holdings=0`.
- Last run: `trade_count=0`, `duplicate_day_skip=false`.
- 7d trades: `total=0`; `adjacent_flip_count=0`.
- No `buffered_hold_counterfactual` entry for this track in the payload.
- Epoch datum: `epoch_started_at=2026-08-12`, `epoch_nav=970.87`, `epoch_return=0.0`, `post_apply_trade_count=0`, `equity_marks=13`, `benchmark_span_available=true`, `enough_epoch_history=false`.

PROPOSED EXPERIMENTS
1. [paper_churn] Raise `min_rebalance_notional_gbp` on rules and ai_judgment track `config.json` (e.g. 10 → 25 GBP) and run one weekly paper pass — expected learning value: test whether sub-notional rebalance intents explain the 51/34 lifetime trade gap vs momentum_grace's 5 trades without touching live guards.

2. [paper_churn] Re-run buffered-hold counterfactual on rules/ai_judgment with extended lookback (beyond 7d, covering epoch start 2026-08-12/26) — expected learning value: the current window tied at delta 0; a longer replay may surface whether `exit_confirm_screens=1` vs `2` changes trade count or cost drag when exit signals actually fire.

3. [offline_sim] Manual replay of ai_judgment_calibrated proposed knobs (`min_conviction=0.05`, `max_positions=4`) already sketched in `learning_tracks_review` counterfactual — expected learning value: log replay shows `cost_drag_delta_vs_actual=0.0349` and `return_delta_vs_actual=0.0369`; confirms whether conviction floor + position cap reduce drag before any paper-track config edit on primary ai_judgment.

DEFER
- Auto-applying decision-review proposed changes (`applied=false` everywhere; calibrated shadows propose `min_conviction=0.05` / `max_positions=4` but are frozen).
- Reducing live `exit_confirm_screens` from 2 to 1 based on counterfactual — replay shows zero delta in-window and payload explicitly marks observe-only.
- Momentum_grace buffered-hold screen comparison — no counterfactual block exists for this track yet.
- Knob proposals for graduated_allocation/technical (`enough_history=false`; benchmark unavailable) until ≥2 epoch marks and ≥1 post-apply trade.
- Exit-shadow grace-vs-rotation auto-tuning — all focus tracks report `closed_count=0`.
- Archive lab (L111) full pre-logging replay — current replays cover logged passes only with stated limitations.
- Any live-capital cutover or engineering/paper-auto pipeline changes.
