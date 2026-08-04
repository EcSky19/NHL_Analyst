# NHL Research Storage Schema

This database (`data\processed\nhl_research.db`) is a reusable local store for NHL research outputs from multiple APIs.

## Tables

### teams
- **PK:** `team_id`
- **Natural dedupe key:** `UNIQUE(source, external_team_id)`
- Stores team identity and source-specific team IDs.

### team_stats
- **PK:** `team_stat_id`
- **FKs:** `team_id -> teams.team_id`, `snapshot_id -> api_snapshots.snapshot_id`
- **Dedupe key:** `UNIQUE(team_id, season, season_type, metric_name, source_api)`
- Stores season/team-level metrics in normalized metric-name/value form.

### players
- **PK:** `player_id`
- **FK:** `team_id -> teams.team_id`
- **Natural dedupe key:** `UNIQUE(source, external_player_id)`
- Stores player identity and optional current team linkage.

### player_stats
- **PK:** `player_stat_id`
- **FKs:** `player_id -> players.player_id`, `team_id -> teams.team_id`, `snapshot_id -> api_snapshots.snapshot_id`
- **Dedupe key:** `UNIQUE(player_id, season, season_type, metric_name, source_api)`
- Stores normalized player metric rows by season.

### shot_threshold_stats
- **PK:** `shot_threshold_stat_id`
- **FKs:** `team_id -> teams.team_id`, `snapshot_id -> api_snapshots.snapshot_id`
- **Threshold constraint:** `threshold_label IN ('<=5','<=10','<=15')`
- **Dedupe key:** `UNIQUE(team_id, season, season_type, threshold_label, event_type, source_api)`
- Stores threshold-based shot analytics (counts/rates).

### api_snapshots
- **PK:** `snapshot_id`
- Tracks API retrieval metadata (`source_api`, `endpoint`, `retrieved_at`, `file_path`, `file_hash`) for lineage/reproducibility.
- **Dedupe key:** `UNIQUE(source_api, endpoint, retrieved_at, file_hash)`

## Notes for downstream todos
- Use `api_snapshots` first when persisting raw pull metadata, then reference `snapshot_id` from stat rows.
- Foreign keys are enabled and indexed for robust joins.
- Schema is idempotent (`CREATE TABLE/INDEX IF NOT EXISTS`) and safe to re-run.
