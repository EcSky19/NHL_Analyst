"""Independently re-evaluate a published live win-probability artifact.

Deliberately re-derives everything from the snapshot database rather than
trusting the metrics recorded inside the artifact: it re-scores the model,
re-fits the analytic baseline on the training season under both Brier and log
loss, checks train/test game overlap, compares against ESPN's published curve
where one exists, and checks monotonicity in margin and in elapsed time.

Usage (from the repo root):

    $env:PYTHONPATH="."; python scripts\\live_wp\\verify_artifacts.py nba 2023 2024
    $env:PYTHONPATH="."; python scripts\\live_wp\\verify_artifacts.py nhl 2024-25 2025-26
"""
import sqlite3
import sys

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr

from app.services.espn_pbp import REGULATION, ot_frac_remaining_clock
from app.services.live_winprob import (
    GameState,
    baseline_normal,
    brier_score,
    build_features,
    log_loss,
    max_calibration_gap,
)

LEAGUE = sys.argv[1]
TRAIN_SEASON = sys.argv[2]
TEST_SEASON = sys.argv[3]

art = joblib.load(f"models/live_wp/{LEAGUE}_live_wp.joblib")
names = art["feature_names"]
print(f"[{LEAGUE}] feature_names={names}")
print(f"[{LEAGUE}] train_seasons={art.get('train_seasons')} test_seasons={art.get('test_seasons')}")
print(f"[{LEAGUE}] claimed brier={art.get('brier')} log_loss={art.get('log_loss')}")

con = sqlite3.connect(f"data/live_wp/{LEAGUE}_snapshots.db")
cols = {d[1] for d in con.execute("PRAGMA table_info(snapshots)")}
HAS_CLOCK = "clock_seconds" in cols
CLOCK_COL = "s.clock_seconds" if HAS_CLOCK else "NULL"
SEL = (f"s.game_id, s.period, s.frac_remaining, s.margin, s.home_won, s.espn_home_wp, {CLOCK_COL}")
if "season" in cols:
    q = f"SELECT {SEL} FROM snapshots s WHERE s.season = ? AND s.home_won IS NOT NULL"
else:
    # NBA's snapshots table carries no season column; it lives on games.
    q = (f"SELECT {SEL} FROM snapshots s JOIN games g ON g.game_id = s.game_id "
         "WHERE g.season_start_year = ? AND s.home_won IS NOT NULL")


def load(season: str):
    return con.execute(q, (season,)).fetchall()


rows = load(TEST_SEASON)
train_rows = load(TRAIN_SEASON)
con.close()
print(f"[{LEAGUE}] held-out rows={len(rows)} games={len({r[0] for r in rows})}")
print(f"[{LEAGUE}] train rows={len(train_rows)} games={len({r[0] for r in train_rows})}")
overlap = {r[0] for r in rows} & {r[0] for r in train_rows}
print(f"[{LEAGUE}] train/test game overlap={len(overlap)} (must be 0)")

periods = {"nhl": 3, "nba": 4, "nfl": 4, "mlb": 9}[LEAGUE]


def build(rowset):
    X, y, espn, states = [], [], [], []
    for _gid, period, frac, margin, won, ewp, clock in rowset:
        is_ot = bool(period and period > periods)
        # Overtime snapshots carry frac_remaining == 0.0, so without the
        # overtime clock the model is being scored in a state it is never
        # actually served in. Reconstruct it exactly as training does.
        ot_frac = (
            ot_frac_remaining_clock(LEAGUE, int(period), clock)
            if (is_ot and LEAGUE in REGULATION and clock is not None)
            else None
        )
        st = GameState(
            league=LEAGUE, margin=margin, frac_remaining=frac,
            period=period, is_overtime=is_ot, ot_frac_remaining=ot_frac,
        )
        feats = build_features(st)
        X.append([feats[n] for n in names])
        y.append(won)
        espn.append(ewp)
        states.append(st)
    return np.array(X, dtype=float), np.array(y, dtype=float), espn, states


X, y, espn, states = build(rows)
_Xtr, ytr, _etr, states_tr = build(train_rows)

margins = np.array([s.margin for s in states], dtype=float)
fracs = np.clip(np.array([s.frac_remaining for s in states], dtype=float), 0.0, 1.0)
margins_tr = np.array([s.margin for s in states_tr], dtype=float)
fracs_tr = np.clip(np.array([s.frac_remaining for s in states_tr], dtype=float), 0.0, 1.0)


def normal_vec(margin, frac, mu, sigma):
    """Vectorised twin of live_winprob.baseline_normal (asserted equal below)."""
    live = frac > 1e-9
    out = np.where(margin > 0, 1.0, np.where(margin < 0, 0.0, 0.5)).astype(float)
    f = np.where(live, frac, 1.0)
    sd = np.maximum(sigma * np.sqrt(f), 1e-9)
    out[live] = ndtr(((margin + mu * f) / sd)[live])
    return out


