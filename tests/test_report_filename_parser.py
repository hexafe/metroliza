import pytest

from metroliza.reports.report_filename_parser import parse_report_filename


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (
            "04L_128_637_outlet gas_duct_2018.01.11.PDF",
            ("04L_128_637", "2018-01-11", "2018.01.11", "outlet gas duct", None),
        ),
        (
            "V29112255_T6_Throttle_body_2019.07.09_1_1.pdf",
            ("V29112255", "2019-07-09", "2019.07.09", "T6 Throttle body", "1"),
        ),
        (
            "VTST5001_Widget_AB123_1.0L_2024.06_20_01.1.PDF",
            ("VTST5001", "2024-06-20", "2024.06.20", "Widget AB123 1.0L", "01.1"),
        ),
        (
            "Fixture_2024_06_20.PDF",
            (None, "2024-06-20", "2024.06.20", "Fixture", None),
        ),
        (
            "V29121544_Throttle_body_DV5R_Sonafi_2020.28.26_01.PDF",
            ("V29121544", None, "2020.28.26", "Throttle body DV5R Sonafi", "01"),
        ),
    ],
)
def test_parse_report_filename_handles_supplier_and_split_date_shapes(filename, expected):
    parsed = parse_report_filename(filename)

    assert (
        parsed.reference,
        parsed.report_date,
        parsed.raw_date_candidate,
        parsed.part_name,
        parsed.sample_tail,
    ) == expected
