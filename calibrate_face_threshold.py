"""Suggest a face-score threshold from labelled comparison CSV data.

CSV columns: score,genuine (genuine is true/false or 1/0). One row per
comparison, collected under representative capture conditions. This script
does not collect data, claim model accuracy, or edit config.py.
"""
from __future__ import annotations
import argparse
import csv
import math
from pathlib import Path


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "genuine"}: return True
    if normalized in {"false", "0", "no", "impostor"}: return False
    raise ValueError(f"Invalid genuine label {value!r}; use true/false or 1/0")


def load_scores(path: Path) -> list[tuple[float, bool]]:
    """Read and validate (score, is_genuine) rows from a labelled CSV."""
    rows: list[tuple[float, bool]] = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"score", "genuine"}.issubset(reader.fieldnames):
            raise ValueError("CSV must include score and genuine columns")
        for line, row in enumerate(reader, start=2):
            score = float(row["score"])
            if not math.isfinite(score) or not 0 <= score <= 100:
                raise ValueError(f"Invalid score on CSV line {line}: expected 0..100")
            rows.append((score, parse_bool(row["genuine"])))
    return rows


def suggest_threshold(path: Path, target_far: float) -> dict[str, float | int]:
    if not 0 <= target_far <= 1: raise ValueError("target FAR must be between 0 and 1")
    rows = load_scores(path)
    genuine_count = sum(is_genuine for _, is_genuine in rows)
    impostor_count = len(rows) - genuine_count
    if not genuine_count or not impostor_count:
        raise ValueError("Need at least one genuine and one impostor comparison")
    # Lowest qualifying threshold minimizes false rejections at the chosen FAR.
    candidates = sorted({score for score, _ in rows} | {0.0, 100.0})
    qualifying = []
    for threshold in candidates:
        false_accepts = sum(score >= threshold and not genuine for score, genuine in rows)
        false_rejects = sum(score < threshold and genuine for score, genuine in rows)
        far = false_accepts / impostor_count
        if far <= target_far:
            qualifying.append((threshold, far, false_rejects / genuine_count))
    if not qualifying:
        raise ValueError("No threshold from 0..100 meets the target FAR for this dataset")
    threshold, far, frr = qualifying[0]
    return {"threshold": threshold, "target_far": target_far, "observed_far": far,
            "observed_frr": frr, "comparisons": len(rows), "genuine": genuine_count,
            "impostor": impostor_count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--target-far", type=float, default=0.01,
                        help="maximum impostor acceptance fraction (default 0.01)")
    args = parser.parse_args()
    try:
        result = suggest_threshold(args.csv_path, args.target_far)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    for key, value in result.items(): print(f"{key}: {value}")
    print("Review this suggestion against the dataset and intended use; it is not a security guarantee.")
    return 0


if __name__ == "__main__": raise SystemExit(main())
