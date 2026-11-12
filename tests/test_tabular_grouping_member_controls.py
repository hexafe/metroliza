"""Business outcomes for visible CSV grouping controls and member identity."""
from __future__ import annotations

import pandas as pd
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QMessageBox

from metroliza.ui.tabular_analytics_grouping_dialog import TabularAnalyticsGroupingDialog


def _choose_group(dialog, name):
    for index in range(dialog.groups_list.count()):
        item = dialog.groups_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == name:
            dialog.groups_list.setCurrentItem(item)
            return
    raise AssertionError(name)


@pytest.fixture
def dialog(qapplication_session, monkeypatch):
    frame = pd.DataFrame({"source_row_number": [11, 27, 42], "part": ["A", "A", "B"]})
    window = TabularAnalyticsGroupingDialog(dataframe=frame)
    window._assign_rows_to_group([11, 27], "Chosen")
    window._refresh_all(preferred_group="Chosen")
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    yield window
    window.close()


def test_remove_member_button_only_returns_selected_record_to_default(dialog):
    assert "Ctrl+D" in dialog.remove_from_group_button.text()
    assert not dialog.remove_from_group_button.isEnabled()
    member = dialog.group_members_list.item(1)
    assert member.data(Qt.ItemDataRole.UserRole) == 27
    dialog.group_members_list.setCurrentItem(member)
    assert dialog.remove_from_group_button.isEnabled()
    dialog.remove_from_group_button.click()
    assert set(dialog._temp_assignments()) == {11}
    assert dialog._group_counts() == {"Chosen": 1, dialog.default_group: 2}
    assert dialog.source_dataframe["source_row_number"].tolist() == [11, 27, 42]
    _choose_group(dialog, dialog.default_group)
    dialog.group_members_list.setCurrentRow(0)
    assert not dialog.remove_from_group_button.isEnabled()


