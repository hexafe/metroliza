from modules.report_identity import build_report_identity_hash
from modules.report_metadata_extractor import extract_report_metadata
from modules.report_metadata_models import MetadataExtractionContext
from modules.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE


def _item(text, x0, y0, x1, y1):
    return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "page_number": 1}


def _context(file_name: str) -> MetadataExtractionContext:
    return MetadataExtractionContext(
        source_file_id=None,
        parser_id="cmm_pdf_header_box",
        source_path=f"/tmp/{file_name}",
        file_name=file_name,
        source_format="pdf",
        page_count=1,
        first_page_width=210.0,
        first_page_height=400.0,
    )


def _extract(file_name: str, header_items):
    return extract_report_metadata(
        _context(file_name),
        header_items=header_items,
        filename=file_name,
    )


def test_serial_variant_fixture_expectation():
    file_name = "V29087794_Front_plate_2019.04.11_02.PDF"
    result = _extract(
        file_name,
        [
            _item("REFERENCE", 10, 10, 40, 16),
            _item("V29087794", 50, 10, 100, 16),
            _item("PART NAME", 10, 18, 40, 24),
            _item("Front plate", 50, 18, 110, 24),
            _item("DATE", 10, 26, 40, 32),
            _item("2019.04.11", 50, 26, 110, 32),
            _item("TIME", 10, 34, 40, 40),
            _item("20:57", 50, 34, 90, 40),
            _item("SER NUMBER", 10, 42, 50, 48),
            _item("V29087794", 60, 42, 110, 48),
            _item("REV NUMBER", 10, 50, 50, 56),
            _item("B", 60, 50, 70, 56),
            _item("STATS COUNT", 10, 58, 50, 64),
            _item("2", 60, 58, 70, 64),
            _item("MEASUREMENT MADE BY", 10, 66, 80, 72),
            _item("Jane Doe", 90, 66, 130, 72),
        ],
    )

    metadata = result.metadata
    assert metadata.template_family == "cmm_pdf_header_box"
    assert metadata.template_variant == "cmm_pdf_header_box_serial_variant"
    assert metadata.reference == "V29087794"
    assert metadata.part_name == "Front plate"
    assert metadata.report_date == "2019-04-11"
    assert metadata.report_time == "20:57"
    assert metadata.revision == "B"
    assert metadata.stats_count_raw == "2"
    assert metadata.stats_count_int == 2
    assert metadata.sample_number == "2"
    assert metadata.sample_number_kind == "stats_count"
    assert metadata.operator_name == "Jane Doe"


def test_drawing_variant_fixture_expectation():
    file_name = "V29046477_001_Balance_disc_2022.03.30_04.PDF"
    result = _extract(
        file_name,
        [
            _item("REFERENCE", 10, 10, 40, 16),
            _item("V29046477_001", 50, 10, 110, 16),
            _item("PART NAME", 10, 18, 40, 24),
            _item("Balance disc", 50, 18, 120, 24),
            _item("DATE", 10, 26, 40, 32),
            _item("2022.03.30", 50, 26, 110, 32),
            _item("TIME", 10, 34, 40, 40),
            _item("09:08", 50, 34, 90, 40),
            _item("DRAWING NO", 10, 42, 50, 48),
            _item("V29046477_001", 60, 42, 140, 48),
            _item("DRAWING REV", 10, 50, 50, 56),
            _item("A.02", 60, 50, 90, 56),
            _item("STATS COUNT", 10, 58, 50, 64),
            _item("4", 60, 58, 70, 64),
            _item("MEASUREMENT MADE BY", 10, 66, 80, 72),
            _item("Jane Doe", 90, 66, 130, 72),
        ],
    )

    metadata = result.metadata
    assert metadata.template_variant == "cmm_pdf_header_box_drawing_variant"
    assert metadata.reference == "V29046477_001"
    assert metadata.part_name == "Balance disc"
    assert metadata.report_date == "2022-03-30"
    assert metadata.report_time == "09:08"
    assert metadata.revision == "A.02"
    assert metadata.stats_count_raw == "4"
    assert metadata.stats_count_int == 4
    assert metadata.sample_number == "4"
    assert metadata.sample_number_kind == "stats_count"


def test_header_over_filename_fallback_wins_and_warns():
    file_name = "VSPC015915_2020.01.01_99.PDF"
    result = _extract(
        file_name,
        [
            _item("REFERENCE", 10, 10, 40, 16),
            _item("VSPC015914", 50, 10, 100, 16),
            _item("PART NAME", 10, 18, 40, 24),
            _item("Spider busbar", 50, 18, 120, 24),
            _item("DATE", 10, 26, 40, 32),
            _item("2017.05.05", 50, 26, 110, 32),
            _item("TIME", 10, 34, 40, 40),
            _item("21:43", 50, 34, 90, 40),
            _item("SER NUMBER", 10, 42, 50, 48),
            _item("VSPC015914", 60, 42, 120, 48),
            _item("REV NUMBER", 10, 50, 50, 56),
            _item("D3", 60, 50, 90, 56),
            _item("STATS COUNT", 10, 58, 50, 64),
            _item("6", 60, 58, 70, 64),
        ],
    )

    metadata = result.metadata
    assert metadata.reference == "VSPC015914"
    assert metadata.part_name == "Spider busbar"
    assert metadata.report_date == "2017-05-05"
    assert metadata.revision == "D3"
    assert metadata.sample_number == "6"
    assert metadata.sample_number_kind == "stats_count"
    assert any(w.code == "header_reference_conflicts_with_filename" for w in metadata.warnings)
    assert any(w.code == "header_date_conflicts_with_filename" for w in metadata.warnings)
    assert any(w.code == "stats_count_conflicts_with_filename_tail" for w in metadata.warnings)


def test_drawing_variant_large_stats_count_and_identity_hash_is_stable():
    file_name = "VSPC017408_EGR_valve_EA897_2023.01.04_353201479.PDF"
    result = _extract(
        file_name,
        [
            _item("REFERENCE", 10, 10, 40, 16),
            _item("VSPC017408", 50, 10, 100, 16),
            _item("PART NAME", 10, 18, 40, 24),
            _item("EGR valve EA897", 50, 18, 140, 24),
            _item("DATE", 10, 26, 40, 32),
            _item("2023.01.04", 50, 26, 110, 32),
            _item("TIME", 10, 34, 40, 40),
            _item("13:36", 50, 34, 90, 40),
            _item("DRAWING NO", 10, 42, 50, 48),
            _item("VSPC017408", 60, 42, 120, 48),
            _item("DRAWING REV", 10, 50, 50, 56),
            _item("D", 60, 50, 90, 56),
            _item("STATS COUNT", 10, 58, 50, 64),
            _item("353201479", 60, 58, 140, 64),
        ],
    )

    metadata = result.metadata
    assert metadata.template_variant == "cmm_pdf_header_box_drawing_variant"
    assert metadata.reference == "VSPC017408"
    assert metadata.part_name == "EGR valve EA897"
    assert metadata.report_date == "2023-01-04"
    assert metadata.report_time == "13:36"
    assert metadata.revision == "D"
    assert metadata.stats_count_raw == "353201479"
    assert metadata.stats_count_int == 353201479
    assert metadata.sample_number == "353201479"
    assert metadata.sample_number_kind == "stats_count"
    assert build_report_identity_hash(metadata) == build_report_identity_hash(metadata)


def test_profile_detector_is_registered():
    assert DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.parser_id == "cmm_pdf_header_box"
