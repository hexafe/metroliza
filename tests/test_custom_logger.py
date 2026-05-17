import builtins
import logging

from modules import custom_logger


def test_notify_user_does_not_raise_when_qt_import_fails(monkeypatch, caplog):
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PyQt6.QtWidgets":
            raise ImportError("DLL load failed while importing QtCore")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with caplog.at_level(logging.ERROR):
        custom_logger.notify_user(message="message")

    assert "Could not show error dialog because Qt failed to import" in caplog.text
