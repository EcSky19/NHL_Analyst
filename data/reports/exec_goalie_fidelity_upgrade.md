# Exec: Goalie fidelity upgrade

## Scope completed
- Upgraded ingestion schema/logic for deterministic starter-goalie inference and certainty metadata.
- Upgraded roster feature build to emit goalie starter certainty + starter-vs-backup quality differential fields.
- Rebuilt roster-aware feature artifacts (SQLite table + CSV) with strict pregame ordering preserved.

## Rebuild outputs
- SQLite table: `backtest_features_last5_roster`
- CSV: `data/processed/backtest_features_last5_roster.csv`

## Starter-goalie profile (historical_game_rosters)
- Team-games: 13120
- Exactly one starter goalie: 13120 (100.00%)
- Zero starter goalies: 0 (0.00%)
- Multiple starter goalies: 0 (0.00%)

## Goalie fidelity feature coverage
| column | non_null_count | total_rows | coverage_pct |
|---|---:|---:|---:|
| `home_pregame_goalie_starter_certainty` | 6560 | 6560 | 100.00% |
| `away_pregame_goalie_starter_certainty` | 6560 | 6560 | 100.00% |
| `home_pregame_goalie_starter_quality_gap_last5` | 387 | 6560 | 5.90% |
| `away_pregame_goalie_starter_quality_gap_last5` | 384 | 6560 | 5.85% |
| `home_pregame_goalie_starter_quality_gap_last10` | 387 | 6560 | 5.90% |
| `away_pregame_goalie_starter_quality_gap_last10` | 384 | 6560 | 5.85% |
| `delta_pregame_goalie_starter_certainty_home_minus_away` | 6560 | 6560 | 100.00% |
| `delta_pregame_goalie_starter_quality_gap_last5_home_minus_away` | 21 | 6560 | 0.32% |
| `delta_pregame_goalie_starter_quality_gap_last10_home_minus_away` | 21 | 6560 | 0.32% |

## Artifacts
- `data/processed/execution_plan/phase2/goalie_feature_coverage.csv`
- `data/processed/execution_plan/phase2/goalie_starter_counts_by_season.csv`
- `data/processed/execution_plan/phase2/goalie_starter_diagnostics.json`

## Pregame/determinism guardrail
- Player/team histories are read before each game row is emitted.
- Current game stats update history only after feature emission, preserving strict pregame logic.
