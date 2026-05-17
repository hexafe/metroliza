import pytest

from modules.env_utils import env_bool, env_choice, env_int, parse_bool, parse_int


def test_parse_bool_uses_common_values_and_default() -> None:
    assert parse_bool(" yes ") is True
    assert parse_bool("OFF", default=True) is False
    assert parse_bool("", default=True) is True
    assert parse_bool("unexpected", default=True) is True


def test_env_bool_supports_custom_values(monkeypatch) -> None:
    monkeypatch.setenv("METROLIZA_TEST_FLAG", "legacy")

    assert (
        env_bool(
            "METROLIZA_TEST_FLAG",
            default=True,
            false_values=frozenset({"legacy"}),
        )
        is False
    )


def test_env_choice_returns_default_for_missing_or_unknown(monkeypatch) -> None:
    monkeypatch.delenv("METROLIZA_TEST_BACKEND", raising=False)
    assert env_choice("METROLIZA_TEST_BACKEND", choices=frozenset({"auto", "python"}), default="auto") == "auto"

    monkeypatch.setenv("METROLIZA_TEST_BACKEND", "native")
    assert env_choice("METROLIZA_TEST_BACKEND", choices=frozenset({"auto", "python"}), default="auto") == "auto"

    monkeypatch.setenv("METROLIZA_TEST_BACKEND", "PYTHON")
    assert env_choice("METROLIZA_TEST_BACKEND", choices=frozenset({"auto", "python"}), default="auto") == "python"


def test_env_int_parses_values_and_reports_bad_input(monkeypatch) -> None:
    monkeypatch.setenv("METROLIZA_TEST_WORKERS", "4")
    assert env_int("METROLIZA_TEST_WORKERS") == 4
    assert parse_int("", default=2, name="workers") == 2

    monkeypatch.setenv("METROLIZA_TEST_WORKERS", "many")
    with pytest.raises(ValueError, match="METROLIZA_TEST_WORKERS must be an integer"):
        env_int("METROLIZA_TEST_WORKERS")
