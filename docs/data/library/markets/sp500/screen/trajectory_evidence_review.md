# Trajectory evidence review

Generated: 2026-09-22T07:39:56.981739+00:00
Archive snapshots: 26
Transition events: 1970
Boundary watch panel: 235
Loser snapshot cards: None

## Boundary watch

- Panel count: 235 (core tags only; mean weeks on boundary=16.96)
- avoid_recovery_candidate: 8
- buy_weakening: 2
- hold_deteriorating: 3
- hold_improving: 1
- pre_avoid: 18
- pre_buy: 154
- strong_buy_candidate: 50

## Outcome summary (1-week forward)

- Upgrades: n=308 mean=0.004371 positive_rate=0.2857
- Downgrades: n=165 mean=0.005459 positive_rate=0.3636

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=126 mean=0.002511 positive_rate=0.3175
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=58 mean=0.006631 positive_rate=0.3966
- buy->strong_buy: n=36 mean=0.008819 positive_rate=0.3889
- hold->avoid: n=73 mean=0.001831 positive_rate=0.3425
- hold->buy: n=115 mean=0.006442 positive_rate=0.2783
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=996 mean=-0.000615 positive_rate=0.3343
- strong_buy->buy: n=32 mean=0.010414 positive_rate=0.3438
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1163 hit_rate=0.3181
- 4w: scored=1100 hit_rate=0.37
- 8w: scored=1002 hit_rate=0.4721
- 12w: scored=884 hit_rate=0.4491

## Weeks to realization

- Realized within 12w: 845/1184 (rate=0.7137)
- Median weeks: 2
- Within 4w rate: 0.6793

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2783 mean=0.006442 n=115 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3175 mean=0.002511 n=126 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3343 mean=-0.000615 n=996 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3425 mean=0.001831 n=73 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3438 mean=0.010414 n=32 — opinion flip did not match next-week price
