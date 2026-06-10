"""Optional Oznak adapter for Metroliza industrial data integration.

The adapter is intentionally lazy: it does not import ``oznak`` at module import
time. Callers can probe availability/diagnostics and execute fetch requests in a
best-effort mode that never hard-fails when Oznak is absent or incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib
import inspect
import json
from typing import Any, Mapping

from metroliza.industrial.industrial_data_repository import looks_sensitive_key, redact_sensitive_text
from metroliza.industrial.industrial_workflow_state import IndustrialQueryFilter


OZNAK_IMPORT_PATH = "oznak"
OZNAK_FETCHER_IMPORT_PATH = "oznak.fetcher"
DEFAULT_OZNAK_FETCH_CHUNK_SIZE = 5_000
DEFAULT_REFERENCE_BATCH_SIZE = 100

_ROW_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "source_primary_key": ("source_primary_key", "id", "pk", "row_id", "record_id", "external_id"),
    "process_timestamp": (
        "process_timestamp",
        "timestamp",
        "event_timestamp",
        "processed_at",
        "process_time",
        "ts",
    ),
    "reference": ("reference", "ref", "measurement_reference"),
    "part_number": ("part_number", "part_no", "part", "pn"),
    "part_name": ("part_name", "part_description"),
    "revision": ("revision", "rev"),
    "serial": ("serial", "serial_number", "sn"),
    "batch": ("batch", "batch_number"),
    "lot": ("lot", "lot_number"),
    "work_order": ("work_order", "workorder", "wo"),
    "station": ("station", "station_id"),
    "line": ("line", "line_id"),
    "operator": ("operator", "operator_id", "user"),
    "status": ("status", "result_status", "state"),
    "cycle_time_s": ("cycle_time_s", "cycle_time", "cycle_seconds"),
}

_REPOSITORY_FIELD_ALIASES = {
    "source_primary_key": "source_record_key",
    "batch": "batch_lot",
    "lot": "batch_lot",
    "operator": "operator_name",
    "status": "process_status",
}


@dataclass(frozen=True)
class OznakAdapterStatus:
    available: bool
    import_path: str = OZNAK_IMPORT_PATH
    version: str | None = None
    module_path: str | None = None
    contracts_available: bool = False
    fetch_available: bool = False
    chunked_fetch_available: bool = False
    streaming_fetch_available: bool = False
    cancellation_available: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class OznakAdapterFetchResult:
    status: OznakAdapterStatus
    records: tuple[dict[str, Any], ...] = ()
    row_count: int = 0
    implemented: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _redact_error_text(value: Any, *, max_len: int = 320) -> str:
    return redact_sensitive_text(value, max_len=max_len)


def _safe_exception_summary(exc: BaseException) -> str:
    message = _redact_error_text(exc)
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


def _get_mapping_value(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _profile_value(profile: Any, *keys: str) -> Any:
    for key in keys:
        value = _get_mapping_value(profile, key)
        if value is not None:
            return value
    return None


def _lookup_case_insensitive(row: Mapping[str, Any], key: str) -> Any:
    if key in row:
        return row[key]
    normalized = key.lower()
    for row_key, row_value in row.items():
        if str(row_key).lower() == normalized:
            return row_value
    return None


def _normalize_column_mappings(profile: Any) -> dict[str, str]:
    raw_mappings = _profile_value(
        profile,
        "column_mappings",
        "column_mapping",
        "field_mappings",
        "field_mapping",
        "profile_column_mappings",
    )
    if not isinstance(raw_mappings, Mapping):
        metadata = _profile_value(profile, "metadata")
        if isinstance(metadata, Mapping):
            raw_mappings = _profile_value(
                metadata,
                "column_mappings",
                "column_mapping",
                "field_mappings",
                "field_mapping",
                "profile_column_mappings",
            )
    if not isinstance(raw_mappings, Mapping):
        normalized: dict[str, str] = {}
        pagination_column = _profile_value(profile, "default_pagination_column", "pagination_column")
        timestamp_column = _profile_value(profile, "timestamp_column")
        if pagination_column:
            normalized["source_primary_key"] = str(pagination_column)
        if timestamp_column:
            normalized["process_timestamp"] = str(timestamp_column)
        return normalized

    canonical_fields = set(_ROW_KEY_ALIASES.keys())
    normalized_raw: dict[str, str] = {}
    for raw_key, raw_value in raw_mappings.items():
        key_text = str(raw_key)
        if isinstance(raw_value, str):
            normalized_raw[key_text] = raw_value
            continue
        if isinstance(raw_value, Mapping):
            source = raw_value.get("source") or raw_value.get("source_column") or raw_value.get("column")
            target = raw_value.get("target") or raw_value.get("target_field") or raw_value.get("canonical")
            if isinstance(source, str) and isinstance(target, str):
                normalized_raw[target] = source
            elif isinstance(source, str):
                normalized_raw[key_text] = source
            elif isinstance(target, str):
                normalized_raw[target] = key_text

    keys_lower = {key.lower() for key in normalized_raw}
    values_lower = {value.lower() for value in normalized_raw.values()}
    keys_are_canonical = bool(keys_lower & canonical_fields)
    values_are_canonical = bool(values_lower & canonical_fields)

    if keys_are_canonical or not values_are_canonical:
        converted = {key.lower(): value for key, value in normalized_raw.items()}
        pagination_column = _profile_value(profile, "default_pagination_column", "pagination_column")
        timestamp_column = _profile_value(profile, "timestamp_column")
        if pagination_column:
            converted.setdefault("source_primary_key", str(pagination_column))
        if timestamp_column:
            converted.setdefault("process_timestamp", str(timestamp_column))
        return converted

    converted: dict[str, str] = {}
    for source_column, canonical_name in normalized_raw.items():
        converted[canonical_name.lower()] = source_column
    pagination_column = _profile_value(profile, "default_pagination_column", "pagination_column")
    timestamp_column = _profile_value(profile, "timestamp_column")
    if pagination_column:
        converted.setdefault("source_primary_key", str(pagination_column))
    if timestamp_column:
        converted.setdefault("process_timestamp", str(timestamp_column))
    return converted


def _coerce_row_mapping(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if hasattr(row, "_asdict"):
        row_as_dict = row._asdict()
        if isinstance(row_as_dict, Mapping):
            return dict(row_as_dict)
    row_to_dict = getattr(row, "to_dict", None)
    if callable(row_to_dict):
        maybe_mapping = row_to_dict()
        if isinstance(maybe_mapping, Mapping):
            return dict(maybe_mapping)
    if hasattr(row, "__dict__"):
        return {str(key): value for key, value in vars(row).items() if not str(key).startswith("_")}
    if isinstance(row, (list, tuple)):
        return {f"col_{index}": value for index, value in enumerate(row)}
    return {"value": row}


def _extract_rows(payload: Any) -> tuple[Any, ...]:
    if payload is None:
        return ()

    candidate = payload
    if isinstance(payload, Mapping):
        for key in ("rows", "records", "data", "items"):
            if key in payload:
                candidate = payload[key]
                break
    else:
        for key in ("rows", "records", "data", "items"):
            value = getattr(payload, key, None)
            if value is not None:
                candidate = value
                break

    to_dict = getattr(candidate, "to_dict", None)
    if callable(to_dict):
        try:
            maybe_records = to_dict("records")
            if isinstance(maybe_records, list):
                return tuple(maybe_records)
        except TypeError:
            maybe_mapping = to_dict()
            if isinstance(maybe_mapping, Mapping):
                return (dict(maybe_mapping),)

    iterrows = getattr(candidate, "iterrows", None)
    if callable(iterrows):
        return tuple(row for _, row in iterrows())

    if isinstance(candidate, Mapping):
        return (dict(candidate),)
    if isinstance(candidate, (str, bytes)):
        return (candidate,)
    if isinstance(candidate, tuple):
        return candidate
    if isinstance(candidate, list):
        return tuple(candidate)

    try:
        return tuple(candidate)
    except TypeError:
        return (candidate,)


def _stable_row_key(row: Mapping[str, Any]) -> str:
    serialized = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"rowhash-{digest[:24]}"


def _diagnostic_to_dict(diagnostic: Any) -> dict[str, Any]:
    if isinstance(diagnostic, Mapping):
        return {str(key): value for key, value in diagnostic.items()}
    result: dict[str, Any] = {}
    for key in (
        "source_alias",
        "status",
        "row_count",
        "elapsed_seconds",
        "error_code",
        "message",
        "query_summary",
        "metadata",
    ):
        value = getattr(diagnostic, key, None)
        if value is None:
            continue
        if key == "status":
            value = getattr(value, "value", value)
        result[key] = value
    return result


def _fetch_result_diagnostics(payload: Any) -> dict[str, Any]:
    source_results = getattr(payload, "source_results", ()) or ()
    errors = tuple(_redact_error_text(error) for error in (getattr(payload, "errors", ()) or ()))
    warnings = tuple(_redact_error_text(warning) for warning in (getattr(payload, "warnings", ()) or ()))
    return {
        "row_count": getattr(payload, "row_count", None),
        "has_errors": bool(getattr(payload, "has_errors", False)),
        "partial_success": bool(getattr(payload, "partial_success", False)),
        "warnings": warnings,
        "errors": errors,
        "source_results": tuple(_diagnostic_to_dict(result) for result in source_results),
    }


def _combine_fetch_diagnostics(payloads: list[Any]) -> dict[str, Any]:
    combined_sources: list[dict[str, Any]] = []
    combined_warnings: list[str] = []
    combined_errors: list[str] = []
    row_count = 0
    has_errors = False
    partial_success = False
    for payload in payloads:
        diagnostics = _fetch_result_diagnostics(payload)
        combined_sources.extend(diagnostics["source_results"])
        combined_warnings.extend(diagnostics["warnings"])
        combined_errors.extend(diagnostics["errors"])
        if diagnostics.get("row_count") is not None:
            row_count += int(diagnostics["row_count"] or 0)
        has_errors = has_errors or bool(diagnostics.get("has_errors"))
        partial_success = partial_success or bool(diagnostics.get("partial_success"))
    return {
        "row_count": row_count,
        "has_errors": has_errors or bool(combined_errors),
        "partial_success": partial_success or ((has_errors or bool(combined_errors)) and row_count > 0),
        "warnings": tuple(combined_warnings),
        "errors": tuple(combined_errors),
        "source_results": tuple(combined_sources),
    }


def _batched(values: tuple[str, ...], batch_size: int) -> tuple[tuple[str, ...], ...]:
    if not values:
        return ((),)
    safe_batch_size = max(1, int(batch_size))
    return tuple(values[index : index + safe_batch_size] for index in range(0, len(values), safe_batch_size))


def _construct_with_supported_kwargs(factory: Any, kwargs: dict[str, Any]) -> Any:
    """Instantiate an Oznak contract while tolerating older keyword surfaces."""
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory(**kwargs)

    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return factory(**kwargs)

    accepted = {
        name: value
        for name, value in kwargs.items()
        if name in parameters and value is not None
    }
    return factory(**accepted)


def _call_with_supported_kwargs(callable_obj: Any, *args: Any, **kwargs: Any) -> Any:
    """Call an Oznak function while tolerating older optional keyword surfaces."""

    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return callable_obj(*args, **kwargs)

    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return callable_obj(*args, **{key: value for key, value in kwargs.items() if value is not None})

    accepted = {
        key: value
        for key, value in kwargs.items()
        if key in parameters and value is not None
    }
    return callable_obj(*args, **accepted)


def _callable_accepts_keyword(callable_obj: Any, keyword: str) -> bool:
    if not callable(callable_obj):
        return False
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False
    return keyword in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _normalize_runtime_columns(
    columns: tuple[str, ...],
    *required_columns: Any,
) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for column in (*columns, *required_columns):
        text = str(column or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _normalize_query_filters(filters: Any) -> tuple[IndustrialQueryFilter, ...]:
    normalized: list[IndustrialQueryFilter] = []
    for filter_state in filters or ():
        if isinstance(filter_state, IndustrialQueryFilter):
            normalized.append(filter_state.validated())
            continue
        if isinstance(filter_state, Mapping):
            values = filter_state.get("values")
            if values is None and "value" in filter_state:
                values = (filter_state.get("value"),)
            elif isinstance(values, (str, bytes)):
                values = (values,)
            normalized.append(
                IndustrialQueryFilter(
                    column=str(filter_state.get("column") or ""),
                    operator=str(filter_state.get("operator") or ""),
                    values=tuple(values or ()),
                ).validated()
            )
    return tuple(normalized)


def deduplicate_reference_query_filters(
    filters: Any,
    *,
    reference_filter_column: str | None,
    reference_values: tuple[str, ...] | list[str] | None,
) -> tuple[tuple[IndustrialQueryFilter, ...], int]:
    """Drop generic filters that exactly duplicate the explicit reference scope."""

    normalized_filters = _normalize_query_filters(filters or ())
    reference_lookup = tuple(
        str(value).strip() for value in (reference_values or ()) if str(value).strip()
    )
    if not normalized_filters or not reference_lookup:
        return normalized_filters, 0
    filter_column = str(reference_filter_column or "reference").strip() or "reference"
    deduplicated: list[IndustrialQueryFilter] = []
    removed = 0
    for filter_state in normalized_filters:
        if (
            filter_state.column == filter_column
            and filter_state.operator == "IN"
            and filter_state.values == reference_lookup
        ):
            removed += 1
            continue
        deduplicated.append(filter_state)
    return tuple(deduplicated), removed


def _build_oznak_query_filters(
    query_filter_type: Any,
    filters: tuple[IndustrialQueryFilter, ...],
) -> tuple[Any, ...]:
    if not filters:
        return ()
    if query_filter_type is None:
        raise RuntimeError("oznak.QueryFilter is unavailable.")
    built: list[Any] = []
    for filter_state in filters:
        value: Any
        if filter_state.operator in {"IS NULL", "IS NOT NULL"}:
            value = None
        elif filter_state.operator in {"IN", "NOT IN"}:
            value = filter_state.values
        else:
            value = filter_state.values[0] if filter_state.values else ""
        built.append(
            query_filter_type(
                column=filter_state.column,
                operator=filter_state.operator,
                value=value,
            )
        )
    return tuple(built)


def map_oznak_rows_to_industrial_records(payload: Any, *, profile: Any) -> tuple[dict[str, Any], ...]:
    """Normalize Oznak rows into synthetic industrial record dictionaries."""

    rows = _extract_rows(payload)
    normalized_mappings = _normalize_column_mappings(profile)
    source_profile_id = _profile_value(profile, "profile_id", "id", "name")
    source_database_alias = _profile_value(
        profile, "source_db_alias", "database_alias", "db_alias", "alias"
    )

    records: list[dict[str, Any]] = []
    for row in rows:
        row_dict = _coerce_row_mapping(row)
        record: dict[str, Any] = {
            "source_profile_id": source_profile_id,
            "source_database_alias": source_database_alias,
        }
        for canonical_name, aliases in _ROW_KEY_ALIASES.items():
            mapped_column = normalized_mappings.get(canonical_name)
            value = None
            if mapped_column:
                value = _lookup_case_insensitive(row_dict, mapped_column)
            if value is None:
                for alias in aliases:
                    value = _lookup_case_insensitive(row_dict, alias)
                    if value is not None:
                        break
            record[canonical_name] = value
        if not record.get("source_primary_key"):
            record["source_primary_key"] = _stable_row_key(row_dict)
        for source_name, target_name in _REPOSITORY_FIELD_ALIASES.items():
            if record.get(source_name) is not None and record.get(target_name) is None:
                record[target_name] = record[source_name]
        for column_name, value in row_dict.items():
            field_name = str(column_name or "").strip()
            if not field_name or field_name in record or looks_sensitive_key(field_name):
                continue
            record[field_name] = value
        record["raw_record"] = row_dict
        records.append(record)
    return tuple(records)


def create_oznak_cancellation_token(*, import_module: Any = None) -> Any:
    """Create an Oznak cancellation token when the installed package supports it."""

    importer = import_module or importlib.import_module
    oznak_module = importer(OZNAK_IMPORT_PATH)
    token_type = getattr(oznak_module, "CancellationToken", None)
    if token_type is None:
        return None
    return token_type()


def fetch_oznak_records_for_source_profile(
    profile: Any,
    *,
    username: str,
    password: str,
    limit: int | None = None,
    timeout_seconds: float | None = None,
    reference_filter_column: str | None = None,
    reference_values: tuple[str, ...] | list[str] | None = None,
    query_filters: tuple[IndustrialQueryFilter, ...] | list[IndustrialQueryFilter] | None = None,
    chunk_size: int | None = DEFAULT_OZNAK_FETCH_CHUNK_SIZE,
    reference_batch_size: int = DEFAULT_REFERENCE_BATCH_SIZE,
    allow_unbounded: bool = False,
    cancellation_token: Any = None,
    progress_callback: Any = None,
    max_workers: int | None = None,
    max_pending_events: int | None = None,
    import_module: Any = None,
) -> OznakAdapterFetchResult:
    """Fetch live Oznak rows for one saved Metroliza industrial source profile."""

    importer = import_module or importlib.import_module
    status = get_oznak_adapter_status(import_module=importer)
    if not status.available:
        return OznakAdapterFetchResult(
            status=status,
            implemented=False,
            diagnostics={"stage": "availability"},
            error=status.error,
        )

    normalized_reference_values = tuple(
        str(value).strip() for value in (reference_values or ()) if str(value).strip()
    )
    normalized_query_filters, deduplicated_reference_query_filter_count = (
        deduplicate_reference_query_filters(
            query_filters or (),
            reference_filter_column=reference_filter_column,
            reference_values=normalized_reference_values,
        )
    )
    if not normalized_reference_values and not normalized_query_filters and limit is None and not allow_unbounded:
        return OznakAdapterFetchResult(
            status=status,
            implemented=True,
            diagnostics={"stage": "scope_validation", "reason": "unbounded_fetch_rejected"},
            error=(
                "Oznak fetch requires reference/ID values or an explicit row limit. "
                "Refusing an unbounded production-table read."
            ),
        )

    try:
        oznak_module = importer(OZNAK_IMPORT_PATH)
        database_profile_type = getattr(oznak_module, "DatabaseProfile")
        fetch_request_type = getattr(oznak_module, "FetchRequest")
        credential_provider_type = getattr(oznak_module, "MappingCredentialProvider")
        fetch_records = getattr(oznak_module, "fetch_records", None)
        fetch_records_chunked = getattr(oznak_module, "fetch_records_chunked", None)
        query_filter_type = getattr(oznak_module, "QueryFilter", None)
        if not callable(fetch_records):
            fetcher_module = importer(OZNAK_FETCHER_IMPORT_PATH)
            fetch_records = getattr(fetcher_module, "fetch_records", None)
            fetch_records_chunked = fetch_records_chunked or getattr(
                fetcher_module,
                "fetch_records_chunked",
                None,
            )
        if not callable(fetch_records):
            raise AttributeError("oznak.fetch_records is unavailable.")
    except Exception as exc:
        return OznakAdapterFetchResult(
            status=status,
            implemented=False,
            diagnostics={"stage": "contract_import"},
            error=_safe_exception_summary(exc),
        )

    alias = str(_profile_value(profile, "source_db_alias", "database_alias", "alias") or "").strip()
    database_type = str(_profile_value(profile, "database_type", "dialect") or "").strip().lower()
    host = str(_profile_value(profile, "host") or "").strip()
    port = _profile_value(profile, "port")
    database_name = str(_profile_value(profile, "database_name", "database") or "").strip()
    table_name = str(_profile_value(profile, "source_object_name", "table") or "").strip()
    timestamp_column = _profile_value(profile, "timestamp_column")
    pagination_column = _profile_value(profile, "default_pagination_column", "pagination_column")
    raw_order_by_enabled = _profile_value(profile, "order_by_enabled")
    order_by_enabled = True if raw_order_by_enabled is None else bool(raw_order_by_enabled)
    allowed_columns = _normalize_runtime_columns(
        tuple(_profile_value(profile, "allowed_columns") or ()),
        timestamp_column,
        pagination_column,
        reference_filter_column,
        *[filter_state.column for filter_state in normalized_query_filters],
    )

    try:
        oznak_profile = _construct_with_supported_kwargs(
            database_profile_type,
            {
                "alias": alias,
                "dialect": database_type,
                "host": host,
                "port": int(port) if port is not None else 0,
                "database": database_name,
                "table": table_name,
                "allowed_columns": allowed_columns,
                "timestamp_column": timestamp_column,
                "pagination_column": pagination_column,
                "display_name": _profile_value(profile, "profile_name"),
                "connect_timeout_seconds": timeout_seconds,
                "query_timeout_seconds": timeout_seconds,
                "order_by_enabled": order_by_enabled,
                "metadata": {"metroliza_source_profile_id": _profile_value(profile, "id", "profile_id")},
            },
        )
        fetch_columns = allowed_columns or None
        credential_provider = credential_provider_type({alias: (username, password)})
    except Exception as exc:
        return OznakAdapterFetchResult(
            status=status,
            implemented=True,
            diagnostics={"stage": "request_build"},
            error=_safe_exception_summary(exc),
        )

    payloads: list[Any] = []
    records_list: list[dict[str, Any]] = []
    remaining_limit = int(limit) if limit is not None else None
    reference_batches = _batched(normalized_reference_values, reference_batch_size)
    use_chunked_fetch = (
        callable(fetch_records_chunked)
        and chunk_size is not None
        and int(chunk_size) > 0
        and remaining_limit is None
        and bool(pagination_column)
        and order_by_enabled
    )

    try:
        for reference_batch in reference_batches:
            batch_limit = remaining_limit if remaining_limit is not None else None
            if batch_limit is not None and batch_limit <= 0:
                break
            filters = _build_oznak_query_filters(
                query_filter_type,
                normalized_query_filters,
            )
            if reference_batch:
                if query_filter_type is None:
                    raise RuntimeError("oznak.QueryFilter is unavailable.")
                filter_column = str(reference_filter_column or "reference").strip()
                filters = (
                    *filters,
                    query_filter_type(
                        column=filter_column,
                        operator="IN",
                        value=reference_batch,
                    ),
                )

            request = _construct_with_supported_kwargs(
                fetch_request_type,
                {
                    "profiles": (oznak_profile,),
                    "filters": filters,
                    "columns": fetch_columns,
                    "limit": batch_limit,
                    "date_column": timestamp_column,
                    "order_by_enabled": order_by_enabled,
                    "timeout_seconds": timeout_seconds,
                },
            )
            if use_chunked_fetch:
                payload = _call_with_supported_kwargs(
                    fetch_records_chunked,
                    request,
                    chunk_size=int(chunk_size),
                    pagination_column=str(pagination_column),
                    credential_provider=credential_provider,
                    cancellation_token=cancellation_token,
                    progress_callback=progress_callback,
                    max_workers=max_workers,
                    max_pending_events=max_pending_events,
                )
            else:
                payload = _call_with_supported_kwargs(
                    fetch_records,
                    request,
                    credential_provider=credential_provider,
                    cancellation_token=cancellation_token,
                    progress_callback=progress_callback,
                    max_workers=max_workers,
                )
            payloads.append(payload)
            batch_records = map_oznak_rows_to_industrial_records(payload, profile=profile)
            if remaining_limit is not None:
                batch_records = batch_records[:remaining_limit]
            records_list.extend(batch_records)
            if remaining_limit is not None:
                remaining_limit -= len(batch_records)
    except Exception as exc:
        return OznakAdapterFetchResult(
            status=status,
            implemented=True,
            diagnostics={"stage": "fetch_call", "reason": "runtime_error"},
            error=_safe_exception_summary(exc),
        )

    records = tuple(records_list)
    diagnostics = {
        "stage": "mapped",
        "raw_payload_type": type(payloads[-1]).__name__ if payloads else "None",
        "fetch_strategy": "chunked" if use_chunked_fetch else "single_request",
        "chunk_size": chunk_size if use_chunked_fetch else None,
        "reference_batch_size": int(reference_batch_size),
        "reference_batches": len(reference_batches),
        "reference_filter_column": reference_filter_column,
        "reference_filter_count": len(normalized_reference_values),
        "query_filter_count": len(normalized_query_filters),
        "deduplicated_reference_query_filter_count": deduplicated_reference_query_filter_count,
        "query_filters": tuple(
            {
                "column": filter_state.column,
                "operator": filter_state.operator,
                "value_count": len(filter_state.values),
            }
            for filter_state in normalized_query_filters
        ),
        "order_by_enabled": order_by_enabled,
        "max_workers": max_workers,
        "max_pending_events": max_pending_events if use_chunked_fetch else None,
    }
    diagnostics.update(_combine_fetch_diagnostics(payloads))
    errors = diagnostics.get("errors") or ()
    warnings = diagnostics.get("warnings") or ()
    partial_success = bool(diagnostics.get("partial_success"))
    if partial_success or warnings:
        diagnostics["completed_with_warnings"] = True
    error = "; ".join(str(item) for item in errors) if errors and not records else None
    return OznakAdapterFetchResult(
        status=status,
        records=records,
        row_count=len(records),
        implemented=True,
        diagnostics=diagnostics,
        error=error,
    )


def _call_fetch_records(fetch_records: Any, *, profile: Any, request: Any) -> Any:
    """Call the moving Oznak fetch API while it transitions to its final shape."""

    try:
        signature = inspect.signature(fetch_records)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        parameters = tuple(signature.parameters.values())
        positional = [
            parameter
            for parameter in parameters
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_varargs = any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters)
        if len(positional) <= 1 and not has_varargs:
            return fetch_records(request)
        if len(positional) >= 2:
            return fetch_records(profile, request)

    try:
        return fetch_records(request)
    except TypeError as one_arg_error:
        try:
            return fetch_records(profile, request)
        except TypeError:
            raise one_arg_error


def get_oznak_adapter_status(*, import_module: Any = None) -> OznakAdapterStatus:
    importer = import_module or importlib.import_module
    diagnostics: dict[str, Any] = {
        "import_path": OZNAK_IMPORT_PATH,
        "fetcher_import_path": OZNAK_FETCHER_IMPORT_PATH,
    }
    try:
        oznak_module = importer(OZNAK_IMPORT_PATH)
    except Exception as exc:
        return OznakAdapterStatus(
            available=False,
            diagnostics=diagnostics,
            error=_safe_exception_summary(exc),
        )

    version = getattr(oznak_module, "__version__", None)
    module_path = getattr(oznak_module, "__file__", None)
    diagnostics["version"] = version
    diagnostics["module_path"] = module_path

    contracts_available = all(
        hasattr(oznak_module, name) for name in ("DatabaseProfile", "FetchRequest", "FetchResult")
    )

    fetch_available = callable(getattr(oznak_module, "fetch_records", None))
    root_fetch_records = getattr(oznak_module, "fetch_records", None)
    root_fetch_records_chunked = getattr(oznak_module, "fetch_records_chunked", None)
    root_iter_records_chunked = getattr(oznak_module, "iter_records_chunked", None)
    chunked_fetch_available = callable(root_fetch_records_chunked)
    streaming_fetch_available = callable(root_iter_records_chunked)
    cancellation_available = callable(getattr(oznak_module, "CancellationToken", None))
    try:
        fetcher_module = importer(OZNAK_FETCHER_IMPORT_PATH)
        fetcher_fetch_records = getattr(fetcher_module, "fetch_records", None)
        fetcher_fetch_records_chunked = getattr(fetcher_module, "fetch_records_chunked", None)
        fetch_available = fetch_available or callable(fetcher_fetch_records)
        chunked_fetch_available = chunked_fetch_available or callable(fetcher_fetch_records_chunked)
        diagnostics["max_workers_supported"] = any(
            _callable_accepts_keyword(candidate, "max_workers")
            for candidate in (
                root_fetch_records,
                root_fetch_records_chunked,
                fetcher_fetch_records,
                fetcher_fetch_records_chunked,
            )
        )
    except Exception as exc:
        diagnostics["fetcher_import_error"] = _safe_exception_summary(exc)
        diagnostics["max_workers_supported"] = any(
            _callable_accepts_keyword(candidate, "max_workers")
            for candidate in (root_fetch_records, root_fetch_records_chunked)
        )

    diagnostics.update(
        {
            "query_request_available": hasattr(oznak_module, "QueryRequest"),
            "chunked_fetch_available": chunked_fetch_available,
            "streaming_fetch_available": streaming_fetch_available,
            "cancellation_available": cancellation_available,
            "source_diagnostics_available": all(
                hasattr(oznak_module, name)
                for name in ("SourceFetchDiagnostics", "SourceFetchStatus")
            ),
            "chunk_queue_supported": _callable_accepts_keyword(
                root_iter_records_chunked,
                "max_pending_events",
            )
            or _callable_accepts_keyword(root_fetch_records_chunked, "max_pending_events"),
            "synthetic_benchmark_available": callable(
                getattr(oznak_module, "run_synthetic_chunked_benchmark", None)
            ),
        }
    )

    return OznakAdapterStatus(
        available=True,
        version=str(version) if version is not None else None,
        module_path=str(module_path) if module_path is not None else None,
        contracts_available=contracts_available,
        fetch_available=fetch_available,
        chunked_fetch_available=chunked_fetch_available,
        streaming_fetch_available=streaming_fetch_available,
        cancellation_available=cancellation_available,
        diagnostics=diagnostics,
        error=None,
    )


def fetch_oznak_records(
    profile: Any,
    request: Any,
    *,
    import_module: Any = None,
) -> OznakAdapterFetchResult:
    importer = import_module or importlib.import_module
    status = get_oznak_adapter_status(import_module=importer)
    if not status.available:
        return OznakAdapterFetchResult(
            status=status,
            implemented=False,
            diagnostics={"stage": "availability"},
            error=status.error,
        )

    try:
        fetcher_module = importer(OZNAK_FETCHER_IMPORT_PATH)
    except Exception as exc:
        return OznakAdapterFetchResult(
            status=status,
            implemented=False,
            diagnostics={"stage": "fetcher_import"},
            error=_safe_exception_summary(exc),
        )

    fetch_records = getattr(fetcher_module, "fetch_records", None)
    if not callable(fetch_records):
        return OznakAdapterFetchResult(
            status=status,
            implemented=False,
            diagnostics={"stage": "fetch_call", "reason": "missing_fetch_records"},
            error="oznak.fetcher.fetch_records is unavailable.",
        )

    try:
        payload = _call_fetch_records(fetch_records, profile=profile, request=request)
    except NotImplementedError as exc:
        return OznakAdapterFetchResult(
            status=status,
            implemented=False,
            diagnostics={"stage": "fetch_call", "reason": "not_implemented"},
            error=_safe_exception_summary(exc),
        )
    except Exception as exc:
        return OznakAdapterFetchResult(
            status=status,
            implemented=True,
            diagnostics={"stage": "fetch_call", "reason": "runtime_error"},
            error=_safe_exception_summary(exc),
        )

    records = map_oznak_rows_to_industrial_records(payload, profile=profile)
    return OznakAdapterFetchResult(
        status=status,
        records=records,
        row_count=len(records),
        implemented=True,
        diagnostics={"stage": "mapped", "raw_payload_type": type(payload).__name__},
        error=None,
    )
