"""Actual Qt key input with explicit window ownership; no test fixtures or product hooks."""

from contextlib import contextmanager
import json
import time

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QGuiApplication, QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget


def key_state(app, target):
    """Return routing classes/identities and flags, never captions or editor contents."""
    def describe(obj):
        if obj is None:
            return None
        state = {'class': type(obj).__name__, 'id': hex(id(obj))}
        if isinstance(obj, QWidget):
            state.update(flags=int(obj.windowFlags()), visible=obj.isVisible(), enabled=obj.isEnabled(),
                         active=obj.isActiveWindow(), modal=obj.isModal(), is_window=obj.isWindow())
        return state

    try:
        return {name: describe(obj) for name, obj in (
            ('target', target), ('top', target.window()), ('active', app.activeWindow()),
            ('modal', app.activeModalWidget()), ('popup', app.activePopupWidget()),
            ('focus', app.focusWidget()), ('native_focus', QGuiApplication.focusWindow()),
        )}
    except Exception as exc:
        return {'state_error': type(exc).__name__, 'target_class': type(target).__name__}


def activate_for_key(app, target):
    """Establish exact Qt activation/modal/focus ownership within one 20-second deadline."""
    window = target.window()
    expected_modal = window
    while expected_modal is not None:
        if expected_modal.isWindow() and expected_modal.isVisible() and expected_modal.isModal():
            break
        expected_modal = expected_modal.parentWidget()
    window.activateWindow()
    if target is not window:
        target.setFocus()  # Qt resolves the target's real focus proxy.

    def ready():
        if (app.activeWindow() is not window or not window.isActiveWindow()
                or app.activeModalWidget() is not expected_modal):
            return False
        focused = app.focusWidget()
        if target is window:
            return ((focused is not None and focused.window() is window)
                    or (focused is None and window.windowHandle() is not None
                        and QGuiApplication.focusWindow() is window.windowHandle()))
        return target.hasFocus() and focused is not None and focused.window() is window

    deadline = time.monotonic() + 20
    while not ready() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)  # Poll the declared state, not a fixed activation/settling delay.
    assert ready(), ('Keyboard activation/focus precondition failed: '
                     + json.dumps(key_state(app, target), sort_keys=True))


class _ShortcutObserver(QObject):
    def __init__(self, app, target):
        super().__init__()
        self.app, self.target = app, target
        self.events, self.errors = [], []

    def eventFilter(self, receiver, event):
        try:
            if event.type() == QEvent.Type.Shortcut and len(self.events) < 32:
                owner = receiver.parent()
                self.events.append({
                    'key': event.key().toString(), 'ambiguous': event.isAmbiguous(),
                    'receiver_class': type(receiver).__name__, 'receiver_id': hex(id(receiver)),
                    'owner_class': type(owner).__name__, 'owner_id': hex(id(owner)),
                    'state': key_state(self.app, self.target),
                })
        except BaseException as exc:
            # Diagnostic failures cannot cross the Qt virtual-callback boundary.
            if len(self.errors) < 8:
                self.errors.append(type(exc).__name__)
        return False


@contextmanager
def observe_key(app, target, sequence):
    """Observe a raw key send without activation, focus changes or event pumping."""
    before = key_state(app, target)
    observer = _ShortcutObserver(app, target)
    app.installEventFilter(observer)
    try:
        yield
    finally:
        app.removeEventFilter(observer)
        print('COMMAND_KEY_TRACE ' + json.dumps({
            'sequence': sequence, 'before': before, 'after': key_state(app, target),
            'shortcuts': observer.events, 'observer_errors': observer.errors,
        }, sort_keys=True))
    assert not observer.errors, observer.errors


def press_key(app, target, sequence):
    activate_for_key(app, target)
    combination = QKeySequence(sequence)[0]
    with observe_key(app, target, sequence):
        QTest.keyClick(target, combination.key(), combination.keyboardModifiers())
        app.processEvents()
