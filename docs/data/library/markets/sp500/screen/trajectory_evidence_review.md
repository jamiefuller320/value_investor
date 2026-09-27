# Trajectory evidence review

Generated: 2026-09-27T06:57:56.111598+00:00
Archive snapshots: 31
Transition events: 2159
Boundary watch panel: 231
Loser snapshot cards: None

## Boundary watch

- Panel count: 231 (core tags only; mean weeks on boundary=21.54)
- avoid_recovery_candidate: 8
- buy_weakening: 1
- hold_deteriorating: 1
- pre_avoid: 15
- pre_buy: 158
- strong_buy_candidate: 49

## Outcome summary (1-week forward)

- Upgrades: n=323 mean=0.003897 positive_rate=0.291
- Downgrades: n=182 mean=0.004571 positive_rate=0.3516

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=132 mean=0.002303 positive_rate=0.3182
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=63 mean=0.005866 positive_rate=0.381
- buy->strong_buy: n=41 mean=0.007859 positive_rate=0.3902
- hold->avoid: n=81 mean=0.001664 positive_rate=0.3457
- hold->buy: n=119 mean=0.005553 positive_rate=0.2857
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=1152 mean=-0.000835 positive_rate=0.342
- strong_buy->buy: n=36 mean=0.007731 positive_rate=0.3056
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1228 hit_rate=0.316
- 4w: scored=1187 hit_rate=0.3698
- 8w: scored=1126 hit_rate=0.4725
- 12w: scored=1016 hit_rate=0.4449

## Weeks to realization

- Realized within 12w: 894/1242 (rate=0.7198)
- Median weeks: 2.0
- Within 4w rate: 0.6823

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2857 mean=0.005553 n=119 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.3056 mean=0.007731 n=36 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3182 mean=0.002303 n=132 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.342 mean=-0.000835 n=1152 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3457 mean=0.001664 n=81 — opinion flip did not match next-week price
