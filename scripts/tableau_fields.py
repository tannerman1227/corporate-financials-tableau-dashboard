"""Tableau calculated fields shared by the workbook and the field guide.

Annual growth looks back one year. Quarterly growth looks back four quarters,
which is the same season a year earlier.
"""

from __future__ import annotations

ANNUAL_FORMULAS = [
    {
        "name": "YoY Revenue Growth %",
        "formula": "(ZN(SUM([revenue_usd])) - LOOKUP(ZN(SUM([revenue_usd])), -1)) / ABS(LOOKUP(ZN(SUM([revenue_usd])), -1))",
        "number_format": "0.0%",
        "plain": "This year's revenue minus last year's revenue, divided by last year's revenue.",
        "compute_using": "Compute using Year Ended. Restart every company.",
    },
    {
        "name": "Gross Margin %",
        "formula": "SUM([gross_profit_usd]) / SUM([revenue_usd])",
        "number_format": "0.0%",
        "plain": "Gross profit divided by revenue.",
        "compute_using": "This is a normal sum. It does not need a table calculation.",
    },
    {
        "name": "Operating Margin %",
        "formula": "SUM([operating_income_usd]) / SUM([revenue_usd])",
        "number_format": "0.0%",
        "plain": "Operating income divided by revenue.",
        "compute_using": "This is a normal sum. It does not need a table calculation.",
    },
    {
        "name": "Net Margin %",
        "formula": "SUM([net_income_usd]) / SUM([revenue_usd])",
        "number_format": "0.0%",
        "plain": "Net income divided by revenue.",
        "compute_using": "This is a normal sum. It does not need a table calculation.",
    },
    {
        "name": "Margin Change bps",
        "formula": "(ZN([Operating Margin %]) - LOOKUP(ZN([Operating Margin %]), -1)) * 10000",
        "number_format": "+#,##0;-#,##0",
        "plain": "How much the operating margin changed from last year, in basis points. 100 basis points equal 1 percentage point.",
        "compute_using": "Compute using Year Ended. Restart every company.",
    },
    {
        "name": "Latest Year Flag",
        "formula": "[year_ended] = { FIXED [ticker] : MAX([year_ended]) }",
        "number_format": "",
        "datatype": "boolean",
        "role": "dimension",
        "type": "nominal",
        "plain": "True for each company's newest year in the data. Use it as a filter when a sheet should open on the latest year.",
        "compute_using": "This is a fixed level-of-detail calculation, so company filters do not change which year is latest.",
    },
]

QUARTERLY_FORMULAS = [
    {
        "name": "YoY Revenue Growth %",
        "formula": "(ZN(SUM([revenue_usd])) - LOOKUP(ZN(SUM([revenue_usd])), -4)) / ABS(LOOKUP(ZN(SUM([revenue_usd])), -4))",
        "number_format": "0.0%",
        "plain": "This quarter's revenue minus the same quarter last year, divided by that older quarter.",
        "compute_using": "Compute using Period End. Restart every company. The lookback is four quarters.",
    },
    {
        "name": "Gross Margin %",
        "formula": "SUM([gross_profit_usd]) / SUM([revenue_usd])",
        "number_format": "0.0%",
        "plain": "Gross profit divided by revenue.",
        "compute_using": "This is a normal sum. It does not need a table calculation.",
    },
    {
        "name": "Operating Margin %",
        "formula": "SUM([operating_income_usd]) / SUM([revenue_usd])",
        "number_format": "0.0%",
        "plain": "Operating income divided by revenue.",
        "compute_using": "This is a normal sum. It does not need a table calculation.",
    },
    {
        "name": "Net Margin %",
        "formula": "SUM([net_income_usd]) / SUM([revenue_usd])",
        "number_format": "0.0%",
        "plain": "Net income divided by revenue.",
        "compute_using": "This is a normal sum. It does not need a table calculation.",
    },
    {
        "name": "Margin Change bps",
        "formula": "(ZN([Operating Margin %]) - LOOKUP(ZN([Operating Margin %]), -4)) * 10000",
        "number_format": "+#,##0;-#,##0",
        "plain": "How much this quarter's operating margin changed from the same quarter last year, in basis points.",
        "compute_using": "Compute using Period End. Restart every company.",
    },
    {
        "name": "TTM Revenue",
        "formula": "WINDOW_SUM(SUM([revenue_usd]), -3, 0)",
        "number_format": "$#,##0,,.0",
        "plain": "Revenue for this quarter plus the three quarters before it. At a year end, this matches the full-year revenue.",
        "compute_using": "Compute using Period End. Restart every company.",
    },
]


def markdown_guide() -> str:
    lines = [
        "# Tableau calculated fields",
        "",
        "These are the calculations in `CorporateFinancialsDashboard.twb`.",
        "You can read them here without opening Tableau.",
        "",
        "The annual workbook looks back one year. The quarterly workbook looks back four quarters, because that is the same season a year earlier.",
        "",
        "A basis point is 0.01 percentage points. A move of 100 basis points is a change of 1 percentage point.",
        "",
        "## Annual data",
        "",
    ]
    lines.extend(_section(ANNUAL_FORMULAS))
    lines.extend(["## Quarterly data", ""])
    lines.extend(_section(QUARTERLY_FORMULAS))
    lines.extend(
        [
            "## Filters",
            "",
            "Company and fiscal year are the two filters on the dashboards.",
            "Peer sheets also use Latest Year Flag so they open on each company's newest completed year.",
            "",
        ]
    )
    return "\n".join(lines)


def _section(formulas: list[dict]) -> list[str]:
    lines = []
    for field in formulas:
        lines.append(f"### {field['name']}")
        lines.append("")
        lines.append(field["plain"])
        lines.append("")
        lines.append(field["compute_using"])
        lines.append("")
        lines.append("```tableau")
        lines.append(field["formula"])
        lines.append("```")
        lines.append("")
    return lines
