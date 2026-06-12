from __future__ import annotations

import types

import pytest

from modules import oznak_adapter
from modules.industrial_workflow_state import IndustrialQueryFilter


def test_adapter_status_reports_unavailable_package_with_import_diagnostics(monkeypatch):
    def _fake_import(module_name: str):
        if module_name == "oznak":
            raise ModuleNotFoundError("No module named 'oznak'")
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    status = oznak_adapter.get_oznak_adapter_status()

    assert status.available is False
    assert status.import_path == "oznak"
    assert status.diagnostics["import_path"] == "oznak"
    assert "ModuleNotFoundError" in (status.error or "")


def test_adapter_status_reports_contracts_and_fetch_availability(monkeypatch):
    oznak_module = types.ModuleType("oznak")
    oznak_module.__version__ = "0.4.0a1"
    oznak_module.__file__ = "/tmp/oznak/__init__.py"
    oznak_module.DatabaseProfile = object
    oznak_module.FetchRequest = object
    oznak_module.FetchResult = object
    oznak_module.QueryRequest = object
    oznak_module.CancellationToken = object
    oznak_module.SourceFetchDiagnostics = object
    oznak_module.SourceFetchStatus = object
    oznak_module.fetch_records_chunked = lambda _request, **_kwargs: {"rows": []}
    oznak_module.iter_records_chunked = lambda _request, **_kwargs: iter(())
    oznak_module.run_synthetic_chunked_benchmark = lambda: None

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = lambda _request: {"rows": []}
    fetcher_module.fetch_records_chunked = lambda _request, **_kwargs: {"rows": []}

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    status = oznak_adapter.get_oznak_adapter_status()

    assert status.available is True
    assert status.contracts_available is True
    assert status.fetch_available is True
    assert status.chunked_fetch_available is True
    assert status.streaming_fetch_available is True
    assert status.cancellation_available is True
    assert status.version == "0.4.0a1"
    assert status.module_path == "/tmp/oznak/__init__.py"
    assert status.diagnostics["fetcher_import_path"] == "oznak.fetcher"
    assert status.diagnostics["query_request_available"] is True
    assert status.diagnostics["chunked_fetch_available"] is True
    assert status.diagnostics["streaming_fetch_available"] is True
    assert status.diagnostics["cancellation_available"] is True
    assert status.diagnostics["source_diagnostics_available"] is True
    assert status.diagnostics["chunk_queue_supported"] is True
    assert status.diagnostics["synthetic_benchmark_available"] is True


def test_adapter_status_reports_raw_sql_fallback_when_engine_contract_exists(monkeypatch):
    oznak_module = types.ModuleType("oznak")
    oznak_module.__version__ = "0.2.0rc1"
    oznak_module.DatabaseProfile = object
    oznak_module.FetchRequest = object
    oznak_module.FetchResult = object
    oznak_module.create_sqlalchemy_engine = lambda _profile, _credentials: object()

    fetcher_module = types.ModuleType("oznak.fetcher")

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        if module_name == "oznak.raw_sql":
            raise ModuleNotFoundError("No module named 'oznak.raw_sql'")
        if module_name == "sqlalchemy":
            return types.SimpleNamespace(text=lambda sql: sql)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    status = oznak_adapter.get_oznak_adapter_status()

    assert status.raw_sql_available is True
    assert status.diagnostics["raw_sql_contract_available"] is False
    assert status.diagnostics["raw_sql_engine_fallback_available"] is True


def test_fetch_reports_not_implemented_without_hard_failure(monkeypatch):
    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = object
    oznak_module.FetchRequest = object
    oznak_module.FetchResult = object

    fetcher_module = types.ModuleType("oznak.fetcher")

    def _raise_not_implemented(_request):
        raise NotImplementedError("fetch pending; password=supersecret")

    fetcher_module.fetch_records = _raise_not_implemented

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records(profile={"profile_id": "p1"}, request={"limit": 10})

    assert result.implemented is False
    assert result.row_count == 0
    assert result.records == ()
    assert "NotImplementedError" in (result.error or "")
    assert "supersecret" not in (result.error or "")
    assert "<redacted>" in (result.error or "")


