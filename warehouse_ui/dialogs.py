"""Detail panel and the case-status dialog."""

import tkinter
from tkinter import messagebox, ttk

import ttkbootstrap as tb

from warehouse.analytics import fmt_number, fmt_kg

from .components import Card


class DetailPanel(Card):
    """Label: value pairs of the selected record (read-only)."""

    def __init__(self, parent, title="Details", actions=()):
        super().__init__(parent, title)
        self.grid_frame = ttk.Frame(self.content, style="CardPlain.TFrame")
        self.grid_frame.grid(row=0, column=0, sticky="we")
        self.buttons = ttk.Frame(self.content, style="CardPlain.TFrame")
        self.buttons.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.action_buttons = []
        for text, command, style in actions:
            button = tb.Button(self.buttons, text=text, bootstyle=style,
                               command=command, state="disabled")
            button.pack(side="left", padx=(0, 6))
            self.action_buttons.append(button)
        self.show([])

    def show(self, pairs, enabled=True):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        if not pairs:
            ttk.Label(self.grid_frame, text="Select a row to see its details.",
                      style="CardMuted.TLabel").grid(row=0, column=0,
                                                     sticky="w")
            enabled = False
        columns = 3
        for index, (label, value) in enumerate(pairs):
            row, col = divmod(index, columns)
            cell = ttk.Frame(self.grid_frame, style="CardPlain.TFrame")
            cell.grid(row=row, column=col, sticky="nw", padx=(0, 24),
                      pady=(0, 6))
            ttk.Label(cell, text=label, style="CardMuted.TLabel").pack(
                anchor="w")
            ttk.Label(cell, text=value if value not in (None, "") else "-",
                      style="Card.TLabel", wraplength=300,
                      justify="left").pack(anchor="w")
        for col in range(columns):
            self.grid_frame.columnconfigure(col, weight=1, uniform="detail")
        for button in self.action_buttons:
            button.configure(state="normal" if enabled else "disabled")


def line_pairs(line):
    return [
        ("Transaction ID", line.line_id), ("Report Control #",
                                           line.control_no),
        ("Activity", line.activity),
        ("Date / Time", f"{line.date:%d-%b-%Y} {line.time}" if line.date
         else "No valid date"),
        ("SO Number", line.so_number), ("Cargo ID", line.cargo_id),
        ("Receiving Ref", line.receiving_ref),
        ("Cargo Description", line.description),
        ("PO Number", line.po_number),
        ("Supplier / Shipper", line.supplier), ("Consignee", line.consignee),
        ("Warehouse", line.warehouse),
        ("Quantity", f"{fmt_number(line.quantity)} {line.unit}"
         if line.quantity is not None else
         f"Not usable: {line.quantity_text or 'missing'}"),
        ("Weight", fmt_kg(line.weight_kg) if line.weight_kg is not None
         else (line.weight_text or "-") + (f" ({line.weight_note})"
                                           if line.weight_note else "")),
        ("Cargo Condition", line.condition),
        ("Findings", line.findings), ("Remarks", line.remarks),
        ("Data Check", "; ".join(line.problems) or "OK"),
    ]


def ask_case_status(ctx, side, control_no, on_saved):
    """Record a Bad Order case status (Open / Under Review / Resolved)."""
    from warehouse.store import CASE_STATUSES
    dialog = tb.Toplevel(ctx.window)
    dialog.title(f"Case Status - {control_no}")
    dialog.transient(ctx.window)
    dialog.resizable(False, False)
    body = ttk.Frame(dialog, padding=20)
    body.pack(fill="both", expand=True)
    current = side.case_statuses().get(control_no)
    ttk.Label(body, text=f"Bad Order case {control_no}",
              font=("Segoe UI", 11, "bold")).grid(row=0, column=0,
                                                  columnspan=2, sticky="w")
    ttk.Label(body, text=f"Current status: "
              f"{current['status'] if current else 'Not recorded'}",
              bootstyle="secondary").grid(row=1, column=0, columnspan=2,
                                          sticky="w", pady=(2, 10))
    status = tkinter.StringVar(value=current["status"] if current
                               else CASE_STATUSES[0])
    for col, value in enumerate(CASE_STATUSES):
        tb.Radiobutton(body, text=value, value=value, variable=status
                       ).grid(row=2, column=col if col < 2 else 0,
                              sticky="w", padx=(0, 14))
    ttk.Label(body, text="Note").grid(row=3, column=0, sticky="w",
                                      pady=(10, 0))
    note = tb.Entry(body, width=56)
    note.grid(row=4, column=0, columnspan=3, sticky="we")
    history = side.case_history(control_no)
    if history:
        ttk.Label(body, text="History: " + " → ".join(
            f"{h['status']} ({h['timestamp'][:10]}, {h['user']})"
            for h in history), bootstyle="secondary", wraplength=440
            ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def save():
        try:
            side.set_case_status(control_no, status.get(), ctx.user_name,
                                 note.get())
        except (ValueError, OSError) as error:
            messagebox.showerror("Case Status", str(error), parent=dialog)
            return
        dialog.destroy()
        on_saved()

    row = ttk.Frame(body)
    row.grid(row=6, column=0, columnspan=3, sticky="we", pady=(14, 0))
    tb.Button(row, text="Save", bootstyle="primary", width=10,
              command=save).pack(side="right")
    tb.Button(row, text="Cancel", bootstyle="secondary-outline", width=10,
              command=dialog.destroy).pack(side="right", padx=8)
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    return dialog
