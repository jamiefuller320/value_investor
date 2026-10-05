# Trajectory evidence review

Generated: 2026-10-05T07:30:39.037137+00:00
Archive snapshots: 37
Transition events: 2716
Boundary watch panel: 245
Loser snapshot cards: None

## Boundary watch

- Panel count: 245 (core tags only; mean weeks on boundary=22.99)
- avoid_recovery_candidate: 5
- buy_weakening: 7
- hold_deteriorating: 8
- hold_improving: 9
- pre_avoid: 26
- pre_buy: 154
- strong_buy_candidate: 46

## Outcome summary (1-week forward)

- Upgrades: n=341 mean=0.003671 positive_rate=0.2757
- Downgrades: n=196 mean=0.004245 positive_rate=0.3265

### By transition key
- avoid->buy: n=1 mean=-0.103446 positive_rate=0.0
- avoid->hold: n=137 mean=0.002219 positive_rate=0.3066
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=67 mean=0.005516 positive_rate=0.3582
- buy->strong_buy: n=46 mean=0.007005 positive_rate=0.3478
- hold->avoid: n=86 mean=0.001567 positive_rate=0.3256
- hold->buy: n=126 mean=0.005188 positive_rate=0.2698
- hold->strong_buy: n=31 mean=0.002422 positive_rate=0.0645
- signal_unchanged: n=1679 mean=-0.001464 positive_rate=0.296
- strong_buy->buy: n=41 mean=0.006788 positive_rate=0.2683
- strong_buy->hold: n=1 mean=0.053377 positive_rate=1.0

## Multi-horizon prediction calibration

- 1w: scored=1301 hit_rate=0.3044
- 4w: scored=1248 hit_rate=0.3782
- 8w: scored=1205 hit_rate=0.4705
- 12w: scored=1158 hit_rate=0.4482

## Weeks to realization

- Realized within 12w: 932/1355 (rate=0.6878)
- Median weeks: 2.0
- Within 4w rate: 0.691

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0645 mean=0.002422 n=31 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.2683 mean=0.006788 n=41 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.2698 mean=0.005188 n=126 — opinion flip did not match next-week price
- [transition_key] signal_unchanged 1w positive_rate=0.296 mean=-0.001464 n=1679 — opinion flip did not match next-week price
- [transition_key] avoid->hold 1w positive_rate=0.3066 mean=0.002219 n=137 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.3256 mean=0.001567 n=86 — opinion flip did not match next-week price
