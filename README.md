# Sports Analytics: Multi-Sport Prediction and Stats

This repository now contains two pregame sports-modeling research tracks: the original NHL work and a new NFL prediction project. The common theme is honest out-of-sample evaluation, explicit data provenance, and resisting headline accuracy claims that do not survive audit.

## NHL project

The NHL project builds and evaluates pregame win-probability models from historical game, team, roster, goalie, schedule, and matchup features. It is useful for researching modest predictive edges, calibration, confidence tiers, and model failure modes in a high-variance sport.

## Honest current benchmark

Previous headline accuracy claims of **61.66%**, **61.89%**, and **62.04%** are retracted. They should not be used as evidence of model quality.

The corrected benchmark is a real-only, no-market expanding walk-forward evaluation over 5,248 games:

| Test season | Games | Accuracy |
|---|---:|---:|
| 2022-23 | 1,312 | 59.07% |
| 2023-24 | 1,312 | 58.23% |
| 2024-25 | 1,312 | 56.78% |
| 2025-26 | 1,312 | 53.20% |
| **Overall** | **5,248** | **56.82%** |

This is a real but modest edge over an always-pick-home baseline of roughly 52-54%, not a 60%+ all-games system.

Primary audit: `data\reports\data_integrity_audit.md`.

## Confidence tiers

Restricting predictions to high-confidence games raises accuracy, but **no tier clears 70% with statistical confidence** once measured on an adequate sample.

Expanded walk-forward evaluation on real data (largest available sample):

| Minimum confidence | Games | Coverage | Accuracy | Wilson 95% CI |
|---|---:|---:|---:|---:|
| >=0.55 | 7,454 | 65.31% | 60.46% | 59.35%-61.57% |
| >=0.60 | 4,093 | 35.86% | 62.86% | 61.37%-64.33% |
| >=0.65 | 1,850 | 16.21% | 67.68% | 65.51%-69.77% |
| >=0.70 | 623 | 5.46% | 71.59% | 67.92%-74.99% |
| >=0.75 | 157 | 1.38% | 73.89% | 66.50%-80.13% |

An earlier verification on a smaller sample reported 77.40% at `>=0.70` (177 games, CI 70.70%-82.94%) and treated it as a defensible 70%+ result. **That finding did not replicate.** With 623 games instead of 177, the same tier falls to 71.59% and its confidence interval lower bound drops to 67.92%, below the 70% bar. The original figure was small-sample optimism.

Honest reading: the highest-confidence tier lands somewhere around **70-72%**, but the data does not support claiming it reliably exceeds 70%. Tiers above `>=0.70` have too few games to distinguish from noise.

Primary verification: `data\reports\confidence_tiers_clean_verification.md` and `data\reports\real_expanded_retrain_results.md`.

## Negative results and improvement discipline

Failed or rejected improvement attempts are documented intentionally, not hidden. See `docs\model_experiments.md` for the latest model-improvement findings, including negative NBA and NHL results and the newly closed NBA recent per-game coverage gap.

## Data integrity incident

A 2026-08-05 audit found two major contamination sources:

1. `scripts\generate_synthetic_historical_data.py` fabricated the 2015-16, 2016-17, and 2017-18 seasons using seeded random generation. Quarantine scope: 1,406 fabricated game/feature rows, 59,052 roster/stat rows, and 2,812 team pregame rows.
2. `scripts\fetch_market_signals.py` did not fetch real betting odds. It synthesized "market" and "Vegas" features from pregame statistics already available to the model, including season points percentage, last-10 percentage, goal differential, and home/road splits. Any measured "market lift" was circular.

The contaminated rows and artifacts were marked rather than deleted. Honest evaluation must exclude synthetic rows and market proxy features.

## What is genuinely true

- Honest all-games accuracy is about **56.8%** on the current clean benchmark.
- The model beats simple baselines, but the edge is modest.
- High-confidence games are genuinely more predictable, but **no confidence tier reliably reaches 70%**. The best tier sits near 71% with a confidence interval spanning 68-75%.
- About **6,084 genuinely real historical games from 2015-2020** have now been ingested from the NHL API with era-correct team handling: Arizona present, Utah/Seattle absent, and Vegas beginning in 2017-18.
- **More real history did not improve accuracy.** Retraining on the expanded real dataset produced 56.82%, identical to the prior benchmark (+0.00 pp). Recent-seasons-only scored 56.90% and recency-weighted full history 56.73% — all within noise. See `data\reports\real_expanded_retrain_results.md`. This suggests the model is limited by signal quality and inherent NHL randomness, not by training volume.

