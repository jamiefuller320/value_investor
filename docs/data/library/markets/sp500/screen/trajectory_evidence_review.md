# Trajectory evidence review

Generated: 2026-09-29T07:18:51.110694+00:00
Archive snapshots: 33
Transition events: 2261
Boundary watch panel: 232
Loser snapshot cards: None

## Boundary watch

- Panel count: 232 (core tags only; mean weeks on boundary=23.2)
- avoid_recovery_candidate: 9
- pre_avoid: 17
- pre_buy: 155
- strong_buy_candidate: 51

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
- signal_unchanged: n=1249 mean=-0.000627 positive_rate=0.3443
- strong_buy->buy: n=37 mean=0.007522 positive_rate=0.2973
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1245 hit_rate=0.3141
- 4w: scored=1215 hit_rate=0.3704
- 8w: scored=1172 hit_rate=0.471
- 12w: scored=1077 hit_rate=0.4522

## Weeks to realization

- Realized within 12w: 904/1254 (rate=0.7209)
- Median weeks: 2.0
- Within 4w rate: 0.6847

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2857 mean=0.005553 n=119 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2973 mean=0.007522 n=37 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3182 mean=0.002303 n=132 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3373 mean=0.001624 n=83 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3443 mean=-0.000627 n=1249 — opinion flip did not match next-week price
