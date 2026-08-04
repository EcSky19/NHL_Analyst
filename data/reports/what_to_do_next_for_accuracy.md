# What to do next for accuracy

## Current state
Best achieved accuracy is **0.597561** (Wave1). Recent waves are below this, with the largest misses concentrated in **0.50-0.60 confidence games**, **2025-26 season drift**, and **away/upset contexts**.

## Top 5 next actions (in order)
1. **Recency-weighted retraining + regime selector retune**  
   Aim: adapt to 2025-26 drift quickly.
2. **Fold-safe season-aware calibration (Platt vs isotonic)**  
   Aim: reduce overconfidence without hurting accuracy.
3. **OOS probability blend (`logistic_engineered` + `improved_roster_aware`)**  
   Aim: capture complementary errors and push past 0.599.
4. **Nonlinear variant on same folds (LightGBM/XGBoost)**  
   Aim: recover interaction signal missing in linear logistic.
5. **Confirmed starting-goalie fidelity + goalie quality differential**  
   Aim: close highest-impact feature-fidelity gap.

## What to run first now vs after
**Run now (fastest/highest EV):** actions **1-3** in sequence.  
**Run after (if still below target):** action **4**, then **5**.

## Numeric success gates
- **Immediate gate (action 1):** overall accuracy **>= 0.5985**, 2025-26 accuracy **>= 0.5710**, log loss not worse than **+0.003**.
- **Blend gate (action 3):** overall accuracy **>= 0.5990** and no season drop **> 0.003** vs best single model.
- **Nonlinear gate (action 4):** overall accuracy **>= 0.6000**, log loss **<= 0.648**, 2025-26 accuracy **>= 0.570**.
- **Goalie fidelity gate (action 5):** goalie coverage **>= 98%** on scored rows and overall lift **>= +0.003**.
- **Final promotion gate:** overall accuracy **> 0.597561** (target **>= 0.600**), 2025-26 accuracy **>= 0.571**, and log loss improvement **>= 0.005** vs current selected run.
