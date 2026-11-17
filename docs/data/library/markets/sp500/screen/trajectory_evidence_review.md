# Trajectory evidence review

Generated: 2026-11-17T07:21:42.586951+00:00
Archive snapshots: 89
Transition events: 5155
Boundary watch panel: 203
Loser snapshot cards: None

## Boundary watch

- Panel count: 203 (core tags only; mean weeks on boundary=27.29)
- avoid_recovery_candidate: 4
- buy_weakening: 4
- hold_deteriorating: 4
- hold_improving: 25
- pre_avoid: 22
- pre_buy: 118
- strong_buy_candidate: 35

## Outcome summary (1-week forward)

- Upgrades: n=637 mean=0.001988 positive_rate=0.1852
- Downgrades: n=561 mean=0.001545 positive_rate=0.1408

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=245 mean=0.001346 positive_rate=0.2041
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=193 mean=0.002006 positive_rate=0.1606
- buy->strong_buy: n=107 mean=0.003557 positive_rate=0.215
- hold->avoid: n=238 mean=0.000563 positive_rate=0.1387
- hold->buy: n=238 mean=0.002791 positive_rate=0.1807
- hold->strong_buy: n=44 mean=-0.000102 positive_rate=0.0455
- signal_unchanged: n=3837 mean=-0.001045 positive_rate=0.2697
- strong_buy->buy: n=121 mean=0.002448 positive_rate=0.1157
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=3060 hit_rate=0.1931
- 4w: scored=2926 hit_rate=0.4033
- 8w: scored=2779 hit_rate=0.4789
- 12w: scored=2727 hit_rate=0.4679

## Weeks to realization

- Realized within 12w: 2165/3180 (rate=0.6808)
- Median weeks: 2
- Within 4w rate: 0.7238

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0455 mean=-0.000102 n=44 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1157 mean=0.002448 n=121 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1387 mean=0.000563 n=238 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1606 mean=0.002006 n=193 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1807 mean=0.002791 n=238 — opinion flip did not match next-week price
