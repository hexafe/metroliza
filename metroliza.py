from modules.MainWindow import MainWindow
from PyQt5.QtWidgets import QApplication, QMessageBox
import sys
import version_date
import logging
import sys

VERSION_DATE = version_date.VERSION_DATE

def log_and_exit(self, exception):
        logging.exception("An error occured: %s", exception)
        QMessageBox.information(None, "Error", "An error occured.\nPlease check log file for more informations.\n(or just contact the author :P)")
        raise

if __name__ == "__main__":
    logging.basicConfig(filename=f'metroliza.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    try:
        app = QApplication(sys.argv)
        main_window = MainWindow(VERSION_DATE)
        main_window.show()
        sys.exit(app.exec_())
    except Exception as e:
        log_and_exit(e)
