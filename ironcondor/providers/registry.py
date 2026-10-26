"""Which data sources exist, and how to build them.

To add a source (e.g. a paid feed with real-time bid/ask):
  1. Create providers/<name>.py with a class inheriting PriceSource and/or OptionSource
     (and/or RateSource) from providers/base.py. Give it `key`, `label`, `description`.
  2. Call register(YourClass) at the bottom of this file.
  3. Pick it in the GUI (Data sources… button). Constructor keyword arguments such as API keys
     come from settings.json -> "provider_options" -> {"<key>": {...}}.
"""

from .base import DataSourceError, OptionSource, PriceSource, RateSource
from .cboe import CboeDelayedSource
from .fred import FredRateSource
from .yahoo import YFinanceSource


CAPABILITIES = {
    "price": PriceSource,
    "option": OptionSource,
    "rate": RateSource,
}

CAPABILITY_LABELS = {
    "price": "Stock price",
    "option": "Option chain / IV",
    "rate": "US 1Y rate",
}

DEFAULT_SOURCES = {
    "price": "yfinance",
    "option": "yfinance",
    "rate": "fred",
}

_SOURCES = {}


def register(cls):
    if not cls.key:
        raise ValueError(f"{cls.__name__} needs a non-empty key")
    _SOURCES[cls.key] = cls
    return cls


def sources_for(capability: str):
    base = CAPABILITIES[capability]
    return [cls for cls in _SOURCES.values() if issubclass(cls, base)]


def source_class(key: str):
    try:
        return _SOURCES[key]
    except KeyError:
        raise DataSourceError(f"Unknown data source: {key!r}")


def create_source(key: str, options=None):
    return source_class(key)(**(options or {}))


register(YFinanceSource)
register(CboeDelayedSource)
register(FredRateSource)
