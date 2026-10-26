"""Long iron condor (long put spread + long call spread) pricing helpers."""

from .blackscholes import bs_price


def strategy_put_call_credit(
    spot: float,
    t_years: float,
    r: float,
    iv: float,
    long_put: float,
    short_put: float,
    long_call: float,
    short_call: float,
):
    long_put_price = bs_price(
        spot=spot,
        strike=long_put,
        t_years=t_years,
        r=r,
        iv=iv,
        option_type="put",
    )

    short_put_price = bs_price(
        spot=spot,
        strike=short_put,
        t_years=t_years,
        r=r,
        iv=iv,
        option_type="put",
    )

    put_credit = long_put_price - short_put_price

    long_call_price = bs_price(
        spot=spot,
        strike=long_call,
        t_years=t_years,
        r=r,
        iv=iv,
        option_type="call",
    )

    short_call_price = bs_price(
        spot=spot,
        strike=short_call,
        t_years=t_years,
        r=r,
        iv=iv,
        option_type="call",
    )

    call_credit = long_call_price - short_call_price

    return put_credit, call_credit


def strategy_credit(
    spot: float,
    t_years: float,
    r: float,
    iv: float,
    long_put: float,
    short_put: float,
    long_call: float,
    short_call: float,
) -> float:
    put_credit, call_credit = strategy_put_call_credit(
        spot=spot,
        t_years=t_years,
        r=r,
        iv=iv,
        long_put=long_put,
        short_put=short_put,
        long_call=long_call,
        short_call=short_call,
    )
    return put_credit + call_credit


def find_root_bisection(func, lo: float, hi: float, max_iter: int = 80):
    flo = func(lo)
    fhi = func(hi)

    if abs(flo) < 1e-8:
        return lo
    if abs(fhi) < 1e-8:
        return hi
    if flo * fhi > 0:
        return None

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        fmid = func(mid)

        if abs(fmid) < 1e-7 or abs(hi - lo) < 1e-4:
            return mid

        if flo * fmid <= 0:
            hi = mid
            fhi = fmid
        else:
            lo = mid
            flo = fmid

    return (lo + hi) / 2.0


def find_breakeven_in_range(func, start: float, end: float):
    if start <= 0 or end <= 0 or end <= start:
        return None

    steps = 500
    prev_x = start
    prev_y = func(prev_x)

    for i in range(1, steps + 1):
        x = start + (end - start) * i / steps
        y = func(x)

        if abs(y) < 1e-6:
            return x

        if prev_y * y < 0:
            return find_root_bisection(func, prev_x, x)

        prev_x = x
        prev_y = y

    return None
