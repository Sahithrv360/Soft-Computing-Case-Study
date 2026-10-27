"""Error-rate helpers using the definitions in the reference paper's Table 4 (p. 18).

FAR = false accepts / impostor trials, FRR = false rejects / genuine trials,
GAR = 1 - FRR, EER = the operating point where FAR == FRR. Nothing here
fabricates data: every number is computed from labelled comparisons that the
operator supplies, and small samples are flagged.
"""
from __future__ import annotations

import math

MIN_RECOMMENDED_TRIALS = 100   # rule of thumb flag, not a statistical guarantee


def rates_at_threshold(rows: list[tuple[float, bool]], threshold: float) -> dict:
    """rows are (score, is_genuine); a trial is accepted when score >= threshold."""
    genuine = [s for s, g in rows if g]
    impostor = [s for s, g in rows if not g]
    if not genuine or not impostor:
        raise ValueError("need at least one genuine and one impostor trial")
    far = sum(s >= threshold for s in impostor) / len(impostor)
    frr = sum(s < threshold for s in genuine) / len(genuine)
    return {"threshold": threshold, "FAR": far, "FRR": frr, "GAR": 1.0 - frr}


def threshold_sweep(rows: list[tuple[float, bool]]) -> list[dict]:
    """FAR/FRR/GAR at every observed score (plus 0 and 100): the trade-off in the paper's Fig. 7."""
    candidates = sorted({s for s, _ in rows} | {0.0, 100.0})
    return [rates_at_threshold(rows, t) for t in candidates]


def equal_error_rate(rows: list[tuple[float, bool]]) -> dict:
    """Approximate EER: the swept point with the smallest |FAR-FRR| (mean of the two)."""
    best = min(threshold_sweep(rows), key=lambda r: (abs(r["FAR"] - r["FRR"]), r["threshold"]))
    return {"EER": (best["FAR"] + best["FRR"]) / 2, "threshold": best["threshold"],
            "FAR": best["FAR"], "FRR": best["FRR"]}


def rule_of_three_upper_bound(trials: int) -> float | None:
    """Approx. 95% upper bound on a rate observed as 0 errors in ``trials`` trials (3/N)."""
    return 3.0 / trials if trials > 0 else None


def sample_warnings(genuine: int, impostor: int) -> list[str]:
    notes = []
    if genuine < MIN_RECOMMENDED_TRIALS:
        notes.append(f"Only {genuine} genuine trials: FRR/GAR are very uncertain.")
    if impostor < MIN_RECOMMENDED_TRIALS:
        notes.append(f"Only {impostor} impostor trials: FAR is very uncertain "
                     f"(0 observed false accepts only bounds FAR below about "
                     f"{3 / max(impostor, 1):.1%} at ~95% confidence).")
    return notes


def confusion_metrics(tp: int, fp: int, tn: int, fn: int) -> dict:
    div = lambda a, b: a / b if b else 0.0
    precision, recall = div(tp, tp + fp), div(tp, tp + fn)
    return {"confusion_matrix": {"TP": tp, "FP": fp, "TN": tn, "FN": fn},
            "accuracy": div(tp + tn, tp + fp + tn + fn), "precision": precision,
            "recall": recall, "f1": div(2 * precision * recall, precision + recall),
            "FAR": div(fp, fp + tn), "FRR": div(fn, fn + tp), "GAR": 1.0 - div(fn, fn + tp) if (fn + tp) else 0.0,
            "genuine_trials": tp + fn, "impostor_trials": fp + tn,
            "warnings": sample_warnings(tp + fn, fp + tn)}
