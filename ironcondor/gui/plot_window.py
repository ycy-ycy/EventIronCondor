"""Simulate: T+1 P&L % contour window and the click-through slice window."""

import math

import matplotlib.colors as mcolors
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from ..core.simulation import TIME_END, TIME_START, pnl_pct_at_time_and_price


XTICKS = [9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5, 16.0]
XTICKLABELS = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"]

# Plot windows have no Qt parent (they are independent top-level windows, like the
# old pyplot figures), so keep them alive here until they are closed.
_OPEN_WINDOWS = set()


def strike_line_specs(surface: dict):
    sim_inputs = surface["sim_inputs"]
    return [
        (sim_inputs["short_put"], "Short put", "#303030", (0, (4, 3)), 0.55),
        (sim_inputs["long_put"], "Long put", "#303030", (0, (4, 3)), 0.55),
        (sim_inputs["long_call"], "Long call", "#303030", (0, (4, 3)), 0.55),
        (sim_inputs["short_call"], "Short call", "#303030", (0, (4, 3)), 0.55),
        (surface["prob50_down"], "-50% Prob", "#6a5acd", (0, (1, 4)), 0.55),
        (surface["prob50_up"], "+50% Prob", "#6a5acd", (0, (1, 4)), 0.55),
        (surface["implied_move_down"], "-1x IM", "#1f4e79", (0, (2, 3)), 0.65),
        (surface["implied_move_up"], "+1x IM", "#1f4e79", (0, (2, 3)), 0.65),
    ]


def format_hour(hour_value: float) -> str:
    hour_value = min(max(float(hour_value), TIME_START), TIME_END)
    total_minutes = int(round(hour_value * 60.0))
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


class FigureWindow(QMainWindow):
    def __init__(self, title: str, figsize):
        super().__init__()
        self.setWindowTitle(title)

        self.figure = Figure(figsize=figsize)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        self.setCentralWidget(central)
        self.resize(int(figsize[0] * 100), int(figsize[1] * 100) + self.toolbar.sizeHint().height())

        _OPEN_WINDOWS.add(self)

    def closeEvent(self, event):
        _OPEN_WINDOWS.discard(self)
        super().closeEvent(event)


