"""Scaffold and workspace helpers for LLM-assisted parser plugin creation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from modules.parser_plugin_paths import default_external_plugin_dir_display


@dataclass(frozen=True)
class PluginScaffoldArtifacts:
    analysis_prompt_template: str
    implementation_prompt_template: str
    plugin_template: str
    test_template: str


@dataclass(frozen=True)
class PluginWorkspaceWriteResult:
    output_dir: Path
    written_files: tuple[Path, ...]


def _default_display_name(plugin_id: str) -> str:
    words = [token for token in re.split(r"[_\-\s]+", str(plugin_id).strip()) if token]
    if not words:
        return "Generated Parser Plugin"
    return " ".join(word.capitalize() for word in words) + " Parser"


def _default_class_name(plugin_id: str) -> str:
    words = [token for token in re.split(r"[^A-Za-z0-9]+", str(plugin_id).strip()) if token]
    stem = "".join(word[:1].upper() + word[1:] for word in words) or "Generated"
    return f"{stem}ReportParser"


def _default_sample_name(source_format: str) -> str:
    extension = {
        "pdf": "pdf",
        "excel": "xlsx",
        "csv": "csv",
    }.get(str(source_format).strip().lower(), "txt")
    return f"sample_report_01.{extension}"


def _render_template(template: str, replacements: dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def build_plugin_scaffold() -> PluginScaffoldArtifacts:
    """Return baseline templates used by the LLM plugin factory workflow."""

    return PluginScaffoldArtifacts(
        analysis_prompt_template=(
            "# Analysis Prompt\n\n"
            "You are designing a Metroliza parser plugin candidate.\n"
            "You must stay inside the existing parser-plugin contract and must not invent new architecture.\n\n"
            "## Inputs you will receive\n"
            "- `supplier_intake.md`\n"
            "- one or more sample reports\n"
            "- `expected_results_template.csv` filled with key values the business user can verify\n\n"
            "## Your job\n"
            "1. Identify the report format and stable template cues.\n"
            "2. Propose a safe `probe(...)` strategy.\n"
            "3. Map source fields into `ParseResultV2`.\n"
            "4. List locale assumptions: decimal separators, dates, units, language, header aliases.\n"
            "5. Explain how to build `raw_text`, `blocks_text`, and final V2 measurement rows.\n"
            "6. List ambiguities, risks, and any extra samples needed.\n\n"
            "## Required output sections\n"
            "- Template summary\n"
            "- Manifest proposal\n"
            "- Probe strategy\n"
            "- Field mapping table\n"
            "- Parsing algorithm\n"
            "- Ambiguities and fallback policy\n"
            "- Questions for the user\n"
        ),
        implementation_prompt_template=(
            "# Implementation Prompt\n\n"
            "Implement a Metroliza parser plugin using only the approved scaffold files.\n"
            "Do not add new dependencies and do not change framework architecture.\n\n"
            "## Files you must return\n"
            "- `generated_plugin.py`\n"
            "- `tests/test_generated_plugin.py`\n\n"
            "## Hard constraints\n"
            "- Inherit both `BaseReportParser` and `BaseReportParserPlugin`.\n"
            "- Implement `probe`, `open_report`, `split_text_to_blocks`, `parse_to_v2`, and `to_legacy_blocks`.\n"
            "- Keep parsing deterministic.\n"
            "- Preserve the requested `plugin_id` and supported format.\n"
            "- Use `ParseResultV2` and nested dataclasses from `modules.parser_plugin_contracts`.\n"
            "- Use only stdlib plus imports already present in the approved scaffold.\n"
            "- Do not invent new runtime flags, registries, or base classes.\n\n"
            "## Output format\n"
            "Return complete file contents for each required file.\n"
            "Explain any assumptions briefly after the files.\n"
        ),
        plugin_template=(
            "from __future__ import annotations\n\n"
            "from pathlib import Path\n"
            "from time import strftime\n\n"
            "from modules.base_report_parser import BaseReportParser\n"
            "from modules.parser_plugin_contracts import (\n"
            "    BaseReportParserPlugin,\n"
            "    MeasurementBlockV2,\n"
            "    MeasurementV2,\n"
            "    ParseMetaV2,\n"
            "    ParseResultV2,\n"
            "    PluginManifest,\n"
            "    ProbeContext,\n"
            "    ProbeResult,\n"
            "    ReportInfoV2,\n"
            ")\n\n\n"
            "class {{CLASS_NAME}}(BaseReportParser, BaseReportParserPlugin):\n"
            "    manifest = PluginManifest(\n"
            "        plugin_id=\"{{PLUGIN_ID}}\",\n"
            "        display_name=\"{{DISPLAY_NAME}}\",\n"
            "        version=\"0.1.0\",\n"
            "        supported_formats=(\"{{SOURCE_FORMAT}}\",),\n"
            "        supported_locales=(\"*\",),\n"
            "        template_ids=(\"default\",),\n"
            "        priority=100,\n"
            "        capabilities={\"ocr_required\": False},\n"
            "    )\n\n"
            "    @classmethod\n"
            "    def probe(cls, input_ref: str | Path, context: ProbeContext) -> ProbeResult:\n"
            "        path_text = str(input_ref).lower()\n"
            "        if path_text.endswith(\".{{FILE_EXTENSION}}\"):\n"
            "            return ProbeResult(\n"
            "                plugin_id=cls.manifest.plugin_id,\n"
            "                can_parse=True,\n"
            "                confidence=70,\n"
            "                matched_template_id=\"default\",\n"
            "                reasons=(\"file_extension\",),\n"
            "            )\n"
            "        return ProbeResult(\n"
            "            plugin_id=cls.manifest.plugin_id,\n"
            "            can_parse=False,\n"
            "            confidence=0,\n"
            "            reasons=(\"unsupported_extension\",),\n"
            "        )\n\n"
            "    def open_report(self):\n"
            "        \"\"\"Populate `raw_text` from the source file deterministically.\"\"\"\n"
            "        report_path = Path(self.file_path) / self.file_name\n"
            "        raise NotImplementedError(f\"Implement raw-text extraction for {report_path}\")\n\n"
            "    def split_text_to_blocks(self):\n"
            "        \"\"\"Populate `blocks_text` using the legacy block shape.\n\n"
            "        Expected legacy row order:\n"
            "        [AX, NOM, +TOL, -TOL, BONUS, MEAS, DEV, OUTTOL]\n"
            "        \"\"\"\n"
            "        raise NotImplementedError(\"Implement deterministic block extraction\")\n\n"
            "    def parse_to_v2(self) -> ParseResultV2:\n"
            "        if not self.raw_text:\n"
            "            self.open_report()\n"
            "        if not self.blocks_text:\n"
            "            self.split_text_to_blocks()\n\n"
            "        blocks_v2: list[MeasurementBlockV2] = []\n"
            "        # TODO: convert `self.blocks_text` into `MeasurementBlockV2` items.\n"
            "        # Use one `MeasurementV2` per measurement row.\n\n"
            "        return ParseResultV2(\n"
            "            meta=ParseMetaV2(\n"
            "                source_file=str(Path(self.file_path) / self.file_name),\n"
            "                source_format=\"{{SOURCE_FORMAT}}\",\n"
            "                plugin_id=self.manifest.plugin_id,\n"
            "                plugin_version=self.manifest.version,\n"
            "                template_id=\"default\",\n"
            "                parse_timestamp=strftime(\"%Y-%m-%dT%H:%M:%SZ\"),\n"
            "                locale_detected=None,\n"
            "                confidence=70,\n"
            "            ),\n"
            "            report=ReportInfoV2(\n"
            "                reference=self.reference,\n"
            "                report_date=self.date,\n"
            "                sample_number=self.sample_number,\n"
            "                file_name=self.file_name,\n"
            "                file_path=self.file_path,\n"
            "            ),\n"
            "            blocks=tuple(blocks_v2),\n"
            "        )\n\n"
            "    @staticmethod\n"
            "    def to_legacy_blocks(parse_result_v2: ParseResultV2):\n"
            "        legacy_blocks = []\n"
            "        for block in parse_result_v2.blocks:\n"
            "            header = [list(block.header_raw)]\n"
            "            rows = []\n"
            "            for row in block.dimensions:\n"
            "                rows.append([\n"
            "                    row.axis_code,\n"
            "                    row.nominal,\n"
            "                    row.tol_plus,\n"
            "                    row.tol_minus,\n"
            "                    row.bonus,\n"
            "                    row.measured,\n"
            "                    row.deviation,\n"
            "                    row.out_of_tolerance,\n"
            "                ])\n"
            "            legacy_blocks.append([header, rows])\n"
            "        return legacy_blocks\n"
        ),
        test_template=(
            "from modules.parser_plugin_contracts import ParseResultV2\n\n"
            "from generated_plugin import {{CLASS_NAME}}\n\n\n"
            "def test_generated_plugin_contract_conformance(tmp_path):\n"
            "    sample_file = tmp_path / \"{{SAMPLE_FILE_NAME}}\"\n"
            "    sample_file.write_text(\"replace with a real sample during implementation\\n\", encoding=\"utf-8\")\n"
            "    parser = {{CLASS_NAME}}(str(sample_file), database=\":memory:\")\n"
            "    try:\n"
            "        parse_result = parser.parse_to_v2()\n"
            "    except NotImplementedError:\n"
            "        # Replace this stub branch once the plugin is implemented.\n"
            "        return\n"
            "    assert isinstance(parse_result, ParseResultV2)\n"
            "    assert parse_result.meta.plugin_id == \"{{PLUGIN_ID}}\"\n"
        ),
    )


def build_plugin_workspace_bundle(
    *,
    plugin_id: str,
    display_name: str | None = None,
    source_format: str = "pdf",
) -> dict[str, str]:
    """Build a ready-to-fill non-technical workspace bundle for one plugin."""

    normalized_plugin_id = str(plugin_id).strip()
    if not normalized_plugin_id:
        raise ValueError("plugin_id must be non-empty")

    normalized_source_format = str(source_format).strip().lower() or "pdf"
    normalized_display_name = str(display_name).strip() if display_name else _default_display_name(normalized_plugin_id)
    class_name = _default_class_name(normalized_plugin_id)
    sample_file_name = _default_sample_name(normalized_source_format)
    install_path = f"{default_external_plugin_dir_display()}/{normalized_plugin_id}.py"

    replacements = {
        "PLUGIN_ID": normalized_plugin_id,
        "DISPLAY_NAME": normalized_display_name,
        "SOURCE_FORMAT": normalized_source_format,
        "FILE_EXTENSION": sample_file_name.rsplit(".", 1)[-1],
        "CLASS_NAME": class_name,
        "SAMPLE_FILE_NAME": sample_file_name,
        "INSTALL_PATH": install_path,
    }
    scaffold = build_plugin_scaffold()

    workspace_readme = """# Parser Plugin Workspace

