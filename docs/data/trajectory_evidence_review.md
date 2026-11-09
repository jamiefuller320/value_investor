# Trajectory evidence review

Generated: 2026-11-08T10:36:41.053152+00:00
Archive snapshots: 32
Transition events: 1624
Boundary watch panel: 68
Loser snapshot cards: 91

## Boundary watch

- Panel count: 68 (core tags only; mean weeks on boundary=8.29)
- avoid_recovery_candidate: 1
- pre_avoid: 33
- pre_buy: 22
- strong_buy_candidate: 7
- timing_wait_on_buy_tier: 5

## Outcome summary (1-week forward)

- Upgrades: n=191 mean=-0.004232 positive_rate=0.3927
- Downgrades: n=212 mean=-0.000335 positive_rate=0.4528

### By transition key
- avoid->buy: n=2 mean=-0.007228 positive_rate=0.0
- avoid->hold: n=71 mean=-0.002266 positive_rate=0.4225
- buy->avoid: n=1 mean=0.004962 positive_rate=1.0
- buy->hold: n=76 mean=0.002963 positive_rate=0.4605
- buy->strong_buy: n=36 mean=-0.001994 positive_rate=0.5278
- hold->avoid: n=93 mean=0.002103 positive_rate=0.5054
- hold->buy: n=79 mean=-0.005641 positive_rate=0.3291
- hold->insufficient_data: n=5 mean=-0.008589 positive_rate=0.4
- hold->strong_buy: n=3 mean=-0.038536 positive_rate=0.0
- insufficient_data->hold: n=5 mean=-0.008409 positive_rate=0.4
- signal_unchanged: n=1205 mean=-0.00329 positive_rate=0.3734
- strong_buy->buy: n=40 mean=-0.010612 positive_rate=0.325
- strong_buy->hold: n=2 mean=-0.036125 positive_rate=0.0

## Multi-horizon prediction calibration

- 1w: scored=1208 hit_rate=0.3675
- 4w: scored=1125 hit_rate=0.4329
- 8w: scored=881 hit_rate=0.4518
- 12w: scored=784 hit_rate=0.4592

## Weeks to realization

- Realized within 12w: 884/1214 (rate=0.7282)
- Median weeks: 1.0
- Within 4w rate: 0.8201

## Model focus candidates (for analysis-review scoring)

- [transition_key] strong_buy->buy 1w positive_rate=0.325 mean=-0.010612 n=40 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.3291 mean=-0.005641 n=79 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3734 mean=-0.00329 n=1205 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.4225 mean=-0.002266 n=71 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.5278 mean=-0.001994 n=36 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.3675 at 1w (n=1208) — implied upgrade/downgrade/conviction sign is not beating chance