def test_map_rows_normalizes_dataframe_like_payload_with_profile_mappings():
    class FakeDataFrame:
        def __init__(self, rows):
            self._rows = rows

        def to_dict(self, orient):
            assert orient == "records"
            return self._rows

    payload = FakeDataFrame(
        [
            {
                "id": "row-42",
                "ts": "2026-05-10T10:05:00Z",
                "serial_number": "SN-9001",
                "wo": "WO-7",
                "state": "OK",
                "part_no": "PN-11",
            }
        ]
    )
    profile = {
        "profile_id": "profile-a",
        "database_alias": "factory-main",
        "column_mappings": {
            "source_primary_key": "id",
            "process_timestamp": "ts",
            "serial": "serial_number",
            "work_order": "wo",
            "status": "state",
        },
    }

    records = oznak_adapter.map_oznak_rows_to_industrial_records(payload, profile=profile)

    assert len(records) == 1
    record = records[0]
    assert record["source_profile_id"] == "profile-a"
    assert record["source_database_alias"] == "factory-main"
    assert record["source_primary_key"] == "row-42"
    assert record["process_timestamp"] == "2026-05-10T10:05:00Z"
    assert record["serial"] == "SN-9001"
    assert record["work_order"] == "WO-7"
    assert record["status"] == "OK"
    assert record["part_number"] == "PN-11"
    assert record["raw_record"]["wo"] == "WO-7"


def test_fetch_supports_temporary_two_argument_fetch_shape(monkeypatch):
    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = object
    oznak_module.FetchRequest = object
    oznak_module.FetchResult = object

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = lambda _profile, _request: {"rows": [{"id": "ROW-1", "reference": "REF"}]}

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records(profile={"profile_id": "p1"}, request={"limit": 10})

    assert result.implemented is True
    assert result.row_count == 1
    assert result.records[0]["source_primary_key"] == "ROW-1"


def test_fetch_source_profile_builds_current_public_oznak_contract(monkeypatch):
    captured = {}
    progress_messages = []

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["profile"] = kwargs

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["request"] = kwargs

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping
            captured["credentials"] = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured.setdefault("filters", []).append(kwargs)

    class FakeResult:
        data = [
            {
                "event_id": "ROW-77",
                "event_at": "2026-05-10T12:30:00Z",
                "reference": "REF-77",
                "station": "S7",
            }
        ]
        source_results = (
            types.SimpleNamespace(
                source_alias="assembly_mes",
                status=types.SimpleNamespace(value="success"),
                row_count=1,
                elapsed_seconds=0.1,
                message="Fetched 1 row",
                query_summary="redacted query",
            ),
        )
        warnings = ()
        errors = ()
        row_count = 1
        has_errors = False
        partial_success = False

    def fake_fetch_records(
        request,
        *,
        credential_provider=None,
        cancellation_token=None,
        progress_callback=None,
    ):
        captured["fetch_request"] = request
        captured["credential_provider"] = credential_provider
        captured["cancellation_token"] = cancellation_token
        if progress_callback is not None:
            progress_callback(FakeResult.source_results[0])
        return FakeResult()

    oznak_module = types.ModuleType("oznak")
    oznak_module.__version__ = "0.1.0"
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records
    oznak_module.CancellationToken = lambda: object()

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)
    token = object()
    profile = types.SimpleNamespace(
        id=12,
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "event_at", "reference", "station"),
        timestamp_column="event_at",
        default_pagination_column="event_id",
        order_by_enabled=False,
    )

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        profile,
        username="operator",
        password="secret",
        limit=25,
        timeout_seconds=10,
        reference_filter_column="reference",
        reference_values=("REF-77", "REF-78"),
        cancellation_token=token,
        progress_callback=lambda diagnostic: progress_messages.append(diagnostic.message),
    )

    assert result.implemented is True
    assert result.error is None
    assert result.row_count == 1
    assert result.records[0]["source_primary_key"] == "ROW-77"
    assert result.records[0]["process_timestamp"] == "2026-05-10T12:30:00Z"
    assert result.records[0]["reference"] == "REF-77"
    assert captured["profile"]["alias"] == "assembly_mes"
    assert captured["profile"]["host"] == "mes.example.invalid"
    assert captured["profile"]["database"] == "plantdb"
    assert captured["profile"]["table"] == "events"
    assert captured["profile"]["pagination_column"] == "event_id"
    assert captured["profile"]["connect_timeout_seconds"] == 10
    assert captured["profile"]["query_timeout_seconds"] == 10
    assert captured["profile"]["order_by_enabled"] is False
    assert captured["profile"]["allowed_columns"] == (
        "event_id",
        "event_at",
        "reference",
        "station",
    )
    assert captured["request"]["limit"] == 25
    assert captured["request"]["timeout_seconds"] == 10
    assert captured["request"]["order_by_enabled"] is False
    assert captured["request"]["columns"] == (
        "event_id",
        "event_at",
        "reference",
        "station",
    )
    assert captured["request"]["filters"][0].column == "reference"
    assert captured["request"]["filters"][0].operator == "IN"
    assert captured["request"]["filters"][0].value == ("REF-77", "REF-78")
    assert captured["filters"] == [
        {"column": "reference", "operator": "IN", "value": ("REF-77", "REF-78")}
    ]
    assert captured["credentials"] == {"assembly_mes": ("operator", "secret")}
    assert captured["cancellation_token"] is token
    assert progress_messages == ["Fetched 1 row"]
    assert result.diagnostics["order_by_enabled"] is False


