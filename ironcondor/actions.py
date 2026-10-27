"""What each fetch button does, without any GUI code.

Each action takes a snapshot of the input texts plus a MarketData, runs on a worker
thread, and returns (updates, message): the input fields to overwrite and a one-line
summary for the status bar.
"""

from .core.calculator import average_iv_text, get_close_day, get_close_r_decimal, get_open_r_decimal
from .core.numbers import finite_positive, fmt_pct_value, fmt_price, parse_float
from .core.timeutils import (
    format_date_text,
    get_current_date_day_hour_minute_for_open,
    get_now,
    get_weekday_name,
    time_to_friday_4pm_years,
)


def require_close_day(inputs: dict) -> str:
    """Close weekday from the expected close date, or a clear error."""
    close_day = get_close_day(inputs)
    if not close_day:
        raise ValueError(
            "Set an expected close date: a weekday from the open date up to that week's "
            "Friday (when the options expire)."
        )
    return close_day


def describe_iv(data: dict) -> str:
    strikes = "/".join(f"{k:g}" for k in data["strikes"])
    details = [f"F {data['forward']:.2f}"]
    if "stock_price" in data:
        gap = data["implied_price"] / data["stock_price"] - 1.0
        details.append(f"implied price {data['implied_price']:.2f} vs {data['stock_price']:.2f} ({gap:+.1%})")
    if data["quote_time"] is not None:
        details.append(f"closed: t pinned to {data['quote_time']:%Y-%m-%d %H:%M:%S} = {data['t_years'] * 365:.3f} d")
    return (
        f"{data['symbol']} {data['actual_expiry']} K {strikes}: "
        f"call {data['call_iv']:.2f}% / put {data['put_iv']:.2f}% "
        f"({', '.join(details)}) — {data['source']}"
    )


def close_market_price(inputs: dict, market, ticker: str = "", prefer_existing: bool = True) -> float:
    """Close-side stock price (for credit / P&L; IV never needs it).

    prefer_existing=True: the value in the close-side Current market price box, else the
    latest price. prefer_existing=False: refresh from the price source first, then fall
    back to the box.
    """
    fetch_error = None

    def existing_close_price():
        try:
            spot = parse_float(inputs["close_market_price"])
        except Exception:
            spot = None
        if spot is not None and finite_positive(spot):
            return float(spot)
        return None

    if prefer_existing:
        spot = existing_close_price()
        if spot is not None:
            return spot

    if ticker:
        try:
            spot = market.latest_price(ticker)
            if finite_positive(spot):
                return float(spot)
        except Exception as exc:
            fetch_error = exc

    if not prefer_existing:
        spot = existing_close_price()
        if spot is not None:
            return spot

    if fetch_error is not None:
        raise fetch_error

    raise ValueError("Missing close market price. Fill the close-side Current market price or click Fetch price.")


def fill_missing_price(inputs: dict, name: str, market) -> dict:
    """{name: latest price} when that price box is empty, else nothing."""
    price = parse_float(inputs[name])
    if price is not None and finite_positive(price):
        return {}
    return {name: fmt_price(market.latest_price(inputs["ticker"]))}


def fetch_open_price(inputs: dict, market):
    price = market.latest_price(inputs["ticker"])
    return {"open_market_price": fmt_price(price)}, f"Open price {fmt_price(price)}"


def fetch_close_price(inputs: dict, market):
    price = market.latest_price(inputs["ticker"])
    return {"close_market_price": fmt_price(price)}, f"Close price {fmt_price(price)}"


def fetch_open_us1y(inputs: dict, market):
    y = market.us1y_yield_percent()
    return {"open_us1y": fmt_pct_value(y)}, f"Open US 1Y {fmt_pct_value(y)}%"


def fetch_close_us1y(inputs: dict, market):
    y = market.us1y_yield_percent()
    return {"close_us1y": fmt_pct_value(y)}, f"Close US 1Y {fmt_pct_value(y)}%"


def fetch_open_iv(inputs: dict, market):
    r = get_open_r_decimal(inputs)
    t_years = time_to_friday_4pm_years(
        inputs["open_day"],
        inputs["open_hour"],
        inputs["open_minute"],
    )
    data = market.front_week_atm_iv(
        inputs["ticker"],
        t_years=t_years,
        r=r,
    )
    updates = {
        "atm_call_iv": fmt_pct_value(data["call_iv"]),
        "atm_put_iv": fmt_pct_value(data["put_iv"]),
    }
    updates.update(fill_missing_price(inputs, "open_market_price", market))
    return updates, f"Open ATM IV — {describe_iv(data)}"


