"""Parity and regression guards for the cached header-label lookups in the metadata selector (#1115).

The selector used to rebuild the per-field label lookups and re-normalise every alias on each
``_match_label_at`` call. The lookups are now compiled once per alias set and the pure normalisation
helpers are cached. These tests prove the output is unchanged against a reference that keeps the
pre-change matching logic and runs with every cache bypassed, and guard against per-call rebuilding.
"""

from __future__ import annotations

from dataclasses import replace
import random
import unicodedata

from metroliza.reports import report_metadata_selector as sel
from metroliza.reports.report_metadata_models import MetadataExtractionContext
from metroliza.reports.report_metadata_profiles import DEFAULT_CMM_PDF_HEADER_BOX_PROFILE

PAGE_WIDTH = 600.0
PAGE_HEIGHT = 800.0

# A second alias set: same fields, accented/translated labels, a label shared by two fields (first field
# in profile order must win) and aliases that only match when spread over several header items.
ALT_PROFILE = replace(
    DEFAULT_CMM_PDF_HEADER_BOX_PROFILE,
    label_aliases={
        "reference": ("NUMÉRO DE SÉRIE", "SER NUMBER", "REF", "ZNACZNIK"),
        "report_date": ("DATE", "DATA RAPORTU", "DATA"),
        "report_time": ("TIME", "GODZINA", "ZNACZNIK"),
        "part_name": ("PART NAME", "NOM DE LA PIÈCE", "PART"),
        "revision": ("REV NUMBER", "RÉVISION", "REVISION LEVEL"),
        "sample_number": ("SAMPLE NUMBER", "NUMER PRÓBKI"),
        "stats_count_raw": ("STATS COUNT", "LICZBA STATYSTYK"),
        "operator_name": ("MEASUREMENT MADE BY", "OPÉRATEUR", "MEASURED BY"),
        "comment": ("COMMENT", "UWAGI"),
    },
)
# Same labels as the default profile, but ``DATE`` now introduces the comment field, and two fields share the
# multi-word label ``REPORT DATE`` (a tie: the earlier field wins) while one has a longer overlapping label.
SHIFTED_PROFILE = replace(
    DEFAULT_CMM_PDF_HEADER_BOX_PROFILE,
    label_aliases={
        **DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.label_aliases,
        "report_date": ("REPORT DATE",),
        "comment": ("COMMENT", "DATE", "REPORT DATE", "REPORT DATE NOTE"),
    },
)
PROFILES = {
    "default": DEFAULT_CMM_PDF_HEADER_BOX_PROFILE,
    "alt": ALT_PROFILE,
    "shifted": SHIFTED_PROFILE,
}

VALUES = {
    "reference": ("VTST1001", "V-TST-1002", "VSPC4411", "VTST0174O8", "AM-12-34"),
    "report_date": ("2024.04.11", "wrzesnla 08, 2024", "8 października 2024", "2024-01-05", "11.04.2024"),
    "report_time": ("20:57", "11;56", "7.05", "21 : 30"),
    "part_name": ("Panel alpha", "Widget AB123 1.0L", "Cover-B 7"),
    "revision": ("B", "D", "07"),
    "sample_number": ("7", "0012"),
    "stats_count_raw": ("2", "12", "0003", "C0UNT 3"),
    "operator_name": ("Jane Doe", "LAB Operator A", "CMM operator b"),
    "comment": ("sample 5", "re-measure after fixture change", "x"),
}
NOISE = ("SYNTHETIC CMM REPORT", "Page 1", "CMM REPORT", "|", "ABC-123")
SEPARATORS = (":", "-", ":-", "", " ")
OCR_SWAPS = (("O", "0"), ("M", "N"), ("I", "L"), ("E", "É"), ("S", "5"))


def _accent(text: str, rng: random.Random) -> str:
    # Decompose one vowel with a combining accent so strip_accents has real work to do.
    vowels = [i for i, char in enumerate(text) if char.upper() in "AEIOU"]
    if not vowels:
        return text
    position = rng.choice(vowels)
    return unicodedata.normalize("NFC", text[: position + 1] + "́" + text[position + 1 :])


def _decorate_label(label: str, rng: random.Random) -> str:
    choice = rng.random()
    if choice < 0.15:
        return label.lower()
    if choice < 0.30:
        return label.title()
    if choice < 0.40:
        return _accent(label, rng)
    if choice < 0.55:
        before, after = rng.choice(OCR_SWAPS)
        return label.replace(before, after, 1)
    if choice < 0.65:
        return label + rng.choice((":", ".", " :"))
    return label


