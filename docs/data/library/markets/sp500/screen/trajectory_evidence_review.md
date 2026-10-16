# Trajectory evidence review

Generated: 2026-10-16T07:17:06.981010+00:00
Archive snapshots: 49
Transition events: 3595
Boundary watch panel: 180
Loser snapshot cards: None

## Boundary watch

- Panel count: 180 (core tags only; mean weeks on boundary=22.86)
- avoid_recovery_candidate: 4
- buy_weakening: 2
- hold_deteriorating: 4
- hold_improving: 3
- pre_avoid: 25
- pre_buy: 114
- strong_buy_candidate: 31

## Outcome summary (1-week forward)

- Upgrades: n=428 mean=0.003121 positive_rate=0.2477
- Downgrades: n=305 mean=0.002788 positive_rate=0.2295

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=163 mean=0.002186 positive_rate=0.2883
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=97 mean=0.003774 positive_rate=0.268
- buy->strong_buy: n=72 mean=0.004707 positive_rate=0.2778
- hold->avoid: n=131 mean=0.001269 positive_rate=0.2366
- hold->buy: n=161 mean=0.004154 positive_rate=0.2298
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2831 mean=-0.000597 positive_rate=0.3896
- strong_buy->buy: n=74 mean=0.00363 positive_rate=0.1622
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1751 hit_rate=0.2507
- 4w: scored=1702 hit_rate=0.3913
- 8w: scored=1393 hit_rate=0.4867
- 12w: scored=1323 hit_rate=0.4535

## Weeks to realization

- Realized within 12w: 1246/1782 (rate=0.6992)
- Median weeks: 2.0
- Within 4w rate: 0.748

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1622 mean=0.00363 n=74 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2298 mean=0.004154 n=161 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2366 mean=0.001269 n=131 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.268 mean=0.003774 n=97 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2778 mean=0.004707 n=72 — opinion flip did not match next-week price