## What is not true

- This repo does **not** currently demonstrate 61.66%, 61.89%, or 62.04% honest all-games accuracy.
- This repo does **not** contain real historical Vegas odds in the synthetic market artifacts.
- This repo does **not** show that 70% accuracy is attainable across all NHL games.
- This repo does **not** show that 70% accuracy is reliably attainable even on a high-confidence subset. The earlier 77.40% claim failed to replicate on a larger sample.

Realistic context: published NHL prediction models and market favorites typically land around the low 60s at best, with Vegas closing favorites around 60%. NHL outcomes have high game-to-game variance, so 70% all-games accuracy is not a realistic target for a pregame model.


## NFL project

The NFL project uses real nflverse data, including real betting-market fields, to test how far pregame team/EPA/QB signal can go.

Key artifacts:

- `data\reports\nfl_project_summary.md` — complete NFL overview and honest interpretation.
- `data\reports\nfl_ingestion_report.md` — games/provenance report.
- `data\reports\nfl_advanced_stats_ingestion.md` — EPA/QB/team-week ingestion report.
- `data\reports\nfl_feature_engineering.md` — feature table and leakage checks.
- `data\reports\nfl_baselines_and_methodology.md` — baselines, holdout rules, and noise floor.
- `data\reports\nfl_market_signal_analysis.md` — market-ceiling and residual-signal tests.

NFL data summary:

- `games`: **7,548** real nflverse games, seasons **1999-2026**.
- Real Vegas moneylines: **72.77%** coverage; real spreads/totals: **100%** coverage.
- Future/unplayed games: **272**, flagged and excluded.
- Ties: **15**, with winner label set to NULL rather than coerced.
- Advanced team-week data: **8,726** rows, seasons **2010-2025**.
- QB weekly stats: **9,874** rows.
- Feature table: **4,363** played non-preseason games, **274** columns, leakage verification passed with **0** source-date violations.

NFL baselines and model findings:

| Reference / model | Accuracy | Notes |
|---|---:|---|
| Always pick home | 56.17% | Wilson 55.00%-57.33% |
| Vegas moneyline favorite | 66.59% | Wilson 65.27%-67.88%, n=5,025 |
| Market only walk-forward | 66.24% | log loss 0.6112 |
| Team/EPA/QB only, no market | 63.98% | log loss 0.6305 |
| Market + team features | 66.34% | log loss worsened to 0.6154 |

Central NFL finding: team/EPA/QB features add **no detectable value** beyond the betting market on the common walk-forward sample. The market + team accuracy gain was only **+0.10 percentage points** with a paired CI of **-0.79 to +0.99 pp**, and log loss worsened. The market is well calibrated, with bucket MAE **1.32%**, and no pre-registered market-bias slice produced a reliable exploitable edge.

The realistic NFL straight-up ceiling here is therefore about **66%-67%**. A durable **70%** result is not supported; it would require beating the closing market by roughly **3.4 pp**. The genuinely positive result is that a market-free model reached **63.98%** using Elo, EPA, and QB signal, within about **2.3 pp** of Vegas.

Home-field advantage is also time-varying: it was often around **57%-61%** in 1999-2003, fell to exactly **50.00%** in the 2020 empty-stadium season, and has been roughly **53%-56%** in 2023-2025.

Noise-floor caution: one modern NFL season has only about 272 games. The minimum detectable difference is about **7.92 pp** for one season, **4.57 pp** for three seasons, and **1.65 pp** for the full 2002-present regular-season era. Small one-season wins over a baseline are not evidence of a better model.

## Cross-sport lesson

NFL games are substantially more predictable than NHL games in this repository: the NFL market sits around **66%-67%**, while the corrected NHL all-games benchmark is about **56.8%**. But **70% is out of reach in both projects** for different versions of the same reason: it sits above the practical ceiling supported by clean out-of-sample evidence.

