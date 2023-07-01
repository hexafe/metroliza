from modules.MainWindow import MainWindow
from PyQt5.QtWidgets import QApplication
import sys
import version_date

VERSION_DATE = version_date.VERSION_DATE

if __name__ == "__main__":   
    app = QApplication(sys.argv)
    main_window = MainWindow(VERSION_DATE)
    main_window.show()
    sys.exit(app.exec_())
