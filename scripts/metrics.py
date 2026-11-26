"""Shared metric math and display formats for the financial dashboard.

Every dollar figure in the README is produced with these formatters so the
write-up, the summary file, and the CSV stay on the same numbers.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


def money(amount: int) -> str:
    """Format a dollar amount as billions or trillions, half-up."""
    sign = "-" if amount < 0 else ""
    magnitude = abs(int(amount))
    if magnitude >= 1_000_000_000_000:
        scaled = (Decimal(magnitude) / Decimal(1_000_000_000_000)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return f"{sign}${scaled} trillion"
    scaled = (Decimal(magnitude) / Decimal(1_000_000_000)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return f"{sign}${scaled} billion"


def percent(ratio: Decimal) -> str:
    """Format a ratio as an unsigned one-decimal percent."""
    scaled = (ratio * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{scaled}%"


def signed_percent(ratio: Decimal) -> str:
    """Format a ratio as a signed one-decimal percent."""
    scaled = (ratio * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if scaled > 0:
        return f"+{scaled}%"
    return f"{scaled}%"


def signed_bps(ratio: Decimal) -> str:
    """Format a ratio difference as signed basis points."""
    scaled = (ratio * Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if scaled > 0:
        return f"+{scaled} bps"
    return f"{scaled} bps"


def ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        raise ZeroDivisionError("Cannot divide by zero revenue.")
    return Decimal(numerator) / Decimal(denominator)


def cagr(start: int, end: int, years: int) -> Decimal:
    if start <= 0 or end <= 0 or years <= 0:
        raise ValueError("CAGR needs positive start, end, and year count.")
    return (Decimal(end) / Decimal(start)) ** (Decimal(1) / Decimal(years)) - Decimal(1)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _by_ticker(rows: Iterable[dict], ticker: str) -> list[dict]:
    return [row for row in rows if row["ticker"] == ticker]


def latest_annual(rows: list[dict], ticker: str) -> dict:
    company_rows = _by_ticker(rows, ticker)
    if not company_rows:
        raise KeyError(ticker)
    return max(company_rows, key=lambda row: (int(row["fiscal_year"]), row["period_end"]))


def prior_annual(rows: list[dict], ticker: str, fiscal_year: int) -> dict:
    matches = [
        row
        for row in _by_ticker(rows, ticker)
        if int(row["fiscal_year"]) == fiscal_year - 1
    ]
    if len(matches) != 1:
        raise ValueError(f"{ticker} fiscal {fiscal_year - 1} not found for YoY.")
    return matches[0]


def quarter_sort_key(row: dict) -> tuple:
    order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
    return (int(row["fiscal_year"]), order[row["fiscal_quarter"]], row["period_end"])


def trailing_four_quarters(rows: list[dict], ticker: str) -> list[dict]:
    company_rows = sorted(_by_ticker(rows, ticker), key=quarter_sort_key)
    if len(company_rows) < 4:
        raise ValueError(f"{ticker} does not have four quarters for TTM.")
    return company_rows[-4:]


def company_snapshot(annual_rows: list[dict], quarterly_rows: list[dict], ticker: str) -> dict:
    latest = latest_annual(annual_rows, ticker)
    prior = prior_annual(annual_rows, ticker, int(latest["fiscal_year"]))
    history = sorted(_by_ticker(annual_rows, ticker), key=lambda row: int(row["fiscal_year"]))
    first = history[0]
    years = int(latest["fiscal_year"]) - int(first["fiscal_year"])
    revenue = int(latest["revenue_usd"])
    prior_revenue = int(prior["revenue_usd"])
    gross_profit = int(latest["gross_profit_usd"])
    operating_income = int(latest["operating_income_usd"])
    net_income = int(latest["net_income_usd"])
    operating_cash_flow = int(latest["operating_cash_flow_usd"])
    prior_operating_margin = ratio(int(prior["operating_income_usd"]), prior_revenue)
    operating_margin = ratio(operating_income, revenue)
    ttm_quarters = trailing_four_quarters(quarterly_rows, ticker)
    ttm_revenue = sum(int(row["revenue_usd"]) for row in ttm_quarters)
    return {
        "ticker": ticker,
        "display_name": latest["display_name"],
        "company_name": latest["company_name"],
        "fiscal_year": int(latest["fiscal_year"]),
        "prior_fiscal_year": int(prior["fiscal_year"]),
        "first_fiscal_year": int(first["fiscal_year"]),
        "cagr_years": years,
        "period_end": latest["period_end"],
        "year_ended": int(latest["year_ended"]),
        "revenue_usd": revenue,
        "prior_revenue_usd": prior_revenue,
        "gross_profit_usd": gross_profit,
        "operating_income_usd": operating_income,
        "net_income_usd": net_income,
        "operating_cash_flow_usd": operating_cash_flow,
        "yoy_revenue_growth": signed_percent(ratio(revenue - prior_revenue, prior_revenue)),
        "gross_margin": percent(ratio(gross_profit, revenue)),
        "operating_margin": percent(operating_margin),
        "net_margin": percent(ratio(net_income, revenue)),
        "ocf_margin": percent(ratio(operating_cash_flow, revenue)),
        "operating_margin_change_bps": signed_bps(operating_margin - prior_operating_margin),
        "revenue_cagr": signed_percent(cagr(int(first["revenue_usd"]), revenue, years)),
        "revenue_display": money(revenue),
        "prior_revenue_display": money(prior_revenue),
        "gross_profit_display": money(gross_profit),
        "operating_income_display": money(operating_income),
        "net_income_display": money(net_income),
        "operating_cash_flow_display": money(operating_cash_flow),
        "first_revenue_display": money(int(first["revenue_usd"])),
        "ttm_revenue_usd": ttm_revenue,
        "ttm_revenue_display": money(ttm_revenue),
        "ttm_through": ttm_quarters[-1]["period_end"],
        "ttm_quarters": [
            f"FY{row['fiscal_year']} {row['fiscal_quarter']} ended {row['period_end']}"
            for row in ttm_quarters
        ],
    }


def allowed_figure_strings(annual_rows: list[dict], snapshots: list[dict]) -> list[str]:
    """Every formatted figure the README is allowed to print."""
    allowed: set[str] = set()
    for row in annual_rows:
        revenue = int(row["revenue_usd"])
        allowed.add(money(revenue))
        allowed.add(money(int(row["gross_profit_usd"])))
        allowed.add(money(int(row["operating_income_usd"])))
        allowed.add(money(int(row["net_income_usd"])))
        allowed.add(money(int(row["operating_cash_flow_usd"])))
        allowed.add(percent(ratio(int(row["gross_profit_usd"]), revenue)))
        allowed.add(percent(ratio(int(row["operating_income_usd"]), revenue)))
        allowed.add(percent(ratio(int(row["net_income_usd"]), revenue)))
        allowed.add(percent(ratio(int(row["operating_cash_flow_usd"]), revenue)))
    by_ticker: dict[str, list[dict]] = {}
    for row in annual_rows:
        by_ticker.setdefault(row["ticker"], []).append(row)
    for rows in by_ticker.values():
        ordered = sorted(rows, key=lambda row: int(row["fiscal_year"]))
        for previous, current in zip(ordered, ordered[1:]):
            allowed.add(
                signed_percent(
                    ratio(
                        int(current["revenue_usd"]) - int(previous["revenue_usd"]),
                        int(previous["revenue_usd"]),
                    )
                )
            )
            current_margin = ratio(int(current["operating_income_usd"]), int(current["revenue_usd"]))
            previous_margin = ratio(int(previous["operating_income_usd"]), int(previous["revenue_usd"]))
            allowed.add(signed_bps(current_margin - previous_margin))
        first = ordered[0]
        last = ordered[-1]
        span = int(last["fiscal_year"]) - int(first["fiscal_year"])
        allowed.add(signed_percent(cagr(int(first["revenue_usd"]), int(last["revenue_usd"]), span)))
    combined_revenue = sum(item["revenue_usd"] for item in snapshots)
    combined_net_income = sum(item["net_income_usd"] for item in snapshots)
    combined_operating_income = sum(item["operating_income_usd"] for item in snapshots)
    combined_cash_flow = sum(item["operating_cash_flow_usd"] for item in snapshots)
    allowed.add(money(combined_revenue))
    allowed.add(money(combined_net_income))
    allowed.add(money(combined_operating_income))
    allowed.add(money(combined_cash_flow))
    allowed.add(percent(ratio(combined_operating_income, combined_revenue)))
    allowed.add(percent(ratio(combined_net_income, combined_revenue)))
    allowed.add(percent(ratio(combined_cash_flow, combined_revenue)))
    for item in snapshots:
        allowed.add(item["ttm_revenue_display"])
        allowed.add(item["revenue_display"])
        allowed.add(item["yoy_revenue_growth"])
        allowed.add(item["gross_margin"])
        allowed.add(item["operating_margin"])
        allowed.add(item["net_margin"])
        allowed.add(item["operating_margin_change_bps"])
        allowed.add(item["revenue_cagr"])
    return sorted(allowed)
