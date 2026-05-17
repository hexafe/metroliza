from modules.base_report_parser import BaseReportParser


class _Parser(BaseReportParser):
    def open_report(self):
        return None

    def split_text_to_blocks(self):
        return None


def test_filename_metadata_extracts_complex_sample_number_and_normalized_date(tmp_path):
    report_path = tmp_path / "2024-04-21_BATCH_17_part_A.PDF"
    parser = _Parser(str(report_path), database=":memory:")

    assert parser.get_date_from_filename() == "2024-04-21"
    assert parser.get_sample_number_from_file() == "BATCH_17_part_A"


def test_filename_metadata_handles_supported_date_separators(tmp_path):
    report_path = tmp_path / "2024.4.2_sample-99.pdf"
    parser = _Parser(str(report_path), database=":memory:")

    assert parser.get_date_from_filename() == "2024-4-2"
    assert parser.get_sample_number_from_file() == "sample-99"


def test_filename_metadata_uses_safe_fallbacks_when_name_does_not_match(tmp_path):
    report_path = tmp_path / "unmatched-report.pdf"
    parser = _Parser(str(report_path), database=":memory:")

    assert parser.get_date_from_filename() == "0000-00-00"
    assert parser.get_sample_number_from_file() == "0000"
