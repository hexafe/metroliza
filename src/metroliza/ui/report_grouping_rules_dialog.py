"""Edit and preview reusable grouping rules in the Reports workflow."""

from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import QIODeviceBase, QSaveFile, Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHeaderView, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from metroliza.reports.report_grouping_rules import (
    MAX_GROUPS, MAX_LABEL_CHARS, MAX_PRESET_BYTES, ReportGroupRule, ReportGroupingPreset,
    ReportGroupingSource, dump_grouping_preset, load_grouping_preset, preview_grouping_preset,
)
from metroliza.ui.ui_foundation import apply_metroliza_theme, configure_window_size

_JSON_FILTER = "Grouping presets (*.json)"


class ReportGroupingRulesDialog(QDialog):
    def __init__(self, parent, database, filter_query, palette, *, draft=None):
        super().__init__(parent)
        self.setWindowTitle("Report grouping rules")
        self._database = database
        self._filter_query = filter_query
        self._palette = tuple(palette)
        self._preview = None
        self._preview_preset = None
        self.accepted_preview = None
        self.kept_preset = None

        self.name_input = QLineEdit()
        self.name_input.setMaxLength(MAX_LABEL_CHARS * 2)
        name_label = QLabel("&Preset name")
        name_label.setBuddy(self.name_input)

        self.rules_table = QTableWidget(0, 3)
        self.rules_table.setAccessibleName("Ordered grouping rules")
        self.rules_table.setHorizontalHeaderLabels(("Group name", "Color", "Typed rule"))
        self.rules_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.rules_table.setColumnWidth(0, 155)
        self.rules_table.setColumnWidth(1, 90)

        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setAccessibleName("Grouping rule status")
        self.preview_output = QPlainTextEdit()
        self.preview_output.setReadOnly(True)
        self.preview_output.setAccessibleName("Grouping rule preview")
        self.preview_output.setMaximumHeight(150)
        self.default_checkbox = QCheckBox("Assign remaining reports to POPULATION")
        self.apply_button = self._button("Use rule grouping", self._apply)
        self.apply_button.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addLayout(self._row(name_label, self.name_input))
        layout.addWidget(self.rules_table)
        layout.addLayout(self._row(
            self._button("Add group", self._add_group), self._button("Remove", self._remove_group),
            self._button("Up", lambda: self._move_group(-1)),
            self._button("Down", lambda: self._move_group(1)),
            self._button("Open preset…", self._open_preset),
            self._button("Save preset…", self._save_preset),
        ))
        hint = QLabel(
            'Use Reference, Part, Revision, Template, Sample or Date. '
            'Try Reference="001" AND Date>=2026-01-01. Using rules replaces the current grouping.'
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.preview_output)
        layout.addWidget(self.feedback)
        layout.addWidget(self.default_checkbox)
        layout.addLayout(self._row(
            self._button("Preview", self._preview_rules), self._button("Cancel", self.reject),
            self._button("Keep draft", self._keep_draft),
            self.apply_button,
        ))

        if draft is None:
            self._add_group()
        else:
            self._load_preset(draft)
        self.name_input.textChanged.connect(self._invalidate_preview)
        self.rules_table.itemChanged.connect(self._invalidate_preview)
        self.default_checkbox.toggled.connect(self._update_apply_button)
        self._invalidate_preview()
        apply_metroliza_theme(self)
        configure_window_size(self, minimum=(660, 480), initial=(820, 570), screen_margin=44)

    @staticmethod
    def _row(*widgets):
        layout = QHBoxLayout()
        for widget in widgets:
            layout.addWidget(widget)
        return layout

    @staticmethod
    def _button(label, callback):
        button = QPushButton(label)
        button.setAutoDefault(False)
        button.clicked.connect(callback)
        return button

    def _add_group(self):
        row = self.rules_table.rowCount()
        if row >= MAX_GROUPS:
            self.feedback.setText(f"A preset can have up to {MAX_GROUPS} groups.")
            return
        color = self._palette[row % len(self._palette)] if self._palette else "#DAE9F6"
        self._insert_rule(uuid4().hex, "", color, "")
        self.rules_table.setCurrentCell(row, 0)
        self._invalidate_preview()

    def _insert_rule(self, group_id, name, color, expression):
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        for column, value in enumerate((name, color, expression)):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, group_id)
            self.rules_table.setItem(row, column, item)

    def _remove_group(self):
        row = self.rules_table.currentRow()
        if row >= 0:
            self.rules_table.removeRow(row)
            self._invalidate_preview()

    def _move_group(self, offset):
        table = self.rules_table
        row = table.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < table.rowCount():
            first = [table.takeItem(row, column) for column in range(3)]
            second = [table.takeItem(target, column) for column in range(3)]
            for column, (left, right) in enumerate(zip(first, second)):
                table.setItem(target, column, left)
                table.setItem(row, column, right)
            table.setCurrentCell(target, 0)
            self._invalidate_preview()

    def _read_draft(self):
        table = self.rules_table
        rules = tuple(
            ReportGroupRule(
                table.item(row, 0).data(Qt.ItemDataRole.UserRole),
                *(table.item(row, column).text().strip() for column in range(3)),
            ) for row in range(table.rowCount())
        )
        return ReportGroupingPreset(self.name_input.text().strip(), rules)

    def _invalidate_preview(self):
        self._preview = None
        self._preview_preset = None
        self.preview_output.clear()
        self.feedback.setText("Preview before using these rules. Applying rules replaces the current grouping.")
        self._update_apply_button()

    def _update_apply_button(self):
        preview = self._preview
        self.apply_button.setEnabled(bool(
            preview and not preview.overlap_count
            and (not preview.unassigned_count or self.default_checkbox.isChecked())
        ))

    def _preview_rules(self):
        self._invalidate_preview()
        try:
            preset = self._read_draft()
            source = ReportGroupingSource.capture(self._database, self._filter_query)
            preview = preview_grouping_preset(preset, source)
        except (OSError, ValueError) as exc:
            self.feedback.setText(str(exc))
            return

        lines = [f"{label} · {count:,} reports" for label, count in preview.counts]
        for label, count, sample in (
            ("Overlaps", preview.overlap_count, preview.overlap_sample),
            ("Unassigned", preview.unassigned_count, preview.unassigned_sample),
        ):
            detail = "   (report IDs " + ", ".join(map(str, sample)) + ")" if sample else ""
            lines.append(f"{label} · {count:,}{detail}")
        self.preview_output.setPlainText("\n".join(lines))
        self._preview = preview
        self._preview_preset = preset
        if preview.overlap_count:
            self.feedback.setText("Edit the rules to resolve overlaps before using this grouping.")
        elif preview.unassigned_count:
            self.feedback.setText("Choose POPULATION if you want to keep unassigned reports.")
        else:
            self.feedback.setText("Review the preview before using this grouping.")
        self._update_apply_button()

    def _apply(self):
        if not self.apply_button.isEnabled() or self._preview is None:
            return
        try:
            self._preview.source.require_current(self._database, self._filter_query, exact_stamp=True)
        except (OSError, ValueError) as exc:
            self._invalidate_preview()
            self.feedback.setText(str(exc))
            return
        self.accepted_preview = self._preview
        self.kept_preset = self._preview_preset
        self.accept()

    def _keep_draft(self):
        try:
            self.kept_preset = self._read_draft()
        except ValueError as exc:
            self.feedback.setText(str(exc))
            return
        self.accept()

    def _open_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open grouping preset", "", _JSON_FILTER)
        if not path:
            return
        try:
            file_path = Path(path)
            if not file_path.is_file():
                raise ValueError("Choose a regular grouping preset file.")
            with file_path.open("rb") as stream:
                preset = load_grouping_preset(stream.read(MAX_PRESET_BYTES + 1))
        except (OSError, ValueError) as exc:
            self.feedback.setText(f"Could not open grouping preset. {exc}")
            return
        self._load_preset(preset)

    def _load_preset(self, preset):
        self.name_input.setText(preset.name)
        self.rules_table.setRowCount(0)
        for rule in preset.rules:
            self._insert_rule(rule.group_id, rule.label, rule.color, rule.expression)
        self.default_checkbox.setChecked(False)
        self._invalidate_preview()

    def _save_preset(self):
        try:
            raw = dump_grouping_preset(self._read_draft())
        except ValueError as exc:
            self.feedback.setText(str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save grouping preset", "Grouping.json", _JSON_FILTER)
        if not path:
            return
        if Path(path).suffix.lower() != ".json":
            self.feedback.setText("Use a .json file name for the grouping preset.")
            return
        save = QSaveFile(path)
        save.setDirectWriteFallback(False)
        if not save.open(QIODeviceBase.OpenModeFlag.WriteOnly):
            self.feedback.setText(f"Could not save grouping preset. {save.errorString()}")
            return
        if save.write(raw) != len(raw):
            save.cancelWriting()
            self.feedback.setText(f"Could not save grouping preset. {save.errorString()}")
            return
        if not save.commit():
            self.feedback.setText(f"Could not save grouping preset. {save.errorString()}")
            return
        self.feedback.setText("Grouping preset saved.")
