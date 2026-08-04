# Advanced temporal roster feature update

## Added leakage-safe pregame temporal features
- Goalie trend/workload: save% windows, shots-against trend, recent starter workload, days since last start.
- Skater depth production: top-9 scoring signal, depth scoring share, and special-teams contributor share.
- Availability continuity proxies: key-contributor continuity and lineup/key-contributor change rates.
- Multi-window rolling windows (last 3/5/10) for skater scoring and two-way form.
- Exponentially weighted recency (EWM) for skaters, two-way index, and goalie save%.
- Team recent-form volatility (variance) and opponent-strength-adjusted form trends.
- Roster stability and continuity: lineup continuity, recent stability, turnover, and core retention.

## Leakage guardrail
- Every feature is computed strictly from each team/player history prior to the current game.
- Current-game stats are only applied to history after feature rows are emitted.

## Coverage diagnostics (new columns)
| column | non_null_count | total_rows | coverage_pct |
|---|---:|---:|---:|
| `home_pregame_skater_points_pg_last3` | 6541 | 6560 | 99.71% |
| `away_pregame_skater_points_pg_last3` | 6547 | 6560 | 99.80% |
| `home_pregame_skater_points_pg_last10` | 6541 | 6560 | 99.71% |
| `away_pregame_skater_points_pg_last10` | 6547 | 6560 | 99.80% |
| `home_pregame_skater_two_way_idx_last3` | 6541 | 6560 | 99.71% |
| `away_pregame_skater_two_way_idx_last3` | 6547 | 6560 | 99.80% |
| `home_pregame_skater_two_way_idx_last10` | 6541 | 6560 | 99.71% |
| `away_pregame_skater_two_way_idx_last10` | 6547 | 6560 | 99.80% |
| `home_pregame_skater_points_pg_ewm` | 6541 | 6560 | 99.71% |
| `away_pregame_skater_points_pg_ewm` | 6547 | 6560 | 99.80% |
| `home_pregame_skater_two_way_idx_ewm` | 6541 | 6560 | 99.71% |
| `away_pregame_skater_two_way_idx_ewm` | 6547 | 6560 | 99.80% |
| `home_pregame_goalie_save_pct_last10` | 6502 | 6560 | 99.12% |
| `away_pregame_goalie_save_pct_last10` | 6485 | 6560 | 98.86% |
| `home_pregame_goalie_save_pct_ewm` | 6502 | 6560 | 99.12% |
| `away_pregame_goalie_save_pct_ewm` | 6485 | 6560 | 98.86% |
| `home_pregame_goalie_save_pct_last3` | 6502 | 6560 | 99.12% |
| `away_pregame_goalie_save_pct_last3` | 6485 | 6560 | 98.86% |
| `home_pregame_goalie_shots_against_pg_last5` | 6502 | 6560 | 99.12% |
| `away_pregame_goalie_shots_against_pg_last5` | 6485 | 6560 | 98.86% |
| `home_pregame_goalie_shots_against_pg_trend` | 6502 | 6560 | 99.12% |
| `away_pregame_goalie_shots_against_pg_trend` | 6485 | 6560 | 98.86% |
| `home_pregame_goalie_recent_starts_last5` | 6534 | 6560 | 99.60% |
| `away_pregame_goalie_recent_starts_last5` | 6538 | 6560 | 99.66% |
| `home_pregame_goalie_days_since_last_start` | 6495 | 6560 | 99.01% |
| `away_pregame_goalie_days_since_last_start` | 6469 | 6560 | 98.61% |
| `home_pregame_recent_form_adj_last5` | 6530 | 6560 | 99.54% |
| `away_pregame_recent_form_adj_last5` | 6527 | 6560 | 99.50% |
| `home_pregame_recent_form_adj_last10` | 6530 | 6560 | 99.54% |
| `away_pregame_recent_form_adj_last10` | 6527 | 6560 | 99.50% |
| `home_pregame_recent_form_volatility_last5` | 6541 | 6560 | 99.71% |
| `away_pregame_recent_form_volatility_last5` | 6547 | 6560 | 99.80% |
| `home_pregame_recent_form_volatility_last10` | 6541 | 6560 | 99.71% |
| `away_pregame_recent_form_volatility_last10` | 6547 | 6560 | 99.80% |
| `home_pregame_lineup_continuity_pct` | 6541 | 6560 | 99.71% |
| `away_pregame_lineup_continuity_pct` | 6547 | 6560 | 99.80% |
| `home_pregame_lineup_continuity_ewm` | 6527 | 6560 | 99.50% |
| `away_pregame_lineup_continuity_ewm` | 6529 | 6560 | 99.53% |
| `home_pregame_lineup_stability_last5` | 6527 | 6560 | 99.50% |
| `away_pregame_lineup_stability_last5` | 6529 | 6560 | 99.53% |
| `home_pregame_key_contributor_continuity_pct` | 6541 | 6560 | 99.71% |
| `away_pregame_key_contributor_continuity_pct` | 6547 | 6560 | 99.80% |
| `home_pregame_key_contributor_change_rate_last5` | 6527 | 6560 | 99.50% |
| `away_pregame_key_contributor_change_rate_last5` | 6529 | 6560 | 99.53% |
| `home_pregame_lineup_change_rate_last5` | 6527 | 6560 | 99.50% |
| `away_pregame_lineup_change_rate_last5` | 6529 | 6560 | 99.53% |
| `home_pregame_roster_turnover_count` | 6560 | 6560 | 100.00% |
| `away_pregame_roster_turnover_count` | 6560 | 6560 | 100.00% |
| `home_pregame_top9_points_pg` | 6541 | 6560 | 99.71% |
| `away_pregame_top9_points_pg` | 6547 | 6560 | 99.80% |
| `home_pregame_depth_points_share_last5` | 6541 | 6560 | 99.71% |
| `away_pregame_depth_points_share_last5` | 6547 | 6560 | 99.80% |
| `home_pregame_special_teams_contributor_share_last5` | 6560 | 6560 | 100.00% |
| `away_pregame_special_teams_contributor_share_last5` | 6560 | 6560 | 100.00% |
| `home_pregame_core_retention_pct` | 6541 | 6560 | 99.71% |
| `away_pregame_core_retention_pct` | 6547 | 6560 | 99.80% |
| `delta_pregame_goalie_shots_against_pg_trend_home_minus_away` | 6446 | 6560 | 98.26% |
| `delta_pregame_goalie_recent_starts_last5_home_minus_away` | 6521 | 6560 | 99.41% |
| `delta_pregame_goalie_days_since_last_start_home_minus_away` | 6424 | 6560 | 97.93% |
| `delta_pregame_top9_points_pg_home_minus_away` | 6537 | 6560 | 99.65% |
| `delta_pregame_depth_points_share_last5_home_minus_away` | 6537 | 6560 | 99.65% |
| `delta_pregame_special_teams_contributor_share_last5_home_minus_away` | 6560 | 6560 | 100.00% |
| `delta_pregame_key_contributor_continuity_pct_home_minus_away` | 6537 | 6560 | 99.65% |
| `delta_pregame_lineup_change_rate_last5_home_minus_away` | 6523 | 6560 | 99.44% |
| `delta_pregame_recent_form_adj_last5_home_minus_away` | 6523 | 6560 | 99.44% |
| `delta_pregame_recent_form_volatility_last5_home_minus_away` | 6537 | 6560 | 99.65% |
| `delta_pregame_lineup_continuity_pct_home_minus_away` | 6537 | 6560 | 99.65% |
| `delta_pregame_roster_turnover_count_home_minus_away` | 6560 | 6560 | 100.00% |
