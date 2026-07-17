from __future__ import annotations

import pandas as pd
import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

    import metroliza.ui.data_grouping as data_grouping_module
    from metroliza.ui.data_grouping import DataGrouping
except ImportError as exc:  # pragma: no cover - depends on optional Qt availability.
    QApplication = None
    DataGrouping = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 grouping widgets are unavailable: {PYQT_IMPORT_ERROR}",
)

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def _source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "REPORT_ID": 1,
                "REFERENCE": "R-01",
                "DATE": "2026-01-01",
                "SAMPLE_NUMBER": "S-01",
                "PART_NAME": "Part A",
                "REVISION": "A",
                "TEMPLATE_VARIANT": "Default",
                "STATUS_CODE": "OK",
                "HAS_NOK": 0,
                "NOK_COUNT": 0,
                "OPERATOR_NAME": "Operator",
                "FILENAME": "report.pdf",
            }
        ]
    )


def test_data_grouping_dirty_x_and_escape_restore_without_parent_mutation(monkeypatch) -> None:
    app = _app()

    class Parent(QDialog):
        def __init__(self):
            super().__init__()
            self.df_for_grouping = None
            self.calls = []

        def set_df_for_grouping(self, dataframe):
            self.calls.append(("dataframe", dataframe))

        def set_grouping_applied(self, applied):
            self.calls.append(("applied", applied))

    parent = Parent()
    monkeypatch.setattr(
        DataGrouping,
        "read_data_to_df",
        lambda self: setattr(self, "df", _source_frame()),
    )
    monkeypatch.setattr(DataGrouping, "_restore_saved_grouping_state", lambda self: None)
    answers = iter(
        [
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ]
    )
    monkeypatch.setattr(
        data_grouping_module.QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(answers),
    )

    dialog = DataGrouping(parent=parent, db_file="")
    try:
        dialog.show()
        app.processEvents()
        dialog.df.loc[:, "GROUP"] = "Fixture A"

        assert dialog.close() is False
        assert dialog.isVisible()
        assert set(dialog.df["GROUP"]) == {"Fixture A"}
        assert dialog.close() is True
        assert not dialog.isVisible()
        assert set(dialog.df["GROUP"]) == {dialog.default_group}
        assert parent.calls == []

        dialog.show()
        app.processEvents()
        dialog.df.loc[:, "GROUP"] = "Fixture B"
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert dialog.isVisible()
        assert set(dialog.df["GROUP"]) == {"Fixture B"}
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        app.processEvents()
        assert not dialog.isVisible()
        assert set(dialog.df["GROUP"]) == {dialog.default_group}
        assert parent.calls == []
    finally:
        dialog.close()
        parent.close()
