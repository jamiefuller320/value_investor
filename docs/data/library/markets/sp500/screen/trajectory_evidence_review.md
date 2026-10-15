# Trajectory evidence review

Generated: 2026-10-15T07:25:00.608569+00:00
Archive snapshots: 47
Transition events: 3605
Boundary watch panel: 160
Loser snapshot cards: None

## Boundary watch

- Panel count: 160 (core tags only; mean weeks on boundary=24.19)
- avoid_recovery_candidate: 4
- buy_weakening: 1
- pre_avoid: 26
- pre_buy: 108
- strong_buy_candidate: 21

## Outcome summary (1-week forward)

- Upgrades: n=425 mean=0.003143 positive_rate=0.2494
- Downgrades: n=301 mean=0.002825 positive_rate=0.2326

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=163 mean=0.002186 positive_rate=0.2883
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=97 mean=0.003774 positive_rate=0.268
- buy->strong_buy: n=70 mean=0.004842 positive_rate=0.2857
- hold->avoid: n=128 mean=0.001299 positive_rate=0.2422
- hold->buy: n=160 mean=0.00418 positive_rate=0.2313
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2858 mean=0.002725 positive_rate=0.3873
- strong_buy->buy: n=73 mean=0.00368 positive_rate=0.1644
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1735 hit_rate=0.2484
- 4w: scored=1443 hit_rate=0.4026
- 8w: scored=1386 hit_rate=0.4812
- 12w: scored=1259 hit_rate=0.4472

## Weeks to realization

- Realized within 12w: 1196/1756 (rate=0.6811)
- Median weeks: 2.0
- Within 4w rate: 0.7366

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1644 mean=0.00368 n=73 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2313 mean=0.00418 n=160 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2422 mean=0.001299 n=128 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.268 mean=0.003774 n=97 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.2857 mean=0.004842 n=70 — opinion flip did not match next-week price
