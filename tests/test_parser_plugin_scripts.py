import importlib
import importlib.util
import json
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

def _load_script_module(script_name: str):
    script_path = REPO_ROOT / "scripts" / script_name
    module_name = f"test_{script_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _snapshot_factory_state():
    factory_module = importlib.import_module("metroliza.reports.report_parser_factory")
    return factory_module, {
        "map": dict(factory_module.PARSER_MAP),
        "manifests": dict(factory_module.PARSER_MANIFESTS),
        "detectors": dict(factory_module.PARSER_DETECTORS),
        "cache": dict(factory_module.PROBE_RESULT_CACHE),
        "loaded": factory_module._EXTERNAL_PLUGINS_LOADED,
        "signature": factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE,
        "entry_points": factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS,
        "env": os.environ.get("PARSER_EXTERNAL_PLUGIN_PATHS"),
    }


def _restore_factory_state(factory_module, snapshot):
    if snapshot["env"] is None:
        os.environ.pop("PARSER_EXTERNAL_PLUGIN_PATHS", None)
    else:
        os.environ["PARSER_EXTERNAL_PLUGIN_PATHS"] = snapshot["env"]
    factory_module.PARSER_MAP.clear()
    factory_module.PARSER_MAP.update(snapshot["map"])
    factory_module.PARSER_MANIFESTS.clear()
    factory_module.PARSER_MANIFESTS.update(snapshot["manifests"])
    factory_module.PARSER_DETECTORS.clear()
    factory_module.PARSER_DETECTORS.update(snapshot["detectors"])
    factory_module.PROBE_RESULT_CACHE.clear()
    factory_module.PROBE_RESULT_CACHE.update(snapshot["cache"])
    factory_module._EXTERNAL_PLUGINS_LOADED = snapshot["loaded"]
    factory_module._EXTERNAL_PLUGIN_CONFIG_SIGNATURE = snapshot["signature"]
    factory_module._EXTERNAL_PLUGIN_ENTRY_POINTS = snapshot["entry_points"]


def _completed_supplier_alpha_plugin() -> str:
    return '''
from __future__ import annotations

from pathlib import Path

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
)


class SupplierAlphaReportParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="supplier_alpha",
        display_name="Supplier Alpha Parser",
        version="0.1.0",
        supported_formats=("pdf",),
        supported_locales=("*",),
        template_ids=("synthetic_fixture",),
        priority=1000,
        capabilities={"ocr_required": False},
    )

    @classmethod
    def probe(cls, input_ref: str | Path, context: ProbeContext) -> ProbeResult:
        if (context.source_format or "").lower() not in cls.manifest.supported_formats:
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=False,
                confidence=0,
                reasons=("unsupported_source_format",),
            )

        try:
            sample_text = Path(input_ref).read_text(encoding="utf-8").casefold()
        except OSError:
            sample_text = ""

        if "synthetic supplier alpha" not in sample_text:
            return ProbeResult(
                plugin_id=cls.manifest.plugin_id,
                can_parse=False,
                confidence=0,
                reasons=("missing_synthetic_fixture_marker",),
            )

        return ProbeResult(
            plugin_id=cls.manifest.plugin_id,
            can_parse=True,
            confidence=92,
            matched_template_id="synthetic_fixture",
            reasons=("source_format_match", "synthetic_fixture_marker"),
        )

    def open_report(self):
        report_path = Path(self.file_path) / self.file_name
        self.raw_text = report_path.read_text(encoding="utf-8").splitlines()

    def split_text_to_blocks(self):
        self.reference = "REF123"
        self.date = "2026-01-05"
        self.sample_number = "0001"
        self.blocks_text = [
            [["MAIN FEATURE"], [["X", 10.0, 0.1, -0.1, None, 10.02, 0.02, 0.0]]],
        ]

    def parse_to_v2(self) -> ParseResultV2:
        if not self.raw_text:
            self.open_report()
        if not self.blocks_text:
            self.split_text_to_blocks()

        return ParseResultV2(
            meta=ParseMetaV2(
                source_file=str(Path(self.file_path) / self.file_name),
                source_format="pdf",
                plugin_id=self.manifest.plugin_id,
                plugin_version=self.manifest.version,
                template_id="synthetic_fixture",
                parse_timestamp="2026-01-01T00:00:00Z",
                locale_detected=None,
                confidence=92,
            ),
            report=ReportInfoV2(
                reference="REF123",
                report_date="2026-01-05",
                sample_number="0001",
                file_name=self.file_name,
                file_path=self.file_path,
            ),
            blocks=(
                MeasurementBlockV2(
                    header_raw=("MAIN FEATURE",),
                    header_normalized="MAIN FEATURE",
                    dimensions=(
                        MeasurementV2(
                            axis_code="X",
                            nominal=10.0,
                            tol_plus=0.1,
                            tol_minus=-0.1,
                            bonus=None,
                            measured=10.02,
                            deviation=0.02,
                            out_of_tolerance=0.0,
                        ),
                    ),
                    block_index=0,
                ),
            ),
        )

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
'''


