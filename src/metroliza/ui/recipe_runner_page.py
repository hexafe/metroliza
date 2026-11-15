"""Persistent recipe form, review and result presentation for a shared controller."""
from __future__ import annotations

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from metroliza.recipes.contracts import ParameterKey, ParameterMode, ParameterType, StepKind
from metroliza.recipes.run_state import RunState
from metroliza.reports.report_metadata_review import REVIEW_FIELDS, FIELD_LABELS

_LABELS = {"input_folder": "Folder raportów", "output_file": "Plik wynikowy",
           "database_file": "Baza danych", "existing_database": "Istniejąca baza",
           "export_preset": "Profil eksportu", "source_file": "Plik źródłowy"}
_STATE_LABELS = {
    RunState.READY: "Gotowe", RunState.RUNNING: "Trwa wykonywanie",
    RunState.REQUIRES_DECISION: "Wymagana decyzja", RunState.COMPLETED: "Zakończono",
    RunState.COMPLETED_WITH_WARNINGS: "Zakończono z ostrzeżeniami",
    RunState.PARTIAL: "Wynik częściowy", RunState.FAILED: "Niepowodzenie",
    RunState.CANCELLING: "Anulowanie", RunState.CANCELLED: "Anulowano",
}


class RecipeRunnerPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.fields = {}
        self._review_rows = ()
        layout = QVBoxLayout(self)
        self.title = QLabel("Uruchom recepturę")
        layout.addWidget(self.title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.form = QFormLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.database = QLabel()
        self.database.setWordWrap(True)
        layout.addWidget(self.database)
        self.status = QLabel("Wybierz parametry i sprawdź plan przed uruchomieniem.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.review_table = QTableWidget()
        self.review_table.setVisible(False)
        layout.addWidget(self.review_table)
        actions = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.continue_button = QPushButton("Kontynuuj zatwierdzony zakres")
        self.copy_button = QPushButton("Zapisz nową kopię")
        self.cancel_button = QPushButton("Anuluj")
        self.open_button = QPushButton("Otwórz wynik")
        self.repeat_button = QPushButton("Powtórz")
        for button in (self.start_button, self.continue_button, self.copy_button,
                       self.cancel_button, self.open_button, self.repeat_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.start_button.clicked.connect(self._start)
        self.continue_button.clicked.connect(self._continue)
        self.copy_button.clicked.connect(lambda: controller.resume("new_copy"))
        self.cancel_button.clicked.connect(controller.cancel)
        self.open_button.clicked.connect(self._open)
        self.repeat_button.clicked.connect(controller.repeat)
        controller.selection_changed.connect(self._selection)
        controller.changed.connect(self._changed)
        controller.failed.connect(self._failed)
        controller.event_received.connect(self._event)
        controller.idle.connect(self._idle)
        self._buttons()

    def _selection(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields.clear()
        self.review_table.hide()
        self.scope.clear()
        self.status.setText("Sprawdź parametry. Start odczyta plan przed pierwszą zmianą bazy.")
        self.title.setText(self.controller.binding.name)
        for spec in self.controller.definition.parameters:
            if spec.mode is not ParameterMode.PROMPT:
                continue
            value = self.controller.binding.value(spec.key)
            if spec.type is ParameterType.BOOLEAN:
                editor = QCheckBox()
                editor.setChecked(bool(value))
                editor.toggled.connect(self._preview)
            else:
                editor = QLineEdit()
                editor.setText(", ".join(value) if isinstance(value, tuple) else str(value if value is not None else ""))
                editor.textChanged.connect(self._preview)
            self.fields[spec.key] = (editor, spec)
            label = _LABELS.get(spec.key.value, spec.key.value.replace("_", " "))
            if spec.type is ParameterType.PATH:
                row = QWidget()
                box = QHBoxLayout(row)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(editor)
                browse = QPushButton("Wybierz…")
                browse.clicked.connect(lambda _checked=False, key=spec.key: self._browse(key))
                box.addWidget(browse)
                self.form.addRow(label, row)
                self.form.labelForField(row).setBuddy(editor)
            else:
                self.form.addRow(label, editor)
        self._preview()
        if self.fields:
            next(iter(self.fields.values()))[0].setFocus()
        self._buttons()

    def _values(self):
        values = {}
        for key, (editor, spec) in self.fields.items():
            if spec.type is ParameterType.BOOLEAN:
                value = editor.isChecked()
            else:
                value = editor.text()
                if spec.type is ParameterType.INTEGER:
                    value = int(value)
                elif spec.type is ParameterType.NUMBER:
                    value = float(value)
                elif spec.type is ParameterType.STRINGS:
                    value = tuple(part.strip() for part in value.split(",") if part.strip())
            values[key] = value
        return values

    def _preview(self, *_):
        output = self.fields.get(ParameterKey.OUTPUT_FILE)
        if output:
            from pathlib import Path
            text = output[0].text().strip()
            self.database.setText(f"Wyliczona baza: {Path(text).with_suffix('.db')}" if text else "Wyliczona baza: —")
        else:
            self.database.clear()

    def _browse(self, key):
        editor, _spec = self.fields[key]
        if key is ParameterKey.INPUT_FOLDER:
            path = QFileDialog.getExistingDirectory(self, "Folder raportów", editor.text())
        elif key is ParameterKey.OUTPUT_FILE:
            html = not any(s.kind is StepKind.EXPORT_MAIN for s in self.controller.definition.steps)
            path, _ = QFileDialog.getSaveFileName(self, "Plik wynikowy", editor.text(),
                                                "HTML (*.html)" if html else "Excel (*.xlsx)")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Plik źródłowy", editor.text())
        if path:
            editor.setText(path)

    def _start(self):
        try:
            prepared = self.controller.prepare(self._values())
        except (ValueError, TypeError):
            self._failed("invalid_parameter")
            return
        if prepared:
            self.controller.start()
            self._buttons()

    def _continue(self):
        for index, row in enumerate(self._review_rows):
            for column, field in enumerate(REVIEW_FIELDS, start=1):
                value = self.review_table.item(index, column).text()
                if value != (row.value(field) or ""):
                    valid, _error = row.set_user_value(field, value)
                    if not valid:
                        self._failed("invalid_metadata")
                        return
        record = self.controller.last_record
        self.controller.resume("continue_partial" if record and record.partial_import else "continue")
        self._buttons()

    def _changed(self, record):
        self.status.setText(_STATE_LABELS.get(record.state, record.state.value))
        if record.state is RunState.REQUIRES_DECISION:
            result = self.controller.runner.review
            if result is not None:
                self.scope.setText("\n".join(result.summary))
                review = result.review
                self._review_rows = getattr(review, "rows", ())
                if review is not None:
                    files = getattr(getattr(review, "preflight", None), "files", ())
                    lines = [f"{item.display_name}: {item.status.value}" for item in files]
                    self.scope.setText("\n".join((*result.summary, *lines)))
                self.review_table.setColumnCount(1 + len(REVIEW_FIELDS))
                self.review_table.setHorizontalHeaderLabels(["Raport", *(FIELD_LABELS[f] for f in REVIEW_FIELDS)])
                self.review_table.setRowCount(len(self._review_rows))
                for index, row in enumerate(self._review_rows):
                    name_item = QTableWidgetItem(row.display_name)
                    name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.review_table.setItem(index, 0, name_item)
                    for column, field in enumerate(REVIEW_FIELDS, start=1):
                        self.review_table.setItem(index, column, QTableWidgetItem(row.value(field) or ""))
                self.review_table.setVisible(bool(self._review_rows))
        else:
            self.review_table.hide()
        self._buttons()

    def _event(self, event):
        if event.total:
            self.progress.setValue(round(100 * event.completed / event.total))

    def _failed(self, code):
        self.status.setText(f"Nie można kontynuować: {code}")
        self._buttons()

    def _idle(self):
        self._buttons()

    def _buttons(self):
        record = self.controller.last_record
        busy = self.controller.busy
        decision = bool(record and record.state is RunState.REQUIRES_DECISION)
        self.start_button.setEnabled(not busy and self.controller.definition is not None)
        self.continue_button.setVisible(decision)
        self.copy_button.setVisible(decision)
        self.continue_button.setEnabled(self.controller._task is None)
        self.copy_button.setEnabled(self.controller._task is None)
        self.cancel_button.setEnabled(busy)
        self.repeat_button.setEnabled(not busy and self.controller.definition is not None)
        verified = bool(record and any(s.result.artifact_verified for s in record.steps))
        self.open_button.setEnabled(verified and self.controller.plan is not None)
        for editor, _spec in self.fields.values():
            editor.setEnabled(not busy)

    def _open(self):
        plan = self.controller.plan
        if plan and plan.output_file and plan.output_file.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(plan.output_file)))
