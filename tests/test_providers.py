import math
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

from ironcondor.core.timeutils import ET
from ironcondor.providers import CAPABILITIES, DataSourceError, create_source, sources_for
from ironcondor.providers.cboe import CboeDelayedSource


def et(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ET)


def cboe_row(symbol, bid, ask, last=0.0, last_time=None, volume=1.0, oi=10.0):
    return {"option": symbol, "bid": bid, "ask": ask, "last_trade_price": last,
            "last_trade_time": last_time, "volume": volume, "open_interest": oi}


CBOE_DATA = {
    "symbol": "XYZ",
    "current_price": 101.25,
    "close": 100.5,
    "last_trade_time": "2026-10-26T15:59:59",
    "options": [
        cboe_row("XYZ261030C00100000", 2.1, 2.3, 2.2, "2026-10-26T15:59:50"),
        cboe_row("XYZ261030P00100000", 1.0, 1.2, 1.1, "2026-10-26T15:58:00"),
        cboe_row("XYZ261030C00105000", 0.5, 0.6, 0.0, None),
        cboe_row("XYZ261030P00105000", 4.0, 4.4, 4.2, "2026-10-26T14:00:00"),
        # This class trades until 16:15 (like SPY); its last trade sets the pinned time.
        cboe_row("XYZ261106C00100000", 3.0, 3.2, 3.1, "2026-10-26T16:14:00"),
        # Adjusted contract after a corporate action: different root, must be skipped.
        cboe_row("XYZ1261113C00100000", 9.0, 9.9, 9.5, "2026-10-26T15:00:00"),
    ],
}


class CboeTest(unittest.TestCase):
    def source(self, generated_at):
        src = CboeDelayedSource()
        src._snapshot = lambda symbol: (CBOE_DATA, generated_at)
        return src

    def test_parses_standard_contracts_only(self):
        src = self.source(et("2026-10-26 14:15"))
        self.assertEqual(src.get_expirations("XYZ"), [date(2026, 10, 30), date(2026, 11, 6)])
        chain = src.get_option_chain("XYZ", date(2026, 10, 30))
        self.assertEqual([q.strike for q in chain.calls], [100.0, 105.0])
        self.assertEqual((chain.puts[0].bid, chain.puts[0].ask, chain.puts[0].volume), (1.0, 1.2, 1.0))
        self.assertEqual(src.get_spot("XYZ"), 101.25)

    def test_intraday_snapshot_is_not_pinned(self):
        # Generated 16:10 -> data time 15:55, still regular hours.
        src = self.source(et("2026-10-26 16:10"))
        self.assertIsNone(src.get_option_chain("XYZ", date(2026, 10, 30)).quote_time)

    def test_after_close_snapshot_is_pinned(self):
        src = self.source(et("2026-10-26 19:00"))
        quote_time = src.get_option_chain("XYZ", date(2026, 10, 30)).quote_time
        # Pinned to the latest option trade of the session (16:14), not the 16:00 stock close.
        self.assertEqual(quote_time, et("2026-10-26 16:14"))

    def test_index_symbols(self):
        self.assertEqual(CboeDelayedSource._cboe_symbol("^SPX"), "_SPX")
        self.assertEqual(CboeDelayedSource._cboe_symbol("MSFT"), "MSFT")


class YFinanceTest(unittest.TestCase):
    def setUp(self):
        try:
            import pandas  # noqa: F401
            from ironcondor.providers.yahoo import YFinanceSource
        except Exception as exc:  # yfinance/pandas missing
            self.skipTest(str(exc))
        self.YFinanceSource = YFinanceSource

    def frame(self, last_trade_utc):
        import pandas as pd
        return pd.DataFrame({
            "strike": [100.0, 105.0],
            "bid": [2.1, float("nan")],
            "ask": [2.3, 0.6],
            "lastPrice": [2.2, 0.55],
            "volume": [float("nan"), 3.0],
            "openInterest": [10.0, 20.0],
            "lastTradeDate": pd.to_datetime([last_trade_utc, "2026-10-26 15:00:00"], utc=True),
        })

    def test_quotes_from_frame(self):
        quotes = self.YFinanceSource._quotes_from_frame(self.frame("2026-10-26 19:59:00"))
        self.assertEqual([q.strike for q in quotes], [100.0, 105.0])
        self.assertIsNone(quotes[1].bid)  # NaN -> None
        self.assertIsNone(quotes[0].volume)

    def test_closing_session(self):
        regular_close = datetime(2026, 10, 26, 16, 0, tzinfo=ET).timestamp()
        raw = SimpleNamespace(calls=self.frame("2026-10-26 20:14:30"), puts=self.frame("2026-10-26 19:59:00"),
                              underlying={"regularMarketTime": regular_close})
        with mock.patch("ironcondor.providers.yahoo.get_now", return_value=et("2026-10-26 19:30")):
            self.assertEqual(self.YFinanceSource._closing_session(raw),
                             datetime(2026, 10, 26, 16, 14, 30, tzinfo=ET))
        with mock.patch("ironcondor.providers.yahoo.get_now", return_value=et("2026-10-26 12:00")):
            self.assertIsNone(self.YFinanceSource._closing_session(raw))


class RegistryTest(unittest.TestCase):
    def test_every_capability_has_a_source(self):
        for capability in CAPABILITIES:
            self.assertTrue(sources_for(capability), capability)

    def test_unknown_source(self):
        with self.assertRaises(DataSourceError):
            create_source("no-such-source")


if __name__ == "__main__":
    unittest.main()
