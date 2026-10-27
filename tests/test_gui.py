"""Main window and Simulate plot, rendered offscreen."""

import copy
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton
except Exception:  # PyQt6 missing
    QApplication = None

from ironcondor import storage

from tests.helpers import CRWV_V21_FILE, MSFT_INPUTS

CJK = re.compile(r"[　-〿一-鿿＀-￯]")
_saved = {}
_app = None


def setUpModule():
    global _app
    if QApplication is None:
        raise unittest.SkipTest("PyQt6 is not installed")
    # Keep the real cache and settings out of the tests.
    _saved.update(cache=storage.CACHE_FILE, settings=storage.load_settings, ensure=storage.ensure_data_dir)
    storage.CACHE_FILE = Path(tempfile.mkdtemp()) / "_cache.json"
    storage.load_settings = lambda: copy.deepcopy(storage.DEFAULT_SETTINGS)
    storage.ensure_data_dir = lambda: None
    _app = QApplication.instance() or QApplication([])


def tearDownModule():
    if _saved:
        storage.CACHE_FILE = _saved["cache"]
        storage.load_settings = _saved["settings"]
        storage.ensure_data_dir = _saved["ensure"]


class MainWindowTest(unittest.TestCase):
    def setUp(self):
        from ironcondor.gui.main_window import MainWindow
        self.window = MainWindow()
        self.window.apply_inputs(MSFT_INPUTS)
        self.window.recalculate()

    def tearDown(self):
        self.window.close()

    def button(self, text):
        return next(b for b in self.window.findChildren(QPushButton) if b.text() == text)

    def test_shows_the_calculated_values(self):
        self.assertEqual(self.window.outputs["total_debit"].text(), "7.9872")
        self.assertEqual(self.window.outputs["pnl_pct"].text(), "(79.29%)")
        self.assertEqual(self.window.outputs["close_day"].text(), "TUE")
        self.assertEqual(self.window.outputs["pnl_pct"]._tone, "loss")

    def test_old_save_file_loads(self):
        self.window.apply_inputs(storage.inputs_from_saved(CRWV_V21_FILE))
        self.window.recalculate()
        self.assertEqual(self.window.outputs["pnl_pct"].text(), "34.22%")

    def test_open_date_moves_the_close_date(self):
        self.window.inputs["open_date"].setText("2026-10-28")
        self.assertEqual(self.window.input_text("close_date"), "2026-10-29")
        self.assertEqual(self.window.outputs["close_day"].text(), "THU")

    def test_unusable_close_date(self):
        self.window.inputs["close_date"].setText("2026-11-02")
        self.assertEqual(self.window.outputs["close_day"].text(), "n/a")
        self.assertEqual(self.window.outputs["total_credit"].text(), "")

    def test_sim_iv_buttons(self):
        self.button("Current IV").click()
        self.assertEqual(self.window.input_text("sim_iv"), "112.665")
        self.button("LT IV").click()
        self.assertEqual(self.window.input_text("sim_iv"), "32.09")
        self.assertEqual(self.window.outputs["total_credit"].text(), "1.6541")

    def test_no_chinese_text(self):
        texts = [w.text() for w in self.window.findChildren(QLabel)]
        texts += [b.text() for b in self.window.findChildren(QPushButton)]
        texts += [g.title() for g in self.window.findChildren(QGroupBox)]
        self.assertEqual([t for t in texts if CJK.search(t)], [])


class PlotWindowTest(unittest.TestCase):
    def test_contour_window(self):
        from ironcondor.core.calculator import calculate
        from ironcondor.core.simulation import build_pnl_surface, get_simulation_inputs
        from ironcondor.gui.plot_window import PnlContourWindow, PnlSliceWindow

        result = calculate(MSFT_INPUTS)
        surface = build_pnl_surface(get_simulation_inputs(MSFT_INPUTS, result.theoretical_open_debit))
        contour = PnlContourWindow(surface)
        self.addCleanup(contour.close)
        self.assertIn("log IM 5.70%", contour.ax.get_title())
        self.assertIn("Sim IV: 32.09%", contour.ax.get_title())
        self.assertEqual(contour.ax.get_xlabel(), "Time on TUE 2026-10-27 (ET)")
        self.assertIn("P&L%=", contour.point_text(10.5, 530.0))

        slices = PnlSliceWindow(contour, 10.5, 530.0)
        self.addCleanup(slices.close)
        self.assertIn("10:30", slices.figure.get_suptitle())


if __name__ == "__main__":
    unittest.main()