def test_fetch_source_profile_keeps_unrestricted_projection_for_empty_allowed_columns(
    monkeypatch,
):
    captured = {}

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["profile"] = kwargs

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["request"] = kwargs

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        data = [
            {
                "event_id": "ROW-1",
                "event_at": "2026-05-10T12:30:00Z",
                "reference": "REF-1",
                "station": "S1",
                "length_mm": 10.5,
            }
        ]
        source_results = ()
        warnings = ()
        errors = ()
        row_count = 1
        has_errors = False
        partial_success = False

    def fake_fetch_records(request, **_kwargs):
        captured["fetch_request"] = request
        return FakeResult()

    oznak_module = types.ModuleType("oznak")
    oznak_module.__version__ = "0.1.0"
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)
    profile = types.SimpleNamespace(
        id=12,
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=(),
        timestamp_column="event_at",
        default_pagination_column="event_id",
    )

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        profile,
        username="operator",
        password="secret",
        limit=10,
        reference_filter_column="reference",
        reference_values=("REF-1",),
        query_filters=(IndustrialQueryFilter("station", "=", ("S1",)),),
    )

    assert result.error is None
    assert result.row_count == 1
    assert captured["profile"]["allowed_columns"] == (
        "event_at",
        "event_id",
        "reference",
        "station",
    )
    assert captured["request"]["columns"] is None
    assert result.records[0]["length_mm"] == 10.5


def test_fetch_source_profile_deduplicates_reference_query_filter_and_keeps_generic_filters(
    monkeypatch,
):
    captured = {}

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["profile"] = kwargs

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["request"] = self

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        data = [{"event_id": "ROW-1", "reference": "REF-1", "station": "S1"}]
        source_results = ()
        warnings = ()
        errors = ()
        row_count = 1
        has_errors = False
        partial_success = False

    def fake_fetch_records(request, **_kwargs):
        captured["filters"] = request.filters
        return FakeResult()

    oznak_module = types.ModuleType("oznak")
    oznak_module.__version__ = "0.1.0"
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)
    profile = types.SimpleNamespace(
        id=12,
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "reference"),
        timestamp_column=None,
        default_pagination_column=None,
    )

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        profile,
        username="operator",
        password="secret",
        limit=100,
        reference_filter_column="reference",
        reference_values=("REF-1", "REF-2"),
        query_filters=(
            IndustrialQueryFilter("reference", "IN", ("REF-1", "REF-2")),
            IndustrialQueryFilter("station", "=", ("S1",)),
        ),
    )

    assert result.error is None
    assert result.row_count == 1
    assert [(item.column, item.operator, item.value) for item in captured["filters"]] == [
        ("station", "=", "S1"),
        ("reference", "IN", ("REF-1", "REF-2")),
    ]
    assert captured["profile"]["allowed_columns"] == ("event_id", "reference", "station")
    assert result.diagnostics["query_filter_count"] == 1
    assert result.diagnostics["deduplicated_reference_query_filter_count"] == 1
    assert result.diagnostics["reference_filter_count"] == 2


