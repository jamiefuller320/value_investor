# Trajectory evidence review

Generated: 2026-09-09T07:21:40.825682+00:00
Archive snapshots: 16
Transition events: 1338
Boundary watch panel: 233
Loser snapshot cards: None

## Boundary watch

- Panel count: 233 (core tags only; mean weeks on boundary=9.02)
- avoid_recovery_candidate: 8
- buy_weakening: 2
- hold_improving: 1
- pre_avoid: 23
- pre_buy: 155
- strong_buy_candidate: 45

## Outcome summary (1-week forward)

- Upgrades: n=253 mean=0.004904 positive_rate=0.2688
- Downgrades: n=122 mean=0.009298 positive_rate=0.4016

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=107 mean=0.001822 positive_rate=0.2804
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=41 mean=0.012299 positive_rate=0.4634
- buy->strong_buy: n=23 mean=0.012805 positive_rate=0.5217
- hold->avoid: n=59 mean=0.003801 positive_rate=0.3559
- hold->buy: n=92 mean=0.008473 positive_rate=0.2609
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=466 mean=-0.000124 positive_rate=0.2318
- strong_buy->buy: n=20 mean=0.017828 positive_rate=0.4
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=810 hit_rate=0.2778
- 4w: scored=638 hit_rate=0.3041
- 8w: scored=353 hit_rate=0.5439
- 12w: scored=49 hit_rate=0.4286

## Weeks to realization

- Realized within 12w: 545/830 (rate=0.6566)
- Median weeks: 3
- Within 4w rate: 0.622

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.2318 mean=-0.000124 n=466 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2609 mean=0.008473 n=92 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2804 mean=0.001822 n=107 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3559 mean=0.003801 n=59 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.2778 at 1w (n=810) — implied upgrade/downgrade/conviction sign is not beating chance
