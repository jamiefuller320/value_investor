# Trajectory evidence review

Generated: 2026-11-01T07:01:30.237224+00:00
Archive snapshots: 67
Transition events: 4166
Boundary watch panel: 200
Loser snapshot cards: None

## Boundary watch

- Panel count: 200 (core tags only; mean weeks on boundary=25.68)
- avoid_recovery_candidate: 3
- buy_weakening: 7
- hold_deteriorating: 13
- hold_improving: 14
- pre_avoid: 21
- pre_buy: 124
- strong_buy_candidate: 27

## Outcome summary (1-week forward)

- Upgrades: n=510 mean=0.002251 positive_rate=0.2216
- Downgrades: n=414 mean=0.002006 positive_rate=0.186

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=194 mean=0.001655 positive_rate=0.2526
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=143 mean=0.002484 positive_rate=0.2098
- buy->strong_buy: n=87 mean=0.003465 positive_rate=0.2414
- hold->avoid: n=170 mean=0.000763 positive_rate=0.1882
- hold->buy: n=193 mean=0.003283 positive_rate=0.2124
- hold->strong_buy: n=34 mean=-0.000132 positive_rate=0.0588
- signal_unchanged: n=3134 mean=-0.001042 positive_rate=0.3197
- strong_buy->buy: n=94 mean=0.003151 positive_rate=0.1489
- strong_buy->hold: n=6 mean=0.008896 positive_rate=0.1667

## Multi-horizon prediction calibration

- 1w: scored=2260 hit_rate=0.2345
- 4w: scored=2196 hit_rate=0.4162
- 8w: scored=2053 hit_rate=0.47
- 12w: scored=1946 hit_rate=0.4409

## Weeks to realization

- Realized within 12w: 1618/2368 (rate=0.6833)
- Median weeks: 2.0
- Within 4w rate: 0.7528

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0588 mean=-0.000132 n=34 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1489 mean=0.003151 n=94 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1882 mean=0.000763 n=170 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2098 mean=0.002484 n=143 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2124 mean=0.003283 n=193 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2414 mean=0.003465 n=87 — opinion flip did not match next-week price
