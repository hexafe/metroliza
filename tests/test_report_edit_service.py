from contextlib import closing
import json
import sqlite3

import pytest

from metroliza.reports import report_edit_service
from metroliza.reports.db import sqlite_file_identity
from metroliza.reports.report_edit_service import (
    ReportEditConflictError,
    ReportEditExpectations,
    ReportEditService,
)


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


@pytest.mark.parametrize("external_change", [
    None,
    "UPDATE REPORTS SET SAMPLE_NUMBER = 'external' WHERE ID = 1",
    "INSERT INTO REPORTS VALUES (3, 'A', 'new')",
    "DELETE FROM MEASUREMENTS WHERE ID = 10",
    "UPDATE MEASUREMENTS SET REPORT_ID = 2 WHERE ID = 10",
])
def test_confirmed_batch_rejects_changes_to_loaded_values_or_scope(tmp_path, external_change):
    database = tmp_path / "legacy-review.db"
    _create_database(database, (
        "CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT, SAMPLE_NUMBER TEXT)",
        "CREATE TABLE MEASUREMENTS (ID INTEGER PRIMARY KEY, REPORT_ID INTEGER, OUTTOL REAL)",
        "INSERT INTO REPORTS VALUES (1, 'A', NULL), (2, 'A', 'old')",
        "INSERT INTO MEASUREMENTS VALUES (10, 1, 1.5)",
    ))
    service = ReportEditService(str(database))
    snapshot = ReportEditExpectations(
        report_values=((1, {"sample_number": None}),),
        measurement_values=((10, {"outtol": 1.5}),),
        measurement_owners=((10, 1),),
        normalization_counts={"reference": {"A": 2}},
        database_identity=sqlite_file_identity(database),
    )
    edits = dict(storage_flavor="legacy", normalization_changes={"reference": (("B", "A"),)},
                 report_updates=((1, {"sample_number": "edited"}),),
                 measurement_updates=((10, {"outtol": 2.5}),), expected_edits=snapshot)
    if external_change is None:
        receipt = service.apply_changes_with_receipt(**edits)
        assert receipt.normalization_samples[0].matched_rows == 2
        assert _rows(database, "SELECT REFERENCE, SAMPLE_NUMBER FROM REPORTS ORDER BY ID") == [
            ("B", "edited"), ("B", "old"),
        ]
        assert _rows(database, "SELECT OUTTOL FROM MEASUREMENTS") == [(2.5,)]
        [(version, recorded_at, payload)] = _rows(database, """
            SELECT schema_version, recorded_at_utc, payload_json FROM metroliza_report_edit_receipts
        """)
        assert version == 1 and recorded_at.endswith("Z")
        assert _rows(database, "PRAGMA user_version") == [(0,)]
        assert json.loads(payload)["record_samples"] == [
            dict(entity="report", record_id=1, field_name="sample_number", before=None, after="edited"),
            dict(entity="measurement", record_id=10, field_name="outtol", before=1.5, after=2.5),
        ]
        return

    _create_database(database, (external_change,))
    reports_before = _rows(database, "SELECT * FROM REPORTS ORDER BY ID")
    measurements_before = _rows(database, "SELECT * FROM MEASUREMENTS ORDER BY ID")
    with pytest.raises(ReportEditConflictError, match="Reopen the editor"):
        service.apply_changes_with_receipt(**edits)
    assert _rows(database, "SELECT * FROM REPORTS ORDER BY ID") == reports_before
    assert _rows(database, "SELECT * FROM MEASUREMENTS ORDER BY ID") == measurements_before
    assert _rows(database, "PRAGMA table_info(metroliza_report_edit_receipts)") == []


def test_edit_rejects_replacement_even_when_same_values_and_ids_exist(tmp_path):
    database = tmp_path / "reviewed.db"
    schema = ("CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)",
              "INSERT INTO REPORTS VALUES (1, 'A')")
    _create_database(database, schema)
    original = sqlite_file_identity(database)
    replacement = tmp_path / "replacement.db"
    _create_database(replacement, schema)
    database.rename(tmp_path / "original.db")
    replacement.rename(database)

    with pytest.raises(ReportEditConflictError, match="database changed"):
        ReportEditService(str(database)).apply_changes(
            storage_flavor="legacy", normalization_changes={}, report_updates=((1, {"reference": "B"}),),
            expected_edits=ReportEditExpectations(report_values=((1, {"reference": "A"}),),
                                                 database_identity=original),
        )
    assert _rows(database, "SELECT REFERENCE FROM REPORTS") == [("A",)]


