"""Transparent serving layer for NHL, NFL, and NBA prediction rows."""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from app.config import settings

ROOT = Path(__file__).resolve().parents[2]
NHL_FEATURES = ROOT / "data" / "processed" / "team_feature_base.csv"
NHL_RECENT = ROOT / "data" / "processed" / "matchup_context_features.csv"
NHL_CONFIG = ROOT / "data" / "processed" / "weighted_win_model_config.json"
NFL_CONFIG = ROOT / "data" / "nfl" / "nfl_final_model_frozen_config.json"
NFL_HOLDOUT = ROOT / "data" / "nfl" / "nfl_final_model_holdout_predictions.csv"
NBA_ARTIFACT = ROOT / "data" / "nba" / "nba_model_final.joblib"
NBA_CONFIG = ROOT / "data" / "nba" / "nba_model_config.json"
NHL_PROB_BOUNDS = (0.20, 0.80)
NFL_PROB_BOUNDS = (0.15, 0.85)
NBA_PROB_BOUNDS = (0.10, 0.90)
NBA_MODEL_ACCURACY = 0.6252
NBA_ELO_BASELINE_ACCURACY = 0.6295


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _logit(p: float) -> float:
    clipped = min(0.999, max(0.001, p))
    return math.log(clipped / (1.0 - clipped))


