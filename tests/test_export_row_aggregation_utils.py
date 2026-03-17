from modules.export_row_aggregation_utils import (
    all_measurements_within_limits,
    build_violin_group_stats_rows,
)


def test_all_measurements_within_limits_inclusive_check():
    assert all_measurements_within_limits([1.0, 1.1, 0.9], 0.9, 1.1)
    assert not all_measurements_within_limits([1.0, 1.2], 0.9, 1.1)


def test_build_violin_group_stats_rows_marks_reference_group():
    rows = build_violin_group_stats_rows(['A', 'B'], [[1.0, 1.1, 1.2], [1.5, 1.6, 1.7]])

    assert rows[0][0] == 'A'
    assert rows[0][-1] == 'Ref'
    assert rows[1][-1] != 'Ref'
