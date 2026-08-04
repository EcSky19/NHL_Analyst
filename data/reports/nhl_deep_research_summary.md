# NHL Deep Research Summary

Generated from: `data\processed\nhl_research.db`  
Related methodology: `data\reports\shot_threshold_methodology.md`

## 1) Sources used and contribution

### NHL sources
- **`api.nhle.com/stats/rest`**: primary team, skater, and goalie statistical datasets.
  - Team endpoints represented in `team_stats.source_api`:  
    `.../team/summary`, `.../team/realtime`, `.../team/powerplay`, `.../team/penaltykill`, `.../team/percentages`
  - Player endpoints represented in `player_stats.source_api`:  
    `.../skater/summary`, `.../skater/scoringpergame`, `.../skater/realtime`, `.../skater/percentages`, `.../goalie/summary`, `.../goalie/advanced`
- **`nhl_play_by_play`**: derived shot-threshold outputs and supporting summary metrics.
  - Stored in `shot_threshold_stats`
  - Supporting aggregate rows in `team_stats` with metrics `games_analyzed`, `goals_analyzed`, `avg_shots_needed_per_goal`
- **Raw NHL files location**: `data\raw\nhl` (81 files)

### ESPN sources
- **ESPN season/team/player feeds** provide complementary team-level and leader-focused player metrics.
  - Team stats in `team_stats.source_api = 'espn_team_stats'`
  - Player leader rows in `player_stats.source_api IN ('espn_team_leaders','espn_league_leaders')`
- **Raw ESPN files location**: `data\raw\espn` (1069 files)

## 2) Data coverage snapshot

- Teams in `teams`: **96** (32 NHL teams represented across 3 sources: `api.nhle.com/stats/rest`, `espn`, `nhl_api`)
- Players in `players`: **2007**
  - `api.nhle.com/stats/rest`: 1070
  - `espn`: 937
- Stats row totals:
  - `team_stats`: **5914**
  - `player_stats`: **82375**
  - `shot_threshold_stats`: **96**
  - `api_snapshots`: **1153**

### Team stats row counts by source (`team_stats`)
- `espn_team_stats`: 2970
- `api.nhle.com/stats/rest/team/summary`: 672
- `api.nhle.com/stats/rest/team/percentages`: 576
- `api.nhle.com/stats/rest/team/powerplay`: 544
- `api.nhle.com/stats/rest/team/penaltykill`: 544
- `api.nhle.com/stats/rest/team/realtime`: 512
- `nhl_play_by_play`: 96

### Player stats row counts by source (`player_stats`)
- `api.nhle.com/stats/rest/skater/realtime`: 22302
- `api.nhle.com/stats/rest/skater/scoringpergame`: 19530
- `api.nhle.com/stats/rest/skater/summary`: 17462
- `api.nhle.com/stats/rest/skater/percentages`: 15851
- `espn_team_leaders`: 3877
- `api.nhle.com/stats/rest/goalie/summary`: 1568
- `api.nhle.com/stats/rest/goalie/advanced`: 1560
- `espn_league_leaders`: 225

## 3) Key team stats dimensions available

Examples of high-value team dimensions:
- **Offense**: goals, shots, shooting %, points/game, faceoff win %, power-play goals/opportunities/pct
- **Defense**: goals against, shots against, save %, blocked shots, takeaways/giveaways, hits
- **Special teams**: power-play %, penalty-kill %, shorthanded goals for/against, PP/PK time on ice
- **Possession/shot-share**: `satPct`, `usatPct`, score-state adjusted SAT/USAT splits, zone start %
- **Derived shot-threshold context**: `games_analyzed`, `goals_analyzed`, `avg_shots_needed_per_goal`

## 4) Key player stats dimensions available

### Skaters (NHL REST + ESPN leaders)
- Scoring: goals, assists, points, points/game, EV/PP/SH splits, GWG/OT goals
- Shooting/attempt profile: shots, shooting %, total shot attempts, blocked/missed shot breakdowns
- Physical/possession context: hits, takeaways, giveaways, time on ice

### Goalies (NHL REST + ESPN leaders)
- Core performance: wins/losses/OT losses, games started, goals against, GAA, saves, save %
- Advanced context: quality starts, complete game %, shots against per 60, goals-for support metrics

