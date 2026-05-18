import pandas as pd
import pytest

from modules.grouping_filter_core import (
    DataFrameGroupingIndex,
    DateFilterSpec,
    NumberFilterSpec,
    TextFilterSpec,
    apply_filter_specs,
    build_filter_mask,
    normalize_grouping_key,
    normalized_grouping_key_frame,
    parse_filter_expression,
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
        ("(blank)", "(blank)"),
        ("R1", "A"),
        ("R1", "B"),
        ("R2", "A"),
    ]
    assert rows[3]["row_count"] == 2
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
            "Supplier": ["IKD", "WEDRONE", "IKD"],
            "Value": [1, 1, 2],
            "Value2": [0, 2, 3],
        }
    )

    parsed = parse_filter_expression(
        "TimeStamp>2026-05-01 AND Supplier=WEDRONE AND Value=1 AND Value2>1",
        frame.columns,
    )
    filtered = apply_filter_specs(frame, parsed.specs, match_mode=parsed.match_mode)

    assert parsed.match_mode == "and"
    assert filtered.index.tolist() == [1]

    parsed_or = parse_filter_expression("Supplier=WEDRONE OR Value2>2", frame.columns)
    filtered_or = apply_filter_specs(frame, parsed_or.specs, match_mode=parsed_or.match_mode)

    assert parsed_or.match_mode == "or"
    assert filtered_or.index.tolist() == [1, 2]
