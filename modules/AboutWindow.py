from PyQt6.QtCore import QSize, QTemporaryFile, Qt, QUrl
from PyQt6.QtGui import QMovie, QDesktopServices, QCursor
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
from modules import Base64EncodedFiles
import base64
import VersionDate


class ClickableLabel(QLabel):
    def __init__(self, text, link):
        super().__init__(text)
        self.link = link
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def enterEvent(self, event):
        self.setStyleSheet("QLabel { color: blue; text-decoration: underline; }")

    def leaveEvent(self, event):
        self.setStyleSheet("QLabel { color: black; text-decoration: none; }")

    def mousePressEvent(self, event):
        QDesktopServices.openUrl(QUrl(self.link))


class AboutWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Set the window title and layout
        self.setWindowTitle("About")
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Create a QLabel to display the loading GIF
        gif_label = QLabel()
        # gif_label.setFixedSize(200, 200)

        # Load the loading.gif from a file, create a QMovie from it, and set it to the label
        gif_decoded = base64.b64decode(Base64EncodedFiles.encoded_loading_gif)

        # Create temporary file and save encoded gif to it
        temp_file = QTemporaryFile()
        temp_file.setAutoRemove(True)
        temp_file_name = ""
        if temp_file.open():
            temp_file.write(gif_decoded)
            temp_file.close()
            temp_file_name = temp_file.fileName()

        # Create the QMovie using the temporary file name
        self.gif = QMovie(temp_file_name)
        self.gif.setScaledSize(QSize(200, 200))
        gif_label.setMovie(self.gif)
        gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gif.start()
        self.layout.addWidget(gif_label)

        # Add the title label
        title_label = QLabel(f"Metroliza Valeo version <b>{VersionDate.VERSION_DATE}</b>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(title_label)
        
        # Add the clickable label with email
        author_label = ClickableLabel(f"Grzegorz Ozimek (grzegorz.ozimek@valeo.com)", "mailto:grzegorz.ozimek@valeo.com")
        author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        author_label.setOpenExternalLinks(True)
        self.layout.addWidget(author_label)
