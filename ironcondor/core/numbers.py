import math


def parse_float(value: str):
    value = value.strip()
    if value == "":
        return None
    return float(value)


def parse_int(value: str):
    value = value.strip()
    if value == "":
        return None
    return int(value)


def finite_positive(value) -> bool:
    try:
        x = float(value)
    except Exception:
        return False
    return math.isfinite(x) and x > 0


def fmt_money(x: float) -> str:
    return f"{x:.4f}"


def fmt_price(x: float) -> str:
    return f"{x:.2f}"


def fmt_pct_value(x: float) -> str:
    return f"{x:.2f}"


def fmt_pct(x: float) -> str:
    return f"{x:.2f}%"


def fmt_signed_money(x: float) -> str:
    if x < 0:
        return f"({abs(x):.4f})"
    return f"{x:.4f}"


def fmt_signed_pct(x: float) -> str:
    if x < 0:
        return f"({abs(x):.2f}%)"
    return f"{x:.2f}%"
