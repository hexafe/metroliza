from __future__ import annotations

import zipfile

import pandas as pd

from modules.industrial_data_repository import IndustrialDataRepository
from modules.industrial_export_service import (
    build_industrial_summary,
    export_cached_industrial_workbook,
    load_cached_industrial_dataframe,
)
from modules.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState


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
                "station": "S1",
                "process_status": "OK",
                "raw_record": {"event_id": "ROW-1"},
            },
            {
                "source_record_key": "ROW-2",
                "reference": "REF-1",
                "station": "S2",
                "process_status": "NOK",
                "raw_record": {"event_id": "ROW-2"},
            },
            {
                "source_record_key": "ROW-3",
                "reference": "REF-2",
                "station": "S1",
                "process_status": "OK",
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
    assert len(dataframe.index) == 2
    assert set(summary["group"]) == {"S1 | OK", "S2 | NOK"}
    assert list(summary["record_count"]) == [1, 1]


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
    workbook = pd.ExcelFile(output_file)
    assert set(workbook.sheet_names) == {
        "Industrial Data",
        "Industrial Summary",
        "Diagnostics",
        "Industrial Charts",
    }
    with zipfile.ZipFile(output_file) as workbook_zip:
        chart_files = [name for name in workbook_zip.namelist() if name.startswith("xl/charts/")]
    assert chart_files
