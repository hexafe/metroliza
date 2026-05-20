import pandas as pd
import pytest

from modules.grouping_filter_core import (
    DataFrameGroupingIndex,
    DateFilterSpec,
    NumberFilterSpec,
    TextFilterSpec,
    apply_filter_specs,
    build_filter_mask,
    looks_like_filter_expression,
    normalize_grouping_key,
    normalized_grouping_key_frame,
    parse_filter_expression,
    resolve_filter_column,
)


def test_grouping_index_preview_filter_count_and_child_keys() -> None:
    frame = pd.DataFrame(
        {
            "reference": ["R1", "R1", "R2", "R2", None],
            "tracecode": ["T-001", "T-002", "T-003", "T-004", "T-005"],
            "shift": ["A", "B", "A", "A", ""],
            "length": [10.0, 10.1, 10.2, 10.3, 10.4],
        }
    )
    index = DataFrameGroupingIndex(frame, ["reference", "shift"])

    rows, total = index.preview_rows()
    search_rows, search_total = index.preview_rows(search_text="r2", limit=1)
    selected = {("R2", "A"), ("(blank)", "(blank)")}
    filtered = index.filter_rows(selected)

    assert total == 4
    assert [row["key"] for row in rows] == [
        ("R1", "A"),
        ("R1", "B"),
        ("R2", "A"),
        ("(blank)", "(blank)"),
    ]
    assert rows[2]["row_count"] == 2
    assert search_total == 1
    assert search_rows[0]["key"] == ("R2", "A")
    assert index.matching_keys(search_text="blank") == (("(blank)", "(blank)"),)
    assert index.count_rows(selected) == 3
    assert filtered["tracecode"].tolist() == ["T-003", "T-004", "T-005"]
    assert index.child_keys_for_selected({("R1",)}) == {("R1", "A"), ("R1", "B")}


def test_grouping_helpers_normalize_missing_columns_and_blank_values() -> None:
    frame = pd.DataFrame({"line": [" L1 ", None, ""], "value": [1, 2, 3]})

    assert normalize_grouping_key(["line", "missing"], ["", None]) == ("(blank)", "(blank)")
    assert DataFrameGroupingIndex(frame, ["missing"]).active is False

    key_frame = normalized_grouping_key_frame(frame, ["line", "missing"])

    assert list(key_frame.columns) == ["line"]
    assert key_frame["line"].tolist() == ["L1", "(blank)", "(blank)"]


def test_apply_filter_specs_combines_text_number_and_date_with_and() -> None:
    frame = pd.DataFrame(
        {
            "tracecode": ["TC-001", "TC-002", "QA-003", None],
            "length": ["10.5", "11.2", "9.8", "bad"],
            "created_at": ["2026-05-01", "2026-05-03 12:00", "2026-05-04", ""],
        }
    )

    filtered = apply_filter_specs(
        frame,
        [
            TextFilterSpec("tracecode", "contains", "tc"),
            NumberFilterSpec("length", "between", 10, 12),
            DateFilterSpec("created_at", "on_or_before", "2026-05-03"),
        ],
        match_mode="and",
    )

    assert filtered["tracecode"].tolist() == ["TC-001", "TC-002"]


def test_apply_filter_specs_combines_filters_with_or() -> None:
    frame = pd.DataFrame(
        {
            "tracecode": ["TC-001", "QA-002", "TC-003", "QA-004"],
            "length": [10.0, 12.5, 9.5, 13.0],
            "created_at": ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04"],
        }
    )

    filtered = apply_filter_specs(
        frame,
        [
            TextFilterSpec("tracecode", "starts_with", "QA"),
            NumberFilterSpec("length", "lt", 10),
            DateFilterSpec("created_at", "after", "2026-05-03"),
        ],
        match_mode="or",
    )

    assert filtered["tracecode"].tolist() == ["QA-002", "TC-003", "QA-004"]


def test_filter_specs_support_blank_checks_and_case_sensitive_text() -> None:
    frame = pd.DataFrame(
        {
            "name": ["Alpha", "alpha", "", None],
            "score": [1, None, "bad", 4],
            "date": ["2026-05-01", "", None, "2026-05-04"],
        }
    )

    assert TextFilterSpec("name", "equals", "Alpha", case_sensitive=True).mask(frame).tolist() == [
        True,
        False,
        False,
        False,
    ]
    assert TextFilterSpec("name", "is_blank").mask(frame).tolist() == [
        False,
        False,
        True,
        True,
    ]
    assert NumberFilterSpec("score", "is_blank").mask(frame).tolist() == [
        False,
        True,
        True,
        False,
    ]
    assert DateFilterSpec("date", "is_not_blank").mask(frame).tolist() == [
        True,
        False,
        False,
        True,
    ]


def test_filter_mask_empty_specs_selects_all_rows_and_validates_match_mode() -> None:
    frame = pd.DataFrame({"value": [1, 2, 3]})

    assert build_filter_mask(frame, []).tolist() == [True, True, True]
    with pytest.raises(ValueError, match="match_mode"):
        build_filter_mask(frame, [], match_mode="xor")


