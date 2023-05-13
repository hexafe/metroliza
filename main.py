from modules import PyQT_GUI, base64_encoded_files
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtCore import QByteArray
import base64
import sys


if __name__ == "__main__":   
    app = QApplication(sys.argv)
    main_window = PyQT_GUI.MainWindow()
    
    icon_decoded = base64.b64decode(base64_encoded_files.encoded_icon)
    byte_array = QByteArray(icon_decoded)
    pixmap = QPixmap()
    pixmap.loadFromData(byte_array)
    icon = QIcon(pixmap)
    main_window.setWindowIcon(icon)

    main_window.show()
    sys.exit(app.exec_())