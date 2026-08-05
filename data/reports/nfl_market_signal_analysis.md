# NFL market signal analysis

Generated: 2026-08-05

## Verdict

The closing market is strong and broadly calibrated. On the common 2014-2025 walk-forward sample, **Market only** scored 66.24% while **Market + team features** scored 66.34%. The incremental accuracy was **+0.10 pp** with an approximate paired 95% CI of -0.79 pp to +0.99 pp, far below the established 1.65 pp full-sample minimum detectable difference; log loss was worse after adding team features. This is not evidence of predictive signal beyond the market.

The realistic straight-up ceiling for this project is therefore matching the market, roughly **66%-67%**. A durable **70%** target would require about +3.4 pp over closing moneyline favorites; these tests do not support that as attainable with the available team/EPA/QB features.

## Market calibration

Moneyline probabilities are de-vigged by normalizing home and away implied American-odds probabilities. Buckets use favorite probability.

| Bucket | Games | Avg implied | Actual | Wilson | Actual - implied |
| --- | --- | --- | --- | --- | --- |
| 50-55% | 642 | 52.60% | 53.12% | 49.25%-56.95% | 0.52% |
| 55-60% | 876 | 57.48% | 56.28% | 52.97%-59.53% | -1.20% |
| 60-65% | 930 | 62.53% | 59.46% | 56.27%-62.57% | -3.06% |
| 65-70% | 751 | 67.58% | 67.38% | 63.94%-70.63% | -0.20% |
| 70-75% | 718 | 72.56% | 73.40% | 70.05%-76.50% | 0.84% |
| 75-80% | 550 | 77.47% | 78.91% | 75.31%-82.11% | 1.44% |
| 80-90% | 536 | 84.20% | 85.45% | 82.21%-88.18% | 1.25% |
| 90-100% | 48 | 91.58% | 95.83% | 86.02%-98.85% | 4.25% |

Mean absolute calibration error across buckets: **1.32%**.

## Pre-registered market-bias slices

Slices tested before looking at outcomes: home underdogs, large favorites, division games, primetime, bad weather, and high totals. The test is calibration within the slice (actual favorite win rate minus average de-vigged implied favorite probability), not whether favorites in that slice win more than other favorites. Bonferroni correction uses these six tests.

| Slice | Games | Avg implied | Actual favorite win | Wilson | Calibration gap | p | Bonferroni significant |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Large favorites (>=75%) | 1134 | 81.25% | 82.72% | 80.41%-84.81% | 1.47% | 0.2054 | False |
| Bad weather | 693 | 67.31% | 65.08% | 61.46%-68.54% | -2.23% | 0.2112 | False |
| High totals | 2534 | 66.81% | 67.48% | 65.63%-69.28% | 0.68% | 0.4700 | False |
| Home underdogs | 1826 | 64.36% | 65.06% | 62.84%-67.21% | 0.70% | 0.5345 | False |
| Division games | 1840 | 67.27% | 66.74% | 64.55%-68.86% | -0.53% | 0.6278 | False |
| Primetime | 930 | 66.56% | 67.31% | 64.23%-70.25% | 0.75% | 0.6286 | False |

No tested slice survives correction as a reliable exploitable calibration bias. Apparent slice gaps should be treated as noise unless they replicate out of sample.

## Incremental value test

Common sample: regular-season, non-tie, played games with market probability available; expanding walk-forward by season; first scored season 2014; training uses only prior seasons. Team features are lagged only: Elo before game, rolling prior-game EPA/success/turnover/QB features, rest, division, weather, and total.

| Model | Games | Correct | Accuracy | Wilson | Log loss |
| --- | --- | --- | --- | --- | --- |
| Market only | 3140 | 2080 | 66.24% | 66.24% (64.57%-67.88%) | 0.6112 |
| Team features only | 3140 | 2009 | 63.98% | 63.98% (62.29%-65.64%) | 0.6305 |
| Market + team features | 3140 | 2083 | 66.34% | 66.34% (64.67%-67.97%) | 0.6154 |

Market + team log loss changed from 0.6112 to 0.6154. The team-only model is useful football signal but remains behind the market and does not add measurable accuracy once market price is included.

## Residual signal test

Pre-registered residual tests: whether out-of-fold team-only disagreement flags actual market misses, and whether a regularized classifier using only team features can identify market misses.

| Test | Games | Value | Detail |
| --- | --- | --- | --- |
| Market misses flagged by team-only disagreement | 1059 | 22.29% | 236 of 1059 market misses |
| Team-only accuracy when it disagreed with market | 544 | 43.38% | 43.38% (39.28%-47.58%) |
| Residual miss classifier ROC AUC | 3140 | 54.89% | Base miss rate 33.73% |
| Top-decile predicted miss rate | 314 | 35.67% | Lift vs base +1.94 pp |

The team-only model flags only a minority of market misses, and its disagreement accuracy is not enough to improve Market + team performance. The residual miss classifier is near chance, so the available features do not reliably predict the market's errors.

## Direct answer on 70%

Do not invest under the assumption that 70% straight-up accuracy is reachable from these inputs. The evidence says a model that includes `spread_line` or moneyline will mostly reproduce Vegas around the mid-60s. Without a new, genuinely exogenous signal unavailable to the closing market, **66%-67% is the practical ceiling** and 70% should be considered unrealistic.
