"""Test-only stand-ins for comparator controls, never application evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import statistics

from scripts.verify_synthetic_oracle import _create_synthetic_database


def create_inference_case(database: Path, artifact: Path) -> None:
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    expected = json.loads((scripts / "synthetic-inference-oracle.json").read_text())
    template = json.loads((scripts / "synthetic-report-oracle.json").read_text())
    reports, aliases, assignments, hashes = [], [], {}, {}
    for index, measured in enumerate(expected["groups"]["A"] + expected["groups"]["B"], 1):
        name = f"REF001_2024-01-01_{index}.pdf"
        digest = hashlib.sha256(f"comparator-test-only-{index}".encode()).hexdigest()
        report = copy.deepcopy(template["persisted_reports"][0])
        report.update(report_id=index, sample_number=str(index))
        report["measurement"].update(measurement_id=index, meas=measured, dev=measured - 10)
        reports.append(report)
        aliases.append({"file_name": name, "sha256": digest})
        assignments[name] = "A" if index <= 5 else "B"
        hashes[name] = digest
    template["persisted_reports"] = reports
    template["fixture_construction"]["staged_aliases"] = aliases
    _create_synthetic_database(template, database)
    descriptions = []
    for group, values in expected["groups"].items():
        descriptions.append(
            {
                "group": group,
                "n": len(values),
                "flags": "none",
                "mean": round(statistics.mean(values), 3),
                "std": round(statistics.stdev(values), 3),
                "min": min(values),
                "max": max(values),
            }
        )
    a, b = expected["groups"]["A"], expected["groups"]["B"]
    delta = statistics.mean(a) - statistics.mean(b)
    pooled = math.sqrt((statistics.variance(a) + statistics.variance(b)) / 2)
    pair = {
        **expected["pairwise"],
        "delta_mean": round(delta, 3),
        "effect_size": round(delta / pooled, 3),
        "adjusted_p_value": round(expected["pairwise"]["p_value"], 4),
    }
    artifact.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assignments": assignments,
                "source_hashes": hashes,
                "analysis": {
                    "status": "ready",
                    "readiness": {"runnable": True},
                    "effective_scope": "single_reference",
                    "metric_rows": [
                        {
                            "metric": "SMOKE FEATURE - X",
                            "spec_status": "EXACT_MATCH",
                            "descriptive_stats": descriptions,
                            "pairwise_rows": [pair],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
