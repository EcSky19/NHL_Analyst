# Roster-aware pregame feature schema foundation

## Scope and pregame-only guardrails
- Goal: establish deterministic schema + script scaffolding for roster-aware pregame modeling without requiring completed roster ingestion.
- Leakage guardrail: every roster feature is defined `as_of_game_date` and must be computed from data available **before puck drop** for that game.
- Any postgame stat updates, same-day final boxscores, or future games are excluded from feature definitions.

## Existing assets inspected

### Modeling scripts
- `scripts\build_last5_backtest_features.py`
  - Existing strict pregame historical feature table: `backtest_features_last5`.
- `scripts\build_matchup_context_features.py`
  - Current matchup context pattern for deterministic CSV + SQLite outputs.
- `scripts\evaluate_last5seasons.py`
  - Existing walk-forward pregame backtest evaluation conventions.

### SQLite tables (`data\processed\nhl_research.db`)
- Historical modeling inputs:
  - `historical_games_last5`
  - `backtest_features_last5`
  - `team_alias_map`
- Player/team stat sources available for roster-derived features:
  - `players`
  - `player_stats`
  - `teams`
  - `team_stats`

## New roster-aware table design

### Final modeling table
- `backtest_features_last5_roster`
- Schema = all columns from `backtest_features_last5` plus roster-aware columns:
  - Team-side pregame roster quality:
    - `home_pregame_roster_quality_idx`, `away_pregame_roster_quality_idx`
    - `home_pregame_goalie_save_pct`, `away_pregame_goalie_save_pct`
    - `home_pregame_top6_points_pg`, `away_pregame_top6_points_pg`
    - `home_pregame_top4_avg_toi`, `away_pregame_top4_avg_toi`
    - `home_pregame_skater_points_pg_last5`, `away_pregame_skater_points_pg_last5`
    - `home_pregame_skater_two_way_idx_last5`, `away_pregame_skater_two_way_idx_last5`
  - Data quality / availability:
    - `home_pregame_roster_games_covered`, `away_pregame_roster_games_covered`
    - `home_pregame_roster_data_coverage_pct`, `away_pregame_roster_data_coverage_pct`
    - `home_pregame_injury_count`, `away_pregame_injury_count`
    - `home_pregame_confirmed_starters_count`, `away_pregame_confirmed_starters_count`
    - `home_roster_source_tag`, `away_roster_source_tag`
    - `home_roster_source_stats_through_date`, `away_roster_source_stats_through_date`
  - ML-ready deltas:
    - `delta_pregame_roster_quality_idx_home_minus_away`
    - `delta_pregame_goalie_save_pct_home_minus_away`
    - `delta_pregame_skater_points_pg_last5_home_minus_away`
    - `delta_pregame_skater_two_way_idx_last5_home_minus_away`
    - `delta_pregame_injury_count_home_minus_away`

### Intermediate scaffold tables
- `roster_team_pregame_features_last5`
  - Grain: `(season, game_id, team_abbrev)`
  - Purpose: deterministic team-level roster feature inputs used by final table build.
- `roster_player_pregame_stats_last5`
  - Grain: `(season, game_id, team_abbrev, player_id)`
  - Purpose: pregame rolling player metrics feeding team rollups.

## Feature definition notes (pregame-only)
- `pregame_roster_quality_idx`
  - Composite score derived only from pregame player form + availability signals.
  - Must use stats snapshots up to `source_stats_through_date <= game_date`.
- `pregame_goalie_save_pct`
  - Expected starter/goalie-group save% using trailing games completed prior to game date.
- `pregame_top6_points_pg`
  - Mean points-per-game among projected top-6 forwards, from trailing completed games only.
- `pregame_top4_avg_toi`
  - Mean TOI/game among projected top-4 defensemen from prior games only.
- `pregame_skater_points_pg_last5`
  - Team-level average skater points/game over each skater’s last 5 completed games before game date.
- `pregame_skater_two_way_idx_last5`
  - Last-5 two-way proxy (e.g., points + defensive impacts) strictly from completed prior games.
- `pregame_roster_data_coverage_pct`
  - Fraction of expected active roster slots with sufficient pregame data; improves model trust handling.

## Deterministic pipeline scaffolding added
- `scripts\prepare_roster_feature_schema.py`
  - Creates final + intermediate roster schema tables and indexes.
  - Idempotent and safe to re-run.
- `scripts\build_last5_backtest_features_roster.py`
  - Inputs:
    - Base table: `backtest_features_last5`
    - Optional roster team table: `roster_team_pregame_features_last5`
  - Outputs:
    - SQLite table: `backtest_features_last5_roster`
    - CSV: `data\processed\backtest_features_last5_roster.csv`
  - If roster table is empty/missing, still emits deterministic schema-valid output with null roster feature values.

## Practical next step for ingestion integration
- Populate `roster_player_pregame_stats_last5` and `roster_team_pregame_features_last5` with pregame snapshots.
- Re-run `build_last5_backtest_features_roster.py` to materialize fully populated roster-aware modeling features.
