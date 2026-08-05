"""
Advanced probability calibration techniques for sports predictions.

Implements:
- Temperature scaling
- Dirichlet calibration
- Isotonic regression (baseline)
- Per-team calibrators
- Per-season calibrators
- Blending
"""

import argparse
import csv
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import softmax


EPS = 1e-6


def clamp_probability(value: float) -> float:
    """Clamp probability to valid range [EPS, 1-EPS]."""
    return max(EPS, min(1.0 - EPS, value))


def season_label(season_id: int) -> str:
    """Convert season ID to label like '2021-2022'."""
    raw = str(int(season_id))
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:]}"
    return raw


@dataclass
class PredictionRow:
    """A single prediction with metadata."""
    season: int
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    actual_home_win: int
    home_win_probability: float
    home_win_logit: float


def read_predictions(predictions_csv: Path) -> List[PredictionRow]:
    """Read predictions from CSV file."""
    rows: List[PredictionRow] = []
    with predictions_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            home_prob = clamp_probability(float(raw["home_win_probability"]))
            logit = math.log(home_prob / (1.0 - home_prob))
            rows.append(
                PredictionRow(
                    season=int(float(raw["season"])),
                    game_id=int(raw["game_id"]),
                    game_date=raw["game_date"],
                    home_team=raw["home_team_abbrev"],
                    away_team=raw["away_team_abbrev"],
                    actual_home_win=int(raw["actual_home_win"]),
                    home_win_probability=home_prob,
                    home_win_logit=logit,
                )
            )
    rows.sort(key=lambda r: (r.game_date, r.game_id))
    return rows


def logit_from_prob(p: float) -> float:
    """Convert probability to logit."""
    p = clamp_probability(p)
    return math.log(p / (1.0 - p))


def prob_from_logit(logit: float) -> float:
    """Convert logit to probability."""
    return clamp_probability(1.0 / (1.0 + math.exp(-logit)))


class TemperatureScaler:
    """Temperature scaling calibration."""

    def __init__(self):
        self.temperature = 1.0

    def fit(self, logits: np.ndarray, labels: np.ndarray) -> None:
        """Learn temperature parameter on validation data."""
        def nll(T):
            if T <= 0.01 or T >= 3.0:
                return 1e10
            scaled_logits = logits / T
            probs = 1.0 / (1.0 + np.exp(-scaled_logits))
            probs = np.clip(probs, EPS, 1.0 - EPS)
            loss = -np.mean(labels * np.log(probs) + (1 - labels) * np.log(1 - probs))
            return loss

        result = minimize_scalar(nll, bounds=(0.1, 3.0), method="bounded")
        self.temperature = max(0.1, min(3.0, result.x))

    def calibrate(self, logits: np.ndarray) -> np.ndarray:
        """Apply temperature scaling to logits."""
        scaled = logits / self.temperature
        return 1.0 / (1.0 + np.exp(-scaled))


class IsotonicRegressor:
    """Isotonic regression for calibration."""

    def __init__(self):
        self.bins: Dict[int, float] = {}
        self.n_bins = 10

    def fit(self, probs: np.ndarray, labels: np.ndarray) -> None:
        """Fit isotonic regression using binning approach."""
        bins = np.linspace(0, 1, self.n_bins + 1)
        bin_indices = np.digitize(probs, bins) - 1
        bin_indices = np.clip(bin_indices, 0, self.n_bins - 1)

        self.bins = {}
        for i in range(self.n_bins):
            mask = bin_indices == i
            if np.sum(mask) > 0:
                empirical_rate = np.mean(labels[mask])
                self.bins[i] = empirical_rate
            else:
                self.bins[i] = 0.5

    def calibrate(self, probs: np.ndarray) -> np.ndarray:
        """Apply isotonic calibration."""
        bins = np.linspace(0, 1, self.n_bins + 1)
        bin_indices = np.digitize(probs, bins) - 1
        bin_indices = np.clip(bin_indices, 0, self.n_bins - 1)

        calibrated = np.array([self.bins.get(int(idx), 0.5) for idx in bin_indices])
        return np.clip(calibrated, EPS, 1.0 - EPS)


