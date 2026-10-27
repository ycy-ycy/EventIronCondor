import math
import unittest
from datetime import date

from ironcondor.core.atm_iv import (
    atm_forward_ivs,
    choose_expiry_on_or_after,
    choose_quarterly_expiry_9_to_12_months,
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

    def test_quarterly_nine_to_twelve_months(self):
        self.assertEqual(choose_quarterly_expiry_9_to_12_months(self.EXPIRIES, date(2026, 10, 26)), date(2027, 9, 17))


if __name__ == "__main__":
    unittest.main()
