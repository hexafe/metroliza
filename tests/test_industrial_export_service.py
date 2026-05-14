from __future__ import annotations

import zipfile

import pandas as pd
import pytest

from modules.industrial_data_repository import IndustrialDataRepository
import modules.industrial_export_service as industrial_export_service
from modules.industrial_export_service import (
    IndustrialExportCancelled,
    build_industrial_summary,
    export_cached_industrial_workbook,
    export_live_industrial_workbook,
    industrial_records_to_export_dataframe,
    load_cached_industrial_dataframe,
)
from modules.industrial_source_config import build_source_profile
from modules.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState
from modules.oznak_adapter import OznakAdapterFetchResult, OznakAdapterStatus


def _seed_cached_industrial_rows(db_path: str):
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        allowed_columns=("event_id", "reference", "station", "process_status"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=[
            {
                "source_record_key": "ROW-1",
                "reference": "REF-1",
                "serial": "SN-1",
                "station": "S1",
                "process_status": "OK",
                "fixture_code": "FX-1",
                "raw_record": {"event_id": "ROW-1"},
            },
            {
                "source_record_key": "ROW-2",
                "reference": "REF-1",
                "serial": "SN-2",
                "station": "S2",
                "process_status": "NOK",
                "fixture_code": "FX-2",
                "raw_record": {"event_id": "ROW-2"},
            },
            {
                "source_record_key": "ROW-3",
                "reference": "REF-2",
                "serial": "SN-3",
                "station": "S1",
                "process_status": "OK",
                "fixture_code": "FX-1",
                "raw_record": {"event_id": "ROW-3"},
            },
        ],
    )


def test_cached_industrial_export_respects_reference_filter_and_grouping(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    _seed_cached_industrial_rows(db_path)

    dataframe = load_cached_industrial_dataframe(
        db_path,
        filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1",)),
    )
    summary = build_industrial_summary(
        dataframe,
        grouping_state=IndustrialGroupingState(fields=("station", "process_status")),
    )

    assert set(dataframe["reference"]) == {"REF-1"}
    assert "raw_record_json" not in dataframe.columns
    assert len(dataframe.index) == 2
    assert set(summary["group"]) == {"S1 | OK", "S2 | NOK"}
    assert list(summary["record_count"]) == [1, 1]


def test_cached_industrial_export_filters_by_non_reference_record_column(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    _seed_cached_industrial_rows(db_path)

    dataframe = load_cached_industrial_dataframe(
        db_path,
        filter_state=IndustrialFilterState(reference_column="serial", references=("SN-2",)),
    )

    assert list(dataframe["source_record_key"]) == ["ROW-2"]
    assert list(dataframe["reference"]) == ["REF-1"]


def test_cached_industrial_export_filters_by_cached_dynamic_column(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    _seed_cached_industrial_rows(db_path)

    dataframe = load_cached_industrial_dataframe(
        db_path,
        filter_state=IndustrialFilterState(reference_column="fixture_code", references=("FX-1",)),
    )

    assert set(dataframe["source_record_key"]) == {"ROW-1", "ROW-3"}


def test_cached_industrial_export_writes_workbook_with_charts(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    _seed_cached_industrial_rows(db_path)
    output_file = tmp_path / "industrial_export.xlsx"

    result = export_cached_industrial_workbook(
        db_file=db_path,
        output_file=str(output_file),
        filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1", "REF-2")),
        grouping_state=IndustrialGroupingState(fields=("station",)),
        include_charts=True,
    )

    assert result["row_count"] == 3
    assert result["summary_rows"] == 2
    assert output_file.exists()
    with pd.ExcelFile(output_file) as workbook:
        assert set(workbook.sheet_names) == {
            "Industrial Data",
            "Industrial Summary",
            "Diagnostics",
            "Industrial Charts",
        }
    industrial_data = pd.read_excel(output_file, sheet_name="Industrial Data")
    assert "raw_record_json" not in industrial_data.columns
    with zipfile.ZipFile(output_file) as workbook_zip:
        chart_files = [name for name in workbook_zip.namelist() if name.startswith("xl/charts/")]
    assert chart_files


def test_cached_industrial_export_cancel_removes_temp_workbook(tmp_path):
    db_path = str(tmp_path / "industrial.db")
    _seed_cached_industrial_rows(db_path)
    output_file = tmp_path / "industrial_export.xlsx"
    checks = 0

    def cancel_after_writer_starts() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with pytest.raises(IndustrialExportCancelled, match="cancelled"):
        export_cached_industrial_workbook(
            db_file=db_path,
            output_file=str(output_file),
            filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1",)),
            grouping_state=IndustrialGroupingState(fields=("station",)),
            include_charts=True,
            cancel_check=cancel_after_writer_starts,
        )

    assert not output_file.exists()
    assert not (tmp_path / ".industrial_export.tmp.xlsx").exists()


def test_live_export_dataframe_preserves_raw_columns_without_reference_requirement():
    profile = build_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "station"),
        default_pagination_column="event_id",
    )

    dataframe = industrial_records_to_export_dataframe(
        (
            {
                "source_primary_key": "ROW-1",
                "station": "S1",
                "raw_record": {"event_id": "ROW-1", "station": "S1", "measurement": 12.5},
            },
        ),
        profile=profile,
    )

    assert dataframe["source_db_alias"].tolist() == ["assembly_mes"]
    assert dataframe["source_record_key"].tolist() == ["ROW-1"]
    assert "reference" in dataframe.columns
    assert dataframe["reference"].isna().all()
    assert dataframe["event_id"].tolist() == ["ROW-1"]
    assert dataframe["measurement"].tolist() == [12.5]


def test_live_industrial_export_fetches_and_writes_workbook_without_cache(monkeypatch, tmp_path):
    profile = build_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "station"),
        default_pagination_column="event_id",
    )
    output_file = tmp_path / "industrial_live.xlsx"
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=(
            {
                "source_primary_key": "ROW-1",
                "station": "S1",
                "raw_record": {"event_id": "ROW-1", "station": "S1"},
            },
        ),
        row_count=1,
        implemented=True,
        diagnostics={"stage": "mapped"},
    )
    fetch_kwargs = {}

    def fake_fetch(*args, **kwargs):
        fetch_kwargs.update(kwargs)
        return result

    monkeypatch.setattr(industrial_export_service, "fetch_oznak_records_for_source_profile", fake_fetch)

    export_result = export_live_industrial_workbook(
        profile=profile,
        username="operator",
        password="secret-password",
        output_file=str(output_file),
        limit=50,
        timeout_seconds=30,
        filter_state=IndustrialFilterState(),
        grouping_state=IndustrialGroupingState(fields=("station",)),
        include_charts=False,
    )

    assert export_result["status"] == "succeeded"
    assert export_result["row_count"] == 1
    assert fetch_kwargs["limit"] == 50
    assert fetch_kwargs["reference_filter_column"] is None
    assert output_file.exists()
    exported = pd.read_excel(output_file, sheet_name="Industrial Data")
    assert exported["event_id"].tolist() == ["ROW-1"]
    assert exported["station"].tolist() == ["S1"]
