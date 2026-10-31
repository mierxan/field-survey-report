"""Reusable widgets of the warehouse pages.

    Card, KpiCard / KpiGrid, EmptyState, StatusBadge text
    PeriodBar        period selector (+ custom date range) and filters
    DataTable        sortable, searchable, paged Treeview + export
    ChartPanel       an embedded Matplotlib chart with hover read-out
    ScrollPage       a vertically scrolling page
    DataService      loads the records in the background, caches them
"""

import threading
import tkinter
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

import ttkbootstrap as tb

from warehouse import analytics as an
from warehouse import periods as pr
from warehouse import tables as tbl

from . import theme

DATE_FORMAT = "%d-%b-%Y"


# =====================================================
# layout pieces
# =====================================================

class ScrollPage(ttk.Frame):
    """A page that scrolls vertically; put widgets into `.body`."""

    instances = []

    def __init__(self, parent):
        super().__init__(parent, style="Page.TFrame")
        self.canvas = tkinter.Canvas(self, highlightthickness=0, bd=0,
                                     yscrollincrement=20)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, style="Page.TFrame",
                              padding=(20, 14, 20, 20))
        self.body.columnconfigure(0, weight=1)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))
        ScrollPage.instances.append(self)
        self.apply_theme()

    def apply_theme(self):
        try:
            self.canvas.configure(background=theme.tokens(tb.Style())["page"])
        except tkinter.TclError:
            pass

    def scroll(self, direction):
        if self.body.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(direction * 3, "units")


def on_page_wheel(event):
    """Mouse wheel over a ScrollPage scrolls it (tables scroll themselves)."""
    try:
        widget = event.widget
        if isinstance(widget, str):
            return
        target = widget
        while target is not None:
            if isinstance(target, (ttk.Treeview, tkinter.Listbox,
                                   tkinter.Text)):
                return
            if isinstance(target, ScrollPage):
                if event.num == 4:
                    direction = -1
                elif event.num == 5:
                    direction = 1
                else:
                    direction = -1 if event.delta > 0 else 1
                target.scroll(direction)
                return
            target = getattr(target, "master", None)
    except (tkinter.TclError, AttributeError, KeyError):
        pass


class Card(ttk.Frame):
    """A white content panel with an optional title row."""

    def __init__(self, parent, title=None, subtitle=None, padding=14):
        super().__init__(parent, style="Card.TFrame", padding=padding)
        self.columnconfigure(0, weight=1)
        self.header = None
        if title:
            self.header = ttk.Frame(self, style="CardPlain.TFrame")
            self.header.grid(row=0, column=0, sticky="we", pady=(0, 8))
            self.header.columnconfigure(0, weight=1)
            ttk.Label(self.header, text=title, style="CardTitle.TLabel").grid(
                row=0, column=0, sticky="w")
            if subtitle:
                self.subtitle = ttk.Label(self.header, text=subtitle,
                                          style="CardMuted.TLabel",
                                          wraplength=900, justify="left")
                self.subtitle.grid(row=1, column=0, sticky="w")
        self.content = ttk.Frame(self, style="CardPlain.TFrame")
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)


def section_label(parent, text, row, pady=(16, 6)):
    label = ttk.Label(parent, text=text.upper(), style="PageMuted.TLabel",
                      font=(theme.FONT, 9, "bold"))
    label.grid(row=row, column=0, sticky="w", pady=pady)
    return label