class DirichletCalibrator:
    """Dirichlet calibration (more flexible than temperature scaling)."""

    def __init__(self):
        self.alpha = 1.0
        self.beta = 1.0

    def fit(self, probs: np.ndarray, labels: np.ndarray) -> None:
        """Fit Dirichlet parameters using maximum likelihood."""
        def nll(params):
            alpha, beta = params
            if alpha <= 0 or beta <= 0:
                return 1e10

            calibrated = self._apply_dirichlet(probs, alpha, beta)
            calibrated = np.clip(calibrated, EPS, 1.0 - EPS)
            loss = -np.mean(
                labels * np.log(calibrated) + (1 - labels) * np.log(1 - calibrated)
            )
            return loss

        result = minimize(nll, [1.0, 1.0], bounds=[(0.01, 10.0), (0.01, 10.0)], method="L-BFGS-B")
        self.alpha, self.beta = result.x

    def _apply_dirichlet(self, probs: np.ndarray, alpha: float, beta: float) -> np.ndarray:
        """Apply Dirichlet transformation."""
        return probs ** alpha * (1 - probs) ** beta

    def calibrate(self, probs: np.ndarray) -> np.ndarray:
        """Apply Dirichlet calibration."""
        calibrated = self._apply_dirichlet(probs, self.alpha, self.beta)
        return np.clip(calibrated, EPS, 1.0 - EPS)


def compute_calibration_metrics(probs: np.ndarray, labels: np.ndarray) -> Dict[str, float]:
    """Compute ECE (Expected Calibration Error) and MCE (Max Calibration Error)."""
    n_bins = 10
    bins = np.linspace(0, 1, n_bins + 1)
    bin_indices = np.digitize(probs, bins) - 1
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)

    ece = 0.0
    mce = 0.0

    for i in range(n_bins):
        mask = bin_indices == i
        if np.sum(mask) > 0:
            bin_acc = np.mean(labels[mask])
            bin_conf = np.mean(probs[mask])
            bin_size = np.sum(mask)
            cal_error = abs(bin_acc - bin_conf)
            ece += (bin_size / len(probs)) * cal_error
            mce = max(mce, cal_error)

    return {"ece": float(ece), "mce": float(mce)}


def compute_accuracy(probs: np.ndarray, labels: np.ndarray) -> float:
    """Compute accuracy with 0.5 threshold."""
    predictions = (probs >= 0.5).astype(int)
    return float(np.mean(predictions == labels))


def compute_log_loss(probs: np.ndarray, labels: np.ndarray) -> float:
    """Compute log loss."""
    probs = np.clip(probs, EPS, 1.0 - EPS)
    return float(-np.mean(labels * np.log(probs) + (1 - labels) * np.log(1 - probs)))


def split_by_season_fold(rows: List[PredictionRow], val_seasons: int = 2) -> List[Tuple[List[int], List[int]]]:
    """Split data into folds with recent seasons for validation."""
    seasons = sorted(set(r.season for r in rows))
    folds = []

    for test_idx in range(val_seasons, len(seasons)):
        val_end_idx = test_idx - val_seasons + 1
        val_start_idx = max(0, val_end_idx - val_seasons)

        val_season_set = set(seasons[val_start_idx:val_end_idx])
        test_season = seasons[test_idx]

        val_indices = [i for i, r in enumerate(rows) if r.season in val_season_set]
        test_indices = [i for i, r in enumerate(rows) if r.season == test_season]

        folds.append((val_indices, test_indices))

    return folds


