from modules.main_window import MainWindow
# from modules.PyQT_GUI import MainWindow
from PyQt5.QtWidgets import QApplication
import sys

VERSION_DATE = "230610.1830"

if __name__ == "__main__":   
    app = QApplication(sys.argv)
    main_window = MainWindow(VERSION_DATE)
    main_window.show()
    sys.exit(app.exec_())
