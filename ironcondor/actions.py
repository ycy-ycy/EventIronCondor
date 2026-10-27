"""What each fetch button does, without any GUI code.

Each action takes a snapshot of the input texts plus a MarketData, runs on a worker
thread, and returns (updates, message): the input fields to overwrite and a one-line
summary for the status bar.
"""

import math

from .core.calculator import (
    average_iv_text,
    get_close_day,
    get_close_r_decimal,
    get_expiry_day,
    get_normal_iv_decimal,
    split_event_variance,
)
from .core.numbers import finite_positive, fmt_pct_value, fmt_price, parse_float
from .core.timeutils import (
    DAYS_PER_YEAR,
    format_date_text,
    format_datetime_text,
    format_expiry_text,
    get_current_date_day_hour_minute_for_open,
    get_now,
    get_weekday_name,
    parse_date_text,
    parse_expiry_text,
    time_to_expiry_4pm_years,
)


def require_close_day(inputs: dict) -> str:
    """Close weekday from the expected close date, or a clear error."""
    close_day = get_close_day(inputs)
    if not close_day:
        raise ValueError(
            "Set an expected close date: a weekday from the open date up to the weekly expiry "
            "(that week's Friday, or Thursday when Friday is a holiday)."
        )
    return close_day


def describe_iv(data: dict) -> str:
    strikes = "/".join(f"{k:g}" for k in data["strikes"])
    details = [f"F {data['forward']:.2f}"]
    if "stock_price" in data:
        gap = data["implied_price"] / data["stock_price"] - 1.0
        details.append(f"implied price {data['implied_price']:.2f} vs {data['stock_price']:.2f} ({gap:+.1%})")
    if data["quote_time"] is not None:
        details.append(f"closed: t pinned to {data['quote_time']:%Y-%m-%d %H:%M:%S} = {data['t_years'] * DAYS_PER_YEAR:.3f} d")
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


def fetch_close_us1y(inputs: dict, market):
    y = market.us1y_yield_percent()
    return {"close_us1y": fmt_pct_value(y)}, f"Close US 1Y {fmt_pct_value(y)}%"


