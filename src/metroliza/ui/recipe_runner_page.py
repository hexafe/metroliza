"""Persistent recipe form, review and result presentation for a shared controller."""
from __future__ import annotations

from pathlib import Path
from time import monotonic

from PyQt6.QtCore import QSignalBlocker, QTimer, QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from metroliza.recipes.contracts import ParameterKey, ParameterMode, ParameterType, RecipeError, StepKind
from metroliza.recipes.run_state import RunState
from metroliza.recipes.ports import PreparationPhase, ResultCode
from metroliza.recipes.validation import DATE_KEYS, RecipeDateError, normalize_recipe_dates
from metroliza.reports.report_metadata_review import REVIEW_FIELDS, FIELD_LABELS
from metroliza.ui.report_planner_metadata import cell_tooltip
from metroliza.ui.recipe_labels import (
    CHOICE_LABELS, DATE_HINT, PARAMETER_LABELS, STEP_LABELS, RecipeSourceFilesEdit, choice_editor,
    date_error_message, date_hint, format_parameter_list, parse_parameter_list,
)

_BROWSE_LABELS = {ParameterKey.INPUT_FOLDER: "Wybierz folder…", ParameterKey.OUTPUT_FILE: "Wybierz wynik…",
                  ParameterKey.EXISTING_DATABASE: "Wybierz bazę…", ParameterKey.SOURCE_FILE: "Wybierz źródło…",
                  ParameterKey.SOURCE_FILES: "Wybierz pliki…"}
_STATE_LABELS = {
    RunState.READY: "Gotowe", RunState.RUNNING: "Trwa wykonywanie",
    RunState.REQUIRES_DECISION: "Wymagana decyzja", RunState.COMPLETED: "Zakończono",
    RunState.COMPLETED_WITH_WARNINGS: "Zakończono z ostrzeżeniami",
    RunState.PARTIAL: "Wynik częściowy", RunState.FAILED: "Niepowodzenie",
    RunState.CANCELLING: "Anulowanie", RunState.CANCELLED: "Anulowano",
}
_MODE_LABELS = CHOICE_LABELS[ParameterKey.METADATA_MODE]
_PHASE_LABELS = {
    PreparationPhase.SCAN: "Skanowanie folderu",
    PreparationPhase.METADATA: "Odczyt metadanych",
    PreparationPhase.OCR: "Odczyt metadanych i OCR",
}


class RecipeRunnerPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.fields = {}
        self.date_hints = {}
        self._saved_date_inputs = {}
        self._review_rows = ()
        self._presented_review = None
        self._attention_rows = set()
        self._stage_key = None
        self._stage_title = ""
        self._stage_started = 0.0
        self._stage_count = ""
        self._stage_timer = QTimer(self)
        self._stage_timer.setInterval(500)
        self._stage_timer.timeout.connect(self._update_stage_label)
        layout = QVBoxLayout(self)
        self.title = QLabel("Uruchom recepturę")
        layout.addWidget(self.title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.form = QFormLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.mode_combo = QComboBox()
        for mode, label in _MODE_LABELS.items():
            self.mode_combo.addItem(label, mode)
        self.mode_combo.setAccessibleName("Tryb importu")
        self.mode_row = QWidget()
        mode_layout = QFormLayout(self.mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addRow("Tryb importu", self.mode_combo)
        self.mode_combo.currentIndexChanged.connect(self._form_edited)
        self.mode_row.hide()
        layout.addWidget(self.mode_row)
        self.database = QLabel()
        self.database.setTextFormat(Qt.TextFormat.PlainText)
        self.database.setWordWrap(True)
        layout.addWidget(self.database)
        self.status = QLabel("Wybierz parametry i sprawdź plan przed uruchomieniem.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.stage = QLabel()
        layout.addWidget(self.stage)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Postęp receptury")
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress, 1)
        self.progress_percent = QLabel()
        self.progress_percent.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress_row.addWidget(self.progress_percent)
        layout.addLayout(progress_row)
        self.scope = QLabel()
        self.scope.setTextFormat(Qt.TextFormat.PlainText)
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.only_attention = QCheckBox("Tylko raporty wymagające uwagi")
        self.only_attention.toggled.connect(self._filter_review)
        self.only_attention.hide()
        layout.addWidget(self.only_attention)
        self.review_table = QTableWidget()
        self.review_table.cellChanged.connect(self._review_cell_changed)
        self.review_table.setAccessibleName("Metadane raportów do przeglądu")
        self.review_table.setMinimumHeight(120)
        self.review_table.setVisible(False)
        layout.addWidget(self.review_table, 1)
        actions = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.continue_button = QPushButton("Kontynuuj zatwierdzony zakres")
        self.copy_button = QPushButton("Zapisz nową kopię")
        self.cancel_button = QPushButton("Anuluj")
        self.open_button = QPushButton("Otwórz wynik")
        self.repeat_button = QPushButton("Powtórz")
        self.restart_button = QPushButton("Zacznij od nowa")
        for button in (self.start_button, self.continue_button, self.copy_button,
                       self.cancel_button, self.open_button, self.repeat_button, self.restart_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.start_button.clicked.connect(self._start)
        self.continue_button.clicked.connect(self._continue)
        self.copy_button.clicked.connect(lambda: controller.resume("new_copy"))
        self.cancel_button.clicked.connect(controller.cancel)
        self.open_button.clicked.connect(self._open)
        self.repeat_button.clicked.connect(controller.repeat)
        self.restart_button.clicked.connect(controller.restart)
        controller.selection_changed.connect(self._selection)
        controller.prepared.connect(self._prepared)
        controller.changed.connect(self._changed)
        controller.failed.connect(self._failed)
        controller.event_received.connect(self._event)
        controller.idle.connect(self._idle)
        self._buttons()

    def _selection(self):
        self._reset_stage()
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields.clear()
        self.date_hints.clear()
        self._saved_date_inputs = {key: self.controller.binding.value(key, "") for key in DATE_KEYS}
        self._review_rows = ()
        self._presented_review = None
        self.only_attention.hide()
        self.review_table.hide()
        self.scope.clear()
        self.scope.setToolTip("")
        self.status.setText("Sprawdź parametry uruchomienia.")
        self.title.setText(self.controller.binding.name)
        self.mode_row.setVisible(any(
            spec.key is ParameterKey.METADATA_MODE and spec.mode is ParameterMode.PROMPT
            for spec in self.controller.definition.parameters
        ))
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(
            self.controller.binding.value(ParameterKey.METADATA_MODE, "complete")
        ))
        for spec in self.controller.definition.parameters:
            if spec.mode is not ParameterMode.PROMPT or spec.key is ParameterKey.METADATA_MODE:
                continue
            value = self.controller.binding.value(spec.key)
            if spec.type is ParameterType.BOOLEAN:
                editor = QCheckBox()
                editor.setChecked(bool(value))
                editor.toggled.connect(self._form_edited)
            elif spec.key is ParameterKey.SOURCE_FILES:
                editor = RecipeSourceFilesEdit(value or ())
                editor.paths_changed.connect(self._form_edited)
            elif spec.key in CHOICE_LABELS:
                editor = choice_editor(spec.key, value)
                editor.currentIndexChanged.connect(self._form_edited)
            else:
                editor = QLineEdit()
                editor.setText(format_parameter_list(spec.key, value) if isinstance(value, tuple)
                               else str(value if value is not None else ""))
                editor.textChanged.connect(self._form_edited)
            self.fields[spec.key] = (editor, spec)
            label = PARAMETER_LABELS[spec.key]
            editor.setAccessibleName(label)
            if spec.type is ParameterType.PATH or spec.key is ParameterKey.SOURCE_FILES:
                row = QWidget()
                box = QHBoxLayout(row)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(editor)
                browse = QPushButton(_BROWSE_LABELS.get(spec.key, "Wybierz plik…"))
                browse.setAccessibleName(browse.text().rstrip("…"))
                browse.setToolTip(browse.accessibleName())
                browse.clicked.connect(lambda _checked=False, key=spec.key: self._browse(key))
                box.addWidget(browse)
                self.form.addRow(label, row)
                self.form.labelForField(row).setBuddy(editor)
            elif spec.key in DATE_KEYS:
                row = QWidget()
                box = QVBoxLayout(row)
                box.setContentsMargins(0, 0, 0, 0)
                box.addWidget(editor)
                hint = date_hint(editor)
                self.date_hints[spec.key] = hint
                box.addWidget(hint)
                self.form.addRow(label, row)
                self.form.labelForField(row).setBuddy(editor)
            else:
                self.form.addRow(label, editor)
        self.controller.draft_edited = False
        self._preview()
        if self.fields:
            next(iter(self.fields.values()))[0].setFocus()
        self._buttons()

    def _form_edited(self, *_):
        self.controller.draft_edited = True
        for hint in self.date_hints.values():
            hint.setText(DATE_HINT)
        self._preview()
        self._buttons()

    def _values(self):
        values = {}
        if not self.mode_row.isHidden():
            values[ParameterKey.METADATA_MODE] = self.mode_combo.currentData()
        for key, (editor, spec) in self.fields.items():
            if spec.type is ParameterType.BOOLEAN:
                value = editor.isChecked()
            elif isinstance(editor, RecipeSourceFilesEdit):
                value = editor.paths
            elif isinstance(editor, QComboBox):
                value = editor.currentData() or ""
            else:
                value = editor.text()
                if spec.type is ParameterType.INTEGER:
                    value = int(value)
                elif spec.type is ParameterType.NUMBER:
                    value = float(value)
                elif spec.type is ParameterType.STRINGS:
                    value = parse_parameter_list(key, value)
            values[key] = value
        return values

    def _path_value(self, key):
        field = self.fields.get(key)
        return field[0].text().strip() if field else str(self.controller.binding.value(key) or "")

    @staticmethod
    def _describe_import(kinds, mode):
        if StepKind.IMPORT_REPORTS not in kinds:
            return []
        lines = [f"Import · {_MODE_LABELS[mode]}"]
        if StepKind.PREPARE_EXISTING_DATABASE in kinds:
            lines.append("Excel obejmie raporty z wybranego folderu.")
        return lines

    def _source_count_line(self, binding):
        field = self.fields.get(ParameterKey.SOURCE_FILES)
        if field:
            count = len(field[0].paths)
        elif binding.value(ParameterKey.SOURCE_FILES):
            count = len(binding.value(ParameterKey.SOURCE_FILES))
        else:
            count = int(bool(self._path_value(ParameterKey.SOURCE_FILE)))
        return f"Liczba plików źródłowych: {count}"

    @staticmethod
    def _grouping_rule_lines(binding):
        from metroliza.recipes.tabular_adapter import analytics_grouping_labels

        try:
            labels = analytics_grouping_labels(binding)
        except (AttributeError, KeyError, TypeError, ValueError):
            return []
        return ["Reguła grupowania — " + " · ".join(labels)] if labels else []

    @staticmethod
    def _output_lines(kinds, binding, output, assets=None):
        if not output:
            return []
        if StepKind.ANALYZE_TABULAR in kinds:
            from metroliza.recipes.tabular_adapter import analytics_output_family
            try:
                family = analytics_output_family(binding, output)
            except (RecipeError, ValueError):
                return []
            lines = [f"Wynik HTML: {family.dashboard}"]
            if family.workbook is not None:
                lines.append(f"Wynik Excel: {family.workbook}")
            return [*lines, f"Zasoby: {family.assets}"]
        if StepKind.EXPORT_MAIN in kinds:
            lines = [f"Wynik Excel: {output.with_suffix('.xlsx')}"]
        else:
            lines = []
        if StepKind.EXPORT_HTML in kinds:
            from metroliza.charts.export_html_dashboard import resolve_html_dashboard_assets_dir
            html = output.with_suffix(".html")
            lines.extend((f"Wynik HTML: {html}", f"Zasoby: {assets or resolve_html_dashboard_assets_dir(html)}"))
        return lines

    def _preview(self, *_):
        if self.controller.definition is None:
            self.database.clear()
            return
        kinds = {s.kind for s in self.controller.definition.steps}
        mode = (self.controller.binding.value(ParameterKey.METADATA_MODE, "complete")
                if self.mode_row.isHidden() else self.mode_combo.currentData())
        lines = self._describe_import(kinds, mode)
        if StepKind.LOAD_TABULAR in kinds:
            lines.append(self._source_count_line(self.controller.binding))
            lines.extend(self._grouping_rule_lines(self.controller.binding))
        output = self._path_value(ParameterKey.OUTPUT_FILE)
        derived = any(p.key is ParameterKey.DATABASE_FILE and p.mode is ParameterMode.DERIVED
                      for p in self.controller.definition.parameters)
        existing = self._path_value(ParameterKey.EXISTING_DATABASE)
        if derived:
            lines.append(f"Wyliczona baza: {Path(output).with_suffix('.db')}" if output else "Wyliczona baza: —")
        elif existing:
            label = "Baza do uzupełnienia" if StepKind.PREPARE_EXISTING_DATABASE in kinds else "Istniejąca baza"
            lines.append(f"{label}: {existing}")
        if output and Path(output).name:
            lines.extend(self._output_lines(kinds, self.controller.binding, Path(output)))
        self.database.setText("\n".join(lines))

    def _prepared(self, plan):
        kinds = {step.kind for step in plan.definition.steps}
        lines = self._describe_import(kinds, plan.value(ParameterKey.METADATA_MODE, "complete"))
        if StepKind.LOAD_TABULAR in kinds:
            lines.append(self._source_count_line(plan.binding))
            lines.extend(self._grouping_rule_lines(plan.binding))
        if plan.database_file is not None:
            if plan.appends_to_database:
                label = "Baza do uzupełnienia"
            else:
                label = "Wyliczona baza" if StepKind.PREPARE_DATABASE in kinds else "Istniejąca baza"
            lines.append(f"{label}: {plan.database_file}")
        lines.extend(self._output_lines(kinds, plan.binding, plan.output_file, plan.assets_dir))
        self.database.setText("\n".join(lines))

    def _browse(self, key):
        editor, _spec = self.fields[key]
        if isinstance(editor, RecipeSourceFilesEdit):
            editor.browse()
            return
        if key is ParameterKey.INPUT_FOLDER:
            path = QFileDialog.getExistingDirectory(self, "Folder raportów", editor.text())
        elif key is ParameterKey.OUTPUT_FILE:
            html = not any(s.kind is StepKind.EXPORT_MAIN for s in self.controller.definition.steps)
            path, _ = QFileDialog.getSaveFileName(self, "Plik wynikowy", editor.text(),
                                                "HTML (*.html)" if html else "Excel (*.xlsx)")
        elif key is ParameterKey.EXISTING_DATABASE:
            path, _ = QFileDialog.getOpenFileName(self, "Baza raportów", editor.text(),
                                                 "Bazy SQLite (*.db *.sqlite *.sqlite3);;Wszystkie pliki (*)")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Plik źródłowy", editor.text())
        if path:
            editor.setText(path)

    def _start(self):
        for key, (editor, spec) in self.fields.items():
            if isinstance(editor, QCheckBox) or not spec.required:
                continue
            text = editor.currentData() if isinstance(editor, QComboBox) else editor.text()
            if not (text or "").strip():
                self._invalid_parameter(key)
                return
        try:
            values = self._values()
            saved = dict(self.controller.binding.values)
            edited = tuple(key for key in DATE_KEYS if key in values and values[key] != self._saved_date_inputs[key])
            values.update(normalize_recipe_dates(saved | values, edited=edited))
            prepared = self.controller.prepare(values)
        except RecipeDateError as error:
            message = date_error_message(error)
            self.status.setText(message)
            if error.key in self.date_hints:
                self.date_hints[error.key].setText(message)
                self.fields[error.key][0].setFocus()
            return
        except (ValueError, TypeError):
            self._failed("invalid_parameter")
            return
        if prepared:
            self.controller.start()
            self._buttons()

    def _continue(self):
        for index, row in enumerate(self._review_rows):
            for column, field in enumerate(REVIEW_FIELDS, start=1):
                item = self.review_table.item(index, column)
                value = item.text()
                if value != (row.value(field) or ""):
                    valid, error = row.set_user_value(field, value)
                    with QSignalBlocker(self.review_table):
                        if valid:
                            item.setText(row.value(field) or "")
                            self._describe_review_item(item, row, field, self._review_field_note(row, field))
                        else:
                            self._set_review_item_description(item, error or "Nieprawidłowa wartość.")
                    if not valid:
                        self.only_attention.setChecked(False)
                        self.review_table.setCurrentItem(item)
                        self.review_table.setFocus()
                        self._failed("invalid_metadata")
                        return
        record = self.controller.last_record
        self.controller.resume("continue_partial" if record and record.partial_import else "continue")
        self._buttons()

    def _changed(self, record):
        messages = {
            ResultCode.SOURCE_CHANGED: "Źródło zmieniło się. Wybierz Powtórz, aby sprawdzić aktualny zbiór.",
            ResultCode.DATABASE_UNAVAILABLE: "Sprawdź, czy wybrana baza nadal istnieje i jest gotowa do pracy w Reports.",
            ResultCode.EXPORT_FAILED: "Nie udało się zapisać wyniku. Sprawdź plik docelowy i jego uprawnienia.",
            ResultCode.OUTPUT_MISSING: "Nie udało się potwierdzić zapisu oczekiwanego pliku wynikowego.",
            ResultCode.WORKBOOK_NOT_PUBLISHED: "Wynik częściowy. Zapisano HTML. Brakuje nowego pliku Excel.",
            ResultCode.GROUPING_RULE_UNAVAILABLE: (
                "W źródle brakuje kolumny wymaganej przez regułę grupowania. Sprawdź mapowanie kolumn lub wybierz inne źródło."
            ),
            ResultCode.MANUAL_GROUPING_RECAPTURE_REQUIRED: (
                "Nie można potwierdzić ręcznych przypisań. W CSV Summary wczytaj aktualne źródło, "
                "sprawdź grupy i zapisz recepturę ponownie."
            ),
        }
        self.status.setText(messages.get(record.code, _STATE_LABELS.get(record.state, record.state.value)))
        self.continue_button.setText("Kontynuuj zatwierdzony zakres")
        if record.state is RunState.REQUIRES_DECISION:
            self._show_decision(record)
        else:
            self.review_table.hide()
            self.only_attention.hide()
            self._presented_review = None
            self.scope.setToolTip("")
            if not record.ownership:
                self.scope.setText(self._import_counts(record))
        self._buttons()

    def _show_decision(self, record):
        if record.decision != "review":
            self._review_rows = ()
            self._presented_review = None
            self.only_attention.hide()
            self.scope.setToolTip("")
        if record.decision == "copy_ready":
            self.scope.setText("Sprawdź ścieżki nowej kopii. Wybierz Kontynuuj, aby uruchomić ten plan.")
        elif record.decision == "collision":
            self.scope.setText("Baza lub jej pliki dziennika już istnieją. Wybierz nową kopię albo anuluj.")
        elif record.decision == "partial":
            self.scope.setText(self._import_counts(record))
            self.continue_button.setText("Eksportuj dostępne raporty")
        elif self.controller.runner.review is not None:
            self._show_review(self.controller.runner.review)
        self.review_table.setVisible(bool(self._review_rows))

    def _show_review(self, result):
        review = result.review
        self._review_rows = getattr(review, "rows", ())
        if getattr(review, "conflicts", ()):
            self.continue_button.setText("Zastąp wynik i kontynuuj")
        if self._presented_review is result:
            return
        self._presented_review = result
        self._attention_rows = {index for index, row in enumerate(self._review_rows)
                                if row.needs_attention or row.conflict_fields or row.warnings}
        files = getattr(getattr(review, "preflight", None), "files", ())
        excluded = tuple(item.display_name for item in files if item.status.value not in {"ready", "duplicate"})
        missing = sum(len(row.missing_fields) for row in self._review_rows)
        summary = [*result.summary]
        conflicts = getattr(review, "conflicts", ())
        if conflicts:
            summary.extend(("Ścieżki z kolizją przy zapisie", *(str(path) for path in conflicts)))
        if self._review_rows:
            summary.append(f"Uwaga: {len(self._attention_rows)} raportów · Brakujące pola: {missing}")
        if excluded:
            summary.append(f"Pliki poza importem: {len(excluded)}")
        self.scope.setText("\n".join(summary))
        self.scope.setToolTip("\n".join(excluded[:20]))
        with QSignalBlocker(self.review_table):
            self._populate_review_table()
        self.only_attention.setVisible(0 < len(self._attention_rows) < len(self._review_rows))
        self.only_attention.setChecked(bool(self._attention_rows))
        self._filter_review(self.only_attention.isChecked())

    def _populate_review_table(self):
        self.review_table.setColumnCount(1 + len(REVIEW_FIELDS))
        self.review_table.setHorizontalHeaderLabels(["Raport", *(FIELD_LABELS[f] for f in REVIEW_FIELDS)])
        self.review_table.setRowCount(len(self._review_rows))
        for index, row in enumerate(self._review_rows):
            name_item = QTableWidgetItem(row.display_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.review_table.setItem(index, 0, name_item)
            for column, field in enumerate(REVIEW_FIELDS, start=1):
                item = QTableWidgetItem(row.value(field) or "")
                if not row.editable:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                note = self._review_field_note(row, field)
                self._describe_review_item(item, row, field, note)
                if note:
                    item.setBackground(self.palette().alternateBase())
                    font = self.review_table.font()
                    font.setBold(True)
                    item.setFont(font)
                self.review_table.setItem(index, column, item)

    def _review_cell_changed(self, index, column):
        if not (0 < column <= len(REVIEW_FIELDS) and index < len(self._review_rows)):
            return
        item = self.review_table.item(index, column)
        if item is None:
            return
        row = self._review_rows[index]
        field = REVIEW_FIELDS[column - 1]
        with QSignalBlocker(self.review_table):
            self._describe_review_item(item, row, field, self._review_field_note(row, field))

    @staticmethod
    def _describe_review_item(item, row, field, note):
        if item.text() != (row.value(field) or ""):
            detail = "Ręczna zmiana czeka na zatwierdzenie."
        else:
            evidence = cell_tooltip(row, row.display_name, field)
            detail = f"{note}\n{evidence}" if note else evidence
        RecipeRunnerPage._set_review_item_description(item, detail)

    @staticmethod
    def _set_review_item_description(item, detail):
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, detail)
        item.setToolTip(detail)

    @staticmethod
    def _review_field_note(row, field):
        if field in row.missing_fields:
            return "Brakująca wartość."
        if field in row.conflict_fields:
            return "Sprzeczne wartości metadanych."
        if field in row.low_confidence_fields:
            return "Sprawdź odczytaną wartość."
        return ""

    def _filter_review(self, checked):
        for index in range(len(self._review_rows)):
            self.review_table.setRowHidden(index, checked and index not in self._attention_rows)

    @staticmethod
    def _import_counts(record):
        step = next((step for step in record.steps if step.kind is StepKind.IMPORT_REPORTS), None)
        if step is None:
            return ""
        result = step.result
        return (f"Zapisano: {result.imported_count} · Już w bazie: {result.duplicate_count}"
                f" · Pominięte lub nieudane: {result.rejected_count}")

    def _event(self, event):
        if event.record.state is not RunState.RUNNING:
            if self._stage_timer.isActive():
                self._update_stage_label()
                self._stage_timer.stop()
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
            if event.record.state in {RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS}:
                self.progress.setValue(100)
                self.progress_percent.setText("100%")
            else:
                self.progress_percent.clear()
            return
        title = STEP_LABELS.get(event.step_kind) or _PHASE_LABELS.get(event.phase) or "Przygotowanie"
        key = (event.record.run_id, event.step_id, title)
        if key != self._stage_key:
            self._stage_key = key
            self._stage_title = title
            self._stage_started = monotonic()
            self._stage_count = ""
            self.progress.setRange(0, 0)
            self.progress_percent.setText("W toku")
        if not self._stage_timer.isActive():
            self._stage_timer.start()
        if event.total:
            self.progress.setRange(0, 100)
            self.progress.setValue(round(100 * event.completed / event.total))
            self.progress_percent.setText(f"{self.progress.value()}%")
            if event.step_kind is None:
                self._stage_count = f" · {event.completed}/{event.total}"
        self._update_stage_label()

    def _update_stage_label(self):
        minutes, seconds = divmod(int(monotonic() - self._stage_started), 60)
        self.stage.setText(f"{self._stage_title} · {minutes:02d}:{seconds:02d}{self._stage_count}")

    def _reset_stage(self):
        self._stage_timer.stop()
        self._stage_key = None
        self.stage.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_percent.clear()

    def _failed(self, code):
        messages = {
            "append_busy": "Zakończ pracę w Reports lub zamknij okno korzystające z tej bazy.",
            "invalid_metadata": "Sprawdź wartość wskazanego pola metadanych.",
            "missing_parameter": "Uzupełnij wymagane pola lub popraw zapisane ustawienia receptury.",
            "invalid_path": "Sprawdź podane ścieżki.",
            "invalid_parameter": "Sprawdź format wartości w formularzu.",
            "recipe_not_found": "Sprawdź, czy zapisana receptura jest dostępna w bibliotece.",
            "target_inside_input": "Zapisz wynik poza folderem źródłowym.",
        }
        self.status.setText(messages.get(code, "Sprawdź wartości i ścieżki lub wybierz inną recepturę."))
        self._buttons()

    def _invalid_parameter(self, key):
        if key is not None and key in self.fields:
            editor, _spec = self.fields[key]
            label = PARAMETER_LABELS[key]
            self.status.setText(f"Wybierz lub wpisz: {label}.")
            editor.setFocus()
            return
        self._failed("invalid_parameter")

    def _idle(self):
        self._buttons()

    def _buttons(self):
        record = self.controller.last_record
        busy = self.controller.busy
        decision = bool(record and record.state is RunState.REQUIRES_DECISION)
        self.start_button.setEnabled(not busy and self.controller.definition is not None)
        self.continue_button.setVisible(decision)
        self.copy_button.setVisible(decision and record.decision != "copy_ready")
        self.continue_button.setEnabled(self.controller._task is None and bool(record)
                                        and record.decision != "collision")
        self.copy_button.setEnabled(self.controller._task is None)
        self.cancel_button.setEnabled(busy)
        show_restart = self.controller.draft_edited and not busy
        self.restart_button.setVisible(show_restart)
        self.repeat_button.setVisible(not show_restart)
        self.repeat_button.setEnabled(self.controller.can_repeat)
        plan = self.controller.plan
        verified = bool(record and plan and record.run_id == plan.run_id
                        and record.state in {RunState.COMPLETED, RunState.COMPLETED_WITH_WARNINGS, RunState.PARTIAL}
                        and any(s.result.artifact_verified for s in record.steps))
        self.open_button.setEnabled(verified)
        self.mode_combo.setEnabled(not busy)
        for editor, _spec in self.fields.values():
            editor.setEnabled(not busy)

    def _open(self):
        plan = self.controller.plan
        if plan and plan.output_file and plan.output_file.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(plan.output_file)))
