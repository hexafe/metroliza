# Open Testing Runbook

Use this runbook to coordinate release-candidate (RC) open testing with internal testers and trusted external testers.

## 1) Scope and audience

### Audience

- QA engineers executing structured regression and smoke passes.
- Developers validating bug fixes and reproductions.
- Release manager coordinating status, risk, and go/no-go decisions.
- Optional trusted beta users running real-world scenarios on RC builds.

### In scope

- RC package install/launch validation on supported targets.
- Core workflows: representative input load, processing, and export generation.
- Release-gated checks from the RC checklist, including packaging/startup expectations and optional manual smoke evidence collection (`packaging-smoke`, `google-conversion-smoke`).
- Regression checks for recently changed areas and prior high-impact defects.

Packaging smoke semantics for open-testing evidence review:
- `packaging-smoke` remains optional/manual (workflow-dispatch) and non-blocking for normal PR CI.
- When executed, it now includes a packaged-artifact parser smoke launch that runs a non-interactive PDF parsing check (`METROLIZA_PDF_PARSER_SMOKE_FIXTURE`) with offscreen Qt available if needed.
- Failures should include uploaded `packaging-smoke-artifacts` (startup stdout/stderr + collected `metroliza.log` files) and should be linked in release evidence.

### Out of scope

- Net-new feature requests or UX redesign suggestions not required for current RC stabilization.
- Performance tuning not linked to a release blocker.
- Experimental or unsupported platforms/configurations.

## 2) Build distribution instructions

### Where to get RC builds

- Canonical RC branch and naming policy: [`branching_strategy.md`](./branching_strategy.md).
- RC readiness and artifact expectations: [`release_candidate_checklist.md`](./release_candidate_checklist.md).
- Build artifacts are distributed by release engineering from the active `release/YYYY.MM-rcN` branch through the standard internal distribution channel (shared drive/release tracker entry).

### Version verification before testing

For every downloaded artifact:

1. Launch the app and verify displayed version/build/date matches RC metadata in `VersionDate.py`.
2. Confirm release notes/highlight context is synchronized in:
   - [`README.md`](../../README.md)
   - [`CHANGELOG.md`](../../CHANGELOG.md)
3. Record tested artifact name/path and commit SHA in the open-testing tracker.

If metadata does not match expected RC values, stop testing that artifact and request a refreshed build.

## 3) Bug reporting template

Use the template below for every issue found during open testing.

```markdown
### Title
[RC YYYY.MM-rcN] Short defect summary

### Environment
- OS/version:
- Build artifact name:
- RC version/build/date shown in app:
- Parser backend mode (auto/native/python):
- Input dataset/sample used:

### Steps to reproduce
1.
2.
3.

### Expected result

### Actual result

### Impact
- Severity candidate: S0 / S1 / S2 / S3
- Affects release-gated workflow? yes/no
- Workaround available? yes/no (describe)

### Evidence attached
- Logs:
- Screenshots/video:
- Output artifact(s) (`.xlsx`, converted sheet link, crash dump, etc.):
- Additional notes:
```

## 4) Triage policy

This runbook triage policy maps directly to the **Release Candidate Checklist [Defect triage criteria](./release_candidate_checklist.md#defect-triage-criteria) section**.

### Severity labels

- **S0 - Release Blocker:** data loss/corruption, core-flow crash, export integrity failure, security/privacy issue without mitigation, release-gated workflow failure, or install/launch blocker.
- **S1 - High:** major functional degradation with high user impact; workaround is poor or risky.
- **S2 - Medium:** limited-impact functional issue with acceptable workaround.
- **S3 - Low:** cosmetic or low-impact issue.

### Response targets

- **S0:** triage immediately; owner assigned same day; fix plan in next triage sync.
- **S1:** triage within 1 business day; owner and target RC identified.
- **S2/S3:** triage within 2 business days; may defer with rationale.

### Blocker definition (aligned with the checklist Defect triage criteria section)

A defect is a release blocker if it meets any "Must-fix before release" criterion in the checklist [Defect triage criteria](./release_candidate_checklist.md#defect-triage-criteria) section. Blockers must be labeled `must-fix` and resolved (or explicitly mitigated and reclassified by release owner + QA) before Go.

## 5) Daily/periodic cadence

### Daily bug triage meeting (during active open testing)

- Participants: release manager, QA lead, engineering representative(s).
- Duration: 15-30 minutes.
- Agenda:
  1. New defects since last sync.
  2. Reconfirm severity and `must-fix`/`defer` label.
  3. Owner/ETA updates for open S0/S1 defects.
  4. Risk trend and RC confidence.

### Status reporting format

Post one update per day in release tracker/channel using:

- RC build under test:
- Tests completed today:
- New defects (count by severity):
- Open blockers (`must-fix`) and owners:
- Deferred items and rationale:
- Overall confidence: Green / Yellow / Red
- Decision recommendation: Continue / Hold / No-Go candidate

### Go/No-Go criteria

Recommend **Go** only when:

- Required RC checks/evidence are complete per checklist.
- No unresolved `must-fix` defects remain.
- Release owner + QA sign-off are recorded.

Recommend **No-Go/Hold** when any blocker remains unresolved, required evidence is missing, or test coverage is incomplete.

## 6) Exit handoff checklist (to RC checklist)

Before final RC decision, attach/confirm the following evidence in the release tracker and in the canonical RC checklist:

- [ ] Open-testing summary (tested builds, coverage, high-risk areas).
- [ ] Final defect ledger with `must-fix`/`defer` labels and rationale (aligned to the checklist Defect triage criteria section).
- [ ] Required test/packaging results linked against the checklist Required test suites and sign-off owners section.
- [ ] Optional packaging smoke workflow evidence linked (if executed).
- [ ] Google conversion smoke evidence linked: [`google_conversion_smoke.md`](./google_conversion_smoke.md).
- [ ] Sign-off note from QA + release owner referencing checklist Open testing exit criteria decision gates.

Then complete and store final decision details in:
[`release_candidate_checklist.md`](./release_candidate_checklist.md).
