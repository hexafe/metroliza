"""Baseline scaffold generator for LLM-assisted parser plugin creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginScaffoldArtifacts:
    analysis_prompt_template: str
    implementation_prompt_template: str
    plugin_template: str
    test_template: str


def build_plugin_scaffold() -> PluginScaffoldArtifacts:
    """Return baseline templates used by the LLM plugin factory workflow."""

    return PluginScaffoldArtifacts(
        analysis_prompt_template=(
            "Analyze sample reports and produce mapping table to ParseResultV2, "
            "locale assumptions, probe strategy, and ambiguity handling."
        ),
        implementation_prompt_template=(
            "Implement plugin using approved scaffold only. Include manifest, probe, "
            "parse_to_v2, and to_legacy_blocks without architecture changes."
        ),
        plugin_template=(
            "class GeneratedReportParser(BaseReportParser, BaseReportParserPlugin):\n"
            "    manifest = PluginManifest(...)\n"
            "    @classmethod\n"
            "    def probe(cls, input_ref, context): ...\n"
            "    def parse_to_v2(self): ...\n"
            "    @staticmethod\n"
            "    def to_legacy_blocks(parse_result_v2): ...\n"
        ),
        test_template=(
            "def test_generated_plugin_contract_conformance():\n"
            "    assert parser.parse_to_v2() is not None\n"
        ),
    )
