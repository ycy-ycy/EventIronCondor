"""Render the README screenshots (docs/main-window.png, docs/simulation.png).

Uses a fixed MSFT example trade, renders offscreen at 2x with Segoe UI, and never touches
your data/_cache.json or settings.json. Run it with the project's environment:

    .venv\\python.exe tools\\render_screenshots.py          (conda-built .venv)
    .venv\\Scripts\\python.exe tools\\render_screenshots.py  (venv-built .venv)
"""

import copy
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"
sys.path.insert(0, str(ROOT))

# Must be set before Qt starts.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
os.environ["QT_SCALE_FACTOR"] = "2"

import ironcondor.storage as storage  # noqa: E402

# Keep the real auto-restore cache and data-source choice out of it.
storage.CACHE_FILE = Path(tempfile.mkdtemp()) / "_cache.json"
storage.ensure_data_dir = lambda: None
storage.load_settings = lambda: copy.deepcopy(storage.DEFAULT_SETTINGS)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ironcondor.core.simulation import build_pnl_surface, get_simulation_inputs  # noqa: E402
from ironcondor.gui.main_window import MainWindow  # noqa: E402
from ironcondor.gui.plot_window import PnlContourWindow  # noqa: E402
from ironcondor.gui.widgets import STYLESHEET  # noqa: E402

EXAMPLE = {
    "ticker": "MSFT",
    "open_date": "2026-10-26",
    "open_day": "MON",
    "open_hour": "14",
    "open_minute": "39",
    "open_market_price": "532.12",
    "open_us1y": "4.41",
    "atm_call_iv": "62.71",
    "atm_put_iv": "62.98",
    "long_term_call_iv": "32.09",
    "long_term_put_iv": "32.09",
    "spread": "20",
    "long_put_strike": "510",
    "long_call_strike": "550",
    "open_debit_override": "",
    "close_day": "TUE",
    "close_hour": "9",
    "close_minute": "30",
    "close_market_price": "531.92",
    "close_us1y": "4.41",
    "close_atm_call_iv": "112.81",
    "close_atm_put_iv": "112.52",
    "sim_iv": "32.09",
}

# Where the Simulate screenshot shows its hover readout.
HOVER_TIME = 14 + 5 / 60
HOVER_PRICE = 542.55


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        pass
    app.setPalette(app.style().standardPalette())
    app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet(STYLESHEET)

    OUT.mkdir(exist_ok=True)

    window = MainWindow()
    window.apply_inputs(EXAMPLE)
    window.recalculate()
    window.resize(1220, 845)
    window.show()
    app.processEvents()
    focused = app.focusWidget()
    if focused is not None:
        focused.clearFocus()  # no blinking text cursor in the screenshot
    app.processEvents()
    window.grab().save(str(OUT / "main-window.png"))

    surface = build_pnl_surface(get_simulation_inputs(window.snapshot(), window.theoretical_open_debit))
    contour = PnlContourWindow(surface)
    contour.show()
    app.processEvents()
    contour.canvas.draw()

    # Same path as moving the mouse onto the plot.
    x, y = contour.ax.transData.transform((HOVER_TIME, HOVER_PRICE))
    contour._on_mouse_move(SimpleNamespace(inaxes=contour.ax, xdata=HOVER_TIME, ydata=HOVER_PRICE, x=x, y=y))
    contour.toolbar.set_message(contour.point_text(HOVER_TIME, HOVER_PRICE))
    contour.canvas.draw()
    app.processEvents()
    contour.grab().save(str(OUT / "simulation.png"))

    for name in ("main-window.png", "simulation.png"):
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
