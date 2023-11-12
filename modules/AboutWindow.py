from PyQt5.QtCore import QSize, QTemporaryFile, Qt, QUrl
from PyQt5.QtGui import QMovie, QDesktopServices, QCursor
from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout
from modules import base64_encoded_files
import base64
import version_date


class ClickableLabel(QLabel):
    def __init__(self, text, link):
        super().__init__(text)
        self.link = link
        self.setCursor(QCursor(Qt.PointingHandCursor))

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
        self.layout.setAlignment(Qt.AlignCenter)

        # Create a QLabel to display the loading GIF
        gif_label = QLabel()
        gif_label.setFixedSize(200, 200)
        gif_label.setAlignment(Qt.AlignCenter)

        # Load the loading.gif from a file, create a QMovie from it, and set it to the label
        gif_decoded = base64.b64decode(base64_encoded_files.encoded_loading_gif)

        # Create temporary file and save encoded loading gif to it
        temp_file = QTemporaryFile()
        temp_file.setAutoRemove(False)
        temp_file_name = ""
        if temp_file.open():
            temp_file.write(gif_decoded)
            temp_file.close()
            temp_file_name = temp_file.fileName()

        # Create the QMovie using the temporary file name
        self.gif = QMovie(temp_file_name)
        self.gif.setScaledSize(QSize(200, 200))
        gif_label.setMovie(self.gif)
        gif_label.setAlignment(Qt.AlignCenter)
        self.gif.start()
        self.layout.addWidget(gif_label)

        # Add the text fields
        text_field_label1 = QLabel(f"Metroliza version <b>{version_date.VERSION_DATE}</b>")
        text_field_label1.setAlignment(Qt.AlignHCenter)
        self.layout.addWidget(text_field_label1)
        
        text_field_label2 = QLabel(f"Grzegorz Ozimek")
        text_field_label2.setAlignment(Qt.AlignHCenter)
        self.layout.addWidget(text_field_label2)

        # Add the text with a link to www.google.com
        link_label = ClickableLabel("Github: https://www.github.com/hexafe/", "https://www.github.com/hexafe/")
        link_label.setOpenExternalLinks(True)
        link_label.setAlignment(Qt.AlignHCenter)
        self.layout.addWidget(link_label)

        # # Add the mailto link
        # mailto_label = ClickableLabel("Send email", "mailto:asd@asd.asd")
        # mailto_label.setOpenExternalLinks(True)
        # self.layout.addWidget(mailto_label)
