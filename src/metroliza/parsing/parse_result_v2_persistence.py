"""Persistence adapter for generic parser-plugin ``ParseResultV2`` output."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from metroliza.parsing.parser_plugin_contracts import ParseResultV2
from metroliza.reports.report_identity import build_report_identity_hash
from metroliza.reports.report_metadata_models import CanonicalReportMetadata, MetadataWarning
from metroliza.reports.report_repository import ReportRepository


@dataclass(frozen=True)
class ParseResultV2PersistencePayload:
    """Repository-ready payload derived from one parser result."""

    metadata: CanonicalReportMetadata
    warnings: tuple[MetadataWarning, ...]
    measurements: tuple[dict[str, Any], ...]
    parse_status: str
    measurement_count: int
    has_nok: bool
    nok_count: int
    identity_hash: str
    raw_report_json: dict[str, Any]


def _clean_optional(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _confidence_fraction(value: Any) -> float:
    try:
        confidence = int(value)
    except (TypeError, ValueError):
        confidence = 0
    return max(0.0, min(1.0, confidence / 100.0))


def _template_family(parse_result: ParseResultV2, manifest: Any = None) -> str:
    if parse_result.meta.template_id:
        return str(parse_result.meta.template_id)
    template_ids = tuple(getattr(manifest, "template_ids", ()) or ())
    if template_ids:
        return str(template_ids[0])
    return str(parse_result.meta.plugin_id or "generated_parser")


def _warning_from_parse_warning(warning: Any) -> MetadataWarning:
    return MetadataWarning(
        code=str(getattr(warning, "code", "parse_warning") or "parse_warning"),
        field_name=_clean_optional(getattr(warning, "field", None)),
        severity="warning",
        message=str(getattr(warning, "message", "") or "Parser warning"),
        details={"source": "ParseResultV2"},
    )


def _raise_for_errors(parse_result: ParseResultV2) -> None:
    if not parse_result.errors:
        return
    details = "; ".join(
        f"{getattr(error, 'code', 'parse_error')}: {getattr(error, 'message', '')}"
        for error in parse_result.errors
    )
    raise ValueError(f"ParseResultV2 contains blocking parser errors: {details}")


def canonical_metadata_from_parse_result_v2(
    parse_result: ParseResultV2,
    *,
    source_path: str | Path,
    manifest: Any = None,
) -> CanonicalReportMetadata:
    """Convert V2 report/meta output into selected canonical metadata."""

    metadata_json = {
        "source": "ParseResultV2",
        "source_path": str(source_path),
        "source_file": parse_result.meta.source_file,
        "source_format": parse_result.meta.source_format,
        "plugin_id": parse_result.meta.plugin_id,
        "plugin_version": parse_result.meta.plugin_version,
        "template_id": parse_result.meta.template_id,
        "parse_timestamp": parse_result.meta.parse_timestamp,
        "locale_detected": parse_result.meta.locale_detected,
        "file_name": parse_result.report.file_name,
        "file_path": parse_result.report.file_path,
        "block_count": len(parse_result.blocks),
        "warning_count": len(parse_result.warnings),
        "error_count": len(parse_result.errors),
    }
    warnings = tuple(_warning_from_parse_warning(warning) for warning in parse_result.warnings)
    return CanonicalReportMetadata(
        parser_id=str(parse_result.meta.plugin_id or getattr(manifest, "plugin_id", "") or "generated_parser"),
        template_family=_template_family(parse_result, manifest),
        template_variant=_clean_optional(parse_result.meta.template_id),
        metadata_confidence=_confidence_fraction(parse_result.meta.confidence),
        reference=_clean_optional(parse_result.report.reference),
        reference_raw=_clean_optional(parse_result.report.reference),
        report_date=_clean_optional(parse_result.report.report_date),
        report_time=None,
        part_name=None,
        revision=None,
        sample_number=_clean_optional(parse_result.report.sample_number),
        sample_number_kind=None,
        stats_count_raw=None,
        stats_count_int=None,
        operator_name=None,
        comment=None,
        page_count=None,
        metadata_json=metadata_json,
        warnings=warnings,
    )


def measurements_from_parse_result_v2(parse_result: ParseResultV2) -> tuple[dict[str, Any], ...]:
    """Convert V2 measurement blocks into repository measurement dictionaries."""

    rows: list[dict[str, Any]] = []
    row_order = 1
    for block in parse_result.blocks:
        header_raw = tuple(str(item) for item in (block.header_raw or ()))
        header = str(block.header_normalized or "").strip() or " | ".join(header_raw)
        header = header or f"Block {block.block_index}"
        for measurement in block.dimensions:
            extensions = dict(measurement.extensions or {})
            outtol = measurement.out_of_tolerance
            try:
                outtol_value = None if outtol is None else float(outtol)
            except (TypeError, ValueError):
                outtol_value = None
            status_code = "unknown" if outtol_value is None else ("nok" if outtol_value > 0 else "ok")
            is_nok = status_code == "nok"
            rows.append(
                {
                    "page_number": extensions.get("page_number"),
                    "row_order": row_order,
                    "header": header,
                    "section_name": header,
                    "feature_label": header,
                    "characteristic_name": extensions.get("characteristic_name") or measurement.axis_code,
                    "characteristic_family": extensions.get("characteristic_family"),
                    "description": extensions.get("description"),
                    "ax": measurement.axis_code,
                    "nominal": measurement.nominal,
                    "tol_plus": measurement.tol_plus,
                    "tol_minus": measurement.tol_minus,
                    "bonus": measurement.bonus,
                    "meas": measurement.measured,
                    "dev": measurement.deviation,
                    "outtol": measurement.out_of_tolerance,
                    "is_nok": is_nok,
                    "status_code": status_code,
                    "raw_measurement_json": {
                        "source": "ParseResultV2",
                        "block_index": block.block_index,
                        "header_raw": header_raw,
                        "raw_tokens": tuple(measurement.raw_tokens or ()),
                        "raw_line_refs": tuple(measurement.raw_line_refs or ()),
                        "extensions": extensions,
                    },
                }
            )
            row_order += 1
    return tuple(rows)


def build_persistence_payload(
    parse_result: ParseResultV2,
    *,
    source_path: str | Path,
    manifest: Any = None,
) -> ParseResultV2PersistencePayload:
    """Build the full repository payload and reject blocking parser errors."""

    _raise_for_errors(parse_result)
    metadata = canonical_metadata_from_parse_result_v2(
        parse_result,
        source_path=source_path,
        manifest=manifest,
    )
    measurements = measurements_from_parse_result_v2(parse_result)
    nok_count = sum(1 for row in measurements if row.get("status_code") == "nok")
    raw_report_json = {
        "source": "ParseResultV2",
        "source_path": str(source_path),
        "parse_result": asdict(parse_result),
    }
    return ParseResultV2PersistencePayload(
        metadata=metadata,
        warnings=metadata.warnings,
        measurements=measurements,
        parse_status="parsed_with_warnings" if parse_result.warnings else "parsed",
        measurement_count=len(measurements),
        has_nok=nok_count > 0,
        nok_count=nok_count,
        identity_hash=build_report_identity_hash(metadata),
        raw_report_json=raw_report_json,
    )


def persist_parse_result_v2(
    parse_result: ParseResultV2,
    *,
    source_path: str | Path,
    database: str,
    connection=None,
    manifest: Any = None,
) -> int:
    """Persist a generic plugin parse result through ``ReportRepository``."""

    payload = build_persistence_payload(
        parse_result,
        source_path=source_path,
        manifest=manifest,
    )
    return persist_parse_result_v2_payload(
        payload,
        parse_result=parse_result,
        source_path=source_path,
        database=database,
        connection=connection,
    )


def persist_parse_result_v2_payload(
    payload: ParseResultV2PersistencePayload,
    *,
    parse_result: ParseResultV2,
    source_path: str | Path,
    database: str,
    connection=None,
) -> int:
    """Persist a prebuilt V2 payload through ``ReportRepository``."""

    repository = ReportRepository(database, connection=connection)
    return repository.persist_parsed_report(
        source_path=source_path,
        parser_id=payload.metadata.parser_id,
        parser_version=parse_result.meta.plugin_version,
        template_family=payload.metadata.template_family,
        template_variant=payload.metadata.template_variant,
        parse_status=payload.parse_status,
        metadata=payload.metadata,
        candidates=(),
        warnings=payload.warnings,
        measurements=payload.measurements,
        metadata_version="parse_result_v2",
        metadata_confidence=payload.metadata.metadata_confidence,
        identity_hash=payload.identity_hash,
        raw_report_json=payload.raw_report_json,
        measurement_count=payload.measurement_count,
        has_nok=payload.has_nok,
        nok_count=payload.nok_count,
    )
