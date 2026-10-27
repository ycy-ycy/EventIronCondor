"""Close-day P&L surface (time of day x stock price) used by the Simulate plot."""

import math
from typing import Mapping

from .blackscholes import price_from_log_move
from .calculator import (
    PROB50_Z,
    get_close_day,
    get_close_r_decimal,
    get_event_split,
    get_expiry_day,
    get_open_debit_for_pnl,
    get_sim_iv_decimal,
)
from .numbers import parse_float
from .strategy import strategy_credit
from .timeutils import time_to_expiry_4pm_years


PRICE_POINTS = 321
TIME_POINTS = 261
TIME_START = 9.5
TIME_END = 16.0


def get_simulation_inputs(inputs: Mapping[str, str], theoretical_open_debit=None) -> dict:
    open_spot = parse_float(inputs["open_market_price"])
    spread = parse_float(inputs["spread"])
    long_put = parse_float(inputs["long_put_strike"])
    long_call = parse_float(inputs["long_call_strike"])
    try:
        split = get_event_split(inputs)
    except ValueError:
        split = None
    sim_iv = get_sim_iv_decimal(inputs)
    open_debit = get_open_debit_for_pnl(inputs, theoretical_open_debit)
    r = get_close_r_decimal(inputs)
    close_day = get_close_day(inputs)

    if (
        open_spot is None
        or spread is None
        or long_put is None
        or long_call is None
        or split is None
        or sim_iv is None
        or open_debit is None
        or not close_day
    ):
        raise ValueError(
            "Missing inputs. Please fill open price, strikes, spread, the open IVs (a usable term structure), sim IV, and a usable expected close date first."
        )

    if open_spot <= 0 or spread <= 0 or open_debit <= 0:
        raise ValueError("Open price, spread, and net debit must be positive.")

    short_put = long_put - spread
    short_call = long_call + spread

    implied_move = math.sqrt(split[1])

    return {
        "ticker": inputs["ticker"].strip().upper(),
        "open_spot": open_spot,
        "spread": spread,
        "long_put": long_put,
        "short_put": short_put,
        "long_call": long_call,
        "short_call": short_call,
        "sim_iv": sim_iv,
        "open_debit": open_debit,
        "r": r,
        "close_day": close_day,
        "close_date": inputs["close_date"].strip(),
        "expiry_day": get_expiry_day(inputs),
        "implied_move": implied_move,
    }


def pnl_pct_at_time_and_price(price: float, hour_value: float, sim_inputs: dict) -> float:
    if price <= 0:
        return float("nan")

    total_minutes = int(round(hour_value * 60.0))
    hour = total_minutes // 60
    minute = total_minutes % 60

    t_years = time_to_expiry_4pm_years(
        sim_inputs["close_day"],
        str(hour),
        f"{minute:02d}",
        sim_inputs["expiry_day"],
    )

    total_credit = strategy_credit(
        spot=price,
        t_years=t_years,
        r=sim_inputs["r"],
        iv=sim_inputs["sim_iv"],
        long_put=sim_inputs["long_put"],
        short_put=sim_inputs["short_put"],
        long_call=sim_inputs["long_call"],
        short_call=sim_inputs["short_call"],
    )

    pnl = total_credit - sim_inputs["open_debit"]
    return pnl / sim_inputs["open_debit"] * 100.0


def build_pnl_surface(sim_inputs: dict) -> dict:
    """Evaluate P&L % on the full price x time grid. Slow-ish (pure Python), run off the GUI thread."""
    import numpy as np

    open_spot = sim_inputs["open_spot"]
    implied_move = sim_inputs["implied_move"]

    low_price = max(0.01, price_from_log_move(open_spot, -2.0 * implied_move))
    high_price = price_from_log_move(open_spot, 2.0 * implied_move)

    if high_price <= low_price:
        raise ValueError("Invalid simulated price range.")

    price_points = np.linspace(low_price, high_price, PRICE_POINTS)
    time_points = np.linspace(TIME_START, TIME_END, TIME_POINTS)

    pnl_pct_grid = np.empty((len(price_points), len(time_points)))

    for i, price in enumerate(price_points):
        for j, hour_value in enumerate(time_points):
            pnl_pct_grid[i, j] = pnl_pct_at_time_and_price(price, hour_value, sim_inputs)

    return {
        "sim_inputs": sim_inputs,
        "low_price": low_price,
        "high_price": high_price,
        "implied_move_down": price_from_log_move(open_spot, -implied_move),
        "implied_move_up": price_from_log_move(open_spot, implied_move),
        "prob50_down": price_from_log_move(open_spot, -PROB50_Z * implied_move),
        "prob50_up": price_from_log_move(open_spot, PROB50_Z * implied_move),
        "price_points": price_points,
        "time_points": time_points,
        "pnl_pct_grid": pnl_pct_grid,
    }
