# Trajectory evidence review

Generated: 2026-11-06T07:42:08.072608+00:00
Archive snapshots: 73
Transition events: 4347
Boundary watch panel: 206
Loser snapshot cards: None

## Boundary watch

- Panel count: 206 (core tags only; mean weeks on boundary=24.96)
- avoid_recovery_candidate: 4
- buy_weakening: 4
- hold_deteriorating: 18
- hold_improving: 13
- pre_avoid: 27
- pre_buy: 119
- strong_buy_candidate: 31

## Outcome summary (1-week forward)

- Upgrades: n=551 mean=0.002084 positive_rate=0.2051
- Downgrades: n=444 mean=0.00187 positive_rate=0.1734

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=209 mean=0.001536 positive_rate=0.2344
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=154 mean=0.002306 positive_rate=0.1948
- buy->strong_buy: n=94 mean=0.003207 positive_rate=0.2234
- hold->avoid: n=178 mean=0.000729 positive_rate=0.1798
- hold->buy: n=208 mean=0.003046 positive_rate=0.1971
- hold->strong_buy: n=38 mean=-0.000119 positive_rate=0.0526
- signal_unchanged: n=3234 mean=0.000274 positive_rate=0.2424
- strong_buy->buy: n=104 mean=0.002848 positive_rate=0.1346
- strong_buy->hold: n=7 mean=0.007625 positive_rate=0.1429

## Multi-horizon prediction calibration

- 1w: scored=2420 hit_rate=0.2198
- 4w: scored=2405 hit_rate=0.4037
- 8w: scored=2271 hit_rate=0.4659
- 12w: scored=2108 hit_rate=0.4502

## Weeks to realization

- Realized within 12w: 1738/2538 (rate=0.6848)
- Median weeks: 2.0
- Within 4w rate: 0.7215

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0526 mean=-0.000119 n=38 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1346 mean=0.002848 n=104 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1798 mean=0.000729 n=178 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1948 mean=0.002306 n=154 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1971 mean=0.003046 n=208 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2234 mean=0.003207 n=94 — opinion flip did not match next-week price
