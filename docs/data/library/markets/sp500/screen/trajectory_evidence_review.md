# Trajectory evidence review

Generated: 2026-10-14T08:44:54.523840+00:00
Archive snapshots: 45
Transition events: 3249
Boundary watch panel: 190
Loser snapshot cards: None

## Boundary watch

- Panel count: 190 (core tags only; mean weeks on boundary=19.79)
- avoid_recovery_candidate: 2
- buy_weakening: 18
- hold_deteriorating: 15
- hold_improving: 9
- pre_avoid: 29
- pre_buy: 105
- strong_buy_candidate: 14

## Outcome summary (1-week forward)

- Upgrades: n=395 mean=0.003389 positive_rate=0.2684
- Downgrades: n=243 mean=0.003597 positive_rate=0.2881

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=154 mean=0.002314 positive_rate=0.3052
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=81 mean=0.004813 positive_rate=0.321
- buy->strong_buy: n=62 mean=0.005467 positive_rate=0.3226
- hold->avoid: n=103 mean=0.001615 positive_rate=0.301
- hold->buy: n=147 mean=0.004571 positive_rate=0.2517
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2109 mean=0.004854 positive_rate=0.3921
- strong_buy->buy: n=56 mean=0.004797 positive_rate=0.2143
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1449 hit_rate=0.2878
- 4w: scored=1403 hit_rate=0.397
- 8w: scored=1335 hit_rate=0.4809
- 12w: scored=1226 hit_rate=0.4502

## Weeks to realization

- Realized within 12w: 1068/1705 (rate=0.6264)
- Median weeks: 2.0
- Within 4w rate: 0.7079

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2143 mean=0.004797 n=56 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2517 mean=0.004571 n=147 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.301 mean=0.001615 n=103 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3052 mean=0.002314 n=154 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.321 mean=0.004813 n=81 — opinion flip did not match next-week price
