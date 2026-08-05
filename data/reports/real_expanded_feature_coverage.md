# Advanced temporal roster feature update

## Added leakage-safe pregame temporal features
- Goalie trend/workload: save% windows, shots-against trend, recent starter workload, days since last start.
- Starter-goalie fidelity: deterministic starter certainty plus starter-vs-backup quality gap (last5/last10 save%).
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
| `home_pregame_skater_points_pg_last3` | 10274 | 12644 | 81.26% |
| `away_pregame_skater_points_pg_last3` | 10278 | 12644 | 81.29% |
| `home_pregame_skater_points_pg_last10` | 10274 | 12644 | 81.26% |
| `away_pregame_skater_points_pg_last10` | 10278 | 12644 | 81.29% |
| `home_pregame_skater_two_way_idx_last3` | 10274 | 12644 | 81.26% |
| `away_pregame_skater_two_way_idx_last3` | 10278 | 12644 | 81.29% |
| `home_pregame_skater_two_way_idx_last10` | 10274 | 12644 | 81.26% |
| `away_pregame_skater_two_way_idx_last10` | 10278 | 12644 | 81.29% |
| `home_pregame_skater_points_pg_ewm` | 10274 | 12644 | 81.26% |
| `away_pregame_skater_points_pg_ewm` | 10278 | 12644 | 81.29% |
| `home_pregame_skater_two_way_idx_ewm` | 10274 | 12644 | 81.26% |
| `away_pregame_skater_two_way_idx_ewm` | 10278 | 12644 | 81.29% |
| `home_pregame_goalie_save_pct_last10` | 10291 | 12644 | 81.39% |
| `away_pregame_goalie_save_pct_last10` | 10291 | 12644 | 81.39% |
| `home_pregame_goalie_save_pct_ewm` | 10291 | 12644 | 81.39% |
| `away_pregame_goalie_save_pct_ewm` | 10291 | 12644 | 81.39% |
| `home_pregame_goalie_save_pct_last3` | 10291 | 12644 | 81.39% |
| `away_pregame_goalie_save_pct_last3` | 10291 | 12644 | 81.39% |
| `home_pregame_goalie_shots_against_pg_last5` | 10227 | 12644 | 80.88% |
| `away_pregame_goalie_shots_against_pg_last5` | 10197 | 12644 | 80.65% |
| `home_pregame_goalie_shots_against_pg_trend` | 10227 | 12644 | 80.88% |
| `away_pregame_goalie_shots_against_pg_trend` | 10197 | 12644 | 80.65% |
| `home_pregame_goalie_recent_starts_last5` | 10261 | 12644 | 81.15% |
| `away_pregame_goalie_recent_starts_last5` | 10267 | 12644 | 81.20% |
| `home_pregame_goalie_days_since_last_start` | 10212 | 12644 | 80.77% |
| `away_pregame_goalie_days_since_last_start` | 10163 | 12644 | 80.38% |
| `home_pregame_recent_form_adj_last5` | 10260 | 12644 | 81.15% |
| `away_pregame_recent_form_adj_last5` | 10258 | 12644 | 81.13% |
| `home_pregame_recent_form_adj_last10` | 10260 | 12644 | 81.15% |
| `away_pregame_recent_form_adj_last10` | 10258 | 12644 | 81.13% |
| `home_pregame_recent_form_volatility_last5` | 10274 | 12644 | 81.26% |
| `away_pregame_recent_form_volatility_last5` | 10276 | 12644 | 81.27% |
| `home_pregame_recent_form_volatility_last10` | 10274 | 12644 | 81.26% |
| `away_pregame_recent_form_volatility_last10` | 10276 | 12644 | 81.27% |
| `home_pregame_lineup_continuity_pct` | 10274 | 12644 | 81.26% |
| `away_pregame_lineup_continuity_pct` | 10276 | 12644 | 81.27% |
| `home_pregame_lineup_continuity_ewm` | 10262 | 12644 | 81.16% |
| `away_pregame_lineup_continuity_ewm` | 10256 | 12644 | 81.11% |
| `home_pregame_lineup_stability_last5` | 10262 | 12644 | 81.16% |
| `away_pregame_lineup_stability_last5` | 10256 | 12644 | 81.11% |
| `home_pregame_key_contributor_continuity_pct` | 10274 | 12644 | 81.26% |
| `away_pregame_key_contributor_continuity_pct` | 10276 | 12644 | 81.27% |
| `home_pregame_key_contributor_change_rate_last5` | 10262 | 12644 | 81.16% |
| `away_pregame_key_contributor_change_rate_last5` | 10256 | 12644 | 81.11% |
| `home_pregame_lineup_change_rate_last5` | 10262 | 12644 | 81.16% |
| `away_pregame_lineup_change_rate_last5` | 10256 | 12644 | 81.11% |
| `home_pregame_roster_turnover_count` | 12644 | 12644 | 100.00% |
| `away_pregame_roster_turnover_count` | 12644 | 12644 | 100.00% |
| `home_pregame_top9_points_pg` | 10274 | 12644 | 81.26% |
| `away_pregame_top9_points_pg` | 10278 | 12644 | 81.29% |
| `home_pregame_depth_points_share_last5` | 10273 | 12644 | 81.25% |
| `away_pregame_depth_points_share_last5` | 10277 | 12644 | 81.28% |
| `home_pregame_special_teams_contributor_share_last5` | 10291 | 12644 | 81.39% |
| `away_pregame_special_teams_contributor_share_last5` | 10291 | 12644 | 81.39% |
| `home_pregame_core_retention_pct` | 10274 | 12644 | 81.26% |
| `away_pregame_core_retention_pct` | 10276 | 12644 | 81.27% |
| `delta_pregame_goalie_shots_against_pg_trend_home_minus_away` | 10152 | 12644 | 80.29% |
| `delta_pregame_goalie_recent_starts_last5_home_minus_away` | 10248 | 12644 | 81.05% |
| `delta_pregame_goalie_days_since_last_start_home_minus_away` | 10104 | 12644 | 79.91% |
| `delta_pregame_top9_points_pg_home_minus_away` | 10272 | 12644 | 81.24% |
| `delta_pregame_depth_points_share_last5_home_minus_away` | 10270 | 12644 | 81.22% |
| `delta_pregame_special_teams_contributor_share_last5_home_minus_away` | 10291 | 12644 | 81.39% |
| `delta_pregame_key_contributor_continuity_pct_home_minus_away` | 10270 | 12644 | 81.22% |
| `delta_pregame_lineup_change_rate_last5_home_minus_away` | 10254 | 12644 | 81.10% |
| `delta_pregame_recent_form_adj_last5_home_minus_away` | 10252 | 12644 | 81.08% |
| `delta_pregame_recent_form_volatility_last5_home_minus_away` | 10270 | 12644 | 81.22% |
| `delta_pregame_lineup_continuity_pct_home_minus_away` | 10270 | 12644 | 81.22% |
| `delta_pregame_roster_turnover_count_home_minus_away` | 12644 | 12644 | 100.00% |
| `home_pregame_goalie_starter_certainty` | 12644 | 12644 | 100.00% |
| `away_pregame_goalie_starter_certainty` | 12644 | 12644 | 100.00% |
| `home_pregame_goalie_starter_quality_gap_last5` | 12644 | 12644 | 100.00% |
| `away_pregame_goalie_starter_quality_gap_last5` | 12644 | 12644 | 100.00% |
| `home_pregame_goalie_starter_quality_gap_last10` | 12644 | 12644 | 100.00% |
| `away_pregame_goalie_starter_quality_gap_last10` | 12644 | 12644 | 100.00% |
| `delta_pregame_goalie_starter_certainty_home_minus_away` | 12644 | 12644 | 100.00% |
| `delta_pregame_goalie_starter_quality_gap_last5_home_minus_away` | 12644 | 12644 | 100.00% |
| `delta_pregame_goalie_starter_quality_gap_last10_home_minus_away` | 12644 | 12644 | 100.00% |
