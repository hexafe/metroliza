import tempfile
import unittest
from pathlib import Path

import pandas as pd

from modules.csv_summary_utils import (
    CsvGroupingIndex,
    build_csv_grouping_preview,
    filter_csv_summary_by_group_keys,
    load_csv_with_fallbacks,
    parse_delimiter_with_sniffer,
    resolve_default_data_columns,
)


class CsvSummaryUtilsTests(unittest.TestCase):
    def test_load_csv_with_semicolon_decimal_comma(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "sample.csv"
            csv_path.write_text("PART;LENGTH;WIDTH\nA;10,5;2,0\nB;11,0;2,1\n", encoding="utf-8")

            df, config = load_csv_with_fallbacks(csv_path)

            self.assertEqual(["PART", "LENGTH", "WIDTH"], list(df.columns))
            self.assertEqual(";", config["delimiter"])
            self.assertEqual(",", config["decimal"])

    def test_resolve_default_data_columns_prefers_numeric(self):
        df = pd.DataFrame(
            {
                "SERIAL": ["A", "B", "C"],
                "MATERIAL": ["X", "Y", "Z"],
                "THICKNESS": ["1.1", "1.2", "1.3"],
                "WEIGHT": ["5", "6", "7"],
            }
        )

        selected = resolve_default_data_columns(df, ["SERIAL"])

        self.assertEqual(["THICKNESS", "WEIGHT"], selected)

    def test_csv_grouping_preview_uses_selected_columns_and_filter_keys(self):
        df = pd.DataFrame(
            {
                "Reference": ["R1", "R1", "R2", "R2"],
                "TraceCode": ["T-001", "T-002", "T-003", "T-004"],
                "Shift": ["A", "B", "A", "A"],
                "Length": [10.0, 10.1, 10.2, 10.3],
            }
        )

        trace_preview = build_csv_grouping_preview(df, ["TraceCode"])
        self.assertEqual(
            [("T-001",), ("T-002",), ("T-003",), ("T-004",)],
            [row["key"] for row in trace_preview],
        )

        filtered = filter_csv_summary_by_group_keys(df, ["Reference"], [("R2",)])
        nested_preview = build_csv_grouping_preview(filtered, ["Reference", "Shift"])

        self.assertEqual([("R2", "A")], [row["key"] for row in nested_preview])
        self.assertEqual([2], [row["row_count"] for row in nested_preview])

    def test_csv_grouping_filter_keeps_tracecode_available_when_reference_is_different(self):
        df = pd.DataFrame(
            {
                "Reference": ["R1", "R1", "R2"],
                "TraceCode": ["T-001", "T-002", "T-003"],
                "Length": [10.0, 10.1, 10.2],
            }
        )

        filtered = filter_csv_summary_by_group_keys(
            df,
            ["TraceCode"],
            [("T-001",), ("T-003",)],
        )

        self.assertEqual(["T-001", "T-003"], filtered["TraceCode"].tolist())
        self.assertEqual(["R1", "R2"], filtered["Reference"].tolist())

    def test_csv_grouping_index_handles_high_cardinality_three_column_filter(self):
        row_count = 5000
        df = pd.DataFrame(
            {
                "Part ID": [f"P-{index:04d}" for index in range(row_count)],
                "TraceCode": [f"TC-{index:04d}" for index in range(row_count)],
                "Line": [f"L{index % 5}" for index in range(row_count)],
                "Length": [float(index) for index in range(row_count)],
            }
        )
        index = CsvGroupingIndex(df, ["Part ID", "TraceCode", "Line"])

        preview_rows, total = index.preview_rows(limit=50)
        second_page, second_total = index.preview_rows(offset=1000, limit=5)
        selected = {
            ("P-0001", "TC-0001", "L1"),
            ("P-2500", "TC-2500", "L0"),
            ("P-4999", "TC-4999", "L4"),
        }
        filtered = index.filter_rows(selected)

        self.assertEqual(5000, total)
        self.assertEqual(50, len(preview_rows))
        self.assertEqual(5000, second_total)
        self.assertEqual(("P-1000", "TC-1000", "L0"), second_page[0]["key"])
        self.assertEqual((("P-4999", "TC-4999", "L4"),), index.matching_keys(search_text="P-4999"))
        self.assertEqual(3, index.count_rows(selected))
        self.assertEqual(["P-0001", "P-2500", "P-4999"], filtered["Part ID"].tolist())

    def test_load_csv_with_fallbacks_handles_wide_semicolon_decimal_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "wide.csv"
            row_count = 1200
            numeric_columns = 160
            text_columns = 20
            headers = [f"N{i}" for i in range(numeric_columns)] + [
                f"T{i}" for i in range(text_columns)
            ]

            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(";".join(headers) + "\n")
                for row in range(row_count):
                    numeric_values = [
                        f"{(row + idx) / 10:.1f}".replace(".", ",")
                        for idx in range(numeric_columns)
                    ]
                    text_values = [f"TXT{(row + idx) % 97}" for idx in range(text_columns)]
                    handle.write(";".join(numeric_values + text_values) + "\n")

            df, config = load_csv_with_fallbacks(csv_path)

            self.assertEqual(df.shape, (row_count, numeric_columns + text_columns))
            self.assertEqual({"delimiter": ";", "decimal": ","}, config)
            self.assertEqual(list(df.columns[:3]), ["N0", "N1", "N2"])

    def test_load_csv_with_preferred_config_is_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "sample.csv"
            csv_path.write_text("PART;LENGTH\nA;10,5\nB;11,0\n", encoding="utf-8")

            _, config = load_csv_with_fallbacks(
                csv_path,
                preferred_config={"delimiter": ";", "decimal": ","},
            )

            self.assertEqual(";", config["delimiter"])
            self.assertEqual(",", config["decimal"])

    def test_parse_delimiter_with_sniffer_returns_common_separator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "sample.csv"
            csv_path.write_text("PART;LENGTH\nA;10,5\n", encoding="utf-8")

            self.assertEqual(";", parse_delimiter_with_sniffer(csv_path))


if __name__ == "__main__":
    unittest.main()
