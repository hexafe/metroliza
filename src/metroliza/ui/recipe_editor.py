"""Typed recipe cards and local parameter controls; no executing editor expressions."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from metroliza.recipes.contracts import ParameterKey, ParameterMode, ParameterType, StepKind
from metroliza.recipes.editor_service import RecipeEditorService
from metroliza.ui.recipe_labels import CHOICE_LABELS, MODE_LABELS, PARAMETER_LABELS, STEP_LABELS, choice_editor

_GROUP_LABELS = {"DATE": "Data", "PART_NAME": "Nazwa części", "REFERENCE": "Numer referencyjny",
                 "REVISION": "Rewizja", "SAMPLE_NUMBER": "Numer próbki", "TEMPLATE_VARIANT": "Wariant szablonu"}


class RecipeEditor(QDialog):
    saved = pyqtSignal(object)

    def __init__(self, stored, store, parent=None):
        super().__init__(parent)
        self._widgets_dirty = False
        self.store = store
        self.service = RecipeEditorService(stored)
        if stored.definition.builtin:
            self.service.duplicate()
        self.setWindowTitle("Edytor receptury")
        self.resize(720, 650)
        layout = QVBoxLayout(self)
        self.name = QLineEdit(self.service.current.binding.name)
        layout.addWidget(QLabel("Nazwa receptury"))
        layout.addWidget(self.name)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.cards = QListWidget()
        self.cards.setAccessibleName("Kroki receptury")
        layout.addWidget(self.cards)
        self.dates = QCheckBox("Wybieraj zakres dat przy uruchomieniu")
        self.dates.setChecked(any(p.key is ParameterKey.DATE_FROM
                                 for p in self.service.current.definition.parameters))
        self.html = QCheckBox("Utwórz także raport HTML")
        self.html.setChecked(any(s.kind is StepKind.EXPORT_HTML for s in stored.definition.steps))
        self.groups = QLineEdit()
        self.groups.setPlaceholderText(", ".join(_GROUP_LABELS.values()))
        self.report_controls = QWidget()
        report_layout = QFormLayout(self.report_controls)
        report_layout.addRow(self.dates)
        self.group_mode = QComboBox()
        for mode in (ParameterMode.FIXED, ParameterMode.PROMPT):
            self.group_mode.addItem(MODE_LABELS[mode], mode)
        self.group_mode.setAccessibleName("Kolumny grupowania — sposób ustawiania")
        group_row = QHBoxLayout()
        group_row.addWidget(self.groups)
        group_row.addWidget(self.group_mode)
        report_layout.addRow("Grupuj według", group_row)
        self.groups.textChanged.connect(lambda text: self.group_mode.setEnabled(bool(text.strip())))
        self.group_mode.activated.connect(self._mark_modified)
        report_layout.addRow(self.html)
        layout.addWidget(self.report_controls)
        kinds = {step.kind for step in stored.definition.steps}
        self.report_controls.setVisible(bool(kinds & {StepKind.IMPORT_REPORTS, StepKind.OPEN_DATABASE}))
        self.html.setEnabled(StepKind.EXPORT_MAIN in kinds)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        self.pin_on_save = QCheckBox("Przypnij do Home po zapisaniu")
        layout.addWidget(self.pin_on_save)
        actions = QHBoxLayout()
        preview = QPushButton("Podgląd")
        preview.clicked.connect(self._preview)
        save = QPushButton("Zapisz recepturę")
        save.clicked.connect(self._save)
        save_new = QPushButton("Zapisz jako nową")
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
        self.status.setText("Niezapisane zmiany")

    def _refresh(self):
        self.cards.clear()
        for step in self.service.current.definition.steps:
            self.cards.addItem(STEP_LABELS[step.kind])
        current = self.service.current
        kinds = {step.kind for step in current.definition.steps}
        self.groups.setText(", ".join(_GROUP_LABELS.get(key, key)
                                      for key in current.binding.value(ParameterKey.GROUPING_RULES, ())))
        group_mode = next((p.mode for p in current.definition.parameters if p.key is ParameterKey.GROUPING_RULES),
                          ParameterMode.FIXED)
        self.group_mode.setCurrentIndex(self.group_mode.findData(group_mode))
        self.group_mode.setEnabled(bool(self.groups.text().strip()))
        self.html.setChecked(StepKind.EXPORT_HTML in kinds)
        widget = QWidget()
        form = QFormLayout(widget)
        self.controls = {}
        for spec in self.service.current.definition.parameters:
            if spec.key is ParameterKey.GROUPING_RULES and not self.report_controls.isHidden():
                continue  # Managed by the single report grouping field above.
            row = QWidget()
            line = QHBoxLayout(row)
            mode = QComboBox()
            modes = [ParameterMode.FIXED, ParameterMode.PROMPT]
            if spec.key is ParameterKey.DATABASE_FILE:
                modes.append(ParameterMode.DERIVED)
            for value in modes:
                mode.addItem(MODE_LABELS[value], value)
            mode.setCurrentIndex(modes.index(spec.mode))
            value = self.service.current.binding.value(spec.key, "")
            if spec.key in CHOICE_LABELS:
                edit = choice_editor(spec.key, value)
                edit.currentIndexChanged.connect(self._mark_modified)
            else:
                edit = QLineEdit(", ".join(value) if type(value) is tuple else str(value))
                edit.textEdited.connect(self._mark_modified)
            if spec.key in {ParameterKey.EXPORT_OPTIONS, ParameterKey.FILTER_VALUES,
                            ParameterKey.ANALYTICS_REQUEST}:
                # Captured typed configuration remains exact; no raw JSON editor.
                edit.setReadOnly(True)
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setEnabled(spec.mode is not ParameterMode.DERIVED)
            mode.currentIndexChanged.connect(lambda _index, m=mode, e=edit:
                e.setEnabled(m.currentData() is not ParameterMode.DERIVED))
            mode.currentIndexChanged.connect(self._mark_modified)
            line.addWidget(mode)
            line.addWidget(edit)
            form.addRow(PARAMETER_LABELS[spec.key], row)
            mode.setAccessibleName(PARAMETER_LABELS[spec.key] + " — sposób ustawiania")
            edit.setAccessibleName(PARAMETER_LABELS[spec.key])
            self.controls[spec.key] = (spec, mode, edit)
        self.scroll.setWidget(widget)
        self.status.setText("Niezapisane zmiany" if self.service.modified or not current.binding.revision
                            else "Zapisano recepturę")

    def _collect(self):
        # Transactional editor changes: a bad control must not retain half an edit.
        previous = self.service.current
        try:
            self.service.rename(self.name.text())
            for key, (spec, mode, edit) in self.controls.items():
                self.service.set_mode(key, mode.currentData())
                if isinstance(edit, QComboBox):
                    if edit.currentIndex() >= 0:
                        self.service.set_value(key, edit.currentData())
                    continue
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
            if not self.report_controls.isHidden():
                self._collect_report_options()
        except Exception:
            self.service.current = previous
            raise

    def _collect_report_options(self):
        by_name = {label.casefold(): key for key, label in _GROUP_LABELS.items()}
        groups = tuple(by_name.get(text.casefold(), text.upper()) for word in self.groups.text().split(",")
                       if (text := word.strip()))
        current = self.service.current
        dates = any(p.key is ParameterKey.DATE_FROM for p in current.definition.parameters)
        html = any(s.kind is StepKind.EXPORT_HTML for s in current.definition.steps)
        if (self.dates.isChecked(), groups, self.html.isChecked()) != (
                dates, current.binding.value(ParameterKey.GROUPING_RULES, ()), html):
            self.service.configure_reports(dates=self.dates.isChecked(), grouping_columns=groups,
                                           additional_html=self.html.isChecked())
        if groups:
            self.service.set_mode(ParameterKey.GROUPING_RULES, self.group_mode.currentData())

    def _preview(self):
        try:
            self._collect()
            self._refresh()
            plan = self.service.preview()
            outputs = [str(path) for path in (plan.database_file, plan.output_file) if path]
            kinds = {s.kind for s in plan.definition.steps}
            if {StepKind.EXPORT_MAIN, StepKind.EXPORT_HTML} <= kinds and plan.output_file:
                outputs.append(str(plan.output_file.with_suffix(".html")))
            self.preview_label.setText("\n".join(outputs))
        except ValueError as error:
            self._error(error)

    def _save(self, _checked=False, *, as_new=False):
        try:
            self._collect()
            saved = self.service.save(self.store, as_new=as_new)
            self.saved.emit(saved)
            self._refresh()
            self._widgets_dirty = False
            if not self.report_controls.isHidden():
                kinds = {s.kind for s in saved.definition.steps}
                outputs = [name for kind, name in ((StepKind.EXPORT_MAIN, "Excel"), (StepKind.EXPORT_HTML, "HTML"))
                           if kind in kinds]
                self.status.setText("Zapisano recepturę. Wyniki: " + " i ".join(outputs))
            self.preview_label.clear()
        except (ValueError, OSError) as error:
            self._error(error)

    def _error(self, error):
        code = getattr(error, "code", "invalid_configuration")
        messages = {
            "unsupported_grouping_rule": "Wpisz nazwę kolumny grupowania z listy podpowiedzi.",
            "missing_parameter": "Uzupełnij wymagane pola, aby zobaczyć podgląd.",
            "revision_conflict": "Receptura została zmieniona. Otwórz ją ponownie lub zapisz jako nową.",
        }
        QMessageBox.warning(self, "Receptura", messages.get(code, "Sprawdź nazwę, wartości pól i miejsce zapisu."))

    def _can_discard(self):
        if not self._widgets_dirty and not self.service.modified:
            return True
        answer = QMessageBox.question(self, "Niezapisane zmiany",
            "Odrzucić zmiany w recepturze?",
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
