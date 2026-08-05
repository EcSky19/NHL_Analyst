# NBA model results

Date: 2026-08-05T23:10:35.075525+00:00

## Headline

The frozen final-holdout evaluation is **62.52%** accuracy on **1,174** 2023 regular-season games, Wilson 95% CI **59.72%-65.25%**. Always-pick-home on the same holdout is **58.43%**; pure Elo is **62.95%**. The model margins are +4.09% vs always-home and -0.43% vs Elo, so differences should be read against the CI/noise floor.

## Data window and scope

- Source DB: `data\nba\nba_research.db`.
- Per-game modeling rows: completed, non-neutral NBA regular-season games, seasons **2002-2023**.
- The 2023-24, 2024-25, and 2025-26 `nba_current_*` tables are season-level aggregates only. They were **not** used for per-game training or testing.
- No fabricated, simulated, synthetic, market, betting, or postgame-derived feature rows are used.

## Pregame features

Elo, rest/back-to-back context, road-trip flags, season-to-date win percentage, rolling 3/5/10/20-game form, offensive/defensive rating, estimated pace, eFG%, 3P rate, rebounding rates, turnover rate, margin/points form, and recent opponent Elo strength. The DB stores 172 model columns; examples: elo_prob_home, elo_diff, rest_diff, home_b2b, away_b2b, away_road_trip, home_road_trip_flag, elo_pre_home, elo_pre_away, elo_pre_diff, opp_elo_pre_home, opp_elo_pre_away, opp_elo_pre_diff, season_win_pct_home, season_win_pct_away, season_win_pct_diff, rest_days_home, rest_days_away, rest_days_diff, is_back_to_back_home.

All rolling/expanding values are shifted by one game within team history. Season-to-date values use only games already played in that season. Elo ratings are recorded before updating with the current game.

## Frozen configuration and fold structure

Config was written to `data\nba\nba_model_config.json` before final holdout scoring. Stored serving artifact: `data\nba\nba_model_final.joblib`. Predictions are in DB table `nba_model_predictions`; metrics in `nba_model_metrics`.

```text
2007: train 2002-2005, calibrate 2006, test 2007 (development)
2008: train 2002-2006, calibrate 2007, test 2008 (development)
2009: train 2002-2007, calibrate 2008, test 2009 (development)
2010: train 2002-2008, calibrate 2009, test 2010 (development)
2011: train 2002-2009, calibrate 2010, test 2011 (development)
2012: train 2002-2010, calibrate 2011, test 2012 (development)
2013: train 2002-2011, calibrate 2012, test 2013 (development)
2014: train 2002-2012, calibrate 2013, test 2014 (development)
2015: train 2002-2013, calibrate 2014, test 2015 (development)
2016: train 2002-2014, calibrate 2015, test 2016 (development)
2017: train 2002-2015, calibrate 2016, test 2017 (development)
2018: train 2002-2016, calibrate 2017, test 2018 (development)
2019: train 2002-2017, calibrate 2018, test 2019 (development)
2020: train 2002-2018, calibrate 2019, test 2020 (development)
2021: train 2002-2019, calibrate 2020, test 2021 (development)
2022: train 2002-2020, calibrate 2021, test 2022 (development)
2023: train 2002-2021, calibrate 2022, test 2023 (final_holdout)
```

## Baselines and final holdout

| Model/baseline | Games | Accuracy | Wilson 95% CI | Log loss | Brier |
|---|---:|---:|---:|---:|---:|
| always_home | 1,174 | 58.43% | 55.59%-61.22% | 0.6789 | 0.2429 |
| pure_elo | 1,174 | 62.95% | 60.15%-65.66% | 0.6499 | 0.2280 |
| nba_model | 1,174 | 62.52% | 59.72%-65.25% | 0.6487 | 0.2285 |

## Per-season walk-forward model results

