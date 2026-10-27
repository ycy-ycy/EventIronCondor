"""All derived outputs of the calculator, computed from the raw input strings.

The GUI only collects input text and paints the result; every formula lives here.
"""

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .blackscholes import bs_price, bs_itm_probability, log_move_pct, price_from_log_move
from .numbers import (
    parse_float,
    fmt_money,
    fmt_price,
    fmt_pct,
    fmt_signed_money,
    fmt_signed_pct,
)
from .strategy import (
    strategy_credit,
    strategy_put_call_credit,
    find_breakeven_in_range,
)
from .timeutils import (
    format_date_text,
    get_this_friday,
    get_weekday_name,
    next_weekday,
    parse_date_text,
    time_to_friday_4pm_years,
)


PROB50_Z = 0.6744897501960817

SCENARIOS = [
    ("downside", "Downside"),
    ("prob50_downside", "50% prob down"),
    ("short_put", "Short put"),
    ("long_put", "Long put"),
    ("middle", "Middle / worst"),
    ("long_call", "Long call"),
    ("short_call", "Short call"),
    ("prob50_upside", "50% prob up"),
    ("upside", "Upside"),
]

# Key order of the saved JSON files.
INPUT_NAMES = [
    "ticker",
    "open_date",
    "open_day",
    "open_hour",
    "open_minute",
    "open_market_price",
    "atm_call_iv",
    "atm_put_iv",
    # Normal (non-event) IV: sets the implied earnings move on the open side.
    "long_term_call_iv",
    "long_term_put_iv",
    "open_us1y",
    "close_us1y",
    "spread",
    "long_put_strike",
    "long_call_strike",
    # Expected close date; the close weekday comes from it.
    "close_date",
    "close_hour",
    "close_minute",
    "close_market_price",
    # Front-week ATM IV observed at close time (informational until applied to sim IV).
    "close_atm_call_iv",
    "close_atm_put_iv",
    # The one IV that prices every leg on the close side (credit, P&L, scenarios, plot).
    "sim_iv",
    "open_debit_override",
]

OUTPUT_NAMES = [
    "short_put_strike",
    "short_call_strike",
    "long_put_move_pct",
    "long_call_move_pct",
    "short_put_move_pct",
    "short_call_move_pct",
    "put_debit",
    "call_debit",
    "total_debit",
    "open_downside_breakeven_price",
    "open_downside_breakeven_move_pct",
    "open_upside_breakeven_price",
    "open_upside_breakeven_move_pct",
    "implied_move_pct",
    "downside_price",
    "upside_price",
    "exp_implied_move_pct",
    "exp_implied_move_down_price",
    "exp_implied_move_up_price",
    "exp_prob50_move_pct",
    "exp_prob50_down_price",
    "exp_prob50_up_price",
    "exp_long_call_itm_prob",
    "exp_long_put_itm_prob",
    "exp_breakeven_call_prob",
    "exp_breakeven_put_prob",
    "exp_short_call_itm_prob",
    "exp_short_put_itm_prob",
    "close_day",
    "put_credit",
    "call_credit",
    "total_credit",
    "close_price_change_pct",
    "pnl_dollar",
    "pnl_pct",
    "sim_downside_breakeven_price",
    "sim_downside_breakeven_move_pct",
    "sim_upside_breakeven_price",
    "sim_upside_breakeven_move_pct",
]

for _key, _ in SCENARIOS:
    OUTPUT_NAMES += [
        f"scenario_{_key}_price",
        f"scenario_{_key}_credit",
        f"scenario_{_key}_pnl_dollar",
        f"scenario_{_key}_pnl_pct",
    ]


def get_avg_iv_decimal(inputs: Mapping[str, str], call_name: str, put_name: str):
    call_iv = parse_float(inputs[call_name])
    put_iv = parse_float(inputs[put_name])

    if call_iv is None and put_iv is None:
        return None

    if call_iv is not None and put_iv is not None:
        return ((call_iv + put_iv) / 2.0) / 100.0

    if call_iv is not None:
        return call_iv / 100.0

    return put_iv / 100.0


def get_atm_iv_decimal(inputs: Mapping[str, str]):
    return get_avg_iv_decimal(inputs, "atm_call_iv", "atm_put_iv")


