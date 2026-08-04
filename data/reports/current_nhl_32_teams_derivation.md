# Current NHL 32 Teams Derivation

- Generated at: 2026-08-03T11:39:08
- Source artifact: `data\processed\team_feature_base.csv`
- Method: filtered to latest `season` in source (`20252026`), selected (`season`, `team_id`, `team_abbreviation`, `team_name`), uppercased abbreviations, corrected Montréal encoding for `MTL`, deduplicated, sorted by abbreviation.

## Validation
- Row count: 32
- Distinct abbreviations: 32
- Distinct names: 32
- Expected-current-team check (32 known current NHL abbreviations): PASS
- Missing abbreviations vs expected set: []
- Unexpected extra abbreviations: []

## Output artifacts
- `data\processed\current_nhl_32_teams.csv`
- SQLite table: `current_nhl_32_teams` in `data\processed\nhl_research.db`