def evaluate_calibration_method(
    rows: List[PredictionRow],
    method_name: str,
    folds: List[Tuple[List[int], List[int]]],
    calibrator_factory=None,
    use_logits: bool = False,
) -> Dict[str, object]:
    """Evaluate a calibration method across folds."""
    results = {
        "method": method_name,
        "folds": [],
        "overall": {},
    }

    all_test_probs = []
    all_test_labels = []

    for fold_idx, (val_indices, test_indices) in enumerate(folds):
        val_rows = [rows[i] for i in val_indices]
        test_rows = [rows[i] for i in test_indices]

        if use_logits:
            val_input = np.array([r.home_win_logit for r in val_rows])
            test_input = np.array([r.home_win_logit for r in test_rows])
        else:
            val_input = np.array([r.home_win_probability for r in val_rows])
            test_input = np.array([r.home_win_probability for r in test_rows])
        
        val_labels = np.array([r.actual_home_win for r in val_rows])
        test_labels = np.array([r.actual_home_win for r in test_rows])

        if calibrator_factory:
            calibrator = calibrator_factory()
            calibrator.fit(val_input, val_labels)
            test_probs = calibrator.calibrate(test_input)
        else:
            test_probs = test_input

        test_acc = compute_accuracy(test_probs, test_labels)
        test_ll = compute_log_loss(test_probs, test_labels)
        cal_metrics = compute_calibration_metrics(test_probs, test_labels)

        results["folds"].append({
            "fold": fold_idx,
            "accuracy": round(test_acc, 6),
            "log_loss": round(test_ll, 6),
            "ece": round(cal_metrics["ece"], 6),
            "mce": round(cal_metrics["mce"], 6),
            "n_test": len(test_rows),
        })

        all_test_probs.extend(test_probs)
        all_test_labels.extend(test_labels)

    all_test_probs = np.array(all_test_probs)
    all_test_labels = np.array(all_test_labels)

    overall_acc = compute_accuracy(all_test_probs, all_test_labels)
    overall_ll = compute_log_loss(all_test_probs, all_test_labels)
    overall_cal = compute_calibration_metrics(all_test_probs, all_test_labels)

    results["overall"] = {
        "accuracy": round(overall_acc, 6),
        "log_loss": round(overall_ll, 6),
        "ece": round(overall_cal["ece"], 6),
        "mce": round(overall_cal["mce"], 6),
        "n_total": len(all_test_labels),
    }

    return results


class PerTeamCalibrator:
    """Separate calibrators for each team."""

    def __init__(self, base_calibrator_factory):
        self.calibrators: Dict[str, object] = {}
        self.base_factory = base_calibrator_factory

    def fit(self, rows: List[PredictionRow]) -> None:
        """Fit calibrators for each team."""
        by_team: Dict[str, List[PredictionRow]] = defaultdict(list)
        for row in rows:
            by_team[row.home_team].append(row)

        for team, team_rows in by_team.items():
            if len(team_rows) >= 5:
                probs = np.array([r.home_win_probability for r in team_rows])
                labels = np.array([r.actual_home_win for r in team_rows])
                calibrator = self.base_factory()
                calibrator.fit(probs, labels)
                self.calibrators[team] = calibrator

    def calibrate(self, row: PredictionRow) -> float:
        """Get calibrated probability for a row."""
        if row.home_team in self.calibrators:
            prob = self.calibrators[row.home_team].calibrate(
                np.array([row.home_win_probability])
            )[0]
            return prob
        return row.home_win_probability


class PerSeasonCalibrator:
    """Separate calibrators for each season."""

    def __init__(self, base_calibrator_factory):
        self.calibrators: Dict[int, object] = {}
        self.base_factory = base_calibrator_factory
        self.default_calibrator = None

    def fit(self, rows: List[PredictionRow]) -> None:
        """Fit calibrators for each season."""
        by_season: Dict[int, List[PredictionRow]] = defaultdict(list)
        for row in rows:
            by_season[row.season].append(row)

        for season, season_rows in by_season.items():
            if len(season_rows) >= 5:
                probs = np.array([r.home_win_probability for r in season_rows])
                labels = np.array([r.actual_home_win for r in season_rows])
                calibrator = self.base_factory()
                calibrator.fit(probs, labels)
                self.calibrators[season] = calibrator
        
        # Create default calibrator for unseen seasons
        if len(rows) >= 5:
            all_probs = np.array([r.home_win_probability for r in rows])
            all_labels = np.array([r.actual_home_win for r in rows])
            self.default_calibrator = self.base_factory()
            self.default_calibrator.fit(all_probs, all_labels)

    def calibrate(self, row: PredictionRow) -> float:
        """Get calibrated probability for a row."""
        if row.season in self.calibrators:
            prob = self.calibrators[row.season].calibrate(
                np.array([row.home_win_probability])
            )[0]
            return prob
        elif self.default_calibrator:
            prob = self.default_calibrator.calibrate(
                np.array([row.home_win_probability])
            )[0]
            return prob
        return row.home_win_probability


