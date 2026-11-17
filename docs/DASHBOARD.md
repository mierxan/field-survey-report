# Dashboard sheet in the Weekly / Monthly Excel reports

Every Weekly and Monthly **Receiving** or **Withdrawal** Excel report starts
with a **Dashboard** sheet, made for the client. This covers the Summary
Report Excel button and the Export Excel button of the Weekly / Monthly
Summary, in the Owner and User editions alike. The phone app (1.7.0)
adds the same sheet to its Weekly Summary.

## What it shows

1. **Banner:** the report's name (for example *WEEKLY RECEIVING
   DASHBOARD*), the period, the site (the Location of the reports, or
   "N sites: ..."), and when it was made.
2. **Four KPI cards**, as on the Receiving and Withdrawal screens. Each
   card shows the change against the previous period, with a green ▲ or a
   red ▼.
   - Receiving: Transactions, Total Quantity Received, Total Packages,
     Good / Bad Order.
   - Withdrawal: Transactions, Cargo Lines Withdrawn, Total Packages,
     Good / Bad Order.
3. **Charts**, two per row:
   - Weekly: Transactions per Day; Good Order / Bad Order (doughnut);
     Quantity Received (or Cargo Lines Withdrawn) per Day; Top Suppliers
     (or Consignees); Transactions per Site / Warehouse.
   - Monthly: the same per Week, plus Transactions per Day.
   - Top lists show the 7 biggest and add up the rest as "Others (n)".
4. **Compared with the previous week or month:** a short table.
5. **Figures behind the charts:** the numbers each chart is drawn from.

The figures are the screen's own (`analytics.summarize`), so the
dashboard and the screen always agree.

## Withdrawal: delivery destinations

A Withdrawal dashboard also shows where the cargo was delivered: a chart of
**shipments per delivery destination**, and a table with, per destination,
the **shipments** (reports), **total packages** (Declared Goods), **cargo
line items** and the share of shipments, with in-cell bars (the phone's
table has no bars).

## The interactive Dashboard (Inspection Reports > Weekly Summary > Export)

The Weekly Summary export starts with an **interactive Dashboard**. The
client picks from four yellow dropdowns - **Activity**, **Week**, **Cargo
Condition**, **Supplier** - and the cards and charts change at once:

- Cards: Transactions, Line Items, Total Quantity, Good / Bad Order.
- Charts: Transactions per Day (the chosen week coloured, the other days
  grey), Transactions per Week, Good Order / Bad Order, Top Suppliers (the
  chosen supplier coloured), Receiving vs Withdrawal, Quantity per Day,
  and Withdrawal: Shipments per Destination.
- Withdrawal delivery destinations table: shipments, total packages,
  cargo line items and share per destination, with in-cell bars. It
  always shows Withdrawal reports and follows the Week, Cargo Condition
  and Supplier choices.

How it works: Excel formulas (SUMIFS) over a hidden **Data** sheet (one
typed row per line, with the Control #, so a report is counted once even
when reports share an SO Number) and a hidden **Calc** sheet that the cards
and charts read. No macros, no security warning; Excel 2007 or later
(SUMIFS). The file asks Excel to calculate on opening, so viewers that do
not calculate (some phone previews) show the cards empty. The Weekly
Summary sheet is unchanged. Packages come from the reports' Declared Goods
on this PC. Checked in Excel 2007 by changing the dropdowns and comparing
the cards with the program's own figures.

The phone app (1.8.0) makes the same interactive Dashboard: Export Excel >
Weekly Summary > **All (interactive)** (`InteractiveDashboard.kt`, its own
xlsx writer). It also saves every formula's value for the first choices,
so phone viewers that do not calculate still show the cards and charts.

## Periods

- PC: a week is Monday to Sunday; a month is the calendar month.
- Phone: its own Weekly Summary periods, Week 1 = days 1-7 of the month
  ... Week 5 = day 29 to the month's end, or the whole month. The period
  before Week 1 is the last week of the previous month.

## How it is made

- `warehouse/dashboard.py` decides what is shown (cards, charts,
  comparison). `exports.write_dashboard` lays it out with openpyxl.
- Classic Excel charts only (column, bar, doughnut), so the file opens in
  every Excel since 2007. Checked by opening the files in Excel 2007.
- Labels hide zeros (`#,##0;-#,##0;;`). openpyxl leaves out
  `sourceLinked="0"`, without which Excel ignores that format; the saved
  file gets it added (`_own_label_formats`).
- Phone: `DashboardBuilder` (the figures), `DashboardSheet` (the layout)
  and `XlsxCharts` (the chart parts of its own xlsx writer). The chart
  parts also carry the figures as a cache, so viewers that do not
  recalculate still show the charts.

## How the charts fit (Phase 12)

Every dashboard chart, PC and phone, is placed by its cells
(`warehouse/chart_style.py`; phone: `ChartPlace` in `XlsxCharts.kt`):

- **Pinned to cells**, not sized in centimetres: a chart covers columns
  A-H, I-P or A-P and 17 rows; the 18th row is the gap to the next charts.
  A chart in centimetres came out wider than its columns wherever the
  columns are drawn narrower - Windows display scaling above 100%, WPS
  Office, phone viewers - and lay under the chart beside it.
- **A gap** of a few pixels between two charts side by side, and a small
  margin inside the right edge and the foot: printed, Excel draws a chart
  a little bigger than its cells. The print area has one spare column (Q)
  for the same reason.
- **Title and legend in their own place**: both are marked as not lying on
  the chart (`overlay` 0), every text has its own size (title 14 pt,
  axes, labels and legend 9 pt), and legends sit under the chart. Viewers
  that guessed otherwise drew the title over the "Selected / Other days"
  legend.
- **A month of days** is labelled with the day number (1 ... 31); 31
  dates side by side ran together. A week keeps its dates (26-Oct ...).
- Numbers inside the stacked bars of the interactive Dashboard are white.
- Card texts shrink to fit their card.
- **Printed pages** start between charts: the banner, cards and first
  charts on page 1, then two rows of charts a page; the figures behind the
  charts start a new page. The page starts on the empty row above a chart,
  so no edge of it shows at the foot of the page before.

Checked by opening the files in Excel and saving each Dashboard as a
picture and as a PDF; `tests/test_chart_layout.py` keeps the rules.
