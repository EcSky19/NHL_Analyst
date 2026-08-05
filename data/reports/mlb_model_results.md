# MLB win-probability model results

## Headline

The frozen MLB model scored 55.72% (Wilson 95% CI 53.74%-57.68%) on the 2025 holdout; it did not beat Elo (56.13%) and beat always-pick-home (54.28%).

This is a walk-forward evaluation. The in-progress 2026 season was excluded from training, calibration, and holdout scoring.

## Frozen configuration and fold structure

- Train: [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022] (includes atypical shortened 2020)
- Validation/config selection: 2023
- Platt calibration: 2024
- Frozen holdout: 2025
- Excluded: [2026]
- Frozen config: `data\mlb\mlb_win_model_frozen_config.json`
- Serving artifact: `data\mlb\mlb_win_model.joblib`

The final configuration JSON was written before scoring the frozen 2025 holdout. Validation accuracy available before freezing was 56.13%.

## Holdout metrics

| model_name | n_games | correct | accuracy | wilson95_low | wilson95_high | log_loss | brier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| logistic_platt | 2430 | 1354 | 0.5572 | 0.5374 | 0.5768 | 0.6804 | 0.2438 |
| always_home | 2430 | 1319 | 0.5428 | 0.5229 | 0.5625 | 0.6896 | 0.2482 |
| elo_baseline | 2430 | 1364 | 0.5613 | 0.5415 | 0.5809 | 0.6875 | 0.2471 |

The model beats always-pick-home and does not beat the Elo baseline on raw accuracy. The Wilson intervals overlap, so small margins should be treated as statistical noise rather than strong evidence.

## Pregame-safe feature list

Every rolling or season-to-date feature is shifted by construction: the script records features first, then updates team/Elo state with the current game's result.

- `pregame_win_pct_diff`: home minus away season-to-date win percentage before this game only; current game is excluded by updating state after feature capture.
- `pregame_run_diff_pg_diff`: home minus away season-to-date run differential per game before this game only; final runs from this game are not included.
- `pregame_runs_scored_pg_diff`: home minus away season-to-date runs scored per game before this game only.
- `pregame_runs_allowed_pg_diff`: home minus away season-to-date runs allowed per game before this game only.
- `last10_win_pct_diff`: home minus away rolling last-10 win percentage from completed prior games only.
- `rest_days_diff_capped`: home minus away days since each team's previous game, capped at 10; uses schedule dates before first pitch.
- `prior_season_win_pct_diff`: home minus away final win percentage from the previous season, known before opening day.
- `prior_season_run_diff_pg_diff`: home minus away previous-season run differential per game, known before opening day.
- `elo_rating_diff_with_home_adv`: pregame Elo rating difference plus fixed home advantage; Elo is updated only after each game is recorded.
- `home_games_played_pre`: home team's number of completed season games before this game.
- `away_games_played_pre`: away team's number of completed season games before this game.

No starting-pitcher feature was used because the verified schema inspected in `mlb_research.db` has no game-level starting-pitcher columns.

## Calibration reliability table

Buckets are based on calibrated holdout home-win probabilities. Per-bucket counts below 150 are not used for confidence-tier claims.

| bucket | count | mean_predicted_home_win_prob | actual_home_win_rate | usable_for_confidence_claims |
| --- | --- | --- | --- | --- |
| 0.0-0.1 | 0 |  |  | False |
| 0.1-0.2 | 0 |  |  | False |
| 0.2-0.3 | 1 | 0.2918 | 1.0000 | False |
| 0.3-0.4 | 110 | 0.3657 | 0.3273 | False |
| 0.4-0.5 | 784 | 0.4630 | 0.5013 | True |
| 0.5-0.6 | 1216 | 0.5434 | 0.5567 | True |
| 0.6-0.7 | 307 | 0.6340 | 0.6547 | True |
| 0.7-0.8 | 12 | 0.7091 | 0.9167 | False |
| 0.8-0.9 | 0 |  |  | False |
| 0.9-1.0 | 0 |  |  | False |

## Leakage self-checks

- Linear regression of final home run differential on the pregame feature matrix: R-squared = 0.0305. This is not implausibly high for baseball and does not suggest direct score leakage.
- Shuffling holdout labels against fixed predictions destroyed accuracy: mean shuffled accuracy = 51.01%, 2.5%-97.5% range = 49.22%-53.09% across 200 shuffles.

## Limitations

- Baseball game winners are intrinsically noisy; this model is intentionally modest and should not be interpreted as a betting edge.
- The database does not include pregame starting-pitcher assignments, the dominant public baseball signal.
- Team-only rolling stats are weaker early in each season and are affected by roster changes not represented in the database.
- 2020 is COVID-shortened and unusual, but it remains in the training window to avoid arbitrary deletion of verified historical games.
- 2026 is partial as of the source database and was excluded from honest evaluation.