def _build_items(rng: random.Random, profile) -> list[dict]:
    """One synthetic header: labelled fields (some missing, some split over items) plus noise."""
    fields = list(profile.label_aliases)
    rng.shuffle(fields)
    pending: list[list[str]] = []
    for field_name in fields:
        if rng.random() < 0.2:
            continue  # label missing from this report
        aliases = (field_name.replace("_", " ").upper(), *profile.label_aliases[field_name])
        label = _decorate_label(rng.choice(aliases), rng)
        words = label.split(" ") if rng.random() < 0.6 else [label]
        tokens = list(words)
        if rng.random() < 0.5:
            tokens.append(rng.choice(SEPARATORS))
        if rng.random() < 0.85:
            tokens.append(rng.choice(VALUES[field_name]))
        pending.append(tokens)
    if rng.random() < 0.5:
        pending.insert(rng.randrange(len(pending) + 1), [rng.choice(NOISE)])

    items: list[dict] = []
    row_index = 0
    cursor = 0
    while cursor < len(pending):
        # Sometimes share a row between two fields so value/label boundaries are exercised.
        width = 2 if rng.random() < 0.25 and cursor + 1 < len(pending) else 1
        x = 10.0
        for tokens in pending[cursor : cursor + width]:
            for token in tokens:
                items.append({"text": token, "x0": x, "y0": 10.0 + 8.0 * row_index, "x1": x + 38.0, "y1": 16.0 + 8.0 * row_index, "page_number": 1})
                x += 40.0
        cursor += width
        row_index += 1
    return items


def _context(file_name: str) -> MetadataExtractionContext:
    return MetadataExtractionContext(
        source_file_id=None,
        parser_id="cmm_pdf_header_box",
        source_path=f"/tmp/{file_name}",
        file_name=file_name,
        source_format="pdf",
        page_count=1,
        first_page_width=PAGE_WIDTH,
        first_page_height=PAGE_HEIGHT,
    )


def _select(profile, items, file_name="VTST1001_Panel_alpha_2024.04.11_02.PDF"):
    return sel.select_report_metadata(context=_context(file_name), profile=profile, header_items=items, filename=file_name)


def _corpus(per_profile: int = 120):
    rng = random.Random(1115)
    cases = []
    for profile_name, profile in PROFILES.items():
        for case_index in range(per_profile):
            file_name = rng.choice(
                (
                    "VTST1001_Panel_alpha_2024.04.11_02.PDF",
                    "VTST4015_2024.01.01_99.PDF",
                    "ABC00100_2024-01-04_0003.pdf",
                    "unparseable name.pdf",
                )
            )
            cases.append((profile_name, case_index, _build_items(rng, profile), file_name))
    return cases


# --- reference: the pre-change matching logic, kept verbatim and run with every cache bypassed -------


def _reference_label_lookup(profile, field_name):
    aliases = profile.label_aliases.get(field_name, ())
    exact_label = field_name.replace("_", " ").upper()
    lookup = {exact_label: "header_exact"}
    for alias in aliases:
        lookup[sel._normalize_label_text(alias)] = (
            "header_alias" if sel._normalize_label_text(alias) != exact_label else "header_exact"
        )
    return lookup


def _reference_match_label_at(row, index, profile):
    if index >= len(row):
        return None

    token_label = sel._normalize_label_text(row[index].text)
    best_match = None
    for field_name in profile.label_aliases:
        label_lookup = _reference_label_lookup(profile, field_name)
        if token_label in label_lookup:
            consumed = index + 1
            while consumed < len(row) and sel._is_label_separator(row[consumed].text):
                consumed += 1
            return field_name, label_lookup[token_label], row[index].text, consumed - index

        for label_text, source_type in label_lookup.items():
            words = sel._label_words(label_text)
            if len(words) <= 1:
                continue
            position = index
            matched_items = []
            for word in words:
                if position >= len(row):
                    matched_items = []
                    break
                if sel._normalize_label_text(row[position].text) != word:
                    matched_items = []
                    break
                matched_items.append(row[position])
                position += 1
            if not matched_items:
                continue
            while position < len(row) and sel._is_label_separator(row[position].text):
                matched_items.append(row[position])
                position += 1
            label_value = sel._collapse_spaces(" ".join(item.text for item in matched_items))
            consumed_count = position - index
            if best_match is None or consumed_count > best_match[3]:
                best_match = (field_name, source_type, label_value, consumed_count)

    return best_match


