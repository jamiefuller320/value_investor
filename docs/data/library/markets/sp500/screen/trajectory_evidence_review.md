# Trajectory evidence review

Generated: 2026-11-16T07:17:06.326262+00:00
Archive snapshots: 87
Transition events: 4918
Boundary watch panel: 182
Loser snapshot cards: None

## Boundary watch

- Panel count: 182 (core tags only; mean weeks on boundary=28.99)
- avoid_recovery_candidate: 3
- buy_weakening: 4
- hold_deteriorating: 11
- hold_improving: 5
- pre_avoid: 31
- pre_buy: 100
- strong_buy_candidate: 35

## Outcome summary (1-week forward)

- Upgrades: n=620 mean=0.002048 positive_rate=0.1903
- Downgrades: n=519 mean=0.001716 positive_rate=0.1522

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=240 mean=0.001374 positive_rate=0.2083
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=179 mean=0.002296 positive_rate=0.1732
- buy->strong_buy: n=104 mean=0.00366 positive_rate=0.2212
- hold->avoid: n=214 mean=0.000626 positive_rate=0.1542
- hold->buy: n=229 mean=0.002914 positive_rate=0.1878
- hold->strong_buy: n=44 mean=-0.000102 positive_rate=0.0455
- signal_unchanged: n=3277 mean=0.000588 positive_rate=0.2713
- strong_buy->buy: n=117 mean=0.002532 positive_rate=0.1197
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=2941 hit_rate=0.2003
- 4w: scored=2869 hit_rate=0.4012
- 8w: scored=2746 hit_rate=0.4792
- 12w: scored=2709 hit_rate=0.467

## Weeks to realization

- Realized within 12w: 2065/3050 (rate=0.677)
- Median weeks: 2
- Within 4w rate: 0.7162

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0455 mean=-0.000102 n=44 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1197 mean=0.002532 n=117 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1542 mean=0.000626 n=214 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1732 mean=0.002296 n=179 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1878 mean=0.002914 n=229 — opinion flip did not match next-week price