class PnlContourWindow(FigureWindow):
    def __init__(self, surface: dict):
        sim_inputs = surface["sim_inputs"]
        ticker = sim_inputs["ticker"] or "Strategy"
        super().__init__(f"{ticker} P&L % simulation", (11, 7))

        self.surface = surface
        self.sim_inputs = sim_inputs
        self.low_price = surface["low_price"]
        self.high_price = surface["high_price"]

        self._draw()

    def point_metrics(self, hour_value: float, price: float):
        hour_value = min(max(float(hour_value), TIME_START), TIME_END)
        price = min(max(float(price), self.low_price), self.high_price)
        pnl_pct = pnl_pct_at_time_and_price(price, hour_value, self.sim_inputs)
        pnl_dollar = pnl_pct / 100.0 * self.sim_inputs["open_debit"]
        credit = pnl_dollar + self.sim_inputs["open_debit"]
        return {
            "hour_value": hour_value,
            "price": price,
            "credit": credit,
            "pnl_pct": pnl_pct,
            "pnl_dollar": pnl_dollar,
        }

    def point_text(self, hour_value: float, price: float, multiline: bool = False) -> str:
        m = self.point_metrics(hour_value, price)
        if multiline:
            return (
                f"Time: {format_hour(m['hour_value'])}\n"
                f"Stock: ${m['price']:.2f}\n"
                f"Credit: ${m['credit']:.4f}\n"
                f"P&L: ${m['pnl_dollar']:+.4f}\n"
                f"P&L%: {m['pnl_pct']:+.2f}%"
            )

        return (
            f"time={format_hour(m['hour_value'])}, "
            f"stock=${m['price']:.2f}, "
            f"credit=${m['credit']:.4f}, "
            f"P&L=${m['pnl_dollar']:+.4f}, "
            f"P&L%={m['pnl_pct']:+.2f}%"
        )

    def _in_plot_area(self, event) -> bool:
        return (
            event.inaxes == self.ax
            and event.xdata is not None
            and event.ydata is not None
            and TIME_START <= event.xdata <= TIME_END
            and self.low_price <= event.ydata <= self.high_price
        )

    def _draw(self):
        surface = self.surface
        sim_inputs = self.sim_inputs
        fig = self.figure
        low_price = self.low_price
        high_price = self.high_price
        open_spot = sim_inputs["open_spot"]
        implied_move = sim_inputs["implied_move"]
        price_points = surface["price_points"]
        time_points = surface["time_points"]
        pnl_pct_grid = surface["pnl_pct_grid"]

        max_abs = np.nanmax(np.abs(pnl_pct_grid))
        if not np.isfinite(max_abs) or max_abs <= 0:
            max_abs = 1.0

        if max_abs <= 20:
            level_step = 0.25
        elif max_abs <= 60:
            level_step = 0.50
        else:
            level_step = 1.00

        level_cap = math.ceil(max_abs / level_step) * level_step
        levels = np.arange(-level_cap, level_cap + level_step * 0.5, level_step)
        if not np.any(np.isclose(levels, 0.0)):
            levels = np.sort(np.append(levels, 0.0))

        cmap = mcolors.LinearSegmentedColormap.from_list(
            "loss_white_profit",
            [(0.0, "#c00000"), (0.5, "#ffffff"), (1.0, "#00a000")],
        )
        norm = mcolors.TwoSlopeNorm(vmin=-level_cap, vcenter=0.0, vmax=level_cap)

        x_mesh, y_mesh = np.meshgrid(time_points, price_points)

        ax = fig.subplots()
        self.ax = ax
        filled = ax.contourf(
            x_mesh,
            y_mesh,
            pnl_pct_grid,
            levels=levels,
            cmap=cmap,
            norm=norm,
            extend="both",
        )

        zero_contour = ax.contour(
            x_mesh,
            y_mesh,
            pnl_pct_grid,
            levels=[0.0],
            colors="black",
            linewidths=1.5,
        )
        ax.clabel(zero_contour, fmt={0.0: "Breakeven"}, inline=True, fontsize=9)

        ref_step = 5.0 if level_cap > 25 else 2.0
        ref_levels = np.arange(-level_cap, level_cap + ref_step * 0.5, ref_step)
        ref_levels = ref_levels[np.abs(ref_levels) > 1e-9]
        if len(ref_levels) > 0:
            ax.contour(
                x_mesh,
                y_mesh,
                pnl_pct_grid,
                levels=ref_levels,
                colors="black",
                linewidths=0.25,
                alpha=0.22,
            )

        ax.axhline(open_spot, color="black", linewidth=0.9, linestyle="--", alpha=0.65)
        ax.text(
            16.02,
            open_spot,
            f" Middle {open_spot:.2f}",
            ha="left",
            va="center",
            fontsize=8,
            color="black",
            alpha=0.9,
            clip_on=False,
        )

        for strike_value, strike_label, strike_color, strike_style, strike_alpha in strike_line_specs(surface):
            if low_price <= strike_value <= high_price:
                ax.axhline(
                    strike_value,
                    color=strike_color,
                    linewidth=0.9,
                    linestyle=strike_style,
                    alpha=strike_alpha,
                )
                ax.text(
                    16.02,
                    strike_value,
                    f" {strike_label} {strike_value:.2f}",
                    ha="left",
                    va="center",
                    fontsize=8,
                    color=strike_color,
                    alpha=min(0.95, strike_alpha + 0.2),
                    clip_on=False,
                )

        colorbar = fig.colorbar(filled, ax=ax, pad=0.12)
        colorbar.set_label("P&L %")

        ax.set_xticks(XTICKS, XTICKLABELS)

        ax.set_xlabel("Time on T+1 (ET)")
        ax.set_ylabel("Stock price ($)")

        title = (
            f"{sim_inputs['ticker'] or 'Strategy'} P&L % simulation\n"
            f"Price range: ${low_price:.2f} to ${high_price:.2f} (open ${open_spot:.2f} × exp(±2×log IM {implied_move*100:.2f}%))\n"
            f"Net debit: ${sim_inputs['open_debit']:.4f}  |  Sim IV: {sim_inputs['sim_iv']*100:.2f}%"
        )
        ax.set_title(title)

        ax.format_coord = lambda x, y: self.point_text(x, y, multiline=False)

        annotation = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(12, 12),
            textcoords="offset points",
            bbox={"boxstyle": "round", "fc": "white", "ec": "black", "alpha": 0.92},
            fontsize=9,
            zorder=5,
        )
        annotation.set_visible(False)
        self.annotation = annotation

        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("button_press_event", self._on_click)

        fig.tight_layout()

    def _place_annotation(self, event):
        ax = self.ax
        annotation = self.annotation
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        x_frac = 0.5 if x1 == x0 else (event.xdata - x0) / (x1 - x0)
        y_frac = 0.5 if y1 == y0 else (event.ydata - y0) / (y1 - y0)

        x_offset = -155 if x_frac > 0.74 else 12
        y_offset = -90 if y_frac > 0.80 else 12

        annotation.xy = (event.xdata, event.ydata)
        annotation.set_position((x_offset, y_offset))
        annotation.set_ha("right" if x_offset < 0 else "left")
        annotation.set_va("top" if y_offset < 0 else "bottom")

    def _on_mouse_move(self, event):
        annotation = self.annotation
        if not self._in_plot_area(event):
            if annotation.get_visible():
                annotation.set_visible(False)
                self.canvas.draw_idle()
            return

        self._place_annotation(event)
        annotation.set_text(self.point_text(event.xdata, event.ydata, multiline=True))
        annotation.set_visible(True)
        self.canvas.draw_idle()

    def _on_click(self, event):
        if not self._in_plot_area(event):
            return

        window = PnlSliceWindow(self, event.xdata, event.ydata)
        window.show()


