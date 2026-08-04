# Shot Threshold Methodology

- Source: NHL API play-by-play (`nhl_play_by_play`)
- Season: 20252026 regular season
- Completed games in season feed: 1312
- Processed play-by-play games: 1312
- Skipped games: 0

Method (team offense perspective):
1. In each game, initialize per-team counter `shots_since_last_team_goal = 0`.
2. Parse play-by-play events; only `shot-on-goal` and `goal` are relevant.
3. Exclude shootout events (`periodType == 'SO'`); include regulation and overtime.
4. On `shot-on-goal` by team T, increment counter for T.
5. On `goal` by team T, record `shots_needed = counter[T] + 1` (goal counts as the scoring shot), then reset counter for T to 0.

Computed per team:
- games_analyzed
- goals_analyzed
- avg_shots_needed_per_goal
- goal rates within <=5, <=10, <=15 shots