class KpiCard(ttk.Frame):
    """Metric name, value, what it counts, period and comparison."""

    TONES = {"success": "good", "danger": "critical", "warning": "warning",
             "primary": "receiving"}

    def __init__(self, parent, kpi):
        super().__init__(parent, style="Card.TFrame", padding=(0, 0, 12, 10))
        self.columnconfigure(1, weight=1)
        tone = self.TONES.get(kpi.tone, "receiving")
        ttk.Frame(self, style=f"Kpi{tone.title()}.TFrame", width=4).grid(
            row=0, column=0, rowspan=5, sticky="ns", padx=(0, 10))
        self.texts = [ttk.Label(self, text=kpi.name, style="KpiName.TLabel")]
        self.texts[0].grid(row=0, column=1, sticky="w", pady=(10, 0))
        long = len(kpi.display) > 14
        self.texts.append(ttk.Label(
            self, text=kpi.display, justify="left",
            style="KpiValueSmall.TLabel" if long else "KpiValue.TLabel"))
        self.texts[1].grid(row=1, column=1, sticky="w", pady=(2, 0))
        detail = kpi.unit
        if kpi.period:
            detail = f"{detail}\n{kpi.period}" if detail else kpi.period
        self.texts.append(ttk.Label(self, text=detail,
                                    style="CardMuted.TLabel",
                                    justify="left"))
        self.texts[2].grid(row=2, column=1, sticky="w")
        for row, text in ((3, kpi.comparison), (4, kpi.note)):
            if text:
                label = ttk.Label(self, text=text, style="CardMuted.TLabel",
                                  justify="left",
                                  foreground=theme.tokens(tb.Style())["text"]
                                  if row == 3 else None)
                label.grid(row=row, column=1, sticky="w", pady=(3, 0))
                self.texts.append(label)
        self._wrap = 0
        self.bind("<Configure>", self._fit)

    def _fit(self, event):
        """Wrap every text to the card's real width (cards re-flow)."""
        wrap = max(event.width - 30, 80)
        if wrap != self._wrap:
            self._wrap = wrap
            for label in self.texts:
                label.configure(wraplength=wrap)


