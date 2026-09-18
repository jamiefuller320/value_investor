# Trajectory evidence review

Generated: 2026-09-18T07:15:00.309744+00:00
Archive snapshots: 23
Transition events: 1836
Boundary watch panel: 231
Loser snapshot cards: None

## Boundary watch

- Panel count: 231 (core tags only; mean weeks on boundary=14.67)
- avoid_recovery_candidate: 8
- pre_avoid: 19
- pre_buy: 152
- strong_buy_candidate: 52

## Outcome summary (1-week forward)

- Upgrades: n=292 mean=0.004177 positive_rate=0.2808
- Downgrades: n=155 mean=0.005811 positive_rate=0.3871

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=123 mean=0.001946 positive_rate=0.3089
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=54 mean=0.007122 positive_rate=0.4259
- buy->strong_buy: n=29 mean=0.008809 positive_rate=0.4483
- hold->avoid: n=69 mean=0.001937 positive_rate=0.3623
- hold->buy: n=109 mean=0.006911 positive_rate=0.2661
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=888 mean=-0.000748 positive_rate=0.3176
- strong_buy->buy: n=30 mean=0.011108 positive_rate=0.3667
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1096 hit_rate=0.3212
- 4w: scored=1010 hit_rate=0.3515
- 8w: scored=895 hit_rate=0.4771
- 12w: scored=545 hit_rate=0.4495

## Weeks to realization

- Realized within 12w: 800/1112 (rate=0.7194)
- Median weeks: 2.0
- Within 4w rate: 0.6663

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2661 mean=0.006911 n=109 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3089 mean=0.001946 n=123 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3176 mean=-0.000748 n=888 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3623 mean=0.001937 n=69 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3667 mean=0.011108 n=30 — opinion flip did not match next-week price
