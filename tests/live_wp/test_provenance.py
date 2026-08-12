"""The provenance check must actually fire, not merely exist.

`verify_artifacts.py` is the tool used to independently re-derive published
numbers, so a silently broken drift check would be worse than none: it would
lend confidence it is not earning. These tests drive the real script through a
subprocess (it is a script, not an importable module) and assert both the
clean and the dirty verdicts.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "live_wp" / "verify_artifacts.py"
LEAGUES = ["nhl", "nfl", "nba", "mlb"]
# A stripped environment breaks the Windows socket layer at import time, so
# inherit the real one and only add what we need.
ENV = {**os.environ, "PYTHONPATH": str(REPO)}

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO / ".git").exists(),
    reason="drift detection is defined in terms of git history",
)


def _provenance(league):
    return subprocess.run(
        [sys.executable, str(SCRIPT), league, "--provenance-only"],
        cwd=REPO, capture_output=True, text=True, env=ENV, timeout=180,
    )


@pytest.mark.parametrize("league", LEAGUES)
def test_provenance_only_is_fast_and_reports_the_source_module(league):
    """It must name the file the behaviour actually comes from."""
    out = _provenance(league)
    assert f"[{league}] model class=" in out.stdout, out.stderr
    # The class lives in a real, readable source file -- that is the whole point.
    line = next(ln for ln in out.stdout.splitlines() if "model class=" in ln)
    module = line.split("model class=")[1].split(" ")[0].rsplit(".", 1)[0]
    assert (REPO / (module.replace(".", "/") + ".py")).exists(), module


@pytest.mark.parametrize("league", LEAGUES)
def test_provenance_reaches_a_verdict(league):
    """Silence is the failure mode we care about: it must say drift or no drift."""
    out = _provenance(league)
    assert ("no drift" in out.stdout or "DRIFT:" in out.stdout
            or "cannot be checked" in out.stdout), out.stdout


@pytest.mark.parametrize("league", LEAGUES)
def test_exit_code_matches_the_verdict(league):
    """Non-zero exit is what makes this usable in a pre-publish check."""
    out = _provenance(league)
    flagged = "DRIFT:" in out.stdout or "UNCOMMITTED" in out.stdout
    assert out.returncode == (1 if flagged else 0), out.stdout


def test_uncommitted_source_is_flagged(tmp_path):
    """Editing a training script must flag the league it serves.

    This is the hazard itself: an edit here changes production with no retrain,
    so the checker has to notice a dirty working tree, not just old commits.
    """
    target = REPO / "scripts" / "live_wp" / "train_nfl.py"
    original = target.read_bytes()
    backup = tmp_path / "train_nfl.py.bak"
    backup.write_bytes(original)
    try:
        target.write_bytes(original + b"\n# provenance drift probe\n")
        out = _provenance("nfl")
        assert "UNCOMMITTED" in out.stdout, out.stdout
        assert out.returncode == 1
    finally:
        target.write_bytes(backup.read_bytes())
    # And the flag must clear once the edit is reverted, or it is just noise.
    assert target.read_bytes() == original
    assert "UNCOMMITTED" not in _provenance("nfl").stdout


def test_missing_seasons_is_an_error_not_a_silent_partial_run():
    out = subprocess.run([sys.executable, str(SCRIPT), "nfl"], cwd=REPO,
                         capture_output=True, text=True, env=ENV, timeout=180)
    assert out.returncode != 0
    assert "usage:" in (out.stderr + out.stdout)


def _fmt_prob():
    """Pull _fmt_prob out of the script, which runs a full re-score on import.

    Located by AST rather than by line offsets so the test does not silently
    start checking the wrong code when the script is edited.
    """
    import ast
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_fmt_prob")
    ns = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<fmt>", "exec"), ns)
    return ns["_fmt_prob"]


@pytest.mark.parametrize("value,dp,expected", [
    # The case this exists for: a bounded near-certainty must not be printed
    # as certainty. 1 - 1e-9 is what the MLB walk-off rule emits.
    (1.0 - 1e-9, 3, "1-1e-09"),
    (1.0 - 1e-9, 4, "1-1e-09"),
    (1.0 - 1e-9, 8, "1-1e-09"),
    # A genuine 1.0 must stay visibly distinct from the bounded value.
    (1.0, 3, "1.000"),
    (0.0, 3, "0.000"),
    # Ordinary values must not be disfigured.
    (0.5, 3, "0.500"),
    (0.891, 3, "0.891"),
    (0.9994, 3, "0.999"),
    # Just inside the rounding shadow, so it must switch representation.
    (0.9996, 3, "1-4e-04"),
    (1e-6, 8, "0.00000100"),
])
def test_fmt_prob_never_rounds_a_bound_into_a_certainty(value, dp, expected):
    assert _fmt_prob()(value, dp) == expected


def test_fmt_prob_distinguishes_exact_one_from_bounded_one():
    """The whole point: these two must never render identically."""
    f = _fmt_prob()
    for dp in (2, 3, 4, 6, 8):
        assert f(1.0, dp) != f(1.0 - 1e-9, dp)
        assert f(0.0, dp) != f(1e-9, dp)

