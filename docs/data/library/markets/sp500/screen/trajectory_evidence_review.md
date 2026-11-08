# Trajectory evidence review

Generated: 2026-11-08T06:44:39.083950+00:00
Archive snapshots: 77
Transition events: 4607
Boundary watch panel: 189
Loser snapshot cards: None

## Boundary watch

- Panel count: 189 (core tags only; mean weeks on boundary=27.14)
- avoid_recovery_candidate: 7
- pre_avoid: 17
- pre_buy: 126
- strong_buy_candidate: 39

## Outcome summary (1-week forward)

- Upgrades: n=601 mean=0.002079 positive_rate=0.193
- Downgrades: n=499 mean=0.001664 positive_rate=0.1543

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=230 mean=0.001396 positive_rate=0.213
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=174 mean=0.002041 positive_rate=0.1724
- buy->strong_buy: n=101 mean=0.003768 positive_rate=0.2277
- hold->avoid: n=201 mean=0.000645 positive_rate=0.1592
- hold->buy: n=224 mean=0.002929 positive_rate=0.1875
- hold->strong_buy: n=43 mean=-0.000105 positive_rate=0.0465
- signal_unchanged: n=3499 mean=0.000117 positive_rate=0.2318
- strong_buy->buy: n=115 mean=0.002576 positive_rate=0.1217
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=2723 hit_rate=0.2035
- 4w: scored=2646 hit_rate=0.4184
- 8w: scored=2451 hit_rate=0.4676
- 12w: scored=2295 hit_rate=0.454

## Weeks to realization

- Realized within 12w: 1883/2731 (rate=0.6895)
- Median weeks: 2
- Within 4w rate: 0.7382

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0465 mean=-0.000105 n=43 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1217 mean=0.002576 n=115 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1592 mean=0.000645 n=201 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1724 mean=0.002041 n=174 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1875 mean=0.002929 n=224 — opinion flip did not match next-week price
