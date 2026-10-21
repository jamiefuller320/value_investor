# Trajectory evidence review

Generated: 2026-10-21T07:26:50.913616+00:00
Archive snapshots: 54
Transition events: 3771
Boundary watch panel: 182
Loser snapshot cards: None

## Boundary watch

- Panel count: 182 (core tags only; mean weeks on boundary=25.31)
- avoid_recovery_candidate: 5
- hold_deteriorating: 8
- pre_avoid: 24
- pre_buy: 120
- strong_buy_candidate: 29

## Outcome summary (1-week forward)

- Upgrades: n=441 mean=0.003096 positive_rate=0.2472
- Downgrades: n=325 mean=0.002721 positive_rate=0.2246

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=169 mean=0.002076 positive_rate=0.284
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=105 mean=0.0036 positive_rate=0.2667
- buy->strong_buy: n=73 mean=0.004643 positive_rate=0.274
- hold->avoid: n=139 mean=0.001356 positive_rate=0.2302
- hold->buy: n=166 mean=0.00424 positive_rate=0.2349
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2504 mean=-0.003462 positive_rate=0.2991
- strong_buy->buy: n=78 mean=0.003444 positive_rate=0.1538
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1843 hit_rate=0.2458
- 4w: scored=1795 hit_rate=0.4033
- 8w: scored=1715 hit_rate=0.4706
- 12w: scored=1412 hit_rate=0.4582

## Weeks to realization

- Realized within 12w: 1323/1863 (rate=0.7101)
- Median weeks: 2
- Within 4w rate: 0.7483

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1538 mean=0.003444 n=78 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2302 mean=0.001356 n=139 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2349 mean=0.00424 n=166 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2667 mean=0.0036 n=105 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.274 mean=0.004643 n=73 — opinion flip did not match next-week price