def test_create_parser_plugin_workspace_script_creates_workspace(tmp_path, capsys):
    module = _load_script_module("create_parser_plugin_workspace.py")
    output_dir = tmp_path / "workspace"

    result = module.main(["--plugin-id", "supplier_alpha", "--output-dir", str(output_dir)])
    output = capsys.readouterr().out

    assert result == 0
    assert (output_dir / "README.md").exists()
    assert (output_dir / "generated_plugin.py").exists()
    assert (output_dir / "artifacts" / "README.md").exists()
    assert (output_dir / "handoff_manifest.json").exists()
    assert (output_dir / "reference" / "contract_snippets.md").exists()
    assert (output_dir / "prompts" / "microtasks" / "01_template_analysis.md").exists()
    manifest = json.loads((output_dir / "handoff_manifest.json").read_text(encoding="utf-8"))
    assert manifest["package_type"] == "python_plugin"
    assert manifest["plugin_id"] == "supplier_alpha"
    assert "NON_TECHNICAL_STEPS.md" in output
    assert "prompts/microtasks/" in output


def test_generated_workspace_plugin_validates_and_resolves_from_explicit_path(
    tmp_path,
    capsys,
    monkeypatch,
):
    create_module = _load_script_module("create_parser_plugin_workspace.py")
    validate_module = _load_script_module("validate_parser_plugins.py")
    diagnostics_module = _load_script_module("explain_parser_resolution.py")
    parser_plugin_paths = importlib.import_module("metroliza.parsing.parser_plugin_paths")
    workspace_dir = tmp_path / "supplier_alpha_workspace"

    create_result = create_module.main(
        [
            "--plugin-id",
            "supplier_alpha",
            "--source-format",
            "pdf",
            "--output-dir",
            str(workspace_dir),
        ]
    )
    sample_file = workspace_dir / "samples" / "sample_report_01.pdf"
    sample_file.write_text("SYNTHETIC SUPPLIER ALPHA\nfixture-only report\n", encoding="utf-8")
    plugin_file = workspace_dir / "generated_plugin.py"
    plugin_file.write_text(_completed_supplier_alpha_plugin(), encoding="utf-8")

    factory_module, snapshot = _snapshot_factory_state()
    try:
        validate_result = validate_module.main(
            [
                "--paths",
                str(plugin_file),
                "--plugin-id",
                "supplier_alpha",
                "--sample-input",
                str(sample_file),
                "--expected-results",
                str(workspace_dir / "expected_results_template.csv"),
            ]
        )
    finally:
        _restore_factory_state(factory_module, snapshot)

    validate_output = capsys.readouterr().out
    assert create_result == 0
    assert validate_result == 0
    assert "[PASS] supplier_alpha" in validate_output
    assert "Validation passed for all selected parser plugins." in validate_output

    factory_module, snapshot = _snapshot_factory_state()
    try:
        def _env_only_plugin_paths(raw_paths=None, include_default_dir=True, home=None):
            return parser_plugin_paths.split_external_plugin_paths(
                os.environ.get(parser_plugin_paths.PARSER_EXTERNAL_PLUGIN_PATHS_ENV, "")
            )

        monkeypatch.delenv("PARSER_EXTERNAL_PLUGIN_PATHS", raising=False)
        monkeypatch.delenv("PARSER_STRICT_MATCHING", raising=False)
        monkeypatch.setattr(factory_module, "_iter_external_plugin_entry_points", lambda: ())
        monkeypatch.setattr(
            parser_plugin_paths,
            "configured_external_plugin_path_entries",
            _env_only_plugin_paths,
        )
        factory_module.reset_external_plugin_loader_state()
        factory_module.reset_probe_cache()

        diagnostics_result = diagnostics_module.main([str(sample_file), "--paths", str(plugin_file)])
    finally:
        _restore_factory_state(factory_module, snapshot)

    diagnostics_output = capsys.readouterr().out
    assert diagnostics_result == 0
    assert "Selection threshold: 80" in diagnostics_output
    assert "supplier_alpha" in diagnostics_output
    assert "synthetic_fixture_marker" in diagnostics_output
    assert "Selected: supplier_alpha" in diagnostics_output


