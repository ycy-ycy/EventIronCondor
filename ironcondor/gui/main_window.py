from pathlib import Path

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import actions, storage
from ..core.numbers import fmt_pct_value
from ..core.calculator import (
    INPUT_NAMES,
    SCENARIOS,
    average_iv_text,
    calculate,
    default_close_date,
    get_normal_iv_decimal,
)
from ..core.timeutils import (
    format_date_text,
    OPEN_DAYS,
    get_current_date_day_hour_minute_for_open,
    get_now,
    get_weekday_name,
)
from ..paths import DATA_DIR, ensure_data_dir
from ..providers import CAPABILITIES, CAPABILITY_LABELS, DataSourceError, source_class
from ..services import MarketData
from .settings_dialog import DataSourceDialog
from .widgets import OutputField, TimeInput, tone_name
from .worker import Task


NOTE = (
    "Notes: IV and yield in %; options expire 16:00 ET on the weekly's day. 1Y = FRED DGS1. "
    "IM / 50% prices map log moves with exp(); P&L % is the return on the debit."
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Earnings Option Spread Calculator")

        self.inputs = {}
        self.outputs = {}
        self.task_buttons = []

        self.theoretical_open_debit = None
        self._loading = False
        self._task = None

        self.settings = storage.load_settings()
        self.market = MarketData.from_settings(self.settings)

        self._build_ui()
        self.apply_inputs(storage.default_inputs())
        self._bind_inputs()

        self.load_cache_on_start()
        self.recalculate()
        self.resize(1220, 845)

    # ------------------------------------------------------------------ widgets

    def make_entry(self, name: str) -> QLineEdit:
        edit = QLineEdit(self)
        self.inputs[name] = edit
        return edit

    def make_fetched_entry(self, name: str) -> QLineEdit:
        """A saved input only a fetch fills: read-only, looks like an output."""
        edit = self.make_entry(name)
        edit.setReadOnly(True)
        edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        edit.setProperty("output", True)
        return edit

    def make_combo(self, name: str, values) -> QComboBox:
        combo = QComboBox(self)
        combo.addItems(values)
        self.inputs[name] = combo
        return combo

    def make_output(self, name: str, tone: str = "neutral", min_chars: int = 8) -> OutputField:
        field = OutputField(default_tone=tone, min_chars=min_chars, parent=self)
        self.outputs[name] = field
        return field

    def make_time_input(self, hour_name: str, minute_name: str) -> TimeInput:
        time_input = TimeInput(self)
        self.inputs[hour_name] = time_input.hour
        self.inputs[minute_name] = time_input.minute
        return time_input

    def make_button(self, text: str, slot, task: bool = False) -> QPushButton:
        button = QPushButton(text, self)
        button.clicked.connect(slot)
        if task:
            self.task_buttons.append(button)
        return button

    @staticmethod
    def row_of(*items) -> QWidget:
        """Horizontal row: text boxes share the width, buttons keep their size, None = spacer."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for item in items:
            if item is None:
                layout.addStretch(1)
            elif isinstance(item, QLineEdit):
                layout.addWidget(item, 1)
            else:
                layout.addWidget(item, 0)
        return container

    @staticmethod
    def header_row(*texts) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for text in texts:
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("role", "header")
            layout.addWidget(label, 1)
        return container

    @staticmethod
    def add_row(grid: QGridLayout, row: int, label: str, widget: QWidget):
        grid.addWidget(QLabel(label), row, 0)
        grid.addWidget(widget, row, 1)

    @staticmethod
    def separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    @staticmethod
    def section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "section")
        return label

    @staticmethod
    def new_panel(title: str):
        box = QGroupBox(title)
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 14, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)
        return box, grid

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        central = QWidget(self)
        root = QGridLayout(central)
        root.setContentsMargins(12, 12, 12, 8)
        root.setHorizontalSpacing(16)
        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 1)
        root.setRowStretch(0, 1)

        left, left_grid = self.new_panel("Open")
        right, right_grid = self.new_panel("Close")
        self._build_left_column(left_grid)
        self._build_right_column(right_grid)

        root.addWidget(left, 0, 0)
        root.addWidget(right, 0, 1)
        root.addWidget(self._build_bottom_bar(), 1, 0, 1, 2)

        self.setCentralWidget(central)

        self.source_label = QLabel()
        self.statusBar().addPermanentWidget(self.source_label)
        self.update_source_label()

    def _build_left_column(self, grid: QGridLayout):
        r = 0

        self.add_row(grid, r, "Ticker name", self.make_entry("ticker"))
        r += 1

        self.add_row(grid, r, "Open date (YYYY-MM-DD)", self.row_of(
            self.make_entry("open_date"),
            self.make_button("Update open", self.update_open_all, task=True),
        ))
        r += 1

        self.add_row(grid, r, "Weekday / time (24h ET)", self.row_of(
            self.make_combo("open_day", OPEN_DAYS),
            self.make_time_input("open_hour", "open_minute"),
            None,
            self.make_button("Now (ET)", self.set_open_now),
        ))
        r += 1

        self.add_row(grid, r, "Current market price ($)", self.row_of(
            self.make_entry("open_market_price"),
            self.make_button("Fetch price", self.fetch_open_price, task=True),
        ))
        r += 1

        # One fetch fills these two rows; both IVs are read at the quote time, so their T runs
        # from it, not from the open time above. The rate comes first: the IV solves use it.
        fetched = []
        for name, sample in (("iv_quote_time", "2026-10-27 16:00"), ("weekly_expiry", "THU 2026-11-26"),
                             ("monthly_expiry", "THU 2026-11-26")):
            edit = self.make_fetched_entry(name)
            edit.setMinimumWidth(edit.fontMetrics().horizontalAdvance(sample) + 14)
            fetched.append(edit)
        self.add_row(grid, r, "IV quote time (ET) / weekly / monthly", self.row_of(
            *fetched,
            self.make_button("Fetch 1Y + IV", self.fetch_open_ivs, task=True),
        ))
        r += 1

        self.add_row(grid, r, "US 1Y (blank = 0) / weekly IV / monthly IV (%)", self.row_of(
            self.make_entry("open_us1y"),
            self.make_entry("weekly_iv"),
            self.make_entry("monthly_iv"),
        ))
        r += 1

        self.add_row(grid, r, "Normal IV / jump (log IM) % / Down / Up", self.row_of(
            self.make_output("normal_iv_pct"),
            self.make_output("implied_move_pct"),
            self.make_output("downside_price", tone="loss"),
            self.make_output("upside_price", tone="profit"),
        ))
        r += 1

        self.add_row(grid, r, "Spread ($)", self.make_entry("spread"))
        r += 1

        self.add_row(grid, r, "Long put $ / log % / Long call $ / log %", self.row_of(
            self.make_entry("long_put_strike"),
            self.make_output("long_put_move_pct"),
            self.make_entry("long_call_strike"),
            self.make_output("long_call_move_pct"),
        ))
        r += 1

        self.add_row(grid, r, "Short put $ / log % / Short call $ / log %", self.row_of(
            self.make_output("short_put_strike"),
            self.make_output("short_put_move_pct"),
            self.make_output("short_call_strike"),
            self.make_output("short_call_move_pct"),
        ))
        r += 1

        self.add_row(grid, r, "Put debit / Call debit ($)", self.row_of(
            self.make_output("put_debit"),
            self.make_output("call_debit"),
        ))
        r += 1

        self.add_row(grid, r, "Total debit / Actual open debit ($)", self.row_of(
            self.make_output("total_debit"),
            self.make_entry("open_debit_override"),
        ))
        r += 1

        self.add_row(grid, r, "BE: Down $ / log % / Up $ / log %", self.row_of(
            self.make_output("open_downside_breakeven_price", tone="loss"),
            self.make_output("open_downside_breakeven_move_pct", tone="loss"),
            self.make_output("open_upside_breakeven_price", tone="profit"),
            self.make_output("open_upside_breakeven_move_pct", tone="profit"),
        ))
        r += 1

        grid.addWidget(self.separator(), r, 0, 1, 2)
        r += 1

        grid.addWidget(self.section_label("Expiration time expectation"), r, 0, 1, 2)
        r += 1

        grid.addWidget(self.header_row("Log move %", "Down price", "Up price"), r, 1)
        r += 1

        self.add_row(grid, r, "Implied move", self.row_of(
            self.make_output("exp_implied_move_pct"),
            self.make_output("exp_implied_move_down_price", tone="loss"),
            self.make_output("exp_implied_move_up_price", tone="profit"),
        ))
        r += 1

        self.add_row(grid, r, "50% prob move", self.row_of(
            self.make_output("exp_prob50_move_pct"),
            self.make_output("exp_prob50_down_price", tone="loss"),
            self.make_output("exp_prob50_up_price", tone="profit"),
        ))
        r += 1

        grid.addWidget(self.header_row("Call prob %", "Put prob %"), r, 1)
        r += 1

        self.add_row(grid, r, "ITM prob: long", self.row_of(
            self.make_output("exp_long_call_itm_prob"),
            self.make_output("exp_long_put_itm_prob"),
        ))
        r += 1

        self.add_row(grid, r, "Expiration BE prob", self.row_of(
            self.make_output("exp_breakeven_call_prob"),
            self.make_output("exp_breakeven_put_prob"),
        ))
        r += 1

        self.add_row(grid, r, "ITM prob: short", self.row_of(
            self.make_output("exp_short_call_itm_prob"),
            self.make_output("exp_short_put_itm_prob"),
        ))
        r += 1

        grid.setRowStretch(r, 1)

    def _build_right_column(self, grid: QGridLayout):
        r = 0

        self.add_row(grid, r, "Expected close date (YYYY-MM-DD)", self.make_entry("close_date"))
        r += 1

        update_row = QWidget()
        update_layout = QHBoxLayout(update_row)
        update_layout.setContentsMargins(0, 0, 0, 0)
        update_layout.addWidget(self.make_button("Update close", self.update_close_all, task=True), 1)
        update_layout.addWidget(self.make_button("Simulate 9:30 (LT IV)", self.simulate_close_930, task=True), 1)
        grid.addWidget(update_row, r, 0, 1, 2)
        r += 1

        self.add_row(grid, r, "Weekday / time (24h ET)", self.row_of(
            self.make_output("close_day", min_chars=5),
            self.make_time_input("close_hour", "close_minute"),
            None,
            self.make_button("Now (ET)", self.set_close_now),
        ))
        # The weekday follows the expected close date; keep its box narrow.
        self.outputs["close_day"].setMaximumWidth(self.outputs["close_day"].minimumWidth() + 10)
        self.outputs["close_day"].setAlignment(Qt.AlignmentFlag.AlignCenter)
        r += 1

        self.add_row(grid, r, "Current market price / log Change %", self.row_of(
            self.make_entry("close_market_price"),
            self.make_output("close_price_change_pct"),
            self.make_button("Fetch price", self.fetch_close_price, task=True),
        ))
        r += 1

        self.add_row(grid, r, "US 1Y yield (%), blank = 0", self.row_of(
            self.make_entry("close_us1y"),
            self.make_button("Fetch 1Y", self.fetch_close_us1y, task=True),
        ))
        r += 1

        self.add_row(grid, r, "ATM mid call IV / ATM mid put IV (%)", self.row_of(
            self.make_entry("close_atm_call_iv"),
            self.make_entry("close_atm_put_iv"),
            self.make_button("Fetch weekly IV", self.fetch_close_iv, task=True),
        ))
        r += 1

        self.add_row(grid, r, "Sim IV (%)", self.row_of(
            self.make_entry("sim_iv"),
            self.make_button("Current IV", self.use_current_iv_for_sim),
            self.make_button("LT IV", self.use_lt_iv_for_sim),
        ))
        r += 1

        self.add_row(grid, r, "Put credit / Call credit ($)", self.row_of(
            self.make_output("put_credit"),
            self.make_output("call_credit"),
        ))
        r += 1

        self.add_row(grid, r, "Total credit ($)", self.make_output("total_credit"))
        r += 1

        self.add_row(grid, r, "P&L $ / P&L %", self.row_of(
            self.make_output("pnl_dollar"),
            self.make_output("pnl_pct"),
        ))
        r += 1

        self.add_row(grid, r, "930 Breakeven downside / log %", self.row_of(
            self.make_output("sim_downside_breakeven_price", tone="loss"),
            self.make_output("sim_downside_breakeven_move_pct", tone="loss"),
        ))
        r += 1

        self.add_row(grid, r, "930 Breakeven upside / log %", self.row_of(
            self.make_output("sim_upside_breakeven_price", tone="profit"),
            self.make_output("sim_upside_breakeven_move_pct", tone="profit"),
        ))
        r += 1

        grid.addWidget(self.separator(), r, 0, 1, 2)
        r += 1

        scenario_header = QWidget()
        header_layout = QHBoxLayout(scenario_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.section_label("Close-day 09:30 ET Scenario P&L"), 1)
        header_layout.addWidget(self.make_button("Simulate", self.plot_pnl_contour, task=True), 0)
        grid.addWidget(scenario_header, r, 0, 1, 2)
        r += 1

        table = QWidget()
        table_grid = QGridLayout(table)
        table_grid.setContentsMargins(0, 0, 0, 0)
        table_grid.setHorizontalSpacing(6)
        table_grid.setVerticalSpacing(4)
        for c in range(5):
            table_grid.setColumnStretch(c, 1)

        for c, text in enumerate(("Scenario", "Stock", "Credit $", "P&L $", "P&L %")):
            label = QLabel(text)
            label.setProperty("role", "header")
            if c > 0:
                label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table_grid.addWidget(label, 0, c)

        for i, (key, label) in enumerate(SCENARIOS, start=1):
            table_grid.addWidget(QLabel(label), i, 0)
            table_grid.addWidget(self.make_output(f"scenario_{key}_price"), i, 1)
            table_grid.addWidget(self.make_output(f"scenario_{key}_credit"), i, 2)
            table_grid.addWidget(self.make_output(f"scenario_{key}_pnl_dollar"), i, 3)
            table_grid.addWidget(self.make_output(f"scenario_{key}_pnl_pct"), i, 4)

        grid.addWidget(table, r, 0, 1, 2)
        r += 1

        grid.setRowStretch(r, 1)

    def _build_bottom_bar(self) -> QWidget:
        bottom = QWidget()
        layout = QHBoxLayout(bottom)
        layout.setContentsMargins(0, 6, 0, 0)

        layout.addWidget(QLabel(NOTE), 1)
        layout.addWidget(self.make_button("Data sources…", self.choose_data_sources))
        layout.addSpacing(12)
        layout.addWidget(self.make_button("Save", self.save_auto_named))
        layout.addWidget(self.make_button("Load", self.load_from_file))
        layout.addWidget(self.make_button("Recalculate", self.recalculate_and_cache))
        layout.addWidget(self.make_button("Clear", self.clear_all_inputs))
        return bottom

    # ------------------------------------------------------------------ inputs

    def _bind_inputs(self):
        for name, widget in self.inputs.items():
            if name == "open_date":
                widget.textChanged.connect(self.on_open_date_change)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.on_input_change)
            else:
                widget.textChanged.connect(self.on_input_change)

    def input_text(self, name: str) -> str:
        widget = self.inputs[name]
        if isinstance(widget, QComboBox):
            return widget.currentText()
        return widget.text()

    def set_input(self, name: str, value: str):
        widget = self.inputs[name]
        if isinstance(widget, QComboBox):
            widget.setCurrentIndex(widget.findText(value))
        else:
            widget.setText(value)

    def snapshot(self) -> dict:
        return {name: self.input_text(name) for name in INPUT_NAMES}

    def apply_inputs(self, values: dict):
        """Set several inputs at once without recalculating after each one."""
        if "open_date" in values and "close_date" not in values:
            # The close is usually the trading day after the open; the user can type another date.
            close_date = default_close_date(values["open_date"])
            if close_date:
                values = dict(values, close_date=close_date)

        self._loading = True
        try:
            for name, value in values.items():
                if name in self.inputs:
                    self.set_input(name, value)
        finally:
            self._loading = False

    def on_input_change(self, *_):
        if self._loading:
            return

        self.recalculate()
        self.write_cache()

    def on_open_date_change(self, open_date: str):
        if self._loading:
            return

        self.apply_inputs({"open_date": open_date})
        self.recalculate_and_cache()

    # ------------------------------------------------------------------ calculation

    def recalculate(self):
        result = calculate(self.snapshot())
        self.theoretical_open_debit = result.theoretical_open_debit

        for name, field in self.outputs.items():
            text = result.text.get(name, "")
            if field.text() != text:
                field.setText(text)
            if name in result.tone:
                field.set_tone(tone_name(result.tone[name]))
            else:
                field.set_tone(field.default_tone)

    def recalculate_and_cache(self):
        self.recalculate()
        self.write_cache()

    def clear_all_inputs(self):
        """Clear every user-entered input field."""
        self.apply_inputs({name: "" for name in INPUT_NAMES})
        self.recalculate_and_cache()

    def set_open_now(self):
        open_date, open_day, hour, minute = get_current_date_day_hour_minute_for_open()
        self.apply_inputs({
            "open_date": open_date,
            "open_day": open_day,
            "open_hour": hour,
            "open_minute": minute,
        })
        self.recalculate_and_cache()

    def set_close_now(self):
        now = get_now()
        values = {
            "close_hour": str(now.hour),
            "close_minute": f"{now.minute:02d}",
        }
        if get_weekday_name(now.date()):
            values["close_date"] = format_date_text(now.date())
        self.apply_inputs(values)
        self.recalculate_and_cache()

    def copy_iv_to_sim(self, call_name: str, put_name: str, label: str):
        """Sim IV = mean of the call/put pair (or whichever one is filled)."""
        try:
            sim_iv = average_iv_text(self.input_text(call_name), self.input_text(put_name))
        except ValueError:
            self.statusBar().showMessage(f"{label} is not a number; nothing applied.")
            return
        if not sim_iv:
            self.statusBar().showMessage(f"{label} is empty; nothing applied.")
            return
        self.apply_inputs({"sim_iv": sim_iv})
        self.recalculate_and_cache()
        self.statusBar().showMessage(f"Sim IV = {label} {sim_iv}%")

    def use_current_iv_for_sim(self):
        self.copy_iv_to_sim("close_atm_call_iv", "close_atm_put_iv", "close ATM IV")

    def use_lt_iv_for_sim(self):
        """Sim IV = the normal IV the open side's IV row solves for."""
        normal_iv = get_normal_iv_decimal(self.snapshot())
        if normal_iv is None:
            self.statusBar().showMessage("LT IV is empty; nothing applied.")
            return
        sim_iv = fmt_pct_value(normal_iv * 100.0)
        self.apply_inputs({"sim_iv": sim_iv})
        self.recalculate_and_cache()
        self.statusBar().showMessage(f"Sim IV = LT IV {sim_iv}%")

    # ------------------------------------------------------------------ background tasks

    def start_task(self, fn, on_success, busy_text: str, error_title: str):
        if self._task is not None:
            return

        task = Task(fn)
        task.signals.succeeded.connect(lambda result: self._finish_task(on_success, result))
        task.signals.failed.connect(lambda message: self._fail_task(error_title, message))
        self._task = task

        for button in self.task_buttons:
            button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage(busy_text)

        QThreadPool.globalInstance().start(task)

    def _end_task(self):
        self._task = None
        for button in self.task_buttons:
            button.setEnabled(True)
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()

    def _finish_task(self, on_success, result):
        self._end_task()
        on_success(result)

    def _fail_task(self, title: str, message: str):
        self._end_task()
        QMessageBox.critical(self, title, message)

    def run_fetch(self, action, busy_text: str):
        snapshot = self.snapshot()
        market = self.market

        def apply(result):
            updates, message = result
            self.apply_inputs(updates)
            self.recalculate_and_cache()
            self.statusBar().showMessage(message)

        self.start_task(lambda: action(snapshot, market), apply, busy_text, "Data error")

    def fetch_open_price(self):
        self.run_fetch(actions.fetch_open_price, "Fetching open price…")

    def fetch_close_price(self):
        self.run_fetch(actions.fetch_close_price, "Fetching close price…")

    def fetch_close_us1y(self):
        self.run_fetch(actions.fetch_close_us1y, "Fetching US 1Y…")

    def fetch_open_ivs(self):
        self.run_fetch(actions.fetch_open_ivs, "Fetching US 1Y and IVs…")

    def fetch_close_iv(self):
        self.run_fetch(actions.fetch_close_iv, "Fetching the weekly's ATM IV…")

    def update_open_all(self):
        self.run_fetch(actions.update_open_all, "Updating open…")

    def update_close_all(self):
        self.run_fetch(actions.update_close_all, "Updating close…")

    def simulate_close_930(self):
        self.run_fetch(actions.simulate_close_930, "Simulating 9:30 with LT IV…")

    def plot_pnl_contour(self):
        try:
            try:
                from ..core.simulation import build_pnl_surface, get_simulation_inputs
                from .plot_window import PnlContourWindow
            except ImportError:
                raise RuntimeError(
                    "Missing dependencies: matplotlib and numpy. Please install them first:\n"
                    "python -m pip install matplotlib numpy"
                )
            sim_inputs = get_simulation_inputs(self.snapshot(), self.theoretical_open_debit)
        except Exception as e:
            QMessageBox.critical(self, "Simulate error", str(e))
            return

        def show(surface):
            try:
                PnlContourWindow(surface).show()
            except Exception as e:
                QMessageBox.critical(self, "Simulate error", str(e))

        self.start_task(lambda: build_pnl_surface(sim_inputs), show, "Computing P&L surface…", "Simulate error")

    # ------------------------------------------------------------------ data sources

    def source_text(self, capability: str) -> str:
        key = self.market.source_keys[capability]
        try:
            return source_class(key).label
        except DataSourceError:
            return f"{key} (unknown)"

    def update_source_label(self):
        self.source_label.setText(
            "Sources — " + " · ".join(
                f"{CAPABILITY_LABELS[capability]}: {self.source_text(capability)}"
                for capability in CAPABILITIES
            )
        )

    def choose_data_sources(self):
        dialog = DataSourceDialog(self.market.source_keys, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.settings["sources"] = dialog.selected_sources()
        try:
            storage.save_settings(self.settings)
        except Exception as e:
            QMessageBox.warning(self, "Data sources", f"Could not save settings:\n{e}")

        self.market = MarketData.from_settings(self.settings)
        self.update_source_label()

    # ------------------------------------------------------------------ files

    def write_cache(self):
        storage.write_cache(self.snapshot())

    def load_cache_on_start(self):
        values = storage.read_cache()
        if values is None:
            return
        self.apply_inputs(values)
        self.write_cache()

    def save_auto_named(self):
        try:
            inputs = self.snapshot()
            path = storage.default_save_path(inputs["ticker"], inputs["open_date"])
            storage.save_inputs(path, inputs)
            self.write_cache()
            QMessageBox.information(self, "Saved", f"Saved to:\n{path}")

        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    def load_from_file(self):
        ensure_data_dir()

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load",
            str(DATA_DIR),
            "JSON files (*.json);;All files (*.*)",
        )

        if not path:
            return

        try:
            values = storage.load_inputs(Path(path))
            self.apply_inputs(values)
            self.recalculate_and_cache()
            QMessageBox.information(self, "Loaded", f"Loaded from:\n{path}")

        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))
