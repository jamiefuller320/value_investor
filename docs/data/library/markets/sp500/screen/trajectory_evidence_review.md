# Trajectory evidence review

Generated: 2026-11-22T07:01:24.513046+00:00
Archive snapshots: 91
Transition events: 5325
Boundary watch panel: 201
Loser snapshot cards: None

## Boundary watch

- Panel count: 201 (core tags only; mean weeks on boundary=27.57)
- avoid_recovery_candidate: 4
- buy_weakening: 6
- hold_deteriorating: 2
- hold_improving: 10
- pre_avoid: 27
- pre_buy: 123
- strong_buy_candidate: 36

## Outcome summary (1-week forward)

- Upgrades: n=686 mean=0.000268 positive_rate=0.188
- Downgrades: n=583 mean=0.000818 positive_rate=0.1475

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=277 mean=-9.3e-05 positive_rate=0.2094
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=200 mean=0.001447 positive_rate=0.17
- buy->strong_buy: n=116 mean=-0.000405 positive_rate=0.1983
- hold->avoid: n=248 mean=4.6e-05 positive_rate=0.1452
- hold->buy: n=246 mean=0.001481 positive_rate=0.187
- hold->strong_buy: n=44 mean=-0.000102 positive_rate=0.0455
- signal_unchanged: n=3554 mean=-0.000652 positive_rate=0.2594
- strong_buy->buy: n=126 mean=0.001006 positive_rate=0.119
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=3303 hit_rate=0.2053
- 4w: scored=3065 hit_rate=0.4192
- 8w: scored=2872 hit_rate=0.4781
- 12w: scored=2746 hit_rate=0.4676

## Weeks to realization

- Realized within 12w: 2336/3370 (rate=0.6932)
- Median weeks: 2.0
- Within 4w rate: 0.7316

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0455 mean=-0.000102 n=44 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.119 mean=0.001006 n=126 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1452 mean=4.6e-05 n=248 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.17 mean=0.001447 n=200 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.187 mean=0.001481 n=246 — opinion flip did not match next-week price