def test_validate_parser_plugins_script_accepts_explicit_plugin_file(tmp_path):
    module = _load_script_module("validate_parser_plugins.py")
    plugin_file = tmp_path / "demo_external_plugin.py"
    plugin_file.write_text(
        """
from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import BaseReportParserPlugin, PluginManifest, ProbeContext, ProbeResult

class DemoExternalParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="demo_external_script",
        display_name="Demo External Script",
        version="1.0.0",
        supported_formats=("pdf",),
    )

    @classmethod
    def probe(cls, _input_ref, _context: ProbeContext) -> ProbeResult:
        return ProbeResult(plugin_id=cls.manifest.plugin_id, can_parse=True, confidence=75)

    def open_report(self):
        self.raw_text = ["ok"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
""",
        encoding="utf-8",
    )

    factory_module, snapshot = _snapshot_factory_state()
    try:
        result = module.main(["--paths", str(plugin_file), "--plugin-id", "demo_external_script"])
    finally:
        _restore_factory_state(factory_module, snapshot)

    assert result == 0


def test_validate_parser_plugins_script_accepts_expected_results_csv(tmp_path):
    module = _load_script_module("validate_parser_plugins.py")
    plugin_file = tmp_path / "demo_semantic_plugin.py"
    plugin_file.write_text(
        """
from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import (
    BaseReportParserPlugin,
    MeasurementBlockV2,
    MeasurementV2,
    ParseMetaV2,
    ParseResultV2,
    PluginManifest,
    ProbeResult,
    ReportInfoV2,
)


class DemoSemanticParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="demo_semantic_script",
        display_name="Demo Semantic Script",
        version="1.0.0",
        supported_formats=("pdf",),
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        return ProbeResult(plugin_id="demo_semantic_script", can_parse=True, confidence=90)

    def open_report(self):
        self.raw_text = ["ok"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        return ParseResultV2(
            meta=ParseMetaV2(
                source_file="sample_report_01.pdf",
                source_format="pdf",
                plugin_id="demo_semantic_script",
                plugin_version="1.0.0",
                template_id="default",
                parse_timestamp="2026-01-01T00:00:00Z",
                locale_detected=None,
                confidence=90,
            ),
            report=ReportInfoV2(
                reference="REF123",
                report_date="2026-01-05",
                sample_number="0001",
                file_name="sample_report_01.pdf",
                file_path=".",
            ),
            blocks=(
                MeasurementBlockV2(
                    header_raw=("MAIN FEATURE",),
                    header_normalized="MAIN FEATURE",
                    dimensions=(
                        MeasurementV2(
                            axis_code="X",
                            nominal=10.0,
                            tol_plus=0.1,
                            tol_minus=-0.1,
                            bonus=None,
                            measured=10.02,
                            deviation=0.02,
                            out_of_tolerance=0.0,
                        ),
                    ),
                    block_index=0,
                ),
            ),
        )

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
""",
        encoding="utf-8",
    )
    sample_file = tmp_path / "sample_report_01.pdf"
    sample_file.write_text("placeholder\n", encoding="utf-8")
    expected_results = tmp_path / "expected_results_template.csv"
    expected_results.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0\n",
        encoding="utf-8",
    )

    factory_module, snapshot = _snapshot_factory_state()
    try:
        result = module.main(
            [
                "--paths",
                str(plugin_file),
                "--plugin-id",
                "demo_semantic_script",
                "--sample-input",
                str(sample_file),
                "--expected-results",
                str(expected_results),
            ]
        )
    finally:
        _restore_factory_state(factory_module, snapshot)

    assert result == 0


