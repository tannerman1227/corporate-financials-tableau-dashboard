"""Build the Tableau workbook, the packaged workbook, and the field guide."""

from __future__ import annotations

import csv
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tableau_fields import ANNUAL_FORMULAS, QUARTERLY_FORMULAS, markdown_guide

DATA_FILES = {
    "federated.annual": ("company_financials_annual.csv", "Annual Financials", ANNUAL_FORMULAS),
    "federated.quarterly": ("company_financials_quarterly.csv", "Quarterly Financials", QUARTERLY_FORMULAS),
    "federated.dim": ("dim_company.csv", "Company Directory", []),
}

DATE_FIELDS = {"period_start", "period_end", "filed_date"}
INTEGER_FIELDS = {"fiscal_year", "year_ended", "days_in_period", "sic"}
REMOTE_TYPE = {"string": "129", "integer": "20", "real": "5", "date": "133"}


def column_type(name: str) -> str:
    if name in DATE_FIELDS:
        return "date"
    if name in INTEGER_FIELDS:
        return "integer"
    if name.endswith("_usd"):
        return "real"
    return "string"


def read_header(filename: str) -> list[str]:
    with (ROOT / "data" / filename).open(encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


def attr(value: str) -> str:
    return escape(value, {"'": "&apos;", '"': "&quot;"})


def calc_columns(formulas: list[dict]) -> str:
    chunks = []
    for field in formulas:
        datatype = field.get("datatype", "real")
        role = field.get("role", "measure")
        kind = field.get("type", "quantitative")
        number_format = field.get("number_format") or ""
        format_attr = f" default-format='{attr(number_format)}'" if number_format else ""
        chunks.append(
            "      <column caption='{name}' datatype='{datatype}' name='[{name}]' role='{role}' type='{kind}'{fmt}>\n"
            "        <calculation class='tableau' formula='{formula}' />\n"
            "      </column>".format(
                name=attr(field["name"]),
                datatype=datatype,
                role=role,
                kind=kind,
                fmt=format_attr,
                formula=attr(field["formula"]),
            )
        )
    return "\n".join(chunks)


def metadata_records(filename: str, columns: list[str]) -> str:
    records = []
    for ordinal, name in enumerate(columns):
        kind = column_type(name)
        aggregation = "Sum" if kind in {"integer", "real"} else "Count"
        records.append(
            "          <metadata-record class='column'>\n"
            f"            <remote-name>{attr(name)}</remote-name>\n"
            f"            <remote-type>{REMOTE_TYPE[kind]}</remote-type>\n"
            f"            <local-name>[{attr(name)}]</local-name>\n"
            f"            <parent-name>[{attr(filename)}]</parent-name>\n"
            f"            <remote-alias>{attr(name)}</remote-alias>\n"
            f"            <ordinal>{ordinal}</ordinal>\n"
            f"            <local-type>{kind}</local-type>\n"
            f"            <aggregation>{aggregation}</aggregation>\n"
            "            <contains-null>true</contains-null>\n"
            f"            <object-id>[{attr(filename)}]</object-id>\n"
            "          </metadata-record>"
        )
    return "\n".join(records)


def relation_columns(columns: list[str]) -> str:
    lines = []
    for ordinal, name in enumerate(columns):
        lines.append(
            f"            <column datatype='{column_type(name)}' name='{attr(name)}' ordinal='{ordinal}' />"
        )
    return "\n".join(lines)


def field_columns(columns: list[str]) -> str:
    lines = []
    for name in columns:
        kind = column_type(name)
        if kind == "real":
            role, semantic = "measure", "quantitative"
            number_format = " default-format='$#,##0,,.0'" if name.endswith("_usd") else ""
        elif kind == "integer" and name.endswith("_usd"):
            role, semantic = "measure", "quantitative"
            number_format = " default-format='$#,##0,,.0'"
        elif kind == "integer":
            role, semantic = "dimension", "ordinal"
            number_format = ""
        elif kind == "date":
            role, semantic = "dimension", "ordinal"
            number_format = ""
        else:
            role, semantic = "dimension", "nominal"
            number_format = ""
        datatype = "real" if kind == "real" else kind
        lines.append(
            f"      <column datatype='{datatype}' name='[{attr(name)}]'{number_format} role='{role}' type='{semantic}' />"
        )
    return "\n".join(lines)


def datasource_xml(ds_name: str, filename: str, caption: str, formulas: list[dict], directory: str) -> str:
    columns = read_header(filename)
    return f"""    <datasource caption='{attr(caption)}' inline='true' name='{ds_name}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='{attr(filename)}' name='textscan.{ds_name}'>
            <connection class='textscan' directory='{attr(directory)}' filename='{attr(filename)}' password='' server='' />
          </named-connection>
        </named-connections>
        <relation connection='textscan.{ds_name}' name='{attr(filename)}' table='[{attr(filename.replace('.csv', '#csv'))}]' type='table'>
          <columns>
{relation_columns(columns)}
          </columns>
        </relation>
        <metadata-records>
{metadata_records(filename, columns)}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
{field_columns(columns)}
{calc_columns(formulas)}
      <layout dim-ordering='alphabetic' measure-ordering='alphabetic' show-structure='true' />
    </datasource>"""


def instance(field: str, derivation: str, suffix: str, semantic: str) -> str:
    prefix = {"None": "none", "Sum": "sum", "User": "usr"}[derivation]
    return (
        f"            <column-instance column='[{attr(field)}]' derivation='{derivation}' "
        f"name='[{prefix}:{attr(field)}:{suffix}]' pivot='key' type='{semantic}' />"
    )


def formulas_for(ds_name: str) -> list[dict]:
    if ds_name == "federated.quarterly":
        return QUARTERLY_FORMULAS
    return ANNUAL_FORMULAS


def dependency_columns(ds_name: str, fields: list[tuple[str, str, str, str]]) -> str:
    """fields: (name, derivation, suffix, semantic) plus the base column declaration."""
    lines = [f"          <datasource-dependencies datasource='{ds_name}'>"]
    seen = set()
    for name, derivation, suffix, semantic in fields:
        if name not in seen:
            if derivation == "User" or name == "Latest Year Flag":
                match = next(field for field in formulas_for(ds_name) if field["name"] == name)
                datatype = match.get("datatype", "real")
                role = match.get("role", "measure")
                kind = match.get("type", "quantitative")
                lines.append(
                    f"            <column caption='{attr(name)}' datatype='{datatype}' name='[{attr(name)}]' role='{role}' type='{kind}'>\n"
                    f"              <calculation class='tableau' formula='{attr(match['formula'])}' />\n"
                    "            </column>"
                )
            else:
                kind = column_type(name)
                if kind in {"real", "integer"} and (name.endswith("_usd") or derivation == "Sum"):
                    role, semantic_type, datatype = "measure", "quantitative", "real" if kind == "real" else "integer"
                elif kind == "date":
                    role, semantic_type, datatype = "dimension", "ordinal", "date"
                elif kind == "integer":
                    role, semantic_type, datatype = "dimension", "ordinal", "integer"
                else:
                    role, semantic_type, datatype = "dimension", "nominal", "string"
                lines.append(
                    f"            <column datatype='{datatype}' name='[{attr(name)}]' role='{role}' type='{semantic_type}' />"
                )
            seen.add(name)
        lines.append("    " + instance(name, derivation, suffix, semantic).strip())
    lines.append("          </datasource-dependencies>")
    return "\n".join(lines)


def worksheet(
    name: str,
    ds_name: str,
    ds_caption: str,
    rows: str,
    cols: str,
    mark: str,
    fields: list[tuple[str, str, str, str]],
    color: str | None = None,
    latest_only: bool = False,
) -> str:
    color_xml = f"              <color column='[{ds_name}].[{color}]' />\n" if color else ""
    latest_filter = ""
    if latest_only:
        latest_filter = (
            f"            <filter class='categorical' column='[{ds_name}].[none:Latest Year Flag:nk]'>\n"
            "              <groupfilter function='member' level='[none:Latest Year Flag:nk]' member='true' />\n"
            "            </filter>\n"
        )
    company_filter = ""
    slices = ""
    if any(field[0] == "display_name" for field in fields):
        company_filter = (
            f"            <filter class='categorical' column='[{ds_name}].[none:display_name:nk]'>\n"
            "              <groupfilter function='level-members' level='[none:display_name:nk]' />\n"
            "            </filter>\n"
        )
        slices = (
            "            <slices>\n"
            f"              <column>[{ds_name}].[none:display_name:nk]</column>\n"
            "            </slices>\n"
        )
    return f"""    <worksheet name='{attr(name)}'>
      <table>
        <view>
          <datasources>
            <datasource caption='{attr(ds_caption)}' name='{ds_name}' />
          </datasources>
{dependency_columns(ds_name, fields)}
{company_filter}{latest_filter}{slices}          <aggregation value='true' />
        </view>
        <style />
        <panes>
          <pane selection-relaxation-option='selection-relaxation-allow'>
            <view>
              <breakdown value='auto' />
            </view>
            <mark class='{mark}' />
            <encodings>
{color_xml}            </encodings>
          </pane>
        </panes>
        <rows>{rows}</rows>
        <cols>{cols}</cols>
      </table>
    </worksheet>"""


def worksheets() -> str:
    annual = "federated.annual"
    quarterly = "federated.quarterly"
    dim = "federated.dim"
    company = ("display_name", "None", "nk", "nominal")
    year = ("year_ended", "None", "ok", "ordinal")
    revenue = ("revenue_usd", "Sum", "qk", "quantitative")
    yoy = ("YoY Revenue Growth %", "User", "qk", "quantitative")
    gross = ("Gross Margin %", "User", "qk", "quantitative")
    operating = ("Operating Margin %", "User", "qk", "quantitative")
    net = ("Net Margin %", "User", "qk", "quantitative")
    change = ("Margin Change bps", "User", "qk", "quantitative")
    latest = ("Latest Year Flag", "None", "nk", "nominal")
    period = ("period_end", "None", "ok", "ordinal")
    ttm = ("TTM Revenue", "User", "qk", "quantitative")
    cash = ("operating_cash_flow_usd", "Sum", "qk", "quantitative")
    profit = ("net_income_usd", "Sum", "qk", "quantitative")
    sheets = [
        worksheet(
            "Revenue Trend",
            annual,
            "Annual Financials",
            f"[{annual}].[sum:revenue_usd:qk]",
            f"[{annual}].[none:year_ended:ok]",
            "Line",
            [year, revenue, company],
            color="none:display_name:nk",
        ),
        worksheet(
            "YoY Revenue Growth",
            annual,
            "Annual Financials",
            f"[{annual}].[usr:YoY Revenue Growth %:qk]",
            f"[{annual}].[none:year_ended:ok]",
            "Bar",
            [year, yoy, company],
            color="none:display_name:nk",
        ),
        worksheet(
            "Gross Margin Trend",
            annual,
            "Annual Financials",
            f"[{annual}].[usr:Gross Margin %:qk]",
            f"[{annual}].[none:year_ended:ok]",
            "Line",
            [year, gross, company],
            color="none:display_name:nk",
        ),
        worksheet(
            "Operating Margin Trend",
            annual,
            "Annual Financials",
            f"[{annual}].[usr:Operating Margin %:qk]",
            f"[{annual}].[none:year_ended:ok]",
            "Line",
            [year, operating, company],
            color="none:display_name:nk",
        ),
        worksheet(
            "Net Margin Trend",
            annual,
            "Annual Financials",
            f"[{annual}].[usr:Net Margin %:qk]",
            f"[{annual}].[none:year_ended:ok]",
            "Line",
            [year, net, company],
            color="none:display_name:nk",
        ),
        worksheet(
            "Margin Change",
            annual,
            "Annual Financials",
            f"[{annual}].[usr:Margin Change bps:qk]",
            f"[{annual}].[none:year_ended:ok]",
            "Bar",
            [year, change, company],
            color="none:display_name:nk",
        ),
        worksheet(
            "TTM Revenue",
            quarterly,
            "Quarterly Financials",
            f"[{quarterly}].[usr:TTM Revenue:qk]",
            f"[{quarterly}].[none:period_end:ok]",
            "Line",
            [period, ttm, company],
            color="none:display_name:nk",
        ),
        worksheet(
            "Latest Revenue",
            annual,
            "Annual Financials",
            f"[{annual}].[none:display_name:nk]",
            f"([{annual}].[none:year_ended:ok] * [{annual}].[sum:revenue_usd:qk])",
            "Bar",
            [company, year, revenue, latest],
            color="none:display_name:nk",
            latest_only=True,
        ),
        worksheet(
            "Latest Operating Margin",
            annual,
            "Annual Financials",
            f"[{annual}].[none:display_name:nk]",
            f"([{annual}].[none:year_ended:ok] * [{annual}].[usr:Operating Margin %:qk])",
            "Bar",
            [company, year, operating, latest],
            color="none:display_name:nk",
            latest_only=True,
        ),
        worksheet(
            "Latest Net Income",
            annual,
            "Annual Financials",
            f"[{annual}].[none:display_name:nk]",
            f"([{annual}].[none:year_ended:ok] * [{annual}].[sum:net_income_usd:qk])",
            "Bar",
            [company, year, profit, latest],
            color="none:display_name:nk",
            latest_only=True,
        ),
        worksheet(
            "Latest Cash Flow",
            annual,
            "Annual Financials",
            f"[{annual}].[none:display_name:nk]",
            f"([{annual}].[none:year_ended:ok] * [{annual}].[sum:operating_cash_flow_usd:qk])",
            "Bar",
            [company, year, cash, latest],
            color="none:display_name:nk",
            latest_only=True,
        ),
        worksheet(
            "Company List",
            dim,
            "Company Directory",
            f"([{dim}].[none:display_name:nk] / [{dim}].[none:business:nk] / [{dim}].[none:headquarters_city:nk])",
            "",
            "Automatic",
            [
                ("display_name", "None", "nk", "nominal"),
                ("business", "None", "nk", "nominal"),
                ("headquarters_city", "None", "nk", "nominal"),
            ],
        ),
    ]
    return "\n".join(sheets)


def zone_chart(zone_id: int, name: str, x: int, y: int, w: int, h: int) -> str:
    return (
        f"        <zone h='{h}' id='{zone_id}' name='{attr(name)}' w='{w}' x='{x}' y='{y}'>\n"
        "          <layout-cache minheight='120' minwidth='160' type-h='scalable' type-v='scalable' />\n"
        "        </zone>"
    )


def zone_text(zone_id: int, text: str, x: int, y: int, w: int, h: int) -> str:
    return (
        f"        <zone h='{h}' id='{zone_id}' type-v2='text' w='{w}' x='{x}' y='{y}'>\n"
        "          <formatted-text>\n"
        f"            <run fontcolor='#102033' fontsize='16'>{attr(text)}</run>\n"
        "          </formatted-text>\n"
        "        </zone>"
    )


def dashboard(name: str, charts: list[tuple[str, int, int, int, int]], blurb: str) -> str:
    zones = [zone_text(2, blurb, 0, 0, 100000, 7000)]
    for index, (sheet, x, y, w, h) in enumerate(charts, start=3):
        zones.append(zone_chart(index, sheet, x, y, w, h))
    inner = "\n".join(zones)
    return f"""    <dashboard name='{attr(name)}'>
      <style>
        <style-rule element='table'>
          <format attr='background-color' value='#f4f7fb' />
        </style-rule>
      </style>
      <size maxheight='900' maxwidth='1400' minheight='900' minwidth='1400' sizing-mode='fixed' />
      <zones>
        <zone h='100000' id='1' type-v2='layout-basic' w='100000' x='0' y='0'>
{inner}
        </zone>
      </zones>
    </dashboard>"""


def dashboards() -> str:
    pages = [
        dashboard(
            "Executive Overview",
            [
                ("Revenue Trend", 0, 7000, 62000, 46000),
                ("YoY Revenue Growth", 62000, 7000, 38000, 46000),
                ("Latest Revenue", 0, 53000, 50000, 47000),
                ("Latest Operating Margin", 50000, 53000, 50000, 47000),
            ],
            "Executive Overview",
        ),
        dashboard(
            "Revenue & Growth",
            [
                ("Revenue Trend", 0, 7000, 64000, 93000),
                ("YoY Revenue Growth", 64000, 7000, 36000, 46000),
                ("TTM Revenue", 64000, 53000, 36000, 47000),
            ],
            "Revenue & Growth",
        ),
        dashboard(
            "Profitability & Margins",
            [
                ("Gross Margin Trend", 0, 7000, 34000, 46000),
                ("Operating Margin Trend", 34000, 7000, 33000, 46000),
                ("Net Margin Trend", 67000, 7000, 33000, 46000),
                ("Margin Change", 0, 53000, 100000, 47000),
            ],
            "Profitability & Margins",
        ),
        dashboard(
            "Peer Comparison",
            [
                ("Latest Revenue", 0, 7000, 50000, 46000),
                ("Latest Operating Margin", 50000, 7000, 50000, 46000),
                ("Latest Net Income", 0, 53000, 34000, 47000),
                ("Latest Cash Flow", 34000, 53000, 33000, 47000),
                ("Company List", 67000, 53000, 33000, 47000),
            ],
            "Peer Comparison",
        ),
    ]
    return "\n".join(pages)


def window_for_sheet(name: str) -> str:
    return f"""    <window class='worksheet' name='{attr(name)}'>
      <cards>
        <edge name='left'>
          <strip size='160'>
            <card type='pages' />
            <card type='filters' />
            <card type='marks' />
          </strip>
        </edge>
        <edge name='top'>
          <strip size='31'>
            <card type='columns' />
          </strip>
          <strip size='31'>
            <card type='rows' />
          </strip>
        </edge>
      </cards>
    </window>"""


def windows() -> str:
    sheet_names = [
        "Revenue Trend",
        "YoY Revenue Growth",
        "Gross Margin Trend",
        "Operating Margin Trend",
        "Net Margin Trend",
        "Margin Change",
        "TTM Revenue",
        "Latest Revenue",
        "Latest Operating Margin",
        "Latest Net Income",
        "Latest Cash Flow",
        "Company List",
    ]
    dashboard_names = [
        "Executive Overview",
        "Revenue & Growth",
        "Profitability & Margins",
        "Peer Comparison",
    ]
    dashboard_sheets = {
        "Executive Overview": ["Revenue Trend", "YoY Revenue Growth", "Latest Revenue", "Latest Operating Margin"],
        "Revenue & Growth": ["Revenue Trend", "YoY Revenue Growth", "TTM Revenue"],
        "Profitability & Margins": ["Gross Margin Trend", "Operating Margin Trend", "Net Margin Trend", "Margin Change"],
        "Peer Comparison": ["Latest Revenue", "Latest Operating Margin", "Latest Net Income", "Latest Cash Flow", "Company List"],
    }
    blocks = []
    for name in dashboard_names:
        views = "\n".join(f"        <viewpoint name='{attr(sheet)}' />" for sheet in dashboard_sheets[name])
        blocks.append(
            f"""    <window class='dashboard' name='{attr(name)}'>
      <viewpoints>
{views}
      </viewpoints>
      <active id='-1' />
    </window>"""
        )
    blocks.extend(window_for_sheet(name) for name in sheet_names)
    return "\n".join(blocks)


def workbook_xml(directory: str) -> str:
    sources = "\n".join(
        datasource_xml(ds_name, filename, caption, formulas, directory)
        for ds_name, (filename, caption, formulas) in DATA_FILES.items()
    )
    return f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook original-version='18.1' source-build='2024.2.0 (20242.24.0709.1612)' source-platform='win' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <preferences>
    <preference name='ui.encoding.shelf.height' value='24' />
    <preference name='ui.shelf.height' value='26' />
  </preferences>
  <datasources>
{sources}
  </datasources>
  <worksheets>
{worksheets()}
  </worksheets>
  <dashboards>
{dashboards()}
  </dashboards>
  <windows source-height='30'>
{windows()}
  </windows>
</workbook>
"""


def main() -> None:
    tableau_dir = ROOT / "tableau"
    tableau_dir.mkdir(parents=True, exist_ok=True)
    twb_path = tableau_dir / "CorporateFinancialsDashboard.twb"
    twb_xml = workbook_xml("../data")
    ElementTree.fromstring(twb_xml)
    twb_path.write_text(twb_xml, encoding="utf-8")
    guide_path = tableau_dir / "calculated_fields.md"
    guide_path.write_text(markdown_guide(), encoding="utf-8")

    packaged_xml = workbook_xml("Data")
    ElementTree.fromstring(packaged_xml)
    twbx_path = tableau_dir / "CorporateFinancialsDashboard.twbx"
    with zipfile.ZipFile(twbx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CorporateFinancialsDashboard.twb", packaged_xml)
        for filename in (
            "company_financials_annual.csv",
            "company_financials_quarterly.csv",
            "dim_company.csv",
        ):
            archive.write(ROOT / "data" / filename, f"Data/{filename}")
    print(f"Wrote {twb_path.relative_to(ROOT)}")
    print(f"Wrote {guide_path.relative_to(ROOT)}")
    print(f"Wrote {twbx_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
