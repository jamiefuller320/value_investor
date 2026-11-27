# Trajectory evidence review

Generated: 2026-11-27T07:23:03.947184+00:00
Archive snapshots: 95
Transition events: 5558
Boundary watch panel: 196
Loser snapshot cards: None

## Boundary watch

- Panel count: 196 (core tags only; mean weeks on boundary=30.87)
- avoid_recovery_candidate: 7
- hold_deteriorating: 2
- pre_avoid: 20
- pre_buy: 124
- strong_buy_candidate: 43

## Outcome summary (1-week forward)

- Upgrades: n=715 mean=0.000257 positive_rate=0.1804
- Downgrades: n=610 mean=0.000782 positive_rate=0.141

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=289 mean=-8.9e-05 positive_rate=0.2007
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=206 mean=0.001405 positive_rate=0.165
- buy->strong_buy: n=122 mean=-0.000385 positive_rate=0.1885
- hold->avoid: n=262 mean=4.4e-05 positive_rate=0.1374
- hold->buy: n=257 mean=0.001417 positive_rate=0.179
- hold->strong_buy: n=44 mean=-0.000102 positive_rate=0.0455
- signal_unchanged: n=4220 mean=-0.000583 positive_rate=0.2204
- strong_buy->buy: n=133 mean=0.000953 positive_rate=0.1128
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=3487 hit_rate=0.1953
- 4w: scored=3391 hit_rate=0.4223
- 8w: scored=3068 hit_rate=0.484
- 12w: scored=2872 hit_rate=0.4683

## Weeks to realization

- Realized within 12w: 2453/3500 (rate=0.7009)
- Median weeks: 2
- Within 4w rate: 0.7419

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0455 mean=-0.000102 n=44 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1128 mean=0.000953 n=133 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1374 mean=4.4e-05 n=262 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.165 mean=0.001405 n=206 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.179 mean=0.001417 n=257 — opinion flip did not match next-week price
