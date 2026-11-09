"""Master Lists and Settings."""

import tkinter
from tkinter import messagebox, simpledialog, ttk

import ttkbootstrap as tb

from .components import Card, ScrollPage

LIST_TITLES = [("consignee_list", "Consignees"), ("supplier_list", "Suppliers"),
               ("broker_list", "Brokerages"), ("hauler_list", "Haulers"),
               ("location_list", "Locations / Warehouses"),
               ("destination_list", "Destinations"),
               ("country_of_origin_list", "Countries of Origin")]


class SettingsPage(ScrollPage):
    title = "Master Lists and Settings"

    def __init__(self, parent, ctx, service):
        super().__init__(parent)
        self.ctx, self.service = ctx, service
        # Only the Owner edition uses MySQL; a User (site) PC keeps its data
        # in Excel/JSON files and sends Master Data files to the owner.
        self.owner_edition = getattr(ctx, "owner_edition", True)
        ttk.Label(self.body, text=(
                  "Where the data is kept, the MySQL connection, aging "
                  "thresholds, the drop-down lists of the inspection form "
                  "and the Demo Mode." if self.owner_edition else
                  "Where the data is kept, the drop-down lists of the "
                  "inspection form and the Demo Mode."),
                  style="PageMuted.TLabel").grid(row=1, column=0, sticky="w")
        self.mysql_label = None
        self._data_card(2)
        if self.owner_edition:
            self._mysql_card(3)
        self._lists_card(4)
        self._demo_card(5)

    def on_show(self):
        self.refresh_labels()

    # ---- data ----
    def _data_card(self, row):
        card = Card(self.body, "Data Storage", (
                    "The Excel data file is the primary store; every saved "
                    "report also goes to MySQL when it is set up. The "
                    "warehouse decisions (reconciliation log, Bad Order case "
                    "status, aging thresholds) are kept in the 'Warehouse "
                    "Data' folder beside the Excel file."
                    if self.owner_edition else
                    "User edition: every report is kept on this PC, in the "
                    "Excel data file and the JSON files beside it. Use "
                    "Export Master Data (left panel of the inspection form) "
                    "and send the file to the owner, who brings it into the "
                    "owner's MySQL database and Excel file."))
        card.grid(row=row, column=0, sticky="we", pady=(14, 0))
        c = card.content
        self.file_label = ttk.Label(c, text="", style="Card.TLabel",
                                    wraplength=900, justify="left")
        self.file_label.grid(row=0, column=0, columnspan=3, sticky="w")
        tb.Button(c, text="Change Excel File...", bootstyle="secondary-outline",
                  command=self.change_file).grid(row=1, column=0, sticky="w",
                                                 pady=(8, 0))
        self.source = tkinter.StringVar(value=self.ctx.data_source())
        if self.owner_edition:
            ttk.Label(c, text="Dashboard and analytics read from:",
                      style="CardMuted.TLabel").grid(row=2, column=0,
                                                     sticky="w", pady=(12, 2))
            row_frame = ttk.Frame(c, style="CardPlain.TFrame")
            row_frame.grid(row=3, column=0, columnspan=3, sticky="w")
            for value, text in (("excel", "Excel data file"),
                                ("mysql", "MySQL database")):
                tb.Radiobutton(row_frame, text=text, value=value,
                               variable=self.source, style="Card.TRadiobutton",
                               command=self.set_source).pack(side="left",
                                                             padx=(0, 16))
        self.side_label = ttk.Label(c, text="", style="CardMuted.TLabel",
                                    wraplength=900, justify="left")
        self.side_label.grid(row=4, column=0, columnspan=3, sticky="w",
                             pady=(8, 0))
        theme_row = ttk.Frame(c, style="CardPlain.TFrame")
        theme_row.grid(row=5, column=0, columnspan=3, sticky="w",
                       pady=(12, 0))
        tb.Button(theme_row, text="Light / Dark Mode",
                  bootstyle="secondary-outline",
                  command=self.ctx.toggle_theme).pack(side="left")
        ttk.Label(theme_row, text=f"   Log file: {self.ctx.log_file}",
                  style="CardMuted.TLabel").pack(side="left")

    def refresh_labels(self):
        from warehouse.store import side_file_path
        path = self.ctx.excel_path()
        exists = path.exists()
        self.file_label.configure(
            text=f"Excel data file: {path}" + ("" if exists else
                                               "   (not created yet - it is "
                                               "made by the first save)"))
        self.side_label.configure(text=f"Warehouse side file: "
                                  f"{side_file_path(path)}")
        self.source.set(self.ctx.data_source())
        self._mysql_status()

    def change_file(self):
        self.ctx.change_excel_file()
        self.service.invalidate()
        self.refresh_labels()

    def set_source(self):
        if self.source.get() == "mysql" and not self.ctx.mysql_enabled():
            messagebox.showinfo("Data Source", "MySQL is not set up (or is "
                                "off in Demo Mode). Using the Excel file.",
                                parent=self.ctx.window)
            self.source.set("excel")
        self.ctx.set_data_source(self.source.get())
        self.service.invalidate()

    # ---- MySQL ----
    def _mysql_card(self, row):
        card = Card(self.body, "MySQL",
                    "Optional. The Cargo ID and Receiving Ref columns need a "
                    "one-time table upgrade on databases created before the "
                    "warehouse monitoring (data/schema/migrations/"
                    "001_add_item_warehouse_links.sql does the same).")
        card.grid(row=row, column=0, sticky="we", pady=(14, 0))
        c = card.content
        self.mysql_label = ttk.Label(c, text="", style="Card.TLabel")
        self.mysql_label.grid(row=0, column=0, columnspan=3, sticky="w")
        buttons = ttk.Frame(c, style="CardPlain.TFrame")
        buttons.grid(row=1, column=0, sticky="w", pady=(8, 0))
        tb.Button(buttons, text="MySQL Settings...",
                  bootstyle="secondary-outline",
                  command=self.ctx.open_mysql_settings).pack(side="left")
        tb.Button(buttons, text="Check Tables", bootstyle="secondary-outline",
                  command=self.check_tables).pack(side="left", padx=6)
        tb.Button(buttons, text="Upgrade MySQL Tables...",
                  bootstyle="warning-outline",
                  command=self.upgrade).pack(side="left")

    def _mysql_status(self):
        if self.mysql_label is None:          # User edition: no MySQL card
            return
        self.mysql_label.configure(
            text="Off in Demo Mode (sample data never reaches MySQL)."
            if self.ctx.demo_mode else
            ("MySQL is set up." if self.ctx.mysql_enabled()
             else "MySQL is not set up - the program uses Excel only."))

    def check_tables(self):
        db = self.ctx.db_mysql
        if not self.ctx.mysql_enabled():
            self._mysql_status()
            return
        try:
            missing = db.missing_link_columns()
            short = db.short_control_tables()
        except Exception as error:
            messagebox.showerror("MySQL", db.explain_error(error),
                                 parent=self.ctx.window)
            return
        problems = []
        if missing:
            problems.append("Missing columns in item_lines: " + ", ".join(missing))
        if short:
            problems.append("control_no is too short for the current Control # "
                            "format in: " + ", ".join(short))
        messagebox.showinfo("MySQL", "\n".join(problems) + "\n\nUse 'Upgrade "
                            "MySQL Tables'." if problems else
                            "The tables are up to date.", parent=self.ctx.window)

    def upgrade(self):
        db = self.ctx.db_mysql
        if not self.ctx.mysql_enabled():
            self._mysql_status()
            return
        if not messagebox.askyesno(
                "Upgrade MySQL Tables",
                "Add any missing columns, and make control_no long enough for "
                "the Control # with initials?\n\nExisting rows are kept (new "
                "columns start empty). If the program's MySQL login may not "
                "change tables, you will be asked for an admin login, which "
                "is not saved.",
                parent=self.ctx.window):
            return
        try:
            added = db.upgrade_schema()
        except Exception as error:
            if getattr(error, "errno", None) == db.ACCESS_DENIED:
                self._upgrade_as_admin()
                return
            self.ctx.log.exception("MySQL upgrade failed")
            messagebox.showerror("MySQL", db.explain_error(error),
                                 parent=self.ctx.window)
            return
        self._upgrade_done(added)

    def _upgrade_as_admin(self):
        db = self.ctx.db_mysql
        user = simpledialog.askstring(
            "MySQL Admin Login", "The program's MySQL login may not change "
            "tables.\n\nAdmin user name (not saved):", initialvalue="root",
            parent=self.ctx.window)
        if not user:
            return
        password = simpledialog.askstring(
            "MySQL Admin Login", f"Password for {user} (not saved):", show="*",
            parent=self.ctx.window)
        if password is None:
            return
        try:
            added = db.upgrade_schema_as(user, password)
        except Exception as error:
            self.ctx.log.exception("MySQL upgrade failed")
            # The MySQL message names the admin login, explain_error the saved one.
            messagebox.showerror("MySQL", str(error), parent=self.ctx.window)
            return
        self._upgrade_done(added)

    def _upgrade_done(self, added):
        messagebox.showinfo("MySQL", "Added: " + ", ".join(added) if added
                            else "Nothing to do - the columns exist.",
                            parent=self.ctx.window)

    # ---- master lists ----
    def _lists_card(self, row):
        card = Card(self.body, "Master Lists",
                    "The drop-down lists of the inspection form "
                    "(master_list.json). New names can also be added while "
                    "typing a report.")
        card.grid(row=row, column=0, sticky="we", pady=(14, 0))
        c = card.content
        c.columnconfigure(0, weight=0)
        c.columnconfigure(2, weight=1)
        self.list_choice = tb.Combobox(c, state="readonly", width=28,
                                       values=[t for _, t in LIST_TITLES])
        self.list_choice.set(LIST_TITLES[0][1])
        self.list_choice.no_dirty = True
        self.list_choice.grid(row=0, column=0, sticky="w")
        self.list_choice.bind("<<ComboboxSelected>>",
                              lambda e: self.show_list())
        self.listbox = tkinter.Listbox(c, height=9, width=50,
                                       exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="w", pady=(6, 0))
        side = ttk.Frame(c, style="CardPlain.TFrame")
        side.grid(row=1, column=1, sticky="nw", padx=12, pady=(6, 0))
        self.new_name = tkinter.StringVar()
        tb.Entry(side, textvariable=self.new_name, width=32).pack(anchor="w")
        tb.Button(side, text="Add Name", bootstyle="primary-outline",
                  command=self.add_name).pack(anchor="w", pady=(6, 0))
        tb.Button(side, text="Remove Selected", bootstyle="danger-outline",
                  command=self.remove_name).pack(anchor="w", pady=(6, 0))
        self.show_list()

    def _key(self):
        return dict((t, k) for k, t in LIST_TITLES)[self.list_choice.get()]

    def show_list(self):
        self.listbox.delete(0, "end")
        for name in self.ctx.master_data.get(self._key(), []):
            self.listbox.insert("end", name)

    def add_name(self):
        name = self.new_name.get().strip()
        values = self.ctx.master_data[self._key()]
        if not name:
            return
        if any(v.casefold() == name.casefold() for v in values):
            messagebox.showinfo("Master Lists", f'"{name}" is already in the '
                                "list.", parent=self.ctx.window)
            return
        values.append(name)
        values.sort(key=str.casefold)
        if not self.ctx.save_master_lists():
            values.remove(name)
        self.new_name.set("")
        self.show_list()

    def remove_name(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        name = self.listbox.get(selection[0])
        if not messagebox.askyesno("Master Lists", f'Remove "{name}" from '
                                   "the list?\n\nSaved reports keep the name.",
                                   parent=self.ctx.window):
            return
        values = self.ctx.master_data[self._key()]
        values.remove(name)
        if not self.ctx.save_master_lists():
            values.append(name)
            values.sort(key=str.casefold)
        self.show_list()

    # ---- demo mode ----
    def _demo_card(self, row):
        card = Card(self.body, "Demo Mode and Sample Data",
                    "Demo Mode uses its own folder (demo_data), its own "
                    "Excel file and no MySQL, so the fictional TEST-... "
                    "records never mix with real reports. Start it with "
                    "START_DEMO.bat; close the program and use START_FSR.bat "
                    "to return to the real data.")
        card.grid(row=row, column=0, sticky="we", pady=(14, 0))
        c = card.content
        ttk.Label(c, text=("DEMO MODE IS ON - data folder: "
                           f"{self.ctx.data_dir}") if self.ctx.demo_mode
                  else "Demo Mode is off: this window shows the real data. "
                  "The sample data tools work only in Demo Mode.",
                  style="CardTitle.TLabel" if self.ctx.demo_mode
                  else "Card.TLabel", wraplength=900).grid(row=0, column=0,
                                                           sticky="w")
        buttons = ttk.Frame(c, style="CardPlain.TFrame")
        buttons.grid(row=1, column=0, sticky="w", pady=(8, 0))
        state = "normal" if self.ctx.demo_mode else "disabled"
        tb.Button(buttons, text="Generate / Refresh Sample Data",
                  bootstyle="warning", state=state,
                  command=self.generate).pack(side="left")
        tb.Button(buttons, text="Remove Sample Data",
                  bootstyle="danger-outline", state=state,
                  command=self.reset).pack(side="left", padx=6)

    def generate(self):
        from warehouse import sample_data
        if not messagebox.askyesno(
                "Sample Data", "Write the fictional TEST-... sample reports "
                f"into the demo folder?\n\n{self.ctx.data_dir}\n\nExisting "
                "TEST reports are updated, not duplicated.",
                parent=self.ctx.window):
            return

        def done(result, error):
            if error is not None:
                messagebox.showerror("Sample Data", str(error),
                                     parent=self.ctx.window)
                return
            path, sample = result
            self.service.invalidate()
            self.ctx.after_sample_change(path)
            messagebox.showinfo(
                "Sample Data", f"{len(sample.receiving)} Receiving and "
                f"{len(sample.withdrawals)} Withdrawal TEST reports are in:"
                f"\n{path}", parent=self.ctx.window)

        self.ctx.run_with_progress(
            self.ctx.window, "Writing the sample reports (about 20 s)...",
            lambda: sample_data.generate(self.ctx.data_dir,
                                         workbook_name=self.ctx.excel_path()
                                         .name), done)

    def reset(self):
        from warehouse import sample_data
        if not messagebox.askyesno(
                "Sample Data", "Remove every TEST-... report, its incident "
                "file, report forms and reconciliation entries from the demo "
                "folder?\n\nOther reports are not touched.",
                parent=self.ctx.window):
            return
        try:
            result = sample_data.reset(self.ctx.data_dir,
                                       self.ctx.excel_path().name)
        except Exception as error:
            messagebox.showerror("Sample Data", str(error),
                                 parent=self.ctx.window)
            return
        self.service.invalidate()
        self.ctx.after_sample_change(self.ctx.excel_path())
        messagebox.showinfo("Sample Data", f"Removed {result['reports']} TEST "
                            f"report(s) and {result['files']} file(s).",
                            parent=self.ctx.window)
