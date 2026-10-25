# Trajectory evidence review

Generated: 2026-10-25T06:55:36.777486+00:00
Archive snapshots: 60
Transition events: 3985
Boundary watch panel: 187
Loser snapshot cards: None

## Boundary watch

- Panel count: 187 (core tags only; mean weeks on boundary=26.95)
- avoid_recovery_candidate: 3
- hold_deteriorating: 8
- hold_improving: 6
- pre_avoid: 25
- pre_buy: 124
- strong_buy_candidate: 25

## Outcome summary (1-week forward)

- Upgrades: n=468 mean=0.002453 positive_rate=0.2415
- Downgrades: n=357 mean=0.002326 positive_rate=0.2157

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=176 mean=0.001824 positive_rate=0.2784
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=124 mean=0.002864 positive_rate=0.2419
- buy->strong_buy: n=80 mean=0.003768 positive_rate=0.2625
- hold->avoid: n=147 mean=0.000882 positive_rate=0.2177
- hold->buy: n=178 mean=0.003559 positive_rate=0.2303
- hold->strong_buy: n=32 mean=-0.000141 positive_rate=0.0625
- signal_unchanged: n=2659 mean=-0.003106 positive_rate=0.2979
- strong_buy->buy: n=83 mean=0.003569 positive_rate=0.1687
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1979 hit_rate=0.2471
- 4w: scored=1918 hit_rate=0.4098
- 8w: scored=1830 hit_rate=0.4732
- 12w: scored=1755 hit_rate=0.441

## Weeks to realization

- Realized within 12w: 1421/2030 (rate=0.7)
- Median weeks: 2
- Within 4w rate: 0.7502

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0625 mean=-0.000141 n=32 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1687 mean=0.003569 n=83 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2177 mean=0.000882 n=147 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2303 mean=0.003559 n=178 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2419 mean=0.002864 n=124 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2625 mean=0.003768 n=80 — opinion flip did not match next-week price
