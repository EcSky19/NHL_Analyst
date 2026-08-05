# NFL prediction model project summary

Generated: 2026-08-05

## Bottom line

The NFL work in this repository is built from real nflverse data and is deliberately evaluated against the betting market, not against a trivial 50% baseline. The central result is clear: **team/EPA/QB features do not add detectable value beyond the closing market** on the common walk-forward sample. The practical straight-up ceiling is roughly **66%-67%**, and **70% is not an achievable target from these inputs** because it would require beating closing moneyline favorites by about **3.4 percentage points**.

The positive result is narrower but real: a market-free model using Elo, EPA, and QB signal reached **63.98%** on the same common sample, within about **2.3 pp** of Vegas without using market data.

Final strict-holdout numbers, if produced separately, belong in `data\reports\nfl_model_results.md`. This summary does not invent them.

## Data sources and database

Primary source: nflverse data from GitHub, especially `nfldata` games and `nflverse-data` play-by-play/team/player weekly releases. The database is local-only and intentionally ignored by git:

- `data\nfl\nfl_research.db`
- `games`: **7,548** real games, seasons **1999-2026**.
- Real Vegas moneylines: **72.77%** coverage.
- Real spreads and totals: **100%** coverage in the source games table.
- Future/unplayed rows: **272**, flagged and excluded from training/evaluation.
- Ties: **15**, with `home_win = NULL` instead of silently coercing them to either side.
- `nfl_team_week_advanced`: **8,726** rows, seasons **2010-2025**, including EPA/play, success rates, and turnover rates from play-by-play.
- `nfl_qb_week_stats`: **9,874** rows of QB EPA/CPOE and related weekly production.
- `nfl_features`: **4,363** played non-preseason games from 2010 onward with **274** columns.

The ingestion reports state the core integrity rule explicitly: no synthetic, simulated, randomly generated, or silently imputed NFL data was created.

## Feature set

Feature families in `nfl_features` include:

- Pregame Elo and Elo differential with neutral-site-aware home-field adjustment.
- Rolling team EPA, pass/rush EPA, success rates, third-down/red-zone rates, and turnover rates.
- QB rolling EPA/CPOE, starter-change flags, and prior-start proxies.
- Situational variables: rest, short weeks, byes, Thursday games, division games, roof/weather, and travel timezone burden.
- Market columns: spread, total, moneylines, and no-vig implied probabilities.

Market columns are real nflverse market data here, not synthetic proxies. They are explicitly separable so models can be run with and without the market.

## Leakage and holdout safeguards

The NFL workflow was designed in response to the earlier NHL data-integrity failure in this repository, where reported 62.04% accuracy collapsed to about 56.8% after fabricated seasons and circular synthetic market proxies were audited.

Safeguards now used for NFL:

- All data must be traceable to nflverse or recorded as unavailable.
- Market data is real and kept separate from team/EPA/QB features.
- Ties and unplayed games are excluded from binary winner accuracy rather than coerced.
- Strict 2024-2025 holdout seasons are gated behind the explicit unlock token `I_UNDERSTAND_THIS_TOUCHES_NFL_HOLDOUT_ONCE`.
- Leakage verification is empirical: source-date checks found **0** rolling/QB source-date violations, forbidden score columns were absent, and the feature build passed the leakage audit.

## Baselines

From `data\reports\nfl_baselines_and_methodology.md`, using played regular-season games with ties skipped:

| Baseline | Games | Accuracy | Wilson 95% CI |
|---|---:|---:|---:|
| Always pick home | 6,952 | 56.17% | 55.00%-57.33% |
| Vegas moneyline favorite | 5,025 | 66.59% | 65.27%-67.88% |
| Spread-implied favorite | 6,922 | 66.66% | 65.54%-67.76% |

Home field has declined over time. It was commonly around **57%-61%** in 1999-2003, exactly **50.00%** in the 2020 empty-stadium season, and roughly **53%-56%** in 2023-2025.

## Market-ceiling test

From `data\reports\nfl_market_signal_analysis.md`, on the common 2014-2025 walk-forward sample:

| Model | Games | Accuracy | Log loss |
|---|---:|---:|---:|
| Market only | 3,140 | 66.24% | 0.6112 |
| Team/EPA/QB only, no market | 3,140 | 63.98% | 0.6305 |
| Market + team features | 3,140 | 66.34% | 0.6154 |

Adding team features to the market improved accuracy by only **+0.10 pp**, with an approximate paired 95% CI of **-0.79 pp to +0.99 pp**. That is below the full-sample detectable threshold, and log loss worsened. The market calibration bucket MAE was **1.32%**, and pre-registered slice tests found no reliable exploitable systematic bias.

Interpretation: the market already captures most available pregame signal. The team-only model is useful football signal, but it does not reliably identify the market's errors.

## Noise floor

NFL samples are small. A single regular season cannot support strong claims about small accuracy differences.

| Sample | Games | Minimum detectable difference |
|---|---:|---:|
| One recent regular season | 271 | 7.92 pp |
| Three recent regular seasons | 815 | 4.57 pp |
| Full 2002-present regular-season era | 6,208 | 1.65 pp |

Practical implication: one season cannot distinguish a 60% model from a 68% model with confidence. Even over three seasons, a few percentage points can easily be noise.

## Direct answer on 70%

Do not read this project as a path to 70% NFL straight-up accuracy. The clean market baseline is about **66%-67%**. Getting to 70% would mean beating the closing market by roughly **3.4 pp**, which is much larger than the measured +0.10 pp team-feature increment and larger than anything supported by the residual-bias tests.

NFL games are more predictable than NHL games in this repository, but 70% still sits above the practical ceiling.

## Main files

- `scripts\nfl\ingest_nfl_games.py`
- `scripts\nfl\ingest_advanced_nfl_stats.py`
- `scripts\nfl\build_nfl_features.py`
- `scripts\nfl\evaluation_harness.py`
- `scripts\nfl\nfl_market_signal_analysis.py`
- `data\reports\nfl_ingestion_report.md`
- `data\reports\nfl_advanced_stats_ingestion.md`
- `data\reports\nfl_feature_engineering.md`
- `data\reports\nfl_baselines_and_methodology.md`
- `data\reports\nfl_market_signal_analysis.md`
- `data\reports\nfl_model_results.md` if generated by the holdout run
