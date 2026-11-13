"""The PO picker on the Item Lists tab (see fsr_withdrawal.py for the rules).

Shown only for Activity = Withdrawal on the Default form. Lines taken from it go
into the Item Lists, which stay on screen. A taken line is locked, because its
details come from its Receiving line: double-click its Quantity to change what
is withdrawn. Lines typed by hand work as they always did.
"""

from tkinter import messagebox, ttk

import ttkbootstrap as tb

import fsr_storage as storage
import fsr_store
import fsr_withdrawal as wd
from warehouse.transactions import WITHDRAWAL, normalize_activity

SOURCE_COLUMNS = (
    ("PO Number", 80), ("Line", 35), ("Received In", 100),
    ("Description", 140), ("Received Qty", 80), ("Remaining", 70), ("UOM", 40),
    ("Packaging", 60),
)
# Open on a taken line: Findings is for the withdrawal to fill in.
UNLOCKED_HEADERS = {"Findings"}


# ---- one line of an Item List (ItemLine widgets of an ItemListSection) ----

def is_linked(widgets):
    return bool(widgets.po_link.get(wd.LINE_NO_HEADER))


def _set_states(section, widgets, state):
    for header, widget in zip(section.headers, widgets):
        if header not in UNLOCKED_HEADERS:
            widget.configure(state=state)


def unlock_line(section, widgets):
    """Back to a plain line, before it is filled or cleared."""
    if widgets.po_link:
        _set_states(section, widgets, "normal")
    widgets.po_link = {}


def restore_link(section, widgets, row):
    """Keep the Withdrawal fields of `row` with the line, and lock a line that
    came from the Receiving data."""
    widgets.po_link = {header: row[header] for header in wd.LINE_EXTRA_HEADERS
                       if row.get(header)}
    if is_linked(widgets):
        _set_states(section, widgets, "readonly")


def bind_line(section, widgets, panel):
    """`panel` returns the WithdrawalPanel (not yet built for the first rows)."""
    quantity = section.cell(widgets, "Quantity")
    quantity.bind("<Double-1>",
                  lambda e: panel().edit_quantity(section, widgets), add="+")
    quantity.bind("<Return>",
                  lambda e: panel().commit_quantity(), add="+")
    quantity.bind("<FocusOut>",
                  lambda e: panel().commit_quantity(), add="+")
    for widget in widgets:
        widget.bind("<FocusIn>",
                    lambda e: panel().line_clicked(section, widgets), add="+")


