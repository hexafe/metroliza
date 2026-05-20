from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PyQt6.QtGui import QImageReader, QMovie
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

import base64

from modules import base64_encoded_files
from modules.ui_foundation import apply_metroliza_theme, configure_window_size, secondary_label

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
    return loading_dialog, loading_label, loading_bar, loading_gif


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

    timer.timeout.connect(_show_now)
    dialog.show = delayed_show
    dialog.close = close
    dialog.accept = accept
    dialog.reject = reject
    dialog._delayed_show_timer = timer
