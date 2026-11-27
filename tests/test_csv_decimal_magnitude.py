"""Both CSV load paths must agree on the physical source values."""

import csv
import math

import pytest

from metroliza.tabular.csv_summary_utils import load_csv_with_fallbacks
from metroliza.tabular.tabular_analytics_service import cleanup_tabular_load_result, load_tabular_analytics_file


@pytest.mark.parametrize(("text", "expected"), [
    ("Length mm\n10.0\n10.2\n", [10.0, 10.2]),
    ("Length mm\n10,0\n10,2\n", [10.0, 10.2]),
    ('Length mm\n"10,0"\n"10,2"\n', [10.0, 10.2]),
    ("Part;Length mm\nA;10.0\nB;10.2\n", [10.0, 10.2]),
    ("Part\tLength mm\nA\t10.0\nB\t10.2\n", [10.0, 10.2]),
    ("Part,Length mm\nA,10.0\nB,10.2\n", [10.0, 10.2]),
    ("Part;Length mm\nA;10,0\nB;10,2\n", [10.0, 10.2]),
    ('Part,Length mm\nA,"1,234.50"\nB,"-2,345.60"\n', [1234.5, -2345.6]),
    ("Part;Length mm\nA;1.234,50\nB;-2.345,60\n", [1234.5, -2345.6]),
    ("Part;Length mm\nA;12,345,678\nB;-12,345,679\n", [12345678, -12345679]),
    ('Length mm\n0.15\n1.234\n"1,234"\n-1.234e1\n', [0.15, 1.234, 1234, -12.34]),
], ids=["single-dot", "single-comma", "quoted-comma", "semicolon-dot", "tab-dot", "comma-dot",
        "semicolon-comma", "dot-grouped", "comma-grouped", "grouped-integers", "corroborated-triplets"])
def test_imported_csv_decimal_magnitude_in_both_loaders(tmp_path, text, expected):
    file = tmp_path / "values.csv"
    file.write_text(text, encoding="utf-8")
    legacy, legacy_config = load_csv_with_fallbacks(file)
    loaded = load_tabular_analytics_file(file)
    try:
        assert legacy["Length mm"].tolist() == pytest.approx(expected)
        assert list(loaded.row_table["length_mm"]) == pytest.approx(expected)
        assert loaded.csv_config == legacy_config
    finally:
        cleanup_tabular_load_result(loaded)


def test_csv_preference_is_a_hint_and_identifier_values_remain_text(tmp_path):
    file = tmp_path / "values.csv"
    file.write_text("Part;Length mm\n1.234;10.0\n001;10.2\n", encoding="utf-8")
    legacy, config = load_csv_with_fallbacks(file, preferred_config={"delimiter": ";", "decimal": ","})
    loaded = load_tabular_analytics_file(file)
    try:
        assert config == loaded.csv_config == {"delimiter": ";", "decimal": "."}
        assert legacy["Part"].tolist() == list(loaded.row_table["part"]) == ["1.234", "001"]
        assert legacy["Length mm"].tolist() == list(loaded.row_table["length_mm"]) == [10.0, 10.2]
    finally:
        cleanup_tabular_load_result(loaded)


@pytest.mark.parametrize("case", [
    "ambiguous-sample", "ambiguous-overflow", "late-ambiguity", "late-change", "late-excess-field",
])
def test_csv_rejects_unproved_magnitude_without_retaining_a_partial_store(tmp_path, monkeypatch, case):
    import metroliza.tabular.tabular_analytics_service as service

    file = tmp_path / "unsafe.csv"
    integers = [("x", "10")] * (54000 if case == "late-change" else 210)
    rows = {
        "ambiguous-sample": [("a", "1.234"), ("b", "2.345")],
        "ambiguous-overflow": [("a", "1.234e307"), ("b", "2.345e307")],
        "late-ambiguity": [*integers, ("late", "1.234")],
        "late-change": [("a", "1.23"), ("b", "1.234"), *integers, ("late", "1,23")],
        "late-excess-field": [*integers, ("late", "10", "25")],
    }[case]
    with file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("Part", "Length mm"))
        writer.writerows(rows)
    monkeypatch.setattr(service.tempfile, "tempdir", str(tmp_path))
    match = "more fields than the header" if case == "late-excess-field" else "Ambiguous CSV number separators"
    progress = []
    with pytest.raises(ValueError, match=match):
        load_csv_with_fallbacks(file)
    with pytest.raises(ValueError, match=match) as caught:
        load_tabular_analytics_file(file, progress_callback=progress.append)
    assert str(file) not in str(caught.value) and "1.234" not in str(caught.value)
    if case == "late-change":
        assert any(event["stage"] == "chunk_loaded" and event["rows_loaded"] == 50000 for event in progress)
    assert not list(tmp_path.glob("metroliza_csv_summary_*.sqlite*"))


