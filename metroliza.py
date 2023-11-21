from modules.MainWindow import MainWindow
from PyQt5.QtWidgets import QApplication
import sys
import version_date
import logging
import sys

VERSION_DATE = version_date.VERSION_DATE

if __name__ == "__main__":
    logging.basicConfig(filename=f'metroliza.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    try:
        app = QApplication(sys.argv)
        main_window = MainWindow(VERSION_DATE)
        main_window.show()
        sys.exit(app.exec_())
    except Exception as e:
        logging.exception("An error occured: %s", e)
        sys.exit(1)
