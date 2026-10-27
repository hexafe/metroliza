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


def test_effective_assignments_preserve_persistent_catalog_and_literal_state(sqlite_source):
    with sqlite_connection_scope(sqlite_source.path) as connection:
        before = connection.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
    store = TabularGroupingAssignmentStore(sqlite_source, table_name='oracle_assignments')
    commands = (
        AssignGroupingRows('001', '#112233', (4, 1, 1)),
        AssignGroupingRows(' ', '#445566', (2,)),
        RenameGroupingGroup('001', '1', '#778899'),
    )
    try:
        assert [(a.row_id, a.group_name, a.color) for a in store.assignments(commands, default_group='POPULATION')] == [
            (1, '1', '#778899'), (2, ' ', '#445566'), (4, '1', '#778899')
        ]
        assert store.group_counts(commands, default_group='POPULATION').as_dict() == {' ': 1, '1': 2, 'POPULATION': 1}
        assert store.group_members(commands, default_group='POPULATION', group_name='1', limit=1).row_ids == (1,)
        with sqlite_connection_scope(sqlite_source.path) as connection:
            assert connection.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall() == before
    finally:
        store.cleanup()
    assert store._connection is None


def test_effective_group_name_index_is_temp_used_and_removed(sqlite_source):
    store = TabularGroupingAssignmentStore(sqlite_source, table_name='indexed_assignments')
    try:
        commands = (AssignGroupingRows('A', '#123456', (1, 3)),)
        store.assignments(commands, default_group='POPULATION')
        connection = store._connection
        assert connection.execute("SELECT name FROM sqlite_temp_master WHERE type='index'").fetchall() == [
            ('indexed_assignments_group_name',)
        ]
        plan = connection.execute(
            'EXPLAIN QUERY PLAN SELECT row_id FROM indexed_assignments WHERE group_name=? ORDER BY row_id LIMIT 2', ('A',)
        ).fetchall()
        assert any('USING COVERING INDEX indexed_assignments_group_name' in row[-1] for row in plan)
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'indexed_assignments%'").fetchall()
        connection.execute('DROP TABLE indexed_assignments')
        assert not connection.execute("SELECT name FROM sqlite_temp_master WHERE name LIKE 'indexed_assignments%'").fetchall()
    finally:
        store.cleanup()


@pytest.mark.parametrize("keys, expected", [
    ((("A", "S1"), ("A", "S1"), ("(blank)", "S2")), [(1, "Żółć", "#123456"), (3, "Żółć", "#123456")]),
    ((("wrong",),), []),
    (((),), []),
])
def test_t23a_literal_selected_key_oracle(sqlite_source, keys, expected):
    store = TabularGroupingAssignmentStore(sqlite_source)
    scope = TabularGroupingScope(
        selector_columns=("line", "station"), search_text="", filter_columns=(),
        selected_filter_keys=(), base_column_filters=(), selected_group_keys=keys,
    )
    try:
        rows = store.assignments((AssignGroupingScope("Żółć", "#123456", scope),), default_group="POPULATION")
        assert [(row.row_id, row.group_name, row.color) for row in rows] == expected
    finally:
        store.cleanup()
    assert store._connection is None


def test_t23a_compound_keys_above_expression_limit_and_temp_cleanup(sqlite_source):
    scope = TabularGroupingScope(
        selector_columns=("line", "station"), search_text="", filter_columns=(),
        selected_filter_keys=(), base_column_filters=(),
        selected_group_keys=tuple((f"missing-{i}", "S") for i in range(1500)) + (("A", "S1"), ("A", "S1"), ("(blank)", "S2")),
    )
    store = TabularGroupingAssignmentStore(sqlite_source)
    commands = (AssignGroupingScope("Selected", "#123456", scope),)
    try:
        assert [(r.row_id, r.group_name) for r in store.assignments(commands, default_group="POPULATION")] == [(1, "Selected"), (3, "Selected")]
        connection = store._connection
        assert not connection.execute("SELECT name FROM sqlite_temp_master WHERE name LIKE 'temp_grouping_selected_keys_%'").fetchall()
        store.invalidate()
        assert store.group_counts(commands, default_group="POPULATION").as_dict() == {"Selected": 2, "POPULATION": 2}
        assert store._connection is connection
    finally:
        store.cleanup()


