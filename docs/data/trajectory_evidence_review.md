# Trajectory evidence review

Generated: 2026-11-15T10:37:45.374807+00:00
Archive snapshots: 33
Transition events: 1637
Boundary watch panel: 91
Loser snapshot cards: 91

## Boundary watch

- Panel count: 91 (core tags only; mean weeks on boundary=6.78)
- avoid_recovery_candidate: 1
- pre_avoid: 55
- pre_buy: 19
- strong_buy_candidate: 11
- timing_wait_on_buy_tier: 5

## Outcome summary (1-week forward)

- Upgrades: n=193 mean=-0.003908 positive_rate=0.399
- Downgrades: n=212 mean=-0.000335 positive_rate=0.4528

### By transition key
- avoid->buy: n=2 mean=-0.007228 positive_rate=0.0
- avoid->hold: n=71 mean=-0.002266 positive_rate=0.4225
- buy->avoid: n=1 mean=0.004962 positive_rate=1.0
- buy->hold: n=76 mean=0.002963 positive_rate=0.4605
- buy->strong_buy: n=37 mean=-0.001471 positive_rate=0.5405
- hold->avoid: n=93 mean=0.002103 positive_rate=0.5054
- hold->buy: n=80 mean=-0.00511 positive_rate=0.3375
- hold->insufficient_data: n=5 mean=-0.008589 positive_rate=0.4
- hold->strong_buy: n=3 mean=-0.038536 positive_rate=0.0
- insufficient_data->hold: n=5 mean=-0.008409 positive_rate=0.4
- signal_unchanged: n=1206 mean=-0.003271 positive_rate=0.374
- strong_buy->buy: n=40 mean=-0.010612 positive_rate=0.325
- strong_buy->hold: n=2 mean=-0.036125 positive_rate=0.0

## Multi-horizon prediction calibration

- 1w: scored=1211 hit_rate=0.3683
- 4w: scored=1160 hit_rate=0.4353
- 8w: scored=909 hit_rate=0.4554
- 12w: scored=797 hit_rate=0.4617

## Weeks to realization

- Realized within 12w: 918/1226 (rate=0.7488)
- Median weeks: 2.0
- Within 4w rate: 0.817

## Model focus candidates (for analysis-review scoring)

- [transition_key] strong_buy->buy 1w positive_rate=0.325 mean=-0.010612 n=40 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.3375 mean=-0.00511 n=80 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.374 mean=-0.003271 n=1206 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.4225 mean=-0.002266 n=71 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.5405 mean=-0.001471 n=37 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.3683 at 1w (n=1211) — implied upgrade/downgrade/conviction sign is not beating chance
