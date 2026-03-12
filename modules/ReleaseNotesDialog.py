import re

import VersionDate
from PyQt6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

from modules import ui_theme_tokens


class ReleaseNotesDialog(QDialog):
    def __init__(self, parent, release_notes):
        super().__init__(parent)

        self.setWindowTitle(f"Release Notes - {VersionDate.VERSION_LABEL}")
        if parent is not None and hasattr(parent, "windowIcon"):
            self.setWindowIcon(parent.windowIcon())
        self.setGeometry(100, 100, 680, 460)

        self.release_notes_browser = QTextBrowser()
        self.release_notes_browser.setOpenExternalLinks(True)
        self.release_notes_browser.setReadOnly(True)
        frame_shape = getattr(getattr(self.release_notes_browser, "Shape", None), "NoFrame", 0)
        if hasattr(self.release_notes_browser, "setFrameShape"):
            self.release_notes_browser.setFrameShape(frame_shape)
        self.release_notes_browser.setStyleSheet(
            "QTextBrowser {"
            f" background-color: {ui_theme_tokens.COLOR_BACKGROUND_APP};"
            f" color: {ui_theme_tokens.COLOR_TEXT_PRIMARY};"
            f" border: 1px solid {ui_theme_tokens.COLOR_BORDER_DEFAULT};"
            f" border-radius: {ui_theme_tokens.RADIUS_12}px;"
            f" padding: {ui_theme_tokens.SPACE_12}px;"
            "}"
        )
        document = self.release_notes_browser.document() if hasattr(self.release_notes_browser, "document") else None
        if document is not None and hasattr(document, "setDefaultStyleSheet"):
            document.setDefaultStyleSheet(self._release_notes_document_css())
        self.release_notes_browser.setHtml(self._render_release_history(release_notes))

        if hasattr(self.release_notes_browser, "textCursor") and hasattr(self.release_notes_browser, "moveCursor"):
            text_cursor = self.release_notes_browser.textCursor()
            move_operation = getattr(getattr(text_cursor, "MoveOperation", None), "Start", None)
            if move_operation is not None:
                self.release_notes_browser.moveCursor(move_operation)

        layout = QVBoxLayout()
        layout.setContentsMargins(
            ui_theme_tokens.SPACE_16,
            ui_theme_tokens.SPACE_16,
            ui_theme_tokens.SPACE_16,
            ui_theme_tokens.SPACE_16,
        )
        layout.setSpacing(ui_theme_tokens.SPACE_8)
        layout.addWidget(self.release_notes_browser)
        self.setLayout(layout)

    def _render_release_history(self, raw_release_notes):
        sections = self._parse_release_sections(raw_release_notes)
        if not sections:
            return "<p>No release notes available.</p>"

        cards = []
        for header, items in sections:
            escaped_header = self._escape_html(header)
            item_markup = "".join(f"<li>{self._escape_html(item)}</li>" for item in items)
            cards.append(
                "<section class='release-card'>"
                f"<h2>{escaped_header}</h2>"
                f"<ul>{item_markup}</ul>"
                "</section>"
            )

        return (
            "<div class='release-history'>"
            "<h1>Release History</h1>"
            + "".join(cards)
            + "</div>"
        )

    @staticmethod
    def _parse_release_sections(raw_release_notes):
        normalized = re.sub(r"<br\s*/?>", "\n", raw_release_notes, flags=re.IGNORECASE)
        normalized = re.sub(r"</?b>", "", normalized, flags=re.IGNORECASE)

        lines = [line.strip() for line in normalized.splitlines() if line.strip()]

        sections = []
        current_header = None
        current_items = []

        for line in lines:
            if line.startswith("-"):
                if current_header is None:
                    continue
                bullet_text = line.lstrip("- ").strip()
                if bullet_text:
                    current_items.append(bullet_text)
                continue

            if current_header is not None:
                sections.append((current_header.rstrip(":"), current_items))
            current_header = line
            current_items = []

        if current_header is not None:
            sections.append((current_header.rstrip(":"), current_items))

        return [section for section in sections if section[0]]

    @staticmethod
    def _escape_html(text):
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    @staticmethod
    def _release_notes_document_css():
        return (
            "body {"
            f" font-size: 12px;"
            f" color: {ui_theme_tokens.COLOR_TEXT_PRIMARY};"
            f" background: {ui_theme_tokens.COLOR_BACKGROUND_APP};"
            "}"
            "h1 {"
            f" font-size: 16px;"
            " font-weight: 700;"
            f" margin: 0 0 {ui_theme_tokens.SPACE_12}px 0;"
            "}"
            ".release-card {"
            f" border: 1px solid {ui_theme_tokens.COLOR_BORDER_DEFAULT};"
            f" border-radius: {ui_theme_tokens.RADIUS_12}px;"
            f" background: {ui_theme_tokens.COLOR_BACKGROUND_PANEL};"
            f" padding: {ui_theme_tokens.SPACE_12}px {ui_theme_tokens.SPACE_12}px {ui_theme_tokens.SPACE_8}px {ui_theme_tokens.SPACE_12}px;"
            f" margin: 0 0 {ui_theme_tokens.SPACE_8}px 0;"
            "}"
            "h2 {"
            f" font-size: 14px;"
            " font-weight: 700;"
            f" margin: 0 0 {ui_theme_tokens.SPACE_8}px 0;"
            "}"
            "ul {"
            f" margin: 0 0 {ui_theme_tokens.SPACE_4}px {ui_theme_tokens.SPACE_16}px;"
            " padding: 0;"
            "}"
            "li {"
            f" margin: 0 0 {ui_theme_tokens.SPACE_4}px 0;"
            f" color: {ui_theme_tokens.COLOR_TEXT_SECONDARY};"
            " line-height: 1.35;"
            "}"
        )
