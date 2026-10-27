"""Equivalence of the vectorised grouping helpers with the original row-wise implementations.

The ``_oracle_*`` functions are verbatim copies of the pre-optimisation code.
"""

import datetime
import hashlib
import json
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from metroliza.shared.grouping_filter_core import DataFrameGroupingIndex
from metroliza.tabular import data_grouping_service as service


def _oracle_compute_group_key_for_df(df):
    if 'REPORT_ID' not in df.columns and 'report_id' not in df.columns:
        raise ValueError("REPORT_ID is required to compute a grouping key.")

    report_id_column = 'REPORT_ID' if 'REPORT_ID' in df.columns else 'report_id'
    normalized_values = df[[report_id_column]].fillna('').astype(str)
    raw_key = normalized_values.apply(
        lambda row: json.dumps(list(row), ensure_ascii=False, separators=(',', ':')),
        axis=1,
    )
    return raw_key.apply(
        lambda value: hashlib.sha1(value.encode('utf-8'), usedforsecurity=False).hexdigest()
    )


def _oracle_grouping_key_counts(df):
    grouping_index = DataFrameGroupingIndex(df, ["GROUP_KEY"], blank_value="")
    rows, _total = grouping_index.preview_rows()
    if rows:
        return pd.DataFrame(
            {
                "GROUP_KEY": [row["key"][0] for row in rows],
                "ROW_COUNT": [int(row["row_count"]) for row in rows],
            }
        )
    return df.groupby("GROUP_KEY", sort=False, dropna=False).size().reset_index(name="ROW_COUNT")


def _oracle_build_grouping_row_index(df, *, group_color_column="GROUP_COLOR"):
    if df is None or df.empty:
        return df.copy() if df is not None else df
    if "GROUP_KEY" not in df.columns:
        raise ValueError("GROUP_KEY is required to build a grouping row index.")

    def _first_display_value(series):
        for value in series:
            if value is None:
                continue
            try:
                if value != value:
                    continue
            except TypeError:
                pass
            text = str(value).strip()
            if text and text not in {"None", "<NA>"}:
                return value
        return series.iloc[0] if len(series.index) else None

    aggregations = {}
    for column in service._GROUPING_INDEX_DISPLAY_COLUMNS:
        if column in df.columns:
            aggregations[column] = _first_display_value
    if group_color_column in df.columns and group_color_column not in aggregations:
        aggregations[group_color_column] = _first_display_value

    indexed = (
        df.groupby("GROUP_KEY", sort=False, dropna=False)
        .agg(**{column: (column, aggregator) for column, aggregator in aggregations.items()})
        .reset_index()
    )
    counts = _oracle_grouping_key_counts(df)
    return indexed.merge(counts, on="GROUP_KEY", how="left")


_REPORT_ID_CASES = {
    "int": [1, 2, 2, 3, 1, 10],
    "int_large": [2**40, 7, 2**40, -5],
    "float_with_nan": [1.0, np.nan, 2.5, 1.0, np.nan, -0.0, 0.0],
    "object_text": ["a", "b", "a", "", " ", "A|B", "A", "None", "nan"],
    "object_none_nan": ["x", None, np.nan, "x", None, pd.NA],
    "object_unicode": ["zażółć", "日本語", "😀", "é", "é", "quote\"s", "back\\slash", "zażółć"],
    "object_mixed_types": [1, 1.0, "1", True, 1, 1.0, None, (1, 2)],
    "object_unhashable": [[1, 2], [1, 2], {"a": 1}, "z"],
    "string_dtype": pd.Series(["a", None, "b", "a", pd.NA, ""], dtype="string"),
    "nullable_int": pd.Series([1, None, 3, 1], dtype="Int64"),
    "bool": [True, False, True],
    "datetime": pd.to_datetime(["2024-01-01", None, "2024-01-01", "2025-06-30"]),
    "categorical": pd.Series(pd.Categorical(["u", "v", None, "u"])),
    # Values that compare equal but render differently must keep the string-form keys of the row-wise code.
    "object_signed_zero": pd.Series([0.0, -0.0, 0.0, -0.0, np.nan], dtype=object),
    "object_decimal": pd.Series([Decimal("1"), Decimal("1.0"), Decimal("1.00"), Decimal("1")], dtype=object),
    "object_int_float_bool": pd.Series([1, 1.0, True, np.float64(1.0), np.int64(1), 1], dtype=object),
    "object_tz_same_instant": pd.Series(
        [
            pd.Timestamp("2024-01-01 12:00", tz="UTC"),
            pd.Timestamp("2024-01-01 13:00", tz="Europe/Warsaw"),
            datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2024, 1, 1, 13, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1))),
            pd.Timestamp("2024-01-01 12:00", tz="UTC"),
        ],
        dtype=object,
    ),
    "float64_signed_zero_without_nan": np.array([0.0, -0.0, 0.0, -0.0, 1.5]),
    "float64_distinct_nan_payloads": np.array([0x7FF8000000000000, 0x7FF8000000000001, 1], dtype=np.int64).view(np.float64),
}


