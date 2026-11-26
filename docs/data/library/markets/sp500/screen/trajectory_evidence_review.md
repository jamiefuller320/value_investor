# Trajectory evidence review

Generated: 2026-11-26T07:20:34.208991+00:00
Archive snapshots: 93
Transition events: 5483
Boundary watch panel: 199
Loser snapshot cards: None

## Boundary watch

- Panel count: 199 (core tags only; mean weeks on boundary=29.2)
- avoid_recovery_candidate: 6
- buy_weakening: 1
- hold_deteriorating: 4
- hold_improving: 2
- pre_avoid: 23
- pre_buy: 123
- strong_buy_candidate: 41

## Outcome summary (1-week forward)

- Upgrades: n=705 mean=0.00026 positive_rate=0.183
- Downgrades: n=596 mean=0.0008 positive_rate=0.1443

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=287 mean=-9e-05 positive_rate=0.2021
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=202 mean=0.001432 positive_rate=0.1683
- buy->strong_buy: n=117 mean=-0.000401 positive_rate=0.1966
- hold->avoid: n=253 mean=4.6e-05 positive_rate=0.1423
- hold->buy: n=254 mean=0.001434 positive_rate=0.1811
- hold->strong_buy: n=44 mean=-0.000102 positive_rate=0.0455
- signal_unchanged: n=4133 mean=0.004122 positive_rate=0.3349
- strong_buy->buy: n=132 mean=0.00096 positive_rate=0.1136
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=3404 hit_rate=0.2001
- 4w: scored=3222 hit_rate=0.4156
- 8w: scored=2915 hit_rate=0.4782
- 12w: scored=2766 hit_rate=0.4685

## Weeks to realization

- Realized within 12w: 2453/3453 (rate=0.7104)
- Median weeks: 2
- Within 4w rate: 0.7419

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0455 mean=-0.000102 n=44 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1136 mean=0.00096 n=132 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1423 mean=4.6e-05 n=253 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1683 mean=0.001432 n=202 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1811 mean=0.001434 n=254 — opinion flip did not match next-week price
