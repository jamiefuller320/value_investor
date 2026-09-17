# Trajectory evidence review

Generated: 2026-09-17T07:21:42.371825+00:00
Archive snapshots: 22
Transition events: 1771
Boundary watch panel: 233
Loser snapshot cards: None

## Boundary watch

- Panel count: 233 (core tags only; mean weeks on boundary=13.67)
- avoid_recovery_candidate: 8
- buy_weakening: 3
- hold_deteriorating: 3
- hold_improving: 6
- pre_avoid: 23
- pre_buy: 152
- strong_buy_candidate: 46

## Outcome summary (1-week forward)

- Upgrades: n=282 mean=0.004191 positive_rate=0.2695
- Downgrades: n=148 mean=0.005879 positive_rate=0.3784

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=117 mean=0.001617 positive_rate=0.2821
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=51 mean=0.007454 positive_rate=0.4118
- buy->strong_buy: n=28 mean=0.009462 positive_rate=0.4643
- hold->avoid: n=68 mean=0.001701 positive_rate=0.3529
- hold->buy: n=106 mean=0.007133 positive_rate=0.2642
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=840 mean=-0.000353 positive_rate=0.3202
- strong_buy->buy: n=27 mean=0.012035 positive_rate=0.3704
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1062 hit_rate=0.3117
- 4w: scored=998 hit_rate=0.3517
- 8w: scored=884 hit_rate=0.4808
- 12w: scored=409 hit_rate=0.4621

## Weeks to realization

- Realized within 12w: 772/1088 (rate=0.7096)
- Median weeks: 2.0
- Within 4w rate: 0.6593

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2642 mean=0.007133 n=106 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2821 mean=0.001617 n=117 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3202 mean=-0.000353 n=840 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3529 mean=0.001701 n=68 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3704 mean=0.012035 n=27 — opinion flip did not match next-week price
