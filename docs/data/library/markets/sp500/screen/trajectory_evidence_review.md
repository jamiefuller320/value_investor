# Trajectory evidence review

Generated: 2026-09-11T07:29:39.495708+00:00
Archive snapshots: 17
Transition events: 1533
Boundary watch panel: 234
Loser snapshot cards: None

## Boundary watch

- Panel count: 234 (core tags only; mean weeks on boundary=9.8)
- avoid_recovery_candidate: 9
- buy_weakening: 2
- hold_deteriorating: 3
- hold_improving: 1
- pre_avoid: 18
- pre_buy: 157
- strong_buy_candidate: 46

## Outcome summary (1-week forward)

- Upgrades: n=257 mean=0.004778 positive_rate=0.2724
- Downgrades: n=124 mean=0.009119 positive_rate=0.4032

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=108 mean=0.001926 positive_rate=0.287
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=41 mean=0.012299 positive_rate=0.4634
- buy->strong_buy: n=24 mean=0.011962 positive_rate=0.5
- hold->avoid: n=60 mean=0.003409 positive_rate=0.35
- hold->buy: n=94 mean=0.008098 positive_rate=0.266
- hold->strong_buy: n=30 mean=0.002503 positive_rate=0.0667
- signal_unchanged: n=651 mean=-0.000397 positive_rate=0.2719
- strong_buy->buy: n=21 mean=0.017742 positive_rate=0.4286
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=940 hit_rate=0.2936
- 4w: scored=825 hit_rate=0.3358
- 8w: scored=373 hit_rate=0.5416
- 12w: scored=281 hit_rate=0.4555

## Weeks to realization

- Realized within 12w: 638/960 (rate=0.6646)
- Median weeks: 2.0
- Within 4w rate: 0.6395

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0667 mean=0.002503 n=30 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.266 mean=0.008098 n=94 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.2719 mean=-0.000397 n=651 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.287 mean=0.001926 n=108 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.35 mean=0.003409 n=60 — opinion flip did not match next-week price
- [horizon_hit_rate] Directional hit_rate=0.2936 at 1w (n=940) — implied upgrade/downgrade/conviction sign is not beating chance
