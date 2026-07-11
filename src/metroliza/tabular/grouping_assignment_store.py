"""SQLite persistence boundary for tabular grouping assignments."""

from __future__ import annotations

import threading
import uuid
from types import MappingProxyType
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, TypeAlias, TypeVar

from metroliza.reports.db import connect_sqlite
from metroliza.tabular.tabular_analytics_service import TabularColumnFilter, TabularSqliteStore


@dataclass(frozen=True)
class TabularGroupingScope:
    """Deferred source-row scope used by an assignment command."""

    selector_columns: tuple[str, ...]
    search_text: str
    filter_columns: tuple[str, ...]
    selected_filter_keys: tuple[tuple[str, ...], ...]
    base_column_filters: tuple[TabularColumnFilter, ...]
    base_filter_expression: str = ""
    filter_aliases: Mapping[str, str] = field(default_factory=dict)
    grouping_filter: object | None = None
    selected_group_keys: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "selector_columns",
            tuple(str(column) for column in self.selector_columns),
        )
        object.__setattr__(
            self,
            "filter_columns",
            tuple(str(column) for column in self.filter_columns),
        )
        object.__setattr__(
            self,
            "selected_filter_keys",
            tuple(tuple(str(part) for part in key) for key in self.selected_filter_keys),
        )
        object.__setattr__(self, "base_column_filters", tuple(self.base_column_filters))
        object.__setattr__(self, "filter_aliases", MappingProxyType(dict(self.filter_aliases)))
        object.__setattr__(
            self,
            "selected_group_keys",
            tuple(tuple(str(part) for part in key) for key in self.selected_group_keys),
        )


@dataclass(frozen=True)
class AssignGroupingRows:
    """Assign explicit source rows to a group."""

    group_name: str
    color: str
    row_ids: tuple[int, ...]
    kind: Literal["rows"] = field(default="rows", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_name", str(self.group_name))
        object.__setattr__(self, "color", str(self.color))
        object.__setattr__(
            self,
            "row_ids",
            tuple(dict.fromkeys(int(row_id) for row_id in self.row_ids)),
        )


@dataclass(frozen=True)
class AssignGroupingScope:
    """Assign a deferred filtered or selected-key scope to a group."""

    group_name: str
    color: str
    scope: TabularGroupingScope
    kind: Literal["scope"] = field(default="scope", init=False)


@dataclass(frozen=True)
class DeleteGroupingGroup:
    """Remove all explicit assignments for one custom group."""

    group_name: str
    kind: Literal["delete_group"] = field(default="delete_group", init=False)


@dataclass(frozen=True)
class RenameGroupingGroup:
    """Rename one custom group and update its display color."""

    group_name: str
    replacement_group_name: str
    replacement_color: str
    kind: Literal["rename_group"] = field(default="rename_group", init=False)


TabularGroupingCommand: TypeAlias = (
    AssignGroupingRows
    | AssignGroupingScope
    | DeleteGroupingGroup
    | RenameGroupingGroup
)


@dataclass(frozen=True)
class TabularGroupingAssignment:
    """One effective persisted assignment in source-row order."""

    row_id: int
    group_name: str
    color: str


@dataclass(frozen=True)
class TabularGroupingCounts:
    """Effective custom/default group counts for the full source store."""

    counts: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, int]:
        return dict(self.counts)


@dataclass(frozen=True)
class TabularGroupingMembers:
    """Ordered preview row identifiers and the complete group size."""

    row_ids: tuple[int, ...]
    total: int


class TabularGroupingAssignmentCleanupError(RuntimeError):
    """Raised when an assignment table cannot be removed explicitly."""


_T = TypeVar("_T")


