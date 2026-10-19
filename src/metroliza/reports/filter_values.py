"""Snapshot filter choices with a bounded, database-change-aware cache."""

from collections import OrderedDict
import os
from pathlib import Path
from threading import Lock

from metroliza.reports.db import sqlite_readonly_connection_scope
from metroliza.reports.report_query_service import build_distinct_value_query
from metroliza.reports.report_schema import ensure_report_schema


FILTER_VALUE_SPECS = (
    ("ax_list", "AX", "vw_measurement_export"),
    ("header_list", "HEADER", "vw_measurement_export"),
    ("all_headers_list", "HEADER", "vw_measurement_export"),
    ("reference_list", "REFERENCE", "vw_report_overview"),
    ("part_name_list", "PART_NAME", "vw_report_overview"),
    ("revision_list", "REVISION", "vw_report_overview"),
    ("template_variant_list", "TEMPLATE_VARIANT", "vw_report_overview"),
    ("sample_number_list", "SAMPLE_NUMBER", "vw_report_overview"),
    ("operator_name_list", "OPERATOR_NAME", "vw_report_overview"),
    ("sample_number_kind_list", "SAMPLE_NUMBER_KIND", "vw_report_overview"),
    ("status_code_list", "STATUS_CODE", "vw_measurement_export"),
    ("filename_list", "FILENAME", "vw_report_overview"),
    ("parser_id_list", "PARSER_ID", "vw_report_overview"),
    ("template_family_list", "TEMPLATE_FAMILY", "vw_report_overview"),
)
_CACHE_LIMIT = 8
_CACHE = OrderedDict()
_CACHE_LOCK = Lock()
# Header bytes that change with content: the database header (offset 24 is its
# change counter; rollback-journal commits) and the WAL header (checkpoint
# sequence and salts; changes at each WAL restart). Commits that overwrite WAL
# frames within the existing length rely on mtime_ns. On POSIX the
# main database file is never opened: closing any descriptor of it would release
# every fcntl lock SQLite holds on it in this process. SQLite takes no locks on
# the -wal file, and Windows locks belong to their own handle.
_DATABASE_HEADER_BYTES = 100 if os.name == "nt" else 0
_WAL_HEADER_BYTES = 32


def _database_signature(path):
    """Watch replacement, rollback-mode writes, and commits to a live WAL."""
    signatures = []
    for candidate in (path, Path(str(path) + "-wal")):
        try:
            stat = candidate.stat()
            size = _DATABASE_HEADER_BYTES if candidate == path else _WAL_HEADER_BYTES
            try:
                header = b""
                if size:
                    with candidate.open("rb") as source:
                        header = source.read(size)
            except FileNotFoundError:
                raise
            except OSError:
                # Briefly unreadable (e.g. a Windows sharing lock): this unique
                # value never matches, so the snapshot is simply not cached.
                header = object()
            # A read-only WAL connection may create an empty sidecar. It carries
            # no committed changes and is equivalent to an absent WAL.
            # Ignore ctime: readers may change it without changing any content
            # (and on CPython 3.11 Windows it is only the creation time).
            signatures.append(
                None if candidate != path and stat.st_size == 0 else
                (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, header)
            )
        except FileNotFoundError:
            signatures.append(None)
    return tuple(signatures)


def _cached_values(key, signature):
    with _CACHE_LOCK:
        # Discard every cached scope for a changed database, not just this one.
        for old_key, (old_signature, _) in tuple(_CACHE.items()):
            if old_key[0] == key[0] and old_signature != signature:
                del _CACHE[old_key]
        entry = _CACHE.get(key)
        if entry is None:
            return None
        _CACHE.move_to_end(key)
        return dict(entry[1])


def _remember_values(key, signature, values):
    with _CACHE_LOCK:
        _CACHE[key] = (signature, dict(values))
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)


def _query_values(connection, filter_query, specs, cancelled):
    values = {}
    queries = {}
    for attribute, column, view in specs:
        if cancelled():
            raise InterruptedError("Filter loading cancelled")
        query = build_distinct_value_query(column, source_view=view, filter_query=filter_query)
        if query not in queries:
            queries[query] = tuple(row[0] for row in connection.execute(query))
        values[attribute] = queries[query]
    return values


def load_filter_values(database, filter_query=None, *, specs=FILTER_VALUE_SPECS, cancelled=lambda: False):
    """Load immutable ordered choices; own all SQLite connections in the caller thread.

    A changed file/WAL invalidates all scopes. Only an unchanged read snapshot is
    cached, so a writer racing the load cannot publish an old snapshot as current.
    No connection or Qt object is kept in the process-wide LRU.
    """
    if cancelled():
        raise InterruptedError("Filter loading cancelled")
    if not str(database or "").strip():
        return {attribute: () for attribute, _, _ in specs}
    path = Path(database).resolve()
    key = (str(path), filter_query or "", tuple(specs))
    signature = _database_signature(path)
    cached = _cached_values(key, signature)
    if cached is not None:
        return cached
    ensure_report_schema(str(path))
    signature = _database_signature(path)
    with sqlite_readonly_connection_scope(str(path)) as connection:
        connection.set_progress_handler(lambda: int(cancelled()), 1000)
        connection.execute("BEGIN")
        values = _query_values(connection, filter_query, specs, cancelled)
    if not cancelled() and _database_signature(path) == signature:
        _remember_values(key, signature, values)
    return values
