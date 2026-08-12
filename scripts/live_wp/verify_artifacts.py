"""Independently re-evaluate a published live win-probability artifact.

Deliberately re-derives everything from the snapshot database rather than
trusting the metrics recorded inside the artifact: it re-scores the model,
re-fits the analytic baseline on the training season under both Brier and log
loss, checks train/test game overlap, compares against ESPN's published curve
where one exists, and checks monotonicity in margin and in elapsed time.

Usage (from the repo root):

    $env:PYTHONPATH="."; python scripts\\live_wp\\verify_artifacts.py nba 2023 2024
    $env:PYTHONPATH="."; python scripts\\live_wp\\verify_artifacts.py nhl 2024-25 2025-26

A full run re-scores every snapshot and takes minutes. To check only whether a
training script has moved since its artifact was written (see "the artifacts
are not self-contained" in docs/live_wp/README.md), which is fast:

    $env:PYTHONPATH="."; python scripts\\live_wp\\verify_artifacts.py mlb --provenance-only

which exits non-zero if the source has drifted or is uncommitted.
"""
import shutil
import sqlite3
import subprocess
import sys

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr

from app.services.espn_pbp import REGULATION, ot_frac_remaining_clock
from app.services.live_winprob import (
    GameState,
    SERVE_CLIP,
    baseline_normal,
    brier_score,
    build_features,
    log_loss,
    max_calibration_gap,
)

LEAGUE = sys.argv[1]
# Provenance is cheap; re-scoring is not. Allow checking drift on its own so
# there is no excuse to skip it before trusting a published number.
PROVENANCE_ONLY = "--provenance-only" in sys.argv[1:]
_pos = [a for a in sys.argv[2:] if not a.startswith("-")]
TRAIN_SEASON = _pos[0] if _pos else None
TEST_SEASON = _pos[1] if len(_pos) > 1 else None
if not PROVENANCE_ONLY and (TRAIN_SEASON is None or TEST_SEASON is None):
    sys.exit("usage: verify_artifacts.py <league> <train_season> <test_season> [--provenance-only]")

art = joblib.load(f"models/live_wp/{LEAGUE}_live_wp.joblib")
names = art["feature_names"]
print(f"[{LEAGUE}] feature_names={names}")
# The artifact is NOT self-contained: pickle stores a reference to the model
# class, not its code, so the logic comes from whatever scripts/live_wp/
# train_*.py says right now. Checking out an old .joblib therefore does not
# give you the old model. Print the provenance so this is impossible to forget.
_model_obj = art["model"] if isinstance(art, dict) else art
print(f"[{LEAGUE}] model class={type(_model_obj).__module__}.{type(_model_obj).__qualname__} "
      f"(behaviour comes from that CURRENT source file, not from the .joblib)")


def _git(*args):
    """Run a git command, returning stripped stdout or None if git is unusable."""
    if shutil.which("git") is None:
        return None
    try:
        out = subprocess.run(("git",) + args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _source_drift(model_obj, artifact_path):
    """Report whether the model's source file moved after the artifact was written.

    Documenting the provenance hazard is not the same as detecting it. Because
    the pickle only references the class, a training script edited after the
    last retrain silently changes what the artifact does. Git already knows
    both timestamps, so the drift is checkable rather than merely warned about.
    """
    module = type(model_obj).__module__
    source = module.replace(".", "/") + ".py"
    if _git("ls-files", "--error-unmatch", source) is None:
        return f"source {source} is not tracked by git; drift cannot be checked"
    dirty = _git("status", "--porcelain", "--", source, artifact_path) or ""
    src_t = _git("log", "-1", "--format=%ct", "--", source)
    art_t = _git("log", "-1", "--format=%ct", "--", artifact_path)
    if not src_t or not art_t:
        return f"no commit history for {source} or {artifact_path}; drift cannot be checked"
    src_sha = _git("log", "-1", "--format=%h", "--", source)
    lines = []
    if int(src_t) > int(art_t):
        lines.append(
            f"DRIFT: {source} was last committed in {src_sha}, AFTER the last commit "
            f"touching {artifact_path}. The served logic is newer than the fitted "
            f"arrays; these metrics may not describe any model that was ever trained.")
    else:
        lines.append(f"source {source} last changed in {src_sha}, at or before the artifact: no drift")
    if dirty:
        lines.append(f"UNCOMMITTED changes to {source} and/or {artifact_path}; "
                     "these numbers describe your working tree, not any commit")
    return "\n".join(f"[{LEAGUE}] {ln}" for ln in lines)


_ART_PATH = f"models/live_wp/{LEAGUE}_live_wp.joblib"
_drift = _source_drift(_model_obj, _ART_PATH)
print(_drift if _drift.startswith("[") else f"[{LEAGUE}] {_drift}")
if PROVENANCE_ONLY:
    sys.exit(1 if "DRIFT:" in _drift or "UNCOMMITTED" in _drift else 0)
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

# What we publish must be what we serve. predict_home_win_prob clips every
# served value into SERVE_CLIP, so scoring the raw model measures something no
# user ever receives. The gap is small but it is not zero, and "small" is a
# measurement, not an assumption -- so report both rather than trusting it.
p_served = np.clip(p, *SERVE_CLIP)
n_clipped = int(((p < SERVE_CLIP[0]) | (p > SERVE_CLIP[1])).sum())
print(f"[{LEAGUE}] AS-SERVED  brier={brier_score(list(p_served), yl):.6f} "
      f"log_loss={log_loss(list(p_served), yl):.6f} "
      f"(clipped {n_clipped} rows, {100 * n_clipped / max(len(p), 1):.3f}%, "
      f"raw range [{p.min():.8f}, {p.max():.8f}])")

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
