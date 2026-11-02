# Trajectory evidence review

Generated: 2026-11-02T07:48:10.696226+00:00
Archive snapshots: 69
Transition events: 4241
Boundary watch panel: 186
Loser snapshot cards: None

## Boundary watch

- Panel count: 186 (core tags only; mean weeks on boundary=29.08)
- avoid_recovery_candidate: 4
- buy_weakening: 3
- hold_improving: 1
- pre_avoid: 17
- pre_buy: 132
- strong_buy_candidate: 29

## Outcome summary (1-week forward)

- Upgrades: n=546 mean=0.002103 positive_rate=0.207
- Downgrades: n=442 mean=0.001853 positive_rate=0.1742

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=208 mean=0.001543 positive_rate=0.2356
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=155 mean=0.002291 positive_rate=0.1935
- buy->strong_buy: n=95 mean=0.003173 positive_rate=0.2211
- hold->avoid: n=177 mean=0.000733 positive_rate=0.1808
- hold->buy: n=204 mean=0.003106 positive_rate=0.201
- hold->strong_buy: n=37 mean=-0.000122 positive_rate=0.0541
- signal_unchanged: n=3225 mean=0.000292 positive_rate=0.2443
- strong_buy->buy: n=102 mean=0.002794 positive_rate=0.1373
- strong_buy->hold: n=7 mean=0.007625 positive_rate=0.1429

## Multi-horizon prediction calibration

- 1w: scored=2401 hit_rate=0.2228
- 4w: scored=2279 hit_rate=0.4212
- 8w: scored=2118 hit_rate=0.4703
- 12w: scored=1995 hit_rate=0.4431

## Weeks to realization

- Realized within 12w: 1642/2429 (rate=0.676)
- Median weeks: 2.0
- Within 4w rate: 0.7546

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0541 mean=-0.000122 n=37 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1373 mean=0.002794 n=102 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1808 mean=0.000733 n=177 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1935 mean=0.002291 n=155 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.201 mean=0.003106 n=204 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2211 mean=0.003173 n=95 — opinion flip did not match next-week price
