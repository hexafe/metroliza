# #1110 — diagnostic timing and native-control evidence

## Execution packet

Authority: [#1110](https://github.com/hexafe/metroliza/issues/1110), including the
owner's comment extending scope to runtime-audit and qualification controls, and
the external orchestrator's session packet. Base: `82f8f57653964dd344fac7c01a84d9ab303cdaac`
(RC1); work branch: `fix/1110-windows-timing-tests`. The explicit RC1 packet
overrides the normal develop starting point. No PR base is selected locally.

Objective: assert bounded diagnostic shutdown and native-control ordering without
depending on shared-runner startup, storage latency, or process teardown scheduling.

Whole-PR class: BOUNDED INTEGRATION; coordinator requested by the external packet:
GPT-6.1 Sol (Codex); reasoning not specified. Actual runtime model/reasoning:
not visible. Coordinator-only execution: shared test/fixture context makes
delegation unnecessary. No workers or model substitutions.

Owned scope: `tests/test_diagnostic_launcher.py`,
`tests/test_windows_runtime_audit.py`, `tests/test_windows_diagnostic_qualification.py`,
their existing synthetic fixtures, and this evidence record. Product launcher or
qualification changes require a demonstrated product defect within #1110.

Sources read: root `AGENTS.md`, project README/architecture/development workflow,
branching strategy, model-routing playbook, task-packet and routing-report templates.

### MUST

1. Classify every reported test failure with source evidence and preserve real
   child exit, publication state, ordering, native identity and cleanup checks.
2. Preserve the 750 ms product close budget; use synchronization or controlled
   clocks instead of increasing bounds, skips, retries or xfail.
3. Run related files and the required complexity, coverage, security and Ruff gates
   with the external packet's crash-safe pytest command.
4. Commit locally on the current branch with issue references and the required
   co-author trailer. Remote reads only; no push, PR, merge or workflow dispatch.
5. Five consecutive Windows core-smoke dispatches on the final fix head remain
   required acceptance evidence owned by the external orchestrator.

### SHOULD

Search other Windows elapsed-time assertions for the same test-design defect;
record remaining seams without expanding into unrelated runtime behavior.

### DEFERRED

Moving qualification into a non-blocking job remains outside #1110. Windows,
frozen-build and hosted-run acceptance cannot be performed on this Linux host;
this is an outstanding gate, not an approved waiver of MUST 5.

Preserved contracts: canonical imports, local-first behavior, private synthetic
diagnostics, bounded I/O and deterministic cleanup. No customer data, migrations,
native optimizations, release actions or security-baseline regeneration.

## Evidence ledger

Baseline on the exact base above: related three files, **512 passed, 21 skipped**
(pre-existing Windows-only applicability guards). No Linux failure reproduced.
Results and classification below will bind final changes to concrete checks.