The earlier NHL failure is the reason the NFL project is explicit about provenance, synthetic-data prohibition, market-feature separation, holdout locking, and empirical leakage checks. In NHL, fabricated seasons and circular fake market features invalidated 61%-62% headline claims. In NFL, the betting market fields are real, but they mostly define the ceiling rather than create an exploitable path beyond it.

## Reading old reports

Older reports are retained for history. Reports with invalidated accuracy claims or market-feature interpretations now carry correction notices at the top. When in doubt, prefer:

- `data\reports\data_integrity_audit.md`
- `data\reports\confidence_tiers_clean_verification.md`

## Web UI

The repository includes a FastAPI + vanilla-JS web UI for browsing NHL, NFL, NBA, and MLB standings, team summaries, player leaders, schedules, live games when an upstream source reports them, and honestly-labelled model predictions. It uses one shared response envelope and one shared standings table shape across all four leagues so the frontend can render them consistently.

### Quickstart

```powershell
python run_ui.py
```

The launcher reads defaults from `app.config.settings`, prints the local URL, and accepts:

```powershell
python run_ui.py --host 127.0.0.1 --port 8031 --reload
```

If the selected port is already in use, choose another port with `--port`.

### API endpoints

All API routes return HTTP 200 with `{ ok, data, error, meta }`, including validation errors.

| Path | Purpose |
|---|---|
| `/api/health` | App, router, database, and season-state health |
| `/api/meta/seasons` | Available seasons per league |
| `/api/nhl/standings` | NHL standings for the current or requested season |
| `/api/nhl/teams` and `/api/nhl/teams/{abbrev}` | NHL team summaries and detail |
| `/api/nhl/players` | NHL player leaders (`team`, `stat`, `limit`) |
| `/api/nhl/schedule` | NHL schedule by optional `date=YYYY-MM-DD` |
| `/api/nfl/standings` | NFL standings for the current or requested season |
| `/api/nfl/teams` and `/api/nfl/teams/{abbrev}` | NFL team summaries and detail |
| `/api/nfl/players` | NFL QB leaders (`team`, `stat`, `limit`) |
| `/api/nfl/schedule` | NFL schedule by `season` and optional `week` |
| `/api/nfl/live` | NFL games currently in progress when ESPN reports them |
| `/api/nba/standings` | NBA standings for the current or requested season |
| `/api/nba/teams` and `/api/nba/teams/{abbrev}` | NBA team summaries and detail |
| `/api/nba/players` | NBA player leaders (`team`, `stat`, `limit`) |
| `/api/nba/schedule` | NBA schedule by optional `date=YYYY-MM-DD` |
| `/api/nba/live` | NBA games currently in progress when ESPN reports them |
| `/api/mlb/standings` | MLB standings for the current or requested season |
| `/api/mlb/teams` and `/api/mlb/teams/{abbrev}` | MLB team summaries and detail |
| `/api/mlb/players` | MLB player leaders (`team`, `stat`, `group`, `limit`) |
| `/api/mlb/schedule` | MLB schedule by optional `date=YYYY-MM-DD` |
| `/api/mlb/live` | MLB games currently in progress from MLB StatsAPI/ESPN-normalized rows |
| `/api/predictions/nhl` | NHL prediction rows when real fixtures are available |
| `/api/predictions/nfl` | NFL prediction rows when real fixtures are available |
| `/api/predictions/nba` | NBA prediction rows when real fixtures are available |
| `/api/predictions/mlb` | MLB prediction rows when real fixtures are available |
| `/api/predictions/matchup` | Hypothetical matchup prediction with `league`, `home`, and `away` |

### Caching and refresh