def test_fetch_source_sql_builds_raw_sql_contract(monkeypatch):
    captured = {}
    progress_messages = []

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["profile"] = kwargs

    class FakeRawSqlRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["request"] = kwargs

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping
            captured["credentials"] = mapping

    class FakeResult:
        data = [
            {
                "event_id": "ROW-99",
                "reference": "REF-99",
                "station": "S9",
            }
        ]
        source_results = (
            types.SimpleNamespace(
                source_alias="assembly_mes",
                status=types.SimpleNamespace(value="success"),
                row_count=1,
                elapsed_seconds=0.1,
                message="Fetched 1 row",
                query_summary="raw SQL preview",
                metadata={"mode": "preview"},
            ),
        )
        warnings = ()
        errors = ()
        row_count = 1
        has_errors = False
        partial_success = False

    def fake_fetch_raw_sql_records(
        request,
        *,
        credential_provider=None,
        cancellation_token=None,
        progress_callback=None,
    ):
        captured["fetch_request"] = request
        captured["credential_provider"] = credential_provider
        captured["cancellation_token"] = cancellation_token
        if progress_callback is not None:
            progress_callback(FakeResult.source_results[0])
        return FakeResult()

    oznak_module = types.ModuleType("oznak")
    oznak_module.__version__ = "0.2.0rc2"
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = object
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.RawSqlRequest = FakeRawSqlRequest
    oznak_module.fetch_raw_sql_records = fake_fetch_raw_sql_records

    fetcher_module = types.ModuleType("oznak.fetcher")

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        if module_name == "oznak.raw_sql":
            return oznak_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)
    token = object()
    profile = types.SimpleNamespace(
        id=12,
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "reference"),
        timestamp_column=None,
        default_pagination_column="event_id",
        order_by_enabled=True,
    )

    result = oznak_adapter.fetch_oznak_records_for_source_sql(
        profile,
        username="operator",
        password="secret",
        sql_text="SELECT event_id, reference, station FROM events",
        limit=5,
        timeout_seconds=20,
        mode="preview",
        cancellation_token=token,
        progress_callback=lambda diagnostic: progress_messages.append(diagnostic.message),
    )

    assert result.implemented is True
    assert result.error is None
    assert result.row_count == 1
    assert result.records[0]["source_primary_key"] == "ROW-99"
    assert result.records[0]["raw_record"]["station"] == "S9"
    assert captured["profile"]["alias"] == "assembly_mes"
    assert captured["request"]["sql"] == "SELECT event_id, reference, station FROM events"
    assert captured["request"]["limit"] == 5
    assert captured["request"]["mode"] == "preview"
    assert captured["credentials"] == {"assembly_mes": ("operator", "secret")}
    assert captured["cancellation_token"] is token
    assert progress_messages == ["Fetched 1 row"]
    assert result.diagnostics["fetch_mode"] == "sql"
    assert result.diagnostics["sql_limit"] == 5
    assert "sql_hash" in result.diagnostics


