import math
import unittest
from datetime import date, datetime, time, timedelta
from unittest import mock

from ironcondor import actions
from ironcondor.core.calculator import calculate
from ironcondor.core.timeutils import ET, get_now, get_this_friday, third_friday
from ironcondor.providers import registry
from ironcondor.providers.base import OptionSource, PriceSource
from ironcondor.services import MarketData

from tests.helpers import MSFT_INPUTS, synthetic_chain

R = 0.044


def monthly_expiries_ahead():
    """The next few third Fridays, so the 21~56-day window always holds one."""
    today = get_now().date()
    months = [(today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1) for k in range(5)]
    return [day for day in (third_friday(y, m) for y, m in months) if day > today]


class FakeSource(PriceSource, OptionSource):
    key = "fake-test"
    label = "Fake"
    spot = 100.0
    pin_one_day_before_expiry = False

    def get_spot(self, symbol):
        return self.spot

    def get_expirations(self, symbol):
        return [get_this_friday(), *monthly_expiries_ahead()]

    def get_option_chain(self, symbol, expiry):
        # A closing snapshot pins every chain to 16:00 the day before this Friday.
        pinned = None
        if self.pin_one_day_before_expiry:
            pinned = datetime.combine(get_this_friday() - timedelta(days=1), time(16, 0), tzinfo=ET)
        if expiry == get_this_friday():
            chain = synthetic_chain(100.0, 0.0, R, 1 / 365, lambda k: 0.60,
                                    [90 + 2.5 * i for i in range(9)], expiry=expiry)
        else:
            t = (datetime.combine(expiry, time(16, 0), tzinfo=ET) - (pinned or get_now())).total_seconds() / (365 * 86400)
            chain = synthetic_chain(100.0, 0.02, R, t, lambda k: 0.45, [80 + 5 * i for i in range(9)],
                                    half_spread=0.02, expiry=expiry)
        chain.quote_time = pinned
        return chain


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

    def test_event_ivs_after_the_close(self):
        # A closing snapshot the day before this Friday: both T run from its 16:00 close.
        FakeSource.pin_one_day_before_expiry = True
        data = self.market.event_atm_ivs("XYZ", stock_price=100.0, r=R)
        self.assertEqual(data["quote_time"], datetime.combine(get_this_friday() - timedelta(days=1), time(16, 0), tzinfo=ET))
        self.assertTrue(data["closing_snapshot"])
        self.assertAlmostEqual(data["weekly"]["t_years"] * 365, 1.0, places=9)
        self.assertAlmostEqual(data["weekly"]["call_iv"], 60.0, places=6)
        self.assertAlmostEqual(data["monthly"]["put_iv"], 45.0, delta=0.01)
        self.assertTrue(21 <= data["monthly"]["actual_expiry_days"] <= 56)
        with self.assertRaisesRegex(RuntimeError, "differs from the price"):
            self.market.event_atm_ivs("XYZ", stock_price=130.0, r=R)

    def test_event_ivs_live_quote_time_is_now_to_the_minute(self):
        thursday = datetime.combine(get_this_friday() - timedelta(days=1), time(16, 0, 30), tzinfo=ET)
        with mock.patch("ironcondor.services.get_now", return_value=thursday):
            data = self.market.event_atm_ivs("XYZ", stock_price=100.0, r=R)
        self.assertEqual(data["quote_time"], thursday.replace(second=0))
        self.assertFalse(data["closing_snapshot"])
        self.assertAlmostEqual(data["weekly"]["call_iv"], 60.0, places=6)


class FakeMarket:
    # ATM call/put IV (%) at the 2026-10-27 16:00 close: the weekly 3 days out, the monthly 24.
    weekly_iv = (110.0, 111.0)
    monthly_iv = (40.0, 40.0)

    def __init__(self):
        self.price_calls = 0

    def latest_price(self, ticker):
        self.price_calls += 1
        return 531.5

    def us1y_yield_percent(self):
        return 4.41

    def front_week_atm_iv(self, ticker, t_years=None, r=0.0, expiry=None):
        self.close_request = (t_years, expiry)
        return {"symbol": ticker, "source": "Fake", "quote_time": None, "t_years": t_years,
                "actual_expiry": "2026-10-30", "strikes": [530.0, 532.5], "forward": 531.9,
                "implied_price": 531.6, "call_iv": 110.0, "put_iv": 111.0, "call_mid": 9.0, "put_mid": 8.5}

    def event_atm_ivs(self, ticker, stock_price=None, r=0.0):
        def leg(expiry, days, ivs):
            return {"actual_expiry": expiry, "t_years": days / 365, "strikes": [530.0, 532.5], "forward": 531.9,
                    "implied_price": 531.5, "call_iv": ivs[0], "put_iv": ivs[1], "call_mid": 9.0, "put_mid": 8.5}
        return {"symbol": ticker, "source": "Fake", "stock_price": stock_price or 531.5,
                "quote_time": datetime(2026, 10, 27, 16, 0, tzinfo=ET), "closing_snapshot": True,
                "weekly": leg("2026-10-30", 3, self.weekly_iv),
                "monthly": dict(leg("2026-11-20", 24, self.monthly_iv), actual_expiry_days=24)}


