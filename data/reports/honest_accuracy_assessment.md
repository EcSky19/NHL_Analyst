> **CORRECTION / RETRACTION (2026-08-05):** This report is retained for history, but its benchmark claims and/or market-feature interpretation are not valid as headline evidence. The previously promoted 61.66% / 61.89% / 62.04% figures were invalidated by fabricated 2015-2018 seasons, circular synthetic market proxies, and selection overfitting. The corrected real-only, no-market benchmark is **56.82%** over 5,248 games; see `data\reports\data_integrity_audit.md`. The only clean 70%+ confidence-tier finding is **77.40%** at `confidence >= 0.70`, covering **177 games / 3.37%**; see `data\reports\confidence_tiers_clean_verification.md`. If this report discusses market features, they are synthetic pregame-stat proxies, **not** real Vegas/odds data.

# Honest NHL Accuracy Assessment

Generated: 2026-08-05

## Headline result

**Honest strict-holdout accuracy: 58.69%** on the most recent real season in the database, **2025-2026** (770/1,312 games; Wilson 95% CI **56.00%-61.32%**).

This uses only the real five-season sample present in the database: `20212022`, `20222023`, `20232024`, `20242025`, `20252026` (6,560 games). The fabricated `20152016`-`20172018` rows were excluded. Market-signal columns were excluded because they are circular/non-betting-derived.

Protocol used for this estimate:

- Candidate model family: deterministic regularized logistic regression over non-market pregame roster/team/context features from `deep_feature_expansion_v4_features`.
- Hyperparameters selected only inside the pre-holdout training window (`20212022`-`20242025`) via walk-forward validation.
- Selected frozen hyperparameters: learning rate `0.05`, L2 `0.08`, epochs `400`.
- Final model trained on `20212022`-`20242025`, then evaluated once on `20252026`.

Same-holdout baselines:

| Model / baseline | Games | Accuracy | 95% CI | Edge vs baseline |
|---|---:|---:|---:|---:|
| Honest frozen model | 1,312 | **58.69%** | 56.00%-61.32% | -- |
| Always pick home | 1,312 | 52.21% | 49.50%-54.90% | +6.48 pp |
| Simple Elo-only baseline | 1,312 | 53.96% | 51.26%-56.64% | +4.73 pp |

The model beats trivial baselines on this holdout, but the honest all-games number is **not 62%**.

## Selection-bias analysis

The prior process repeatedly compared variants against the same walk-forward/test seasons, then promoted the max. I counted:

- **761** accuracy-bearing rows in summary/comparison/candidate CSV artifacts.
- **391** unique configuration/accuracy records after removing obvious duplicate rows across mirrored overall/comparison files.
- **2,409** recorded accuracy-bearing candidate entries if nested JSON blend/weight-selection diagnostics are also included.

So the effective number of tries is not one; it is at least hundreds of recorded comparisons, with many correlated variants.

Observed artifact accuracy spread across recorded candidates was roughly **48.0%-63.5%**, with a standard deviation near **2.6 percentage points**. Not all of that spread is noise, but with ~6,500 games the binomial standard error near 60% is about **0.6 pp**. Picking the maximum from many noisy, correlated estimates plausibly adds about **1-2 pp** of optimism; if the hundreds of trials were independent, the expected max-noise bonus would be about **2.1 pp**. The latest **62.04%** should therefore be treated as an optimistic selected-on-test number, not an unbiased headline.

For the reported 62.04%:

- If evaluated on 1,312 games, 95% CI is about **59.39%-64.63%**.
- If evaluated on all 6,560 real games, 95% CI is about **60.86%-63.21%**.
- These intervals do **not** include selection-overfitting bias; they are only sampling intervals.

## Which reported gains are statistically meaningful?

Reported sequence: **57.88 -> 59.76 -> 61.66 -> 61.89 -> 62.04**.

Using the requested practical rule that differences under roughly **1.2 pp** are not meaningful with this sample size:

| Step | Gain | Interpretation |
|---|---:|---|
| 57.88% -> 59.76% | +1.88 pp | Likely distinguishable from sampling noise, though still subject to model-selection bias. |
| 59.76% -> 61.66% | +1.90 pp | Likely distinguishable from sampling noise, though still subject to model-selection bias. |
| 61.66% -> 61.89% | +0.23 pp | Noise; not statistically meaningful. |
| 61.89% -> 62.04% | +0.15 pp | Noise; not statistically meaningful. This includes the blend weight selected on test performance. |

