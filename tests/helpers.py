"""Shared fixtures: example trades and synthetic option chains."""

import math
from datetime import date

from ironcondor.core.blackscholes import bs_price
from ironcondor.providers.base import OptionChain, OptionQuote


# The CRWV save file from May 2026 (format v21, before LT IV moved to the open side).
CRWV_V21_FILE = {
    "version": 21,
    "saved_at": "2026-05-08T11:31:57.139296-04:00",
    "inputs": {
        "ticker": "CRWV",
        "open_date": "2026-05-07",
        "open_day": "THU",
        "open_hour": "15",
        "open_minute": "55",
        "open_market_price": "127.92",
        "atm_call_iv": "282.03",
        "atm_put_iv": "277.50",
        "long_term_call_iv": "82.86",
        "long_term_put_iv": "82.86",
        "open_us1y": "3.73",
        "close_us1y": "3.73",
        "spread": "1",
        "long_put_strike": "122",
        "long_call_strike": "134",
        "close_hour": "9",
        "close_minute": "30",
        "close_market_price": "116",
        "open_debit_override": "0.73",
    },
}

# The MSFT trade from the screenshot of the running app (current input layout). The
# screenshot showed this Friday's ATM IV 62.71 / 62.98 and LT IV 32.09; the IV row is what
# that v23 file converts to: the same normal IV and jump.
MSFT_INPUTS = {
    "ticker": "MSFT",
    "open_date": "2026-10-26",
    "open_day": "MON",
    "open_hour": "14",
    "open_minute": "39",
    "open_market_price": "532.12",
    "iv_quote_time": "2026-10-26 14:39",
    "weekly_expiry": "FRI 2026-10-30",
    "monthly_expiry": "FRI 2026-11-20",
    "weekly_iv": "62.845",
    "monthly_iv": "38.761194",
    "open_us1y": "4.41",
    "spread": "20",
    "long_put_strike": "510",
    "long_call_strike": "550",
    "open_debit_override": "",
    "close_date": "2026-10-27",
    "close_hour": "9",
    "close_minute": "30",
    "close_market_price": "531.92",
    "close_us1y": "4.41",
    "close_atm_call_iv": "112.81",
    "close_atm_put_iv": "112.52",
    "sim_iv": "32.09",
}


def synthetic_chain(spot, q, r, t, iv_of_strike, strikes, half_spread=0.0, volume=10, expiry=date(2026, 10, 30)):
    """Calls and puts priced with Black-Scholes (dividend yield q), quoted mid +/- half_spread."""
    calls, puts = [], []
    for strike in strikes:
        iv = iv_of_strike(strike)
        for option_type, bucket in (("call", calls), ("put", puts)):
            price = bs_price(spot, strike, t, r, iv, option_type, q=q)
            bucket.append(OptionQuote(
                strike=strike,
                bid=price * (1 - half_spread),
                ask=price * (1 + half_spread),
                last=price,
                volume=volume,
                open_interest=100,
            ))
    return OptionChain(expiry=expiry, calls=calls, puts=puts)


def true_forward(spot, q, r, t):
    return spot * math.exp((r - q) * t)