def _use_uncached_reference(patch):
    """Route the selector through the uncached pre-change logic (the 'index' handed around is the profile)."""
    patch.setattr(sel, "_normalize_label_text", sel._normalize_label_text.__wrapped__)
    patch.setattr(sel, "_label_words", sel._label_words.__wrapped__)
    patch.setattr(sel, "_label_index", lambda profile: profile)
    patch.setattr(sel, "_match_label_at", _reference_match_label_at)


def _run_corpus(cases):
    return [_select(PROFILES[profile_name], items, file_name) for profile_name, _case_index, items, file_name in cases]


def test_cached_selector_matches_uncached_reference_over_varied_synthetic_headers(monkeypatch):
    cases = _corpus()
    sel._build_label_index.cache_clear()
    sel._normalize_label_text.cache_clear()
    sel._label_words.cache_clear()
    cached_results = _run_corpus(cases)
    # Second pass runs fully warm, so a stale or mis-keyed entry would show up as a difference as well.
    warm_results = _run_corpus(cases)

    with monkeypatch.context() as patch:
        _use_uncached_reference(patch)
        reference_results = _run_corpus(cases)

    assert len(cached_results) == len(reference_results) == len(cases)
    for (profile_name, case_index, _items, _file_name), cached, warm, reference in zip(
        cases, cached_results, warm_results, reference_results
    ):
        where = f"{profile_name} case {case_index}"
        assert cached.metadata == reference.metadata, where
        assert cached.candidates == reference.candidates, where
        assert cached.metadata.warnings == reference.metadata.warnings, where
        assert warm == cached, where

    # The corpus has to be varied enough to mean something.
    candidates = [candidate for result in cached_results for candidate in result.candidates]
    source_types = {candidate.source_type for candidate in candidates}
    assert {"header_exact", "header_alias", "filename_candidate"} <= source_types
    assert len({candidate.field_name for candidate in candidates if candidate.source_type.startswith("header")}) >= 7
    assert any(result.metadata.warnings for result in cached_results)
    assert any(not result.metadata.warnings for result in cached_results)
    assert any(candidate.label_text and " " in candidate.label_text for candidate in candidates)
    assert len({result.metadata.template_variant for result in cached_results}) >= 2


def test_reference_really_bypasses_the_caches(monkeypatch):
    with monkeypatch.context() as patch:
        _use_uncached_reference(patch)
        assert not hasattr(sel._normalize_label_text, "cache_info")
        assert not hasattr(sel._label_words, "cache_info")
        assert sel._match_label_at is _reference_match_label_at
        result = _select(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, _sample_items())
    assert any(c.field_name == "part_name" and c.raw_value == "Panel alpha" for c in result.candidates)
    assert hasattr(sel._normalize_label_text, "cache_info")


def test_default_profile_ocr_drift_header_is_unchanged_by_caching():
    def item(text, x0, y0, x1, y1):
        return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "page_number": 1}

    items = [
        item("PARTNANE", 10, 10, 60, 16),
        item("WidgetAB123 1.0L", 70, 10, 150, 16),
        item("SER", 10, 40, 35, 46),
        item("NUNBER", 40, 40, 90, 46),
        item("VTST0174O8", 100, 40, 160, 46),
        item("MEASUREMENT NADE BY", 10, 70, 110, 76),
        item("LAB Operator A", 120, 70, 180, 76),
    ]
    first = _select(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, items)
    second = _select(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, items)
    assert first == second
    assert first.metadata.reference == "VTST017408"
    assert first.metadata.part_name == "Widget AB123 1.0L"
    assert first.metadata.operator_name == "LAB_OPERATOR_A"


# --- label index identity ---------------------------------------------------------------------------


def test_label_index_follows_alias_content_when_profiles_alternate_in_one_process():
    items = [
        {"text": "DATE", "x0": 10, "y0": 10, "x1": 40, "y1": 16},
        {"text": "2024.04.11", "x0": 50, "y0": 10, "x1": 100, "y1": 16},
    ]
    for _ in range(3):
        default_fields = {c.field_name for c in _select(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, items).candidates if c.source_type.startswith("header")}
        shifted_fields = {c.field_name for c in _select(SHIFTED_PROFILE, items).candidates if c.source_type.startswith("header")}
        assert default_fields == {"report_date"}
        assert shifted_fields == {"comment"}


def test_equal_alias_sets_share_one_index_and_different_alias_sets_do_not():
    sel._build_label_index.cache_clear()
    copy = replace(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, label_aliases=dict(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.label_aliases))
    assert sel._label_index(copy) is sel._label_index(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE)
    assert sel._label_index(ALT_PROFILE) is not sel._label_index(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE)
    assert sel._build_label_index.cache_info().currsize == 2


