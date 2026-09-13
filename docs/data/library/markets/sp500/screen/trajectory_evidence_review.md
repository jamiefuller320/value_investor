# Trajectory evidence review

Generated: 2026-09-13T06:48:13.323177+00:00
Archive snapshots: 18
Transition events: 1603
Boundary watch panel: 233
Loser snapshot cards: None

## Boundary watch

- Panel count: 233 (core tags only; mean weeks on boundary=10.46)
- avoid_recovery_candidate: 11
- buy_weakening: 1
- hold_deteriorating: 3
- hold_improving: 2
- pre_avoid: 22
- pre_buy: 154
- strong_buy_candidate: 43

## Outcome summary (1-week forward)

- Upgrades: n=260 mean=0.004692 positive_rate=0.2731
- Downgrades: n=130 mean=0.008792 positive_rate=0.4077

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=109 mean=0.001865 positive_rate=0.2844
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=44 mean=0.011484 positive_rate=0.4545
- buy->strong_buy: n=25 mean=0.010443 positive_rate=0.48
- hold->avoid: n=61 mean=0.003362 positive_rate=0.3607
- hold->buy: n=95 mean=0.008251 positive_rate=0.2737
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=713 mean=-0.000233 positive_rate=0.2959
- strong_buy->buy: n=23 mean=0.016662 positive_rate=0.4348
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=982 hit_rate=0.2984
- 4w: scored=880 hit_rate=0.3386
- 8w: scored=409 hit_rate=0.5257
- 12w: scored=314 hit_rate=0.4586

## Weeks to realization

- Realized within 12w: 674/1010 (rate=0.6673)
- Median weeks: 2.0
- Within 4w rate: 0.6439

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2737 mean=0.008251 n=95 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2844 mean=0.001865 n=109 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.2959 mean=-0.000233 n=713 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3607 mean=0.003362 n=61 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.2984 at 1w (n=982) — implied upgrade/downgrade/conviction sign is not beating chance
