"""Validation gate helpers for parser plugin contract conformance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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


def validate_plugin_contract(
    parser_cls: type,
    sample_input_ref: str | Path = "sample.pdf",
    parse_invoker: Callable[[BaseReportParserPlugin], ParseResultV2] | None = None,
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
        try:
            plugin_instance = parser_cls(str(sample_input_ref), database=":memory:")
            if not isinstance(plugin_instance, BaseReportParser):
                checks.append(_check("parser_inherits_base_report_parser", False, "plugin should also inherit BaseReportParser"))
            parse_result = parse_invoker(plugin_instance)
            checks.append(_check("parse_to_v2_returns_parse_result_v2", isinstance(parse_result, ParseResultV2)))
            if isinstance(parse_result, ParseResultV2):
                legacy_blocks = parser_cls.to_legacy_blocks(parse_result)
                checks.append(_check("legacy_adapter_returns_list", isinstance(legacy_blocks, list)))
        except Exception as exc:
            checks.append(_check("parse_validation_execution", False, f"parse validation raised exception: {exc}"))

    passed = all(check.passed for check in checks)
    return ValidationReport(plugin_id=plugin_id, passed=passed, checks=tuple(checks))
