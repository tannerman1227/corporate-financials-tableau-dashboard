"""Download real corporate financials from the SEC EDGAR Company Facts API.

The script refreshes the CSV files in data/ and writes data/data_sources.json
plus data/summary_metrics.json. No API key is required. SEC asks callers to
send a descriptive User-Agent and to stay under 10 requests per second.

Fiscal-year labels come from the first 10-K or 10-Q that reported the period.
Later filings sometimes stamp the new form's fiscal year onto older comparison
columns, so the newest filing is used for the amount and the oldest filing is
used for the year and quarter label.

These retailers do not tag a standalone fourth quarter in Company Facts.
Fourth-quarter income-statement amounts are the reported full year minus the
reported first, second, and third quarters.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.metrics import company_snapshot, sha256_bytes

USER_AGENT = "Tanner Allred corporate-financials-tableau-dashboard tannerman1227@gmail.com"
ANNUAL_MIN_PERIOD_END = "2021-01-01"
QUARTER_MIN_PERIOD_END = "2020-01-01"
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
ANNUAL_DAYS = (350, 380)
QUARTER_DAYS = (75, 100)
PEER_GROUP = "U.S. retail leaders"

COMPANIES = [
    {
        "ticker": "WMT",
        "cik": "0000104169",
        "display_name": "Walmart",
        "legal_name": "Walmart Inc.",
        "business": "General merchandise and grocery",
        "fiscal_year_mode": "end_year",
        "revenue_tags": ["Revenues"],
        "cost_tags": ["CostOfRevenue"],
        "gross_profit_tags": [],
    },
    {
        "ticker": "COST",
        "cik": "0000909832",
        "display_name": "Costco",
        "legal_name": "Costco Wholesale Corporation",
        "business": "Membership warehouse clubs",
        "fiscal_year_mode": "end_year",
        "revenue_tags": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
        "cost_tags": ["CostOfGoodsAndServicesSold"],
        "gross_profit_tags": [],
    },
    {
        "ticker": "DG",
        "cik": "0000029534",
        "display_name": "Dollar General",
        "legal_name": "Dollar General Corporation",
        "business": "Discount stores",
        "fiscal_year_mode": "january_year",
        "revenue_tags": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        "cost_tags": ["CostOfGoodsAndServicesSold", "CostOfRevenue"],
        "gross_profit_tags": ["GrossProfit"],
    },
    {
        "ticker": "HD",
        "cik": "0000354950",
        "display_name": "Home Depot",
        "legal_name": "The Home Depot, Inc.",
        "business": "Home improvement",
        "fiscal_year_mode": "january_year",
        "revenue_tags": ["RevenueFromContractWithCustomerExcludingAssessedTax"],
        "cost_tags": ["CostOfRevenue"],
        "gross_profit_tags": ["GrossProfit"],
    },
    {
        "ticker": "LOW",
        "cik": "0000060667",
        "display_name": "Lowe's",
        "legal_name": "Lowe's Companies, Inc.",
        "business": "Home improvement",
        "fiscal_year_mode": "january_year",
        "revenue_tags": ["RevenueFromContractWithCustomerExcludingAssessedTax"],
        "cost_tags": ["CostOfGoodsAndServicesSold"],
        "gross_profit_tags": ["GrossProfit"],
    },
    {
        "ticker": "BBY",
        "cik": "0000764478",
        "display_name": "Best Buy",
        "legal_name": "Best Buy Co., Inc.",
        "business": "Consumer electronics",
        "fiscal_year_mode": "end_year",
        "revenue_tags": ["RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues"],
        "cost_tags": ["CostOfGoodsAndServicesSold"],
        "gross_profit_tags": ["GrossProfit"],
    },
]

OPERATING_INCOME_TAG = "OperatingIncomeLoss"
NET_INCOME_TAG = "NetIncomeLoss"
OCF_TAG = "NetCashProvidedByUsedInOperatingActivities"

ANNUAL_FIELDS = [
    "ticker",
    "display_name",
    "company_name",
    "cik",
    "fiscal_year",
    "year_ended",
    "period_start",
    "period_end",
    "days_in_period",
    "revenue_usd",
    "cost_of_revenue_usd",
    "gross_profit_usd",
    "operating_income_usd",
    "net_income_usd",
    "operating_cash_flow_usd",
    "gross_profit_method",
    "revenue_xbrl_tag",
    "cost_xbrl_tag",
    "gross_profit_xbrl_tag",
    "operating_income_xbrl_tag",
    "net_income_xbrl_tag",
    "ocf_xbrl_tag",
    "source_form",
    "filed_date",
    "accession_number",
    "value_is_restated",
    "companyfacts_url",
    "filing_index_url",
]

QUARTERLY_FIELDS = [
    "ticker",
    "display_name",
    "company_name",
    "cik",
    "fiscal_year",
    "fiscal_quarter",
    "year_ended",
    "period_start",
    "period_end",
    "days_in_period",
    "revenue_usd",
    "cost_of_revenue_usd",
    "gross_profit_usd",
    "operating_income_usd",
    "net_income_usd",
    "operating_cash_flow_usd",
    "value_basis",
    "derivation",
    "gross_profit_method",
    "revenue_xbrl_tag",
    "cost_xbrl_tag",
    "gross_profit_xbrl_tag",
    "operating_income_xbrl_tag",
    "net_income_xbrl_tag",
    "ocf_xbrl_tag",
    "source_form",
    "filed_date",
    "accession_number",
    "value_is_restated",
    "companyfacts_url",
    "filing_index_url",
]

DIM_FIELDS = [
    "ticker",
    "display_name",
    "company_name",
    "sec_entity_name",
    "cik",
    "sic",
    "sic_description",
    "exchange",
    "fiscal_year_end",
    "headquarters_city",
    "headquarters_state",
    "business",
    "peer_group",
    "revenue_xbrl_tag",
    "cost_xbrl_tag",
    "gross_profit_xbrl_tag",
    "operating_income_xbrl_tag",
    "net_income_xbrl_tag",
    "ocf_xbrl_tag",
    "companyfacts_url",
    "submissions_url",
]


def companyfacts_url(cik: str) -> str:
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def submissions_url(cik: str) -> str:
    return f"https://data.sec.gov/submissions/CIK{cik}.json"


def filing_index_url(cik: str, accession: str) -> str:
    cik_int = str(int(cik))
    accession_compact = accession.replace("-", "")
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{accession_compact}/{accession}-index.html"
    )


def fetch_json(url: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return json.loads(raw)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not download {url}: {last_error}")


def days_between(start: str, end: str) -> int:
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    return (end_dt - start_dt).days


def clean_text(value: str) -> str:
    cleaned = value.replace("\u00a0", " ").replace("\u2019", "'").replace("\u2018", "'")
    return " ".join(cleaned.split())


def company_fiscal_year(company: dict, period_end: str) -> int:
    """Return the fiscal year the company uses in its own reports.

    Home Depot, Lowe's, and Dollar General end in January or February and
    name the year for the calendar year that just finished. Walmart, Costco,
    and Best Buy name the year for the calendar year of the period end.
    """
    end = datetime.fromisoformat(period_end)
    if company["fiscal_year_mode"] == "end_year":
        return end.year
    if company["fiscal_year_mode"] == "january_year" and end.month <= 2:
        return end.year - 1
    if company["fiscal_year_mode"] == "january_year":
        return end.year
    raise ValueError(f"Unknown fiscal year mode for {company['ticker']}")


def select_periods(rows: list[dict], kind: str) -> list[dict]:
    low, high = ANNUAL_DAYS if kind == "annual" else QUARTER_DAYS
    minimum_end = ANNUAL_MIN_PERIOD_END if kind == "annual" else QUARTER_MIN_PERIOD_END
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in rows:
        if item.get("form") not in FORMS:
            continue
        start = item.get("start")
        end = item.get("end")
        if not start or not end or item.get("val") is None:
            continue
        if end < minimum_end:
            continue
        span = days_between(start, end)
        if not (low <= span <= high):
            continue
        grouped[end].append(item)

    selected = []
    for end, items in grouped.items():
        earliest = min(items, key=lambda row: (row["filed"], row["accn"]))
        latest = max(items, key=lambda row: (row["filed"], row["accn"]))
        fiscal_period = earliest.get("fp")
        if kind == "annual" and fiscal_period != "FY":
            continue
        if kind == "quarter" and fiscal_period not in {"Q1", "Q2", "Q3", "Q4"}:
            continue
        selected.append(
            {
                "fiscal_year": int(earliest["fy"]),
                "fiscal_period": fiscal_period,
                "period_start": latest["start"],
                "period_end": latest["end"],
                "days_in_period": days_between(latest["start"], latest["end"]),
                "value": int(latest["val"]),
                "source_form": latest["form"],
                "filed_date": latest["filed"],
                "accession_number": latest["accn"],
                "value_is_restated": "yes" if int(latest["val"]) != int(earliest["val"]) else "no",
            }
        )
    return selected


def tag_map(facts: dict, tags: list[str], kind: str) -> dict[str, dict]:
    """Map a period end date to the preferred tag's selected fact.

    Fiscal-year labels on some tags are wrong when the tag first appears in a
    later comparison column. Callers that need the year use the revenue fact,
    then attach the other line items by the shared period end date.
    """
    chosen: dict[str, dict] = {}
    gaap = facts["us-gaap"]
    for tag in tags:
        if tag not in gaap:
            continue
        periods = select_periods(gaap[tag]["units"].get("USD", []), kind)
        for period in periods:
            end = period["period_end"]
            if end in chosen:
                continue
            period = dict(period)
            period["xbrl_tag"] = tag
            chosen[end] = period
    return chosen


def require_overlap_agreement(facts: dict, tags: list[str], kind: str, ticker: str, label: str) -> None:
    """Fallback tags may fill gaps only when they match on shared period ends."""
    if len(tags) < 2:
        return
    maps = []
    gaap = facts["us-gaap"]
    for tag in tags:
        if tag not in gaap:
            maps.append({})
            continue
        periods = {
            item["period_end"]: item["value"]
            for item in select_periods(gaap[tag]["units"].get("USD", []), kind)
        }
        maps.append(periods)
    primary = maps[0]
    for tag, other in zip(tags[1:], maps[1:]):
        shared = set(primary) & set(other)
        for key in shared:
            if primary[key] != other[key]:
                raise RuntimeError(
                    f"{ticker} {label} tag {tag} disagrees with {tags[0]} for {key}: "
                    f"{other[key]} vs {primary[key]}"
                )


def any_restated(*facts: dict) -> str:
    return "yes" if any(fact.get("value_is_restated") == "yes" for fact in facts) else "no"


def build_annual_rows(company: dict, facts: dict) -> list[dict]:
    revenue = tag_map(facts, company["revenue_tags"], "annual")
    cost = tag_map(facts, company["cost_tags"], "annual")
    gross = tag_map(facts, company["gross_profit_tags"], "annual") if company["gross_profit_tags"] else {}
    operating = tag_map(facts, [OPERATING_INCOME_TAG], "annual")
    net_income = tag_map(facts, [NET_INCOME_TAG], "annual")
    cash_flow = tag_map(facts, [OCF_TAG], "annual")
    rows = []
    for end in sorted(revenue):
        revenue_fact = revenue[end]
        missing = [
            name
            for name, series in (
                ("cost", cost),
                ("operating income", operating),
                ("net income", net_income),
                ("operating cash flow", cash_flow),
            )
            if end not in series
        ]
        if missing:
            raise RuntimeError(
                f"{company['ticker']} annual period {end} is missing {', '.join(missing)}."
            )
        year = company_fiscal_year(company, revenue_fact["period_end"])
        sec_year = int(revenue_fact["fiscal_year"])
        # Best Buy's XBRL feed labels the year ended January 30, 2021 as 2020.
        # The company calls that year fiscal 2021, which lines up with every later year.
        if sec_year != year and not (company["ticker"] == "BBY" and year - sec_year == 1):
            raise RuntimeError(
                f"{company['ticker']} period {end} company fiscal year {year} "
                f"does not match the SEC label {sec_year}."
            )
        cost_fact = cost[end]
        operating_fact = operating[end]
        net_fact = net_income[end]
        cash_fact = cash_flow[end]
        if end in gross:
            gross_value = gross[end]["value"]
            gross_tag = gross[end]["xbrl_tag"]
            method = "reported"
            if gross_value != revenue_fact["value"] - cost_fact["value"]:
                raise RuntimeError(
                    f"{company['ticker']} FY{year} reported gross profit {gross_value} "
                    f"does not equal revenue minus cost "
                    f"{revenue_fact['value'] - cost_fact['value']}"
                )
        else:
            gross_value = revenue_fact["value"] - cost_fact["value"]
            gross_tag = "revenue minus cost of revenue"
            method = "calculated"
        rows.append(
            {
                "ticker": company["ticker"],
                "display_name": company["display_name"],
                "company_name": company["legal_name"],
                "cik": company["cik"],
                "fiscal_year": year,
                "year_ended": int(revenue_fact["period_end"][:4]),
                "period_start": revenue_fact["period_start"],
                "period_end": revenue_fact["period_end"],
                "days_in_period": revenue_fact["days_in_period"],
                "revenue_usd": revenue_fact["value"],
                "cost_of_revenue_usd": cost_fact["value"],
                "gross_profit_usd": gross_value,
                "operating_income_usd": operating_fact["value"],
                "net_income_usd": net_fact["value"],
                "operating_cash_flow_usd": cash_fact["value"],
                "gross_profit_method": method,
                "revenue_xbrl_tag": revenue_fact["xbrl_tag"],
                "cost_xbrl_tag": cost_fact["xbrl_tag"],
                "gross_profit_xbrl_tag": gross_tag,
                "operating_income_xbrl_tag": operating_fact["xbrl_tag"],
                "net_income_xbrl_tag": net_fact["xbrl_tag"],
                "ocf_xbrl_tag": cash_fact["xbrl_tag"],
                "source_form": revenue_fact["source_form"],
                "filed_date": revenue_fact["filed_date"],
                "accession_number": revenue_fact["accession_number"],
                "value_is_restated": any_restated(
                    revenue_fact, cost_fact, operating_fact, net_fact, cash_fact
                ),
                "companyfacts_url": companyfacts_url(company["cik"]),
                "filing_index_url": filing_index_url(company["cik"], revenue_fact["accession_number"]),
            }
        )
    return rows


def build_quarterly_rows(company: dict, facts: dict, annual_rows: list[dict]) -> list[dict]:
    revenue = tag_map(facts, company["revenue_tags"], "quarter")
    cost = tag_map(facts, company["cost_tags"], "quarter")
    gross = tag_map(facts, company["gross_profit_tags"], "quarter") if company["gross_profit_tags"] else {}
    operating = tag_map(facts, [OPERATING_INCOME_TAG], "quarter")
    net_income = tag_map(facts, [NET_INCOME_TAG], "quarter")
    cash_flow = tag_map(facts, [OCF_TAG], "quarter")
    reported_ends = sorted(set(revenue) & set(cost) & set(operating) & set(net_income))
    rows = []
    for end in reported_ends:
        # Quarter labels come from revenue. The other tags are only the amounts.
        revenue_fact = dict(revenue[end])
        pieces = [revenue_fact, cost[end], operating[end], net_income[end]]
        if end in cash_flow:
            pieces.append(cash_flow[end])
        if end in gross:
            pieces.append(gross[end])
        revenue_fact["value_is_restated"] = any_restated(*pieces)
        rows.append(
            quarter_row(
                company,
                revenue_fact,
                cost[end],
                gross.get(end),
                operating[end],
                net_income[end],
                cash_flow.get(end),
                "reported",
                "",
            )
        )

    # Place each reported quarter inside the annual year it belongs to.
    # The XBRL quarter label is sometimes wrong, so order by period end.
    labeled: list[dict] = []
    used_ends: set[str] = set()
    for annual in annual_rows:
        inside = [
            row
            for row in rows
            if annual["period_start"] < row["period_end"] < annual["period_end"]
        ]
        inside.sort(key=lambda row: row["period_end"])
        if len(inside) != 3:
            raise RuntimeError(
                f"{company['ticker']} FY{annual['fiscal_year']} has {len(inside)} "
                "reported quarters inside the year, expected 3."
            )
        quarter_names = ("Q1", "Q2", "Q3")
        named = []
        for name, row in zip(quarter_names, inside):
            row = dict(row)
            row["fiscal_year"] = int(annual["fiscal_year"])
            row["fiscal_quarter"] = name
            named.append(row)
            used_ends.add(row["period_end"])
        labeled.extend(named)
        labeled.append(derive_q4(company, annual, named[0], named[1], named[2]))

    last_annual_end = annual_rows[-1]["period_end"]
    upcoming = [row for row in rows if row["period_end"] > last_annual_end and row["period_end"] not in used_ends]
    upcoming.sort(key=lambda row: row["period_end"])
    if len(upcoming) > 3:
        raise RuntimeError(f"{company['ticker']} has {len(upcoming)} quarters after the latest full year.")
    next_year = int(annual_rows[-1]["fiscal_year"]) + 1
    for index, row in enumerate(upcoming, start=1):
        row = dict(row)
        row["fiscal_year"] = next_year
        row["fiscal_quarter"] = f"Q{index}"
        labeled.append(row)

    labeled.sort(key=lambda row: (int(row["fiscal_year"]), row["fiscal_quarter"]))
    return labeled


def quarter_row(
    company: dict,
    revenue_fact: dict,
    cost_fact: dict,
    gross_fact: dict | None,
    operating_fact: dict,
    net_fact: dict,
    cash_fact: dict | None,
    basis: str,
    derivation: str,
) -> dict:
    if gross_fact is not None:
        gross_value = gross_fact["value"]
        gross_tag = gross_fact["xbrl_tag"]
        method = "reported"
        if gross_value != revenue_fact["value"] - cost_fact["value"]:
            raise RuntimeError(
                f"{company['ticker']} {revenue_fact['fiscal_year']} {revenue_fact['fiscal_period']} "
                "reported gross profit does not equal revenue minus cost."
            )
    else:
        gross_value = revenue_fact["value"] - cost_fact["value"]
        gross_tag = "revenue minus cost of revenue"
        method = "calculated"
    cash_value = cash_fact["value"] if cash_fact else ""
    return {
        "ticker": company["ticker"],
        "display_name": company["display_name"],
        "company_name": company["legal_name"],
        "cik": company["cik"],
        "fiscal_year": int(revenue_fact["fiscal_year"]),
        "fiscal_quarter": revenue_fact["fiscal_period"],
        "year_ended": int(revenue_fact["period_end"][:4]),
        "period_start": revenue_fact["period_start"],
        "period_end": revenue_fact["period_end"],
        "days_in_period": revenue_fact["days_in_period"],
        "revenue_usd": revenue_fact["value"],
        "cost_of_revenue_usd": cost_fact["value"],
        "gross_profit_usd": gross_value,
        "operating_income_usd": operating_fact["value"],
        "net_income_usd": net_fact["value"],
        "operating_cash_flow_usd": cash_value,
        "value_basis": basis,
        "derivation": derivation,
        "gross_profit_method": method,
        "revenue_xbrl_tag": revenue_fact["xbrl_tag"],
        "cost_xbrl_tag": cost_fact["xbrl_tag"],
        "gross_profit_xbrl_tag": gross_tag,
        "operating_income_xbrl_tag": operating_fact["xbrl_tag"],
        "net_income_xbrl_tag": net_fact["xbrl_tag"],
        "ocf_xbrl_tag": cash_fact["xbrl_tag"] if cash_fact else "",
        "source_form": revenue_fact["source_form"],
        "filed_date": revenue_fact["filed_date"],
        "accession_number": revenue_fact["accession_number"],
        "value_is_restated": revenue_fact["value_is_restated"],
        "companyfacts_url": companyfacts_url(company["cik"]),
        "filing_index_url": filing_index_url(company["cik"], revenue_fact["accession_number"]),
    }


def derive_q4(company: dict, annual: dict, q1: dict, q2: dict, q3: dict) -> dict:
    def remainder(field: str) -> int:
        return int(annual[field]) - int(q1[field]) - int(q2[field]) - int(q3[field])

    revenue = remainder("revenue_usd")
    cost = remainder("cost_of_revenue_usd")
    operating_income = remainder("operating_income_usd")
    net_income = remainder("net_income_usd")
    gross = revenue - cost
    if gross != remainder("gross_profit_usd"):
        raise RuntimeError(f"{company['ticker']} FY{annual['fiscal_year']} Q4 gross profit does not reconcile.")
    share = revenue / int(annual["revenue_usd"])
    if not (0.15 <= share <= 0.45):
        raise RuntimeError(
            f"{company['ticker']} FY{annual['fiscal_year']} derived Q4 revenue share {share:.1%} "
            "is outside 15% to 45%."
        )
    start_dt = datetime.fromisoformat(q3["period_end"]).date()
    period_start = (start_dt + timedelta(days=1)).isoformat()
    period_end = annual["period_end"]
    restated = "yes" if "yes" in {
        annual["value_is_restated"],
        q1["value_is_restated"],
        q2["value_is_restated"],
        q3["value_is_restated"],
    } else "no"
    return {
        "ticker": company["ticker"],
        "display_name": company["display_name"],
        "company_name": company["legal_name"],
        "cik": company["cik"],
        "fiscal_year": int(annual["fiscal_year"]),
        "fiscal_quarter": "Q4",
        "year_ended": int(period_end[:4]),
        "period_start": period_start,
        "period_end": period_end,
        "days_in_period": days_between(period_start, period_end),
        "revenue_usd": revenue,
        "cost_of_revenue_usd": cost,
        "gross_profit_usd": gross,
        "operating_income_usd": operating_income,
        "net_income_usd": net_income,
        "operating_cash_flow_usd": "",
        "value_basis": "derived_q4",
        "derivation": "Reported full-year amount minus reported Q1, Q2, and Q3.",
        "gross_profit_method": "calculated",
        "revenue_xbrl_tag": annual["revenue_xbrl_tag"],
        "cost_xbrl_tag": annual["cost_xbrl_tag"],
        "gross_profit_xbrl_tag": "revenue minus cost of revenue",
        "operating_income_xbrl_tag": annual["operating_income_xbrl_tag"],
        "net_income_xbrl_tag": annual["net_income_xbrl_tag"],
        "ocf_xbrl_tag": "",
        "source_form": annual["source_form"],
        "filed_date": annual["filed_date"],
        "accession_number": annual["accession_number"],
        "value_is_restated": restated,
        "companyfacts_url": annual["companyfacts_url"],
        "filing_index_url": annual["filing_index_url"],
    }


def assert_series_quality(company: dict, annual_rows: list[dict], quarterly_rows: list[dict]) -> None:
    ticker = company["ticker"]
    if len(annual_rows) < 5:
        raise RuntimeError(f"{ticker} has only {len(annual_rows)} annual years.")
    years = [int(row["fiscal_year"]) for row in annual_rows]
    if years != list(range(years[0], years[-1] + 1)):
        raise RuntimeError(f"{ticker} fiscal years are not consecutive: {years}")
    year_ended = [int(row["year_ended"]) for row in annual_rows]
    if year_ended != list(range(year_ended[0], year_ended[-1] + 1)):
        raise RuntimeError(f"{ticker} year-ended labels are not consecutive: {year_ended}")
    for row in annual_rows:
        revenue = int(row["revenue_usd"])
        gross_margin = int(row["gross_profit_usd"]) / revenue
        operating_margin = int(row["operating_income_usd"]) / revenue
        net_margin = int(row["net_income_usd"]) / revenue
        if int(row["gross_profit_usd"]) != revenue - int(row["cost_of_revenue_usd"]):
            raise RuntimeError(f"{ticker} FY{row['fiscal_year']} gross profit identity failed.")
        if not (0.05 < gross_margin < 0.50):
            raise RuntimeError(f"{ticker} FY{row['fiscal_year']} gross margin {gross_margin:.1%} looks wrong.")
        if not (0 < operating_margin < 0.25):
            raise RuntimeError(f"{ticker} FY{row['fiscal_year']} operating margin {operating_margin:.1%} looks wrong.")
        if not (-0.05 < net_margin < 0.20):
            raise RuntimeError(f"{ticker} FY{row['fiscal_year']} net margin {net_margin:.1%} looks wrong.")
        if int(row["operating_cash_flow_usd"]) <= 0:
            raise RuntimeError(f"{ticker} FY{row['fiscal_year']} operating cash flow is not positive.")
    annual_years = set(years)
    for year in years:
        parts = [
            row
            for row in quarterly_rows
            if int(row["fiscal_year"]) == year and row["fiscal_quarter"] in {"Q1", "Q2", "Q3", "Q4"}
        ]
        if len(parts) != 4:
            raise RuntimeError(f"{ticker} FY{year} has {len(parts)} quarters, expected 4.")
        annual = next(row for row in annual_rows if int(row["fiscal_year"]) == year)
        for field in (
            "revenue_usd",
            "cost_of_revenue_usd",
            "gross_profit_usd",
            "operating_income_usd",
            "net_income_usd",
        ):
            total = sum(int(row[field]) for row in parts)
            if total != int(annual[field]):
                raise RuntimeError(
                    f"{ticker} FY{year} {field} quarters sum to {total}, annual is {annual[field]}."
                )
    extra_years = {int(row["fiscal_year"]) for row in quarterly_rows} - annual_years
    for year in extra_years:
        parts = [row for row in quarterly_rows if int(row["fiscal_year"]) == year]
        quarters = {row["fiscal_quarter"] for row in parts}
        if quarters - {"Q1", "Q2", "Q3"}:
            raise RuntimeError(f"{ticker} FY{year} partial-year quarters look wrong: {sorted(quarters)}")


def load_company(company: dict) -> tuple[dict, dict, list[dict], list[dict]]:
    facts_payload = fetch_json(companyfacts_url(company["cik"]))
    time.sleep(0.2)
    submissions = fetch_json(submissions_url(company["cik"]))
    time.sleep(0.2)
    facts = facts_payload["facts"]
    require_overlap_agreement(facts, company["revenue_tags"], "annual", company["ticker"], "revenue")
    require_overlap_agreement(facts, company["revenue_tags"], "quarter", company["ticker"], "revenue")
    annual_rows = build_annual_rows(company, facts)
    quarterly_rows = build_quarterly_rows(company, facts, annual_rows)
    assert_series_quality(company, annual_rows, quarterly_rows)
    entity_name = clean_text(facts_payload.get("entityName", ""))
    address = submissions.get("addresses", {}).get("business", {})
    exchanges = submissions.get("exchanges") or []
    profile = {
        "ticker": company["ticker"],
        "display_name": company["display_name"],
        "company_name": company["legal_name"],
        "sec_entity_name": entity_name,
        "cik": company["cik"],
        "sic": str(submissions.get("sic", "")),
        "sic_description": clean_text(str(submissions.get("sicDescription", ""))),
        "exchange": exchanges[0] if exchanges else "",
        "fiscal_year_end": str(submissions.get("fiscalYearEnd", "")),
        "headquarters_city": clean_text(str(address.get("city", ""))).title(),
        "headquarters_state": str(address.get("stateOrCountry", "")),
        "business": company["business"],
        "peer_group": PEER_GROUP,
        "revenue_xbrl_tag": annual_rows[-1]["revenue_xbrl_tag"],
        "cost_xbrl_tag": annual_rows[-1]["cost_xbrl_tag"],
        "gross_profit_xbrl_tag": annual_rows[-1]["gross_profit_xbrl_tag"],
        "operating_income_xbrl_tag": OPERATING_INCOME_TAG,
        "net_income_xbrl_tag": NET_INCOME_TAG,
        "ocf_xbrl_tag": OCF_TAG,
        "companyfacts_url": companyfacts_url(company["cik"]),
        "submissions_url": submissions_url(company["cik"]),
    }
    if submissions.get("tickers") and company["ticker"] not in submissions["tickers"]:
        raise RuntimeError(f"{company['ticker']} not in SEC tickers {submissions.get('tickers')}")
    return profile, facts_payload, annual_rows, quarterly_rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def build_summary(annual_rows: list[dict], quarterly_rows: list[dict], data_dir: Path) -> dict:
    order = [company["ticker"] for company in COMPANIES]
    snapshots = [company_snapshot(annual_rows, quarterly_rows, ticker) for ticker in order]
    combined_revenue = sum(item["revenue_usd"] for item in snapshots)
    combined_operating_income = sum(item["operating_income_usd"] for item in snapshots)
    combined_net_income = sum(item["net_income_usd"] for item in snapshots)
    combined_cash_flow = sum(item["operating_cash_flow_usd"] for item in snapshots)
    from scripts.metrics import money, percent, ratio

    required = []
    for item in snapshots:
        required.extend(
            [
                item["revenue_display"],
                item["yoy_revenue_growth"],
                item["gross_margin"],
                item["operating_margin"],
                item["net_margin"],
                item["net_income_display"],
                item["operating_cash_flow_display"],
                item["operating_margin_change_bps"],
                item["revenue_cagr"],
                item["ttm_revenue_display"],
            ]
        )
    required.extend(
        [
            money(combined_revenue),
            money(combined_operating_income),
            money(combined_net_income),
            money(combined_cash_flow),
            percent(ratio(combined_operating_income, combined_revenue)),
            percent(ratio(combined_net_income, combined_revenue)),
        ]
    )
    # Preserve order while dropping duplicates.
    seen = set()
    required_unique = []
    for item in required:
        if item not in seen:
            seen.add(item)
            required_unique.append(item)
    files = {}
    for name in (
        "company_financials_annual.csv",
        "company_financials_quarterly.csv",
        "dim_company.csv",
    ):
        payload = (data_dir / name).read_bytes()
        files[name] = {"sha256": sha256_bytes(payload), "bytes": len(payload)}
    return {
        "snapshots": snapshots,
        "combined": {
            "revenue_usd": combined_revenue,
            "operating_income_usd": combined_operating_income,
            "net_income_usd": combined_net_income,
            "operating_cash_flow_usd": combined_cash_flow,
            "revenue_display": money(combined_revenue),
            "operating_income_display": money(combined_operating_income),
            "net_income_display": money(combined_net_income),
            "operating_cash_flow_display": money(combined_cash_flow),
            "operating_margin": percent(ratio(combined_operating_income, combined_revenue)),
            "net_margin": percent(ratio(combined_net_income, combined_revenue)),
        },
        "required_readme_strings": required_unique,
        "preview_images": [
            "assets/01_executive_overview.png",
            "assets/02_revenue_and_growth.png",
            "assets/03_profitability_margins.png",
            "assets/04_peer_comparison.png",
        ],
        "inputs": files,
    }


def main() -> None:
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    profiles = []
    annual_rows: list[dict] = []
    quarterly_rows: list[dict] = []
    source_companies = []
    for company in COMPANIES:
        print(f"Fetching {company['display_name']} ({company['ticker']})...")
        profile, _payload, annual, quarterly = load_company(company)
        profiles.append(profile)
        annual_rows.extend(annual)
        quarterly_rows.extend(quarterly)
        source_companies.append(
            {
                "ticker": company["ticker"],
                "display_name": company["display_name"],
                "legal_name": company["legal_name"],
                "sec_entity_name": profile["sec_entity_name"],
                "cik": company["cik"],
                "companyfacts_url": profile["companyfacts_url"],
                "submissions_url": profile["submissions_url"],
                "sic": profile["sic"],
                "sic_description": profile["sic_description"],
                "exchange": profile["exchange"],
                "fiscal_year_end": profile["fiscal_year_end"],
                "headquarters_city": profile["headquarters_city"],
                "headquarters_state": profile["headquarters_state"],
                "annual_period_end_min": annual[0]["period_end"],
                "annual_period_end_max": annual[-1]["period_end"],
                "annual_fiscal_years": [int(row["fiscal_year"]) for row in annual],
                "quarterly_period_end_min": min(row["period_end"] for row in quarterly),
                "quarterly_period_end_max": max(row["period_end"] for row in quarterly),
                "quarterly_rows": len(quarterly),
                "xbrl_tags": {
                    "revenue": profile["revenue_xbrl_tag"],
                    "cost_of_revenue": profile["cost_xbrl_tag"],
                    "gross_profit": profile["gross_profit_xbrl_tag"],
                    "operating_income": OPERATING_INCOME_TAG,
                    "net_income": NET_INCOME_TAG,
                    "operating_cash_flow": OCF_TAG,
                },
            }
        )
        print(
            f"  {len(annual)} fiscal years ({annual[0]['fiscal_year']}-{annual[-1]['fiscal_year']}), "
            f"{len(quarterly)} quarters, latest revenue {annual[-1]['revenue_usd']:,}"
        )

    ticker_order = {company["ticker"]: index for index, company in enumerate(COMPANIES)}
    annual_rows.sort(key=lambda row: (ticker_order[row["ticker"]], int(row["fiscal_year"])))
    quarterly_rows.sort(
        key=lambda row: (
            ticker_order[row["ticker"]],
            int(row["fiscal_year"]),
            row["fiscal_quarter"],
        )
    )
    write_csv(data_dir / "company_financials_annual.csv", ANNUAL_FIELDS, annual_rows)
    write_csv(data_dir / "company_financials_quarterly.csv", QUARTERLY_FIELDS, quarterly_rows)
    write_csv(data_dir / "dim_company.csv", DIM_FIELDS, profiles)

    sources = {
        "fetch_timestamp_utc": fetched_at,
        "user_agent": USER_AGENT,
        "api": "SEC EDGAR Company Facts API",
        "api_documentation": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "peer_group": PEER_GROUP,
        "currency": "USD",
        "annual_minimum_period_end": ANNUAL_MIN_PERIOD_END,
        "quarterly_minimum_period_end": QUARTER_MIN_PERIOD_END,
        "companies": source_companies,
        "methodology": [
            "Amounts are taken from us-gaap XBRL facts in SEC Company Facts, units USD.",
            "Only 10-K, 10-K/A, 10-Q, and 10-Q/A facts are used.",
            "The annual fact is the full-year duration (about 52 or 53 weeks) with fiscal period FY.",
            "The quarterly fact is the standalone quarter (about 12 or 13 weeks), not a year-to-date total.",
            "When a later filing repeats an older period, the newest amount is kept. Quarter labels are assigned by where the quarter sits inside the fiscal year, because some XBRL tags reuse the wrong year on older columns.",
            "Home Depot, Lowe's, and Dollar General end the year in January or February and name that fiscal year for the prior calendar year. Walmart, Costco, and Best Buy name the fiscal year for the calendar year of the period end. Best Buy's XBRL feed labels the year ended January 30, 2021 as 2020; the company calls it fiscal 2021, and that is the label used here.",
            "Fourth-quarter income-statement amounts are the reported full year minus reported Q1, Q2, and Q3. Company Facts does not tag a standalone Q4 for these retailers.",
            "Operating cash flow is stored for the full year. Quarterly cash flow is stored only when the filing tags a standalone quarter, which for these companies is usually the first quarter.",
            "Gross profit uses the GrossProfit tag when the company reports it. Otherwise gross profit is revenue minus cost of revenue. For Walmart, revenue is total revenue, so membership and other income remains inside gross profit. For Costco, membership fees also remain inside gross profit because they are part of total revenue and are not in merchandise cost.",
            "Net income is NetIncomeLoss, which is net income attributable to the company.",
        ],
    }
    (data_dir / "data_sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    summary = build_summary(annual_rows, quarterly_rows, data_dir)
    summary["fetch_timestamp_utc"] = fetched_at
    (data_dir / "summary_metrics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("\nLatest completed fiscal year")
    print(
        f"{'Company':<12} {'FY':>6} {'Ended':<12} {'Revenue':>16} {'YoY':>8} "
        f"{'Gross':>8} {'Op.':>8} {'Net':>8} {'Op. bps':>10} {'CAGR':>8}"
    )
    for item in summary["snapshots"]:
        print(
            f"{item['display_name']:<12} {item['fiscal_year']:>6} {item['period_end']:<12} "
            f"{item['revenue_display']:>16} {item['yoy_revenue_growth']:>8} "
            f"{item['gross_margin']:>8} {item['operating_margin']:>8} {item['net_margin']:>8} "
            f"{item['operating_margin_change_bps']:>10} {item['revenue_cagr']:>8}"
        )
    print(
        f"\nCombined revenue {summary['combined']['revenue_display']}, "
        f"operating income {summary['combined']['operating_income_display']}, "
        f"net income {summary['combined']['net_income_display']}, "
        f"operating margin {summary['combined']['operating_margin']}"
    )
    print(f"Wrote data files at {fetched_at}")


if __name__ == "__main__":
    main()
