"""Compatibility imports for the neutral report ingestion schema."""

from modules.report_schema import ensure_report_schema, ensure_schema_indexes

__all__ = ["ensure_cmm_report_schema", "ensure_report_schema", "ensure_schema_indexes"]


def ensure_cmm_report_schema(database, *, connection=None, retries=4, retry_delay_s=1):
    """Ensure the report ingestion schema exists."""

    return ensure_report_schema(
        database,
        connection=connection,
        retries=retries,
        retry_delay_s=retry_delay_s,
    )
