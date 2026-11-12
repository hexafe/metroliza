"""Bounded presentation of draft metadata and validated output requests; no data reads."""
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QLabel

from metroliza.ui.shortcuts import bind_shortcut, visible_shortcut


def install_output_commands(window, generate, stop, close, search):
    """Keep mutation keys window-scoped and use existing action/close guards."""
    for sequence, callback in (("Ctrl+S", generate.click), ("Ctrl+Shift+S", stop), ("Ctrl+W", close), ("Ctrl+F", search)):
        action = QAction(window)
        bind_shortcut(action, sequence)
        action.setAutoRepeat(False)
        action.triggered.connect(callback)
        window.addAction(action)
    visible_shortcut(generate, "Ctrl+S")
    legend = QLabel("Generate Ctrl+S · Stop Ctrl+Shift+S · Close Ctrl+W / Esc · Search Ctrl+F")
    legend.setWordWrap(True)
    layout = window.layout() if callable(window.layout) else window.layout
    layout.insertWidget(layout.count() - 1, legend)
    return legend


def output_summary(*, source, scope, grouping, dashboard, workbook, phase="Draft", extra=""):
    """Return compact visible copy and full-path details from supplied metadata only."""
    def brief(value, missing="not selected"):
        text = str(value or "")
        return (Path(text).name or text)[:100] if text else missing

    scope = str(scope or "all rows")
    grouping = str(grouping or "not applied")
    text = (f"{phase} — Source: {brief(source)} | Filter: {scope[:100]} | Groups: {grouping[:80]}\n"
            f"Dashboard (HTML): {brief(dashboard, 'off')} | Output workbook (XLSX): {brief(workbook, 'off')}")
    if extra:
        text += f" | {extra}"
    details = (f"{phase}\nSource: {source or 'not selected'}\nFilter: {scope}\nGroups: {grouping}\n"
               f"Dashboard (HTML): {dashboard or 'off'}\nOutput workbook (XLSX): {workbook or 'off'}\n{extra}")
    return text, details


def analytics_scope(request):
    """Describe immutable predicate metadata without validating or materializing input."""
    if request.source_kind == "production_cache":
        return request.filter_state.summary()
    return tabular_scope(request.tabular_filter_expression, request.tabular_column_filters,
                         request.tabular_filter_columns, request.tabular_filter_keys)


def tabular_scope(expression, rules, columns, keys):
    parts = [expression] if expression else []
    parts.extend(_column_rule_summary(rule) for rule in rules[:3])
    if len(rules) > 3:
        parts.append(f"{len(rules)} column conditions")
    if keys:
        preview = "; ".join(" / ".join(key) for key in keys[:3])
        parts.append(f"{', '.join(columns)}: {preview} ({len(keys)} selected keys)")
    return "; ".join(parts) or "all rows"


def assignment_summary(assignments):
    if assignments is None:
        return "not applied"
    names = ", ".join(dict.fromkeys(row.group for row in assignments[:3]))
    return f"{len(assignments)} assigned rows ({names})"


def _column_rule_summary(rule):
    if rule.selected_values:
        detail = ", ".join(str(value) for value in rule.selected_values[:3])
        detail += f" ({len(rule.selected_values)} values)"
    elif rule.numeric_operator:
        detail = f"{rule.numeric_operator} {rule.numeric_value}"
    elif rule.date_operator:
        detail = f"{rule.date_operator} {rule.date_value}"
    else:
        detail = f"{rule.date_mode} {rule.date_from or ''} {rule.date_to or ''}"
    return f"{rule.column}: {detail}"


def analytics_summary(request, *, phase="Launch request"):
    files = getattr(request.tabular_load_result, "source_files", ()) or ()
    source = request.db_file if request.source_kind == "production_cache" else request.input_file
    fields = request.aggregation_state.group_fields
    grouping = assignment_summary(request.grouping_df) if request.grouping_df is not None else ", ".join(fields)
    extra = (f"{len(request.metric_selection)} metrics; {request.aggregation_state.time_bucket}; "
             + ", ".join(request.aggregation_state.aggregation_methods))
    if request.cohort_state.is_applied:
        extra += "; " + request.cohort_state.summary()
    if len(files) > 1:
        extra += f"; {len(files)} input files"
    return output_summary(source=source, scope=analytics_scope(request), grouping=grouping,
                          dashboard=request.output_dashboard_file, workbook=request.output_workbook_file,
                          phase=phase, extra=extra)


def set_output_summary(label, summary):
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(summary[0])
    label.setToolTip(summary[1])
