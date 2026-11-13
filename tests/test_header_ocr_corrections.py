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
    assert correct_reference_ocr_text("VTST0174O8") == "VTST017408"
    assert correct_header_ocr_value("reference", "VTST0174O8") == "VTST017408"
    assert correct_header_ocr_value("part_name", "VTST0174O8") == "VTST0174O8"


def test_operator_aliases_are_canonicalized_deterministically():
    assert correct_operator_name_ocr_text("LAB Operator A") == "LAB_OPERATOR_A"
    assert correct_operator_name_ocr_text("LAB MW") == "LAB_MW"
    assert correct_operator_name_ocr_text("CMM Operator A") == "CMM_OPERATOR_A"
    assert correct_operator_name_ocr_text("CMM_Operator B") == "CMM_OPERATOR_B"
    assert correct_operator_name_ocr_text("MADEBY : CMM Operator A") == "CMM_OPERATOR_A"
    assert correct_operator_name_ocr_text("MEASUREMENT MADEBY : LAB Operator A") == "LAB_OPERATOR_A"


def test_part_name_cleanup_is_conservative():
    assert correct_part_name_ocr_text("WidgetAB123 1.0L") == "Widget AB123 1.0L"
    assert correct_part_name_ocr_text("Valve AB 123") == "Valve AB123"


def test_comments_are_preserved():
    assert preserve_comment_text("  raw  comment  text  ") == "raw  comment  text"
    assert correct_header_ocr_value("comment", "  1_1_2  ") == "1_1_2"


def test_logo_noise_filter_is_conservative():
    assert is_logo_noise_text("logo") is True
    assert is_logo_noise_text("LAB", y0=8.0) is True
    assert is_logo_noise_text("LAB_MW", y0=72.0) is False


def test_batch_postprocessing_filters_noise_and_canonicalizes_labels():
    items = [
        {"text": "logo", "y0": 4.0},
        {"text": "PARTNAME", "y0": 10.0},
        {"text": "LAB", "y0": 8.0},
        {"text": "LAB Operator A", "y0": 72.0, "field_name": "operator_name"},
    ]

    corrected = postprocess_header_ocr_items(items)

    assert [item["text"] for item in corrected] == ["PART NAME", "LAB_OPERATOR_A"]
    assert postprocess_header_ocr_item({"text": "REV NUMBERE"})["text"] == "REV NUMBER"


# Independent literal pre-T20 string transformations, including raw coercion order.
def _original_compact_token(value):
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in normalized if not unicodedata.combining(char)).upper()
    return re.sub(r"[^A-Z0-9]+", "", text)


def test_literal_compact_and_accent_corpus():
    import unicodedata
    from metroliza.reports import header_ocr_corrections as rules

    corpus = [None, False, True, 0, 12, -0.0, float("nan"), float("inf"),
              "", " \t\n", "\x00(A).B:C;", "e\u0301", "ĄŚŻ łódź", "ßﬃİ", "ＰＡＲＴＮＡＭＥ",
              "DRAWING No", "a" * 5000]
    for value in corpus:
        assert rules.compact_token(value) == _original_compact_token(value)
        if isinstance(value, str):
            normalized = unicodedata.normalize("NFKD", value)
            expected = "".join(c for c in normalized if not unicodedata.combining(c))
            assert rules.strip_accents(value) == expected


def test_compact_raw_callbacks_and_errors():
    from metroliza.reports import header_ocr_corrections as rules

    events = []

    class Raw:
        def __bool__(self):
            events.append("bool")
            return True

        def __str__(self):
            events.append("str")
            return "párt name"

    class Text(str):
        __bool__ = Raw.__bool__
        __str__ = Raw.__str__

    for value in (Raw(), Text("NOK")):
        events.clear()
        expected = _original_compact_token(value), list(events)
        events.clear()
        assert (rules.compact_token(value), list(events)) == expected

    class Bad:
        def __bool__(self):
            events.append("bool_error")
            raise ValueError("truth failed")

    import pytest
    for function in (rules.compact_token, _original_compact_token):
        with pytest.raises(ValueError, match="truth failed"):
            function(Bad())