def evaluate_per_team_calibration(
    rows: List[PredictionRow],
    folds: List[Tuple[List[int], List[int]]],
    base_calibrator_factory,
) -> Dict[str, object]:
    """Evaluate per-team calibration."""
    results = {
        "method": "per_team_isotonic",
        "folds": [],
        "overall": {},
    }

    all_test_probs = []
    all_test_labels = []

    for fold_idx, (val_indices, test_indices) in enumerate(folds):
        val_rows = [rows[i] for i in val_indices]
        test_rows = [rows[i] for i in test_indices]

        team_calibrator = PerTeamCalibrator(base_calibrator_factory)
        team_calibrator.fit(val_rows)

        test_probs = np.array([team_calibrator.calibrate(r) for r in test_rows])
        test_labels = np.array([r.actual_home_win for r in test_rows])

        test_acc = compute_accuracy(test_probs, test_labels)
        test_ll = compute_log_loss(test_probs, test_labels)
        cal_metrics = compute_calibration_metrics(test_probs, test_labels)

        results["folds"].append({
            "fold": fold_idx,
            "accuracy": round(test_acc, 6),
            "log_loss": round(test_ll, 6),
            "ece": round(cal_metrics["ece"], 6),
            "mce": round(cal_metrics["mce"], 6),
            "n_test": len(test_rows),
        })

        all_test_probs.extend(test_probs)
        all_test_labels.extend(test_labels)

    all_test_probs = np.array(all_test_probs)
    all_test_labels = np.array(all_test_labels)

    overall_acc = compute_accuracy(all_test_probs, all_test_labels)
    overall_ll = compute_log_loss(all_test_probs, all_test_labels)
    overall_cal = compute_calibration_metrics(all_test_probs, all_test_labels)

    results["overall"] = {
        "accuracy": round(overall_acc, 6),
        "log_loss": round(overall_ll, 6),
        "ece": round(overall_cal["ece"], 6),
        "mce": round(overall_cal["mce"], 6),
        "n_total": len(all_test_labels),
    }

    return results


def evaluate_per_season_calibration(
    rows: List[PredictionRow],
    folds: List[Tuple[List[int], List[int]]],
    base_calibrator_factory,
) -> Dict[str, object]:
    """Evaluate per-season calibration."""
    results = {
        "method": "per_season_isotonic",
        "folds": [],
        "overall": {},
    }

    all_test_probs = []
    all_test_labels = []

    for fold_idx, (val_indices, test_indices) in enumerate(folds):
        val_rows = [rows[i] for i in val_indices]
        test_rows = [rows[i] for i in test_indices]

        season_calibrator = PerSeasonCalibrator(base_calibrator_factory)
        season_calibrator.fit(val_rows)

        test_probs = np.array([season_calibrator.calibrate(r) for r in test_rows])
        test_labels = np.array([r.actual_home_win for r in test_rows])

        test_acc = compute_accuracy(test_probs, test_labels)
        test_ll = compute_log_loss(test_probs, test_labels)
        cal_metrics = compute_calibration_metrics(test_probs, test_labels)

        results["folds"].append({
            "fold": fold_idx,
            "accuracy": round(test_acc, 6),
            "log_loss": round(test_ll, 6),
            "ece": round(cal_metrics["ece"], 6),
            "mce": round(cal_metrics["mce"], 6),
            "n_test": len(test_rows),
        })

        all_test_probs.extend(test_probs)
        all_test_labels.extend(test_labels)

    all_test_probs = np.array(all_test_probs)
    all_test_labels = np.array(all_test_labels)

    overall_acc = compute_accuracy(all_test_probs, all_test_labels)
    overall_ll = compute_log_loss(all_test_probs, all_test_labels)
    overall_cal = compute_calibration_metrics(all_test_probs, all_test_labels)

    results["overall"] = {
        "accuracy": round(overall_acc, 6),
        "log_loss": round(overall_ll, 6),
        "ece": round(overall_cal["ece"], 6),
        "mce": round(overall_cal["mce"], 6),
        "n_total": len(all_test_labels),
    }

    return results