def _assert_series_identical(actual, expected):
    pd.testing.assert_series_equal(actual, expected, check_exact=True)


def _assert_keys_match_oracle(df):
    try:
        expected = _oracle_compute_group_key_for_df(df)
    except Exception as exc:  # noqa: BLE001 - unsupported dtypes must fail the same way
        with pytest.raises(type(exc)):
            service.compute_group_key_for_df(df)
        return
    _assert_series_identical(service.compute_group_key_for_df(df), expected)


@pytest.mark.parametrize("case", sorted(_REPORT_ID_CASES))
@pytest.mark.parametrize("column_name", ["REPORT_ID", "report_id"])
def test_group_keys_match_oracle_for_report_id_dtypes(case, column_name):
    df = pd.DataFrame({column_name: _REPORT_ID_CASES[case], "OTHER": 0})
    df.index = pd.RangeIndex(100, 100 + len(df.index))

    _assert_keys_match_oracle(df)


def test_group_keys_for_object_ids_hash_each_distinct_string_once(monkeypatch):
    calls = []
    real_sha1 = hashlib.sha1

    def counting_sha1(data, **kwargs):
        calls.append(data)
        return real_sha1(data, **kwargs)

    monkeypatch.setattr(service.hashlib, "sha1", counting_sha1)
    ids = pd.Series(["a", "b", None, "a", "b", None] * 200, dtype=object)

    keys = service.compute_group_key_for_df(pd.DataFrame({"REPORT_ID": ids}))

    assert len(calls) == 3
    assert keys.nunique() == 3


def test_group_keys_keep_values_that_print_differently_apart():
    ids = pd.Series([0.0, -0.0, Decimal("1"), Decimal("1.0")], dtype=object)

    keys = service.compute_group_key_for_df(pd.DataFrame({"REPORT_ID": ids}))

    assert keys.nunique() == 4


def test_group_keys_prefer_upper_case_report_id_and_ignore_other_columns():
    df = pd.DataFrame({"report_id": [1, 2], "REPORT_ID": [5, 5], "REFERENCE": ["a", "b"]})

    keys = service.compute_group_key_for_df(df)

    _assert_series_identical(keys, _oracle_compute_group_key_for_df(df))
    assert keys.iloc[0] == keys.iloc[1]


def test_group_keys_known_values_and_missing_report_id_error():
    keys = service.compute_group_key_for_df(pd.DataFrame({"REPORT_ID": [1, None]}, dtype=object))
    assert keys.iloc[0] == hashlib.sha1(b'["1"]', usedforsecurity=False).hexdigest()
    assert keys.iloc[1] == hashlib.sha1(b'[""]', usedforsecurity=False).hexdigest()
    with pytest.raises(ValueError, match="REPORT_ID is required"):
        service.compute_group_key_for_df(pd.DataFrame({"REFERENCE": ["a"]}))


@pytest.mark.parametrize("dtype", ["int64", "object", "float64"])
def test_group_keys_for_empty_frame_match_oracle(dtype):
    df = pd.DataFrame({"REPORT_ID": pd.Series([], dtype=dtype)})

    _assert_series_identical(service.compute_group_key_for_df(df), _oracle_compute_group_key_for_df(df))


