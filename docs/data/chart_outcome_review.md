# Buy-tier chart outcomes

74 terrible path(s) among 1092 buy-tier charts — inspect weakest names before treating timing as benign.

**Verdict:** Has terrible outcomes (`has_terrible`)

Observe-only. Frozen initial recommendation levels + first crossings. Not a decision-review input.

Short-term underwater is expected while the hypothesis stands. The test is the longer path — do not retune entry timing from this mix.

## Counts

- Charts: 1092
- Well timed: 165
- Target then fade: 5
- Underwater (no target): 476
- Intact positive: 231
- Flat: 141
- Terrible: 74
- Stop hits: 4
- Target hits: 22

## Returns since recommendation

- Median: -0.1%
- Mean: -1.0%
- Range: -53.9% to +100.0%
- Median drawdown: -5.1%
- Worst drawdown: -54.3%

## Well timed

| Ticker | Signal | Return | Drawdown | Days to target |
|---|---|---:|---:|---:|
| HEAD.L | hold | +100.0% | +0.0% | — |
| RWS.L | buy | +78.3% | -1.7% | — |
| ACN | strong_buy | +44.6% | -4.1% | — |
| CDA.AX | hold | +44.3% | -2.7% | — |
| HWG.L | avoid | +41.9% | +0.0% | — |
| BS6.SI | buy | +40.9% | +0.0% | — |
| FDEV.L | hold | +40.7% | -5.0% | — |
| PRU.AX | hold | +39.0% | -0.2% | — |

## Weakest open returns

| Ticker | Signal | Return | Drawdown | Outcome | Stop | Target |
|---|---|---:|---:|---|---|---|
| LNZ.VI | hold | -53.9% | -54.3% | terrible | no | no |
| MAB1.L | hold | -38.0% | -39.3% | terrible | no | no |
| GBG.L | hold | -33.5% | -36.8% | terrible | no | no |
| EIX | hold | -28.0% | -34.1% | terrible | no | no |
| SDY.L | hold | -26.8% | -26.8% | terrible | no | no |
| REG.AX | hold | -26.5% | -29.5% | terrible | no | no |
| NIO | avoid | -25.6% | -29.9% | terrible | no | no |
| TIT.MI | hold | -24.5% | -24.5% | terrible | no | no |

_Observe-only rollup of buy-tier chart JSON. Entry is the frozen initial last (recommendation-week close), not the first bar after signal_since. Short-term underwater is expected while the hypothesis stands — the test is the longer path. Do not apply decision-review knobs or entry-timing overlays from this file. Yahoo LSE GBp↔GBP ~100× mid-series flips are normalized before scoring (see price_unit_normalization on affected rows)._

