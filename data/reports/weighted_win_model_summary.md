# Weighted Win Model Fit Summary

- Model version: `weighted_win_model_v1`
- Teams scored: 32
- Matchup predictions generated: 7

## Method
- Deterministic weighted rating model with logistic transform.
- High-signal metrics use larger absolute weights: goal scoring/prevention rates, goalie save performance, special teams, shot share, recent form, and streak.
- Volatile or sparse metrics are down-weighted (e.g., faceoff %, turnover-like counts, top-scorer share, pressure-rate proxy).
- Missing values are imputed with league medians per feature, then robustly scaled (median + IQR-based scale), with z-scores clipped to reduce outlier instability.
- Team priors are blended via logit(points_pct) proxy and recent-form impact is coverage-aware to avoid overreacting when context is sparse.
- Home/away effect is explicit: base home-ice logit bonus plus home-vs-road points and goal-differential edge terms.

## Stability and confidence notes
- Pearson correlation between blended team strengths and points priors: 0.896
- Mean predicted home win probability (scheduled games): 0.564
- Mean confidence distance from 50/50: 0.298
- No direct historical game-result labels are currently used in this fit, so calibration confidence is limited and probabilities should be treated as directional likelihoods.

## Top 5 team strengths
- Colorado Avalanche (COL): 5.437
- Dallas Stars (DAL): 4.407
- Tampa Bay Lightning (TBL): 3.181
- Buffalo Sabres (BUF): 2.816
- Minnesota Wild (MIN): 2.164

## Bottom 5 team strengths
- Anaheim Ducks (ANA): -2.772
- San Jose Sharks (SJS): -2.907
- Toronto Maple Leafs (TOR): -3.293
- Chicago Blackhawks (CHI): -3.312
- Vancouver Canucks (VAN): -5.963

## Artifacts
- `scripts\train_weighted_win_model.py`
- `data\processed\weighted_win_model_config.json`
- `data\processed\weighted_win_predictions.csv`
- SQLite table `weighted_win_predictions` in `data\processed\nhl_research.db`
