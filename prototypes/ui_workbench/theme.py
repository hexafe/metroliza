"""Local semantic tokens; intentionally independent of production startup."""

from PyQt6.QtGui import QColor, QFont, QPalette


TOKENS = {
    "dark": dict(bg="#111d26", surface="#182731", soft="#1c2d39", line="#344b58",
                 text="#e4ecf1", muted="#acbfcc", accent="#6ccec0", onaccent="#102b29",
                 focus="#a7c6ff", selected="#29445e", nav="#0d1922"),
    "light": dict(bg="#f3f5f8", surface="#ffffff", soft="#eaf0f4", line="#c5d1da",
                  text="#182939", muted="#526576", accent="#176b68", onaccent="#ffffff",
                  focus="#285bab", selected="#dae8fa", nav="#e2ebef"),
}


def apply_theme(app, mode):
    t = TOKENS[mode]
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 10))
    palette = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
                      (QPalette.ColorRole.Base, "surface"), (QPalette.ColorRole.AlternateBase, "soft"),
                      (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "surface"),
                      (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "selected"),
                      (QPalette.ColorRole.HighlightedText, "text"), (QPalette.ColorRole.ToolTipBase, "surface"),
                      (QPalette.ColorRole.ToolTipText, "text")):
        palette.setColor(role, QColor(t[key]))
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget { color: %(text)s; }
        QMainWindow, QDialog { background: %(bg)s; }
        QLabel#title { font-size: 26px; font-weight: 700; }
        QLabel#section { font-size: 16px; font-weight: 600; }
        QLabel#muted { color: %(muted)s; }
        QFrame#surface { background: %(surface)s; border: 1px solid %(line)s; border-radius: 7px; }
        QFrame#sidebar { background: %(nav)s; }
        QPushButton, QToolButton, QComboBox, QLineEdit { border: 1px solid %(line)s; border-radius: 5px;
            background: %(surface)s; padding: 7px 9px; min-height: 18px; }
        QPushButton:hover, QToolButton:hover { background: %(soft)s; }
        QPushButton[primary="true"] { background: %(accent)s; color: %(onaccent)s; font-weight: 600; }
        QPushButton:disabled { color: %(muted)s; background: %(soft)s; }
        QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus,
        QCheckBox:focus, QTableView:focus, QListWidget:focus { border: 2px solid %(focus)s; }
        QCheckBox { spacing: 8px; padding: 4px; }
        QTableView { background: %(surface)s; alternate-background-color: %(soft)s;
            border: 1px solid %(line)s; gridline-color: %(line)s; selection-background-color: %(selected)s; }
        QHeaderView::section { background: %(soft)s; color: %(muted)s; padding: 9px 5px; border: 0;
            border-bottom: 1px solid %(line)s; font-size: 11px; font-weight: 600; }
        QListWidget { background: transparent; border: 0; }
        QListWidget::item { padding: 11px 8px; margin: 2px; border-radius: 4px; }
        QListWidget::item:selected { background: %(selected)s; color: %(text)s; }
        QProgressBar { border: 1px solid %(line)s; border-radius: 4px; background: %(soft)s; text-align: center; }
        QProgressBar::chunk { background: %(accent)s; }
        QTextBrowser { background: %(surface)s; border: 0; padding: 8px; }
        QSplitter::handle { background: %(bg)s; width: 10px; }
        QTabWidget::pane { border: 0; }
        QTabBar::tab { padding: 10px 16px; background: %(surface)s; border-bottom: 2px solid %(line)s; }
        QTabBar::tab:selected { border-bottom-color: %(accent)s; }
    """ % t)
