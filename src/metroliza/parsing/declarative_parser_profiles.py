"""Declarative parser profile runtime and approval store.

Self-service parser creation uses data-only YAML profiles interpreted by trusted
Metroliza code. Generated Python plugins remain an operator-only extension path.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

import yaml

from metroliza.parsing.base_report_parser import BaseReportParser
from metroliza.parsing.parser_plugin_contracts import (
    BaseReportParserPlugin,
    MeasurementBlockV2,
    MeasurementV2,
    ParseMetaV2,
    ParseResultV2,
    PluginManifest,
    ProbeContext,
    ProbeResult,
    ReportInfoV2,
    infer_source_format,
)
from metroliza.parsing.parser_plugin_paths import (
    default_external_plugin_dir,
    disabled_plugin_ids,
)
from metroliza.parsing.parser_plugin_validation import (
    ValidationReport,
    validate_plugin_contract,
)


PROFILE_SCHEMA_VERSION = 1
PROFILE_APPROVAL_SCHEMA_VERSION = 1
PROFILE_STORE_SUBDIR = "profiles"
PROFILE_APPROVED_SUBDIR = "approved"
PROFILE_DISABLED_SUBDIR = "disabled"
PROFILE_INCOMING_SUBDIR = "incoming"
PROFILE_QUARANTINE_SUBDIR = "quarantine"
PROFILE_BACKUP_SUBDIR = "backups"
PROFILE_FILE_NAME = "profile.yaml"
APPROVAL_FILE_NAME = "approval.json"
SUPPORTED_SOURCE_FORMATS = {"pdf", "excel", "csv"}
PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?$")
MAX_PROFILE_REGEX_LENGTH = 750
MAX_PROFILE_SOURCE_TEXT_CHARS = 2_000_000
MAX_PROFILE_ROW_MATCHES_PER_BLOCK = 10_000
DANGEROUS_NESTED_REPEAT_PATTERN = re.compile(
    r"\((?:\?:|\?P<[^>]+>)?[^)]*(?:[+*]|\{\d*,?\d*\})[^)]*\)\s*(?:[+*]|\{\d*,?\d*\})"
)
BACKREFERENCE_PATTERN = re.compile(r"(?:\\[1-9]|\\g<[^>]+>|\(\?P=[^)]+\))")
UNBOUNDED_DOT_PATTERN = re.compile(r"(?<!\\)\.(?:\*|\+)")


@dataclass(frozen=True)
class ProfileCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ProfileValidationReport:
    plugin_id: str
    passed: bool
    checks: tuple[ProfileCheck, ...]
    contract_reports: tuple[ValidationReport, ...] = ()


@dataclass(frozen=True)
class ProfileInstallResult:
    plugin_id: str
    approved_dir: Path
    profile_path: Path
    approval_path: Path
    backup_dir: Path | None
    sha256: str


@dataclass(frozen=True)
class InstalledProfile:
    plugin_id: str
    profile_path: Path
    approval_path: Path | None
    enabled: bool
    approved: bool
    detail: str = ""


def _check(name: str, passed: bool, detail: str = "") -> ProfileCheck:
    return ProfileCheck(name=name, passed=passed, detail=detail)


def _validate_plugin_id_for_store(plugin_id: str) -> str:
    normalized = str(plugin_id or "").strip()
    if not PLUGIN_ID_PATTERN.fullmatch(normalized):
        raise ValueError("plugin_id must match ^[a-z][a-z0-9_]{2,63}$")
    return normalized


def profile_store_root(*, home: Path | None = None) -> Path:
    return default_external_plugin_dir(home=home) / PROFILE_STORE_SUBDIR


def profile_state_dir(state: str, *, home: Path | None = None) -> Path:
    return profile_store_root(home=home) / state


def approved_profiles_dir(*, home: Path | None = None) -> Path:
    return profile_state_dir(PROFILE_APPROVED_SUBDIR, home=home)


def disabled_profiles_dir(*, home: Path | None = None) -> Path:
    return profile_state_dir(PROFILE_DISABLED_SUBDIR, home=home)


def incoming_profiles_dir(*, home: Path | None = None) -> Path:
    return profile_state_dir(PROFILE_INCOMING_SUBDIR, home=home)


def quarantine_profiles_dir(*, home: Path | None = None) -> Path:
    return profile_state_dir(PROFILE_QUARANTINE_SUBDIR, home=home)


def profile_backups_dir(*, home: Path | None = None) -> Path:
    return profile_state_dir(PROFILE_BACKUP_SUBDIR, home=home)


def ensure_profile_store_dirs(*, home: Path | None = None) -> None:
    for state in (
        PROFILE_APPROVED_SUBDIR,
        PROFILE_DISABLED_SUBDIR,
        PROFILE_INCOMING_SUBDIR,
        PROFILE_QUARANTINE_SUBDIR,
        PROFILE_BACKUP_SUBDIR,
    ):
        profile_state_dir(state, home=home).mkdir(parents=True, exist_ok=True)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_profile_payload(path: str | Path) -> dict[str, Any]:
    profile_path = Path(path)
    payload = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Profile must be a YAML mapping.")
    return payload


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        iterable = (value,)
    elif isinstance(value, Iterable):
        iterable = tuple(value)
    else:
        iterable = (value,)
    return tuple(str(item).strip() for item in iterable if str(item).strip())


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _plugin_section(payload: dict[str, Any]) -> dict[str, Any]:
    return _mapping(payload.get("plugin"))


def profile_plugin_id(payload: dict[str, Any]) -> str:
    return str(_plugin_section(payload).get("plugin_id") or "").strip()


def profile_display_name(payload: dict[str, Any]) -> str:
    plugin = _plugin_section(payload)
    display_name = str(plugin.get("display_name") or "").strip()
    return display_name or profile_plugin_id(payload)


def profile_version(payload: dict[str, Any]) -> str:
    return str(_plugin_section(payload).get("version") or "").strip()


def profile_source_format(payload: dict[str, Any]) -> str:
    return str(_plugin_section(payload).get("source_format") or "").strip().lower()


def profile_template_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    return _string_tuple(_plugin_section(payload).get("template_ids"))


def profile_priority(payload: dict[str, Any]) -> int:
    raw_priority = _plugin_section(payload).get("priority", 100)
    try:
        return int(raw_priority)
    except (TypeError, ValueError):
        return 100


def profile_manifest(payload: dict[str, Any]) -> PluginManifest:
    plugin = _plugin_section(payload)
    return PluginManifest(
        plugin_id=profile_plugin_id(payload),
        display_name=profile_display_name(payload),
        version=profile_version(payload),
        supported_formats=(profile_source_format(payload),),
        supported_locales=_string_tuple(plugin.get("supported_locales")) or ("*",),
        template_ids=profile_template_ids(payload),
        priority=profile_priority(payload),
        capabilities={"declarative_profile": True},
    )


def _profile_policy_checks(payload: dict[str, Any]) -> list[ProfileCheck]:
    checks: list[ProfileCheck] = []
    schema_version = payload.get("schema_version")
    plugin = _plugin_section(payload)
    probe = _mapping(payload.get("probe"))
    extraction = _mapping(payload.get("extraction"))

    plugin_id = profile_plugin_id(payload)
    source_format = profile_source_format(payload)
    version = profile_version(payload)
    priority = profile_priority(payload)
    template_ids = profile_template_ids(payload)
    required_markers = _string_tuple(probe.get("required_markers"))
    row_patterns = _row_specs(payload)
    report_fields = _mapping(extraction.get("report_fields"))

    checks.append(
        _check(
            "schema_version_supported",
            schema_version == PROFILE_SCHEMA_VERSION,
            f"expected {PROFILE_SCHEMA_VERSION}, got {schema_version!r}",
        )
    )
    checks.append(_check("plugin_section_present", bool(plugin), "plugin section is required"))
    checks.append(
        _check(
            "plugin_id_slug",
            bool(PLUGIN_ID_PATTERN.match(plugin_id)),
            "plugin_id must match ^[a-z][a-z0-9_]{2,63}$",
        )
    )
    checks.append(_check("display_name_present", bool(profile_display_name(payload)), "display_name is required"))
    checks.append(_check("version_semver", bool(VERSION_PATTERN.match(version)), "version must look like 1.2.3"))
    checks.append(
        _check(
            "source_format_supported",
            source_format in SUPPORTED_SOURCE_FORMATS,
            f"source_format must be one of {', '.join(sorted(SUPPORTED_SOURCE_FORMATS))}",
        )
    )
    checks.append(_check("template_ids_present", bool(template_ids), "at least one template id is required"))
    checks.append(_check("priority_range", 0 <= priority <= 1000, "priority must be between 0 and 1000"))
    checks.append(_check("probe_required_markers_present", bool(required_markers), "probe.required_markers is required"))

    confidence = _probe_confidence(payload)
    checks.append(_check("probe_confidence_range", 80 <= confidence <= 100, "probe.confidence must be 80-100"))

    required_report_fields = ("reference", "report_date", "sample_number")
    missing_fields = [field for field in required_report_fields if field not in report_fields]
    checks.append(
        _check(
            "report_field_patterns_present",
            not missing_fields,
            "" if not missing_fields else f"missing fields: {', '.join(missing_fields)}",
        )
    )
    checks.append(_check("row_patterns_present", bool(row_patterns), "at least one extraction block/row pattern is required"))

    for field, pattern in report_fields.items():
        checks.append(_regex_check(f"report_field_{field}_regex_compiles", pattern))
        checks.append(_regex_safety_check(f"report_field_{field}_regex_safe", pattern))
    for index, spec in enumerate(row_patterns):
        checks.append(_regex_check(f"row_pattern_{index}_regex_compiles", spec.get("pattern")))
        checks.append(_regex_safety_check(f"row_pattern_{index}_regex_safe", spec.get("pattern"), row_pattern=True))

    return checks


def _regex_check(name: str, pattern: Any) -> ProfileCheck:
    if not isinstance(pattern, str) or not pattern.strip():
        return _check(name, False, "regex pattern must be a non-empty string")
    try:
        re.compile(pattern)
    except re.error as exc:
        return _check(name, False, f"invalid regex: {exc}")
    return _check(name, True)


def _regex_safety_check(name: str, pattern: Any, *, row_pattern: bool = False) -> ProfileCheck:
    if not isinstance(pattern, str) or not pattern.strip():
        return _check(name, False, "regex pattern must be a non-empty string")
    if len(pattern) > MAX_PROFILE_REGEX_LENGTH:
        return _check(name, False, f"regex pattern must be at most {MAX_PROFILE_REGEX_LENGTH} characters")
    if BACKREFERENCE_PATTERN.search(pattern):
        return _check(name, False, "backreferences are not allowed in declarative profiles")
    if UNBOUNDED_DOT_PATTERN.search(pattern):
        return _check(name, False, "use explicit character classes instead of unbounded dot wildcards")
    if DANGEROUS_NESTED_REPEAT_PATTERN.search(pattern):
        return _check(name, False, "nested repeating groups are not allowed in declarative profiles")
    if row_pattern and not pattern.lstrip().startswith("^"):
        return _check(name, False, "row patterns must be line-anchored with ^")
    return _check(name, True)


def _probe_confidence(payload: dict[str, Any]) -> int:
    raw_confidence = _mapping(payload.get("probe")).get("confidence", 80)
    try:
        return max(0, min(100, int(raw_confidence)))
    except (TypeError, ValueError):
        return 0


def _row_specs(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    extraction = _mapping(payload.get("extraction"))
    rows = extraction.get("blocks", extraction.get("rows", ()))
    if isinstance(rows, dict):
        rows = (rows,)
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes)):
        return ()
    specs: list[dict[str, Any]] = []
    for item in rows:
        if isinstance(item, dict):
            specs.append(dict(item))
    return tuple(specs)


def _read_source_text(path: str | Path) -> str:
    source_path = Path(path)
    if source_path.suffix.lower() == ".pdf":
        try:  # pragma: no cover - depends on local PyMuPDF/runtime PDFs.
            import fitz

            parts: list[str] = []
            with fitz.open(source_path) as document:
                for page in document:
                    parts.append(page.get_text())
            text = "\n".join(parts)
            if text.strip():
                _ensure_text_within_profile_limits(text, source_path)
                return text
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            pass
    if source_path.suffix.lower() in {".xlsx", ".xls"}:
        text = _read_excel_source_text(source_path)
        _ensure_text_within_profile_limits(text, source_path)
        return text
    text = source_path.read_text(encoding="utf-8", errors="ignore")
    _ensure_text_within_profile_limits(text, source_path)
    return text


def _read_excel_source_text(path: Path) -> str:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - dependency hygiene gate covers runtime install.
        raise ValueError("Excel parser profiles require pandas and an Excel reader engine") from exc

    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    except Exception as exc:
        raise ValueError(f"failed to read Excel workbook {path}: {exc}") from exc

    lines: list[str] = []
    for sheet_name, frame in sheets.items():
        lines.append(f"SHEET {sheet_name}")
        for row in frame.itertuples(index=False, name=None):
            cells: list[str] = []
            for value in row:
                if pd.isna(value):
                    continue
                text = str(value).strip()
                if text:
                    cells.append(text)
            if cells:
                lines.append(" ".join(cells))
    return "\n".join(lines)


def _ensure_text_within_profile_limits(text: str, source_path: Path) -> None:
    if len(text) > MAX_PROFILE_SOURCE_TEXT_CHARS:
        raise ValueError(
            f"{source_path} extracted {len(text)} characters; "
            f"declarative profiles allow at most {MAX_PROFILE_SOURCE_TEXT_CHARS}"
        )


def _marker_found(text: str, marker: str) -> bool:
    return marker.casefold() in text.casefold()


def profile_probe(payload: dict[str, Any], input_ref: str | Path, context: ProbeContext) -> ProbeResult:
    manifest = profile_manifest(payload)
    source_format = (context.source_format or infer_source_format(input_ref)).lower()
    if source_format not in manifest.supported_formats:
        return ProbeResult(
            plugin_id=manifest.plugin_id,
            can_parse=False,
            confidence=0,
            reasons=("unsupported_source_format",),
        )

    probe = _mapping(payload.get("probe"))
    required_markers = _string_tuple(probe.get("required_markers"))
    reject_markers = _string_tuple(probe.get("reject_markers"))
    try:
        text = _read_source_text(input_ref)
    except (OSError, ValueError) as exc:
        return ProbeResult(
            plugin_id=manifest.plugin_id,
            can_parse=False,
            confidence=0,
            reasons=("source_unreadable",),
            warnings=(str(exc),),
        )

    missing = tuple(marker for marker in required_markers if not _marker_found(text, marker))
    rejected = tuple(marker for marker in reject_markers if _marker_found(text, marker))
    if missing:
        return ProbeResult(
            plugin_id=manifest.plugin_id,
            can_parse=False,
            confidence=0,
            reasons=("missing_required_markers",),
            warnings=tuple(f"missing marker: {marker}" for marker in missing),
        )
    if rejected:
        return ProbeResult(
            plugin_id=manifest.plugin_id,
            can_parse=False,
            confidence=0,
            reasons=("reject_marker_found",),
            warnings=tuple(f"reject marker: {marker}" for marker in rejected),
        )

    template_ids = manifest.template_ids
    return ProbeResult(
        plugin_id=manifest.plugin_id,
        can_parse=True,
        confidence=_probe_confidence(payload),
        matched_template_id=template_ids[0] if template_ids else None,
        reasons=("required_markers_found",),
    )


def _extract_value(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        return ""
    if "value" in match.groupdict():
        return str(match.group("value")).strip()
    if match.groups():
        return str(match.group(1)).strip()
    return str(match.group(0)).strip()


def _parse_float(value: Any, *, decimal_separator: str = ".") -> float | None:
    return _parse_float_with_missing_tokens(
        value,
        decimal_separator=decimal_separator,
        missing_value_tokens=(),
    )


def _parse_float_with_missing_tokens(
    value: Any,
    *,
    decimal_separator: str = ".",
    missing_value_tokens: Iterable[str] = (),
) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    default_missing_tokens = {"", "-", "none", "null", "na", "n/a", "nan"}
    configured_missing_tokens = {str(token).strip().casefold() for token in missing_value_tokens}
    if text.casefold() in default_missing_tokens | configured_missing_tokens:
        return None
    text = text.replace(" ", "").replace("_", "").replace("'", "")
    if decimal_separator == ",":
        text = text.replace(".", "").replace(",", ".")
    elif "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_date_value(value: str, date_formats: Iterable[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for date_format in date_formats:
        try:
            parsed = datetime.strptime(text, str(date_format))
        except ValueError:
            continue
        return parsed.date().isoformat()
    return text


def _line_refs(text: str, start_offset: int) -> tuple[int, ...]:
    line_number = text.count("\n", 0, start_offset) + 1
    return (line_number,)


def parse_profile_result(payload: dict[str, Any], source_path: str | Path) -> ParseResultV2:
    manifest = profile_manifest(payload)
    text = _read_source_text(source_path)
    extraction = _mapping(payload.get("extraction"))
    normalization = _mapping(payload.get("normalization"))
    decimal_separator = str(normalization.get("decimal_separator") or ".")
    date_formats = _string_tuple(normalization.get("date_formats"))
    missing_value_tokens = _string_tuple(normalization.get("missing_value_tokens"))

    report_fields = _mapping(extraction.get("report_fields"))
    reference = _extract_value(str(report_fields.get("reference", "")), text)
    report_date = _normalize_date_value(
        _extract_value(str(report_fields.get("report_date", "")), text),
        date_formats,
    )
    sample_number = _extract_value(str(report_fields.get("sample_number", "")), text)

    blocks: list[MeasurementBlockV2] = []
    for block_index, spec in enumerate(_row_specs(payload)):
        header = str(spec.get("header") or spec.get("header_normalized") or f"Block {block_index + 1}").strip()
        pattern = str(spec.get("pattern") or "")
        dimensions: list[MeasurementV2] = []
        for row_index, match in enumerate(re.finditer(pattern, text, flags=re.MULTILINE)):
            if row_index >= MAX_PROFILE_ROW_MATCHES_PER_BLOCK:
                raise ValueError(
                    f"profile {manifest.plugin_id} exceeded "
                    f"{MAX_PROFILE_ROW_MATCHES_PER_BLOCK} row matches in block {block_index}"
                )
            group = match.groupdict()

            def numeric(name: str) -> float | None:
                return _parse_float_with_missing_tokens(
                    group.get(name),
                    decimal_separator=decimal_separator,
                    missing_value_tokens=missing_value_tokens,
                )

            dimensions.append(
                MeasurementV2(
                    axis_code=str(group.get("axis_code") or "").strip(),
                    nominal=numeric("nominal"),
                    tol_plus=numeric("tol_plus"),
                    tol_minus=numeric("tol_minus"),
                    bonus=numeric("bonus"),
                    measured=numeric("measured"),
                    deviation=numeric("deviation"),
                    out_of_tolerance=numeric("out_of_tolerance"),
                    raw_tokens=tuple(str(value) for value in match.groups() if value is not None),
                    raw_line_refs=_line_refs(text, match.start()),
                )
            )
        blocks.append(
            MeasurementBlockV2(
                header_raw=(header,),
                header_normalized=header,
                dimensions=tuple(dimensions),
                block_index=block_index,
            )
        )

    path = Path(source_path)
    probe = profile_probe(payload, path, ProbeContext(source_path=str(path), source_format=infer_source_format(path)))
    template_id = probe.matched_template_id
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return ParseResultV2(
        meta=ParseMetaV2(
            source_file=str(path),
            source_format=profile_source_format(payload),
            plugin_id=manifest.plugin_id,
            plugin_version=manifest.version,
            template_id=template_id,
            parse_timestamp=timestamp,
            locale_detected=None,
            confidence=probe.confidence,
        ),
        report=ReportInfoV2(
            reference=reference,
            report_date=report_date,
            sample_number=sample_number,
            file_name=path.name,
            file_path=str(path.parent),
        ),
        blocks=tuple(blocks),
    )


def build_parser_class_from_profile(payload: dict[str, Any], *, origin_path: str | Path | None = None) -> type:
    plugin_manifest = profile_manifest(payload)
    class_name = "".join(part.capitalize() for part in plugin_manifest.plugin_id.split("_")) + "DeclarativeParser"

    class DeclarativeProfileParser(BaseReportParser, BaseReportParserPlugin):
        profile_payload = payload
        profile_origin_path = str(origin_path or "")

        @classmethod
        def probe(cls, input_ref: str | Path, context: ProbeContext) -> ProbeResult:
            return profile_probe(cls.profile_payload, input_ref, context)

        def open_report(self):
            self.raw_text = _read_source_text(self.source_path).splitlines()

        def split_text_to_blocks(self):
            parse_result = self.parse_to_v2()
            self.reference = parse_result.report.reference
            self.date = parse_result.report.report_date
            self.sample_number = parse_result.report.sample_number
            self.blocks_text = self.to_legacy_blocks(parse_result)

        def parse_to_v2(self) -> ParseResultV2:
            return parse_profile_result(self.profile_payload, self.source_path)

        @staticmethod
        def to_legacy_blocks(parse_result_v2: ParseResultV2):
            legacy_blocks = []
            for block in parse_result_v2.blocks:
                rows = [
                    [
                        row.axis_code,
                        row.nominal,
                        row.tol_plus,
                        row.tol_minus,
                        row.bonus,
                        row.measured,
                        row.deviation,
                        row.out_of_tolerance,
                    ]
                    for row in block.dimensions
                ]
                legacy_blocks.append([[list(block.header_raw)], rows])
            return legacy_blocks

    DeclarativeProfileParser.__name__ = class_name
    DeclarativeProfileParser.__qualname__ = class_name
    DeclarativeProfileParser.manifest = plugin_manifest
    return DeclarativeProfileParser


def validate_profile_payload(
    payload: dict[str, Any],
    *,
    sample_paths: Iterable[str | Path] = (),
    expected_results_ref: str | Path | None = None,
    origin_path: str | Path | None = None,
) -> ProfileValidationReport:
    checks = _profile_policy_checks(payload)
    plugin_id = profile_plugin_id(payload) or "unknown"
    contract_reports: list[ValidationReport] = []
    parser_cls: type | None = None
    if all(check.passed for check in checks):
        try:
            parser_cls = build_parser_class_from_profile(payload, origin_path=origin_path)
        except Exception as exc:
            checks.append(_check("profile_parser_class_builds", False, str(exc)))

    normalized_sample_paths = tuple(Path(path) for path in sample_paths)
    if parser_cls is not None:
        if normalized_sample_paths:
            for sample_path in normalized_sample_paths:
                report = validate_plugin_contract(
                    parser_cls,
                    sample_input_ref=sample_path,
                    parse_invoker=lambda parser: parser.parse_to_v2(),
                    expected_results_ref=expected_results_ref,
                )
                contract_reports.append(report)
                checks.append(
                    _check(
                        f"sample_{sample_path.name}_contract_validation",
                        report.passed,
                        "contract and expected-results validation",
                    )
                )
                probe = parser_cls.probe(
                    sample_path,
                    ProbeContext(source_path=str(sample_path), source_format=infer_source_format(sample_path)),
                )
                checks.append(
                    _check(
                        f"sample_{sample_path.name}_profile_probe_selected",
                        probe.can_parse and probe.confidence >= 80,
                        f"can_parse={probe.can_parse}, confidence={probe.confidence}",
                    )
                )
        else:
            report = validate_plugin_contract(parser_cls)
            contract_reports.append(report)
            checks.append(_check("profile_contract_validation", report.passed, "structural contract validation"))

    passed = all(check.passed for check in checks) and all(report.passed for report in contract_reports)
    return ProfileValidationReport(
        plugin_id=plugin_id,
        passed=passed,
        checks=tuple(checks),
        contract_reports=tuple(contract_reports),
    )


def validate_profile_file(
    path: str | Path,
    *,
    sample_paths: Iterable[str | Path] = (),
    expected_results_ref: str | Path | None = None,
) -> ProfileValidationReport:
    profile_path = Path(path)
    try:
        payload = load_profile_payload(profile_path)
    except Exception as exc:
        return ProfileValidationReport(
            plugin_id="unknown",
            passed=False,
            checks=(_check("profile_yaml_readable", False, str(exc)),),
        )
    checks = [_check("profile_yaml_readable", True)]
    report = validate_profile_payload(
        payload,
        sample_paths=sample_paths,
        expected_results_ref=expected_results_ref,
        origin_path=profile_path,
    )
    return ProfileValidationReport(
        plugin_id=report.plugin_id,
        passed=report.passed and all(check.passed for check in checks),
        checks=tuple(checks) + report.checks,
        contract_reports=report.contract_reports,
    )


def expected_sample_paths(workspace_dir: str | Path, expected_results_ref: str | Path) -> tuple[Path, ...]:
    workspace_path = Path(workspace_dir)
    samples_root = (workspace_path / "samples").resolve(strict=False)
    expected_path = Path(expected_results_ref)
    sample_names: list[str] = []
    with expected_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            sample_name = str(row.get("sample_file") or "").strip()
            if sample_name and sample_name not in sample_names:
                sample_names.append(sample_name)
    paths: list[Path] = []
    for sample_name in sample_names:
        sample_ref = Path(sample_name)
        if sample_ref.is_absolute() or ".." in sample_ref.parts:
            raise ValueError("expected-results sample_file entries must stay under samples/")
        candidate = (samples_root / sample_ref).resolve(strict=False)
        try:
            candidate.relative_to(samples_root)
        except ValueError as exc:
            raise ValueError("expected-results sample_file entries must stay under samples/") from exc
        paths.append(candidate)
    return tuple(paths)


def _approval_payload(
    *,
    profile_path: Path,
    validation_report: ProfileValidationReport,
    expected_results_ref: str | Path | None,
    sample_paths: Iterable[str | Path],
    approved_by: str,
) -> dict[str, Any]:
    profile_payload = load_profile_payload(profile_path)
    expected_hash = sha256_file(expected_results_ref) if expected_results_ref else None
    return {
        "schema_version": PROFILE_APPROVAL_SCHEMA_VERSION,
        "plugin_id": validation_report.plugin_id,
        "version": profile_version(profile_payload),
        "sha256": sha256_file(profile_path),
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "validation_passed": validation_report.passed,
        "validation_checks": [
            {"name": check.name, "passed": check.passed, "detail": check.detail}
            for check in validation_report.checks
        ],
        "sample_count": len(tuple(sample_paths)),
        "expected_results_sha256": expected_hash,
        "source_path": str(profile_path),
    }


def install_profile(
    profile_path: str | Path,
    *,
    sample_paths: Iterable[str | Path] = (),
    expected_results_ref: str | Path | None = None,
    approved_by: str = "operator",
    home: Path | None = None,
    dry_run: bool = False,
) -> ProfileInstallResult:
    source_profile_path = Path(profile_path)
    normalized_sample_paths = tuple(Path(path) for path in sample_paths)
    if expected_results_ref is None:
        raise ValueError("profile install requires an expected-results CSV")
    expected_results_path = Path(expected_results_ref)
    if not expected_results_path.is_file():
        raise ValueError(f"expected-results CSV not found: {expected_results_path}")
    if not normalized_sample_paths:
        raise ValueError("profile install requires at least one sample report")
    missing_samples = [str(path) for path in normalized_sample_paths if not path.is_file()]
    if missing_samples:
        raise ValueError(f"profile install sample reports not found: {', '.join(missing_samples)}")

    validation_report = validate_profile_file(
        source_profile_path,
        sample_paths=normalized_sample_paths,
        expected_results_ref=expected_results_path,
    )
    if not validation_report.passed:
        raise ValueError(f"profile validation failed for {validation_report.plugin_id}")

    ensure_profile_store_dirs(home=home)
    plugin_id = validation_report.plugin_id
    target_dir = approved_profiles_dir(home=home) / plugin_id
    target_profile = target_dir / PROFILE_FILE_NAME
    target_approval = target_dir / APPROVAL_FILE_NAME
    backup_dir: Path | None = None

    if target_dir.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = profile_backups_dir(home=home) / f"{plugin_id}-{stamp}"

    approval_payload = _approval_payload(
        profile_path=source_profile_path,
        validation_report=validation_report,
        expected_results_ref=expected_results_path,
        sample_paths=normalized_sample_paths,
        approved_by=approved_by,
    )
    profile_hash = approval_payload["sha256"]

    if dry_run:
        return ProfileInstallResult(plugin_id, target_dir, target_profile, target_approval, backup_dir, profile_hash)

    if backup_dir is not None:
        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target_dir), str(backup_dir))

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_profile_path, target_profile)
    target_approval.write_text(json.dumps(approval_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ProfileInstallResult(plugin_id, target_dir, target_profile, target_approval, backup_dir, profile_hash)


def _approval_matches(profile_path: Path, approval_path: Path) -> tuple[bool, str]:
    if not approval_path.exists():
        return False, "approval sidecar missing"
    try:
        payload = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"approval sidecar is not valid JSON: {exc}"
    if payload.get("schema_version") != PROFILE_APPROVAL_SCHEMA_VERSION:
        return False, "approval schema version is unsupported"
    if payload.get("validation_passed") is not True:
        return False, "approval does not record a passing validation"
    try:
        profile_payload = load_profile_payload(profile_path)
    except Exception as exc:
        return False, f"profile YAML is unreadable: {exc}"
    if str(payload.get("plugin_id") or "") != profile_plugin_id(profile_payload):
        return False, "approval plugin id does not match profile"
    expected_hash = str(payload.get("sha256") or "")
    actual_hash = sha256_file(profile_path)
    if expected_hash != actual_hash:
        return False, "approval checksum mismatch"
    return True, "approved"


def approved_profile_paths(*, home: Path | None = None) -> tuple[Path, ...]:
    root = approved_profiles_dir(home=home)
    if not root.exists():
        return ()
    paths: list[Path] = []
    for item in sorted(root.iterdir()):
        if item.is_dir() and (item / PROFILE_FILE_NAME).is_file():
            paths.append(item / PROFILE_FILE_NAME)
        elif item.is_file() and item.suffix in {".yaml", ".yml"}:
            paths.append(item)
    return tuple(paths)


def list_profiles(*, home: Path | None = None) -> tuple[InstalledProfile, ...]:
    installed: list[InstalledProfile] = []
    disabled_ids = disabled_plugin_ids()
    for profile_path in approved_profile_paths(home=home):
        approval_path = profile_path.parent / APPROVAL_FILE_NAME
        try:
            payload = load_profile_payload(profile_path)
            plugin_id = profile_plugin_id(payload)
        except Exception as exc:
            installed.append(
                InstalledProfile(
                    plugin_id=profile_path.parent.name,
                    profile_path=profile_path,
                    approval_path=approval_path if approval_path.exists() else None,
                    enabled=False,
                    approved=False,
                    detail=str(exc),
                )
            )
            continue
        approved, detail = _approval_matches(profile_path, approval_path)
        installed.append(
            InstalledProfile(
                plugin_id=plugin_id,
                profile_path=profile_path,
                approval_path=approval_path if approval_path.exists() else None,
                enabled=approved and plugin_id not in disabled_ids,
                approved=approved,
                detail=detail,
            )
        )
    disabled_root = disabled_profiles_dir(home=home)
    if disabled_root.exists():
        for item in sorted(disabled_root.iterdir()):
            profile_path = item / PROFILE_FILE_NAME if item.is_dir() else item
            if not profile_path.is_file() or profile_path.suffix not in {".yaml", ".yml"}:
                continue
            approval_path = profile_path.parent / APPROVAL_FILE_NAME
            try:
                plugin_id = profile_plugin_id(load_profile_payload(profile_path))
            except Exception:
                plugin_id = item.stem
            approved, detail = _approval_matches(profile_path, approval_path)
            installed.append(
                InstalledProfile(
                    plugin_id=plugin_id,
                    profile_path=profile_path,
                    approval_path=approval_path if approval_path.exists() else None,
                    enabled=False,
                    approved=approved,
                    detail="disabled" if approved else f"disabled: {detail}",
                )
            )
    return tuple(installed)


def disable_profile(plugin_id: str, *, home: Path | None = None) -> Path:
    plugin_id = _validate_plugin_id_for_store(plugin_id)
    ensure_profile_store_dirs(home=home)
    source_dir = approved_profiles_dir(home=home) / plugin_id
    target_dir = disabled_profiles_dir(home=home) / plugin_id
    if not source_dir.exists():
        raise FileNotFoundError(f"approved profile not found: {plugin_id}")
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.move(str(source_dir), str(target_dir))
    return target_dir


def enable_profile(plugin_id: str, *, home: Path | None = None) -> Path:
    plugin_id = _validate_plugin_id_for_store(plugin_id)
    ensure_profile_store_dirs(home=home)
    source_dir = disabled_profiles_dir(home=home) / plugin_id
    target_dir = approved_profiles_dir(home=home) / plugin_id
    if not source_dir.exists():
        raise FileNotFoundError(f"disabled profile not found: {plugin_id}")
    if target_dir.exists():
        raise FileExistsError(f"approved profile already exists: {plugin_id}")
    shutil.move(str(source_dir), str(target_dir))
    return target_dir


def rollback_profile(plugin_id: str, *, backup_name: str | None = None, home: Path | None = None) -> Path:
    plugin_id = _validate_plugin_id_for_store(plugin_id)
    ensure_profile_store_dirs(home=home)
    backup_root = profile_backups_dir(home=home)
    if backup_name:
        backup_ref = Path(backup_name)
        if backup_ref.is_absolute() or ".." in backup_ref.parts or not backup_name.startswith(f"{plugin_id}-"):
            raise ValueError("backup_name must name a backup for the selected plugin")
        backup_dir = backup_root / backup_name
    else:
        candidates = sorted(
            path
            for path in backup_root.glob(f"{plugin_id}-*")
            if "-rollback-current-" not in path.name
        )
        if not candidates:
            raise FileNotFoundError(f"no backup found for {plugin_id}")
        backup_dir = candidates[-1]
    backup_profile = backup_dir / PROFILE_FILE_NAME
    backup_approval = backup_dir / APPROVAL_FILE_NAME
    approved, detail = _approval_matches(backup_profile, backup_approval)
    if not approved:
        raise ValueError(f"backup profile is not approved: {detail}")
    target_dir = approved_profiles_dir(home=home) / plugin_id
    if target_dir.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.move(str(target_dir), str(profile_backups_dir(home=home) / f"{plugin_id}-rollback-current-{stamp}"))
    shutil.move(str(backup_dir), str(target_dir))
    restored, restored_detail = _approval_matches(target_dir / PROFILE_FILE_NAME, target_dir / APPROVAL_FILE_NAME)
    if not restored:
        raise ValueError(f"restored profile is not approved: {restored_detail}")
    return target_dir


def load_approved_profile_parsers(*, home: Path | None = None) -> tuple[tuple[str, type], tuple[str, ...]]:
    disabled_ids = disabled_plugin_ids()
    loaded: list[tuple[str, type]] = []
    errors: list[str] = []
    for profile_path in approved_profile_paths(home=home):
        approval_path = profile_path.parent / APPROVAL_FILE_NAME
        approved, detail = _approval_matches(profile_path, approval_path)
        if not approved:
            errors.append(f"{profile_path}: {detail}")
            continue
        try:
            payload = load_profile_payload(profile_path)
            plugin_id = profile_plugin_id(payload)
            if plugin_id in disabled_ids:
                continue
            report = validate_profile_payload(payload, origin_path=profile_path)
            if not report.passed:
                failed = ", ".join(check.name for check in report.checks if not check.passed)
                errors.append(f"{profile_path}: validation failed: {failed}")
                continue
            loaded.append((plugin_id, build_parser_class_from_profile(payload, origin_path=profile_path)))
        except Exception as exc:
            errors.append(f"{profile_path}: {exc}")
    return tuple(loaded), tuple(errors)


def profile_store_signature(*, home: Path | None = None) -> tuple[tuple[str, str, str], ...]:
    """Return checksum metadata for approved declarative profiles."""

    signature: list[tuple[str, str, str]] = []
    for profile_path in approved_profile_paths(home=home):
        approval_path = profile_path.parent / APPROVAL_FILE_NAME
        try:
            payload = load_profile_payload(profile_path)
            plugin_id = profile_plugin_id(payload) or profile_path.parent.name
            profile_hash = sha256_file(profile_path)
            approval_hash = sha256_file(approval_path) if approval_path.exists() else "missing"
        except OSError as exc:
            signature.append((profile_path.parent.name, "unreadable", str(exc)))
            continue
        except Exception as exc:
            signature.append((profile_path.parent.name, "invalid", str(exc)))
            continue
        signature.append((plugin_id, profile_hash, approval_hash))
    return tuple(sorted(signature))


def render_profile_template(*, plugin_id: str, display_name: str, source_format: str = "pdf") -> str:
    safe_plugin_id = re.sub(r"[^a-z0-9_]+", "_", plugin_id.strip().casefold()).strip("_")
    if not safe_plugin_id or not safe_plugin_id[0].isalpha():
        safe_plugin_id = f"supplier_{safe_plugin_id or 'profile'}"
    if len(safe_plugin_id) < 3:
        safe_plugin_id = f"{safe_plugin_id}_profile"
    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "plugin": {
            "plugin_id": safe_plugin_id[:64],
            "display_name": display_name,
            "version": "0.1.0",
            "source_format": source_format,
            "supported_locales": ["*"],
            "template_ids": ["default_template"],
            "priority": 900,
        },
        "probe": {
            "required_markers": ["SUPPLIER TEMPLATE MARKER"],
            "reject_markers": [],
            "confidence": 90,
        },
        "extraction": {
            "report_fields": {
                "reference": r"Reference:\s*(?P<value>\S+)",
                "report_date": r"Date:\s*(?P<value>\d{4}-\d{2}-\d{2})",
                "sample_number": r"Sample:\s*(?P<value>\S+)",
            },
            "blocks": [
                {
                    "header": "MAIN FEATURE",
                    "pattern": (
                        r"^DIM\s+(?P<axis_code>\w+)\s+(?P<nominal>[-0-9.,]+)\s+"
                        r"(?P<tol_plus>[-0-9.,]+)\s+(?P<tol_minus>[-0-9.,]+)\s+"
                        r"(?P<bonus>[-0-9.,]+|-)\s+(?P<measured>[-0-9.,]+)\s+"
                        r"(?P<deviation>[-0-9.,]+)\s+(?P<out_of_tolerance>[-0-9.,]+)$"
                    ),
                }
            ],
        },
        "normalization": {
            "decimal_separator": ".",
            "date_formats": ["%Y-%m-%d"],
            "missing_value_tokens": ["", "-", "NA", "N/A"],
        },
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


__all__ = [
    "APPROVAL_FILE_NAME",
    "PROFILE_FILE_NAME",
    "InstalledProfile",
    "ProfileCheck",
    "ProfileInstallResult",
    "ProfileValidationReport",
    "approved_profile_paths",
    "approved_profiles_dir",
    "build_parser_class_from_profile",
    "disable_profile",
    "enable_profile",
    "ensure_profile_store_dirs",
    "expected_sample_paths",
    "install_profile",
    "list_profiles",
    "load_approved_profile_parsers",
    "load_profile_payload",
    "profile_probe",
    "profile_store_signature",
    "profile_store_root",
    "render_profile_template",
    "rollback_profile",
    "sha256_file",
    "validate_profile_file",
    "validate_profile_payload",
]
