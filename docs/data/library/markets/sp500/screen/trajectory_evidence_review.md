# Trajectory evidence review

Generated: 2026-10-18T06:56:29.373200+00:00
Archive snapshots: 51
Transition events: 3681
Boundary watch panel: 179
Loser snapshot cards: None

## Boundary watch

- Panel count: 179 (core tags only; mean weeks on boundary=24.06)
- avoid_recovery_candidate: 4
- buy_weakening: 2
- hold_deteriorating: 1
- hold_improving: 1
- pre_avoid: 23
- pre_buy: 114
- strong_buy_candidate: 35

## Outcome summary (1-week forward)

- Upgrades: n=434 mean=0.003078 positive_rate=0.2442
- Downgrades: n=314 mean=0.002708 positive_rate=0.2229

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=166 mean=0.002146 positive_rate=0.2831
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=101 mean=0.003624 positive_rate=0.2574
- buy->strong_buy: n=73 mean=0.004643 positive_rate=0.274
- hold->avoid: n=134 mean=0.001241 positive_rate=0.2313
- hold->buy: n=162 mean=0.004128 positive_rate=0.2284
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2912 mean=-0.003576 positive_rate=0.3383
- strong_buy->buy: n=76 mean=0.003535 positive_rate=0.1579
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1790 hit_rate=0.2458
- 4w: scored=1743 hit_rate=0.397
- 8w: scored=1424 hit_rate=0.4888
- 12w: scored=1367 hit_rate=0.4543

## Weeks to realization

- Realized within 12w: 1265/1811 (rate=0.6985)
- Median weeks: 2
- Within 4w rate: 0.7518

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1579 mean=0.003535 n=76 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2284 mean=0.004128 n=162 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2313 mean=0.001241 n=134 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2574 mean=0.003624 n=101 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.274 mean=0.004643 n=73 — opinion flip did not match next-week price
