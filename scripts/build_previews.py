"""Draw Tableau-style dashboard previews from the SEC CSV files.

These pictures are not screenshots from Tableau. They use the same annual
figures as the workbook so a reader can see the story on GitHub.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.metrics import money, percent, ratio, signed_percent

for weight in ("Regular", "Medium", "SemiBold", "Bold"):
    font_manager.fontManager.addfont(f"/usr/share/fonts/truetype/macos/Inter-{weight}.ttf")

plt.rcParams["font.family"] = "Inter"
plt.rcParams["axes.unicode_minus"] = False

COLORS = {
    "Walmart": "#2F6FED",
    "Costco": "#E03C31",
    "Dollar General": "#C48A12",
    "Home Depot": "#F97316",
    "Lowe's": "#1F9D55",
    "Best Buy": "#7A5AF8",
}
INK = "#102033"
MUTED = "#5C6B7A"
LINE = "#E4E8EF"
BG = "#F4F7FB"
NAVY = "#0E2744"


def load_annual() -> list[dict]:
    path = ROOT / "data" / "company_financials_annual.csv"
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            for field in (
                "fiscal_year",
                "year_ended",
                "revenue_usd",
                "gross_profit_usd",
                "operating_income_usd",
                "net_income_usd",
                "operating_cash_flow_usd",
            ):
                row[field] = int(row[field])
            rows.append(row)
    return rows


def by_company(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["display_name"], []).append(row)
    for name in grouped:
        grouped[name].sort(key=lambda row: row["year_ended"])
    return grouped


def latest_map(grouped: dict[str, list[dict]]) -> list[dict]:
    latest = [rows[-1] for rows in grouped.values()]
    latest.sort(key=lambda row: row["revenue_usd"], reverse=True)
    return latest


def yoy(current: dict, previous: dict) -> float:
    return (current["revenue_usd"] - previous["revenue_usd"]) / previous["revenue_usd"]


def new_figure():
    fig = plt.figure(figsize=(15.2, 8.7), dpi=170, facecolor=BG)
    header = fig.add_axes([0, 0.905, 1, 0.095])
    header.set_xlim(0, 1)
    header.set_ylim(0, 1)
    header.axis("off")
    header.add_patch(plt.Rectangle((0, 0), 1, 1, color=NAVY))
    return fig, header


def paint_header(header, title: str, subtitle: str) -> None:
    header.text(0.028, 0.64, title, color="white", fontsize=18, fontweight="semibold", ha="left", va="center")
    header.text(0.028, 0.26, subtitle, color="#C9D6E5", fontsize=10, ha="left", va="center")
    header.text(0.972, 0.64, "SEC EDGAR", color="white", fontsize=10, ha="right", va="center", fontweight="medium")
    header.text(0.972, 0.26, "U.S. retail leaders", color="#C9D6E5", fontsize=9, ha="right", va="center")


def paint_footer(fig, note: str) -> None:
    fig.text(0.028, 0.018, note, color=MUTED, fontsize=8, ha="left", va="center")
    fig.text(0.972, 0.018, "Dashboard preview  ·  same CSV files as the Tableau workbook", color=MUTED, fontsize=8, ha="right", va="center")


def chip(fig, x: float, y: float, label: str) -> None:
    fig.text(
        x,
        y,
        label,
        color=INK,
        fontsize=8.5,
        ha="left",
        va="center",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": LINE, "linewidth": 0.8},
    )


def year_ticks(ax, years: list[int]) -> None:
    ax.set_xticks(years)
    ax.set_xticklabels([str(year) for year in years])


def style_axis(ax, title: str) -> None:
    ax.set_facecolor("white")
    ax.set_title(title, loc="left", color=INK, fontsize=12, fontweight="semibold", pad=10)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(LINE)
    ax.spines["bottom"].set_color(LINE)
    ax.grid(axis="x", color="#EEF2F6", zorder=0)
    ax.set_axisbelow(True)


def card(ax, eyebrow: str, value: str, note: str) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        FancyBboxPatch(
            (0.03, 0.08),
            0.94,
            0.84,
            boxstyle="round,pad=0.012,rounding_size=0.04",
            facecolor="white",
            edgecolor=LINE,
            linewidth=1,
        )
    )
    ax.text(0.09, 0.72, eyebrow.upper(), color=MUTED, fontsize=8, fontweight="medium", ha="left")
    ax.text(0.09, 0.42, value, color=INK, fontsize=16, fontweight="semibold", ha="left")
    ax.text(0.09, 0.18, note, color=MUTED, fontsize=8, ha="left")


def executive(grouped: dict[str, list[dict]]) -> None:
    latest = latest_map(grouped)
    combined_revenue = sum(row["revenue_usd"] for row in latest)
    combined_profit = sum(row["net_income_usd"] for row in latest)
    combined_operating = sum(row["operating_income_usd"] for row in latest)
    combined_cash = sum(row["operating_cash_flow_usd"] for row in latest)
    fig, header = new_figure()
    paint_header(header, "Executive overview", "Latest completed fiscal year for each company")
    chip(fig, 0.028, 0.868, "Company: All")
    chip(fig, 0.145, 0.868, "Year: Latest completed")
    grid = fig.add_gridspec(1, 4, left=0.04, right=0.97, top=0.83, bottom=0.67, wspace=0.18)
    cards = [
        ("Combined revenue", money(combined_revenue), "Six latest fiscal years"),
        ("Net income", money(combined_profit), "After interest and tax"),
        ("Operating margin", percent(ratio(combined_operating, combined_revenue)), "Operating income / revenue"),
        ("Operating cash flow", money(combined_cash), "Cash from the business"),
    ]
    for index, (eyebrow, value, note) in enumerate(cards):
        card(fig.add_subplot(grid[0, index]), eyebrow, value, note)

    ax = fig.add_axes([0.16, 0.34, 0.30, 0.28])
    names = [row["display_name"] for row in latest][::-1]
    values = [row["revenue_usd"] / 1_000_000_000 for row in latest][::-1]
    colors = [COLORS[name] for name in names]
    ax.barh(names, values, color=colors, height=0.62, zorder=2)
    for name, value, row in zip(names, values, latest[::-1]):
        ax.text(value + 8, name, money(row["revenue_usd"]), va="center", ha="left", color=INK, fontsize=8)
    style_axis(ax, "Revenue")
    ax.set_xlim(0, max(values) * 1.28)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color="#EEF2F6")
    ax.tick_params(axis="y", colors=INK)

    ax2 = fig.add_axes([0.62, 0.34, 0.32, 0.28])
    growth_rows = []
    for row in latest:
        history = grouped[row["display_name"]]
        growth_rows.append((row["display_name"], yoy(history[-1], history[-2])))
    growth_rows = list(reversed(growth_rows))
    bar_colors = ["#1F9D55" if value >= 0 else "#C0392B" for _, value in growth_rows]
    ax2.barh([name for name, _ in growth_rows], [value * 100 for _, value in growth_rows], color=bar_colors, height=0.62, zorder=2)
    for name, value in growth_rows:
        history = grouped[name]
        label = signed_percent(
            ratio(history[-1]["revenue_usd"] - history[-2]["revenue_usd"], history[-2]["revenue_usd"])
        )
        offset = 0.15 if value >= 0 else -0.15
        ax2.text(value * 100 + offset, name, label, va="center", ha="left" if value >= 0 else "right", color=INK, fontsize=8)
    style_axis(ax2, "Revenue growth vs. the prior year")
    ax2.axvline(0, color="#D5DCE6", linewidth=0.8)
    ax2.set_xlim(-1, 13)
    ax2.grid(axis="y", visible=False)
    ax2.tick_params(axis="y", colors=INK)

    note_ax = fig.add_axes([0.04, 0.055, 0.92, 0.24])
    note_ax.axis("off")
    note_ax.add_patch(
        FancyBboxPatch(
            (0, 0.08),
            1,
            0.84,
            boxstyle="round,pad=0.012,rounding_size=0.02",
            facecolor="white",
            edgecolor=LINE,
            linewidth=1,
            transform=note_ax.transAxes,
        )
    )
    fastest = max(latest, key=lambda row: yoy(grouped[row["display_name"]][-1], grouped[row["display_name"]][-2]))
    widest = max(latest, key=lambda row: row["operating_income_usd"] / row["revenue_usd"])
    note_ax.text(0.03, 0.68, "What stands out", color=INK, fontsize=12, fontweight="semibold")
    note_ax.text(
        0.03,
        0.38,
        f"{fastest['display_name']} grew the fastest. {widest['display_name']} kept the widest operating margin.\n"
        "Fiscal years do not share a calendar. The date each year ended is the fair way to line them up.\n"
        "Home Depot and Lowe's turn a much larger share of each sales dollar into operating profit than the general-merchandise chains.",
        color=MUTED,
        fontsize=10,
        va="center",
        linespacing=1.45,
    )
    paint_footer(fig, "Source: SEC EDGAR Company Facts  ·  U.S. dollars as reported  ·  Not inflation adjusted")
    fig.savefig(ROOT / "assets" / "01_executive_overview.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def revenue_and_growth(grouped: dict[str, list[dict]]) -> None:
    fig, header = new_figure()
    paint_header(header, "Revenue and growth", "Indexed sales, plus the latest year in dollars")
    chip(fig, 0.028, 0.868, "Company: All")
    chip(fig, 0.145, 0.868, "Years ended: 2021–2026")
    left = fig.add_axes([0.06, 0.12, 0.52, 0.68])
    for name, rows in grouped.items():
        base = rows[0]["revenue_usd"]
        years = [row["year_ended"] for row in rows]
        index = [row["revenue_usd"] / base * 100 for row in rows]
        left.plot(years, index, color=COLORS[name], linewidth=2.2, marker="o", markersize=4.5, label=name)
    style_axis(left, "Revenue index  ·  year ended 2021 = 100")
    left.set_xlim(2020.8, 2026.3)
    year_ticks(left, [2021, 2022, 2023, 2024, 2025, 2026])
    left.legend(frameon=False, fontsize=8, loc="upper left", ncol=2)
    left.grid(axis="y", color="#EEF2F6")
    left.grid(axis="x", visible=False)
    left.axhline(100, color="#D5DCE6", linewidth=0.8)

    latest = latest_map(grouped)
    right = fig.add_axes([0.70, 0.12, 0.26, 0.68])
    names = [row["display_name"] for row in latest][::-1]
    values = [row["revenue_usd"] / 1_000_000_000 for row in latest][::-1]
    right.barh(names, values, color=[COLORS[name] for name in names], height=0.62)
    for name, row in zip(names, latest[::-1]):
        history = grouped[name]
        growth = signed_percent(ratio(history[-1]["revenue_usd"] - history[-2]["revenue_usd"], history[-2]["revenue_usd"]))
        right.text(row["revenue_usd"] / 1_000_000_000 + 8, name, growth, va="center", fontsize=8, color=INK)
    style_axis(right, "Latest revenue, label = yearly growth")
    right.set_xlabel("USD billions", color=MUTED, fontsize=8)
    right.set_xlim(0, max(values) * 1.32)
    right.grid(axis="y", visible=False)
    right.tick_params(axis="y", colors=INK)
    paint_footer(fig, "Source: SEC EDGAR Company Facts  ·  Index removes the Walmart scale so growth is easy to compare")
    fig.savefig(ROOT / "assets" / "02_revenue_and_growth.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def profitability(grouped: dict[str, list[dict]]) -> None:
    fig, header = new_figure()
    paint_header(header, "Profitability and margins", "Gross, operating, and net margin, and the change in operating margin")
    chip(fig, 0.028, 0.868, "Company: All")
    chip(fig, 0.145, 0.868, "Years ended: 2021–2026")
    specs = [
        (0.05, "Gross margin", "gross_profit_usd"),
        (0.37, "Operating margin", "operating_income_usd"),
        (0.69, "Net margin", "net_income_usd"),
    ]
    for left, title, field in specs:
        ax = fig.add_axes([left, 0.46, 0.27, 0.34])
        for name, rows in grouped.items():
            years = [row["year_ended"] for row in rows]
            values = [row[field] / row["revenue_usd"] * 100 for row in rows]
            ax.plot(years, values, color=COLORS[name], linewidth=2, marker="o", markersize=3.5)
        style_axis(ax, title)
        year_ticks(ax, [2021, 2023, 2025])
        ax.grid(axis="y", color="#EEF2F6")
        ax.grid(axis="x", visible=False)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _pos: f"{value:.0f}%"))

    ax = fig.add_axes([0.16, 0.10, 0.50, 0.28])
    names = []
    changes = []
    for name, rows in grouped.items():
        current = rows[-1]["operating_income_usd"] / rows[-1]["revenue_usd"]
        previous = rows[-2]["operating_income_usd"] / rows[-2]["revenue_usd"]
        names.append(name)
        changes.append((current - previous) * 10000)
    order = sorted(range(len(names)), key=lambda index: changes[index])
    names = [names[index] for index in order]
    changes = [changes[index] for index in order]
    colors = ["#1F9D55" if value >= 0 else "#C0392B" for value in changes]
    ax.barh(names, changes, color=colors, height=0.62)
    for name, value in zip(names, changes):
        label = format_bps(grouped[name])
        ax.text(value + (4 if value >= 0 else -4), name, label, va="center", ha="left" if value >= 0 else "right", fontsize=8, color=INK)
    style_axis(ax, "Operating margin change vs. the prior year, in basis points")
    ax.axvline(0, color="#D5DCE6", linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", colors=INK)
    span = max(abs(min(changes)), abs(max(changes)))
    ax.set_xlim(-span * 1.45, span * 1.45)

    legend = fig.add_axes([0.72, 0.12, 0.24, 0.26])
    legend.axis("off")
    legend.add_patch(
        FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.02,rounding_size=0.04", facecolor="white", edgecolor=LINE, linewidth=1)
    )
    legend.text(0.08, 0.86, "Companies", color=INK, fontsize=11, fontweight="semibold")
    for index, name in enumerate(COLORS):
        y = 0.70 - index * 0.12
        legend.add_patch(plt.Rectangle((0.08, y - 0.02), 0.06, 0.06, color=COLORS[name], transform=legend.transAxes))
        legend.text(0.20, y, name, color=INK, fontsize=9, va="center")
    paint_footer(fig, "Source: SEC EDGAR Company Facts  ·  100 basis points = 1 percentage point  ·  Margins use total revenue")
    fig.savefig(ROOT / "assets" / "03_profitability_margins.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def format_bps(history: list[dict]) -> str:
    from decimal import Decimal

    from scripts.metrics import signed_bps

    current = Decimal(history[-1]["operating_income_usd"]) / Decimal(history[-1]["revenue_usd"])
    previous = Decimal(history[-2]["operating_income_usd"]) / Decimal(history[-2]["revenue_usd"])
    return signed_bps(current - previous)


def peer_comparison(grouped: dict[str, list[dict]]) -> None:
    latest = latest_map(grouped)
    fig, header = new_figure()
    paint_header(header, "Peer comparison", "Latest completed fiscal year, ranked by revenue")
    chip(fig, 0.028, 0.868, "Company: All")
    chip(fig, 0.145, 0.868, "View: Latest year")

    ax = fig.add_axes([0.15, 0.48, 0.32, 0.32])
    names = [row["display_name"] for row in latest][::-1]
    margins = [row["operating_income_usd"] / row["revenue_usd"] * 100 for row in latest][::-1]
    ax.barh(names, margins, color=[COLORS[name] for name in names], height=0.62)
    for name, row in zip(names, latest[::-1]):
        ax.text(
            row["operating_income_usd"] / row["revenue_usd"] * 100 + 0.2,
            name,
            percent(ratio(row["operating_income_usd"], row["revenue_usd"])),
            va="center",
            fontsize=8,
            color=INK,
        )
    style_axis(ax, "Operating margin")
    ax.set_xlim(0, 16)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", colors=INK)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda value, _pos: f"{value:.0f}%"))

    ax2 = fig.add_axes([0.56, 0.46, 0.40, 0.34])
    import numpy as np

    labels = ["Gross", "Operating", "Net"]
    x = np.arange(len(latest))
    width = 0.24
    series = [
        [row["gross_profit_usd"] / row["revenue_usd"] * 100 for row in latest],
        [row["operating_income_usd"] / row["revenue_usd"] * 100 for row in latest],
        [row["net_income_usd"] / row["revenue_usd"] * 100 for row in latest],
    ]
    palette = ["#8FB8F6", "#2F6FED", "#0E2744"]
    for offset, values, color, label in zip((-width, 0, width), series, palette, labels):
        ax2.bar(x + offset, values, width=width, color=color, label=label)
    style_axis(ax2, "Gross, operating, and net margin")
    ax2.set_xticks(x)
    ax2.set_xticklabels([row["display_name"].replace(" ", "\n") for row in latest], fontsize=7.5, color=INK)
    ax2.grid(axis="y", color="#EEF2F6")
    ax2.grid(axis="x", visible=False)
    ax2.legend(frameon=False, fontsize=8, loc="upper right")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _pos: f"{value:.0f}%"))
    ax2.tick_params(axis="x", length=0)

    table_ax = fig.add_axes([0.04, 0.08, 0.92, 0.32])
    table_ax.axis("off")
    columns = ["Company", "Year ended", "Revenue", "YoY", "Gross margin", "Operating margin", "Net margin", "Cash flow"]
    cells = []
    for row in latest:
        history = grouped[row["display_name"]]
        cells.append(
            [
                row["display_name"],
                row["period_end"],
                money(row["revenue_usd"]),
                signed_percent(ratio(history[-1]["revenue_usd"] - history[-2]["revenue_usd"], history[-2]["revenue_usd"])),
                percent(ratio(row["gross_profit_usd"], row["revenue_usd"])),
                percent(ratio(row["operating_income_usd"], row["revenue_usd"])),
                percent(ratio(row["net_income_usd"], row["revenue_usd"])),
                money(row["operating_cash_flow_usd"]),
            ]
        )
    table = table_ax.table(cellText=cells, colLabels=columns, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.35)
    for (row_index, col_index), cell in table.get_celld().items():
        cell.set_edgecolor(LINE)
        cell.set_linewidth(0.6)
        if row_index == 0:
            cell.set_facecolor(NAVY)
            cell.set_text_props(color="white", fontweight="medium")
        else:
            cell.set_facecolor("white" if row_index % 2 else "#F7F9FC")
            cell.set_text_props(color=INK)
    paint_footer(fig, "Source: SEC EDGAR Company Facts  ·  Cash flow is cash from operations for the full fiscal year")
    fig.savefig(ROOT / "assets" / "04_peer_comparison.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    rows = load_annual()
    grouped = by_company(rows)
    assets = ROOT / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    executive(grouped)
    revenue_and_growth(grouped)
    profitability(grouped)
    peer_comparison(grouped)
    for path in sorted(assets.glob("*.png")):
        print(f"Wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