class ActionsTest(unittest.TestCase):
    def test_update_open_sets_the_time_and_price_then_fetches_the_ivs(self):
        tuesday_1015 = datetime(2026, 10, 27, 10, 15, tzinfo=ET)
        with mock.patch("ironcondor.core.timeutils.get_now", return_value=tuesday_1015):
            updates, message = actions.update_open_all(MSFT_INPUTS, FakeMarket())
        self.assertEqual(updates, {"open_date": "2026-10-27", "open_day": "TUE", "open_hour": "10",
                                   "open_minute": "15", "open_market_price": "531.50",
                                   "iv_quote_time": "2026-10-27 16:00", "weekly_expiry": "FRI 2026-10-30",
                                   "monthly_expiry": "FRI 2026-11-20", "open_us1y": "4.41",
                                   "weekly_iv": "110.50", "monthly_iv": "40.00"})
        self.assertIn("normal IV", message)

    def test_update_close_sets_today_and_sim_iv(self):
        tuesday_1015 = datetime(2026, 10, 27, 10, 15, tzinfo=ET)
        with mock.patch("ironcondor.actions.get_now", return_value=tuesday_1015):
            updates, _ = actions.update_close_all(MSFT_INPUTS, FakeMarket())
        self.assertEqual(updates["close_date"], "2026-10-27")
        self.assertEqual((updates["close_hour"], updates["close_minute"]), ("10", "15"))
        self.assertEqual(updates["sim_iv"], "110.5")

    def test_close_iv_reads_the_positions_weekly(self):
        # Good Friday week: the weekly expires Thursday 16:00, a day after this Wednesday 16:00 close.
        market = FakeMarket()
        actions.fetch_close_iv(dict(MSFT_INPUTS, weekly_expiry="THU 2026-10-29", close_date="2026-10-28",
                                    close_hour="16", close_minute="00"), market)
        t_years, expiry = market.close_request
        self.assertAlmostEqual(t_years * 365, 1.0, places=9)
        self.assertEqual(expiry, date(2026, 10, 29))

    def test_update_close_after_expiry_week_is_an_error(self):
        next_monday = datetime(2026, 11, 2, 10, 0, tzinfo=ET)
        with mock.patch("ironcondor.actions.get_now", return_value=next_monday):
            with self.assertRaisesRegex(ValueError, "expected close date"):
                actions.update_close_all(MSFT_INPUTS, FakeMarket())

    def open_ivs(self, weekly_iv, monthly_iv, **boxes):
        """The open IV fetch with quotes 3 days before the weekly and 24 days before the monthly."""
        market = FakeMarket()
        market.weekly_iv, market.monthly_iv = weekly_iv, monthly_iv
        return actions.fetch_open_ivs(dict(MSFT_INPUTS, **boxes), market)

    def test_fetch_open_ivs(self):
        # Normal IV 30% plus a 0.004 jump in both expiries; call and put IV average out.
        def iv(days):
            return 100 * math.sqrt(0.09 + 0.004 / (days / 365))
        # The open boxes say THU 15:00 and a 0% rate: T runs from the quote time, r is fetched.
        updates, message = self.open_ivs((iv(3) - 1, iv(3) + 1), (iv(24),) * 2,
                                         open_day="THU", open_hour="15", open_minute="00", open_us1y="")
        self.assertEqual(updates, {"iv_quote_time": "2026-10-27 16:00", "weekly_expiry": "FRI 2026-10-30",
                                   "monthly_expiry": "FRI 2026-11-20", "open_us1y": "4.41",
                                   "weekly_iv": f"{iv(3):.2f}", "monthly_iv": f"{iv(24):.2f}"})
        self.assertIn("(closing snapshot)", message)
        self.assertIn("(3.000 d), the 24-day monthly", message)
        # The open panel solves the filled boxes back to the normal IV and the jump.
        result = calculate(dict(MSFT_INPUTS, **updates))
        self.assertEqual((result.text["normal_iv_pct"], result.text["implied_move_pct"]), ("30.00%", "6.32%"))
        # An empty price is filled.
        updates, _ = self.open_ivs((iv(3),) * 2, (iv(24),) * 2, open_market_price="")
        self.assertEqual(updates["open_market_price"], "531.50")

    def test_fetch_open_ivs_odd_term_structure_is_an_error(self):
        # Front total variance 1.1^2 x 3d is above the monthly's 0.3^2 x 24d.
        with self.assertRaisesRegex(ValueError, "Odd term structure, nothing filled.*total variance.*normal variance is -"):
            self.open_ivs((110.0, 110.0), (30.0, 30.0))
        # Front IV below the monthly IV, so the jump comes out negative.
        with self.assertRaisesRegex(ValueError, "Odd term structure, nothing filled.*below the monthly.*jump variance is -"):
            self.open_ivs((35.0, 35.0), (40.0, 40.0))

    def test_simulate_930(self):
        updates, message = actions.simulate_close_930(MSFT_INPUTS, FakeMarket())
        self.assertEqual((updates["close_hour"], updates["close_minute"], updates["sim_iv"]), ("9", "30", "32.09"))
        self.assertIn("TUE 2026-10-27", message)
        with self.assertRaisesRegex(ValueError, "LT IV is empty"):
            actions.simulate_close_930(dict(MSFT_INPUTS, weekly_iv=""), FakeMarket())
        with self.assertRaisesRegex(ValueError, "expected close date"):
            actions.simulate_close_930(dict(MSFT_INPUTS, close_date="2026-11-03"), FakeMarket())


if __name__ == "__main__":
    unittest.main()
