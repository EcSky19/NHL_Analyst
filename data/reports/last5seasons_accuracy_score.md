# Last 5 Seasons Model Accuracy

- **Overall accuracy:** **57.8811%** (0.578811)
- **Total games evaluated:** **6,560**

## Accuracy by season
- 2021-2022: **61.8140%** (0.618140)
- 2022-2023: **58.9177%** (0.589177)
- 2023-2024: **58.5366%** (0.585366)
- 2024-2025: **56.5549%** (0.565549)
- 2025-2026: **53.5823%** (0.535823)

## Methodology
Pregame-only, strict walk-forward backtest with no leakage: each game prediction is generated before puck drop using only data available at that time.

## Caveats
Results are for the `historical_games_last5` regular-season sample only; season-to-season variance is material, and backtest accuracy does not guarantee future or postseason performance.
