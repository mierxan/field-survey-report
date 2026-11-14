"""The Item Lists tab: one section of item lines (ItemListSection) with its rows, totals, columns per Item List form and the PO-linked Withdrawal panel.

Moved here from field_survey_report.py (Phase 4). The code is unchanged
except that the names it takes from the program's window module are
read as `host.<name>`, at the moment they are used (bind() is called
by the window module)."""

from fsr_typeahead import Combobox as TypeaheadCombobox
from fsr_storage import CURRENCIES
from fsr_storage import ITEM_FORM_DEFAULT
from fsr_storage import ITEM_LINE_HEADERS
from fsr_storage import UNIT_NO_HEADER
from fsr_storage import UNIT_NO_LABELS
from fsr_storage import UOM_CHOICES
from fsr_storage import WEIGHT_UNIT_CHOICES
from fsr_storage import split_quantity_unit
from fsr_storage import to_number
import fsr_withdrawal
import fsr_withdrawal_ui


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


class ItemLine(list):
    """The entry widgets of one line, plus its hidden saved values."""

    def __init__(self):
        super().__init__()
        self.hidden = {}
        self.po_link = {}       # Withdrawal fields of a PO-linked line


class ItemListSection:
    """One 'Item List' card with its rows, buttons and subtotal. It shows
    the columns of the Item List form chosen for the report."""

    def __init__(self, parent, number):
        self.form = host.item_form_var.get()
        self.headers, self.widths = host.ITEM_FORM_COLUMNS[self.form]
        self.hidden_headers = [h for h in ITEM_LINE_HEADERS
                               if h not in self.headers]
        self.priced = "Total Price" in self.headers

        title = f"Item List {number}"
        if self.form != ITEM_FORM_DEFAULT:
            title += f" - {self.form}"
        self.frame = host.tb.Labelframe(parent, text=title, padding=10)
        self.frame.grid(row=number - 1, column=0, pady=6, sticky="we")
        self.rows = []          # list of ItemLine (Entry widgets)

        for col_index, header in enumerate(self.headers):
            heading = host.tb.Label(self.frame, text=self.label(header),
                               font=host.bold_font)
            heading.grid(
                row=0, column=col_index, padx=3, pady=(0, 4), sticky="w"
            )
            if header in host.ITEM_HEADER_TIPS:
                host.add_tip(heading, host.ITEM_HEADER_TIPS[header])

        toolbar = host.tb.Frame(self.frame)
        toolbar.grid(row=host.MAX_ROWS + 1, column=0,
                     columnspan=len(self.headers),
                     pady=(10, 0), sticky="we")
        toolbar.columnconfigure(3, weight=1)

        self.add_btn = host.tb.Button(
            toolbar, text="+ Add Line", width=20, command=self.add_line,
            bootstyle="primary-outline"
        )
        self.add_btn.grid(row=0, column=0, padx=(0, 6))

        self.remove_btn = host.tb.Button(
            toolbar, text="- Remove Line", command=self.remove_line,
            bootstyle="secondary-outline"
        )
        self.remove_btn.grid(row=0, column=1)

        self.counter_label = host.tb.Label(toolbar, anchor="w")
        self.counter_label.grid(row=0, column=2, padx=(15, 0), sticky="w")

        # Containerized / Loading have no prices: no subtotal.
        self.subtotal_label = host.tb.Label(toolbar, anchor="e", font=host.bold_font)
        if self.priced:
            self.subtotal_label.grid(row=0, column=3, sticky="e")

        for _ in range(5):
            self.create_row()
        self.update_buttons()
        self.update_subtotal()

    def label(self, header):
        """The heading shown for a column on this form."""
        if self.form == ITEM_FORM_DEFAULT:
            return header
        if header == UNIT_NO_HEADER:
            return UNIT_NO_LABELS[self.form]
        return host.UNIT_FORM_LABELS.get(header, header)

    def cell(self, widgets, header):
        return widgets[self.headers.index(header)]

    # ---- rows ----

    def create_row(self):
        row_no = len(self.rows) + 1
        widgets = ItemLine()

        for col_index, (header, width) in enumerate(
                zip(self.headers, self.widths)):
            if header == "UOM":
                entry = TypeaheadCombobox(self.frame, width=width,
                                    values=UOM_CHOICES)
                host.scroll_instead_of_change(entry)
            elif header == "Weight Unit":
                entry = TypeaheadCombobox(self.frame, width=width,
                                    values=WEIGHT_UNIT_CHOICES)
                host.scroll_instead_of_change(entry)
            elif header == "Currency":
                entry = TypeaheadCombobox(self.frame, width=width,
                                    values=[""] + CURRENCIES)
                entry.bind(
                    "<<ComboboxSelected>>",
                    lambda e, w=widgets: self.row_changed(w, "Currency"),
                    add="+")
                entry.bind(
                    "<FocusOut>",
                    lambda e, w=widgets: self.upper_currency(w), add="+")
                host.scroll_instead_of_change(entry)
            else:
                entry = host.tb.Entry(self.frame, width=width)
            entry.grid(row=row_no, column=col_index, padx=3, pady=2,
                       sticky="w")
            entry.manual_total = False
            entry.bind(
                "<KeyRelease>",
                lambda e, w=widgets, h=header: self.row_changed(w, h),
                add="+"
            )
            widgets.append(entry)

        self.cell(widgets, "Quantity").bind(
            "<FocusOut>", lambda e, w=widgets: self.split_quantity(w),
            add="+")
        self.cell(widgets, "Weights").bind(
            "<FocusOut>", lambda e, w=widgets: self.split_weight(w),
            add="+")
        fsr_withdrawal_ui.bind_line(self, widgets, lambda: host.withdrawal_panel)
        self.rows.append(widgets)
        host.refresh_findings_counter()

    def add_line(self):
        if len(self.rows) < host.MAX_ROWS:
            self.create_row()
            self.update_buttons()
            host.mark_dirty()

    def remove_line(self):
        if len(self.rows) > 1:
            for widget in self.rows.pop():
                widget.destroy()
            self.update_buttons()
            self.update_subtotal()
            host.refresh_findings_counter()
            host.mark_dirty()

    def set_row_count(self, count):
        """Used when a saved report is loaded or the form is cleared."""
        count = max(1, min(count, host.MAX_ROWS))
        while len(self.rows) < count:
            self.add_line()
        while len(self.rows) > count:
            self.remove_line()

    # ---- numbers ----

    def split_quantity(self, widgets):
        """'12 pcs' typed in Quantity -> Quantity 12, UOM PCS."""
        if fsr_withdrawal_ui.is_linked(widgets):
            return
        quantity_box = self.cell(widgets, "Quantity")
        uom_box = self.cell(widgets, "UOM")
        typed = quantity_box.get().strip()
        quantity, uom = split_quantity_unit(typed, uom_box.get())
        if quantity != typed:
            host.set_entry(quantity_box, quantity)
            host.set_entry(uom_box, uom.upper())
            self.row_changed(widgets, "Quantity")

    def split_weight(self, widgets):
        """'1,250 kg' typed in Weights -> Weights 1,250, Weight Unit KG."""
        weight_box = self.cell(widgets, "Weights")
        unit_box = self.cell(widgets, "Weight Unit")
        typed = weight_box.get().strip()
        weight, unit = split_quantity_unit(typed, unit_box.get())
        if weight != typed:
            host.set_entry(weight_box, weight)
            host.set_entry(unit_box, unit.upper())

    def upper_currency(self, widgets):
        """A typed currency 'usd' -> 'USD' (one subtotal per code)."""
        currency = self.cell(widgets, "Currency")
        typed = currency.get()
        if typed != typed.strip().upper():
            host.set_entry(currency, typed.strip().upper())
            self.update_subtotal()

    def row_changed(self, widgets, header):
        """Auto Total Price = Quantity x Unit Price (unless typed by hand)."""
        if self.priced:
            total = self.cell(widgets, "Total Price")

            if header == "Total Price":
                total.manual_total = bool(total.get().strip())
            elif header in ("Quantity", "Unit Price") and not total.manual_total:
                qty = to_number(self.cell(widgets, "Quantity").get())
                unit = to_number(self.cell(widgets, "Unit Price").get())
                numeric = (int, float)
                if isinstance(qty, numeric) and isinstance(unit, numeric):
                    host.set_entry(total, f"{qty * unit:,.2f}")
                else:
                    host.set_entry(total, "")
            if header in ("Unit Price", "Total Price"):
                self.default_currency(widgets)

        self.update_subtotal()
        self.update_buttons()
        host.refresh_findings_counter()

    def default_currency(self, widgets):
        """A line given a price takes the currency of the line above."""
        currency = self.cell(widgets, "Currency")
        if currency.get() or not (
                self.cell(widgets, "Unit Price").get().strip()
                or self.cell(widgets, "Total Price").get().strip()):
            return
        above = [self.cell(w, "Currency").get()
                 for w in self.rows[:self.rows.index(widgets)]
                 if self.cell(w, "Currency").get()]
        if above:
            currency.set(above[-1])

    def filled_count(self):
        return sum(
            1 for widgets in self.rows
            if any(w.get().strip() for w in widgets)
        )

    def subtotals(self):
        """{currency: amount}; '' for prices without a currency."""
        amounts = {}
        if not self.priced:
            return amounts
        for widgets in self.rows:
            value = to_number(self.cell(widgets, "Total Price").get())
            if isinstance(value, (int, float)):
                code = self.cell(widgets, "Currency").get()
                amounts[code] = amounts.get(code, 0.0) + value
        return amounts

    def update_subtotal(self):
        amounts = self.subtotals() or {"": 0.0}
        text = "  |  ".join(
            f"{code} {amount:,.2f}".strip()
            for code, amount in sorted(amounts.items()))
        self.subtotal_label.configure(text=f"Subtotal: {text}")

    def update_buttons(self):
        used = len(self.rows)
        self.add_btn.configure(
            text=host.add_button_text(used, host.MAX_ROWS),
            state="disabled" if used >= host.MAX_ROWS else "normal"
        )
        self.remove_btn.configure(state="disabled" if used <= 1 else "normal")
        host.update_line_counter(self.counter_label, used, host.MAX_ROWS)

    def line_values(self, widgets):
        """One line as {header: text} (every saved column), or None when
        it is empty."""
        row = {header: widget.get().strip()
               for header, widget in zip(self.headers, widgets)}
        weight, unit = split_quantity_unit(row["Weights"],
                                           row.pop("Weight Unit"))
        row["Weights"] = " ".join(filter(None, (weight, unit)))
        row.update({h: widgets.hidden.get(h, "")
                    for h in self.hidden_headers})
        row.update(widgets.po_link)
        return row if any(row[h] for h in host.SAVED_LINE_HEADERS) else None

    def values(self):
        """The filled lines as {header: text} (every saved column)."""
        return [row for row in map(self.line_values, self.rows) if row]

    def set_values(self, lines):
        """Fill rows from a list of {header: text} dictionaries."""
        self.set_row_count(max(5, len(lines)))
        for widgets, row in zip(self.rows, lines):
            self.fill_line(widgets, row)
        self.update_subtotal()
        host.refresh_findings_counter()

    def fill_line(self, widgets, row):
        """Fill one line from a {header: text} dictionary."""
        fsr_withdrawal_ui.unlock_line(self, widgets)
        row = dict(row)
        if not row.get(fsr_withdrawal.LINE_NO_HEADER):
            row["Quantity"], row["UOM"] = split_quantity_unit(
                row.get("Quantity"), row.get("UOM"))
        row["Weights"], row["Weight Unit"] = split_quantity_unit(
            row.get("Weights"))
        for header, widget in zip(self.headers, widgets):
            host.set_entry(widget, str(row.get(header) or ""))
        widgets.hidden = {h: str(row.get(h) or "")
                          for h in self.hidden_headers}
        if self.priced:
            total = self.cell(widgets, "Total Price")
            total.manual_total = bool(total.get().strip())
        fsr_withdrawal_ui.restore_link(self, widgets, row)

    def clear(self):
        for widgets in self.rows:
            fsr_withdrawal_ui.unlock_line(self, widgets)
            for widget in widgets:
                host.set_entry(widget, "")
                widget.manual_total = False
            widgets.hidden = {}
        self.update_subtotal()

    def destroy(self):
        self.frame.destroy()
