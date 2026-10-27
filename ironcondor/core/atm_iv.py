"""ATM implied volatility from an option chain, plus expiry selection.

Works on the source-neutral OptionChain / OptionQuote model, so every data source
goes through the same quote filtering and IV solving.
"""

import math
from datetime import date, timedelta

from .blackscholes import solve_iv_from_option_mid
from .numbers import finite_positive
from .timeutils import get_this_friday, is_standard_monthly_expiry_date


def choose_weekly_expiry(expiries, reference_date: date) -> date:
    """This week's standard weekly: its Friday, or the Thursday before it when that Friday
    isn't listed (a market holiday).

    Never the nearest expiry: a Monday or Wednesday one may expire before the earnings.
    """
    friday = get_this_friday(reference_date)
    if friday in expiries:
        return friday
    thursday = friday - timedelta(days=1)
    if thursday >= reference_date and thursday in expiries:
        return thursday
    raise RuntimeError(
        f"No weekly expiry is listed this week: neither Friday {friday:%Y-%m-%d} nor Thursday "
        f"{thursday:%Y-%m-%d}"
    )


def choose_expiry_on_or_after(expiries, target_date: date) -> date:
    """Exact target if listed, else the first listed expiry after it, else the last one."""
    if not expiries:
        raise RuntimeError("No option expirations were returned")

    if target_date in expiries:
        return target_date

    future = [d for d in expiries if d >= target_date]
    if future:
        return sorted(future)[0]

    return sorted(expiries)[-1]


# LT IV comes from the standard monthly expiry this many days out (both ends included).
LT_MIN_DAYS = 21
LT_MAX_DAYS = 56


def choose_monthly_expiry_21_to_56_days(expiries, reference_date: date) -> date:
    """The standard monthly expiry 21~56 days after reference_date; the earlier one if two are."""
    min_date = reference_date + timedelta(days=LT_MIN_DAYS)
    max_date = reference_date + timedelta(days=LT_MAX_DAYS)

    monthlies = [
        d for d in expiries
        if min_date <= d <= max_date
        and is_standard_monthly_expiry_date(d)
        # A Thursday only stands in for a holiday third Friday, not next to a listed one.
        and not (d.weekday() == 3 and d + timedelta(days=1) in expiries)
    ]

    if not monthlies:
        raise RuntimeError(
            f"No standard monthly expiry {LT_MIN_DAYS}~{LT_MAX_DAYS} days out "
            f"({min_date:%Y-%m-%d}..{max_date:%Y-%m-%d}) is listed"
        )

    return min(monthlies)


def option_mid_and_relative_spread(quote, allow_last_price: bool = True):
    """Return (mid, relative_spread) using bid/ask when available.

    For reliability-sensitive long-dated IV, call with allow_last_price=False.
    The last trade can be stale; bid/ask mid is the only acceptable input there.
    """
    bid = quote.bid
    ask = quote.ask

    if finite_positive(bid) and finite_positive(ask) and float(ask) >= float(bid):
        bid_f = float(bid)
        ask_f = float(ask)
        mid = (bid_f + ask_f) / 2.0
        rel_spread = (ask_f - bid_f) / mid if mid > 0 else float("inf")
        return mid, rel_spread

    if allow_last_price:
        if finite_positive(quote.last):
            return float(quote.last), 9.0

    raise RuntimeError("No reliable bid/ask midpoint for the selected option")


def quote_activity_score(quote):
    """Small helper for rejecting completely dead long-dated quotes."""
    score = 0.0
    for value in (quote.volume, quote.open_interest):
        try:
            if value is not None and math.isfinite(float(value)):
                score += max(float(value), 0.0)
        except Exception:
            pass
    return score



# LT IV sanity check: the stock price implied by the option quotes, F * e^(-rT), may differ
# from the price in the box only by this fraction (dividends, borrow cost, quote delay).
MAX_IMPLIED_PRICE_GAP = 0.10


def parity_forward(strike: float, call_mid: float, put_mid: float, t_years: float, r: float) -> float:
    """Forward implied by one call/put pair: C - P = e^(-rT) (F - K)  =>  F = K + e^(rT) (C - P)."""
    return strike + math.exp(r * t_years) * (call_mid - put_mid)


