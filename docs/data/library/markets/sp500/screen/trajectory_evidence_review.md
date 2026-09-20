# Trajectory evidence review

Generated: 2026-09-20T06:43:41.906734+00:00
Archive snapshots: 24
Transition events: 1886
Boundary watch panel: 233
Loser snapshot cards: None

## Boundary watch

- Panel count: 233 (core tags only; mean weeks on boundary=15.43)
- avoid_recovery_candidate: 8
- buy_weakening: 2
- hold_deteriorating: 4
- hold_improving: 1
- pre_avoid: 18
- pre_buy: 154
- strong_buy_candidate: 48

## Outcome summary (1-week forward)

- Upgrades: n=296 mean=0.004042 positive_rate=0.2804
- Downgrades: n=155 mean=0.005811 positive_rate=0.3871

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=123 mean=0.001946 positive_rate=0.3089
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=54 mean=0.007122 positive_rate=0.4259
- buy->strong_buy: n=30 mean=0.008221 positive_rate=0.4333
- hold->avoid: n=69 mean=0.001937 positive_rate=0.3623
- hold->buy: n=112 mean=0.006596 positive_rate=0.2679
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=934 mean=-0.000578 positive_rate=0.3319
- strong_buy->buy: n=30 mean=0.011108 positive_rate=0.3667
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1115 hit_rate=0.3211
- 4w: scored=1040 hit_rate=0.3596
- 8w: scored=946 hit_rate=0.4672
- 12w: scored=702 hit_rate=0.4573

## Weeks to realization

- Realized within 12w: 818/1146 (rate=0.7138)
- Median weeks: 2.0
- Within 4w rate: 0.6711

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2679 mean=0.006596 n=112 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3089 mean=0.001946 n=123 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3319 mean=-0.000578 n=934 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3623 mean=0.001937 n=69 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3667 mean=0.011108 n=30 — opinion flip did not match next-week price