The broad improvement from the earliest models to ~61% may be real. The final climb from **61.66% to 62.04% is not statistically credible** and is exactly where selection overfitting is most likely.

## Confidence-tier analysis correction (clean pooled verification)

The original single-holdout tier table below this heading has been superseded by `data\reports\confidence_tiers_clean_verification.md`. It was not shown to be inflated by `market_*` leakage: reproducing the 2025-2026 frozen-logistic holdout with fabricated seasons and market-derived features excluded gives the same 58.69% / 77.42% single-season figures.

However, those figures came from a different ad-hoc frozen logistic experiment than the audited benchmark in `data_integrity_audit.md`, and they covered only one season. The corrected clean pooled benchmark uses `data\processed\execution_plan\honest_real_only_no_market\predictions.csv` over 2022-2023 through 2025-2026.

## Clean pooled confidence buckets

Basis: `honest_real_only_no_market` predictions, real test seasons 2022-2023 through 2025-2026, N=5,248. Confidence = `max(home_win_probability, away_win_probability)`. Calibration gap = accuracy minus average confidence.

| Confidence bucket | Games | Coverage | Accuracy | Wilson 95% CI | Avg confidence | Calibration gap |
|---|---:|---:|---:|---:|---:|---:|
| 0.50-0.55 | 1,931 | 36.79% | 51.84% | 49.61%-54.06% | 52.49% | -0.65 pp |
| 0.55-0.60 | 1,619 | 30.85% | 55.22% | 52.79%-57.63% | 57.41% | -2.19 pp |
| 0.60-0.65 | 1,000 | 19.05% | 59.80% | 56.73%-62.80% | 62.37% | -2.57 pp |
| 0.65-0.70 | 521 | 9.93% | 67.56% | 63.43%-71.44% | 67.10% | +0.46 pp |
| 0.70-0.75 | 136 | 2.59% | 80.88% | 73.46%-86.61% | 71.89% | +9.00 pp |
| 0.75-0.80 | 32 | 0.61% | 65.62% | 48.31%-79.59% | 76.59% | -10.96 pp |
| 0.80+ | 9 | 0.17% | 66.67% | 35.42%-87.94% | 87.28% | -20.61 pp |

## Clean cumulative thresholds

| Minimum confidence | Games | Coverage | Accuracy | Wilson 95% CI | Avg confidence | Calibration gap | Note |
|---|---:|---:|---:|---:|---:|---:|---|
| >=0.55 | 3,317 | 63.21% | 59.72% | 58.04%-61.38% | 61.29% | -1.56 pp |  |
| >=0.60 | 1,698 | 32.36% | 64.02% | 61.70%-66.27% | 64.98% | -0.97 pp |  |
| >=0.65 | 698 | 13.30% | 70.06% | 66.56%-73.34% | 68.73% | +1.33 pp | 70% point estimate only; CI lower below 70% |
| >=0.70 | 177 | 3.37% | 77.40% | 70.70%-82.94% | 73.52% | +3.88 pp | passes 70% lower-bound test |
| >=0.75 | 41 | 0.78% | 65.85% | 50.55%-78.44% | 78.93% | -13.08 pp | too small to rely on |
| >=0.80 | 9 | 0.17% | 66.67% | 35.42%-87.94% | 87.28% | -20.61 pp | too small to rely on |

## Direct answer

Yes, on this clean pooled benchmark, `confidence >=0.70` reaches >=70% with the 95% CI lower bound also >=70%: **77.40% accuracy** on **177 games**, covering **3.37%** of scored games, with Wilson 95% CI **70.70%-82.94%**.

However, the old operational headline was inflated in coverage, not by market leakage: the verified clean pooled threshold covers only 3.37%, not 11.8%. Thresholds `>=0.75` and `>=0.80` are under 100 games and should not be relied on; they also show severe overconfidence. The best honest tradeoff before the lower-bound test is `>=0.65`: **70.06%** point accuracy over **698 games / 13.30% coverage**, but its CI lower bound is only **66.56%**, so it does not support a statistically defensible 70% claim.
