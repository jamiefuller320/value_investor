# Trajectory evidence review

Generated: 2026-11-07T12:37:07.282327+00:00
Archive snapshots: 75
Transition events: 4593
Boundary watch panel: 190
Loser snapshot cards: None

## Boundary watch

- Panel count: 190 (core tags only; mean weeks on boundary=25.05)
- avoid_recovery_candidate: 6
- buy_weakening: 5
- hold_deteriorating: 4
- hold_improving: 8
- pre_avoid: 21
- pre_buy: 121
- strong_buy_candidate: 32

## Outcome summary (1-week forward)

- Upgrades: n=580 mean=0.002155 positive_rate=0.2
- Downgrades: n=484 mean=0.001716 positive_rate=0.1591

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=222 mean=0.001446 positive_rate=0.2207
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=171 mean=0.002077 positive_rate=0.1754
- buy->strong_buy: n=99 mean=0.003844 positive_rate=0.2323
- hold->avoid: n=195 mean=0.000665 positive_rate=0.1641
- hold->buy: n=218 mean=0.00301 positive_rate=0.1927
- hold->strong_buy: n=39 mean=-0.000115 positive_rate=0.0513
- signal_unchanged: n=3457 mean=-0.000245 positive_rate=0.2858
- strong_buy->buy: n=110 mean=0.002693 positive_rate=0.1273
- strong_buy->hold: n=7 mean=0.007625 positive_rate=0.1429

## Multi-horizon prediction calibration

- 1w: scored=2651 hit_rate=0.209
- 4w: scored=2481 hit_rate=0.4051
- 8w: scored=2403 hit_rate=0.4653
- 12w: scored=2226 hit_rate=0.4551

## Weeks to realization

- Realized within 12w: 1883/2723 (rate=0.6915)
- Median weeks: 2
- Within 4w rate: 0.7382

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0513 mean=-0.000115 n=39 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1273 mean=0.002693 n=110 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1641 mean=0.000665 n=195 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1754 mean=0.002077 n=171 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1927 mean=0.00301 n=218 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2207 mean=0.001446 n=222 — opinion flip did not match next-week price