_chk = normal_vec(margins[:200], fracs[:200], 0.3, 7.0)
_ref = np.array([baseline_normal(s, 0.3, 7.0) for s in states[:200]])
assert np.allclose(_chk, _ref, atol=1e-12), "vectorised baseline diverges from frozen one"

# Fit the 2-parameter analytic baseline on TRAIN only, then score it on TEST.
# Fit under BOTH objectives: a baseline tuned for Brier is not the same as one
# tuned for log loss, and reporting only the flattering one would be cheating.
def fit_baseline(objective):
    def obj(theta):
        q = list(normal_vec(margins_tr, fracs_tr, theta[0], max(theta[1], 1e-3)))
        return objective(q, list(ytr))

    best_res = None
    for s0 in (2.0, 7.0, 13.0, 18.0):
        res = minimize(obj, x0=np.array([0.0, s0]), method="Nelder-Mead",
                       options={"xatol": 1e-4, "fatol": 1e-8, "maxiter": 400})
        if best_res is None or res.fun < best_res.fun:
            best_res = res
    return float(best_res.x[0]), float(max(best_res.x[1], 1e-3))


p = art["model"].predict_proba(X)[:, 1]
yl = list(y)
print(f"[{LEAGUE}] REPRODUCED brier={brier_score(list(p), yl):.6f} log_loss={log_loss(list(p), yl):.6f}")
print(f"[{LEAGUE}] calib_gap={max_calibration_gap(list(p), yl):.4f}")

base = None
for label, objective in (("brier", brier_score), ("logloss", log_loss)):
    mu, sigma = fit_baseline(objective)
    b = normal_vec(margins, fracs, mu, sigma)
    if label == "brier":
        base = b
    print(f"[{LEAGUE}] baseline fit-by-{label:<7} (mu={mu:+.3f} sigma={sigma:.3f}) "
          f"brier={brier_score(list(b), yl):.6f} log_loss={log_loss(list(b), yl):.6f}")

mask = np.array([e is not None for e in espn])
if mask.any():
    ev = np.array([e for e in espn if e is not None], dtype=float)
    print(f"[{LEAGUE}] ESPN rows={int(mask.sum())} brier={brier_score(list(ev), list(y[mask])):.6f} "
          f"| ours on same rows={brier_score(list(p[mask]), list(y[mask])):.6f} "
          f"| baseline={brier_score(list(base[mask]), list(y[mask])):.6f}")
else:
    print(f"[{LEAGUE}] ESPN rows=0 -> no external benchmark exists")

tied = np.array([r[3] == 0 for r in rows])
print(f"[{LEAGUE}] TIED-state rows={int(tied.sum())} "
      f"brier={brier_score(list(p[tied]), list(y[tied])):.6f} (coin flip = 0.250000)")

# Monotonicity: flexible models can break it.
for frac in (0.75, 0.25, 0.05):
    probs = [
        art["model"].predict_proba(
            np.array([[build_features(GameState(LEAGUE, m, frac))[n] for n in names]], dtype=float)
        )[0][1]
        for m in range(-4, 5)
    ]
    ok = all(a <= b + 1e-9 for a, b in zip(probs, probs[1:]))
    print(f"[{LEAGUE}] frac={frac} margins -4..4 monotone={ok} "
          + " ".join(f"{v:.3f}" for v in probs))

# Monotonicity in TIME: a fixed lead must gain value as the clock runs out.
# Not gated historically, which is how NFL/MLB shipped with local reversals.
#
# The sweep resolution deliberately does NOT match the 41-point grid the
# training-time monotone envelopes are built on. Sweeping the envelope's own
# grid is circular: it samples exactly the points the envelope makes monotone
# by construction, and is blind to reversals in between. A 401-point sweep at
# an offset caught real MLB reversals of up to 1.4e-02 that a 40-step sweep
# reported as perfectly clean.
#
# Negative margins are swept too. The envelope mirrors to a min for a trailing
# team, and applying it in only one direction is a mistake we have made before.
STEPS = 400
for margin in (1, 2, 3, -1, -2, -3):
    seq = [
        art["model"].predict_proba(
            np.array([[build_features(GameState(LEAGUE, margin, 1.0 - i / STEPS))[n]
                       for n in names]], dtype=float)
        )[0][1]
        for i in range(STEPS + 1)
    ]
    if margin > 0:
        drops = [a - b for a, b in zip(seq, seq[1:]) if b < a - 1e-9]
    else:
        drops = [b - a for a, b in zip(seq, seq[1:]) if b > a + 1e-9]
    sign = "+" if margin > 0 else ""
    print(f"[{LEAGUE}] margin={sign}{margin} time-monotone={not drops} "
          f"drops={len(drops)}/{STEPS} worst={max(drops, default=0.0):.5f} "
          f"{seq[0]:.4f}->{seq[-1]:.4f}")
