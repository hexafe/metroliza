# #1134 — frozen compute workers

Authority: supplied Issue #1134 and execution instructions; local-only work on
`feat/1134-frozen-compute-workers`, from RC2 candidate
`67a5fea10eee0607ed711503f0872fd9183ffd88`. No remote operations authorized.
Whole-PR class: FEATURE / CROSS-LAYER (packaging, process ownership, both pools,
Windows qualification). Coordinator only; runtime model/reasoning: not visible.
Sources: AGENTS.md, project README/architecture/development workflow, branch policy,
AI routing and packet/report templates, OCR worker/spec, identity/audit/probe,
both pools, portable qualification, startup route measurement and portable CI job.

## MUST

- Dedicated compute executable dispatches freeze support before application code;
  no Qt runtime/hooks. Frozen pools use its validated package identity with spawn.
- Preserve source behavior, ordered results, parent-only persistence/workbook ownership,
  bounded queues, serial fallback and supervised descendant cleanup.
- Register immutable component and explicitly verify owned compute topology.
- Add self-checking built supervised Windows qualification: >=40 Extended-plots
  groups and >=200 synthetic PDFs, forced on/off, equivalence, median-of-three
  timings, effective worker use and uploaded receipt. Keep existing qualifications.
- Run affected files, complexity/coverage/security gates and Ruff; commit locally.

## SHOULD

- Share executable selection; reject missing/modified packages before pool launch.
- Keep measurement fixtures synthetic and report performance/calibration honestly.

## DEFERRED

- Parallel preflight (Issue #1134 deferred seam); migrations, releases and remote work.
- Windows execution is unavailable here. Proposed Windows defaults require the
  Windows receipt before they can be described as calibrated or release-qualified.

## Validation and handoff

Base snapshot and pre-edit synthetic reference outputs are captured under the
session scratch `codex/1134` directory (archive of HEAD, no second worktree).
The handoff records exact commands/results, comparison, source head and remaining
Windows-only proof. Independent exact-head review and all remote CI belong to the
external orchestrator. Stop before any unapproved remote/destructive operation.
