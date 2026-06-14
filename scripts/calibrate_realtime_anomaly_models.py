#!/usr/bin/env python3
"""Prepare optional ML calibration reports for realtime anomaly models."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3
from typing import Any

from metroliza.industrial.anomaly.optional_dependencies import (
    load_sklearn_ensemble,
    optional_dependency_available,
)


DEFAULT_CONTAMINATION_CANDIDATES = (0.005, 0.01, 0.02, 0.05)
OPTIONAL_DEPENDENCY_GUIDANCE = {
    "package": "scikit-learn",
    "import": "sklearn",
    "install": "python -m pip install scikit-learn",
    "dry_run": "Use --dry-run to generate dependency-free summaries without ML fitting.",
    "purpose": "Actual ML calibration uses sklearn.ensemble.IsolationForest.",
}


@dataclass(frozen=True)
class CalibrationRequest:
    database: str
    signal_id: int | None
    signal_key: str | None
    source_profile_id: int | None
    training_start: str
    training_end: str
    validation_start: str
    validation_end: str
    contamination_candidates: tuple[float, ...]
    output: Path
    dry_run: bool


@dataclass(frozen=True)
class SignalSelection:
    id: int | None
    source_profile_id: int | None
    signal_key: str | None
    metric_name: str | None
    unit: str | None = None
    nominal: float | None = None
    lsl: float | None = None
    usl: float | None = None
    lower_warning: float | None = None
    upper_warning: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_profile_id": self.source_profile_id,
            "signal_key": self.signal_key,
            "metric_name": self.metric_name,
            "unit": self.unit,
            "nominal": self.nominal,
            "lsl": self.lsl,
            "usl": self.usl,
            "lower_warning": self.lower_warning,
            "upper_warning": self.upper_warning,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a realtime anomaly ML calibration report. Dry-run mode is "
            "dependency-free and does not fit sklearn models."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--db", required=True, help="Path to the Metroliza SQLite database.")
    signal = parser.add_mutually_exclusive_group(required=True)
    signal.add_argument("--signal-id", type=int, help="industrial_signal_definitions.id to calibrate.")
    signal.add_argument(
        "--signal-key",
        help=(
            "Signal key to calibrate. Pair with --source-profile-id when the key "
            "is not globally unique."
        ),
    )
    parser.add_argument("--source-profile-id", type=int, help="Source profile for --signal-key.")
    parser.add_argument(
        "--training-start",
        "--train-start",
        dest="training_start",
        required=True,
        help="Inclusive ISO-8601 event_time lower bound for training samples.",
    )
    parser.add_argument(
        "--training-end",
        "--train-end",
        dest="training_end",
        required=True,
        help="Exclusive ISO-8601 event_time upper bound for training samples.",
    )
    parser.add_argument(
        "--validation-start",
        "--valid-start",
        dest="validation_start",
        required=True,
        help="Inclusive ISO-8601 event_time lower bound for validation samples.",
    )
    parser.add_argument(
        "--validation-end",
        "--valid-end",
        dest="validation_end",
        required=True,
        help="Exclusive ISO-8601 event_time upper bound for validation samples.",
    )
    parser.add_argument(
        "--contamination-candidates",
        default=",".join(str(value) for value in DEFAULT_CONTAMINATION_CANDIDATES),
        help="Comma-separated candidate outlier fractions for calibration.",
    )
    parser.add_argument("--output", required=True, help="Path for the recommended config JSON report.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate metadata and empirical threshold summaries without sklearn.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    request = CalibrationRequest(
        database=args.db,
        signal_id=args.signal_id,
        signal_key=args.signal_key,
        source_profile_id=args.source_profile_id,
        training_start=args.training_start,
        training_end=args.training_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        contamination_candidates=_parse_contamination_candidates(args.contamination_candidates),
        output=Path(args.output),
        dry_run=bool(args.dry_run),
    )

    if not request.dry_run:
        _ensure_optional_ml_dependencies()

    report = build_report(request)
    request.output.parent.mkdir(parents=True, exist_ok=True)
    request.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _print_summary(report, request.output)
    return 0


def build_report(request: CalibrationRequest) -> dict[str, Any]:
    warnings: list[str] = []
    signal = SignalSelection(
        id=request.signal_id,
        source_profile_id=request.source_profile_id,
        signal_key=request.signal_key,
        metric_name=None,
    )
    training_values: list[float] = []
    validation_values: list[float] = []

    db_path = Path(request.database)
    if not db_path.exists():
        warnings.append(f"Database not found: {db_path}")
    else:
        try:
            with _connect_readonly(db_path) as connection:
                signal, signal_warnings = _resolve_signal(connection, request)
                warnings.extend(signal_warnings)
                if signal.id is not None:
                    training_values = _read_values(
                        connection,
                        signal_id=signal.id,
                        start=request.training_start,
                        end=request.training_end,
                    )
                    validation_values = _read_values(
                        connection,
                        signal_id=signal.id,
                        start=request.validation_start,
                        end=request.validation_end,
                    )
                else:
                    warnings.append("No resolved signal id; sample windows were not queried.")
        except sqlite3.Error as exc:
            warnings.append(f"Could not read calibration data from SQLite: {exc}")

    candidate_summaries = _candidate_summaries(
        request.contamination_candidates,
        training_values=training_values,
        validation_values=validation_values,
    )
    if not request.dry_run:
        candidate_summaries = _sklearn_candidate_summaries(
            request.contamination_candidates,
            training_values=training_values,
            validation_values=validation_values,
        )
    recommended_candidate = _recommended_candidate(candidate_summaries, request.contamination_candidates)

    report = {
        "schema_version": 1,
        "mode": "dry_run" if request.dry_run else "sklearn_calibration",
        "dry_run": request.dry_run,
        "database": str(db_path),
        "signal": signal.to_json(),
        "windows": {
            "training": {
                "start": request.training_start,
                "end": request.training_end,
                "summary": _value_summary(training_values),
            },
            "validation": {
                "start": request.validation_start,
                "end": request.validation_end,
                "summary": _value_summary(validation_values),
            },
        },
        "contamination_candidates": list(request.contamination_candidates),
        "candidate_summaries": candidate_summaries,
        "threshold_summary": _threshold_summary(candidate_summaries),
        "recommended_config": _recommended_config(
            request=request,
            signal=signal,
            recommended_candidate=recommended_candidate,
        ),
        "optional_dependency_guidance": OPTIONAL_DEPENDENCY_GUIDANCE,
        "warnings": warnings,
    }
    return report


def _resolve_signal(
    connection: sqlite3.Connection,
    request: CalibrationRequest,
) -> tuple[SignalSelection, list[str]]:
    warnings: list[str] = []
    if request.signal_id is not None:
        rows = connection.execute(
            """
            SELECT
                id,
                source_profile_id,
                signal_key,
                metric_name,
                unit,
                nominal,
                lsl,
                usl,
                lower_warning,
                upper_warning
            FROM industrial_signal_definitions
            WHERE id = ?
            """,
            (request.signal_id,),
        ).fetchall()
    elif request.source_profile_id is not None:
        rows = connection.execute(
            """
            SELECT
                id,
                source_profile_id,
                signal_key,
                metric_name,
                unit,
                nominal,
                lsl,
                usl,
                lower_warning,
                upper_warning
            FROM industrial_signal_definitions
            WHERE signal_key = ? AND source_profile_id = ?
            """,
            (request.signal_key, request.source_profile_id),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT
                id,
                source_profile_id,
                signal_key,
                metric_name,
                unit,
                nominal,
                lsl,
                usl,
                lower_warning,
                upper_warning
            FROM industrial_signal_definitions
            WHERE signal_key = ?
            ORDER BY source_profile_id ASC, id ASC
            """,
            (request.signal_key,),
        ).fetchall()

    if not rows:
        warnings.append("Requested signal was not found in industrial_signal_definitions.")
        return (
            SignalSelection(
                id=request.signal_id,
                source_profile_id=request.source_profile_id,
                signal_key=request.signal_key,
                metric_name=None,
            ),
            warnings,
        )
    if len(rows) > 1:
        warnings.append(
            "Signal key matched multiple source profiles; using the first match. "
            "Pass --source-profile-id to disambiguate."
        )
    return _signal_from_row(rows[0]), warnings


