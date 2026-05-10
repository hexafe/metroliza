import pandas as pd

from modules.export_data_thread import ExportDataThread


def test_export_industrial_context_writes_context_and_diagnostics_sheets():
    captured = []
    thread = ExportDataThread.__new__(ExportDataThread)
    thread.write_data_to_excel = lambda df, table_name, _writer: captured.append((table_name, df.copy()))

    export_df = pd.DataFrame(
        [
            {
                "REPORT_ID": 1,
                "REFERENCE": "REF-1",
                "DATE": "2026-05-10",
                "PART_NAME": "Housing",
                "REVISION": "A",
                "SAMPLE_NUMBER": "1",
                "INDUSTRIAL_RECORD_ID": 10,
                "INDUSTRIAL_SOURCE_PROFILE": "Assembly",
                "INDUSTRIAL_STATION": "S1",
                "INDUSTRIAL_LINK_CONFIDENCE": 1.0,
            },
            {
                "REPORT_ID": 2,
                "REFERENCE": "REF-2",
                "DATE": "2026-05-10",
                "PART_NAME": "Housing",
                "REVISION": "A",
                "SAMPLE_NUMBER": "2",
                "INDUSTRIAL_RECORD_ID": None,
                "INDUSTRIAL_SOURCE_PROFILE": None,
                "INDUSTRIAL_STATION": None,
                "INDUSTRIAL_LINK_CONFIDENCE": None,
            },
        ]
    )

    thread.export_industrial_context_data(export_df, object())

    sheet_names = [name for name, _df in captured]
    assert sheet_names == ["INDUSTRIAL_CONTEXT", "INDUSTRIAL_DIAGNOSTICS"]
    context_df = captured[0][1]
    diagnostics_df = captured[1][1]
    assert list(context_df["INDUSTRIAL_STATION"]) == ["S1"]
    assert diagnostics_df.set_index("metric").loc["linked_reports", "value"] == 1
    assert diagnostics_df.set_index("metric").loc["unmatched_reports", "value"] == 1


def test_export_industrial_context_writes_diagnostics_for_empty_export():
    captured = []
    thread = ExportDataThread.__new__(ExportDataThread)
    thread.write_data_to_excel = lambda df, table_name, _writer: captured.append((table_name, df.copy()))

    thread.export_industrial_context_data(pd.DataFrame(), object())

    assert [name for name, _df in captured] == ["INDUSTRIAL_DIAGNOSTICS"]
    assert captured[0][1].set_index("metric").loc["export_rows", "value"] == 0