def test_fetch_source_sql_uses_engine_fallback_when_raw_contract_missing(monkeypatch):
    captured = {}
    progress_messages = []

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured["profile"] = kwargs

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

        def get_credentials(self, alias):
            captured["credential_alias"] = alias
            return self.mapping[alias]

    class FakeMappings:
        def __init__(self):
            self.calls = 0

        def fetchmany(self, limit):
            self.calls += 1
            captured.setdefault("fetch_limits", []).append(limit)
            if self.calls > 1:
                return []
            return [
                {
                    "event_id": "ROW-88",
                    "reference": "REF-88",
                    "station": "S8",
                }
            ]

    class FakeCursor:
        def __init__(self):
            self._mappings = FakeMappings()

        def mappings(self):
            return self._mappings

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement):
            captured["sql"] = str(statement)
            return FakeCursor()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            captured["disposed"] = True

    def fake_engine_factory(profile, credentials):
        captured["engine_profile"] = profile
        captured["engine_credentials"] = credentials
        return FakeEngine()

    oznak_module = types.ModuleType("oznak")
    oznak_module.__version__ = "0.2.0rc1"
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = object
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.create_sqlalchemy_engine = fake_engine_factory

    fetcher_module = types.ModuleType("oznak.fetcher")

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        if module_name == "oznak.raw_sql":
            raise ModuleNotFoundError("No module named 'oznak.raw_sql'")
        if module_name == "sqlalchemy":
            return types.SimpleNamespace(text=lambda sql: sql)
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)
    profile = types.SimpleNamespace(
        id=12,
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "reference"),
        timestamp_column=None,
        default_pagination_column="event_id",
        order_by_enabled=True,
    )

    result = oznak_adapter.fetch_oznak_records_for_source_sql(
        profile,
        username="operator",
        password="secret",
        sql_text="SELECT event_id, reference, station FROM events WHERE status = 'delete'",
        limit=5,
        mode="preview",
        progress_callback=lambda diagnostic: progress_messages.append(diagnostic.message),
    )

    assert result.implemented is True
    assert result.error is None
    assert result.row_count == 1
    assert result.records[0]["source_primary_key"] == "ROW-88"
    assert result.records[0]["raw_record"]["station"] == "S8"
    assert captured["profile"]["alias"] == "assembly_mes"
    assert captured["credential_alias"] == "assembly_mes"
    assert captured["engine_credentials"] == ("operator", "secret")
    assert captured["fetch_limits"][0] == 5
    assert captured["disposed"] is True
    assert captured["sql"] == "SELECT event_id, reference, station FROM events WHERE status = 'delete'"
    assert progress_messages[-1] == "Fetched 1 rows from source 'assembly_mes'"
    assert result.diagnostics["raw_sql_contract"] == "metroliza_engine_fallback"


@pytest.mark.parametrize(
    "sql_text",
    [
        "SELECT event_id INTO scratch_events FROM events",
        "WITH visible AS (SELECT event_id FROM events) SELECT event_id INTO scratch FROM visible",
        "SELECT event_id, reference FROM events INTO OUTFILE '/tmp/events.csv'",
        "SELECT event_id FROM events INTO DUMPFILE '/tmp/events.bin'",
        "SELECT event_id FROM events WHERE status = 'queued' FOR UPDATE",
        "SELECT event_id FROM events WHERE status = 'queued' LOCK IN SHARE MODE",
    ],
)
def test_raw_sql_validator_rejects_select_forms_with_side_effects(sql_text):
    with pytest.raises(ValueError):
        oznak_adapter._validate_raw_select_sql(sql_text)


def test_raw_sql_validator_allows_side_effect_keywords_inside_literals_and_comments():
    sql_text = """
        SELECT event_id, 'INTO OUTFILE', "FOR UPDATE", [LOCK IN SHARE MODE]
        FROM events
        WHERE status = 'SELECT INTO scratch'
        -- SELECT event_id INTO scratch FROM events
        /* SELECT event_id FROM events LOCK IN SHARE MODE */
    """

    assert oznak_adapter._validate_raw_select_sql(sql_text) == sql_text.strip()


def test_raw_sql_validator_allows_schema_qualified_objects_in_sql_mode():
    sql_text = "SELECT event_id, reference FROM dbo.events WHERE station = 'S1'"

    assert oznak_adapter._validate_raw_select_sql(sql_text) == sql_text


def test_fetch_source_sql_fallback_rejects_write_statement(monkeypatch):
    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = object
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.create_sqlalchemy_engine = lambda _profile, _credentials: object()

    fetcher_module = types.ModuleType("oznak.fetcher")

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        if module_name == "oznak.raw_sql":
            raise ModuleNotFoundError("No module named 'oznak.raw_sql'")
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records_for_source_sql(
        types.SimpleNamespace(
            id=12,
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "reference"),
            timestamp_column=None,
            default_pagination_column="event_id",
        ),
        username="operator",
        password="secret",
        sql_text="DELETE FROM events",
        limit=5,
        mode="preview",
    )

    assert result.implemented is True
    assert "Only SELECT queries are supported" in (result.error or "")


