import zipfile

import pandas as pd

from metroliza.industrial.industrial_analytics_state import ProductionMetricSelection
from metroliza.industrial.industrial_analytics_workbook import (
    export_production_analytics_workbook,
)


def test_production_analytics_workbook_writes_untrusted_strings_literally(tmp_path):
    output_file = tmp_path / "analytics-hostile.xlsx"
    dataframe = pd.DataFrame(
        (
            {
                "reference": "=2+2",
                "station": "https://example.invalid/station",
                "cycle_time": 10.0,
            },
        )
    )

    export_production_analytics_workbook(
        dataframe=dataframe,
        metric_selection=(ProductionMetricSelection("cycle_time"),),
        output_file=output_file,
        separate_parameter_sheets=True,
    )

    with zipfile.ZipFile(output_file) as workbook_zip:
        worksheet_xml = b"".join(
            workbook_zip.read(name)
            for name in workbook_zip.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        shared_strings = workbook_zip.read("xl/sharedStrings.xml").decode("utf-8")
    assert b"<f" not in worksheet_xml
    assert b"<hyperlink" not in worksheet_xml
    assert "=2+2" in shared_strings
    assert "https://example.invalid/station" in shared_strings