def test_remove_member_shortcut_and_reset_keep_draft_boundary(dialog, qapplication_session):
    dialog._capture_committed_grouping_state()
    dialog.show()
    dialog.activateWindow()
    dialog.group_members_list.setFocus()
    dialog.group_members_list.setCurrentRow(0)
    qapplication_session.processEvents()
    QTest.keyClick(dialog.group_members_list, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert set(dialog._temp_assignments()) == {27}
    assert dialog._is_grouping_dirty()
    dialog._request_reset_grouping()
    assert set(dialog._temp_assignments()) == {11, 27}
    assert not dialog._is_grouping_dirty()


def test_column_controls_respect_visible_search_and_preserve_groups(dialog):
    assert "Ctrl+E" in dialog.add_column_button.text()
    assert "Ctrl+Shift+E" in dialog.remove_column_button.text()
    dialog.add_column_button.click()
    assert dialog.selector_columns == ["part"]
    assert set(dialog._temp_assignments()) == {11, 27}
    dialog.selected_column_search.setText("absent")
    dialog._apply_selected_column_search()
    assert dialog.selected_columns_list.currentItem() is None
    assert not dialog.remove_column_button.isEnabled()
    dialog.remove_selected_selector_column()
    assert dialog.selector_columns == ["part"]
    dialog.selected_column_search.clear()
    dialog._apply_selected_column_search()
    dialog.remove_column_button.click()
    assert dialog.selector_columns == []
    assert set(dialog._temp_assignments()) == {11, 27}
    dialog.column_search.setText("absent")
    dialog._apply_column_search()
    assert not dialog.add_column_button.isEnabled()


def test_column_shortcuts_work_from_search_without_stealing_text_editing(dialog, qapplication_session):
    dialog.show()
    dialog.activateWindow()
    dialog.column_search.setFocus()
    qapplication_session.processEvents()
    QTest.keyClick(dialog.column_search, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert dialog.selector_columns == ["part"]
    QTest.keyClicks(dialog.column_search, "part")
    QTest.keyClick(dialog.column_search, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert dialog.column_search.selectedText() == "part"
    QTest.keyClick(dialog.column_search, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert dialog.selector_columns == []


@pytest.mark.parametrize("field", ["column_search", "selected_column_search", "selector_search", "page_jump_input"])
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["Return", "Enter"])
def test_grouping_inputs_keep_real_return_signal_local(dialog, qapplication_session, field, key):
    from tests.qt_key_input import activate_for_key

    dialog.show()
    editor = getattr(dialog, field)
    editor.setText("1" if field == "page_jump_input" else "part")
    returned = QSignalSpy(editor.returnPressed)
    accepted = QSignalSpy(dialog.accepted)
    saved = QSignalSpy(dialog.use_grouping_button.clicked)
    activate_for_key(qapplication_session, editor)
    QTest.keyClick(editor, key)
    qapplication_session.processEvents()
    assert len(returned) == 1
    assert dialog.isVisible()
    assert len(accepted) == len(saved) == 0


def test_invalid_page_return_keeps_validator_and_does_not_save(dialog, qapplication_session):
    from tests.qt_key_input import press_key

    dialog.show()
    editor = dialog.page_jump_input
    editor.setText("0")
    assert not editor.hasAcceptableInput()
    returned = QSignalSpy(editor.returnPressed)
    accepted = QSignalSpy(dialog.accepted)
    saved = QSignalSpy(dialog.use_grouping_button.clicked)
    press_key(qapplication_session, editor, "Return")
    assert len(returned) == len(accepted) == len(saved) == 0
    assert dialog.isVisible()


def _assert_full_member_labels_visible(window, artifact_dir, key):
    """Check actual row/text layout, and retain the real 980px rendering when requested."""
    import json
    from math import ceil
    from pathlib import Path
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtGui import QTextLayout, QTextOption

    listing = window.group_members_list
    scroll = window.grouping_body_scroll
    assert window.width() == 980
    observations = []
    for index, row_id in enumerate((1, 13, 25)):
        item = listing.item(index)
        assert item.data(Qt.ItemDataRole.UserRole) == row_id
        label = item.text()
        assert label.endswith(f"[Row {row_id}]")
        if row_id == 25:
            assert "Operator lot code: Missing identifier" in label
        else:
            assert "Operator lot code: DUP-1212" in label
        expected_date = "Missing date" if row_id == 13 else f"2026-01-{1 if row_id == 1 else 3:02d}"
        assert f"Captured at: {expected_date}" in label
        rect = listing.visualItemRect(item)
        assert listing.viewport().rect().contains(rect)
        # The list itself can extend past the outer body viewport; the visible rows cannot.
        body_rect = rect.translated(listing.viewport().mapTo(scroll.viewport(), QPoint()))
        assert scroll.viewport().rect().contains(body_rect)
        layout = QTextLayout(label, listing.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        layout.setTextOption(option)
        layout.beginLayout()
        height = 0.0
        fragments = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(rect.width() - 4)  # Standard item text inset; no icon/check box.
            line.setPosition(QPointF(0, height))
            height += line.height()
            assert line.naturalTextWidth() <= rect.width() - 4
            fragments.append(label[line.textStart():line.textStart() + line.textLength()])
        layout.endLayout()
        assert "".join(fragments) == label
        assert len(fragments) > 1
        assert rect.height() >= ceil(height), (label, rect, height)
        observations.append({"id": row_id, "label": label, "lines": fragments,
                             "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
                             "required_text_height": height})
    assert listing.horizontalScrollBar().maximum() == 0
    if artifact_dir:
        target = Path(artifact_dir)
        target.mkdir(parents=True, exist_ok=True)
        stem = f"grouping-member-labels-980-{key}"
        assert window.grab().save(str(target / (stem + ".png")))
        (target / (stem + ".json")).write_text(json.dumps({
            "window": [window.width(), window.height()], "dpr": window.devicePixelRatioF(),
            "viewport": [listing.viewport().width(), listing.viewport().height()],
            "font": listing.font().toString(), "rows": observations,
        }, indent=2))


@pytest.mark.parametrize("key", ["Return", "Enter"])
def test_sqlite_search_return_stays_open_without_committing_parent(
    qapplication_session, tmp_path, key,
):
    import os
    from pathlib import Path
    import time
    import traceback
    from PyQt6.QtCore import QTimer
    from metroliza.tabular.tabular_analytics_service import load_tabular_analytics_file
    from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog, SOURCE_TABULAR_FILE
    from tests.qt_key_input import activate_for_key, press_key

    source = tmp_path / "sqlite-search.csv"
    identities = [f"P-{i:06d}" for i in range(3000)]
    identities[0] = identities[12] = "DUP-1212"
    identities[24] = ""
    dates = ["2026-01-01"] * 3000
    dates[12], dates[24] = "", "2026-01-03"
    pd.DataFrame({"Operator lot code": identities, "Captured at": dates, "Value": range(3000)}).to_csv(source, index=False)
    loaded = load_tabular_analytics_file(source, force_sqlite=True,
                                        reference_column="operator_lot_code", timestamp_column="captured_at")
    assert loaded.sqlite_store is not None
    store_path = Path(loaded.sqlite_store.path)
    parent = IndustrialAnalyticsDialog(source_kind=SOURCE_TABULAR_FILE, tabular_load_result=loaded, input_file=source)
    groups = pd.DataFrame({"REPORT_ID": range(1, 3001),
                           "GROUP": [f"G-{i % 12:03d}" for i in range(3000)], "GROUP_COLOR": ["#4488cc"] * 3000})
    parent.set_df_for_grouping(groups)
    parent.set_grouping_applied(True)
    saved = parent.df_for_grouping
    baseline = saved.copy(deep=True)
    failures, children = [], []

    def drive():
        child = None
        try:
            child = qapplication_session.activeModalWidget()
            assert isinstance(child, TabularAnalyticsGroupingDialog)
            children.append(child)
            accepted = QSignalSpy(child.accepted)
            committed = QSignalSpy(child.use_grouping_button.clicked)
            _choose_group(child, "G-000")
            child.resize(980, 700)
            qapplication_session.processEvents()
            child.column_search.setText("Operator lot code")
            press_key(qapplication_session, child.column_search, key)
            item = next(child.available_columns_list.item(i) for i in range(child.available_columns_list.count())
                        if child.available_columns_list.item(i).data(Qt.ItemDataRole.UserRole) == "operator_lot_code")
            child.available_columns_list.setCurrentItem(item)
            child.add_column_button.click()
            assert child.selector_columns == ["operator_lot_code"]
            child.selector_search.setText("DUP-1212")
            returned = QSignalSpy(child.selector_search.returnPressed)
            # The real scope query disables/re-enables this owner. No focus repair after Return.
            press_key(qapplication_session, child.selector_search, key)
            assert len(returned) == 1
            assert child.isVisible()
            assert len(accepted) == len(committed) == 0
            assert child._applied_selector_filter_text == "DUP-1212"
            assert child._applied_scope_count == 2
            assert child.selector_list.count() == 1
            assert child.selector_list.item(0).data(Qt.ItemDataRole.UserRole) == ("DUP-1212",)
            assert parent.df_for_grouping is saved
            pd.testing.assert_frame_equal(parent.df_for_grouping, baseline)
            _assert_full_member_labels_visible(child, os.environ.get("METROLIZA_GROUPING_MEMBER_ARTIFACT_DIR"), key)
        except BaseException:
            # Assertions/diagnostics must never escape a Qt timer callback.
            failures.append(traceback.format_exc())
        finally:
            try:
                if isinstance(child, TabularAnalyticsGroupingDialog) and child.isVisible():
                    child.cancel_button.click()  # No grouping mutation: real Cancel has no discard prompt.
            except BaseException:
                failures.append(traceback.format_exc())

    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.timeout.connect(drive)
    try:
        parent.show()
        activate_for_key(qapplication_session, parent.edit_groups_button)
        timer.start(0)
        parent.edit_groups_button.click()  # Real launcher/constructor/exec; no timer-stealing key pump.
        assert len(children) == 1
        assert not failures, "\n".join(failures)
        assert parent.df_for_grouping is saved
        pd.testing.assert_frame_equal(parent.df_for_grouping, baseline)
        assert loaded.sqlite_store.count_rows() == 3000
        assert parent.analytics_thread is None and parent.tabular_load_thread is None
    finally:
        timer.stop()
        timer.deleteLater()
        deadline = time.monotonic() + 20
        while any(t.isRunning() for child in children for t in child._selector_preview_threads) and time.monotonic() < deadline:
            qapplication_session.processEvents()
            QTest.qWait(5)
        parent.close()
        qapplication_session.processEvents()
    assert not store_path.exists()


@pytest.mark.parametrize("timestamp", ["when_measured", None])
def test_member_identity_uses_actual_fields_and_keeps_duplicate_ids_distinct(qapplication_session, timestamp):
    frame = pd.DataFrame({
        "source_row_number": [11, 27, 42], "custom_part": ["Same", "Same", pd.NA],
        "when_measured": ["2026-01-01", None, "2026-01-03"], "selector": ["X"] * 3,
    }, index=[7, 9, 14])
    window = TabularAnalyticsGroupingDialog(
        dataframe=frame, identity_column="custom_part", datetime_column=timestamp,
        column_mapping={"Part code": "custom_part", "Measured": "when_measured"},
    )
    try:
        window._assign_rows_to_group([11, 27, 42], "Chosen")
        window.selector_columns = ["selector"]
        window._refresh_all(preferred_group="Chosen")
        labels = [window.group_members_list.item(i).text() for i in range(3)]
        assert labels[0].startswith("Part code: Same")
        assert labels[0].endswith("[Row 11]")
        assert labels[1].endswith("[Row 27]")
        assert "Missing identifier" in labels[2]
        if timestamp:
            assert "Measured: 2026-01-01" in labels[0]
            assert "Missing date" in labels[1]
        else:
            assert "Measured:" not in labels[0]
        window.group_members_list.setCurrentRow(1)
        window.remove_from_group_button.click()
        assert set(window._temp_assignments()) == {11, 42}
        assert len(window.source_dataframe) == 3
    finally:
        window._reset_grouping_draft(refresh=False)
        window.close()


def test_sqlite_member_identity_read_is_bounded_and_survives_search_and_reopen(
    qapplication_session, tmp_path, monkeypatch,
):
    from metroliza.tabular.tabular_analytics_service import (
        cleanup_tabular_load_result, load_tabular_analytics_file,
    )
    from metroliza.ui import tabular_analytics_grouping_dialog as module

    source = tmp_path / "synthetic.csv"
    pd.DataFrame({
        "PART": ["Same" if i % 24 == 0 else None for i in range(3000)],
        "DATE": ["2026-01-01" if i % 24 == 0 else None for i in range(3000)],
        "LINE": [str(i % 12) for i in range(3000)], "VALUE": range(3000),
        "source_row_number": ["duplicate source label"] * 3000,
    }).to_csv(source, index=False)
    loaded = load_tabular_analytics_file(source, force_sqlite=True)
    store = loaded.sqlite_store
    assert store is not None
    assert loaded.column_mapping["source_row_number"] != "source_row_number"
    monkeypatch.setattr(module, "_GROUP_MEMBER_PREVIEW_LIMIT", 3)
    reads = []
    real_read = type(store).read_row_table

    def read_spy(self, **kwargs):
        reads.append(kwargs)
        assert kwargs["limit"] == 3
        assert len(kwargs["selected_filter_keys"]) <= 3
        return real_read(self, **kwargs)

    monkeypatch.setattr(type(store), "read_row_table", read_spy)
    window = TabularAnalyticsGroupingDialog(
        dataframe=loaded.dataframe, sqlite_store=store, column_mapping=loaded.column_mapping,
        identity_column=loaded.column_mapping["PART"], datetime_column=loaded.column_mapping["DATE"],
    )
    try:
        for group in range(12):
            window._assign_rows_to_group(list(range(group + 1, 3001, 12)), f"Line {group}")
        window._capture_committed_grouping_state()
        window._refresh_all(preferred_group="Line 0")
        assert window.group_members_list.count() == 4
        ids = [window.group_members_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)]
        assert ids == [1, 13, 25]
        assert "PART: Same" in window.group_members_list.item(0).text()
        assert "DATE: 2026-01-01" in window.group_members_list.item(0).text()
        assert "Missing identifier" in window.group_members_list.item(1).text()
        assert "Missing date" in window.group_members_list.item(1).text()
        assert reads[-1]["columns"] == ("source_row_number", "part", "date")
        assert not window.group_members_list.item(3).flags() & Qt.ItemFlag.ItemIsSelectable
        window.selector_search.setText("absent")
        window._apply_selector_filter()
        _choose_group(window, "Line 1")
        _choose_group(window, "Line 0")
        assert window.group_members_list.item(1).data(Qt.ItemDataRole.UserRole) == 13
        window.group_members_list.setCurrentRow(1)
        window.remove_from_group_button.click()
        assert window._group_counts()["Line 0"] == 249
        assert [window.group_members_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)] == [1, 25, 37]
        window._reset_grouping_draft()
        assert window._group_counts()["Line 0"] == 250
        saved = window._materialize_grouping_dataframe()
        window.close()
        reopened = TabularAnalyticsGroupingDialog(
            dataframe=loaded.dataframe, sqlite_store=store, grouping_dataframe=saved,
            identity_column="part", datetime_column="date",
        )
        try:
            _choose_group(reopened, "Line 0")
            assert reopened.group_members_list.item(1).data(Qt.ItemDataRole.UserRole) == 13
            assert "Missing identifier" in reopened.group_members_list.item(1).text()
        finally:
            reopened.close()
    finally:
        window.close()
        cleanup_tabular_load_result(loaded)


@pytest.mark.parametrize("sqlite", [False, True])
def test_grouping_caller_forwards_actual_user_identity_and_date(
    qapplication_session, tmp_path, monkeypatch, sqlite,
):
    from types import SimpleNamespace
    from metroliza.tabular.tabular_analytics_service import (
        cleanup_tabular_load_result, load_tabular_analytics_file,
    )
    from metroliza.ui.industrial_analytics_dialog import IndustrialAnalyticsDialog

    source = tmp_path / "synthetic.csv"
    pd.DataFrame({"Key A": ["A"], "Time A": ["2026-01-01"], "Value": [1]}).to_csv(source, index=False)
    loaded = load_tabular_analytics_file(source, force_sqlite=sqlite)
    parent = IndustrialAnalyticsDialog(source_kind="tabular_file", tabular_load_result=loaded)
    calls = []
    try:
        parent._populate_tabular_column_options(
            loaded.column_mapping, reference_column="key_a", timestamp_column="time_a",
        )
        monkeypatch.setattr(parent, "_create_tabular_grouping_dialog", lambda *_a, **kwargs: (
            calls.append(kwargs) or SimpleNamespace(exec=lambda: None)
        ))
        parent.open_grouping_dialog()
        assert calls[0]["identity_column"] == "key_a"
        assert calls[0]["datetime_column"] == "time_a"
    finally:
        parent.close()
        cleanup_tabular_load_result(loaded)


@pytest.mark.parametrize("identity,timestamp", [(None, None), ("unknown_id", "unknown_date")])
def test_empty_or_unknown_identity_fields_never_use_another_column(qapplication_session, identity, timestamp):
    window = TabularAnalyticsGroupingDialog(
        dataframe=pd.DataFrame({"reference": ["WRONG ID"], "process_datetime": ["WRONG DATE"]}),
        identity_column=identity, datetime_column=timestamp,
    )
    try:
        window._assign_rows_to_group([1], "Chosen")
        window._refresh_all(preferred_group="Chosen")
        label = window.group_members_list.item(0).text()
        assert "Missing identifier" in label and "[Row 1]" in label
        assert "WRONG" not in label
        assert ("Missing date" in label) is bool(timestamp)
    finally:
        window._reset_grouping_draft(refresh=False)
        window.close()


def test_bare_commands_only_run_in_their_directly_focused_lists(dialog, qapplication_session):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    dialog.show()
    dialog.activateWindow()
    dialog.column_search.setFocus()
    qapplication_session.processEvents()
    QTest.keyClicks(dialog.column_search, "er")
    assert dialog.column_search.text() == "er"
    assert dialog.selector_columns == []
    assert set(dialog._temp_assignments()) == {11, 27}
    dialog.available_columns_list.setFocus()
    QTest.keyClick(dialog.available_columns_list, Qt.Key.Key_E, Qt.KeyboardModifier.ShiftModifier)
    assert dialog.selector_columns == []
    QTest.keyClick(dialog.available_columns_list, Qt.Key.Key_E)
    assert dialog.selector_columns == ["part"]
    dialog.selected_columns_list.setFocus()
    repeat = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.NoModifier, "r", True)
    QApplication.sendEvent(dialog.selected_columns_list, repeat)
    assert dialog.selector_columns == ["part"]
    QTest.keyClick(dialog.selected_columns_list, Qt.Key.Key_R)
    assert dialog.selector_columns == []
    # R cannot remove a member without selection, nor can AltGr-like modifiers.
    _choose_group(dialog, "Chosen")
    dialog.group_members_list.setFocus()
    dialog.group_members_list.clearSelection()
    QTest.keyClick(dialog.group_members_list, Qt.Key.Key_R)
    assert set(dialog._temp_assignments()) == {11, 27}
    dialog.group_members_list.setCurrentRow(0)
    QTest.keyClick(dialog.group_members_list, Qt.Key.Key_R,
                   Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert set(dialog._temp_assignments()) == {11, 27}
    QTest.keyClick(dialog.group_members_list, Qt.Key.Key_R)
    assert set(dialog._temp_assignments()) == {27}
    # The same key in an empty selected-columns list remains harmless.
    dialog.selected_columns_list.setFocus()
    QTest.keyClick(dialog.selected_columns_list, Qt.Key.Key_R)
    assert dialog.selector_columns == []


@pytest.mark.parametrize("size", [(997, 680), (760, 560)])
def test_grouping_small_screen_keeps_lists_separate_and_footer_reachable(
    qapplication_session, monkeypatch, size,
):
    import json
    import os
    from pathlib import Path
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QFont

    screen = qapplication_session.primaryScreen().availableGeometry()
    artifact_dir = os.environ.get("METROLIZA_GROUPING_GEOMETRY_DIR")
    if artifact_dir:
        # The explicit DPI evidence run must prove the real configured screen before rendering.
        assert (screen.width(), screen.height()) == (1280, 720)
        assert qapplication_session.primaryScreen().devicePixelRatio() == 1.5
    else:
        # Ordinary CI verifies the same local layout on a deterministic virtual available area.
        from metroliza.ui import ui_foundation
        monkeypatch.setattr(ui_foundation, "_available_window_size", lambda *_a: (1240, 680))
    previous_font = qapplication_session.font()
    qapplication_session.setFont(QFont("Liberation Sans", 9))
    window = TabularAnalyticsGroupingDialog(
        dataframe=pd.DataFrame({"part": [f"P-{i}" for i in range(3000)], "line": [i % 12 for i in range(3000)]}),
        identity_column="part",
    )
    try:
        for group in range(12):
            window._assign_rows_to_group(list(range(group + 1, 3001, 12)), f"G-{group:03d}")
        window._refresh_all(preferred_group="G-000")
        window.show()
        qapplication_session.processEvents()
        window.resize(*size)
        qapplication_session.processEvents()
        assert (window.width(), window.height()) == size, (screen, window.devicePixelRatioF())
        for listing, button in (
            (window.available_columns_list, window.add_column_button),
            (window.selected_columns_list, window.remove_column_button),
        ):
            assert listing.parentWidget() is button.parentWidget()
            assert listing.geometry().bottom() < button.geometry().top()
            assert listing.geometry().height() >= listing.minimumHeight()
        member_list = window.group_members_list
        member_button = window.remove_from_group_button
        member_legend = window.group_member_command_legend
        assert member_list.parentWidget() is member_button.parentWidget()
        assert member_button.geometry().bottom() < member_legend.geometry().top()
        assert member_legend.geometry().bottom() < member_list.geometry().top()
        assert member_list.height() >= member_list.minimumHeight()
        scroll = window.grouping_body_scroll
        initial_member_rect = member_button.rect().translated(member_button.mapTo(scroll.viewport(), QPoint()))
        initial_legend_rect = member_legend.rect().translated(member_legend.mapTo(scroll.viewport(), QPoint()))
        if artifact_dir:
            target = Path(artifact_dir)
            target.mkdir(parents=True, exist_ok=True)
            assert window.grab().save(str(target / f"grouping-{size[0]}x{size[1]}-initial.png"))
        if size[0] >= 997:
            # At default-width / 680px-high (stricter than 700px), discover the action before scrolling.
            assert scroll.verticalScrollBar().value() == 0
            assert scroll.viewport().rect().contains(initial_member_rect)
            assert scroll.viewport().rect().contains(initial_legend_rect)
        footer = (
            window.assign_filtered_rows_button, window.create_group_button, window.rename_group_button,
            window.delete_group_button, window.clear_selection_button, window.dont_use_grouping_button,
            window.cancel_button, window.use_grouping_button,
        )
        footer_rects = [button.rect().translated(button.mapTo(window, QPoint())) for button in footer]
        assert all(window.rect().contains(rect) for rect in footer_rects)
        assert all(not first.intersects(second)
                   for index, first in enumerate(footer_rects) for second in footer_rects[index + 1:])
        assert all(not window.grouping_body_scroll.isAncestorOf(button) for button in footer)
        # Body commands remain reachable without pushing the pinned footer off screen.
        window.grouping_body_scroll.ensureWidgetVisible(window.remove_from_group_button)
        qapplication_session.processEvents()
        scroll = window.grouping_body_scroll
        member_rect = window.remove_from_group_button.rect().translated(
            window.remove_from_group_button.mapTo(scroll.viewport(), QPoint()))
        assert scroll.viewport().rect().contains(member_rect)
        if artifact_dir:
            target = Path(artifact_dir)
            target.mkdir(parents=True, exist_ok=True)
            stem = f"grouping-{size[0]}x{size[1]}"
            assert window.grab().save(str(target / f"{stem}.png"))
            (target / f"{stem}.json").write_text(json.dumps({
                "window": list(size), "dpr": window.devicePixelRatioF(),
                "available_screen": [qapplication_session.primaryScreen().availableGeometry().width(),
                                     qapplication_session.primaryScreen().availableGeometry().height()],
                "body_scroll_maximum": scroll.verticalScrollBar().maximum(),
                "footer_rects": [[r.x(), r.y(), r.width(), r.height()] for r in footer_rects],
                "member_button_in_viewport": [member_rect.x(), member_rect.y(), member_rect.width(), member_rect.height()],
                "initial_member_button_in_viewport": [initial_member_rect.x(), initial_member_rect.y(), initial_member_rect.width(), initial_member_rect.height()],
                "initial_member_legend_in_viewport": [initial_legend_rect.x(), initial_legend_rect.y(), initial_legend_rect.width(), initial_legend_rect.height()],
            }, indent=2))
    finally:
        window._reset_grouping_draft(refresh=False)
        window.close()
        qapplication_session.setFont(previous_font)
