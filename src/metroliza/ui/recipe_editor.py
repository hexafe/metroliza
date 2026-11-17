"""Typed recipe cards and local parameter controls; no executing editor expressions."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from metroliza.recipes.contracts import ParameterKey, ParameterMode, ParameterType, StepKind
from metroliza.recipes.editor_service import RecipeEditorService
from metroliza.recipes.report_configuration_adapter import GROUPING_COLUMNS


class RecipeEditor(QDialog):
    saved = pyqtSignal(object)

    def __init__(self, stored, store, parent=None):
        super().__init__(parent)
        self._widgets_dirty = False
        self.store = store
        self.service = RecipeEditorService(stored)
        if stored.definition.builtin:
            self.service.duplicate()
        self.setWindowTitle("Recipe editor")
        self.resize(720, 650)
        layout = QVBoxLayout(self)
        self.name = QLineEdit(self.service.current.binding.name)
        layout.addWidget(QLabel("Private recipe name"))
        layout.addWidget(self.name)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.cards = QListWidget()
        self.cards.setAccessibleName("Typed recipe steps")
        layout.addWidget(self.cards)
        self.dates = QCheckBox("Filter by dates (ask at start)")
        self.dates.setChecked(any(p.key is ParameterKey.DATE_FROM
                                 for p in self.service.current.definition.parameters))
        self.html = QCheckBox("Also produce HTML dashboard")
        self.html.setChecked(any(s.kind is StepKind.EXPORT_HTML for s in stored.definition.steps))
        self.groups = QLineEdit(", ".join(self.service.current.binding.value(ParameterKey.GROUPING_RULES, ())))
        self.groups.setPlaceholderText(", ".join(sorted(GROUPING_COLUMNS)))
        self.report_controls = QWidget()
        report_layout = QFormLayout(self.report_controls)
        report_layout.addRow(self.dates)
        report_layout.addRow("Group by columns", self.groups)
        report_layout.addRow(self.html)
        configure = QPushButton("Apply Reports steps")
        configure.clicked.connect(self._configure)
        report_layout.addRow(configure)
        layout.addWidget(self.report_controls)
        self.report_controls.setVisible(any(s.kind in {StepKind.IMPORT_REPORTS, StepKind.OPEN_DATABASE}
                                           for s in stored.definition.steps))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        self.pin_on_save = QCheckBox("Przypnij do Home po zapisaniu")
        layout.addWidget(self.pin_on_save)
        actions = QHBoxLayout()
        preview = QPushButton("Preview plan")
        preview.clicked.connect(self._preview)
        save = QPushButton("Save revision")
        save.clicked.connect(self._save)
        save_new = QPushButton("Save as new")
        save_new.clicked.connect(lambda: self._save(as_new=True))
        for button in (preview, save, save_new):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.name.textEdited.connect(self._mark_modified)
        self.dates.toggled.connect(self._mark_modified)
        self.html.toggled.connect(self._mark_modified)
        self.groups.textEdited.connect(self._mark_modified)
        self._refresh()

    def _mark_modified(self, *_args):
        self._widgets_dirty = True
        self.status.setText("Modified — unsaved local changes")

    def _refresh(self):
        self.cards.clear()
        for step in self.service.current.definition.steps:
            self.cards.addItem(f"{step.kind.value}: {step.input_kind.value} → {step.output_kind.value}")
        widget = QWidget()
        form = QFormLayout(widget)
        self.controls = {}
        for spec in self.service.current.definition.parameters:
            row = QWidget()
            line = QHBoxLayout(row)
            mode = QComboBox()
            modes = [ParameterMode.FIXED, ParameterMode.PROMPT]
            if spec.key is ParameterKey.DATABASE_FILE:
                modes.append(ParameterMode.DERIVED)
            for value in modes:
                mode.addItem(value.value, value)
            mode.setCurrentIndex(modes.index(spec.mode))
            value = self.service.current.binding.value(spec.key, "")
            edit = QLineEdit(", ".join(value) if type(value) is tuple else str(value))
            if spec.key in {ParameterKey.EXPORT_OPTIONS, ParameterKey.FILTER_VALUES,
                            ParameterKey.ANALYTICS_REQUEST}:
                # Captured typed configuration remains exact; no raw JSON editor.
                edit.setReadOnly(True)
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setEnabled(spec.mode is not ParameterMode.DERIVED)
            mode.currentIndexChanged.connect(lambda _index, m=mode, e=edit:
                e.setEnabled(m.currentData() is not ParameterMode.DERIVED))
            mode.currentIndexChanged.connect(self._mark_modified)
            edit.textEdited.connect(self._mark_modified)
            line.addWidget(mode)
            line.addWidget(edit)
            form.addRow(spec.key.value, row)
            self.controls[spec.key] = (spec, mode, edit)
        self.scroll.setWidget(widget)
        self.status.setText("Modified" if self.service.modified else "Saved")

    def _collect(self):
        # Transactional editor changes: a bad control must not retain half an edit.
        previous = self.service.current
        try:
            self.service.rename(self.name.text())
            for key, (spec, mode, edit) in self.controls.items():
                self.service.set_mode(key, mode.currentData())
                if edit.isReadOnly() or mode.currentData() is ParameterMode.DERIVED:
                    continue
                text = edit.text()
                if spec.type is ParameterType.STRINGS:
                    value = tuple(v.strip() for v in text.split(",") if v.strip())
                elif spec.type is ParameterType.BOOLEAN:
                    if text.lower() not in {"true", "false"}:
                        raise ValueError("boolean_required")
                    value = text.lower() == "true"
                elif spec.type is ParameterType.INTEGER:
                    value = int(text)
                elif spec.type is ParameterType.NUMBER:
                    value = float(text)
                else:
                    value = text
                self.service.set_value(key, value)
        except Exception:
            self.service.current = previous
            raise

    def _configure(self):
        try:
            self._collect()
            groups = tuple(v.strip().upper() for v in self.groups.text().split(",") if v.strip())
            self.service.configure_reports(dates=self.dates.isChecked(), grouping_columns=groups,
                                           additional_html=self.html.isChecked())
            self._refresh()
        except ValueError as error:
            self._error(error)

    def _preview(self):
        try:
            self._collect()
            plan = self.service.preview()
            outputs = [str(plan.database_file), str(plan.output_file)]
            if any(s.kind is StepKind.EXPORT_HTML for s in plan.definition.steps) and plan.output_file:
                outputs.append(str(plan.output_file.with_suffix(".html")))
            self.preview_label.setText("\n".join(outputs))
        except ValueError as error:
            self._error(error)

    def _save(self, _checked=False, *, as_new=False):
        try:
            self._collect()
            saved = self.service.save(self.store, as_new=as_new)
            self.saved.emit(saved)
            self._widgets_dirty = False
            self._refresh()
        except (ValueError, OSError) as error:
            self._error(error)

    def _error(self, error):
        code = getattr(error, "code", "invalid_configuration")
        QMessageBox.warning(self, "Recipe", f"Cannot apply configuration: {code}")

    def _can_discard(self):
        if not self._widgets_dirty and not self.service.modified:
            return True
        answer = QMessageBox.question(self, "Unsaved recipe",
            "Discard unsaved recipe changes?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Discard:
            self._widgets_dirty = False
            self.service.current = self.service.original
            return True
        return False

    def closeEvent(self, event):
        if self._can_discard():
            QDialog.reject(self)
            event.accept()
        else:
            event.ignore()

    def reject(self):
        if self._can_discard():
            super().reject()
