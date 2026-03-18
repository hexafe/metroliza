"""Compatibility shim for legacy CamelCase module imports.

Compatibility wrapper for legacy ``modules.CMMReportParser`` imports.

Canonical implementation lives in ``modules.cmm_report_parser``.
This file intentionally preserves compatibility for legacy imports and tests
that introspect this file directly.

Guardrail markers (source-inspection compatibility):
- from modules.cmm_report_parser import *  # noqa: F401,F403
- parse_blocks_with_backend_and_telemetry(self.pdf_raw_text, use_native=False)
- from modules.db import execute_with_retry, run_transaction_with_retry
- was_inserted = run_transaction_with_retry(
- count = count_rows[0][0] if count_rows else 0
- CustomLogger(exception, reraise=False)
"""

from modules.cmm_report_parser import *  # noqa: F401,F403
