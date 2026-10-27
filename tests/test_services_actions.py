import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock

from ironcondor import actions
from ironcondor.core.timeutils import ET, get_now, get_this_friday, is_quarterly_standard_expiry_date
from ironcondor.providers import registry
from ironcondor.providers.base import OptionSource, PriceSource
from ironcondor.services import MarketData

from tests.helpers import MSFT_INPUTS, synthetic_chain

R = 0.044


def quarterly_expiry_ahead():
    """A standard quarterly expiry 9-12 months from today (what Fetch LT IV looks for)."""
    today = get_now().date()
    day = today + timedelta(days=300)
    while not is_quarterly_standard_expiry_date(day):
        day += timedelta(days=1)
    return day


class FakeSource(PriceSource, OptionSource):
    key = "fake-test"
    label = "Fake"
    spot = 100.0
    pin_one_day_before_expiry = False

    def get_spot(self, symbol):
        return self.spot

    def get_expirations(self, symbol):
        return [get_this_friday(), quarterly_expiry_ahead()]

    def get_option_chain(self, symbol, expiry):
        if expiry == get_this_friday():
            chain = synthetic_chain(100.0, 0.0, R, 1 / 365, lambda k: 0.60,
                                    [90 + 2.5 * i for i in range(9)], expiry=expiry)
            if self.pin_one_day_before_expiry:
                chain.quote_time = datetime.combine(expiry - timedelta(days=1), time(16, 0), tzinfo=ET)
            return chain
        t = (datetime.combine(expiry, time(16, 0), tzinfo=ET) - get_now()).total_seconds() / (365 * 86400)
        return synthetic_chain(100.0, 0.02, R, t, lambda k: 0.45, [80 + 5 * i for i in range(9)],
                               half_spread=0.02, expiry=expiry)


class MarketDataTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(registry._SOURCES, {FakeSource.key: FakeSource})
        patcher.start()
        self.addCleanup(patcher.stop)
        FakeSource.pin_one_day_before_expiry = False
        self.market = MarketData({"price": "fake-test", "option": "fake-test", "rate": "fred"})

    def test_front_week_uses_the_given_time(self):
        data = self.market.front_week_atm_iv("xyz", t_years=1 / 365, r=R)
        self.assertEqual(data["symbol"], "XYZ")
        self.assertIsNone(data["quote_time"])
        self.assertAlmostEqual(data["call_iv"], 60.0, places=6)

    def test_closing_snapshot_pins_time(self):
        FakeSource.pin_one_day_before_expiry = True
        # The box time says 4 days; the quotes are a closing snapshot 1 day before expiry.
        data = self.market.front_week_atm_iv("XYZ", t_years=4 / 365, r=R)
        self.assertAlmostEqual(data["t_years"] * 365, 1.0, places=9)
        self.assertAlmostEqual(data["call_iv"], 60.0, places=6)

    def test_quarterly_lt_iv(self):
        data = self.market.quarterly_atm_iv("XYZ", stock_price=100.0, r=R)
        self.assertAlmostEqual(data["call_iv"], 45.0, delta=0.01)
        self.assertGreater(data["actual_expiry_days"], 270)
        with self.assertRaisesRegex(RuntimeError, "differs from the price"):
            self.market.quarterly_atm_iv("XYZ", stock_price=130.0, r=R)


class FakeMarket:
    def __init__(self):
        self.price_calls = 0

    def latest_price(self, ticker):
        self.price_calls += 1
        return 531.5

    def us1y_yield_percent(self):
        return 4.41

    def front_week_atm_iv(self, ticker, t_years=None, r=0.0):
        return {"symbol": ticker, "source": "Fake", "quote_time": None, "t_years": t_years,
                "actual_expiry": "2026-10-30", "strikes": [530.0, 532.5], "forward": 531.9,
                "implied_price": 531.6, "call_iv": 110.0, "put_iv": 111.0, "call_mid": 9.0, "put_mid": 8.5}


class ActionsTest(unittest.TestCase):
    def test_fetch_open_iv_fills_only_an_empty_price(self):
        market = FakeMarket()
        updates, message = actions.fetch_open_iv(MSFT_INPUTS, market)
        self.assertEqual((updates["atm_call_iv"], updates["atm_put_iv"]), ("110.00", "111.00"))
        self.assertNotIn("open_market_price", updates)
        self.assertIn("K 530/532.5", message)
        updates, _ = actions.fetch_open_iv(dict(MSFT_INPUTS, open_market_price=""), market)
        self.assertEqual(updates["open_market_price"], "531.50")

    def test_update_close_sets_today_and_sim_iv(self):
        tuesday_1015 = datetime(2026, 10, 27, 10, 15, tzinfo=ET)
        with mock.patch("ironcondor.actions.get_now", return_value=tuesday_1015):
            updates, _ = actions.update_close_all(MSFT_INPUTS, FakeMarket())
        self.assertEqual(updates["close_date"], "2026-10-27")
        self.assertEqual((updates["close_hour"], updates["close_minute"]), ("10", "15"))
        self.assertEqual(updates["sim_iv"], "110.5")

    def test_update_close_after_expiry_week_is_an_error(self):
        next_monday = datetime(2026, 11, 2, 10, 0, tzinfo=ET)
        with mock.patch("ironcondor.actions.get_now", return_value=next_monday):
            with self.assertRaisesRegex(ValueError, "expected close date"):
                actions.update_close_all(MSFT_INPUTS, FakeMarket())

    def test_simulate_930(self):
        updates, message = actions.simulate_close_930(MSFT_INPUTS, FakeMarket())
        self.assertEqual((updates["close_hour"], updates["close_minute"], updates["sim_iv"]), ("9", "30", "32.09"))
        self.assertIn("TUE 2026-10-27", message)
        with self.assertRaisesRegex(ValueError, "LT IV is empty"):
            actions.simulate_close_930(dict(MSFT_INPUTS, long_term_call_iv="", long_term_put_iv=""), FakeMarket())
        with self.assertRaisesRegex(ValueError, "expected close date"):
            actions.simulate_close_930(dict(MSFT_INPUTS, close_date="2026-11-03"), FakeMarket())


if __name__ == "__main__":
    unittest.main()
