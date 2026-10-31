"""Dashboard, Receiving / Withdrawal Transactions and Bad Order Monitoring."""

import tkinter
from datetime import date, datetime, timedelta
from tkinter import ttk

import ttkbootstrap as tb

from warehouse import analytics as an
from warehouse import exports
from warehouse import periods as pr
from warehouse import tables as tbl
from warehouse.transactions import BAD_ORDER, RECEIVING, WITHDRAWAL

from .components import (Card, ChartPanel, DataTable, EmptyState, KpiGrid,
                         PeriodBar, ScrollPage, ask_export,
                         explain_load_error, fill_choices, section_label)
from .dialogs import DetailPanel, ask_case_status, line_pairs

DATE_FORMAT = "%d-%b-%Y"


class Page(ScrollPage):
    """A module page: header, then content built by render(snapshot)."""

    title = ""
    subtitle = ""

    def __init__(self, parent, ctx, service):
        super().__init__(parent)
        self.ctx, self.service = ctx, service
        self.snapshot = None
        head = ttk.Frame(self.body, style="Page.TFrame")
        head.grid(row=0, column=0, sticky="we")
        head.columnconfigure(0, weight=1)
        subtitle = ttk.Label(head, text=self.subtitle,
                             style="PageMuted.TLabel", justify="left")
        subtitle.grid(row=1, column=0, columnspan=3, sticky="w",
                      pady=(4, 0))
        head.bind("<Configure>", lambda e: subtitle.configure(
            wraplength=max(e.width - 10, 300)))
        self.source_label = ttk.Label(head, text="", style="PageMuted.TLabel")
        self.source_label.grid(row=0, column=0, sticky="w")
        tb.Button(head, text="⟳ Refresh", bootstyle="secondary-outline",
                  command=self.reload).grid(row=0, column=2, sticky="e")
        self.state_holder = ttk.Frame(self.body, style="Page.TFrame")
        self.state_holder.grid(row=1, column=0, sticky="we", pady=(10, 0))
        self.state_holder.columnconfigure(0, weight=1)
        self.main = ttk.Frame(self.body, style="Page.TFrame")
        self.main.grid(row=2, column=0, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.built = False

    # ---- loading ----
    def on_show(self):
        self.service.request(self._loaded)

    def reload(self):
        self.service.invalidate()
        self.service.request(self._loaded)

    def _loaded(self, snapshot, error):
        for child in self.state_holder.winfo_children():
            child.destroy()
        self.snapshot = snapshot
        if error is not None:
            EmptyState(self.state_holder, "Records unavailable",
                       explain_load_error(error), "Try again",
                       self.reload).grid(row=0, column=0, sticky="we")
            self.main.grid_remove()
            return
        self.source_label.configure(text=(
            f"Data: {self.ctx.source_text()}  ·  loaded "
            f"{snapshot.loaded_at:%H:%M}"))
        if not snapshot.reports:
            EmptyState(
                self.state_holder, "No saved inspection reports yet",
                "Figures appear here once reports are saved. Create a report "
                "in Inspection Reports (set Activity to Receiving or "
                "Withdrawal), or start the Demo Mode to explore the system "
                "with fictional TEST data.", "Go to Inspection Reports",
                lambda: self.ctx.show_module("inspection")).grid(
                row=0, column=0, sticky="we")
            if not self.show_when_empty:
                self.main.grid_remove()
                return
        self.main.grid()
        if not self.built:
            self.build()
            self.built = True
        self.render(snapshot)

    show_when_empty = False

    def build(self):
        raise NotImplementedError

    def render(self, snapshot):
        raise NotImplementedError

    def apply_theme(self):
        super().apply_theme()
        if getattr(self, "built", False) and self.snapshot is not None:
            self.render(self.snapshot)


# =====================================================
# DASHBOARD
# =====================================================

class DashboardPage(Page):
    title = "Dashboard"
    subtitle = ("Inspection and warehouse KPIs calculated from the saved "
                "records. Reports, cargo lines, quantities and weights are "
                "counted separately.")

    def build(self):
        self.bar = PeriodBar(self.main, self.render_filters,
                             filters=("warehouse",), default="this_month")
        self.bar.grid(row=0, column=0, sticky="we")
        section_label(self.main, "Inspection reports - selected period", 1)
        self.inspection = KpiGrid(self.main)
        self.inspection.grid(row=2, column=0, sticky="we")
        section_label(self.main, "Warehouse activity - selected period", 3)
        self.activity = KpiGrid(self.main)
        self.activity.grid(row=4, column=0, sticky="we")
        charts = ttk.Frame(self.main, style="Page.TFrame")
        charts.grid(row=7, column=0, sticky="we", pady=(8, 0))
        for col in range(2):
            charts.columnconfigure(col, weight=1, uniform="ch")
        self.trend = ChartPanel(charts, "Receiving vs Withdrawal "
                                "Transactions", "Transactions (reports) per "
                                "day / week / month of the period")
        self.trend.grid(row=0, column=0, columnspan=2, sticky="we",
                        pady=(0, 10))
        self.good_bad = ChartPanel(charts, "Good Order vs Bad Order",
                                   "Inspection reports in the period")
        self.good_bad.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.status = ChartPanel(charts, "Warehouse Cargo by Status",
                                 "Inventory items, current balance")
        self.status.grid(row=1, column=1, sticky="nsew")
        self.aging = ChartPanel(charts, "Inventory Aging",
                                "Receiving batches with a remaining balance")
        self.aging.grid(row=2, column=0, columnspan=2, sticky="we",
                        pady=(10, 0))

    def render(self, snapshot):
        fill_choices(self.bar, snapshot.transactions)
        self.bar._changed()

    def render_filters(self, filters):
        snap = self.snapshot
        if snap is None:
            return
        self.inspection.show(an.inspection_kpis(snap.transactions, filters))
        kpis = an.warehouse_kpis(snap.transactions, snap.inventory, filters)
        self.activity.show(kpis[:4])
        series, gran = an.trend(snap.transactions, filters.period,
                                filters=an.Filters(
                                    warehouse=filters.warehouse))
        wseries, _ = an.trend(snap.transactions, filters.period, gran,
                              activity=WITHDRAWAL, filters=an.Filters(
                                  warehouse=filters.warehouse))
        rseries, _ = an.trend(snap.transactions, filters.period, gran,
                              activity=RECEIVING, filters=an.Filters(
                                  warehouse=filters.warehouse))
        self.trend.trend([c for c, _ in series],
                         [("Receiving", [v for _, v in rseries], "receiving"),
                          ("Withdrawal", [v for _, v in wseries],
                           "withdrawal")], "Transactions")
        split = an.good_vs_bad(snap.transactions, filters)
        self.good_bad.bars(list(split), [("Reports", list(split.values()),
                                          None)], horizontal=True,
                           value_label="Inspection reports")
        _color_bars(self.good_bad, ["good", "critical"])
        _status_chart(self.status, snap.inventory, filters.warehouse)
        _aging_chart(self.aging, snap.inventory, filters.warehouse)


def _color_bars(panel, tokens_):
    """Recolour a single-series bar chart per bar (status colours)."""
    if panel.ax is None:
        return
    bars = [p for p in panel.ax.patches]
    for bar, token in zip(bars, tokens_):
        bar.set_color(panel.t[token])
        bar.set_edgecolor(panel.t["card"])
    panel.canvas.draw_idle()


def _status_chart(panel, inventory, warehouse=""):
    from .theme import STATUS_TONES
    items = [i for i in inventory.items if not warehouse
             or an.norm_key(i.warehouse) == an.norm_key(warehouse)]
    counts = {s: sum(1 for i in items if i.status == s)
              for s in STATUS_TONES}
    labels = {"In Stock": "In Stock (no withdrawal)"}
    panel.bars([labels.get(s, s) for s in counts],
               [("Items", list(counts.values()), None)], horizontal=True,
               value_label="Inventory items")
    _color_bars(panel, list(STATUS_TONES.values()))


def _aging_chart(panel, inventory, warehouse=""):
    from warehouse.inventory import bucket_labels
    rows = [r for r in inventory.aging_rows if not warehouse
            or an.norm_key(r.item.warehouse) == an.norm_key(warehouse)]
    labels = bucket_labels(inventory.thresholds)
    counts = [sum(1 for r in rows if r.bucket == label) for label in labels]
    panel.bars(labels, [("Batches", counts, None)],
               value_label="Receiving batches")
    if panel.ax is not None:
        ramp = panel.t["ramp"]
        for bar, color in zip(panel.ax.patches, ramp):
            bar.set_color(color)
            bar.set_edgecolor(panel.t["card"])
        panel.canvas.draw_idle()


# =====================================================
# RECEIVING / WITHDRAWAL TRANSACTIONS
# =====================================================

class TransactionsPage(Page):
    activity = RECEIVING

    def __init__(self, parent, ctx, service, activity):
        self.activity = activity
        self.title = f"{activity} Transactions"
        self.subtitle = (
            f"Inspection reports with Activity = {activity}, read directly "
            "from the saved reports (no copies). One report = one "
            "transaction; each Item List line = one cargo line.")
        super().__init__(parent, ctx, service)
        self.mode = tkinter.StringVar(value="daily")
        self.day = date.today()

    def build(self):
        tabs = ttk.Frame(self.main, style="Page.TFrame")
        tabs.grid(row=0, column=0, sticky="we")
        self.tab_buttons = {}
        for key, text in (("daily", "Daily Summary"),
                          ("weekly", "Weekly Summary"),
                          ("monthly", "Monthly Summary"),
                          ("all", "All Transactions")):
            button = tb.Button(tabs, text=text, width=17,
                               command=lambda k=key: self.set_mode(k))
            button.pack(side="left", padx=(0, 6))
            self.tab_buttons[key] = button

        # --- summary view ---
        self.summary_view = ttk.Frame(self.main, style="Page.TFrame")
        self.summary_view.columnconfigure(0, weight=1)
        picker = Card(self.summary_view)
        picker.grid(row=0, column=0, sticky="we", pady=(10, 0))
        row = picker.content
        tb.Button(row, text="‹", width=3, bootstyle="secondary-outline",
                  command=lambda: self.step(-1)).grid(row=0, column=0)
        self.day_entry = tb.DateEntry(row, dateformat=DATE_FORMAT,
                                      firstweekday=0, width=13)
        self.day_entry.grid(row=0, column=1, padx=6)
        self.day_entry.bind("<<DateEntrySelected>>", self._day_typed,
                            add="+")
        self.day_entry.entry.bind("<Return>", self._day_typed)
        tb.Button(row, text="›", width=3, bootstyle="secondary-outline",
                  command=lambda: self.step(1)).grid(row=0, column=2)
        tb.Button(row, text="Today", bootstyle="secondary-outline",
                  command=lambda: self.set_day(date.today())).grid(
            row=0, column=3, padx=(6, 16))
        self.period_label = ttk.Label(row, text="", style="CardTitle.TLabel")
        self.period_label.grid(row=0, column=4, sticky="w")
        row.columnconfigure(4, weight=1)
        tb.Button(row, text="Export Excel", bootstyle="success-outline",
                  command=lambda: self.export_summary("xlsx")).grid(
            row=0, column=5)
        tb.Button(row, text="Export PDF", bootstyle="info-outline",
                  command=lambda: self.export_summary("pdf")).grid(
            row=0, column=6, padx=(6, 0))
        # Weekly / Monthly only: the line-by-line Summary Report format.
        self.report_buttons = [
            tb.Button(row, text="Summary Report Excel", bootstyle="success",
                      command=lambda: self.export_report("xlsx")),
            tb.Button(row, text="Summary Report PDF", bootstyle="info",
                      command=lambda: self.export_report("pdf"))]
        for col, button in enumerate(self.report_buttons, start=7):
            button.grid(row=0, column=col, padx=(6, 0))
        self.kpis = KpiGrid(self.summary_view)
        self.kpis.grid(row=1, column=0, sticky="we", pady=(10, 0))
        mid = ttk.Frame(self.summary_view, style="Page.TFrame")
        mid.grid(row=2, column=0, sticky="we")
        for col in range(2):
            mid.columnconfigure(col, weight=1, uniform="mid")
        self.breakdown_chart = ChartPanel(mid, "Breakdown", height=220)
        self.breakdown_chart.grid(row=0, column=0, sticky="nsew",
                                  padx=(0, 10))
        self.breakdowns = Card(mid, "Breakdowns and Comparison")
        self.breakdowns.grid(row=0, column=1, sticky="nsew")
        lines_card = Card(self.summary_view, "Transaction Lines",
                          "Double-click a line to open its inspection "
                          "report.")
        lines_card.grid(row=3, column=0, sticky="we", pady=(10, 0))
        self.summary_table = DataTable(lines_card.content, tbl.LINE_COLUMNS,
                                       height=10,
                                       on_open=self.open_line)
        self.summary_table.grid(row=0, column=0, sticky="we")

        # --- all transactions view ---
        self.all_view = ttk.Frame(self.main, style="Page.TFrame")
        self.all_view.columnconfigure(0, weight=1)
        party = "supplier" if self.activity == RECEIVING else "consignee"
        self.bar = PeriodBar(self.all_view, self.render_all,
                             filters=("warehouse", party, "condition"),
                             default="this_month", with_search=True)
        self.bar.grid(row=0, column=0, sticky="we", pady=(10, 0))
        self.all_kpis = KpiGrid(self.all_view)
        self.all_kpis.grid(row=1, column=0, sticky="we", pady=(10, 0))
        table_card = Card(self.all_view, f"{self.activity} Cargo Lines",
                          "Click a column heading to sort. Double-click to "
                          "open the original inspection report.")
        table_card.grid(row=2, column=0, sticky="we")
        self.all_table = DataTable(table_card.content, tbl.LINE_COLUMNS,
                                   height=14, on_select=self.show_line,
                                   on_open=self.open_line,
                                   export=self.export_all)
        self.all_table.grid(row=0, column=0, sticky="we")
        self.detail = DetailPanel(self.all_view, "Transaction Details",
                                  [("Open Inspection Report",
                                    self.open_selected, "primary")])
        self.detail.grid(row=3, column=0, sticky="we", pady=(10, 0))
        self.set_mode("daily", render=False)

    # ---- modes ----
    def set_mode(self, mode, render=True):
        self.mode.set(mode)
        for key, button in self.tab_buttons.items():
            button.configure(bootstyle="primary" if key == mode
                             else "secondary-outline")
        for button in self.report_buttons:
            button.configure(state="normal" if mode in ("weekly", "monthly")
                             else "disabled")
        if mode == "all":
            self.summary_view.grid_remove()
            self.all_view.grid(row=1, column=0, sticky="we")
        else:
            self.all_view.grid_remove()
            self.summary_view.grid(row=1, column=0, sticky="we")
        if render and self.snapshot is not None:
            self.render(self.snapshot)

    def step(self, direction):
        mode = self.mode.get()
        if mode == "daily":
            self.set_day(self.day + timedelta(days=direction))
        elif mode == "weekly":
            self.set_day(self.day + timedelta(days=7 * direction))
        else:
            first = self.day.replace(day=1)
            target = (first - timedelta(days=1)).replace(day=1) \
                if direction < 0 else (first + timedelta(days=32)).replace(
                    day=1)
            self.set_day(target)

    def set_day(self, day):
        self.day = day
        self.day_entry.entry.delete(0, "end")
        self.day_entry.entry.insert(0, day.strftime(DATE_FORMAT))
        if self.snapshot is not None:
            self.render_summary()

    def _day_typed(self, event=None):
        try:
            self.set_day(datetime.strptime(self.day_entry.entry.get().strip(),
                                           DATE_FORMAT).date())
        except ValueError:
            self.period_label.configure(text="⚠ Use dd-MMM-yyyy, e.g. "
                                        "05-Oct-2026")

    # ---- render ----
    def render(self, snapshot):
        if self.mode.get() == "all":
            fill_choices(self.bar, snapshot.transactions)
            self.bar._changed()
        else:
            self.set_day(self.day)

    def current_summary(self):
        kind = self.mode.get()
        make = {"daily": pr.day_period, "weekly": pr.week_period,
                "monthly": pr.month_period}[kind]
        return an.summarize(self.snapshot.transactions, self.activity,
                            make(self.day))

    def render_summary(self):
        summary = self.current_summary()
        self.period_label.configure(text=summary.period.describe())
        self.kpis.show(exports.summary_kpis(summary))
        kind = self.mode.get()
        if kind == "daily":
            groups = summary.by_warehouse
            self.breakdown_chart.header.winfo_children()[0].configure(
                text="Transactions by Warehouse")
            self.breakdown_chart.bars([g[0] for g in groups], [
                ("Transactions", [g[1] for g in groups],
                 self.activity.lower())], horizontal=True,
                value_label="Transactions")
        else:
            data = summary.by_day if kind == "weekly" else summary.by_week
            labels = [pr.bucket_label(d, "day" if kind == "weekly"
                                      else "week") for d in data]
            self.breakdown_chart.header.winfo_children()[0].configure(
                text="Daily Breakdown" if kind == "weekly"
                else "Weekly Breakdown")
            self.breakdown_chart.bars(labels, [(
                "Transactions", list(data.values()),
                self.activity.lower())], value_label="Transactions")
        self._fill_breakdowns(summary)
        self.summary_table.set_rows(tbl.line_rows(summary.lines),
                                    summary.lines,
                                    f"No {self.activity} lines in this "
                                    "period.")

    def _fill_breakdowns(self, summary):
        content = self.breakdowns.content
        for child in content.winfo_children():
            child.destroy()
        row = 0

        def block(title, pairs):
            nonlocal row
            ttk.Label(content, text=title, style="KpiName.TLabel").grid(
                row=row, column=0, columnspan=4, sticky="w", pady=(6, 2))
            row += 1
            if not pairs:
                ttk.Label(content, text="None", style="CardMuted.TLabel"
                          ).grid(row=row, column=0, sticky="w")
                row += 1
            for values in pairs[:8]:
                for col, value in enumerate(values):
                    ttk.Label(content, text=str(value), style="Card.TLabel"
                              if col == 0 else "CardMuted.TLabel"
                              ).grid(row=row, column=col, sticky="w",
                                     padx=(0, 14))
                row += 1

        block("Warehouse  ·  transactions",
              [(w, t) for w, t, _ in summary.by_warehouse])
        if self.activity == RECEIVING:
            block("Supplier  ·  transactions",
                  [(s or "(not recorded)", t)
                   for s, t, _ in summary.by_supplier])
        else:
            block("Destination  ·  transactions",
                  [(s or "(not recorded)", t)
                   for s, t, _ in summary.by_destination])
        block("Good Order / Bad Order (transactions)",
              list(summary.by_condition.items()))
        if summary.previous is not None:
            block(f"Compared with {summary.previous.period.describe()}",
                  [(m, f"now {c}", f"before {p}", ch)
                   for m, c, p, ch in an.comparison_rows(summary)])

    def render_all(self, filters):
        snap = self.snapshot
        if snap is None:
            return
        filters.activity = self.activity
        chosen = an.filter_transactions(snap.transactions, filters)
        lines = an.lines_of(chosen)
        qty = an.qty_by_unit(lines)
        bad = sum(1 for t in chosen if t.condition == BAD_ORDER)
        transactions = an.KPI(f"{self.activity} Transactions", len(chosen),
                              an.fmt_number(len(chosen)),
                              "transactions (reports)",
                              filters.period.describe())
        bad_kpi = an.KPI("Bad Order Records", bad, an.fmt_number(bad),
                         "transactions", tone="danger")
        declared = [t.packages for t in chosen if t.packages is not None]
        packages = sum(declared) if declared else None
        packages_kpi = an.KPI("Total Packages", packages,
                              an.fmt_number(packages), "from Declared Goods")
        if self.activity == RECEIVING:
            total = sum(qty.values()) if qty else None
            self.all_kpis.show([
                transactions,
                an.KPI("Total Quantity Received", total,
                       an.fmt_number(total), "all units combined"),
                packages_kpi,
                bad_kpi,
            ])
        else:
            self.all_kpis.show([transactions, packages_kpi, bad_kpi])
        self.filters = filters
        self.all_table.set_rows(tbl.line_rows(lines), lines)
        self.detail.show([])

    # ---- actions ----
    def show_line(self, line):
        self.detail.show(line_pairs(line) if line else [])

    def open_line(self, line):
        self.ctx.open_report(line.control_no)

    def open_selected(self):
        line = self.all_table.selected_object()
        if line is not None:
            self.open_line(line)

    def export_summary(self, kind):
        doc = exports.transaction_summary_report(
            self.snapshot, self.activity, self.mode.get(), self.day)
        ask_export(self.ctx, doc, kind)

    def export_report(self, kind):
        doc = exports.summary_report(
            self.snapshot, self.activity, self.mode.get(), self.day)
        doc.source = self.ctx.source_text()
        ask_export(self.ctx, doc, kind)

    def export_all(self, kind):
        f = self.filters
        doc = exports.table_report(
            f"{self.activity} Transactions", f.period.describe(),
            f.describe(), tbl.LINE_COLUMNS, self.all_table.visible_rows(),
            source=self.ctx.source_text())
        ask_export(self.ctx, doc, kind)


# =====================================================
# BAD ORDER MONITORING
# =====================================================

class BadOrderPage(Page):
    title = "Bad Order Monitoring"
    subtitle = ("Inspection reports classified as Bad Order. Report counts "
                "and affected cargo lines are shown separately. Bad Order "
                "cargo stays in the inventory (no rule excludes it).")

    def build(self):
        self.bar = PeriodBar(self.main, self.render_filters,
                             filters=("warehouse", "activity", "supplier",
                                      "consignee", "case_status"),
                             default="this_year", with_search=True)
        self.bar.grid(row=0, column=0, sticky="we")
        self.kpis = KpiGrid(self.main)
        self.kpis.grid(row=1, column=0, sticky="we", pady=(10, 0))
        charts = ttk.Frame(self.main, style="Page.TFrame")
        charts.grid(row=2, column=0, sticky="we")
        for col in range(2):
            charts.columnconfigure(col, weight=1, uniform="bo")
        self.trend = ChartPanel(charts, "Bad Order Reports over Time")
        self.trend.grid(row=0, column=0, columnspan=2, sticky="we")
        gran = ttk.Frame(self.trend.header, style="CardPlain.TFrame")
        gran.grid(row=0, column=1, sticky="e")
        self.granularity = tkinter.StringVar(value="auto")
        for value, text in (("auto", "Auto"), ("day", "By Day"),
                            ("week", "By Week"), ("month", "By Month")):
            tb.Radiobutton(gran, text=text, value=value,
                           variable=self.granularity, style="Card.TRadiobutton",
                           command=lambda: self.render_filters(
                               self.filters)).pack(side="left", padx=4)
        self.by_wh = ChartPanel(charts, "Bad Order Reports by Warehouse")
        self.by_wh.grid(row=1, column=0, sticky="nsew", padx=(0, 10),
                        pady=(10, 0))
        self.split = ChartPanel(charts, "Good Order vs Bad Order")
        self.split.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        self.by_type = ChartPanel(charts, "Bad Order by Cargo Type",
                                  "Types of Goods ticked on the report")
        self.by_type.grid(row=2, column=0, columnspan=2, sticky="we",
                          pady=(10, 0))
        card = Card(self.main, "Bad Order Records",
                    "Case status is recorded here (it is not part of the "
                    "inspection report). 'Not recorded' cases are not "
                    "counted as unresolved.")
        card.grid(row=3, column=0, sticky="we", pady=(10, 0))
        self.table = DataTable(card.content, tbl.BAD_ORDER_COLUMNS, height=12,
                               on_select=self.selected,
                               on_open=lambda tx: self.ctx.open_report(
                                   tx.control_no), export=self.export)
        self.table.grid(row=0, column=0, sticky="we")
        buttons = ttk.Frame(card.content, style="CardPlain.TFrame")
        buttons.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.status_btn = tb.Button(buttons, text="Set Case Status...",
                                    bootstyle="warning", state="disabled",
                                    command=self.set_status)
        self.status_btn.pack(side="left")
        self.open_btn = tb.Button(buttons, text="Open Inspection Report",
                                  bootstyle="primary-outline",
                                  state="disabled",
                                  command=lambda: self.ctx.open_report(
                                      self.table.selected_object().control_no))
        self.open_btn.pack(side="left", padx=6)
        tb.Button(buttons, text="Export Bad Order Summary (PDF)",
                  bootstyle="info-outline",
                  command=lambda: ask_export(self.ctx, exports.bad_order_report(
                      self.snapshot, self.filters), "pdf")).pack(
            side="left", padx=(20, 0))
        tb.Button(buttons, text="Export Bad Order Summary (Excel)",
                  bootstyle="success-outline",
                  command=lambda: ask_export(self.ctx, exports.bad_order_report(
                      self.snapshot, self.filters), "xlsx")).pack(
            side="left", padx=6)

    def render(self, snapshot):
        fill_choices(self.bar, snapshot.transactions)
        self.bar._changed()

    def render_filters(self, filters):
        snap = self.snapshot
        if snap is None:
            return
        self.filters = filters
        statuses = snap.side.case_statuses()
        self.kpis.show(an.bad_order_kpis(snap.transactions, filters,
                                         statuses))
        bad = an.filter_transactions(snap.transactions, an.Filters(
            **{**filters.__dict__, "condition": BAD_ORDER}))
        wanted = self.bar.value("case_status")
        if wanted:
            bad = [t for t in bad if statuses.get(t.control_no, {}).get(
                "status", "Not recorded") == wanted]
        gran = self.granularity.get()
        series, used = an.trend(snap.transactions, filters.period,
                                None if gran == "auto" else gran,
                                condition=BAD_ORDER, filters=filters)
        self.trend.header.winfo_children()[0].configure(
            text=f"Bad Order Reports by {used.title()}")
        self.trend.trend([c for c, _ in series], [
            ("Bad Order reports", [v for _, v in series], "critical")],
            "Reports")
        b = an.bad_order_breakdowns(snap.transactions, filters)
        self.by_wh.bars([k for k, _ in b["warehouse"]], [(
            "Reports", [v for _, v in b["warehouse"]], "critical")],
            horizontal=True, value_label="Bad Order reports")
        split = an.good_vs_bad(snap.transactions, filters)
        self.split.bars(list(split), [("Reports", list(split.values()),
                                       None)], horizontal=True,
                        value_label="Inspection reports")
        _color_bars(self.split, ["good", "critical"])
        self.by_type.bars([k for k, _ in b["cargo_type"]], [(
            "Reports", [v for _, v in b["cargo_type"]], "critical")],
            horizontal=True, value_label="Bad Order reports")
        self.table.set_rows(tbl.bad_order_rows(bad, statuses), bad,
                            "No Bad Order reports for the selected "
                            "filters.")
        self.selected(None)

    def selected(self, tx):
        state = "normal" if tx is not None else "disabled"
        self.status_btn.configure(state=state)
        self.open_btn.configure(state=state)

    def set_status(self):
        tx = self.table.selected_object()
        if tx is None:
            return
        ask_case_status(self.ctx, self.snapshot.side, tx.control_no,
                        lambda: self.render_filters(self.filters))

    def export(self, kind):
        doc = exports.table_report(
            "Bad Order Records", self.filters.period.describe(),
            self.filters.describe(), tbl.BAD_ORDER_COLUMNS,
            self.table.visible_rows(), source=self.ctx.source_text())
        ask_export(self.ctx, doc, kind)
