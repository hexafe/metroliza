"""Qt-free state and merge rules for the pre-import metadata review step (#1100).

The review table is a transient, in-memory view of metadata that has been read
from reports *before* anything is written to the database.  This module owns:

* the per-report row state (``ReviewRow``) with fast-mode prefill, manual edits
  and explicit OCR choices protected from later automatic readings;
* the immutable ``ReportMetadataOverride`` that carries the confirmed values to
  the import (keyed by the import plan's occurrence id and source fingerprint);
* ``apply_metadata_override`` which turns an override into the selected
  metadata and the candidate rows persisted by the repository, keeping the
  detected values as unselected candidates and recording provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from metroliza.reports.report_metadata_models import (
    MetadataCandidate,
    MetadataSelectionResult,
    MetadataWarning,
    SAMPLE_NUMBER_PROJECTION_WARNING_CODE,
    USER_SOURCE_TYPE,
)
from metroliza.reports.report_metadata_normalizers import (
    is_missing_reference,
    normalize_comment,
    normalize_operator_name,
    normalize_part_name,
    normalize_reference,
    normalize_report_date,
    normalize_report_time,
    normalize_revision,
    normalize_sample_number,
)

# Editable columns of the review table, in display order.  ``reference`` is the
# part reference/number and ``part_name`` the part description: report_metadata
# has no separate "part number" column.  The last four fields are normally only
# produced by header OCR, so the table is where OCR visibly adds value.
REVIEW_FIELDS = (
    "reference",
    "part_name",
    "sample_number",
    "report_date",
    "report_time",
    "revision",
    "operator_name",
    "comment",
)
# Fields whose absence is flagged ("missing"). OCR-only fields are often
# legitimately blank, so they are never flagged.
CORE_FIELDS = ("reference", "part_name", "sample_number", "report_date")
FIELD_LABELS = {
    "reference": "Reference",
    "part_name": "Part name",
    "sample_number": "Sample no.",
    "report_date": "Date",
    "report_time": "Time",
    "revision": "Revision",
    "operator_name": "Operator",
    "comment": "Comment",
}
LOW_CONFIDENCE_THRESHOLD = 0.7

ORIGIN_DETECTED = "detected"
ORIGIN_OCR = "ocr"
ORIGIN_USER = "user"
OVERRIDE_ORIGINS = frozenset({ORIGIN_OCR, ORIGIN_USER})

OCR_REVIEW_SOURCE_TYPE = "ocr_review"
MANUAL_OVERRIDE_SOURCE = "metadata_review"
_FILENAME_SOURCE_TYPE = "filename_candidate"
_SAMPLE_KIND_BY_SOURCE = {
    "explicit_sample_number": "explicit_sample_number",
    "comment_derived": "derived_counter",
    "projected_from_stats_count": "stats_count",
    _FILENAME_SOURCE_TYPE: "filename_tail",
}
SAMPLE_NUMBER_COMMENT_WARNING_CODE = "sample_number_derived_from_comment"
_SAMPLE_SOURCE_WARNINGS = {
    "projected_from_stats_count": (
        SAMPLE_NUMBER_PROJECTION_WARNING_CODE, "warning", "Sample number was projected from stats count.",
    ),
    "comment_derived": (
        SAMPLE_NUMBER_COMMENT_WARNING_CODE, "info", "Sample number was derived from comment.",
    ),
}

ROW_PENDING = "pending"
ROW_READY = "ready"
ROW_FAILED = "failed"
ROW_CHANGED = "changed"
ROW_UNSUPPORTED = "unsupported"

OCR_NONE = "none"
OCR_DONE = "done"
OCR_FAILED = "failed"


def normalize_review_value(field_name: str, text) -> tuple[str | None, str | None]:
    """Normalize user text for ``field_name``; return ``(value, error)``."""

    if field_name not in REVIEW_FIELDS:
        raise ValueError(f"Unsupported review field: {field_name}")
    if text is None or not str(text).strip():
        return None, None
    if field_name == "reference":
        return normalize_reference(text), None
    if field_name == "part_name":
        return normalize_part_name(text), None
    if field_name == "sample_number":
        return normalize_sample_number(text), None
    if field_name == "report_date":
        value = normalize_report_date(text)
        return (value, None) if value else (None, "Enter a valid date, for example 2024-05-06.")
    if field_name == "report_time":
        value = normalize_report_time(text)
        return (value, None) if value else (None, "Enter a valid time, for example 14:30.")
    if field_name == "revision":
        return normalize_revision(text), None
    if field_name == "operator_name":
        return normalize_operator_name(text), None
    return normalize_comment(text), None


def is_missing_value(field_name: str, value) -> bool:
    """Missing-value rule for one field; references use the shared definition."""

    if field_name == "reference":
        return is_missing_reference(value)
    return value is None or not str(value).strip()


# --------------------------------------------------------------------------
# Override carried from the review step to the import.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldOverride:
    """One confirmed field value, with exact evidence for an explicit OCR choice."""

    field_name: str
    value: str | None
    origin: str
    ocr_candidate: MetadataCandidate | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.field_name not in REVIEW_FIELDS:
            raise ValueError(f"Unsupported review field: {self.field_name}")
        if self.origin not in OVERRIDE_ORIGINS:
            raise ValueError(f"Unsupported override origin: {self.origin}")
        if self.value is None and self.origin != ORIGIN_USER:
            raise ValueError("Only a user override may clear a field.")
        if self.ocr_candidate is not None and (
            self.origin != ORIGIN_OCR
            or not _backs_ocr_choice(self.ocr_candidate, self.field_name, self.value)
        ):
            raise ValueError("The reviewed OCR candidate does not match the field override.")


@dataclass(frozen=True)
class ReportMetadataOverride:
    """Confirmed metadata for one reviewed report.

    ``occurrence_id`` and ``fingerprint`` are the import plan's stable file
    identity for the report; display names are never used as keys.
    ``ocr_candidates`` are the candidates seen by the review's OCR run; they are
    persisted as detected (unselected) candidates unless one of them backs an
    ``ocr`` field override.
    """

    occurrence_id: str
    fingerprint: str
    fields: tuple[FieldOverride, ...] = ()
    ocr_candidates: tuple[MetadataCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not self.occurrence_id or not self.fingerprint:
            raise ValueError("A metadata override needs an occurrence id and a fingerprint.")
        if not isinstance(self.fields, tuple) or not isinstance(self.ocr_candidates, tuple):
            raise ValueError("Metadata override fields and candidates must be tuples.")
        names = [item.field_name for item in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("Metadata override contains a field more than once.")

    @property
    def is_empty(self) -> bool:
        return not self.fields and not self.ocr_candidates


def _backs_ocr_choice(candidate: MetadataCandidate, field_name: str, value: str | None) -> bool:
    return (
        isinstance(candidate, MetadataCandidate)
        and value is not None
        and candidate.selected
        and candidate.field_name == field_name
        and candidate.normalized_value == value
        and candidate.source_type not in (_FILENAME_SOURCE_TYPE, USER_SOURCE_TYPE)
    )


def accepted_ocr_fields(metadata_json: dict) -> frozenset[str]:
    """Read the persisted OCR choices, including the original v1 review format."""

    review = metadata_json.get("metadata_review")
    if not isinstance(review, dict) or type(review.get("version")) is not int or review["version"] != 1:
        return frozenset()
    # Older review receipts did not distinguish explicitly chosen OCR from prefill.
    fields = review.get("accepted_ocr_fields", review.get("ocr_fields"))
    if not isinstance(fields, list):
        return frozenset()
    return frozenset(name for name in fields if type(name) is str and name in REVIEW_FIELDS)


def sample_number_source_warnings(warnings, source):
    """Align classification warnings with the stored sample source."""

    expected = _SAMPLE_SOURCE_WARNINGS.get(source) if isinstance(source, str) else None
    source_codes = (SAMPLE_NUMBER_PROJECTION_WARNING_CODE, SAMPLE_NUMBER_COMMENT_WARNING_CODE)
    result = []
    found = False
    for warning in warnings:
        code = warning.get("code") if isinstance(warning, dict) else getattr(warning, "code", None)
        if code not in source_codes:
            result.append(warning)
        elif expected is not None and code == expected[0] and not found:
            result.append(warning)
            found = True
    if expected is not None and not found:
        code, severity, message = expected
        result.append(MetadataWarning(code, "sample_number", severity, message))
    return tuple(result)


def _candidate_key(candidate: MetadataCandidate) -> tuple:
    return (
        candidate.field_name,
        candidate.source_type,
        candidate.rule_id,
        candidate.raw_value,
        candidate.normalized_value,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _select_ocr_override_candidate(candidates: list[MetadataCandidate], item: FieldOverride) -> str:
    reviewed = item.ocr_candidate
    if reviewed is not None:
        # Preserve the exact chosen evidence alongside fresh detections of the same value.
        unselected = replace(reviewed, selected=False)
        for index, candidate in enumerate(candidates):
            if candidate == unselected:
                candidates[index] = reviewed
                break
        else:
            candidates.append(reviewed)
        return reviewed.source_type

    backing = [
        (index, candidate)
        for index, candidate in enumerate(candidates)
        if candidate.field_name == item.field_name
        and candidate.normalized_value == item.value
        and candidate.source_type not in (_FILENAME_SOURCE_TYPE, USER_SOURCE_TYPE)
    ]
    if backing:
        index, candidate = max(backing, key=lambda pair: pair[1].confidence)
        candidates[index] = replace(candidate, selected=True)
        return candidate.source_type

    candidates.append(
        MetadataCandidate(
            field_name=item.field_name,
            raw_value=item.value,
            normalized_value=item.value,
            source_type=OCR_REVIEW_SOURCE_TYPE,
            source_detail=MANUAL_OVERRIDE_SOURCE,
            page_number=None,
            region_name=MANUAL_OVERRIDE_SOURCE,
            label_text=None,
            rule_id=f"ocr_review:{item.field_name}",
            confidence=0.5,
            evidence_text=None,
            selected=True,
        )
    )
    return OCR_REVIEW_SOURCE_TYPE


def apply_metadata_override(
    selection: MetadataSelectionResult,
    override: ReportMetadataOverride,
    *,
    applied_at: str | None = None,
) -> MetadataSelectionResult:
    """Apply confirmed values to a freshly extracted selection result.

    Detected candidates are kept (unselected where a confirmed value replaces
    them), ``reference_raw`` keeps the detected raw text, user values add a
    selected ``user_manual`` candidate, and ``metadata_json`` records the
    manual overrides (so later OCR enrichment will not overwrite them) and the
    values that were detected before the override.
    """

    metadata = selection.metadata
    stamp = applied_at or _utc_now()
    candidates = list(selection.candidates)
    seen = {_candidate_key(candidate) for candidate in candidates}
    for candidate in override.ocr_candidates:
        if _candidate_key(candidate) not in seen:
            seen.add(_candidate_key(candidate))
            candidates.append(replace(candidate, selected=False))

    metadata_json = dict(metadata.metadata_json or {})
    field_sources = dict(metadata_json.get("field_sources") or {})
    manual_overrides = dict(metadata_json.get("manual_overrides") or {})
    warnings = metadata.warnings
    values: dict[str, object] = {}
    detected_values: dict[str, object] = {}
    edited_fields: list[str] = []
    ocr_fields: list[str] = []

    for item in override.fields:
        name = item.field_name
        detected_values[name] = getattr(metadata, name)
        candidates = [
            replace(candidate, selected=False) if candidate.field_name == name else candidate
            for candidate in candidates
        ]
        values[name] = item.value
        source_type = None
        if item.origin == ORIGIN_USER:
            edited_fields.append(name)
            source_type = USER_SOURCE_TYPE
            if item.value is not None:
                candidates.append(
                    MetadataCandidate.from_manual_edit(
                        name, item.value, source_detail=MANUAL_OVERRIDE_SOURCE,
                    )
                )
            manual_overrides[name] = {
                "value": item.value,
                "source": MANUAL_OVERRIDE_SOURCE,
                "updated_at": stamp,
            }
        else:
            ocr_fields.append(name)
            source_type = _select_ocr_override_candidate(candidates, item)
        field_sources[name] = source_type
        if name == "sample_number":
            values["sample_number_kind"] = (
                _SAMPLE_KIND_BY_SOURCE.get(source_type, "unknown")
                if item.origin == ORIGIN_OCR and item.value is not None
                else "unknown"
            )
            metadata_json["sample_number_provenance"] = source_type
            warnings = sample_number_source_warnings(warnings, source_type)

    metadata_json["field_sources"] = field_sources
    if manual_overrides:
        metadata_json["manual_overrides"] = manual_overrides
    metadata_json["metadata_review"] = {
        "version": 1,
        "applied_at": stamp,
        "edited_fields": sorted(edited_fields),
        "ocr_fields": sorted(ocr_fields),
        "accepted_ocr_fields": sorted(item.field_name for item in override.fields if item.ocr_candidate is not None),
        "ocr_run": bool(override.ocr_candidates) or any(item.ocr_candidate is not None for item in override.fields),
        "detected_values": detected_values,
    }
    return MetadataSelectionResult(
        metadata=replace(metadata, metadata_json=metadata_json, warnings=warnings, **values),
        candidates=tuple(candidates),
    )


# --------------------------------------------------------------------------
# Row state.
# --------------------------------------------------------------------------


@dataclass
class ReviewCell:
    """Detected metadata, an optional manual edit, and the current OCR review state."""

    auto_value: str | None = None
    auto_origin: str = ORIGIN_DETECTED
    auto_source: str | None = None
    auto_confidence: float | None = None
    user_set: bool = False
    user_value: str | None = None
    ocr_suggestion: str | None = None
    accepted_ocr: MetadataCandidate | None = field(default=None, repr=False)

    @property
    def value(self) -> str | None:
        return self.user_value if self.user_set else self.auto_value

    @property
    def origin(self) -> str:
        return ORIGIN_USER if self.user_set else self.auto_origin

    @property
    def source(self) -> str | None:
        return USER_SOURCE_TYPE if self.user_set else self.auto_source

    @property
    def confidence(self) -> float | None:
        return 1.0 if self.user_set else self.auto_confidence


def selection_cell_values(
    selection: MetadataSelectionResult,
) -> dict[str, tuple[str | None, str | None, float | None]]:
    """Return ``{field: (value, source_type, confidence)}`` for the review fields."""

    metadata = selection.metadata
    json_sources = (metadata.metadata_json or {}).get("field_sources") or {}
    selected = {
        candidate.field_name: candidate for candidate in selection.candidates if candidate.selected
    }
    result: dict[str, tuple[str | None, str | None, float | None]] = {}
    for name in REVIEW_FIELDS:
        raw = getattr(metadata, name, None)
        value = str(raw).strip() if raw is not None and str(raw).strip() else None
        candidate = selected.get(name)
        source = json_sources.get(name) or (candidate.source_type if candidate else None)
        confidence = candidate.confidence if candidate is not None else None
        result[name] = (value, source, confidence)
    return result


@dataclass
class ReviewRow:
    """Editable review state for one READY report, keyed by plan identity."""

    occurrence_id: str
    fingerprint: str
    display_name: str
    parser_id: str | None = None
    cells: dict[str, ReviewCell] = field(
        default_factory=lambda: {name: ReviewCell() for name in REVIEW_FIELDS}
    )
    state: str = ROW_PENDING
    note: str = ""
    warnings: tuple[tuple[str, str], ...] = ()
    metadata_confidence: float | None = None
    ocr_state: str = OCR_NONE
    ocr_note: str = ""
    ocr_candidates: tuple[MetadataCandidate, ...] = ()
    # Every candidate of the fast reading, kept so the details pane can list the
    # alternatives to the selected value.  Never persisted by ``to_override``.
    fast_candidates: tuple[MetadataCandidate, ...] = ()

    # -- state -------------------------------------------------------------

    @property
    def editable(self) -> bool:
        return self.state not in (ROW_CHANGED, ROW_UNSUPPORTED)

    def value(self, field_name: str) -> str | None:
        return self.cells[field_name].value

    def is_missing(self, field_name: str) -> bool:
        return field_name in CORE_FIELDS and is_missing_value(field_name, self.value(field_name))

    @property
    def missing_fields(self) -> tuple[str, ...]:
        if not self.editable:
            return ()
        return tuple(name for name in CORE_FIELDS if self.is_missing(name))

    @property
    def reference_missing(self) -> bool:
        return self.editable and is_missing_reference(self.value("reference"))

    def is_low_confidence(self, field_name: str) -> bool:
        cell = self.cells[field_name]
        if field_name not in CORE_FIELDS or cell.origin == ORIGIN_USER or not cell.value:
            return False
        return cell.confidence is not None and cell.confidence < LOW_CONFIDENCE_THRESHOLD

    @property
    def low_confidence_fields(self) -> tuple[str, ...]:
        if not self.editable:
            return ()
        return tuple(name for name in CORE_FIELDS if self.is_low_confidence(name))

    @property
    def needs_attention(self) -> bool:
        return bool(self.missing_fields or self.low_confidence_fields) or self.state in (
            ROW_FAILED,
            ROW_CHANGED,
            ROW_UNSUPPORTED,
        )

    @property
    def edited_fields(self) -> tuple[str, ...]:
        return tuple(name for name in REVIEW_FIELDS if self.cells[name].user_set)

    @property
    def conflict_fields(self) -> tuple[str, ...]:
        return tuple(name for name in REVIEW_FIELDS if self.cells[name].ocr_suggestion is not None)

    # -- readings ----------------------------------------------------------

    def apply_fast(self, selection: MetadataSelectionResult) -> None:
        """Prefill from fast (light) metadata; never replaces user or OCR values."""

        self.state = ROW_READY
        self.note = ""
        self.fast_candidates = tuple(selection.candidates)
        for name, (value, source, confidence) in selection_cell_values(selection).items():
            cell = self.cells[name]
            if cell.auto_origin == ORIGIN_OCR:
                continue
            cell.auto_value, cell.auto_source, cell.auto_confidence = value, source, confidence
            cell.auto_origin = ORIGIN_DETECTED
        if self.ocr_state != OCR_DONE:
            self.warnings = _warning_pairs(selection)
            self.metadata_confidence = selection.metadata.metadata_confidence

    def mark_failed(self, note: str, *, state: str = ROW_FAILED) -> None:
        self.state = state
        self.note = note

    def apply_ocr(self, selection: MetadataSelectionResult, *, note: str = "") -> tuple[str, ...]:
        """Merge an OCR run, protecting manual values and previously accepted OCR.

        Returns the fields whose displayed value changed.
        """

        changed: list[str] = []
        self.ocr_state = OCR_DONE
        self.ocr_note = note
        self.ocr_candidates = tuple(selection.candidates)
        native_header = (selection.metadata.metadata_json or {}).get("header_extraction_mode") in ("words", "none")
        for name, (value, source, confidence) in selection_cell_values(selection).items():
            cell = self.cells[name]
            cell.ocr_suggestion = None
            if value is None:
                continue
            if cell.user_set or cell.accepted_ocr is not None:
                if not native_header and value != cell.value and self._ocr_candidate(name, value) is not None:
                    cell.ocr_suggestion = value
                continue
            if source == _FILENAME_SOURCE_TYPE or source is None:
                continue  # nothing OCR-specific; keep the fast detection as is
            if value == cell.auto_value and cell.auto_origin == ORIGIN_DETECTED:
                continue
            cell.auto_value, cell.auto_source = value, source
            cell.auto_confidence, cell.auto_origin = confidence, ORIGIN_OCR
            changed.append(name)
        if self.state in (ROW_PENDING, ROW_FAILED):
            self.state = ROW_READY
        self.warnings = _warning_pairs(selection)
        self.metadata_confidence = selection.metadata.metadata_confidence
        return tuple(changed)

    def mark_ocr_failed(self, note: str) -> None:
        self.ocr_state = OCR_FAILED
        self.ocr_note = note

    # -- user edits --------------------------------------------------------

    def _ocr_candidate(self, field_name: str, value: str | None) -> MetadataCandidate | None:
        return next(
            (candidate for candidate in self.ocr_candidates if _backs_ocr_choice(candidate, field_name, value)),
            None,
        )

    def suggested_ocr_candidate(self, field_name: str) -> MetadataCandidate | None:
        """Return the candidate that can be acted on in the current review."""

        if self.state != ROW_READY or field_name not in self.cells:
            return None
        suggestion = self.cells[field_name].ocr_suggestion
        return self._ocr_candidate(field_name, suggestion) if suggestion is not None else None

    def set_user_value(self, field_name: str, text) -> tuple[bool, str | None]:
        """Set a manual value. Returns ``(accepted, error)``."""

        if not self.editable:
            return False, "This report cannot be edited."
        value, error = normalize_review_value(field_name, text)
        if error:
            return False, error
        cell = self.cells[field_name]
        if value == cell.auto_value:
            cell.user_set, cell.user_value = False, None
        else:
            cell.user_set, cell.user_value = True, value
        if cell.ocr_suggestion == value:
            cell.ocr_suggestion = None
        return True, None

    def reset_user_edits(self, fields=None) -> int:
        count = 0
        for name in fields or REVIEW_FIELDS:
            cell = self.cells[name]
            if cell.user_set:
                cell.user_set, cell.user_value = False, None
                count += 1
            cell.ocr_suggestion = None
        return count

    def accept_ocr_suggestions(self, fields=None) -> tuple[str, ...]:
        """Replace chosen cells with their backed OCR suggestions and protect them."""

        accepted = []
        reviewed_fields = self.conflict_fields if fields is None else fields
        for name in reviewed_fields:
            candidate = self.suggested_ocr_candidate(name)
            if candidate is None:
                continue
            cell = self.cells[name]
            cell.accepted_ocr = candidate
            cell.auto_value, cell.auto_origin = candidate.normalized_value, ORIGIN_OCR
            cell.auto_source, cell.auto_confidence = candidate.source_type, candidate.confidence
            cell.user_set, cell.user_value, cell.ocr_suggestion = False, None, None
            accepted.append(name)
        return tuple(accepted)

    def dismiss_ocr_suggestion(self, field_name: str) -> bool:
        """Keep the current value and dismiss this suggestion until a new read."""

        if self.suggested_ocr_candidate(field_name) is None:
            return False
        self.cells[field_name].ocr_suggestion = None
        return True

    # -- import hand-off ---------------------------------------------------

    def to_override(self) -> ReportMetadataOverride | None:
        """Return the confirmed values for import, or ``None`` if nothing differs."""

        if not self.editable:
            return None
        fields = []
        for name in REVIEW_FIELDS:
            cell = self.cells[name]
            if cell.user_set:
                fields.append(FieldOverride(name, cell.user_value, ORIGIN_USER))
            elif cell.auto_origin == ORIGIN_OCR and cell.auto_value is not None:
                fields.append(FieldOverride(name, cell.auto_value, ORIGIN_OCR, ocr_candidate=cell.accepted_ocr))
        override = ReportMetadataOverride(
            occurrence_id=self.occurrence_id,
            fingerprint=self.fingerprint,
            fields=tuple(fields),
            ocr_candidates=self.ocr_candidates if self.ocr_state == OCR_DONE else (),
        )
        return None if override.is_empty else override


def _warning_pairs(selection: MetadataSelectionResult) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(getattr(warning, "severity", "warning")), str(getattr(warning, "message", "")))
        for warning in (selection.metadata.warnings or ())
    )


def apply_value_to_rows(rows, field_name: str, text) -> tuple[int, str | None]:
    """Apply one manual value to many rows; returns ``(rows_changed, error)``."""

    value, error = normalize_review_value(field_name, text)
    if error:
        return 0, error
    changed = 0
    for row in rows:
        before = row.cells[field_name].value
        accepted, _error = row.set_user_value(field_name, value)
        if accepted and row.cells[field_name].value != before:
            changed += 1
    return changed, None


def build_overrides(rows) -> tuple[ReportMetadataOverride, ...]:
    """Collect import overrides for rows, in a deterministic order."""

    overrides = (row.to_override() for row in rows)
    return tuple(
        sorted((item for item in overrides if item is not None), key=lambda item: item.occurrence_id)
    )


__all__ = [
    "CORE_FIELDS",
    "FIELD_LABELS",
    "FieldOverride",
    "LOW_CONFIDENCE_THRESHOLD",
    "OCR_REVIEW_SOURCE_TYPE",
    "ORIGIN_DETECTED",
    "ORIGIN_OCR",
    "ORIGIN_USER",
    "REVIEW_FIELDS",
    "ReportMetadataOverride",
    "ReviewCell",
    "ReviewRow",
    "USER_SOURCE_TYPE",
    "apply_metadata_override",
    "apply_value_to_rows",
    "build_overrides",
    "is_missing_value",
    "normalize_review_value",
    "selection_cell_values",
]
