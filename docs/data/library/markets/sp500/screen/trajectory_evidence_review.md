# Trajectory evidence review

Generated: 2026-11-12T07:24:23.731931+00:00
Archive snapshots: 83
Transition events: 4671
Boundary watch panel: 197
Loser snapshot cards: None

## Boundary watch

- Panel count: 197 (core tags only; mean weeks on boundary=30.63)
- avoid_recovery_candidate: 9
- buy_weakening: 3
- hold_deteriorating: 4
- hold_improving: 3
- pre_avoid: 19
- pre_buy: 124
- strong_buy_candidate: 40

## Outcome summary (1-week forward)

- Upgrades: n=604 mean=0.002069 positive_rate=0.1921
- Downgrades: n=502 mean=0.001654 positive_rate=0.1534

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=231 mean=0.00139 positive_rate=0.2121
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=174 mean=0.002041 positive_rate=0.1724
- buy->strong_buy: n=101 mean=0.003768 positive_rate=0.2277
- hold->avoid: n=204 mean=0.000636 positive_rate=0.1569
- hold->buy: n=226 mean=0.002903 positive_rate=0.1858
- hold->strong_buy: n=43 mean=-0.000105 positive_rate=0.0465
- signal_unchanged: n=3517 mean=0.000118 positive_rate=0.2303
- strong_buy->buy: n=115 mean=0.002576 positive_rate=0.1217
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=2742 hit_rate=0.202
- 4w: scored=2737 hit_rate=0.4045
- 8w: scored=2717 hit_rate=0.4785
- 12w: scored=2486 hit_rate=0.4545

## Weeks to realization

- Realized within 12w: 1962/2790 (rate=0.7032)
- Median weeks: 2.0
- Within 4w rate: 0.7085

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0465 mean=-0.000105 n=43 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1217 mean=0.002576 n=115 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1569 mean=0.000636 n=204 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1724 mean=0.002041 n=174 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1858 mean=0.002903 n=226 — opinion flip did not match next-week price
