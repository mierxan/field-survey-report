"""Dashboard, Receiving / Withdrawal Transactions and Incident Reports
Monitoring (the Bad Order reports)."""

import tkinter
from datetime import date, datetime, timedelta
from tkinter import ttk

import ttkbootstrap as tb

from warehouse import analytics as an
from warehouse import exports
from warehouse import periods as pr
from warehouse import tables as tbl
from warehouse.transactions import BAD_ORDER, RECEIVING, WITHDRAWAL

from . import theme
from .components import (Card, ChartPanel, DataTable, EmptyState, KpiGrid,
                         PeriodBar, ScrollPage, ask_export,
                         explain_load_error, fill_choices, section_label)
from .dialogs import DetailPanel, ask_case_status, line_pairs

DATE_FORMAT = "%d-%b-%Y"


class Page(ScrollPage):
    """A module page: header, then content built by render(snapshot)."""

    title = ""
    subtitle = ""
    neo = False             # the futuristic look (theme.NEO), as on the phone

    def __init__(self, parent, ctx, service):
        super().__init__(parent, neo=self.neo)
        self.ctx, self.service = ctx, service
        self.snapshot = None
        st = self.st = theme.styles(self.neo)
        head = ttk.Frame(self.body, style=st["page"])
        head.grid(row=0, column=0, sticky="we")
        head.columnconfigure(0, weight=1)
        subtitle = ttk.Label(head, text=self.subtitle,
                             style=st["page_muted"], justify="left")
        subtitle.grid(row=1, column=0, columnspan=3, sticky="w",
                      pady=(4, 0))
        head.bind("<Configure>", lambda e: subtitle.configure(
            wraplength=max(e.width - 10, 300)))
        self.source_label = ttk.Label(head, text="", style=st["page_muted"])
        self.source_label.grid(row=0, column=0, sticky="w")
        tb.Button(head, text="⟳ Refresh", bootstyle="secondary-outline",
                  command=self.reload).grid(row=0, column=2, sticky="e")
        self.state_holder = ttk.Frame(self.body, style=st["page"])
        self.state_holder.grid(row=1, column=0, sticky="we", pady=(10, 0))
        self.state_holder.columnconfigure(0, weight=1)
        self.main = ttk.Frame(self.body, style=st["page"])
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
        # Tk keeps an emptied frame at its last size, so the space of a
        # removed notice would stay as a blank band above the page: the
        # holder is shown only while it holds a notice.
        self.state_holder.grid_remove()
        self.snapshot = snapshot
        if error is not None:
            EmptyState(self.state_holder, "Records unavailable",
                       explain_load_error(error), "Try again",
                       self.reload).grid(row=0, column=0, sticky="we")
            self.state_holder.grid()
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
            self.state_holder.grid()
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
    neo = True

    def build(self):
        self.bar = PeriodBar(self.main, self.render_filters,
                             filters=("warehouse",), default="this_month",
                             neo=True)
        self.bar.grid(row=0, column=0, sticky="we")
        section_label(self.main, "Inspection reports - selected period", 1,
                      neo=True)
        # Total, Good Order, Bad Order, Bad Order %, Receiving, Withdrawal
        self.inspection = KpiGrid(self.main, neo=True)
        self.inspection.grid(row=2, column=0, sticky="we")
        section_label(self.main, "Visualization", 3, neo=True)
        charts = ttk.Frame(self.main, style=self.st["page"])
        charts.grid(row=4, column=0, sticky="we")
        for col in range(2):
            charts.columnconfigure(col, weight=1, uniform="ch")

        def chart(title, subtitle, accent, row, column, span=1, height=250):
            panel = ChartPanel(charts, title, subtitle, height=height,
                               neo=True, accent=accent)
            panel.grid(row=row, column=column, columnspan=span, sticky="nsew",
                       padx=(0, 10) if span == 1 and column == 0 else 0,
                       pady=(0, 10))
            return panel

        self.trend = chart("Overall Transactions",
                           "Receiving and Withdrawal transactions (reports) "
                           "per day / week / month of the period", "cyan",
                           0, 0, span=2, height=270)
        self.receiving = chart("Receiving Transactions",
                               "Receiving reports per day / week / month",
                               "green", 1, 0)
        self.withdrawal = chart("Withdrawal Transactions",
                                "Withdrawal reports per day / week / month",
                                "violet", 1, 1)
        self.status = chart("Warehouse Items / Cargo Status",
                            "Stored, Withdrawn: in the period  ·  In Stock: "
                            "left today, all dates", "blue", 2, 0)
        self.good_bad = chart("Incident Reports",
                              "Good Order and Incident (Bad Order) inspection "
                              "reports in the period", "red", 2, 1)
        self.aging = chart("Inventory Aging",
                           "Item List lines still in stock, all dates (a "
                           "fully withdrawn line is not counted; the "
                           "period does not apply)",
                           "amber", 3, 0, span=2)
        self.aging.on_bar_click = lambda index, bucket: self.show_aging(
            bucket)

        # the lines behind the Inventory Aging bars (click a bar)
        card = Card(charts, "Inventory Aging List",
                    "Click a bar of Inventory Aging to list its Item List "
                    "lines. Double-click a line to open its report.",
                    neo=True, accent="amber")
        card.grid(row=4, column=0, columnspan=2, sticky="we")
        self.aging_card = card
        head = ttk.Frame(card.content, style=self.st["plain"])
        head.grid(row=0, column=0, sticky="we", pady=(0, 6))
        head.columnconfigure(0, weight=1)
        self.aging_shown = ttk.Label(head, text="", style=self.st["title"])
        self.aging_shown.grid(row=0, column=0, sticky="w")
        self.aging_all_btn = tb.Button(
            head, text="Show All Ages", bootstyle="warning-outline",
            command=lambda: self.show_aging(None))
        self.aging_all_btn.grid(row=0, column=1, sticky="e")
        self.aging_table = DataTable(
            card.content, AGING_COLUMNS, height=10, neo=True,
            on_open=lambda row: self.ctx.open_report(
                row.batch.line.control_no))
        self.aging_table.grid(row=1, column=0, sticky="we")
        card.content.columnconfigure(0, weight=1)
        self.aging_bucket = None

    def show_aging(self, bucket):
        """List the in-stock lines of one aging group (None: every age)."""
        self.aging_bucket = bucket
        snap = self.snapshot
        if snap is None:
            return
        warehouse = self.bar.filters().warehouse
        rows = [r for r in _aging_lines(snap.inventory, warehouse)
                if bucket is None or r.bucket == bucket]
        rows.sort(key=lambda r: (-r.age_days, r.batch.line.line_id))
        self.aging_table.set_rows(
            [aging_row(r) for r in rows], rows,
            empty_text="No Item List lines in stock in this age group.")
        self.aging_shown.configure(
            text=f"{bucket or 'All ages'}  ·  {len(rows)} line"
                 f"{'s' if len(rows) != 1 else ''} in stock")
        self.aging_all_btn.configure(
            state="disabled" if bucket is None else "normal")

    def render(self, snapshot):
        fill_choices(self.bar, snapshot.transactions)
        self.bar._changed()

    def render_filters(self, filters):
        snap = self.snapshot
        if snap is None:
            return
        self.inspection.show(incident_names(
            an.inspection_kpis(snap.transactions, filters)))
        where = an.Filters(warehouse=filters.warehouse)
        series, gran = an.trend(snap.transactions, filters.period,
                                filters=where)
        rseries, _ = an.trend(snap.transactions, filters.period, gran,
                              activity=RECEIVING, filters=where)
        wseries, _ = an.trend(snap.transactions, filters.period, gran,
                              activity=WITHDRAWAL, filters=where)
        labels = [c for c, _ in series]
        received = [v for _, v in rseries]
        withdrawn = [v for _, v in wseries]
        self.trend.trend(labels, [("Receiving", received, "receiving"),
                                  ("Withdrawal", withdrawn, "withdrawal")],
                         "Transactions")
        self.receiving.trend(labels, [("Receiving", received, "receiving")],
                             "Transactions")
        self.withdrawal.trend(labels, [("Withdrawal", withdrawn,
                                        "withdrawal")], "Transactions")
        split = an.good_vs_bad(snap.transactions, filters)
        good, bad = split.get("Good Order", 0), split.get(BAD_ORDER, 0)
        share = f"Incident · {bad / (good + bad):.1%}" if good + bad \
            else "Incident"
        self.good_bad.donut(["Good Order", "Incident Reports"], [good, bad],
                            ["good", "critical"], an.fmt_number(bad), share)
        _line_items_chart(self.status, snap.transactions, filters,
                          snap.inventory)
        _aging_chart(self.aging, snap.inventory, filters.warehouse)
        self.show_aging(self.aging_bucket)


