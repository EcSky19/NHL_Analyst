# Accuracy Error Slice Analysis (Current Best Model)

**Model selection check:** improved_roster_aware accuracy = 59.72% (5248 games) vs logistic_engineered = 59.50% (3936 games).
Using **improved_roster_aware** as the current best model for failure slicing.

**Overall error rate:** 40.28% (accuracy 59.72%) across 5248 games.

## 1) Required Error Slices

### By season

| Season | Games | Accuracy | Error rate |
|---|---:|---:|---:|
| 20222023 | 1312 | 60.29% | 39.71% |
| 20232024 | 1312 | 61.74% | 38.26% |
| 20242025 | 1312 | 60.67% | 39.33% |
| 20252026 | 1312 | 56.17% | 43.83% |

### By confidence bucket (max(home/away probability))

| Confidence bucket | Games | Accuracy | Error rate |
|---|---:|---:|---:|
| 0.50-0.55 | 1408 | 52.20% | 47.80% |
| 0.55-0.60 | 1212 | 52.89% | 47.11% |
| 0.60-0.65 | 959 | 60.48% | 39.52% |
| 0.65-0.70 | 641 | 63.18% | 36.82% |
| 0.70+ | 1028 | 75.19% | 24.81% |

### By home/away prediction context

| Context | Games | Accuracy | Error rate |
|---|---:|---:|---:|
| Predicted Home | 3170 | 61.14% | 38.86% |
| Predicted Away | 2078 | 57.56% | 42.44% |

### Team/opponent groupings (min 60 picks)

Worst predicted-team error rates:

| Predicted team | Games | Accuracy | Error rate |
|---|---:|---:|---:|
| ANA | 83 | 51.81% | 48.19% |
| NYI | 175 | 52.00% | 48.00% |
| CBJ | 80 | 52.50% | 47.50% |
| VAN | 161 | 53.42% | 46.58% |
| CGY | 149 | 53.69% | 46.31% |
| OTT | 145 | 55.17% | 44.83% |
| STL | 132 | 56.06% | 43.94% |
| BUF | 147 | 56.46% | 43.54% |

Worst opponent contexts when model picks against them (i.e., opponent frequently upsets pick):

| Opponent team | Games | Accuracy of pick | Error rate |
|---|---:|---:|---:|
| CAR | 85 | 42.35% | 57.65% |
| FLA | 121 | 48.76% | 51.24% |
| VGK | 91 | 51.65% | 48.35% |
| BOS | 123 | 52.03% | 47.97% |
| TBL | 88 | 53.41% | 46.59% |
| OTT | 183 | 53.55% | 46.45% |
| BUF | 181 | 53.59% | 46.41% |
| TOR | 119 | 53.78% | 46.22% |

## 2) Top recurring failure patterns

- 1. **Season drift risk:** 20252026 has the worst error rate at 43.83% (1312 games), versus best season error 38.26%.
- 2. **Coin-flip zone is largest miss pool:** bucket 0.50-0.55 has 1408 games with 47.80% error (673 misses).
- 3. **Overconfidence at high probabilities:** bucket 0.70+ still misses 24.81% (255/1028 games).
- 4. **High-confidence away picks are weaker than high-confidence home picks:** away error 30.56% vs home error 28.82% for confidence >=0.65.
- 5. **Team-specific miss concentration:** when picking ANA, error is 48.19% across 83 picks.
- 6. **Upset-prone opponent context:** picks against CAR fail 57.65% over 85 games.
- 7. **Calibration gap:** biggest confidence-accuracy gap in bucket 0.55-0.60 is 4.51% (mean confidence 57.39% vs actual accuracy 52.89%).
- 8. **Recurring matchup misses:** BUF vs MTL produced 8 misses in 8 games (error 100.00%).

## 3) At least 5 actionable diagnostics (quantified)

1. **Confidence-gated strategy:** 0.50-0.55 bucket accuracy is only 52.20%; treat these 1408 games as low-edge/no-bet or require additional features.
2. **Cap extreme confidence:** 0.70+ bucket error is 24.81%; apply calibration (Platt/isotonic) to reduce overconfident misses.
3. **Home/away asymmetry fix:** for confidence >=0.65, away-pick error is 30.56% vs 28.82% home; add away-travel/back-to-back fatigue features for away favorites.
4. **Season-regime adaptation:** worst season 20252026 error 43.83% indicates drift; retrain with stronger recency weighting and revalidate per season.
5. **Team-specific residual modeling:** ANA pick error is 48.19% over 83 games; add team interaction features or team-level random effects.
6. **Opponent upset profile:** picks against CAR miss 57.65% of the time (85 games); add opponent-clutch or matchup-style features for this group.

### Extra context from SQLite (`last5seasons_game_predictions`): rating-gap slice

| Pre-game rating gap bucket | Games | Mean confidence | Accuracy | Error rate |
|---|---:|---:|---:|---:|
| 0-20 | 754 | 51.43% | 48.94% | 51.06% |
| 20-40 | 753 | 54.32% | 51.26% | 48.74% |
| 40-60 | 709 | 57.15% | 56.28% | 43.72% |
| 60+ | 4344 | 69.81% | 60.84% | 39.16% |