# Trajectory evidence review

Generated: 2026-09-15T07:30:30.936055+00:00
Archive snapshots: 20
Transition events: 1653
Boundary watch panel: 236
Loser snapshot cards: None

## Boundary watch

- Panel count: 236 (core tags only; mean weeks on boundary=12.12)
- avoid_recovery_candidate: 9
- buy_weakening: 3
- hold_deteriorating: 3
- hold_improving: 1
- pre_avoid: 19
- pre_buy: 154
- strong_buy_candidate: 47

## Outcome summary (1-week forward)

- Upgrades: n=270 mean=0.004382 positive_rate=0.263
- Downgrades: n=135 mean=0.008466 positive_rate=0.3926

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=112 mean=0.001488 positive_rate=0.2768
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=47 mean=0.010751 positive_rate=0.4255
- buy->strong_buy: n=27 mean=0.009669 positive_rate=0.4444
- hold->avoid: n=62 mean=0.003307 positive_rate=0.3548
- hold->buy: n=100 mean=0.007838 positive_rate=0.26
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=747 mean=0.000443 positive_rate=0.3119
- strong_buy->buy: n=24 mean=0.015968 positive_rate=0.4167
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1007 hit_rate=0.2939
- 4w: scored=942 hit_rate=0.3439
- 8w: scored=702 hit_rate=0.5028
- 12w: scored=375 hit_rate=0.4667

## Weeks to realization

- Realized within 12w: 722/1034 (rate=0.6983)
- Median weeks: 2.0
- Within 4w rate: 0.6524

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.26 mean=0.007838 n=100 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2768 mean=0.001488 n=112 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3119 mean=0.000443 n=747 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3548 mean=0.003307 n=62 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.2939 at 1w (n=1007) — implied upgrade/downgrade/conviction sign is not beating chance
