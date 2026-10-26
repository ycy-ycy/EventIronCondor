import json
import re
import threading
import time as _time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
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


OCC_SYMBOL_RE = re.compile(r"^(?P<root>[A-Z0-9.]+?)(?P<yymmdd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


class CboeDelayedSource(PriceSource, OptionSource):
    """Cboe's public delayed-quotes JSON (the data behind cboe.com's option chain pages).

    Free and keyless. Quotes are ~15 minutes delayed, but bid/ask/volume/OI come straight
    from Cboe and are usually far more complete than Yahoo's. One request returns every
    expiration, so the payload is cached briefly and shared by price/expiry/chain calls.
    """

    key = "cboe"
    label = "Cboe delayed quotes"
    description = (
        "Free, no API key. Stock and option quotes ~15 min delayed. After the close, IV time is "
        "pinned to the options' last tradable moment (16:00, or up to 16:15 for ETF/index options)."
    )

    URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
    CACHE_SECONDS = 20.0
    TIMEOUT_SECONDS = 20

    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    @staticmethod
    def _cboe_symbol(symbol: str) -> str:
        # Indices use a leading underscore on Cboe (_SPX); accept Yahoo-style ^SPX too.
        if symbol.startswith("^"):
            return "_" + symbol[1:]
        return symbol

    def _payload(self, symbol: str) -> dict:
        return self._snapshot(symbol)[0]

    def _snapshot(self, symbol: str):
        """(data, generated_at ET or None) for one download, cached briefly."""
        cboe_symbol = self._cboe_symbol(symbol)
        with self._lock:
            cached = self._cache.get(cboe_symbol)
            if cached is not None and _time.monotonic() - cached[0] < self.CACHE_SECONDS:
                return cached[1], cached[2]

        url = self.URL.format(symbol=cboe_symbol)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                raise DataSourceError(f"Cboe has no delayed quotes for {symbol} (HTTP {exc.code})")
            raise DataSourceError(f"Cboe request failed for {symbol}: {exc}")
        except Exception as exc:
            raise DataSourceError(f"Cboe request failed for {symbol}: {exc}")

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise DataSourceError(f"Unexpected Cboe response for {symbol}")

        try:
            generated_at = datetime.strptime(str(payload.get("timestamp")), "%Y-%m-%d %H:%M:%S")
            generated_at = generated_at.replace(tzinfo=timezone.utc).astimezone(ET)
        except ValueError:
            generated_at = None

        with self._lock:
            self._cache[cboe_symbol] = (_time.monotonic(), data, generated_at)
        return data, generated_at

    @staticmethod
    def _et_time(text):
        try:
            return datetime.fromisoformat(str(text)).replace(tzinfo=ET)
        except ValueError:
            return None

    def _closing_session(self, data: dict, generated_at):
        """Pinned quote time once the session is over (see closed_session_quote_time), else None.

        The file's "timestamp" is when it was generated; its data is QUOTE_DELAY older.
        """
        option_trades = [self._et_time(row.get("last_trade_time")) for row in data.get("options") or []]
        option_trades = [moment for moment in option_trades if moment is not None]
        return closed_session_quote_time(
            (generated_at or get_now()) - QUOTE_DELAY,
            last_regular_trade=self._et_time(data.get("last_trade_time")),
            last_option_trade=max(option_trades) if option_trades else None,
        )

    def _parsed_options(self, symbol: str, data: dict):
        """(expiry, 'C'/'P', OptionQuote) for the standard (non-adjusted) contracts in one payload."""
        wanted_root = re.sub(r"[^A-Z0-9]", "", self._cboe_symbol(symbol).lstrip("_"))
        parsed = []
        for row in data.get("options") or []:
            match = OCC_SYMBOL_RE.match(str(row.get("option", "")))
            if not match:
                continue
            yymmdd = match.group("yymmdd")
            try:
                expiry = date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))
            except ValueError:
                continue
            quote = OptionQuote(
                strike=int(match.group("strike")) / 1000.0,
                bid=to_float_or_none(row.get("bid")),
                ask=to_float_or_none(row.get("ask")),
                last=to_float_or_none(row.get("last_trade_price")),
                volume=to_float_or_none(row.get("volume")),
                open_interest=to_float_or_none(row.get("open_interest")),
            )
            parsed.append((match.group("root"), expiry, match.group("cp"), quote))

        # Adjusted contracts after splits/spinoffs get roots like "XYZ1"; skip them
        # when standard ones exist. Index weeklies (SPXW) are kept if nothing matches.
        standard = [item for item in parsed if item[0] == wanted_root]
        return [item[1:] for item in (standard or parsed)]

    def get_spot(self, symbol: str) -> float:
        data = self._payload(symbol)
        for key in ("current_price", "close", "prev_day_close"):
            value = data.get(key)
            if finite_positive(value):
                return float(value)
        raise DataSourceError(f"Could not fetch latest price for {symbol} from Cboe")

    def get_expirations(self, symbol: str) -> List[date]:
        return sorted({expiry for expiry, _, _ in self._parsed_options(symbol, self._payload(symbol))})

    def get_option_chain(self, symbol: str, expiry: date) -> OptionChain:
        data, generated_at = self._snapshot(symbol)
        chain = OptionChain(expiry=expiry, quote_time=self._closing_session(data, generated_at))
        for option_expiry, cp, quote in self._parsed_options(symbol, data):
            if option_expiry != expiry:
                continue
            (chain.calls if cp == "C" else chain.puts).append(quote)
        chain.calls.sort(key=lambda q: q.strike)
        chain.puts.sort(key=lambda q: q.strike)
        return chain
