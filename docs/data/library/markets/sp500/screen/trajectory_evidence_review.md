# Trajectory evidence review

Generated: 2026-09-21T01:37:55.740453+00:00
Archive snapshots: 25
Transition events: 1954
Boundary watch panel: 232
Loser snapshot cards: None

## Boundary watch

- Panel count: 232 (core tags only; mean weeks on boundary=16.37)
- avoid_recovery_candidate: 8
- hold_improving: 2
- pre_avoid: 19
- pre_buy: 156
- strong_buy_candidate: 49

## Outcome summary (1-week forward)

- Upgrades: n=301 mean=0.003975 positive_rate=0.2757
- Downgrades: n=165 mean=0.005459 positive_rate=0.3636

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=124 mean=0.00193 positive_rate=0.3065
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=58 mean=0.006631 positive_rate=0.3966
- buy->strong_buy: n=34 mean=0.007254 positive_rate=0.3824
- hold->avoid: n=73 mean=0.001831 positive_rate=0.3425
- hold->buy: n=112 mean=0.006596 positive_rate=0.2679
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=990 mean=-0.000649 positive_rate=0.3323
- strong_buy->buy: n=32 mean=0.010414 positive_rate=0.3438
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1150 hit_rate=0.3139
- 4w: scored=1071 hit_rate=0.3679
- 8w: scored=979 hit_rate=0.4729
- 12w: scored=831 hit_rate=0.4609

## Weeks to realization

- Realized within 12w: 821/1168 (rate=0.7029)
- Median weeks: 2
- Within 4w rate: 0.6724

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2679 mean=0.006596 n=112 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3065 mean=0.00193 n=124 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3323 mean=-0.000649 n=990 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3425 mean=0.001831 n=73 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3438 mean=0.010414 n=32 — opinion flip did not match next-week price
