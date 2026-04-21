from modules.report_metadata_normalizers import (
    normalize_comment,
    normalize_operator_name,
    normalize_part_name,
    normalize_reference,
    normalize_report_date,
    normalize_report_time,
    normalize_revision,
    normalize_sample_number,
    normalize_stats_count,
)


def test_normalize_reference_preserves_suffix_tokens():
    assert normalize_reference("  V29046477_001  ") == "V29046477_001"


def test_normalize_report_date_supports_numeric_and_polish_months():
    assert normalize_report_date("2019.04.11") == "2019-04-11"
    assert normalize_report_date("11 kwietnia 2024") == "2024-04-11"
    assert normalize_report_date("czerwca 20, 2018") == "2018-06-20"
    assert normalize_report_date("czerwca 20 2018") == "2018-06-20"
    assert normalize_report_date("pazdziernika 08, 2020") == "2020-10-08"


def test_normalize_report_time_zero_pads_and_rejects_invalid_times():
    assert normalize_report_time("9:8") == "09:08"
    assert normalize_report_time("25:10") is None


def test_normalize_part_name_handles_filename_fallback_and_header_values():
    assert normalize_part_name("Front_plate", from_filename=True) == "Front plate"
    assert normalize_part_name("Front plate", from_filename=False) == "Front plate"


def test_normalize_revision_preserves_alphanumeric_structure():
    assert normalize_revision(" A.02 ") == "A.02"


def test_normalize_stats_count_returns_text_and_integer():
    assert normalize_stats_count(" 353201479 ") == ("353201479", 353201479)
    assert normalize_stats_count("A12") == ("A12", None)


def test_normalize_sample_number_operator_and_comment():
    assert normalize_sample_number(" 0004 ") == "0004"
    assert normalize_operator_name("  Jane   Doe ") == "Jane Doe"
    assert normalize_comment("   ") is None
