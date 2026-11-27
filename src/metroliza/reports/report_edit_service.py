"""Transactional write boundary for report metadata editing workflows."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from metroliza.reports.db import quote_identifier, run_transaction_with_retry, sqlite_file_identity
from metroliza.reports.report_curation import StoredOcrApproval
from metroliza.reports.report_edit_audit import (
    AUDIT_SAMPLE_LIMIT,
    ReportEditReceipt,
    normalization_sample,
    persist_confirmed_receipt,
    read_sample_values,
    record_sample_targets,
    sampled_record_edits,
    unobservable_legacy_tables,
)
from metroliza.reports.report_repository import ReportRepository, validate_manual_number


SQLStatement = tuple[str, tuple[Any, ...]]
ValueChange = tuple[str, str]
RecordUpdate = tuple[int, dict[str, Any]]


@dataclass(frozen=True, repr=False)
class ReportEditExpectations:
    """Values and scope from the editor snapshot the user reviewed."""

    report_values: tuple[RecordUpdate, ...] = ()
    measurement_values: tuple[RecordUpdate, ...] = ()
    report_sources: tuple[tuple[int, int], ...] = ()
    measurement_owners: tuple[tuple[int, int | None], ...] = ()
    normalization_counts: Mapping[str, Mapping[str, int]] = dataclass_field(default_factory=dict)
    database_identity: tuple[int, int] | None = None


class ReportEditConflictError(ValueError):
    """The database changed after the editor loaded and needs a fresh review."""


_STALE_EDIT_MESSAGE = "The database changed after these records were loaded. Reopen the editor and review the latest values."
_NATIVE_REPOSITORY = ReportRepository
_NATIVE_RECORD_METHODS = {
    name: getattr(_NATIVE_REPOSITORY, name)
    for name in ("update_report_metadata_fields", "update_measurement_fields")
}
_NORMALIZATION_BATCH_SIZE = 128
_CURRENT_METADATA_NORMALIZATION_SQL = {
    "reference": (
        "SELECT count(*) FROM report_metadata WHERE reference = ?",
        "SELECT report_id FROM report_metadata WHERE reference = ? ORDER BY report_id LIMIT ?",
        "SELECT report_id FROM report_metadata WHERE reference = ? AND report_id > ? ORDER BY report_id LIMIT ?",
    ),
    "sample_number": (
        "SELECT count(*) FROM report_metadata WHERE sample_number = ?",
        "SELECT report_id FROM report_metadata WHERE sample_number = ? ORDER BY report_id LIMIT ?",
        "SELECT report_id FROM report_metadata WHERE sample_number = ? AND report_id > ? ORDER BY report_id LIMIT ?",
    ),
}

NORMALIZATION_TARGETS = {
    "legacy": {
        "reference": ("REPORTS", "REFERENCE"),
        "sample_number": ("REPORTS", "SAMPLE_NUMBER"),
        "header": ("MEASUREMENTS", "HEADER"),
    },
    "current": {
        "reference": ("report_metadata", "reference"),
        "sample_number": ("report_metadata", "sample_number"),
        "header": ("report_measurements", "header"),
    },
}

_RECORD_EXISTS_SQL = {
    "legacy": {
        "report": "SELECT 1 FROM REPORTS WHERE ID = ? LIMIT 1",
        "measurement": "SELECT 1 FROM MEASUREMENTS WHERE ID = ? LIMIT 1",
    },
    "current": {
        "report": "SELECT 1 FROM parsed_reports WHERE id = ?",
        "measurement": "SELECT 1 FROM report_measurements WHERE id = ?",
    },
}

LEGACY_REPORT_FIELD_COLUMNS = {
    "reference": "REFERENCE",
    "report_date": "DATE",
    "sample_number": "SAMPLE_NUMBER",
}
LEGACY_MEASUREMENT_FIELD_COLUMNS = {
    "header": "HEADER",
    "ax": "AX",
    "nominal": "NOM",
    "tol_plus": "+TOL",
    "tol_minus": "-TOL",
    "bonus": "BONUS",
    "meas": "MEAS",
    "dev": "DEV",
    "outtol": "OUTTOL",
}


class ReportEditService:
    """Validate and persist edits collected by the Modify Database dialog."""

    def __init__(
        self,
        database: str,
        *,
        repository_factory: Callable[[str], object] = ReportRepository,
    ) -> None:
        self.database = str(database)
        self._repository_factory = repository_factory

    def apply_changes(
        self,
        *,
        storage_flavor: str,
        normalization_changes: Mapping[str, Iterable[ValueChange]],
        report_updates: Iterable[RecordUpdate] = (),
        measurement_updates: Iterable[RecordUpdate] = (),
        expected_edits: ReportEditExpectations | None = None,
        stored_ocr_approval: StoredOcrApproval | None = None,
    ) -> None:
        """Apply the entire confirmed edit batch as one retryable transaction."""

        if stored_ocr_approval is not None:
            self._apply_stored_ocr(storage_flavor, normalization_changes, report_updates, measurement_updates,
                                   expected_edits, stored_ocr_approval)
            return
        self._apply_changes(storage_flavor, normalization_changes, report_updates, measurement_updates,
                            expected_edits=expected_edits)

    def apply_changes_with_receipt(
        self,
        *,
        storage_flavor: str,
        normalization_changes: Mapping[str, Iterable[ValueChange]],
        report_updates: Iterable[RecordUpdate] = (),
        measurement_updates: Iterable[RecordUpdate] = (),
        expected_edits: ReportEditExpectations | None = None,
        stored_ocr_approval: StoredOcrApproval | None = None,
    ) -> ReportEditReceipt | None:
        """Return local audit samples after commit, if the native transaction is observable."""

        if type(self) is not ReportEditService:
            options = {"expected_edits": expected_edits} if expected_edits is not None else {}
            if stored_ocr_approval is not None:
                options["stored_ocr_approval"] = stored_ocr_approval
            self.apply_changes(
                storage_flavor=storage_flavor, normalization_changes=normalization_changes,
                report_updates=report_updates, measurement_updates=measurement_updates, **options,
            )
            return None
        if stored_ocr_approval is not None:
            self._apply_stored_ocr(storage_flavor, normalization_changes, report_updates, measurement_updates,
                                   expected_edits, stored_ocr_approval)
            return None
        return self._apply_changes(
            storage_flavor, normalization_changes, report_updates, measurement_updates,
            observe=True, expected_edits=expected_edits,
        )

    def _apply_stored_ocr(self, flavor, normalizations, reports, measurements, expected_edits, approval):
        if (self._validate_storage_flavor(flavor) != "current" or any(normalizations.values())
                or tuple(reports) or tuple(measurements)):
            raise ValueError("Review and accept the stored OCR suggestion separately from other edits.")
        self._check_database_identity(getattr(expected_edits, "database_identity", None))
        self._repository_factory(self.database).accept_deferred_ocr(approval)

    def _apply_changes(self, storage_flavor, normalization_changes, report_updates,
                       measurement_updates, *, observe=False, expected_edits=None):
        normalized_flavor = self._validate_storage_flavor(storage_flavor)
        database_identity = getattr(expected_edits, "database_identity", None)
        self._check_database_identity(database_identity)
        normalized_report_updates = self._normalize_record_updates(report_updates)
        normalized_measurement_updates = self._normalize_record_updates(measurement_updates)
        statements = self.build_normalization_update_statements(
            normalized_flavor,
            normalization_changes,
        )
        normalization_count = len(statements)
        normalized_measurement_updates = tuple(
            (record_id, self._validate_measurement_numbers(fields))
            for record_id, fields in normalized_measurement_updates
        )

        repository = None
        native_bulk = (normalized_flavor == "current" and bool(statements)
                       and type(self) is ReportEditService and self._repository_factory is _NATIVE_REPOSITORY)
        if normalized_flavor == "legacy":
            statements.extend(
                self.build_legacy_record_update_statements(
                    normalized_report_updates,
                    normalized_measurement_updates,
                )
            )
        elif normalized_report_updates or normalized_measurement_updates or native_bulk:
            repository = self._repository_factory(self.database)
            self.validate_record_update_methods(
                repository,
                normalized_report_updates,
                normalized_measurement_updates,
            )

        native_records = repository is None or self._uses_native_record_methods(repository)
        observable = (
            (observe or expected_edits is not None)
            and self._repository_factory is _NATIVE_REPOSITORY and native_records
        )
        normalization_repository = repository if native_bulk and native_records else None

        def apply_batch(cursor):
            cursor.execute("BEGIN IMMEDIATE")
            if expected_edits is not None:
                self._check_database_identity(database_identity)
                self._check_expected_edits(cursor, normalized_flavor, expected_edits,
                                          normalized_report_updates, normalized_measurement_updates)
            if observable:
                receipt = self._apply_observed_batch(
                    cursor, normalized_flavor, statements, normalization_count, repository,
                    normalized_report_updates, normalized_measurement_updates, normalization_repository,
                    expected_edits,
                )
                if expected_edits is not None:
                    persist_confirmed_receipt(cursor, receipt)
                    self._check_database_identity(database_identity)
                return receipt
            if normalization_repository is None:
                self.apply_update_statements(cursor, statements)
            else:
                self._apply_normalizations(cursor, normalized_flavor, statements, normalization_repository)
            self._apply_joined_record_updates(
                cursor, repository, normalized_report_updates, normalized_measurement_updates,
            )
            return None

        if statements or repository is not None:
            if not statements and repository is not None and not isinstance(repository, ReportRepository):
                # Custom adapters retain their own storage contract and dispatch hooks.
                self.apply_record_updates(repository, normalized_report_updates, normalized_measurement_updates)
                return None
            return run_transaction_with_retry(self.database, apply_batch)
        return None

    def _check_database_identity(self, expected_identity):
        if expected_identity is None:
            return
        try:
            identity = sqlite_file_identity(Path(self.database).resolve(strict=True))
        except (OSError, RuntimeError):
            identity = None
        if identity != expected_identity:
            raise ReportEditConflictError(_STALE_EDIT_MESSAGE)

    @staticmethod
    def _check_expected_edits(cursor, flavor, expected, reports, measurements):
        for field_name, counts in expected.normalization_counts.items():
            table, column = NORMALIZATION_TARGETS[flavor][field_name]
            query = f"SELECT count(*) FROM {quote_identifier(table)} WHERE {quote_identifier(column)} = ?"
            for text, count in counts.items():
                if cursor.execute(query, (text,)).fetchone() != (count,):
                    raise ReportEditConflictError(_STALE_EDIT_MESSAGE)

        owner_query = (
            "SELECT REPORT_ID FROM MEASUREMENTS WHERE ID = ? LIMIT 2" if flavor == "legacy"
            else "SELECT report_id FROM report_measurements WHERE id = ?"
        )
        for query, originals in (
            ("SELECT source_file_id FROM parsed_reports WHERE id = ?", expected.report_sources),
            (owner_query, expected.measurement_owners),
        ):
            for record_id, owner in originals:
                if cursor.execute(query, (record_id,)).fetchall() != [(owner,)]:
                    raise ReportEditConflictError(_STALE_EDIT_MESSAGE)

        ReportEditService._check_expected_record_values(cursor, flavor, expected, reports, measurements)

    @staticmethod
    def _check_expected_record_values(cursor, flavor, expected, reports, measurements):
        originals = {
            (entity, record_id, name): value
            for entity, updates in (("report", expected.report_values), ("measurement", expected.measurement_values))
            for record_id, fields in updates
            for name, value in fields.items()
        }
        for entity, updates in (("report", reports), ("measurement", measurements)):
            for record_id, changed_fields in updates:
                if any((entity, record_id, name) not in originals for name in changed_fields):
                    if cursor.execute(_RECORD_EXISTS_SQL[flavor][entity], (record_id,)).fetchone() is None:
                        raise ReportEditConflictError(f"{entity.capitalize()} {record_id} does not exist")
                    raise ReportEditConflictError(
                        f"{entity.capitalize()} {record_id} does not exist in the reviewed edits. "
                        "Reopen the editor and review the latest values."
                    )

        targets, truncated = record_sample_targets(
            flavor, expected.report_values, expected.measurement_values, len(originals),
            LEGACY_REPORT_FIELD_COLUMNS, LEGACY_MEASUREMENT_FIELD_COLUMNS,
        )
        if truncated or len(targets) != len(originals):
            raise ReportEditConflictError(_STALE_EDIT_MESSAGE)
        groups = {}
        for target in targets:
            group = (target.table, target.key, target.record_id)
            groups.setdefault(group, []).append(
                (target.column, originals[target.entity, target.record_id, target.field_name])
            )
        for (table, key, record_id), values in groups.items():
            columns = ", ".join(quote_identifier(column) for column, _ in values)
            query = f"SELECT {columns} FROM {quote_identifier(table)} WHERE {quote_identifier(key)} = ? LIMIT 2"
            actual = cursor.execute(query, (record_id,)).fetchall()
            if actual != [tuple(value for _, value in values)]:
                raise ReportEditConflictError(_STALE_EDIT_MESSAGE)

    @staticmethod
    def _uses_native_record_methods(repository):
        return type(repository) is _NATIVE_REPOSITORY and all(
            name not in vars(repository) and vars(_NATIVE_REPOSITORY).get(name) is method
            for name, method in _NATIVE_RECORD_METHODS.items()
        )

    def _apply_joined_record_updates(self, cursor, repository, reports, measurements):
        if repository is None:
            return
        with self._join_edit_transaction(cursor, repository):
            self.apply_record_updates(repository, reports, measurements)

    @staticmethod
    @contextmanager
    def _join_edit_transaction(cursor, repository):
        if isinstance(repository, ReportRepository):
            old_connection, old_join = repository.connection, repository.join_edit_transaction
            repository.connection, repository.join_edit_transaction = cursor.connection, True
            try:
                yield
            finally:
                repository.connection, repository.join_edit_transaction = old_connection, old_join
        else:
            yield

    def _apply_observed_batch(self, cursor, flavor, statements, normalization_count,
                              repository, reports, measurements, normalization_repository, expected_edits):
        remaining = max(0, AUDIT_SAMPLE_LIMIT - normalization_count)
        sampled, records_truncated = record_sample_targets(
            flavor, reports, measurements, remaining,
            LEGACY_REPORT_FIELD_COLUMNS, LEGACY_MEASUREMENT_FIELD_COLUMNS,
        )
        unavailable_tables = unobservable_legacy_tables(cursor, sampled) if flavor == "legacy" else frozenset()
        before = read_sample_values(cursor, sampled, unavailable_tables)
        normalization_samples = self._apply_normalizations(
            cursor, flavor, statements[:normalization_count], normalization_repository,
            sample_limit=AUDIT_SAMPLE_LIMIT,
            expected_counts=expected_edits.normalization_counts if expected_edits is not None else None,
        )
        for query, params in statements[normalization_count:]:
            cursor.execute(query, params)
        self._apply_joined_record_updates(cursor, repository, reports, measurements)
        record_samples, unavailable_count = sampled_record_edits(cursor, sampled, before, unavailable_tables)
        return ReportEditReceipt(
            storage_flavor=flavor,
            normalization_operation_count=normalization_count,
            normalization_samples=tuple(normalization_samples),
            record_samples=record_samples,
            unavailable_record_sample_count=unavailable_count,
            samples_truncated=normalization_count > AUDIT_SAMPLE_LIMIT or records_truncated,
        )

    def _apply_normalizations(self, cursor, flavor, statements, repository, *, sample_limit=0, expected_counts=None):
        fields_by_query = {
            self.build_value_update_statements(table, column, (("", ""),))[0][0]: name
            for name, (table, column) in NORMALIZATION_TARGETS[flavor].items()
        }
        samples = []
        with self._join_edit_transaction(cursor, repository):
            for query, params in statements:
                field_name = fields_by_query[query]
                if repository is not None and field_name in _CURRENT_METADATA_NORMALIZATION_SQL:
                    matched = self._normalize_report_metadata(cursor, repository, field_name, params)
                else:
                    cursor.execute(query, params)
                    matched = cursor.rowcount
                if expected_counts is not None and matched != expected_counts.get(field_name, {}).get(params[1]):
                    raise ReportEditConflictError(
                        "The normalization changes would affect a different number of records than shown. "
                        "Review one replacement at a time if the values overlap."
                    )
                if len(samples) < sample_limit:
                    samples.append(normalization_sample(field_name, params, matched))
        return samples

    @staticmethod
    def _normalize_report_metadata(cursor, repository, field_name, params):
        new_value, old_value = params
        count_query, first_query, next_query = _CURRENT_METADATA_NORMALIZATION_SQL[field_name]
        if new_value == old_value:
            return cursor.execute(count_query, (old_value,)).fetchone()[0]

        matched = 0
        page = cursor.execute(first_query, (old_value, _NORMALIZATION_BATCH_SIZE)).fetchall()
        while page:
            # Finish the read before changing any row from SQLite's matching index.
            for (report_id,) in page:
                repository.update_report_metadata_fields(report_id, {field_name: new_value}, reason="bulk_normalization")
            matched += len(page)
            if len(page) < _NORMALIZATION_BATCH_SIZE:
                break
            page = cursor.execute(next_query, (old_value, page[-1][0], _NORMALIZATION_BATCH_SIZE)).fetchall()
        return matched

    @staticmethod
    def _validate_measurement_numbers(fields):
        normalized = dict(fields)
        for field in {"nominal", "tol_plus", "tol_minus", "bonus", "meas", "dev", "outtol"}.intersection(fields):
            normalized[field] = validate_manual_number(fields[field])
        for field in {"page_number", "row_order"}.intersection(fields):
            normalized[field] = validate_manual_number(fields[field], integer=True)
        if "status_code" in fields:
            # Validate the whole batch before the first mutation where possible.
            normalized["status_code"] = ReportRepository._prepare_measurement_field_updates(
                {"status_code": fields["status_code"]}
            )["status_code"]
        return normalized

    @staticmethod
    def _validate_storage_flavor(storage_flavor: str) -> str:
        normalized = str(storage_flavor).strip().lower()
        if normalized not in NORMALIZATION_TARGETS:
            raise ValueError(f"Unsupported report edit storage flavor: {storage_flavor}")
        return normalized

    @staticmethod
    def _normalize_record_updates(updates: Iterable[RecordUpdate]) -> tuple[RecordUpdate, ...]:
        return tuple((int(record_id), dict(fields)) for record_id, fields in updates)

    @classmethod
    def build_normalization_update_statements(
        cls,
        storage_flavor: str,
        changes_by_field: Mapping[str, Iterable[ValueChange]],
    ) -> list[SQLStatement]:
        normalized_flavor = cls._validate_storage_flavor(storage_flavor)
        targets = NORMALIZATION_TARGETS[normalized_flavor]
        unknown_fields = set(changes_by_field) - set(targets)
        if unknown_fields:
            raise ValueError(f"Unsupported normalization fields: {sorted(unknown_fields)}")

        statements: list[SQLStatement] = []
        for field_name in ("reference", "sample_number", "header"):
            table_name, column_name = targets[field_name]
            statements.extend(
                cls.build_value_update_statements(
                    table_name,
                    column_name,
                    changes_by_field.get(field_name, ()),
                )
            )
        return statements

    @staticmethod
    def build_value_update_statements(
        table_name: str,
        column_name: str,
        changes: Iterable[ValueChange],
    ) -> list[SQLStatement]:
        quoted_table = quote_identifier(table_name)
        quoted_column = quote_identifier(column_name)
        query = f"UPDATE {quoted_table} SET {quoted_column} = ? WHERE {quoted_column} = ?"
        return [(query, (str(new_value), str(old_value))) for new_value, old_value in changes]

    @classmethod
    def build_legacy_record_update_statements(
        cls,
        report_updates: Iterable[RecordUpdate],
        measurement_updates: Iterable[RecordUpdate],
    ) -> list[SQLStatement]:
        statements = cls._build_legacy_update_statements(
            "REPORTS",
            "ID",
            LEGACY_REPORT_FIELD_COLUMNS,
            report_updates,
        )
        statements.extend(
            cls._build_legacy_update_statements(
                "MEASUREMENTS",
                "ID",
                LEGACY_MEASUREMENT_FIELD_COLUMNS,
                measurement_updates,
            )
        )
        return statements

    @staticmethod
    def _build_legacy_update_statements(
        table_name: str,
        key_column: str,
        field_columns: Mapping[str, str],
        updates: Iterable[RecordUpdate],
    ) -> list[SQLStatement]:
        quoted_table = quote_identifier(table_name)
        quoted_key = quote_identifier(key_column)
        statements: list[SQLStatement] = []
        for record_id, fields in updates:
            assignments: list[str] = []
            params: list[Any] = []
            for field_name, value in fields.items():
                column_name = field_columns.get(field_name)
                if column_name is None:
                    continue
                assignments.append(f"{quote_identifier(column_name)} = ?")
                params.append(value)
            if not assignments:
                continue
            params.append(int(record_id))
            statements.append(
                (
                    f"UPDATE {quoted_table} SET {', '.join(assignments)} "
                    f"WHERE {quoted_key} = ?",
                    tuple(params),
                )
            )
        return statements

    @staticmethod
    def apply_update_statements(cursor, statements: Iterable[SQLStatement]) -> None:
        for query, params in statements:
            cursor.execute(query, params)

    @staticmethod
    def validate_record_update_methods(
        repository: object,
        report_updates: Iterable[RecordUpdate],
        measurement_updates: Iterable[RecordUpdate],
    ) -> None:
        missing_methods: list[str] = []
        if tuple(report_updates) and not hasattr(repository, "update_report_metadata_fields"):
            missing_methods.append("update_report_metadata_fields")
        if tuple(measurement_updates) and not hasattr(repository, "update_measurement_fields"):
            missing_methods.append("update_measurement_fields")
        if missing_methods:
            raise RuntimeError(
                "ReportRepository does not provide required targeted update API(s): "
                + ", ".join(missing_methods)
            )

    @classmethod
    def apply_record_updates(
        cls,
        repository: object,
        report_updates: Iterable[RecordUpdate],
        measurement_updates: Iterable[RecordUpdate],
    ) -> None:
        normalized_report_updates = tuple(report_updates)
        normalized_measurement_updates = tuple(measurement_updates)
        cls.validate_record_update_methods(
            repository,
            normalized_report_updates,
            normalized_measurement_updates,
        )
        for report_id, fields in normalized_report_updates:
            repository.update_report_metadata_fields(report_id, fields)
        for measurement_id, fields in normalized_measurement_updates:
            repository.update_measurement_fields(measurement_id, fields)


__all__ = [
    "LEGACY_MEASUREMENT_FIELD_COLUMNS",
    "LEGACY_REPORT_FIELD_COLUMNS",
    "NORMALIZATION_TARGETS",
    "RecordUpdate",
    "ReportEditService",
    "SQLStatement",
    "ValueChange",
]