def test_fetch_source_profile_falls_back_to_fetcher_module_when_root_fetch_missing(monkeypatch):
    calls = {"fetcher": 0}

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeResult:
        data = [{"event_id": "ROW-1", "reference": "REF-1"}]
        source_results = ()
        warnings = ()
        errors = ()
        row_count = 1
        has_errors = False
        partial_success = False

    def fake_fetch_records(*args, **kwargs):
        calls["fetcher"] += 1
        return FakeResult()

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        types.SimpleNamespace(
            id=12,
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "reference"),
            timestamp_column=None,
            default_pagination_column=None,
        ),
        username="operator",
        password="secret",
        limit=1,
    )

    assert result.error is None
    assert result.row_count == 1
    assert calls["fetcher"] == 1


def test_map_rows_generates_stable_record_key_when_source_key_missing():
    payload = {"rows": [{"reference": "REF-1", "station": "S1"}]}
    profile = {"profile_id": "p1", "source_db_alias": "assembly_mes"}

    first = oznak_adapter.map_oznak_rows_to_industrial_records(payload, profile=profile)
    second = oznak_adapter.map_oznak_rows_to_industrial_records(payload, profile=profile)

    assert first[0]["source_primary_key"].startswith("rowhash-")
    assert first[0]["source_primary_key"] == second[0]["source_primary_key"]


def test_fetch_source_profile_uses_chunked_reference_batches_by_default(monkeypatch):
    calls = {"chunked": [], "single": 0}

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        def __init__(self, references):
            self.data = [
                {"event_id": f"ROW-{reference}", "reference": reference}
                for reference in references
            ]
            self.source_results = ()
            self.warnings = ()
            self.errors = ()
            self.row_count = len(self.data)
            self.has_errors = False
            self.partial_success = False

    def fake_fetch_records(*args, **kwargs):
        calls["single"] += 1
        return FakeResult(())

    def fake_fetch_records_chunked(
        request,
        *,
        chunk_size,
        pagination_column,
        credential_provider=None,
        cancellation_token=None,
        progress_callback=None,
        read_sql=None,
        engine_factory=None,
        max_workers=None,
        max_pending_events=None,
    ):
        references = request.filters[0].value
        calls["chunked"].append(
            {
                "references": references,
                "chunk_size": chunk_size,
                "pagination_column": pagination_column,
                "max_workers": max_workers,
                "max_pending_events": max_pending_events,
            }
        )
        return FakeResult(references)

    oznak_module = types.ModuleType("oznak")
    oznak_module.__version__ = "0.1.0"
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records
    oznak_module.fetch_records_chunked = fake_fetch_records_chunked

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)
    profile = types.SimpleNamespace(
        id=12,
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "reference"),
        timestamp_column=None,
        default_pagination_column="event_id",
    )

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        profile,
        username="operator",
        password="secret",
        reference_filter_column="reference",
        reference_values=("REF1", "REF2", "REF3"),
        chunk_size=1000,
        reference_batch_size=2,
        max_workers=4,
        max_pending_events=8,
    )

    assert calls["single"] == 0
    assert calls["chunked"] == [
        {
            "references": ("REF1", "REF2"),
            "chunk_size": 1000,
            "pagination_column": "event_id",
            "max_workers": 4,
            "max_pending_events": 8,
        },
        {
            "references": ("REF3",),
            "chunk_size": 1000,
            "pagination_column": "event_id",
            "max_workers": 4,
            "max_pending_events": 8,
        },
    ]
    assert result.row_count == 3
    assert result.diagnostics["fetch_strategy"] == "chunked"
    assert result.diagnostics["reference_batches"] == 2
    assert result.diagnostics["max_workers"] == 4
    assert result.diagnostics["max_pending_events"] == 8
    assert {record["reference"] for record in result.records} == {"REF1", "REF2", "REF3"}


