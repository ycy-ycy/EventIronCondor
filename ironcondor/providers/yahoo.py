import time as _time
from datetime import datetime
from typing import List

from ..core.numbers import finite_positive
from ..core.timeutils import ET, QUOTE_DELAY, closed_session_quote_time, get_now
from .base import (
    DataSourceError,
    OptionChain,
    OptionQuote,
    OptionSource,
    PriceSource,
    to_float_or_none,
)


def fast_info_get(fast_info, key: str):
    try:
        value = fast_info.get(key)
        if value is not None:
            return value
    except Exception:
        pass

    try:
        return fast_info[key]
    except Exception:
        return None


class YFinanceSource(PriceSource, OptionSource):
    key = "yfinance"
    label = "Yahoo Finance (yfinance)"
    description = (
        "Free, no API key. Near-live stock price; option quotes ~15 min delayed (IV uses the "
        "option quotes only). After the close, IV time is pinned to the options' last tradable moment."
    )

    # yf.Ticker caches prices/expirations internally; reuse one only within a single
    # button action so a later click always gets fresh data.
    TICKER_TTL_SECONDS = 5.0

    def __init__(self):
        try:
            import yfinance
        except Exception:
            raise DataSourceError(
                "Missing dependency: yfinance. Please install it first:\n"
                "python -m pip install yfinance"
            )
        self._yf = yfinance
        self._tickers = {}

    def _ticker(self, symbol: str):
        now = _time.monotonic()
        cached = self._tickers.get(symbol)
        if cached is not None and now - cached[0] < self.TICKER_TTL_SECONDS:
            return cached[1]
        ticker_obj = self._yf.Ticker(symbol)
        self._tickers[symbol] = (now, ticker_obj)
        return ticker_obj

    def get_spot(self, symbol: str) -> float:
        ticker_obj = self._ticker(symbol)

        try:
            fast_info = ticker_obj.fast_info
            for key in ("last_price", "regular_market_price", "previous_close"):
                value = fast_info_get(fast_info, key)
                if finite_positive(value):
                    return float(value)
        except Exception:
            pass

        for period, interval, prepost in (
            ("1d", "1m", True),
            ("5d", "1d", False),
            ("1mo", "1d", False),
        ):
            try:
                hist = ticker_obj.history(period=period, interval=interval, prepost=prepost)
                if hist is None or hist.empty or "Close" not in hist:
                    continue

                closes = hist["Close"].dropna()
                if closes.empty:
                    continue

                value = closes.iloc[-1]
                if finite_positive(value):
                    return float(value)
            except Exception:
                pass

        raise DataSourceError(f"Could not fetch latest price for {symbol}")

    def get_expirations(self, symbol: str):
        expiries = list(getattr(self._ticker(symbol), "options", []) or [])
        parsed = []
        for expiry in expiries:
            try:
                parsed.append(datetime.strptime(expiry, "%Y-%m-%d").date())
            except Exception:
                pass
        return sorted(parsed)

    def get_option_chain(self, symbol: str, expiry) -> OptionChain:
        raw = self._ticker(symbol).option_chain(expiry.strftime("%Y-%m-%d"))
        return OptionChain(
            expiry=expiry,
            calls=self._quotes_from_frame(raw.calls),
            puts=self._quotes_from_frame(raw.puts),
            quote_time=self._closing_session(raw),
        )

    @staticmethod
    def _closing_session(raw):
        """Pinned quote time once the session is over (see closed_session_quote_time), else None.

        Yahoo's option quotes run QUOTE_DELAY behind, so the data time is now minus that.
        The stock's regularMarketTime (last regular-session trade) marks holidays.
        """
        underlying = getattr(raw, "underlying", None) or {}
        try:
            last_regular_trade = datetime.fromtimestamp(float(underlying["regularMarketTime"]), ET)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            last_regular_trade = None

        last_option_trade = None
        for frame in (raw.calls, raw.puts):
            if frame is None or frame.empty or "lastTradeDate" not in frame.columns:
                continue
            times = frame["lastTradeDate"].dropna()
            if times.empty:
                continue
            latest = times.max()
            latest = latest.tz_convert(ET) if latest.tzinfo is not None else latest.tz_localize("UTC").tz_convert(ET)
            latest = latest.to_pydatetime()
            if last_option_trade is None or latest > last_option_trade:
                last_option_trade = latest

        return closed_session_quote_time(
            get_now() - QUOTE_DELAY,
            last_regular_trade=last_regular_trade,
            last_option_trade=last_option_trade,
        )

    @staticmethod
    def _quotes_from_frame(frame) -> List[OptionQuote]:
        if frame is None or frame.empty or "strike" not in frame.columns:
            return []

        def col(row, name):
            return to_float_or_none(row[name]) if name in row else None

        quotes = []
        for _, row in frame.iterrows():
            strike = to_float_or_none(row["strike"])
            if strike is None:
                continue
            quotes.append(OptionQuote(
                strike=strike,
                bid=col(row, "bid"),
                ask=col(row, "ask"),
                last=col(row, "lastPrice"),
                volume=col(row, "volume"),
                open_interest=col(row, "openInterest"),
            ))
        return quotes