# On screen a Bad Order report is an Incident Report (the report's Cargo
# Condition stays "Bad Order": it is data the phone, the Excel files and the
# imports rely on). The exports keep their own names.
INCIDENT_NAMES = {
    "Bad Order Reports": "Incident Reports",
    "Bad Order Percentage": "Incident Report Percentage",
    "Total Bad Order Reports": "Total Incident Reports",
    "Bad Order Receiving Transactions": "Incident Reports - Receiving",
    "Bad Order Withdrawal Transactions": "Incident Reports - Withdrawal",
}


def incident_names(kpis, leave_out=()):
    """The KPIs with the Incident Report names; [leave_out]: names not shown."""
    import dataclasses
    return [dataclasses.replace(k, name=INCIDENT_NAMES.get(k.name, k.name))
            for k in kpis if k.name not in leave_out]


# the Inventory Aging List: (heading, kind, width in characters)
AGING_COLUMNS = (("Control Number", "text", 20), ("Date", "date", 13),
                 ("Line Item", "text", 14), ("Description", "text", 24),
                 ("PO", "text", 14), ("Qty in Stock", "qty", 15),
                 ("UOM", "text", 7), ("Age (Days)", "number", 12))


def aging_row(row):
    """One line of the Inventory Aging List (an AgingRow)."""
    from warehouse.inventory import line_numbers
    line = row.batch.line
    try:
        _, list_no, line_no = line_numbers(line.line_id)
        item = f"List {list_no} · Line {line_no}"
    except ValueError:
        item = line.line_id
    return (line.control_no, line.date, item, line.description,
            line.po_number, row.remaining, line.unit, row.age_days)


