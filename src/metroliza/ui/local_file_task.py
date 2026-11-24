"""Run explicit workspace and result-file operations off the UI thread."""

from PyQt6.QtCore import QThread, pyqtSignal

from metroliza.ui import detached_threads


class LocalFileTask(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation, *args):
        super().__init__()
        self.operation = operation
        self.args = args

    def start_owned(self, owner, finished):
        detached_threads.register(self, defer_quit=True, owner=owner, on_finished=finished)
        self.start()

    def run(self):
        try:
            result = self.operation(*self.args)
        except Exception as exc:
            self.failed.emit(str(exc) or "The file operation could not be completed.")
        else:
            self.succeeded.emit(result)