def _read_values(
    connection: sqlite3.Connection,
    *,
    signal_id: int,
    start: str,
    end: str,
) -> list[float]:
    rows = connection.execute(
        """
        SELECT value
        FROM industrial_samples
        WHERE signal_id = ? AND event_time >= ? AND event_time < ?
        ORDER BY event_time ASC, id ASC
        """,
        (signal_id, start, end),
    ).fetchall()
    return [float(row[0]) for row in rows]


def _candidate_summaries(
    contamination_candidates: Sequence[float],
    *,
    training_values: Sequence[float],
    validation_values: Sequence[float],
) -> list[dict[str, Any]]:
    evaluation_values = validation_values or training_values
    summaries: list[dict[str, Any]] = []
    for contamination in contamination_candidates:
        thresholds = _empirical_thresholds(training_values, contamination)
        training_flags = _count_outside(training_values, thresholds)
        validation_flags = _count_outside(evaluation_values, thresholds)
        summaries.append(
            {
                "contamination": contamination,
                "method": "empirical_two_sided_quantile",
                "thresholds": thresholds,
                "training_flagged_count": training_flags,
                "training_flagged_rate": _safe_ratio(training_flags, len(training_values)),
                "validation_flagged_count": validation_flags,
                "validation_flagged_rate": _safe_ratio(validation_flags, len(evaluation_values)),
                "validation_sample_count": len(evaluation_values),
            }
        )
    return summaries


