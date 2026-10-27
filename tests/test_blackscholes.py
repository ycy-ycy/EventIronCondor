import math
import unittest

from ironcondor.core.blackscholes import (
    bs_itm_probability,
    bs_price,
    log_move_pct,
    price_from_log_move,
    solve_iv_from_option_mid,
)


class BlackScholesTest(unittest.TestCase):
    def test_put_call_parity(self):
        s, k, t, r, iv, q = 100.0, 95.0, 0.25, 0.04, 0.35, 0.02
        call = bs_price(s, k, t, r, iv, "call", q=q)
        put = bs_price(s, k, t, r, iv, "put", q=q)
        self.assertAlmostEqual(call - put, s * math.exp(-q * t) - k * math.exp(-r * t), places=10)

    def test_expiry_is_intrinsic(self):
        self.assertEqual(bs_price(110, 100, 0.0, 0.04, 0.5, "call"), 10.0)
        self.assertEqual(bs_price(110, 100, 0.0, 0.04, 0.5, "put"), 0.0)

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            bs_price(100, 100, 0.1, 0.0, 0.0, "call")
        with self.assertRaises(ValueError):
            bs_price(100, 100, 0.1, 0.0, 0.3, "straddle")

    def test_iv_round_trip(self):
        for option_type in ("call", "put"):
            for strike in (80, 100, 120):
                price = bs_price(100, strike, 4 / 365, 0.044, 0.9, option_type)
                iv = solve_iv_from_option_mid(100, strike, 4 / 365, 0.044, option_type, price)
                self.assertAlmostEqual(iv, 0.9, places=6, msg=f"{option_type} {strike}")

    def test_price_below_intrinsic_is_rejected(self):
        with self.assertRaises(RuntimeError):
            solve_iv_from_option_mid(100, 90, 0.1, 0.0, "call", 5.0)

    def test_deep_itm_below_plain_intrinsic_still_solves(self):
        # High rate, long time: the European put is worth 14.38, under K - S = 20.
        price = bs_price(80, 100, 2.0, 0.08, 0.25, "put")
        self.assertLess(price, 20.0)
        self.assertAlmostEqual(solve_iv_from_option_mid(80, 100, 2.0, 0.08, "put", price), 0.25, places=6)
        # Dividends do the same to a call: worth less than S - K.
        price = bs_price(100, 80, 2.0, 0.0, 0.2, "call", q=0.06)
        self.assertLess(price, 20.0)
        self.assertAlmostEqual(solve_iv_from_option_mid(100, 80, 2.0, 0.0, "call", price, q=0.06), 0.2, places=6)
        # Below the discounted intrinsic is still an arbitrage and still rejected.
        with self.assertRaisesRegex(RuntimeError, "below the discounted intrinsic"):
            solve_iv_from_option_mid(80, 100, 2.0, 0.08, "put", 5.0)

    def test_itm_probabilities_sum_to_one(self):
        call = bs_itm_probability(100, 105, 0.1, 0.04, 0.5, "call")
        put = bs_itm_probability(100, 105, 0.1, 0.04, 0.5, "put")
        self.assertAlmostEqual(call + put, 1.0, places=12)

    def test_log_move_round_trip(self):
        self.assertAlmostEqual(log_move_pct(100, price_from_log_move(100, 0.1)), 10.0, places=10)


if __name__ == "__main__":
    unittest.main()
