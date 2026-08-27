# Repository-wide bug-sweep control plane

Status: Active audit foundation

Owner: Issue [#975](https://github.com/hexafe/metroliza/issues/975)

Parent program: [#974](https://github.com/hexafe/metroliza/issues/974)

Baseline: `develop@fcb462942e90aeeb64bba84bfe080d556da0efdb`

Last reviewed: 2026-08-27

This directory is the canonical control plane for the repository-wide bug sweep. It proves review
surface ownership; it does **not** claim that a finite review proves the absence of every bug.
Green aggregate tests are supporting evidence, never a substitute for an audited path, workflow,
failure mode, packaged environment, or manual gate.

## Exact-SHA scope

The planning baseline was fetched twice before the work branch was created and remained:

`develop@fcb462942e90aeeb64bba84bfe080d556da0efdb`

That commit contains 929 paths from `git ls-files`. The foundation adds six tracked audit-control
paths and updates three existing index/planning paths, so the complete PR tree contains 935 tracked
paths. The validator always expands the actual Git index/tree rather than trusting these recorded
counts.

Every wave records the exact audited commit SHA, repository path expansion, environment, command,
fixture, and evidence link. The planning `baseline.sha` is not terminal evidence. If `develop`
moves, earlier exact-head evidence remains historical evidence but cannot be represented as proof
for the new tree. A wave must re-expand the current tree and state whether earlier findings still
apply.

## Machine-readable ownership ledger

[`coverage.json`](./coverage.json) is standard JSON and is readable with the Python standard
library. It contains:

- the baseline branch, SHA, and tracked-path count;
- Issues #975–#985 and their execution order;
- current open-Issue mappings for #901–#957 and #971;
- PRs #972/#973 as compatibility inputs only;
- allowed classes, statuses, consequence tiers, and consequence tags;
- the exact fields required for a rule-scoped terminal snapshot;
- the exact structured fields required for a deferred residual risk;
- non-overlapping include/exclude rules; and
- per-rule primary owner, secondary owners, audit state, evidence, findings, disposition, and
  residual risk.

[`validate_bug_sweep_coverage.py`](../../../scripts/quality/validate_bug_sweep_coverage.py)
evaluates **all** rules for each `git ls-files` path. Rule order is deterministic for reporting but
is not precedence: an overlap is a duplicate-primary failure, not a hidden first-match win. Globs
are repository-relative POSIX patterns; `*` stays within one path segment and `**` may cross
directories. Exclusions are part of the matching rule and make broad categories disjoint.

The validator fails offline, without network access, when:

- a tracked path has no primary rule;
- a tracked path matches more than one primary rule;
- an owner is not one of the captured existing Issues #975–#985;
- a class, status, consequence tier, or consequence tag is invalid;
- terminal coverage (`completed`, `accepted behavior`, or `deferred residual risk`) lacks evidence
  or a disposition, an exact audited commit SHA, or its exact matched-path snapshot;
- a terminal snapshot contains a glob, a non-repository path, an empty, duplicate, or unsorted path,
  or differs from the rule's current deterministic expansion;
- a pending, in-progress, or blocked rule carries terminal snapshot evidence;
- deferred residual risk lacks a reason, accountable person/role, target Issue/phase, next gate, or
  preserved seam;
- a workstream has no primary path;
- a rule matches zero tracked paths or the immutable baseline metadata is altered;
- the open-Issue map or #972/#973 compatibility-input contract is malformed; or
- a newly tracked path bypasses every rule.

Run:

~~~bash
python scripts/quality/validate_bug_sweep_coverage.py
python scripts/quality/validate_bug_sweep_coverage.py --json
~~~

### Rule-scoped terminal snapshots

Schema version 2 requires every rule to contain `terminal_snapshot` explicitly. It is `null` while
the rule is `pending`, `in progress`, or `blocked`. A `completed`, `accepted behavior`, or
`deferred residual risk` rule instead records exactly:

~~~json
{
  "audited_commit_sha": "<lowercase 40-character Git commit SHA>",
  "matched_paths": ["<exact sorted repository-relative POSIX path>"]
}
~~~

`audited_commit_sha` identifies the commit at which the rule's evidence was produced.
`matched_paths` is a non-empty, sorted, unique list of explicit paths, not a glob or a digest. The
validator compares that list byte-for-byte with the rule's current deterministic expansion.

Ownership globs select the current audit surface; they do not extend old evidence to files that
happen to match later. A newly added, removed, renamed, reclassified, or newly matching path makes
the expansion differ and invalidates the terminal rule until the rule is audited and snapshotted
again. A path owned only by another rule does not invalidate an unchanged terminal rule, because
this evidence is rule-scoped rather than a whole-repository lock.

The snapshot also does not claim that an older SHA proves later content at an unchanged path.
Wave-level change review must decide whether the older evidence still applies, and any later claim
must remain explicit about that boundary. Coverage rows expose `terminal_snapshot`; JSON output
also exposes each value in `rule_snapshots`. All foundation rules are currently `pending`, so every
snapshot is `null` and no terminal evidence is fabricated.

### Expanded foundation counts

These are the deterministic counts for the 935-path foundation tree. Re-run the validator after any
tree change; do not copy these numbers forward as current evidence.

| Primary owner | Paths |
|---:|---:|
| #975 | 156 |
| #976 | 58 |
| #977 | 45 |
| #978 | 59 |
| #979 | 19 |
| #980 | 29 |
| #981 | 53 |
| #982 | 56 |
| #983 | 12 |
| #984 | 155 |
| #985 | 293 |

| Path class | Paths |
|---|---:|
| canonical runtime | 254 |
| compatibility runtime | 149 |
| test | 246 |
| fixture | 47 |
| script/tooling | 40 |
| workflow/configuration | 12 |
| packaging/build | 26 |
| active documentation | 99 |
| archive/reference | 53 |
| generated/static asset | 9 |

Uncovered paths: **0**. Duplicate-primary paths: **0**.

## Include, exclude, and classification rules

All tracked paths are in scope for an explicit disposition.

- Canonical runtime is under `src/metroliza`; ownership follows the dominant package/file
  contract.
- `modules/**` and `VersionDate.py` are compatibility runtime, not a second implementation
  area.
- Tests are primary #985, with relevant subsystem waves recorded as secondary owners. Sanitized
  fixtures are a separate class.
- Build manifests, CI, packaging definitions, Windows helpers, and release tooling are primary
  #976.
- Active documentation is primary #975, with #985 responsible for final claim reconciliation.
- Historical payloads under `docs/archive/**` plus explicitly completed/historical roadmap records
  are `archive/reference`. The maintained `docs/archive/README.md` and
  `docs/archive/2026/README.md` indexes remain active documentation.
- Tracked ONNX models, Plotly JavaScript, images, icons, PDFs, and generated inventory/snapshot JSON
  are explicit `generated/static asset` rows. Their provenance, regeneration, packaging, and
  runtime discovery still require evidence.
- The repository contains no tracked submodule entry. External packages and dependencies are not
  silently treated as first-party paths; their manifests/adapters and compatibility evidence remain
  in scope.
- Untracked build output, caches, local environments, credentials, customer reports, and production
  extracts are outside the Git-tree ledger. Their supported boundaries remain manual/environment
  evidence, not an exclusion from relevant workflow audit.

Static-search absence is never proof that a path is dead, generated, or unused. Reflection,
plugins, import shims, package resource lookup, and Windows frozen layouts are audited explicitly by
#984/#976.

## Workstreams and order

| Order | Issue | Primary surface |
|---:|---:|---|
| 0 | [#975](https://github.com/hexafe/metroliza/issues/975) | Baseline, ownership, finding protocol, indexes, and validator |
| 1 | [#976](https://github.com/hexafe/metroliza/issues/976) | Build, CI, dependencies, packaging, and Windows |
| 2 | [#983](https://github.com/hexafe/metroliza/issues/983) | Security, confidentiality, configuration, diagnostics, and licensing |
| 3 | [#979](https://github.com/hexafe/metroliza/issues/979) | SQLite, caches, migrations, persistence, and atomicity |
| 4 | [#980](https://github.com/hexafe/metroliza/issues/980) | Filtering, grouping, statistics, and Python/native parity |
| 5 | [#978](https://github.com/hexafe/metroliza/issues/978) | Import, parsing, OCR, archives, and validation |
| 6 | [#981](https://github.com/hexafe/metroliza/issues/981) | Reports, Excel, Google, dashboards, and atomic publication |
| 7 | [#977](https://github.com/hexafe/metroliza/issues/977) | Startup, PyQt lifecycle, threading, cancellation, and state |
| 8 | [#982](https://github.com/hexafe/metroliza/issues/982) | Tabular, industrial, realtime, and long-running workflows |
| 9 | [#984](https://github.com/hexafe/metroliza/issues/984) | Compatibility, imports, dead paths, and packaged discovery |
| 10 | [#985](https://github.com/hexafe/metroliza/issues/985) | Test challenge and final residual-risk closeout |

#975 integrates first. The initial Product Owner policy requires exactly one audit PR at a time in
the order above. Parallelization requires a later explicit decision plus proof that branches do not
overlap in shared audit artifacts, test environments, or exact-baseline assumptions; concurrent
workers must never write the same ledger/report paths. #985 runs last and independently challenges
the reports, tests, coverage, findings, and remaining uncertainty.

Persistent repositories, schemas, transaction helpers, and offsets remain primary #979 even when
used by industrial/realtime workflows; their orchestration remains #982. Tests remain #985.
Compatibility shims remain #984. Security is a primary owner only for dedicated security,
credential, diagnostic, and licensing paths; it is secondary on domain paths with a security
boundary.

## Discovery audit versus defect repair

Audit PRs add only approved audit artifacts, sanitized fixtures, and audit tooling. They do not
opportunistically repair runtime behavior, update dependencies, modify workflows, or promote a
release.

A confirmed defect follows a separate chain:

1. capture safe evidence at an exact SHA;
2. search for an authoritative existing Issue;
3. add evidence to that Issue or create one focused bug Issue;
4. create a separate `fix/<issue>-...` branch and PR;
5. show fail-first regression evidence;
6. implement the fix;
7. run focused and exact-head validation; and
8. obtain independent review.

Audit status and fix status are separate fields. A reviewed path can still have an open defect; a
merged fix does not by itself prove the rest of a path or workflow was audited.

## Finding taxonomy

Every candidate receives exactly one disposition:

- **Confirmed defect**
- **Credible defect hypothesis** requiring a bounded reproducer
- **Test/observability gap**
- **Design/maintainability risk** without demonstrated incorrectness
- **Dependency/platform compatibility risk**
- **Accepted behavior / false positive**
- **Deferred residual risk** with reason, accountable person/role, target Issue/phase, next gate, and
  preserved seam

Severity is consequence and reach, not repair effort:

- **P0** — confidentiality/security exposure, data loss/corruption, wrong persisted ownership,
  materially wrong engineering/statistical result, or unsafe release/destructive behavior.
- **P1** — crash, lost work, deadlock, broken transaction/cancellation/recovery, major supported
  workflow failure, or materially misleading output.
- **P2** — recoverable incorrectness, edge-case workflow defect, or platform/package regression
  with a workaround.
- **P3** — low-impact defect, diagnostics/usability problem, or test/maintainability debt without
  current incorrect behavior.

Use [`finding_template.md`](./finding_template.md). A confirmed or credible P0 finding stops the
current slice. The coordinator records sanitized evidence, the affected invariant, safe state,
operations not performed, and the required Product Owner/external-orchestrator decision. Do not
continue adjacent audit work when it could overwrite evidence, expose confidential material, or
worsen impact.

## Duplicate handling and current Issue map

`coverage.json` maps all 55 currently open Issues in #901–#957 plus #971 to one or more audit
waves. #911 is closed; #909 and #910 are pull-request numbers, not open Issues. The map is a routing
aid, not correctness evidence.

Before opening a bug:

1. search open and closed Issues by path, symbol, workflow, symptom, platform, and error;
2. compare the candidate's affected contract and acceptance boundary;
3. add new exact-SHA evidence to the existing authoritative Issue when scope already exists;
4. create a focused Issue only when no authoritative scope exists; and
5. link the decision in the finding record.

An existing feature, architecture, or acceptance Issue says what must become true. Its checklist,
implementation claim, or green test is not proof that current behavior is correct.

GitHub settings, ChatGPT Project state, remote refs/history, hosted services, clean-machine Windows,
legal review, and release-owner decisions are not tracked files. Record them as manual or external
evidence in the relevant wave and [residual-risk report](./residual_risk_template.md); never
fabricate ledger rows for them.

## Current automated-evidence baseline

This inventory describes the baseline configuration, not a completed audit:

- **Tests:** 292 tracked paths under `tests/`; 47 are classified as fixtures and 245 as test/audit
  code before this validator test is added. CI runs the full pytest tree, then appends selected
  offscreen real-Qt dialog shards.
- **Coverage:** CI measures `src/metroliza`, `modules`, and `scripts`; it blocks below 80% for
  combined line coverage and separately for canonical `src/metroliza` line coverage. Execution
  coverage does not prove assertions, failure paths, or platform behavior.
- **Markers/skips:** pytest registers an `integration` marker for optional external runtimes,
  sample files, or packaged artifacts. Tests contain environment-dependent PyQt, native extension,
  Pillow, openpyxl, River, cryptography, external plot-package, and OS-specific permission/symlink
  skips or import-skips. #985 must reconcile what was actually run.
- **Ruff:** `ruff==0.15.10`, Python 3.11 target, full-repository CI lint, with four recorded E402
  per-file exceptions.
- **mypy:** `mypy==2.2.0`, strict configuration with `follow_imports = "skip"`, but CI checks
  only Google credential hygiene, anomaly contracts, and realtime stream contracts.
- **Bandit/pip-audit:** `scripts/security_audit.py --ci` runs Bandit and pip-audit, expands three
  pinned sibling repositories in CI, and checks the finite
  `config/security/bandit_baseline.json`. Tool failure and findings must be reported separately.
- **Python/Rust/native:** CI builds five locked Rust wheels, installs them, exercises available and
  intentionally absent fallback paths, runs chart and CMM parity smokes, and runs the blocking CMM
  performance guardrail.
- **CI lanes:** automatic jobs are Static checks, Unit tests, Native wheel build and smoke checks,
  CMM parser perf guardrail, and Windows core smoke. The general performance trend job is explicitly
  non-blocking. Packaging smoke and Windows startup benchmark are workflow-dispatch opt-ins.
- **Manual/package limits:** Linux and Windows-core CI do not prove clean-machine packaged startup,
  real PyInstaller/Nuitka distribution behavior, browser/accessibility, Google OAuth conversion,
  notices/legal approval, or release-owner acceptance.
- **Optional dependencies/fallbacks:** OCR, ML anomaly detection, external package adapters, and
  native extensions have separate dependency or availability paths. Each wave records requested
  versus effective backend and whether absence skips, falls back, warns, or fails.

## Dependency pull requests as compatibility inputs

- [#972](https://github.com/hexafe/metroliza/pull/972) is an open three-update GitHub Actions group.
  #976 audits runner requirements, permissions, artifact/cache behavior, and pinned provenance;
  #983/#985 challenge security and gate effectiveness.
- [#973](https://github.com/hexafe/metroliza/pull/973) is an open 35-update Python dependency group.
  It spans security/auth, scientific/data/visual/ML, Qt, workbook/PDF/image/OCR, native/build,
  packaging, and test/lint/security tools, including major-version transitions.

Both are **compatibility input only**. This foundation does not edit, close, update, merge, or
accept either PR. A passing import smoke is insufficient; #976 owns a decomposed compatibility
matrix with downstream evidence from #977–#984.

## Wave report format for #976–#984

Each wave publishes one sanitized report with:

1. Issue, exact audited SHA, base SHA, branch, date, coordinator/worker routing, and actual runtime
   identity or `not visible`;
2. expanded primary paths and relevant secondary paths, with zero ownership ambiguity;
3. environments/platforms/backends, dependency versions, fixtures, seeds, and exact commands;
4. supported workflows and happy, boundary, negative, cancellation, rollback, and failure paths;
5. per-path audit status, exact terminal snapshot, evidence, exact disposition, finding links, and
   residual-risk note;
6. confirmed findings and credible hypotheses, each linked to one authoritative Issue;
7. accepted behaviors/false positives and the evidence that rejected each candidate;
8. skips, unavailable/manual evidence, sampled scope, blocked access, and unsupported scope;
9. confidentiality review and confirmation that all artifacts are sanitized;
10. exact-head CI, GitHub Codex Review, independent review, and unresolved-thread count; and
11. confirmation that the audit PR made no opportunistic runtime/dependency/release change.

Update the ledger status only from durable evidence. Completed, accepted-behavior, and deferred
residual-risk rules require both an evidence link and a disposition; a deferral also requires the
five structured fields named in the ledger. Silence cannot mean terminal.

## Confidentiality and safe evidence

Use generated or deliberately sanitized files, databases, measurements, credentials, tokens,
paths, identities, and diagnostics. Never attach customer/supplier reports, proprietary
measurements, production extracts, real connection strings, OAuth credentials, keys, or
unredacted logs.

Review evidence before committing or posting it. Record only the smallest reproducer needed to
prove the behavior. When adequate evidence would expose confidential material, stop, preserve a
safe description, and request a restricted evidence path rather than weakening the rule.

## Final closeout through #985

#985 re-expands the exact closeout tree, rebinds final closeout evidence to that tree, requires a
final disposition for every path, reconciles every finding to one authoritative Issue, challenges
high-consequence “no defect found” claims, and uses targeted
property/fuzz/mutation/state-machine/fault/parity probes where justified.

The closeout uses [`residual_risk_template.md`](./residual_risk_template.md) and separates:
automated proof, manual proof, sampled coverage, blocked environment/access, unsupported scope,
Product Owner acceptance, and the open defect backlog. #974 remains open until its complete
acceptance criteria and independent external-orchestrator Ultra exact-head closeout review are
observed.
