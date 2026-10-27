import math
import unittest

from ironcondor.core.calculator import (
    SCENARIOS,
    average_iv_text,
    calculate,
    default_close_date,
    get_normal_iv_decimal,
    get_open_iv_decimal,
    split_event_variance,
)
from ironcondor.core.simulation import get_simulation_inputs, pnl_pct_at_time_and_price
from ironcondor.storage import inputs_from_saved

from tests.helpers import CRWV_V21_FILE, MSFT_INPUTS


class GoldenValuesTest(unittest.TestCase):
    """Displayed values for two real trades; any formula change shows up here."""

    def assertOutputs(self, result, expected):
        for name, text in expected.items():
            with self.subTest(name):
                self.assertEqual(result.text[name], text)

    def test_crwv_saved_file(self):
        # Verified against the original single-file app (Earnings.py) before the rewrite. Since
        # v24 both spreads are priced at one IV (the mean of the old call/put ATM IV), so the
        # put/call debit moved slightly; the rest uses the actual 0.73 debit.
        result = calculate(inputs_from_saved(CRWV_V21_FILE))
        self.assertOutputs(result, {
            "implied_move_pct": "14.01%",
            "downside_price": "111.20",
            "upside_price": "147.16",
            "short_put_strike": "121.00",
            "short_call_strike": "135.00",
            "put_debit": "0.3903",
            "call_debit": "0.3392",
            "total_debit": "0.7295",
            "open_downside_breakeven_price": "121.27",
            "open_downside_breakeven_move_pct": "(5.34%)",
            "open_upside_breakeven_price": "134.73",
            "open_upside_breakeven_move_pct": "5.19%",
            "exp_implied_move_pct": "14.67%",
            "close_day": "FRI",
            "close_price_change_pct": "(9.78%)",
            "put_credit": "0.9798",
            "call_credit": "0.0000",
            "total_credit": "0.9798",
            "pnl_dollar": "0.2498",
            "pnl_pct": "34.22%",
            "sim_downside_breakeven_price": "119.85",
            "sim_upside_breakeven_price": "136.41",
            "scenario_downside_pnl_pct": "36.98%",
            "scenario_middle_price": "128.00",
            "scenario_middle_pnl_pct": "(96.55%)",
        })

    def test_msft_screenshot(self):
        # Read off a screenshot of the running app. Since v24 both spreads are priced at one IV
        # (the mean of the screenshot's 62.71 / 62.98), so the debit and the values built on it
        # moved slightly; the normal IV, log IM and prices are the screenshot's.
        result = calculate(MSFT_INPUTS)
        self.assertOutputs(result, {
            "normal_iv_pct": "32.09%",
            "implied_move_pct": "5.70%",
            "downside_price": "502.66",
            "upside_price": "563.31",
            "long_put_move_pct": "(4.25%)",
            "long_call_move_pct": "3.30%",
            "short_put_move_pct": "(8.25%)",
            "short_call_move_pct": "6.88%",
            "put_debit": "3.6720",
            "call_debit": "4.3151",
            "total_debit": "7.9872",
            "open_downside_breakeven_price": "502.01",
            "open_upside_breakeven_price": "557.99",
            "exp_implied_move_pct": "6.63%",
            "exp_prob50_move_pct": "4.47%",
            "exp_long_call_itm_prob": "29.99%",
            "exp_long_put_itm_prob": "26.92%",
            "exp_breakeven_call_prob": "22.90%",
            "exp_breakeven_put_prob": "19.67%",
            "exp_short_call_itm_prob": "14.37%",
            "exp_short_put_itm_prob": "11.14%",
            "close_day": "TUE",
            "close_price_change_pct": "(0.04%)",
            "put_credit": "0.5665",
            "call_credit": "1.0875",
            "total_credit": "1.6541",
            "pnl_dollar": "(6.3331)",
            "pnl_pct": "(79.29%)",
            "sim_downside_breakeven_price": "504.19",
            "sim_downside_breakeven_move_pct": "(5.39%)",
            "sim_upside_breakeven_price": "555.42",
            "sim_upside_breakeven_move_pct": "4.29%",
            "scenario_downside_credit": "8.7128",
            "scenario_downside_pnl_pct": "9.08%",
            "scenario_middle_pnl_dollar": "(6.3990)",
            "scenario_upside_pnl_dollar": "3.4621",
        })

    def test_tones(self):
        result = calculate(MSFT_INPUTS)
        self.assertLess(result.tone["pnl_dollar"], 0)
        self.assertGreater(result.tone["scenario_upside_pnl_pct"], 0)
        self.assertLess(result.tone["open_downside_breakeven_move_pct"], 0)