This folder is the complete working packet for one Metroliza parser plugin.

## What this workspace is for
- A non-technical user can prepare the business context and sample files.
- An LLM can use the prompts and scaffold here to generate the parser code.
- The generated parser can be validated and repaired with explicit commands.

## Step-by-step
1. Put 3-5 real sample reports into `samples/`.
2. Fill `supplier_intake.md`.
3. Fill `expected_results_template.csv` with the key values you can verify manually.
4. Upload the sample reports, `supplier_intake.md`, `expected_results_template.csv`, and `prompts/01_analysis_prompt.md` to your LLM.
5. Save the LLM analysis into `responses/analysis_response.md`.
6. Upload `responses/analysis_response.md`, `prompts/02_implementation_prompt.md`, `generated_plugin.py`, and `tests/test_generated_plugin.py` to the LLM.
7. Paste the returned file contents into `generated_plugin.py` and `tests/test_generated_plugin.py`.
8. Validate the generated plugin:

```bash
python scripts/validate_parser_plugins.py --paths generated_plugin.py --plugin-id {{PLUGIN_ID}} --sample-input samples/{{SAMPLE_FILE_NAME}}
```

9. If validation fails, generate a repair prompt:

```bash
python scripts/build_parser_plugin_repair_prompt.py --paths generated_plugin.py --plugin-id {{PLUGIN_ID}} --sample-input samples/{{SAMPLE_FILE_NAME}} --output artifacts/repair_prompt.md
```

