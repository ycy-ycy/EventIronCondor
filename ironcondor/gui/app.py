import sys
import traceback

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from .main_window import MainWindow
from .widgets import STYLESHEET


def _install_excepthook():
    # PyQt aborts the process on an exception escaping a slot unless a hook is set.
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        if sys.__stderr__ is not None:  # None under pythonw
            sys.__stderr__.write(text)
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "Unexpected error", f"{exc_type.__name__}: {exc}")

    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Earnings Option Spread Calculator")

    # Profit/loss colors are tuned for a light background; keep the light scheme
    # even when Windows is in dark mode.
    app.setStyle("Fusion")
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        pass
    app.setPalette(app.style().standardPalette())
    app.setStyleSheet(STYLESHEET)

    _install_excepthook()

    window = MainWindow()
    window.show()
    return app.exec()
