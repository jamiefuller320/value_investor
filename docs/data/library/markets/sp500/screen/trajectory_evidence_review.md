# Trajectory evidence review

Generated: 2026-09-06T06:45:15.517583+00:00
Archive snapshots: 14
Transition events: 785
Boundary watch panel: 228
Loser snapshot cards: None

## Boundary watch

- Panel count: 228 (core tags only; mean weeks on boundary=7.29)
- avoid_recovery_candidate: 5
- buy_weakening: 2
- hold_deteriorating: 1
- hold_improving: 12
- pre_avoid: 29
- pre_buy: 148
- strong_buy_candidate: 38

## Outcome summary (1-week forward)

- Upgrades: n=244 mean=0.004461 positive_rate=0.2828
- Downgrades: n=118 mean=0.009412 positive_rate=0.4153

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=95 mean=0.002052 positive_rate=0.3158
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=41 mean=0.011719 positive_rate=0.4634
- buy->strong_buy: n=22 mean=0.010608 positive_rate=0.5455
- hold->avoid: n=57 mean=0.003934 positive_rate=0.3684
- hold->buy: n=95 mean=0.007249 positive_rate=0.2632
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=367 mean=0.001092 positive_rate=0.2262
- strong_buy->buy: n=18 mean=0.019809 positive_rate=0.4444
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=729 hit_rate=0.2908
- 4w: scored=390 hit_rate=0.2205
- 8w: scored=293 hit_rate=0.5358
- 12w: scored=0 hit_rate=None

## Weeks to realization

- Realized within 12w: 497/785 (rate=0.6331)
- Median weeks: 3
- Within 4w rate: 0.5895

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.2262 mean=0.001092 n=367 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2632 mean=0.007249 n=95 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3158 mean=0.002052 n=95 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3684 mean=0.003934 n=57 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.2908 at 1w (n=729) — implied upgrade/downgrade/conviction sign is not beating chance
