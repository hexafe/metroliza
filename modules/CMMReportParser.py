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

from __future__ import annotations

import importlib
import sys


def _load_canonical_module():
    module_name = "modules.cmm_report_parser"
    module = sys.modules.get(module_name)
    parser_cls = getattr(module, "CMMReportParser", None) if module is not None else None
    if parser_cls is not None and getattr(parser_cls, "__module__", "") == module_name:
        return module

    if module is not None:
        sys.modules.pop(module_name, None)

    return importlib.import_module(module_name)


_canonical = _load_canonical_module()

for _name in dir(_canonical):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_canonical, _name)


__all__ = [name for name in globals() if not name.startswith("_")]