@pytest.mark.parametrize("error", [RuntimeError("scope failed"), KeyboardInterrupt("cancel")])
@pytest.mark.parametrize("incremental", [False, True])
def test_t23a_selected_key_table_cleanup_after_failure(sqlite_source, monkeypatch, error, incremental):
    scope = TabularGroupingScope(
        selector_columns=("line",), search_text="", filter_columns=(),
        selected_filter_keys=(), base_column_filters=(), selected_group_keys=(("A",),),
    )
    store = TabularGroupingAssignmentStore(sqlite_source)
    initial = (AssignGroupingRows("First", "red", (3,)),) if incremental else ()
    if initial:
        assert [row.row_id for row in store.assignments(initial, default_group="POPULATION")] == [3]
    original = TabularGroupingAssignmentStore._apply_scope_query
    def fail(*args):
        raise error
    monkeypatch.setattr(TabularGroupingAssignmentStore, "_apply_scope_query", fail)
    try:
        with pytest.raises(type(error), match=str(error)):
            store.assignments((*initial, AssignGroupingScope("A", "red", scope)), default_group="POPULATION")
        connection = store._connection
        assert not store._connection.execute("SELECT name FROM sqlite_temp_master WHERE name LIKE 'temp_grouping_selected_keys_%'").fetchall()
        monkeypatch.setattr(TabularGroupingAssignmentStore, "_apply_scope_query", original)
        assert [r.row_id for r in store.assignments((*initial, AssignGroupingScope("A", "red", scope)), default_group="POPULATION")] == ([1, 2, 3] if incremental else [1, 2])
        assert store._connection is connection
    finally:
        store.cleanup()


def test_t23a_custom_store_retains_general_selected_key_path(sqlite_source, monkeypatch):
    from dataclasses import fields
    from metroliza.tabular.tabular_analytics_service import TabularSqliteStore
    class CustomStore(TabularSqliteStore):
        pass
    custom = CustomStore(**{f.name: getattr(sqlite_source, f.name) for f in fields(sqlite_source) if f.init})
    store = TabularGroupingAssignmentStore(custom)
    scope = TabularGroupingScope(
        selector_columns=("line", "station"), search_text="", filter_columns=(),
        selected_filter_keys=(), base_column_filters=(), selected_group_keys=(("A", "S2"),),
    )
    try:
        query, params = store._selected_group_keys_query(scope)
        assert " IN (SELECT " not in query
        assert params[-2:] == ["A", "S2"]
        assert [r.row_id for r in store.assignments((AssignGroupingScope("A", "red", scope),), default_group="POPULATION")] == [2]
    finally:
        store.cleanup()


def test_t23a_selected_keys_exceed_connection_parameter_limit(sqlite_source):
    import sqlite3
    store = TabularGroupingAssignmentStore(sqlite_source)
    try:
        assert store.assignments((), default_group="POPULATION") == ()
        old_limit = store._connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 9)
        scope = TabularGroupingScope(
            selector_columns=("line",), search_text="", filter_columns=(),
            selected_filter_keys=(), base_column_filters=(),
            selected_group_keys=tuple((f"absent-{i}",) for i in range(120)) + (("A",),),
        )
        assert [r.row_id for r in store.assignments((AssignGroupingScope("A", "red", scope),), default_group="POPULATION")] == [1, 2]
        store._connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, old_limit)
    finally:
        store.cleanup()


def test_t23a_inherited_store_does_not_dispatch_new_helper_collisions(sqlite_source):
    class CustomStore(TabularGroupingAssignmentStore):
        def _selected_key_scope(self, *args):
            raise AssertionError("old subclass helper")
        def _apply_scope_query(self, *args):
            raise AssertionError("old subclass helper")
    store = CustomStore(sqlite_source)
    scope = TabularGroupingScope(
        selector_columns=("line",), search_text="", filter_columns=(),
        selected_filter_keys=(), base_column_filters=(), selected_group_keys=(("A",),),
    )
    try:
        assert [r.row_id for r in store.assignments((AssignGroupingScope("A", "red", scope),), default_group="POPULATION")] == [1, 2]
    finally:
        store.cleanup()
