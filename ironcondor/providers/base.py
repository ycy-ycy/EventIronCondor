"""Market-data source interfaces.

A data source can implement any subset of the three capabilities:

  PriceSource   -> latest stock price (prices the debit / credit)
  OptionSource  -> option expirations, option chain (bid/ask/last/volume/OI)
  RateSource    -> US 1Y Treasury yield

The rest of the app only talks to these interfaces, so a better (paid) source can be
dropped in without touching the calculator or the GUI. See providers/registry.py.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import ClassVar, List, Optional


class DataSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionQuote:
    strike: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[float] = None
    open_interest: Optional[float] = None


@dataclass
class OptionChain:
    expiry: date
    calls: List[OptionQuote] = field(default_factory=list)
    puts: List[OptionQuote] = field(default_factory=list)
    # Set when the quotes are a closing snapshot (pre-market / after hours): the options'
    # last tradable moment of that session (16:00 ET, up to 16:15 for ETF/index classes).
    # IV is then solved with time to expiry measured from this moment instead of from the
    # time in the input boxes. See timeutils.closed_session_quote_time.
    quote_time: Optional[datetime] = None


def to_float_or_none(value) -> Optional[float]:
    """Normalize vendor numbers (None, NaN, strings) to float or None."""
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


class DataSource:
    """Common metadata. Subclasses also inherit one or more capability classes below."""

    key: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""


class PriceSource(DataSource, ABC):
    @abstractmethod
    def get_spot(self, symbol: str) -> float:
        """Latest traded/quoted price of the underlying."""


class OptionSource(DataSource, ABC):
    @abstractmethod
    def get_expirations(self, symbol: str) -> List[date]:
        """All listed expirations, ascending."""

    @abstractmethod
    def get_option_chain(self, symbol: str, expiry: date) -> OptionChain:
        """Calls and puts for one expiration (IV comes from these quotes alone)."""


class RateSource(DataSource, ABC):
    @abstractmethod
    def get_us1y_yield_percent(self) -> float:
        """Latest 1-year Treasury yield, in percent (e.g. 3.73)."""
