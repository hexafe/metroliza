"""Presentation-only scope labels and guarded keys for filter editors."""

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication

from metroliza.ui.shortcuts import bind_shortcut, plain_text, visible_shortcut


def choice_scope_text(selected_count, matches, *, hidden_count=0):
    scope = f"Selected ({selected_count})" if selected_count else "All"
    hidden = f" · {hidden_count} hidden selected" if hidden_count else ""
    return f"Values: {scope} · {matches}{hidden}"


def list_choice_text(widget, *, all_marker=None):
    items = [widget.item(row) for row in range(widget.count())]
    values = [item for item in items if item.text() != all_marker]
    selected = [item for item in values if item.isSelected()]
    if any(item.isSelected() and item.text() == all_marker for item in items):
        selected = []
    matching = sum(not item.isHidden() for item in values)
    return choice_scope_text(len(selected), f"{matching} matching / {len(values)} listed choices",
                             hidden_count=sum(item.isHidden() for item in selected))


class FilterCommandBindings(QObject):
    """Window commands use real buttons; bare keys belong only to focused lists."""

    def __init__(self, window, commands, *, local=()):
        super().__init__(window)
        self.window = window
        self.actions = {}
        self.local = dict(local)
        for sequence, button in commands:
            action = QAction(plain_text(button.text()), window)
            bind_shortcut(action, sequence)
            action.setAutoRepeat(False)
            action.triggered.connect(lambda checked=False, target=button: self._invoke(target))
            window.addAction(action)
            self.actions[sequence] = action
            legacy = button.shortcut().toString()
            if legacy:
                base = button.property("metrolizaShortcutTooltipBase") or button.accessibleName()
                button.setToolTip(f"{base} · {legacy} (secondary)")
            visible_shortcut(button, sequence)
        for listing, _key in self.local:
            listing.installEventFilter(self)

    def _invoke(self, button):
        modal = QApplication.activeModalWidget()
        if (self.window.isActiveWindow() and modal in (None, self.window)
                and button.isVisibleTo(self.window) and button.isEnabled()):
            button.click()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            button = self.local.get((watched, event.key()))
            if button is not None and watched.hasFocus():
                if not event.isAutoRepeat():
                    self._invoke(button)
                return True
        return super().eventFilter(watched, event)
