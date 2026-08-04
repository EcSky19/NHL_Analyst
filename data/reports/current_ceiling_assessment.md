# Current Model Ceiling Assessment

## 1) Best-achieved accuracy and trend across waves

| Wave | Selected variant | Accuracy | Delta vs Wave1 SOTA |
|---|---|---:|---:|
| Wave1 | `hybrid_exponential + logistic_engineered` | **0.597561** | baseline SOTA |
| Wave2 | `single + blend_logistic_weighted_70_30` | 0.590447 | -0.007114 |
| Wave3 | `single + logistic_engineered` | 0.592226 | -0.005335 |

- **Best achieved accuracy remains Wave1: 0.597561 (59.76%)**.
- Trend after Wave1: **drop in Wave2, partial rebound in Wave3, still below Wave1**.
- This suggests the system is currently capped around the **~59.2%–59.8%** band on the current 3,936-game evaluation setup.

## 2) Dominant unsolved error slices

From current-best failure slicing (`improved_roster_aware`, 5,248 games, 59.72% accuracy):

1. **Season drift (2025-2026):** 56.17% accuracy, **43.83% error** (worst season).
2. **Coin-flip confidence zone dominates misses:**  
   - 0.50–0.55: 52.20% accuracy, **47.80% error**, 1,408 games (~673 misses)  
   - 0.55–0.60: 52.89% accuracy, **47.11% error**, 1,212 games (~571 misses)
3. **Away-pick weakness:** predicted away context has **42.44% error** vs 38.86% for predicted home.
4. **Team/opponent concentration failures:**  
   - Predicted ANA: **48.19% error**  
   - Picks against CAR: **57.65% error** (upset-prone context)
5. **Residual overconfidence/calibration gap:** even 0.70+ bucket still has **24.81% error**; 0.55–0.60 bucket is overconfident by ~4.5 pts.

## 3) Why recent feature expansions likely did not exceed Wave1 SOTA

1. **Regime drift remains stronger than added feature signal.**  
   Wave3 added broad context/roster families, but 2025-2026 still has materially elevated error, implying non-stationarity not fully captured by current recency/regime treatment.

2. **Accuracy bottleneck is concentrated in low-edge games.**  
   Largest miss pool is still the 0.50–0.60 range; adding many features may improve confidence shaping without creating enough true class separation in marginal matchups.

3. **Feature expansion may have diluted robust core signal.**  
   Wave1’s simpler winning setup (`hybrid_exponential + logistic_engineered`) outperformed Wave2/Wave3 despite fewer expansions, consistent with added features introducing noise/instability relative to the objective (accuracy).

4. **Objective mismatch/calibration side effects.**  
   Tie-breakers and richer models can improve probabilistic metrics in places, but not necessarily discrete accuracy; persistent overconfidence pockets and away/opponent-specific misses support this.

## 4) Top 3 leverage points

1. **Targeted low-edge decision policy (0.50–0.60 zone).**  
   Build a specialized second-stage model or abstention/re-ranking policy for low-margin games, since this zone contributes the largest absolute error volume.

2. **Explicit season-regime/drift adaptation for 2025-2026-like conditions.**  
   Use rolling/season-conditional refits, stronger drift detection, and regime-specific coefficients to prevent late-season degradation from dominating aggregate results.

3. **Context-specific residual modeling (away + upset-prone/team interactions).**  
   Add focused residual learners for away favorites and known upset-opponent/team clusters (e.g., against CAR, ANA picks), rather than broad feature-family expansion.

---

### Bottom line
The current ceiling is **not a universal-model feature shortage**; it is primarily a **distribution-shift + low-edge classification + context-specific residual error** problem. The most leverage is in targeted error-slice strategies, not indiscriminate feature breadth.
