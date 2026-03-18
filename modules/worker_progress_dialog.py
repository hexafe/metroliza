from PyQt6.QtCore import QSize, QTemporaryFile, Qt
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

import base64

from modules import base64_encoded_files


def create_worker_progress_dialog(parent, *, window_title, initial_status_text, on_cancel):
    """Create a standardized progress dialog used by parse/export/csv worker flows."""
    loading_dialog = QDialog(parent, Qt.WindowType.WindowTitleHint)
    loading_dialog.setWindowTitle(window_title)
    loading_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    loading_dialog.setFixedSize(400, 350)

    loading_gif_label = QLabel(loading_dialog)
    loading_gif_label.setFixedSize(200, 200)
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
    loading_gif.setScaledSize(QSize(200, 200))
    loading_gif_label.setMovie(loading_gif)
    loading_gif.start()

    loading_label = QLabel(initial_status_text, loading_dialog)
    loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    loading_label.setWordWrap(True)
    loading_label.setFixedWidth(380)
    loading_label.setMinimumHeight((loading_label.fontMetrics().lineSpacing() * 3) + 8)

    loading_bar = QProgressBar(loading_dialog)
    loading_bar.setValue(0)
    loading_bar.setFixedSize(380, 20)
    loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout = QVBoxLayout(loading_dialog)
    layout.setContentsMargins(10, 12, 10, 12)
    layout.setSpacing(8)
    layout.addWidget(loading_gif_label, alignment=Qt.AlignmentFlag.AlignHCenter)
    layout.addWidget(loading_label, alignment=Qt.AlignmentFlag.AlignHCenter)
    layout.addWidget(loading_bar, alignment=Qt.AlignmentFlag.AlignHCenter)

    cancel_button = QPushButton("Cancel", loading_dialog)
    cancel_button.clicked.connect(on_cancel)
    layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    return loading_dialog, loading_label, loading_bar, loading_gif
