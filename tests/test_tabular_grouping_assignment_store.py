from __future__ import annotations

import pandas as pd
import pytest

from metroliza.reports.db import sqlite_connection_scope
from metroliza.tabular.grouping_assignment_store import (
    AssignGroupingRows,
    AssignGroupingScope,
    DeleteGroupingGroup,
    RenameGroupingGroup,
    TabularGroupingAssignmentCleanupError,
    TabularGroupingAssignmentStore,
    TabularGroupingScope,
)
from metroliza.tabular.tabular_analytics_service import (
    TabularColumnFilter,
    cleanup_tabular_load_result,
    load_tabular_analytics_file,
)


@pytest.fixture
def sqlite_source(tmp_path):
    source_path = tmp_path / "grouping_store.csv"
    pd.DataFrame(
        {
            "Line": ["A", "A", None, "B"],
            "Station": ["S1", "S2", "S2", "S1"],
            "Supplier": ["KEEP", "DROP", "KEEP", "KEEP"],
            "TraceCode": ["MATCH-001", "MATCH-002", "OTHER-003", "MATCH-004"],
        }
    ).to_csv(source_path, index=False)
    loaded = load_tabular_analytics_file(source_path, force_sqlite=True)
    assert loaded.sqlite_store is not None
    try:
        yield loaded.sqlite_store
    finally:
        cleanup_tabular_load_result(loaded)


def test_selected_key_scope_matches_source_store_semantics_and_order(sqlite_source) -> None:
    scope = TabularGroupingScope(
        selector_columns=("line", "station"),
        search_text="",
        filter_columns=(),
        selected_filter_keys=(),
        base_column_filters=(
            TabularColumnFilter("supplier", selected_values=("KEEP",)),
        ),
        selected_group_keys=(("A", "S1"), ("(blank)", "S2")),
    )
    expected_ids = sqlite_source.row_ids_for_group_keys(
        scope.selector_columns,
        scope.selected_group_keys,
        base_column_filters=scope.base_column_filters,
    )
    store = TabularGroupingAssignmentStore(sqlite_source)
    try:
        assignments = store.assignments(
            (AssignGroupingScope("Selected", "#123456", scope),),
            default_group="POPULATION",
        )

        assert expected_ids == [1, 3]
        assert [assignment.row_id for assignment in assignments] == expected_ids
        assert [assignment.group_name for assignment in assignments] == ["Selected", "Selected"]
        assert [assignment.color for assignment in assignments] == ["#123456", "#123456"]
    finally:
        store.cleanup()


def test_scope_indexes_are_prepared_before_assignment_transaction(sqlite_source) -> None:
    scope = TabularGroupingScope(
        selector_columns=("tracecode",),
        search_text="MATCH",
        filter_columns=(),
        selected_filter_keys=(),
        base_column_filters=(TabularColumnFilter("line", selected_values=("A",)),),
    )
    store = TabularGroupingAssignmentStore(sqlite_source)
    try:
        command = AssignGroupingScope("Matches", "#ABCDEF", scope)

        assert store.group_counts((command,), default_group="POPULATION").as_dict() == {
            "Matches": 2,
            "POPULATION": 2,
        }
        assert [
            assignment.row_id
            for assignment in store.assignments((command,), default_group="POPULATION")
        ] == [1, 2]
    finally:
        store.cleanup()


def test_incremental_commands_update_rename_delete_and_deassign(sqlite_source) -> None:
    store = TabularGroupingAssignmentStore(sqlite_source)
    commands = [AssignGroupingRows("First", "#111111", (3, 1))]
    try:
        assert [row.row_id for row in store.assignments(commands, default_group="POPULATION")] == [1, 3]

        commands.append(AssignGroupingRows("Second", "#222222", (3,)))
        commands.append(RenameGroupingGroup("First", "Renamed", "#333333"))
        commands.append(DeleteGroupingGroup("Second"))
        assignments = store.assignments(commands, default_group="POPULATION")
        assert [(row.row_id, row.group_name, row.color) for row in assignments] == [
            (1, "Renamed", "#333333")
        ]

        commands.append(AssignGroupingRows("POPULATION", "#FFFFFF", (1,)))
        assert store.assignments(commands, default_group="POPULATION") == ()
    finally:
        store.cleanup()


def test_concurrent_stores_use_isolated_temp_tables_and_idempotent_cleanup(sqlite_source) -> None:
    first = TabularGroupingAssignmentStore(sqlite_source)
    second = TabularGroupingAssignmentStore(sqlite_source)
    first_command = (AssignGroupingRows("First", "#111111", (1,)),)
    second_command = (AssignGroupingRows("Second", "#222222", (2,)),)
    try:
        assert [row.row_id for row in first.assignments(first_command, default_group="POPULATION")] == [1]
        assert [row.row_id for row in second.assignments(second_command, default_group="POPULATION")] == [2]
        assert first.table_name != second.table_name
        assert first._connection.execute(
            "SELECT name FROM sqlite_temp_master WHERE name = ?",
            (first.table_name,),
        ).fetchone() == (first.table_name,)
        with sqlite_connection_scope(sqlite_source.path) as connection:
            leaked = connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE '__metroliza_grouping_assignments_%'"
            ).fetchall()
        assert leaked == []

        first.cleanup()
        first.cleanup()
        assert [row.row_id for row in second.assignments(second_command, default_group="POPULATION")] == [2]
    finally:
        first.cleanup()
        second.cleanup()


def test_cleanup_failure_is_explicit_and_closes_session(sqlite_source) -> None:
    class _BrokenConnection:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, _query):
            raise RuntimeError("drop failed")

        def close(self):
            self.closed = True

    store = TabularGroupingAssignmentStore(sqlite_source)
    broken_connection = _BrokenConnection()
    store._connection = broken_connection

    with pytest.raises(TabularGroupingAssignmentCleanupError, match="drop failed"):
        store.cleanup()

    assert broken_connection.closed is True
    assert store._connection is None