10. Re-run the LLM using `artifacts/repair_prompt.md`, then validate again.
11. After validation passes, install the parser by copying `generated_plugin.py` to `{{INSTALL_PATH}}`.
12. Restart Metroliza and load a report from the new supplier. The parser factory will probe the file and select this plugin when it matches.

## Runtime loading
- Metroliza automatically discovers parser plugins placed in `{{INSTALL_PATH}}`.
- Advanced override: `PARSER_EXTERNAL_PLUGIN_PATHS` can still point to extra plugin files or folders.

## Human approval checklist
- Reference, date, and sample number are correct.
- Key measurements match the expected results file.
- Validation passes.
- Warnings are understandable and acceptable.
- Pilot rollout plan is prepared before broad activation.
"""

    supplier_intake = """# Supplier Intake

Fill this before asking the LLM to design the parser.

## Supplier identity
- Supplier name:
- Internal owner:
- Country or region:
- Main language on report:

## Report format
- Source format (`pdf`, `excel`, `csv`):
- Known template name or label:
- Any version string shown on the report:

## Locale and formatting notes
- Decimal separator (`.` or `,`):
- Date format examples:
- Units used in the report:
- Header aliases or multilingual labels:

## Parsing expectations
- Which fields are mandatory:
- Which fields are optional:
- How tolerance is shown:
- How repeated measurement blocks are separated:

## Known risks
- OCR needed or not:
- Known bad samples:
- Known ambiguous labels:
"""

    expected_results_template = """sample_file,reference,report_date,sample_number,block_index,header_normalized,axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance
{{SAMPLE_FILE_NAME}},REF123,2026-01-05,0001,0,MAIN FEATURE,X,10.0,0.1,-0.1,,10.02,0.02,0
"""

    samples_readme = """Place 3-5 representative sample reports in this folder.

Use real reports from the same supplier and same template family when possible.
Include at least one sample that clearly shows dates, tolerances, and multiple measurement rows.
"""

    analysis_response = """# Analysis Response

Paste the LLM analysis here after Step 4.
"""

    review_checklist = """# Review Checklist

- Does the probe strategy look specific enough to avoid false matches?
- Does the mapping table cover reference, report date, sample number, headers, and measurements?
- Does the parser avoid new dependencies?
- Does the parser keep deterministic behavior?
- Are the warnings and ambiguities explained clearly?
"""

    return {
        "README.md": _render_template(workspace_readme, replacements),
        "supplier_intake.md": _render_template(supplier_intake, replacements),
        "expected_results_template.csv": _render_template(expected_results_template, replacements),
        "artifacts/README.md": "Place generated repair prompts and validation evidence in this folder.\n",
        "samples/README.md": _render_template(samples_readme, replacements),
        "responses/analysis_response.md": _render_template(analysis_response, replacements),
        "prompts/01_analysis_prompt.md": _render_template(scaffold.analysis_prompt_template, replacements),
        "prompts/02_implementation_prompt.md": _render_template(scaffold.implementation_prompt_template, replacements),
        "generated_plugin.py": _render_template(scaffold.plugin_template, replacements),
        "tests/test_generated_plugin.py": _render_template(scaffold.test_template, replacements),
        "review_checklist.md": _render_template(review_checklist, replacements),
    }


def write_plugin_workspace(
    output_dir: str | Path,
    *,
    plugin_id: str,
    display_name: str | None = None,
    source_format: str = "pdf",
    overwrite: bool = False,
) -> PluginWorkspaceWriteResult:
    """Write a parser-plugin workspace bundle to disk."""

    target_dir = Path(output_dir)
    if target_dir.exists() and any(target_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Workspace already exists and is not empty: {target_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_plugin_workspace_bundle(
        plugin_id=plugin_id,
        display_name=display_name,
        source_format=source_format,
    )

    written_files: list[Path] = []
    for relative_path, contents in bundle.items():
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
        written_files.append(destination)

    return PluginWorkspaceWriteResult(
        output_dir=target_dir,
        written_files=tuple(written_files),
    )
