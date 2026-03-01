# Pass 1 — Foundations and Interfaces

## Goal
Define the baseline plugin architecture contract and freeze interface expectations before implementation.

## Why this pass exists
Without a strict contract, generated plugins and manual plugins will diverge. This pass establishes a single contract that all future plugins must satisfy.

## Required outputs
1. **Plugin interface specification** (`BaseReportParserPlugin` contract).
2. **Parser result contract entrypoint** (`parse_to_v2(...) -> ParseResultV2`).
3. **Capability metadata contract** (`PluginManifest`).
4. **Error/warning model** for parser and detection outcomes.
5. **Versioning rules** for interface evolution.

## Interface blueprint (spec-level)

### 1) Plugin manifest (metadata)
Each plugin must declare:
- `plugin_id`: unique, immutable id (e.g., `pcdimsv1`, `supplier_xyz_cn_v1`)
- `display_name`
- `version`
- `supported_formats`: one or more of `pdf|excel|csv`
- `supported_locales`: e.g., `en`, `zh-CN`, `de`, `pl`, `*`
- `template_ids`: known templates/signatures
- `priority`: integer for match tie-breakers
- `capabilities`: feature flags (e.g., OCR required, table extraction mode)

### 2) Plugin detection interface
- `probe(input_ref, context) -> ProbeResult`
- `ProbeResult` includes:
  - `can_parse: bool`
  - `confidence: int (0..100)`
  - `matched_template_id: str | None`
  - `reasons: list[str]`
  - `warnings: list[str]`

### 3) Plugin parse interface
- `parse_to_v2(input_ref, context) -> ParseResultV2`
- Must return canonical V2 schema only.
- Must never return legacy positional structures directly.

### 4) Compatibility interface
- `to_legacy_blocks(parse_result_v2) -> legacy_pdf_blocks_text_shape`
- Used only during migration and parity validation.

### 5) Diagnostics interface
- Structured logging hooks:
  - template matched / fallback used
  - low-confidence parse
  - unresolved fields / assumptions applied

## Acceptance criteria
- Interface contracts are documented and approved.
- Naming/versioning conventions are frozen.
- Plugin lifecycle documented (detect → parse → validate → persist).
- Architecture review completed with no open blockers.

## Risks
- Over-designing contracts before practical plugin implementation.
- Missing fields needed by future templates.

## Fallback
- Keep contract minimal and additive.
- Use explicit `extensions: dict[str, Any]` area in V2 for forward compatibility.

## Jira seed checklist
- [ ] Define `PluginManifest` schema.
- [ ] Define `ProbeResult` schema.
- [ ] Define `ParseResultV2` top-level contract.
- [ ] Define parser plugin base interface methods.
- [ ] Define compatibility adapter interface.
- [ ] Publish interface versioning policy.