class CloseDateTest(unittest.TestCase):
    def test_close_weekday_follows_the_date(self):
        for close_date, weekday in (("2026-10-26", "MON"), ("2026-10-28", "WED"), ("2026-10-30", "FRI")):
            self.assertEqual(calculate(dict(MSFT_INPUTS, close_date=close_date)).text["close_day"], weekday)

    def test_unusable_dates_blank_the_close_side(self):
        # Before the open, a weekend, after the Friday expiry, unparsable.
        for close_date in ("2026-10-23", "2026-10-31", "2026-11-02", "soon"):
            with self.subTest(close_date):
                result = calculate(dict(MSFT_INPUTS, close_date=close_date))
                self.assertEqual(result.text["close_day"], "n/a")
                self.assertEqual(result.text["total_credit"], "")
                self.assertEqual(result.text["scenario_middle_credit"], "")

    def test_blank_date(self):
        result = calculate(dict(MSFT_INPUTS, close_date=""))
        self.assertEqual(result.text["close_day"], "")
        self.assertEqual(result.text["pnl_pct"], "")

    def test_later_close_day_lowers_the_credit(self):
        tuesday = calculate(MSFT_INPUTS).theoretical_close_credit
        thursday = calculate(dict(MSFT_INPUTS, close_date="2026-10-29")).theoretical_close_credit
        self.assertLess(thursday, tuesday)

    def test_default_close_date(self):
        self.assertEqual(default_close_date("2026-05-07"), "2026-05-08")
        self.assertEqual(default_close_date("2026-05-08"), "2026-05-11")
        self.assertEqual(default_close_date(""), "")


class ConsistencyTest(unittest.TestCase):
    def test_implied_move_ignores_the_close_time(self):
        with_time = calculate(MSFT_INPUTS).text["implied_move_pct"]
        without = calculate(dict(MSFT_INPUTS, close_hour="", close_minute="")).text["implied_move_pct"]
        self.assertEqual(with_time, without)

    def test_plot_matches_the_panel(self):
        result = calculate(MSFT_INPUTS)
        sim = get_simulation_inputs(MSFT_INPUTS, result.theoretical_open_debit)
        self.assertEqual(f"{sim['implied_move'] * 100:.2f}%", result.text["implied_move_pct"])
        # The plot's 09:30 P&L at the strike scenarios equals the scenario table.
        levels = {"short_put": sim["short_put"], "long_put": sim["long_put"],
                  "long_call": sim["long_call"], "short_call": sim["short_call"]}
        for key, _ in SCENARIOS:
            if key in levels:
                pct = pnl_pct_at_time_and_price(levels[key], 9.5, sim)
                shown = result.text[f"scenario_{key}_pnl_pct"]
                expected = f"({abs(pct):.2f}%)" if pct < 0 else f"{pct:.2f}%"
                self.assertEqual(shown, expected, key)

    def test_average_iv_text(self):
        self.assertEqual(average_iv_text("70.10", "71.20"), "70.65")
        self.assertEqual(average_iv_text("", "71.2"), "71.2")
        self.assertEqual(average_iv_text("57.01", "56.76"), "56.885")
        self.assertEqual(average_iv_text("", ""), "")


