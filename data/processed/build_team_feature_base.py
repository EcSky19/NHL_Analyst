import argparse
import csv
import sqlite3
from pathlib import Path
from typing import Optional, Tuple


def resolve_season_scope(conn: sqlite3.Connection, season: Optional[str], season_type: str) -> str:
    """Pick a consistent season shared by team and player NHL API tables."""
    if season:
        return season

    query = """
    WITH team_scope AS (
        SELECT season, COUNT(DISTINCT team_id) AS team_count
        FROM team_stats
        WHERE season_type = :season_type
          AND source_api LIKE 'api.nhle.com/stats/rest/team/%'
        GROUP BY season
    ),
    player_scope AS (
        SELECT season, COUNT(DISTINCT team_id) AS team_count
        FROM player_stats
        WHERE season_type = :season_type
          AND source_api LIKE 'api.nhle.com/stats/rest/%'
        GROUP BY season
    ),
    threshold_scope AS (
        SELECT season, COUNT(DISTINCT team_id) AS team_count
        FROM shot_threshold_stats
        WHERE season_type = :season_type
        GROUP BY season
    )
    SELECT t.season
    FROM team_scope t
    JOIN player_scope p ON p.season = t.season
    LEFT JOIN threshold_scope s ON s.season = t.season
    WHERE t.team_count >= 30 AND p.team_count >= 30
    ORDER BY
        CASE WHEN s.team_count IS NULL THEN 0 ELSE 1 END DESC,
        t.team_count DESC,
        p.team_count DESC,
        t.season DESC
    LIMIT 1
    """
    row = conn.execute(query, {"season_type": season_type}).fetchone()
    if not row:
        raise RuntimeError("Could not infer a consistent season scope from existing tables.")
    return row[0]


