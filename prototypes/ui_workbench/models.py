"""Native table model, stable identity selection and independent visibility proxy."""

from PyQt6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt


class ReportsModel(QAbstractTableModel):
    headers = (
        "Select",
        "Report / location",
        "Recognition",
        "Destination",
        "Eligibility",
        "Parser",
        "Confidence",
        "Outcome",
    )

    def __init__(self, session):
        super().__init__(session)
        self.session = session
        session.rows_changed.connect(self.reload)
        session.changed.connect(self.refresh)

    def reload(self):
        self.beginResetModel()
        self.endResetModel()

    def refresh(self):
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 7))

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.session.reports)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.session.reports[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row.identity
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return (
                Qt.CheckState.Checked
                if row.identity in self.session.selected
                else Qt.CheckState.Unchecked
            )
        outcome = (
            self.session.results.get(row.identity)
            if self.session.plan
            and self.session.plan.context == self.session.context
            and self.session.plan.review_version == self.session.review_version
            else None
        )
        values = (
            "",
            f"{row.name}\n{row.folder}",
            row.recognition.value,
            row.destination.value,
            "Rejected · refresh review"
            if outcome and outcome.value == "Changed since review"
            else row.eligibility,
            row.parser,
            f"{row.confidence}% · demo",
            outcome.value if outcome else "—",
        )
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{row.name}\n{row.eligibility}\n{row.fingerprint}\nSynthetic fixture; completeness is not a production adapter."
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0:
            row = self.session.reports[index.row()]
            if row.selectable and self.session.review_current and not self.session.busy:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            return self.session.select(
                self.session.reports[index.row()].identity,
                value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked,
            )
        return False


class ReportsProxy(QSortFilterProxyModel):
    def __init__(self, model):
        super().__init__(model)
        self.setSourceModel(model)
        self.query = ""
        self.status = "All reports"
        self.parser = "All parsers"
        self.setDynamicSortFilter(False)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def configure(self, query, status, parser):
        self.query, self.status, self.parser = query.casefold(), status, parser
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, parent):
        row = self.sourceModel().session.reports[source_row]
        if self.query not in f"{row.name} {row.folder}".casefold():
            return False
        if self.parser != "All parsers" and self.parser != row.parser:
            return False
        return {
            "All reports": True,
            "New reports": row.destination.value == "No match",
            "Destination matches": row.destination.value != "No match",
            "Needs attention": not row.selectable,
            "Selected": row.identity in self.sourceModel().session.selected,
        }.get(self.status, True)

    def visible_ids(self):
        rows = self.sourceModel().session.reports
        return {
            rows[self.mapToSource(self.index(i, 0)).row()].identity for i in range(self.rowCount())
        }

    def lessThan(self, left, right):
        session = self.sourceModel().session
        rows = session.reports
        a, b = rows[left.row()], rows[right.row()]
        if left.column() == 0:
            return (a.identity in session.selected, a.identity) < (
                b.identity in session.selected,
                b.identity,
            )
        if left.column() == 7:
            current = (
                session.plan
                and session.plan.context == session.context
                and session.plan.review_version == session.review_version
            )

            def key(row):
                outcome = session.results.get(row.identity) if current else None
                return (outcome.value if outcome else "", row.identity)

            return key(a) < key(b)
        fields = (
            "identity",
            "name",
            "recognition",
            "destination",
            "eligibility",
            "parser",
            "confidence",
            "identity",
        )
        field = fields[left.column()]
        return getattr(a, field) < getattr(b, field)
