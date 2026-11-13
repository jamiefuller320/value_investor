# Trajectory evidence review

Generated: 2026-11-13T07:21:54.140598+00:00
Archive snapshots: 85
Transition events: 4794
Boundary watch panel: 197
Loser snapshot cards: None

## Boundary watch

- Panel count: 197 (core tags only; mean weeks on boundary=32.34)
- avoid_recovery_candidate: 7
- hold_deteriorating: 2
- hold_improving: 1
- pre_avoid: 17
- pre_buy: 127
- strong_buy_candidate: 43

## Outcome summary (1-week forward)

- Upgrades: n=615 mean=0.002032 positive_rate=0.1886
- Downgrades: n=512 mean=0.001622 positive_rate=0.1504

### By transition key
- avoid->buy: n=3 mean=-0.034482 positive_rate=0.0
- avoid->hold: n=234 mean=0.001372 positive_rate=0.2094
- buy->avoid: n=1 mean=-0.004061 positive_rate=0.0
- buy->hold: n=178 mean=0.001995 positive_rate=0.1685
- buy->strong_buy: n=104 mean=0.00366 positive_rate=0.2212
- hold->avoid: n=208 mean=0.000624 positive_rate=0.1538
- hold->buy: n=230 mean=0.002852 positive_rate=0.1826
- hold->strong_buy: n=44 mean=-0.000102 positive_rate=0.0455
- signal_unchanged: n=3648 mean=-0.000727 positive_rate=0.2667
- strong_buy->buy: n=117 mean=0.002532 positive_rate=0.1197
- strong_buy->hold: n=8 mean=0.006672 positive_rate=0.125

## Multi-horizon prediction calibration

- 1w: scored=2847 hit_rate=0.1992
- 4w: scored=2770 hit_rate=0.4029
- 8w: scored=2722 hit_rate=0.4787
- 12w: scored=2647 hit_rate=0.4658

## Weeks to realization

- Realized within 12w: 2017/2866 (rate=0.7038)
- Median weeks: 2
- Within 4w rate: 0.71

## Model focus candidates (for analysis-review scoring)

- [transition_key] hold->strong_buy 1w positive_rate=0.0455 mean=-0.000102 n=44 — opinion flip did not match next-week price
- [transition_key] strong_buy->buy 1w positive_rate=0.1197 mean=0.002532 n=117 — opinion flip did not match next-week price
- [transition_key] strong_buy->hold 1w positive_rate=0.125 mean=0.006672 n=8 — opinion flip did not match next-week price
- [transition_key] hold->avoid 1w positive_rate=0.1538 mean=0.000624 n=208 — opinion flip did not match next-week price
- [transition_key] buy->hold 1w positive_rate=0.1685 mean=0.001995 n=178 — opinion flip did not match next-week price
- [transition_key] hold->buy 1w positive_rate=0.1826 mean=0.002852 n=230 — opinion flip did not match next-week price
