"""Save files, the auto-restore cache, and data-source settings."""

import copy
import json
import re
from pathlib import Path

from .core.calculator import INPUT_NAMES, average_iv_text, default_close_day
from .core.timeutils import get_now, get_today_date_text, parse_open_date_for_filename
from .paths import CACHE_FILE, DATA_DIR, SETTINGS_FILE, ensure_data_dir
from .providers import DEFAULT_SOURCES


# 22: close_day, close_atm_*_iv and sim_iv inputs; LT IV moved to the open side.
CACHE_VERSION = 22

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
        "close_day": default_close_day("MON"),
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

    legacy_long_term_iv = inputs.get("long_term_iv")
    if legacy_long_term_iv and not inputs.get("long_term_call_iv") and not inputs.get("long_term_put_iv"):
        values["long_term_call_iv"] = text(legacy_long_term_iv)
        values["long_term_put_iv"] = text(legacy_long_term_iv)

    # Before version 22 the close weekday was always the day after the open, and the
    # close panel was priced with the mean LT IV. Keep old files giving the same results.
    if "close_day" not in inputs:
        values["close_day"] = default_close_day(values["open_day"])
    if "sim_iv" not in inputs:
        try:
            if "sim_call_iv" in inputs or "sim_put_iv" in inputs:
                # Short-lived layout with a call/put pair of sim IVs.
                values["sim_iv"] = average_iv_text(text(inputs.get("sim_call_iv")), text(inputs.get("sim_put_iv")))
            else:
                values["sim_iv"] = average_iv_text(values["long_term_call_iv"], values["long_term_put_iv"])
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
