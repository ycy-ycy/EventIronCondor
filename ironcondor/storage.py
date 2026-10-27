"""Save files, the auto-restore cache, and data-source settings."""

import copy
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

from .core.calculator import INPUT_NAMES, average_iv_text, default_close_date
from .core.numbers import parse_float
from .core.timeutils import (
    ET,
    NEXT_DAY,
    WEEKDAY_INDEX,
    format_date_text,
    format_datetime_text,
    format_expiry_text,
    get_now,
    get_this_friday,
    get_today_date_text,
    parse_24h_time,
    parse_date_text,
    parse_open_date_for_filename,
    third_friday,
    years_from_now_to_expiry_4pm,
)
from .paths import CACHE_FILE, DATA_DIR, SETTINGS_FILE, ensure_data_dir
from .providers import DEFAULT_SOURCES


# 22: close_day, close_atm_*_iv and sim_iv inputs; LT IV moved to the open side.
# 23: close_date (expected close date) replaces the close_day weekday input.
# 24: one IV row (quote time, both expiries, the weekly's and the monthly's IV) replaces
#     the open ATM and LT IV pairs; normal IV and jump are solved from it.
CACHE_VERSION = 24

DEFAULT_SETTINGS = {
    "sources": dict(DEFAULT_SOURCES),
    # Constructor kwargs per source key, e.g. {"some_paid_feed": {"api_key": "..."}}
    "provider_options": {},
}


def default_inputs() -> dict:
    values = {name: "" for name in INPUT_NAMES}
    values.update({
        "open_date": get_today_date_text(),
        "open_day": "MON",
        "open_hour": "16",
        "open_minute": "00",
        "close_date": default_close_date(get_today_date_text()),
        "close_hour": "9",
        "close_minute": "30",
    })
    return values


def serialize_file(inputs: dict) -> dict:
    return {
        "version": CACHE_VERSION,
        "saved_at": get_now().isoformat(),
        "inputs": {name: inputs.get(name, "") for name in INPUT_NAMES},
    }


def close_date_in_open_week(open_date_text: str, weekday: str) -> str:
    """The date with that weekday in the open date's week ("" if either is unusable)."""
    open_date = parse_date_text(open_date_text)
    if open_date is None or weekday not in WEEKDAY_INDEX:
        return ""
    monday = open_date - timedelta(days=open_date.weekday())
    return format_date_text(monday + timedelta(days=WEEKDAY_INDEX[weekday]))


def iv_row_from_old_ivs(atm_call_iv: str, atm_put_iv: str, lt_call_iv: str, lt_put_iv: str, values: dict) -> dict:
    """The IV row for a file from before version 24, so its trade prices as it did.

    Those files kept this Friday's ATM IV at the open time and the LT (normal) IV, each a
    call/put pair; each becomes its mean. The quote time becomes the open time and the weekly
    expiry that week's Friday, which those files always assumed. The monthly, the first third Friday 21+ days out, gets the IV
    that solves back to the same normal IV and jump. Unusable values convert nothing; an
    ATM IV below the LT IV leaves the monthly IV blank.
    """
    try:
        weekly_iv = parse_float(average_iv_text(atm_call_iv, atm_put_iv))
        normal_iv = parse_float(average_iv_text(lt_call_iv, lt_put_iv))
        open_date = parse_date_text(values["open_date"])
        if weekly_iv is None or open_date is None:
            return {}
        quote_time = datetime.combine(open_date, parse_24h_time(values["open_hour"], values["open_minute"]), tzinfo=ET)
        weekly_expiry = get_this_friday(open_date)
        earliest = open_date + timedelta(days=21)
        monthly_expiry = third_friday(earliest.year, earliest.month)
        if monthly_expiry < earliest:
            next_month = earliest.replace(day=1) + timedelta(days=32)
            monthly_expiry = third_friday(next_month.year, next_month.month)
        t_week = years_from_now_to_expiry_4pm(format_date_text(weekly_expiry), reference_dt=quote_time)
        t_month = years_from_now_to_expiry_4pm(format_date_text(monthly_expiry), reference_dt=quote_time)
    except ValueError:
        return {}

    row = {
        "iv_quote_time": format_datetime_text(quote_time),
        "weekly_expiry": format_expiry_text(weekly_expiry),
        "monthly_expiry": format_expiry_text(monthly_expiry),
        "weekly_iv": average_iv_text(atm_call_iv, atm_put_iv),
    }
    if normal_iv is not None:
        normal_var = (normal_iv / 100.0) ** 2
        jump = ((weekly_iv / 100.0) ** 2 - normal_var) * t_week
        if jump >= 0:
            monthly_iv = math.sqrt(normal_var + jump / t_month) * 100.0
            row["monthly_iv"] = f"{round(monthly_iv, 6):.6f}".rstrip("0").rstrip(".")
    return row


