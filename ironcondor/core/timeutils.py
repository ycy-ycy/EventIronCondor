from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from .numbers import parse_int


ET = ZoneInfo("America/New_York")

OPEN_DAYS = ["MON", "TUE", "WED", "THU"]
CLOSE_DAYS = ["MON", "TUE", "WED", "THU", "FRI"]

WEEKDAY_INDEX = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
}

NEXT_DAY = {
    "MON": "TUE",
    "TUE": "WED",
    "WED": "THU",
    "THU": "FRI",
}

BASE_MONDAY = date(2024, 1, 1)

SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
# ETF and index option classes (SPY, QQQ, SPX...) keep trading until 16:15.
LATEST_OPTION_CLOSE = time(16, 15)
# The free option feeds (Cboe delayed quotes, Yahoo) run about this far behind.
QUOTE_DELAY = timedelta(minutes=15)


def parse_24h_time(hour_text: str, minute_text: str) -> time:
    hour = parse_int(hour_text)
    minute = parse_int(minute_text)

    if hour is None or minute is None:
        raise ValueError("Missing time")

    if hour < 0 or hour > 23:
        raise ValueError("Invalid hour")

    if minute < 0 or minute > 59:
        raise ValueError("Invalid minute")

    return time(hour, minute)


def time_to_friday_4pm_years(day: str, hour_text: str, minute_text: str) -> float:
    if day not in WEEKDAY_INDEX:
        raise ValueError("Invalid weekday")

    selected_time = parse_24h_time(hour_text, minute_text)

    current_date = BASE_MONDAY + timedelta(days=WEEKDAY_INDEX[day])
    expiry_date = BASE_MONDAY + timedelta(days=WEEKDAY_INDEX["FRI"])

    current_dt = datetime.combine(current_date, selected_time)
    expiry_dt = datetime.combine(expiry_date, time(16, 0))

    seconds = (expiry_dt - current_dt).total_seconds()

    if seconds < 0:
        raise ValueError("Time is after Friday 4 PM")

    return seconds / (365.0 * 24.0 * 3600.0)


def years_from_now_to_expiry_4pm(expiry_text: str, reference_dt=None) -> float:
    if reference_dt is None:
        reference_dt = get_now()

    expiry_date = datetime.strptime(expiry_text, "%Y-%m-%d").date()
    expiry_dt = datetime.combine(expiry_date, time(16, 0), tzinfo=ET)

    seconds = (expiry_dt - reference_dt).total_seconds()

    if seconds <= 0:
        raise ValueError("Selected expiry is not in the future")

    return seconds / (365.0 * 24.0 * 3600.0)


def get_now() -> datetime:
    return datetime.now(ET)


def closed_session_quote_time(as_of: datetime, last_regular_trade=None, last_option_trade=None):
    """Moment a snapshot's option quotes belong to once the session is over, else None.

    as_of: when the (delayed) data was taken. Regular hours are weekdays 09:30-16:00 with
    a regular stock trade that day, so a holiday counts as closed and so does 09:30-09:45,
    when the delayed data still shows the pre-open. Outside them the quotes are the final
    ones of the last session, and time to expiry is pinned to the options' last tradable
    moment: their latest trade that day, not before 16:00 (closing bid/ask stay live until
    the close) nor after 16:15; 16:00 when there is no trade time.
    """
    in_session = (
        as_of.weekday() < 5
        and SESSION_OPEN <= as_of.time() < SESSION_CLOSE
        and (last_regular_trade is None or last_regular_trade.date() == as_of.date())
    )
    if in_session:
        return None

    if last_regular_trade is not None and last_regular_trade <= as_of:
        session_date = last_regular_trade.date()
    else:
        # No usable stock trade time (or a live one newer than the delayed quotes).
        session_date = as_of.date()
        if as_of.time() < SESSION_CLOSE:
            session_date -= timedelta(days=1)
        while session_date.weekday() > 4:
            session_date -= timedelta(days=1)

    pinned = datetime.combine(session_date, SESSION_CLOSE, tzinfo=ET)
    if last_option_trade is not None and last_option_trade.date() == session_date:
        latest = datetime.combine(session_date, LATEST_OPTION_CLOSE, tzinfo=ET)
        pinned = min(max(pinned, last_option_trade), latest)
    return pinned


def format_date_text(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def get_today_date_text() -> str:
    return format_date_text(get_now().date())


def get_this_friday(reference_date=None) -> date:
    if reference_date is None:
        reference_date = get_now().date()

    days_until_friday = (WEEKDAY_INDEX["FRI"] - reference_date.weekday()) % 7
    return reference_date + timedelta(days=days_until_friday)


def get_open_day_for_date(value: date) -> str:
    weekday = value.weekday()

    if weekday == 0:
        return "MON"
    if weekday == 1:
        return "TUE"
    if weekday == 2:
        return "WED"
    if weekday == 3:
        return "THU"
    if weekday == 4:
        return "THU"

    return "MON"


def get_weekday_name(value: date):
    """MON..FRI for a weekday, None on weekends."""
    weekday = value.weekday()
    if weekday > 4:
        return None
    return CLOSE_DAYS[weekday]


def get_current_date_day_hour_minute_for_open():
    now = get_now()
    today = now.date()

    return (
        format_date_text(today),
        get_open_day_for_date(today),
        str(now.hour),
        f"{now.minute:02d}",
    )


DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d")


def parse_date_text(text: str):
    """A date typed as YYYY-MM-DD, YYYY/MM/DD or YYYYMMDD; None if blank or unparsable."""
    text = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def parse_open_date_for_filename(open_date_text: str) -> str:
    text = open_date_text.strip()

    if not text:
        raise ValueError("Missing open date")

    value = parse_date_text(text)
    if value is not None:
        return value.strftime("%Y%m%d")

    raise ValueError("Open date must be YYYY-MM-DD, YYYY/MM/DD, or YYYYMMDD")


def next_weekday(value: date) -> date:
    """The next Monday-Friday date after value (market holidays are not known)."""
    value += timedelta(days=1)
    while value.weekday() > 4:
        value += timedelta(days=1)
    return value


def third_friday(year: int, month: int) -> date:
    first_day = date(year, month, 1)
    days_until_friday = (4 - first_day.weekday()) % 7
    return first_day + timedelta(days=days_until_friday + 14)


def is_standard_monthly_expiry_date(expiry_date: date) -> bool:
    tf = third_friday(expiry_date.year, expiry_date.month)
    # Normally monthly equity options expire on the third Friday. If that Friday
    # is a market holiday, the listed expiry may be the previous Thursday.
    return expiry_date == tf or expiry_date == tf - timedelta(days=1)


def is_quarterly_standard_expiry_date(expiry_date: date) -> bool:
    return expiry_date.month in (3, 6, 9, 12) and is_standard_monthly_expiry_date(expiry_date)
