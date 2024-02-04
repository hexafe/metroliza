from modules.MainWindow import MainWindow
from modules.CustomLogger import CustomLogger
import VersionDate
from PyQt6.QtWidgets import QApplication
import sys
import logging

VERSION_DATE = VersionDate.VERSION_DATE

def log_and_exit(exception):
    """Handles logging exceptions using CustomLogger."""
    CustomLogger(exception)

if __name__ == "__main__":
    # Setup logging configuration
    logging.basicConfig(filename='metroliza.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

    try:
        app = QApplication(sys.argv)

        # Initialize MainWindow with the version date
        main_window = MainWindow(VERSION_DATE)
        main_window.show()

        sys.exit(app.exec())
    except Exception as e:
        log_and_exit(e)
