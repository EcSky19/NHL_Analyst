# Model-improvement findings

This project treats negative findings as first-class results. Given the repository's history of retracted headline accuracy claims, documenting failed improvement attempts is the intended behavior: it prevents quiet overfitting, protects the frozen holdout protocol, and keeps serving claims tied to evidence.

## NBA blend experiment: probability-quality gain, not an accuracy win

Source report: `data\reports\nba_blend_results.md`. Supporting tables: `nba_blend_metrics` and `nba_blend_predictions` in `data\nba\nba_research.db`.

The pre-registered NBA blend used a frozen 2023 holdout of 1,174 games:

| Model | Accuracy | Wilson 95% CI | Log loss | Brier |
|---|---:|---:|---:|---:|
| pure_elo | 62.95% | 60.15%-65.66% | 0.6499 | 0.2280 |
| nba_model | 62.52% | 59.72%-65.25% | 0.6487 | 0.2285 |
| logistic_stack | 62.78% | 59.97%-65.50% | 0.6440 | 0.2261 |
| always_home | 58.43% | n/a | n/a | n/a |

Verdict: the logistic stack did **not** beat pure Elo on accuracy. It trailed Elo by 0.17 percentage points, comfortably inside the confidence interval.

The positive finding is narrower and should be stated only as probability quality: the blend had the best log loss, 0.6440, and the best Brier score, 0.2261, of all four evaluated approaches. That supports better-calibrated probabilities, not a defensible argmax accuracy win.

The methodology lesson is the important part. On development folds from 2009-2022, totaling 16,640 games, the stack beat Elo on accuracy, 66.46% versus 65.97%. That edge did not survive on the frozen holdout, illustrating why configuration must be frozen before touching holdout rows.

No serving artifact was promoted. Live NBA serving is unchanged.

## NHL improvement attempt: point estimate up, not accepted

Source report: `data\reports\nhl_improvement_results.md`. Supporting tables: `nhl_improved_predictions` and `nhl_improved_metrics` in `data\processed\nhl_research.db`.

The selected NHL model scored 58.61% on the frozen 2025-2026 holdout of 1,312 games, versus the current audited 56.82%. That point estimate is higher, but it is not evidence of a real improvement: the Wilson 95% CI is 55.93%-61.25%, and 56.82% sits inside that interval.

Synthetic data handling was verified before evaluation. All 1,406 synthetic rows were excluded, and every one of the 1,312 evaluated rows had `is_synthetic = 0`.

OT and shootout games were included as final-winner outcomes. This choice materially affects the number and should be stated whenever the result is cited.

The model was **not shipped** because the probability outputs are systematically overconfident:

| Bucket | Games | Avg predicted | Actual | Overconfidence |
|---|---:|---:|---:|---:|
| 0.70-0.80 | 92 | 0.7411 | 0.6630 | 7.8 pp |
| 0.60-0.70 | 308 | 0.6406 | 0.5812 | 5.9 pp |
| Mid bucket | 853 | 0.5045 | 0.4877 | 1.7 pp |

Probabilities ranged from 0.146 to 0.906, which is not defensible for a roughly 57%-59% hockey model. The live UI still reports the audited 56.82%, and serving was not changed.

A useful contrast: the NBA model also emits a wide probability range, but there it is empirically earned. On 20,274 out-of-sample NBA games, the `>=0.85` bucket predicted 0.8793 and actually hit 0.8787, with n=1,072. The surface symptom is similar, but the verdict is opposite because reliability data, not the range alone, decides whether probabilities are trustworthy.

## NBA per-game coverage gap closed

Source report: `data\reports\nba_recent_games_report.md`. Supporting database: `data\nba\nba_recent_games.db`.

Previously, NBA per-game data stopped at 2022-23 and only season aggregates existed after that. The recent-games database now contains 1,230 games for each of 2023-24, 2024-25, and 2025-26, scraped from Basketball-Reference with robots.txt permission and a 3.1-second delay honoring the site's crawl delay.

Integrity checks passed:

- Aggregating the new games into win-loss records reproduces all 90 rows in `nba_current_standings` exactly, with 0 mismatches.
- Home win rates are 54.3%, 54.4%, and 55.5%.
- There are no duplicate game IDs, self-games, ties, or null scores.

Future readers should note that in this database, `season` is the season end year as an integer. For example, `2024` means the 2023-24 NBA season.

## MLB starting-pitcher features: fifth honest negative

Source report: `data\reports\mlb_pitcher_model_results.md`. Script: `scripts\mlb\train_mlb_pitcher_model.py`.

The served MLB model names its own largest gap: it uses no pregame starting-pitcher
information. That gap was closed experimentally and measured on the same frozen
2,430-game 2025 holdout.

| model | accuracy | log loss | Brier |
| --- | --- | --- | --- |
| pitcher features | 0.5584 | **0.6795** | **0.2434** |
| served MLB model | 0.5572 | 0.6804 | 0.2438 |
| pure Elo | **0.5613** | 0.6875 | 0.2471 |
| always pick home | 0.5428 | 0.6896 | 0.2482 |

Starter assignments were available for 2,425 of 2,430 holdout games (99.79%), so the
result is not an artifact of thin coverage.

The pitcher model has the best log loss and Brier of any MLB model built here,
including Elo. That is a real probability-quality result and mirrors the NBA blend
finding. But it still does not beat Elo on accuracy, and it beats the served model by
0.12 percentage points, which is **three games out of 2,430** and far inside the
roughly two-point Wilson noise floor.

### It was deliberately not promoted to serving

Two reasons, recorded so the decision can be re-examined:

1. The accuracy and probability-quality gains over the served model are both at noise
   scale. Promoting on a three-game margin is exactly the kind of overfitting to a
   single holdout that this project's retraction was about.
2. There is an operational cost that the offline metric hides. Starting pitchers come
   from the StatsAPI `probablePitcher` hydrate and are not known far in advance, so a
   pitcher-dependent serving path would degrade or fail for future-dated matchups,
   which is the main thing the UI is asked for.

### Leakage was checked, not assumed

Per-game pitcher logs contain each game's own earned runs and outs, so building these
features naively would leak the result. Three independent checks:

- Features are snapshotted from cumulative state **before** that game's line is added,
  over logs sorted by UTC start time.
- A spot check on the most recent holdout start (Logan Webb, COL at SF, 2025-09-28)
  confirmed the pregame ERA used 179 prior games (3.3974) and excluded the game's own
  line of 16 outs and 0 earned runs, which would have moved it to 3.3803.
- The accuracy magnitude itself is the strongest evidence. A model that had leaked
  in-game pitcher lines would score far above 70%, not 55.84%.
