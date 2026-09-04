# Trajectory evidence review

Generated: 2026-09-04T07:20:54.618902+00:00
Archive snapshots: 13
Transition events: 731
Boundary watch panel: 218
Loser snapshot cards: None

## Boundary watch

- Panel count: 218 (core tags only; mean weeks on boundary=6.7)
- avoid_recovery_candidate: 5
- buy_weakening: 4
- hold_deteriorating: 7
- hold_improving: 6
- pre_avoid: 27
- pre_buy: 140
- strong_buy_candidate: 34

## Outcome summary (1-week forward)

- Upgrades: n=225 mean=0.004394 positive_rate=0.2711
- Downgrades: n=92 mean=0.01373 positive_rate=0.4674

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=89 mean=0.001363 positive_rate=0.3034
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=34 mean=0.015355 positive_rate=0.5
- buy->strong_buy: n=15 mean=0.016707 positive_rate=0.6
- hold->avoid: n=42 mean=0.007501 positive_rate=0.4286
- hold->buy: n=89 mean=0.007248 positive_rate=0.2584
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=319 mean=0.002149 positive_rate=0.2194
- strong_buy->buy: n=14 mean=0.026912 positive_rate=0.5
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=636 hit_rate=0.2563
- 4w: scored=355 hit_rate=0.1972
- 8w: scored=261 hit_rate=0.5211
- 12w: scored=0 hit_rate=None

## Weeks to realization

- Realized within 12w: 441/731 (rate=0.6033)
- Median weeks: 4
- Within 4w rate: 0.5374

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.2194 mean=0.002149 n=319 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2584 mean=0.007248 n=89 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3034 mean=0.001363 n=89 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.2563 at 1w (n=636) — implied upgrade/downgrade/conviction sign is not beating chance
- [horizon_hit_rate] Directional hit_rate=0.1972 at 4w (n=355) — implied upgrade/downgrade/conviction sign is not beating chance