def test_fetch_source_profile_order_by_disabled_uses_single_fetch(monkeypatch):
    calls = {"chunked": 0, "single": []}

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        data = [{"event_id": "ROW-REF1", "reference": "REF1"}]
        source_results = ()
        warnings = ()
        errors = ()
        row_count = 1
        has_errors = False
        partial_success = False

    def fake_fetch_records(request, **kwargs):
        calls["single"].append(
            {
                "filters": request.filters,
                "order_by_enabled": request.order_by_enabled,
            }
        )
        return FakeResult()

    def fake_fetch_records_chunked(*args, **kwargs):
        calls["chunked"] += 1
        return FakeResult()

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records
    oznak_module.fetch_records_chunked = fake_fetch_records_chunked

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)
    profile = types.SimpleNamespace(
        id=12,
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "reference"),
        timestamp_column=None,
        default_pagination_column="event_id",
        order_by_enabled=False,
    )

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        profile,
        username="operator",
        password="secret",
        reference_filter_column="reference",
        reference_values=("REF1",),
        chunk_size=1000,
    )

    assert calls["chunked"] == 0
    assert len(calls["single"]) == 1
    assert calls["single"][0]["order_by_enabled"] is False
    assert result.diagnostics["fetch_strategy"] == "single_request"
    assert result.diagnostics["order_by_enabled"] is False


def test_fetch_source_profile_limit_zero_does_not_call_fetch(monkeypatch):
    calls = {"single": 0, "chunked": 0, "filters": 0}

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            calls["filters"] += 1
            self.__dict__.update(kwargs)

    def fake_fetch_records(*args, **kwargs):
        calls["single"] += 1
        return {"rows": []}

    def fake_fetch_records_chunked(*args, **kwargs):
        calls["chunked"] += 1
        return {"rows": []}

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records
    oznak_module.fetch_records_chunked = fake_fetch_records_chunked

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        types.SimpleNamespace(
            id=12,
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "reference"),
            timestamp_column=None,
            default_pagination_column="event_id",
        ),
        username="operator",
        password="secret",
        limit=0,
        reference_filter_column="reference",
        reference_values=("REF1", "REF2"),
        reference_batch_size=1,
    )

    assert result.row_count == 0
    assert calls == {"single": 0, "chunked": 0, "filters": 0}


def test_fetch_source_profile_limit_uses_single_fetch_across_reference_batches(monkeypatch):
    calls = []

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        def __init__(self, references):
            self.data = [{"event_id": f"ROW-{reference}", "reference": reference} for reference in references]
            self.source_results = ()
            self.warnings = ()
            self.errors = ()
            self.row_count = len(self.data)
            self.has_errors = False
            self.partial_success = False

    def fake_fetch_records(request, **kwargs):
        references = request.filters[0].value
        calls.append((references, request.limit))
        return FakeResult(references)

    def fake_fetch_records_chunked(*args, **kwargs):
        raise AssertionError("chunked fetch should not run when a limit is passed")

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records
    oznak_module.fetch_records_chunked = fake_fetch_records_chunked

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = oznak_module.fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        types.SimpleNamespace(
            id=12,
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "reference"),
            timestamp_column=None,
            default_pagination_column="event_id",
        ),
        username="operator",
        password="secret",
        limit=2,
        reference_filter_column="reference",
        reference_values=("REF1", "REF2", "REF3"),
        reference_batch_size=0,
    )

    assert calls == [(("REF1",), 2), (("REF2",), 1)]
    assert result.row_count == 2
    assert {record["reference"] for record in result.records} == {"REF1", "REF2"}
    assert result.diagnostics["reference_batches"] == 3
    assert result.diagnostics["fetch_strategy"] == "single_request"


def test_fetch_source_profile_marks_partial_success_as_completed_with_warnings(monkeypatch):
    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeResult:
        data = [{"event_id": "ROW-1", "reference": "REF1"}]
        source_results = ()
        warnings = ("secondary source timed out password=secret",)
        errors = ()
        row_count = 1
        has_errors = True
        partial_success = True

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.fetch_records = lambda *args, **kwargs: FakeResult()

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = oznak_module.fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        types.SimpleNamespace(
            id=12,
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "reference"),
            timestamp_column=None,
            default_pagination_column=None,
        ),
        username="operator",
        password="secret",
        limit=10,
    )

    assert result.error is None
    assert result.row_count == 1
    assert result.diagnostics["completed_with_warnings"] is True
    assert result.diagnostics["partial_success"] is True
    assert result.diagnostics["warnings"] == ("secondary source timed out password=<redacted>",)


