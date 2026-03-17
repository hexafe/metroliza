import base64
from dataclasses import dataclass
from datetime import datetime

from modules.base64_encoded_files import encoded_icon, public_key_b64


@dataclass(frozen=True)
class LicenseValidationResult:
    is_valid: bool
    days_until_expiration: int | None


def decode_icon(encoded_icon_payload: str):
    """Decode the base64 encoded icon and return a QIcon object."""
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtGui import QIcon, QPixmap

    icon_decoded = base64.b64decode(encoded_icon_payload)
    byte_array = QByteArray(icon_decoded)
    pixmap = QPixmap()
    pixmap.loadFromData(byte_array)
    return QIcon(pixmap)


def show_invalid_license_message(title: str, message: str, hardware_id: str) -> int:
    """Display a blocking invalid license dialog and return the dialog result."""
    from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

    dialog = QDialog()
    dialog.setWindowTitle(title)
    dialog.setWindowIcon(decode_icon(encoded_icon))

    main_layout = QVBoxLayout()
    message_layout = QVBoxLayout()

    message_label = QLabel(message)
    message_label.setWordWrap(True)
    message_layout.addWidget(message_label)

    hardware_id_layout = QHBoxLayout()
    hardware_id_label = QLabel("Hardware ID:")
    hardware_id_field = QLineEdit(hardware_id)
    hardware_id_field.setReadOnly(True)
    hardware_id_layout.addWidget(hardware_id_label)
    hardware_id_layout.addWidget(hardware_id_field)

    ok_button = QPushButton("OK")
    ok_button.clicked.connect(dialog.accept)
    dialog.rejected.connect(dialog.reject)

    main_layout.addLayout(message_layout)
    main_layout.addLayout(hardware_id_layout)
    main_layout.addWidget(ok_button)
    dialog.setLayout(main_layout)

    return dialog.exec()


def get_days_until_expiration(license_key: str | None) -> int:
    """Calculate number of days left from the encoded license expiration date."""
    from modules.license_key_manager import LicenseKeyManager

    if not license_key:
        return 0

    expiration_date_str = LicenseKeyManager.get_expiration_date_from_license_key(license_key)
    if not expiration_date_str:
        return 0

    try:
        expiration_date = datetime.strptime(expiration_date_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0

    return (expiration_date - datetime.now()).days


def verify_license() -> bool:
    """Verify license key against embedded public key and local hardware id."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    from modules.license_key_manager import LicenseKeyManager

    try:
        public_key = base64.b64decode(public_key_b64)
        public_key = serialization.load_der_public_key(public_key, backend=default_backend())
        license_key = LicenseKeyManager.read_license_key_file()
        hardware_id = LicenseKeyManager.generate_hardware_id()

        if not license_key or not public_key:
            return False

        return LicenseKeyManager.validate_license_key(license_key, hardware_id, public_key)
    except Exception:
        return False


def validate_license_bootstrap(license_verification_enabled: bool) -> LicenseValidationResult:
    """Evaluate license bootstrap requirements and return launch metadata."""
    if not license_verification_enabled:
        return LicenseValidationResult(is_valid=True, days_until_expiration=None)

    if not verify_license():
        return LicenseValidationResult(is_valid=False, days_until_expiration=None)

    from modules.license_key_manager import LicenseKeyManager

    license_key = LicenseKeyManager.read_license_key_file()
    return LicenseValidationResult(
        is_valid=True,
        days_until_expiration=get_days_until_expiration(license_key),
    )