def _sklearn_candidate_summaries(
    contamination_candidates: Sequence[float],
    *,
    training_values: Sequence[float],
    validation_values: Sequence[float],
) -> list[dict[str, Any]]:
    if len(training_values) < 2:
        raise SystemExit("Actual sklearn calibration requires at least two training samples.")

    isolation_forest_class = load_sklearn_ensemble().IsolationForest

    x_train = [[value] for value in training_values]
    evaluation_values = tuple(validation_values or training_values)
    x_validation = [[value] for value in evaluation_values]
    summaries: list[dict[str, Any]] = []
    for contamination in contamination_candidates:
        model = isolation_forest_class(contamination=contamination, random_state=42)
        model.fit(x_train)
        train_predictions = model.predict(x_train)
        validation_predictions = model.predict(x_validation)
        train_scores = [float(score) for score in model.decision_function(x_train)]
        validation_scores = [float(score) for score in model.decision_function(x_validation)]
        training_flags = sum(1 for prediction in train_predictions if int(prediction) == -1)
        validation_flags = sum(1 for prediction in validation_predictions if int(prediction) == -1)
        summaries.append(
            {
                "contamination": contamination,
                "method": "sklearn_isolation_forest",
                "score_threshold": _percentile(train_scores, contamination * 100.0),
                "training_flagged_count": training_flags,
                "training_flagged_rate": _safe_ratio(training_flags, len(training_values)),
                "validation_flagged_count": validation_flags,
                "validation_flagged_rate": _safe_ratio(validation_flags, len(evaluation_values)),
                "validation_sample_count": len(evaluation_values),
                "score_summary": {
                    "training": _value_summary(train_scores),
                    "validation": _value_summary(validation_scores),
                },
            }
        )
    return summaries


def _recommended_config(
    *,
    request: CalibrationRequest,
    signal: SignalSelection,
    recommended_candidate: dict[str, Any],
) -> dict[str, Any]:
    signal_name = signal.signal_key or f"signal_{signal.id or 'unknown'}"
    detector_key = f"ml_isolation_forest:{signal_name}"
    return {
        "detector_key": detector_key,
        "detector_type": "optional_ml_isolation_forest",
        "enabled": not request.dry_run,
        "parameters": {
            "backend": "sklearn.ensemble.IsolationForest",
            "signal_id": signal.id,
            "signal_key": signal.signal_key,
            "training_window": {
                "start": request.training_start,
                "end": request.training_end,
            },
            "validation_window": {
                "start": request.validation_start,
                "end": request.validation_end,
            },
            "contamination": recommended_candidate.get("contamination"),
            "candidate_method": recommended_candidate.get("method"),
            "empirical_thresholds": recommended_candidate.get("thresholds"),
            "score_threshold": recommended_candidate.get("score_threshold"),
        },
        "severity_map": {
            "isolation_forest_outlier": "major",
            "operator_review_required": "warning",
        },
        "notes": [
            "Dry-run reports are calibration proposals only; do not enable without validation.",
            "Persist model artifacts separately before enabling an ML detector config.",
        ],
    }


def _recommended_candidate(
    candidate_summaries: Sequence[dict[str, Any]],
    requested_candidates: Sequence[float],
) -> dict[str, Any]:
    if not candidate_summaries:
        return {"contamination": requested_candidates[0], "method": "none"}
    usable = [
        candidate
        for candidate in candidate_summaries
        if candidate.get("validation_sample_count", 0) > 0
    ]
    if not usable:
        return dict(candidate_summaries[0])
    return dict(
        min(
            usable,
            key=lambda candidate: (
                abs(
                    float(candidate.get("validation_flagged_rate", 0.0))
                    - float(candidate.get("contamination", 0.0))
                ),
                float(candidate.get("contamination", 0.0)),
            ),
        )
    )


