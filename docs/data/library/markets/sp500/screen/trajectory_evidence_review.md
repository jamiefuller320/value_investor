# Trajectory evidence review

Generated: 2026-10-19T07:17:31.628603+00:00
Archive snapshots: 52
Transition events: 3720
Boundary watch panel: 178
Loser snapshot cards: None

## Boundary watch

- Panel count: 178 (core tags only; mean weeks on boundary=24.88)
- avoid_recovery_candidate: 4
- hold_deteriorating: 1
- hold_improving: 1
- pre_avoid: 23
- pre_buy: 115
- strong_buy_candidate: 35

## Outcome summary (1-week forward)

- Upgrades: n=437 mean=0.003056 positive_rate=0.2426
- Downgrades: n=321 mean=0.002649 positive_rate=0.2181

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=167 mean=0.002133 positive_rate=0.2814
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=102 mean=0.003589 positive_rate=0.2549
- buy->strong_buy: n=73 mean=0.004643 positive_rate=0.274
- hold->avoid: n=138 mean=0.001205 positive_rate=0.2246
- hold->buy: n=164 mean=0.004078 positive_rate=0.2256
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2461 mean=-0.003397 positive_rate=0.3003
- strong_buy->buy: n=78 mean=0.003444 positive_rate=0.1538
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1819 hit_rate=0.2419
- 4w: scored=1755 hit_rate=0.4006
- 8w: scored=1442 hit_rate=0.4889
- 12w: scored=1374 hit_rate=0.4549

## Weeks to realization

- Realized within 12w: 1271/1826 (rate=0.6961)
- Median weeks: 2
- Within 4w rate: 0.753

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1538 mean=0.003444 n=78 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2246 mean=0.001205 n=138 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2256 mean=0.004078 n=164 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2549 mean=0.003589 n=102 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.274 mean=0.004643 n=73 — opinion flip did not match next-week price
