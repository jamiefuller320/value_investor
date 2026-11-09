# Trajectory evidence review

Generated: 2026-11-09T07:21:39.485283+00:00
Archive snapshots: 78
Transition events: 4613
Boundary watch panel: 199
Loser snapshot cards: None

## Boundary watch

- Panel count: 199 (core tags only; mean weeks on boundary=26.41)
- avoid_recovery_candidate: 8
- hold_improving: 1
- pre_avoid: 17
- pre_buy: 129
- strong_buy_candidate: 45

## Outcome summary (1-week forward)

- Upgrades: n=601 mean=0.002079 positive_rate=0.193
- Downgrades: n=499 mean=0.001664 positive_rate=0.1543

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=230 mean=0.001396 positive_rate=0.213
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=174 mean=0.002041 positive_rate=0.1724
- buy->strong_buy: n=101 mean=0.003768 positive_rate=0.2277
- hold->avoid: n=201 mean=0.000645 positive_rate=0.1592
- hold->buy: n=224 mean=0.002929 positive_rate=0.1875
- hold->strong_buy: n=43 mean=-0.000105 positive_rate=0.0465
- signal_unchanged: n=3009 mean=0.000135 positive_rate=0.2692
- strong_buy->buy: n=115 mean=0.002576 positive_rate=0.1217
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=2726 hit_rate=0.2032
- 4w: scored=2647 hit_rate=0.4182
- 8w: scored=2457 hit_rate=0.4685
- 12w: scored=2301 hit_rate=0.4546

## Weeks to realization

- Realized within 12w: 1884/2747 (rate=0.6858)
- Median weeks: 2.0
- Within 4w rate: 0.7378

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0465 mean=-0.000105 n=43 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1217 mean=0.002576 n=115 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1592 mean=0.000645 n=201 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1724 mean=0.002041 n=174 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1875 mean=0.002929 n=224 — opinion flip did not match next-week price