def atm_forward_ivs(option_chain, t_years: float, r: float, strict: bool = False, stock_price=None) -> dict:
    """ATM call/put IV from the option quotes alone, no stock price.

    1. Strikes quoted on both sides; K0 = the one with the smallest |C - P| (Cboe VIX rule).
    2. Add the neighbouring strike on the other side of K0's forward, when usable.
    3. F = mean of the put-call-parity forwards of those one or two strikes.
    4. Call and put IV at each strike with Black-76 on F, interpolated to F.
    Dividends, borrow cost and quote delay all sit inside F, so call and put IV agree.

    strict=True is used for the 21~56-day monthly behind the LT IV:
      - bid/ask midpoint only; never the last trade
      - relative spread <= 60% and some volume/open interest
      - strikes within 8% of F
      - IV sanity band and call/put agreement
      - implied stock price F e^(-rT) within MAX_IMPLIED_PRICE_GAP of stock_price
      - reject instead of outputting a questionable IV
    """
    if t_years <= 0:
        raise ValueError("Time to expiry must be positive")

    calls = {}
    puts = {}
    for quotes, by_strike in ((option_chain.calls, calls), (option_chain.puts, puts)):
        for quote in quotes or []:
            if finite_positive(quote.strike):
                by_strike.setdefault(float(quote.strike), quote)

    errors = []
    pairs = []
    for strike in sorted(set(calls) & set(puts)):
        call_row = calls[strike]
        put_row = puts[strike]
        try:
            call_mid, call_rel_spread = option_mid_and_relative_spread(call_row, allow_last_price=not strict)
            put_mid, put_rel_spread = option_mid_and_relative_spread(put_row, allow_last_price=not strict)

            if strict and (call_rel_spread > 0.60 or put_rel_spread > 0.60):
                raise RuntimeError(
                    f"strike {strike:g} spread too wide: call {call_rel_spread:.0%}, put {put_rel_spread:.0%}"
                )

            if strict and (quote_activity_score(call_row) + quote_activity_score(put_row)) <= 0:
                raise RuntimeError(f"strike {strike:g} has zero volume/open interest")
        except RuntimeError as e:
            errors.append(str(e))
            continue
        pairs.append((strike, call_mid, put_mid))

    def fail(detail):
        if strict:
            return RuntimeError(
                "No reliable monthly ATM IV for the LT IV. "
                "I rejected the available quotes instead of filling a questionable IV. "
                f"First rejection: {detail}"
            )
        return RuntimeError(f"Cannot solve ATM IV from this option chain. First error: {detail}")

    if not pairs:
        raise fail(errors[0] if errors else "no strike has both a call and a put quote")

    k0 = min(range(len(pairs)), key=lambda i: abs(pairs[i][1] - pairs[i][2]))
    used = [pairs[k0]]
    k0_forward = parity_forward(*pairs[k0], t_years, r)
    neighbour = k0 + 1 if k0_forward > pairs[k0][0] else k0 - 1
    if k0_forward != pairs[k0][0] and 0 <= neighbour < len(pairs):
        used.append(pairs[neighbour])

    forward = sum(parity_forward(*pair, t_years, r) for pair in used) / len(used)
    if not finite_positive(forward):
        raise fail(f"implied forward {forward:.4f} is not positive")

    # Black-76 on F equals Black-Scholes on F e^(-rT) with no dividend yield.
    implied_price = forward * math.exp(-r * t_years)

    solved = []
    for strike, call_mid, put_mid in used:
        try:
            if strict and abs(strike / forward - 1.0) > 0.08:
                raise RuntimeError(f"strike {strike:g} is too far from the forward {forward:.2f}")
            call_iv = solve_iv_from_option_mid(implied_price, strike, t_years, r, "call", call_mid)
            put_iv = solve_iv_from_option_mid(implied_price, strike, t_years, r, "put", put_mid)
        except (RuntimeError, ValueError) as e:
            errors.append(str(e))
            continue
        solved.append((strike, call_iv, put_iv, call_mid, put_mid))

    if not solved:
        raise fail(errors[0] if errors else "no usable ATM strike")

    solved.sort()
    if len(solved) == 2:
        (k_lo, call_lo, put_lo, _, _), (k_hi, call_hi, put_hi, _, _) = solved
        weight = min(max((forward - k_lo) / (k_hi - k_lo), 0.0), 1.0)
        call_iv = call_lo + weight * (call_hi - call_lo)
        put_iv = put_lo + weight * (put_hi - put_lo)
    else:
        call_iv, put_iv = solved[0][1], solved[0][2]

    if strict:
        avg_iv = (call_iv + put_iv) / 2.0
        iv_gap = abs(call_iv - put_iv)
        if not (0.03 <= avg_iv <= 2.50):
            raise fail("IV outside sanity band")
        if iv_gap > max(0.05, 0.20 * avg_iv):
            raise fail(f"call/put IV mismatch: {call_iv * 100:.2f}% vs {put_iv * 100:.2f}%")
        if finite_positive(stock_price):
            gap = implied_price / float(stock_price) - 1.0
            if abs(gap) > MAX_IMPLIED_PRICE_GAP:
                raise fail(
                    f"implied stock price {implied_price:.2f} differs from the price {float(stock_price):.2f} "
                    f"by {gap:+.1%} (limit {MAX_IMPLIED_PRICE_GAP:.0%})"
                )

    nearest = min(solved, key=lambda item: abs(item[0] - forward))
    return {
        "strikes": [item[0] for item in solved],
        "forward": forward,
        "implied_price": implied_price,
        "call_iv": call_iv * 100.0,
        "put_iv": put_iv * 100.0,
        "call_mid": nearest[3],
        "put_mid": nearest[4],
    }
