from __future__ import annotations

from metroliza.industrial.industrial_data_repository import IndustrialDataRepository
from metroliza.industrial.industrial_tabular_bridge import load_industrial_cache_tabular_result


def test_industrial_cache_bridge_exposes_source_and_dynamic_columns(tmp_path) -> None:
    db_file = tmp_path / "industrial.sqlite"
    repository = IndustrialDataRepository(str(db_file))
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="prod_a",
        database_type="mssql",
        source_object_name="measurements",
        allowed_columns=("reference", "length_mm", "fixture"),
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=(
            {
                "source_record_key": "row-1",
                "process_timestamp": "2026-06-01T10:00:00Z",
                "reference": "REF-1",
                "length_mm": "12.5",
                "fixture": "F1",
            },
            {
                "source_record_key": "row-2",
                "process_timestamp": "2026-06-01T10:01:00Z",
                "reference": "REF-2",
                "length_mm": "12.7",
                "fixture": "F2",
            },
        ),
    )

    loaded = load_industrial_cache_tabular_result(db_file)

    assert loaded.storage_mode == "sqlite"
    assert loaded.row_count == 2
    assert "source" in loaded.dataframe.columns
    assert "length_mm" in loaded.dataframe.columns
    assert loaded.dataframe.loc[0, "source"] == "Line A"
    assert loaded.dataframe.loc[0, "fixture"] == "F1"
    assert any(candidate.field_name == "length_mm" for candidate in loaded.metric_candidates)
    sqlite_frame = loaded.sqlite_store.read_dataframe(columns=("source", "length_mm", "fixture"))
    assert sqlite_frame.to_dict("records")[0] == {
        "source": "Line A",
        "length_mm": "12.5",
        "fixture": "F1",
    }
