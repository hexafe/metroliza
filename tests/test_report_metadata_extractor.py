import importlib.util
from pathlib import Path

from modules.report_identity import build_report_identity_hash
from modules.report_metadata_extractor import extract_report_metadata
from modules.report_metadata_models import MetadataExtractionContext
from modules.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE


def _item(text, x0, y0, x1, y1):
    return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "page_number": 1}


def _context(file_name: str, *, width: float = 210.0, height: float = 400.0) -> MetadataExtractionContext:
    return MetadataExtractionContext(
        source_file_id=None,
        parser_id="cmm_pdf_header_box",
        source_path=f"/tmp/{file_name}",
        file_name=file_name,
        source_format="pdf",
        page_count=1,
        first_page_width=width,
        first_page_height=height,
    )


def _extract(file_name: str, header_items, *, width: float = 210.0, height: float = 400.0):
    return extract_report_metadata(
        _context(file_name, width=width, height=height),
        header_items=header_items,
        filename=file_name,
    )


def test_serial_variant_fixture_expectation():
    file_name = "VTST1001_Panel_alpha_2024.04.11_02.PDF"
    result = _extract(
        file_name,
        [
            _item("REFERENCE", 10, 10, 40, 16),
            _item("VTST1001", 50, 10, 100, 16),
            _item("PART NAME", 10, 18, 40, 24),
            _item("Panel alpha", 50, 18, 110, 24),
            _item("DATE", 10, 26, 40, 32),
            _item("2024.04.11", 50, 26, 110, 32),
            _item("TIME", 10, 34, 40, 40),
            _item("20:57", 50, 34, 90, 40),
            _item("SER NUMBER", 10, 42, 50, 48),
            _item("VTST1001", 60, 42, 110, 48),
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
    assert metadata.reference == "VTST1001"
    assert metadata.part_name == "Panel alpha"
    assert metadata.report_date == "2024-04-11"
    assert metadata.report_time == "20:57"
    assert metadata.revision == "B"
    assert metadata.stats_count_raw == "2"
    assert metadata.stats_count_int == 2
    assert metadata.sample_number == "2"
    assert metadata.sample_number_kind == "stats_count"
    assert metadata.operator_name == "Jane Doe"


def test_drawing_variant_fixture_expectation():
    file_name = "VTST2001_001_Fixture_disk_2024.03.30_04.PDF"
    result = _extract(
        file_name,
        [
            _item("REFERENCE", 10, 10, 40, 16),
            _item("VTST2001_001", 50, 10, 110, 16),
            _item("PART NAME", 10, 18, 40, 24),
            _item("Fixture disk", 50, 18, 120, 24),
            _item("DATE", 10, 26, 40, 32),
            _item("2024.03.30", 50, 26, 110, 32),
            _item("TIME", 10, 34, 40, 40),
            _item("09:08", 50, 34, 90, 40),
            _item("DRAWING NO", 10, 42, 50, 48),
            _item("VTST2001_001", 60, 42, 140, 48),
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
    assert metadata.reference == "VTST2001_001"
    assert metadata.part_name == "Fixture disk"
    assert metadata.report_date == "2024-03-30"
    assert metadata.report_time == "09:08"
    assert metadata.revision == "A.02"
    assert metadata.stats_count_raw == "4"
    assert metadata.stats_count_int == 4
    assert metadata.sample_number == "4"
    assert metadata.sample_number_kind == "stats_count"


def test_ocr_drift_labels_values_are_corrected_with_telemetry():
    file_name = "VTST017408_Widget_AB123_1.0L_2024.09.08_03.PDF"
    result = _extract(
        file_name,
        [
            _item("PARTNANE", 10, 10, 60, 16),
            _item("WidgetAB123 1.0L", 70, 10, 150, 16),
            _item("DATE", 10, 20, 40, 26),
            _item("wrzesnla 08, 2024", 70, 20, 150, 26),
            _item("TIME", 10, 30, 40, 36),
            _item("11;56", 70, 30, 110, 36),
            _item("SER", 10, 40, 35, 46),
            _item("NUNBER", 40, 40, 90, 46),
            _item("VTST0174O8", 100, 40, 160, 46),
            _item("REV", 10, 50, 35, 56),
            _item("NUMBERE", 40, 50, 90, 56),
            _item("D", 100, 50, 110, 56),
            _item("STATS", 10, 60, 50, 66),
            _item("C0UNT", 55, 60, 95, 66),
            _item("3", 100, 60, 110, 66),
            _item("MEASUREMENT NADE BY", 10, 70, 110, 76),
            _item("LAB Operator A", 120, 70, 180, 76),
        ],
        width=600.0,
        height=800.0,
    )

    metadata = result.metadata
    assert metadata.template_variant == "cmm_pdf_header_box_serial_variant"
    assert metadata.reference == "VTST017408"
    assert metadata.part_name == "Widget AB123 1.0L"
    assert metadata.report_date == "2024-09-08"
    assert metadata.report_time == "11:56"
    assert metadata.revision == "D"
    assert metadata.stats_count_raw == "3"
    assert metadata.sample_number == "3"
    assert metadata.operator_name == "LAB_OPERATOR_A"

    corrections = metadata.metadata_json["field_corrections"]
    assert corrections["reference"]["raw_ocr_value"] == "VTST0174O8"
    assert corrections["reference"]["corrected_input_value"] == "VTST017408"
    assert corrections["reference"]["was_corrected"] is True
    assert corrections["report_time"]["correction_rule"] == "time:separator_normalized"
    assert corrections["operator_name"]["corrected_input_value"] == "LAB_OPERATOR_A"


def test_header_over_filename_fallback_wins_and_warns():
    file_name = "VTST4015_2024.01.01_99.PDF"
    result = _extract(
        file_name,
        [
            _item("REFERENCE", 10, 10, 40, 16),
            _item("VTST4014", 50, 10, 100, 16),
            _item("PART NAME", 10, 18, 40, 24),
            _item("Connector bar", 50, 18, 120, 24),
            _item("DATE", 10, 26, 40, 32),
            _item("2024.05.05", 50, 26, 110, 32),
            _item("TIME", 10, 34, 40, 40),
            _item("21:43", 50, 34, 90, 40),
            _item("SER NUMBER", 10, 42, 50, 48),
            _item("VTST4014", 60, 42, 120, 48),
            _item("REV NUMBER", 10, 50, 50, 56),
            _item("D3", 60, 50, 90, 56),
            _item("STATS COUNT", 10, 58, 50, 64),
            _item("6", 60, 58, 70, 64),
        ],
    )

    metadata = result.metadata
    assert metadata.reference == "VTST4014"
    assert metadata.part_name == "Connector bar"
    assert metadata.report_date == "2024-05-05"
    assert metadata.revision == "D3"
    assert metadata.sample_number == "6"
    assert metadata.sample_number_kind == "stats_count"
    assert any(w.code == "header_reference_conflicts_with_filename" for w in metadata.warnings)
    assert any(w.code == "header_date_conflicts_with_filename" for w in metadata.warnings)
    assert any(w.code == "stats_count_conflicts_with_filename_tail" for w in metadata.warnings)


def test_drawing_variant_large_stats_count_and_identity_hash_is_stable():
    file_name = "VTST3001_Valve_AB123_2024.01.04_353201479.PDF"
    result = _extract(
        file_name,
        [
            _item("REFERENCE", 10, 10, 40, 16),
            _item("VTST3001", 50, 10, 100, 16),
            _item("PART NAME", 10, 18, 40, 24),
            _item("Valve AB123", 50, 18, 140, 24),
            _item("DATE", 10, 26, 40, 32),
            _item("2024.01.04", 50, 26, 110, 32),
            _item("TIME", 10, 34, 40, 40),
            _item("13:36", 50, 34, 90, 40),
            _item("DRAWING NO", 10, 42, 50, 48),
            _item("VTST3001", 60, 42, 120, 48),
            _item("DRAWING REV", 10, 50, 50, 56),
            _item("D", 60, 50, 90, 56),
            _item("STATS COUNT", 10, 58, 50, 64),
            _item("353201479", 60, 58, 140, 64),
        ],
    )

    metadata = result.metadata
    assert metadata.template_variant == "cmm_pdf_header_box_drawing_variant"
    assert metadata.reference == "VTST3001"
    assert metadata.part_name == "Valve AB123"
    assert metadata.report_date == "2024-01-04"
    assert metadata.report_time == "13:36"
    assert metadata.revision == "D"
    assert metadata.stats_count_raw == "353201479"
    assert metadata.stats_count_int == 353201479
    assert metadata.sample_number == "353201479"
    assert metadata.sample_number_kind == "stats_count"
    assert build_report_identity_hash(metadata) == build_report_identity_hash(metadata)


def test_positional_serial_variant_extracts_unlabeled_date_time_and_preserves_comment():
    file_name = "VTST5001_Widget_AB123_1.0L_2024.06_20_01.1.PDF"
    result = _extract(
        file_name,
        [
            _item("PART", 150, 10, 178, 16),
            _item("NAME", 182, 10, 220, 16),
            _item(":", 224, 10, 230, 16),
            _item("Widget", 250, 10, 282, 16),
            _item("AB", 286, 10, 302, 16),
            _item("123", 306, 10, 330, 16),
            _item("1.0L", 334, 10, 365, 16),
            _item("czerwca", 450, 10, 492, 16),
            _item("20,", 496, 10, 512, 16),
            _item("2024", 516, 10, 526, 16),
            _item("11:56", 536, 10, 568, 16),
            _item("REV", 150, 40, 175, 46),
            _item("NUMBER", 180, 40, 228, 46),
            _item(":", 232, 40, 238, 46),
            _item("B", 250, 40, 258, 46),
            _item("SER", 305, 40, 330, 46),
            _item("NUMBER", 334, 40, 382, 46),
            _item(":", 386, 40, 392, 46),
            _item("VTST5001_001", 398, 40, 440, 46),
            _item("STATS", 450, 40, 488, 46),
            _item("COUNT", 492, 40, 532, 46),
            _item(":", 536, 40, 542, 46),
            _item("1", 552, 40, 560, 46),
            _item("MEASUREMENT", 150, 70, 225, 76),
            _item("MADE", 230, 70, 260, 76),
            _item("BY", 264, 70, 278, 76),
            _item(":", 282, 70, 288, 76),
            _item("LAB_MW", 290, 70, 298, 76),
            _item("COMMENT", 320, 70, 380, 76),
            _item(":", 384, 70, 390, 76),
            _item("1_1_2", 400, 70, 440, 76),
        ],
        width=600.0,
        height=800.0,
    )

    metadata = result.metadata
    assert metadata.template_variant == "cmm_pdf_header_box_serial_variant"
    assert metadata.reference == "VTST5001_001"
    assert metadata.part_name == "Widget AB 123 1.0L"
    assert metadata.report_date == "2024-06-20"
    assert metadata.report_time == "11:56"
    assert metadata.revision == "B"
    assert metadata.operator_name == "LAB_MW"
    assert metadata.comment == "1_1_2"
    assert metadata.stats_count_raw == "1"
    assert metadata.stats_count_int == 1
    assert metadata.sample_number == "1"
    assert metadata.sample_number_kind == "stats_count"
    assert metadata.metadata_json["field_sources"]["report_date"] == "position_cell"
    assert metadata.metadata_json["sample_number_provenance"] == "projected_from_stats_count"
    assert not any(w.code == "insufficient_header_text" for w in metadata.warnings)


def test_rapidocr_style_position_cells_extract_embedded_time_and_strip_operator_label():
    file_name = "VTST5001_Widget_AB123_1.0L_2024.01.28_4_1.pdf"
    result = _extract(
        file_name,
        [
            _item("PART NAME", 167.2, 15.7, 207.9, 20.9),
            _item("WidgetAB123 1.0L", 232.6, 15.7, 281.3, 21.4),
            _item("stycznia 28, 2024", 423.0, 15.4, 470.7, 21.7),
            _item("13:41", 491.8, 15.1, 507.5, 21.4),
            _item("DRAWING REV", 167.4, 44.8, 213.0, 50.6),
            _item("D.01", 231.8, 44.8, 245.0, 51.1),
            _item("DRAWING No", 296.5, 44.8, 337.2, 50.6),
            _item("VTST5001_001", 358.4, 45.1, 405.8, 50.6),
            _item("STATS COUNT", 423.5, 45.1, 469.4, 50.0),
            _item("1", 491.3, 45.6, 494.4, 49.5),
            _item("MEASUREMENT MADEBY : CMM OPERATOR A", 167.2, 74.5, 288.0, 80.0),
            _item("COMMENT :4_1", 296.5, 74.2, 342.4, 80.2),
        ],
        width=595.273,
        height=841.886,
    )

    metadata = result.metadata
    assert metadata.report_date == "2024-01-28"
    assert metadata.report_time == "13:41"
    assert metadata.operator_name == "CMM_OPERATOR_A"
    assert metadata.metadata_json["field_sources"]["report_time"] == "position_cell"
    corrections = metadata.metadata_json["field_corrections"]
    assert corrections["report_time"]["source_cell"] == "row0_date_cell:embedded_time"
    assert corrections["operator_name"]["correction_rule"] == "operator_alias:cmm_operator_a"


def test_filename_split_date_fallback_does_not_pollute_part_name():
    file_name = "VTST5001_Widget_AB123_1.0L_2024.06_20_01.1.PDF"
    result = _extract(file_name, [])

    metadata = result.metadata
    assert metadata.reference == "VTST5001"
    assert metadata.report_date == "2024-06-20"
    assert metadata.part_name == "Widget AB123 1.0L"
    assert metadata.sample_number == "01.1"
    assert metadata.sample_number_kind == "filename_tail"
    assert metadata.stats_count_raw == "01.1"
    assert metadata.stats_count_int is None
    assert any(w.code == "insufficient_header_text" for w in metadata.warnings)


def test_parser_header_extraction_uses_ocr_when_structured_words_are_missing(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "_cmm_report_parser_real_header_test",
        Path("modules/cmm_report_parser.py"),
    )
    parser_module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(parser_module)
    parser_class = parser_module.CMMReportParser

    class _Rect:
        width = 600.0
        height = 800.0

    class _Page:
        rect = _Rect()

        def get_text(self, mode=None):
            if mode == "dict":
                return {
                    "blocks": [
                        {
                            "type": 1,
                            "bbox": (40.0, 5.0, 560.0, 95.0),
                        }
                    ]
                }
            if mode == "words":
                return []
            return ""

    ocr_items = [
        _item("PART", 150, 10, 178, 16),
        _item("NAME", 182, 10, 220, 16),
        _item("SER", 305, 40, 330, 46),
        _item("NUMBER", 334, 40, 382, 46),
        _item("REV", 150, 40, 175, 46),
        _item("NUMBER", 180, 40, 228, 46),
        _item("STATS", 450, 40, 488, 46),
        _item("COUNT", 492, 40, 532, 46),
    ]

    def _fake_ocr(cls, page, bbox, pdf_backend):
        return ocr_items, None

    monkeypatch.setattr(parser_class, "_ocr_header_items_from_pixmap", classmethod(_fake_ocr))

    items, diagnostics = parser_class._extract_first_page_header_items(_Page(), object())

    assert items == ocr_items
    assert diagnostics["header_extraction_mode"] == "ocr"
    assert diagnostics["header_word_count"] == len(ocr_items)
    assert diagnostics["header_required_fields_found"] >= 4


def test_parser_header_extraction_light_mode_skips_ocr_when_structured_words_are_missing(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "_cmm_report_parser_real_light_header_test",
        Path("modules/cmm_report_parser.py"),
    )
    parser_module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(parser_module)
    parser_class = parser_module.CMMReportParser

    class _Rect:
        width = 600.0
        height = 800.0

    class _Page:
        rect = _Rect()

        def get_text(self, mode=None):
            if mode == "dict":
                return {
                    "blocks": [
                        {
                            "type": 1,
                            "bbox": (40.0, 5.0, 560.0, 95.0),
                        }
                    ]
                }
            if mode == "words":
                return []
            return ""

    def _fail_ocr(cls, page, bbox, pdf_backend):
        raise AssertionError("OCR fallback should be skipped in light metadata mode")

    monkeypatch.setattr(parser_class, "_ocr_header_items_from_pixmap", classmethod(_fail_ocr))

    items, diagnostics = parser_class._extract_first_page_header_items(
        _Page(),
        object(),
        metadata_parsing_mode="light",
    )

    assert items == []
    assert diagnostics["metadata_parsing_mode"] == "light"
    assert diagnostics["header_extraction_mode"] == "none"
    assert diagnostics["header_ocr_skipped"] == "light_metadata_mode"
    assert "header_ocr_error" not in diagnostics


def test_profile_detector_is_registered():
    assert DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.parser_id == "cmm_pdf_header_box"
