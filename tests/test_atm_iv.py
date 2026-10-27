import math
import unittest
from datetime import date

from ironcondor.core.atm_iv import (
    atm_forward_ivs,
    choose_expiry_on_or_after,
    choose_monthly_expiry_21_to_56_days,
    choose_weekly_expiry,
)
from ironcondor.providers.base import OptionChain, OptionQuote

from tests.helpers import synthetic_chain, true_forward

R = 0.044
T_FRONT = 4 / 365
T_LT = 0.9
FRONT_STRIKES = [80 + 2.5 * i for i in range(17)]
LT_STRIKES = [70 + 5 * i for i in range(13)]


class ForwardIvTest(unittest.TestCase):
    def test_flat_iv_recovered_without_stock_price(self):
        # Dividend 3%: the forward absorbs it, so no stock price or q is needed.
        for spot in (100.0, 101.3, 98.85):
            chain = synthetic_chain(spot, 0.03, R, T_FRONT, lambda k: 0.60, FRONT_STRIKES)
            result = atm_forward_ivs(chain, T_FRONT, R)
            self.assertAlmostEqual(result["call_iv"], 60.0, places=6)
            self.assertAlmostEqual(result["put_iv"], 60.0, places=6)
            self.assertAlmostEqual(result["forward"], true_forward(spot, 0.03, R, T_FRONT), places=6)
            self.assertLessEqual(len(result["strikes"]), 2)

    def test_high_rate_long_time(self):
        # r 12%, T 1.5 y: the put above F is worth less than K - F e^(-rT) and must still solve.
        chain = synthetic_chain(100.0, 0.0, 0.12, 1.5, lambda k: 0.30, [80 + 5 * i for i in range(13)])
        result = atm_forward_ivs(chain, 1.5, 0.12)
        self.assertAlmostEqual(result["call_iv"], 30.0, places=6)
        self.assertAlmostEqual(result["put_iv"], 30.0, places=6)

    def test_uses_strikes_around_the_forward(self):
        chain = synthetic_chain(101.3, 0.0, R, T_FRONT, lambda k: 0.60, FRONT_STRIKES)
        self.assertEqual(atm_forward_ivs(chain, T_FRONT, R)["strikes"], [100.0, 102.5])

    def test_skew_is_interpolated_to_the_forward(self):
        forward = true_forward(101.3, 0.0, R, T_FRONT)
        chain = synthetic_chain(101.3, 0.0, R, T_FRONT, lambda k: 0.60 - 0.8 * math.log(k / forward), FRONT_STRIKES)
        result = atm_forward_ivs(chain, T_FRONT, R)
        self.assertAlmostEqual(result["call_iv"], 60.0, delta=0.05)
        self.assertAlmostEqual(result["put_iv"], 60.0, delta=0.05)

    def test_call_and_put_agree_with_noisy_quotes(self):
        chain = synthetic_chain(100.0, 0.0, R, T_FRONT, lambda k: 0.60, FRONT_STRIKES, half_spread=0.03)
        result = atm_forward_ivs(chain, T_FRONT, R)
        self.assertLess(abs(result["call_iv"] - result["put_iv"]), 0.5)

    def test_no_common_strike_is_an_error(self):
        chain = OptionChain(
            expiry=date(2026, 10, 30),
            calls=[OptionQuote(strike=100, bid=1.0, ask=1.1)],
            puts=[OptionQuote(strike=105, bid=1.0, ask=1.1)],
        )
        with self.assertRaises(RuntimeError):
            atm_forward_ivs(chain, T_FRONT, R)

    def test_last_trade_fallback_only_outside_strict_mode(self):
        quotes = synthetic_chain(100.0, 0.0, R, T_LT, lambda k: 0.45, LT_STRIKES)
        no_bid_ask = OptionChain(
            expiry=quotes.expiry,
            calls=[OptionQuote(strike=q.strike, last=q.last, volume=5) for q in quotes.calls],
            puts=[OptionQuote(strike=q.strike, last=q.last, volume=5) for q in quotes.puts],
        )
        self.assertAlmostEqual(atm_forward_ivs(no_bid_ask, T_LT, R)["call_iv"], 45.0, places=4)
        with self.assertRaises(RuntimeError):
            atm_forward_ivs(no_bid_ask, T_LT, R, strict=True, stock_price=100.0)


class StrictLtIvTest(unittest.TestCase):
    def lt_chain(self, q, half_spread=0.02, volume=10):
        return synthetic_chain(100.0, q, R, T_LT, lambda k: 0.45, LT_STRIKES, half_spread=half_spread, volume=volume)

    def test_dividend_and_borrow_cost_are_accepted(self):
        for q in (0.05, -0.015):  # implied price -4.4% / +1.4% vs the box
            result = atm_forward_ivs(self.lt_chain(q), T_LT, R, strict=True, stock_price=100.0)
            self.assertAlmostEqual(result["call_iv"], 45.0, places=4)

    def test_implied_price_gap_over_limit_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "differs from the price"):
            atm_forward_ivs(self.lt_chain(0.14), T_LT, R, strict=True, stock_price=100.0)
        with self.assertRaisesRegex(RuntimeError, "differs from the price"):
            atm_forward_ivs(self.lt_chain(0.0), T_LT, R, strict=True, stock_price=125.0)

    def test_wide_or_dead_quotes_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "spread too wide"):
            atm_forward_ivs(self.lt_chain(0.0, half_spread=0.5), T_LT, R, strict=True, stock_price=100.0)
        with self.assertRaisesRegex(RuntimeError, "zero volume"):
            dead = self.lt_chain(0.0, volume=0)
            dead = OptionChain(
                expiry=dead.expiry,
                calls=[OptionQuote(q.strike, q.bid, q.ask, q.last, 0, 0) for q in dead.calls],
                puts=[OptionQuote(q.strike, q.bid, q.ask, q.last, 0, 0) for q in dead.puts],
            )
            atm_forward_ivs(dead, T_LT, R, strict=True, stock_price=100.0)


