"""
QThread-based worker for long-running backend operations.

Usage:
    def my_func(progress_cb):
        progress_cb(10, "Loading mesh...")
        result = do_work()
        progress_cb(100, "Done")
        return result

    worker = Worker(my_func)
    worker.progress.connect(on_progress)   # (int, str)
    worker.finished.connect(on_finished)   # (object)
    worker.error.connect(on_error)         # (str)
    worker.start()
"""
from __future__ import annotations
from typing import Callable, Any

from PyQt6.QtCore import QThread, pyqtSignal


class Worker(QThread):
    progress = pyqtSignal(int, str)   # percent, message
    finished = pyqtSignal(object)     # result object
    error    = pyqtSignal(str)        # error message string

    def __init__(self, func: Callable, *args, **kwargs):
        super().__init__()
        self._func   = func
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        def progress_cb(pct: int, msg: str = ""):
            self.progress.emit(pct, msg)

        try:
            result = self._func(progress_cb, *self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as exc:
            import traceback
            self.error.emit(traceback.format_exc())
