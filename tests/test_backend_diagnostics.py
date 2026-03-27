from modules import backend_diagnostics


def test_backend_diagnostics_reports_native_available(monkeypatch):
    monkeypatch.setattr(backend_diagnostics.cmm_native_parser, "_runtime_backend_choice", lambda: "auto")
    monkeypatch.setattr(backend_diagnostics.cmm_native_parser, "native_backend_available", lambda: True)
    monkeypatch.setattr(backend_diagnostics.cmm_native_parser, "resolve_cmm_parser_backend", lambda: "native")

    summary = backend_diagnostics.build_backend_diagnostic_summary()
    parser_status = summary["cmm_parser"]

    assert parser_status["available"] is True
    assert parser_status["selected_mode"] == "auto"
    assert parser_status["effective_backend"] == "native"
    assert parser_status["status"] == "native_available"
    assert parser_status["forced_native_failure"] is False


def test_backend_diagnostics_reports_native_unavailable_fallback(monkeypatch):
    monkeypatch.setattr(backend_diagnostics.chart_renderer, "_runtime_backend_choice", lambda: "auto")
    monkeypatch.setattr(backend_diagnostics.chart_renderer, "native_chart_backend_available", lambda: False)
    monkeypatch.setattr(backend_diagnostics.chart_renderer, "native_histogram_backend_available", lambda: False)
    monkeypatch.setattr(backend_diagnostics.chart_renderer, "native_distribution_backend_available", lambda: False)
    monkeypatch.setattr(backend_diagnostics.chart_renderer, "resolve_chart_renderer_backend", lambda: "matplotlib")

    summary = backend_diagnostics.build_backend_diagnostic_summary()
    chart_status = summary["chart_renderer"]

    assert chart_status["available"] is False
    assert chart_status["selected_mode"] == "auto"
    assert chart_status["effective_backend"] == "matplotlib"
    assert chart_status["histogram_available"] is False
    assert chart_status["distribution_available"] is False
    assert chart_status["status"] == "native_unavailable_fallback"
    assert chart_status["forced_native_failure"] is False


def test_backend_diagnostics_reports_forced_native_failure(monkeypatch):
    monkeypatch.setattr(backend_diagnostics.cmm_native_parser, "_runtime_backend_choice", lambda: "native")
    monkeypatch.setattr(backend_diagnostics.cmm_native_parser, "native_backend_available", lambda: False)

    def _raise_forced():
        raise RuntimeError("Native CMM parser backend requested but unavailable")

    monkeypatch.setattr(backend_diagnostics.cmm_native_parser, "resolve_cmm_parser_backend", _raise_forced)

    summary = backend_diagnostics.build_backend_diagnostic_summary()
    parser_status = summary["cmm_parser"]

    assert parser_status["available"] is False
    assert parser_status["selected_mode"] == "native"
    assert parser_status["effective_backend"] == "python"
    assert parser_status["status"] == "forced_native_failure"
    assert parser_status["forced_native_failure"] is True
    assert "unavailable" in parser_status["error"].lower()


def test_backend_diagnostics_reports_group_stats_forced_native_failure(monkeypatch):
    monkeypatch.setattr(backend_diagnostics.group_stats_native, "_runtime_backend_choice", lambda: "native")
    monkeypatch.setattr(backend_diagnostics.group_stats_native, "native_backend_available", lambda: False)

    summary = backend_diagnostics.build_backend_diagnostic_summary()
    group_status = summary["group_stats"]

    assert group_status["available"] is False
    assert group_status["selected_mode"] == "native"
    assert group_status["effective_backend"] == "python"
    assert group_status["status"] == "forced_native_failure"
    assert group_status["forced_native_failure"] is True