def test_filter_specs_raise_for_missing_column_and_bad_operator() -> None:
    frame = pd.DataFrame({"value": [1, 2, 3]})

    with pytest.raises(KeyError, match="missing"):
        NumberFilterSpec("missing", "gt", 1).mask(frame)
    with pytest.raises(ValueError, match="Unsupported text"):
        TextFilterSpec("value", "regex", "1").mask(frame)
    with pytest.raises(ValueError, match="must be numeric"):
        NumberFilterSpec("value", "gt", "not-a-number").mask(frame)
    with pytest.raises(ValueError, match="must be date-like"):
        DateFilterSpec("value", "after", "not-a-date").mask(frame)


def test_parse_filter_expression_supports_text_number_date_and_or() -> None:
    frame = pd.DataFrame(
        {
            "TimeStamp": ["2026-04-30", "2026-05-02", "2026-05-03"],
            "Supplier": ["OTHER", "SUPPLIER", "OTHER"],
            "Value": [1, 1, 2],
            "Value2": [0, 2, 3],
        }
    )

    parsed = parse_filter_expression(
        "TimeStamp>2026-05-01 AND Supplier=SUPPLIER AND Value=1 AND Value2>1",
        frame.columns,
    )
    filtered = apply_filter_specs(frame, parsed.specs, match_mode=parsed.match_mode)

    assert parsed.match_mode == "and"
    assert filtered.index.tolist() == [1]

    parsed_or = parse_filter_expression("Supplier=SUPPLIER OR Value2>2", frame.columns)
    filtered_or = apply_filter_specs(frame, parsed_or.specs, match_mode=parsed_or.match_mode)

    assert parsed_or.match_mode == "or"
    assert filtered_or.index.tolist() == [1, 2]


def test_parse_filter_expression_supports_nested_mixed_and_or() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S-1", "S-1", "S-2", "S-3"],
            "Part": ["bolt", "nut", "bolt", "gear"],
            "Value": [8, 13, 4, 20],
            "Date": ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04"],
        }
    )

    parsed = parse_filter_expression(
        "(Sample = S-1 AND (Part = bolt OR Value >= 12)) OR (Sample = S-3 AND Date > 2026-05-03)",
        frame.columns,
    )
    filtered = apply_filter_specs(frame, parsed.specs, match_mode=parsed.match_mode)

    assert parsed.match_mode == "and"
    assert filtered.index.tolist() == [0, 1, 3]
    assert parsed.mask(frame).tolist() == [True, True, False, True]


def test_parse_filter_expression_supports_text_wildcard_equality() -> None:
    frame = pd.DataFrame(
        {
            "Part": ["Bolt-01", "bolt-02", "Nut-01", "BOLT-extra", None],
            "Value": [10, 11, 12, 13, 14],
        }
    )

    parsed = parse_filter_expression("Part = bolt-*", frame.columns)
    filtered = apply_filter_specs(frame, parsed.specs, match_mode=parsed.match_mode)

    assert TextFilterSpec("Part", "equals", "bolt-*").mask(frame).tolist() == [
        False,
        False,
        False,
        False,
        False,
    ]
    assert filtered["Value"].tolist() == [10, 11, 13]

    parsed_not = parse_filter_expression("Part != bolt-*", frame.columns)
    filtered_not = apply_filter_specs(frame, parsed_not.specs, match_mode=parsed_not.match_mode)

    assert filtered_not["Value"].tolist() == [12, 14]


def test_parse_filter_expression_resolves_display_aliases() -> None:
    frame = pd.DataFrame(
        {
            "sample_id": ["S-1", "S-2", "S-1"],
            "created_at": ["2026-05-01", "2026-05-02", "2026-05-03"],
            "part_name": ["Bolt", "Bolt", "Nut"],
        }
    )
    aliases = {"Sample": "sample_id", "Date": "created_at", "Part": "part_name"}

    parsed = parse_filter_expression(
        "Sample = S-1 AND Date >= 2026-05-02 AND Part = nut",
        frame.columns,
        aliases=aliases,
    )
    filtered = apply_filter_specs(frame, parsed.specs, match_mode=parsed.match_mode)

    assert resolve_filter_column("sample", frame.columns, aliases=aliases) == "sample_id"
    assert filtered.index.tolist() == [2]


def test_parse_filter_expression_supports_quoted_values_and_delimited_fields() -> None:
    frame = pd.DataFrame(
        {
            "Sample Code": ["A B", "A C", "A B"],
            "Part Name": ["gear shaft", "gear shaft", "bolt"],
            "Operator": ["AND team", "OR team", "AND team"],
        }
    )

    parsed = parse_filter_expression(
        "`Sample Code` = 'A B' AND [Part Name] = \"gear shaft\" AND Operator = 'AND team'",
        frame.columns,
    )
    filtered = apply_filter_specs(frame, parsed.specs, match_mode=parsed.match_mode)

    assert looks_like_filter_expression("`Sample Code` = 'A B'")
    assert filtered.index.tolist() == [0]


def test_parse_filter_expression_rejects_unknown_fields() -> None:
    frame = pd.DataFrame({"Sample": ["S-1"], "Value": [1]})

    with pytest.raises(KeyError, match="Missing"):
        parse_filter_expression("Missing = S-1", frame.columns)
