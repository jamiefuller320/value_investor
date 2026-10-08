# Trajectory evidence review

Generated: 2026-10-08T08:41:33.277775+00:00
Archive snapshots: 41
Transition events: 2962
Boundary watch panel: 239
Loser snapshot cards: None

## Boundary watch

- Panel count: 239 (core tags only; mean weeks on boundary=26.55)
- avoid_recovery_candidate: 5
- buy_weakening: 1
- hold_improving: 3
- pre_avoid: 25
- pre_buy: 153
- strong_buy_candidate: 53

## Outcome summary (1-week forward)

- Upgrades: n=376 mean=0.003166 positive_rate=0.25
- Downgrades: n=227 mean=0.003665 positive_rate=0.2819

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=147 mean=0.002068 positive_rate=0.2857
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=76 mean=0.004863 positive_rate=0.3158
- buy->strong_buy: n=55 mean=0.004747 positive_rate=0.2909
- hold->avoid: n=96 mean=0.001404 positive_rate=0.2917
- hold->buy: n=142 mean=0.004604 positive_rate=0.2394
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2342 mean=-0.000962 positive_rate=0.3292
- strong_buy->buy: n=52 mean=0.005352 positive_rate=0.2115
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1409 hit_rate=0.2825
- 4w: scored=1357 hit_rate=0.3876
- 8w: scored=1248 hit_rate=0.4736
- 12w: scored=1204 hit_rate=0.4435

## Weeks to realization

- Realized within 12w: 1003/1423 (rate=0.7048)
- Median weeks: 2
- Within 4w rate: 0.7079

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2115 mean=0.005352 n=52 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2394 mean=0.004604 n=142 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2857 mean=0.002068 n=147 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2909 mean=0.004747 n=55 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2917 mean=0.001404 n=96 — opinion flip did not match next-week price
