import unittest
from datetime import date, datetime

from ironcondor.core.timeutils import (
    ET,
    closed_session_quote_time,
    get_this_friday,
    get_weekday_name,
    next_weekday,
    parse_date_text,
    time_to_friday_4pm_years,
)


def et(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET) if text else None


class TimeToExpiryTest(unittest.TestCase):
    def test_monday_close_to_friday_close_is_four_days(self):
        self.assertAlmostEqual(time_to_friday_4pm_years("MON", "16", "00") * 365, 4.0, places=12)

    def test_after_friday_close_raises(self):
        with self.assertRaises(ValueError):
            time_to_friday_4pm_years("FRI", "16", "01")

    def test_bad_time_raises(self):
        for hour, minute in (("24", "00"), ("9", "60"), ("", "30")):
            with self.assertRaises(ValueError):
                time_to_friday_4pm_years("TUE", hour, minute)


class DateHelpersTest(unittest.TestCase):
    def test_parse_date_text(self):
        for text in ("2026-05-08", "2026/05/08", "20260508", " 2026-05-08 "):
            self.assertEqual(parse_date_text(text), date(2026, 5, 8))
        self.assertIsNone(parse_date_text("garbage"))
        self.assertIsNone(parse_date_text(""))

    def test_weekdays(self):
        self.assertEqual(get_weekday_name(date(2026, 5, 8)), "FRI")
        self.assertIsNone(get_weekday_name(date(2026, 5, 9)))
        self.assertEqual(next_weekday(date(2026, 5, 8)), date(2026, 5, 11))
        self.assertEqual(get_this_friday(date(2026, 5, 6)), date(2026, 5, 8))


class ClosedSessionQuoteTimeTest(unittest.TestCase):
    # (data time, last regular stock trade, last option trade, expected pin or None)
    CASES = [
        ("intraday", "2026-10-26 13:45:00", "2026-10-26 13:44:58", "2026-10-26 13:44:50", None),
        ("16:05 wall clock, data still 15:50", "2026-10-26 15:50:00", "2026-10-26 15:49:59", "2026-10-26 15:49:58", None),
        ("after close, stock options", "2026-10-26 16:09:00", "2026-10-26 15:59:59", "2026-10-26 15:59:55", "2026-10-26 16:00:00"),
        ("ETF options trade to 16:15", "2026-10-26 19:00:00", "2026-10-26 16:00:00", "2026-10-26 16:14:59", "2026-10-26 16:14:59"),
        ("bad late trade time capped", "2026-10-26 19:00:00", "2026-10-26 15:59:59", "2026-10-26 17:30:00", "2026-10-26 16:15:00"),
        ("illiquid, last trade 13:00", "2026-10-26 19:00:00", "2026-10-26 15:59:59", "2026-10-26 13:00:00", "2026-10-26 16:00:00"),
        ("no option trade time", "2026-10-26 19:00:00", "2026-10-26 15:59:59", None, "2026-10-26 16:00:00"),
        ("next pre-market", "2026-10-27 08:00:00", "2026-10-26 16:00:00", "2026-10-26 16:14:59", "2026-10-26 16:14:59"),
        ("09:31 wall clock, live stock time newer than data", "2026-10-27 09:16:00", "2026-10-27 09:31:02",
         "2026-10-26 15:59:58", "2026-10-26 16:00:00"),
        ("Saturday", "2026-10-31 12:00:00", "2026-10-30 15:59:59", "2026-10-30 15:59:59", "2026-10-30 16:00:00"),
        ("holiday", "2026-11-26 11:00:00", "2026-11-25 15:59:59", "2026-11-25 15:59:57", "2026-11-25 16:00:00"),
        ("Monday pre-market, no times", "2026-11-02 08:00:00", None, None, "2026-10-30 16:00:00"),
        ("overnight trade ignored", "2026-10-27 08:00:00", "2026-10-26 16:00:00", "2026-10-27 02:00:00", "2026-10-26 16:00:00"),
    ]

    def test_cases(self):
        for label, as_of, regular, option, expected in self.CASES:
            with self.subTest(label):
                self.assertEqual(closed_session_quote_time(et(as_of), et(regular), et(option)), et(expected))


if __name__ == "__main__":
    unittest.main()
