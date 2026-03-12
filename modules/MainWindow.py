import base64
from modules import Base64EncodedFiles
from modules.export_dialog import ExportDialog
from modules.parsing_dialog import ParsingDialog
from modules.modify_db import ModifyDB
from modules.about_window import AboutWindow
from modules.release_notes_dialog import ReleaseNotesDialog
from modules.custom_logger import CustomLogger
from modules.csv_summary_dialog import CSVSummaryDialog
from modules.characteristic_mapping_dialog import CharacteristicMappingDialog
from modules import ui_theme_tokens
from VersionDate import release_notes
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPixmap, QAction
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class TaskCardButton(QPushButton):
    """Clickable task card used on the dashboard."""

    def __init__(self, title, description):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(ui_theme_tokens.SPACE_16, ui_theme_tokens.SPACE_16, ui_theme_tokens.SPACE_16, ui_theme_tokens.SPACE_12)
        card_layout.setSpacing(ui_theme_tokens.SPACE_8)

        title_label = QLabel(title)
        title_label.setStyleSheet(ui_theme_tokens.typography_style("card", ui_theme_tokens.COLOR_TEXT_PRIMARY))
        card_layout.addWidget(title_label)

        description_label = QLabel(description)
        description_label.setWordWrap(False)
        description_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_HELPER))
        card_layout.addWidget(description_label)
        card_layout.addStretch()

        self.setStyleSheet(
            "QPushButton {"
            f" min-height: {ui_theme_tokens.CONTROL_HEIGHT}px;"
            f" padding: {ui_theme_tokens.SPACE_8}px {ui_theme_tokens.SPACE_12}px;"
            f" border: 1px solid {ui_theme_tokens.COLOR_BORDER_DEFAULT};"
            f" border-radius: {ui_theme_tokens.RADIUS_12}px;"
            f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_PANEL};"
            f" color: {ui_theme_tokens.COLOR_TEXT_SECONDARY};"
            " text-align: left;"
            "}"
            "QPushButton:hover {"
            f" border: 1px solid {ui_theme_tokens.COLOR_BORDER_STRONG};"
            f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_PANEL_ELEVATED};"
            "}"
            "QPushButton:pressed {"
            f" border: 1px solid {ui_theme_tokens.COLOR_ACCENT_HOVER};"
            f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_PANEL_MUTED};"
            "}"
            "QPushButton:focus {"
            f" border: 2px solid {ui_theme_tokens.COLOR_FOCUS_RING};"
            " outline: none;"
            f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_PANEL_ELEVATED};"
            "}"
        )


