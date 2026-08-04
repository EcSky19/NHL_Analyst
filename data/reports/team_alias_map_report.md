# Team Alias Map Build Report

- Generated at: 2026-08-03T11:44:25
- Canonical source: `data\processed\current_nhl_32_teams.csv`
- Alias source: `teams` table in `data\processed\nhl_research.db` (`source` values from active API rows)
- Output CSV: `data\processed\team_alias_map.csv`
- Output table: `team_alias_map` in `data\processed\nhl_research.db`

## Validation
- Canonical teams expected: 32
- Rows written: 32
- Teams with non-empty alias abbrev + alias name mappings: 32
- Missing mappings: []

## Notes
- Mapping is deterministic (sorted by `canonical_abbrev`; aliases sorted alphabetically and `|`-delimited).
- UTA row includes historical ARI/Arizona Coyotes aliases for cross-season joins.
- MTL row includes accented/non-accented name variants.
