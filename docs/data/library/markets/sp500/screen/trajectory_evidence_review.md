# Trajectory evidence review

Generated: 2026-11-19T08:30:14.389886+00:00
Archive snapshots: 90
Transition events: 5179
Boundary watch panel: 188
Loser snapshot cards: None

## Boundary watch

- Panel count: 188 (core tags only; mean weeks on boundary=29.76)
- avoid_recovery_candidate: 6
- buy_weakening: 1
- hold_deteriorating: 7
- hold_improving: 7
- pre_avoid: 24
- pre_buy: 116
- strong_buy_candidate: 33

## Outcome summary (1-week forward)

- Upgrades: n=673 mean=0.001293 positive_rate=0.1917
- Downgrades: n=570 mean=0.001396 positive_rate=0.1474

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=270 mean=0.000732 positive_rate=0.2148
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=193 mean=0.002206 positive_rate=0.1658
- buy->strong_buy: n=112 mean=0.002101 positive_rate=0.2054
- hold->avoid: n=243 mean=0.000651 positive_rate=0.1481
- hold->buy: n=244 mean=0.002233 positive_rate=0.1885
- hold->strong_buy: n=44 mean=-0.000102 positive_rate=0.0455
- signal_unchanged: n=3434 mean=0.000281 positive_rate=0.2635
- strong_buy->buy: n=125 mean=0.001303 positive_rate=0.12
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=3183 hit_rate=0.1954
- 4w: scored=2936 hit_rate=0.405
- 8w: scored=2794 hit_rate=0.4771
- 12w: scored=2746 hit_rate=0.4676

## Weeks to realization

- Realized within 12w: 2254/3227 (rate=0.6985)
- Median weeks: 2.0
- Within 4w rate: 0.7258

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0455 mean=-0.000102 n=44 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.12 mean=0.001303 n=125 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1481 mean=0.000651 n=243 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1658 mean=0.002206 n=193 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1885 mean=0.002233 n=244 — opinion flip did not match next-week price
