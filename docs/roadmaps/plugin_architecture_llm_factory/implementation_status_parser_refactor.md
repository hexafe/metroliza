# Implementation Status: Parser Refactor (Contracts + Registry + LLM Factory Base)

## Scope covered
This implementation now aligns runtime with roadmap Pass 1 / Pass 2 / Pass 3 and establishes Pass 4 baseline assets by introducing:
- parser plugin contracts (`BaseReportParserPlugin`, `PluginManifest`, `ProbeResult`),
- canonical schema dataclasses (`ParseResultV2` and nested models),
- deterministic parser plugin resolver and registry diagnostics,
- CMM parser V2 parse entrypoint and V2→legacy adapter,
- baseline LLM plugin factory scaffold (analysis + implementation prompt templates and plugin/test skeletons).

## What is now implemented
1. **Pass 1 foundations and interfaces**
   - Plugin manifest, probe result, warning/error, and base parser plugin interface are codified.
   - `parse_to_v2(...)` + `to_legacy_blocks(...)` contracts are formalized for migration-safe plugin development.

2. **Pass 2 canonical V2 schema and adapters**
   - V2 canonical dataclasses are implemented for metadata, report identity, block, and measurement fields.
   - CMM parser now emits `ParseResultV2` and can adapt back into legacy `blocks_text` structure.

3. **Pass 3 registry + detection + orchestration baseline**
   - Registry is driven by plugin manifest metadata and class-level probes.
   - Resolver selection uses deterministic tie-break rules (`confidence`, then manifest `priority`, then `plugin_id`).
   - Diagnostics payloads are available for selection/rejection visibility.

4. **Pass 4 LLM-assisted plugin factory base**
   - Baseline scaffold helper returns generation templates for analysis prompt, implementation prompt, plugin skeleton, and fixture test skeleton.
   - This provides the required extension point for introducing a full two-pass generation and validation gate later.

## Compatibility decisions
- Kept legacy aliases (`pdf_*`) in parser base to avoid breaking historical callsites/tests.
- Kept `cmm_open()` alias for older workflows.
- Preserved `get_parser(...)` and `detect_format(...)` factory APIs for compatibility while migrating internals to plugin resolution.
- Preserved legacy `register_parser(format_id, parser_cls, detector=..., manifest=...)` usage while also supporting new class-first registration.

## Enablement assets
- Added a non-technical plugin creation quickstart to support business users during supplier onboarding.

## Deferred roadmap items
The following roadmap items remain future work (outside this refactor slice):
- full adapter equivalence matrix and lossy conversion registry governance,
- external plugin package loading/entrypoint discovery,
- full validation gate automation for generated plugins,
- end-to-end repair loop workflow and governance process for LLM-generated parser candidates.
