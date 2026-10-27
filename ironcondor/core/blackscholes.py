import math

from .numbers import finite_positive


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def log_move_pct(reference_price: float, target_price: float) -> float:
    """Return the continuously-compounded/log move from reference to target, in percent."""
    if reference_price <= 0 or target_price <= 0:
        raise ValueError("Prices must be positive for log move")
    return math.log(target_price / reference_price) * 100.0


def price_from_log_move(reference_price: float, log_move: float) -> float:
    """Apply a log-return move to a price: S_target = S_ref * exp(log_move)."""
    if reference_price <= 0:
        raise ValueError("Reference price must be positive")
    return reference_price * math.exp(log_move)


def bs_price(
    spot: float,
    strike: float,
    t_years: float,
    r: float,
    iv: float,
    option_type: str,
    q: float = 0.0,
) -> float:
    if spot <= 0 or strike <= 0 or t_years < 0 or iv <= 0:
        raise ValueError("Invalid Black-Scholes input")

    if t_years == 0:
        if option_type == "call":
            return max(spot - strike, 0.0)
        if option_type == "put":
            return max(strike - spot, 0.0)
        raise ValueError("Invalid option type")

    sqrt_t = math.sqrt(t_years)

    d1 = (
        math.log(spot / strike)
        + (r - q + 0.5 * iv * iv) * t_years
    ) / (iv * sqrt_t)

    d2 = d1 - iv * sqrt_t

    discounted_spot = spot * math.exp(-q * t_years)
    discounted_strike = strike * math.exp(-r * t_years)

    if option_type == "call":
        return discounted_spot * norm_cdf(d1) - discounted_strike * norm_cdf(d2)

    if option_type == "put":
        return discounted_strike * norm_cdf(-d2) - discounted_spot * norm_cdf(-d1)

    raise ValueError("Invalid option type")


def bs_itm_probability(
    spot: float,
    strike: float,
    t_years: float,
    r: float,
    iv: float,
    option_type: str,
    q: float = 0.0,
) -> float:
    """Risk-neutral probability that the option finishes ITM at expiry."""
    if spot <= 0 or strike <= 0 or t_years < 0 or iv <= 0:
        raise ValueError("Invalid Black-Scholes input")

    if t_years == 0:
        if option_type == "call":
            return 1.0 if spot > strike else 0.0
        if option_type == "put":
            return 1.0 if spot < strike else 0.0
        raise ValueError("Invalid option type")

    sqrt_t = math.sqrt(t_years)
    d2 = (
        math.log(spot / strike)
        + (r - q - 0.5 * iv * iv) * t_years
    ) / (iv * sqrt_t)

    if option_type == "call":
        return norm_cdf(d2)
    if option_type == "put":
        return norm_cdf(-d2)
    raise ValueError("Invalid option type")


def solve_iv_from_option_mid(
    spot: float,
    strike: float,
    t_years: float,
    r: float,
    option_type: str,
    target_price: float,
    q: float = 0.0,
) -> float:
    if not finite_positive(spot) or not finite_positive(strike):
        raise ValueError("Invalid spot or strike")

    if t_years <= 0:
        raise ValueError("Time to expiry must be positive")

    if target_price <= 0:
        raise ValueError("Option midpoint must be positive")

    # A European option's floor is the discounted intrinsic, not max(S - K, 0) or
    # max(K - S, 0): with a high rate or a long time a deep in-the-money put is rightly
    # worth less than K - S (a call with dividends less than S - K).
    discounted_spot = spot * math.exp(-q * t_years)
    discounted_strike = strike * math.exp(-r * t_years)
    if option_type == "call":
        floor = max(discounted_spot - discounted_strike, 0.0)
    else:
        floor = max(discounted_strike - discounted_spot, 0.0)

    if target_price + 1e-6 < floor:
        raise RuntimeError(
            f"{option_type.upper()} {strike:g} midpoint {target_price:.4f} is below the discounted "
            f"intrinsic {floor:.4f}"
        )

    low = 1e-4
    high = 5.0

    def price_at(iv):
        return bs_price(
            spot=spot,
            strike=strike,
            t_years=t_years,
            r=r,
            iv=iv,
            option_type=option_type,
            q=q,
        )

    low_price = price_at(low)
    high_price = price_at(high)

    while high_price < target_price and high < 20.0:
        high *= 2.0
        high_price = price_at(high)

    if target_price < low_price - 1e-6 or target_price > high_price + 1e-6:
        raise RuntimeError(
            f"Cannot solve IV for {option_type.upper()} {strike:g}: "
            f"midpoint={target_price:.4f}, model range={low_price:.4f}..{high_price:.4f}"
        )

    for _ in range(80):
        mid = (low + high) / 2.0
        mid_price = price_at(mid)

        if mid_price < target_price:
            low = mid
        else:
            high = mid

    return (low + high) / 2.0
