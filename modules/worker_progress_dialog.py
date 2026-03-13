from PyQt6.QtCore import QSize, QTemporaryFile, Qt
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

import base64

from modules import Base64EncodedFiles, ui_theme_tokens


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
    loading_label.setStyleSheet(ui_theme_tokens.typography_style("body", ui_theme_tokens.COLOR_TEXT_SECONDARY))

    loading_bar = QProgressBar(loading_dialog)
    loading_bar.setValue(0)
    loading_bar.setFixedSize(390, 20)
    loading_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
    loading_bar.setStyleSheet(
        "QProgressBar {"
        f" border: 1px solid {ui_theme_tokens.COLOR_BORDER_DEFAULT};"
        f" border-radius: {ui_theme_tokens.RADIUS_10}px;"
        f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_INPUT};"
        f" color: {ui_theme_tokens.COLOR_TEXT_PRIMARY};"
        " text-align: center;"
        "}"
        "QProgressBar::chunk {"
        f" border-radius: {ui_theme_tokens.RADIUS_10}px;"
        f" background-color: {ui_theme_tokens.COLOR_ACCENT_PRIMARY};"
        "}"
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
    layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    return loading_dialog, loading_label, loading_bar, loading_gif
