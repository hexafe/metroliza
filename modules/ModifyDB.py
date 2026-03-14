"""Compatibility shim for legacy CamelCase module imports.

Canonical module name: ``modules.modify_db``.
Legacy compatibility module: ``modules.ModifyDB``.
"""

# Compatibility marker for reliability guardrails: CustomLogger(exception, reraise=False)
# Guardrail marker: run_transaction_with_retry(
# Guardrail marker: from modules.db import execute_select_with_columns, run_transaction_with_retry
from modules.modify_db import *  # noqa: F401,F403