def test_header_dynamic_aliases_functions_and_independent_results(monkeypatch):
    from metroliza.reports import header_ocr_corrections as rules
    from modules import header_ocr_corrections as legacy

    assert legacy is rules
    first = rules.canonicalize_label("PARTNAME")
    second = rules.canonicalize_label("PARTNAME")
    assert first == second and first is not second
    monkeypatch.setitem(rules._LABEL_ALIASES, "PARTNAME", "CHANGED")
    assert rules.canonicalize_label("PARTNAME").value == "CHANGED"
    monkeypatch.setitem(rules._LABEL_FIELDS, "CHANGED", "comment")
    assert rules.canonicalize_header_field_name("PARTNAME") == "comment"
    monkeypatch.setattr(rules, "strip_accents", lambda value: "NANE")
    assert rules.compact_token("PARTNAME") == "NANE"
    assert rules.canonicalize_label("PARTNAME").value == "NAME"


def test_header_regex_and_unicode_function_overrides(monkeypatch):
    import re
    from metroliza.reports import header_ocr_corrections as rules

    rules.compact_token("abc")
    monkeypatch.setattr(rules, "_NON_ALNUM_RE", re.compile("B"))
    assert rules.compact_token("abc") == "AC"
    rules.strip_accents("abc")
    monkeypatch.setattr(rules.unicodedata, "normalize", lambda form, value: "é")
    assert rules.strip_accents("abc") == "é"
    assert rules.compact_token("abc") == "É"


def test_normalization_cache_activation_bounds_eviction_and_fallback():
    from metroliza.reports import header_ocr_corrections as rules

    for cache in (rules._strip_accents_cached, rules._compact_token_cached):
        cache.cache_clear()
    for text in ("PARTNAME", "párt nâme", "ßﬃİ"):
        assert rules.compact_token(text) == _original_compact_token(text)
        assert rules.compact_token(text) == _original_compact_token(text)
    assert rules._strip_accents_cached.cache_info().hits == 3
    assert rules._compact_token_cached.cache_info().hits == 3
    before = (rules._strip_accents_cached.cache_info(), rules._compact_token_cached.cache_info())
    long_text = "é" * 5000
    assert rules.compact_token(long_text) == _original_compact_token(long_text)
    assert before == (rules._strip_accents_cached.cache_info(), rules._compact_token_cached.cache_info())

    class Text(str):
        pass

    strip_before = rules._strip_accents_cached.cache_info()
    assert rules.strip_accents(Text("é")) == "e"
    assert strip_before == rules._strip_accents_cached.cache_info()
    for index in range(1100):
        text = f"párt {index}"
        assert rules.compact_token(text) == _original_compact_token(text)
    for cache in (rules._strip_accents_cached, rules._compact_token_cached):
        assert cache.cache_info().currsize == cache.cache_info().maxsize == 1024
    misses = rules._strip_accents_cached.cache_info().misses
    assert rules.strip_accents("PARTNAME") == "PARTNAME"
    assert rules._strip_accents_cached.cache_info().misses == misses + 1


def test_ascii_fastpath_skips_unicode_work_and_unicode_cache_is_warm():
    import sys
    from metroliza.reports import header_ocr_corrections as rules

    rules._strip_accents_cached.cache_clear()
    calls = []

    def observe(frame, event, arg):
        if event == "c_call" and arg is rules.unicodedata.normalize:
            calls.append(arg)

    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        assert rules.strip_accents("ASCII") == "ASCII"
        assert calls == []
        assert rules.strip_accents("é") == "e"
        assert len(calls) == 1
        assert rules.strip_accents("é") == "e"
        assert len(calls) == 1
    finally:
        sys.setprofile(previous)


def test_combining_override_and_item_mutability_remain_live(monkeypatch):
    from metroliza.reports import header_ocr_corrections as rules

    assert rules.strip_accents("é") == "e"
    monkeypatch.setattr(rules.unicodedata, "combining", lambda char: 0)
    assert rules.strip_accents("é") == "e\u0301"
    item = {"text": "PARTNAME", "y0": 25, "metadata": {"kept": True}}
    first = rules.postprocess_header_ocr_item(item)
    second = rules.postprocess_header_ocr_item(item)
    first["text"] = "changed"
    assert item["text"] == "PARTNAME" and second["text"] == "PART NAME"
    assert first["metadata"] is item["metadata"] is second["metadata"]
