"""Independent comparison of the public synthetic PDF/group-inference chain.

Only SQLite, JSON and standard-library arithmetic are used. Expected values do
not come from the application's parser, grouping service or statistics adapter.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics


class InferenceMismatch(ValueError):
    """A closed synthetic acceptance invariant failed."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise InferenceMismatch(reason)


def _number(actual, expected: float) -> None:
    _require(type(actual) in (int, float), "numeric_type")
    _require(
        math.isfinite(actual) and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9),
        "numeric_value",
    )


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecars(database: Path) -> bool:
    return any(
        database.with_name(database.name + suffix).exists()
        for suffix in ("-wal", "-shm", "-journal")
    )


def _read_database(database: Path) -> list[dict]:
    _require(not _sidecars(database), "database_sidecars")
    before = _hash(database)
    try:
        with closing(
            sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        ) as connection:
            for query in (
                "SELECT COUNT(*) FROM source_files",
                "SELECT COUNT(*) FROM source_file_locations",
                "SELECT COUNT(*) FROM source_file_locations WHERE is_active = 1",
                "SELECT COUNT(*) FROM parsed_reports",
                "SELECT COUNT(*) FROM report_metadata",
                "SELECT COUNT(*) FROM report_measurements",
            ):
                _require(connection.execute(query).fetchone() == (10,), "database_cardinality")
            _require(
                "unit"
                not in {
                    row[1] for row in connection.execute("PRAGMA table_info(report_measurements)")
                },
                "invented_unit",
            )
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute("""
                SELECT pr.id AS report_id, m.id AS measurement_id, sfl.file_name,
                       sf.sha256, rm.reference, rm.report_date, rm.sample_number,
                       pr.measurement_count, pr.has_nok, m.header, m.ax, m.nominal,
                       m.tol_plus, m.tol_minus, m.meas, m.dev, m.outtol, m.bonus,
                       m.is_nok, m.status_code, m.row_order
                FROM parsed_reports pr
                JOIN source_files sf ON sf.id = pr.source_file_id
                JOIN source_file_locations sfl ON sfl.source_file_id = sf.id AND sfl.is_active = 1
                JOIN report_metadata rm ON rm.report_id = pr.id
                JOIN report_measurements m ON m.report_id = pr.id
                ORDER BY sfl.file_name
            """)
            ]
    finally:
        _require(
            _hash(database) == before and not _sidecars(database), "database_changed_by_comparison"
        )


def _expected_rows(oracle: dict) -> dict[str, tuple[str, float, str]]:
    result = {}
    for group, indices in (("A", range(1, 6)), ("B", range(6, 11))):
        for index, value in zip(indices, oracle["groups"][group], strict=True):
            result[f"REF001_2024-01-01_{index}.pdf"] = (group, value, str(index))
    return result


def _compare_rows(oracle: dict, payload: dict, rows: list[dict]) -> None:
    expected = _expected_rows(oracle)
    _require(
        len(rows) == 10 and {row["file_name"] for row in rows} == set(expected),
        "database_filename_set",
    )
    _require(
        len({row["report_id"] for row in rows}) == 10
        and len({row["measurement_id"] for row in rows}) == 10,
        "database_keyset",
    )
    _require(
        payload["assignments"] == {name: value[0] for name, value in expected.items()},
        "group_assignment",
    )
    hashes = payload["source_hashes"]
    _require(set(hashes) == set(expected), "source_hash_set")
    for row in rows:
        _group, measured, sample = expected[row["file_name"]]
        _require(
            type(hashes[row["file_name"]]) is str
            and re.fullmatch(r"[0-9a-f]{64}", hashes[row["file_name"]]) is not None,
            "source_hash_format",
        )
        _require(row["sha256"] == hashes[row["file_name"]], "persisted_source_identity")
        text = {
            "reference": "REF001",
            "report_date": "2024-01-01",
            "sample_number": sample,
            "header": "SMOKE FEATURE",
            "ax": "X",
            "status_code": "ok",
        }
        _require(all(row[key] == value for key, value in text.items()), "persisted_report_identity")
        values = {
            "nominal": 10.0,
            "tol_plus": 0.1,
            "tol_minus": -0.1,
            "meas": measured,
            "dev": measured - 10.0,
            "outtol": 0.0,
            "bonus": 0.0,
            "measurement_count": 1,
            "has_nok": 0,
            "is_nok": 0,
            "row_order": 1,
        }
        for key, value in values.items():
            _number(row[key], value)


def _compare_analysis(oracle: dict, analysis: dict) -> None:
    _require(
        analysis["status"] == "ready" and analysis["readiness"]["runnable"] is True,
        "analysis_not_runnable",
    )
    _require(analysis["effective_scope"] == "single_reference", "analysis_scope")
    metrics = analysis["metric_rows"]
    _require(len(metrics) == 1, "metric_count")
    metric = metrics[0]
    _require(
        metric["metric"] == "SMOKE FEATURE - X" and metric["spec_status"] == "EXACT_MATCH",
        "metric_identity",
    )
    descriptions = metric["descriptive_stats"]
    _require(
        len(descriptions) == 2 and {row["group"] for row in descriptions} == {"A", "B"},
        "descriptive_group_set",
    )
    for row in descriptions:
        values = oracle["groups"][row["group"]]
        _require(
            type(row["n"]) is int and row["n"] == 5 and row["flags"] == "none",
            "descriptive_n_or_flags",
        )
        for key, value in {
            "mean": statistics.mean(values),
            "std": statistics.stdev(values),
            "min": min(values),
            "max": max(values),
        }.items():
            _number(row[key], round(value, 3))
    _require(len(metric["pairwise_rows"]) == 1, "pairwise_count")
    _compare_pair(oracle, metric["pairwise_rows"][0])


def _compare_pair(oracle: dict, row: dict) -> None:
    expected = oracle["pairwise"]
    for key in ("group_a", "group_b", "test_used", "effect_type", "difference", "flags"):
        _require(row[key] == expected[key], "pairwise_identity")
    a, b = oracle["groups"]["A"], oracle["groups"]["B"]
    delta = statistics.mean(a) - statistics.mean(b)
    pooled = math.sqrt((statistics.variance(a) + statistics.variance(b)) / 2)
    _number(row["delta_mean"], round(delta, 3))
    _number(row["effect_size"], round(delta / pooled, 3))
    _number(row["p_value"], expected["p_value"])
    _number(row["adjusted_p_value"], round(expected["p_value"], 4))


def verify(database: Path, artifact: Path, oracle_path: Path | None = None) -> None:
    """Reject semantic drift even when a producer supplies updated file hashes."""
    oracle_path = oracle_path or Path(__file__).with_name("synthetic-inference-oracle.json")
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    _require(oracle["schema"] == "metroliza-synthetic-inference-oracle-v1", "oracle_schema")
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    _require(
        type(payload["schema_version"]) is int and payload["schema_version"] == 1, "artifact_schema"
    )
    _compare_rows(oracle, payload, _read_database(database))
    _compare_analysis(oracle, payload["analysis"])