def test_build_parser_plugin_repair_prompt_script_writes_artifact_for_failed_validation(tmp_path):
    module = _load_script_module("build_parser_plugin_repair_prompt.py")
    plugin_file = tmp_path / "bad_external_plugin.py"
    plugin_file.write_text(
        """
from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import BaseReportParserPlugin, PluginManifest

class BadExternalParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="bad_external_script",
        display_name="Bad External Script",
        version="1.0.0",
        supported_formats=("pdf",),
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        return "bad"

    def open_report(self):
        self.raw_text = ["ok"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        raise NotImplementedError

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "repair_prompt.md"

    factory_module, snapshot = _snapshot_factory_state()
    try:
        result = module.main(
            [
                "--paths",
                str(plugin_file),
                "--plugin-id",
                "bad_external_script",
                "--output",
                str(output_path),
            ]
        )
    finally:
        _restore_factory_state(factory_module, snapshot)

    assert result == 1
    assert output_path.exists()
    prompt_text = output_path.read_text(encoding="utf-8")
    assert "probe_returns_probe_result" in prompt_text
    assert "PluginManifest" in prompt_text
    assert "ParseResultV2" in prompt_text
    assert "sample_file,reference,report_date" in prompt_text
    assert "complete updated file contents" in prompt_text.casefold()


def test_build_parser_plugin_repair_prompt_script_includes_semantic_mismatch_checks(tmp_path):
    module = _load_script_module("build_parser_plugin_repair_prompt.py")
    plugin_file = tmp_path / "semantic_mismatch_plugin.py"
    plugin_file.write_text(
        """
from modules.base_report_parser import BaseReportParser
from modules.parser_plugin_contracts import (
    BaseReportParserPlugin,
    MeasurementBlockV2,
    MeasurementV2,
    ParseMetaV2,
    ParseResultV2,
    PluginManifest,
    ProbeResult,
    ReportInfoV2,
)


class SemanticMismatchParser(BaseReportParser, BaseReportParserPlugin):
    manifest = PluginManifest(
        plugin_id="semantic_mismatch_script",
        display_name="Semantic Mismatch Script",
        version="1.0.0",
        supported_formats=("pdf",),
    )

    @classmethod
    def probe(cls, _input_ref, _context):
        return ProbeResult(plugin_id="semantic_mismatch_script", can_parse=True, confidence=90)

    def open_report(self):
        self.raw_text = ["ok"]

    def split_text_to_blocks(self):
        self.blocks_text = []

    def parse_to_v2(self):
        return ParseResultV2(
            meta=ParseMetaV2(
                source_file="sample_report_01.pdf",
                source_format="pdf",
                plugin_id="semantic_mismatch_script",
                plugin_version="1.0.0",
                template_id="default",
                parse_timestamp="2026-01-01T00:00:00Z",
                locale_detected=None,
                confidence=90,
            ),
            report=ReportInfoV2(
                reference="REF123",
                report_date="2026-01-05",
                sample_number="0001",
                file_name="sample_report_01.pdf",
                file_path=".",
            ),
            blocks=(
                MeasurementBlockV2(
                    header_raw=("MAIN FEATURE",),
                    header_normalized="MAIN FEATURE",
                    dimensions=(
                        MeasurementV2(
                            axis_code="X",
                            nominal=10.0,
                            tol_plus=0.1,
                            tol_minus=-0.1,
                            bonus=None,
                            measured=10.5,
                            deviation=0.5,
                            out_of_tolerance=1.0,
                        ),
                    ),
                    block_index=0,
                ),
            ),
        )

    @staticmethod
    def to_legacy_blocks(_parse_result_v2):
        return []
""",
        encoding="utf-8",
    )
    sample_file = tmp_path / "sample_report_01.pdf"
    sample_file.write_text("placeholder\n", encoding="utf-8")
    expected_results = tmp_path / "expected_results_template.csv"
    expected_results.write_text(
        "sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
        "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "repair_prompt.md"

    factory_module, snapshot = _snapshot_factory_state()
    try:
        result = module.main(
            [
                "--paths",
                str(plugin_file),
                "--plugin-id",
                "semantic_mismatch_script",
                "--sample-input",
                str(sample_file),
                "--expected-results",
                str(expected_results),
                "--output",
                str(output_path),
            ]
        )
    finally:
        _restore_factory_state(factory_module, snapshot)

    assert result == 1
    assert output_path.exists()
    assert "expected_results_" in output_path.read_text(encoding="utf-8")