class TabularGroupingAssignmentStore:
    """Own deferred grouping commands and their transactional SQLite read model."""

    def __init__(
        self,
        source_store: TabularSqliteStore,
        *,
        table_name: str | None = None,
    ) -> None:
        self.source_store = source_store
        token = uuid.uuid4().hex
        self.table_name = table_name or f"__metroliza_grouping_assignments_{token}"
        self._scope_table_name = f"temp_grouping_assignment_scope_{token}"
        self._applied_commands: tuple[TabularGroupingCommand, ...] = ()
        self._reset_required = True
        self._lock = threading.RLock()
        self._connection: Any = None

    def invalidate(self) -> None:
        """Force the next read to rebuild from the supplied command sequence."""

        with self._lock:
            self._applied_commands = ()
            self._reset_required = True

    def assignments(
        self,
        commands: tuple[TabularGroupingCommand, ...] | list[TabularGroupingCommand],
        *,
        default_group: str,
    ) -> tuple[TabularGroupingAssignment, ...]:
        """Return effective assignments ordered by source row identifier."""

        def read(connection, table_name: str) -> tuple[TabularGroupingAssignment, ...]:
            rows = connection.execute(
                f"SELECT row_id, group_name, color FROM {table_name} ORDER BY row_id"
            ).fetchall()
            return tuple(
                TabularGroupingAssignment(
                    row_id=int(row_id),
                    group_name=str(group_name),
                    color=str(color),
                )
                for row_id, group_name, color in rows
            )

        return self._read_effective_table(commands, default_group=default_group, reader=read)

    def group_counts(
        self,
        commands: tuple[TabularGroupingCommand, ...] | list[TabularGroupingCommand],
        *,
        default_group: str,
    ) -> TabularGroupingCounts:
        """Return custom assignment counts plus the unassigned/default count."""

        source_scope = self.source_store.query_scope(columns=("source_row_number",))

        def read(connection, table_name: str) -> TabularGroupingCounts:
            total_rows = int(
                connection.execute(
                    source_scope.row_count_sql,
                    source_scope.params,
                ).fetchone()[0]
                or 0
            )
            rows = connection.execute(
                f"SELECT group_name, COUNT(*) FROM {table_name} GROUP BY group_name"
            ).fetchall()
            assigned_count = int(
                connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0] or 0
            )
            counts = [
                (str(group_name), int(row_count or 0))
                for group_name, row_count in rows
                if str(group_name) != default_group
            ]
            default_count = max(0, total_rows - assigned_count)
            if default_count or not counts:
                counts.append((default_group, default_count))
            return TabularGroupingCounts(tuple(counts))

        return self._read_effective_table(commands, default_group=default_group, reader=read)

    def group_members(
        self,
        commands: tuple[TabularGroupingCommand, ...] | list[TabularGroupingCommand],
        *,
        default_group: str,
        group_name: str,
        limit: int,
    ) -> TabularGroupingMembers:
        """Return an ordered member preview and the full custom-group count."""

        normalized_limit = max(0, int(limit))

        def read(connection, table_name: str) -> TabularGroupingMembers:
            rows = connection.execute(
                f"SELECT row_id FROM {table_name} "
                "WHERE group_name = ? ORDER BY row_id LIMIT ?",
                (group_name, normalized_limit),
            ).fetchall()
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE group_name = ?",
                    (group_name,),
                ).fetchone()[0]
                or 0
            )
            return TabularGroupingMembers(
                row_ids=tuple(int(row[0]) for row in rows),
                total=total,
            )

        return self._read_effective_table(commands, default_group=default_group, reader=read)

    def cleanup(self) -> None:
        """Drop this dialog's assignment table or raise an explicit cleanup error."""

        with self._lock:
            connection = self._connection
            if connection is None:
                self._applied_commands = ()
                self._reset_required = True
                return
            cleanup_error: Exception | None = None
            try:
                with connection:
                    connection.execute(
                        f"DROP TABLE IF EXISTS {_quote_identifier(self.table_name)}"
                    )
            except Exception as exc:
                cleanup_error = exc
            try:
                connection.close()
            except Exception as exc:
                cleanup_error = cleanup_error or exc
            self._connection = None
            self._applied_commands = ()
            self._reset_required = True
            if cleanup_error is not None:
                raise TabularGroupingAssignmentCleanupError(
                    f"Could not remove tabular grouping assignment table "
                    f"{self.table_name}: {cleanup_error}"
                ) from cleanup_error

    def _read_effective_table(
        self,
        commands: tuple[TabularGroupingCommand, ...] | list[TabularGroupingCommand],
        *,
        default_group: str,
        reader: Any,
    ) -> _T:
        normalized_commands = tuple(commands)
        with self._lock:
            replay_start = self._replay_start(normalized_commands)
            scope_queries = {
                index: self._scope_query(command.scope)
                for index, command in enumerate(normalized_commands[replay_start:], replay_start)
                if isinstance(command, AssignGroupingScope)
            }
            connection = self._connection
            if connection is None:
                connection = connect_sqlite(self.source_store.path)
                self._connection = connection
            with connection:
                table_name = self._prepare_effective_table(
                    connection,
                    normalized_commands,
                    default_group=default_group,
                    replay_start=replay_start,
                    scope_queries=scope_queries,
                )
                result: _T = reader(connection, table_name)
            self._applied_commands = normalized_commands
            self._reset_required = False
            return result

    def _replay_start(self, commands: tuple[TabularGroupingCommand, ...]) -> int:
        applied_count = len(self._applied_commands)
        if (
            self._reset_required
            or applied_count > len(commands)
            or commands[:applied_count] != self._applied_commands
        ):
            return 0
        return applied_count

    def _prepare_effective_table(
        self,
        connection: Any,
        commands: tuple[TabularGroupingCommand, ...],
        *,
        default_group: str,
        replay_start: int,
        scope_queries: Mapping[int, tuple[str, list[Any]]],
    ) -> str:
        table_name = _quote_identifier(self.table_name)
        connection.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {table_name} ("
            "row_id INTEGER PRIMARY KEY, "
            "group_name TEXT NOT NULL, "
            "color TEXT NOT NULL)"
        )
        if replay_start == 0:
            connection.execute(f"DELETE FROM {table_name}")
        for index, command in enumerate(commands[replay_start:], replay_start):
            self._apply_command(
                connection,
                table_name,
                command,
                default_group=default_group,
                scope_query=scope_queries.get(index),
            )
        return table_name

    def _apply_command(
        self,
        connection: Any,
        table_name: str,
        command: TabularGroupingCommand,
        *,
        default_group: str,
        scope_query: tuple[str, list[Any]] | None,
    ) -> None:
        if isinstance(command, AssignGroupingRows):
            self._apply_rows_command(
                connection,
                table_name,
                command,
                default_group=default_group,
            )
            return
        if isinstance(command, AssignGroupingScope):
            self._apply_scope_command(
                connection,
                table_name,
                command,
                default_group=default_group,
                scope_query=scope_query,
            )
            return
        if isinstance(command, DeleteGroupingGroup):
            connection.execute(
                f"DELETE FROM {table_name} WHERE group_name = ?",
                (command.group_name,),
            )
            return
        if isinstance(command, RenameGroupingGroup):
            connection.execute(
                f"UPDATE {table_name} SET group_name = ?, color = ? WHERE group_name = ?",
                (
                    command.replacement_group_name,
                    command.replacement_color,
                    command.group_name,
                ),
            )
            return
        raise TypeError(f"Unsupported tabular grouping command: {type(command).__name__}")

    @staticmethod
    def _apply_rows_command(
        connection: Any,
        table_name: str,
        command: AssignGroupingRows,
        *,
        default_group: str,
    ) -> None:
        row_ids = tuple(dict.fromkeys(int(row_id) for row_id in command.row_ids))
        if not row_ids:
            return
        if command.group_name == default_group:
            for start in range(0, len(row_ids), 900):
                chunk = row_ids[start : start + 900]
                placeholders = ", ".join("?" for _row_id in chunk)
                connection.execute(
                    f"DELETE FROM {table_name} WHERE row_id IN ({placeholders})",
                    chunk,
                )
            return
        connection.executemany(
            f"INSERT INTO {table_name} (row_id, group_name, color) VALUES (?, ?, ?) "
            "ON CONFLICT(row_id) DO UPDATE SET "
            "group_name = excluded.group_name, color = excluded.color",
            ((row_id, command.group_name, command.color) for row_id in row_ids),
        )

    def _apply_scope_command(
        self,
        connection: Any,
        table_name: str,
        command: AssignGroupingScope,
        *,
        default_group: str,
        scope_query: tuple[str, list[Any]] | None,
    ) -> None:
        query, params = scope_query or ("", [])
        if not query:
            return
        scope_table = _quote_identifier(self._scope_table_name)
        connection.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS {scope_table} (row_id INTEGER PRIMARY KEY)"
        )
        connection.execute(f"DELETE FROM {scope_table}")
        connection.execute(
            f"INSERT OR IGNORE INTO {scope_table} (row_id) "
            f"SELECT source_row_number FROM ({query})",
            params,
        )
        if command.group_name == default_group:
            connection.execute(
                f"DELETE FROM {table_name} WHERE row_id IN (SELECT row_id FROM {scope_table})"
            )
            return
        connection.execute(
            f"UPDATE {table_name} SET group_name = ?, color = ? "
            f"WHERE row_id IN (SELECT row_id FROM {scope_table})",
            (command.group_name, command.color),
        )
        connection.execute(
            f"INSERT OR IGNORE INTO {table_name} (row_id, group_name, color) "
            f"SELECT row_id, ?, ? FROM {scope_table}",
            (command.group_name, command.color),
        )

    def _scope_query(self, scope: TabularGroupingScope) -> tuple[str, list[Any]]:
        if scope.selected_group_keys:
            return self._selected_group_keys_query(scope)
        if scope.search_text:
            return self.source_store.source_row_number_query_for_group_search(
                scope.selector_columns,
                search_text=scope.search_text,
                filter_columns=scope.filter_columns,
                selected_filter_keys=scope.selected_filter_keys,
                base_column_filters=scope.base_column_filters,
                grouping_filter_expression=scope.base_filter_expression,
                grouping_filter_aliases=scope.filter_aliases,
                grouping_filter=scope.grouping_filter,
            )
        return self.source_store.source_row_number_query(
            filter_columns=scope.filter_columns,
            selected_filter_keys=scope.selected_filter_keys,
            base_column_filters=scope.base_column_filters,
            grouping_filter_expression=scope.base_filter_expression,
            grouping_filter_aliases=scope.filter_aliases,
            grouping_filter=scope.grouping_filter,
        )

    def _selected_group_keys_query(
        self,
        scope: TabularGroupingScope,
    ) -> tuple[str, list[Any]]:
        columns = tuple(
            str(column)
            for column in scope.selector_columns
            if str(column) in self.source_store.columns
        )
        selected_keys = tuple(
            tuple(str(part) for part in key)
            for key in scope.selected_group_keys
            if len(key) == len(columns)
        )
        if not columns or not selected_keys:
            return "", []

        base_scope = self.source_store.query_scope(
            filter_columns=scope.filter_columns,
            selected_filter_keys=scope.selected_filter_keys,
            base_column_filters=scope.base_column_filters,
            columns=("source_row_number", *columns),
            grouping_filter_expression=scope.base_filter_expression,
            grouping_filter_aliases=scope.filter_aliases,
            grouping_filter=scope.grouping_filter,
        )
        key_params: list[Any] = []
        predicate = _selected_key_predicate(columns, selected_keys, key_params)
        row_column = _quote_identifier("source_row_number")
        query = (
            f"SELECT {row_column} FROM ({base_scope.sql}) AS selected_grouping_scope "
            f"WHERE {predicate}"
        )
        return query, [*base_scope.params, *key_params]


