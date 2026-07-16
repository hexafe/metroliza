"""Persistence adapter for generic parser-plugin ``ParseResultV2`` output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metroliza.parsing.parser_plugin_contracts import ParseResultV2
from metroliza.parsing.source_inspection import SourceInspectionContext
from metroliza.reports.report_identity import build_report_identity_hash
from metroliza.reports.report_metadata_models import CanonicalReportMetadata, MetadataWarning
from metroliza.reports.report_repository import ReportRepository


MAX_RAW_PROVENANCE_DIAGNOSTICS = 50
MAX_RAW_PROVENANCE_TEXT_CHARS = 500


class ParseResultContractError(ValueError):
    """Raised when plugin output violates the selected parser contract."""


class EmptyParseResultError(ParseResultContractError):
    """Raised when a parser produces no persistable measurement rows."""

    def __init__(self, source_path: str | Path, *, plugin_id: str) -> None:
        self.source_path = str(source_path)
        self.plugin_id = str(plugin_id)
        super().__init__(
            "Parser produced no persistable measurements: "
            f"plugin={self.plugin_id or 'unknown'} source={self.source_path}"
        )


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


def _normalized_required_meta_value(
    value: Any,
    *,
    field_name: str,
    source_path: str | Path,
    lowercase: bool = False,
) -> str:
    raw_value = str(value or "")
    normalized = raw_value.strip()
    if lowercase:
        normalized = normalized.lower()
    if not normalized:
        raise ParseResultContractError(
            f"ParseResultV2.meta.{field_name} is required for {source_path}"
        )
    if raw_value != normalized:
        raise ParseResultContractError(
            f"ParseResultV2.meta.{field_name} must be normalized exactly: "
            f"actual={raw_value!r} source={source_path}"
        )
    return normalized


def _validate_plugin_provenance(
    parse_result: ParseResultV2,
    *,
    source_path: str | Path,
    manifest: Any,
) -> str:
    parse_plugin_id = _normalized_required_meta_value(
        parse_result.meta.plugin_id,
        field_name="plugin_id",
        source_path=source_path,
    )

    manifest_plugin_id = str(getattr(manifest, "plugin_id", "") or "").strip()
    if manifest_plugin_id and parse_plugin_id != manifest_plugin_id:
        raise ParseResultContractError(
            "ParseResultV2 plugin_id does not match the selected parser: "
            f"expected={manifest_plugin_id} actual={parse_plugin_id} source={source_path}"
        )

    parse_plugin_version = _normalized_required_meta_value(
        parse_result.meta.plugin_version,
        field_name="plugin_version",
        source_path=source_path,
    )
    manifest_plugin_version = str(getattr(manifest, "version", "") or "").strip()
    if manifest_plugin_version and parse_plugin_version != manifest_plugin_version:
        raise ParseResultContractError(
            "ParseResultV2 plugin_version does not match the selected parser: "
            f"expected={manifest_plugin_version} actual={parse_plugin_version} "
            f"source={source_path}"
        )
    return parse_plugin_id


def _validate_source_format_provenance(
    parse_result: ParseResultV2,
    *,
    source_path: str | Path,
    manifest: Any,
    expected_source_format: str | None,
    parse_plugin_id: str,
) -> None:
    source_format = _normalized_required_meta_value(
        parse_result.meta.source_format,
        field_name="source_format",
        source_path=source_path,
        lowercase=True,
    )
    expected_format = str(expected_source_format or "").strip().lower()
    if expected_format and source_format != expected_format:
        raise ParseResultContractError(
            "ParseResultV2 source_format does not match the inspected source: "
            f"expected={expected_format} actual={source_format} source={source_path}"
        )

    supported_formats = tuple(
        str(value).strip().lower()
        for value in (getattr(manifest, "supported_formats", ()) or ())
        if str(value).strip()
    )
    if supported_formats and source_format not in supported_formats:
        raise ParseResultContractError(
            "ParseResultV2 source_format is not supported by the selected parser: "
            f"plugin={parse_plugin_id} format={source_format} source={source_path}"
        )


def _validate_parse_result_identity(
    parse_result: ParseResultV2,
    *,
    source_path: str | Path,
    manifest: Any = None,
    expected_source_format: str | None = None,
) -> None:
    """Ensure parse provenance agrees with the selected registration."""

    parse_plugin_id = _validate_plugin_provenance(
        parse_result,
        source_path=source_path,
        manifest=manifest,
    )
    _validate_source_format_provenance(
        parse_result,
        source_path=source_path,
        manifest=manifest,
        expected_source_format=expected_source_format,
        parse_plugin_id=parse_plugin_id,
    )


def _bounded_provenance_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= MAX_RAW_PROVENANCE_TEXT_CHARS:
        return text
    return f"{text[: MAX_RAW_PROVENANCE_TEXT_CHARS - 3]}..."


def _bounded_diagnostics(values: Any) -> list[dict[str, str | None]]:
    return [
        {
            "code": _bounded_provenance_text(getattr(value, "code", None)),
            "message": _bounded_provenance_text(getattr(value, "message", None)),
            "field": _bounded_provenance_text(getattr(value, "field", None)),
        }
        for value in tuple(values)[:MAX_RAW_PROVENANCE_DIAGNOSTICS]
    ]


def _raw_provenance_summary(
    parse_result: ParseResultV2,
    *,
    source_path: str | Path,
    measurement_count: int,
) -> dict[str, Any]:
    """Build bounded report-level provenance without duplicating measurement trees."""

    warning_count = len(parse_result.warnings)
    error_count = len(parse_result.errors)
    return {
        "source": "ParseResultV2",
        "source_path": _bounded_provenance_text(source_path),
        "provenance_version": 2,
        "parse_result_summary": {
            "meta": {
                "source_file": _bounded_provenance_text(parse_result.meta.source_file),
                "source_format": _bounded_provenance_text(parse_result.meta.source_format),
                "plugin_id": _bounded_provenance_text(parse_result.meta.plugin_id),
                "plugin_version": _bounded_provenance_text(parse_result.meta.plugin_version),
                "template_id": _bounded_provenance_text(parse_result.meta.template_id),
                "parse_timestamp": _bounded_provenance_text(parse_result.meta.parse_timestamp),
                "locale_detected": _bounded_provenance_text(parse_result.meta.locale_detected),
                "confidence": parse_result.meta.confidence,
            },
            "report": {
                "reference": _bounded_provenance_text(parse_result.report.reference),
                "report_date": _bounded_provenance_text(parse_result.report.report_date),
                "sample_number": _bounded_provenance_text(parse_result.report.sample_number),
                "file_name": _bounded_provenance_text(parse_result.report.file_name),
                "file_path": _bounded_provenance_text(parse_result.report.file_path),
            },
            "block_count": len(parse_result.blocks),
            "measurement_count": measurement_count,
            "warning_count": warning_count,
            "error_count": error_count,
            "warnings": _bounded_diagnostics(parse_result.warnings),
            "errors": _bounded_diagnostics(parse_result.errors),
            "diagnostics_truncated": (
                warning_count > MAX_RAW_PROVENANCE_DIAGNOSTICS
                or error_count > MAX_RAW_PROVENANCE_DIAGNOSTICS
            ),
        },
    }


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
    expected_source_format: str | None = None,
) -> ParseResultV2PersistencePayload:
    """Build the full repository payload and reject blocking parser errors."""

    _raise_for_errors(parse_result)
    _validate_parse_result_identity(
        parse_result,
        source_path=source_path,
        manifest=manifest,
        expected_source_format=expected_source_format,
    )
    measurements = measurements_from_parse_result_v2(parse_result)
    if not measurements:
        raise EmptyParseResultError(
            source_path,
            plugin_id=parse_result.meta.plugin_id,
        )
    metadata = canonical_metadata_from_parse_result_v2(
        parse_result,
        source_path=source_path,
        manifest=manifest,
    )
    nok_count = sum(1 for row in measurements if row.get("status_code") == "nok")
    raw_report_json = _raw_provenance_summary(
        parse_result,
        source_path=source_path,
        measurement_count=len(measurements),
    )
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
    source_sha256: str | None = None,
    source_inspection: SourceInspectionContext | None = None,
) -> int:
    """Persist a generic plugin parse result through ``ReportRepository``."""

    payload = build_persistence_payload(
        parse_result,
        source_path=source_path,
        manifest=manifest,
        expected_source_format=(
            source_inspection.source_format if source_inspection is not None else None
        ),
    )
    return persist_parse_result_v2_payload(
        payload,
        parse_result=parse_result,
        source_path=source_path,
        database=database,
        connection=connection,
        source_sha256=source_sha256,
        source_inspection=source_inspection,
    )


def persist_parse_result_v2_payload(
    payload: ParseResultV2PersistencePayload,
    *,
    parse_result: ParseResultV2,
    source_path: str | Path,
    database: str,
    connection=None,
    source_sha256: str | None = None,
    source_inspection: SourceInspectionContext | None = None,
) -> int:
    """Persist a prebuilt V2 payload through ``ReportRepository``."""

    if payload.measurement_count <= 0 or not payload.measurements:
        raise EmptyParseResultError(
            source_path,
            plugin_id=parse_result.meta.plugin_id,
        )

    verified_source_sha256 = source_sha256
    if source_inspection is not None:
        current_sha256 = source_inspection.verified_sha256()
        if (
            source_sha256 is not None
            and (
                current_sha256 is None
                or source_sha256.casefold() != current_sha256.casefold()
            )
        ):
            raise ValueError(
                "Explicit source digest does not match the inspected source digest: "
                f"{source_path}"
            )
        verified_source_sha256 = current_sha256

    repository = ReportRepository(database, connection=connection)
    return repository.persist_parsed_report(
        source_path=source_path,
        source_sha256=verified_source_sha256,
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
