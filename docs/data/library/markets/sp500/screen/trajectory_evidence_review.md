# Trajectory evidence review

Generated: 2026-09-23T07:19:57.688835+00:00
Archive snapshots: 28
Transition events: 2040
Boundary watch panel: 232
Loser snapshot cards: None

## Boundary watch

- Panel count: 232 (core tags only; mean weeks on boundary=19.05)
- avoid_recovery_candidate: 9
- buy_weakening: 1
- pre_avoid: 16
- pre_buy: 157
- strong_buy_candidate: 49

## Outcome summary (1-week forward)

- Upgrades: n=311 mean=0.003975 positive_rate=0.283
- Downgrades: n=173 mean=0.005207 positive_rate=0.3468

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=127 mean=0.002491 positive_rate=0.315
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=61 mean=0.006304 positive_rate=0.377
- buy->strong_buy: n=36 mean=0.008819 positive_rate=0.3889
- hold->avoid: n=76 mean=0.001758 positive_rate=0.3289
- hold->buy: n=117 mean=0.00539 positive_rate=0.2735
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=1541 mean=1.8e-05 positive_rate=0.3933
- strong_buy->buy: n=34 mean=0.009802 positive_rate=0.3235
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1191 hit_rate=0.3132
- 4w: scored=1148 hit_rate=0.3702
- 8w: scored=1046 hit_rate=0.4713
- 12w: scored=948 hit_rate=0.4409

## Weeks to realization

- Realized within 12w: 864/1206 (rate=0.7164)
- Median weeks: 2.0
- Within 4w rate: 0.6794

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2735 mean=0.00539 n=117 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.315 mean=0.002491 n=127 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3235 mean=0.009802 n=34 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3289 mean=0.001758 n=76 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.377 mean=0.006304 n=61 — opinion flip did not match next-week price
