# Pass 3 — Plugin Registry, Detection, and Orchestration

## Goal
Design runtime selection of the right plugin for diverse report formats and global template variations.

## Required outputs
1. Registry design for first-party plugins (extensible for external plugins later).
2. Multi-stage detection flow (fast probe + deep probe).
3. Deterministic tie-breaking and fallback rules.
4. Parse thread orchestration integration plan.

## Detection strategy

### Stage 0: Format routing
- Infer probable format from extension and quick sniff.
- Route candidate set by format family (`pdf`, `excel`, `csv`).

### Stage 1: Fast probe
- Filename patterns, metadata hints, known sheet names, header tokens.
- Low-cost checks only.

### Stage 2: Deep probe (on narrowed candidates)
- Parse minimal content slice (first page/sheet/chunk).
- Evaluate template anchors and locale hints.

### Selection rule
- Max by `confidence`.
- Tie-break by plugin `priority`.
- Final tie-break by deterministic plugin id ordering.
- If confidence below threshold, either reject or parse with explicit fallback warning.

## Registry behavior
- Built-in registration for in-repo plugins.
- Optional external plugin entrypoint support planned, not required in first release.
- Registry must expose:
  - list plugins
  - filter by format
  - resolve parser for file
  - diagnostics for why plugin was selected/rejected

## Orchestration impact
- Parsing thread should no longer hardcode a single parser implementation.
- Replace parser factory with plugin resolver call.
- Maintain existing dedup and DB write flow during transition.

## Acceptance criteria
- Selection process reproducible and deterministic.
- Ambiguous matches are logged with rationale.
- Unsupported templates produce actionable diagnostics.

## Risks
- False positives in probe logic.
- Expensive deep probe over large batches.

## Fallback
- Strict confidence thresholds + fallback to default compatible parser with warning.
- Cache probe results per file path per run.

## Current implementation notes (repo status)
- Probe results are cached per `(plugin_id, source_path)` during process lifetime in `modules/report_parser_factory.py` and reset on registration changes.
- Strict confidence thresholding is controlled by `PARSER_STRICT_MATCHING` (`true/1/on/yes`):
  - disabled (default): candidates with confidence `>= 1` can be selected,
  - enabled: candidates must have confidence `>= 80`.
- Resolver diagnostics include explicit rejection reasons for unsupported inputs (`no_plugin_can_parse`) and threshold failures (`no_plugin_above_confidence_threshold`).

## Jira seed checklist
- [x] Define registry API and plugin loading sequence.
- [x] Define probe context object and caching policy.
- [x] Define selection tie-break policy and thresholds.
- [ ] Define parse-thread integration points.
- [x] Define diagnostics/logging payload for selection events.
- [ ] Define unsupported-template handling path.
