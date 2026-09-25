# Trajectory evidence review

Generated: 2026-09-25T07:22:18.526262+00:00
Archive snapshots: 30
Transition events: 2102
Boundary watch panel: 232
Loser snapshot cards: None

## Boundary watch

- Panel count: 232 (core tags only; mean weeks on boundary=20.79)
- avoid_recovery_candidate: 7
- buy_weakening: 1
- hold_deteriorating: 2
- hold_improving: 1
- pre_avoid: 18
- pre_buy: 158
- strong_buy_candidate: 47

## Outcome summary (1-week forward)

- Upgrades: n=321 mean=0.003827 positive_rate=0.2866
- Downgrades: n=177 mean=0.004942 positive_rate=0.3446

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=131 mean=0.00215 positive_rate=0.313
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=61 mean=0.006304 positive_rate=0.377
- buy->strong_buy: n=41 mean=0.007859 positive_rate=0.3902
- hold->avoid: n=79 mean=0.001596 positive_rate=0.3291
- hold->buy: n=118 mean=0.005535 positive_rate=0.2797
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=1102 mean=-0.00043 positive_rate=0.343
- strong_buy->buy: n=35 mean=0.008992 positive_rate=0.3143
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1215 hit_rate=0.3144
- 4w: scored=1184 hit_rate=0.3708
- 8w: scored=1106 hit_rate=0.4747
- 12w: scored=1004 hit_rate=0.4482

## Weeks to realization

- Realized within 12w: 883/1230 (rate=0.7179)
- Median weeks: 2
- Within 4w rate: 0.6806

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2797 mean=0.005535 n=118 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.313 mean=0.00215 n=131 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3143 mean=0.008992 n=35 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3291 mean=0.001596 n=79 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.343 mean=-0.00043 n=1102 — opinion flip did not match next-week price
