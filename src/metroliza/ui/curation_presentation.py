"""Bounded draft presentation and window-local commands for curation dialogs."""
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication

from metroliza.ui.shortcuts import bind_shortcut, plain_text, visible_shortcut


FIELD_LABELS = {
    'report_id': 'Report ID', 'measurement_id': 'Measurement ID',
    'reference': 'Reference', 'report_date': 'Date', 'report_time': 'Time',
    'part_name': 'Part name', 'revision': 'Revision', 'sample_number': 'Sample number',
    'operator_name': 'Operator name', 'comment': 'Comment', 'file_name': 'File name',
    'filename': 'File name', 'fileloc': 'Source file location', 'template_variant': 'Template variant',
    'header': 'Header', 'section_name': 'Section', 'feature_key': 'Feature key',
    'characteristic': 'Characteristic', 'family': 'Family', 'description': 'Description',
    'feature_label': 'Feature label', 'characteristic_name': 'Characteristic name',
    'characteristic_family': 'Characteristic family',
    'ax': 'Axis', 'nominal': 'Nominal', 'tol_plus': 'Upper tolerance',
    'tol_minus': 'Lower tolerance', 'bonus': 'Bonus', 'meas': 'Measured value',
    'dev': 'Deviation', 'outtol': 'Outside tolerance', 'status_code': 'Status code',
}


def field_label(spec):
    return FIELD_LABELS.get(spec['field'], spec['label'])


def short_value(value):
    text = 'NULL' if value is None else repr(str(value))
    return text if len(text) <= 90 else text[:87] + '…'


def bind_button(window, button, sequence):
    """Invoke the actual enabled button, isolated from child windows."""
    action = QAction(plain_text(button.text()), window)
    bind_shortcut(action, sequence)
    action.setAutoRepeat(False)

    def invoke():
        if (window.isActiveWindow() and QApplication.activeModalWidget() in (None, window)
                and button.isVisibleTo(window) and button.isEnabled()):
            # Match a mouse click: commit the active table delegate before Apply.
            button.setFocus()
            button.click()

    action.triggered.connect(invoke)
    window.addAction(action)
    legacy = button.shortcut().toString()
    if legacy:
        base = button.property("metrolizaShortcutTooltipBase") or button.accessibleName()
        button.setToolTip(f"{base} · {legacy} (secondary)")
    visible_shortcut(button, sequence)
    return action
