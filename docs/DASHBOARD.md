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

## Owner Dashboard: Top 10 Suppliers by Total Value (PHP)

On the Owner edition's **Dashboard** page (not an Excel sheet): the ten
suppliers whose Receiving deliveries in the chosen period and warehouse
are worth the most, in Philippine pesos. Withdrawal reports are never
counted.

- A cargo line's value: its **Total Price**, or **Unit Price x Quantity**
  when the Total Price is empty, in the line's **Currency** (a code typed
  with the price, as in `jpy 4,000.-`, is used when the Currency column is
  empty).
- **Exchange Rates to PHP...**: one rate per currency (1 USD = n PHP),
  entered by the owner and kept in the warehouse settings file with the
  date and user. The program is offline and never fetches rates.
- Left out and counted in the note under the chart: lines in a currency
  without a rate, lines with a price but no currency, lines without a
  price.
- Suppliers are grouped by their name as typed: two spellings of one
  supplier are two bars.
- Code: `warehouse/values.py` (the figures), `DashboardPage` in
  `warehouse_ui/pages.py` and `ask_php_rates` in `warehouse_ui/dialogs.py`.

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
