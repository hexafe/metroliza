# Pass 2 — V2 Schema and Compatibility Adapters

## Goal
Define canonical V2 parsing schema and adapter rules that ensure backward compatibility.

## Required outputs
1. Canonical schema field catalog with type/null policy.
2. `legacy -> v2` adapter spec.
3. `v2 -> legacy` adapter spec.
4. Semantic equivalence rules and known lossy edge cases.

## Canonical schema draft (spec-level)

### ParseResultV2
- `meta`
  - `source_file`
  - `source_format`
  - `plugin_id`
  - `plugin_version`
  - `template_id`
  - `parse_timestamp`
  - `locale_detected`
  - `confidence`
- `report`
  - `reference`
  - `report_date`
  - `sample_number`
  - `file_name`
  - `file_path`
- `blocks: list[MeasurementBlockV2]`
- `warnings: list[ParseWarning]`
- `errors: list[ParseError]`

### MeasurementBlockV2
- `header_raw: list[str]`
- `header_normalized: str`
- `dimensions: list[MeasurementV2]`
- `block_index: int`

### MeasurementV2
- `axis_code: str`
- `nominal: float | None`
- `tol_plus: float | None`
- `tol_minus: float | None`
- `bonus: float | None`
- `measured: float | None`
- `deviation: float | None`
- `out_of_tolerance: float | None`
- `raw_tokens: list[str]`
- `raw_line_refs: list[int]`
- `extensions: dict[str, str | float | int | bool | None]`

## Null / empty policy
- Use `None` for unknown/missing numeric values.
- Use `0` only when explicitly present as semantic zero (not inferred absence).
- Use empty string only for human-readable optional text fields where blank is meaningful.
- Preserve raw values in `raw_tokens` when normalization is uncertain.

## Adapter policy

### Legacy -> V2
- Map positional indexes deterministically into named numeric fields.
- Record provenance in `raw_tokens` if reconstructable.
- Preserve header text and block boundaries exactly.

### V2 -> Legacy
- Required for migration only.
- Convert missing numeric values to legacy-compatible placeholders per existing behavior.
- Document any intentionally lossy conversions.

## Acceptance criteria
- V2 field table approved across parsing + DB + export stakeholders.
- Adapter equivalence test matrix approved.
- Known lossy cases documented and accepted.

## Risks
- Ambiguity when legacy placeholders (`""`, `"0"`, `0`) are overloaded.
- Template-specific semantics may not map 1:1.

## Fallback
- Preserve source semantics in `extensions` and warnings until dedicated mapping rules are added.

## Jira seed checklist
- [ ] Publish V2 schema table with field types.
- [ ] Publish null/placeholder policy.
- [ ] Define legacy->V2 mapping table by index.
- [ ] Define V2->legacy mapping table by field.
- [ ] Define semantic parity test cases.
- [ ] Define lossy conversion register.