def get_long_term_iv_decimal(inputs: Mapping[str, str]):
    return get_avg_iv_decimal(inputs, "long_term_call_iv", "long_term_put_iv")


def get_sim_iv_decimal(inputs: Mapping[str, str]):
    iv = parse_float(inputs["sim_iv"])
    if iv is None:
        return None
    return iv / 100.0


def average_iv_text(call_text: str, put_text: str) -> str:
    """Collapse a call/put IV pair (either may be blank) into one IV, as input-box text.

    Same rule as get_avg_iv_decimal: the mean of both, or whichever one is filled.
    """
    values = [v for v in (parse_float(call_text), parse_float(put_text)) if v is not None]
    if not values:
        return ""
    avg = sum(values) / len(values)
    return f"{round(avg, 6):.6f}".rstrip("0").rstrip(".")


def get_rate_decimal(inputs: Mapping[str, str], name: str):
    y = parse_float(inputs[name])
    if y is None:
        return 0.0
    return y / 100.0


def get_open_r_decimal(inputs: Mapping[str, str]):
    return get_rate_decimal(inputs, "open_us1y")


def get_close_r_decimal(inputs: Mapping[str, str]):
    return get_rate_decimal(inputs, "close_us1y")


def get_close_day(inputs: Mapping[str, str]) -> str:
    """Close weekday (MON..FRI) from the expected close date; "" when it can't be used.

    The options expire on the Friday of the open week, so the close date must be a weekday
    from the open date up to that Friday.
    """
    close_date = parse_date_text(inputs["close_date"])
    if close_date is None:
        return ""
    weekday = get_weekday_name(close_date)
    if weekday is None:
        return ""
    open_date = parse_date_text(inputs["open_date"])
    if open_date is not None and not (open_date <= close_date <= get_this_friday(open_date)):
        return ""
    return weekday


def default_close_date(open_date_text: str) -> str:
    """The trading day after the open (the usual earnings exit); "" if the open date is unusable."""
    open_date = parse_date_text(open_date_text)
    if open_date is None:
        return ""
    return format_date_text(next_weekday(open_date))


def implied_event_variance(current_iv: float, normal_iv: float, t_years: float) -> float:
    """Earnings-event variance: front-week variance minus normal variance over the same time.

    current_iv * current_iv * T = normal_iv * normal_iv * T + event_variance, with one T (open to
    Friday 16:00) on both sides. sqrt(event_variance) is a log-return move, so price levels
    must use exp(±move). Used by both the open panel and the Simulate plot.
    """
    return (current_iv * current_iv - normal_iv * normal_iv) * t_years


def get_open_debit_for_pnl(inputs: Mapping[str, str], theoretical_open_debit):
    override = parse_float(inputs["open_debit_override"])

    if override is not None:
        return override

    return theoretical_open_debit


@dataclass
class CalcResult:
    text: dict = field(default_factory=dict)
    # Sign used to color an output: >0 profit (green), <0 loss (red), 0/None neutral.
    # Only outputs whose color depends on the numbers appear here.
    tone: dict = field(default_factory=dict)
    theoretical_open_debit: Optional[float] = None
    theoretical_close_credit: Optional[float] = None