class EventSplitTest(unittest.TestCase):
    def test_recovers_normal_variance_and_jump(self):
        t_front, t_month = 3 / 365, 24 / 365
        front_iv = math.sqrt(0.09 + 0.004 / t_front)
        monthly_iv = math.sqrt(0.09 + 0.004 / t_month)
        normal_var, jump = split_event_variance(front_iv, t_front, monthly_iv, t_month)
        self.assertAlmostEqual(normal_var, 0.09, places=12)
        self.assertAlmostEqual(jump, 0.004, places=12)
        # Normal variance + J / T gives both expiries' IVs back.
        self.assertAlmostEqual(normal_var + jump / t_front, front_iv ** 2, places=12)
        self.assertAlmostEqual(normal_var + jump / t_month, monthly_iv ** 2, places=12)

    def test_odd_term_structures_come_out_negative(self):
        self.assertLess(split_event_variance(1.10, 3 / 365, 0.30, 24 / 365)[0], 0)
        self.assertLess(split_event_variance(0.35, 3 / 365, 0.40, 24 / 365)[1], 0)
        with self.assertRaises(ValueError):
            split_event_variance(0.60, 24 / 365, 0.40, 3 / 365)


class HolidayWeekTest(unittest.TestCase):
    """Good Friday week: the weekly expires Thursday, and everything is priced to it."""

    def setUp(self):
        self.thursday_week = dict(MSFT_INPUTS, weekly_expiry="THU 2026-10-29")

    def test_open_is_priced_to_thursday(self):
        # A day less to go at the open.
        self.assertLess(calculate(self.thursday_week).theoretical_open_debit, calculate(MSFT_INPUTS).theoretical_open_debit)

    def test_close_date_ends_on_thursday(self):
        self.assertEqual(calculate(dict(self.thursday_week, close_date="2026-10-29")).text["close_day"], "THU")
        self.assertEqual(calculate(dict(self.thursday_week, close_date="2026-10-30")).text["close_day"], "n/a")

    def test_close_and_plot_are_priced_to_thursday(self):
        friday, thursday = calculate(MSFT_INPUTS), calculate(self.thursday_week)
        self.assertNotEqual(thursday.text["total_credit"], friday.text["total_credit"])
        sim = get_simulation_inputs(self.thursday_week, thursday.theoretical_open_debit)
        self.assertEqual(sim["expiry_day"], "THU")
        pct = pnl_pct_at_time_and_price(sim["short_put"], 9.5, sim)
        self.assertEqual(thursday.text["scenario_short_put_pnl_pct"], f"({abs(pct):.2f}%)" if pct < 0 else f"{pct:.2f}%")


class OpenIvTest(unittest.TestCase):
    def test_iv_row_gives_this_fridays_iv_at_the_open(self):
        # The open time is the quote time here, so this Friday's IV comes straight back.
        self.assertAlmostEqual(get_open_iv_decimal(MSFT_INPUTS) * 100, 62.845, places=4)
        self.assertAlmostEqual(get_normal_iv_decimal(MSFT_INPUTS) * 100, 32.09, places=4)
        self.assertIsNone(get_open_iv_decimal(dict(MSFT_INPUTS, monthly_iv="")))
        # Odd term structure (the weekly below the monthly): no normal IV, no debit.
        odd = calculate(dict(MSFT_INPUTS, weekly_iv="35"))
        self.assertEqual((odd.text["normal_iv_pct"], odd.text["implied_move_pct"], odd.text["total_debit"]), ("", "", ""))

    def test_t_runs_from_the_quote_time(self):
        later_quote = dict(MSFT_INPUTS, iv_quote_time="2026-10-27 14:39")
        self.assertNotEqual(get_normal_iv_decimal(later_quote), get_normal_iv_decimal(MSFT_INPUTS))
        # The open time boxes don't touch the normal IV or the move.
        thursday = dict(MSFT_INPUTS, open_date="2026-10-29", open_day="THU")
        self.assertEqual(get_normal_iv_decimal(thursday), get_normal_iv_decimal(MSFT_INPUTS))

    def test_later_open_raises_the_iv_but_not_the_move(self):
        thursday = dict(MSFT_INPUTS, open_date="2026-10-29", open_day="THU")
        self.assertGreater(get_open_iv_decimal(thursday), get_open_iv_decimal(MSFT_INPUTS))
        self.assertEqual(calculate(thursday).text["implied_move_pct"], calculate(MSFT_INPUTS).text["implied_move_pct"])
        # Same jump, less normal variance left: a cheaper debit.
        self.assertLess(calculate(thursday).theoretical_open_debit, calculate(MSFT_INPUTS).theoretical_open_debit)


if __name__ == "__main__":
    unittest.main()
