# Trajectory evidence review

Generated: 2026-08-25T06:24:54.105731+00:00
Archive snapshots: 10
Transition events: 383
Boundary watch panel: 57
Loser snapshot cards: 53

## Boundary watch

- Panel count: 57 (core tags only; mean weeks on boundary=6.91)
- pre_avoid: 29
- pre_buy: 22
- timing_wait_on_buy_tier: 6

## Outcome summary (1-week forward)

- Upgrades: n=49 mean=-0.003031 positive_rate=0.3469
- Downgrades: n=42 mean=0.006744 positive_rate=0.5238

### By transition key
- avoid->hold: n=17 mean=0.004647 positive_rate=0.5294
- buy->hold: n=16 mean=0.014583 positive_rate=0.5625
- buy->strong_buy: n=12 mean=-0.00492 positive_rate=0.25
- hold->avoid: n=16 mean=0.002368 positive_rate=0.4375
- hold->buy: n=20 mean=-0.008424 positive_rate=0.25
- hold->insufficient_data: n=3 mean=0.007928 positive_rate=0.6667
- insufficient_data->hold: n=3 mean=0.004663 positive_rate=0.3333
- signal_unchanged: n=239 mean=-0.002598 positive_rate=0.3431
- strong_buy->buy: n=9 mean=0.002237 positive_rate=0.6667
- strong_buy->hold: n=1 mean=-0.008092 positive_rate=0.0

## Multi-horizon prediction calibration

- 1w: scored=266 hit_rate=0.406
- 4w: scored=158 hit_rate=0.519
- 8w: scored=18 hit_rate=0.3889
- 12w: scored=0 hit_rate=None

## Weeks to realization

- Realized within 12w: 181/302 (rate=0.5993)
- Median weeks: 1
- Within 4w rate: 0.9448

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->buy 1w positive_rate=0.25 mean=-0.008424 n=20 — opinion flip did not match next-week price
- [transition_key] buy->strong_buy 1w positive_rate=0.25 mean=-0.00492 n=12 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3431 mean=-0.002598 n=239 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.406 at 1w (n=266) — implied upgrade/downgrade/conviction sign is not beating chance
- [horizon_hit_rate] Directional hit_rate=0.3889 at 8w (n=18) — implied upgrade/downgrade/conviction sign is not beating chance
- [realization_lag] 1w hit_rate=0.406 but within_4w realization=0.9448 (median=1w, n=181) — opinion changes may fire before price; timing/conviction delay candidate
