"""Navigation sidebar and module switching inside the main window."""

from tkinter import ttk

import ttkbootstrap as tb

from warehouse.transactions import WITHDRAWAL

from . import theme
from .components import DataService, ScrollPage, on_page_wheel

MODULES = [
    ("dashboard", "Dashboard", "▦"),
    ("inspection", "Inspection Reports", "✎"),
    ("receiving", "Receiving Transactions", "↓"),
    ("withdrawal", "Withdrawal Transactions", "↑"),
    ("warehouse", "Warehouse Monitoring", "▤"),
    ("bad_order", "Bad Order Monitoring", "⚠"),
    ("analytics", "Analytics and Reports", "▲"),
    ("settings", "Master Lists and Settings", "⚙"),
]


class Shell:
    def __init__(self, ctx):
        self.ctx = ctx
        self.service = DataService(ctx)
        self.pages = {}
        self.current = None
        self.buttons = {}
        self._build_sidebar()
        ctx.window.bind_all("<MouseWheel>", on_page_wheel, add="+")
        ctx.window.bind_all("<Button-4>", on_page_wheel, add="+")
        ctx.window.bind_all("<Button-5>", on_page_wheel, add="+")
        self.service.listeners.append(self._data_changed)

    # ---- sidebar ----
    def _build_sidebar(self):
        bar = self.ctx.sidebar
        for child in bar.winfo_children():
            child.destroy()
        top = ttk.Frame(bar, style="Sidebar.TFrame", padding=(18, 18, 18, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Field Survey Report", style="SidebarBrand.TLabel").pack(
            anchor="w")
        ttk.Label(top, text="Cargo Inspection",
                  style="Sidebar.TLabel", justify="left").pack(anchor="w",
                                                              pady=(2, 0))
        ttk.Label(bar, text="MODULES", style="SidebarMuted.TLabel",
                  padding=(18, 14, 0, 4)).pack(fill="x")
        for key, label, icon in MODULES:
            button = ttk.Button(bar, text=f"{icon}   {label}",
                                style="Sidebar.TButton", takefocus=False,
                                command=lambda k=key: self.show(k))
            button.pack(fill="x")
            self.buttons[key] = button
        foot = ttk.Frame(bar, style="Sidebar.TFrame", padding=(18, 10))
        foot.pack(side="bottom", fill="x")
        if self.ctx.demo_mode:
            ttk.Label(foot, text="DEMO MODE - TEST DATA ONLY",
                      style="Demo.TLabel", padding=(8, 4)).pack(
                anchor="w", pady=(0, 8))
        ttk.Label(foot, text=self.ctx.user_name, style="Sidebar.TLabel"
                  ).pack(anchor="w")
        role = "Owner" if self.ctx.is_owner else "User"
        edition = getattr(self.ctx, "edition_label", "")
        ttk.Label(foot, text=f"{role}  -  {edition} edition" if edition
                  else role, style="SidebarMuted.TLabel").pack(anchor="w")

    def _highlight(self):
        for key, button in self.buttons.items():
            button.configure(style="SidebarActive.TButton" if key ==
                             self.current else "Sidebar.TButton")

    # ---- modules ----
    def _page(self, key):
        if key in self.pages:
            return self.pages[key]
        from .analytics_page import AnalyticsPage
        from .pages import BadOrderPage, DashboardPage, TransactionsPage
        from .settings_page import SettingsPage
        from .warehouse_page import WarehousePage
        parent = self.ctx.window
        factories = {
            "dashboard": lambda: DashboardPage(parent, self.ctx, self.service),
            "receiving": lambda: TransactionsPage(parent, self.ctx,
                                                  self.service, "Receiving"),
            "withdrawal": lambda: TransactionsPage(parent, self.ctx,
                                                   self.service, WITHDRAWAL),
            "bad_order": lambda: BadOrderPage(parent, self.ctx, self.service),
            "warehouse": lambda: WarehousePage(parent, self.ctx, self.service),
            "analytics": lambda: AnalyticsPage(parent, self.ctx,
                                               self.service),
            "settings": lambda: SettingsPage(parent, self.ctx, self.service),
        }
        self.pages[key] = factories[key]()
        return self.pages[key]

    def show(self, key, tab=None):
        if key == self.current and tab is None:
            return
        old = self.current
        if old in ("inspection", None):     # None: the form shown at start
            self.ctx.inspection_frame.pack_forget()
        elif old in self.pages:
            self.pages[old].pack_forget()
        self.current = key
        self._highlight()
        label = dict((k, l) for k, l, _ in MODULES)[key]
        self.ctx.set_title(label, inspection=key == "inspection")
        if key == "inspection":
            self.ctx.inspection_frame.pack(side="top", fill="both",
                                           expand=True)
            return
        page = self._page(key)
        page.pack(side="top", fill="both", expand=True)
        if tab is not None and hasattr(page, "show_tab"):
            page.tab = tab
        page.on_show()

    def is_inspection(self):
        return self.current == "inspection"

    def _data_changed(self):
        page = self.pages.get(self.current)
        if page is not None:
            page.on_show()

    def theme_changed(self):
        theme.apply_styles(tb.Style())
        for page in ScrollPage.instances:
            try:
                page.apply_theme()
            except Exception:
                self.ctx.log.exception("Theme change of a page failed")
        self._highlight()


def install(ctx):
    theme.apply_styles(tb.Style())
    shell = Shell(ctx)
    ctx.show_module = shell.show
    return shell
