"""Selected source rows are identical in the typed reference and tabular export scope."""

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from metroliza.industrial.contracts import IndustrialAnalyticsRequest, validate_industrial_analytics_request
from metroliza.industrial.industrial_analytics_state import ProductionAggregationState
from metroliza.industrial.industrial_analytics_workflow import run_tabular_file_analytics
from metroliza.recipes.tabular_adapter import capture
from metroliza.shared.typed_filter import FilterPreview, PandasFilterAdapter
from metroliza.tabular.tabular_analytics_service import (
    cleanup_tabular_load_result, load_tabular_analytics_file, load_tabular_analytics_files, materialize_tabular_dataframe,
)
from metroliza.tabular.tabular_typed_filter import prepare_tabular_typed_filter, tabular_typed_filter_fields


@pytest.fixture
def measurement_source(tmp_path):
    path = tmp_path / "measurements.csv"
    path.write_text(
        "Reading mm;Measured Date;Label\n"
        "1,5;2026-02-15;001\n"
        "invalid;bad;001\n"
        "18446744073709551615;2026-02-16;Straße\n"
        "18446744073709551614;2026-02-17;STRASSE\n"
        "0,5;15.02.2026;AB-01\n"
        ";;\n"
        "-4;2026-02-20;001\n",
        encoding="utf-8",
    )
    loaded = load_tabular_analytics_file(
        path, timestamp_column="Measured Date", column_types={("Reading mm", 1): "number"}
    )
    try:
        yield path, loaded
    finally:
        cleanup_tabular_load_result(loaded)


@pytest.mark.parametrize(("expression", "expected"), [
    ('(`Reading mm` >= 1.5 and `Measured Date` <= "2026-02-16") or Label = "001"', (1, 2, 3, 7)),
    ('`Reading mm` = 18446744073709551615', (3,)),
    ('`Reading mm` = 18446744073709551614', (4,)),
    ('`Reading mm` != 0.5', (1, 2, 3, 4, 6, 7)),
    ('`Reading mm` not in (1.5, 0.5)', (2, 3, 4, 6, 7)),
    ('`Measured Date` = "2026-02-15"', (1, 5)),
    ('Label = "strasse"', (3, 4)),
    ('Label not in ("001", "AB-01")', (3, 4, 6)),
])
def test_actual_csv_typed_rules_match_reference_and_final_projection(measurement_source, expression, expected):
    _path, loaded = measurement_source
    fields = {item.label: item.field_id for item in tabular_typed_filter_fields(loaded)}
    source = pd.DataFrame({
        "source_row_number": range(1, 8),
        fields["Reading mm"]: [1.5, None, "18446744073709551615", "18446744073709551614", 0.5, None, -4],
        fields["Measured Date"]: ["2026-02-15", None, "2026-02-16", "2026-02-17", "2026-02-15", None, "2026-02-20"],
        fields["Label"]: ["001", "001", "Straße", "STRASSE", "AB-01", None, "001"],
    }, dtype=object)
    scope = prepare_tabular_typed_filter(loaded, expression)
    reference = PandasFilterAdapter(source, "source_row_number").prepare(scope.expression)
    assert tuple(reference.iter_row_ids()) == expected
    assert scope.preview() == reference.preview() == FilterPreview(len(expected), expected)
    result = materialize_tabular_dataframe(loaded, typed_scope=scope, required_columns=("source_row_number", "label"))
    assert tuple(result.dataframe["source_row_number"]) == expected
    assert result.diagnostics[0].context == {"input_row_count": 7, "output_row_count": len(expected)}


def test_field_ids_keep_raw_occurrences_across_sanitized_collisions_and_reorder(tmp_path):
    first = tmp_path / "first.csv"
    first.write_text("Size mm;Size!mm;Size mm\n10;100;2\n10;200;9\n", encoding="utf-8")
    second = tmp_path / "second.csv"
    second.write_text("Size!mm;Size mm;Size mm\n100;10;2\n200;10;9\n", encoding="utf-8")
    original = load_tabular_analytics_file(first)
    reordered = load_tabular_analytics_file(second)
    try:
        labels = {field.label: field.field_id for field in tabular_typed_filter_fields(original)}
        assert len(set(labels.values())) == len(labels) == 3
        assert labels == {item.label: item.field_id for item in tabular_typed_filter_fields(reordered)}
        assert original.source_column_identities != reordered.source_column_identities
        for loaded in (original, reordered):
            scope = prepare_tabular_typed_filter(loaded, f'{labels["Size mm (occurrence 2)"]} < 4')
            assert scope.preview() == FilterPreview(1, (1,))
    finally:
        cleanup_tabular_load_result(original)
        cleanup_tabular_load_result(reordered)


