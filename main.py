from modules import PyQT_GUI
from PyQt5.QtWidgets import QApplication
import sys


if __name__ == "__main__":   
    app = QApplication(sys.argv)
    main_window = PyQT_GUI.MainWindow()

    main_window.show()
    sys.exit(app.exec_())