def _random_grouping_frame(seed, rows):
    rng = np.random.default_rng(seed)
    report_ids = rng.integers(0, max(2, rows // 3), rows)
    blanks = ["", " ", "None", "<NA>", None, np.nan, "  \t"]
    words = ["REF-A", "REF-B", " padded ", "zażółć", "日本語", "0", "nan"]

    def text_column(null_rate):
        values = []
        for _ in range(rows):
            roll = rng.random()
            values.append(blanks[rng.integers(len(blanks))] if roll < null_rate else words[rng.integers(len(words))])
        return values

    df = pd.DataFrame(
        {
            "REPORT_ID": report_ids,
            "REFERENCE": text_column(0.4),
            "DATE": text_column(0.2),
            "SAMPLE_NUMBER": text_column(0.5),
            "PART_NAME": text_column(0.3),
            "REVISION": text_column(0.9),
            "TEMPLATE_VARIANT": text_column(0.1),
            "HAS_NOK": rng.integers(0, 2, rows),
            "NOK_COUNT": np.where(rng.random(rows) < 0.3, np.nan, rng.integers(0, 9, rows)),
            "STATUS_CODE": pd.array(np.where(rng.random(rows) < 0.5, None, "OK"), dtype="string"),
            "OPERATOR_NAME": text_column(0.95),
            "FILENAME": [f"f{value}.pdf" for value in report_ids],
            "GROUP": "POPULATION",
            "GROUP_COLOR": text_column(0.5),
        }
    )
    df["GROUP_KEY"] = service.compute_group_key_for_df(df)
    return df


@pytest.mark.parametrize("seed", range(12))
def test_row_index_matches_oracle_on_random_frames(seed):
    df = _random_grouping_frame(seed, rows=40 + seed * 17)
    df.index = pd.RangeIndex(5, 5 + len(df.index))

    actual = service.build_grouping_row_index(df)
    expected = _oracle_build_grouping_row_index(df)

    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_row_index_matches_oracle_for_all_blank_groups_and_nan_keys():
    df = pd.DataFrame(
        {
            "REPORT_ID": [1, 1, 2, 3, 3],
            "REFERENCE": [None, "R", np.nan, "None", "<NA>"],
            "PART_NAME": ["", " ", "\t", None, np.nan],
            "GROUP_KEY": ["k1", "k1", np.nan, "  padded", None],
            "GROUP": ["POPULATION"] * 5,
            "GROUP_COLOR": [None, None, "#fff", "#fff", None],
        }
    )

    pd.testing.assert_frame_equal(
        service.build_grouping_row_index(df), _oracle_build_grouping_row_index(df), check_exact=True
    )


def test_row_index_matches_oracle_with_custom_color_column_and_missing_columns():
    df = pd.DataFrame(
        {
            "GROUP_KEY": ["a", "b", "a", "c"],
            "REFERENCE": [None, "r2", "r1", "r3"],
            "COLOR_X": [None, "#111", "#222", None],
            "EXTRA": [1, 2, 3, 4],
        }
    )

    actual = service.build_grouping_row_index(df, group_color_column="COLOR_X")

    pd.testing.assert_frame_equal(
        actual, _oracle_build_grouping_row_index(df, group_color_column="COLOR_X"), check_exact=True
    )
    assert list(actual.columns) == ["GROUP_KEY", "REFERENCE", "COLOR_X", "ROW_COUNT"]


@pytest.mark.parametrize(
    "keys",
    [
        ["k1", "k1", "k2"],
        [3, 3, 4, 3],
        ["b", "a", "b", "c", "a"],
        [" a", "a", "a ", "b"],
    ],
)
def test_row_index_matches_oracle_for_key_shapes(keys):
    df = pd.DataFrame({"GROUP_KEY": keys, "REFERENCE": list("vwxyz")[: len(keys)]})
    try:
        expected = _oracle_build_grouping_row_index(df)
    except Exception as exc:  # noqa: BLE001 - the vectorised version must fail the same way
        with pytest.raises(type(exc)):
            service.build_grouping_row_index(df)
        return

    pd.testing.assert_frame_equal(service.build_grouping_row_index(df), expected, check_exact=True)


def test_row_index_empty_and_missing_key_behaviour_unchanged():
    empty = pd.DataFrame({"GROUP_KEY": [], "REFERENCE": []})
    pd.testing.assert_frame_equal(service.build_grouping_row_index(empty), _oracle_build_grouping_row_index(empty))
    assert service.build_grouping_row_index(None) is None
    with pytest.raises(ValueError, match="GROUP_KEY is required"):
        service.build_grouping_row_index(pd.DataFrame({"REFERENCE": ["a"]}))


def test_row_index_does_not_modify_input():
    df = _random_grouping_frame(3, rows=60)
    snapshot = df.copy(deep=True)

    service.build_grouping_row_index(df)

    pd.testing.assert_frame_equal(df, snapshot)


def test_row_counts_match_oracle_counts():
    df = _random_grouping_frame(5, rows=90)
    df.loc[df.index[:6], "GROUP_KEY"] = [" spaced ", "", None, np.nan, "  ", "x"]

    pd.testing.assert_frame_equal(
        service._grouping_key_counts(df), _oracle_grouping_key_counts(df), check_exact=True
    )


def test_fixture_sized_report_set_matches_oracle():
    """1500 reports with realistic duplicated metadata (the size of the Export -> Grouping fixture)."""
    rng = np.random.default_rng(1500)
    rows = 1500
    df = pd.DataFrame(
        {
            "REPORT_ID": np.arange(1, rows + 1),
            "REFERENCE": [f"REF-{value:03d}" for value in rng.integers(0, 120, rows)],
            "DATE": [f"2025-{month:02d}-{day:02d}" for month, day in zip(rng.integers(1, 13, rows), rng.integers(1, 29, rows))],
            "SAMPLE_NUMBER": [str(value) for value in rng.integers(1, 30, rows)],
            "PART_NAME": [f"Part {value}" for value in rng.integers(0, 40, rows)],
            "REVISION": [("A", "B", "", None)[value] for value in rng.integers(0, 4, rows)],
            "TEMPLATE_VARIANT": "default",
            "HAS_NOK": rng.integers(0, 2, rows),
            "NOK_COUNT": rng.integers(0, 5, rows),
            "FILENAME": [f"report_{value}.pdf" for value in range(rows)],
        }
    )
    df["GROUP"] = "POPULATION"
    df["GROUP_COLOR"] = "#FFFFFF"

    keys = service.compute_group_key_for_df(df)
    _assert_series_identical(keys, _oracle_compute_group_key_for_df(df))
    df["GROUP_KEY"] = keys
    # Duplicate raw rows so that groups hold several rows with a blank first value.
    doubled = pd.concat([df, df.assign(REFERENCE=None, PART_NAME="")], ignore_index=True)

    for frame in (df, doubled):
        pd.testing.assert_frame_equal(
            service.build_grouping_row_index(frame), _oracle_build_grouping_row_index(frame), check_exact=True
        )
    assert service.build_grouping_row_index(df)["GROUP_KEY"].tolist() == keys.tolist()


_OBJECT_COLUMN_CASES = {
    "text": ["a", "b", "c", "d", "e", "f"],
    "text_and_none": [None, "b", None, None, "e", "f"],
    "all_blank": [None, "", " ", "None", "<NA>", np.nan],
    "ints": [1, 2, 3, 4, 5, 6],
    "ints_and_none": [None, 2, None, 4, 5, 6],
    "mixed_int_text": [None, "x", 3, None, 5, "y"],
    "bools": [True, False, None, True, False, True],
    "floats_and_nan": [np.nan, 1.5, np.nan, 2.5, 3.5, np.nan],
    "timestamps": [pd.NaT, pd.Timestamp("2024-01-01"), pd.NaT, pd.Timestamp("2024-02-01"), None, pd.NaT],
    "pd_na": [pd.NA, "b", pd.NA, "d", pd.NA, pd.NA],
    "nan_text_literal": ["nan", None, "NaN", "", "ok", None],
}


@pytest.mark.parametrize("case", sorted(_OBJECT_COLUMN_CASES))
def test_row_index_matches_oracle_for_object_column_contents(case):
    values = _OBJECT_COLUMN_CASES[case]
    df = pd.DataFrame(
        {
            "GROUP_KEY": ["g1", "g1", "g2", "g2", "g3", "g1"],
            "REFERENCE": pd.Series(values, dtype=object),
            "NOK_COUNT": pd.Series(values, dtype=object),
            "GROUP_COLOR": pd.Series(values[::-1], dtype=object),
        }
    )

    pd.testing.assert_frame_equal(
        service.build_grouping_row_index(df), _oracle_build_grouping_row_index(df), check_exact=True
    )


@pytest.mark.parametrize(
    "series",
    [
        pd.Series([None, 2, None, 4, 5, 6], dtype="Int64"),
        pd.Series([None, "b", None, "d", None, "f"], dtype="string"),
        pd.Series(pd.Categorical([None, "b", "b", "d", None, "f"])),
        pd.Series([np.nan, 1.5, np.nan, 2.5, np.nan, 3.5]),
        pd.Series(pd.to_datetime([None, "2024-01-01", None, "2024-03-01", None, "2024-05-01"])),
        pd.Series(pd.to_datetime([None, "2024-01-01", None, "2024-03-01", None, "2024-05-01"]).tz_localize("UTC")),
        pd.Series([1, 2, 3, 4, 5, 6], dtype="int32"),
        pd.Series([True, False, True, True, False, True]),
    ],
    ids=["Int64", "string", "categorical", "float64", "datetime64", "datetime64_utc", "int32", "bool"],
)
def test_row_index_matches_oracle_for_other_column_dtypes(series):
    df = pd.DataFrame({"GROUP_KEY": ["g1", "g1", "g2", "g2", "g3", "g1"], "REFERENCE": series})

    pd.testing.assert_frame_equal(
        service.build_grouping_row_index(df), _oracle_build_grouping_row_index(df), check_exact=True
    )


def test_native_color_assignment_activation_and_original_fallbacks():
    native = pd.DataFrame({'GROUP': ['POPULATION', 'A', 'A', 'B'],
                           'GROUP_COLOR': ['#FFFFFF', '#123456', '#789ABC', '#654321']})
    result = service.native_group_color_assignment(native, default_group='POPULATION',
                                                    default_color='#FFFFFF', color_column='GROUP_COLOR')
    assert result is not None
    assert result.tolist() == ['#FFFFFF', '#123456', '#123456', '#654321']
    pd.testing.assert_frame_equal(native, pd.DataFrame({'GROUP': ['POPULATION', 'A', 'A', 'B'],
                                                       'GROUP_COLOR': ['#FFFFFF', '#123456', '#789ABC', '#654321']}))
    for frame in (native.assign(GROUP_COLOR='#FFFFFF'), native.assign(GROUP=[None, 'A', 'A', 'B'])):
        assert service.native_group_color_assignment(frame, default_group='POPULATION',
                                                    default_color='#FFFFFF', color_column='GROUP_COLOR') is None


def test_native_color_assignment_declines_overridden_manager_and_axis_before_callbacks():
    from pandas.core.internals.managers import BlockManager

    class CustomManager(BlockManager):
        pass

    class CustomIndex(pd.RangeIndex):
        pass

    for override in ('manager_subclass', 'manager_state', 'axis_subclass', 'axis_state', 'custom_value', 'metadata', 'block_cache'):
        frame = pd.DataFrame({'GROUP': ['A', 'A'], 'GROUP_COLOR': ['#123456', '#789ABC']})
        if override == 'manager_subclass':
            frame._mgr = CustomManager(frame._mgr.blocks, frame._mgr.axes)
        elif override == 'manager_state':
            frame._mgr.__dict__['get_slice'] = lambda *args: pytest.fail('manager callback dispatched')
        elif override == 'axis_subclass':
            frame.index = CustomIndex(2)
        elif override == 'axis_state':
            frame.index.__dict__['__len__'] = lambda: pytest.fail('axis callback dispatched')
        elif override == 'metadata':
            class CustomAttrs:
                def __bool__(self):
                    pytest.fail('metadata callback dispatched')
            frame.__dict__['_attrs'] = CustomAttrs()
        elif override == 'block_cache':
            frame._mgr.blocks[0].__dict__['_cache'] = {'dtype': object()}
        else:
            class CustomText(str):
                def __str__(self):
                    pytest.fail('custom scalar callback dispatched')
            frame['GROUP'] = pd.Series([CustomText('A'), 'A'], dtype=object)
        assert service.native_group_color_assignment(frame, default_group='POPULATION',
                                                    default_color='#FFFFFF', color_column='GROUP_COLOR') is None