def test_typed_filter_source_staleness_and_mixed_request_are_rejected(measurement_source, tmp_path):
    path, loaded = measurement_source
    scope = prepare_tabular_typed_filter(loaded, 'Label = "001"')
    request = IndustrialAnalyticsRequest(
        source_kind="tabular_file", input_file=str(path), output_dashboard_file=str(tmp_path / "out.html"),
        tabular_load_result=loaded, _tabular_typed_filter=scope,
    )
    assert validate_industrial_analytics_request(request).tabular_typed_filter is scope
    assert scope.preview().sample_row_ids == (1, 2, 7)
    with pytest.raises(ValueError, match="Clear the existing row filters and manual groups"):
        validate_industrial_analytics_request(replace(request, tabular_filter_expression='Label = "001"'))
    by_label = replace(request, aggregation_state=ProductionAggregationState(group_fields=("label",)))
    assert validate_industrial_analytics_request(by_label).aggregation_state.group_fields == ("label",)
    with pytest.raises(ValueError, match="Clear the existing row filters and manual groups"):
        validate_industrial_analytics_request(replace(
            by_label, grouping_df=pd.DataFrame({"REPORT_ID": [1], "GROUP": ["Manual selection"]}),
        ))
    for fields in (("GROUP",), ("label", "measured_date"), ("reading_mm",), ("source_file",), ("missing",)):
        with pytest.raises(ValueError, match="Select one source column"):
            validate_industrial_analytics_request(replace(request, aggregation_state=ProductionAggregationState(
                group_fields=fields,
            )))
    with pytest.raises(ValueError, match="Clear the typed filter before saving a recipe"):
        capture(request)
    legacy = capture(replace(request, _tabular_typed_filter=None))
    assert "tabular_typed_filter" not in repr(legacy.binding)
    with pytest.raises(ValueError, match="needs a new preview"):
        materialize_tabular_dataframe(replace(loaded), typed_scope=scope)
    path.write_text(path.read_text() + "99;2026-02-21;001\n", encoding="utf-8")
    with pytest.raises(ValueError, match="selected source changed"):
        scope.preview()
    with pytest.raises(ValueError, match="selected source changed"):
        materialize_tabular_dataframe(loaded, typed_scope=scope)
    dashboard, workbook = tmp_path / "out.html", tmp_path / "out.xlsx"
    dashboard.write_bytes(b"prior dashboard")
    workbook.write_bytes(b"prior workbook")
    with pytest.raises(ValueError, match="Reload CSV/Excel data before export"):
        run_tabular_file_analytics(
            input_file=str(path), output_dashboard_file=str(dashboard), output_workbook_file=str(workbook),
            tabular_load_result=loaded, tabular_typed_filter=scope,
        )
    assert dashboard.read_bytes() == b"prior dashboard"
    assert workbook.read_bytes() == b"prior workbook"
    assert Path(loaded.sqlite_store.path).is_file()