def _flt(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence(prob: float, league: str) -> str:
    distance = abs(prob - 0.5)
    high = 0.15 if league == "nhl" else 0.20
    medium = 0.07 if league == "nhl" else 0.10
    if distance >= high:
        return "high (probability distance only; not tier accuracy)"
    if distance >= medium:
        return "medium (probability distance only; not tier accuracy)"
    return "low (probability distance only; not tier accuracy)"


def _prob_pair(home_prob: float, bounds: tuple[float, float] = (0.01, 0.99)) -> tuple[float, float]:
    home = min(bounds[1], max(bounds[0], home_prob))
    return round(home, 6), round(1.0 - home, 6)


def _fit_platt(xs: list[float], ys: list[float]) -> tuple[float, float]:
    intercept, slope = 0.0, 1.0
    if len(xs) < 100:
        return intercept, slope
    for _ in range(50):
        grad_i = 0.0
        grad_s = 0.0
        h_ii = 1e-6
        h_is = 0.0
        h_ss = 1e-6
        for x, y in zip(xs, ys):
            p = _sigmoid(intercept + slope * x)
            err = p - y
            weight = max(p * (1.0 - p), 1e-9)
            grad_i += err
            grad_s += err * x
            h_ii += weight
            h_is += weight * x
            h_ss += weight * x * x
        grad_s += 1e-3 * (slope - 1.0)
        h_ss += 1e-3
        det = h_ii * h_ss - h_is * h_is
        if abs(det) < 1e-12:
            break
        step_i = (h_ss * grad_i - h_is * grad_s) / det
        step_s = (-h_is * grad_i + h_ii * grad_s) / det
        intercept -= max(-1.0, min(1.0, step_i))
        slope -= max(-1.0, min(1.0, step_s))
        if abs(step_i) + abs(step_s) < 1e-8:
            break
    return intercept, slope


def _apply_platt(raw_logit: float, calibration: tuple[float, float]) -> float:
    intercept, slope = calibration
    return _sigmoid(intercept + slope * raw_logit)


@dataclass(frozen=True)
class PredictionRow:
    game_id: str | None
    game_date: str | None
    league: str
    home: str
    away: str
    home_win_prob: float
    away_win_prob: float
    confidence: str
    model: str
    model_accuracy: float
    baseline_accuracy: float
    features_used: list[str]
    disclaimer: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class PredictionError(ValueError):
    """Validation/data problem safe to expose to the UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NHLScorer:
    """Applies the saved weighted-win serving config to current team profiles."""

    def __init__(self) -> None:
        self.config = json.loads(NHL_CONFIG.read_text(encoding="utf-8"))
        self.profiles = self._load_profiles()
        self.calibration = self._fit_calibration()

    def _load_profiles(self) -> dict[str, dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        with NHL_FEATURES.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code = str(row["team_abbreviation"]).upper()
                profile: dict[str, Any] = {"team": code, "name": row.get("team_name", code)}
                for feature in self.config["season_feature_weights"]:
                    profile[feature] = _flt(row.get(feature))
                gf = _flt(row.get("off_goals_per_game"))
                ga = _flt(row.get("def_goals_against_per_game"))
                denom = gf * gf + ga * ga
                profile["points_pct_prior"] = gf * gf / denom if denom > 0 else 0.5
                profile["goal_diff_per_game"] = gf - ga
                profile["games_played"] = _flt(row.get("games_played"))
                profiles[code] = profile
        self._merge_recent(profiles)
        return profiles

    def _merge_recent(self, profiles: dict[str, dict[str, Any]]) -> None:
        if not NHL_RECENT.exists():
            return
        buckets: dict[str, dict[str, list[float]]] = {}
        keys = [
            "l10_points_pct",
            "l10_goal_diff_per_game",
            "trend_points_pct_l10_minus_season",
            "trend_goal_diff_pg_l10_minus_season",
            "streak_signed",
            "home_points_pct",
            "road_points_pct",
            "home_goal_diff_per_game",
            "road_goal_diff_per_game",
            "points_pct",
        ]
        with NHL_RECENT.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                for side in ("home", "away"):
                    code = str(row.get(f"{side}_team_abbrev", "")).upper()
                    if not code:
                        continue
                    team_bucket = buckets.setdefault(code, {})
                    for key in keys:
                        val = row.get(f"{side}_{key}")
                        if val not in (None, "", "None"):
                            team_bucket.setdefault(key, []).append(_flt(val))
        for code, profile in profiles.items():
            rec = {k: sum(v) / len(v) for k, v in buckets.get(code, {}).items() if v}
            for feature in self.config["recent_feature_weights"]:
                profile[feature] = rec.get(feature)
            points = rec.get("points_pct", profile["points_pct_prior"])
            gd = profile["goal_diff_per_game"]
            profile["points_pct_prior"] = min(0.95, max(0.05, float(points)))
            profile["home_points_pct"] = rec.get("home_points_pct", min(0.95, profile["points_pct_prior"] + 0.04))
            profile["road_points_pct"] = rec.get("road_points_pct", max(0.05, profile["points_pct_prior"] - 0.04))
            profile["home_goal_diff_per_game"] = rec.get("home_goal_diff_per_game", gd + 0.12)
            profile["road_goal_diff_per_game"] = rec.get("road_goal_diff_per_game", gd - 0.12)

    def _strength(self, profile: dict[str, Any]) -> float:
        stats = self.config["feature_stats"]
        season = 0.0
        for feature, weight in self.config["season_feature_weights"].items():
            stat = stats[feature]
            z = (_flt(profile.get(feature), stat["median"]) - stat["median"]) / max(stat["scale"], 1e-6)
            season += float(weight) * max(-3.0, min(3.0, z))
        recent = 0.0
        present = 0
        for feature, weight in self.config["recent_feature_weights"].items():
            stat = stats[feature]
            if profile.get(feature) is not None:
                present += 1
            z = (_flt(profile.get(feature), stat["median"]) - stat["median"]) / max(stat["scale"], 1e-6)
            recent += float(weight) * max(-3.0, min(3.0, z))
        constants = self.config["constants"]
        prior = _logit(_flt(profile.get("points_pct_prior"), 0.5))
        recent_blend = float(constants["recent_blend_max"]) * present / max(len(self.config["recent_feature_weights"]), 1)
        return float(constants["season_blend"]) * season + recent_blend * recent + float(constants["prior_blend"]) * prior

    def raw_logit(self, home: str, away: str) -> float:
        hp, ap = self.profiles[home], self.profiles[away]
        constants = self.config["constants"]
        loc = float(constants["home_advantage_logit"])
        loc += float(constants["location_points_weight"]) * (_flt(hp["home_points_pct"]) - _flt(ap["road_points_pct"]))
        loc += float(constants["location_goal_diff_weight"]) * (_flt(hp["home_goal_diff_per_game"]) - _flt(ap["road_goal_diff_per_game"]))
        logit_home = (self._strength(hp) - self._strength(ap) + loc) * float(constants["logit_diff_shrink"])
        return logit_home / float(constants["logit_temperature"])

    def _fit_calibration(self) -> tuple[float, float]:
        xs: list[float] = []
        ys: list[float] = []
        if not settings.nhl_db.exists():
            return (0.0, 1.0)
        with sqlite3.connect(settings.nhl_db) as con:
            for home, away, won in con.execute(
                """
                SELECT home_team_abbrev, away_team_abbrev, home_win
                FROM backtest_features_last5_roster
                WHERE home_win IS NOT NULL
                  AND COALESCE(is_synthetic, 0) = 0
                """
            ):
                h, a = str(home).upper(), str(away).upper()
                if h in self.profiles and a in self.profiles:
                    xs.append(self.raw_logit(h, a))
                    ys.append(float(won))
        return _fit_platt(xs, ys)

    def row(self, home: str, away: str) -> PredictionRow:
        h, a = home.upper(), away.upper()
        if h == a:
            raise PredictionError("bad_request", "home and away must be different teams")
        missing = [team for team in (h, a) if team not in self.profiles]
        if missing:
            raise PredictionError("no_data", f"unknown NHL team abbreviation(s): {', '.join(missing)}")
        prob = _apply_platt(self.raw_logit(h, a), self.calibration)
        home_prob, away_prob = _prob_pair(prob, NHL_PROB_BOUNDS)
        return PredictionRow(
            game_id=f"hypothetical:nhl:{h}:{a}",
            game_date=None,
            league="nhl",
            home=h,
            away=a,
            home_win_prob=home_prob,
            away_win_prob=away_prob,
            confidence=_confidence(home_prob, "nhl"),
            model="nhl-weighted-win-serving + empirical Platt calibration",
            model_accuracy=settings.nhl_model_accuracy,
            baseline_accuracy=settings.nhl_baseline_accuracy,
            features_used=[
                "team_feature_base",
                "recent_matchup_context",
                "home_ice_adjustment",
                "empirical_platt_calibration_real_games",
                "transparent_0.20_0.80_safety_bound",
            ],
            disclaimer=(
                "NHL model accuracy is 56.82% vs 53.5% always-home baseline; "
                "probabilities are Platt-calibrated on real completed games with a transparent 20%-80% safety bound; "
                "this is not a betting edge or tier-specific accuracy claim."
            ),
        )


class NFLScorer:
    """Uses real nfl_features aggregates when no fitted serving artifact exists."""

    def __init__(self) -> None:
        self.config = json.loads(NFL_CONFIG.read_text(encoding="utf-8")) if NFL_CONFIG.exists() else {}
        self.profiles = self._load_profiles()
        self.calibration = self._fit_calibrations()

    def _load_profiles(self) -> dict[str, dict[str, float]]:
        if not settings.nfl_db.exists():
            return {}
        rows: list[sqlite3.Row]
        with sqlite3.connect(settings.nfl_db) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT * FROM nfl_features
                WHERE season BETWEEN 2023 AND 2025
                  AND game_type = 'REG'
                  AND COALESCE(is_tie, 0) = 0
                  AND target_home_win IS NOT NULL
                ORDER BY season, week, game_id
                """
            ).fetchall()
        raw: dict[str, dict[str, list[float]]] = {}
        for row in rows:
            margin = _flt(row["target_home_margin"])
            for side, sign in (("home", 1.0), ("away", -1.0)):
                team = str(row[f"{side}_team"]).upper()
                bucket = raw.setdefault(team, {"wins": [], "margin": [], "elo": [], "epa": [], "market": []})
                home_win = int(row["target_home_win"])
                bucket["wins"].append(1.0 if (home_win == 1 and side == "home") or (home_win == 0 and side == "away") else 0.0)
                bucket["margin"].append(sign * margin)
                bucket["elo"].append(_flt(row[f"{side}_elo_pregame"], 1500.0))
                off = _flt(row[f"{side}_offensive_epa_per_play_season_to_date"])
                defense_allowed = _flt(row[f"{side}_defensive_epa_per_play_allowed_season_to_date"])
                bucket["epa"].append(off - defense_allowed)
                market_home = row["home_moneyline_implied_no_vig"]
                if market_home not in (None, "", "None"):
                    p_team = _flt(market_home, 0.5) if side == "home" else 1.0 - _flt(market_home, 0.5)
                    bucket["market"].append(p_team)
        profiles: dict[str, dict[str, float]] = {}
        for team, vals in raw.items():
            games = len(vals["wins"])
            if games <= 0:
                continue
            profiles[team] = {
                "games": float(games),
                "win_pct": sum(vals["wins"]) / games,
                "margin_pg": sum(vals["margin"]) / games,
                "elo": sum(vals["elo"]) / len(vals["elo"]),
                "epa": sum(vals["epa"]) / len(vals["epa"]),
                "market_logit": _logit(sum(vals["market"]) / len(vals["market"])) if vals["market"] else 0.0,
            }
        return profiles

    def _market_free_logit(self, home: dict[str, float], away: dict[str, float]) -> float:
        elo = (home["elo"] - away["elo"]) / 400.0
        win = (home["win_pct"] - away["win_pct"]) * 1.15
        margin = (home["margin_pg"] - away["margin_pg"]) / 16.0
        epa = (home["epa"] - away["epa"]) * 1.4
        return 0.16 + elo + win + margin + epa

    def _full_logit(self, home: dict[str, float], away: dict[str, float]) -> float:
        market_free = self._market_free_logit(home, away)
        market = 0.12 + home["market_logit"] - away["market_logit"]
        return (0.55 * market_free) + (0.45 * market)

    def _fit_calibrations(self) -> dict[str, tuple[float, float]]:
        xs_market_free: list[float] = []
        xs_full: list[float] = []
        ys: list[float] = []
        if not settings.nfl_db.exists():
            return {"market_free": (0.0, 1.0), "full": (0.0, 1.0)}
        with sqlite3.connect(settings.nfl_db) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT home_team, away_team, target_home_win
                FROM nfl_features
                WHERE season BETWEEN 2010 AND 2025
                  AND game_type = 'REG'
                  AND COALESCE(is_tie, 0) = 0
                  AND target_home_win IS NOT NULL
                """
            ).fetchall()
        for row in rows:
            h, a = str(row["home_team"]).upper(), str(row["away_team"]).upper()
            if h in self.profiles and a in self.profiles:
                xs_market_free.append(self._market_free_logit(self.profiles[h], self.profiles[a]))
                xs_full.append(self._full_logit(self.profiles[h], self.profiles[a]))
                ys.append(float(row["target_home_win"]))
        return {"market_free": _fit_platt(xs_market_free, ys), "full": _fit_platt(xs_full, ys)}

    def rows(self, home: str, away: str) -> list[PredictionRow]:
        h, a = home.upper(), away.upper()
        if h == a:
            raise PredictionError("bad_request", "home and away must be different teams")
        missing = [team for team in (h, a) if team not in self.profiles]
        if missing:
            raise PredictionError("no_data", f"unknown NFL team abbreviation(s) or no recent games: {', '.join(missing)}")
        hp, ap = self.profiles[h], self.profiles[a]
        market_free_logit = self._market_free_logit(hp, ap)
        market_free_prob = _apply_platt(market_free_logit, self.calibration["market_free"])
        full_prob = _apply_platt(self._full_logit(hp, ap), self.calibration["full"])
        rows: list[PredictionRow] = []
        for prob, model, acc, features, disclaimer in [
            (
                market_free_prob,
                "nfl-market-free-elo-logistic serving proxy + empirical Platt calibration (primary)",
                settings.nfl_market_free_accuracy,
                [
                    "elo_diff",
                    "recent_win_pct_diff",
                    "point_margin_diff",
                    "epa_diff",
                    "empirical_platt_calibration_real_games",
                    "transparent_0.15_0.85_safety_bound",
                ],
                "NFL market-free model accuracy is 66.11% vs 56.17% always-home baseline; probabilities are Platt-calibrated with a transparent 15%-85% safety bound and are not a betting edge.",
            ),
            (
                full_prob,
                "nfl-full-market-aware historical-market proxy + empirical Platt calibration (secondary)",
                settings.nfl_full_accuracy,
                [
                    "market_free_logit",
                    "historical_moneyline_implied_team_signal",
                    "empirical_platt_calibration_real_games",
                    "transparent_0.15_0.85_safety_bound",
                ],
                "NFL full model accuracy is 67.40%, below the same-holdout Vegas bar of 68.51%; it largely echoes Vegas, is safety-bounded at 15%-85%, and is not a betting edge.",
            ),
        ]:
            home_prob, away_prob = _prob_pair(prob, NFL_PROB_BOUNDS)
            rows.append(
                PredictionRow(
                    game_id=f"hypothetical:nfl:{h}:{a}",
                    game_date=None,
                    league="nfl",
                    home=h,
                    away=a,
                    home_win_prob=home_prob,
                    away_win_prob=away_prob,
                    confidence=_confidence(home_prob, "nfl"),
                    model=model,
                    model_accuracy=acc,
                    baseline_accuracy=settings.nfl_baseline_accuracy,
                    features_used=features,
                    disclaimer=disclaimer,
                )
            )
        return rows


class NBAScorer:
    """Scores NBA hypothetical matchups with the frozen model artifact."""

    def __init__(self) -> None:
        if not NBA_ARTIFACT.exists() or not settings.nba_db.exists():
            raise PredictionError("no_data", "NBA model artifact or database is unavailable")
        self.config = json.loads(NBA_CONFIG.read_text(encoding="utf-8")) if NBA_CONFIG.exists() else {}
        artifact = joblib.load(NBA_ARTIFACT)
        self.base_model = artifact["base_model"]
        self.platt = artifact["platt"]
        self.features: list[str] = list(artifact.get("features") or self.config["feature_columns"])
        self.feature_bases = self._feature_bases()
        self.aliases = self._load_aliases()
        self.profiles = self._load_profiles()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{settings.nba_db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def _feature_bases(self) -> set[str]:
        bases: set[str] = set()
        for feature in self.features:
            for suffix in ("_home", "_away", "_diff"):
                if feature.endswith(suffix):
                    bases.add(feature[: -len(suffix)])
        return bases

    def _load_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        with self._connect() as con:
            rows = con.execute("SELECT abbreviation, alias_source_codes FROM nba_teams").fetchall()
        for row in rows:
            canonical = str(row["abbreviation"]).upper()
            aliases[canonical] = canonical
            raw = str(row["alias_source_codes"] or "").split(";", 1)[0]
            for alias in raw.split(","):
                code = alias.strip().upper()
                if code:
                    aliases[code] = canonical
        aliases.update({"CHO": "CHA", "CHH": "CHA", "NJ": "BKN", "NJN": "BKN", "NOH": "NOP", "NOK": "NOP", "NO": "NOP", "NY": "NYK", "GS": "GSW", "SA": "SAS", "SEA": "OKC", "WSH": "WAS", "UTAH": "UTA"})
        return aliases

    def _load_profiles(self) -> dict[str, dict[str, float]]:
        profiles: dict[str, dict[str, float]] = {}
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM nba_features_pregame
                WHERE season BETWEEN 2021 AND 2023
                ORDER BY game_date, game_id
                """
            ).fetchall()
            for row in rows:
                columns = set(row.keys())
                for side in ("home", "away"):
                    team = self.aliases.get(str(row[f"{side}_team"]).upper())
                    if not team:
                        continue
                    profile = profiles.setdefault(team, {})
                    suffix = f"_{side}"
                    for base in self.feature_bases:
                        column = f"{base}{suffix}"
                        if column in columns:
                            value = row[column]
                            if value is not None:
                                profile[base] = _flt(value)

            current_rows = con.execute(
                """
                SELECT *
                FROM nba_current_standings
                WHERE season_end_year = (SELECT MAX(season_end_year) FROM nba_current_standings)
                """
            ).fetchall()
            for row in current_rows:
                team = self.aliases.get(str(row["team_abbrev"]).upper())
                if not team:
                    continue
                profile = profiles.setdefault(team, {})
                win_pct = min(0.95, max(0.05, _flt(row["win_pct"], 0.5)))
                profile["season_win_pct"] = win_pct
                points_for = _flt(row["points_for_per_game"])
                points_against = _flt(row["points_against_per_game"])
                if points_for and points_against:
                    margin = points_for - points_against
                    for window in (3, 5, 10, 20):
                        profile[f"points_last{window}"] = points_for
                        profile[f"opp_points_last{window}"] = points_against
                        profile[f"margin_last{window}"] = margin
                        profile[f"off_rating_last{window}"] = points_for
                        profile[f"def_rating_last{window}"] = points_against
                profile["elo_pre"] = 1500.0 + 400.0 * math.log10(win_pct / (1.0 - win_pct))

            stat_rows = con.execute(
                """
                SELECT *
                FROM nba_current_team_stats
                WHERE season_end_year = (SELECT MAX(season_end_year) FROM nba_current_team_stats)
                """
            ).fetchall()
            for row in stat_rows:
                team = self.aliases.get(str(row["team_abbrev"]).upper())
                if not team:
                    continue
                profile = profiles.setdefault(team, {})
                fg_pct = _flt(row["fg_pct"])
                turnovers = _flt(row["turnovers_per_game"])
                if fg_pct:
                    for window in (3, 5, 10, 20):
                        profile[f"efg_pct_last{window}"] = min(0.62, fg_pct + 0.035)
                if turnovers:
                    for window in (3, 5, 10, 20):
                        profile[f"turnover_rate_last{window}"] = min(0.22, max(0.09, turnovers / 90.0))
        return profiles

    def _profile_value(self, team: str, base: str) -> float | None:
        return self.profiles.get(team, {}).get(base)

    def _feature_row(self, home: str, away: str) -> dict[str, float | None]:
        hp = self.profiles[home]
        ap = self.profiles[away]
        home_elo = hp.get("elo_pre", 1500.0)
        away_elo = ap.get("elo_pre", 1500.0)
        elo_diff = home_elo - away_elo
        row: dict[str, float | None] = {
            "elo_pre_home": home_elo,
            "elo_pre_away": away_elo,
            "elo_pre_diff": elo_diff,
            "elo_diff": elo_diff,
            "elo_prob_home": 1.0 / (1.0 + 10.0 ** (-((elo_diff + 65.0) / 400.0))),
            "opp_elo_pre_home": away_elo,
            "opp_elo_pre_away": home_elo,
            "opp_elo_pre_diff": away_elo - home_elo,
            "rest_days_home": 2.0,
            "rest_days_away": 2.0,
            "rest_days_diff": 0.0,
            "rest_diff": 0.0,
            "home_b2b": 0.0,
            "away_b2b": 0.0,
            "is_back_to_back_home": 0.0,
            "is_back_to_back_away": 0.0,
            "is_back_to_back_diff": 0.0,
            "away_road_trip": 0.0,
            "home_road_trip_flag": 0.0,
            "road_trip_game_home": 0.0,
            "road_trip_game_away": 0.0,
            "road_trip_game_diff": 0.0,
        }
        for feature in self.features:
            if feature in row:
                continue
            if feature.endswith("_home"):
                row[feature] = self._profile_value(home, feature[:-5])
            elif feature.endswith("_away"):
                row[feature] = self._profile_value(away, feature[:-5])
            elif feature.endswith("_diff"):
                base = feature[:-5]
                home_value = self._profile_value(home, base)
                away_value = self._profile_value(away, base)
                row[feature] = home_value - away_value if home_value is not None and away_value is not None else None
            else:
                row[feature] = None
        return row

    def row(self, home: str, away: str) -> PredictionRow:
        h = self.aliases.get(home.upper(), home.upper())
        a = self.aliases.get(away.upper(), away.upper())
        if h == a:
            raise PredictionError("bad_request", "home and away must be different teams")
        missing = [team for team in (h, a) if team not in self.profiles]
        if missing:
            raise PredictionError("no_data", f"unknown NBA team abbreviation(s) or no profile data: {', '.join(missing)}")
        frame = pd.DataFrame([self._feature_row(h, a)], columns=self.features)
        raw_logit = self.base_model.decision_function(frame)
        prob = float(self.platt.predict_proba(raw_logit.reshape(-1, 1))[0, 1])
        home_prob, away_prob = _prob_pair(prob, NBA_PROB_BOUNDS)
        return PredictionRow(
            game_id=f"hypothetical:nba:{h}:{a}",
            game_date=None,
            league="nba",
            home=h,
            away=a,
            home_win_prob=home_prob,
            away_win_prob=away_prob,
            confidence="not reported (NBA calibration buckets are mostly under 150 games)",
            model="nba-frozen-histgradientboosting + empirical Platt calibration",
            model_accuracy=NBA_MODEL_ACCURACY,
            baseline_accuracy=NBA_ELO_BASELINE_ACCURACY,
            features_used=[
                "frozen_nba_model_final_joblib",
                "current_team_standings_profile",
                "recent_historical_pregame_profile",
                "empirical_platt_calibration_real_games",
                "transparent_0.10_0.90_safety_bound",
            ],
            disclaimer=(
                "NBA frozen holdout accuracy is 62.52% on 1,174 2023 games "
                "(Wilson 95% CI 59.72%-65.25%), with log loss 0.6487 and Brier 0.2285. "
                "It is higher than always-home (58.43%) but roughly matches and does not beat a simple "
                "pure Elo baseline (62.95%); the -0.43% gap is inside the Wilson interval. "
                "Probabilities include a transparent 10%-90% safety bound; this is not a betting "
                "edge or confidence-tier claim."
            ),
        )


