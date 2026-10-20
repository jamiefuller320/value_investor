# Trajectory evidence review

Generated: 2026-10-20T07:24:44.479422+00:00
Archive snapshots: 53
Transition events: 3725
Boundary watch panel: 179
Loser snapshot cards: None

## Boundary watch

- Panel count: 179 (core tags only; mean weeks on boundary=25.64)
- avoid_recovery_candidate: 5
- hold_deteriorating: 2
- hold_improving: 1
- pre_avoid: 23
- pre_buy: 115
- strong_buy_candidate: 34

## Outcome summary (1-week forward)

- Upgrades: n=438 mean=0.003008 positive_rate=0.242
- Downgrades: n=322 mean=0.002566 positive_rate=0.2174

### By transition key
- avoid->buy: n=2 mean=-0.051723 positive_rate=0.0
- avoid->hold: n=168 mean=0.002012 positive_rate=0.2798
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=103 mean=0.003319 positive_rate=0.2524
- buy->strong_buy: n=73 mean=0.004643 positive_rate=0.274
- hold->avoid: n=138 mean=0.001205 positive_rate=0.2246
- hold->buy: n=164 mean=0.004078 positive_rate=0.2256
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=2464 mean=-0.003403 positive_rate=0.2999
- strong_buy->buy: n=78 mean=0.003444 positive_rate=0.1538
- strong_buy->hold: n=2 mean=0.026689 positive_rate=0.5

## Multi-horizon prediction calibration

- 1w: scored=1824 hit_rate=0.2429
- 4w: scored=1794 hit_rate=0.403
- 8w: scored=1702 hit_rate=0.4671
- 12w: scored=1393 hit_rate=0.458

## Weeks to realization

- Realized within 12w: 1301/1834 (rate=0.7094)
- Median weeks: 2
- Within 4w rate: 0.7479

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1538 mean=0.003444 n=78 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.2246 mean=0.001205 n=138 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2256 mean=0.004078 n=164 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.2524 mean=0.003319 n=103 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.274 mean=0.004643 n=73 — opinion flip did not match next-week price
