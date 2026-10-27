"""Render the README screenshots (docs/main-window.png, docs/simulation.png).

Uses a real CRWV example trade, renders offscreen at 2x with Segoe UI, and never touches
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

# A real trade (CRWV earnings, May 2026): opened Thu 15:55 for a 0.73 debit, closed Fri
# ~10:30 at 114.51 for a 0.95 credit. The close-side IV was not recorded, so the close is
# priced with the LT IV and the Close ATM IV boxes stay empty.
EXAMPLE = {
    "ticker": "CRWV",
    "open_date": "2026-05-07",
    "open_day": "THU",
    "open_hour": "15",
    "open_minute": "55",
    "open_market_price": "127.92",
    "open_us1y": "3.73",
    "atm_call_iv": "282.03",
    "atm_put_iv": "277.50",
    "long_term_call_iv": "82.86",
    "long_term_put_iv": "82.86",
    "spread": "1",
    "long_put_strike": "122",
    "long_call_strike": "134",
    "open_debit_override": "0.73",
    "close_date": "2026-05-08",
    "close_hour": "10",
    "close_minute": "30",
    "close_market_price": "114.51",
    "close_us1y": "3.73",
    "close_atm_call_iv": "",
    "close_atm_put_iv": "",
    "sim_iv": "82.86",
}

# Where the Simulate screenshot shows its hover readout: the actual exit.
HOVER_TIME = 10.5
HOVER_PRICE = 114.51


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