def nhl_matchup(home: str, away: str) -> list[dict[str, Any]]:
    return [_nhl_scorer().row(home, away).as_dict()]


def nfl_matchup(home: str, away: str) -> list[dict[str, Any]]:
    return [row.as_dict() for row in _nfl_scorer().rows(home, away)]


def nba_matchup(home: str, away: str) -> list[dict[str, Any]]:
    return [_nba_scorer().row(home, away).as_dict()]


def nfl_holdout_predictions(season: int | None, week: int | None) -> list[dict[str, Any]]:
    if not NFL_HOLDOUT.exists() or season is None or week is None:
        return []
    rows: list[dict[str, Any]] = []
    with NFL_HOLDOUT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["season"]) != season or int(row["week"]) != week:
                continue
            prob, away_prob = _prob_pair(_flt(row["prob_home_win"], 0.5), NFL_PROB_BOUNDS)
            is_full = row["model"].lower() == "full"
            rows.append(
                PredictionRow(
                    game_id=row["game_id"],
                    game_date=None,
                    league="nfl",
                    home=row["home_team"],
                    away=row["away_team"],
                    home_win_prob=prob,
                    away_win_prob=away_prob,
                    confidence=_confidence(prob, "nfl"),
                    model=("nfl-full-market-aware frozen holdout (secondary)" if is_full else "nfl-market-free frozen holdout (primary)"),
                    model_accuracy=(settings.nfl_full_accuracy if is_full else settings.nfl_market_free_accuracy),
                    baseline_accuracy=settings.nfl_baseline_accuracy,
                    features_used=(["frozen_holdout_full_features"] if is_full else ["frozen_holdout_market_free_features"]),
                    disclaimer=(
                        "NFL full model accuracy is 67.40%, below Vegas 68.51%; not a betting edge."
                        if is_full
                        else "NFL market-free model accuracy is 66.11% vs 56.17% home baseline; not a betting edge."
                    ),
                ).as_dict()
            )
    return rows


def validate_iso_date(value: str | None) -> None:
    if value:
        date.fromisoformat(value)


@lru_cache(maxsize=1)
def _nhl_scorer() -> NHLScorer:
    return NHLScorer()


@lru_cache(maxsize=1)
def _nfl_scorer() -> NFLScorer:
    return NFLScorer()


@lru_cache(maxsize=1)
def _nba_scorer() -> NBAScorer:
    return NBAScorer()