def test_fetch_source_profile_rejects_direct_unbounded_fetch_without_references(monkeypatch):
    calls = {"single": [], "chunked": 0, "filters": 0}

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            calls["filters"] += 1
            self.__dict__.update(kwargs)

    class FakeResult:
        data = [{"event_id": "ROW-1", "reference": "REF1"}]
        source_results = ()
        warnings = ()
        errors = ()
        row_count = 1
        has_errors = False
        partial_success = False

    def fake_fetch_records(request, **kwargs):
        calls["single"].append(request.filters)
        return FakeResult()

    def fake_fetch_records_chunked(*args, **kwargs):
        calls["chunked"] += 1
        return FakeResult()

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records
    oznak_module.fetch_records_chunked = fake_fetch_records_chunked

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        types.SimpleNamespace(
            id=12,
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "reference"),
            timestamp_column=None,
            default_pagination_column="event_id",
        ),
        username="operator",
        password="secret",
        reference_values=(),
    )

    assert calls == {"single": [], "chunked": 0, "filters": 0}
    assert result.row_count == 0
    assert result.error == (
        "Oznak fetch requires reference/ID values or an explicit row limit. "
        "Refusing an unbounded production-table read."
    )
    assert result.diagnostics["reason"] == "unbounded_fetch_rejected"


def test_fetch_source_profile_allows_explicit_unbounded_fetch_when_requested(monkeypatch):
    calls = {"single": [], "chunked": 0, "filters": 0}

    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    class FakeQueryFilter:
        def __init__(self, **kwargs):
            calls["filters"] += 1
            self.__dict__.update(kwargs)

    class FakeResult:
        data = [{"event_id": "ROW-1", "reference": "REF1"}]
        source_results = ()
        warnings = ()
        errors = ()
        row_count = 1
        has_errors = False
        partial_success = False

    def fake_fetch_records(request, **kwargs):
        calls["single"].append(request.filters)
        return FakeResult()

    def fake_fetch_records_chunked(*args, **kwargs):
        calls["chunked"] += 1
        return FakeResult()

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.QueryFilter = FakeQueryFilter
    oznak_module.fetch_records = fake_fetch_records
    oznak_module.fetch_records_chunked = fake_fetch_records_chunked

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        types.SimpleNamespace(
            id=12,
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "reference"),
            timestamp_column=None,
            default_pagination_column="event_id",
        ),
        username="operator",
        password="secret",
        reference_values=(),
        chunk_size=0,
        allow_unbounded=True,
    )

    assert calls == {"single": [()], "chunked": 0, "filters": 0}
    assert result.row_count == 1
    assert result.diagnostics["fetch_strategy"] == "single_request"


def test_fetch_source_profile_redacts_runtime_fetch_exceptions(monkeypatch):
    class FakeDatabaseProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeFetchRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCredentialProvider:
        def __init__(self, mapping):
            self.mapping = mapping

    def fake_fetch_records(*args, **kwargs):
        raise RuntimeError(
            "mssql://operator:uri-secret@db.example.invalid failed "
            "password=plain-secret token:token-secret {'clientSecret': 'dict-secret'}"
        )

    oznak_module = types.ModuleType("oznak")
    oznak_module.DatabaseProfile = FakeDatabaseProfile
    oznak_module.FetchRequest = FakeFetchRequest
    oznak_module.FetchResult = object
    oznak_module.MappingCredentialProvider = FakeCredentialProvider
    oznak_module.fetch_records = fake_fetch_records

    fetcher_module = types.ModuleType("oznak.fetcher")
    fetcher_module.fetch_records = fake_fetch_records

    def _fake_import(module_name: str):
        if module_name == "oznak":
            return oznak_module
        if module_name == "oznak.fetcher":
            return fetcher_module
        raise AssertionError(f"Unexpected import: {module_name}")

    monkeypatch.setattr(oznak_adapter.importlib, "import_module", _fake_import)

    result = oznak_adapter.fetch_oznak_records_for_source_profile(
        types.SimpleNamespace(
            id=12,
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "reference"),
            timestamp_column=None,
            default_pagination_column=None,
        ),
        username="operator",
        password="secret",
        limit=1,
    )

    assert result.error
    for secret in ("uri-secret", "plain-secret", "token-secret", "dict-secret"):
        assert secret not in result.error
    assert result.error.count("<redacted>") >= 4
