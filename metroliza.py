from modules.MainWindow import MainWindow
from modules.CustomLogger import CustomLogger
from modules.Base64EncodedFiles import public_key_b64
from modules.LicenseKeyManager import LicenseKeyManager
import VersionDate
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from datetime import datetime
import sys
import logging
import base64

VERSION_DATE = VersionDate.VERSION_DATE

def log_and_exit(exception):
    """Handles logging exceptions using CustomLogger."""
    CustomLogger(exception)

def show_invalid_license_message(title, message, hardware_id):
    dialog = QDialog()
    dialog.setWindowTitle(title)

    # Create layouts
    main_layout = QVBoxLayout()
    message_layout = QVBoxLayout()

    # Message label
    message_label = QLabel(message)
    message_label.setWordWrap(True)
    message_layout.addWidget(message_label)

    # Hardware ID label and field
    hardware_id_layout = QHBoxLayout()
    hardware_id_label = QLabel("Hardware ID:")
    hardware_id_field = QLineEdit(hardware_id)
    hardware_id_field.setReadOnly(True)
    hardware_id_layout.addWidget(hardware_id_label)
    hardware_id_layout.addWidget(hardware_id_field)

    # OK button
    ok_button = QPushButton("OK")
    ok_button.clicked.connect(dialog.accept)

    # Connect rejected signal to reject the dialog
    dialog.rejected.connect(dialog.reject)

    # Add layouts to main layout
    main_layout.addLayout(message_layout)
    main_layout.addLayout(hardware_id_layout)
    main_layout.addWidget(ok_button)

    # Set main layout for dialog
    dialog.setLayout(main_layout)

    # Show dialog and return result
    dialog_result = dialog.exec()
    return dialog_result
    
def verify_license():   
    # Decode public key for signature verification
    # public_key = LicenseKeyManager().read_public_key_file()
    public_key = base64.b64decode(public_key_b64)
    public_key = serialization.load_der_public_key(public_key, backend=default_backend())
    license_key = LicenseKeyManager().read_license_key_file()
    hardware_id = LicenseKeyManager().generate_hardware_id()
    
    # Validate the license key
    if license_key and public_key:
        if LicenseKeyManager().validate_license_key(license_key, hardware_id, public_key):
            return True
        else:
            return False
    else:
        return False

def get_days_until_expiration(license_key):
    """
    Calculate the number of days left until the expiration date.

    Args:
        license_key (str): The license key.

    Returns:
        int: The number of days until expiration.
    """
    expiration_date_str = LicenseKeyManager.get_expiration_date_from_license_key(license_key)
    expiration_date = datetime.strptime(expiration_date_str, "%Y-%m-%d %H:%M:%S")
    current_date = datetime.now()
    days_until_expiration = (expiration_date - current_date).days
    return days_until_expiration

if __name__ == "__main__":
    # Setup logging configuration
    logging.basicConfig(filename='metroliza.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

    try:
        app = QApplication(sys.argv)
        hardware_id = LicenseKeyManager().generate_hardware_id()
        if verify_license():
            # Read expiration date from license key
            license_key = LicenseKeyManager().read_license_key_file()
            days_until_expiration = get_days_until_expiration(license_key)
            
            # Initialize MainWindow with the version date
            main_window = MainWindow(VersionDate.VERSION_DATE, days_until_expiration)
            main_window.show()
            sys.exit(app.exec())
        else:
            show_invalid_license_message("Invalid or no license key found", "To request license key send the hardware id to the author", hardware_id)
            sys.exit()
    except Exception as e:
        log_and_exit(e)
