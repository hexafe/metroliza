from PyQt6.QtCore import QSize, QTemporaryFile, Qt
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

import base64

from modules import base64_encoded_files
from modules.ui_foundation import apply_metroliza_theme, configure_window_size, secondary_label


def create_worker_progress_dialog(parent, *, window_title, initial_status_text, on_cancel):
    """Create a standardized progress dialog used by parse/export/csv worker flows."""
    loading_dialog = QDialog(parent, Qt.WindowType.WindowTitleHint)
    loading_dialog.setWindowTitle(window_title)
    loading_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    configure_window_size(loading_dialog, minimum=(420, 210), initial=(460, 260))
    apply_metroliza_theme(loading_dialog)

    loading_gif_label = QLabel(loading_dialog)
    loading_gif_label.setFixedSize(96, 96)
    loading_gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    loading_gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)

    temp_file = QTemporaryFile()
    temp_file.setAutoRemove(False)
    temp_file_name = ""
    if temp_file.open():
        temp_file.write(loading_gif_decoded)
        temp_file.close()
        temp_file_name = temp_file.fileName()

    loading_gif = QMovie(temp_file_name)
    loading_gif.setScaledSize(QSize(96, 96))
    loading_gif_label.setMovie(loading_gif)
    loading_gif.start()

    loading_label = secondary_label(initial_status_text)
    loading_label.setParent(loading_dialog)
    loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    loading_label.setMinimumHeight((loading_label.fontMetrics().lineSpacing() * 3) + 8)

    loading_bar = QProgressBar(loading_dialog)
    loading_bar.setValue(0)
    loading_bar.setMinimumWidth(360)
    loading_bar.setMaximumHeight(20)
    loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout = QVBoxLayout(loading_dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)
    layout.addWidget(loading_gif_label, alignment=Qt.AlignmentFlag.AlignHCenter)
    layout.addWidget(loading_label)
    layout.addWidget(loading_bar)

    cancel_button = QPushButton("Cancel", loading_dialog)
    cancel_button.clicked.connect(on_cancel)
    layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    return loading_dialog, loading_label, loading_bar, loading_gif
