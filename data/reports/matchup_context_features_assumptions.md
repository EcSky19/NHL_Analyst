# Matchup context feature assumptions

1. **Winning streak source**  
   `home_streak_signed` / `away_streak_signed` are derived from NHL standings `streakCode` + `streakCount` (`W` positive, non-`W` negative) because direct per-game streak tables are not stored in `nhl_research.db`.

2. **Recent-form proxy**  
   Recent trend metrics use standings last-10 splits (`l10*` fields), including:
   - `l10_points_pct`
   - `l10_goal_diff_per_game`
   - `trend_*_l10_minus_season` deltas versus season-long rates

3. **Location context**  
   Home/away location effects are approximated from standings home/road splits:
   - `home_home_points_pct` vs `away_road_points_pct`
   - `home_home_goal_diff_per_game` vs `away_road_goal_diff_per_game`
   plus `is_neutral_site` from ESPN competition metadata.

4. **Season boundary behavior**  
   If scoreboard events are future-season games and current-season team game logs are unavailable, the script uses the latest available standings snapshot as preseason prior context.

5. **Join alignment**  
   Output rows are game-level and keyed by `game_id`, `game_date_utc`, `home_team_abbrev`, and `away_team_abbrev`, with both team-side and delta features ready for downstream joins.
