"""Parentless filter loaders survive dialog closure until SQLite is cleaned up."""

from functools import partial

from PyQt6.QtCore import QThread, QTimer, pyqtSignal

from metroliza.reports.filter_values import load_filter_values


_RUNNING_LOADERS = set()


def _retire_loader(loader):
    # finished may precede native/thread-local cleanup. Poll without GUI waits.
    if not loader.wait(0):
        QTimer.singleShot(10, partial(_retire_loader, loader))
        return
    _RUNNING_LOADERS.discard(loader)
    loader.deleteLater()


class FilterValuesLoader(QThread):
    values_ready = pyqtSignal(int, object)
    load_failed = pyqtSignal(int, object)

    def __init__(self, request_id, database, filter_query, specs):
        super().__init__()
        self.request_id = request_id
        self.database = database
        self.filter_query = filter_query
        self.specs = specs
        self.finished.connect(partial(_retire_loader, self))

    def start(self):
        _RUNNING_LOADERS.add(self)
        super().start()

    def run(self):
        try:
            values = load_filter_values(
                self.database, self.filter_query, specs=self.specs,
                cancelled=self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.values_ready.emit(self.request_id, values)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.load_failed.emit(self.request_id, exc)
