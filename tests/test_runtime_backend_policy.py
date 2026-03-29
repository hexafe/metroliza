import sys

from modules import cmm_native_parser, comparison_stats_native, distribution_fit_candidate_native, group_stats_native
from modules.runtime_backend_policy import should_prefer_python_backend_in_auto_mode


def test_runtime_policy_prefers_python_in_frozen_auto_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("METROLIZA_ENABLE_NATIVE_IN_FROZEN", raising=False)
    assert should_prefer_python_backend_in_auto_mode() is True


def test_runtime_policy_allows_native_override_in_frozen_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("METROLIZA_ENABLE_NATIVE_IN_FROZEN", "1")
    assert should_prefer_python_backend_in_auto_mode() is False


def test_runtime_policy_runtime_choices_downgrade_auto_to_python_in_frozen_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("METROLIZA_ENABLE_NATIVE_IN_FROZEN", raising=False)
    monkeypatch.delenv("METROLIZA_GROUP_STATS_BACKEND", raising=False)
    monkeypatch.delenv("METROLIZA_COMPARISON_STATS_CI_BACKEND", raising=False)
    monkeypatch.delenv("METROLIZA_COMPARISON_STATS_BACKEND", raising=False)
    monkeypatch.delenv("METROLIZA_CMM_PARSER_BACKEND", raising=False)
    monkeypatch.delenv("METROLIZA_CMM_PERSIST_BACKEND", raising=False)
    monkeypatch.delenv("METROLIZA_DISTRIBUTION_FIT_KERNEL", raising=False)

    assert group_stats_native._runtime_backend_choice() == "python"
    assert comparison_stats_native._runtime_backend_choice() == "python"
    assert comparison_stats_native._runtime_pairwise_backend_choice() == "python"
    assert cmm_native_parser._runtime_backend_choice() == "python"
    assert cmm_native_parser._runtime_persistence_backend_choice() == "python"
    assert distribution_fit_candidate_native.resolve_kernel_mode(None) == "python"
