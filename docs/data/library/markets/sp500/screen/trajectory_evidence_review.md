# Trajectory evidence review

Generated: 2026-10-11T06:59:17.553519+00:00
Archive snapshots: 43
Transition events: 3171
Boundary watch panel: 237
Loser snapshot cards: None

## Boundary watch

- Panel count: 237 (core tags only; mean weeks on boundary=28.41)
- avoid_recovery_candidate: 5
- buy_weakening: 1
- hold_deteriorating: 1
- pre_avoid: 25
- pre_buy: 155
- strong_buy_candidate: 50

## Outcome summary (1-week forward)

- Upgrades: n=390 mean=0.003502 positive_rate=0.2692
- Downgrades: n=236 mean=0.003635 positive_rate=0.2924

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=154 mean=0.002314 positive_rate=0.3052
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=79 mean=0.005005 positive_rate=0.3291
- buy->strong_buy: n=60 mean=0.005649 positive_rate=0.3333
- hold->avoid: n=99 mean=0.001458 positive_rate=0.303
- hold->buy: n=144 mean=0.004852 positive_rate=0.25
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2043 mean=0.004979 positive_rate=0.3882
- strong_buy->buy: n=55 mean=0.004885 positive_rate=0.2182
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1424 hit_rate=0.2872
- 4w: scored=1378 hit_rate=0.3919
- 8w: scored=1253 hit_rate=0.4733
- 12w: scored=1204 hit_rate=0.4468

## Weeks to realization

- Realized within 12w: 1040/1438 (rate=0.7232)
- Median weeks: 2.0
- Within 4w rate: 0.7087

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2182 mean=0.004885 n=55 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.25 mean=0.004852 n=144 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.303 mean=0.001458 n=99 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3052 mean=0.002314 n=154 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.3291 mean=0.005005 n=79 — opinion flip did not match next-week price
