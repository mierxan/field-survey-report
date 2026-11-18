"""One-click Findings for the Item Lists (both editions).

  * All Good Order and Complete - every item line's Findings becomes
    "Good Order and Complete" (lines that already say something else are
    replaced only when the inspector says so).
  * With Issues... - the inspector ticks the lines with an issue and types
    their findings; every other line becomes "Good Order and Complete".

Only the Findings boxes of the form change (the report is saved as usual).
A line's hidden Packing List No. is not touched; the With Issues window shows
it, so the inspector can check each Packing List.

`h` is the main module's globals (as in fsr_handover_ui).
"""
import tkinter as tk
from tkinter import messagebox, ttk

GOOD = "Good Order and Complete"
TITLE = "Findings"


def item_lines(h):
    """[(Item List no., line no., section, line widgets, Findings box)] of
    the filled lines shown on the form."""
    found = []
    for list_no, section in enumerate(h["item_frames"], start=1):
        if "Findings" not in section.headers:
            continue
        column = section.headers.index("Findings")
        number = 0
        for widgets in section.rows:
            if not section.line_values(widgets):
                continue
            number += 1
            found.append((list_no, number, section, widgets, widgets[column]))
    return found


def _describe(section, widgets):
    def cell(header):
        return widgets[section.headers.index(header)].get().strip() \
            if header in section.headers else ""
    quantity = " ".join(filter(None, (cell("Quantity"), cell("UOM"))))
    return " · ".join(filter(None, (cell("Description of Goods"),
                                    cell("PO Number") and
                                    f"PO {cell('PO Number')}", quantity)))


def _write(h, box, text):
    h["set_entry"](box, text)


def accept_all(h):
    """Every line: Good Order and Complete. Returns how many were filled."""
    window = h["window"]
    lines = item_lines(h)
    if not lines:
        messagebox.showinfo(TITLE, "There are no item lines yet.",
                            parent=window)
        return 0
    other = [line for line in lines
             if line[4].get().strip() not in ("", GOOD)]
    targets = lines
    if other:
        answer = messagebox.askyesnocancel(
            TITLE, f"{len(other)} line(s) already have other Findings.\n\n"
            f"Yes: write \"{GOOD}\" on EVERY line, replacing them.\n"
            f"No: write it only on the lines without Findings.\n"
            "Cancel: change nothing.", parent=window)
        if answer is None:
            return 0
        if answer is False:
            targets = [line for line in lines if not line[4].get().strip()]
    for *_, box in targets:
        _write(h, box, GOOD)
    if targets:
        h["mark_dirty"]()
    h["notify"](f"Findings: {len(targets)} line(s) set to \"{GOOD}\".")
    return len(targets)


def with_issues(h):
    """The window: tick the lines with an issue and type their findings;
    the other lines get Good Order and Complete. Returns the window."""
    window = h["window"]
    lines = item_lines(h)
    if not lines:
        messagebox.showinfo(TITLE, "There are no item lines yet.",
                            parent=window)
        return None
    dialog = tk.Toplevel(window)
    dialog.title("Findings - lines with issues")
    dialog.transient(window)
    dialog.geometry("1040x560")
    dialog.minsize(760, 380)
    body = ttk.Frame(dialog, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, wraplength=940, justify="left", text=(
        "Tick each line with an issue and type what you found. Every line "
        f"you do not tick gets \"{GOOD}\" when you click Apply.")).pack(
        anchor="w", pady=(0, 8))

    bar = ttk.Frame(body)
    bar.pack(side="bottom", fill="x", pady=(10, 0))
    summary = ttk.Label(body, text="")
    summary.pack(side="bottom", anchor="w", pady=(8, 0))

    holder = ttk.Frame(body)
    holder.pack(fill="both", expand=True)
    canvas = tk.Canvas(holder, highlightthickness=0, bd=0)
    scroll = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
    table = ttk.Frame(canvas)
    table.bind("<Configure>", lambda e: canvas.configure(
        scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=table, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    dialog.bind("<MouseWheel>", lambda e: canvas.yview_scroll(
        -1 if e.delta > 0 else 1, "units"))

    for column, (text, width) in enumerate((
            ("Issue", 6), ("Line", 10), ("Packing List", 20),
            ("Item", 36), ("Findings for this line", 30))):
        ttk.Label(table, text=text, font=("", 9, "bold"), width=width).grid(
            row=0, column=column, sticky="w", padx=4, pady=(0, 4))

    rows = []

    def refresh(*_):
        issues = sum(1 for flag, _, _ in rows if flag.get())
        summary.configure(text=f"{issues} line(s) with an issue; "
                          f"{len(rows) - issues} line(s) will be "
                          f"\"{GOOD}\".")

    for index, (list_no, line_no, section, widgets, box) in enumerate(
            lines, start=1):
        current = box.get().strip()
        flag = tk.BooleanVar(value=bool(current) and current != GOOD)
        text = tk.StringVar(value=current if flag.get() else "")
        entry = ttk.Entry(table, textvariable=text, width=34,
                          state="normal" if flag.get() else "disabled")

        def toggle(flag=flag, entry=entry):
            entry.configure(state="normal" if flag.get() else "disabled")
            if flag.get():
                entry.focus_set()
            refresh()

        ttk.Checkbutton(table, variable=flag, command=toggle).grid(
            row=index, column=0, padx=4, pady=2)
        ttk.Label(table, text=f"List {list_no} · {line_no}").grid(
            row=index, column=1, sticky="w", padx=4)
        ttk.Label(table, text=widgets.hidden.get("Packing List No.") or "-"
                  ).grid(row=index, column=2, sticky="w", padx=4)
        ttk.Label(table, text=_describe(section, widgets), width=40).grid(
            row=index, column=3, sticky="w", padx=4)
        entry.grid(row=index, column=4, sticky="we", padx=4, pady=2)
        rows.append((flag, text, box))
    refresh()

    def apply():
        missing = [i for i, (flag, text, _) in enumerate(rows, start=1)
                   if flag.get() and not text.get().strip()]
        if missing:
            messagebox.showwarning(
                TITLE, "Type the findings of every ticked line (or untick "
                "it).", parent=dialog)
            return
        for flag, text, box in rows:
            _write(h, box, text.get().strip() if flag.get() else GOOD)
        h["mark_dirty"]()
        issues = sum(1 for flag, _, _ in rows if flag.get())
        h["notify"](f"Findings: {issues} line(s) with an issue, "
                    f"{len(rows) - issues} \"{GOOD}\".")
        dialog.destroy()

    ttk.Button(bar, text="Apply", command=apply).pack(side="right")
    ttk.Button(bar, text="Cancel", command=dialog.destroy).pack(
        side="right", padx=6)
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.apply = apply                      # for the tests
    dialog.rows = rows
    return dialog
