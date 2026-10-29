# Trajectory evidence review

Generated: 2026-10-29T07:24:28.829061+00:00
Archive snapshots: 63
Transition events: 4127
Boundary watch panel: 189
Loser snapshot cards: None

## Boundary watch

- Panel count: 189 (core tags only; mean weeks on boundary=27.4)
- avoid_recovery_candidate: 4
- buy_weakening: 7
- hold_deteriorating: 4
- hold_improving: 7
- pre_avoid: 22
- pre_buy: 124
- strong_buy_candidate: 27

## Outcome summary (1-week forward)

- Upgrades: n=479 mean=0.002397 positive_rate=0.2359
- Downgrades: n=371 mean=0.002238 positive_rate=0.2075

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=182 mean=0.001764 positive_rate=0.2692
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=129 mean=0.002753 positive_rate=0.2326
- buy->strong_buy: n=80 mean=0.003768 positive_rate=0.2625
- hold->avoid: n=153 mean=0.000848 positive_rate=0.2092
- hold->buy: n=182 mean=0.003481 positive_rate=0.2253
- hold->strong_buy: n=33 mean=-0.000136 positive_rate=0.0606
- signal_unchanged: n=3213 mean=-0.002629 positive_rate=0.2487
- strong_buy->buy: n=83 mean=0.003569 positive_rate=0.1687
- strong_buy->hold: n=5 mean=0.010675 positive_rate=0.2

## Multi-horizon prediction calibration

- 1w: scored=2049 hit_rate=0.245
- 4w: scored=1993 hit_rate=0.4205
- 8w: scored=1886 hit_rate=0.4724
- 12w: scored=1814 hit_rate=0.4421

## Weeks to realization

- Realized within 12w: 1481/2113 (rate=0.7009)
- Median weeks: 2
- Within 4w rate: 0.7529

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0606 mean=-0.000136 n=33 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1687 mean=0.003569 n=83 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2092 mean=0.000848 n=153 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2253 mean=0.003481 n=182 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2326 mean=0.002753 n=129 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.2487 mean=-0.002629 n=3213 — opinion flip did not match next-week price
