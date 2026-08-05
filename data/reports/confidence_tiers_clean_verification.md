# Clean confidence-tier verification

Generated: 2026-08-05

## Verdict

The 2025-2026 discrepancy is not an apples-to-apples disagreement. `honest_accuracy_assessment.md` used a separate frozen logistic model on `deep_feature_expansion_v4_features` and a single 2025-2026 holdout; I reproduced its 770/1,312 = 58.69% result after excluding fabricated seasons and market-derived features. `data_integrity_audit.md` used the corrected benchmark artifact `data\processed\execution_plan\honest_real_only_no_market\predictions.csv`: an expanding walk-forward 50/50 blend of `weighted_calibrated` and `elo_form_tuned`, real seasons only, market excluded. For that benchmark, the comparable 2025-2026 figure is 698/1,312 = 53.20%.

So the audit's **53.20%** is the correct number for the audited benchmark. The older **58.69%** is only correct for a different, single-season frozen logistic experiment and should not be mixed with the benchmark.

## Artifact diagnosis

| Report | Feature source | Model/configuration | Prediction artifact | Synthetic rows? | Market/circular features? |
|---|---|---|---|---|---|
| `honest_accuracy_assessment.md` | `data\processed\execution_plan\deep_feature_expansion_v4\deep_feature_expansion_v4_features.csv` / DB table `deep_feature_expansion_v4_features` | deterministic regularized logistic regression; robust-scaled non-market features; selected `lr=0.05`, `l2=0.08`, `epochs=400`; trained on 2021-2022 through 2024-2025; tested once on 2025-2026 | no persisted prediction CSV found; reproduced from the feature CSV and script functions | excluded in the reported/reproduced 58.69% run | not included; source has no `market_*` columns and reproduced feature list excludes `market_*` / `market_signals_x_model_confidence` |
| `data_integrity_audit.md` | DB table `backtest_features_last5_roster` | `honest_blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned`; expanding walk-forward; first real season training-only; fold-selected calibrator | `data\processed\execution_plan\honest_real_only_no_market\predictions.csv` | excluded (`is_synthetic=0`) | excluded via `exclude_market_features=True` |

Validation rerun: `python scripts\honest_real_only_benchmark.py` reproduced 5,248 games at 56.8216% overall and 53.2012% for 2025-2026.

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
