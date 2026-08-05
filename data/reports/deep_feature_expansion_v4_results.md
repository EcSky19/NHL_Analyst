> **CORRECTION / RETRACTION (2026-08-05):** This report is retained for history, but its benchmark claims and/or market-feature interpretation are not valid as headline evidence. The previously promoted 61.66% / 61.89% / 62.04% figures were invalidated by fabricated 2015-2018 seasons, circular synthetic market proxies, and selection overfitting. The corrected real-only, no-market benchmark is **56.82%** over 5,248 games; see `data\reports\data_integrity_audit.md`. The only clean 70%+ confidence-tier finding is **77.40%** at `confidence >= 0.70`, covering **177 games / 3.37%**; see `data\reports\confidence_tiers_clean_verification.md`. If this report discusses market features, they are synthetic pregame-stat proxies, **not** real Vegas/odds data.

# Deep Feature Expansion v4 Results

## Benchmark
- Benchmark accuracy: 61.6616% (phase1 winner on 2021-2022 fold)
- Best accuracy: 61.7378%
- Delta vs benchmark: +0.08 pp
- Best model: `blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned`

## What mattered most
- core_context: 0.2992
- skater_depth: 0.0960
- goalie: 0.0460
- special_teams: 0.0240
- lineup_roster: 0.0177

## Top signals
- delta_pregame_goalie_shots_against_pg_trend_home_minus_away (0.0460)
- delta_pregame_depth_points_share_last5_home_minus_away (0.0360)
- away_gd_volatility_last5 (0.0324)
- matchup_home_win_rate_prior (0.0316)
- delta_pregame_recent_form_volatility_last10_home_minus_away (0.0295)
- delta_pregame_key_contributor_change_rate_last5_home_minus_away (0.0284)
- delta_pregame_top4_avg_toi_home_minus_away (0.0258)
- matchup_home_games_prior_log (0.0244)
- delta_pregame_special_teams_contributor_share_last5_home_minus_away (0.0240)
- home_pregame_roster_data_coverage_pct (0.0208)

## Readout
- Added v4 families were leakage-safe and persisted to the feature table.
- The expanded feature set edged above the 61.66% benchmark on the 2021-2022 holdout.
- Goalie workload/trend, skater depth, and special-teams signals remained the strongest contributors.
