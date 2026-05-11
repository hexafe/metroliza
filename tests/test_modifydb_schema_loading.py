import json
import os
import sqlite3
import subprocess
import sys
import textwrap

import pytest


def _create_legacy_database(db_path):
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE REPORTS (
                ID INTEGER PRIMARY KEY,
                REFERENCE TEXT,
                FILELOC TEXT,
                FILENAME TEXT,
                DATE TEXT,
                SAMPLE_NUMBER TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE MEASUREMENTS (
                ID INTEGER PRIMARY KEY,
                REPORT_ID INTEGER,
                AX TEXT,
                NOM REAL,
                "+TOL" REAL,
                "-TOL" REAL,
                BONUS REAL,
                MEAS REAL,
                DEV REAL,
                OUTTOL REAL,
                HEADER TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO REPORTS(ID, REFERENCE, FILELOC, FILENAME, DATE, SAMPLE_NUMBER)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "REF-A", "/reports", "a.pdf", "2024-01-01", "001"),
                (2, "REF-B", "/reports", "b.pdf", "2024-01-02", "002"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO MEASUREMENTS(ID, REPORT_ID, AX, NOM, "+TOL", "-TOL", BONUS, MEAS, DEV, OUTTOL, HEADER)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (10, 1, "X", 10.0, 0.1, -0.1, 0.0, 10.05, 0.05, 0.0, "WIDTH"),
                (11, 2, "Y", 20.0, 0.2, -0.2, 0.0, 20.05, 0.05, 0.0, "HEIGHT"),
            ],
        )
        connection.commit()


def _run_probe(script):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_STYLE_OVERRIDE"] = "Fusion"
    try:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=os.fspath(os.path.dirname(os.path.dirname(__file__))),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        headless_runtime_markers = (
            "libGL.so.1",
            "libEGL.so.1",
            "Could not load the Qt platform plugin",
            "no Qt platform plugin could be initialized",
            "qt.qpa.plugin",
        )
        if any(marker in stderr for marker in headless_runtime_markers):
            pytest.skip(f"PyQt runtime dependency missing in test environment: {stderr}")
        raise AssertionError(
            "ModifyDB schema probe subprocess failed unexpectedly.\n"
            f"Return code: {exc.returncode}\n"
            f"STDOUT:\n{(exc.stdout or '').strip()}\n"
            f"STDERR:\n{stderr}"
        ) from exc
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_modifydb_loads_legacy_database_without_report_metadata(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_database(db_path)

    payload = _run_probe(
        f"""
        import json
        from PyQt6.QtWidgets import QApplication
        from modules.modify_db import ModifyDB

        app = QApplication.instance() or QApplication([])
        dialog = ModifyDB(parent=None, db_file={json.dumps(str(db_path))})
        try:
            app.processEvents()
            print(json.dumps({{
                "storage_flavor": dialog._storage_flavor,
                "reference_rows": dialog.reference_table.rowCount(),
                "sample_rows": dialog.part_number_table.rowCount(),
                "header_rows": dialog.header_table.rowCount(),
                "report_rows": dialog.report_records_table.rowCount(),
                "measurement_rows": dialog.measurement_records_table.rowCount(),
                "first_reference": dialog.reference_table.item(0, 0).text(),
                "second_header": dialog.header_table.item(1, 0).text(),
            }}, sort_keys=True))
        finally:
            dialog.close()
            app.processEvents()
        """
    )

    assert payload == {
        "storage_flavor": "legacy",
        "reference_rows": 2,
        "sample_rows": 2,
        "header_rows": 2,
        "report_rows": 2,
        "measurement_rows": 2,
        "first_reference": "REF-A",
        "second_header": "WIDTH",
    }


def test_modifydb_applies_normalization_to_legacy_database(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_database(db_path)

    payload = _run_probe(
        f"""
        import json
        import sqlite3
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from modules.modify_db import ModifyDB

        app = QApplication.instance() or QApplication([])
        QMessageBox.information = lambda *args, **kwargs: None
        dialog = ModifyDB(parent=None, db_file={json.dumps(str(db_path))})
        try:
            app.processEvents()
            dialog.reference_table.item(0, 1).setText("REF-A2")
            dialog.header_table.item(0, 1).setText("HEIGHT2")
            dialog.apply_changes()

            with sqlite3.connect({json.dumps(str(db_path))}) as connection:
                references = connection.execute("SELECT REFERENCE FROM REPORTS ORDER BY ID").fetchall()
                headers = connection.execute("SELECT HEADER FROM MEASUREMENTS ORDER BY ID").fetchall()

            print(json.dumps({{
                "references": references,
                "headers": headers,
            }}, sort_keys=True))
        finally:
            dialog.close()
            app.processEvents()
        """
    )

    assert payload["references"] == [["REF-A2"], ["REF-B"]]
    assert payload["headers"] == [["WIDTH"], ["HEIGHT2"]]


def test_modifydb_loads_current_database_after_schema_bootstrap(tmp_path):
    db_path = tmp_path / "current.db"

    payload = _run_probe(
        f"""
        import json
        from PyQt6.QtWidgets import QApplication
        from modules.modify_db import ModifyDB

        app = QApplication.instance() or QApplication([])
        dialog = ModifyDB(parent=None, db_file={json.dumps(str(db_path))})
        try:
            app.processEvents()
            print(json.dumps({{
                "storage_flavor": dialog._storage_flavor,
                "reference_rows": dialog.reference_table.rowCount(),
                "report_columns": dialog.report_records_table.columnCount(),
            }}, sort_keys=True))
        finally:
            dialog.close()
            app.processEvents()
        """
    )

    assert payload == {
        "storage_flavor": "current",
        "reference_rows": 0,
        "report_columns": len(
            [
                "REPORT_ID",
                "REFERENCE",
                "DATE",
                "TIME",
                "PART_NAME",
                "REVISION",
                "SAMPLE_NUMBER",
                "OPERATOR_NAME",
                "COMMENT",
                "FILENAME",
                "TEMPLATE_VARIANT",
            ]
        ),
    }
