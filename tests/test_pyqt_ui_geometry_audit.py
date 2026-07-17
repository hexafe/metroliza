from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")

try:
    from PyQt6.QtWidgets import QApplication

    from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
    from metroliza.reports.report_schema import ensure_report_schema
    from metroliza.tabular.tabular_analytics_service import (
        cleanup_tabular_load_result,
        load_tabular_analytics_file,
    )
    from metroliza.ui.characteristic_mapping_dialog import CharacteristicMappingDialog
    from metroliza.ui.dashboard_visual_options_dialog import DashboardVisualOptionsDialog
    from metroliza.ui.industrial_analytics_dialog import (
        SOURCE_TABULAR_FILE,
        IndustrialAnalyticsDialog,
    )
    from metroliza.ui.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
    from metroliza.ui.industrial_sync_dialog import IndustrialSqlQueryDialog, IndustrialSyncDialog
    from metroliza.ui.tabular_analytics_filter_dialog import TabularAnalyticsFilterDialog
except Exception as exc:  # pragma: no cover - depends on local Qt/runtime availability.
    QApplication = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None

from metroliza.reports.characteristic_alias_service import (
    ensure_characteristic_alias_schema,
    upsert_characteristic_alias,
)

from tests.ui_geometry_audit import assert_dialog_geometry_clean


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 UI geometry audit is unavailable: {PYQT_IMPORT_ERROR}",
)

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


@pytest.fixture(autouse=True)
def _ensure_qapplication():
    _app()


def _long_label(prefix: str) -> str:
    return f"{prefix} " + " / ".join(f"very_long_layout_segment_{index:02d}" for index in range(8))


def _audit_and_close(dialog) -> None:
    app = _app()
    try:
        assert_dialog_geometry_clean(dialog, app)
    finally:
        # Geometry probes intentionally mutate fields without committing them.
        # Hide before teardown so transactional editors restore drafts without
        # opening an operator confirmation modal in the headless test process.
        dialog.hide()
        app.processEvents()
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_source_profile_editor_geometry_handles_long_paths_and_labels(tmp_path) -> None:
    dialog = IndustrialSourceProfilesDialog(
        db_file=str(tmp_path / "industrial-cache.sqlite"),
        config_path=tmp_path / "nested" / "deep" / "source_profiles_with_long_name.yaml",
    )
    dialog.source_name_edit.setText(_long_label("Assembly source"))
    dialog.alias_edit.setText("assembly_source_with_long_layout_identifier")
    dialog.host_edit.setText("production-database-host-with-long-name.example.invalid")
    dialog.database_edit.setText("metrology_production_database_with_long_identifier")
    dialog.table_edit.setText("schema.production_events_with_long_identifier")
    dialog.columns_edit.setText(
        ", ".join(
            [
                "event_id",
                "part_number",
                "revision",
                "serial_number",
                "station_name",
                "operator_badge",
                "process_timestamp",
                "measurement_payload_json",
            ]
        )
    )

    _audit_and_close(dialog)


def test_sync_dialog_and_sql_editor_geometry_handle_dense_profiles(tmp_path) -> None:
    db_path = tmp_path / "industrial.sqlite"
    ensure_report_schema(str(db_path))
    repository = IndustrialDataRepository(str(db_path))
    repository.upsert_source_profile(
        profile_key="assembly_mes_with_many_columns",
        profile_name=_long_label("Assembly MES"),
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="schema.production_events_with_very_long_table_name",
        host="production-database-host-with-long-name.example.invalid",
        port=1433,
        database_name="metrology_production_database_with_long_identifier",
        allowed_columns=(
            "event_id",
            "part_number",
            "revision",
            "serial_number",
            "station_name",
            "operator_badge",
            "process_timestamp",
            "measurement_payload_json",
        ),
        default_pagination_column="event_id",
    )

    dialog = IndustrialSyncDialog(db_file=str(db_path), config_path=tmp_path / "missing.yaml")
    dialog.sql_query_edit.setPlainText(
        "SELECT event_id, part_number, revision, serial_number, station_name, "
        "measurement_payload_json FROM schema.production_events_with_very_long_table_name "
        "WHERE process_timestamp >= :start_time ORDER BY event_id"
    )
    _audit_and_close(dialog)

    parent_dialog = IndustrialSyncDialog(db_file=str(db_path), config_path=tmp_path / "missing.yaml")
    sql_dialog = IndustrialSqlQueryDialog(parent_dialog)
    sql_dialog._geometry_parent = parent_dialog
    sql_dialog.query_edit.setPlainText(parent_dialog.sql_query_edit.toPlainText())
    _audit_and_close(sql_dialog)
    parent_dialog.close()
    parent_dialog.deleteLater()


