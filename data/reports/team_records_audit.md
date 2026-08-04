# Team Records Audit

- Generated at: 2026-08-03T11:38:23
- Database: `data\processed\nhl_research.db`
- Total rows in `teams`: 96
- Distinct deduped teams (abbreviation/name matching): 32
- Duplicate real-world teams across sources: 32

## Counts by source

- api.nhle.com/stats/rest: 32
- espn: 32
- nhl_api: 32

## Duplicate real-world teams across sources

Rows below have `source_count > 1` after normalization and abbreviation/name matching.

| cluster_id | canonical_name | canonical_abbreviation | source_count | row_count | sources |
|---:|---|---|---:|---:|---|
| 1 | Anaheim Ducks | ANA | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 2 | Boston Bruins | BOS | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 3 | Buffalo Sabres | BUF | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 4 | Calgary Flames | CGY | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 5 | Carolina Hurricanes | CAR | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 6 | Chicago Blackhawks | CHI | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 7 | Colorado Avalanche | COL | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 8 | Columbus Blue Jackets | CBJ | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 9 | Dallas Stars | DAL | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 10 | Detroit Red Wings | DET | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 11 | Edmonton Oilers | EDM | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 12 | Florida Panthers | FLA | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 13 | Los Angeles Kings | LAK | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 14 | Minnesota Wild | MIN | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 15 | Montréal Canadiens | MTL | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 16 | Nashville Predators | NSH | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 17 | New Jersey Devils | NJD | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 18 | New York Islanders | NYI | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 19 | New York Rangers | NYR | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 20 | Ottawa Senators | OTT | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 21 | Philadelphia Flyers | PHI | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 22 | Pittsburgh Penguins | PIT | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 23 | San Jose Sharks | SJS | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 24 | Seattle Kraken | SEA | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 25 | St. Louis Blues | STL | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 26 | Tampa Bay Lightning | TBL | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 27 | Toronto Maple Leafs | TOR | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 28 | Utah Mammoth | UTA | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 29 | Vancouver Canucks | VAN | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 30 | Vegas Golden Knights | VGK | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 31 | Washington Capitals | WSH | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |
| 32 | Winnipeg Jets | WPG | 3 | 3 | api.nhle.com/stats/rest|espn|nhl_api |

## Artifact files

- `data\reports\team_rows_current.csv` (all current rows with normalization and cluster id)
- `data\reports\team_rows_deduped.csv` (normalized deduped team list)
