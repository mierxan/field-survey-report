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
