"""Headless approval, ordering, cancellation and artifact contracts."""
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

from metroliza.exporting.export_outcomes import ExportRunStatus
from metroliza.recipes.export_service import ExportRecipeService
from metroliza.parsing.preflight import ParseFilePreflight, ParsePreflightResult, ParsePreflightStatus
from metroliza.recipes.report_ports import ImportExecutionResult, ReportsRecipeService
from metroliza.recipes.bindings import resolve_plan
from metroliza.recipes.builtin_recipes import REPORTS_EXCEL_MAIN, builtin_binding
from metroliza.recipes.ports import ResultCode, StepContext, StepStatus


def make_plan(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    return resolve_plan(REPORTS_EXCEL_MAIN, builtin_binding(
        REPORTS_EXCEL_MAIN, str(source), str(tmp_path / "result.xlsx")))


def context(plan, cancelled=lambda: False):
    return StepContext(plan.flow_id, plan.run_id, str(uuid4()), cancelled, lambda *_args: None)


class Scanner:
    def __init__(self):
        self.digest = "sha256:" + "a" * 64
        self.status = ParsePreflightStatus.READY

    def scan_source(self, **kwargs):
        item = ParseFilePreflight("report.pdf", "report.pdf", self.status, "pdf", self.digest,
                                  parser_id="cmm", registry_generation_id=1)
        return ParsePreflightResult(str(kwargs["source_path"]), str(kwargs["database_path"]),
                                    kwargs["metadata_parsing_mode"], (item,))


class MetadataReader:
    complete = True

    def __init__(self, scan):
        self.scan = scan

    def read(self, occurrences, *, on_reading, **_kwargs):
        for occurrence in occurrences:
            metadata = SimpleNamespace(reference="R1" if self.complete else None, part_name="Part",
                sample_number="1", report_date="2026-11-15", report_time=None, revision=None,
                operator_name=None, comment=None, metadata_json={}, metadata_confidence=1.0, warnings=())
            on_reading(SimpleNamespace(occurrence_id=occurrence, status="ok",
                                      selection=SimpleNamespace(metadata=metadata, candidates=())))


def workbook(path):
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")


def test_headless_ready_preflight_does_not_write_and_orders_import_before_export(tmp_path):
    plan = make_plan(tmp_path)
    events = []

    def importer(request, _context):
        assert request.preflight_result_id
        assert not plan.database_file.exists()
        events.append("import")
        plan.database_file.write_bytes(b"synthetic database")
        return ImportExecutionResult(imported=1)

    def exporter(request, _context):
        assert events == ["import"]
        events.append("export")
        workbook(request.paths.excel_file)
        return SimpleNamespace(status=ExportRunStatus.COMPLETE)

    service = ReportsRecipeService(importer, exporter, scanner=Scanner(), metadata_reader=MetadataReader)
    assert service.preflight(plan, context(plan)).ready
    assert not plan.database_file.exists()
    for step in plan.definition.steps:
        result = service.execute(step, plan, context(plan))
        assert result.status is StepStatus.COMPLETED
    assert events == ["import", "export"]
    assert result.artifact_verified


def test_missing_metadata_requires_explicit_review_and_changed_source_blocks_write(tmp_path):
    plan = make_plan(tmp_path)
    scanner = Scanner()
    reader = type("MissingReader", (MetadataReader,), {"complete": False})
    service = ReportsRecipeService(lambda *_args: None, lambda *_args: None,
                                   scanner=scanner, metadata_reader=reader)
    result = service.preflight(plan, context(plan))
    assert result.requires_decision and not result.ready
    assert not plan.database_file.exists()
    assert service.approve(plan, "continue")
    scanner.digest = "sha256:" + "b" * 64
    assert service.preflight(plan, context(plan)).code is ResultCode.SOURCE_CHANGED
    assert not plan.database_file.exists()


def test_ambiguous_scan_cannot_be_approved(tmp_path):
    plan = make_plan(tmp_path)
    scanner = Scanner()
    scanner.status = ParsePreflightStatus.AMBIGUOUS
    service = ReportsRecipeService(lambda *_args: None, lambda *_args: None,
                                   scanner=scanner, metadata_reader=MetadataReader)
    assert service.preflight(plan, context(plan)).requires_decision
    assert not service.approve(plan, "continue")


def test_required_enrichment_and_cancel_prevent_export(tmp_path):
    plan = make_plan(tmp_path)
    service = ReportsRecipeService(lambda *_args: ImportExecutionResult(imported=1, enrichment_complete=False),
                                   lambda *_args: (_ for _ in ()).throw(AssertionError("must not export")),
                                   scanner=Scanner(), metadata_reader=MetadataReader)
    assert service.preflight(plan, context(plan)).ready
    imported = service.execute(plan.definition.steps[1], plan, context(plan))
    assert imported.status is StepStatus.FAILED
    assert service.execute(plan.definition.steps[2], plan, context(plan)).status is StepStatus.FAILED
    assert service.execute(plan.definition.steps[1], plan, context(plan, lambda: True)).status is StepStatus.CANCELLED


def test_success_receipt_without_real_output_is_rejected(tmp_path):
    plan = make_plan(tmp_path)
    service = ExportRecipeService(lambda *_args: SimpleNamespace(status=ExportRunStatus.COMPLETE))
    assert service.execute(plan, context(plan)).code is ResultCode.OUTPUT_MISSING
    plan.output_file.write_bytes(b"not an XLSX archive")
    assert not service.verify(plan.output_file)
    workbook(plan.output_file)
    assert service.verify(plan.output_file)


def test_overwrite_approval_is_bound_to_current_entry(tmp_path):
    from metroliza.exporting.output_publication import publish_output
    import pytest
    plan = make_plan(tmp_path)
    workbook(plan.output_file)
    service = ReportsRecipeService(lambda *_args: None, lambda *_args: None,
                                   scanner=Scanner(), metadata_reader=MetadataReader)
    assert service.preflight(plan, context(plan)).requires_decision
    assert service.approve(plan, "continue")
    consent = service._reviews[plan.run_id].consents
    plan.output_file.write_bytes(b"changed after approval")
    staged = tmp_path / "staged.xlsx"
    workbook(staged)
    with pytest.raises(FileExistsError):
        publish_output(staged, plan.output_file, consents=consent)
    assert plan.output_file.read_bytes() == b"changed after approval"


def test_existing_reports_database_uses_canonical_schema_readiness_without_migration(tmp_path):
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest, validate_export_request
    from metroliza.recipes.report_configuration_adapter import capture_export_configuration
    from metroliza.reports.db import sqlite_connection_scope
    from metroliza.reports.report_schema import ensure_report_schema

    database = tmp_path / "canonical.db"
    ensure_report_schema(str(database))
    stored = capture_export_configuration(validate_export_request(ExportRequest(
        AppPaths(str(database), excel_file=str(tmp_path / "existing.xlsx")), ExportOptions())))
    plan = resolve_plan(stored.definition, stored.binding)
    service = ReportsRecipeService(lambda *_args: None, lambda *_args: None)
    before = database.read_bytes()
    assert service.preflight(plan, context(plan)).ready
    assert database.read_bytes() == before
    service.finish(plan)
    # Table-name presence alone cannot authorize a schema missing migration evidence.
    with sqlite_connection_scope(str(database)) as connection:
        connection.execute("DELETE FROM app_schema WHERE key='source_location_ownership_version'")
        connection.commit()
    before = database.read_bytes()
    assert not service.preflight(plan, context(plan)).ready
    assert database.read_bytes() == before


def test_explicitly_reviewed_exclusions_survive_success_as_warning(tmp_path):
    from dataclasses import replace
    plan = make_plan(tmp_path)

    class MixedScanner(Scanner):
        def scan_source(self, **kwargs):
            result = super().scan_source(**kwargs)
            excluded = replace(result.files[0], display_name="unsupported.pdf", occurrence_id="unsupported.pdf",
                               status=ParsePreflightStatus.UNSUPPORTED, fingerprint=None, parser_id=None)
            return replace(result, files=(*result.files, excluded))

    service = ReportsRecipeService(lambda *_args: ImportExecutionResult(imported=1), lambda *_args: None,
                                   scanner=MixedScanner(), metadata_reader=MetadataReader)
    assert service.preflight(plan, context(plan)).requires_decision
    assert service.approve(plan, "continue")
    result = service.execute(plan.definition.steps[1], plan, context(plan))
    assert result.status is StepStatus.COMPLETED
    assert result.warnings == (ResultCode.UNSUPPORTED,)
