"""Validation gate helpers for parser plugin contract conformance."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Callable

from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import (
    BaseReportParserPlugin,
    ParseResultV2,
    PluginManifest,
    ProbeContext,
    ProbeResult,
    infer_source_format,
)


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ValidationReport:
    plugin_id: str
    passed: bool
    checks: tuple[ValidationCheck, ...]


def _check(name: str, passed: bool, detail: str = "") -> ValidationCheck:
    return ValidationCheck(name=name, passed=passed, detail=detail)


def _normalize_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_casefold_text(value) -> str | None:
    text = _normalize_text(value)
    return text.casefold() if text is not None else None


def _normalize_header_text(value) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    return " ".join(text.split())


def _parse_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    text = _normalize_text(value)
    if text is None:
        return None

    candidate = text.replace(" ", "").replace("_", "").replace("'", "")
    lowered = candidate.casefold()
    if lowered in {"-", "none", "null", "na", "n/a", "nan"}:
        return None
    if "," in candidate and "." in candidate:
        candidate = candidate.replace(",", "")
    elif "," in candidate:
        candidate = candidate.replace(",", ".")

    try:
        return float(candidate)
    except ValueError:
        return None


def _parse_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = _normalize_text(value)
    if text is None:
        return None

    try:
        return int(text)
    except ValueError:
        numeric_value = _parse_float(text)
        return None if numeric_value is None else int(numeric_value)


def _slugify_for_check(value) -> str:
    text = _normalize_text(value)
    if text is None:
        return "unknown"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text.casefold()).strip("_")
    return slug or "unknown"


def _load_expected_results_rows(expected_results_ref: str | Path) -> tuple[list[dict[str, str]], tuple[ValidationCheck, ...]]:
    checks: list[ValidationCheck] = []
    expected_path = Path(expected_results_ref)
    if not expected_path.exists():
        checks.append(_check("expected_results_file_present", False, f"file not found: {expected_path}"))
        return [], tuple(checks)

    try:
        with expected_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
    except Exception as exc:
        checks.append(_check("expected_results_csv_readable", False, f"failed to read CSV: {exc}"))
        return [], tuple(checks)

    required_columns = (
        "sample_file",
        "reference",
        "report_date",
        "sample_number",
        "block_index",
        "header_normalized",
        "axis_code",
        "nominal",
        "tol_plus",
        "tol_minus",
        "bonus",
        "measured",
        "deviation",
        "out_of_tolerance",
    )
    missing_columns = tuple(column for column in required_columns if column not in fieldnames)
    checks.append(
        _check(
            "expected_results_required_columns_present",
            not missing_columns,
            "" if not missing_columns else f"missing columns: {', '.join(missing_columns)}",
        )
    )
    normalized_rows: list[dict[str, str]] = []
    for row_index, row in enumerate(rows, start=2):
        normalized_row = {key: (value if value is not None else "") for key, value in row.items()}
        normalized_row["__row_number__"] = str(row_index)
        normalized_rows.append(normalized_row)

    return normalized_rows, tuple(checks)


def _row_matches_sample_file(row: dict[str, str], sample_file_name: str) -> bool:
    sample_file_value = _normalize_text(row.get("sample_file"))
    if sample_file_value is None:
        return False
    return Path(sample_file_value).name.casefold() == sample_file_name.casefold()


def _extract_actual_rows(parse_result: ParseResultV2) -> dict[tuple[int, str, str], dict[str, object]]:
    actual_rows: dict[tuple[int, str, str], dict[str, object]] = {}
    for block in parse_result.blocks:
        header_normalized = _normalize_header_text(block.header_normalized) or ""
        for row in block.dimensions:
            key = (
                int(block.block_index),
                header_normalized.casefold(),
                _normalize_casefold_text(row.axis_code) or "",
            )
            actual_rows[key] = {
                "row": row,
                "block_index": int(block.block_index),
                "header_normalized": header_normalized,
            }
    return actual_rows


def _compare_text_field(
    *,
    check_name: str,
    expected_value,
    actual_value,
    normalize_expected=None,
    normalize_actual=None,
) -> ValidationCheck:
    expected_normalizer = normalize_expected or _normalize_text
    actual_normalizer = normalize_actual or _normalize_text
    expected_text = expected_normalizer(expected_value)
    actual_text = actual_normalizer(actual_value)
    passed = expected_text == actual_text
    detail = f"expected={expected_text!r}, actual={actual_text!r}"
    return _check(check_name, passed, detail)


def _compare_numeric_field(*, check_name: str, expected_value, actual_value) -> ValidationCheck:
    expected_number = _parse_float(expected_value)
    actual_number = _parse_float(actual_value)
    passed = expected_number is None and actual_number is None
    if expected_number is not None and actual_number is not None:
        passed = math.isclose(expected_number, actual_number, rel_tol=1e-9, abs_tol=1e-6)
    detail = f"expected={expected_number!r}, actual={actual_number!r}"
    return _check(check_name, passed, detail)


def _compare_optional_int_field(*, check_name: str, expected_value, actual_value) -> ValidationCheck:
    expected_number = _parse_int(expected_value)
    actual_number = _parse_int(actual_value)
    passed = expected_number == actual_number
    detail = f"expected={expected_number!r}, actual={actual_number!r}"
    return _check(check_name, passed, detail)


def _build_expected_results_checks(
    parse_result: ParseResultV2,
    *,
    sample_input_ref: str | Path,
    expected_results_ref: str | Path,
) -> tuple[ValidationCheck, ...]:
    checks: list[ValidationCheck] = []
    expected_rows, load_checks = _load_expected_results_rows(expected_results_ref)
    checks.extend(load_checks)
    if not expected_rows:
        return tuple(checks)

    sample_file_name = Path(sample_input_ref).name
    sample_rows = [row for row in expected_rows if _row_matches_sample_file(row, sample_file_name)]
    checks.append(
        _check(
            "expected_results_sample_rows_found",
            bool(sample_rows),
            "" if sample_rows else f"no rows matched sample_file={sample_file_name}",
        )
    )
    if not sample_rows:
        return tuple(checks)

    first_row = sample_rows[0]
    checks.append(
        _compare_text_field(
            check_name="expected_results_report_reference_matches",
            expected_value=first_row.get("reference"),
            actual_value=parse_result.report.reference,
        )
    )
    checks.append(
        _compare_text_field(
            check_name="expected_results_report_date_matches",
            expected_value=first_row.get("report_date"),
            actual_value=parse_result.report.report_date,
        )
    )
    checks.append(
        _compare_text_field(
            check_name="expected_results_report_sample_number_matches",
            expected_value=first_row.get("sample_number"),
            actual_value=parse_result.report.sample_number,
        )
    )

    actual_rows = _extract_actual_rows(parse_result)
    for row in sample_rows:
        row_number = row.get("__row_number__", "?")
        block_index = _parse_int(row.get("block_index"))
        header_normalized = _normalize_header_text(row.get("header_normalized")) or ""
        axis_code = _normalize_casefold_text(row.get("axis_code")) or ""
        row_key = (block_index if block_index is not None else -1, header_normalized.casefold(), axis_code)
        row_label = f"row_{row_number}_b{row_key[0]}_{_slugify_for_check(header_normalized)}_{_slugify_for_check(axis_code)}"
        actual_entry = actual_rows.get(row_key)
        if actual_entry is None:
            checks.append(
                _check(
                    f"expected_results_{row_label}_present",
                    False,
                    f"missing actual row for block_index={block_index}, header_normalized={header_normalized!r}, axis_code={axis_code!r}",
                )
            )
            continue

        checks.append(_check(f"expected_results_{row_label}_present", True))
        checks.append(
            _compare_text_field(
                check_name=f"expected_results_{row_label}_axis_code_matches",
                expected_value=row.get("axis_code"),
                actual_value=actual_entry["row"].axis_code,
                normalize_expected=_normalize_casefold_text,
                normalize_actual=_normalize_casefold_text,
            )
        )
        checks.append(
            _compare_optional_int_field(
                check_name=f"expected_results_{row_label}_block_index_matches",
                expected_value=row.get("block_index"),
                actual_value=actual_entry["block_index"],
            )
        )
        checks.append(
            _compare_text_field(
                check_name=f"expected_results_{row_label}_header_normalized_matches",
                expected_value=row.get("header_normalized"),
                actual_value=actual_entry["header_normalized"],
                normalize_expected=_normalize_header_text,
                normalize_actual=_normalize_header_text,
            )
        )
        checks.append(
            _compare_numeric_field(
                check_name=f"expected_results_{row_label}_nominal_matches",
                expected_value=row.get("nominal"),
                actual_value=actual_entry["row"].nominal,
            )
        )
        checks.append(
            _compare_numeric_field(
                check_name=f"expected_results_{row_label}_tol_plus_matches",
                expected_value=row.get("tol_plus"),
                actual_value=actual_entry["row"].tol_plus,
            )
        )
        checks.append(
            _compare_numeric_field(
                check_name=f"expected_results_{row_label}_tol_minus_matches",
                expected_value=row.get("tol_minus"),
                actual_value=actual_entry["row"].tol_minus,
            )
        )
        checks.append(
            _compare_numeric_field(
                check_name=f"expected_results_{row_label}_bonus_matches",
                expected_value=row.get("bonus"),
                actual_value=actual_entry["row"].bonus,
            )
        )
        checks.append(
            _compare_numeric_field(
                check_name=f"expected_results_{row_label}_measured_matches",
                expected_value=row.get("measured"),
                actual_value=actual_entry["row"].measured,
            )
        )
        checks.append(
            _compare_numeric_field(
                check_name=f"expected_results_{row_label}_deviation_matches",
                expected_value=row.get("deviation"),
                actual_value=actual_entry["row"].deviation,
            )
        )
        checks.append(
            _compare_numeric_field(
                check_name=f"expected_results_{row_label}_out_of_tolerance_matches",
                expected_value=row.get("out_of_tolerance"),
                actual_value=actual_entry["row"].out_of_tolerance,
            )
        )

    return tuple(checks)


def validate_plugin_contract(
    parser_cls: type,
    sample_input_ref: str | Path = "sample.pdf",
    parse_invoker: Callable[[BaseReportParserPlugin], ParseResultV2] | None = None,
    expected_results_ref: str | Path | None = None,
) -> ValidationReport:
    """Run baseline contract validation checks for a parser plugin class.

    The default path performs structural checks and probe validation without parsing
    report content. If ``parse_invoker`` is provided, parse/adapter checks are added.
    """

    checks: list[ValidationCheck] = []
    plugin_id = getattr(getattr(parser_cls, "manifest", None), "plugin_id", getattr(parser_cls, "__name__", "unknown"))

    checks.append(
        _check(
            "is_parser_plugin_subclass",
            isinstance(parser_cls, type) and issubclass(parser_cls, BaseReportParserPlugin),
            "class must inherit BaseReportParserPlugin",
        )
    )

    manifest = getattr(parser_cls, "manifest", None)
    checks.append(
        _check(
            "manifest_instance",
            isinstance(manifest, PluginManifest),
            "manifest must be PluginManifest",
        )
    )

    if isinstance(manifest, PluginManifest):
        checks.append(_check("manifest_plugin_id_present", bool(manifest.plugin_id.strip()), "plugin_id must be non-empty"))
        checks.append(
            _check(
                "manifest_supported_formats_present",
                len(manifest.supported_formats) > 0,
                "supported_formats must contain at least one format",
            )
        )

    probe_ok = False
    try:
        context = ProbeContext(source_path=str(sample_input_ref), source_format=infer_source_format(sample_input_ref))
        probe_result = parser_cls.probe(str(sample_input_ref), context)
        probe_ok = isinstance(probe_result, ProbeResult)
        checks.append(_check("probe_returns_probe_result", probe_ok, "probe must return ProbeResult"))
        if probe_ok:
            checks.append(
                _check(
                    "probe_plugin_id_matches_manifest",
                    probe_result.plugin_id == plugin_id,
                    "probe_result.plugin_id should match manifest.plugin_id",
                )
            )
            checks.append(
                _check(
                    "probe_confidence_range",
                    0 <= probe_result.confidence <= 100,
                    "confidence should be in [0, 100]",
                )
            )
    except Exception as exc:
        checks.append(_check("probe_execution", False, f"probe raised exception: {exc}"))

    if parse_invoker is not None:
        parse_result: ParseResultV2 | None = None
        try:
            plugin_instance = parser_cls(str(sample_input_ref), database=":memory:")
            if not isinstance(plugin_instance, BaseReportParser):
                checks.append(_check("parser_inherits_base_report_parser", False, "plugin should also inherit BaseReportParser"))
            parse_result = parse_invoker(plugin_instance)
            parse_result_ok = isinstance(parse_result, ParseResultV2)
            checks.append(_check("parse_to_v2_returns_parse_result_v2", parse_result_ok))
            if parse_result_ok:
                legacy_blocks = parser_cls.to_legacy_blocks(parse_result)
                checks.append(_check("legacy_adapter_returns_list", isinstance(legacy_blocks, list)))
                if expected_results_ref is not None:
                    checks.extend(
                        _build_expected_results_checks(
                            parse_result,
                            sample_input_ref=sample_input_ref,
                            expected_results_ref=expected_results_ref,
                        )
                    )
        except Exception as exc:
            checks.append(_check("parse_validation_execution", False, f"parse validation raised exception: {exc}"))
    elif expected_results_ref is not None:
        checks.append(
            _check(
                "expected_results_requires_parse_invoker",
                False,
                "expected-results comparison requires parse_invoker to be provided",
            )
        )

    passed = all(check.passed for check in checks)
    return ValidationReport(plugin_id=plugin_id, passed=passed, checks=tuple(checks))
