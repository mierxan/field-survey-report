"""Open Saved Report: the list of saved reports (Excel file or MySQL, and the PO-linked Withdrawal reports), with search, from which a report is opened for editing.

Moved here from field_survey_report.py (Phase 4). The code is unchanged
except that the names it takes from the program's window module are
read as `host.<name>`, at the moment they are used (bind() is called
by the window module)."""
from fsr_storage import Workbook
from tkinter import messagebox
from tkinter import ttk
import tkinter


class _Host:
    """The window module's names, read when they are used."""

    def __init__(self):
        object.__setattr__(self, "names", None)

    def __getattr__(self, name):
        names = object.__getattribute__(self, "names")
        if names is None:
            raise RuntimeError("bind() was not called")
        try:
            return names[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        object.__getattribute__(self, "names")[name] = value


host = _Host()


def bind(names):
    """Called by the window module with its globals()."""
    object.__setattr__(host, "names", names)


def read_withdrawal_listing():
    """(list rows, search index) of the Withdrawal workbook. Trouble with it
    is reported and does not hide the reports of the main workbook."""
    try:
        store = host.data_store()    # ValueError in Demo Mode, as before
        return (host.busy(store.list_withdrawal_reports),
                host.busy(store.withdrawal_search_index))
    except Exception as error:
        host.log.exception("Reading the Withdrawal workbook failed")
        messagebox.showwarning(
            "Withdrawal Workbook",
            f"The PO-linked Withdrawal reports could not be listed:\n{error}",
            parent=host.window)
        return [], {}


def open_saved_report_dialog(initial_search=""):
    """List the saved reports; double-click one to edit it."""

    use_mysql = host.db_mysql is not None and host.db_mysql.is_enabled()

    if Workbook is None and not use_mysql:
        host.excel_missing_message()
        return

    path = host.excel_state["path"]
    source_var = tkinter.StringVar(value="mysql" if use_mysql else "excel")
    withdrawal_rows, withdrawal_index = read_withdrawal_listing()
    withdrawal_labels = {row[0] for row in withdrawal_rows}

    def fetch_reports(show_errors=True):
        """The list for the chosen source ([] and a message on trouble)."""
        try:
            if source_var.get() == "mysql":
                return host.busy(host.db_mysql.list_reports)
            return sorted([*host.busy(host.data_store(path).list_reports), *withdrawal_rows],
                          reverse=True)
        except PermissionError:
            problem = ("Cannot read the Excel file. Close it in Excel and "
                       "try again.")
        except Exception as error:
            if source_var.get() == "mysql" and host.mysql_away(
                    error, "the list shows the reports in this PC's Excel "
                           "file"):
                source_var.set("excel")
                return fetch_reports(show_errors)
            host.log.exception("Reading saved reports failed")
            problem = (host.db_mysql.explain_error(error)
                       if source_var.get() == "mysql" else
                       f"Unable to read the Excel file:\n{error}")
        if show_errors:
            messagebox.showerror("Open Error", problem, parent=host.window)
        return None

    reports = fetch_reports()
    if reports is None:
        return

    search_index = {}

    def load_index():
        """What each report contains (SO, BL/AWB, PO, DR, Gatepass,
        Description) so the search can look inside the reports."""
        try:
            if source_var.get() == "mysql":
                found = host.busy(host.db_mysql.search_index)
            else:
                found = {**host.busy(host.data_store(path).search_index), **withdrawal_index}
        except Exception:
            host.log.exception("Building the search list failed")
            found = {}
        search_index.clear()
        search_index.update(found)

    load_index()

    if not reports and not use_mysql:
        messagebox.showinfo(
            "No Saved Reports",
            f"There are no saved reports yet in:\n{path}",
            parent=host.window
        )
        return

    dialog = host.tb.Toplevel(host.window)
    dialog.title("Open Saved Report")
    dialog.transient(host.window)

    width, height = 1280, 480
    x = host.window.winfo_rootx() + max((host.window.winfo_width() - width) // 2, 0)
    y = host.window.winfo_rooty() + 60
    dialog.geometry(f"{width}x{height}+{x}+{y}")

    top = host.tb.Frame(dialog)
    top.pack(fill="x", padx=15, pady=(15, 5))
    host.tb.Label(top, text="Search:").pack(side="left")
    search_var = tkinter.StringVar()
    search_entry = host.tb.Entry(top, textvariable=search_var, width=34)
    search_entry.pack(side="left", padx=(10, 8))
    host.tb.Label(top, text="in").pack(side="left")
    SEARCH_FIELDS = [
        ("All", None), ("SO Number", "so"), ("BL/AWB", "bl"), ("PO", "po"),
        ("DR", "dr"), ("Gatepass", "gatepass"),
        ("Description", "description"),
    ]
    field_var = tkinter.StringVar(value="All")
    field_combo = host.tb.Combobox(
        top, textvariable=field_var, state="readonly", width=14,
        values=[name for name, _ in SEARCH_FIELDS]
    )
    field_combo.pack(side="left", padx=8)
    field_combo.no_dirty = True

    if use_mysql:
        source_row = host.tb.Frame(dialog)
        source_row.pack(fill="x", padx=15, pady=(0, 5))
        host.tb.Label(source_row, text="Open from:").pack(side="left")
        for _text, _value in (("MySQL database", "mysql"),
                              ("Excel file", "excel")):
            host.tb.Radiobutton(
                source_row, text=_text, value=_value, variable=source_var,
                command=lambda: switch_source()
            ).pack(side="left", padx=10)

    columns = ("control", "so", "date", "consignee", "bl", "po", "dr",
               "gatepass", "description", "saved")
    headings = ("Control #", "SO Number", "Inspection Date", "Consignee",
                "BL/AWB", "PO", "DR", "Gatepass", "Description",
                "Last Saved")
    widths = (115, 120, 105, 170, 110, 110, 90, 90, 220, 130)
    if withdrawal_labels:           # room for the "[Withdrawal]" label
        widths = (200, *widths[1:])

    tree_frame = host.tb.Frame(dialog)
    tree_frame.pack(fill="both", expand=True, padx=15, pady=5)

    tree = ttk.Treeview(
        tree_frame, columns=columns, show="headings", selectmode="browse"
    )
    for column, heading, col_width in zip(columns, headings, widths):
        tree.heading(column, text=heading)
        tree.column(column, width=col_width, anchor="w")

    tree_scroll = ttk.Scrollbar(
        tree_frame, orient="vertical", command=tree.yview
    )
    tree_hscroll = ttk.Scrollbar(
        tree_frame, orient="horizontal", command=tree.xview
    )
    tree.configure(yscrollcommand=tree_scroll.set,
                   xscrollcommand=tree_hscroll.set)
    tree_hscroll.pack(side="bottom", fill="x")
    tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")

    def switch_source():
        found = fetch_reports()
        reports[:] = found or []
        load_index()
        refresh()

    def refresh(*_):
        query = search_var.get().strip().casefold()
        tree.delete(*tree.get_children())

        key = dict(SEARCH_FIELDS)[field_var.get()]
        for row in reports:
            parts = search_index.get(row[0], {})
            label = (f"{row[0]} [Withdrawal]" if row[0] in withdrawal_labels
                     else row[0])
            if key is None:
                text = label + " " + " ".join(row) + " " + " ".join(
                    " ".join(values) for values in parts.values())
            else:
                text = " ".join(parts.get(key, []))
            if query in text.casefold():
                def joined(name):
                    return ", ".join(dict.fromkeys(parts.get(name, [])))  # noqa: B023 - used in this same pass
                tree.insert("", "end", iid=row[0], values=(
                    label, row[1], row[2], row[3], joined("bl"),
                    joined("po"), joined("dr"), joined("gatepass"),
                    joined("description"), row[4]))

        children = tree.get_children()
        if children:
            tree.selection_set(children[0])
            tree.focus(children[0])

    def load_selected(event=None):
        selection = tree.selection()
        if not selection:
            return

        control_no = selection[0]
        chosen_source = source_var.get()
        dialog.destroy()
        host.load_report_into_form(control_no, chosen_source)

    buttons = host.tb.Frame(dialog)
    buttons.pack(fill="x", padx=15, pady=(5, 15))
    host.tb.Button(
        buttons, text="Open Report", width=14, command=load_selected,
        bootstyle="primary"
    ).pack(side="right")
    host.tb.Button(
        buttons, text="Cancel", width=10, command=dialog.destroy,
        bootstyle="secondary-outline"
    ).pack(side="right", padx=10)

    search_var.trace_add("write", refresh)
    field_combo.bind("<<ComboboxSelected>>", refresh)

    def on_double_click(event):
        # Ignore double-clicks on the column headers.
        if tree.identify_region(event.x, event.y) == "cell":
            load_selected()

    tree.bind("<Double-1>", on_double_click)
    dialog.bind("<Return>", load_selected)
    dialog.bind("<Escape>", lambda e: dialog.destroy())

    if initial_search:
        search_var.set(initial_search)
    refresh()
    search_entry.focus_set()
    dialog.wait_visibility()
    dialog.grab_set()