def test_shared_931_fixture_with_imported_csv_values(tmp_path):
    import csv

    from metroliza.shared.typed_filter import load_typed_filter
    from metroliza.tabular.tabular_typed_filter import _compile_tabular_typed_filter, _field_bindings
    from tests.typed_filter_conformance import GROUPED_CASE, OPERATOR_CASES, ROWS, condition, document

    path = tmp_path / "shared-fixture.csv"
    # CSV cells are strings. Preserve the shared fixture's invalid date case
    # without introducing a valid ISO compact date during that conversion.
    input_rows = [
        (number, "invalid date" if type(day) is int else day, label)
        for _id, number, day, label in ROWS
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(("Reading", "Recorded Date", "Label"))
        writer.writerows(input_rows)
    loaded = load_tabular_analytics_file(
        path, timestamp_column="Recorded Date", column_types={("Reading", 1): "number"}
    )
    try:
        bindings = {item.field_id: (item, column) for item, column in _field_bindings(loaded)}
        fields = {item.label: item for item, _column in bindings.values()}
        remap = {key: fields[label].field_id for key, label in (
            ("n", "Reading"), ("d", "Recorded Date"), ("label", "Label"),
        )}
        frame = pd.DataFrame(
            [(index, number, day, label.strip() or None if label is not None else None)
             for index, (number, day, label) in enumerate(input_rows, 1)],
            columns=["source_row_number", remap["n"], remap["d"], remap["label"]],
            dtype=object,
        )
        cases = []
        for field, kind, op, values, expected in OPERATOR_CASES:
            if field == "label" and op == "in":
                # The existing loader strips cell edges and stores empty cells as NULL.
                expected = [6, 9]
            elif field == "label" and op == "not_in":
                expected = [1, 2, 3, 4, 5, 7, 8, 10, 11]
            cases.append((document(condition(field, kind, op, *values)), tuple(expected)))
        cases.append(GROUPED_CASE)
        for rule, expected in cases:
            ast = load_typed_filter(rule, tuple(fields.values()), remap=remap)
            scope = _compile_tabular_typed_filter(loaded, bindings, ast, text="")
            reference = PandasFilterAdapter(frame, "source_row_number").prepare(ast)
            assert tuple(reference.iter_row_ids()) == expected, rule
            assert scope.preview() == reference.preview() == FilterPreview(len(expected), expected), rule
            result = materialize_tabular_dataframe(loaded, typed_scope=scope, required_columns=("source_row_number",))
            assert tuple(result.dataframe["source_row_number"]) == expected, rule
    finally:
        cleanup_tabular_load_result(loaded)


@pytest.mark.parametrize("headers", [
    ("A", " A ", "A (occurrence 1)", "a", "A", "Plain"),
    ("Unnamed column", "", " ", "Unnamed column (occurrence 1)", "", "Plain"),
    ("A", "csv_559aead08264d5795d39_1", "Plain"),
], ids=["heading-imitates-occurrence", "blank-and-literal-unnamed", "heading-imitates-field-id"])
def test_loaded_labels_distinguish_literal_raw_headings_and_occurrences(tmp_path, headers):
    import csv
    import json

    labels_by_id = None
    physical_order = tuple(range(len(headers)))
    reordered = tuple(sorted(physical_order, key=lambda index: headers[index], reverse=True))
    for version, order in enumerate((physical_order, reordered)):
        path = tmp_path / f"source-{version}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=";", quoting=csv.QUOTE_ALL)
            writer.writerow([headers[index] for index in order])
            writer.writerows(["hit" if column == row else "miss" for column in order] for row in physical_order)
        loaded = load_tabular_analytics_file(path)
        try:
            fields = tabular_typed_filter_fields(loaded)
            assert len({field.label.casefold() for field in fields}) == len(headers)
            assert not {field.label.casefold() for field in fields} & {
                field.field_id.casefold() for field in fields
            }
            labels = {field.field_id: field.label for field in fields}
            if labels_by_id is None:
                labels_by_id = labels
            else:
                assert labels == labels_by_id
            for field, physical_index in zip(fields, order, strict=True):
                raw = headers[physical_index]
                if raw == "Plain":
                    assert field.label == raw
                if (raw and raw != raw.strip()) or (not raw and physical_index == headers.index("")):
                    assert json.dumps(raw, ensure_ascii=False) in field.label
                quoted_label = "`" + field.label.replace("`", "``") + "`"
                expected = FilterPreview(1, (physical_index + 1,))
                for alias in (quoted_label, field.field_id):
                    scope = prepare_tabular_typed_filter(loaded, f'{alias} = "hit"')
                    assert scope.preview() == expected
        finally:
            cleanup_tabular_load_result(loaded)


def test_mixed_csv_and_workbook_use_inferred_number_for_exact_combined_rows(tmp_path):
    from openpyxl import Workbook

    csv_input = tmp_path / "first.csv"
    csv_input.write_text("Part;Rate;Rate\nA;99,1;8,2\nB;99,2;10,4\n", encoding="utf-8")
    excel_input = tmp_path / "second.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Rate", "Part", "Rate"])
    worksheet.append([99.3, "C", 9.6])
    worksheet.append([99.4, "D", 11.5])
    workbook.save(excel_input)
    workbook.close()

    loaded = load_tabular_analytics_files((csv_input, excel_input))
    try:
        field = next(item for item in tabular_typed_filter_fields(loaded) if item.label == "Rate (occurrence 2)")
        assert field.kind == "number"
        scope = prepare_tabular_typed_filter(loaded, '`Rate (occurrence 2)` > 10')
        request = IndustrialAnalyticsRequest(
            source_kind="tabular_file", input_file=str(csv_input), output_dashboard_file=str(tmp_path / "out.html"),
            tabular_load_result=loaded, _tabular_typed_filter=scope,
            aggregation_state=ProductionAggregationState(group_fields=("source_file",)),
        )
        assert validate_industrial_analytics_request(request).aggregation_state.group_fields == ("source_file",)
        frame = pd.DataFrame({"source_row_number": [1, 2, 3, 4], field.field_id: [8.2, 10.4, 9.6, 11.5]})
        expected = FilterPreview(2, (2, 4))
        reference = PandasFilterAdapter(frame, "source_row_number").prepare(scope.expression)
        assert scope.preview() == reference.preview() == expected
        result = materialize_tabular_dataframe(loaded, typed_scope=scope).dataframe
        assert result["source_row_number"].tolist() == list(reference.iter_row_ids()) == [2, 4]
        assert result["source_file"].tolist() == ["first.csv", "second.xlsx"]
        assert result["rate_2"].tolist() == [10.4, 11.5]
    finally:
        cleanup_tabular_load_result(loaded)