class ExpiryChoiceTest(unittest.TestCase):
    EXPIRIES = [date(2026, 10, 30), date(2026, 11, 6), date(2026, 11, 20), date(2027, 6, 17),
                date(2027, 7, 16), date(2027, 9, 17), date(2027, 12, 17), date(2028, 1, 21)]

    def test_on_or_after(self):
        self.assertEqual(choose_expiry_on_or_after(self.EXPIRIES, date(2026, 10, 30)), date(2026, 10, 30))
        self.assertEqual(choose_expiry_on_or_after(self.EXPIRIES, date(2026, 11, 1)), date(2026, 11, 6))
        self.assertEqual(choose_expiry_on_or_after(self.EXPIRIES, date(2029, 1, 1)), date(2028, 1, 21))

    def test_weekly_is_the_friday_never_the_nearest(self):
        # Monday and Wednesday expiries may come before the earnings: the Friday is the weekly.
        mon_wed_fri = [date(2026, 10, 26), date(2026, 10, 28), date(2026, 10, 30), date(2026, 11, 2)]
        self.assertEqual(choose_weekly_expiry(mon_wed_fri, date(2026, 10, 27)), date(2026, 10, 30))
        # On a weekend it is next week's.
        self.assertEqual(choose_weekly_expiry([date(2026, 10, 30), date(2026, 11, 6)], date(2026, 10, 31)),
                         date(2026, 11, 6))

    def test_weekly_thursday_only_when_the_friday_is_not_listed(self):
        # Good Friday 2027-03-26: the weekly expires Thursday 03-25, not the next Friday.
        good_friday = [date(2027, 3, 24), date(2027, 3, 25), date(2027, 4, 2)]
        self.assertEqual(choose_weekly_expiry(good_friday, date(2027, 3, 22)), date(2027, 3, 25))
        # Dailies with the Friday listed: the Friday.
        dailies = [date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)]
        self.assertEqual(choose_weekly_expiry(dailies, date(2026, 10, 27)), date(2026, 10, 30))
        # Only a Wednesday this week: no weekly, not the Wednesday.
        with self.assertRaisesRegex(RuntimeError, "No weekly expiry is listed this week"):
            choose_weekly_expiry([date(2026, 10, 28), date(2026, 11, 6)], date(2026, 10, 27))

    MONTHLY = [date(2026, 10, 30), date(2026, 11, 6), date(2026, 11, 13), date(2026, 11, 20),
               date(2026, 11, 27), date(2026, 12, 18), date(2027, 1, 15)]

    def test_monthly_21_to_56_days_takes_the_earlier_of_two(self):
        # 2026-10-27: Nov 20 is 24 days out, Dec 18 is 52; weeklies don't count.
        self.assertEqual(choose_monthly_expiry_21_to_56_days(self.MONTHLY, date(2026, 10, 27)), date(2026, 11, 20))
        # Nov 20 is 20 days out on 10-31, so Dec 18 (48 days).
        self.assertEqual(choose_monthly_expiry_21_to_56_days(self.MONTHLY, date(2026, 10, 31)), date(2026, 12, 18))

    def test_monthly_window_includes_both_ends(self):
        self.assertEqual(choose_monthly_expiry_21_to_56_days(self.MONTHLY, date(2026, 10, 30)), date(2026, 11, 20))
        only_december = [date(2026, 10, 30), date(2026, 12, 18)]
        self.assertEqual(choose_monthly_expiry_21_to_56_days(only_december, date(2026, 10, 23)), date(2026, 12, 18))
        with self.assertRaisesRegex(RuntimeError, "No standard monthly expiry 21~56 days out"):
            choose_monthly_expiry_21_to_56_days(only_december, date(2026, 10, 22))

    def test_monthly_thursday_only_for_a_holiday_friday(self):
        # June 19, 2026 (third Friday) is Juneteenth: the monthly is Thursday June 18.
        juneteenth = [date(2026, 6, 12), date(2026, 6, 18), date(2026, 6, 26), date(2026, 7, 17)]
        self.assertEqual(choose_monthly_expiry_21_to_56_days(juneteenth, date(2026, 5, 20)), date(2026, 6, 18))
        # With daily expiries the Thursday before a listed third Friday is not the monthly.
        dailies = [date(2026, 11, 19), date(2026, 11, 20), date(2026, 12, 17), date(2026, 12, 18)]
        self.assertEqual(choose_monthly_expiry_21_to_56_days(dailies, date(2026, 10, 27)), date(2026, 11, 20))


if __name__ == "__main__":
    unittest.main()
