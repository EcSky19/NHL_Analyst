# Wave3 feature build validation

Generated: 2026-08-03 23:36:12 UTC

## Deterministic rerun command
```powershell
Set-Location 'C:\Users\t-ecoskay\Sports_analytics'
python scripts\build_last5_backtest_features_roster.py
```

## Build outputs
- CSV: `data\processed\backtest_features_last5_roster.csv` (present)
- SQLite: `data\processed\nhl_research.db` table `backtest_features_last5_roster` (present)
- Row count parity: CSV **6560** vs SQLite **6560** (match)

## Key wave3 columns presence
- Checked columns: **41** (game-context: 16, player-stats: 25)
- Missing in CSV: none
- Missing in SQLite table schema: none

## Non-null coverage (key wave3 columns)
| column | non_null | coverage_pct |
|---|---:|---:|
| `home_three_in_four` | 6560 | 100.00% |
| `away_three_in_four` | 6560 | 100.00% |
| `home_four_in_six` | 6560 | 100.00% |
| `away_four_in_six` | 6560 | 100.00% |
| `home_pregame_travel_miles` | 6472 | 98.66% |
| `away_pregame_travel_miles` | 6488 | 98.90% |
| `delta_travel_miles_home_minus_away` | 6459 | 98.46% |
| `home_timezone_shift_hours` | 6472 | 98.66% |
| `away_timezone_shift_hours` | 6488 | 98.90% |
| `delta_timezone_shift_hours_home_minus_away` | 6459 | 98.46% |
| `home_pregame_home_stand_len` | 6560 | 100.00% |
| `away_pregame_home_stand_len` | 6560 | 100.00% |
| `home_pregame_road_trip_len` | 6560 | 100.00% |
| `away_pregame_road_trip_len` | 6560 | 100.00% |
| `delta_home_stand_len_home_minus_away` | 6560 | 100.00% |
| `delta_road_trip_len_home_minus_away` | 6560 | 100.00% |
| `home_pregame_skater_points_pg_last3` | 6541 | 99.71% |
| `away_pregame_skater_points_pg_last3` | 6547 | 99.80% |
| `home_pregame_skater_points_pg_last10` | 6541 | 99.71% |
| `away_pregame_skater_points_pg_last10` | 6547 | 99.80% |
| `home_pregame_skater_two_way_idx_ewm` | 6541 | 99.71% |
| `away_pregame_skater_two_way_idx_ewm` | 6547 | 99.80% |
| `home_pregame_goalie_save_pct_last10` | 6502 | 99.12% |
| `away_pregame_goalie_save_pct_last10` | 6485 | 98.86% |
| `home_pregame_goalie_shots_against_pg_trend` | 6502 | 99.12% |
| `away_pregame_goalie_shots_against_pg_trend` | 6485 | 98.86% |
| `home_pregame_goalie_days_since_last_start` | 6495 | 99.01% |
| `away_pregame_goalie_days_since_last_start` | 6469 | 98.61% |
| `home_pregame_top9_points_pg` | 6541 | 99.71% |
| `away_pregame_top9_points_pg` | 6547 | 99.80% |
| `home_pregame_depth_points_share_last5` | 6541 | 99.71% |
| `away_pregame_depth_points_share_last5` | 6547 | 99.80% |
| `home_pregame_special_teams_contributor_share_last5` | 6560 | 100.00% |
| `away_pregame_special_teams_contributor_share_last5` | 6560 | 100.00% |
| `home_pregame_lineup_continuity_pct` | 6541 | 99.71% |
| `away_pregame_lineup_continuity_pct` | 6547 | 99.80% |
| `home_pregame_roster_turnover_count` | 6560 | 100.00% |
| `away_pregame_roster_turnover_count` | 6560 | 100.00% |
| `delta_pregame_goalie_days_since_last_start_home_minus_away` | 6424 | 97.93% |
| `delta_pregame_top9_points_pg_home_minus_away` | 6537 | 99.65% |
| `delta_pregame_lineup_continuity_pct_home_minus_away` | 6537 | 99.65% |

## Coverage caveats
Lowest-coverage key columns (still high):
- `delta_pregame_goalie_days_since_last_start_home_minus_away`: 6424/6560 (97.93%)
- `delta_travel_miles_home_minus_away`: 6459/6560 (98.46%)
- `delta_timezone_shift_hours_home_minus_away`: 6459/6560 (98.46%)
- `away_pregame_goalie_days_since_last_start`: 6469/6560 (98.61%)
- `home_pregame_travel_miles`: 6472/6560 (98.66%)
- Remaining nulls are expected for early-season warm-up/history gaps and goalie-history-dependent deltas.
- No leakage changes were introduced in this build step; features are produced by pregame-only scripts already updated in prior wave3 todos.
