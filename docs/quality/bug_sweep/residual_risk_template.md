# Bug-sweep residual-risk report

Use this template for each wave and for the final #985 closeout. It records what was proved and what
remains unproved; it must never be titled or described as proof that the repository has no bugs.

## Report identity

- Report type: wave #976–#984 / final #985 closeout
- Owning Issue:
- Exact audited repository SHA:
- Base branch and SHA:
- Coverage-ledger schema/version:
- Report date:
- Coordinator:
- Actual runtime model:
- Actual reasoning mode:
- Environments/platforms/backends:
- Sanitized fixtures and versions:

Use `not visible` for unobserved runtime identity and `not available` for evidence that could not
be obtained.

## Coverage reconciliation

| Measure | Count | Evidence |
|---|---:|---|
| Exact tracked paths |  |  |
| Paths owned by this wave |  |  |
| Completed dispositions |  |  |
| Pending |  |  |
| Blocked |  |  |
| Deferred residual risk |  |  |
| Accepted behavior / false positive |  |  |
| Uncovered paths |  |  |
| Duplicate-primary paths |  |  |
| Confirmed findings |  |  |
| Credible hypotheses |  |  |
| Test/observability gaps |  |  |

- Exact validator command/result:
- Ledger commit/SHA:
- Changed-tree reconciliation:
- Paths added or removed since the prior wave:
- Baseline movement and effect on earlier evidence:

At final closeout, uncovered and duplicate-primary counts must be zero and every row must have one
final disposition with evidence.

## Evidence categories

Apply every relevant category. These are orthogonal evidence/risk dimensions: an automated result
may also be sampled, and an accepted risk may remain in the open defect backlog. Record proof mode,
completeness, disposition, and backlog state without collapsing one into another.

| Category | What belongs here | Evidence standard |
|---|---|---|
| Proven by automated evidence | Deterministic assertions executed at the exact SHA | Command/run, environment, fixture, result, and a representative falsifier |
| Proven only by manual evidence | Packaged, clean-machine, browser, accessibility, service, legal, or owner-observed behavior | Procedure, artifact/build identity, observer, date, and result |
| Sampled, not exhaustive | Bounded inputs, iterations, platforms, timings, methods, or path samples | Sampling rule, seed/count, selection rationale, and unsampled remainder |
| Blocked by environment/access | Required evidence unavailable because of runner, hardware, service, credential, legal, or approved-access limits | Exact blocker, owner, safe alternative attempted, and next gate |
| Unsupported / out of product scope | A platform, format, integration, or behavior not promised by current product authority | Source decision and wording of the unsupported claim |
| Accepted by Product Owner | Known residual risk explicitly accepted | Decision link, rationale, scope, expiry/review date, and rollback/monitoring |
| Open defect backlog | Confirmed defect or credible hypothesis still requiring work | One authoritative Issue, severity, owner, state, and required regression evidence |

## Residual-risk entries

Repeat this section for every remaining risk.

### <risk ID> — <short title>

- Categories:
- Severity/consequence tier:
- Consequence tags:
- Primary/secondary audit owners:
- Paths/symbols/workflow:
- Exact SHA:
- What was proved:
- What remains unproved:
- Why it remains:
- Evidence and finding links:
- Affected platform/backend/environment:
- User/data/security/release impact:
- Workaround or containment:
- Preserved seam/rollback:
- Authoritative Issue:
- Accountable person/role:
- Next gate and expected evidence:
- Due date/event:
- Product Owner acceptance link and expiry, or `not accepted`:
- Unsupported claims explicitly avoided:

## Automated evidence

| Claim | Exact command/check | Fixture/environment | Result | Head SHA | Falsifier/broken case |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

Passing aggregate tests is not enough. State which boundary the assertion reaches, what is mocked,
which skips occurred, and what representative broken behavior it would detect.

## Manual and external evidence

| Gate | Build/artifact identity | Procedure/observer/date | Result | Limitation or follow-up |
|---|---|---|---|---|
| Packaged Windows |  |  |  |  |
| Clean-machine startup/core flow |  |  |  |  |
| Browser/offline/accessibility |  |  |  |  |
| Google sandbox/local fallback |  |  |  |  |
| Production/live source |  |  |  |  |
| Notices/legal/release owner |  |  |  |  |
| Other |  |  |  |  |

Write `not applicable`, `not run`, or `blocked` with a reason. Unit, mocked, Linux, or
Windows-core CI cannot be relabeled as packaged/manual proof.

## Sampling and environment limits

- Input/file/schema sample:
- Seeds and iteration counts:
- Timing/repetition controls:
- Supported platforms exercised:
- Supported platforms not exercised:
- Dependency/backend combinations exercised:
- Optional dependencies/fallbacks not exercised:
- Faults injected:
- Faults not feasible:
- Confidentiality constraints:
- Access/hardware/service blockers:

## Finding and backlog reconciliation

| Finding | Disposition | Severity | Authoritative Issue | Fix/accept/block state | Regression/future evidence |
|---|---|---:|---|---|---|
|  |  |  |  |  |  |

- Duplicate-Issue decisions:
- P0 status:
- P1 status:
- P2/P3 status:
- Findings without an owner: **must be zero**
- Existing feature/architecture acceptance criteria incorrectly treated as proof: **must be zero**

## Dependency/platform compatibility inputs

- PR #972 current state/head and audited action families:
- PR #973 current state/head and decomposed dependency families:
- Compatibility evidence completed:
- Versions intentionally deferred:
- Unproven Windows/native/Qt/OCR/scientific/tooling combinations:
- Merge/edit/close/update performed on #972/#973: **none**

## Confidentiality review

- [ ] All fixtures/evidence are generated or deliberately sanitized.
- [ ] No customer/supplier report, proprietary measurement, production extract, or identity is
      present.
- [ ] No credential, token, key, secret-bearing URI, connection string, or unredacted environment
      value is present.
- [ ] Logs, exceptions, SQL, paths, bundles, databases, workbooks, PDFs, and images were reviewed.
- [ ] Restricted evidence, if any, is referenced only through an approved safe record.

Reviewer and result:

## Review and closeout

- Exact-head local gate:
- Exact-head CI runs/conclusions:
- GitHub Codex Review:
- Independent external-orchestrator Ultra exact-head closeout review:
- Unresolved review-thread count:
- Head unchanged since review:
- Mergeable state:
- P0/P1 blockers:
- Product Owner acceptances:
- Final statement of what the sweep did **not** prove:

#974 is not closed until all program acceptance criteria, final exact-tree coverage, finding
ownership, P0 dispositions, residual risks, and independent Ultra exact-head closeout review are
observed.
