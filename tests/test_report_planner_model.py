import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - environment-dependent import
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    PYQT_IMPORT_ERROR is not None,
    reason=f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}",
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _review():
    from metroliza.parsing.preflight import (
        ParserCandidateEvidence,
        ParseFilePreflight,
        ParsePreflightResult,
        ParsePreflightStatus,
    )

    return ParsePreflightResult(
        source_path="/operator/reports.zip",
        database_path="/operator/reports.sqlite3",
        metadata_parsing_mode="light",
        files=(
            ParseFilePreflight(
                display_name="archive/A-ready.pdf",
                source_path="/tmp/extracted/private/A-ready.pdf",
                status=ParsePreflightStatus.READY,
                source_format="pdf",
                fingerprint="sha256:" + "a" * 64,
                parser_id="cmm",
                confidence=93,
                registry_generation_id=1,
                reason_codes=("strong_cmm_marker",),
                candidates=(ParserCandidateEvidence(
                    parser_id="cmm",
                    confidence=93,
                    can_parse=True,
                    outcome="match",
                    reasons=("strong_cmm_marker",),
                    warnings=("untrusted warning /tmp/private",),
                ),),
                diagnostic_detail="raw parser output must not reach the model view",
                occurrence_id="archive/A-ready.pdf",
            ),
            ParseFilePreflight(
                display_name="archive/B-duplicate.pdf",
                source_path="/tmp/extracted/private/B-duplicate.pdf",
                status=ParsePreflightStatus.DUPLICATE,
                source_format="pdf",
                fingerprint="sha256:duplicate-b",
                parser_id="cmm",
                confidence=88,
                registry_generation_id=1,
                reason_codes=("duplicate_in_selected_source",),
                occurrence_id="archive/B-duplicate.pdf",
            ),
            ParseFilePreflight(
                display_name="archive/C-unknown.pdf",
                source_path="/tmp/extracted/private/C-unknown.pdf",
                status=ParsePreflightStatus.UNSUPPORTED,
                source_format="pdf",
                fingerprint=None,
                parser_id="supplier.profile",
                confidence=None,
                reason_codes=("unknown_untrusted_reason",),
                diagnostic_detail="do not disclose /tmp/extracted/private/C-unknown.pdf",
                occurrence_id="archive/C-unknown.pdf",
            ),
        ),
    )


def test_fresh_review_selects_only_ready_and_keeps_duplicate_uncheckable():
    from metroliza.ui.report_planner_model import ReportPlannerModel

    model = ReportPlannerModel()
    emissions = []
    model.selection_changed.connect(lambda: emissions.append(model.selected_ids))
    model.set_review(_review())

    assert model.valid
    assert model.selected_ids == ("archive/A-ready.pdf",)
    assert model.counts == {
        "selected": 1, "ready": 1, "excluded": 2, "attention": 3, "total": 3,
    }
    duplicate = model.index(1, model.CHECKBOX_COLUMN)
    assert not model.flags(duplicate) & Qt.ItemFlag.ItemIsUserCheckable
    assert not model.setData(duplicate, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.selected_ids == ("archive/A-ready.pdf",)
    assert emissions[-1] == ("archive/A-ready.pdf",)


def test_selection_is_source_owned_across_proxy_filter_and_sort():
    from metroliza.ui.report_planner_model import ReportPlannerFilterModel, ReportPlannerModel

    model = ReportPlannerModel()
    model.set_review(_review())
    proxy = ReportPlannerFilterModel()
    proxy.setSourceModel(model)

    model.clear_selection()
    model.setData(
        model.index(0, model.CHECKBOX_COLUMN),
        Qt.CheckState.Checked,
        Qt.ItemDataRole.CheckStateRole,
    )
    proxy.set_text_filter("duplicate")
    proxy.sort(model.LOCATION_COLUMN, Qt.SortOrder.DescendingOrder)

    assert proxy.rowCount() == 1
    assert model.selected_ids == ("archive/A-ready.pdf",)
    model.select_all_ready()
    assert model.selected_ids == ("archive/A-ready.pdf",)
    assert proxy.data(proxy.index(0, model.LOCATION_COLUMN)) == "archive/B-duplicate.pdf"


def test_model_presentation_never_uses_source_paths_or_raw_diagnostics():
    from metroliza.ui.report_planner_model import ReportPlannerModel

    model = ReportPlannerModel()
    model.set_review(_review())

    rendered = "\n".join(
        str(model.data(model.index(row, column)) or "")
        for row in range(model.rowCount())
        for column in range(model.columnCount())
    )
    assert "archive/A-ready.pdf" in rendered
    assert "/tmp/extracted" not in rendered
    assert "raw parser output" not in rendered
    assert "supplier.profile" in rendered
    assert "unknown_untrusted_reason" not in rendered
    assert "duplicate_in_selected_source" in rendered
    assert model.parser_ids == ("cmm", "supplier.profile")
    assert "/tmp/extracted" not in model.details_text(0)
    assert "raw parser output" not in model.details_text(0)
    assert "untrusted warning" not in model.details_text(0)
    assert "Digest: sha256:aaaaaaaaaaaa..." in model.details_text(0)
    assert "Candidate: cmm · match · confidence 93" in model.details_text(0)
    assert "warnings review_warning" in model.details_text(0)
    assert "this row is excluded from the planner import" in model.details_text(1)


def test_filters_use_safe_presentation_fields_and_attention_status():
    from metroliza.ui.report_planner_model import ReportPlannerFilterModel, ReportPlannerModel

    model = ReportPlannerModel()
    model.set_review(_review())
    proxy = ReportPlannerFilterModel()
    proxy.setSourceModel(model)

    proxy.set_status_filter("duplicate")
    assert proxy.rowCount() == 1
    proxy.set_status_filter("")
    proxy.set_parser_filter("cmm")
    assert proxy.rowCount() == 2
    proxy.set_parser_filter("supplier.profile")
    assert proxy.rowCount() == 1
    proxy.set_parser_filter("")
    proxy.set_text_filter("/tmp/extracted")
    assert proxy.rowCount() == 0
    proxy.set_text_filter("")
    proxy.set_attention_only(True)
    assert proxy.rowCount() == 3


def test_invalidate_drops_review_and_selection():
    from metroliza.ui.report_planner_model import ReportPlannerModel

    model = ReportPlannerModel()
    model.set_review(_review())
    model.invalidate()

    assert not model.valid
    assert model.rowCount() == 0
    assert model.selected_ids == ()
    assert model.counts == {
        "selected": 0, "ready": 0, "excluded": 0, "attention": 0, "total": 0,
    }
    assert model.item_at(0) is None


def test_incomplete_or_nonunique_ready_evidence_is_not_selectable():
    from dataclasses import replace

    from metroliza.ui.report_planner_model import ReportPlannerModel

    review = _review()
    incomplete = replace(review.files[0], fingerprint=None)
    duplicate_identity = replace(review.files[1], status=review.files[0].status,
                                 occurrence_id=review.files[0].occurrence_id)
    model = ReportPlannerModel()
    model.set_review(replace(review, files=(incomplete, duplicate_identity)))

    assert model.selected_ids == ()
    for row in range(model.rowCount()):
        index = model.index(row, model.CHECKBOX_COLUMN)
        assert not model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
        assert not model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)


