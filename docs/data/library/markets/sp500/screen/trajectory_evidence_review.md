# Trajectory evidence review

Generated: 2026-10-12T07:20:18.046751+00:00
Archive snapshots: 44
Transition events: 3239
Boundary watch panel: 232
Loser snapshot cards: None

## Boundary watch

- Panel count: 232 (core tags only; mean weeks on boundary=29.83)
- avoid_recovery_candidate: 5
- hold_deteriorating: 1
- pre_avoid: 24
- pre_buy: 150
- strong_buy_candidate: 52

## Outcome summary (1-week forward)

- Upgrades: n=393 mean=0.003475 positive_rate=0.2672
- Downgrades: n=241 mean=0.003559 positive_rate=0.2863

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=154 mean=0.002314 positive_rate=0.3052
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=80 mean=0.004943 positive_rate=0.325
- buy->strong_buy: n=62 mean=0.005467 positive_rate=0.3226
- hold->avoid: n=102 mean=0.001416 positive_rate=0.2941
- hold->buy: n=145 mean=0.004819 positive_rate=0.2483
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2103 mean=0.004855 positive_rate=0.3913
- strong_buy->buy: n=56 mean=0.004797 positive_rate=0.2143
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1439 hit_rate=0.2856
- 4w: scored=1385 hit_rate=0.3935
- 8w: scored=1275 hit_rate=0.4769
- 12w: scored=1216 hit_rate=0.4482

## Weeks to realization

- Realized within 12w: 1042/1451 (rate=0.7181)
- Median weeks: 2.0
- Within 4w rate: 0.7092

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2143 mean=0.004797 n=56 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2483 mean=0.004819 n=145 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2941 mean=0.001416 n=102 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3052 mean=0.002314 n=154 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.3226 mean=0.005467 n=62 — opinion flip did not match next-week price
