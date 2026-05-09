from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PyQt6.QtGui import QImageReader, QMovie
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

import base64

from modules import base64_encoded_files
from modules.ui_foundation import apply_metroliza_theme, configure_window_size, secondary_label


def _scaled_loading_gif_size(source_size):
    """Return an aspect-preserving presentation size for the loading GIF."""
    target_max_dimension = 168
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
    configure_window_size(loading_dialog, minimum=(460, 220), initial=(520, 260))
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
    loading_label.setMinimumHeight((loading_label.fontMetrics().lineSpacing() * 3) + 8)
    loading_label.setWordWrap(True)

    loading_bar = QProgressBar(loading_dialog)
    loading_bar.setValue(0)
    loading_bar.setMinimumWidth(360)
    loading_bar.setMaximumHeight(20)
    loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout = QVBoxLayout(loading_dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    status_layout = QHBoxLayout()
    status_layout.setSpacing(14)
    status_layout.addWidget(loading_gif_label, alignment=Qt.AlignmentFlag.AlignVCenter)
    status_layout.addWidget(loading_label, stretch=1)
    layout.addLayout(status_layout)
    layout.addWidget(loading_bar)

    cancel_button = QPushButton("Cancel", loading_dialog)
    cancel_button.clicked.connect(on_cancel)
    layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    loading_dialog._loading_gif_buffer = loading_gif_buffer
    return loading_dialog, loading_label, loading_bar, loading_gif