## 5) Shot-threshold analysis (what it is + where results are)

- Method is documented in `data\reports\shot_threshold_methodology.md`.
- Computation used season play-by-play (`nhl_play_by_play`) to track shots since previous team goal, excluding shootout events.
- Stored outputs:
  - **Threshold rows** in `shot_threshold_stats` for `<=5`, `<=10`, `<=15` (event type: `goal_within_shots_since_prev_team_goal`)
  - **Per-team aggregate support** in `team_stats` (`source_api='nhl_play_by_play'`) via `avg_shots_needed_per_goal`, `games_analyzed`, `goals_analyzed`

## 6) Example SQL queries (practical usage)

```sql
-- A) Coverage by team-stat source
SELECT source_api, COUNT(*) AS rows, COUNT(DISTINCT team_id) AS teams
FROM team_stats
GROUP BY source_api
ORDER BY rows DESC;
```

```sql
-- B) Team shooting % leaderboard (ESPN team stats)
SELECT t.name, ts.metric_value AS shooting_pct
FROM team_stats ts
JOIN teams t ON t.team_id = ts.team_id
WHERE ts.source_api = 'espn_team_stats'
  AND ts.metric_name = 'offensive.shootingPct'
ORDER BY ts.metric_value DESC
LIMIT 10;
```

```sql
-- C) Goalie save % leaderboard (NHL goalie summary)
SELECT p.full_name, t.name AS team, ps.metric_value AS save_pct
FROM player_stats ps
JOIN players p ON p.player_id = ps.player_id
LEFT JOIN teams t ON t.team_id = ps.team_id
WHERE ps.source_api = 'api.nhle.com/stats/rest/goalie/summary'
  AND ps.metric_name = 'savePct'
ORDER BY ps.metric_value DESC
LIMIT 20;
```

```sql
-- D) How often teams score within X shots of previous team goal
-- Set X using threshold_label IN ('<=5','<=10','<=15')
SELECT t.name, s.threshold_label, s.stat_count, ROUND(s.stat_rate, 4) AS rate
FROM shot_threshold_stats s
JOIN teams t ON t.team_id = s.team_id
WHERE s.event_type = 'goal_within_shots_since_prev_team_goal'
  AND s.threshold_label = '<=10'
ORDER BY s.stat_rate DESC;
```

```sql
-- E) "After X shots" framing (example X=10): share of goals NOT scored within 10 shots
SELECT t.name,
       ROUND(1.0 - s.stat_rate, 4) AS pct_goals_after_10_plus_shots
FROM shot_threshold_stats s
JOIN teams t ON t.team_id = s.team_id
WHERE s.event_type = 'goal_within_shots_since_prev_team_goal'
  AND s.threshold_label = '<=10'
ORDER BY pct_goals_after_10_plus_shots DESC;
```

```sql
-- F) Average shots needed per goal from play-by-play derived aggregates
SELECT t.name, ts.metric_value AS avg_shots_needed_per_goal
FROM team_stats ts
JOIN teams t ON t.team_id = ts.team_id
WHERE ts.source_api = 'nhl_play_by_play'
  AND ts.metric_name = 'avg_shots_needed_per_goal'
ORDER BY ts.metric_value ASC;
```

## 7) Caveats / data quality notes

- **Source-specific entity duplication**: teams and players are source-scoped (`teams.source`, `players.source`), so the same real-world entity can appear multiple times across sources.
- **Season key format differs by source**:
  - NHL REST rows commonly use `season='20252026'`
  - ESPN-derived rows commonly use `season='2026'`
- **Metric naming differs by source**:
  - ESPN team metrics are namespace-like (e.g., `offensive.*`, `defensive.*`, `penalties.*`)
  - NHL REST metrics are endpoint-specific normalized names (e.g., `satPct`, `ppGoalsPerGame`)
- **ESPN team leader metric names are high-cardinality** (e.g., `team_<id>_leader.points`), requiring pattern matching for broad comparisons.
- **Shot-threshold precompute is discrete**: stored thresholds are only `<=5`, `<=10`, `<=15`; arbitrary X requires recomputation from raw play-by-play events.
