# Trajectory evidence review

Generated: 2026-10-07T16:25:40.794161+00:00
Archive snapshots: 39
Transition events: 2815
Boundary watch panel: 238
Loser snapshot cards: None

## Boundary watch

- Panel count: 238 (core tags only; mean weeks on boundary=24.81)
- avoid_recovery_candidate: 4
- buy_weakening: 4
- hold_deteriorating: 2
- hold_improving: 1
- pre_avoid: 26
- pre_buy: 154
- strong_buy_candidate: 49

## Outcome summary (1-week forward)

- Upgrades: n=366 mean=0.003253 positive_rate=0.2568
- Downgrades: n=218 mean=0.003816 positive_rate=0.2936

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=146 mean=0.002083 positive_rate=0.2877
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=74 mean=0.004994 positive_rate=0.3243
- buy->strong_buy: n=54 mean=0.004835 positive_rate=0.2963
- hold->avoid: n=93 mean=0.001449 positive_rate=0.3011
- hold->buy: n=134 mean=0.004879 positive_rate=0.2537
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2201 mean=-0.000165 positive_rate=0.3503
- strong_buy->buy: n=48 mean=0.005798 positive_rate=0.2292
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1363 hit_rate=0.292
- 4w: scored=1277 hit_rate=0.3798
- 8w: scored=1229 hit_rate=0.4711
- 12w: scored=1182 hit_rate=0.445

## Weeks to realization

- Realized within 12w: 977/1393 (rate=0.7014)
- Median weeks: 2
- Within 4w rate: 0.7001

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2292 mean=0.005798 n=48 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2537 mean=0.004879 n=134 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2877 mean=0.002083 n=146 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2963 mean=0.004835 n=54 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3011 mean=0.001449 n=93 — opinion flip did not match next-week price
