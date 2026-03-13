from PyQt6.QtCore import QSize, QTemporaryFile, Qt
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

import base64

from modules import Base64EncodedFiles, ui_theme_tokens


def set_worker_progress_dialog_cancel_state(loading_dialog, *, enabled, label_text=None):
    """Update standardized cancel-button state for worker progress dialogs."""
    cancel_button = getattr(loading_dialog, "cancel_button", None)
    if cancel_button is None:
        return
    cancel_button.setEnabled(bool(enabled))
    if label_text is not None:
        cancel_button.setText(label_text)


def create_worker_progress_dialog(parent, *, window_title, initial_status_text, on_cancel):
    """Create a standardized progress dialog used by parse/export/csv worker flows."""
    loading_dialog = QDialog(parent, Qt.WindowType.WindowTitleHint)
    loading_dialog.setWindowTitle(window_title)
    loading_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    loading_dialog.setFixedSize(420, 360)
    loading_dialog.setStyleSheet(ui_theme_tokens.dialog_shell_style())

    loading_gif_label = QLabel(loading_dialog)
    loading_gif_label.setFixedSize(200, 200)
    loading_gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    loading_gif_decoded = base64.b64decode(Base64EncodedFiles.encoded_loading_gif)

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
    loading_label.setFixedWidth(390)
    loading_label.setMinimumHeight((loading_label.fontMetrics().lineSpacing() * 3) + 8)
    loading_label.setStyleSheet(ui_theme_tokens.typography_style("body", ui_theme_tokens.COLOR_TEXT_PRIMARY))

    loading_bar = QProgressBar(loading_dialog)
    loading_bar.setValue(0)
    loading_bar.setFixedSize(390, 20)
    loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
    loading_bar.setStyleSheet(ui_theme_tokens.progress_bar_style())

    loading_dialog.setStyleSheet(
        ui_theme_tokens.dialog_shell_style()
        + ui_theme_tokens.modal_surface_style('QDialog')
    )

    layout = QVBoxLayout(loading_dialog)
    layout.setContentsMargins(ui_theme_tokens.SPACE_12, ui_theme_tokens.SPACE_16, ui_theme_tokens.SPACE_12, ui_theme_tokens.SPACE_16)
    layout.setSpacing(ui_theme_tokens.SPACE_12)
    layout.addWidget(loading_gif_label, alignment=Qt.AlignmentFlag.AlignHCenter)
    layout.addWidget(loading_label, alignment=Qt.AlignmentFlag.AlignHCenter)
    layout.addWidget(loading_bar, alignment=Qt.AlignmentFlag.AlignHCenter)

    cancel_button = QPushButton("Cancel", loading_dialog)
    cancel_button.setStyleSheet(ui_theme_tokens.button_style("secondary"))
    cancel_button.clicked.connect(on_cancel)
    loading_dialog.cancel_button = cancel_button
    layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    return loading_dialog, loading_label, loading_bar, loading_gif