def _aging_lines(inventory, warehouse=""):
    """The Receiving lines (batches) still in stock today, all dates: what
    Inventory Aging counts."""
    return [r for r in inventory.aging_rows if not warehouse
            or an.norm_key(r.item.warehouse) == an.norm_key(warehouse)]


def _line_items_chart(panel, transactions, filters, inventory=None):
    """Warehouse Items / Cargo Status: the Item List lines of the period's
    Receiving reports (stored) and Withdrawal reports (withdrawn), and the
    lines still in stock today (all dates - the Inventory Aging total)."""
    def lines(activity):
        chosen = an.filter_transactions(transactions, an.Filters(
            **{**filters.__dict__, "activity": activity}))
        return len(an.lines_of(chosen))

    names = ["Total Line Items Stored", "Total Line Items Withdrawn"]
    values = [lines(RECEIVING), lines(WITHDRAWAL)]
    colors = ["receiving", "withdrawal"]
    if inventory is not None:
        names.append("Total Line Items In Stock")
        values.append(len(_aging_lines(inventory, filters.warehouse)))
        colors.append("warning")
    panel.bars(names, [("Line items", values, None)], horizontal=True,
               value_label="Item List lines")
    _color_bars(panel, colors)


def _color_bars(panel, tokens_):
    """Recolour a single-series bar chart per bar (status colours). In the
    Neo look each bar has a glow drawn first: bar i and glow i share a
    colour."""
    if panel.ax is None:
        return
    bars = [p for p in panel.ax.patches]
    for index, bar in enumerate(bars):
        color = panel.t[tokens_[index % len(tokens_)]]
        bar.set_facecolor(color)
        bar.set_edgecolor(color if panel.neo else panel.t["card"])
    panel.canvas.draw_idle()


