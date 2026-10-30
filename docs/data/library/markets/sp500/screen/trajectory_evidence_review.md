# Trajectory evidence review

Generated: 2026-10-30T07:40:41.866821+00:00
Archive snapshots: 65
Transition events: 4064
Boundary watch panel: 189
Loser snapshot cards: None

## Boundary watch

- Panel count: 189 (core tags only; mean weeks on boundary=27.9)
- avoid_recovery_candidate: 4
- buy_weakening: 4
- hold_deteriorating: 11
- hold_improving: 5
- pre_avoid: 22
- pre_buy: 120
- strong_buy_candidate: 27

## Outcome summary (1-week forward)

- Upgrades: n=502 mean=0.002368 positive_rate=0.2311
- Downgrades: n=396 mean=0.002097 positive_rate=0.1944

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=189 mean=0.001698 positive_rate=0.2593
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=133 mean=0.00267 positive_rate=0.2256
- buy->strong_buy: n=85 mean=0.003758 positive_rate=0.2706
- hold->avoid: n=165 mean=0.000786 positive_rate=0.1939
- hold->buy: n=192 mean=0.003417 positive_rate=0.2188
- hold->strong_buy: n=34 mean=-0.000132 positive_rate=0.0588
- signal_unchanged: n=3109 mean=0.002189 positive_rate=0.3808
- strong_buy->buy: n=92 mean=0.00322 positive_rate=0.1522
- strong_buy->hold: n=5 mean=0.010675 positive_rate=0.2

## Multi-horizon prediction calibration

- 1w: scored=2214 hit_rate=0.2412
- 4w: scored=2122 hit_rate=0.4138
- 8w: scored=2003 hit_rate=0.4638
- 12w: scored=1935 hit_rate=0.4398

## Weeks to realization

- Realized within 12w: 1580/2271 (rate=0.6957)
- Median weeks: 2.0
- Within 4w rate: 0.7468

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0588 mean=-0.000132 n=34 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1522 mean=0.00322 n=92 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1939 mean=0.000786 n=165 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2188 mean=0.003417 n=192 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2256 mean=0.00267 n=133 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2593 mean=0.001698 n=189 — opinion flip did not match next-week price
