# Full Module Audit Release Check - 2026-06-08

Release line: `2026.05 RC4`  
Build: `260609`  
Branch: `codex/full-module-audit-20260608`  
Base: `rc2` at `44116433a8fcd5f55aff3653b4644240a04b15d6`

## Scope

This release check covers the full-module audit hardening slice documented in
[`../roadmaps/full_module_audit_2026_06.md`](../roadmaps/full_module_audit_2026_06.md).

Implemented release-relevant fixes:

- Parsed-report replacement is atomic across report rows, metadata, warnings,
  candidates, measurements, and semantic duplicate warnings.
- CMM persistence errors now propagate to parse orchestration.
- HTML dashboard-only export failures are fatal and no longer report success.
- CSV Summary optimized SQLite loading keeps global multi-file header identity
  and aligns invalid-value `!=` filters with the in-memory path.
- Native histogram, IQR, and trend chart exceptions fall back to matplotlib when
  a fallback figure exists.
- Packaging smoke and native packaging helper now validate header OCR runtime
  dependencies.
- Windows startup benchmark samples now fail on bad process/profile evidence.
- The blocking CMM performance trend gate now fails when its baseline or
  observed rows are missing.

## Local Evidence

Completed locally on 2026-06-08:

```bash
PYTHONPATH=src:. python -m ruff check .
PYTHONPATH=src:. python -m compileall -q -x '^\./\.git/' .
python scripts/sync_release_metadata.py --check
python scripts/check_release_hygiene.py
python scripts/security_audit.py --ci --sibling-root /home/hexaf/Projects
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q
```

Results:

- Ruff: passed.
- Compileall: passed.
- Release metadata sync: passed.
- Release hygiene: passed.
- Security audit: passed after rerunning with normal network access for
  `pip-audit`; `pip-audit` reported no known vulnerabilities. Existing Bandit
  medium findings remain report-only baseline items tracked in
  [`implementation_item_triage.md`](./implementation_item_triage.md).
- Full headless pytest: `1889 passed, 263 skipped, 6 warnings, 71 subtests passed`.

## Pending Release Owner Evidence

Manual/opt-in release evidence remains required before promotion:

- Packaging smoke on the final artifact.
- Windows packaged startup benchmark on the final artifact.
- Google conversion smoke on the final artifact.
- Release owner sign-off for remaining implementation/security triage items.
