# Audit Hardening RC2

This branch hardens existing RC2 parser selection, industrial diagnostics, raw SQL
validation coverage, and industrial repository regression coverage.

## Hardened Areas

- CMM parser probing now uses cheap marker-based confidence instead of treating
  every `.pdf` as a full-confidence CMM report.
- The built-in CMM resolver detector now uses the same marker probe, so generic
  PDFs are not selected by extension alone under strict matching.
- Industrial worker error/progress emissions now redact sensitive fragments
  before UI signals are emitted.
- Oznak source diagnostics and progress callback payloads now redact
  credential-like values, connection strings, host/user fields, and SQL/query
  fragments before diagnostics leave the adapter boundary.
- Industrial repository persistence now redacts sensitive fragments inside
  free-form string payload values, not only values under sensitive keys.

## Tests Added

- `tests/test_cmm_parser_probe.py`
- `tests/test_industrial_error_redaction.py`
- `tests/test_industrial_data_repository_regression.py`
- `tests/test_oznak_adapter_sql_safety.py`

## Validation

- `python -m compileall -x '^./.git/' .`
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests -q --maxfail=1`
- `python scripts/check_release_hygiene.py`
- `python scripts/sync_release_metadata.py --check`
- `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest tests/test_docs_markdown_links.py -q`

## Remaining Risks

- Image-only/scanned CMM PDFs with generic filenames may remain low-confidence
  during probe because the probe intentionally avoids OCR and full parsing.
- Diagnostic redaction is intentionally conservative for host, user, and SQL
  fields. If operators need those values, expose reviewed summaries rather than
  raw diagnostic strings.

## Real-Time Module Scope

The real-time industrial monitoring and anomaly-detection module is intentionally
not included in this branch. This branch is limited to current RC2 architecture,
tests, parser selection safety, and industrial diagnostic hardening.
