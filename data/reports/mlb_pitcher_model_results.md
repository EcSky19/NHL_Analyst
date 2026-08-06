# MLB starting-pitcher win-probability model results

## Headline

The frozen starting-pitcher model scored 55.84% (Wilson 95% CI 53.86%-57.81%) on the 2025 holdout; it beat the existing model (55.72%, approximate Wilson 95% CI 53.74%-57.68%) and did not beat Elo (56.13%, Wilson 95% CI 54.15%-58.09%). Both margins are inside the roughly two-point Wilson noise floor.

Starter coverage on the 2025 holdout was 2425 of 2430 games (99.79%); both starters had prior regular-season pitching stats before the game in 2388 games (98.27%).

## Frozen protocol

- Train: [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022]
- Validation/config selection: 2023
- Platt calibration: 2024
- Frozen holdout: 2025
- Excluded: [2026]
- Frozen config: `data\mlb\mlb_pitcher_model_frozen_config.json`
- Holdout scoring began only after the config JSON was written.
- Existing model comparison point: 55.72% accuracy, log loss 0.6804, Brier 0.2438.
- Elo comparison point: 56.13% accuracy, log loss 0.6875, Brier 0.2471.

Validation accuracy available before freezing was 55.93%; validation log loss was 0.6798 and Brier was 0.2435.

## Holdout metrics

| model_name | n_games | correct | accuracy | wilson95_low | wilson95_high | log_loss | brier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pitcher_logistic_platt | 2430 | 1357 | 0.5584 | 0.5386 | 0.5781 | 0.6795 | 0.2434 |
| always_home | 2430 | 1319 | 0.5428 | 0.5229 | 0.5625 | 0.6896 | 0.2482 |
| elo_baseline | 2430 | 1364 | 0.5613 | 0.5415 | 0.5809 | 0.6875 | 0.2471 |

## Pitcher-data coverage

| split | games | both_starters | both_starters_rate | both_starters_with_prior_stats | prior_stats_rate |
| --- | --- | --- | --- | --- | --- |
| 2025 holdout | 2430 | 2425 | 0.9979 | 2388 | 0.9827 |

The source for assignments is StatsAPI `schedule` with `hydrate=probablePitcher`. Pitching stat features come from StatsAPI `people` game logs and are shifted by construction: a pitcher's pregame feature row is captured before that game's pitching line is added to the cumulative state.

## Pregame-safe pitcher features

- `sp_starts_pre_diff`: home starter minus away starter pitching starts before this game only.
- `sp_ip_pre_diff`: home starter minus away starter career regular-season innings in the local database before this game only.
- `sp_era_pre_diff`: home starter minus away starter earned-run average before this game only; current-game and future earned runs are excluded.
- `sp_whip_pre_diff`: home starter minus away starter WHIP before this game only.
- `sp_k9_pre_diff`: home starter minus away starter strikeouts per 9 innings before this game only.
- `sp_bb9_pre_diff`: home starter minus away starter walks per 9 innings before this game only.
- `sp_hr9_pre_diff`: home starter minus away starter home runs per 9 innings before this game only.
- `sp_recent3_ip_pre_diff`: home starter minus away starter innings across the pitcher's three prior starts only.
- `sp_recent3_era_pre_diff`: home starter minus away starter ERA across the pitcher's three prior starts only.
- `sp_recent3_whip_pre_diff`: home starter minus away starter WHIP across the pitcher's three prior starts only.
- `sp_recent3_k9_pre_diff`: home starter minus away starter K/9 across the pitcher's three prior starts only.
- `home_sp_known`: indicator that StatsAPI supplied a home starter assignment for this game.
- `away_sp_known`: indicator that StatsAPI supplied an away starter assignment for this game.
- `home_sp_no_prior`: indicator that the listed home starter had no prior regular-season pitching stats in this database before this game.
- `away_sp_no_prior`: indicator that the listed away starter had no prior regular-season pitching stats in this database before this game.
- `home_sp_starts_pre`: home starter prior regular-season starts before this game only.
- `away_sp_starts_pre`: away starter prior regular-season starts before this game only.

For rookies or pitchers with no previous MLB regular-season pitching line in this database, ratio features are missing, the training-fold median imputer supplies the numeric fallback, and explicit no-prior indicators tell the model that the fallback was used.

## Calibration reliability table

| bucket | count | mean_predicted_home_win_prob | actual_home_win_rate | usable_for_confidence_claims |
| --- | --- | --- | --- | --- |
| 0.0-0.1 | 0 |  |  | False |
| 0.1-0.2 | 0 |  |  | False |
| 0.2-0.3 | 9 | 0.2851 | 0.1111 | False |
| 0.3-0.4 | 144 | 0.3625 | 0.4375 | False |
| 0.4-0.5 | 767 | 0.4595 | 0.4915 | True |
| 0.5-0.6 | 1116 | 0.5457 | 0.5556 | True |
| 0.6-0.7 | 360 | 0.6360 | 0.6389 | True |
| 0.7-0.8 | 34 | 0.7192 | 0.8235 | False |
| 0.8-0.9 | 0 |  |  | False |
| 0.9-1.0 | 0 |  |  | False |

Holdout probability range was 0.2607-0.7865, which remains in a realistic baseball range.

## Leakage self-checks

- Linear regression of final home run differential on the full pregame feature matrix: R-squared = 0.0346.
- Shuffling holdout labels against fixed predictions collapsed accuracy: mean shuffled accuracy = 50.89%, 2.5%-97.5% range = 49.26%-52.88% across 200 shuffles.

## Verdict

Starting-pitcher features improved raw accuracy versus the existing model and did not beat Elo. Because the observed margins are small relative to the holdout uncertainty, this should be read as an honest direct-comparison result rather than a claim of a durable betting edge.
