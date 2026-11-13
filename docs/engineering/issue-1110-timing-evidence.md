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

## Per-test classification

All reported cases are test defects by the contracts below. No product defect
was established by these failures. This classification is source/log reasoning;
the changed native fixtures still require Windows execution.

Line references in this table identify the base commit unless marked **fix**.
Launcher source is unchanged, so its line references apply to both trees.

| Test | Classification and evidence | Fix and retained assertion |
| --- | --- | --- |
| `test_stalled_store_io_is_bounded_and_preserves_actual_child_exit[end_session-normal-0]` (and begin/publish variants) | Test: base `tests/test_diagnostic_launcher.py:890-910` auto-releases the stall at 3 s and measures the entire child launch. `src/metroliza/app/diagnostic_launcher.py:284-293` starts the close budget only after supervision returns. Thus 3.27 s total cannot establish a close-bound breach. | Hold I/O until explicit test cleanup; require the actual child exit and `PUBLISH_INCOMPLETE` while the worker is still held. Join that worker before fixture teardown. **Fix** `tests/test_diagnostic_launcher.py:953`. |
| `test_stalled_disk_publisher_returns_unknown_completion_with_bounded_queue` | Test: base `tests/test_diagnostic_launcher.py:749-764` waits just 1 s for publish entry although `_publish_live` first performs marker/authentication I/O (`src/metroliza/app/diagnostic_launcher.py:224-225`). Its 3 s auto-release and elapsed-time assertion also mix scheduling with the property. | Establish authenticated storage before scheduling the live item; use an entry event as the precondition, then hold publication through close. Check the one-live-slot rejection, final-slot priority and incomplete worker state. The readiness watchdog is outside the tested close interval. **Fix** `tests/test_diagnostic_launcher.py:798`. |
| `test_inflight_begin_finishes_before_final_incident_is_persisted` | Test: base `tests/test_diagnostic_launcher.py:843-874` synchronizes entry to close but requires main-thread release, worker scheduling and real disk publication within 750 ms. A saved result at exactly 750 ms is valid: close returns `SAVED` when `final_saved` is set (`src/metroliza/app/diagnostic_launcher.py:272-275`). | Use a test-local logical clock/completion scheduler; retain the real worker and store. Require `begin_entered → begin_finished → publish`, saved/done state and marker resolution. Release and join on assertion failure too. **Fix** `tests/test_diagnostic_launcher.py:870`. |
| `test_diagnostic_thread_exhaustion_does_not_prevent_actual_app_start[diagnostic-receiver]` | Test: base `tests/test_diagnostic_launcher.py:1028-1048` requires cold incident persistence within close despite testing thread-start failure. [Run 39122548015](https://github.com/hexafe/metroliza/actions/runs/39122548015) records actual exit 0, missing handshake and incomplete storage. `src/metroliza/app/diagnostic_launcher.py:274-275` explicitly permits that storage state. | Controlled completion scheduling isolates persistence from disk latency; preserve actual packaged-entry source startup, exit 0, missing handshake and saved incident. Publisher-start exhaustion still requires `IO_FAILED`. **Fix** `tests/test_diagnostic_launcher.py:1112`. |
| `test_real_exit_publishes_same_session_incident_and_selected_export` | Test: base `tests/test_diagnostic_launcher.py:165-187` requires final store I/O to complete within close; its trace explicitly reports publication still in flight at 750 ms. The marker barrier separates authentication but cannot guarantee final disk latency. | Controlled completion scheduling retains real child/transport/store/export, session identity, event ownership, marker cleanup and redaction checks. **Fix** `tests/test_diagnostic_launcher.py:220`. |
| `test_native_journal_correlates_owned_roles_and_survives_hard_exit[late_other]` | Test: base fixture `tests/fixtures/windows_runtime_audit_control.py:44-45` launches a short-lived shell; base `tests/test_windows_runtime_audit.py:823` repeatedly queries its image. [Run 39122548015](https://github.com/hexafe/metroliza/actions/runs/39122548015) records `image/false/job_observation`, error 31, **after all three roles were already verified**. A still-listed retiring PID does not guarantee image-query availability. Production correctly refuses unsupported identity evidence. | Hold the unrelated shell on stdin until the host observes application/cmd/conhost; stop image queries after explicit acknowledgement. Require exact `other_command` journal event/phase, all three roles, no unobserved/unavailable members, empty Job, and rejection by `verified_runtime_order`. Applies to the same `other` control too. **Fix** `tests/fixtures/windows_runtime_audit_control.py:43`, `tests/test_windows_runtime_audit.py:698,898,937`. |
| `test_native_gui_stdio_facts_distinguish_redirected_handles_from_console[attached]` | Test: [run 39084988780](https://github.com/hexafe/metroliza/actions/runs/39084988780) fails in base `tests/test_windows_diagnostic_qualification.py:6380`: `active_processes()` performs fresh identity queries (`scripts/qualify_windows_diagnostics.py:956-958`) after pythonw has exited and its console helper is retiring. Stdio facts require drain accounting, not image attribution. | Read native Job active accounting to establish zero remaining processes, preserve exit 0 and every stdio/console fact, and keep owned-process cleanup. No production identity fallback was relaxed. **Fix** `tests/test_windows_diagnostic_qualification.py:6385`. |
| `test_scenario_uses_fixed_receipt_and_closes_completed_job` | Test: [run 39083721084](https://github.com/hexafe/metroliza/actions/runs/39083721084) times out at `scripts/qualify_windows_diagnostics.py:3392` with an already-completed `_FakeProcess`. Base `tests/test_windows_diagnostic_qualification.py:5169` supplies a real 1 s deadline before fake launch writes receipts. `_run_scenario` correctly honors that deadline. | Give this state/receipt unit test a fixed module-local monotonic clock. Keep real receipt parsing, ready callback, exact exit and successful non-terminating Job close assertions. Existing timeout/active-descendant negative tests remain unchanged. **Fix** `tests/test_windows_diagnostic_qualification.py:5152`. |

## Test design and equivalence

`_completion_scheduler` at `tests/test_diagnostic_launcher.py:35` replaces only
the launcher's clock and the publisher's completion wait for functional tests.
It uses a fixed logical clock and real event/worker completion, with a 10 s
deadlock watchdog. That watchdog is not an increased product deadline or a timing
acceptance criterion. Supervisor, transport, child process, real storage and
export remain active. The normal clean-marker test and unnecessary-marker-retry
test use the same scheduler because they assert functional persistence too.

The separate `test_close_wait_uses_only_remaining_budget` at line 70 tests 0,
200 ms and 1 s setup consumption against the **unchanged 750 ms budget**; it
asserts respectively 750, 550 and 0 ms requested waits, final-slot publication,
and `PUBLISH_INCOMPLETE` for a held worker. The real held-I/O tests additionally
prove return before release, rather than relying on that fake worker alone.

The native-control helper's Linux tests establish that identity observation is
absent before readiness, happens while all three Job members are held, and is
absent after acknowledgement. Fixture tests require stdin release and process
context cleanup on both acknowledgement and watchdog failure.

Two scratch-only falsifiers passed: the budget assertion rejects a mutant that
always waits the full 750 ms after 200 ms setup; the held-interval assertion
rejects a mutant that queries identities before the readiness marker. Both use
in-memory monkeypatches and catch the expected assertion failure. No runtime
file was mutated. Exact command/result: **2 passed**.

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" /tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/codex/1110/test_falsifiers.py
```

This is a test repair, not an optimization. No benchmark or faster-product claim
is made. Baseline output was captured before editing. `git diff
82f8f57653964dd344fac7c01a84d9ab303cdaac -- src scripts packaging
config/security/bandit_baseline.json` is empty: runtime/build/security-baseline
bytes are identical. No second worktree was needed or created under the
current-worktree-only packet. Synthetic assertions retain actual exit, event,
session, storage, marker, export and redaction behavior. Native fixture
equivalence (especially cmd/conhost lifetime) is reviewable but unverified on
Linux; it is not claimed as Windows proof.

| Surface | Before | After |
| --- | --- | --- |
| Product close budget | 750 ms | 750 ms; identical source |
| Stalled I/O | Auto-release after 3 s; total-launch stopwatch | Explicit release after close; incomplete state and worker ownership |
| Persistence ordering | Real storage must finish before wall-clock deadline | Real storage under controlled completion; budget tested separately |
| Unrelated native helper | `echo` may exit during image query | Host acknowledgement holds identities through observation |
| Attached-console drain | Image query after primary exit | Native Job accounting after primary exit |
| Completed fake scenario | Real 1 s deadline includes receipt I/O | Fixed monotonic clock; same receipt/exit/cleanup assertions |
| Related Linux tests | 512 passed, 21 existing skips | 518 passed, 21 existing skips |

## SHOULD search and remaining seams

Search: `rg -n 'monotonic\(\) - started <|elapsed_ms.*< 750' tests`.
The targeted 2.5 s/1.5 s/750 ms assertions and the unnecessary-marker-retry
750 ms assertion are removed. Remaining launcher checks at lines 564, 735 and
778 measure only `publisher.close`, after setup, rather than total child startup.
They cover real lock exhaustion and saved-publication-before-marker-resolution.
They still depend on real scheduling; this packet does not claim all possible
Windows timing flakes are eliminated. The supervisor checks at
`tests/test_diagnostic_supervisor.py:210,269` include real launch and are additional
startup-sensitive seams found by the search, outside the listed failure fixes.
Owner for further triage: external orchestrator under #1110; preserve supervisor
protocol-loss, bounded-history and shutdown assertions when changing them.

## Validation and routing handoff

Local implementation head: `ea50f416cae7c20d832ed4ca9c8dea23ba4cffea`.
Final documentation commit is a descendant with unchanged executable test code.

The integrated related-files plus required-gates command completed with
**636 passed, 21 existing skips**; the final run including Markdown-link
validation completed with **641 passed, 21 existing skips** on the implementation
head above and the final evidence-document content. An initial intermediate run reported
**1 failed, 515 passed, 21 skipped** because the new completion scheduler tried
to join a publisher thread whose start had intentionally failed. That helper
defect was corrected by preserving the unstarted close path; the adverse result
is retained in the scratch evidence, not hidden as a retry.

Exact integrated command:

```bash
ulimit -c 0; env -u QT_QPA_PLATFORMTHEME QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:/tmp/claude-1000/-home-hexaf-p15-Projects-metroliza/9466a750-f701-4a3a-be83-d9aee8d78fd8/scratchpad/qt_keeper /home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m pytest -p qt_app_keeper -q -p no:cacheprovider -o addopts="" tests/test_diagnostic_launcher.py tests/test_windows_runtime_audit.py tests/test_windows_diagnostic_qualification.py tests/test_complexity_ratchet.py tests/test_bug_sweep_coverage.py tests/test_security_audit.py tests/test_docs_markdown_links.py
/home/hexaf-p15/Projects/metroliza/dev/.venv/bin/python -m ruff check .
git diff --check
```

Focused timing runs use exactly the pytest command above with its final four
gate files omitted. These are three planned measurements, not failure retries.
Timing/load receipts and final gate results are recorded below.

| Planned focused run at implementation head | Result | Elapsed command seconds | Load average (1 / 5 / 15 min) |
| --- | --- | --- | --- |
| 1 | 518 passed, 21 existing skips | 13.596 | 6.29 / 5.19 / 3.24 |
| 2 | 518 passed, 21 existing skips | 13.582 | 5.70 / 5.11 / 3.25 |
| 3 | 518 passed, 21 existing skips | 13.566 | 5.11 / 5.01 / 3.25 |

Median elapsed command time: **13.582 s**. These are validation timings, not a
before/after performance comparison. Baseline was captured once for behavior,
so no baseline median or speedup is asserted. Raw local receipts/scripts live
under the packet's scratch directory `codex/1110/`; no diagnostic data was
published. Ruff reports `All checks passed!`; whitespace check exits 0.

| MUST | Evidence | Status |
| --- | --- | --- |
| Per-failure classification | Source/log table above | Complete locally; native confirmation pending |
| Preserve runtime bounds and semantics | Empty runtime/build diff; controlled budget and real held-I/O tests | Local PASS |
| Related and required gates | Commands/results in this record | Local PASS |
| Local-only commits | Conventional messages and required trailers; no push/PR/dispatch/merge | PASS |
| Five consecutive Windows dispatches | External orchestrator must run on the final fix head | **PENDING** |

Internal scope/negative-path audit: no product, identity-allowance, baseline,
budget, packaging, release, migration or credential changes. Six new
parameterized Linux cases test budget consumption, held observation and fixture
cleanup. No new skips, retries or xfail. No independent reviewer was invoked;
independent exact-head review, CI, mergeability and review-thread state belong
to the external orchestrator and are pending. **NOT READY for issue closure.**

Routing feedback: bounded integration was adequate for local test repair; native
confirmation remains pending. No P0/P1/P2 product finding established; zero
correction cycles after readiness because readiness has not been claimed.
Next comparable packet: bounded integration with native Windows review and
dispatch capacity. Actual model/reasoning remains `not visible`.

Remote ledger: read issue/comments and three historical CI logs only. No
external publication, branch mutation, dispatch, PR, merge, deploy or release.
Rollback: revert the local test/doc commits; runtime bytes are unchanged.