def test_csv_duplicate_headers_keep_independent_separator_evidence(tmp_path):
    file = tmp_path / "occurrences.csv"
    file.write_text("Reading;Reading\n1.1;1,1\n1.234;1.234\n", encoding="utf-8")
    legacy, _config = load_csv_with_fallbacks(file)
    loaded = load_tabular_analytics_file(file)
    try:
        assert legacy.values.tolist() == [[1.1, 1.1], [1.234, 1234]]
        assert loaded.source_column_identities == {("Reading", 1): "reading", ("Reading", 2): "reading_2"}
        rows = loaded.row_table
        assert list(rows["reading"]) == [1.1, 1.234]
        assert list(rows["reading_2"]) == [1.1, 1234]
    finally:
        cleanup_tabular_load_result(loaded)


def test_csv_malformed_groups_and_nonfinite_values_have_no_numeric_shadow(tmp_path):
    from contextlib import closing
    import sqlite3

    file = tmp_path / "invalid.csv"
    file.write_text(
        "Part;Reading\nA;1.2\nB;1,23.45\nC;1.23.456\nD;Inf\nE;NaN\nF;1.234e309\n",
        encoding="utf-8",
    )
    legacy, _config = load_csv_with_fallbacks(file)
    loaded = load_tabular_analytics_file(file, column_types={("Reading", 1): "number"})
    try:
        assert legacy["Reading"].iloc[0] == 1.2
        assert all(math.isnan(value) for value in legacy["Reading"].iloc[1:])
        store = loaded.sqlite_store
        shadow = store.numeric_filter_columns["reading"]
        with closing(sqlite3.connect(store.path)) as connection:
            values = connection.execute(
                f'SELECT reading, "{shadow}" FROM tabular_rows ORDER BY source_row_number'
            ).fetchall()
        assert values == [
            ("1.2", 1.2), ("1,23.45", None), ("1.23.456", None),
            ("Inf", None), ("NaN", None), ("1.234e309", None),
        ]
    finally:
        cleanup_tabular_load_result(loaded)


def test_csv_explicit_text_preserves_custom_identifier(tmp_path):
    file = tmp_path / "types.csv"
    file.write_text("Workpiece code;Reading\n1.234;1.2\n001;1.3\n", encoding="utf-8")
    loaded = load_tabular_analytics_file(file, column_types={("Workpiece code", 1): "text"})
    try:
        assert list(loaded.row_table["workpiece_code"]) == ["1.234", "001"]
        assert list(loaded.row_table["reading"]) == [1.2, 1.3]
    finally:
        cleanup_tabular_load_result(loaded)
    with pytest.raises(ValueError, match="Ambiguous CSV number separators"):
        load_tabular_analytics_file(file, column_types={("Workpiece code", 1): "number"})


def test_csv_numeric_looking_identifiers_preserve_all_original_text(tmp_path):
    file = tmp_path / "identifiers.csv"
    file.write_text(
        "Batch code;Reading\n1.234;10.1\n2;10.2\n3;10.3\n4;10.4\n5;10.5\n",
        encoding="utf-8",
    )
    legacy, _config = load_csv_with_fallbacks(file)
    loaded = load_tabular_analytics_file(file)
    try:
        expected = ["1.234", "2", "3", "4", "5"]
        assert legacy["Batch code"].tolist() == list(loaded.row_table["batch_code"]) == expected
        assert {metric.field_name for metric in loaded.metric_candidates} == {"reading"}
    finally:
        cleanup_tabular_load_result(loaded)
