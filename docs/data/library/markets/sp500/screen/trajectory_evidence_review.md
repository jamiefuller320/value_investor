# Trajectory evidence review

Generated: 2026-10-22T07:24:23.750154+00:00
Archive snapshots: 56
Transition events: 3850
Boundary watch panel: 182
Loser snapshot cards: None

## Boundary watch

- Panel count: 182 (core tags only; mean weeks on boundary=26.98)
- avoid_recovery_candidate: 5
- buy_weakening: 3
- hold_deteriorating: 2
- hold_improving: 1
- pre_avoid: 23
- pre_buy: 119
- strong_buy_candidate: 30

## Outcome summary (1-week forward)

- Upgrades: n=446 mean=0.003061 positive_rate=0.2444
- Downgrades: n=334 mean=0.002648 positive_rate=0.2186

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=169 mean=0.002076 positive_rate=0.284
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=113 mean=0.003345 positive_rate=0.2478
- buy->strong_buy: n=75 mean=0.004519 positive_rate=0.2667
- hold->avoid: n=140 mean=0.001346 positive_rate=0.2286
- hold->buy: n=169 mean=0.004165 positive_rate=0.2308
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=3054 mean=-0.002105 positive_rate=0.3491
- strong_buy->buy: n=78 mean=0.003444 positive_rate=0.1538
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1879 hit_rate=0.2453
- 4w: scored=1830 hit_rate=0.4049
- 8w: scored=1755 hit_rate=0.4735
- 12w: scored=1442 hit_rate=0.4632

## Weeks to realization

- Realized within 12w: 1342/1895 (rate=0.7082)
- Median weeks: 2.0
- Within 4w rate: 0.7481

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1538 mean=0.003444 n=78 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2286 mean=0.001346 n=140 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2308 mean=0.004165 n=169 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2478 mean=0.003345 n=113 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2667 mean=0.004519 n=75 — opinion flip did not match next-week price