def inputs_from_saved(data) -> dict:
    """Turn a save/cache file (current or legacy layout) into a full input dict."""
    if isinstance(data, dict) and "inputs" in data and isinstance(data["inputs"], dict):
        inputs = data["inputs"]
    else:
        inputs = data

    if not isinstance(inputs, dict):
        raise ValueError("This file does not contain calculator inputs")

    def text(value):
        return "" if value is None else str(value)

    values = default_inputs()

    legacy_us1y = inputs.get("us1y") or inputs.get("us10y")
    legacy_open_us1y = inputs.get("open_us1y") or inputs.get("open_us10y") or legacy_us1y
    legacy_close_us1y = inputs.get("close_us1y") or inputs.get("close_us10y") or legacy_us1y

    for name, value in inputs.items():
        if name in values:
            values[name] = text(value)

    if legacy_open_us1y is not None and not values["open_us1y"]:
        values["open_us1y"] = text(legacy_open_us1y)
    if legacy_close_us1y is not None and not values["close_us1y"]:
        values["close_us1y"] = text(legacy_close_us1y)

    # Before version 24: LT IV call/put pair (one long_term_iv before that).
    lt_call_iv = text(inputs.get("long_term_call_iv"))
    lt_put_iv = text(inputs.get("long_term_put_iv"))
    legacy_long_term_iv = inputs.get("long_term_iv")
    if legacy_long_term_iv and not lt_call_iv and not lt_put_iv:
        lt_call_iv = lt_put_iv = text(legacy_long_term_iv)

    if "weekly_iv" not in inputs and "monthly_iv" not in inputs:
        values.update(iv_row_from_old_ivs(
            text(inputs.get("atm_call_iv")), text(inputs.get("atm_put_iv")), lt_call_iv, lt_put_iv, values
        ))

    # Before version 23 the close was a weekday of the open week (before 22, always the day
    # after the open), and before 22 the close panel was priced with the mean LT IV. Keep
    # old files giving the same results.
    if "close_date" not in inputs:
        weekday = text(inputs.get("close_day")) or NEXT_DAY.get(values["open_day"], "")
        values["close_date"] = close_date_in_open_week(values["open_date"], weekday)
    if "sim_iv" not in inputs:
        try:
            if "sim_call_iv" in inputs or "sim_put_iv" in inputs:
                # Short-lived layout with a call/put pair of sim IVs.
                values["sim_iv"] = average_iv_text(text(inputs.get("sim_call_iv")), text(inputs.get("sim_put_iv")))
            else:
                values["sim_iv"] = average_iv_text(lt_call_iv, lt_put_iv)
        except ValueError:
            values["sim_iv"] = ""

    return values


def write_json(path: Path, payload: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_cache(inputs: dict):
    try:
        ensure_data_dir()
        write_json(CACHE_FILE, serialize_file(inputs))
    except Exception:
        pass


def read_cache():
    if not CACHE_FILE.exists():
        return None
    try:
        return inputs_from_saved(read_json(CACHE_FILE))
    except Exception:
        return None


def sanitize_ticker_for_filename(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not ticker:
        return "UNTITLED"

    cleaned = re.sub(r"[^A-Z0-9._-]+", "", ticker)
    return cleaned or "UNTITLED"


def default_save_path(ticker: str, open_date_text: str) -> Path:
    ensure_data_dir()
    yyyymmdd = parse_open_date_for_filename(open_date_text)
    clean_ticker = sanitize_ticker_for_filename(ticker)
    return DATA_DIR / f"{yyyymmdd}{clean_ticker}.json"


def save_inputs(path: Path, inputs: dict):
    write_json(path, serialize_file(inputs))


def load_inputs(path: Path) -> dict:
    return inputs_from_saved(read_json(path))


def load_settings() -> dict:
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    try:
        stored = read_json(SETTINGS_FILE)
    except Exception:
        return settings

    if isinstance(stored, dict):
        if isinstance(stored.get("sources"), dict):
            settings["sources"].update({k: v for k, v in stored["sources"].items() if v})
        if isinstance(stored.get("provider_options"), dict):
            settings["provider_options"] = stored["provider_options"]
    return settings


def save_settings(settings: dict):
    write_json(SETTINGS_FILE, settings)
