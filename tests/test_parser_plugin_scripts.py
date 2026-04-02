import importlib
import importlib.machinery
import importlib.util
import os
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

custom_logger_stub = types.ModuleType("modules.custom_logger")


class _DummyCustomLogger:
    def __init__(self, *_args, **_kwargs):
        pass


custom_logger_stub.CustomLogger = _DummyCustomLogger
sys.modules.setdefault("modules.custom_logger", custom_logger_stub)

fitz_stub = types.ModuleType("fitz")
fitz_stub.__spec__ = importlib.machinery.ModuleSpec("fitz", loader=None)
fitz_stub.open = lambda *_args, **_kwargs: None
sys.modules.setdefault("fitz", fitz_stub)


def _load_script_module(script_name: str):
    script_path = REPO_ROOT / "scripts" / script_name
    module_name = f"test_{script_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _snapshot_factory_state():
    factory_module = importlib.import_module("modules.report_parser_factory")
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


def test_create_parser_plugin_workspace_script_creates_workspace(tmp_path):
    module = _load_script_module("create_parser_plugin_workspace.py")
    output_dir = tmp_path / "workspace"

    result = module.main(["--plugin-id", "supplier_alpha", "--output-dir", str(output_dir)])

    assert result == 0
    assert (output_dir / "README.md").exists()
    assert (output_dir / "generated_plugin.py").exists()
    assert (output_dir / "artifacts" / "README.md").exists()


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
    assert "probe_returns_probe_result" in output_path.read_text(encoding="utf-8")