class KpiGrid(ttk.Frame):
    """KPI cards in a grid that re-flows with the window width."""

    MIN_WIDTH = 230

    def __init__(self, parent):
        super().__init__(parent, style="Page.TFrame")
        self.cards = []
        self._columns = 0
        self.bind("<Configure>", self._reflow)

    def show(self, kpis):
        for card in self.cards:
            card.destroy()
        self.cards = [KpiCard(self, k) for k in kpis]
        self._columns = 0
        self._reflow()

    def _reflow(self, event=None):
        width = self.winfo_width() if event is None else event.width
        columns = max(1, min(len(self.cards) or 1,
                             max(width, 1) // self.MIN_WIDTH))
        if columns == self._columns and event is not None:
            return
        self._columns = columns
        for col in range(8):
            self.columnconfigure(col, weight=1 if col < columns else 0,
                                 uniform="kpi" if col < columns else "")
        for index, card in enumerate(self.cards):
            card.grid(row=index // columns, column=index % columns,
                      sticky="nsew", padx=(0, 10), pady=(0, 10))


class EmptyState(ttk.Frame):
    def __init__(self, parent, title, message, action_text=None,
                 action=None):
        super().__init__(parent, style="Card.TFrame", padding=30)
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text=title, style="CardTitle.TLabel",
                  font=(theme.FONT, 13, "bold")).grid(row=0, column=0,
                                                      pady=(10, 6))
        ttk.Label(self, text=message, style="CardMuted.TLabel",
                  font=(theme.FONT, 10), wraplength=640,
                  justify="center").grid(row=1, column=0)
        if action_text and action:
            tb.Button(self, text=action_text, bootstyle="primary",
                      command=action).grid(row=2, column=0, pady=(14, 4))


def status_text(status):
    """Status badge text: a symbol + the status (never colour alone)."""
    symbols = {"In Stock": "●", "Partially Withdrawn": "◐",
               "Fully Withdrawn": "○", "Over-Withdrawn": "▲",
               "Reconciliation Required": "!"}
    for key, symbol in symbols.items():
        if str(status).startswith(key):
            return f"{symbol} {status}"
    return str(status)


# =====================================================
# period selector + filters
# =====================================================

class PeriodBar(ttk.Frame):
    """Period choice (+ custom range) and optional filter drop-downs.
    on_change(filters) runs when anything changes."""

    def __init__(self, parent, on_change, filters=("warehouse",),
                 default="this_month", with_search=False):
        super().__init__(parent, style="Card.TFrame", padding=(12, 10))
        self.on_change = on_change
        self.period_var = tkinter.StringVar(value=pr.PERIOD_LABELS[default])
        self.combos = {}
        self.fields = []                # field frames, re-flowed to fit
        self.flow = ttk.Frame(self, style="CardPlain.TFrame")
        self.flow.grid(row=0, column=0, sticky="we")
        self.columnconfigure(0, weight=1)
        self._flow_width = 0
        self.bind("<Configure>", self._reflow)

        field = self._field("Reporting period")
        self.period_combo = tb.Combobox(
            field, textvariable=self.period_var, state="readonly", width=17,
            values=[label for _, label in pr.PERIOD_CHOICES])
        self.period_combo.no_dirty = True
        self.period_combo.pack(anchor="w")
        self.period_combo.bind("<<ComboboxSelected>>", self._period_chosen)
        self.custom = self._field("Custom range (dd-MMM-yyyy)")
        holder = ttk.Frame(self.custom, style="CardPlain.TFrame")
        holder.pack(anchor="w")
        self.start_entry = tb.DateEntry(holder, dateformat=DATE_FORMAT,
                                        firstweekday=0, width=12)
        self.end_entry = tb.DateEntry(holder, dateformat=DATE_FORMAT,
                                      firstweekday=0, width=12)
        self.start_entry.pack(side="left")
        ttk.Label(holder, text=" to ", style="Card.TLabel").pack(side="left")
        self.end_entry.pack(side="left")
        tb.Button(holder, text="Apply", bootstyle="primary-outline",
                  command=self._changed).pack(side="left", padx=(6, 0))
        labels = {"warehouse": "Warehouse", "supplier": "Supplier",
                  "consignee": "Consignee", "condition": "Cargo Condition",
                  "activity": "Transaction Type", "cargo_type": "Cargo Type",
                  "case_status": "Case Status"}
        for name in filters:
            field = self._field(labels[name])
            combo = tb.Combobox(field, state="readonly", width=24 if name in (
                "warehouse", "supplier", "consignee") else 15,
                values=["All"])
            combo.set("All")
            combo.no_dirty = True
            combo.pack(anchor="w")
            combo.bind("<<ComboboxSelected>>", self._changed)
            self.combos[name] = combo
        self.search_var = tkinter.StringVar()
        if with_search:
            field = self._field("Search (SO, Control #, Cargo ID, "
                                "description...)")
            entry = tb.Entry(field, textvariable=self.search_var, width=30)
            entry.pack(anchor="w")
            entry.bind("<Return>", self._changed)
            self._after = None
            self.search_var.trace_add("write", self._search_typed)
        self.range_label = ttk.Label(self, text="", style="CardMuted.TLabel")
        self.range_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._show_custom()

    def _field(self, label):
        frame = ttk.Frame(self.flow, style="CardPlain.TFrame")
        ttk.Label(frame, text=label, style="CardMuted.TLabel").pack(
            anchor="w")
        self.fields.append(frame)
        return frame

    def _reflow(self, event=None):
        """Place the fields left to right, wrapping to a new row when the
        bar is too narrow (nothing is ever cut off)."""
        width = max(self.winfo_width() - 24, 200)
        if event is not None and width == self._flow_width:
            return
        self._flow_width = width
        row = col = used = 0
        for frame in self.fields:
            if frame is self.custom and not self._custom_on:
                frame.grid_remove()
                continue
            need = frame.winfo_reqwidth() + 12
            if col and used + need > width:
                row, col, used = row + 1, 0, 0
            frame.grid(row=row, column=col, sticky="nw", padx=(0, 12),
                       pady=(0, 4))
            col += 1
            used += need

    def _search_typed(self, *_):
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(350, self._changed)

    def _period_key(self):
        label = self.period_var.get()
        return next(k for k, v in pr.PERIOD_CHOICES if v == label)

    def _show_custom(self):
        self._custom_on = self._period_key() == "custom"
        self._reflow()

    def _period_chosen(self, event=None):
        self._show_custom()
        if self._period_key() != "custom":
            self._changed()

    def set_choices(self, name, values):
        combo = self.combos.get(name)
        if combo is None:
            return
        current = combo.get()
        combo.configure(values=["All"] + list(values))
        if current not in values:
            combo.set("All")

    def value(self, name):
        combo = self.combos.get(name)
        if combo is None or combo.get() == "All":
            return ""
        return combo.get()

    def period(self):
        key = self._period_key()
        if key == "custom":
            start = _parse(self.start_entry.entry.get())
            end = _parse(self.end_entry.entry.get())
            return pr.period_for("custom", custom=(start, end))
        return pr.period_for(key)

    def filters(self):
        return an.Filters(period=self.period(),
                          warehouse=self.value("warehouse"),
                          supplier=self.value("supplier"),
                          consignee=self.value("consignee"),
                          condition=self.value("condition"),
                          activity=self.value("activity"),
                          cargo_type=self.value("cargo_type"),
                          search=self.search_var.get().strip())

    def _changed(self, *_):
        try:
            filters = self.filters()
        except ValueError as error:
            self.range_label.configure(text=f"⚠ {error}",
                                       foreground=theme.tokens(
                                           tb.Style())["critical"])
            return
        self.range_label.configure(
            text=f"Showing: {filters.period.describe()}",
            foreground=theme.tokens(tb.Style())["text_muted"])
        self.on_change(filters)


def _parse(text):
    try:
        return datetime.strptime(text.strip(), DATE_FORMAT).date()
    except ValueError:
        return None


def fill_choices(bar, transactions):
    bar.set_choices("warehouse", an.distinct_values(transactions,
                                                    "warehouse"))
    bar.set_choices("supplier", an.distinct_values(transactions, "supplier"))
    bar.set_choices("consignee", an.distinct_values(transactions,
                                                    "consignee"))
    bar.set_choices("condition", ["Good Order", "Bad Order"])
    bar.set_choices("activity", ["Receiving", "Withdrawal"])
    bar.set_choices("cargo_type", an.cargo_types(transactions))
    bar.set_choices("case_status", ["Open", "Under Review", "Resolved",
                                    "Not recorded"])


# =====================================================
# table
# =====================================================

class DataTable(ttk.Frame):
    """Sortable / searchable / paged table. set_rows(rows, objects) - the
    objects (lines, items, issues...) come back in on_select / on_open."""

    PAGE = 500

    def __init__(self, parent, columns, height=12, on_select=None,
                 on_open=None, export=None, search=True, title_for_export=""):
        super().__init__(parent, style="CardPlain.TFrame")
        self.columns = columns
        self.on_select = on_select
        self.on_open = on_open
        self.export_cb = export
        self.title_for_export = title_for_export
        self.all_rows, self.objects, self.view = [], [], []
        self.page = 0
        self.sort_col, self.sort_reverse = None, False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, style="CardPlain.TFrame")
        top.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 6))
        top.columnconfigure(1, weight=1)
        self.search_var = tkinter.StringVar()
        if search:
            ttk.Label(top, text="Find in table:", style="CardMuted.TLabel"
                      ).grid(row=0, column=0, sticky="w", padx=(0, 6))
            entry = tb.Entry(top, textvariable=self.search_var, width=28)
            entry.grid(row=0, column=1, sticky="w")
            self.search_var.trace_add("write", lambda *_: self._apply())
        self.count_label = ttk.Label(top, text="", style="CardMuted.TLabel")
        self.count_label.grid(row=0, column=2, sticky="e", padx=8)
        self.prev_btn = tb.Button(top, text="‹ Prev", width=7,
                                  bootstyle="secondary-outline",
                                  command=lambda: self._page(-1))
        self.next_btn = tb.Button(top, text="Next ›", width=7,
                                  bootstyle="secondary-outline",
                                  command=lambda: self._page(1))
        self.prev_btn.grid(row=0, column=3)
        self.next_btn.grid(row=0, column=4, padx=(4, 0))
        if export:
            tb.Button(top, text="Export Excel", bootstyle="success-outline",
                      command=lambda: export("xlsx")).grid(row=0, column=5,
                                                          padx=(10, 0))
            tb.Button(top, text="Export PDF", bootstyle="info-outline",
                      command=lambda: export("pdf")).grid(row=0, column=6,
                                                         padx=(4, 0))

        ids = [f"c{i}" for i in range(len(columns))]
        self.tree = ttk.Treeview(self, columns=ids, show="headings",
                                 height=height, selectmode="browse")
        for cid, (heading, kind, width) in zip(ids, columns):
            self.tree.heading(cid, text=heading,
                              command=lambda c=cid: self._sort(c))
            self.tree.column(cid, width=max(int(width * 7.5), 60),
                             minwidth=50, stretch=kind == "text"
                             and width >= 24,
                             anchor="e" if kind in ("qty", "number")
                             else "w")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal",
                            command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")
        hsb.grid(row=2, column=0, sticky="we")
        self.tree.tag_configure("odd", background=theme.tokens(
            tb.Style())["page"])
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Double-1>", self._double)
        self.tree.bind("<Return>", lambda e: self._open_selected())
        self.empty_text = "No records for the selected filters."

    def set_rows(self, rows, objects=None, empty_text=None):
        self.all_rows = list(rows)
        self.objects = list(objects) if objects is not None else \
            [None] * len(self.all_rows)
        if empty_text:
            self.empty_text = empty_text
        self.page = 0
        self._apply()

    def _apply(self):
        query = self.search_var.get().strip().casefold()
        pairs = list(zip(self.all_rows, self.objects))
        if query:
            pairs = [(r, o) for r, o in pairs if query in " ".join(
                tbl.cell_text(v, c[1]) for v, c in zip(r, self.columns)
            ).casefold()]
        if self.sort_col is not None:
            index = int(self.sort_col[1:])

            def key(pair):
                value = pair[0][index]
                if value is None or value == "":
                    return (1, "")
                if isinstance(value, (int, float)):
                    return (0, value)
                if isinstance(value, (date, datetime)):
                    return (0, value.toordinal())
                return (0, str(value).casefold())
            try:
                pairs.sort(key=key, reverse=self.sort_reverse)
            except TypeError:
                pairs.sort(key=lambda p: str(p[0][index]),
                           reverse=self.sort_reverse)
        self.view = pairs
        pages = max(1, -(-len(pairs) // self.PAGE))
        self.page = min(self.page, pages - 1)
        self._render()

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        start = self.page * self.PAGE
        chunk = self.view[start:start + self.PAGE]
        for n, (row, _) in enumerate(chunk):
            self.tree.insert("", "end", iid=str(start + n), values=[
                status_text(v) if c[0] in ("Inventory Status", "Item Status")
                else tbl.cell_text(v, c[1])
                for v, c in zip(row, self.columns)],
                tags=("odd",) if n % 2 else ())
        total = len(self.view)
        pages = max(1, -(-total // self.PAGE))
        if total == 0:
            text = self.empty_text
        elif pages > 1:
            text = (f"{start + 1}-{start + len(chunk)} of {total} rows "
                    f"(page {self.page + 1}/{pages})")
        else:
            text = f"{total} row(s)"
        if total != len(self.all_rows):
            text += f"  ·  filtered from {len(self.all_rows)}"
        self.count_label.configure(text=text)
        self.prev_btn.configure(state="normal" if self.page > 0
                                else "disabled")
        self.next_btn.configure(state="normal" if self.page < pages - 1
                                else "disabled")

    def _page(self, step):
        self.page += step
        self._render()

    def _sort(self, cid):
        if self.sort_col == cid:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col, self.sort_reverse = cid, False
        for i, (heading, _, _) in enumerate(self.columns):
            arrow = ""
            if f"c{i}" == cid:
                arrow = " ▼" if self.sort_reverse else " ▲"
            self.tree.heading(f"c{i}", text=heading + arrow)
        self._apply()

    def selected_object(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return self.view[int(selection[0])][1]

    def _selected(self, event=None):
        if self.on_select:
            self.on_select(self.selected_object())

    def _double(self, event):
        if self.tree.identify_region(event.x, event.y) == "cell":
            self._open_selected()

    def _open_selected(self):
        obj = self.selected_object()
        if obj is not None and self.on_open:
            self.on_open(obj)

    def visible_rows(self):
        """The rows as filtered / sorted on screen (for exports)."""
        return [row for row, _ in self.view]


# =====================================================
# charts
# =====================================================

_mpl = {}


def _matplotlib():
    if not _mpl:
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        _mpl.update(Figure=Figure, Canvas=FigureCanvasTkAgg)
    return _mpl


class ChartPanel(Card):
    """A titled chart card. One measure per chart, one y-axis, a legend for
    two or more series, values read out on hover."""

    def __init__(self, parent, title, subtitle=None, height=250):
        super().__init__(parent, title, subtitle, padding=12)
        mpl = _matplotlib()
        scaling = float(self.tk.call("tk", "scaling"))
        self.figure = mpl["Figure"](figsize=(5, height / 96), dpi=72 * scaling,
                                    layout="constrained")
        self.canvas = mpl["Canvas"](self.figure, master=self.content)
        widget = self.canvas.get_tk_widget()
        widget.configure(height=height, highlightthickness=0, bd=0)
        widget.grid(row=0, column=0, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.ax = None
        self.hover = []                 # (artist, text)
        self.note = None
        self.canvas.mpl_connect("motion_notify_event", self._motion)

    def _start(self):
        t = theme.tokens(tb.Style())
        self.t = t
        self.figure.clear()
        self.figure.set_facecolor(t["card"])
        self.ax = self.figure.add_subplot(111)
        ax = self.ax
        ax.set_facecolor(t["card"])
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(t["grid"])
        ax.tick_params(colors=t["text_muted"], labelsize=8, length=0)
        ax.grid(axis="y", color=t["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        self.hover = []
        self.note = ax.annotate("", (0, 0), xytext=(8, 8),
                                textcoords="offset points", fontsize=8,
                                color=t["text"], zorder=10,
                                bbox=dict(boxstyle="round,pad=0.4",
                                          fc=t["card"], ec=t["card_border"]))
        self.note.set_visible(False)
        return ax

    def empty(self, message="No records for the selected filters."):
        ax = self._start()
        ax.set_axis_off()
        ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=9,
                color=self.t["text_muted"], transform=ax.transAxes,
                wrap=True)
        self.canvas.draw_idle()

    def bars(self, categories, series, horizontal=False, value_label="",
             fmt=an.fmt_number, label_values=True):
        """series: [(name, values, colour token or hex)]."""
        if not categories or not any(any(v for v in vals)
                                     for _, vals, _ in series):
            self.empty()
            return
        ax = self._start()
        n = len(series)
        width = 0.7 / n if n > 1 else 0.6
        positions = range(len(categories))
        many = len(categories) * n > 24
        for index, (name, values, color) in enumerate(series):
            color = self.t.get(color, color)
            offsets = [p + (index - (n - 1) / 2) * width for p in positions]
            draw = ax.barh if horizontal else ax.bar
            bars = draw(offsets, values, width * 0.92, color=color,
                        label=name, edgecolor=self.t["card"], linewidth=1)
            for bar, cat, value in zip(bars, categories, values):
                self.hover.append((bar, f"{cat}\n{name}: {fmt(value)}"))
            if label_values and not many:
                ax.bar_label(bars, labels=[fmt(v) if v else "" for v in
                                           values],
                             padding=2, fontsize=8, color=self.t["text"])
        if horizontal:
            ax.set_yticks(list(positions), categories)
            ax.invert_yaxis()
            ax.grid(axis="y", visible=False)
            ax.grid(axis="x", color=self.t["grid"], linewidth=0.8)
            ax.set_xlabel(value_label, fontsize=8, color=self.t["text_muted"])
        else:
            ax.set_xticks(list(positions), categories)
            step = max(1, len(categories) // 12)
            for i, label in enumerate(ax.get_xticklabels()):
                label.set_visible(i % step == 0)
                label.set_rotation(30 if len(categories) > 6 else 0)
                label.set_ha("right" if len(categories) > 6 else "center")
            ax.set_ylabel(value_label, fontsize=8, color=self.t["text_muted"])
        ax.margins(x=0.02 if not horizontal else 0.12,
                   y=0.12 if not horizontal else 0.02)
        if n > 1:
            ax.legend(frameon=False, fontsize=8, labelcolor=self.t["text"],
                      loc="upper left", ncols=n)
        self.canvas.draw_idle()

    def lines(self, categories, series, value_label="", fmt=an.fmt_number):
        if not categories or not any(any(v for v in vals)
                                     for _, vals, _ in series):
            self.empty()
            return
        ax = self._start()
        x = list(range(len(categories)))
        for name, values, color in series:
            color = self.t.get(color, color)
            ax.plot(x, values, color=color, linewidth=2, label=name,
                    marker="o", markersize=4 if len(x) > 30 else 6)
            for xi, cat, v in zip(x, categories, values):
                self.hover.append(((xi, v), f"{cat}\n{name}: {fmt(v)}"))
        ax.set_xticks(x, categories)
        step = max(1, len(categories) // 10)
        for i, label in enumerate(ax.get_xticklabels()):
            label.set_visible(i % step == 0)
            label.set_rotation(30)
            label.set_ha("right")
        ax.set_ylabel(value_label, fontsize=8, color=self.t["text_muted"])
        ax.set_ylim(bottom=0)
        if len(series) > 1:
            ax.legend(frameon=False, fontsize=8, labelcolor=self.t["text"],
                      loc="upper left", ncols=len(series))
        self.canvas.draw_idle()

    def trend(self, categories, series, value_label=""):
        """Columns for short ranges, lines for long ones."""
        if len(categories) > 20:
            self.lines(categories, series, value_label)
        else:
            self.bars(categories, series, value_label=value_label)

    def _motion(self, event):
        if self.ax is None or self.note is None:
            return
        found = None
        if event.inaxes is self.ax:
            for target, text in self.hover:
                if isinstance(target, tuple):
                    px, py = self.ax.transData.transform(target)
                    if abs(px - event.x) < 10 and abs(py - event.y) < 10:
                        found = (target, text)
                        break
                elif target.contains(event)[0]:
                    found = ((event.xdata, event.ydata), text)
                    break
        if found:
            self.note.xy = found[0]
            self.note.set_text(found[1])
            self.note.set_visible(True)
            self.canvas.draw_idle()
        elif self.note.get_visible():
            self.note.set_visible(False)
            self.canvas.draw_idle()


# =====================================================
# data service (background loading + cache)
# =====================================================

class DataService:
    """Loads the reports once in a background thread, keeps the snapshot
    until something changes, and tells the pages."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.snapshot = None
        self.error = None
        self.loading = False
        self.waiting = []
        self.listeners = []

    def invalidate(self):
        self.snapshot = None
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:
                self.ctx.log.exception("Refresh after a change failed")

    def request(self, callback):
        """callback(snapshot or None, error or None) on the GUI thread."""
        if self.snapshot is not None:
            callback(self.snapshot, None)
            return
        self.waiting.append(callback)
        if self.loading:
            return
        self.loading = True
        result = {}
        path, source = self.ctx.excel_path(), self.ctx.data_source()

        def work():
            from warehouse import store
            try:
                result["value"] = store.load_snapshot(path, source)
            except Exception as error:
                self.ctx.log.exception("Loading the warehouse data failed")
                result["error"] = error

        thread = threading.Thread(target=work, daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.ctx.window.after(120, poll)
                return
            self.loading = False
            self.snapshot = result.get("value")
            self.error = result.get("error")
            waiting, self.waiting = self.waiting, []
            for cb in waiting:
                cb(self.snapshot, self.error)

        self.ctx.window.after(120, poll)

    def rebuild_ledger(self):
        from warehouse import store
        if self.snapshot is not None:
            store.rebuild_inventory(self.snapshot)


def explain_load_error(error):
    if isinstance(error, PermissionError):
        return ("The Excel file is open in another program (Excel?). "
                "Close it and press Refresh.")
    return f"The records could not be loaded:\n{error}"


# =====================================================
# exporting
# =====================================================

def ask_export(ctx, doc, kind, parent=None):
    """Ask where to save, then write the report in the background."""
    from warehouse import exports
    parent = parent or ctx.window
    folder = ctx.reports_folder()
    path = filedialog.asksaveasfilename(
        parent=parent, title=f"Export {doc.title}",
        defaultextension=f".{kind}", initialdir=str(folder),
        initialfile=f"{doc.file_stem}.{kind}",
        filetypes=[("Excel Workbook", "*.xlsx")] if kind == "xlsx"
        else [("PDF", "*.pdf")])
    if not path:
        return

    def done(result, error):
        if isinstance(error, PermissionError):
            messagebox.showerror("Export", f"Cannot write to:\n{path}\n\n"
                                 "Close the file and try again.",
                                 parent=parent)
        elif error is not None:
            messagebox.showerror("Export Error",
                                 f"The report could not be exported:\n"
                                 f"{error}", parent=parent)
        else:
            ctx.notify(f"Exported {doc.title}")
            if messagebox.askyesno("Export", f"Saved:\n{path}\n\nOpen it "
                                   "now?", parent=parent):
                ctx.open_file(path)

    ctx.run_with_progress(parent, f"Creating {doc.title}...",
                          lambda: exports.export(doc, path), done)
