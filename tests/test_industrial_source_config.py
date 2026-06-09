from __future__ import annotations

import pytest
import yaml

from modules.industrial_credentials import (
    credential_env_keys,
    load_industrial_credentials,
    save_industrial_credentials,
)
from modules.industrial_data_repository import IndustrialDataRepository
from modules.industrial_source_config import (
    IndustrialSourceConfigError,
    build_source_profile,
    import_source_profiles_to_repository,
    load_source_profiles_from_config,
    upsert_source_profile_in_config,
)


def test_source_config_round_trip_uses_oznak_yaml_shape_without_credentials(tmp_path):
    config_path = tmp_path / "industrial_sources.yaml"
    profile = build_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        source_object_name="events",
        allowed_columns=("event_id", "reference", "station"),
        timestamp_column="event_at",
        default_pagination_column="event_id",
        order_by_enabled=False,
    )

    upsert_source_profile_in_config(config_path, profile)

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert set(payload) == {"databases"}
    assert payload["databases"]["assembly_mes"] == {
        "type": "mssql",
        "host": "mes.example.invalid",
        "port": 1433,
        "database": "plantdb",
        "table": "events",
        "display_name": "Assembly MES",
        "allowed_columns": ["event_id", "reference", "station"],
        "timestamp_column": "event_at",
        "pagination_column": "event_id",
        "order_by_enabled": False,
    }
    assert "password" not in config_path.read_text(encoding="utf-8").lower()

    loaded = load_source_profiles_from_config(config_path)
    assert len(loaded) == 1
    assert loaded[0].profile_key == "assembly_mes"
    assert loaded[0].database_type == "mssql"
    assert loaded[0].allowed_columns == ("event_id", "reference", "station")
    assert loaded[0].order_by_enabled is False


def test_source_config_imports_manual_file_profiles_into_selected_database(tmp_path):
    config_path = tmp_path / "industrial_sources.yaml"
    config_path.write_text(
        """
databases:
  line_a:
    type: mysql
    host: db.example.invalid
    port: 3306
    database: processdb
    table: events
    display_name: Line A
    allowed_columns:
      - id
      - reference
      - station
    pagination_column: id
""".strip(),
        encoding="utf-8",
    )
    db_path = str(tmp_path / "metroliza.db")

    imported = import_source_profiles_to_repository(
        config_path,
        IndustrialDataRepository(db_path),
    )
    profiles = IndustrialDataRepository(db_path).list_source_profiles(include_disabled=True)

    assert [profile.profile_key for profile in imported] == ["line_a"]
    assert len(profiles) == 1
    assert profiles[0].profile_name == "Line A"
    assert profiles[0].host == "db.example.invalid"
    assert profiles[0].default_pagination_column == "id"
    assert profiles[0].order_by_enabled is True


def test_source_config_loads_order_by_disabled_from_manual_file(tmp_path):
    config_path = tmp_path / "industrial_sources.yaml"
    config_path.write_text(
        """
databases:
  line_a:
    type: mssql
    host: db.example.invalid
    port: 1433
    database: processdb
    table: events
    order_by_enabled: false
""".strip(),
        encoding="utf-8",
    )

    profiles = load_source_profiles_from_config(config_path)

    assert len(profiles) == 1
    assert profiles[0].order_by_enabled is False


def test_source_config_rejects_scalar_allowed_columns_from_manual_file(tmp_path):
    config_path = tmp_path / "industrial_sources.yaml"
    config_path.write_text(
        """
databases:
  line_a:
    type: mysql
    host: db.example.invalid
    port: 3306
    database: processdb
    table: events
    allowed_columns: reference
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(IndustrialSourceConfigError, match="allowed_columns.*sequence"):
        load_source_profiles_from_config(config_path)


@pytest.mark.parametrize("raw_columns", ["reference", 123])
def test_build_source_profile_rejects_scalar_allowed_columns(raw_columns):
    with pytest.raises(IndustrialSourceConfigError, match="allowed_columns.*sequence"):
        build_source_profile(
            profile_key="line_a",
            profile_name="Line A",
            source_db_alias="line_a",
            database_type="mysql",
            host="db.example.invalid",
            port=3306,
            database_name="processdb",
            source_object_name="events",
            allowed_columns=raw_columns,
        )


def test_source_config_rejects_credential_like_keys(tmp_path):
    config_path = tmp_path / "industrial_sources.yaml"
    config_path.write_text(
        """
databases:
  line_a:
    type: mysql
    host: db.example.invalid
    port: 3306
    database: processdb
    table: events
    password: should-not-be-here
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(IndustrialSourceConfigError, match="credential-like"):
        load_source_profiles_from_config(config_path)


def test_source_config_rejects_nested_camel_case_credentials(tmp_path):
    config_path = tmp_path / "industrial_sources.yaml"
    config_path.write_text(
        """
databases:
  line_a:
    type: mysql
    host: db.example.invalid
    port: 3306
    database: processdb
    table: events
    options:
      apiKey: should-not-be-here
      nested:
        clientSecret: also-secret
        refreshToken: token-secret
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(IndustrialSourceConfigError) as excinfo:
        load_source_profiles_from_config(config_path)

    message = str(excinfo.value)
    assert "options.apiKey" in message
    assert "options.nested.clientSecret" in message
    assert "options.nested.refreshToken" in message


def test_local_credential_store_round_trip_uses_user_env_file(tmp_path):
    credential_path = tmp_path / "industrial_credentials.env"
    username_key, password_key = credential_env_keys("assembly_mes")

    saved_path = save_industrial_credentials(
        "assembly_mes",
        username="operator",
        password="secret password",
        credential_path=credential_path,
    )

    assert saved_path == credential_path
    assert username_key in credential_path.read_text(encoding="utf-8")
    assert password_key in credential_path.read_text(encoding="utf-8")
    assert credential_path.stat().st_mode & 0o777 == 0o600

    loaded = load_industrial_credentials(
        "assembly_mes",
        credential_path=credential_path,
        environ={},
    )

    assert loaded.username == "operator"
    assert loaded.password == "secret password"
    assert loaded.source == str(credential_path)