def fetch_lt_iv(inputs: dict, market):
    """LT IV = strict 9~12 month quarterly ATM IV; the open price only feeds the sanity check."""
    stock_price = parse_float(inputs["open_market_price"])
    r = get_open_r_decimal(inputs)
    data = market.quarterly_atm_iv(
        inputs["ticker"],
        stock_price=stock_price,
        r=r,
    )
    updates = {
        "long_term_call_iv": fmt_pct_value(data["call_iv"]),
        "long_term_put_iv": fmt_pct_value(data["put_iv"]),
    }
    if stock_price is None or not finite_positive(stock_price):
        updates["open_market_price"] = fmt_price(data["stock_price"])
    return updates, f"LT IV (quarterly, {data['actual_expiry_days']} days) — {describe_iv(data)}"


def fetch_close_iv(inputs: dict, market):
    ticker = inputs["ticker"]
    r = get_close_r_decimal(inputs)
    close_day = require_close_day(inputs)
    t_years = time_to_friday_4pm_years(
        close_day,
        inputs["close_hour"],
        inputs["close_minute"],
    )
    data = market.front_week_atm_iv(
        ticker,
        t_years=t_years,
        r=r,
    )
    updates = {
        "close_atm_call_iv": fmt_pct_value(data["call_iv"]),
        "close_atm_put_iv": fmt_pct_value(data["put_iv"]),
    }
    updates.update(fill_missing_price(inputs, "close_market_price", market))
    return updates, f"Close ATM IV — {describe_iv(data)}"


def update_open_all(inputs: dict, market):
    ticker = inputs["ticker"]
    open_date, open_day, hour, minute = get_current_date_day_hour_minute_for_open()
    price = market.latest_price(ticker)
    us1y = market.us1y_yield_percent()
    r = us1y / 100.0
    t_years = time_to_friday_4pm_years(open_day, hour, minute)
    data = market.front_week_atm_iv(
        ticker,
        t_years=t_years,
        r=r,
    )
    updates = {
        "open_date": open_date,
        "open_day": open_day,
        "open_hour": hour,
        "open_minute": minute,
        "open_market_price": fmt_price(price),
        "open_us1y": fmt_pct_value(us1y),
        "atm_call_iv": fmt_pct_value(data["call_iv"]),
        "atm_put_iv": fmt_pct_value(data["put_iv"]),
    }
    return updates, f"Open updated — price {fmt_price(price)}, US1Y {fmt_pct_value(us1y)}%, {describe_iv(data)}"


def update_close_all(inputs: dict, market):
    ticker = inputs["ticker"]
    now = get_now()
    hour = str(now.hour)
    minute = f"{now.minute:02d}"

    # Closing now: today is the close date (on weekends keep the expected close date).
    close_date = format_date_text(now.date()) if get_weekday_name(now.date()) else inputs["close_date"]
    close_day = require_close_day(dict(inputs, close_date=close_date))

    price = close_market_price(inputs, market, ticker, prefer_existing=False)
    us1y = market.us1y_yield_percent()
    r = us1y / 100.0
    t_years = time_to_friday_4pm_years(close_day, hour, minute)
    data = market.front_week_atm_iv(
        ticker,
        t_years=t_years,
        r=r,
    )
    call_iv = fmt_pct_value(data["call_iv"])
    put_iv = fmt_pct_value(data["put_iv"])
    updates = {
        "close_date": close_date,
        "close_hour": hour,
        "close_minute": minute,
        "close_market_price": fmt_price(price),
        "close_us1y": fmt_pct_value(us1y),
        "close_atm_call_iv": call_iv,
        "close_atm_put_iv": put_iv,
        # A full close update marks the position at the IV observed now.
        "sim_iv": average_iv_text(call_iv, put_iv),
    }
    return updates, f"Close updated — price {fmt_price(price)}, US1Y {fmt_pct_value(us1y)}%, {describe_iv(data)}"


def simulate_close_930(inputs: dict, market):
    ticker = inputs["ticker"]
    close_day = require_close_day(inputs)

    lt_iv = average_iv_text(inputs["long_term_call_iv"], inputs["long_term_put_iv"])
    if not lt_iv:
        raise ValueError("LT IV is empty. Fill it on the open side (Fetch LT IV) first.")

    # Simulated 9:30 uses the close-side stock price already shown in the close
    # panel; fetch latest only if that box is empty.
    price = close_market_price(inputs, market, ticker, prefer_existing=True)
    us1y = market.us1y_yield_percent()
    updates = {
        "close_hour": "9",
        "close_minute": "30",
        "close_market_price": fmt_price(price),
        "close_us1y": fmt_pct_value(us1y),
        "sim_iv": lt_iv,
    }
    return updates, (
        f"Simulating {close_day} {inputs['close_date'].strip()} 09:30 with LT IV {lt_iv}%, "
        f"price {fmt_price(price)}, US1Y {fmt_pct_value(us1y)}%"
    )
