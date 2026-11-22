# Trajectory evidence review

Generated: 2026-11-22T10:38:08.778376+00:00
Archive snapshots: 34
Transition events: 1694
Boundary watch panel: 91
Loser snapshot cards: 91

## Boundary watch

- Panel count: 91 (core tags only; mean weeks on boundary=5.93)
- avoid_recovery_candidate: 1
- pre_avoid: 55
- pre_buy: 19
- strong_buy_candidate: 11
- timing_wait_on_buy_tier: 5

## Outcome summary (1-week forward)

- Upgrades: n=195 mean=-0.003479 positive_rate=0.4051
- Downgrades: n=220 mean=-0.001632 positive_rate=0.4455

### By transition key
- avoid->buy: n=2 mean=-0.007228 positive_rate=0.0
- avoid->hold: n=72 mean=-0.001534 positive_rate=0.4306
- buy->avoid: n=1 mean=0.004962 positive_rate=1.0
- buy->hold: n=80 mean=0.00114 positive_rate=0.45
- buy->strong_buy: n=37 mean=-0.001471 positive_rate=0.5405
- hold->avoid: n=94 mean=0.001566 positive_rate=0.5
- hold->buy: n=81 mean=-0.004734 positive_rate=0.3457
- hold->insufficient_data: n=5 mean=-0.008589 positive_rate=0.4
- hold->strong_buy: n=3 mean=-0.038536 positive_rate=0.0
- insufficient_data->hold: n=5 mean=-0.008409 positive_rate=0.4
- signal_unchanged: n=1209 mean=-0.003207 positive_rate=0.3755
- strong_buy->buy: n=43 mean=-0.012327 positive_rate=0.3256
- strong_buy->hold: n=2 mean=-0.036125 positive_rate=0.0

## Multi-horizon prediction calibration

- 1w: scored=1223 hit_rate=0.3729
- 4w: scored=1169 hit_rate=0.4363
- 8w: scored=1040 hit_rate=0.4452
- 12w: scored=819 hit_rate=0.4652

## Weeks to realization

- Realized within 12w: 942/1273 (rate=0.74)
- Median weeks: 2.0
- Within 4w rate: 0.8153

## Model focus candidates (for analysis-review scoring)

- [transition_key] strong_buy->buy 1w positive_rate=0.3256 mean=-0.012327 n=43 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.3457 mean=-0.004734 n=81 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3755 mean=-0.003207 n=1209 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.4306 mean=-0.001534 n=72 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.5405 mean=-0.001471 n=37 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.3729 at 1w (n=1223) — implied upgrade/downgrade/conviction sign is not beating chance
