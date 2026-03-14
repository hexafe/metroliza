# Pass 4 — LLM-Assisted Plugin Factory

## Goal
Define a safe, repeatable system for generating new template plugins from sample reports + prompt + baseline template.

## Global supplier requirement
This factory must support global supplier variability (not only Chinese), including language, locale, units, delimiters, and formatting diversity.

## Factory concept
Use a controlled generation pipeline:
1. Intake sample reports.
2. Build structured context package.
3. Run two-pass LLM workflow (design pass, then code pass).
4. Execute contract + fixture + performance tests.
5. Accept/reject generated plugin.

## Inputs to generation
- Supplier sample bundle (PDF/Excel/CSV and expected outputs when available).
- Baseline plugin template scaffold.
- Interface contract docs (Pass 1).
- V2 schema + adapter policy (Pass 2).
- Detection/registry rules (Pass 3).

## Two-pass generation policy

### Pass A: Analysis only
LLM outputs:
- mapping table (source tokens/columns -> V2 fields),
- locale assumptions,
- tolerance interpretation rules,
- ambiguity and fallback policy,
- probe strategy.

### Pass B: Implementation draft
LLM outputs plugin code using baseline scaffold only.
No architecture invention allowed outside approved extension points.

## Mandatory baseline plugin scaffold requirements
- Manifest + parser class skeleton.
- `probe(...)` and `parse_to_v2(...)` method signatures.
- Locale normalization helpers (unicode, decimal/date parsing, header aliases).
- Structured warnings/errors helper.
- Fixture-driven test template.

## Validation gate (must pass)
- Contract conformance tests.
- Fixture semantic parity tests.
- Legacy compatibility adapter tests.
- Native/python parity where applicable.
- Performance and determinism thresholds.

## Observability requirements
- Log selected plugin id/version/template.
- Log confidence and fallback reason.
- Log unresolved field counts and normalization warnings.

## Security and safety controls
- Generated plugins are untrusted until tests pass.
- No dynamic code execution from report content.
- Dependency usage restricted to approved package list.
- Require human review before activation.

## Acceptance criteria
- Factory can generate a candidate plugin package from a supplier sample bundle.
- Generated plugin is either accepted by gates or rejected with actionable failure report.
- Re-run with same inputs is reproducible.

## Risks
- Hallucinated mappings on sparse sample sets.
- Locale-specific edge cases missed in training examples.

## Fallback
- Require minimum fixture diversity before generation.
- Route failed candidates into repair loop with failing diffs as context.

## Jira seed checklist
- [ ] Create generation context pack format.
- [x] Create baseline plugin scaffold.
- [x] Create analysis-pass prompt template.
- [x] Create implementation-pass prompt template.
- [x] Implement validation gate script/workflow (baseline contract gate).
- [ ] Implement repair loop policy and artifacts.
