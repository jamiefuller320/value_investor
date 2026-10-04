# Trajectory evidence review

Generated: 2026-10-04T07:04:44.039242+00:00
Archive snapshots: 36
Transition events: 2420
Boundary watch panel: 233
Loser snapshot cards: None

## Boundary watch

- Panel count: 233 (core tags only; mean weeks on boundary=24.85)
- avoid_recovery_candidate: 6
- buy_weakening: 1
- hold_deteriorating: 2
- hold_improving: 2
- pre_avoid: 17
- pre_buy: 155
- strong_buy_candidate: 51

## Outcome summary (1-week forward)

- Upgrades: n=330 mean=0.003793 positive_rate=0.2848
- Downgrades: n=191 mean=0.004356 positive_rate=0.3351

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=135 mean=0.002252 positive_rate=0.3111
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=65 mean=0.005686 positive_rate=0.3692
- buy->strong_buy: n=42 mean=0.007672 positive_rate=0.381
- hold->avoid: n=84 mean=0.001604 positive_rate=0.3333
- hold->buy: n=121 mean=0.005403 positive_rate=0.281
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=1871 mean=-0.000903 positive_rate=0.3763
- strong_buy->buy: n=40 mean=0.006958 positive_rate=0.275
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1280 hit_rate=0.3125
- 4w: scored=1253 hit_rate=0.3775
- 8w: scored=1210 hit_rate=0.4719
- 12w: scored=1156 hit_rate=0.4498

## Weeks to realization

- Realized within 12w: 939/1308 (rate=0.7179)
- Median weeks: 2
- Within 4w rate: 0.688

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.275 mean=0.006958 n=40 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.281 mean=0.005403 n=121 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3111 mean=0.002252 n=135 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3333 mean=0.001604 n=84 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.3692 mean=0.005686 n=65 — opinion flip did not match next-week price
