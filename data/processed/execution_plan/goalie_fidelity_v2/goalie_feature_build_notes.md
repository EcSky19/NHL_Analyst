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
| `home_pregame_skater_points_pg_last3` | 7854 | 7966 | 98.59% |
| `away_pregame_skater_points_pg_last3` | 7872 | 7966 | 98.82% |
| `home_pregame_skater_points_pg_last10` | 7854 | 7966 | 98.59% |
| `away_pregame_skater_points_pg_last10` | 7872 | 7966 | 98.82% |
| `home_pregame_skater_two_way_idx_last3` | 7854 | 7966 | 98.59% |
| `away_pregame_skater_two_way_idx_last3` | 7872 | 7966 | 98.82% |
| `home_pregame_skater_two_way_idx_last10` | 7854 | 7966 | 98.59% |
| `away_pregame_skater_two_way_idx_last10` | 7872 | 7966 | 98.82% |
| `home_pregame_skater_points_pg_ewm` | 7854 | 7966 | 98.59% |
| `away_pregame_skater_points_pg_ewm` | 7872 | 7966 | 98.82% |
| `home_pregame_skater_two_way_idx_ewm` | 7854 | 7966 | 98.59% |
| `away_pregame_skater_two_way_idx_ewm` | 7872 | 7966 | 98.82% |
| `home_pregame_goalie_save_pct_last10` | 7863 | 7966 | 98.71% |
| `away_pregame_goalie_save_pct_last10` | 7846 | 7966 | 98.49% |
| `home_pregame_goalie_save_pct_ewm` | 7921 | 7966 | 99.44% |
| `away_pregame_goalie_save_pct_ewm` | 7924 | 7966 | 99.47% |
| `home_pregame_goalie_save_pct_last3` | 7921 | 7966 | 99.44% |
| `away_pregame_goalie_save_pct_last3` | 7924 | 7966 | 99.47% |
| `home_pregame_goalie_shots_against_pg_last5` | 7755 | 7966 | 97.35% |
| `away_pregame_goalie_shots_against_pg_last5` | 7732 | 7966 | 97.06% |
| `home_pregame_goalie_shots_against_pg_trend` | 7755 | 7966 | 97.35% |
| `away_pregame_goalie_shots_against_pg_trend` | 7732 | 7966 | 97.06% |
| `home_pregame_goalie_recent_starts_last5` | 7787 | 7966 | 97.75% |
| `away_pregame_goalie_recent_starts_last5` | 7785 | 7966 | 97.73% |
| `home_pregame_goalie_days_since_last_start` | 7748 | 7966 | 97.26% |
| `away_pregame_goalie_days_since_last_start` | 7716 | 7966 | 96.86% |
| `home_pregame_recent_form_adj_last5` | 0 | 7966 | 0.00% |
| `away_pregame_recent_form_adj_last5` | 0 | 7966 | 0.00% |
| `home_pregame_recent_form_adj_last10` | 0 | 7966 | 0.00% |
| `away_pregame_recent_form_adj_last10` | 0 | 7966 | 0.00% |
| `home_pregame_recent_form_volatility_last5` | 7904 | 7966 | 99.22% |
| `away_pregame_recent_form_volatility_last5` | 7910 | 7966 | 99.30% |
| `home_pregame_recent_form_volatility_last10` | 7904 | 7966 | 99.22% |
| `away_pregame_recent_form_volatility_last10` | 7910 | 7966 | 99.30% |
| `home_pregame_lineup_continuity_pct` | 7904 | 7966 | 99.22% |
| `away_pregame_lineup_continuity_pct` | 7910 | 7966 | 99.30% |
| `home_pregame_lineup_continuity_ewm` | 7891 | 7966 | 99.06% |
| `away_pregame_lineup_continuity_ewm` | 7892 | 7966 | 99.07% |
| `home_pregame_lineup_stability_last5` | 7891 | 7966 | 99.06% |
| `away_pregame_lineup_stability_last5` | 7892 | 7966 | 99.07% |
| `home_pregame_key_contributor_continuity_pct` | 7904 | 7966 | 99.22% |
| `away_pregame_key_contributor_continuity_pct` | 7910 | 7966 | 99.30% |
| `home_pregame_key_contributor_change_rate_last5` | 7891 | 7966 | 99.06% |
| `away_pregame_key_contributor_change_rate_last5` | 7892 | 7966 | 99.07% |
| `home_pregame_lineup_change_rate_last5` | 7891 | 7966 | 99.06% |
| `away_pregame_lineup_change_rate_last5` | 7892 | 7966 | 99.07% |
| `home_pregame_roster_turnover_count` | 7921 | 7966 | 99.44% |
| `away_pregame_roster_turnover_count` | 7924 | 7966 | 99.47% |
| `home_pregame_top9_points_pg` | 7854 | 7966 | 98.59% |
| `away_pregame_top9_points_pg` | 7872 | 7966 | 98.82% |
| `home_pregame_depth_points_share_last5` | 7854 | 7966 | 98.59% |
| `away_pregame_depth_points_share_last5` | 7871 | 7966 | 98.81% |
| `home_pregame_special_teams_contributor_share_last5` | 7921 | 7966 | 99.44% |
| `away_pregame_special_teams_contributor_share_last5` | 7924 | 7966 | 99.47% |
| `home_pregame_core_retention_pct` | 7904 | 7966 | 99.22% |
| `away_pregame_core_retention_pct` | 7910 | 7966 | 99.30% |
| `delta_pregame_goalie_shots_against_pg_trend_home_minus_away` | 7575 | 7966 | 95.09% |
| `delta_pregame_goalie_recent_starts_last5_home_minus_away` | 7650 | 7966 | 96.03% |
| `delta_pregame_goalie_days_since_last_start_home_minus_away` | 7553 | 7966 | 94.82% |
| `delta_pregame_top9_points_pg_home_minus_away` | 7794 | 7966 | 97.84% |
| `delta_pregame_depth_points_share_last5_home_minus_away` | 7793 | 7966 | 97.83% |
| `delta_pregame_special_teams_contributor_share_last5_home_minus_away` | 7879 | 7966 | 98.91% |
| `delta_pregame_key_contributor_continuity_pct_home_minus_away` | 7856 | 7966 | 98.62% |
| `delta_pregame_lineup_change_rate_last5_home_minus_away` | 7837 | 7966 | 98.38% |
| `delta_pregame_recent_form_adj_last5_home_minus_away` | 0 | 7966 | 0.00% |
| `delta_pregame_recent_form_volatility_last5_home_minus_away` | 7856 | 7966 | 98.62% |
| `delta_pregame_lineup_continuity_pct_home_minus_away` | 7856 | 7966 | 98.62% |
| `delta_pregame_roster_turnover_count_home_minus_away` | 7879 | 7966 | 98.91% |
| `home_pregame_goalie_starter_certainty` | 7966 | 7966 | 100.00% |
| `away_pregame_goalie_starter_certainty` | 7966 | 7966 | 100.00% |
| `home_pregame_goalie_starter_quality_gap_last5` | 7966 | 7966 | 100.00% |
| `away_pregame_goalie_starter_quality_gap_last5` | 7966 | 7966 | 100.00% |
| `home_pregame_goalie_starter_quality_gap_last10` | 7966 | 7966 | 100.00% |
| `away_pregame_goalie_starter_quality_gap_last10` | 7966 | 7966 | 100.00% |
| `delta_pregame_goalie_starter_certainty_home_minus_away` | 7966 | 7966 | 100.00% |
| `delta_pregame_goalie_starter_quality_gap_last5_home_minus_away` | 7966 | 7966 | 100.00% |
| `delta_pregame_goalie_starter_quality_gap_last10_home_minus_away` | 7966 | 7966 | 100.00% |
