"""The Share with Destination window (both editions).

`h` is the main module's globals (as in fsr_handover_ui): names are looked
up when they are used. The work itself is fsr_shipment; the Withdrawal
report is only read.
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fsr_handover_ui
import fsr_shipment

TITLE = "Share with Destination"


def _report_row(report):
    general = report.get("general_information") or {}
    found = fsr_shipment.groups(report)
    lines = sum(len(g["lines"]) for g in found)
    numbered = sum(1 for g in found if g["number"])
    return (report["control_no"], general.get("inspection_date", ""),
            general.get("location", ""), general.get("destination", ""),
            lines, numbered)


def _known_destination(h, text):
    """The master list spelling of `text` when it is one destination."""
    wanted = str(text or "").strip().casefold()
    names = (h.get("master_data") or {}).get(h.get("DESTINATION_LIST_KEY")
                                             or "destination_list", [])
    return next((n for n in names if n.casefold() == wanted), "")


def open_share(h):
    window = h["window"]
    state = h["report_state"]
    if state["dirty"]:
        answer = messagebox.askyesnocancel(
            TITLE, "The form has changes that are not saved yet. A shipment "
            "is made from the SAVED report only.\n\nYes: save the report "
            "first.\nNo: go on without the unsaved changes.\nCancel: go back "
            "to the form.", parent=window)
        if answer is None:
            return None
        if answer and (not h["save_report"]() or state["dirty"]):
            return None
    path = h["excel_state"]["path"]
    store = h["data_store"](path)
    try:
        reports = h["busy"](fsr_shipment.withdrawal_reports, store)
    except (OSError, ValueError) as error:
        messagebox.showerror(TITLE, f"The reports could not be read:\n"
                             f"{error}", parent=window)
        return None
    if not reports:
        messagebox.showinfo(TITLE, "There is no saved Withdrawal report to "
                            "share.", parent=window)
        return None
    destinations = list((h.get("master_data") or {}).get(
        h.get("DESTINATION_LIST_KEY") or "destination_list", []))

    dialog = tk.Toplevel(window)
    dialog.title("Share a Withdrawal Item List with its Destinations")
    dialog.transient(window)
    dialog.geometry("980x700")
    dialog.minsize(820, 560)
    body = ttk.Frame(dialog, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, wraplength=940, justify="left", text=(
        "1. Choose the Withdrawal report.  2. Select Packing Lists and give "
        "them their destination.  3. Create the files: one file per "
        "destination, holding only its Packing Lists. Send each file to "
        "its destination; there the item list comes in as a Receiving "
        "draft, so it is not typed again. Only the cargo details travel "
        "(no prices, SO Number or Supplier). The Withdrawal report itself "
        "is not changed.")).pack(anchor="w", pady=(0, 8))

    reports_label = ttk.Label(body, text="Withdrawal reports",
                              font=("", 10, "bold"))
    reports_label.pack(anchor="w")
    top = ttk.Frame(body)
    top.pack(fill="both", expand=True)
    columns = (("control", "Control #", 170), ("date", "Date", 100),
               ("location", "Location", 190), ("dest", "Destination", 190),
               ("lines", "Lines", 60), ("pls", "Packing Lists", 115))
    reports_tree = ttk.Treeview(top, columns=[c[0] for c in columns],
                                show="headings", height=7,
                                selectmode="browse")
    for key, text, width in columns:
        reports_tree.heading(key, text=text)
        reports_tree.column(key, width=width, anchor="e" if key in (
            "lines", "pls") else "w", stretch=key in ("location", "dest"))
    scroll = ttk.Scrollbar(top, orient="vertical",
                           command=reports_tree.yview)
    reports_tree.configure(yscrollcommand=scroll.set)
    reports_tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    by_iid = {}
    for index, report in enumerate(reversed(reports)):
        iid = str(index)
        by_iid[iid] = report
        reports_tree.insert("", "end", iid=iid, values=_report_row(report))

    ttk.Label(body, text="Packing Lists of the chosen report",
              font=("", 10, "bold")).pack(anchor="w", pady=(10, 0))
    middle = ttk.Frame(body)
    middle.pack(fill="both", expand=True)
    pl_columns = (("number", "Packing List No.", 190),
                  ("pos", "PO Numbers", 330), ("lines", "Lines", 60),
                  ("dest", "Destination", 200))
    pl_tree = ttk.Treeview(middle, columns=[c[0] for c in pl_columns],
                           show="headings", height=8, selectmode="extended")
    for key, text, width in pl_columns:
        pl_tree.heading(key, text=text)
        pl_tree.column(key, width=width, anchor="e" if key == "lines"
                       else "w", stretch=key == "pos")
    pl_scroll = ttk.Scrollbar(middle, orient="vertical",
                              command=pl_tree.yview)
    pl_tree.configure(yscrollcommand=pl_scroll.set)
    pl_tree.pack(side="left", fill="both", expand=True)
    pl_scroll.pack(side="right", fill="y")

    assign_row = ttk.Frame(body)
    assign_row.pack(fill="x", pady=(8, 0))
    ttk.Label(assign_row, text="Destination for the selected Packing "
              "Lists:").pack(side="left")
    destination_box = ttk.Combobox(assign_row, values=destinations,
                                   width=30)
    destination_box.pack(side="left", padx=6)
    assign_button = ttk.Button(assign_row, text="Assign")
    assign_button.pack(side="left")
    clear_button = ttk.Button(assign_row, text="Remove Destination")
    clear_button.pack(side="left", padx=6)
    select_all = ttk.Button(assign_row, text="Select All")
    select_all.pack(side="left")

    summary = ttk.Label(body, text="", justify="left", wraplength=940)
    summary.pack(anchor="w", pady=(8, 0))
    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(10, 0))
    create_button = ttk.Button(bar, text="Create Shipment Files...")
    create_button.pack(side="left")
    ttk.Button(bar, text="Close", command=dialog.destroy).pack(side="right")
    # the buttons and the summary keep their room; the two lists share the
    # rest (packed first, at the bottom)
    for widget, gap in ((bar, (10, 0)), (summary, (8, 0)),
                        (assign_row, (8, 0))):
        widget.pack_configure(side="bottom", before=reports_label, pady=gap)

    current = {"report": None, "groups": [], "assign": {}}

    def chosen_report():
        picked = reports_tree.selection()
        return by_iid.get(picked[0]) if picked else None

    def refresh_groups():
        pl_tree.delete(*pl_tree.get_children())
        for index, group in enumerate(current["groups"]):
            pl_tree.insert("", "end", iid=str(index), values=(
                fsr_shipment.label(group["number"]),
                ", ".join(group["po_numbers"]), len(group["lines"]),
                current["assign"].get(group["number"], "")))
        refresh_summary()

    def refresh_summary():
        per = {}
        for group in current["groups"]:
            destination = current["assign"].get(group["number"])
            if destination:
                entry = per.setdefault(destination, [0, 0])
                entry[0] += 1
                entry[1] += len(group["lines"])
        if current["report"] is None:
            text = "Choose a Withdrawal report above."
        elif not per:
            text = ("No Packing List has a destination yet: select them, "
                    "choose the destination and click Assign.")
        else:
            left = sum(1 for g in current["groups"]
                       if not current["assign"].get(g["number"]))
            text = (f"{len(per)} file(s) will be made: " + "; ".join(
                f"{d} - {n} Packing List(s), {lines} line(s)"
                for d, (n, lines) in per.items())
                + (f".  Not shared: {left} Packing List(s) without a "
                   "destination." if left else "."))
        summary.configure(text=text)
        create_button.configure(state="normal" if per else "disabled")

    def report_chosen(_=None):
        report = chosen_report()
        current["report"] = report
        current["groups"] = fsr_shipment.groups(report) if report else []
        current["assign"] = {}
        if report is not None:
            # the report's own destination, when it is one known destination
            known = _known_destination(h, (report.get(
                "general_information") or {}).get("destination"))
            if known:
                current["assign"] = {g["number"]: known
                                     for g in current["groups"]}
                destination_box.set(known)
        refresh_groups()

    def selected_numbers():
        return [current["groups"][int(i)]["number"]
                for i in pl_tree.selection()]

    def assign():
        numbers = selected_numbers()
        destination = destination_box.get().strip()
        if not numbers:
            messagebox.showinfo(TITLE, "Select one or more Packing Lists "
                                "first.", parent=dialog)
            return
        if not destination:
            messagebox.showinfo(TITLE, "Choose the destination first.",
                                parent=dialog)
            destination_box.focus_set()
            return
        known = _known_destination(h, destination)
        if not known and not messagebox.askyesno(
                TITLE, f'"{destination}" is not in the Destination master '
                "list. The destination brings the file in only under this "
                "exact name.\n\nUse it anyway?", parent=dialog):
            return
        for number in numbers:
            current["assign"][number] = known or destination
        keep = pl_tree.selection()
        refresh_groups()
        pl_tree.selection_set(keep)

    def clear():
        for number in selected_numbers():
            current["assign"].pop(number, None)
        keep = pl_tree.selection()
        refresh_groups()
        pl_tree.selection_set(keep)

    def create():
        report = current["report"]
        if report is None:
            return
        folder = filedialog.askdirectory(
            parent=dialog, title="Choose the folder for the shipment files",
            mustexist=True)
        if not folder:
            return
        try:
            written = h["busy"](
                fsr_shipment.write_shipments, store, report["control_no"],
                dict(current["assign"]), folder,
                fsr_handover_ui.sender(h))
        except (fsr_shipment.ShipmentError, OSError, ValueError) as error:
            h["log"].exception("Shipment files not made")
            messagebox.showerror(TITLE, f"No file was made:\n{error}",
                                 parent=dialog)
            return
        listing = "\n".join(f"  {d}:  {p.name}" for d, p, _ in written)
        h["log"].info("Shipment files of %s: %s", report["control_no"],
                      ", ".join(str(p) for _, p, _ in written))
        messagebox.showinfo(
            TITLE, f"{len(written)} shipment file(s) saved in:\n{folder}\n\n"
            f"{listing}\n\nSend each file to its destination (e-mail, chat "
            f"or USB stick). Withdrawal report {report['control_no']} was "
            "not changed.", parent=dialog)

    reports_tree.bind("<<TreeviewSelect>>", report_chosen)
    assign_button.configure(command=assign)
    clear_button.configure(command=clear)
    select_all.configure(command=lambda: pl_tree.selection_set(
        pl_tree.get_children()))
    create_button.configure(command=create)
    dialog.bind("<Escape>", lambda e: dialog.destroy())

    # the report open on the form, when it is a saved Withdrawal report
    open_control = h["control_entry"].get().strip()
    pick = next((iid for iid, r in by_iid.items()
                 if state["editing"] and r["control_no"].strip().casefold()
                 == open_control.casefold()), None)
    if pick is not None:
        reports_tree.selection_set(pick)
        reports_tree.see(pick)
        report_chosen()
    else:
        refresh_summary()
    h["shipment_state"]["dialog"] = dialog
    return dialog


# =====================================================================
# Receive Shipment (the destination)
# =====================================================================

RECEIVE_TITLE = "Receive Shipment"


def destinations_of(h):
    return list((h.get("master_data") or {}).get(
        h.get("DESTINATION_LIST_KEY") or "destination_list", []))


def choose_destination(h, parent, current=""):
    """Asks for this PC's destination (the Destination master list); saves
    it in the settings. Returns the name, or None when cancelled."""
    names = destinations_of(h)
    dialog = tk.Toplevel(parent)
    dialog.title("This PC's destination")
    dialog.transient(parent)
    dialog.resizable(False, False)
    body = ttk.Frame(dialog, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, wraplength=420, justify="left", text=(
        "Which destination does this PC receive shipments for? Only shipment "
        "files made for this destination can be imported here. (This is a "
        "check against mistakes, not a security lock.)")).pack(anchor="w")
    box = ttk.Combobox(body, values=names, state="readonly", width=34)
    box.pack(anchor="w", pady=10)
    if current in names:
        box.set(current)
    chosen = {"value": None}

    def ok():
        name = box.get().strip()
        if not name:
            messagebox.showinfo("This PC's destination", "Choose the "
                                "destination first.", parent=dialog)
            return
        if current and name != current and not messagebox.askyesno(
                "This PC's destination",
                f"Change this PC's destination from {current} to {name}?\n\n"
                f"Shipments for {current} can then no longer be imported "
                "here.", parent=dialog):
            return
        chosen["value"] = name
        dialog.destroy()

    row = ttk.Frame(body)
    row.pack(fill="x")
    ttk.Button(row, text="Save", command=ok).pack(side="right")
    ttk.Button(row, text="Cancel", command=dialog.destroy).pack(
        side="right", padx=6)
    if not names:
        ttk.Label(body, foreground="red", wraplength=420, text=(
            "The Destination master list is empty. Add the destinations in "
            "Master Lists and Settings first.")).pack(anchor="w", pady=(8, 0))
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.wait_visibility()
    dialog.grab_set()
    dialog.wait_window()
    name = chosen["value"]
    if name:
        h["settings"][fsr_shipment.SETTING] = name
        h["save_settings"]()
    return name


def open_receive(h, chosen=None):
    """Storage > Receive Shipment...: this PC's destination, then a shipment
    file into a new Receiving draft. `chosen`: a file opened from Windows.
    Returns the new draft value, or None."""
    window = h["window"]
    destination = fsr_shipment.site_destination(h["settings"])
    if not destination:
        messagebox.showinfo(
            RECEIVE_TITLE, "First set which destination this PC receives "
            "shipments for (once).", parent=window)
        destination = choose_destination(h, window)
        if not destination:
            return None
    if chosen is None:
        dialog = tk.Toplevel(window)
        dialog.title(RECEIVE_TITLE)
        dialog.transient(window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, wraplength=460, justify="left", text=(
            "A shipment file (.fsrshipment) holds the Packing Lists a "
            "Withdrawal sends to this destination. It becomes a new "
            "Receiving draft with the item list already in it: you fill in "
            "the First Page and the Findings, then save the report.")).pack(
            anchor="w")
        where = ttk.Frame(body)
        where.pack(fill="x", pady=12)
        shown = ttk.Label(where, text=f"This PC's destination:  "
                          f"{destination}", font=("", 10, "bold"))
        shown.pack(side="left")
        picked = {"file": None}

        def change():
            nonlocal destination
            name = choose_destination(h, dialog, destination)
            if name:
                destination = name
                shown.configure(text=f"This PC's destination:  {name}")

        def pick():
            path = filedialog.askopenfilename(
                parent=dialog, title="Choose the shipment file",
                filetypes=[("Shipment file", "*" + fsr_shipment.SUFFIX),
                           ("All files", "*.*")])
            if path:
                picked["file"] = path
                dialog.destroy()

        ttk.Button(where, text="Change...", command=change).pack(
            side="left", padx=10)
        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Button(row, text="Choose Shipment File...", command=pick).pack(
            side="left")
        ttk.Button(row, text="Close", command=dialog.destroy).pack(
            side="right")
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        h["shipment_state"]["dialog"] = dialog
        dialog.wait_visibility()
        dialog.grab_set()
        dialog.wait_window()
        chosen = picked["file"]
        if not chosen:
            return None
    return receive_file(h, chosen, destination)


def receive_file(h, chosen, destination=None):
    """One shipment file into a new Receiving draft (asks first)."""
    window = h["window"]
    destination = destination or fsr_shipment.site_destination(h["settings"])
    path = h["excel_state"]["path"]
    controller = h.get("draft_controller")
    if controller is None:
        messagebox.showerror(RECEIVE_TITLE, "Drafts are not available on "
                             "this PC, so the shipment cannot be imported.",
                             parent=window)
        return None
    try:
        payload = fsr_shipment.read_file(chosen)
        store = h["data_store"](path)
        h["busy"](fsr_shipment.check_import, path, payload, destination,
                  store, controller.store)
    except fsr_shipment.ShipmentError as error:
        messagebox.showerror(RECEIVE_TITLE, f"Nothing was imported.\n\n"
                             f"{error}", parent=window)
        return None
    if not messagebox.askyesno(
            RECEIVE_TITLE, fsr_shipment.describe_import(payload)
            + f"\n\nThis PC's destination: {destination}  (matches)\n\n"
            "Make a new Receiving draft with these lines? The First Page "
            "stays empty and the Findings are left for you; the Packing "
            "List numbers are kept with the lines.", parent=window):
        return None
    try:
        value = h["busy"](
            fsr_shipment.import_shipment, path, payload, destination, store,
            controller.store, (h.get("current_user") or {}).get(
                "initials", ""),
            lambda data: fsr_handover_ui.form_of(h, data))
    except (fsr_shipment.ShipmentError, OSError, ValueError) as error:
        h["log"].exception("Shipment not imported")
        messagebox.showerror(RECEIVE_TITLE, f"Nothing was imported.\n\n"
                             f"{error}", parent=window)
        return None
    h["log"].info("Shipment %s of %s imported as draft %s",
                  payload["transfer_id"], payload["origin"]["control_no"],
                  value["id"])
    if messagebox.askyesno(
            RECEIVE_TITLE, "The Receiving draft was made. It is in Account "
            "> Unfinished work.\n\nOpen it now?", parent=window):
        try:
            controller.restore(value)
        except Exception as error:          # it stays in Unfinished work
            h["log"].exception("The imported draft could not be opened")
            messagebox.showwarning(
                RECEIVE_TITLE, f"The draft is in Account > Unfinished work; "
                f"it could not be opened here:\n{error}", parent=window)
    return value