class PnlSliceWindow(FigureWindow):
    def __init__(self, contour: PnlContourWindow, click_time: float, click_price: float):
        super().__init__("P&L slices", (10.5, 7.8))

        surface = contour.surface
        sim_inputs = contour.sim_inputs
        low_price = contour.low_price
        high_price = contour.high_price
        price_points = surface["price_points"]
        time_points = surface["time_points"]

        click_time = min(max(float(click_time), TIME_START), TIME_END)
        click_price = min(max(float(click_price), low_price), high_price)

        pnl_vs_price = np.array([
            pnl_pct_at_time_and_price(price, click_time, sim_inputs)
            for price in price_points
        ])
        pnl_vs_time = np.array([
            pnl_pct_at_time_and_price(click_price, hour_value, sim_inputs)
            for hour_value in time_points
        ])
        click_metrics = contour.point_metrics(click_time, click_price)

        slice_fig = self.figure
        ax_price, ax_time = slice_fig.subplots(2, 1, sharex=False)

        ax_price.plot(price_points, pnl_vs_price, linewidth=1.8)
        ax_price.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.7)
        ax_price.axvline(click_price, color="black", linewidth=0.8, linestyle=":", alpha=0.7)
        ax_price.plot([click_price], [click_metrics['pnl_pct']], marker="o")

        for strike_value, strike_label, strike_color, strike_style, strike_alpha in strike_line_specs(surface):
            if low_price <= strike_value <= high_price:
                ax_price.axvline(
                    strike_value,
                    color=strike_color,
                    linewidth=0.9,
                    linestyle=strike_style,
                    alpha=strike_alpha,
                )
                y_top = ax_price.get_ylim()[1]
                ax_price.text(
                    strike_value,
                    y_top,
                    strike_label,
                    rotation=90,
                    ha="right",
                    va="top",
                    fontsize=8,
                    color=strike_color,
                    alpha=min(0.95, strike_alpha + 0.2),
                )
        ax_price.set_xlabel("Stock price ($)")
        ax_price.set_ylabel("P&L %")
        ax_price.set_title(f"P&L % vs stock price at {format_hour(click_time)}")
        ax_price.grid(True, alpha=0.25)

        ax_time.plot(time_points, pnl_vs_time, linewidth=1.8)
        ax_time.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.7)
        ax_time.axvline(click_time, color="black", linewidth=0.8, linestyle=":", alpha=0.7)
        ax_time.plot([click_time], [click_metrics['pnl_pct']], marker="o")
        ax_time.set_xlabel("Time on T+1 (ET)")
        ax_time.set_ylabel("P&L %")
        ax_time.set_title(f"P&L % vs time at stock price ${click_price:.2f}")
        ax_time.grid(True, alpha=0.25)
        ax_time.set_xticks(XTICKS, XTICKLABELS)

        slice_title = (
            f"Slices through clicked point: {format_hour(click_time)}, ${click_price:.2f}"
            f"  |  P&L% {click_metrics['pnl_pct']:+.2f}%"
        )
        slice_fig.suptitle(slice_title)
        slice_fig.tight_layout(rect=(0, 0, 1, 0.96))
