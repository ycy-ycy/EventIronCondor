from PyQt6.QtCore import QObject, QRunnable, pyqtSignal


class TaskSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)


class Task(QRunnable):
    """Run a plain function on the thread pool and report back through Qt signals.

    The caller must keep a reference to the Task until a signal arrives, otherwise the
    signals object can be garbage-collected before the queued signal is delivered.
    """

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()

    def run(self):
        try:
            result = self.fn()
        except Exception as exc:
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.succeeded.emit(result)