def build_feature_table(conn: sqlite3.Connection, season: str, season_type: str) -> int:
    create_table_sql = """
    CREATE TABLE team_feature_base AS
    WITH ranked_team_stats AS (
        SELECT
            ts.team_id,
            ts.season,
            ts.season_type,
            ts.metric_name,
            ts.metric_value,
            ROW_NUMBER() OVER (
                PARTITION BY ts.team_id, ts.season, ts.season_type, ts.metric_name
                ORDER BY
                    CASE
                        WHEN ts.source_api = 'api.nhle.com/stats/rest/team/summary' THEN 1
                        WHEN ts.source_api = 'api.nhle.com/stats/rest/team/realtime' THEN 2
                        WHEN ts.source_api = 'api.nhle.com/stats/rest/team/percentages' THEN 3
                        WHEN ts.source_api = 'api.nhle.com/stats/rest/team/powerplay' THEN 4
                        WHEN ts.source_api = 'api.nhle.com/stats/rest/team/penaltykill' THEN 5
                        WHEN ts.source_api = 'nhl_play_by_play' THEN 6
                        ELSE 99
                    END,
                    ts.snapshot_id DESC,
                    ts.team_stat_id DESC
            ) AS rn
        FROM team_stats ts
        WHERE ts.season = :season
          AND ts.season_type = :season_type
          AND (
              ts.source_api LIKE 'api.nhle.com/stats/rest/team/%'
              OR ts.source_api = 'nhl_play_by_play'
          )
    ),
    team_metric_wide AS (
        SELECT
            team_id,
            season,
            season_type,
            MAX(CASE WHEN metric_name = 'gamesPlayed' THEN metric_value END) AS games_played,
            MAX(CASE WHEN metric_name = 'goalsFor' THEN metric_value END) AS goals_for,
            MAX(CASE WHEN metric_name = 'shots' THEN metric_value END) AS shots_for,
            MAX(CASE WHEN metric_name = 'goalsAgainst' THEN metric_value END) AS goals_against,
            MAX(CASE WHEN metric_name = 'shotsAgainstPerGame' THEN metric_value END) AS shots_against_per_game,
            MAX(CASE WHEN metric_name = 'savePct5v5' THEN metric_value END) AS save_pct_5v5,
            MAX(CASE WHEN metric_name = 'shootingPct5v5' THEN metric_value END) AS shooting_pct_5v5,
            MAX(CASE WHEN metric_name = 'powerPlayPct' THEN metric_value END) AS power_play_pct,
            MAX(CASE WHEN metric_name = 'penaltyKillPct' THEN metric_value END) AS penalty_kill_pct,
            MAX(CASE WHEN metric_name = 'powerPlayGoalsFor' THEN metric_value END) AS power_play_goals_for,
            MAX(CASE WHEN metric_name = 'ppOpportunities' THEN metric_value END) AS pp_opportunities,
            MAX(CASE WHEN metric_name = 'timesShorthanded' THEN metric_value END) AS times_shorthanded,
            MAX(CASE WHEN metric_name = 'ppGoalsAgainst' THEN metric_value END) AS pp_goals_against,
            MAX(CASE WHEN metric_name = 'faceoffWinPct' THEN metric_value END) AS faceoff_win_pct,
            MAX(CASE WHEN metric_name = 'satPct' THEN metric_value END) AS sat_pct,
            MAX(CASE WHEN metric_name = 'blockedShots' THEN metric_value END) AS blocked_shots,
            MAX(CASE WHEN metric_name = 'hits' THEN metric_value END) AS hits,
            MAX(CASE WHEN metric_name = 'takeaways' THEN metric_value END) AS takeaways,
            MAX(CASE WHEN metric_name = 'giveaways' THEN metric_value END) AS giveaways,
            NULL AS avg_shots_needed_per_goal,
            NULL AS goals_analyzed,
            NULL AS games_analyzed
        FROM ranked_team_stats
        WHERE rn = 1
        GROUP BY team_id, season, season_type
    ),
    -- Play-by-play records use nhl_api team IDs, so map via abbreviation.
    pbp_agg AS (
        SELECT
            t.abbreviation AS team_abbreviation_raw,
            MAX(CASE WHEN ts.metric_name = 'avg_shots_needed_per_goal' THEN ts.metric_value END) AS avg_shots_needed_per_goal,
            MAX(CASE WHEN ts.metric_name = 'goals_analyzed' THEN ts.metric_value END) AS goals_analyzed,
            MAX(CASE WHEN ts.metric_name = 'games_analyzed' THEN ts.metric_value END) AS games_analyzed
        FROM team_stats ts
        JOIN teams t
          ON t.team_id = ts.team_id
         AND t.source = 'nhl_api'
        WHERE ts.season = :season
          AND ts.season_type = :season_type
          AND ts.source_api = 'nhl_play_by_play'
        GROUP BY t.abbreviation
    ),
    skater_summary AS (
        SELECT
            ps.team_id,
            ps.player_id,
            MAX(CASE WHEN ps.metric_name = 'gamesPlayed' THEN ps.metric_value END) AS games_played,
            MAX(CASE WHEN ps.metric_name = 'goals' THEN ps.metric_value END) AS goals,
            MAX(CASE WHEN ps.metric_name = 'assists' THEN ps.metric_value END) AS assists,
            MAX(CASE WHEN ps.metric_name = 'points' THEN ps.metric_value END) AS points,
            MAX(CASE WHEN ps.metric_name = 'shots' THEN ps.metric_value END) AS shots
        FROM player_stats ps
        WHERE ps.season = :season
          AND ps.season_type = :season_type
          AND ps.source_api = 'api.nhle.com/stats/rest/skater/summary'
        GROUP BY ps.team_id, ps.player_id
    ),
    skater_realtime AS (
        SELECT
            ps.team_id,
            ps.player_id,
            MAX(CASE WHEN ps.metric_name = 'hits' THEN ps.metric_value END) AS hits,
            MAX(CASE WHEN ps.metric_name = 'blockedShots' THEN ps.metric_value END) AS blocked_shots,
            MAX(CASE WHEN ps.metric_name = 'takeaways' THEN ps.metric_value END) AS takeaways,
            MAX(CASE WHEN ps.metric_name = 'giveaways' THEN ps.metric_value END) AS giveaways
        FROM player_stats ps
        WHERE ps.season = :season
          AND ps.season_type = :season_type
          AND ps.source_api = 'api.nhle.com/stats/rest/skater/realtime'
        GROUP BY ps.team_id, ps.player_id
    ),
    skater_team_agg AS (
        SELECT
            ss.team_id,
            COUNT(DISTINCT ss.player_id) AS skater_count,
            COALESCE(SUM(ss.games_played), 0.0) AS skater_games_total,
            COALESCE(SUM(ss.goals), 0.0) AS skater_goals_total,
            COALESCE(SUM(ss.assists), 0.0) AS skater_assists_total,
            COALESCE(SUM(ss.points), 0.0) AS skater_points_total,
            COALESCE(SUM(ss.shots), 0.0) AS skater_shots_total,
            COALESCE(MAX(ss.points), 0.0) AS top_scorer_points,
            COALESCE(SUM(sr.hits), 0.0) AS skater_hits_total,
            COALESCE(SUM(sr.blocked_shots), 0.0) AS skater_blocked_shots_total,
            COALESCE(SUM(sr.takeaways), 0.0) AS skater_takeaways_total,
            COALESCE(SUM(sr.giveaways), 0.0) AS skater_giveaways_total
        FROM skater_summary ss
        LEFT JOIN skater_realtime sr
            ON sr.team_id = ss.team_id
           AND sr.player_id = ss.player_id
        GROUP BY ss.team_id
    ),
    goalie_summary AS (
        SELECT
            ps.team_id,
            ps.player_id,
            MAX(CASE WHEN ps.metric_name = 'gamesStarted' THEN ps.metric_value END) AS games_started,
            MAX(CASE WHEN ps.metric_name = 'wins' THEN ps.metric_value END) AS wins,
            MAX(CASE WHEN ps.metric_name = 'saves' THEN ps.metric_value END) AS saves,
            MAX(CASE WHEN ps.metric_name = 'shotsAgainst' THEN ps.metric_value END) AS shots_against,
            MAX(CASE WHEN ps.metric_name = 'goalsAgainst' THEN ps.metric_value END) AS goals_against,
            MAX(CASE WHEN ps.metric_name = 'savePct' THEN ps.metric_value END) AS save_pct
        FROM player_stats ps
        WHERE ps.season = :season
          AND ps.season_type = :season_type
          AND ps.source_api = 'api.nhle.com/stats/rest/goalie/summary'
        GROUP BY ps.team_id, ps.player_id
    ),
    goalie_team_agg AS (
        SELECT
            gs.team_id,
            COUNT(DISTINCT gs.player_id) AS goalie_count,
            COALESCE(SUM(gs.games_started), 0.0) AS goalie_games_started_total,
            COALESCE(SUM(gs.wins), 0.0) AS goalie_wins_total,
            COALESCE(SUM(gs.saves), 0.0) AS goalie_saves_total,
            COALESCE(SUM(gs.shots_against), 0.0) AS goalie_shots_against_total,
            COALESCE(SUM(gs.goals_against), 0.0) AS goalie_goals_against_total,
            COALESCE(AVG(gs.save_pct), 0.0) AS goalie_avg_save_pct
        FROM goalie_summary gs
        GROUP BY gs.team_id
    ),
    -- Shot-threshold rows also use nhl_api team IDs, so map via abbreviation.
    threshold_agg AS (
        SELECT
            t.abbreviation AS team_abbreviation_raw,
            MAX(CASE WHEN sts.threshold_label = '<=5' THEN sts.stat_count END) AS goal_within_5_shots_count,
            MAX(CASE WHEN sts.threshold_label = '<=10' THEN sts.stat_count END) AS goal_within_10_shots_count,
            MAX(CASE WHEN sts.threshold_label = '<=15' THEN sts.stat_count END) AS goal_within_15_shots_count,
            MAX(CASE WHEN sts.threshold_label = '<=5' THEN sts.stat_rate END) AS goal_within_5_shots_rate,
            MAX(CASE WHEN sts.threshold_label = '<=10' THEN sts.stat_rate END) AS goal_within_10_shots_rate,
            MAX(CASE WHEN sts.threshold_label = '<=15' THEN sts.stat_rate END) AS goal_within_15_shots_rate
        FROM shot_threshold_stats sts
        JOIN teams t
          ON t.team_id = sts.team_id
         AND t.source = 'nhl_api'
        WHERE sts.season = :season
          AND sts.season_type = :season_type
          AND sts.event_type = 'goal_within_shots_since_prev_team_goal'
        GROUP BY t.abbreviation
    )
    SELECT
        tmw.season,
        tmw.season_type,
        tmw.team_id,
        LOWER(REPLACE(t.abbreviation, ' ', '_')) AS team_abbreviation,
        t.name AS team_name,
        COALESCE(tmw.games_played, 0.0) AS games_played,
        COALESCE(tmw.goals_for, 0.0) AS off_goals_for,
        COALESCE(tmw.shots_for, 0.0) AS off_shots_for,
        ROUND(COALESCE(tmw.goals_for / NULLIF(tmw.games_played, 0), 0.0), 6) AS off_goals_per_game,
        ROUND(COALESCE(tmw.shots_for / NULLIF(tmw.games_played, 0), 0.0), 6) AS off_shots_per_game,
        ROUND(COALESCE((tmw.goals_for * 100.0) / NULLIF(tmw.shots_for, 0), 0.0), 6) AS off_shooting_pct,
        COALESCE(tmw.shooting_pct_5v5, 0.0) AS off_shooting_pct_5v5,
        COALESCE(tmw.goals_against, 0.0) AS def_goals_against,
        ROUND(COALESCE(tmw.goals_against / NULLIF(tmw.games_played, 0), 0.0), 6) AS def_goals_against_per_game,
        COALESCE(tmw.shots_against_per_game, 0.0) AS def_shots_against_per_game,
        ROUND(COALESCE((tmw.shots_against_per_game * tmw.games_played), 0.0), 6) AS def_shots_against_est_total,
        ROUND(
            COALESCE(
                (
                    ((tmw.shots_against_per_game * tmw.games_played) - tmw.goals_against) * 100.0
                ) / NULLIF((tmw.shots_against_per_game * tmw.games_played), 0),
                0.0
            ),
            6
        ) AS def_save_pct_est,
        COALESCE(tmw.save_pct_5v5, 0.0) AS def_save_pct_5v5,
        COALESCE(tmw.power_play_pct, 0.0) AS st_power_play_pct,
        COALESCE(tmw.penalty_kill_pct, 0.0) AS st_penalty_kill_pct,
        ROUND(COALESCE(tmw.power_play_pct + tmw.penalty_kill_pct, 0.0), 6) AS st_special_teams_index,
        COALESCE(tmw.power_play_goals_for, 0.0) AS st_power_play_goals_for,
        COALESCE(tmw.pp_opportunities, 0.0) AS st_power_play_opportunities,
        ROUND(COALESCE((tmw.power_play_goals_for * 100.0) / NULLIF(tmw.pp_opportunities, 0), 0.0), 6) AS st_power_play_goal_rate_pct,
        COALESCE(tmw.times_shorthanded, 0.0) AS st_times_shorthanded,
        COALESCE(tmw.pp_goals_against, 0.0) AS st_power_play_goals_against,
        ROUND(COALESCE((tmw.pp_goals_against * 100.0) / NULLIF(tmw.times_shorthanded, 0), 0.0), 6) AS st_pp_goals_against_rate_pct,
        COALESCE(tmw.faceoff_win_pct, 0.0) AS puck_faceoff_win_pct,
        COALESCE(tmw.sat_pct, 0.0) AS puck_sat_pct,
        COALESCE(tmw.blocked_shots, 0.0) AS puck_blocked_shots,
        COALESCE(tmw.hits, 0.0) AS puck_hits,
        COALESCE(tmw.takeaways, 0.0) AS puck_takeaways,
        COALESCE(tmw.giveaways, 0.0) AS puck_giveaways,
        COALESCE(sta.skater_count, 0) AS player_skater_count,
        COALESCE(sta.skater_goals_total, 0.0) AS player_skater_goals_total,
        COALESCE(sta.skater_assists_total, 0.0) AS player_skater_assists_total,
        COALESCE(sta.skater_points_total, 0.0) AS player_skater_points_total,
        COALESCE(sta.skater_shots_total, 0.0) AS player_skater_shots_total,
        ROUND(COALESCE(sta.skater_points_total / NULLIF(sta.skater_games_total, 0), 0.0), 6) AS player_skater_points_per_game,
        COALESCE(sta.top_scorer_points, 0.0) AS player_top_scorer_points,
        ROUND(COALESCE(sta.top_scorer_points / NULLIF(sta.skater_points_total, 0), 0.0), 6) AS player_top_scorer_points_share,
        COALESCE(sta.skater_hits_total, 0.0) AS player_skater_hits_total,
        COALESCE(sta.skater_blocked_shots_total, 0.0) AS player_skater_blocked_shots_total,
        COALESCE(sta.skater_takeaways_total, 0.0) AS player_skater_takeaways_total,
        COALESCE(sta.skater_giveaways_total, 0.0) AS player_skater_giveaways_total,
        COALESCE(gta.goalie_count, 0) AS player_goalie_count,
        COALESCE(gta.goalie_games_started_total, 0.0) AS player_goalie_games_started_total,
        COALESCE(gta.goalie_wins_total, 0.0) AS player_goalie_wins_total,
        COALESCE(gta.goalie_saves_total, 0.0) AS player_goalie_saves_total,
        COALESCE(gta.goalie_shots_against_total, 0.0) AS player_goalie_shots_against_total,
        COALESCE(gta.goalie_goals_against_total, 0.0) AS player_goalie_goals_against_total,
        ROUND(COALESCE((gta.goalie_saves_total * 100.0) / NULLIF(gta.goalie_shots_against_total, 0), 0.0), 6) AS player_goalie_save_pct_weighted,
        ROUND(COALESCE(gta.goalie_avg_save_pct, 0.0), 6) AS player_goalie_save_pct_avg,
        ROUND(COALESCE((gta.goalie_wins_total * 100.0) / NULLIF(gta.goalie_games_started_total, 0), 0.0), 6) AS player_goalie_win_pct,
        COALESCE(ta.goal_within_5_shots_count, 0) AS pressure_goal_within_5_shots_count,
        COALESCE(ta.goal_within_10_shots_count, 0) AS pressure_goal_within_10_shots_count,
        COALESCE(ta.goal_within_15_shots_count, 0) AS pressure_goal_within_15_shots_count,
        ROUND(COALESCE(ta.goal_within_5_shots_rate, 0.0), 6) AS pressure_goal_within_5_shots_rate,
        ROUND(COALESCE(ta.goal_within_10_shots_rate, 0.0), 6) AS pressure_goal_within_10_shots_rate,
        ROUND(COALESCE(ta.goal_within_15_shots_rate, 0.0), 6) AS pressure_goal_within_15_shots_rate,
        COALESCE(pbp.avg_shots_needed_per_goal, 0.0) AS pressure_avg_shots_needed_per_goal,
        COALESCE(pbp.goals_analyzed, 0.0) AS pressure_goals_analyzed,
        COALESCE(pbp.games_analyzed, 0.0) AS pressure_games_analyzed
    FROM team_metric_wide tmw
    JOIN teams t
      ON t.team_id = tmw.team_id
     AND t.source = 'api.nhle.com/stats/rest'
    LEFT JOIN skater_team_agg sta
      ON sta.team_id = tmw.team_id
    LEFT JOIN goalie_team_agg gta
      ON gta.team_id = tmw.team_id
    LEFT JOIN threshold_agg ta
      ON ta.team_abbreviation_raw = t.abbreviation
    LEFT JOIN pbp_agg pbp
      ON pbp.team_abbreviation_raw = t.abbreviation
    ORDER BY tmw.season, team_abbreviation
    """
    conn.execute("DROP TABLE IF EXISTS team_feature_base")
    conn.execute(create_table_sql, {"season": season, "season_type": season_type})
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_team_feature_base_scope
        ON team_feature_base (season, season_type, team_id)
        """
    )
    row_count = conn.execute("SELECT COUNT(*) FROM team_feature_base").fetchone()[0]
    return row_count


def export_csv(conn: sqlite3.Connection, csv_path: Path) -> Tuple[int, int]:
    rows = conn.execute(
        "SELECT * FROM team_feature_base ORDER BY season, team_abbreviation"
    ).fetchall()
    columns = [row[1] for row in conn.execute("PRAGMA table_info(team_feature_base)").fetchall()]

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    return len(rows), len(columns)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build team-level NHL feature base from local research DB.")
    parser.add_argument(
        "--db-path",
        default=str(Path(__file__).with_name("nhl_research.db")),
        help="Path to SQLite DB file (default: data\\processed\\nhl_research.db).",
    )
    parser.add_argument(
        "--output-csv",
        default=str(Path(__file__).with_name("team_feature_base.csv")),
        help="Output CSV path (default: data\\processed\\team_feature_base.csv).",
    )
    parser.add_argument("--season", default=None, help="Season scope override (default: auto-detect).")
    parser.add_argument("--season-type", default="regular", help="Season type (default: regular).")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    out_csv = Path(args.output_csv)

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        season = resolve_season_scope(conn, args.season, args.season_type)
        row_count = build_feature_table(conn, season, args.season_type)
        csv_rows, csv_cols = export_csv(conn, out_csv)
        conn.commit()

    print(f"season={season}, season_type={args.season_type}")
    print(f"team_feature_base rows={row_count}")
    print(f"csv={out_csv} rows={csv_rows} cols={csv_cols}")


if __name__ == "__main__":
    main()
