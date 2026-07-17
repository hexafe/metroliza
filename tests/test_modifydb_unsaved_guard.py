from __future__ import annotations

import pytest


_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def test_modify_database_close_requires_explicit_discard_for_unapplied_edits(monkeypatch):
    pytest.importorskip("PyQt6")
    from PyQt6.QtGui import QCloseEvent
    from PyQt6.QtWidgets import QMessageBox

    from metroliza.ui.modify_db import ModifyDB

    _app()
    dialog = ModifyDB(parent=None, db_file="")
    dialog.populate_table(dialog.reference_table, [("REF-A", 3)])
    dialog.reference_table.item(0, 1).setText("REF-B")
    try:
        assert dialog.has_pending_changes()

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )
        cancelled_close = QCloseEvent()
        cancelled_close.accept()
        dialog.closeEvent(cancelled_close)
        assert not cancelled_close.isAccepted()

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
        )
        discarded_close = QCloseEvent()
        discarded_close.accept()
        dialog.closeEvent(discarded_close)
        assert discarded_close.isAccepted()
    finally:
        dialog._changes_committed = True
        dialog.close()
