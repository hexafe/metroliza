"""Deterministic stand-ins for the metadata reader used by the planner UI tests (#1100).

The fake follows ``MetadataReviewReader.read``: it reports one ``MetadataReading``
per occurrence, honours ``should_cancel`` between reports and can be held back
by a gate so a test controls when a worker is "running".  It reads no files and
never opens a database.
"""

from __future__ import annotations

from threading import Event
import time

from metroliza.parsing.metadata_review import (
    MODE_OCR,
    NOTE_FAILED,
    NOTE_SOURCE_CHANGED,
    NOTE_UNSUPPORTED,
    READING_OK,
    MetadataReadSummary,
    MetadataReading,
)
from metroliza.parsing.preflight import (
    ParseFilePreflight,
    ParsePreflightResult,
    ParsePreflightStatus,
)
from metroliza.parsing import report_parser_factory
from metroliza.reports.report_metadata_models import (
    CanonicalReportMetadata,
    MetadataCandidate,
    MetadataSelectionResult,
)
from metroliza.reports.report_metadata_review import (
    REVIEW_FIELDS,
    ROW_CHANGED,
    ROW_FAILED,
    ROW_UNSUPPORTED,
)

HEADER = "header_exact"
FILE_NAME = "filename_candidate"


def make_selection(values: dict, *, confidence: float = 0.99) -> MetadataSelectionResult:
    """Build a selection; ``values`` maps field to ``value`` or ``(value, source, confidence)``."""

    fields: dict[str, object] = {name: None for name in REVIEW_FIELDS}
    sources: dict[str, str] = {}
    candidates = []
    for name, spec in values.items():
        value, source, level = spec if isinstance(spec, tuple) else (spec, HEADER, confidence)
        fields[name] = value
        sources[name] = source
        candidates.append(
            MetadataCandidate(
                field_name=name, raw_value=value, normalized_value=value, source_type=source,
                source_detail=None, page_number=1, region_name=None, label_text=None,
                rule_id=f"fake:{name}", confidence=level, evidence_text=None, selected=True,
            )
        )
    metadata = CanonicalReportMetadata(
        parser_id="cmm", template_family="fake", template_variant=None, metadata_confidence=0.9,
        reference=fields["reference"], reference_raw=fields["reference"],
        report_date=fields["report_date"], report_time=fields["report_time"],
        part_name=fields["part_name"], revision=fields["revision"],
        sample_number=fields["sample_number"], sample_number_kind="unknown", stats_count_raw=None,
        stats_count_int=None, operator_name=fields["operator_name"], comment=fields["comment"],
        page_count=1, metadata_json={"field_sources": sources}, warnings=(),
    )
    return MetadataSelectionResult(metadata=metadata, candidates=tuple(candidates))


class FakeMetadataReader:
    """Reader double.

    ``fast``/``ocr`` map a display name to the values of the reading; names in
    ``statuses`` produce a failed/changed/unsupported reading.  ``gate`` (an
    ``Event``) blocks each report until set or until the batch is cancelled;
    ``blocker`` blocks without looking at cancellation (a slow single report).
    """

    def __init__(self, preflight: ParsePreflightResult, *, fast=None, ocr=None, statuses=None,
                 gate=None, blocker=None):
        self.preflight = preflight
        self.blocker = blocker
        self.fast = fast or {}
        self.ocr = ocr or {}
        self.statuses = statuses or {}
        self.gate = gate
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.read_ids: list[tuple[str, str]] = []
        self.cancelled_seen = Event()
        self.started = Event()
        self._items = {item.stable_occurrence_id: item for item in preflight.files}

    def read(self, occurrence_ids, *, mode, should_cancel=lambda: False, on_reading=None, on_progress=None):
        ordered = [occ for occ in dict.fromkeys(occurrence_ids) if occ in self._items]
        self.calls.append((mode, tuple(ordered)))
        self.started.set()
        done = failed = 0
        for position, occurrence_id in enumerate(ordered, start=1):
            if self.gate is not None:
                while not self.gate.is_set() and not should_cancel():
                    time.sleep(0.005)
            if self.blocker is not None:
                self.blocker.wait(15)  # not cancel-aware: a long single report
            if should_cancel():
                self.cancelled_seen.set()
                break
            name = self._items[occurrence_id].display_name
            self.read_ids.append((mode, occurrence_id))
            status = self.statuses.get(name, READING_OK)
            if status != READING_OK:
                failed += 1
                note = {ROW_CHANGED: NOTE_SOURCE_CHANGED, ROW_UNSUPPORTED: NOTE_UNSUPPORTED}.get(status, NOTE_FAILED)
                reading = MetadataReading(occurrence_id, status, mode, note=note)
            else:
                values = (self.ocr if mode == MODE_OCR else self.fast).get(name, {})
                done += 1
                reading = MetadataReading(
                    occurrence_id, READING_OK, mode, selection=make_selection(values),
                    ocr_note="Header read with OCR." if mode == MODE_OCR else "",
                )
            if on_reading is not None:
                on_reading(reading)
            if on_progress is not None:
                on_progress(position, len(ordered), name)
        return MetadataReadSummary(len(ordered), done, failed, len(ordered) - done - failed)


def install_fake_reader(monkeypatch):
    """Replace the hosts' reader seam; per-review options come from ``queue``, then ``options``.

    Also routes unexpected host errors to the test (the real handler would open
    a modal dialog) and reports OCR as available.
    """

    from types import SimpleNamespace

    from metroliza.ui.parsing_dialog import _ReportOperations

    registry = SimpleNamespace(options={}, queue=[], instances=[])

    def factory(self):
        options = registry.queue.pop(0) if registry.queue else registry.options
        reader = FakeMetadataReader(self._preflight_result, **options)
        registry.instances.append(reader)
        return reader

    def release_all():
        for reader in registry.instances:
            for event in (reader.gate, reader.blocker):
                if event is not None:
                    event.set()

    def fail_loudly(self, exception):
        raise exception

    registry.release_all = release_all
    monkeypatch.setattr(_ReportOperations, "log_and_exit", fail_loudly)
    monkeypatch.setattr(_ReportOperations, "_create_metadata_reader", factory)
    monkeypatch.setattr(_ReportOperations, "_ocr_unavailable_reason", staticmethod(lambda: ""))
    return registry


def review_result(names, *, source="/synthetic/reports", database="/synthetic/reports.sqlite3",
                  other=()):
    """Synthetic review with READY ``names`` followed by ``other`` ``(name, status)`` rows."""

    generation = report_parser_factory.get_registry_snapshot().generation_id
    files = []
    for index, name in enumerate(names):
        files.append(
            ParseFilePreflight(
                display_name=name, source_path=f"/temporary/{name}", status=ParsePreflightStatus.READY,
                source_format="pdf", fingerprint="sha256:" + f"{index + 1:x}" * 64, parser_id="cmm",
                confidence=90, registry_generation_id=generation, occurrence_id=name,
            )
        )
    for name, status in other:
        files.append(
            ParseFilePreflight(
                display_name=name, source_path=f"/temporary/{name}", status=status,
                source_format="pdf", fingerprint="sha256:" + "f" * 64, occurrence_id=name,
            )
        )
    return ParsePreflightResult(
        source_path=source, database_path=database, metadata_parsing_mode="light", files=tuple(files),
    )


__all__ = [
    "FILE_NAME",
    "HEADER",
    "FakeMetadataReader",
    "install_fake_reader",
    "ROW_CHANGED",
    "ROW_FAILED",
    "ROW_UNSUPPORTED",
    "make_selection",
    "review_result",
]
