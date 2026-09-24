# Trajectory evidence review

Generated: 2026-09-24T07:39:34.726569+00:00
Archive snapshots: 29
Transition events: 2043
Boundary watch panel: 236
Loser snapshot cards: None

## Boundary watch

- Panel count: 236 (core tags only; mean weeks on boundary=19.6)
- avoid_recovery_candidate: 8
- hold_improving: 4
- pre_avoid: 19
- pre_buy: 158
- strong_buy_candidate: 49

## Outcome summary (1-week forward)

- Upgrades: n=314 mean=0.004007 positive_rate=0.2866
- Downgrades: n=176 mean=0.004934 positive_rate=0.3409

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=127 mean=0.002491 positive_rate=0.315
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=61 mean=0.006304 positive_rate=0.377
- buy->strong_buy: n=38 mean=0.008345 positive_rate=0.3947
- hold->avoid: n=78 mean=0.001536 positive_rate=0.3205
- hold->buy: n=118 mean=0.005535 positive_rate=0.2797
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=1051 mean=-0.000133 positive_rate=0.3425
- strong_buy->buy: n=35 mean=0.008992 positive_rate=0.3143
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1201 hit_rate=0.3156
- 4w: scored=1168 hit_rate=0.3716
- 8w: scored=1077 hit_rate=0.4735
- 12w: scored=981 hit_rate=0.4495

## Weeks to realization

- Realized within 12w: 877/1216 (rate=0.7212)
- Median weeks: 2
- Within 4w rate: 0.6796

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2797 mean=0.005535 n=118 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3143 mean=0.008992 n=35 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.315 mean=0.002491 n=127 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3205 mean=0.001536 n=78 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3425 mean=-0.000133 n=1051 — opinion flip did not match next-week price