def test_current_edit_rejects_a_report_rebound_to_another_source(tmp_path):
    database = tmp_path / "rebound-source.db"
    _create_database(database, (
        "CREATE TABLE parsed_reports (id INTEGER PRIMARY KEY, source_file_id INTEGER NOT NULL)",
        "CREATE TABLE report_metadata (report_id INTEGER PRIMARY KEY, reference TEXT)",
        "INSERT INTO parsed_reports VALUES (1, 2)",
        "INSERT INTO report_metadata VALUES (1, 'old')",
    ))
    with pytest.raises(ReportEditConflictError, match="database changed"):
        ReportEditService(str(database)).apply_changes_with_receipt(
            storage_flavor="current", normalization_changes={}, report_updates=((1, {"reference": "new"}),),
            expected_edits=ReportEditExpectations(report_values=((1, {"reference": "old"}),),
                                                 report_sources=((1, 1),)),
        )
    assert _rows(database, "SELECT reference FROM report_metadata") == [("old",)]
    assert _rows(database, "PRAGMA table_info(metroliza_report_edit_receipts)") == []


def test_reviewed_overlapping_normalizations_roll_back_the_expanded_scope(tmp_path):
    database = tmp_path / "overlap.db"
    _create_database(database, (
        "CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)",
        "INSERT INTO REPORTS VALUES (1, 'FIRST'), (2, 'FIRST'), (3, 'SECOND')",
    ))
    with pytest.raises(ReportEditConflictError, match="different number"):
        ReportEditService(str(database)).apply_changes_with_receipt(
            storage_flavor="legacy",
            normalization_changes={"reference": (("SECOND", "FIRST"), ("THIRD", "SECOND"))},
            expected_edits=ReportEditExpectations(normalization_counts={"reference": {"FIRST": 2, "SECOND": 1}}),
        )
    assert _rows(database, "SELECT REFERENCE FROM REPORTS ORDER BY ID") == [("FIRST",), ("FIRST",), ("SECOND",)]
    assert _rows(database, "PRAGMA table_info(metroliza_report_edit_receipts)") == []


@pytest.mark.parametrize(("normalization", "record_updates", "message"), [
    ({"reference": (("new", "old"),)}, (), "different number"),
    ({}, ((1, {"reference": "new"}),), "does not exist in the reviewed edits"),
    ({}, ((2, {"reference": "new"}),), "^Report 2 does not exist$"),
])
def test_confirmed_edits_require_a_captured_scope_and_original_values(tmp_path, normalization, record_updates, message):
    database = tmp_path / "partial-preview.db"
    _create_database(database, (
        "CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)",
        "INSERT INTO REPORTS VALUES (1, 'old')",
    ))
    with pytest.raises(ReportEditConflictError, match=message):
        ReportEditService(str(database)).apply_changes_with_receipt(
            storage_flavor="legacy", normalization_changes=normalization, report_updates=record_updates,
            expected_edits=ReportEditExpectations(),
        )
    assert _rows(database, "SELECT REFERENCE FROM REPORTS") == [("old",)]
    assert _rows(database, "PRAGMA table_info(metroliza_report_edit_receipts)") == []


def test_local_edit_receipt_failure_rolls_back_both_schema_and_values(tmp_path, monkeypatch):
    database = tmp_path / "receipt-failure.db"
    _create_database(database, (
        "CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)",
        "INSERT INTO REPORTS VALUES (1, 'old')",
    ))
    persist = report_edit_service.persist_confirmed_receipt

    def fail_after_insert(cursor, receipt):
        persist(cursor, receipt)
        raise sqlite3.DatabaseError("fault after the audit insert")

    monkeypatch.setattr(report_edit_service, "persist_confirmed_receipt", fail_after_insert)
    with pytest.raises(sqlite3.DatabaseError, match="after the audit insert"):
        ReportEditService(str(database)).apply_changes_with_receipt(
            storage_flavor="legacy", normalization_changes={}, report_updates=((1, {"reference": "new"}),),
            expected_edits=ReportEditExpectations(report_values=((1, {"reference": "old"}),)),
        )
    assert _rows(database, "SELECT REFERENCE FROM REPORTS") == [("old",)]
    assert _rows(database, "PRAGMA table_info(metroliza_report_edit_receipts)") == []


def test_incompatible_local_receipt_table_blocks_edit_without_overwriting(tmp_path):
    database = tmp_path / "receipt-collision.db"
    _create_database(database, (
        "CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)",
        "INSERT INTO REPORTS VALUES (1, 'old')",
        "CREATE TABLE metroliza_report_edit_receipts (original TEXT)",
        "INSERT INTO metroliza_report_edit_receipts VALUES ('foreign table data')",
    ))
    with pytest.raises(sqlite3.DatabaseError, match="incompatible layout"):
        ReportEditService(str(database)).apply_changes_with_receipt(
            storage_flavor="legacy", normalization_changes={}, report_updates=((1, {"reference": "new"}),),
            expected_edits=ReportEditExpectations(report_values=((1, {"reference": "old"}),)),
        )
    assert _rows(database, "SELECT REFERENCE FROM REPORTS") == [("old",)]
    assert _rows(database, "SELECT original FROM metroliza_report_edit_receipts") == [("foreign table data",)]


