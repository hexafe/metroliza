import scripts.validate_qt_runtime as validator


def test_qt_runtime_validator_reports_import_failure_hints(monkeypatch):
    def fail_import():
        raise ImportError("DLL load failed while importing QtCore")

    monkeypatch.setattr(validator, "_import_pyqt_modules", fail_import)
    monkeypatch.setattr(
        validator,
        "_distribution_version",
        lambda name: {
            "PyQt6": "6.6.1",
            "PyQt6-Qt6": "6.6.1",
            "PyQt6-sip": "13.6.0",
        }.get(name),
    )

    payload = validator.build_payload()

    assert payload["ok"] is False
    assert payload["pyqt"]["import_ok"] is False
    assert payload["pyqt"]["error"]["type"] == "ImportError"
    assert "QtCore" in payload["pyqt"]["error"]["message"]
    assert any("Install the Microsoft Visual C++ Redistributable" in hint for hint in payload["pyqt"]["hints"])


def test_qt_runtime_validator_rejects_mismatched_pyqt_payload(monkeypatch):
    class QtCoreStub:
        QT_VERSION_STR = "6.11.0"
        PYQT_VERSION_STR = "6.6.1"

        @staticmethod
        def qVersion():
            return "6.11.0"

    monkeypatch.setattr(validator, "_import_pyqt_modules", lambda: (QtCoreStub, object()))
    monkeypatch.setattr(
        validator,
        "_distribution_version",
        lambda name: {
            "PyQt6": "6.6.1",
            "PyQt6-Qt6": "6.11.0",
            "PyQt6-sip": "13.6.0",
        }.get(name),
    )

    payload = validator.build_payload()

    assert payload["ok"] is False
    assert payload["pyqt"]["import_ok"] is True
    assert payload["pyqt"]["version_alignment_ok"] is False
    assert payload["pyqt"]["warnings"]
