#!/usr/bin/env python3
"""Compare realtime detector alert costs on synthetic fixtures without storing a model."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
from statistics import NormalDist, fmean, quantiles

from metroliza.industrial.anomaly.contracts import DetectorContext
from metroliza.industrial.anomaly.detectors import IQRDetector, RollingZScoreDetector, SpecLimitDetector
from metroliza.industrial.anomaly.isolation_forest import MODEL_TYPE, IsolationForestAnomalyDetector
from metroliza.industrial.anomaly.model_registry import ModelArtifact
from metroliza.industrial.anomaly.optional_dependencies import load_sklearn_ensemble
from metroliza.industrial.realtime.replay import ReplayRequest, load_csv_rows, rows_to_samples
from metroliza.industrial.realtime.stream_contracts import SignalDefinition


FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "industrial_realtime"
SCENARIOS = (
    "stable_normal_process",
    "single_high_outlier",
    "single_low_outlier",
    "usl_lsl_breach",
    "warning_limit_breach",
    "gradual_drift_upward",
    "sudden_step_change",
    "sub_warning_step",
)
SPEC_LIMIT_LABELS = frozenset({"high_outlier", "low_outlier", "usl_breach", "lsl_breach"})


def _scenario(name):
    source = "sudden_step_change" if name == "sub_warning_step" else name
    path = FIXTURES / f"{source}.csv"
    rows = load_csv_rows(str(path))
    if name == "sub_warning_step":
        for row in rows:
            if row["expected_label"] == "step_change":
                row["metric_value"] = "103.5"
    return path, rows


def _alerted_rows(detector, samples, context):
    alerted = set()
    for position, sample in enumerate(samples):
        if detector.score_one(sample, context) is not None:
            alerted.add(position)
        context = replace(context, state=detector.update_one(sample, context))
    return alerted


def _episode_results(rows, alerted):
    episodes = []
    for label, group in groupby(enumerate(rows), key=lambda item: item[1]["expected_label"]):
        if label == "normal":
            continue
        positions = [position for position, _ in group]
        first_alert = next((position for position in positions if position in alerted), None)
        delay = None if first_alert is None else first_alert - positions[0]
        episodes.append((label in SPEC_LIMIT_LABELS, delay))
    return {
        "false_alert_rows": sum(rows[position]["expected_label"] == "normal" for position in alerted),
        "missed_critical": sum(critical and delay is None for critical, delay in episodes),
        "missed_process": sum(not critical and delay is None for critical, delay in episodes),
        "delay_samples": sum(delay for _, delay in episodes if delay is not None),
        "alert_rows": len(alerted),
    }


def evaluate():
    # Deterministic reference independent of all held-out fixture rows.
    distribution = NormalDist(100.0, 1.0)
    training = [distribution.inv_cdf((index + 0.5) / 256) for index in range(256)]
    q1, _, q3 = quantiles(training, method="inclusive")
    signal = SignalDefinition(
        id=1, source_profile_id=1, signal_key="cycle_time", metric_name="metric_value",
        nominal=100, lsl=90, usl=110, lower_warning=95, upper_warning=105,
    )
    context = DetectorContext(
        signal=signal,
        baseline={"n": len(training), "q1": q1, "q3": q3, "iqr": q3 - q1},
    )
    detectors = [IQRDetector(), RollingZScoreDetector()]
    try:
        ensemble = load_sklearn_ensemble()
    except ImportError:
        sklearn_version = None
    else:
        from sklearn import __version__ as sklearn_version

        model = ensemble.IsolationForest(contamination=0.01, n_estimators=100, random_state=919, n_jobs=1)
        model.fit([[value] for value in training])
        artifact = ModelArtifact("synthetic-reference", MODEL_TYPE, "", "", metrics={"training_mean": fmean(training)})
        detectors.append(IsolationForestAnomalyDetector(model, artifact))

    per_fixture = {}
    fixture_hashes = {}
    row_count = 0
    for name in SCENARIOS:
        path, rows = _scenario(name)
        fixture_hashes[path.name] = sha256(path.read_bytes()).hexdigest()
        row_count += len(rows)
        request = ReplayRequest(
            input_file=str(path), database="", source_profile_id=1, signal_key=signal.signal_key,
            metric_column="metric_value", event_time_column="process_timestamp", record_key_column="record_id",
        )
        samples = rows_to_samples(rows, request, signal_id=1)
        limits = _alerted_rows(SpecLimitDetector(), samples, context)
        estimates = {"spec_limits": _episode_results(rows, limits)}
        for detector in detectors:
            alerts = _alerted_rows(detector, samples, context)
            estimates[detector.detector_key] = _episode_results(rows, alerts)
            estimates[f"spec+{detector.detector_key}"] = _episode_results(rows, limits | alerts)
        per_fixture[name] = estimates

    totals = {}
    for detector_key, example in per_fixture[SCENARIOS[0]].items():
        result = {
            metric: sum(per_fixture[name][detector_key][metric] for name in SCENARIOS)
            for metric in example
        }
        result["loss"] = (
            result["false_alert_rows"] + 100 * result["missed_critical"]
            + 10 * result["missed_process"] + result["delay_samples"]
        )
        totals[detector_key] = result
    return {
        "sklearn": sklearn_version,
        "training_quantiles": {"q1": q1, "q3": q3},
        "fixtures_sha256": fixture_hashes,
        "rows": row_count,
        "totals": totals,
        "per_fixture": per_fixture,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2, sort_keys=True))
