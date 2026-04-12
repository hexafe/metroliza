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
   - Probe result caching is active per `(plugin_id, source_path)` to avoid repeated probe calls in long parse runs.
   - Strict confidence gating is supported via `PARSER_STRICT_MATCHING` for higher-safety selection behavior.

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
- end-to-end repair loop workflow and governance process for LLM-generated parser candidates.

## Verification snapshot (2026-03-14)
After reviewing the current code paths and targeted tests, the status is:

- **Parser refactoring completion:** **Substantially complete for Pass 1–3 baseline** and usable in runtime.
  - Contracts (`BaseReportParserPlugin`, `PluginManifest`, `ProbeResult`, `ParseResultV2`) are implemented.
  - Registry/detection/resolution and compatibility registration paths are implemented and test-covered.
  - CMM parser implements `parse_to_v2(...)` + `to_legacy_blocks(...)` and remains backward-compatible with existing entrypoints.
- **LLM plugin build readiness:** **Partially ready (foundation ready, production workflow not complete).**
  - A baseline LLM scaffold exists (`build_plugin_scaffold`) with prompt and template assets.
  - However, roadmap Pass 4/5 operational gates remain incomplete (automated validation gate workflow, repair loop automation, external plugin loading/discovery, governance/runbook integration).

### Readiness verdict
- **Ready now for internal/pilot LLM-assisted plugin prototyping** against the existing contract and scaffold.
- **Not yet fully ready for broad production rollout** of LLM-generated plugins until deferred Pass 4/5 controls are implemented.

### Highest-priority next actions
1. Expand validation gate from baseline contract checks to fixture semantic parity and deterministic-output assertions in CI.
2. Extend entrypoint-based external plugin loading with signature/allowlist hardening for production environments.
3. Integrate repair-loop artifact generation into an automated candidate-regeneration workflow.
4. Add runtime monitoring dashboards/alerts for parse failures, fallback spikes, and unresolved field drifts.

## Newly implemented from verification follow-up
- Added external plugin discovery/loading via `PARSER_EXTERNAL_PLUGIN_PATHS` in `modules/report_parser_factory.py` (supports file or directory inputs).
- Added a baseline automated validation gate utility in `modules/parser_plugin_validation.py` with a runnable script `scripts/validate_parser_plugins.py`.
- Added tests covering external plugin loading and validation gate behavior.
- Added entrypoint-based plugin discovery (`metroliza.parser_plugins`) in `modules/report_parser_factory.py`.
- Added repair-loop prompt artifact helpers in `modules/parser_plugin_repair_loop.py` and script `scripts/build_parser_plugin_repair_prompt.py`.
- Added rollout/rollback + ownership governance checklist in `docs/release_checks/parser_plugin_rollout_runbook.md` and linked it from `docs/ci-policy.md`.