def test_proxy_integer_qt_roles_expose_identity_and_checkbox_state():
    from metroliza.ui.report_planner_model import ReportPlannerFilterModel, ReportPlannerModel

    model = ReportPlannerModel()
    model.set_review(_review())
    proxy = ReportPlannerFilterModel()
    proxy.setSourceModel(model)
    index = proxy.index(0, 0)
    assert proxy.data(index, Qt.ItemDataRole.UserRole.value) == "archive/A-ready.pdf"
    assert proxy.data(index, Qt.ItemDataRole.CheckStateRole.value) in (
        Qt.CheckState.Checked, Qt.CheckState.Checked.value,
    )
    assert proxy.setData(index, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole.value)
    assert not model.selected_ids


def test_candidate_outcome_never_renders_raw_diagnostic_content():
    from dataclasses import replace
    from metroliza.ui.report_planner_model import ReportPlannerModel

    review = _review()
    candidate = replace(review.files[0].candidates[0], outcome="CONFIDENTIAL report text")
    row = replace(review.files[0], candidates=(candidate,))
    model = ReportPlannerModel()
    model.set_review(replace(review, files=(row,)))
    assert "CONFIDENTIAL" not in model.details_text(0)
    assert "unavailable" in model.details_text(0)


def test_reason_sanitizer_keeps_known_cmm_and_factory_codes_without_raw_exception_text():
    from dataclasses import replace

    from metroliza.ui.report_planner_model import ReportPlannerModel, safe_review_detail

    review = _review()
    candidate = replace(
        review.files[0].candidates[0],
        reasons=(
            "pdf_extension",
            "partial_cmm_markers",
            "nominal_marker",
            "tolerance_marker",
            "measured_marker",
            "deviation_marker",
            "out_of_tolerance_marker",
            "bonus_marker",
            "probe_exception",
            "detector_invalid_probe_result",
            "pdf_backend_text_probe_failed:RuntimeError: /private/report.pdf",
        ),
        warnings=("CMM probe exploded at /private/report.pdf: secret",),
    )
    item = replace(
        review.files[0],
        reason_codes=candidate.reasons,
        candidates=(candidate,),
        diagnostic_detail="RuntimeError: secret content at /private/report.pdf",
    )
    model = ReportPlannerModel()
    model.set_review(replace(review, files=(item,)))

    detail = safe_review_detail(item)
    for known in (
        "pdf_extension",
        "partial_cmm_markers",
        "nominal_marker",
        "tolerance_marker",
        "measured_marker",
        "deviation_marker",
        "out_of_tolerance_marker",
        "bonus_marker",
        "probe_exception",
        "detector_invalid_probe_result",
    ):
        assert known in detail
    assert "review_reason_unavailable" in detail
    rendered = model.details_text(0)
    assert "review_reason_unavailable" in rendered
    assert "review_warning" in rendered
    assert "/private/report.pdf" not in rendered
    assert "secret content" not in rendered