def test_label_index_notices_in_place_alias_changes():
    aliases = {name: tuple(values) for name, values in DEFAULT_CMM_PDF_HEADER_BOX_PROFILE.label_aliases.items()}
    profile = replace(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, label_aliases=aliases)
    items = [
        {"text": "BATCH", "x0": 10, "y0": 10, "x1": 40, "y1": 16},
        {"text": "Q7", "x0": 50, "y0": 10, "x1": 100, "y1": 16},
    ]
    assert not any(c.source_type.startswith("header") for c in _select(profile, items).candidates)
    aliases["comment"] = (*aliases["comment"], "BATCH")
    comment = [c for c in _select(profile, items).candidates if c.source_type.startswith("header")]
    assert [(c.field_name, c.raw_value) for c in comment] == [("comment", "Q7")]


def test_label_index_keeps_profile_order_semantics():
    index = sel._label_index(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE)
    for first_word, entries in index.multi_word.items():
        for _field_name, _source_type, words in entries:
            assert words[0] == first_word and len(words) > 1
    # ALT_PROFILE lists ZNACZNIK under reference and report_time: the earlier field in profile order wins.
    assert sel._label_index(ALT_PROFILE).exact["ZNACZNIK"][0] == "reference"


# --- guards against per-call rebuilding -------------------------------------------------------------


def _sample_items():
    return [
        {"text": "PART", "x0": 10, "y0": 10, "x1": 30, "y1": 16},
        {"text": "NAME", "x0": 40, "y0": 10, "x1": 60, "y1": 16},
        {"text": "Panel alpha", "x0": 70, "y0": 10, "x1": 150, "y1": 16},
        {"text": "DATE", "x0": 10, "y0": 20, "x1": 40, "y1": 26},
        {"text": "2024.04.11", "x0": 70, "y0": 20, "x1": 150, "y1": 26},
        {"text": "MEASUREMENT", "x0": 10, "y0": 30, "x1": 60, "y1": 36},
        {"text": "MADE", "x0": 62, "y0": 30, "x1": 80, "y1": 36},
        {"text": "BY", "x0": 82, "y0": 30, "x1": 90, "y1": 36},
        {"text": "Jane Doe", "x0": 100, "y0": 30, "x1": 150, "y1": 36},
    ]


def test_label_lookups_are_built_once_per_profile_not_once_per_call(monkeypatch):
    profile = DEFAULT_CMM_PDF_HEADER_BOX_PROFILE
    built: list[str] = []
    real_label_lookup = sel._label_lookup

    def counting_label_lookup(field_name, aliases):
        built.append(field_name)
        return real_label_lookup(field_name, aliases)

    monkeypatch.setattr(sel, "_label_lookup", counting_label_lookup)
    sel._build_label_index.cache_clear()
    items = _sample_items()

    for _ in range(25):
        _select(profile, items)

    # One lookup per field, regardless of how many reports were processed (it used to be hundreds per report).
    assert sorted(built) == sorted(profile.label_aliases)

    _select(replace(profile, label_aliases=dict(profile.label_aliases)), items)
    assert len(built) == len(profile.label_aliases), "an equal alias set must reuse the compiled index"

    _select(ALT_PROFILE, items)
    assert len(built) == len(profile.label_aliases) + len(ALT_PROFILE.label_aliases)


def test_warm_selector_does_not_renormalise_labels(monkeypatch):
    items = _sample_items()
    _select(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, items)  # warm every cache for this header

    canonicalised: list[str | None] = []
    real_canonicalize = sel.canonicalize_header_label

    def counting_canonicalize(value):
        canonicalised.append(value)
        return real_canonicalize(value)

    monkeypatch.setattr(sel, "canonicalize_header_label", counting_canonicalize)
    before = sel._normalize_label_text.cache_info()
    for _ in range(10):
        _select(DEFAULT_CMM_PDF_HEADER_BOX_PROFILE, items)
    after = sel._normalize_label_text.cache_info()

    assert canonicalised == []
    assert after.misses == before.misses
    assert after.hits > before.hits


def test_normalisation_caches_are_bounded():
    for cached in (sel._normalize_label_text, sel._label_words, sel._build_label_index):
        info = cached.cache_info()
        assert info.maxsize is not None and 0 < info.maxsize <= 65536

    maxsize = sel._label_words.cache_info().maxsize
    for number in range(maxsize + 50):
        sel._label_words(f"UNIQUE LABEL {number}")
    assert sel._label_words.cache_info().currsize <= maxsize