def _selected_key_predicate(
    columns: tuple[str, ...],
    selected_keys: tuple[tuple[str, ...], ...],
    params: list[Any],
) -> str:
    if len(columns) == 1:
        expression = _normalized_value_expression(columns[0])
        values = [str(key[0]) for key in selected_keys]
        clauses: list[str] = []
        for start in range(0, len(values), 900):
            chunk = values[start : start + 900]
            placeholders = ", ".join("?" for _value in chunk)
            clauses.append(f"{expression} IN ({placeholders})")
            params.extend(chunk)
        return f"({' OR '.join(clauses)})"

    key_clauses: list[str] = []
    for key in selected_keys:
        parts: list[str] = []
        for column, value in zip(columns, key, strict=False):
            parts.append(f"{_normalized_value_expression(column)} = ?")
            params.append(str(value))
        key_clauses.append(f"({' AND '.join(parts)})")
    return f"({' OR '.join(key_clauses)})"


def _normalized_value_expression(column: str) -> str:
    identifier = _quote_identifier(column)
    return f"COALESCE(NULLIF(TRIM(CAST({identifier} AS TEXT)), ''), '(blank)')"


def _quote_identifier(identifier: str) -> str:
    escaped = str(identifier).replace('"', '""')
    return f'"{escaped}"'


__all__ = [
    "AssignGroupingRows",
    "AssignGroupingScope",
    "DeleteGroupingGroup",
    "RenameGroupingGroup",
    "TabularGroupingAssignment",
    "TabularGroupingAssignmentCleanupError",
    "TabularGroupingAssignmentStore",
    "TabularGroupingCommand",
    "TabularGroupingCounts",
    "TabularGroupingMembers",
    "TabularGroupingScope",
]
