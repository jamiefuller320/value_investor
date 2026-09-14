# Trajectory evidence review

Generated: 2026-09-14T07:13:56.376392+00:00
Archive snapshots: 19
Transition events: 1645
Boundary watch panel: 231
Loser snapshot cards: None

## Boundary watch

- Panel count: 231 (core tags only; mean weeks on boundary=11.53)
- avoid_recovery_candidate: 10
- hold_improving: 1
- pre_avoid: 20
- pre_buy: 156
- strong_buy_candidate: 44

## Outcome summary (1-week forward)

- Upgrades: n=269 mean=0.004535 positive_rate=0.2639
- Downgrades: n=135 mean=0.008466 positive_rate=0.3926

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=111 mean=0.001831 positive_rate=0.2793
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=47 mean=0.010751 positive_rate=0.4255
- buy->strong_buy: n=27 mean=0.009669 positive_rate=0.4444
- hold->avoid: n=62 mean=0.003307 positive_rate=0.3548
- hold->buy: n=100 mean=0.007838 positive_rate=0.26
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=741 mean=0.000378 positive_rate=0.3077
- strong_buy->buy: n=24 mean=0.015968 positive_rate=0.4167
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1002 hit_rate=0.2924
- 4w: scored=891 hit_rate=0.3367
- 8w: scored=545 hit_rate=0.5046
- 12w: scored=345 hit_rate=0.4609

## Weeks to realization

- Realized within 12w: 674/1012 (rate=0.666)
- Median weeks: 2.0
- Within 4w rate: 0.6439

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.26 mean=0.007838 n=100 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.2793 mean=0.001831 n=111 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.3077 mean=0.000378 n=741 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3548 mean=0.003307 n=62 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.2924 at 1w (n=1002) — implied upgrade/downgrade/conviction sign is not beating chance
