"""Market-data facade: routes each request to the data source chosen for it."""

from .core.atm_iv import (
    atm_forward_ivs,
    choose_monthly_expiry_21_to_56_days,
    choose_weekly_expiry,
)
from .core.numbers import finite_positive
from .core.timeutils import (
    format_date_text,
    get_now,
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

    def front_week_atm_iv(self, ticker: str, t_years=None, r=0.0, expiry=None) -> dict:
        """ATM IV of the weekly, from the option quotes alone.

        expiry: the position's weekly; None for this week's (see choose_weekly_expiry).
        t_years: from the time boxes to it; None for from now.
        """
        symbol = normalize_ticker(ticker)
        options = self.source("option")

        actual_expiry = expiry or choose_weekly_expiry(self._expirations(options, symbol), get_now().date())
        option_chain = options.get_option_chain(symbol, actual_expiry)
        if option_chain.quote_time is not None or t_years is None or t_years <= 0:
            # From now, or from the 16:00 close when the quotes are a closing snapshot.
            t_years = years_from_now_to_expiry_4pm(format_date_text(actual_expiry), reference_dt=option_chain.quote_time)

        atm = atm_forward_ivs(option_chain, t_years, r)

        return {
            "symbol": symbol,
            "source": options.label,
            "quote_time": option_chain.quote_time,
            "t_years": t_years,
            "actual_expiry": format_date_text(actual_expiry),
            **atm,
        }

    def event_atm_ivs(self, ticker: str, stock_price=None, r=0.0) -> dict:
        """The weekly's and the 21~56-day monthly's ATM IV, both with T from one quote time.

        The quote time is the closing snapshot's once the session is over, else now; to the
        minute, as its box shows it. The monthly is read strictly; stock_price only feeds its
        implied-price check.
        """
        symbol = normalize_ticker(ticker)
        options = self.source("option")

        if stock_price is None or not finite_positive(stock_price):
            stock_price = self.latest_price(symbol)

        expiries = self._expirations(options, symbol)
        reference_date = get_now().date()
        weekly_expiry = choose_weekly_expiry(expiries, reference_date)
        monthly_expiry = choose_monthly_expiry_21_to_56_days(expiries, reference_date=reference_date)
        weekly_chain = options.get_option_chain(symbol, weekly_expiry)
        monthly_chain = options.get_option_chain(symbol, monthly_expiry)
        quote_time = (weekly_chain.quote_time or get_now()).replace(second=0, microsecond=0)

        def read(option_chain, expiry, **checks):
            t_years = years_from_now_to_expiry_4pm(format_date_text(expiry), reference_dt=quote_time)
            return {"actual_expiry": format_date_text(expiry), "t_years": t_years,
                    **atm_forward_ivs(option_chain, t_years, r, **checks)}

        return {
            "symbol": symbol,
            "source": options.label,
            "stock_price": float(stock_price),
            "quote_time": quote_time,
            "closing_snapshot": weekly_chain.quote_time is not None,
            "weekly": read(weekly_chain, weekly_expiry),
            "monthly": {
                "actual_expiry_days": (monthly_expiry - reference_date).days,
                **read(monthly_chain, monthly_expiry, strict=True, stock_price=stock_price),
            },
        }