class WithdrawalPanel:
    """`host` provides: window, activity_entry, form_var, main_path(),
    control_no(),
    sections() (the Item Lists), stored_in_main() (is the open report a saved
    main workbook report?), header_po_entry(), mark_dirty()."""

    def __init__(self, parent, host, row):
        self.host = host
        self.owned = False          # the open report is in the Withdrawal book
        self.found = {}             # picker row id -> PoLine
        self.activity_text = ""     # to go back when a change is refused
        self.asking = False         # a dialog takes focus: do not ask twice
        self.editing = None         # (section, widgets, old text) of a Quantity
        self.clicked = None         # (section, widgets) clicked last

        self.frame = tb.Labelframe(
            parent, text="Withdrawal from a PO", padding=10)
        self.frame.grid(row=row, column=0, pady=6, sticky="we")
        self.frame.grid_remove()

        self.source_label = tb.Label(self.frame, bootstyle="secondary",
                                     wraplength=520)
        self.source_label.grid(row=0, column=0, sticky="w", pady=(0, 6))

        top = tb.Frame(self.frame)
        top.grid(row=1, column=0, sticky="w")
        tb.Label(top, text="PO Number:").pack(side="left")
        self.po_entry = tb.Entry(top, width=24)
        self.po_entry.pack(side="left", padx=8)
        self.po_entry.bind("<Return>", lambda e: self.find_po())
        tb.Button(top, text="Show Lines", command=self.find_po,
                  bootstyle="primary").pack(side="left")

        holder = tb.Frame(self.frame)
        holder.grid(row=2, column=0, sticky="we")
        names = [f"c{index}" for index in range(len(SOURCE_COLUMNS))]
        self.source_tree = ttk.Treeview(
            holder, columns=names, show="headings", height=5,
            selectmode="browse")
        for name, (heading, width) in zip(names, SOURCE_COLUMNS):
            self.source_tree.heading(name, text=heading)
            self.source_tree.column(name, width=width, anchor="w")
        scroll = ttk.Scrollbar(holder, orient="vertical",
                               command=self.source_tree.yview)
        self.source_tree.configure(yscrollcommand=scroll.set)
        self.source_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.source_tree.bind("<Double-1>", self._on_double_click)

        actions = tb.Frame(self.frame)
        actions.grid(row=3, column=0, sticky="w", pady=(6, 0))
        tb.Button(actions, text="All in the Item List", command=self.add_all,
                  bootstyle="primary-outline").pack(side="left")
        tb.Button(actions, text="Remove Clicked Line",
                  command=self.remove_clicked,
                  bootstyle="secondary-outline").pack(side="left", padx=8)
        tb.Label(self.frame, bootstyle="secondary", wraplength=520,
                 text="Double-click a PO line to add it to the Item List. "
                      "Double-click a Quantity in the Item List to change it.",
                 ).grid(row=4, column=0, sticky="w", pady=(6, 0))

    # ---- when it applies ----

    def applies(self):
        return (normalize_activity(self.host.activity_entry.get()) == WITHDRAWAL
                and self.host.form_var.get() == storage.ITEM_FORM_DEFAULT)

    def linked_lines(self):
        """[(section, widgets)] of the lines taken from the Receiving data."""
        return [(section, widgets) for section in self.host.sections()
                for widgets in section.rows if is_linked(widgets)]

    def linked(self):
        """The open report belongs in the Withdrawal workbook."""
        return self.owned or bool(self.linked_lines())

    def sync(self):
        if self.applies():
            self.activity_text = self.host.activity_entry.get()
            self.frame.grid()
            self.source_label.configure(
                text="PO lines come from the Receiving reports in: "
                     f"{self.host.main_path().name}")
        else:
            self.frame.grid_remove()

    def context_changed(self):
        """Activity or form changed, or the report is being saved. False when
        a change was refused and put back. Taken lines are never dropped
        without asking."""
        self.commit_quantity()
        if self.asking:
            return True
        if self.applies() or not self.linked():
            self.sync()
            return True
        self.asking = True
        try:
            if self.owned:
                messagebox.showwarning(
                    "PO-Linked Withdrawal",
                    "This saved report is a PO-linked Withdrawal and stays in "
                    "the Withdrawal workbook, so its Activity and Item List "
                    "form cannot be changed.\n\nStart a new report for "
                    "anything else.", parent=self.host.window)
                discard = False
            else:
                discard = messagebox.askyesno(
                    "PO-Linked Withdrawal",
                    f"Discard the {len(self.linked_lines())} PO line(s) added "
                    "to this Withdrawal?", parent=self.host.window)
        finally:
            self.asking = False
        if not discard:
            self.host.activity_entry.set(self.activity_text or WITHDRAWAL)
            self.host.form_var.set(storage.ITEM_FORM_DEFAULT)
            self.sync()
            return False
        while self.linked_lines():
            self._remove_line(*self.linked_lines()[0])
        self.sync()
        self.host.mark_dirty()
        return True

    # ---- the Receiving lines ----

    def find_po(self, quiet=False):
        """Show every line of the PO typed. Nothing is added to the report.
        `quiet`: the list is only being brought up to date."""
        self.source_tree.delete(*self.source_tree.get_children())
        self.found.clear()
        po = self.po_entry.get().strip()
        window = self.host.window
        if not wd.is_usable_po(po):
            messagebox.showinfo(
                "PO Not Usable",
                f"'{po}' does not name a PO.\n\nEnter the PO Number, or record "
                "this Withdrawal on the Item Lists with no PO link."
                if po else "Please enter a PO Number.", parent=window)
            return
        try:
            found = fsr_store.ExcelStore(self.host.main_path()).find_po(po)
        except wd.PoSourceMissing as error:
            messagebox.showinfo(
                "No Receiving Data",
                f"{error}\n\nRecord this Withdrawal on the Item Lists with no "
                "PO link.", parent=window)
            return
        except PermissionError:
            messagebox.showerror(
                "File In Use", "Cannot read the Excel file. Close it in Excel "
                "and try again.", parent=window)
            return
        except wd.PoSourceError as error:
            messagebox.showerror("Receiving Data", str(error), parent=window)
            return
        for index, line in enumerate(found.lines):
            iid = str(index)
            self.found[iid] = line
            self.source_tree.insert("", "end", iid=iid, values=(
                line.po_number, line.line_no, line.control_no, line.description,
                wd.format_quantity(line.received_qty),
                wd.format_quantity(line.remaining_qty), line.uom,
                line.packaging))
        if quiet:
            return
        if found.finished and not found.lines:
            messagebox.showinfo(
                "Fully Withdrawn",
                f"All {found.finished} line(s) of PO {po} with a readable "
                "quantity have already been fully withdrawn.", parent=window)
            return
        if not found.lines and not found.unreadable:
            shared = (f"\n\n{found.shared} line(s) are listed under several "
                      "POs in one cell, so they cannot be tied to this PO."
                      if found.shared else "")
            messagebox.showinfo(
                "PO Not Found",
                f"PO {po} has no saved Receiving lines.{shared}\n\nCheck the "
                "number, or record this Withdrawal on the Item Lists with no "
                "PO link.", parent=window)
            return
        if found.unreadable:
            messagebox.showwarning(
                "Lines Left Out",
                f"{found.unreadable} line(s) of PO {po} are not shown because "
                "their Quantity is not a number above 0. Correct their Receiving "
                "report, or enter them on the Item Lists with no PO link.",
                parent=window)

    def _on_double_click(self, event):
        # Ignore double-clicks on the column headers.
        if self.source_tree.identify_region(event.x, event.y) == "cell":
            self.add_lines([self.source_tree.identify_row(event.y)])

    def add_all(self):
        """Every line shown goes into the Item List."""
        if not self.found:
            messagebox.showinfo("Add Lines", "Show the lines of a PO first.",
                                parent=self.host.window)
            return
        self.add_lines(list(self.found))

    def add_lines(self, iids):
        """Each line becomes one Item List line, filled from that line."""
        window = self.host.window
        if not iids:
            return
        if self.host.stored_in_main() and not self.owned:
            messagebox.showwarning(
                "Saved in the Main Workbook",
                "This saved report stays in the main workbook, so PO lines "
                "cannot be added to it.\n\nStart a new report to link a PO.",
                parent=window)
            return
        taken = {wd.row_key(section.line_values(widgets))
                 for section, widgets in self.linked_lines()}
        problems = []
        added = False
        for line in (self.found[iid] for iid in iids):
            row = wd.new_row(line)
            if wd.row_key(row) in taken:
                problems.append(f"PO {line.po_number} line {line.line_no} is "
                                "already in this report.")
            elif self._insert(row):
                taken.add(wd.row_key(row))
                added = True
            else:
                problems.append(f"PO {line.po_number} line {line.line_no}: the "
                                "Item Lists are full. Create a new Item List.")
        if added:
            entry = self.host.header_po_entry()
            if not entry.get().strip():
                entry.insert(0, self.found[iids[0]].po_number)
            self.host.mark_dirty()
        if problems:
            messagebox.showwarning("Not Added", "\n".join(problems),
                                   parent=window)

    def _insert(self, row):
        """Into the first empty line, adding a line when an Item List is full."""
        for section in self.host.sections():
            for widgets in section.rows:
                if not section.line_values(widgets):
                    section.fill_line(widgets, row)
                    section.update_subtotal()
                    return True
            before = len(section.rows)
            section.add_line()
            if len(section.rows) > before:
                section.fill_line(section.rows[-1], row)
                section.update_subtotal()
                return True
        return False

    # ---- a taken line in the Item List ----

    def line_clicked(self, section, widgets):
        self.clicked = (section, widgets)

    def edit_quantity(self, section, widgets):
        """Double-click: the Quantity of a taken line opens for editing."""
        if not is_linked(widgets):
            return
        self.commit_quantity()
        quantity = section.cell(widgets, "Quantity")
        self.editing = (section, widgets, quantity.get())
        quantity.configure(state="normal")
        quantity.focus_set()
        quantity.selection_range(0, "end")

    def commit_quantity(self):
        """A quantity that breaks a rule is refused and the old one comes back.
        Returns False only then."""
        if self.editing is None:
            return True
        section, widgets, old_text = self.editing
        self.editing = None
        quantity = section.cell(widgets, "Quantity")
        row = section.line_values(widgets)
        try:
            number = wd.validate_quantity(
                quantity.get(), row["UOM"], row[wd.RECEIVED_HEADER],
                fsr_store.ExcelStore(self.host.main_path())
                .remaining_quantity(row, self.host.control_no()))
        except wd.WithdrawalError as error:
            quantity.delete(0, "end")
            quantity.insert(0, old_text)
            quantity.configure(state="readonly")
            messagebox.showwarning("Withdrawal Quantity", str(error),
                                   parent=self.host.window)
            return False
        wd.set_quantity(row, number)
        if row["Quantity"] != old_text:
            self.host.mark_dirty()
        section.fill_line(widgets, row)
        section.update_subtotal()
        return True

    def _remove_line(self, section, widgets):
        lines = [section.line_values(other) for other in section.rows
                 if other is not widgets and section.line_values(other)]
        section.clear()
        section.set_values(lines)

    def remove_clicked(self):
        """Take the line clicked last out of the Item List."""
        section, widgets = self.clicked or (None, None)
        if (section is None or section not in self.host.sections()
                or widgets not in section.rows or not is_linked(widgets)):
            messagebox.showinfo(
                "Remove Line", "Click a PO line in the Item List first.",
                parent=self.host.window)
            return
        self.commit_quantity()
        self._remove_line(section, widgets)
        self.clicked = None
        self.host.mark_dirty()

    # ---- the report ----

    def reset(self):
        """A new report: nothing linked, nothing picked."""
        self.owned = False
        self.editing = None
        self.clicked = None
        self.found.clear()
        self.source_tree.delete(*self.source_tree.get_children())
        self.po_entry.delete(0, "end")
        self.sync()

    def load(self, owned):
        """A saved report was opened (its Item Lists are already filled)."""
        self.owned = owned
        self.sync()

    def fill_report(self, data):
        """Mark a report collected from the form when it has taken lines."""
        if self.linked():
            data["item_form"] = storage.ITEM_FORM_DEFAULT
            data["po_source_file"] = self.host.main_path().name
        return data

    def saved(self, data):
        """Keep the Line IDs given at save time, so the next save updates."""
        if not self.linked():
            return
        self.owned = True
        for section, saved in zip(self.host.sections(), data["item_lists"]):
            filled = [w for w in section.rows if section.line_values(w)]
            for widgets, row in zip(filled, saved["rows"]):
                widgets.po_link[wd.LINE_ID_HEADER] = row[wd.LINE_ID_HEADER]
        if self.po_entry.get().strip():     # the Remaining figures have changed
            self.find_po(quiet=True)