def test_tabular_analytics_dialog_geometry_handles_long_artifact_paths(tmp_path) -> None:
    dialog = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE)
    dialog.input_file = str(tmp_path / "source files" / "incoming_measurements_with_long_name.csv")
    dialog.output_dashboard_file = str(
        tmp_path / "dashboards" / "analytics_dashboard_with_long_layout_name.html"
    )
    dialog.output_workbook_file = str(
        tmp_path / "workbooks" / "analytics_workbook_with_long_layout_name.xlsx"
    )
    dialog.references_edit.setPlainText("REF-100, REF-200, REF-300, REF-400")
    dialog.readiness_label.setText(_long_label("Ready to analyze selected production metrics"))

    _audit_and_close(dialog)


def test_dashboard_visual_options_geometry_handles_long_preview_names(monkeypatch) -> None:
    import metroliza.ui.dashboard_visual_options_dialog as dialog_module

    monkeypatch.setattr(
        dialog_module,
        "build_dashboard_visual_preview_spec",
        lambda settings, *, chart_type, **_kwargs: {"data": [], "layout": {}, "config": {}},
    )
    monkeypatch.setattr(dialog_module, "build_dashboard_visual_preview_html", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        dialog_module,
        "build_dashboard_visual_preview_png",
        lambda *_args, **_kwargs: None,
    )
    dialog = DashboardVisualOptionsDialog(
        preview_group_names=(
            "Cavity A with extended production group label",
            "Fixture B with extended production group label",
            "Station C with extended production group label",
        ),
        persist_on_accept=False,
    )
    dialog._preview_timer.stop()

    _audit_and_close(dialog)


def test_tabular_filter_dialog_geometry_handles_multi_column_filters(tmp_path) -> None:
    input_file = tmp_path / "tabular_filter_layout_source.csv"
    pd.DataFrame(
        {
            "Time Stamp": pd.date_range("2026-05-10 08:00", periods=8, freq="h"),
            "Reference ID": [f"REF-{index:03d}" for index in range(8)],
            "TraceCode": [f"TRACE-CODE-WITH-LONG-LAYOUT-VALUE-{index:03d}" for index in range(8)],
            "Line": ["Assembly Line Alpha With Long Name", "Paint Line Beta With Long Name"] * 4,
            "Length mm": [10.0 + index / 10 for index in range(8)],
        }
    ).to_csv(input_file, index=False)
    loaded = load_tabular_analytics_file(input_file, force_sqlite=True)
    dialog = TabularAnalyticsFilterDialog(
        dataframe=loaded.dataframe,
        column_mapping=loaded.column_mapping,
        sqlite_store=loaded.sqlite_store,
    )
    dialog._loaded_table = loaded

    try:
        _audit_and_close(dialog)
    finally:
        cleanup_tabular_load_result(loaded)


def test_characteristic_mapping_dialog_geometry_handles_long_metric_aliases(tmp_path) -> None:
    db_path = Path(tmp_path) / "aliases.sqlite"
    ensure_characteristic_alias_schema(str(db_path))
    upsert_characteristic_alias(
        str(db_path),
        alias_name="DIAMETER_X_WITH_LONG_MACHINE_EXPORT_NAME",
        canonical_name="DIAMETER X COMMON CHARACTERISTIC WITH LONG NAME",
        scope_type="reference",
        scope_value="REF-100-WITH-LONG-SUFFIX",
    )

    dialog = CharacteristicMappingDialog(parent=None, db_file=str(db_path))
    _audit_and_close(dialog)
