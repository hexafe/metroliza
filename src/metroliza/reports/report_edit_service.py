"""Transactional write boundary for report metadata editing workflows."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from metroliza.reports.db import quote_identifier, run_transaction_with_retry
from metroliza.reports.report_repository import ReportRepository


SQLStatement = tuple[str, tuple[Any, ...]]
ValueChange = tuple[str, str]
RecordUpdate = tuple[int, dict[str, Any]]

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
    ) -> None:
        """Apply edits with the existing normalization/repository transaction boundary."""

        normalized_flavor = self._validate_storage_flavor(storage_flavor)
        normalized_report_updates = self._normalize_record_updates(report_updates)
        normalized_measurement_updates = self._normalize_record_updates(measurement_updates)
        statements = self.build_normalization_update_statements(
            normalized_flavor,
            normalization_changes,
        )

        repository = None
        if normalized_flavor == "legacy":
            statements.extend(
                self.build_legacy_record_update_statements(
                    normalized_report_updates,
                    normalized_measurement_updates,
                )
            )
        elif normalized_report_updates or normalized_measurement_updates:
            repository = self._repository_factory(self.database)
            self.validate_record_update_methods(
                repository,
                normalized_report_updates,
                normalized_measurement_updates,
            )

        if statements:
            run_transaction_with_retry(
                self.database,
                lambda cursor: self.apply_update_statements(cursor, statements),
            )

        if repository is not None:
            self.apply_record_updates(
                repository,
                normalized_report_updates,
                normalized_measurement_updates,
            )

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
