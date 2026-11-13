# Bug-sweep finding

Copy this template into the wave report or authoritative GitHub Issue. Remove instructional text,
keep explicit `none` / `not applicable` entries, and include only sanitized evidence.

## Identity and ownership

- Finding ID:
- Audit wave / Issue:
- Exact repository SHA:
- Baseline SHA:
- Date observed:
- Reporter/reviewer:
- Primary ledger rule and path owner:
- Secondary audit owners:
- Authoritative finding Issue:
- Fix PR, accepted deferral, or blocker:
- Audit status:
- Fix status:

Audit status and fix status are independent. Do not mark the rest of a path audited merely because
one defect was fixed.

## Exactly one disposition

Select one:

- [ ] Confirmed defect
- [ ] Credible defect hypothesis requiring a bounded reproducer
- [ ] Test/observability gap
- [ ] Design/maintainability risk without demonstrated incorrectness
- [ ] Dependency/platform compatibility risk
- [ ] Accepted behavior / false positive
- [ ] Deferred residual risk with reason, accountable person/role, target Issue/phase, next gate, and
      preserved seam

## Severity

Select one and justify it from consequence and reach, not repair effort:

- [ ] **P0** — confidentiality/security exposure, data loss/corruption, wrong persisted ownership,
      materially wrong engineering/statistical result, or unsafe release/destructive behavior
- [ ] **P1** — crash, lost work, deadlock, broken transaction/cancellation/recovery, major
      supported-workflow failure, or materially misleading output
- [ ] **P2** — recoverable incorrectness, edge-case workflow defect, or platform/package regression
      with a workaround
- [ ] **P3** — low-impact defect, diagnostics/usability problem, or test/maintainability debt
      without current incorrect behavior

Severity/impact rationale:

## Affected surface

- Path(s):
- Symbol(s):
- Supported workflow:
- Platform/OS/architecture:
- Source, editable, installed, native-wheel, or packaged layout:
- Python/dependency/tool versions:
- Requested backend:
- Effective backend/fallback:
- Data/store/schema version:
- Consequence tags:

## Sanitized reproduction or fixture

- Fixture/source:
- Sanitization method and review:
- Preconditions:
- Exact command or interaction:
- Deterministic seed/iteration count, if applicable:
- Fault injection or negative control:
- Reproduction frequency:
- Smallest safe evidence link:

Do not attach real customer/supplier reports, proprietary measurements, production extracts,
credentials, tokens, keys, connection strings, identities, or unredacted diagnostics.

## Expected versus observed

Expected behavior and source contract:

Observed behavior:

Why the difference is incorrect or remains a credible hypothesis:

## Contract and impact analysis

- Relevant product requirement:
- Relevant architecture/data/security/compatibility contract:
- Relevant release/manual contract:
- Affected users/workflows:
- Data-integrity or ownership effect:
- Numerical/statistical effect:
- Confidentiality/security effect:
- Cancellation/recovery/atomicity effect:
- Windows/package/offline effect:
- Reach and workaround:

## Parity dimension

Complete every applicable comparison:

- Python reference versus native/Rust:
- in-memory/pandas versus SQLite:
- GUI/result model versus Excel/HTML/Google:
- native-text versus OCR:
- source checkout versus installed/package:
- Linux CI versus Windows core/package:
- online/optional integration versus local fallback:
- normal, warning, failure, cancellation, and retry behavior:

Use `not applicable` with a reason. Do not call two implementations an independent oracle when
they share the same code or assumptions.

## Regression-test expectation

- Smallest fail-first test:
- Broken behavior the test must detect:
- Expected pre-fix failure:
- Expected post-fix result:
- Negative/fault/parity cases:
- Environment/manual evidence that automation cannot replace:
- Why existing green tests did not prove this behavior:

## Duplicate and authoritative-Issue analysis

- Search terms:
- Paths/symbols/workflows searched:
- Open Issues reviewed:
- Closed Issues reviewed:
- Existing Issue selected:
- Why its scope is authoritative:
- Or why a new focused bug Issue is required:
- Evidence added without duplicating acceptance scope:

An existing feature or architecture Issue is not proof of current correctness. Add exact-SHA defect
evidence to it only when it already owns the affected contract; otherwise create one focused bug
Issue.

## Confidentiality review

- [ ] Evidence is generated or deliberately sanitized.
- [ ] No unsanitized customer/supplier report contents, proprietary measurement rows, or production
      extracts are present; any synthetic or deliberately sanitized rows were reviewed.
- [ ] No credential, token, key, URI secret, or connection string is present.
- [ ] Paths, user/customer/supplier identities, environment values, SQL, and exceptions are
      redacted where needed.
- [ ] Images, PDFs, databases, workbooks, logs, bundles, and metadata were reviewed recursively.
- [ ] GitHub visibility is appropriate for the remaining evidence.

Reviewer and result:

## Disposition and next gate

- Current disposition:
- Accountable person/role:
- Target Issue/phase:
- Required next evidence:
- Due date or event:
- Preserved seam/rollback:
- Unsupported claim explicitly avoided:

### P0 stop/escalation record

Complete for a confirmed or credible P0; otherwise write `not applicable`.

- Time work stopped:
- Safe state:
- Evidence preserved:
- Confidential/restricted evidence location, if approved:
- Affected invariant and exposure:
- Product Owner/external-orchestrator decision required:
- Options and recommended decision:
- Operations explicitly **not** performed:
- Adjacent waves paused:

Do not continue adjacent audit work when it could overwrite evidence, expose confidential material,
worsen impact, or make an unsafe remote/destructive change.