| Season/scope | Games | Accuracy | Wilson 95% CI | Log loss | Brier |
|---|---:|---:|---:|---:|---:|
| 2007 | 1,230 | 63.09% | 60.36%-65.74% | 0.6419 | 0.2252 |
| 2008 | 1,230 | 68.05% | 65.39%-70.59% | 0.6019 | 0.2072 |
| 2009 | 1,230 | 68.37% | 65.72%-70.91% | 0.5956 | 0.2047 |
| 2010 | 1,230 | 68.78% | 66.14%-71.31% | 0.5979 | 0.2057 |
| 2011 | 1,230 | 68.86% | 66.22%-71.39% | 0.5921 | 0.2031 |
| 2012 | 990 | 66.26% | 63.26%-69.14% | 0.6114 | 0.2116 |
| 2013 | 1,228 | 67.35% | 64.67%-69.91% | 0.6010 | 0.2070 |
| 2014 | 1,229 | 65.74% | 63.05%-68.34% | 0.6112 | 0.2120 |
| 2015 | 1,228 | 67.83% | 65.17%-70.39% | 0.5998 | 0.2066 |
| 2016 | 1,228 | 67.67% | 65.00%-70.23% | 0.5949 | 0.2046 |
| 2017 | 1,227 | 64.47% | 61.75%-67.10% | 0.6237 | 0.2175 |
| 2018 | 1,227 | 65.36% | 62.66%-67.97% | 0.6224 | 0.2164 |
| 2019 | 1,227 | 65.85% | 63.15%-68.45% | 0.6122 | 0.2120 |
| 2020 | 1,056 | 65.06% | 62.13%-67.87% | 0.6375 | 0.2233 |
| 2021 | 1,080 | 62.59% | 59.67%-65.43% | 0.6454 | 0.2272 |
| 2022 | 1,230 | 65.04% | 62.33%-67.65% | 0.6346 | 0.2217 |
| 2023 | 1,174 | 62.52% | 59.72%-65.25% | 0.6487 | 0.2285 |

## Overall scopes

| Season/scope | Games | Accuracy | Wilson 95% CI | Log loss | Brier |
|---|---:|---:|---:|---:|---:|
| all_walk_forward | 20,274 | 66.09% | 65.44%-66.74% | 0.6156 | 0.2136 |
| development_overall | 19,100 | 66.31% | 65.64%-66.98% | 0.6135 | 0.2127 |
| final_holdout_overall | 1,174 | 62.52% | 59.72%-65.25% | 0.6487 | 0.2285 |

## Calibration reliability table: final holdout

Bucket-weighted absolute calibration error is **5.75%** on the final holdout.

| Predicted bucket | Games | Avg predicted home win | Actual home win |
|---|---:|---:|---:|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 0 | n/a | n/a |
| 0.2-0.3 | 49 | 27.00% | 30.61% |
| 0.3-0.4 | 169 | 35.74% | 39.05% |
| 0.4-0.5 | 288 | 45.28% | 51.39% |
| 0.5-0.6 | 304 | 54.64% | 63.82% |
| 0.6-0.7 | 206 | 64.65% | 67.96% |
| 0.7-0.8 | 131 | 74.37% | 78.63% |
| 0.8-0.9 | 27 | 82.21% | 74.07% |
| 0.9-1.0 | 0 | n/a | n/a |

Calibration is Platt scaling fitted only on the immediately prior season for each fold. Buckets with fewer than 150 games are shown for transparency but should not be used as confidence tiers.

## Leakage checks

- Fold boundaries above show every test season trains on earlier seasons only and calibrates on the immediately prior season.
- A high-capacity margin reconstruction check trained before the final holdout and predicted the held-out final margin with R² **0.1021**, MAE **10.07** points, and only **6.47%** within one point.
- The maximum absolute single-feature correlation with final margin was **0.3785**. This is not consistent with a leaked final-score identity.

## Limitations

- There is no real betting-market baseline in this NBA database; comparisons are always-home and pure Elo only.
- Per-game NBA modeling data currently stops at the 2023 season; current-season aggregate tables cannot support per-game training.
- The model was not tuned across dozens of variants on the holdout. This is intentionally conservative, but not proof of an optimal NBA ceiling.
- Reported confidence tiers are avoided because most calibration buckets contain fewer than 150 games.
- Accuracy margins over baselines are small relative to Wilson intervals; treat them as noisy estimates, not betting advice.