def fetch_open_ivs(inputs: dict, market):
    """The open side's one market fetch: the quote time, both expiries, US 1Y and both IVs.

    The weekly (this week's Friday, or Thursday when Friday is a holiday) and the 21~56-day
    monthly ATM IV are read at one quote time, each with T from it to its expiry, never from
    the open time boxes; each is the mean of its call and put IV. The open panel solves them
    for the normal IV and the earnings jump:
        weekly IV² · T_week  = normal IV² · T_week  + J
        month IV² · T_month = normal IV² · T_month + J
    An odd term structure makes the normal variance or J negative: that is reported as an
    error and nothing is filled. The open price only feeds the monthly's sanity check.
    """
    us1y = market.us1y_yield_percent()
    stock_price = parse_float(inputs["open_market_price"])
    data = market.event_atm_ivs(inputs["ticker"], stock_price=stock_price, r=us1y / 100.0)
    week, month = data["weekly"], data["monthly"]
    updates = {
        "iv_quote_time": format_datetime_text(data["quote_time"]),
        "weekly_expiry": format_expiry_text(parse_date_text(week["actual_expiry"])),
        "monthly_expiry": format_expiry_text(parse_date_text(month["actual_expiry"])),
        "open_us1y": fmt_pct_value(us1y),
        "weekly_iv": fmt_pct_value((week["call_iv"] + week["put_iv"]) / 2.0),
        "monthly_iv": fmt_pct_value((month["call_iv"] + month["put_iv"]) / 2.0),
    }

    common = {"symbol": data["symbol"], "source": data["source"], "quote_time": None}
    quotes = (
        f"weekly {describe_iv(dict(common, **week))}; "
        f"monthly {describe_iv(dict(common, stock_price=data['stock_price'], **month))}"
    )
    weekly_iv = parse_float(updates["weekly_iv"]) / 100.0
    monthly_iv = parse_float(updates["monthly_iv"]) / 100.0
    t_week, t_month = week["t_years"], month["t_years"]
    normal_var, jump = split_event_variance(weekly_iv, t_week, monthly_iv, t_month)
    if normal_var < 0:
        raise ValueError(
            f"Odd term structure, nothing filled: the weekly's total variance {weekly_iv * weekly_iv * t_week:.5f} "
            f"is above the monthly's {monthly_iv * monthly_iv * t_month:.5f}, so the normal variance is "
            f"{normal_var:+.4f}. Quotes: {quotes}"
        )
    if jump < 0:
        raise ValueError(
            f"Odd term structure, nothing filled: the weekly IV {weekly_iv * 100:.2f}% is below the monthly's "
            f"{monthly_iv * 100:.2f}%, so the earnings jump variance is {jump:+.5f}. Quotes: {quotes}"
        )

    if stock_price is None or not finite_positive(stock_price):
        updates["open_market_price"] = fmt_price(data["stock_price"])
    snapshot = " (closing snapshot)" if data["closing_snapshot"] else ""
    return updates, (
        f"IVs at {updates['iv_quote_time']} ET{snapshot}: weekly {updates['weekly_expiry']} {updates['weekly_iv']}% "
        f"({t_week * DAYS_PER_YEAR:.3f} d), the {month['actual_expiry_days']}-day monthly {updates['monthly_iv']}% "
        f"({t_month * DAYS_PER_YEAR:.3f} d), US 1Y {updates['open_us1y']}% -> normal IV "
        f"{math.sqrt(normal_var) * 100:.2f}%, log IM {math.sqrt(jump) * 100:.2f}% — {quotes}"
    )


def fetch_close_iv(inputs: dict, market):
    ticker = inputs["ticker"]
    r = get_close_r_decimal(inputs)
    close_day = require_close_day(inputs)
    t_years = time_to_expiry_4pm_years(
        close_day,
        inputs["close_hour"],
        inputs["close_minute"],
        get_expiry_day(inputs),
    )
    data = market.front_week_atm_iv(
        ticker,
        t_years=t_years,
        r=r,
        expiry=parse_expiry_text(inputs["weekly_expiry"]),
    )
    updates = {
        "close_atm_call_iv": fmt_pct_value(data["call_iv"]),
        "close_atm_put_iv": fmt_pct_value(data["put_iv"]),
    }
    updates.update(fill_missing_price(inputs, "close_market_price", market))
    return updates, f"Close ATM IV — {describe_iv(data)}"


def update_open_all(inputs: dict, market):
    """Open now: the date, time and price, then the same fetch as Fetch 1Y + IV."""
    open_date, open_day, hour, minute = get_current_date_day_hour_minute_for_open()
    price = market.latest_price(inputs["ticker"])
    updates = {
        "open_date": open_date,
        "open_day": open_day,
        "open_hour": hour,
        "open_minute": minute,
        "open_market_price": fmt_price(price),
    }
    iv_updates, iv_message = fetch_open_ivs(dict(inputs, **updates), market)
    updates.update(iv_updates)
    return updates, f"Open updated — {open_day} {open_date} {hour}:{minute}, price {fmt_price(price)}; {iv_message}"


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
    t_years = time_to_expiry_4pm_years(close_day, hour, minute, get_expiry_day(inputs))
    data = market.front_week_atm_iv(
        ticker,
        t_years=t_years,
        r=r,
        expiry=parse_expiry_text(inputs["weekly_expiry"]),
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

    normal_iv = get_normal_iv_decimal(inputs)
    if normal_iv is None:
        raise ValueError("LT IV is empty. Fill the open side's IVs (Fetch 1Y + IV) first.")
    lt_iv = fmt_pct_value(normal_iv * 100.0)

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
