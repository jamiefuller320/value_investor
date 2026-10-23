# Trajectory evidence review

Generated: 2026-10-23T07:22:44.177173+00:00
Archive snapshots: 59
Transition events: 3961
Boundary watch panel: 190
Loser snapshot cards: None

## Boundary watch

- Panel count: 190 (core tags only; mean weeks on boundary=26.87)
- avoid_recovery_candidate: 4
- buy_weakening: 2
- hold_deteriorating: 9
- hold_improving: 6
- pre_avoid: 24
- pre_buy: 124
- strong_buy_candidate: 25

## Outcome summary (1-week forward)

- Upgrades: n=453 mean=0.003014 positive_rate=0.2406
- Downgrades: n=341 mean=0.002561 positive_rate=0.2141

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=170 mean=0.002063 positive_rate=0.2824
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=115 mean=0.003287 positive_rate=0.2435
- buy->strong_buy: n=77 mean=0.004402 positive_rate=0.2597
- hold->avoid: n=141 mean=0.001336 positive_rate=0.227
- hold->buy: n=173 mean=0.004069 positive_rate=0.2254
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=3112 mean=-0.002637 positive_rate=0.2551
- strong_buy->buy: n=82 mean=0.003139 positive_rate=0.1463
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1921 hit_rate=0.2426
- 4w: scored=1899 hit_rate=0.4055
- 8w: scored=1827 hit_rate=0.4745
- 12w: scored=1756 hit_rate=0.4391

## Weeks to realization

- Realized within 12w: 1386/1976 (rate=0.7014)
- Median weeks: 2.0
- Within 4w rate: 0.7439

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1463 mean=0.003139 n=82 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2254 mean=0.004069 n=173 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.227 mean=0.001336 n=141 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2435 mean=0.003287 n=115 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.2551 mean=-0.002637 n=3112 — opinion flip did not match next-week price
