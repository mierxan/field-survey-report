"""The Export Master Data window (both editions).

It asks first what goes into the file: all data (every saved report, as
before) or only the saved reports the inspector chooses, for example one new
Withdrawal report. Both kinds of saved report are listed: those of the main
workbook and the PO-linked Withdrawal reports. The work itself is
fsr_master_export; nothing here changes a report.

`h` is the main module's globals (as in fsr_handover_ui): names are looked
up when they are used.
"""
import socket
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

import fsr_master_export
import fsr_storage as storage

TITLE = "Export Master Data"
ALL = "all"
CHOSEN = "chosen"
KIND_TEXT = {"report": "Report", "withdrawal": "Withdrawal (PO-linked)"}


def file_name(device, controls, day):
    """FSR_Master_Data_<PC>_<date>.json for all data; with the Control # for
    one chosen report, or the number of reports for several."""
    clean = storage.safe_filename
    middle = ""
    if controls is not None:
        middle = (f"_{clean(controls[0])}" if len(controls) == 1
                  else f"_{len(controls)}_reports")
    return f"FSR_Master_Data_{clean(device)}{middle}_{day:%Y-%m-%d}.json"


def open_export(h):
    """Show the window. Returns it (None when nothing can be listed)."""
    window = h["window"]
    path = h["excel_state"]["path"]
    try:
        rows = h["busy"](fsr_master_export.saved_reports, path)
    except (OSError, ValueError) as error:
        h["log"].exception("Export Master Data: the reports were not listed")
        messagebox.showerror(TITLE, f"The saved reports could not be "
                             f"read:\n{error}", parent=window)
        return None

    dialog = tk.Toplevel(window)
    dialog.title(TITLE)
    dialog.transient(window)
    dialog.geometry("1040x600")
    dialog.minsize(760, 480)
    body = ttk.Frame(dialog, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, wraplength=1000, justify="left", text=(
        "The Master Data file is for the owner. Do you want to export all "
        "data, or only the reports you choose? Only SAVED reports are "
        "exported. Sending a report again later is fine: the owner's import "
        "does not duplicate it, and reports left out of the file are not "
        "removed at the owner.")).pack(anchor="w", pady=(0, 8))

    choice = tk.StringVar(dialog, value=ALL)
    ttk.Radiobutton(
        body, variable=choice, value=ALL,
        text=f"All data: every saved report ({len(rows)}), the master lists "
        "and the Bad Order case statuses").pack(anchor="w")
    ttk.Radiobutton(
        body, variable=choice, value=CHOSEN,
        text="Only the reports I choose below (with the master lists)"
    ).pack(anchor="w", pady=(2, 8))

    search_row = ttk.Frame(body)
    search_row.pack(fill="x")
    ttk.Label(search_row, text="Search:").pack(side="left")
    search_text = tk.StringVar(dialog)  # typed or pasted, both filter
    search = ttk.Entry(search_row, width=40, textvariable=search_text)
    search.pack(side="left", padx=6)
    select_all = ttk.Button(search_row, text="Select All Shown")
    select_all.pack(side="left", padx=4)
    clear = ttk.Button(search_row, text="Clear Selection")
    clear.pack(side="left", padx=4)

    middle = ttk.Frame(body)
    middle.pack(fill="both", expand=True, pady=8)
    columns = (("control", "Control #", 170), ("so", "SO Number", 130),
               ("date", "Inspection Date", 125),
               ("consignee", "Consignee", 185), ("saved", "Last Saved", 150),
               ("kind", "Type", 170))
    tree = ttk.Treeview(middle, columns=[c[0] for c in columns],
                        show="headings", height=12, selectmode="extended")
    for key, text, width in columns:
        tree.heading(key, text=text)
        tree.column(key, width=width, anchor="w",
                    stretch=key == "consignee")
    scroll = ttk.Scrollbar(middle, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    summary = ttk.Label(body, text="")
    summary.pack(anchor="w")
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(10, 0))
    export_button = ttk.Button(bar, text="Export...")
    export_button.pack(side="left", padx=4)
    ttk.Button(bar, text="Cancel", command=dialog.destroy).pack(side="right")

    by_iid = {str(index): row for index, row in enumerate(rows)}
    chosen = set()            # control_key() of the chosen reports
    filling = {"now": False}

    def picked_controls():
        """The chosen Control #s in the order listed."""
        return [row[0] for row in rows
                if storage.control_key(row[0]) in chosen]

    def update():
        count = len(picked_controls())
        if choice.get() == ALL:
            summary.configure(text=f"All {len(rows)} saved report(s) will "
                              "be exported.")
            export_button.configure(state="normal")
        else:
            summary.configure(text=f"{count} report(s) chosen." if count
                              else "Choose one or more reports in the list "
                              "(Ctrl or Shift + click for several).")
            export_button.configure(state="normal" if count else "disabled")

    def fill():
        filling["now"] = True
        try:
            tree.delete(*tree.get_children())
            # search_text (not search) keeps the variable and its trace alive
            wanted = search_text.get().strip().casefold()
            for iid, row in by_iid.items():
                text = " ".join(str(v) for v in row[:4]).casefold()
                if wanted and wanted not in text:
                    continue
                tree.insert("", "end", iid=iid, values=(
                    row[0], row[1], row[2], row[3], row[4],
                    KIND_TEXT.get(row[5], row[5])))
                if storage.control_key(row[0]) in chosen:
                    tree.selection_add(iid)
        finally:
            filling["now"] = False
        update()

    def selection_changed(_=None):
        if filling["now"]:
            return
        selected = set(tree.selection())
        before = set(chosen)
        for iid in tree.get_children():
            key = storage.control_key(by_iid[iid][0])
            if iid in selected:
                chosen.add(key)
            else:
                chosen.discard(key)
        if chosen - before and choice.get() != CHOSEN:
            choice.set(CHOSEN)          # choosing a report means "only these"
        update()

    def select_shown():
        tree.selection_set(tree.get_children())
        selection_changed()

    def clear_selection():
        chosen.clear()
        tree.selection_remove(tree.selection())
        update()

    def export():
        controls = None if choice.get() == ALL else picked_controls()
        if controls is not None and not controls:
            return
        device = socket.gethostname()
        target = filedialog.asksaveasfilename(
            parent=dialog, title="Save the Master Data file for the owner",
            defaultextension=".json",
            initialfile=file_name(device, controls, date.today()),
            filetypes=[("Master data file", "*.json")])
        if not target:
            return
        try:
            count = h["busy"](fsr_master_export.write_export, path, target,
                              device, h.get("USER_FULL_NAME") or "",
                              h.get("master_data"), controls)
        except Exception as error:
            h["log"].exception("Export Master Data failed")
            messagebox.showerror(TITLE, f"The file was not written:\n{error}",
                                 parent=dialog)
            return
        which = ""
        if controls is not None:
            listed = "\n".join(f"  {c}" for c in controls[:15])
            more = len(controls) - 15
            which = f"\n\nThe chosen report(s):\n{listed}" + (
                f"\n  ... and {more} more" if more > 0 else "")
        messagebox.showinfo(
            TITLE, f"{count} report(s) saved to:\n{target}{which}\n\nSend "
            "this one file to the owner. Sending it again later is fine: "
            "reports the owner already has are not duplicated.",
            parent=dialog)
        dialog.destroy()

    tree.bind("<<TreeviewSelect>>", selection_changed)
    search_text.trace_add("write", lambda *_: fill())
    choice.trace_add("write", lambda *_: update())
    select_all.configure(command=select_shown)
    clear.configure(command=clear_selection)
    export_button.configure(command=export)
    fill()
    h["master_export_state"]["dialog"] = dialog
    return dialog