def _threshold_summary(candidate_summaries: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for candidate in candidate_summaries:
        entry = {
            "contamination": candidate["contamination"],
            "method": candidate["method"],
            "validation_flagged_count": candidate["validation_flagged_count"],
            "validation_flagged_rate": candidate["validation_flagged_rate"],
        }
        if candidate.get("thresholds") is not None:
            entry["thresholds"] = candidate["thresholds"]
        if candidate.get("score_threshold") is not None:
            entry["score_threshold"] = candidate["score_threshold"]
        summary.append(entry)
    return summary


def _empirical_thresholds(values: Sequence[float], contamination: float) -> dict[str, float] | None:
    if not values:
        return None
    lower_percentile = contamination * 50.0
    upper_percentile = 100.0 - lower_percentile
    return {
        "low": _percentile(values, lower_percentile),
        "high": _percentile(values, upper_percentile),
        "low_percentile": lower_percentile,
        "high_percentile": upper_percentile,
    }


def _value_summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    sorted_values = sorted(float(value) for value in values)
    count = len(sorted_values)
    return {
        "count": count,
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "mean": sum(sorted_values) / count,
        "stddev": _sample_stddev(sorted_values),
        "p01": _percentile(sorted_values, 1.0),
        "p05": _percentile(sorted_values, 5.0),
        "p50": _percentile(sorted_values, 50.0),
        "p95": _percentile(sorted_values, 95.0),
        "p99": _percentile(sorted_values, 99.0),
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("Cannot compute percentile for empty values.")
    sorted_values = sorted(float(value) for value in values)
    bounded = min(100.0, max(0.0, float(percentile)))
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (bounded / 100.0) * (len(sorted_values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    weight = rank - lower
    return sorted_values[lower] + ((sorted_values[upper] - sorted_values[lower]) * weight)


def _sample_stddev(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _count_outside(
    values: Sequence[float],
    thresholds: dict[str, float] | None,
) -> int:
    if thresholds is None:
        return 0
    low = thresholds["low"]
    high = thresholds["high"]
    return sum(1 for value in values if value < low or value > high)


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _signal_from_row(row: sqlite3.Row | tuple[Any, ...]) -> SignalSelection:
    return SignalSelection(
        id=int(row[0]),
        source_profile_id=int(row[1]),
        signal_key=str(row[2]),
        metric_name=str(row[3]),
        unit=row[4],
        nominal=_optional_float(row[5]),
        lsl=_optional_float(row[6]),
        usl=_optional_float(row[7]),
        lower_warning=_optional_float(row[8]),
        upper_warning=_optional_float(row[9]),
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _parse_contamination_candidates(raw: str) -> tuple[float, ...]:
    candidates: list[float] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            contamination = float(value)
        except ValueError as exc:
            raise SystemExit(f"Invalid contamination candidate: {value!r}") from exc
        if not 0.0 < contamination < 0.5:
            raise SystemExit(
                "Contamination candidates must be greater than 0 and less than 0.5: "
                f"{value!r}"
            )
        candidates.append(contamination)
    if not candidates:
        raise SystemExit("At least one contamination candidate is required.")
    return tuple(candidates)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)


def _ensure_optional_ml_dependencies() -> None:
    if not optional_dependency_available("sklearn"):
        raise SystemExit(
            "Actual sklearn calibration requires optional dependency scikit-learn. "
            "Install it in a calibration environment with "
            "`python -m pip install scikit-learn`, or rerun with --dry-run for a "
            "dependency-free report."
        )


def _print_summary(report: dict[str, Any], output: Path) -> None:
    mode = "Dry-run report" if report["dry_run"] else "Sklearn calibration report"
    signal = report["signal"]
    signal_label = signal.get("signal_key") or signal.get("id") or "unresolved signal"
    print(f"{mode}: {signal_label}")
    print(f"output: {output}")
    print(f"training samples: {report['windows']['training']['summary']['count']}")
    print(f"validation samples: {report['windows']['validation']['summary']['count']}")
    print("candidate summary:")
    for candidate in report["threshold_summary"]:
        flagged_rate = candidate["validation_flagged_rate"] * 100.0
        print(
            "  "
            f"contamination={candidate['contamination']:.4g} "
            f"method={candidate['method']} "
            f"validation_flags={candidate['validation_flagged_count']} "
            f"validation_flagged_rate={flagged_rate:.2f}%"
        )
    if report["warnings"]:
        print("warnings:")
        for warning in report["warnings"]:
            print(f"  {warning}")


if __name__ == "__main__":
    raise SystemExit(main())
