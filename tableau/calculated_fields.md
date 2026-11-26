# Tableau calculated fields

These are the calculations in `CorporateFinancialsDashboard.twb`.
You can read them here without opening Tableau.

The annual workbook looks back one year. The quarterly workbook looks back four quarters, because that is the same season a year earlier.

A basis point is 0.01 percentage points. A move of 100 basis points is a change of 1 percentage point.

## Annual data

### YoY Revenue Growth %

This year's revenue minus last year's revenue, divided by last year's revenue.

Compute using Year Ended. Restart every company.

```tableau
(ZN(SUM([revenue_usd])) - LOOKUP(ZN(SUM([revenue_usd])), -1)) / ABS(LOOKUP(ZN(SUM([revenue_usd])), -1))
```

### Gross Margin %

Gross profit divided by revenue.

This is a normal sum. It does not need a table calculation.

```tableau
SUM([gross_profit_usd]) / SUM([revenue_usd])
```

### Operating Margin %

Operating income divided by revenue.

This is a normal sum. It does not need a table calculation.

```tableau
SUM([operating_income_usd]) / SUM([revenue_usd])
```

### Net Margin %

Net income divided by revenue.

This is a normal sum. It does not need a table calculation.

```tableau
SUM([net_income_usd]) / SUM([revenue_usd])
```

### Margin Change bps

How much the operating margin changed from last year, in basis points. 100 basis points equal 1 percentage point.

Compute using Year Ended. Restart every company.

```tableau
(ZN([Operating Margin %]) - LOOKUP(ZN([Operating Margin %]), -1)) * 10000
```

### Latest Year Flag

True for each company's newest year in the data. Use it as a filter when a sheet should open on the latest year.

This is a fixed level-of-detail calculation, so company filters do not change which year is latest.

```tableau
[year_ended] = { FIXED [ticker] : MAX([year_ended]) }
```

## Quarterly data

### YoY Revenue Growth %

This quarter's revenue minus the same quarter last year, divided by that older quarter.

Compute using Period End. Restart every company. The lookback is four quarters.

```tableau
(ZN(SUM([revenue_usd])) - LOOKUP(ZN(SUM([revenue_usd])), -4)) / ABS(LOOKUP(ZN(SUM([revenue_usd])), -4))
```

### Gross Margin %

Gross profit divided by revenue.

This is a normal sum. It does not need a table calculation.

```tableau
SUM([gross_profit_usd]) / SUM([revenue_usd])
```

### Operating Margin %

Operating income divided by revenue.

This is a normal sum. It does not need a table calculation.

```tableau
SUM([operating_income_usd]) / SUM([revenue_usd])
```

### Net Margin %

Net income divided by revenue.

This is a normal sum. It does not need a table calculation.

```tableau
SUM([net_income_usd]) / SUM([revenue_usd])
```

### Margin Change bps

How much this quarter's operating margin changed from the same quarter last year, in basis points.

Compute using Period End. Restart every company.

```tableau
(ZN([Operating Margin %]) - LOOKUP(ZN([Operating Margin %]), -4)) * 10000
```

### TTM Revenue

Revenue for this quarter plus the three quarters before it. At a year end, this matches the full-year revenue.

Compute using Period End. Restart every company.

```tableau
WINDOW_SUM(SUM([revenue_usd]), -3, 0)
```

## Filters

Company and fiscal year are the two filters on the dashboards.
Peer sheets also use Latest Year Flag so they open on each company's newest completed year.
