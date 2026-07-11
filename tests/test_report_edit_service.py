from contextlib import closing
import sqlite3

import pytest

from metroliza.reports.report_edit_service import ReportEditService


def _create_database(path, statements):
    with closing(sqlite3.connect(path)) as connection, connection:
        for statement in statements:
            connection.execute(statement)


def _rows(path, query):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(query).fetchall()


def test_legacy_edit_batch_rolls_back_every_statement_on_sql_failure(tmp_path):
    database = str(tmp_path / "legacy-edit.db")
    _create_database(
        database,
        (
            "CREATE TABLE REPORTS (REFERENCE TEXT PRIMARY KEY)",
            "INSERT INTO REPORTS (REFERENCE) VALUES ('A')",
        ),
    )
    service = ReportEditService(database)

    with pytest.raises(sqlite3.OperationalError, match="MEASUREMENTS"):
        service.apply_changes(
            storage_flavor="legacy",
            normalization_changes={
                "reference": (("A2", "A"),),
                "header": (("WIDTH2", "WIDTH"),),
            },
        )

    assert _rows(database, "SELECT REFERENCE FROM REPORTS") == [("A",)]


def test_current_repository_validation_fails_before_normalization_commit(tmp_path):
    database = str(tmp_path / "current-validation.db")
    _create_database(
        database,
        (
            "CREATE TABLE report_metadata (reference TEXT PRIMARY KEY)",
            "INSERT INTO report_metadata (reference) VALUES ('A')",
        ),
    )
    service = ReportEditService(database, repository_factory=lambda _database: object())

    with pytest.raises(RuntimeError, match="update_report_metadata_fields"):
        service.apply_changes(
            storage_flavor="current",
            normalization_changes={"reference": (("A2", "A"),)},
            report_updates=((1, {"reference": "A2"}),),
        )

    assert _rows(database, "SELECT reference FROM report_metadata") == [("A",)]


def test_current_normalization_commit_precedes_repository_update_failure(tmp_path):
    database = str(tmp_path / "current-boundary.db")
    _create_database(
        database,
        (
            "CREATE TABLE report_metadata (reference TEXT PRIMARY KEY)",
            "INSERT INTO report_metadata (reference) VALUES ('A')",
        ),
    )

    class _FailingRepository:
        def __init__(self):
            self.report_updates = []

        def update_report_metadata_fields(self, report_id, fields):
            self.report_updates.append((report_id, fields))

        def update_measurement_fields(self, measurement_id, fields):
            raise ValueError(f"Measurement {measurement_id} does not exist")

    repository = _FailingRepository()
    service = ReportEditService(
        database,
        repository_factory=lambda _database: repository,
    )

    with pytest.raises(ValueError, match="Measurement 7 does not exist"):
        service.apply_changes(
            storage_flavor="current",
            normalization_changes={"reference": (("A2", "A"),)},
            report_updates=((42, {"comment": "reviewed"}),),
            measurement_updates=((7, {"header": "WIDTH"}),),
        )

    assert _rows(database, "SELECT reference FROM report_metadata") == [("A2",)]
    assert repository.report_updates == [(42, {"comment": "reviewed"})]


def test_report_edit_service_rejects_unknown_flavor_and_normalization_field(tmp_path):
    service = ReportEditService(str(tmp_path / "invalid.db"))

    with pytest.raises(ValueError, match="storage flavor"):
        service.apply_changes(
            storage_flavor="future",
            normalization_changes={},
        )
    with pytest.raises(ValueError, match="normalization fields"):
        service.apply_changes(
            storage_flavor="current",
            normalization_changes={"unknown": (("new", "old"),)},
        )