def _status_chart(panel, inventory, warehouse=""):
    """The inventory items by status: a ring in the Neo look, else bars."""
    from .theme import STATUS_TONES
    items = [i for i in inventory.items if not warehouse
             or an.norm_key(i.warehouse) == an.norm_key(warehouse)]
    counts = {s: sum(1 for i in items if i.status == s)
              for s in STATUS_TONES}
    labels = {"In Stock": "In Stock (no withdrawal)"}
    if panel.neo:
        panel.donut([labels.get(s, s) for s in counts], list(counts.values()),
                    list(STATUS_TONES.values()), an.fmt_number(len(items)),
                    "cargo items")
        return
    panel.bars([labels.get(s, s) for s in counts],
               [("Items", list(counts.values()), None)], horizontal=True,
               value_label="Inventory items")
    _color_bars(panel, list(STATUS_TONES.values()))


def _aging_chart(panel, inventory, warehouse=""):
    from warehouse.inventory import bucket_labels
    rows = _aging_lines(inventory, warehouse)
    labels = bucket_labels(inventory.thresholds)
    counts = [sum(1 for r in rows if r.bucket == label) for label in labels]
    panel.bars(labels, [("Line items in stock", counts, None)],
               value_label="Item List lines in stock")
    if panel.ax is not None:
        ramp = panel.t["ramp"]
        for index, bar in enumerate(panel.ax.patches):
            color = ramp[(index % len(labels)) % len(ramp)]
            bar.set_facecolor(color)
            bar.set_edgecolor(color if panel.neo else panel.t["card"])
        panel.canvas.draw_idle()


# =====================================================
# RECEIVING / WITHDRAWAL TRANSACTIONS
# =====================================================

class TransactionsPage(Page):
    activity = RECEIVING
    neo = True

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
        neo = self.neo
        accent = "green" if self.activity == RECEIVING else "violet"
        tabs = ttk.Frame(self.main, style=self.st["page"])
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
        self.summary_view = ttk.Frame(self.main, style=self.st["page"])
        self.summary_view.columnconfigure(0, weight=1)
        picker = Card(self.summary_view, neo=neo)
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
        self.period_label = ttk.Label(row, text="", style=self.st["title"])
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
        self.kpis = KpiGrid(self.summary_view, neo=neo)
        self.kpis.grid(row=1, column=0, sticky="we", pady=(10, 0))
        mid = ttk.Frame(self.summary_view, style=self.st["page"])
        mid.grid(row=2, column=0, sticky="we")
        for col in range(2):
            mid.columnconfigure(col, weight=1, uniform="mid")
        self.breakdown_chart = ChartPanel(mid, "Breakdown", height=240,
                                          neo=neo, accent=accent)
        self.breakdown_chart.grid(row=0, column=0, sticky="nsew",
                                  padx=(0, 10))
        self.breakdowns = Card(mid, "Breakdowns and Comparison", neo=neo,
                               accent="cyan")
        self.breakdowns.grid(row=0, column=1, sticky="nsew")
        lines_card = Card(self.summary_view, "Transaction Lines",
                          "Double-click a line to open its inspection "
                          "report.", neo=neo)
        lines_card.grid(row=3, column=0, sticky="we", pady=(10, 0))
        self.summary_table = DataTable(lines_card.content, tbl.LINE_COLUMNS,
                                       height=10,
                                       on_open=self.open_line, neo=neo)
        self.summary_table.grid(row=0, column=0, sticky="we")

        # --- all transactions view ---
        self.all_view = ttk.Frame(self.main, style=self.st["page"])
        self.all_view.columnconfigure(0, weight=1)
        party = "supplier" if self.activity == RECEIVING else "consignee"
        self.bar = PeriodBar(self.all_view, self.render_all,
                             filters=("warehouse", party, "condition"),
                             default="this_month", with_search=True, neo=neo)
        self.bar.grid(row=0, column=0, sticky="we", pady=(10, 0))
        self.all_kpis = KpiGrid(self.all_view, neo=neo)
        self.all_kpis.grid(row=1, column=0, sticky="we", pady=(10, 0))
        table_card = Card(self.all_view, f"{self.activity} Cargo Lines",
                          "Click a column heading to sort. Double-click to "
                          "open the original inspection report.", neo=neo,
                          accent=accent)
        table_card.grid(row=2, column=0, sticky="we")
        self.all_table = DataTable(table_card.content, tbl.LINE_COLUMNS,
                                   height=14, on_select=self.show_line,
                                   on_open=self.open_line,
                                   export=self.export_all, neo=neo)
        self.all_table.grid(row=0, column=0, sticky="we")
        self.detail = DetailPanel(self.all_view, "Transaction Details",
                                  [("Open Inspection Report",
                                    self.open_selected, "primary")], neo=neo)
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
        # Total Transactions, Total Packages, Items Inspected (as on the phone)
        self.kpis.show(an.activity_kpis(
            summary.transactions,
            summary.previous.transactions if summary.previous else None,
            summary.period.describe()))
        kind = self.mode.get()
        if kind == "daily":
            groups = summary.by_warehouse
            self.breakdown_chart.title_label.configure(
                text="●  Transactions by Warehouse")
            self.breakdown_chart.bars([g[0] for g in groups], [
                ("Transactions", [g[1] for g in groups],
                 self.activity.lower())], horizontal=True,
                value_label="Transactions")
        else:
            data = summary.by_day if kind == "weekly" else summary.by_week
            labels = [pr.bucket_label(d, "day" if kind == "weekly"
                                      else "week") for d in data]
            self.breakdown_chart.title_label.configure(
                text="●  Daily Breakdown" if kind == "weekly"
                else "●  Weekly Breakdown")
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

        st = self.st

        def block(title, pairs):
            nonlocal row
            ttk.Label(content, text=("◆ " if self.neo else "") + title,
                      style="NeoAccentCyan.TLabel" if self.neo
                      else st["kpi_name"]).grid(
                row=row, column=0, columnspan=4, sticky="w", pady=(8, 3))
            row += 1
            if not pairs:
                ttk.Label(content, text="None", style=st["muted"]
                          ).grid(row=row, column=0, sticky="w")
                row += 1
            for values in pairs[:8]:
                for col, value in enumerate(values):
                    text = str(value)
                    label = ttk.Label(content, text=text, style=st["label"]
                                      if col == 0 else st["muted"])
                    if self.neo and col == 3:
                        # the change: green up, red down
                        label.configure(foreground=theme.NEO[
                            "green" if text.startswith("+") else "red"
                            if text.startswith("-") else "text_muted"])
                    label.grid(row=row, column=col, sticky="w", padx=(0, 14))
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
        # Total Transactions, Total Packages, Items Inspected (as on the phone)
        self.all_kpis.show(an.activity_kpis(
            chosen, period_label=filters.period.describe()))
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
# INCIDENT REPORTS MONITORING (Bad Order reports)
# =====================================================