Backend fetches use the disk-backed cache in `data\ui_cache\`: standings refresh about every 5 minutes, schedules every 2 minutes, stats every 15 minutes, and predictions every 10 minutes. If an upstream refresh fails but a cached copy exists, the API serves the stale cached payload with `meta.stale: true` instead of blanking the UI. The frontend auto-refreshes data and surfaces stale/offseason notes from `meta`.

### Live win probability

Live game rows expose a `win_probability` object with the modelled chance the **home** team wins, given the current score and how much of the game is left. Models are trained on in-game snapshots derived from ESPN play-by-play (~780k snapshots across 2,069 games) and are split **by game**, never by snapshot, so no game appears in both train and test.

The cross-league model selection policy and verification commands are documented in `docs\live_wp\README.md`.

Measured on a held-out season, alongside ESPN's own published win-probability curve as an independent professional benchmark:

| League | Ours (Brier) | Ours (log loss) | Analytic baseline (Brier) | ESPN (Brier) |
| --- | ---: | ---: | ---: | ---: |
| NBA | 0.167947 | 0.491963 | 0.166237 | **0.157319** |
| NFL | 0.163903 | 0.479367 | 0.163775 | **0.145762** |
| MLB | **0.154305** | **0.462951** | 0.155233 | 0.153735 (partial coverage) |
| NHL | 0.175316 | 0.515720 | *is* the baseline | none published |

Read that honestly:

- **ESPN's model is better than ours in every league where it publishes one.** We do not match it, and we are not claiming to. The gap is largest in the NFL.
- **MLB is our one clear success**: it beats the analytic baseline on both Brier and log loss, and lands within 0.001 Brier of ESPN on the snapshots ESPN covers.
- Our NBA and NFL models beat the two-parameter analytic baseline on log loss and calibration but **lose to it on Brier** — a genuinely mixed result, not a win.
- The NFL model additionally consumes ESPN's **situational** state (possession, down, distance, field position). On the situational snapshot set that improves it from 0.161824/0.474385 to 0.160183/0.469577, closing **11.8%** of the log-loss gap to ESPN. Situation is not the whole story: our earlier hypothesis that possession/down/distance explained most of the ESPN gap was measurably wrong.
- The table above is measured on the score/clock-only snapshot set, so all four leagues stay comparable. NFL scores better there than the table suggests once situation is available.
- **NHL ships the analytic baseline itself**, because seven learned models across two rounds all failed to beat it, and the best of them was additionally non-monotone in margin (it rated a 4-goal lead below a 3-goal lead). See `docs\live_wp\nhl.md`.
- ESPN publishes **no** win-probability curve for NHL, so that league has no external benchmark at all.
- Every shipped model is required to be **monotone in both margin and time**: more lead is never worse, and a lead never loses value as the clock runs out. The time half of that rule was added late and caught NFL and MLB already violating it; both were refit and came out slightly more accurate, not less.
- We know part of *why* ESPN wins the NFL: their model sees possession, down, distance and field position, and ours sees only score and clock. Measured on data we harvested to test exactly this, adding that situational state improves our NFL Brier from 0.170280 to 0.166505 — real, but it closes only about a sixth of the gap to ESPN, so situational blindness is not the whole explanation. See `docs\live_wp\nfl_situation_data.md`.

These are model estimates, not betting lines, and they are not accurate enough to bet on. If a league has no validated artifact the API returns `available: false` with a reason and the UI shows "unavailable" rather than inventing a number. Per-league validation details, including failed experiments, are in `docs\live_wp\{league}.md`.

### Season-state behavior

As of 2026-08-05, NHL and NBA are between seasons, NFL is entering preseason, and MLB is in its regular season. Endpoints include `meta.season_state` so the UI can display offseason/preseason/live-season banners rather than implying the wrong freshness.

### Tests

```powershell
python -m pytest tests\ui -q
```

Network-sensitive tests are marked `network` and skip gracefully when live upstream data is unavailable. The suite also guards the frozen envelope, shared standings keys, cache stale fallback, static assets, edge-case errors, and prediction honesty bounds.

### Prediction honesty

Predictions are modest statistical estimates, not betting advice. NHL predictions must show the audited 56.82% model accuracy, while NFL predictions must stay within the audited 66.11% market-free and 67.40% full-model figures. Probabilities are bounded and labelled with disclaimers so retracted overconfidence claims do not creep back into the UI.

## NBA project

NBA coverage is documented separately from the NHL/NFL honesty disclosures above; those retractions remain in force and unchanged.

NBA data:

- Historical per-game data comes from hoopR (sportsdataverse), seasons 2001-02 through 2022-23: 28,222 games, 56,136 team box rows, 739,524 player box rows, and 30 teams. Recent per-game coverage is now supplemented by `data\nba\nba_recent_games.db`, with 1,230 games in each of 2023-24, 2024-25, and 2025-26.
- Current standings for 2023-24, 2024-25, and 2025-26 are scraped from basketball-reference `/leagues/` (robots.txt-permitted; Crawl-delay 3 honored at 3.1s) and cross-validated against Wikipedia. Wins equal losses at 1,230 per season.
- basketball-reference year convention uses the season end year, so `NBA_2026` is the 2025-26 season.

NBA model accuracy must be stated with its baselines:

| Evaluation | Result |
|---|---:|
| Frozen holdout | 62.52% on 1,174 games (2023 season), Wilson 95% CI 59.72%-65.25% |
| Always-home baseline | 58.43% |
| Pure Elo baseline | 62.95% |

The headline NBA accuracy is the frozen-holdout **62.52%**, not the walk-forward development figure. The model is **-0.43 percentage points versus pure Elo**, so it does **not** beat a simple Elo baseline, and the gap sits well inside the confidence interval. No betting-market baseline exists for NBA.

The NBA blend experiment reinforces that point: logistic stacking reached **62.78%** on the same 1,174-game frozen holdout, behind pure Elo's **62.95%** by 0.17 percentage points. Its useful result was probability quality, not accuracy: best log loss (**0.6440**) and best Brier (**0.2261**). No NBA blend serving artifact was promoted.

## MLB project

MLB uses the official MLB StatsAPI (`statsapi.mlb.com/api/v1`), which is free and public and requires no API key.

MLB data:

- Historical ingest: 32,906 games.
- Regular-season completed counts for 2015-2026: 2,429, 2,428, 2,430, 2,431, 2,429, 898, 2,429, 2,430, 2,430, 2,429, 2,430, 1,709.
- 2020 is COVID-shortened (898 completed games); 2026 is in progress (1,709 completed as of 2026-08-05).
- Doubleheaders are preserved and keyed by `gamePk` (verified: 2026-07-29 ATL at NYM, gamePks 823596 and 823598).
- Spot-check: 2025 World Series Game 7, LAD 5 at TOR 4.
- MLB is currently mid-season and was the only league with live games observed on 2026-08-05 (games were observed transitioning Warmup -> In Progress).

### MLB model (fourth honest negative)

An MLB win model is now trained and served, replacing the earlier "no trained model" state. It **does not beat a plain Elo baseline** and is published on that basis:

- Model accuracy: **55.72%** (Wilson 95% CI 53.74%-57.68%) on a frozen 2,430-game 2025 holdout.
- Pure Elo baseline: **56.13%**. Always-pick-home: **54.28%**.
- The 2026 season is deliberately excluded from evaluation because it is still in progress.

As with NBA, the API reports a `baseline_accuracy` that is **higher** than `model_accuracy`. That is intentional and correct, not a display bug.

Predicted probabilities span roughly 0.40-0.66 across ordered team pairs, with the best-vs-worst matchup (MIL 70-43 at home vs LAA 43-70) at **0.662**. This narrow range is the correct shape for baseball, where even a dominant team beats a poor one only modestly. Widening it would recreate the original calibration defect described in the retraction above. A sweep of 132 ordered matchups returned 132 distinct values with none pinned at the clamp bounds.

Known limitation, now measured rather than merely noted: the served model uses **no pregame starting-pitcher information**. A pitcher-feature variant was built and evaluated on the same holdout (starters available for 2,425 of 2,430 games). It reached **55.84%** — better probability quality than any other MLB model here (log loss 0.6795, Brier 0.2434, both beating Elo) but still **short of Elo's 56.13%** on accuracy, and ahead of the served model by only 3 games out of 2,430. It was **not promoted to serving**: the margin is noise-scale, and starting pitchers are not known far enough in advance to serve future matchups reliably. See `docs/model_experiments.md`.

## External API caveats

The shared ESPN client uses ESPN's `site.web.api.espn.com` scoreboard API with a browser `User-Agent`, one request per slate. The similar `site.api.espn.com` host returned HTTP 403 even with a browser `User-Agent`; that earlier host mix-up caused the now-corrected conclusion that ESPN was unavailable. NBA source checks also found `stats.nba.com` timing out, `cdn.nba.com` returning 403, and balldontlie returning 401.

ESPN scoreboard validation measured on 2026-08-05:

- NFL 2025-11-01..2025-11-10 reconciled against this repo's databases with **27/27 exact score matches**.
- NBA 2025-01-10..2025-01-20 reconciled with **79/79 exact score matches**.
- ESPN also listed three postponed NBA games on 2025-01-11 that this repo's stored data omits.
- ESPN listed 17 NFL preseason events from 2026-08-05 through 2026-08-15; nflverse's regular-season structure cannot provide those preseason games.

Maintainer gotchas: ESPN reports `score: "0"` for games that never happened, including scheduled and postponed games, so unplayed scores must be nulled. `dates=` filters by US Eastern date, not UTC; the Hall of Fame game at `2026-08-07T00:00Z` appears under `dates=20260806`. Calling the scoreboard with no `dates` returns the next season. ESPN carries All-Star exhibitions on the normal slate with `season.type` still 2, so filter them via `competitions[0].type.abbreviation == "ALLSTAR"`. ESPN team abbreviations differ from this repo's abbreviations for NBA (`GS`, `NO`, `NY`, `SA`, `UTAH`, `WSH`) and NFL (`LAR`, `WSH`).

## Live games and week schedules

All four leagues expose two endpoints, specified in `docs/ui_api_contract.md`:

- `GET /api/{league}/live` — games currently in progress
- `GET /api/{league}/schedule/week?start=YYYY-MM-DD&days=7` — a date window (1-14 days)

NFL additionally accepts `?week=N`, since its natural unit is the game week rather than
seven calendar days.

Every league emits the same shared keys (`game_id`, `league`, `game_date`,
`start_time_utc`, `home`, `away`, `home_name`, `away_name`, `home_score`, `away_score`,
`status`, `detailed_status`, `venue`), and `status` is normalized to exactly
`scheduled`, `live`, `final` or `postponed`. Raw upstream state is preserved in
`detailed_status`. Scores for unplayed games are `null`, never `0`.

### What each league can actually do

This differs by league, and the differences are real limitations rather than bugs:

| league | week schedule | true live in-game state |
| --- | --- | --- |
| MLB | yes | **yes** — StatsAPI, with inning, balls, strikes, outs and runners |
| NHL | yes | yes, when the season is running |
| NBA | yes | yes via ESPN scoreboard schema, but not observed live on 2026-08-05 because the NBA was in offseason |
| NFL | yes, including ESPN preseason coverage | yes via ESPN scoreboard schema, but not observed live on 2026-08-05 because the first preseason game had not started |

NBA and NFL live support is sourced from ESPN, not nflverse. The live row shape was validated structurally and against ESPN's MLB feed, whose schema matched and had two genuinely in-progress games cross-checked against MLB StatsAPI. No NBA or NFL game was observed live on 2026-08-05, so do not claim production-observed NBA/NFL live rendering from that date.

### Empty is a correct answer

As of 2026-08-05 the NHL and NBA are in their offseason, the first NFL preseason game is about 20 hours away, and MLB is active. Empty live lists remain correct when `meta.empty_reason` truthfully says no games are currently in progress. Do not approximate or simulate live state.

### Notes for future maintainers

Two upstream behaviours caused real bugs during development and are worth knowing:

- **MLB evening games cross midnight UTC.** Games with a 7pm ET or later first pitch sit
  on the previous UTC date's slate. Querying only "today in UTC" returned zero live games
  while nine were actually in progress. The live path queries a multi-day window.
- **A postponed MLB game keeps its `gamePk` and appears on two slates** — its original
  date as `Postponed` and its makeup date as `Final`. Emitting both produced duplicate
  `game_id`s that looked like a team playing twice in one day. Superseded postponed rows
  are dropped. This is distinct from doubleheaders, which are genuinely separate games
  with different `gamePk`s and are preserved.
- **NHL `schedule.nextStartDate` is a pagination cursor, not a game date.** Using it
  advertised a "next game" on 2026-09-17, a day with zero games; the true next date was
  2026-09-19. Both endpoints now scan forward for the first day with at least one game.