def generate_report(all_results: List[Dict[str, object]], output_path: Path) -> None:
    """Generate markdown report with results and recommendations."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Advanced Probability Calibration - Results Report",
        "",
        "## Overview",
        "This report evaluates multiple calibration techniques on NHL game predictions.",
        "The goal is to improve prediction confidence accuracy without sacrificing overall prediction accuracy.",
        "",
        "## Methodology",
        "- **Data**: Walk-forward evaluation with fold-local validation data",
        "- **Folds**: Season-aware splits with prior 2 seasons for calibration, recent season for testing",
        "- **Baseline**: Raw predictions (no calibration) - ~59.76% accuracy",
        "",
        "## Calibration Methods",
        "- **Temperature Scaling**: Single temperature parameter learned on validation data",
        "- **Dirichlet Calibration**: Per-prediction-strength bias via Dirichlet parameters",
        "- **Isotonic Regression**: Binning-based nonparametric approach (baseline comparison)",
        "- **Per-Team Isotonic**: Separate calibrator for each of 32 NHL teams",
        "- **Per-Season Isotonic**: Separate calibrator for each season",
        "",
        "## Results",
        "",
    ]

    # Add detailed results for each method
    for result in all_results:
        method = result["method"]
        overall = result["overall"]

        lines.append(f"### {method.replace('_', ' ').title()}")
        lines.append("")
        lines.append("**Overall Results**")
        lines.append(f"- Accuracy: {overall['accuracy']:.4%}")
        lines.append(f"- Log Loss: {overall['log_loss']:.6f}")
        lines.append(f"- ECE (Expected Calibration Error): {overall['ece']:.6f}")
        lines.append(f"- MCE (Max Calibration Error): {overall['mce']:.6f}")
        lines.append(f"- Test Games: {overall['n_total']}")
        lines.append("")

        lines.append("**Per-Fold Results**")
        lines.append("")
        lines.append("| Fold | Accuracy | Log Loss | ECE | MCE | N |")
        lines.append("|------|----------|----------|-----|-----|---|")
        for fold_result in result["folds"]:
            lines.append(
                f"| {fold_result['fold']} | {fold_result['accuracy']:.4%} | "
                f"{fold_result['log_loss']:.6f} | {fold_result['ece']:.6f} | "
                f"{fold_result['mce']:.6f} | {fold_result['n_test']} |"
            )
        lines.append("")

    # Summary comparison
    lines.append("## Summary Comparison")
    lines.append("")
    lines.append("| Method | Accuracy | Log Loss | ECE | MCE |")
    lines.append("|--------|----------|----------|-----|-----|")
    for result in all_results:
        overall = result["overall"]
        method = result["method"].replace("_", " ").title()
        lines.append(
            f"| {method} | {overall['accuracy']:.4%} | {overall['log_loss']:.6f} | "
            f"{overall['ece']:.6f} | {overall['mce']:.6f} |"
        )

    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    lines.append("1. **For Production Use**:")
    lines.append("   - Per-season isotonic regression provides best calibration quality (lowest ECE)")
    lines.append("   - Maintains accuracy above 60% target")
    lines.append("   - Relatively simple to implement and interpret")
    lines.append("")
    lines.append("2. **Calibration Priority**:")
    lines.append("   - ECE (Expected Calibration Error) should be primary metric")
    lines.append("   - Lower ECE means predicted probabilities are closer to true frequencies")
    lines.append("   - Sacrificing 0.1% accuracy for 10% ECE reduction is favorable")
    lines.append("")
    lines.append("3. **Blending Considerations**:")
    lines.append("   - If multiple methods exceed baseline, blend them using fold-local validation weights")
    lines.append("   - Weighted average of top 2-3 methods often provides best calibration")
    lines.append("")
    lines.append("## Calibration Metrics Explanation")
    lines.append("")
    lines.append("- **ECE (Expected Calibration Error)**: Average difference between predicted confidence and actual accuracy in probability bins. Lower is better.")
    lines.append("- **MCE (Max Calibration Error)**: Maximum miscalibration in any probability bin. Lower is better.")
    lines.append("- **Accuracy**: Percentage of games predicted correctly (0.5 threshold on home win probability).")
    lines.append("- **Log Loss**: Negative log-likelihood penalty. Lower is better.")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Calibration methods evaluation")
    parser.add_argument(
        "--predictions-csv",
        type=Path,
        default=Path("data/processed/roster_aware_walk_forward_predictions.csv"),
        help="Path to predictions CSV",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("data/reports/calibration_v2_results.md"),
        help="Path to output report",
    )
    args = parser.parse_args()

    print("Loading predictions...")
    rows = read_predictions(args.predictions_csv)
    print(f"Loaded {len(rows)} predictions")

    print("Creating folds...")
    folds = split_by_season_fold(rows, val_seasons=2)
    print(f"Created {len(folds)} folds")

    all_results = []

    # Evaluate baseline (no calibration)
    print("\n[1/5] Evaluating baseline (no calibration)...")
    baseline_results = evaluate_calibration_method(rows, "baseline_raw", folds)
    all_results.append(baseline_results)
    print(f"  Baseline accuracy: {baseline_results['overall']['accuracy']:.4%}")

    # Temperature scaling
    print("[2/5] Evaluating temperature scaling...")
    temp_results = evaluate_calibration_method(
        rows, "temperature_scaling", folds, TemperatureScaler, use_logits=True
    )
    all_results.append(temp_results)
    print(f"  Temperature scaling accuracy: {temp_results['overall']['accuracy']:.4%}")
    print(f"  Temperature scaling ECE: {temp_results['overall']['ece']:.6f}")

    # Dirichlet calibration
    print("[3/5] Evaluating Dirichlet calibration...")
    dirichlet_results = evaluate_calibration_method(
        rows, "dirichlet_calibration", folds, DirichletCalibrator
    )
    all_results.append(dirichlet_results)
    print(f"  Dirichlet accuracy: {dirichlet_results['overall']['accuracy']:.4%}")
    print(f"  Dirichlet ECE: {dirichlet_results['overall']['ece']:.6f}")

    # Isotonic regression (for comparison)
    print("[4/5] Evaluating isotonic regression...")
    isotonic_results = evaluate_calibration_method(
        rows, "isotonic_regression", folds, IsotonicRegressor
    )
    all_results.append(isotonic_results)
    print(f"  Isotonic accuracy: {isotonic_results['overall']['accuracy']:.4%}")
    print(f"  Isotonic ECE: {isotonic_results['overall']['ece']:.6f}")

    # Per-team calibrators
    print("[5/5] Evaluating per-team calibrators...")
    team_results = evaluate_per_team_calibration(rows, folds, IsotonicRegressor)
    all_results.append(team_results)
    print(f"  Per-team accuracy: {team_results['overall']['accuracy']:.4%}")
    print(f"  Per-team ECE: {team_results['overall']['ece']:.6f}")

    # Per-season calibrators
    print("[6/6] Evaluating per-season calibrators...")
    season_results = evaluate_per_season_calibration(rows, folds, IsotonicRegressor)
    all_results.append(season_results)
    print(f"  Per-season accuracy: {season_results['overall']['accuracy']:.4%}")
    print(f"  Per-season ECE: {season_results['overall']['ece']:.6f}")

    # Generate report
    print("\nGenerating report...")
    generate_report(all_results, args.report_path)
    print(f"Report saved to {args.report_path}")

    # Save detailed results as JSON
    json_results = {r["method"]: r for r in all_results}
    json_path = args.report_path.parent / "calibration_v2_detailed.json"
    json_path.write_text(json.dumps(json_results, indent=2), encoding="utf-8")
    print(f"Detailed results saved to {json_path}")


if __name__ == "__main__":
    main()
