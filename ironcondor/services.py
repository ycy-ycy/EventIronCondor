"""Market-data facade: routes each request to the data source chosen for it."""

from datetime import timedelta

from .core.atm_iv import (
    atm_forward_ivs,
    choose_expiry_on_or_after,
    choose_quarterly_expiry_9_to_12_months,
)
from .core.numbers import finite_positive
from .core.timeutils import (
    format_date_text,
    get_now,
    get_open_day_for_date,
    get_this_friday,
    time_to_friday_4pm_years,
    years_from_now_to_expiry_4pm,
)
from .providers import (
    CAPABILITIES,
    CAPABILITY_LABELS,
    DEFAULT_SOURCES,
    DataSourceError,
    create_source,
)


def normalize_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("Missing ticker")
    return ticker


class MarketData:
    def __init__(self, sources=None, provider_options=None):
        sources = sources or {}
        self.source_keys = {
            capability: sources.get(capability) or DEFAULT_SOURCES[capability]
            for capability in CAPABILITIES
        }
        self.provider_options = provider_options or {}
        self._instances = {}

    @classmethod
    def from_settings(cls, settings: dict) -> "MarketData":
        return cls(settings.get("sources"), settings.get("provider_options"))

    def source(self, capability: str):
        key = self.source_keys[capability]
        instance = self._instances.get(key)
        if instance is None:
            # One instance per key, so e.g. Cboe price + chain share one download.
            instance = create_source(key, self.provider_options.get(key))
            self._instances[key] = instance
        if not isinstance(instance, CAPABILITIES[capability]):
            raise DataSourceError(f"{instance.label} cannot provide {CAPABILITY_LABELS[capability]}")
        return instance

    def latest_price(self, ticker: str) -> float:
        symbol = normalize_ticker(ticker)
        return float(self.source("price").get_spot(symbol))

    def us1y_yield_percent(self) -> float:
        return float(self.source("rate").get_us1y_yield_percent())

    def _expirations(self, option_source, symbol: str):
        expiries = sorted(option_source.get_expirations(symbol))
        if not expiries:
            raise DataSourceError(f"No option expirations were returned by {option_source.label}")
        return expiries

    def front_week_atm_iv(self, ticker: str, t_years=None, r=0.0) -> dict:
        """ATM IV of the first expiry on/after this Friday, from the option quotes alone."""
        symbol = normalize_ticker(ticker)
        options = self.source("option")

        if t_years is None or t_years <= 0:
            now = get_now()
            t_years = time_to_friday_4pm_years(
                get_open_day_for_date(now.date()),
                str(now.hour),
                f"{now.minute:02d}",
            )

        target_expiry = get_this_friday()
        actual_expiry = choose_expiry_on_or_after(self._expirations(options, symbol), target_expiry)
        option_chain = options.get_option_chain(symbol, actual_expiry)
        if option_chain.quote_time is not None:
            # Closing snapshot: the quotes are the 16:00 ones, so time runs from 16:00.
            t_years = years_from_now_to_expiry_4pm(format_date_text(actual_expiry), reference_dt=option_chain.quote_time)

        atm = atm_forward_ivs(option_chain, t_years, r)

        return {
            "symbol": symbol,
            "source": options.label,
            "quote_time": option_chain.quote_time,
            "t_years": t_years,
            "target_expiry": format_date_text(target_expiry),
            "actual_expiry": format_date_text(actual_expiry),
            **atm,
        }

    def quarterly_atm_iv(self, ticker: str, stock_price=None, r=0.0) -> dict:
        """Strict 9~12M quarterly ATM IV (LT IV). stock_price only feeds the implied-price check."""
        symbol = normalize_ticker(ticker)
        options = self.source("option")

        if stock_price is None or not finite_positive(stock_price):
            stock_price = self.latest_price(symbol)

        reference_date = get_now().date()
        actual_expiry = choose_quarterly_expiry_9_to_12_months(
            self._expirations(options, symbol),
            reference_date=reference_date,
        )
        actual_expiry_text = format_date_text(actual_expiry)
        target_expiry = (
            f"{format_date_text(reference_date + timedelta(days=270))}.."
            f"{format_date_text(reference_date + timedelta(days=390))}"
        )

        option_chain = options.get_option_chain(symbol, actual_expiry)
        # From now, or from the 16:00 close when the quotes are a closing snapshot.
        t_years = years_from_now_to_expiry_4pm(actual_expiry_text, reference_dt=option_chain.quote_time)

        atm = atm_forward_ivs(option_chain, t_years, r, strict=True, stock_price=stock_price)

        return {
            "symbol": symbol,
            "source": options.label,
            "stock_price": float(stock_price),
            "quote_time": option_chain.quote_time,
            "t_years": t_years,
            "target_expiry": target_expiry,
            "actual_expiry": actual_expiry_text,
            "actual_expiry_days": (actual_expiry - reference_date).days,
            **atm,
        }
