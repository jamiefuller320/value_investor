# Trajectory evidence review

Generated: 2026-09-28T07:24:09.179805+00:00
Archive snapshots: 32
Transition events: 2257
Boundary watch panel: 230
Loser snapshot cards: None

## Boundary watch

- Panel count: 230 (core tags only; mean weeks on boundary=22.63)
- avoid_recovery_candidate: 8
- pre_avoid: 15
- pre_buy: 158
- strong_buy_candidate: 49

## Outcome summary (1-week forward)

- Upgrades: n=324 mean=0.003885 positive_rate=0.2901
- Downgrades: n=186 mean=0.004473 positive_rate=0.3441

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=132 mean=0.002303 positive_rate=0.3182
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=64 mean=0.005774 positive_rate=0.375
- buy->strong_buy: n=42 mean=0.007672 positive_rate=0.381
- hold->avoid: n=83 mean=0.001624 positive_rate=0.3373
- hold->buy: n=119 mean=0.005553 positive_rate=0.2857
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=1245 mean=-0.000596 positive_rate=0.3454
- strong_buy->buy: n=37 mean=0.007522 positive_rate=0.2973
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1241 hit_rate=0.3151
- 4w: scored=1202 hit_rate=0.371
- 8w: scored=1152 hit_rate=0.4722
- 12w: scored=1046 hit_rate=0.4493

## Weeks to realization

- Realized within 12w: 896/1250 (rate=0.7168)
- Median weeks: 2.0
- Within 4w rate: 0.683

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2857 mean=0.005553 n=119 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2973 mean=0.007522 n=37 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3182 mean=0.002303 n=132 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3373 mean=0.001624 n=83 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3454 mean=-0.000596 n=1245 — opinion flip did not match next-week price
