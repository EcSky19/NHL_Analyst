# Weighted Win Prediction Guide

- Model version: `weighted_win_model_v1`
- Purpose: estimate home-vs-away win likelihood using weighted team quality, recent trend/streak context, and location edge.

## Final weighting scheme and rationale
- Heavy features (high impact, stronger signal):
  - def_goals_against_per_game (-1.25)
  - def_save_pct_5v5 (+1.05)
  - l10_goal_diff_per_game (+0.90)
  - l10_points_pct (+1.05)
  - off_goals_per_game (+1.15)
  - player_goalie_save_pct_weighted (+0.95)
  - st_special_teams_index (+0.90)
- Light features (kept but intentionally down-weighted due to volatility/sparsity):
  - player_top_scorer_points_share (-0.15)
  - pressure_avg_shots_needed_per_goal (-0.35)
  - puck_faceoff_win_pct (+0.25)
  - puck_giveaways (-0.20)
  - puck_takeaways (+0.20)
- Rationale: scoring/defense/save%, special teams, and short-horizon form carry more stable predictive value than noisier puck-battle or concentrated-player share proxies.

## Streak and location application
- Streak is a signed recent-form feature (`streak_signed`) in the recent component; optional CLI adjustments add directly to each team's streak before scoring.
- Location adjustment uses: base_home_ice=0.18, points_edge_weight=0.65, goal_diff_edge_weight=0.35.
- Location override options:
  - `home`: listed home team keeps home-ice context (default)
  - `away`: listed home team treated as away (away team gets home-like edge)
  - `neutral`: removes location edge terms

## Example predictions
- baseline_01: STL vs DAL (home), home=0.152, away=0.848, confidence=0.697 (high)
- baseline_02: TOR vs MTL (home), home=0.149, away=0.851, confidence=0.702 (high)
- baseline_03: MTL vs TOR (home), home=0.873, away=0.127, confidence=0.746 (high)
- baseline_04: MIN vs CHI (home), home=0.888, away=0.112, confidence=0.776 (high)
- baseline_05: EDM vs WPG (home), home=0.702, away=0.298, confidence=0.403 (medium)
- streak_demo_plus2_minus2: STL vs DAL (home), home=0.161, away=0.839, confidence=0.677 (high)

## Confidence interpretation and limitations
- Confidence index is distance from 50/50; it is directional certainty, not guaranteed calibration.
- Use low-confidence outputs as coin-flip tiers; treat medium/high as stronger lean, not certainty.
- Model is deterministic and feature-based; it does not ingest game-day injuries/line changes unless upstream features are refreshed.
- Best practice: re-run upstream feature and training scripts before production use when new data arrives.

## Reproducibility
- Rebuild these artifacts with:
  - `python scripts\weighted_win_predictor.py --build-artifacts`

## Artifact outputs
- `scripts\weighted_win_predictor.py`
- `data\processed\matchup_predictions_examples.csv`
- SQLite table `matchup_predictions_examples` in `data\processed\nhl_research.db`
- `data\reports\weighted_win_prediction_guide.md`
