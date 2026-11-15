# Trajectory evidence review

Generated: 2026-11-15T06:57:28.222257+00:00
Archive snapshots: 86
Transition events: 4842
Boundary watch panel: 198
Loser snapshot cards: None

## Boundary watch

- Panel count: 198 (core tags only; mean weeks on boundary=32.76)
- avoid_recovery_candidate: 5
- hold_deteriorating: 2
- hold_improving: 5
- pre_avoid: 18
- pre_buy: 126
- strong_buy_candidate: 42

## Outcome summary (1-week forward)

- Upgrades: n=613 mean=0.002071 positive_rate=0.1925
- Downgrades: n=513 mean=0.001736 positive_rate=0.154

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=235 mean=0.001403 positive_rate=0.2128
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=177 mean=0.002322 positive_rate=0.1751
- buy->strong_buy: n=104 mean=0.00366 positive_rate=0.2212
- hold->avoid: n=210 mean=0.000638 positive_rate=0.1571
- hold->buy: n=227 mean=0.00294 positive_rate=0.1894
- hold->strong_buy: n=44 mean=-0.000102 positive_rate=0.0455
- signal_unchanged: n=3214 mean=0.000513 positive_rate=0.2666
- strong_buy->buy: n=117 mean=0.002532 positive_rate=0.1197
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=2890 hit_rate=0.199
- 4w: scored=2791 hit_rate=0.4016
- 8w: scored=2746 hit_rate=0.4792
- 12w: scored=2642 hit_rate=0.4659

## Weeks to realization

- Realized within 12w: 2051/2919 (rate=0.7026)
- Median weeks: 2
- Within 4w rate: 0.7143

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0455 mean=-0.000102 n=44 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1197 mean=0.002532 n=117 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1571 mean=0.000638 n=210 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1751 mean=0.002322 n=177 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1894 mean=0.00294 n=227 — opinion flip did not match next-week price
