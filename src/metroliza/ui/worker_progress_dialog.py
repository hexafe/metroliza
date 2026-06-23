from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PyQt6.QtGui import QImageReader, QMovie
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

import base64

from metroliza.resources import base64_encoded_files
from metroliza.ui.ui_foundation import apply_metroliza_theme, configure_window_size, secondary_label

try:
    from PyQt6.QtCore import QTimer
except ImportError:  # pragma: no cover - compatibility with lightweight test stubs.
    QTimer = None


def _scaled_loading_gif_size(source_size):
    """Return an aspect-preserving presentation size for the loading GIF."""
    target_max_dimension = 216
    if not source_size.isValid() or source_size.isEmpty():
        return QSize(target_max_dimension, target_max_dimension)

    width = source_size.width()
    height = source_size.height()
    if width >= height:
        scaled_width = target_max_dimension
        scaled_height = max(1, round((target_max_dimension * height) / width))
    else:
        scaled_height = target_max_dimension
        scaled_width = max(1, round((target_max_dimension * width) / height))
    return QSize(scaled_width, scaled_height)


def create_worker_progress_dialog(parent, *, window_title, initial_status_text, on_cancel):
    """Create a standardized progress dialog used by parse/export/csv worker flows."""
    loading_dialog = QDialog(parent, Qt.WindowType.WindowTitleHint)
    loading_dialog.setWindowTitle(window_title)
    loading_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    apply_metroliza_theme(loading_dialog)

    loading_gif_label = QLabel(loading_dialog)
    loading_gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    loading_gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)
    loading_gif_reader_buffer = QBuffer(loading_dialog)
    loading_gif_reader_buffer.setData(QByteArray(loading_gif_decoded))
    loading_gif_reader_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    loading_gif_source_size = QImageReader(loading_gif_reader_buffer, b"gif").size()

    loading_gif_buffer = QBuffer(loading_dialog)
    loading_gif_buffer.setData(QByteArray(loading_gif_decoded))
    loading_gif_buffer.open(QIODevice.OpenModeFlag.ReadOnly)

    loading_gif = QMovie(loading_gif_buffer, b"gif", loading_dialog)
    loading_gif_size = _scaled_loading_gif_size(loading_gif_source_size)
    loading_gif.setScaledSize(loading_gif_size)
    loading_gif_label.setMovie(loading_gif)
    loading_gif.start()
    loading_gif_label.setFixedSize(loading_gif_size)

    loading_label = secondary_label(initial_status_text)
    loading_label.setParent(loading_dialog)
    loading_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    loading_label.setMinimumHeight(loading_label.fontMetrics().lineSpacing() * 3)
    loading_label.setWordWrap(True)

    loading_bar = QProgressBar(loading_dialog)
    loading_bar.setValue(0)
    loading_bar.setMinimumWidth(320)
    loading_bar.setMaximumHeight(20)
    loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout = QVBoxLayout(loading_dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(6)

    status_layout = QHBoxLayout()
    status_layout.setSpacing(10)
    status_layout.addWidget(loading_gif_label, alignment=Qt.AlignmentFlag.AlignVCenter)
    status_layout.addWidget(loading_label, stretch=1)
    layout.addLayout(status_layout)

    cancel_button = QPushButton("Cancel", loading_dialog)
    cancel_button.clicked.connect(on_cancel)

    footer_layout = QHBoxLayout()
    footer_layout.setSpacing(8)
    footer_layout.addWidget(loading_bar, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
    footer_layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignVCenter)
    layout.addLayout(footer_layout)

    content_size = loading_dialog.sizeHint()
    configure_window_size(
        loading_dialog,
        minimum=(480, 240),
        initial=(max(520, content_size.width()), max(240, content_size.height())),
    )

    loading_dialog._loading_gif_buffer = loading_gif_buffer
    _install_user_close_cancel(loading_dialog, on_cancel=on_cancel)
    return loading_dialog, loading_label, loading_bar, loading_gif


def dismiss_worker_progress_dialog(dialog, *, rejected: bool = False) -> None:
    """Close a worker progress dialog after the worker has reached a terminal state."""
    if dialog is None:
        return

    if rejected:
        reject_as_terminal = getattr(dialog, "reject_as_terminal", None)
        if callable(reject_as_terminal):
            reject_as_terminal()
            return
        request_terminal_close = getattr(dialog, "request_terminal_close", None)
        if callable(request_terminal_close):
            request_terminal_close()
        reject = getattr(dialog, "reject", None)
        if callable(reject):
            reject()
            return

    accept = getattr(dialog, "accept", None)
    if callable(accept):
        accept()
        return

    close = getattr(dialog, "close", None)
    if callable(close):
        close()


def _install_user_close_cancel(dialog, *, on_cancel) -> None:
    """Route user window-close attempts through the cooperative cancel callback."""
    original_close_event = dialog.closeEvent
    original_close = dialog.close
    original_accept = dialog.accept
    original_reject = dialog.reject
    state = {"terminal_close": False, "cancel_requested": False}

    def _request_terminal_close() -> None:
        state["terminal_close"] = True

    def _request_cancel() -> None:
        if not state["cancel_requested"]:
            state["cancel_requested"] = True
            on_cancel()

    def close_event(event) -> None:
        if state["terminal_close"]:
            original_close_event(event)
            return
        _request_cancel()
        event.ignore()

    def close() -> bool:
        _request_terminal_close()
        return original_close()

    def accept() -> None:
        _request_terminal_close()
        original_accept()

    def reject() -> None:
        if not state["terminal_close"]:
            _request_cancel()
            return
        original_reject()

    def reject_as_terminal() -> None:
        _request_terminal_close()
        original_reject()

    dialog.closeEvent = close_event
    dialog.close = close
    dialog.accept = accept
    dialog.reject = reject
    dialog.request_terminal_close = _request_terminal_close
    dialog.reject_as_terminal = reject_as_terminal


def create_delayed_worker_progress_dialog(
    parent,
    *,
    window_title,
    initial_status_text,
    on_cancel,
    delay_ms=1000,
):
    """Create a worker progress dialog whose first show is delayed.

    Worker flows can create the widgets immediately, connect progress signals, start the
    worker, and call ``show()``. The actual dialog appears only if the operation is still
    running after ``delay_ms``. Closing, accepting, or rejecting before the timer fires
    cancels the pending show.
    """
    loading_dialog, loading_label, loading_bar, loading_gif = create_worker_progress_dialog(
        parent,
        window_title=window_title,
        initial_status_text=initial_status_text,
        on_cancel=on_cancel,
    )
    _install_delayed_show(loading_dialog, delay_ms=delay_ms)
    return loading_dialog, loading_label, loading_bar, loading_gif


def _install_delayed_show(dialog, *, delay_ms: int) -> None:
    if QTimer is None:
        return

    delay_ms = max(0, int(delay_ms))
    original_show = dialog.show
    original_close = dialog.close
    original_accept = dialog.accept
    original_reject = dialog.reject
    original_reject_as_terminal = getattr(dialog, "reject_as_terminal", None)
    timer = QTimer(dialog)
    timer.setSingleShot(True)
    state = {"finished": False, "shown": False}

    def _show_now() -> None:
        if state["finished"]:
            return
        state["shown"] = True
        original_show()

    def delayed_show() -> None:
        if state["finished"] or state["shown"]:
            return
        if delay_ms <= 0:
            _show_now()
            return
        if not timer.isActive():
            timer.start(delay_ms)

    def finish() -> None:
        state["finished"] = True
        if timer.isActive():
            timer.stop()

    def close() -> bool:
        finish()
        return original_close()

    def accept() -> None:
        finish()
        original_accept()

    def reject() -> None:
        finish()
        original_reject()

    def reject_as_terminal() -> None:
        finish()
        if callable(original_reject_as_terminal):
            original_reject_as_terminal()
        else:
            original_reject()

    timer.timeout.connect(_show_now)
    dialog.show = delayed_show
    dialog.close = close
    dialog.accept = accept
    dialog.reject = reject
    dialog.reject_as_terminal = reject_as_terminal
    dialog._delayed_show_timer = timer