class MainWindow(QMainWindow):
    """A main window class that provides the user interface for the Metroliza application."""

    def __init__(self, version_label, days_until_expiration):
        """Initialize the main window and its components.

        Args:
            VERSION_DATE (str): The version and date of the application.
        """
        super().__init__()

        # Initialize the main window and layout
        if days_until_expiration is None:
            self.setWindowTitle(f"Metroliza [{version_label}]")
        else:
            self.setWindowTitle(f"Metroliza [{version_label}] ({days_until_expiration+1} day{'s' if days_until_expiration+1 > 1 else ''} left)")
        self.setGeometry(100, 100, 1120, 760)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QGridLayout()
        self.central_widget.setLayout(self.layout)
        self.days_until_expiration = days_until_expiration

        # Set the window icon
        self.setWindowIcon(self.decode_icon(Base64EncodedFiles.encoded_icon))

        # Initialize the dialogs and attributes
        self.parsing_dialog = None
        self.modifydb_dialog = None
        self.export_dialog = None
        self.directory = None
        self.db_file = None

        # Initialize and set up dashboard task cards
        self.parse_button = TaskCardButton(
            "Parse Reports",
            "Import report PDFs into the current database.",
        )
        self.modifydb_button = TaskCardButton(
            "Review Data",
            "Inspect and refine stored records.",
        )
        self.export_button = TaskCardButton(
            "Export Analysis",
            "Create filtered workbook outputs.",
        )
        self.csv_summary_button = TaskCardButton(
            "CSV Quick Charts",
            "Generate quick summaries from CSV data.",
        )
        self.map_characteristics_button = TaskCardButton(
            "Match Characteristic Names",
            "Align raw names to shared terms.",
        )

        self.heading_label = QLabel("Metroliza dashboard")
        self.subheading_label = QLabel("Move from report intake to clean, reviewable output.")
        self.status_label = QLabel()
        self.last_export_label = QLabel()
        self.setup_button_tooltips()

        # Set up menu items
        self.setup_menu_actions()

        # Add buttons to the layout and connect signals
        self.setup_buttons_layout()

    def decode_icon(self, encoded_icon):
        """Decode the base64 encoded icon and return an QIcon object.

        Args:
            encoded_icon (str): The base64 encoded icon.

        Returns:
            QIcon: The decoded icon.
        """
        icon_decoded = base64.b64decode(encoded_icon)
        byte_array = QByteArray(icon_decoded)
        pixmap = QPixmap()
        pixmap.loadFromData(byte_array)
        icon = QIcon(pixmap)
        return icon

    def setup_button_tooltips(self):
        """Set up the tooltips for the buttons."""
        self.parse_button.setToolTip("Import PDF reports into the working database.")
        self.modifydb_button.setToolTip("Edit references, part numbers, and headers in the database.")
        self.export_button.setToolTip("Filter and export selected data from the database to Excel.")
        self.csv_summary_button.setToolTip("Generate summary charts from CSV input files.")
        self.map_characteristics_button.setToolTip("Create and manage name match to common name mappings by apply to and reference.")

    def setup_menu_actions(self):
        """Set up the menu actions for the main window."""
        self.about_button = QAction("About", self)
        self.about_button.triggered.connect(self.open_about_window)
        self.release_notes_action = QAction("Release notes", self)
        self.release_notes_action.triggered.connect(self.open_release_notes_dialog)
        self.menuBar().addAction(self.about_button)
        self.menuBar().addAction(self.release_notes_action)

    def setup_buttons_layout(self):
        """Add the buttons to the layout and connect the signals."""
        main_container = QFrame()
        self.central_widget.setStyleSheet(
            f"QWidget {{ background-color: {ui_theme_tokens.COLOR_BACKGROUND_APP}; color: {ui_theme_tokens.COLOR_TEXT_SECONDARY}; }}"
        )
        main_container.setStyleSheet(
            "QFrame {"
            f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_APP};"
            "}"
        )
        main_container_layout = QVBoxLayout(main_container)
        main_container_layout.setContentsMargins(ui_theme_tokens.SPACE_20, ui_theme_tokens.SPACE_20, ui_theme_tokens.SPACE_20, ui_theme_tokens.SPACE_20)
        main_container_layout.setSpacing(ui_theme_tokens.SPACE_20)

        main_container_layout.addWidget(self._build_dashboard_header())
        main_container_layout.addWidget(self._build_dashboard_card_grid())
        main_container_layout.addStretch()

        self.layout.addWidget(main_container, 0, 0)

        self.update_context_status()
        self.parse_button.clicked.connect(self.launch_parsing_dialog)
        self.modifydb_button.clicked.connect(self.launch_modifydb_dialog)
        self.export_button.clicked.connect(self.launch_export_dialog)
        self.csv_summary_button.clicked.connect(self.launch_csv_summary_dialog)
        self.map_characteristics_button.clicked.connect(self.launch_characteristic_mapping_dialog)

    def _build_dashboard_header(self):
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame {"
            f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_PANEL};"
            f" border: 1px solid {ui_theme_tokens.COLOR_BORDER_DEFAULT};"
            f" border-radius: {ui_theme_tokens.RADIUS_12}px;"
            "}"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(ui_theme_tokens.SPACE_20, ui_theme_tokens.SPACE_20, ui_theme_tokens.SPACE_20, ui_theme_tokens.SPACE_16)
        panel_layout.setSpacing(ui_theme_tokens.SPACE_12)
        self.heading_label.setStyleSheet(ui_theme_tokens.typography_style("dashboard_page", ui_theme_tokens.COLOR_TEXT_PRIMARY))
        self.subheading_label.setWordWrap(True)
        self.subheading_label.setStyleSheet(ui_theme_tokens.typography_style("body", ui_theme_tokens.COLOR_TEXT_SECONDARY))

        context_strip = QFrame()
        context_strip.setStyleSheet(
            "QFrame {"
            f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_PANEL_MUTED};"
            f" border: 1px solid {ui_theme_tokens.COLOR_BORDER_MUTED};"
            f" border-radius: {ui_theme_tokens.RADIUS_10}px;"
            "}"
        )
        context_layout = QVBoxLayout(context_strip)
        context_layout.setContentsMargins(ui_theme_tokens.SPACE_12, ui_theme_tokens.SPACE_12, ui_theme_tokens.SPACE_12, ui_theme_tokens.SPACE_12)
        context_layout.setSpacing(ui_theme_tokens.SPACE_8)

        self.status_label.setWordWrap(True)
        self.last_export_label.setWordWrap(True)
        self.status_label.setStyleSheet(ui_theme_tokens.typography_style("body", ui_theme_tokens.COLOR_TEXT_SECONDARY))
        self.last_export_label.setStyleSheet(ui_theme_tokens.typography_style("helper", ui_theme_tokens.COLOR_TEXT_HELPER))

        context_layout.addWidget(self.status_label)
        context_layout.addWidget(self.last_export_label)

        panel_layout.addWidget(self.heading_label)
        panel_layout.addWidget(self.subheading_label)
        panel_layout.addWidget(context_strip)
        return panel

    def _build_dashboard_card_grid(self):
        card_region = QFrame()
        card_region_layout = QVBoxLayout(card_region)
        card_region_layout.setContentsMargins(0, 0, 0, 0)
        card_region_layout.setSpacing(ui_theme_tokens.SPACE_12)

        section_title = QLabel("Workflows")
        section_title.setStyleSheet(ui_theme_tokens.typography_style("section", ui_theme_tokens.COLOR_TEXT_PRIMARY))
        card_region_layout.addWidget(section_title)

        card_grid = QGridLayout()
        card_grid.setContentsMargins(0, 0, 0, 0)
        card_grid.setHorizontalSpacing(ui_theme_tokens.SPACE_16)
        card_grid.setVerticalSpacing(ui_theme_tokens.SPACE_16)

        cards = [
            self.parse_button,
            self.modifydb_button,
            self.export_button,
            self.csv_summary_button,
            self.map_characteristics_button,
        ]
        columns = 2
        for index, card in enumerate(cards):
            row = index // columns
            column = index % columns
            card_grid.addWidget(card, row, column)
        card_grid.setColumnStretch(0, 1)
        card_grid.setColumnStretch(1, 1)

        card_region_layout.addLayout(card_grid)
        return card_region

    def update_context_status(self):
        if self.db_file:
            self.status_label.setText(f"Database: {self.db_file}")
        else:
            self.status_label.setText("Database: Not selected yet")

        self.last_export_label.setText("Last export: Not run yet")

    def launch_parsing_dialog(self):
        """Launch the parsing dialog and close the other dialogs if they are open."""
        try:
            if self.export_dialog and self.export_dialog.isVisible():
                self.export_dialog.close()
                
            if self.modifydb_dialog and self.modifydb_dialog.isVisible():
                self.modifydb_dialog.close()

            if not self.parsing_dialog or not self.parsing_dialog.isVisible():
                self.parsing_dialog = ParsingDialog(self, self.directory, self.db_file)
                self.parsing_dialog.show()
        except Exception as e:
            CustomLogger(e, reraise=False)
            
    def launch_modifydb_dialog(self):
        try:
            if self.export_dialog and self.export_dialog.isVisible():
                self.export_dialog.close()
                
            if self.parsing_dialog and self.parsing_dialog.isVisible():
                self.parsing_dialog.close()

            if not self.modifydb_dialog or not self.modifydb_dialog.isVisible():
                self.modifydb_dialog = ModifyDB(self, self.db_file)
                self.modifydb_dialog.show()

            self.modifydb_dialog.raise_()
            self.modifydb_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def launch_export_dialog(self):
        try:
            if self.parsing_dialog and self.parsing_dialog.isVisible():
                self.parsing_dialog.close()
                
            if self.modifydb_dialog and self.modifydb_dialog.isVisible():
                self.modifydb_dialog.close()

            if not self.export_dialog or not self.export_dialog.isVisible():
                self.export_dialog = ExportDialog(self, self.db_file)
                self.export_dialog.show()

            self.export_dialog.raise_()
            self.export_dialog.activateWindow()
        except Exception as e:
            self.log_and_exit(e)

    def open_about_window(self):
        try:
            about_window = AboutWindow(self, days_until_expiration=self.days_until_expiration)
            about_window.exec()
        except Exception as e:
            self.log_and_exit(e)

    def open_release_notes_dialog(self):
        try:
            release_notes_dialog = ReleaseNotesDialog(self, release_notes)
            release_notes_dialog.exec()
        except Exception as e:
            self.log_and_exit(e)

    def launch_csv_summary_dialog(self):
        try:
            csv_summary_window = CSVSummaryDialog(self)
            csv_summary_window.exec()
            pass
        except Exception as e:
            self.log_and_exit(e)

    def launch_characteristic_mapping_dialog(self):
        try:
            characteristic_mapping_dialog = CharacteristicMappingDialog(self, self.db_file)
            characteristic_mapping_dialog.exec()
        except Exception as e:
            self.log_and_exit(e)

    def set_db_file(self, db_file):
        try:
            self.db_file = db_file
            self.update_context_status()
        except Exception as e:
            self.log_and_exit(e)

    def set_directory(self, directory):
        try:
            self.directory = directory
            self.update_context_status()
        except Exception as e:
            self.log_and_exit(e)

    def log_and_exit(self, exception):
        CustomLogger(exception, reraise=False)
