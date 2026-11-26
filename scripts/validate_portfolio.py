"""Check that the portfolio workbook, data, pictures, and write-up agree.

The check is offline. Pass --live to download the SEC files again and confirm
the saved annual amounts still match the feed.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.metrics import allowed_figure_strings, company_snapshot, sha256_bytes

BANNED = (
    "synthetic",
    "placeholder",
    "lorem ipsum",
    "dummy data",
    "fake data",
    "sample data",
    "todo",
    "tbd",
    "changeme",
    "notional",
    "hypothetical",
)
MONEY_RE = re.compile(r"\$\d[\d,]*(?:\.\d+)? (?:billion|trillion)")
PERCENT_RE = re.compile(r"(?<![\w.])[+-]?\d+\.\d%")
LOOSE_PERCENT_RE = re.compile(r"(?<![\w.])[+-]?\d+%")
BPS_RE = re.compile(r"(?<![\w.])[+-]?\d+ bps")
TEXT_SUFFIXES = {".md", ".json", ".csv", ".py", ".twb", ".yml", ".txt"}
PREVIEW_IMAGES = [
    "assets/01_executive_overview.png",
    "assets/02_revenue_and_growth.png",
    "assets/03_profitability_margins.png",
    "assets/04_peer_comparison.png",
]


class ValidationError(Exception):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"{path} is not a PNG.")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def check_banned(path: Path) -> None:
    if path.suffix not in TEXT_SUFFIXES:
        return
    text = path.read_text(encoding="utf-8").lower()
    for word in BANNED:
        if word in text:
            fail(f"{path.relative_to(ROOT)} contains banned wording: {word}")


def check_annual_identity(rows: list[dict]) -> None:
    by_ticker: dict[str, list[dict]] = {}
    for row in rows:
        for field in (
            "revenue_usd",
            "cost_of_revenue_usd",
            "gross_profit_usd",
            "operating_income_usd",
            "net_income_usd",
            "operating_cash_flow_usd",
            "fiscal_year",
        ):
            if row[field] == "":
                fail(f"{row['ticker']} FY{row.get('fiscal_year')} is missing {field}.")
        if int(row["gross_profit_usd"]) != int(row["revenue_usd"]) - int(row["cost_of_revenue_usd"]):
            fail(f"{row['ticker']} FY{row['fiscal_year']} gross profit does not equal revenue minus cost.")
        if row["gross_profit_method"] not in {"reported", "calculated"}:
            fail(f"Unexpected gross profit method {row['gross_profit_method']}.")
        if int(row["revenue_usd"]) <= 0:
            fail(f"{row['ticker']} FY{row['fiscal_year']} revenue is not positive.")
        by_ticker.setdefault(row["ticker"], []).append(row)
    if len(by_ticker) < 5:
        fail("Expected at least five companies.")
    for ticker, company_rows in by_ticker.items():
        if len(company_rows) < 5:
            fail(f"{ticker} has fewer than five fiscal years.")


def check_quarters(annual_rows: list[dict], quarterly_rows: list[dict]) -> None:
    for row in quarterly_rows:
        if row["value_basis"] not in {"reported", "derived_q4"}:
            fail(f"Unexpected quarterly basis {row['value_basis']}.")
        if row["fiscal_quarter"] not in {"Q1", "Q2", "Q3", "Q4"}:
            fail(f"Unexpected quarter {row['fiscal_quarter']}.")
    for annual in annual_rows:
        parts = [
            row
            for row in quarterly_rows
            if row["ticker"] == annual["ticker"] and row["fiscal_year"] == annual["fiscal_year"]
        ]
        if len(parts) != 4:
            fail(f"{annual['ticker']} FY{annual['fiscal_year']} does not have four quarters.")
        derived = [row for row in parts if row["value_basis"] == "derived_q4"]
        if len(derived) != 1 or derived[0]["fiscal_quarter"] != "Q4":
            fail(f"{annual['ticker']} FY{annual['fiscal_year']} should have one derived fourth quarter.")
        for field in (
            "revenue_usd",
            "cost_of_revenue_usd",
            "gross_profit_usd",
            "operating_income_usd",
            "net_income_usd",
        ):
            total = sum(int(row[field]) for row in parts)
            if total != int(annual[field]):
                fail(f"{annual['ticker']} FY{annual['fiscal_year']} {field} does not tie to the quarters.")


def check_summary(annual_rows: list[dict], quarterly_rows: list[dict], summary: dict, data_dir: Path) -> list[dict]:
    order = []
    for row in annual_rows:
        if row["ticker"] not in order:
            order.append(row["ticker"])
    snapshots = [company_snapshot(annual_rows, quarterly_rows, ticker) for ticker in order]
    saved = summary["snapshots"]
    if len(saved) != len(snapshots):
        fail("summary_metrics.json company count does not match the CSV files.")
    for expected, found in zip(snapshots, saved):
        for key in (
            "ticker",
            "fiscal_year",
            "revenue_usd",
            "net_income_usd",
            "operating_cash_flow_usd",
            "revenue_display",
            "yoy_revenue_growth",
            "gross_margin",
            "operating_margin",
            "net_margin",
            "operating_margin_change_bps",
            "revenue_cagr",
            "ttm_revenue_usd",
            "ttm_revenue_display",
        ):
            if expected[key] != found[key]:
                fail(f"{expected['ticker']} {key} is {found[key]} in summary and {expected[key]} from the CSV.")
    for name, meta in summary["inputs"].items():
        payload = (data_dir / name).read_bytes()
        digest = sha256_bytes(payload)
        if digest != meta["sha256"]:
            fail(f"{name} has changed since summary_metrics.json was written.")
    return snapshots


def check_readme(readme: str, summary: dict, annual_rows: list[dict], snapshots: list[dict], sources: dict) -> None:
    for image in PREVIEW_IMAGES:
        if f"]({image})" not in readme and f"]({image} " not in readme:
            # Standard markdown image or link.
            if image not in readme:
                fail(f"README does not link {image}.")
        path = ROOT / image
        if not path.exists():
            fail(f"Missing preview {image}.")
        width, height = png_size(path)
        if width < 2000 or height < 1100:
            fail(f"{image} is {width}x{height}. Previews should be at least 2000 by 1100.")
    hashes = {(ROOT / image).read_bytes() for image in PREVIEW_IMAGES}
    if len(hashes) != len(PREVIEW_IMAGES):
        fail("Preview images are not unique.")
    for required in summary["required_readme_strings"]:
        if required not in readme:
            fail(f"README is missing the figure {required}.")
    allowed = set(allowed_figure_strings(annual_rows, snapshots))
    for pattern, label in ((MONEY_RE, "money"), (PERCENT_RE, "percent"), (BPS_RE, "basis points")):
        for match in pattern.findall(readme):
            if match not in allowed:
                fail(f"README {label} figure {match} is not in the CSV figures.")
    for match in LOOSE_PERCENT_RE.findall(readme):
        if not match.endswith(".%") and "." not in match.strip("%").lstrip("+-")[1:]:
            # One-decimal percents are already checked. Reject whole-number percents.
            if not re.fullmatch(r"[+-]?\d+\.\d+%", match):
                fail(f"README percent {match} should use one decimal place.")
    fetch_day = sources["fetch_timestamp_utc"][:10]
    if fetch_day not in readme:
        fail(f"README does not mention the download date {fetch_day}.")
    for company in sources["companies"]:
        if company["companyfacts_url"] not in readme:
            fail(f"README does not link {company['companyfacts_url']}.")


def check_sources(sources: dict, dim_rows: list[dict]) -> None:
    if sources["api"] != "SEC EDGAR Company Facts API":
        fail("data_sources.json is not using the SEC Company Facts API.")
    if not sources["fetch_timestamp_utc"].endswith("Z"):
        fail("Fetch timestamp is missing.")
    dim_by_ticker = {row["ticker"]: row for row in dim_rows}
    if len(sources["companies"]) != len(dim_rows):
        fail("Company count differs between data_sources.json and dim_company.csv.")
    for company in sources["companies"]:
        url = company["companyfacts_url"]
        expected = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company['cik']}.json"
        if url != expected:
            fail(f"Unexpected company facts URL {url}.")
        if company["cik"] != dim_by_ticker[company["ticker"]]["cik"]:
            fail(f"CIK mismatch for {company['ticker']}.")
        if not company["annual_fiscal_years"] or len(company["annual_fiscal_years"]) < 5:
            fail(f"{company['ticker']} does not record five fiscal years.")


def check_workbook() -> None:
    twb_path = ROOT / "tableau" / "CorporateFinancialsDashboard.twb"
    xml_text = twb_path.read_text(encoding="utf-8")
    root = ElementTree.fromstring(xml_text)
    if root.tag != "workbook":
        fail("Workbook root is not workbook.")
    dashboards = {node.attrib["name"] for node in root.findall("./dashboards/dashboard")}
    for name in ("Executive Overview", "Revenue & Growth", "Profitability & Margins", "Peer Comparison"):
        if name not in dashboards:
            fail(f"Workbook is missing the {name} dashboard.")
    for filename in (
        "company_financials_annual.csv",
        "company_financials_quarterly.csv",
        "dim_company.csv",
    ):
        if filename not in xml_text:
            fail(f"Workbook does not connect to {filename}.")
    if "directory='../data'" not in xml_text:
        fail("Standalone workbook should point at ../data.")
    guide = (ROOT / "tableau" / "calculated_fields.md").read_text(encoding="utf-8")
    formulas = re.findall(r"```tableau\n(.*?)```", guide, flags=re.S)
    if len(formulas) < 6:
        fail("calculated_fields.md does not list the Tableau formulas.")
    for formula in formulas:
        if formula.strip() not in xml_text:
            fail(f"Workbook is missing formula: {formula.strip()}")
    for required in (
        "YoY Revenue Growth %",
        "Gross Margin %",
        "Operating Margin %",
        "Net Margin %",
        "TTM Revenue",
        "Margin Change bps",
    ):
        if required not in xml_text or required not in guide:
            fail(f"Missing calculated field {required}.")
    twbx_path = ROOT / "tableau" / "CorporateFinancialsDashboard.twbx"
    if not zipfile.is_zipfile(twbx_path):
        fail("Packaged workbook is not a zip archive.")
    with zipfile.ZipFile(twbx_path) as archive:
        names = set(archive.namelist())
        for name in (
            "CorporateFinancialsDashboard.twb",
            "Data/company_financials_annual.csv",
            "Data/company_financials_quarterly.csv",
            "Data/dim_company.csv",
        ):
            if name not in names:
                fail(f"Packaged workbook is missing {name}.")
        packaged = archive.read("CorporateFinancialsDashboard.twb")
        packaged_root = ElementTree.fromstring(packaged)
        if packaged_root.tag != "workbook":
            fail("Packaged workbook XML is not a workbook.")
        if b"directory='Data'" not in packaged:
            fail("Packaged workbook should read CSVs from the Data folder.")


def check_live() -> None:
    from scripts.fetch_data import COMPANIES, load_company

    annual = read_csv(ROOT / "data" / "company_financials_annual.csv")
    saved = {
        (row["ticker"], row["fiscal_year"], row["period_end"]): row
        for row in annual
    }
    for company in COMPANIES:
        print(f"Live check {company['ticker']}...")
        _profile, _payload, fresh, _quarterly = load_company(company)
        for row in fresh:
            key = (row["ticker"], str(row["fiscal_year"]), row["period_end"])
            current = saved.get(key)
            if current is None:
                fail(f"Live SEC data has {key} and the CSV does not.")
            for field in (
                "revenue_usd",
                "cost_of_revenue_usd",
                "gross_profit_usd",
                "operating_income_usd",
                "net_income_usd",
                "operating_cash_flow_usd",
            ):
                if int(current[field]) != int(row[field]):
                    fail(f"{key} {field} CSV {current[field]} does not match live SEC {row[field]}.")


def main() -> None:
    data_dir = ROOT / "data"
    annual_rows = read_csv(data_dir / "company_financials_annual.csv")
    quarterly_rows = read_csv(data_dir / "company_financials_quarterly.csv")
    dim_rows = read_csv(data_dir / "dim_company.csv")
    summary = json.loads((data_dir / "summary_metrics.json").read_text(encoding="utf-8"))
    sources = json.loads((data_dir / "data_sources.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    check_annual_identity(annual_rows)
    check_quarters(annual_rows, quarterly_rows)
    snapshots = check_summary(annual_rows, quarterly_rows, summary, data_dir)
    check_sources(sources, dim_rows)
    check_readme(readme, summary, annual_rows, snapshots, sources)
    check_workbook()
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "assets" in path.parts:
            continue
        if path.name == "validate_portfolio.py":
            continue
        check_banned(path)
    if "--live" in sys.argv:
        check_live()
    print("Portfolio validation passed.")
    print(f"Companies: {len({row['ticker'] for row in annual_rows})}")
    print(f"Annual rows: {len(annual_rows)}")
    print(f"Quarterly rows: {len(quarterly_rows)}")
    print(f"README figures checked: {len(summary['required_readme_strings'])}")


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        print(f"Validation failed: {exc}")
        sys.exit(1)
