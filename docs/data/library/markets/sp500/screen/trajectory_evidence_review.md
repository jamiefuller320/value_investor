# Trajectory evidence review

Generated: 2026-09-16T07:15:49.979257+00:00
Archive snapshots: 21
Transition events: 1722
Boundary watch panel: 228
Loser snapshot cards: None

## Boundary watch

- Panel count: 228 (core tags only; mean weeks on boundary=13.19)
- avoid_recovery_candidate: 8
- hold_deteriorating: 1
- hold_improving: 4
- pre_avoid: 20
- pre_buy: 150
- strong_buy_candidate: 48

## Outcome summary (1-week forward)

- Upgrades: n=273 mean=0.004391 positive_rate=0.2637
- Downgrades: n=146 mean=0.006497 positive_rate=0.3767

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=113 mean=0.001396 positive_rate=0.2743
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=50 mean=0.009209 positive_rate=0.42
- buy->strong_buy: n=27 mean=0.009669 positive_rate=0.4444
- hold->avoid: n=67 mean=0.001698 positive_rate=0.3433
- hold->buy: n=102 mean=0.007925 positive_rate=0.2647
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=802 mean=-0.000112 positive_rate=0.3204
- strong_buy->buy: n=27 mean=0.012035 positive_rate=0.3704
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1036 hit_rate=0.305
- 4w: scored=975 hit_rate=0.3497
- 8w: scored=831 hit_rate=0.4946
- 12w: scored=375 hit_rate=0.4667

## Weeks to realization

- Realized within 12w: 751/1059 (rate=0.7092)
- Median weeks: 2
- Within 4w rate: 0.6565

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2647 mean=0.007925 n=102 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2743 mean=0.001396 n=113 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3204 mean=-0.000112 n=802 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3433 mean=0.001698 n=67 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3704 mean=0.012035 n=27 — opinion flip did not match next-week price