def test_local_edit_receipts_keep_latest_batches_and_bound_values(tmp_path):
    database = tmp_path / "receipt-retention.db"
    _create_database(database, (
        "CREATE TABLE REPORTS (ID INTEGER PRIMARY KEY, REFERENCE TEXT)",
        "INSERT INTO REPORTS VALUES (1, 'original')",
    ))
    service = ReportEditService(str(database))
    before = "original"
    for index in range(102):
        after = "ą" * 300 if index == 101 else str(index)
        service.apply_changes_with_receipt(
            storage_flavor="legacy", normalization_changes={}, report_updates=((1, {"reference": after}),),
            expected_edits=ReportEditExpectations(report_values=((1, {"reference": before}),)),
        )
        before = after

    receipts = _rows(database, "SELECT receipt_id, payload_json FROM metroliza_report_edit_receipts ORDER BY receipt_id")
    assert [receipt_id for receipt_id, _ in receipts] == list(range(3, 103))
    sample = json.loads(receipts[-1][1])["record_samples"][0]
    assert sample["before"] == "100" and sample["after"] == {"omitted": "preview_limit"}
    assert _rows(database, "SELECT REFERENCE FROM REPORTS") == [(before,)]


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


def test_current_normalization_rolls_back_on_repository_update_failure(tmp_path):
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

    assert _rows(database, "SELECT reference FROM report_metadata") == [("A",)]
    assert repository.report_updates == [(42, {"comment": "reviewed"})]


def test_custom_current_normalization_keeps_sql_storage_and_skips_adapter_construction(tmp_path):
    database = str(tmp_path / "adapter-normalization.db")
    _create_database(database, (
        "CREATE TABLE report_metadata (reference TEXT PRIMARY KEY)",
        "INSERT INTO report_metadata (reference) VALUES ('A')",
    ))

    def unused_adapter(_database):
        pytest.fail("Normalization-only edits should not create the custom records adapter")

    service = ReportEditService(database, repository_factory=unused_adapter)
    assert service.apply_changes_with_receipt(
        storage_flavor="current", normalization_changes={"reference": (("B", "A"),)},
    ) is None
    assert _rows(database, "SELECT reference FROM report_metadata") == [("B",)]


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


def test_literal_custom_dispatch_and_error_order(tmp_path):
    events = []

    class Repository:
        def update_report_metadata_fields(self, record_id, fields):
            events.append(('report', record_id, dict(fields)))

        def update_measurement_fields(self, record_id, fields):
            events.append(('measurement', record_id, dict(fields)))
            raise TypeError('literal custom failure')

    def factory(database):
        events.append(('factory', database))
        return Repository()

    service = ReportEditService('literal.db', repository_factory=factory)
    with pytest.raises(TypeError, match='literal custom failure'):
        service.apply_changes(
            storage_flavor='current', normalization_changes={},
            report_updates=((42, {'comment': 'reviewed'}), (43, {})),
            measurement_updates=((7, {'header': 'WIDTH'}), (8, {'header': 'never'})),
        )
    assert events == [
        ('factory', 'literal.db'), ('report', 42, {'comment': 'reviewed'}),
        ('report', 43, {}), ('measurement', 7, {'header': 'WIDTH'}),
    ]


def test_literal_noop_and_normalization_failure_do_not_dispatch(tmp_path):
    events = []
    database = str(tmp_path / 'missing.db')
    service = ReportEditService(database, repository_factory=lambda path: events.append(path))
    service.apply_changes(storage_flavor='current', normalization_changes={})
    assert events == []
    assert not (tmp_path / 'missing.db').exists()
    with pytest.raises(ValueError, match='normalization fields'):
        service.apply_changes(storage_flavor='current', normalization_changes={'invalid': ()},
                              report_updates=((1, {'comment': 'never'}),))
    assert events == []


def test_literal_service_subclass_keeps_virtual_hooks(tmp_path):
    events = []

    class Service(ReportEditService):
        def build_normalization_update_statements(self, flavor, changes):
            events.append(('normalize', flavor, changes))
            return []

        def validate_record_update_methods(self, repository, reports, measurements):
            events.append(('validate', reports, measurements))

        def apply_record_updates(self, repository, reports, measurements):
            events.append(('apply', reports, measurements))

    service = Service('unused.db', repository_factory=lambda path: object())
    service.apply_changes(storage_flavor='current', normalization_changes={},
                          report_updates=((1, {'comment': 'value'}),))
    assert events == [('normalize', 'current', {}),
                      ('validate', ((1, {'comment': 'value'}),), ()),
                      ('apply', ((1, {'comment': 'value'}),), ())]
