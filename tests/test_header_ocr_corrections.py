from modules.header_ocr_corrections import (
    canonicalize_header_field_name,
    canonicalize_header_label,
    correct_header_ocr_value,
    correct_operator_name_ocr_text,
    correct_part_name_ocr_text,
    correct_polish_month_ocr_text,
    correct_reference_ocr_text,
    is_logo_noise_text,
    postprocess_header_ocr_item,
    postprocess_header_ocr_items,
    preserve_comment_text,
)


def test_label_canonicalization_handles_known_ocr_drifts():
    assert canonicalize_header_label("PARTNAME") == "PART NAME"
    assert canonicalize_header_label("DRAWINGREV") == "DRAWING REV"
    assert canonicalize_header_label("SERNUMBER") == "SER NUMBER"
    assert canonicalize_header_label("REV NUMBERE") == "REV NUMBER"
    assert canonicalize_header_label("STATSCOUNT") == "STATS COUNT"
    assert canonicalize_header_label("MEASUREMENT MADEBY") == "MEASUREMENT MADE BY"


def test_field_name_canonicalization_tracks_raw_labels():
    assert canonicalize_header_field_name("PARTNAME") == "part_name"
    assert canonicalize_header_field_name("DRAWINGREV") == "revision"
    assert canonicalize_header_field_name("SERNUMBER") == "reference"
    assert canonicalize_header_field_name("STATSCOUNT") == "stats_count_raw"
    assert canonicalize_header_field_name("MEASUREMENT MADEBY") == "operator_name"


def test_polish_month_helper_corrects_common_ocr_drift():
    assert correct_polish_month_ocr_text("stycznla 28, 2020") == "stycznia 28, 2020"
    assert correct_header_ocr_value("report_date", "wrzesnla 08, 2020") == "września 08, 2020"


def test_reference_correction_only_applies_in_reference_fields():
    assert correct_reference_ocr_text("VSPC0174O8") == "VSPC017408"
    assert correct_header_ocr_value("reference", "VSPC0174O8") == "VSPC017408"
    assert correct_header_ocr_value("part_name", "VSPC0174O8") == "VSPC0174O8"


def test_operator_aliases_are_canonicalized_deterministically():
    assert correct_operator_name_ocr_text("PAM Jakbiec S.") == "PAM_Jakubiec S."
    assert correct_operator_name_ocr_text("PAM MW") == "PAM_MW"
    assert correct_operator_name_ocr_text("REX GAZDA") == "REX_GAZDA"
    assert correct_operator_name_ocr_text("REX_Stachura") == "REX_Stachura"
    assert correct_operator_name_ocr_text("MADEBY : REX GAZDA") == "REX_GAZDA"
    assert correct_operator_name_ocr_text("MEASUREMENT MADEBY : PAM Jakubiec S.") == "PAM_Jakubiec S."


def test_part_name_cleanup_is_conservative():
    assert correct_part_name_ocr_text("BodyEA211 1.0L") == "Body EA211 1.0L"
    assert correct_part_name_ocr_text("EGR valve EA 897") == "EGR valve EA897"


def test_comments_are_preserved():
    assert preserve_comment_text("  raw  comment  text  ") == "raw  comment  text"
    assert correct_header_ocr_value("comment", "  1_1_2  ") == "1_1_2"


def test_logo_noise_filter_is_conservative():
    assert is_logo_noise_text("logo") is True
    assert is_logo_noise_text("PAM", y0=8.0) is True
    assert is_logo_noise_text("PAM_MW", y0=72.0) is False


def test_batch_postprocessing_filters_noise_and_canonicalizes_labels():
    items = [
        {"text": "logo", "y0": 4.0},
        {"text": "PARTNAME", "y0": 10.0},
        {"text": "PAM", "y0": 8.0},
        {"text": "PAM Jakbiec S.", "y0": 72.0, "field_name": "operator_name"},
    ]

    corrected = postprocess_header_ocr_items(items)

    assert [item["text"] for item in corrected] == ["PART NAME", "PAM_Jakubiec S."]
    assert postprocess_header_ocr_item({"text": "REV NUMBERE"})["text"] == "REV NUMBER"