class BadOrderPage(Page):
    title = "Incident Reports Monitoring"
    subtitle = ("Incident Reports: the inspection reports with Cargo "
                "Condition Bad Order. The cargo of an Incident Report stays "
                "in the inventory (no rule excludes it).")
    neo = True

    MONTH_COLUMNS = (("Report Control #", 150), ("Inspection Date", 105),
                     ("Activity", 85), ("Warehouse / Location", 190),
                     ("Supplier / Consignee", 190), ("SO Number", 120),
                     ("Case Status", 110))
    # the cards the page does not show (they stay in the exports)
    LEFT_OUT = ("Affected Cargo Lines", "Unresolved Bad Order Cases")

    def build(self):
        self.filters = None
        self.bar = PeriodBar(self.main, self.render_filters,
                             filters=("warehouse", "activity", "supplier",
                                      "consignee", "case_status"),
                             default="this_year", with_search=True, neo=True)
        self.bar.grid(row=0, column=0, sticky="we")
        self.kpis = KpiGrid(self.main, neo=True)
        self.kpis.grid(row=1, column=0, sticky="we", pady=(10, 0))
        charts = ttk.Frame(self.main, style=self.st["page"])
        charts.grid(row=2, column=0, sticky="we")
        for col in range(2):
            charts.columnconfigure(col, weight=1, uniform="bo")
        self.trend = ChartPanel(charts, "Incident Reports over Time",
                                neo=True, accent="red")
        self.trend.grid(row=0, column=0, columnspan=2, sticky="we")
        gran = ttk.Frame(self.trend.header, style=self.st["plain"])
        gran.grid(row=0, column=1, sticky="e")
        self.granularity = tkinter.StringVar(value="auto")
        for value, text in (("auto", "Auto"), ("day", "By Day"),
                            ("week", "By Week"), ("month", "By Month")):
            tb.Radiobutton(gran, text=text, value=value,
                           variable=self.granularity,
                           style=self.st["radio"],
                           command=lambda: self.render_filters(
                               self.filters)).pack(side="left", padx=4)
        self.by_wh = ChartPanel(charts, "Incident Reports by Warehouse",
                                neo=True, accent="amber")
        self.by_wh.grid(row=1, column=0, sticky="nsew", padx=(0, 10),
                        pady=(10, 0))
        self.split = ChartPanel(charts, "Good Order vs Incident Reports",
                                neo=True, accent="green")
        self.split.grid(row=1, column=1, sticky="nsew", pady=(10, 0))

        # per month: a chart and the reports of each month
        section_label(self.main, "Incident Reports per month", 3, neo=True)
        self.per_month = ChartPanel(self.main, "Incident Reports per Month",
                                    "Each month of the selected period",
                                    neo=True, accent="red", height=230)
        self.per_month.grid(row=4, column=0, sticky="we")
        month_card = Card(self.main, "Incident Reports by Month",
                          "Click a month to open or close it. Double-click a "
                          "report to open it; select one to set its case "
                          "status.", neo=True, accent="red")
        month_card.grid(row=5, column=0, sticky="we", pady=(10, 0))
        holder = ttk.Frame(month_card.content, style=self.st["plain"])
        holder.grid(row=0, column=0, sticky="we")
        holder.columnconfigure(0, weight=1)
        self.months = ttk.Treeview(
            holder, columns=[f"c{i}" for i in range(len(self.MONTH_COLUMNS))],
            show="tree headings", height=14, selectmode="browse",
            style=self.st["tree"])
        self.months.heading("#0", text="Month")
        self.months.column("#0", width=250, minwidth=180, stretch=False)
        for index, (heading, width) in enumerate(self.MONTH_COLUMNS):
            self.months.heading(f"c{index}", text=heading)
            self.months.column(f"c{index}", width=width, minwidth=60,
                               stretch=heading.startswith(("Warehouse",
                                                           "Supplier")))
        self.months.tag_configure("month", foreground=theme.NEO["red"],
                                  font=(theme.FONT, 9, "bold"))
        vsb = ttk.Scrollbar(holder, orient="vertical",
                            command=self.months.yview)
        self.months.configure(yscrollcommand=vsb.set)
        self.months.grid(row=0, column=0, sticky="we")
        vsb.grid(row=0, column=1, sticky="ns")
        self.months.bind("<Double-1>", self._open_month_report)
        self.months.bind("<<TreeviewSelect>>",
                         lambda e: self.selected(self.chosen()))
        self.month_reports = {}             # tree item -> transaction
        buttons = ttk.Frame(month_card.content, style=self.st["plain"])
        buttons.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.status_btn = tb.Button(buttons, text="Set Case Status...",
                                    bootstyle="warning", state="disabled",
                                    command=self.set_status)
        self.status_btn.pack(side="left")
        self.open_btn = tb.Button(buttons, text="Open Inspection Report",
                                  bootstyle="primary-outline",
                                  state="disabled",
                                  command=lambda: self.ctx.open_report(
                                      self.chosen().control_no))
        self.open_btn.pack(side="left", padx=6)
        tb.Button(buttons, text="Export Incident Report Summary (PDF)",
                  bootstyle="info-outline",
                  command=lambda: ask_export(self.ctx, exports.bad_order_report(
                      self.snapshot, self.filters), "pdf")).pack(
            side="left", padx=(20, 0))
        tb.Button(buttons, text="Export Incident Report Summary (Excel)",
                  bootstyle="success-outline",
                  command=lambda: ask_export(self.ctx, exports.bad_order_report(
                      self.snapshot, self.filters), "xlsx")).pack(
            side="left", padx=6)

    def render(self, snapshot):
        fill_choices(self.bar, snapshot.transactions)
        self.bar._changed()

    def reports(self, filters):
        """The Incident (Bad Order) reports of the filters and Case Status."""
        snap = self.snapshot
        statuses = snap.side.case_statuses()
        bad = an.filter_transactions(snap.transactions, an.Filters(
            **{**filters.__dict__, "condition": BAD_ORDER}))
        wanted = self.bar.value("case_status")
        if wanted:
            bad = [t for t in bad if statuses.get(t.control_no, {}).get(
                "status", "Not recorded") == wanted]
        return bad, statuses

    def render_filters(self, filters):
        snap = self.snapshot
        if snap is None or filters is None:
            return
        self.filters = filters
        bad, statuses = self.reports(filters)
        self.kpis.show(incident_names(
            an.bad_order_kpis(snap.transactions, filters, statuses),
            leave_out=self.LEFT_OUT))
        gran = self.granularity.get()
        series, used = an.trend(snap.transactions, filters.period,
                                None if gran == "auto" else gran,
                                condition=BAD_ORDER, filters=filters)
        self.trend.title_label.configure(
            text=f"●  Incident Reports by {used.title()}")
        self.trend.trend([c for c, _ in series], [
            ("Incident Reports", [v for _, v in series], "critical")],
            "Reports")
        b = an.bad_order_breakdowns(snap.transactions, filters)
        self.by_wh.bars([k for k, _ in b["warehouse"]], [(
            "Reports", [v for _, v in b["warehouse"]], "warning")],
            horizontal=True, value_label="Incident Reports")
        split = an.good_vs_bad(snap.transactions, filters)
        good, bad_count = split.get("Good Order", 0), split.get(BAD_ORDER, 0)
        share = f"Incident · {bad_count / (good + bad_count):.1%}" \
            if good + bad_count else "Incident"
        self.split.donut(["Good Order", "Incident Reports"],
                         [good, bad_count], ["good", "critical"],
                         an.fmt_number(bad_count), share)
        months, _ = an.trend(snap.transactions, filters.period, "month",
                             condition=BAD_ORDER, filters=filters)
        self.per_month.bars([c for c, _ in months], [(
            "Incident Reports", [v for _, v in months], "critical")],
            value_label="Incident Reports")
        self._fill_months(bad, statuses)
        self.selected(None)

    def _fill_months(self, bad, statuses):
        """The Incident Reports grouped by month, the latest month open."""
        tree = self.months
        tree.delete(*tree.get_children())
        self.month_reports = {}
        groups = an.bad_order_by_month(bad)
        if not groups:
            tree.insert("", "end", text="No Incident Reports for the "
                        "selected filters.", values=[""] * len(
                            self.MONTH_COLUMNS))
            return
        for index, (month, reports) in enumerate(groups):
            name = month.strftime("%B %Y") if month else "No date"
            count = len(reports)
            parent = tree.insert("", "end", open=index == 0, tags=("month",),
                                 text=f"{name}  ·  {count} "
                                      f"report{'s' if count != 1 else ''}",
                                 values=[""] * len(self.MONTH_COLUMNS))
            for tx in reports:
                party = tx.supplier if tx.activity == RECEIVING \
                    else tx.consignee
                item = tree.insert(parent, "end", text="", values=[
                    tx.control_no,
                    tx.date.strftime(DATE_FORMAT) if tx.date else tx.date_text,
                    tx.activity, tx.warehouse, party or "", tx.so_number,
                    statuses.get(tx.control_no, {}).get("status",
                                                        "Not recorded")])
                self.month_reports[item] = tx

    def chosen(self):
        """The report selected in the month list (None: a month or nothing)."""
        selection = self.months.selection()
        return self.month_reports.get(selection[0]) if selection else None

    def _open_month_report(self, event):
        tx = self.month_reports.get(self.months.identify_row(event.y))
        if tx is not None:
            self.ctx.open_report(tx.control_no)

    def selected(self, tx):
        state = "normal" if tx is not None else "disabled"
        self.status_btn.configure(state=state)
        self.open_btn.configure(state=state)

    def set_status(self):
        tx = self.chosen()
        if tx is None:
            return
        ask_case_status(self.ctx, self.snapshot.side, tx.control_no,
                        lambda: self.render_filters(self.filters))
