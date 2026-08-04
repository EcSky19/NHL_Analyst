# Wave3 Results

## Selected winner and settings
- **Winner:** `logistic_engineered` (recency candidate `single`)
- **Selection rule:** highest accuracy on full-coverage variants (3936 games), then lower log loss, then lower Brier
- **Key settings:** `season_regime` selector, `hybrid_exponential` recency, season half-life **0.85**, game half-life **552.5**, min weight **0.09**

## Overall metrics (n=3936)
- **Accuracy:** **0.592226**
- **Log loss:** **0.661336**
- **Brier score:** **0.234841**

## Accuracy deltas
- vs baseline (**0.578811**): **+0.013415**
- vs previous best roster-aware (**0.597180**): **-0.004954**
- vs wave1 SOTA (**0.597561**): **-0.005335**

## New stats added (summary)
- **Game-context families:** schedule/rest stress (3-in-4, 4-in-6), travel/venue load (miles, timezone shift), home-stand/road-trip streak context.
- **Player/roster families:** goalie workload/form trends, skater scoring/two-way recency windows, depth/special-teams contribution, lineup continuity/stability, roster turnover, opponent-adjusted recent form, plus home-away delta features.

## Conclusion
Wave3 improved substantially vs the legacy baseline, but **did not improve SOTA**: selected accuracy (**0.592226**) remains below both prior roster-aware best (**0.597180**) and wave1 SOTA (**0.597561**).
