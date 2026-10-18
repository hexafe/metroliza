"""Qt orchestration in the app, synchronous notifications in the compute image.

The compute image only calls summary_sheet_fill. It never starts a thread or
an event loop. Keeping the adapter here lets that method share exactly the
application's renderer without loading Qt or providing fake PyQt modules.
"""

from metroliza.shared.compute_worker import is_compute_worker


class _Signal:
    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.setdefault(self.name, _BoundSignal())


class _BoundSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *values):
        for callback in self.callbacks:
            callback(*values)


class _SynchronousOnly:
    @staticmethod
    def processEvents():
        raise RuntimeError("compute_worker_event_loop_forbidden")

    def start(self):
        raise RuntimeError("compute_worker_thread_forbidden")


if is_compute_worker():
    QThread = QCoreApplication = _SynchronousOnly

    def pyqtSignal(*_types):
        return _Signal()
else:
    from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal  # noqa: F401
