# Buy-tier chart outcomes

69 terrible path(s) among 1125 buy-tier charts — inspect weakest names before treating timing as benign.

**Verdict:** Has terrible outcomes (`has_terrible`)

Observe-only. Frozen initial recommendation levels + first crossings. Not a decision-review input.

Short-term underwater is expected while the hypothesis stands. The test is the longer path — do not retune entry timing from this mix.

## Counts

- Charts: 1125
- Well timed: 253
- Target then fade: 2
- Underwater (no target): 427
- Intact positive: 233
- Flat: 141
- Terrible: 69
- Stop hits: 7
- Target hits: 27

## Returns since recommendation

- Median: +0.0%
- Mean: +0.3%
- Range: -54.3% to +76.6%
- Median drawdown: -4.8%
- Worst drawdown: -56.6%

## Well timed

| Ticker | Signal | Return | Drawdown | Days to target |
|---|---|---:|---:|---:|
| RWS.L | buy | +76.6% | -1.7% | — |
| ACN | strong_buy | +63.9% | -4.1% | — |
| SAP.DE | hold | +51.6% | -7.2% | — |
| THG.L | avoid | +50.7% | +0.0% | — |
| JSE.L | hold | +43.3% | -6.6% | — |
| NTAP | hold | +42.8% | +0.0% | — |
| MSFT | hold | +32.7% | -4.9% | — |
| BS6.SI | buy | +32.3% | +0.0% | — |

## Weakest open returns

| Ticker | Signal | Return | Drawdown | Outcome | Stop | Target |
|---|---|---:|---:|---|---|---|
| LNZ.VI | hold | -54.3% | -56.6% | terrible | no | no |
| APP | hold | -38.1% | -38.7% | terrible | no | no |
| SDY.L | hold | -32.4% | -32.6% | terrible | no | no |
| CIA.AX | hold | -31.7% | -33.8% | terrible | no | no |
| NIO | avoid | -31.6% | -32.2% | terrible | no | no |
| AMAT | hold | -29.3% | -33.0% | terrible | no | no |
| GBG.L | hold | -28.4% | -36.8% | terrible | no | no |
| MIN.AX | hold | -26.5% | -31.3% | terrible | no | no |

_Observe-only rollup of buy-tier chart JSON. Entry is the frozen initial last (recommendation-week close), not the first bar after signal_since. Short-term underwater is expected while the hypothesis stands — the test is the longer path. Do not apply decision-review knobs or entry-timing overlays from this file. Yahoo LSE GBp↔GBP ~100× mid-series flips are normalized before scoring (see price_unit_normalization on affected rows)._

