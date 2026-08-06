from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.live_winprob import (
    FEATURE_NAMES,
    GameState,
    artifact_path,
    baseline_leader,
    baseline_normal,
    brier_score,
    build_features,
    calibration_table,
    log_loss,
    max_calibration_gap,
    predict_home_win_prob,
)

DB_PATH = ROOT / "data" / "live_wp" / "mlb_snapshots.db"
NORMAL_MU = 0.25
NORMAL_SIGMA = 4.5
MAX_TRAIN_SNAPSHOTS_PER_GAME = 120


def rows() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    out = [
        dict(r)
        for r in conn.execute(
            """
            SELECT * FROM snapshots
            ORDER BY season, game_id, snapshot_index
            """
        )
    ]
    conn.close()
    if not out:
        raise SystemExit(f"No snapshots found in {DB_PATH}. Run harvest_mlb.py first.")
    return out


def state(row: dict) -> GameState:
    period = int(row["period"])
    return GameState(
        league="mlb",
        margin=int(row["margin"]),
        frac_remaining=float(row["frac_remaining"]),
        period=period,
        is_overtime=period > 9,
    )


def vector(row: dict) -> list[float]:
    feats = build_features(state(row))
    return [feats[name] for name in FEATURE_NAMES]


def outcomes(data: list[dict]) -> list[int]:
    return [int(r["home_won"]) for r in data]


def probs_for_model(model, data: list[dict]) -> list[float]:
    return [float(p) for p in model.predict_proba([vector(r) for r in data])[:, 1]]


def metric_block(probs: list[float], ys: list[int]) -> dict:
    return {
        "brier": round(brier_score(probs, ys), 6),
        "log_loss": round(log_loss(probs, ys), 6),
    }


def sampled_training_rows(data: list[dict]) -> list[dict]:
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in data:
        by_game[str(row["game_id"])].append(row)

    sampled: list[dict] = []
    for game_id in sorted(by_game):
        game = by_game[game_id]
        if len(game) <= MAX_TRAIN_SNAPSHOTS_PER_GAME:
            sampled.extend(game)
            continue
        picks = np.linspace(0, len(game) - 1, MAX_TRAIN_SNAPSHOTS_PER_GAME, dtype=int)
        sampled.extend(game[int(i)] for i in picks)
    return sampled


def evaluate(model, data: list[dict]) -> dict:
    ys = outcomes(data)
    st = [state(r) for r in data]
    model_probs = probs_for_model(model, data)
    leader_probs = [baseline_leader(s) for s in st]
    constant_probs = [0.5 for _ in st]
    normal_probs = [baseline_normal(s, NORMAL_MU, NORMAL_SIGMA) for s in st]
    espn_rows = [(float(r["espn_home_wp"]), int(r["home_won"])) for r in data if r["espn_home_wp"] is not None]
    espn_probs = [p for p, _y in espn_rows]
    espn_ys = [y for _p, y in espn_rows]

    phase_breakdown = {}
    buckets = [
        ("innings_1_3", 0.666666, 1.000001),
        ("innings_4_6", 0.333333, 0.666666),
        ("innings_7_9", 0.000001, 0.333333),
        ("extra_or_no_regulation_left", -0.000001, 0.000001),
    ]
    for name, lo, hi in buckets:
        idx = [i for i, r in enumerate(data) if lo < float(r["frac_remaining"]) <= hi]
        espn_idx = [i for i in idx if data[i]["espn_home_wp"] is not None]
        phase_breakdown[name] = {
            "n": len(idx),
            "model": metric_block([model_probs[i] for i in idx], [ys[i] for i in idx]) if idx else None,
            "leader": metric_block([leader_probs[i] for i in idx], [ys[i] for i in idx]) if idx else None,
            "constant_0_5": metric_block([0.5 for _ in idx], [ys[i] for i in idx]) if idx else None,
            "normal": metric_block([normal_probs[i] for i in idx], [ys[i] for i in idx]) if idx else None,
            "espn": metric_block([float(data[i]["espn_home_wp"]) for i in espn_idx], [ys[i] for i in espn_idx])
            if espn_idx
            else None,
            "espn_coverage": f"{len(espn_idx)}/{len(idx)}",
        }

    sanity_states = {
        "tied_top_1st": GameState(league="mlb", margin=0, frac_remaining=1.0, period=1),
        "early_home_plus_1": GameState(league="mlb", margin=1, frac_remaining=0.85, period=2),
        "late_home_plus_1": GameState(league="mlb", margin=1, frac_remaining=0.10, period=9),
        "late_home_minus_1": GameState(league="mlb", margin=-1, frac_remaining=0.10, period=9),
        "bottom_9_tied_proxy": GameState(league="mlb", margin=0, frac_remaining=1.0 / 18.0, period=9),
        "bottom_9_home_plus_1_proxy": GameState(league="mlb", margin=1, frac_remaining=1.0 / 18.0, period=9),
        "extra_tied": GameState(league="mlb", margin=0, frac_remaining=0.0, period=10, is_overtime=True),
    }
    sanity = {
        k: round(float(model.predict_proba([[build_features(s)[n] for n in FEATURE_NAMES]])[0][1]), 6)
        for k, s in sanity_states.items()
    }

    return {
        "model": metric_block(model_probs, ys),
        "baselines": {
            "leader": metric_block(leader_probs, ys),
            "constant_0_5": metric_block(constant_probs, ys),
            f"normal_mu_{NORMAL_MU}_sigma_{NORMAL_SIGMA}": metric_block(normal_probs, ys),
            "espn_home_wp": {
                **metric_block(espn_probs, espn_ys),
                "coverage": f"{len(espn_probs)}/{len(data)}",
            },
        },
        "calibration_table": calibration_table(model_probs, ys, bins=10),
        "max_calibration_gap": round(max_calibration_gap(model_probs, ys, bins=10, min_n=30), 6),
        "phase_breakdown": phase_breakdown,
        "sanity_checks": sanity,
    }


