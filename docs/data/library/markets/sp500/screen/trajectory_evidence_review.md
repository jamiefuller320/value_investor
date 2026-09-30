# Trajectory evidence review

Generated: 2026-09-30T07:22:06.141575+00:00
Archive snapshots: 34
Transition events: 2317
Boundary watch panel: 240
Loser snapshot cards: None

## Boundary watch

- Panel count: 240 (core tags only; mean weeks on boundary=23.36)
- avoid_recovery_candidate: 9
- buy_weakening: 4
- hold_deteriorating: 1
- hold_improving: 3
- pre_avoid: 20
- pre_buy: 156
- strong_buy_candidate: 51

## Outcome summary (1-week forward)

- Upgrades: n=326 mean=0.003839 positive_rate=0.2883
- Downgrades: n=186 mean=0.004473 positive_rate=0.3441

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=132 mean=0.002303 positive_rate=0.3182
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=64 mean=0.005774 positive_rate=0.375
- buy->strong_buy: n=42 mean=0.007672 positive_rate=0.381
- hold->avoid: n=83 mean=0.001624 positive_rate=0.3373
- hold->buy: n=121 mean=0.005403 positive_rate=0.281
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=1303 mean=-0.000996 positive_rate=0.3415
- strong_buy->buy: n=37 mean=0.007522 positive_rate=0.2973
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1257 hit_rate=0.315
- 4w: scored=1228 hit_rate=0.373
- 8w: scored=1191 hit_rate=0.4694
- 12w: scored=1106 hit_rate=0.4521

## Weeks to realization

- Realized within 12w: 913/1274 (rate=0.7166)
- Median weeks: 2
- Within 4w rate: 0.6857

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.281 mean=0.005403 n=121 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2973 mean=0.007522 n=37 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3182 mean=0.002303 n=132 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3373 mean=0.001624 n=83 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3415 mean=-0.000996 n=1303 — opinion flip did not match next-week price