class Calculator:
    def __init__(self, inputs: Mapping[str, str]):
        self.inputs = {name: str(inputs.get(name, "") or "") for name in INPUT_NAMES}
        self.result = CalcResult(text={name: "" for name in OUTPUT_NAMES})

        self.theoretical_open_debit = None
        self.theoretical_close_credit = None
        self.downside_price_value = None
        self.prob50_downside_price_value = None
        self.prob50_upside_price_value = None
        self.upside_price_value = None

    def input(self, name: str) -> str:
        return self.inputs[name]

    def set_output(self, name: str, value: str):
        self.result.text[name] = value

    def clear_output(self, *names):
        for name in names:
            self.result.text[name] = ""

    def set_output_style(self, name: str, value):
        self.result.tone[name] = value

    def set_pnl_style(self, pnl):
        for name in ("pnl_dollar", "pnl_pct"):
            self.set_output_style(name, pnl)

    def get_open_debit_for_pnl(self):
        return get_open_debit_for_pnl(self.inputs, self.theoretical_open_debit)

    def run(self) -> CalcResult:
        steps = (
            self.recalculate_close_day,
            self.recalculate_short_strikes,
            self.recalculate_strike_moves,
            self.recalculate_opening_debit_and_implied_move,
            self.recalculate_expiration_expectation,
            self.recalculate_close_price_change,
            self.recalculate_closing_credit,
            self.recalculate_pnl,
            self.recalculate_scenario_pnl,
            self.recalculate_simulated_breakevens,
        )
        for step in steps:
            # A step only fails on unparsable text (e.g. letters in a number box);
            # its outputs stay blank and the remaining steps still run.
            try:
                step()
            except Exception:
                pass

        self.result.theoretical_open_debit = self.theoretical_open_debit
        self.result.theoretical_close_credit = self.theoretical_close_credit
        return self.result

    def recalculate_close_day(self):
        close_day = get_close_day(self.inputs)
        if close_day:
            self.set_output("close_day", close_day)
            self.set_output_style("close_day", None)
        elif self.input("close_date").strip():
            # A date is typed but unusable: weekend, before the open, or after the Friday expiry.
            self.set_output("close_day", "n/a")
            self.set_output_style("close_day", -1)
        else:
            self.set_output_style("close_day", None)

    def recalculate_short_strikes(self):
        try:
            spread = parse_float(self.input("spread"))
            long_put = parse_float(self.input("long_put_strike"))
            long_call = parse_float(self.input("long_call_strike"))

            if spread is not None and long_put is not None:
                self.set_output("short_put_strike", fmt_price(long_put - spread))
            else:
                self.set_output("short_put_strike", "")

            if spread is not None and long_call is not None:
                self.set_output("short_call_strike", fmt_price(long_call + spread))
            else:
                self.set_output("short_call_strike", "")

        except Exception:
            self.clear_output("short_put_strike", "short_call_strike")

    def recalculate_strike_moves(self):
        def set_move_output(name: str, move_pct):
            self.set_output(name, fmt_signed_pct(move_pct))
            self.set_output_style(name, move_pct)

        try:
            spot = parse_float(self.input("open_market_price"))
            long_put = parse_float(self.input("long_put_strike"))

            if spot is None or spot <= 0 or long_put is None or long_put <= 0:
                raise ValueError("Missing long put move inputs")

            set_move_output("long_put_move_pct", log_move_pct(spot, long_put))

        except Exception:
            self.clear_output("long_put_move_pct")
            self.set_output_style("long_put_move_pct", None)

        try:
            spot = parse_float(self.input("open_market_price"))
            long_call = parse_float(self.input("long_call_strike"))

            if spot is None or spot <= 0 or long_call is None or long_call <= 0:
                raise ValueError("Missing long call move inputs")

            set_move_output("long_call_move_pct", log_move_pct(spot, long_call))

        except Exception:
            self.clear_output("long_call_move_pct")
            self.set_output_style("long_call_move_pct", None)

        try:
            spot = parse_float(self.input("open_market_price"))
            spread = parse_float(self.input("spread"))
            long_put = parse_float(self.input("long_put_strike"))

            if spot is None or spot <= 0 or spread is None or long_put is None:
                raise ValueError("Missing short put move inputs")

            short_put = long_put - spread
            if short_put <= 0:
                raise ValueError("Invalid short put")

            set_move_output("short_put_move_pct", log_move_pct(spot, short_put))

        except Exception:
            self.clear_output("short_put_move_pct")
            self.set_output_style("short_put_move_pct", None)

        try:
            spot = parse_float(self.input("open_market_price"))
            spread = parse_float(self.input("spread"))
            long_call = parse_float(self.input("long_call_strike"))

            if spot is None or spot <= 0 or spread is None or long_call is None:
                raise ValueError("Missing short call move inputs")

            short_call = long_call + spread
            if short_call <= 0:
                raise ValueError("Invalid short call")

            set_move_output("short_call_move_pct", log_move_pct(spot, short_call))

        except Exception:
            self.clear_output("short_call_move_pct")
            self.set_output_style("short_call_move_pct", None)

    def recalculate_close_price_change(self):
        try:
            open_price = parse_float(self.input("open_market_price"))
            close_price = parse_float(self.input("close_market_price"))

            if open_price is None or close_price is None or open_price <= 0:
                raise ValueError("Missing market prices")

            change_pct = log_move_pct(open_price, close_price)

            self.set_output("close_price_change_pct", fmt_signed_pct(change_pct))
            self.set_output_style("close_price_change_pct", change_pct)

        except Exception:
            self.clear_output("close_price_change_pct")
            self.set_output_style("close_price_change_pct", None)

    def recalculate_opening_debit_and_implied_move(self):
        spot = parse_float(self.input("open_market_price"))
        spread = parse_float(self.input("spread"))
        long_put = parse_float(self.input("long_put_strike"))
        long_call = parse_float(self.input("long_call_strike"))
        r = get_open_r_decimal(self.inputs)
        avg_iv = get_atm_iv_decimal(self.inputs)
        call_iv_raw = parse_float(self.input("atm_call_iv"))
        put_iv_raw = parse_float(self.input("atm_put_iv"))
        call_iv = None if avg_iv is None else (avg_iv if call_iv_raw is None else call_iv_raw / 100.0)
        put_iv = None if avg_iv is None else (avg_iv if put_iv_raw is None else put_iv_raw / 100.0)

        put_debit = None
        call_debit = None
        total_debit = None
        self.theoretical_open_debit = None

        # Calculate each side independently. A missing call strike should not blank the put side, and vice versa.
        try:
            if spot is None or spot <= 0 or spread is None or spread <= 0 or long_put is None or put_iv is None:
                raise ValueError("Missing put debit inputs")

            short_put = long_put - spread
            if long_put <= 0 or short_put <= 0:
                raise ValueError("Invalid put strikes")

            t_before = time_to_friday_4pm_years(
                self.input("open_day"),
                self.input("open_hour"),
                self.input("open_minute"),
            )

            long_put_price = bs_price(
                spot=spot,
                strike=long_put,
                t_years=t_before,
                r=r,
                iv=put_iv,
                option_type="put",
            )
            short_put_price = bs_price(
                spot=spot,
                strike=short_put,
                t_years=t_before,
                r=r,
                iv=put_iv,
                option_type="put",
            )
            put_debit = long_put_price - short_put_price
            self.set_output("put_debit", fmt_money(put_debit))
        except Exception:
            self.clear_output("put_debit")

        try:
            if spot is None or spot <= 0 or spread is None or spread <= 0 or long_call is None or call_iv is None:
                raise ValueError("Missing call debit inputs")

            short_call = long_call + spread
            if long_call <= 0 or short_call <= 0:
                raise ValueError("Invalid call strikes")

            t_before = time_to_friday_4pm_years(
                self.input("open_day"),
                self.input("open_hour"),
                self.input("open_minute"),
            )

            long_call_price = bs_price(
                spot=spot,
                strike=long_call,
                t_years=t_before,
                r=r,
                iv=call_iv,
                option_type="call",
            )
            short_call_price = bs_price(
                spot=spot,
                strike=short_call,
                t_years=t_before,
                r=r,
                iv=call_iv,
                option_type="call",
            )
            call_debit = long_call_price - short_call_price
            self.set_output("call_debit", fmt_money(call_debit))
        except Exception:
            self.clear_output("call_debit")

        if put_debit is not None and call_debit is not None:
            total_debit = put_debit + call_debit
            self.theoretical_open_debit = total_debit
            self.set_output("total_debit", fmt_money(total_debit))
        else:
            self.clear_output("total_debit")

        # Breakeven must use the full strategy debit, not the single-leg debit.
        # Actual open debit has priority; if blank, fall back to theoretical total debit.
        try:
            if spot is None or spot <= 0 or long_put is None or long_call is None:
                raise ValueError("Missing breakeven inputs")

            breakeven_debit = self.get_open_debit_for_pnl()
            if breakeven_debit is None:
                breakeven_debit = total_debit

            if breakeven_debit is None or breakeven_debit <= 0:
                raise ValueError("Missing total debit for breakeven")

            downside_breakeven = long_put - breakeven_debit
            upside_breakeven = long_call + breakeven_debit

            if downside_breakeven <= 0 or upside_breakeven <= 0:
                raise ValueError("Invalid breakeven")

            downside_breakeven_move = log_move_pct(spot, downside_breakeven)
            upside_breakeven_move = log_move_pct(spot, upside_breakeven)

            self.set_output("open_downside_breakeven_price", fmt_price(downside_breakeven))
            self.set_output("open_downside_breakeven_move_pct", fmt_signed_pct(downside_breakeven_move))
            self.set_output("open_upside_breakeven_price", fmt_price(upside_breakeven))
            self.set_output("open_upside_breakeven_move_pct", fmt_signed_pct(upside_breakeven_move))

            self.set_output_style("open_downside_breakeven_price", downside_breakeven_move)
            self.set_output_style("open_downside_breakeven_move_pct", downside_breakeven_move)
            self.set_output_style("open_upside_breakeven_price", upside_breakeven_move)
            self.set_output_style("open_upside_breakeven_move_pct", upside_breakeven_move)

        except Exception:
            self.clear_output(
                "open_downside_breakeven_price",
                "open_downside_breakeven_move_pct",
                "open_upside_breakeven_price",
                "open_upside_breakeven_move_pct",
            )
            self.set_output_style("open_downside_breakeven_price", None)
            self.set_output_style("open_downside_breakeven_move_pct", None)
            self.set_output_style("open_upside_breakeven_price", None)
            self.set_output_style("open_upside_breakeven_move_pct", None)

        try:
            current_iv = avg_iv
            normal_iv = get_long_term_iv_decimal(self.inputs)

            if spot is None or spot <= 0 or current_iv is None or normal_iv is None:
                raise ValueError("Missing implied move inputs")

            t_before = time_to_friday_4pm_years(
                self.input("open_day"),
                self.input("open_hour"),
                self.input("open_minute"),
            )

            event_variance = implied_event_variance(current_iv, normal_iv, t_before)

            if event_variance < 0:
                raise ValueError("Negative event variance")

            implied_move = math.sqrt(event_variance)

            downside = price_from_log_move(spot, -implied_move)
            prob50_downside = price_from_log_move(spot, -PROB50_Z * implied_move)
            prob50_upside = price_from_log_move(spot, PROB50_Z * implied_move)
            upside = price_from_log_move(spot, implied_move)

            self.downside_price_value = downside
            self.prob50_downside_price_value = prob50_downside
            self.prob50_upside_price_value = prob50_upside
            self.upside_price_value = upside

            self.set_output("implied_move_pct", fmt_pct(implied_move * 100.0))
            self.set_output("downside_price", fmt_price(downside))
            self.set_output("upside_price", fmt_price(upside))

        except Exception:
            self.downside_price_value = None
            self.prob50_downside_price_value = None
            self.prob50_upside_price_value = None
            self.upside_price_value = None
            self.clear_output(
                "implied_move_pct",
                "downside_price",
                "upside_price",
            )

    def clear_expiration_expectation_outputs(self):
        self.clear_output(
            "exp_implied_move_pct",
            "exp_implied_move_down_price",
            "exp_implied_move_up_price",
            "exp_prob50_move_pct",
            "exp_prob50_down_price",
            "exp_prob50_up_price",
            "exp_long_call_itm_prob",
            "exp_long_put_itm_prob",
            "exp_breakeven_call_prob",
            "exp_breakeven_put_prob",
            "exp_short_call_itm_prob",
            "exp_short_put_itm_prob",
        )

    def recalculate_expiration_expectation(self):
        self.clear_expiration_expectation_outputs()

        try:
            spot = parse_float(self.input("open_market_price"))
            if spot is None or spot <= 0:
                raise ValueError("Missing open market price")

            t_exp = time_to_friday_4pm_years(
                self.input("open_day"),
                self.input("open_hour"),
                self.input("open_minute"),
            )
            if t_exp < 0:
                raise ValueError("Invalid time to expiry")

            avg_iv = get_atm_iv_decimal(self.inputs)
            if avg_iv is None or avg_iv <= 0:
                raise ValueError("Missing ATM IV")

            exp_move = avg_iv * math.sqrt(t_exp)
            exp_move_pct = exp_move * 100.0
            exp_down = price_from_log_move(spot, -exp_move)
            exp_up = price_from_log_move(spot, exp_move)

            prob50_move = PROB50_Z * exp_move
            prob50_move_pct = prob50_move * 100.0
            prob50_down = price_from_log_move(spot, -prob50_move)
            prob50_up = price_from_log_move(spot, prob50_move)

            self.set_output("exp_implied_move_pct", fmt_pct(exp_move_pct))
            self.set_output("exp_implied_move_down_price", fmt_price(exp_down))
            self.set_output("exp_implied_move_up_price", fmt_price(exp_up))
            self.set_output("exp_prob50_move_pct", fmt_pct(prob50_move_pct))
            self.set_output("exp_prob50_down_price", fmt_price(prob50_down))
            self.set_output("exp_prob50_up_price", fmt_price(prob50_up))

            long_put = parse_float(self.input("long_put_strike"))
            long_call = parse_float(self.input("long_call_strike"))
            spread = parse_float(self.input("spread"))

            if long_put is None or long_call is None or spread is None or spread <= 0:
                raise ValueError("Missing strikes or spread")

            short_put = long_put - spread
            short_call = long_call + spread
            if short_put <= 0 or short_call <= 0:
                raise ValueError("Invalid short strikes")

            call_iv_raw = parse_float(self.input("atm_call_iv"))
            put_iv_raw = parse_float(self.input("atm_put_iv"))
            call_iv = avg_iv if call_iv_raw is None else call_iv_raw / 100.0
            put_iv = avg_iv if put_iv_raw is None else put_iv_raw / 100.0
            r = get_open_r_decimal(self.inputs)

            long_call_prob = bs_itm_probability(
                spot=spot,
                strike=long_call,
                t_years=t_exp,
                r=r,
                iv=call_iv,
                option_type="call",
            )
            long_put_prob = bs_itm_probability(
                spot=spot,
                strike=long_put,
                t_years=t_exp,
                r=r,
                iv=put_iv,
                option_type="put",
            )
            short_call_prob = bs_itm_probability(
                spot=spot,
                strike=short_call,
                t_years=t_exp,
                r=r,
                iv=call_iv,
                option_type="call",
            )
            short_put_prob = bs_itm_probability(
                spot=spot,
                strike=short_put,
                t_years=t_exp,
                r=r,
                iv=put_iv,
                option_type="put",
            )

            open_debit = self.get_open_debit_for_pnl()
            breakeven_call_prob = None
            breakeven_put_prob = None

            if open_debit is not None and open_debit > 0:
                downside_breakeven = long_put - open_debit
                upside_breakeven = long_call + open_debit

                if downside_breakeven > 0 and upside_breakeven > 0:
                    breakeven_call_prob = bs_itm_probability(
                        spot=spot,
                        strike=upside_breakeven,
                        t_years=t_exp,
                        r=r,
                        iv=call_iv,
                        option_type="call",
                    )
                    breakeven_put_prob = bs_itm_probability(
                        spot=spot,
                        strike=downside_breakeven,
                        t_years=t_exp,
                        r=r,
                        iv=put_iv,
                        option_type="put",
                    )

            self.set_output("exp_long_call_itm_prob", fmt_pct(long_call_prob * 100.0))
            self.set_output("exp_long_put_itm_prob", fmt_pct(long_put_prob * 100.0))
            if breakeven_call_prob is not None and breakeven_put_prob is not None:
                self.set_output("exp_breakeven_call_prob", fmt_pct(breakeven_call_prob * 100.0))
                self.set_output("exp_breakeven_put_prob", fmt_pct(breakeven_put_prob * 100.0))
            self.set_output("exp_short_call_itm_prob", fmt_pct(short_call_prob * 100.0))
            self.set_output("exp_short_put_itm_prob", fmt_pct(short_put_prob * 100.0))

        except Exception:
            self.clear_expiration_expectation_outputs()

    def recalculate_closing_credit(self):
        try:
            spot = parse_float(self.input("close_market_price"))
            spread = parse_float(self.input("spread"))
            long_put = parse_float(self.input("long_put_strike"))
            long_call = parse_float(self.input("long_call_strike"))
            sim_iv = get_sim_iv_decimal(self.inputs)

            r = get_close_r_decimal(self.inputs)

            if (
                spot is None
                or spread is None
                or long_put is None
                or long_call is None
                or sim_iv is None
            ):
                raise ValueError("Missing closing inputs")

            if spot <= 0 or spread <= 0:
                raise ValueError("Invalid spot or spread")

            short_put = long_put - spread
            short_call = long_call + spread

            close_day = get_close_day(self.inputs)

            t_after = time_to_friday_4pm_years(
                close_day,
                self.input("close_hour"),
                self.input("close_minute"),
            )

            put_credit, call_credit = strategy_put_call_credit(
                spot=spot,
                t_years=t_after,
                r=r,
                iv=sim_iv,
                long_put=long_put,
                short_put=short_put,
                long_call=long_call,
                short_call=short_call,
            )

            total_credit = put_credit + call_credit
            self.theoretical_close_credit = total_credit

            self.set_output("put_credit", fmt_money(put_credit))
            self.set_output("call_credit", fmt_money(call_credit))
            self.set_output("total_credit", fmt_money(total_credit))

        except Exception:
            self.theoretical_close_credit = None
            self.clear_output(
                "put_credit",
                "call_credit",
                "total_credit",
            )

    def recalculate_pnl(self):
        try:
            close_credit = self.theoretical_close_credit
            if close_credit is None:
                raise ValueError("Missing close credit")

            open_debit = self.get_open_debit_for_pnl()

            if open_debit is None or open_debit <= 0:
                raise ValueError("Missing open debit")

            pnl = close_credit - open_debit
            pnl_pct = pnl / open_debit * 100.0

            self.set_output("pnl_dollar", fmt_signed_money(pnl))
            self.set_output("pnl_pct", fmt_signed_pct(pnl_pct))
            self.set_pnl_style(pnl)

        except Exception:
            self.clear_output("pnl_dollar", "pnl_pct")
            self.set_pnl_style(None)

    def clear_scenario_outputs(self):
        for key, _ in SCENARIOS:
            self.clear_output(
                f"scenario_{key}_price",
                f"scenario_{key}_credit",
                f"scenario_{key}_pnl_dollar",
                f"scenario_{key}_pnl_pct",
            )

            self.set_output_style(f"scenario_{key}_credit", None)
            self.set_output_style(f"scenario_{key}_pnl_dollar", None)
            self.set_output_style(f"scenario_{key}_pnl_pct", None)

    def recalculate_scenario_pnl(self):
        self.clear_scenario_outputs()

        try:
            spread = parse_float(self.input("spread"))
            long_put = parse_float(self.input("long_put_strike"))
            long_call = parse_float(self.input("long_call_strike"))
            sim_iv = get_sim_iv_decimal(self.inputs)

            open_debit = self.get_open_debit_for_pnl()

            if (
                spread is None
                or long_put is None
                or long_call is None
                or sim_iv is None
                or open_debit is None
            ):
                raise ValueError("Missing scenario inputs")

            if spread <= 0 or open_debit <= 0:
                raise ValueError("Invalid scenario inputs")

            short_put = long_put - spread
            short_call = long_call + spread
            middle = (long_put + long_call) / 2.0

            r = get_close_r_decimal(self.inputs)

            close_day = get_close_day(self.inputs)

            t_930 = time_to_friday_4pm_years(
                close_day,
                "9",
                "30",
            )

            price_levels = {
                "downside": self.downside_price_value,
                "prob50_downside": self.prob50_downside_price_value,
                "short_put": short_put,
                "long_put": long_put,
                "middle": middle,
                "long_call": long_call,
                "short_call": short_call,
                "prob50_upside": self.prob50_upside_price_value,
                "upside": self.upside_price_value,
            }

            for key, _ in SCENARIOS:
                price = price_levels.get(key)

                if price is None or price <= 0:
                    continue

                total_credit = strategy_credit(
                    spot=price,
                    t_years=t_930,
                    r=r,
                    iv=sim_iv,
                    long_put=long_put,
                    short_put=short_put,
                    long_call=long_call,
                    short_call=short_call,
                )

                pnl = total_credit - open_debit
                pnl_pct = pnl / open_debit * 100.0

                self.set_output(f"scenario_{key}_price", fmt_price(price))
                self.set_output(f"scenario_{key}_credit", fmt_money(total_credit))
                self.set_output(f"scenario_{key}_pnl_dollar", fmt_signed_money(pnl))
                self.set_output(f"scenario_{key}_pnl_pct", fmt_signed_pct(pnl_pct))

                self.set_output_style(f"scenario_{key}_credit", pnl)
                self.set_output_style(f"scenario_{key}_pnl_dollar", pnl)
                self.set_output_style(f"scenario_{key}_pnl_pct", pnl)

        except Exception:
            self.clear_scenario_outputs()

    def clear_simulated_breakeven_outputs(self):
        self.clear_output(
            "sim_downside_breakeven_price",
            "sim_downside_breakeven_move_pct",
            "sim_upside_breakeven_price",
            "sim_upside_breakeven_move_pct",
        )
        self.set_output_style("sim_downside_breakeven_price", None)
        self.set_output_style("sim_downside_breakeven_move_pct", None)
        self.set_output_style("sim_upside_breakeven_price", None)
        self.set_output_style("sim_upside_breakeven_move_pct", None)

    def recalculate_simulated_breakevens(self):
        self.clear_simulated_breakeven_outputs()

        try:
            open_spot = parse_float(self.input("open_market_price"))
            close_spot = parse_float(self.input("close_market_price"))
            spread = parse_float(self.input("spread"))
            long_put = parse_float(self.input("long_put_strike"))
            long_call = parse_float(self.input("long_call_strike"))
            sim_iv = get_sim_iv_decimal(self.inputs)
            open_debit = self.get_open_debit_for_pnl()

            if (
                open_spot is None
                or close_spot is None
                or spread is None
                or long_put is None
                or long_call is None
                or sim_iv is None
                or open_debit is None
            ):
                raise ValueError("Missing simulated breakeven inputs")

            if open_spot <= 0 or close_spot <= 0 or spread <= 0 or open_debit <= 0:
                raise ValueError("Invalid simulated breakeven inputs")

            short_put = long_put - spread
            short_call = long_call + spread
            middle = (long_put + long_call) / 2.0
            r = get_close_r_decimal(self.inputs)
            close_day = get_close_day(self.inputs)

            t_930 = time_to_friday_4pm_years(
                close_day,
                "9",
                "30",
            )

            def pnl_at_price(price: float) -> float:
                total_credit = strategy_credit(
                    spot=price,
                    t_years=t_930,
                    r=r,
                    iv=sim_iv,
                    long_put=long_put,
                    short_put=short_put,
                    long_call=long_call,
                    short_call=short_call,
                )
                return total_credit - open_debit

            low = max(0.01, min(open_spot, close_spot, short_put, long_put) * 0.25)
            high = max(open_spot, close_spot, short_call, long_call) * 1.75

            # Expand until the wings are far enough to capture the U-shaped payoff roots.
            for _ in range(6):
                if pnl_at_price(low) > 0:
                    break
                low *= 0.6
                if low < 0.01:
                    low = 0.01
                    break

            for _ in range(6):
                if pnl_at_price(high) > 0:
                    break
                high *= 1.4

            downside_be = find_breakeven_in_range(pnl_at_price, low, middle)
            upside_be = find_breakeven_in_range(pnl_at_price, middle, high)

            if downside_be is not None and downside_be > 0:
                downside_move = log_move_pct(open_spot, downside_be)
                self.set_output("sim_downside_breakeven_price", fmt_price(downside_be))
                self.set_output("sim_downside_breakeven_move_pct", fmt_signed_pct(downside_move))
                self.set_output_style("sim_downside_breakeven_price", downside_move)
                self.set_output_style("sim_downside_breakeven_move_pct", downside_move)

            if upside_be is not None and upside_be > 0:
                upside_move = log_move_pct(open_spot, upside_be)
                self.set_output("sim_upside_breakeven_price", fmt_price(upside_be))
                self.set_output("sim_upside_breakeven_move_pct", fmt_signed_pct(upside_move))
                self.set_output_style("sim_upside_breakeven_price", upside_move)
                self.set_output_style("sim_upside_breakeven_move_pct", upside_move)

        except Exception:
            self.clear_simulated_breakeven_outputs()


def calculate(inputs: Mapping[str, str]) -> CalcResult:
    return Calculator(inputs).run()
