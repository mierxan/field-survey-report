"""Analytics and Reports: trend charts, the management summary and the
report centre (Excel / PDF reports)."""

from fsr_typeahead import Combobox as TypeaheadCombobox

from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk

import ttkbootstrap as tb

from warehouse import analytics as an
from warehouse import exports
from warehouse import periods as pr
from warehouse.transactions import RECEIVING, WITHDRAWAL

from .components import Card, ChartPanel, PeriodBar, ask_export, fill_choices
from .pages import Page, _color_bars, _status_chart

DATE_FORMAT = "%d-%b-%Y"


class AnalyticsPage(Page):
    title = "Analytics and Reports"
    subtitle = ("Transaction trends, cargo condition and inventory "
                "status.")

    def build(self):
        self.bar = PeriodBar(self.main, self.render_filters,
                             filters=("warehouse", "supplier", "consignee",
                                      "cargo_type", "condition", "activity"),
                             default="this_year")
        self.bar.grid(row=0, column=0, sticky="we")

        summary = Card(self.main, "Management Summary",
                       "Statements are generated only from the records; "
                       "nothing is estimated.")
        summary.grid(row=1, column=0, sticky="we", pady=(10, 0))
        self.statements = summary.content

        charts = ttk.Frame(self.main, style="Page.TFrame")
        charts.grid(row=2, column=0, sticky="we", pady=(10, 0))
        for col in range(2):
            charts.columnconfigure(col, weight=1, uniform="an")
        self.daily = ChartPanel(charts, "Daily Receiving vs Withdrawal "
                                "Transactions")
        self.daily.grid(row=0, column=0, columnspan=2, sticky="we")
        self.weekly = ChartPanel(charts, "Weekly Receiving vs Withdrawal "
                                 "Transactions")
        self.weekly.grid(row=1, column=0, sticky="nsew", padx=(0, 10),
                         pady=(10, 0))
        self.monthly = ChartPanel(charts, "Monthly Receiving vs Withdrawal "
                                  "Transactions")
        self.monthly.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        self.good_bad = ChartPanel(charts, "Good Order vs Bad Order",
                                   "Inspection reports")
        self.good_bad.grid(row=2, column=0, sticky="nsew", padx=(0, 10),
                           pady=(10, 0))
        self.status = ChartPanel(charts, "Remaining Warehouse Cargo by "
                                 "Status", "Inventory items, current "
                                 "balance")
        self.status.grid(row=2, column=1, sticky="nsew", pady=(10, 0))

        self._build_report_centre()

    def _build_report_centre(self):
        card = Card(self.main, "Report Centre",
                    "Each report includes the title, reporting period, date "
                    "generated, filters, KPI summary, detailed records and "
                    "totals. Filters above apply where relevant.")
        card.grid(row=3, column=0, sticky="we", pady=(10, 0))
        c = card.content
        ttk.Label(c, text="Report", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w")
        self.report = TypeaheadCombobox(c, state="readonly", width=36,
                                  values=[t for _, t in exports.REPORT_TYPES])
        self.report.set(exports.REPORT_TYPES[-1][1])
        self.report.no_dirty = True
        self.report.grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.report.bind("<<ComboboxSelected>>", lambda e: self._report_kind())
        ttk.Label(c, text="Day (daily / weekly / monthly summaries)",
                  style="CardMuted.TLabel").grid(row=0, column=1, sticky="w")
        self.report_day = tb.DateEntry(c, dateformat=DATE_FORMAT,
                                       firstweekday=0, width=13)
        self.report_day.grid(row=1, column=1, sticky="w", padx=(0, 10))
        ttk.Label(c, text="Cargo item (transaction history)",
                  style="CardMuted.TLabel").grid(row=0, column=2, sticky="w")
        self.report_item = TypeaheadCombobox(c, state="readonly", width=52)
        self.report_item.no_dirty = True
        self.report_item.grid(row=1, column=2, sticky="w", padx=(0, 10))
        tb.Button(c, text="Export Excel", bootstyle="success",
                  command=lambda: self.export_report("xlsx")).grid(
            row=1, column=3)
        tb.Button(c, text="Export PDF", bootstyle="info",
                  command=lambda: self.export_report("pdf")).grid(
            row=1, column=4, padx=6)
        self._report_kind()

    def _report_kind(self):
        key = self._report_key()
        self.report_day.configure(state="normal" if key.split("_")[0] in
                                  exports.SUMMARY_KINDS else "disabled")
        self.report_item.configure(state="readonly" if key == "history"
                                   else "disabled")

    def _report_key(self):
        title = self.report.get()
        return next(k for k, t in exports.REPORT_TYPES if t == title)

    def export_report(self, kind):
        key = self._report_key()
        try:
            filters = self.bar.filters()
            day = datetime.strptime(self.report_day.entry.get().strip(),
                                    DATE_FORMAT).date()
        except ValueError as error:
            messagebox.showwarning("Report", f"Check the dates:\n{error}",
                                   parent=self.ctx.window)
            return
        item = None
        if key == "history":
            labels = self.report_item.cget("values")
            if self.report_item.get() not in labels:
                messagebox.showwarning("Report", "Choose a cargo item first.",
                                       parent=self.ctx.window)
                return
            item = self.snapshot.inventory.items[
                list(labels).index(self.report_item.get())]
        doc = exports.build_report(key, self.snapshot, filters, day, item)
        doc.source = self.ctx.source_text()
        ask_export(self.ctx, doc, kind)

    # ---- render ----
    def render(self, snapshot):
        fill_choices(self.bar, snapshot.transactions)
        self.report_item.configure(values=[
            f"{i.warehouse} | {i.identity} | {i.description}"
            for i in snapshot.inventory.items])
        self.bar._changed()

    def render_filters(self, filters):
        snap = self.snapshot
        if snap is None:
            return
        self.filters = filters
        txs = snap.transactions
        daily_period = self._daily_period(filters.period)
        self.daily.header.winfo_children()[0].configure(
            text="Daily Receiving vs Withdrawal Transactions  ·  "
                 f"{daily_period.range_text()}")
        for panel, gran, period in ((self.daily, "day", daily_period),
                                    (self.weekly, "week", filters.period),
                                    (self.monthly, "month", filters.period)):
            series = []
            for activity in (RECEIVING, WITHDRAWAL):
                if filters.activity and filters.activity != activity:
                    continue
                points, _ = an.trend(txs, period, gran,
                                     activity=activity, filters=filters)
                series.append((activity, [v for _, v in points],
                               activity.lower()))
            labels = [c for c, _ in points] if series else []
            panel.trend(labels, series, "Transactions")
        split = an.good_vs_bad(txs, filters)
        self.good_bad.bars(list(split), [("Reports", list(split.values()),
                                          None)], horizontal=True,
                           value_label="Inspection reports")
        _color_bars(self.good_bad, ["good", "critical"])
        _status_chart(self.status, snap.inventory, filters.warehouse)
        self._render_statements()

    def _daily_period(self, period):
        """Daily points over a long period are unreadable: the daily chart
        shows the last 31 days of the period (up to today / the last
        record) and says so in its title."""
        start, end = period.start, period.end
        if start is None:
            start, end = an.data_span(self.snapshot.transactions)
            if start is None:
                return period
        end = min(end, max(date.today(), start))
        if (end - start).days <= 31:
            return pr.Period(start, end, "custom", "Daily")
        return pr.Period(end - timedelta(days=30), end, "custom",
                         "Last 31 days")

    def _render_statements(self):
        for child in self.statements.winfo_children():
            child.destroy()
        ms = an.management_summary(self.snapshot.transactions,
                                   self.snapshot.inventory, self.filters,
                                   self.snapshot.side.case_statuses())
        ttk.Label(self.statements, text=f"Period: "
                  f"{self.filters.period.describe()}  ·  Filters: "
                  f"{'; '.join(self.filters.describe())}",
                  style="CardMuted.TLabel").grid(row=0, column=0,
                                                 columnspan=2, sticky="w",
                                                 pady=(0, 6))
        for row, (topic, text) in enumerate(ms.statements, start=1):
            ttk.Label(self.statements, text=topic, style="KpiName.TLabel"
                      ).grid(row=row, column=0, sticky="nw", padx=(0, 14),
                             pady=2)
            ttk.Label(self.statements, text=text, style="Card.TLabel",
                      wraplength=900, justify="left").grid(
                row=row, column=1, sticky="w", pady=2)
        self.statements.columnconfigure(1, weight=1)
