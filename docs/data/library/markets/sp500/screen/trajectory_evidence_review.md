# Trajectory evidence review

Generated: 2026-10-09T07:23:45.855849+00:00
Archive snapshots: 42
Transition events: 3078
Boundary watch panel: 243
Loser snapshot cards: None

## Boundary watch

- Panel count: 243 (core tags only; mean weeks on boundary=26.85)
- avoid_recovery_candidate: 5
- buy_weakening: 2
- hold_deteriorating: 3
- hold_improving: 4
- pre_avoid: 26
- pre_buy: 156
- strong_buy_candidate: 52

## Outcome summary (1-week forward)

- Upgrades: n=383 mean=0.003491 positive_rate=0.2611
- Downgrades: n=229 mean=0.003542 positive_rate=0.2795

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=150 mean=0.002298 positive_rate=0.2933
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=76 mean=0.004863 positive_rate=0.3158
- buy->strong_buy: n=58 mean=0.005749 positive_rate=0.3276
- hold->avoid: n=97 mean=0.00124 positive_rate=0.2887
- hold->buy: n=143 mean=0.004806 positive_rate=0.2448
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=1964 mean=0.004646 positive_rate=0.3676
- strong_buy->buy: n=53 mean=0.005133 positive_rate=0.2075
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1402 hit_rate=0.2832
- 4w: scored=1341 hit_rate=0.3908
- 8w: scored=1243 hit_rate=0.4755
- 12w: scored=1195 hit_rate=0.4444

## Weeks to realization

- Realized within 12w: 1016/1420 (rate=0.7155)
- Median weeks: 2.0
- Within 4w rate: 0.7077

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2075 mean=0.005133 n=53 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2448 mean=0.004806 n=143 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2887 mean=0.00124 n=97 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2933 mean=0.002298 n=150 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.3158 mean=0.004863 n=76 — opinion flip did not match next-week price