def main() -> None:
    data = rows()
    seasons = sorted({int(r["season"]) for r in data})
    if len(seasons) < 2:
        raise SystemExit(f"Need at least two seasons; found {seasons}")

    test_season = max(seasons)
    train_all = [r for r in data if int(r["season"]) < test_season]
    test = [r for r in data if int(r["season"]) == test_season]
    if not train_all or not test:
        raise SystemExit("Train/test split produced an empty side.")
    train = sampled_training_rows(train_all)

    base_model = make_pipeline(
        StandardScaler(),
        GradientBoostingClassifier(n_estimators=120, learning_rate=0.05, max_depth=2, random_state=42),
    )
    model = CalibratedClassifierCV(base_model, method="sigmoid", cv=3)
    model.fit([vector(r) for r in train], outcomes(train))

    validation = evaluate(model, test)
    all_games = len({r["game_id"] for r in data})
    train_games = len({r["game_id"] for r in train_all})
    test_games = len({r["game_id"] for r in test})
    bundle = {
        "model": model,
        "feature_names": FEATURE_NAMES,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_games": all_games,
        "n_snapshots": len(data),
        "brier": validation["model"]["brier"],
        "log_loss": validation["model"]["log_loss"],
        "validation": {
            **validation,
            "protocol": {
                "split": f"game-level chronological season holdout: train seasons < {test_season}, test season {test_season}",
                "train_games": train_games,
                "train_snapshots_available": len(train_all),
                "train_snapshots_used": len(train),
                "max_train_snapshots_per_game": MAX_TRAIN_SNAPSHOTS_PER_GAME,
                "test_games": test_games,
                "test_snapshots": len(test),
                "train_seasons": [s for s in seasons if s < test_season],
                "test_season": test_season,
                "normal_baseline": {"mu": NORMAL_MU, "sigma": NORMAL_SIGMA},
                "estimator": "GradientBoostingClassifier calibrated with 3-fold sigmoid calibration on training games only",
            },
        },
        "notes": (
            "MLB live WP trained only on frozen live_winprob.build_features fields. "
            "No test-set tuning; the latest harvested season is a held-out game-level season. "
            "Top/bottom half-inning is represented only through frac_remaining; outs are harvested "
            "but intentionally not used because the frozen serving feature map has no outs field."
        ),
    }

    path = artifact_path("mlb")
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)

    prob, meta = predict_home_win_prob(GameState(league="mlb", margin=1, frac_remaining=0.1))
    print(json.dumps(bundle["validation"], indent=2, sort_keys=True))
    print(f"saved={path}")
    print(f"serving_check_margin1_frac0.1={prob} available={meta.get('available')}")


if __name__ == "__main__":
    main()
