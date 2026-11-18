"""The Hand Over and Receive Hand-over windows (both editions).

`h` is the main module's globals (as in fsr_drafts_ui): names are looked up
when they are used. The work itself is fsr_handover.
"""
import copy
import re
import socket
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import fsr_draft_form
import fsr_handover
import fsr_incoming
import fsr_storage as storage

TITLE = "Hand Over"
RECEIVE_TITLE = "Receive Hand-over"


def sender(h):
    user = h.get("current_user") or {}
    return {"inspector": h.get("USER_FULL_NAME") or "",
            "initials": user.get("initials", ""),
            "device_id": socket.gethostname()}


def _safe(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_") or "Draft"


def _day(text):
    try:
        return datetime.fromisoformat(str(text)).astimezone().strftime(
            "%Y-%m-%d %H:%M")
    except ValueError:
        return str(text or "")[:16]


def form_of(h, data):
    """The draft form of a report in the Windows data shape (a draft from
    the phone app), made by the form itself: it is filled as when a saved
    report is opened, read, and put back exactly as it was. Nothing is
    shown in between and no draft is written."""
    controller = h.get("draft_controller")
    state = h["report_state"]
    before = (fsr_draft_form.capture(h), dict(state),
              h["control_entry"].get(), h["notebook"].select())
    muted = controller.muted if controller is not None else None
    if controller is not None:
        controller.muted = True
    try:
        h["populate_form"](copy.deepcopy(data))
        return fsr_draft_form.capture(h)
    finally:
        try:
            fsr_draft_form.restore(h, before[0])
            state.clear()
            state.update(before[1])
            h["set_control_number"](before[2])
            h["notebook"].select(before[3])
        finally:
            if controller is not None:
                controller.muted = muted
        h["update_status"]()


def rows(h, path, controller):
    """What can be handed over: this account's drafts of this workbook,
    then the saved reports of the main workbook."""
    result = []
    if controller is not None:
        found, _ = controller.store.list()
        for value in found:
            try:
                same = (Path(value["workbook"]).resolve()
                        == Path(path).resolve())
            except OSError:
                same = False
            if not same:
                continue
            away = value.get("handed_over")
            status = (f"Handed over to {away.get('to') or '?'} on "
                      f"{_day(away.get('at'))}" if away else "")
            kept = fsr_handover._kept(value.get("received"))
            result.append({
                "kind": "draft", "value": value,
                "control": value["control"] or "",
                "label": value["control"] or (kept or {}).get("control")
                or "New report",
                "so": value["form"].get("simple", {}).get(
                    "SO_number_entry", ""),
                "when": _day(value["changed"]), "status": status,
                "away": bool(away)})
    record = fsr_handover.load(path)
    for control, so, day, *_ in h["data_store"](path).list_reports():
        _, entry = fsr_handover.find(record, control)
        away = entry is not None and \
            entry.get("state") == fsr_handover.HANDED_OVER
        status = (f"Handed over to {entry.get('to') or '?'} on "
                  f"{_day(entry.get('at'))}" if away else "")
        result.append({"kind": "report", "control": control,
                       "label": control, "so": so or "",
                       "when": str(day or ""), "status": status,
                       "away": away})
    return result


def open_hand_over(h):
    window = h["window"]
    state = h["report_state"]
    controller = h.get("draft_controller")
    if state["dirty"]:
        answer = messagebox.askyesnocancel(
            TITLE,
            "The form has changes that are not saved yet.\n\n"
            "Yes: save the report first, then hand it over.\n"
            "No: keep the changes as a draft, to hand over the draft.\n"
            "Cancel: go back to the form.", parent=window)
        if answer is None:
            return None
        if answer:
            if not h["save_report"]() or state["dirty"]:
                return None
        elif controller is None or not controller.flush():
            messagebox.showwarning(
                TITLE, "The changes could not be kept as a draft. Save the "
                "report instead.", parent=window)
            return None
    path = h["excel_state"]["path"]
    owner_edition = bool(h.get("IS_OWNER_EDITION"))
    try:
        items = rows(h, path, controller)
    except (OSError, ValueError) as error:
        messagebox.showerror(TITLE, str(error), parent=window)
        return None

    dialog = tk.Toplevel(window)
    dialog.title("Hand Over to the Next Inspector")
    dialog.transient(window)
    dialog.geometry("860x560")
    body = ttk.Frame(dialog, padding=14)
    body.pack(fill="both", expand=True)
    ttk.Label(body, wraplength=820, justify="left", text=(
        "Choose the report or unfinished draft that the next inspector will "
        "finish. One file is saved: send it to them (e-mail, chat or USB "
        "stick). They open it with Receive Hand-over, on a PC or on the "
        "phone app. The report keeps its Control #. Your copy stays here, "
        "marked handed over: you can open and print it, not save it."
    )).pack(anchor="w", pady=(0, 8))

    search_row = ttk.Frame(body)
    search_row.pack(fill="x")
    ttk.Label(search_row, text="Search:").pack(side="left")
    search = ttk.Entry(search_row, width=40)
    search.pack(side="left", padx=6)

    tree = ttk.Treeview(body, columns=("type", "report", "so", "when",
                                       "status"),
                        show="headings", height=12, selectmode="browse")
    for name, label, width in [("type", "Type", 70),
                               ("report", "Control #", 170),
                               ("so", "SO Number", 140),
                               ("when", "Date", 120),
                               ("status", "Status", 300)]:
        tree.heading(name, text=label)
        tree.column(name, width=width, anchor="w")
    tree.pack(fill="both", expand=True, pady=8)

    form = ttk.Frame(body)
    form.pack(fill="x")
    ttk.Label(form, text="Next inspector:").grid(row=0, column=0, sticky="w")
    to_entry = ttk.Entry(form, width=40)
    to_entry.grid(row=0, column=1, sticky="w", padx=6, pady=2)
    ttk.Label(form, text="Note (optional):").grid(row=1, column=0,
                                                  sticky="w")
    note_entry = ttk.Entry(form, width=80)
    note_entry.grid(row=1, column=1, sticky="w", padx=6, pady=2)

    bar = ttk.Frame(body)
    bar.pack(fill="x", pady=(10, 0))
    hand_button = ttk.Button(bar, text="Hand Over...")
    hand_button.pack(side="left", padx=4)
    cancel_button = ttk.Button(bar, text="Cancel Hand-over")
    cancel_button.pack(side="left", padx=4)
    ttk.Button(bar, text="Close", command=dialog.destroy).pack(side="right")

    shown = {}

    def fill(select=None):
        nonlocal items
        tree.delete(*tree.get_children())
        shown.clear()
        wanted = search.get().strip().casefold()
        for index, item in enumerate(items):
            if wanted and wanted not in (
                    f"{item['label']} {item['so']}".casefold()):
                continue
            iid = str(index)
            shown[iid] = item
            tree.insert("", "end", iid=iid, values=(
                "Draft" if item["kind"] == "draft" else "Report",
                item["label"], item["so"], item["when"], item["status"]))
        if select is not None and select in shown:
            tree.selection_set(select)
            tree.see(select)
        changed()

    def selected():
        picked = tree.selection()
        return shown.get(picked[0]) if picked else None

    def changed(_=None):
        item = selected()
        hand_button.configure(state="normal" if item and not (
            item["kind"] == "draft" and item["away"]) else "disabled")
        cancel_button.configure(state="normal" if item and item["kind"]
                                == "report" and item["away"] else "disabled")

    def reload(select_control=None):
        nonlocal items
        try:
            items = rows(h, path, controller)
        except (OSError, ValueError) as error:
            messagebox.showerror(TITLE, str(error), parent=dialog)
            return
        select = None
        for index, item in enumerate(items):
            if item["kind"] == "report" and select_control and \
                    storage.same_key(item["control"],
                                                  select_control):
                select = str(index)
        fill(select)

    def hand_over():
        item = selected()
        if item is None:
            return
        to = to_entry.get().strip()
        if not to:
            messagebox.showwarning(
                TITLE, "Type the name of the next inspector first.",
                parent=dialog)
            to_entry.focus_set()
            return
        if item["away"] and not messagebox.askyesno(
                TITLE, f"{item['label']} is already handed over "
                f"({item['status']}).\n\nMake the file again?",
                parent=dialog):
            return
        target = filedialog.asksaveasfilename(
            parent=dialog, title="Save the hand-over file",
            defaultextension=fsr_incoming.SUFFIX,
            initialfile=fsr_handover.file_name(
                item["control"] or "Draft", sender(h).get("initials"),
                date.today(), fsr_incoming.SUFFIX),
            filetypes=[("Hand-over file", "*" + fsr_incoming.SUFFIX)])
        if not target:
            return
        note = note_entry.get().strip()
        try:
            if item["kind"] == "report":
                h["busy"](fsr_handover.hand_over_report, path,
                          item["control"], target, sender(h), to, note,
                          owner_edition)
            else:
                h["busy"](fsr_handover.hand_over_draft, path, item["value"],
                          controller.store, target, sender(h), to, note,
                          owner_edition)
        except (fsr_handover.HandoverError, OSError, ValueError) as error:
            h["log"].exception("Hand over failed")
            messagebox.showerror(TITLE, f"No file was made:\n{error}",
                                 parent=dialog)
            return
        if item["kind"] == "draft" and controller is not None and \
                item["value"]["id"] == controller.draft_id:
            # the draft on the form goes to the next inspector
            controller.writer.invalidate()
            controller.draft_id = None
            state["dirty"] = False
            h["new_report"](confirm=False)
        if item["kind"] == "report" or item["control"]:
            kept = (f"Your copy of {item['control']} stays here, marked "
                    "handed over: you can open and print it, not save it.")
        else:
            kept = ("Your draft stays in Account > Unfinished work, marked "
                    "handed over (it can only be discarded).")
        messagebox.showinfo(
            TITLE, f"Saved:\n{target}\n\nSend this one file to {to}. On a "
            "PC they choose Storage > Receive Hand-over...; on the phone "
            f"app, Master Data > Receive Hand-over.\n\n{kept}",
            parent=dialog)
        reload(item["control"])

    def cancel_hand_over():
        item = selected()
        if item is None or not item["away"]:
            return
        if not messagebox.askyesno(
                TITLE, f"Cancel the hand-over of {item['control']}?\n\n"
                "Do this only if the next inspector will NOT finish it (the "
                "file was lost, or the work stays with you). If they also "
                "change it, the Owner gets two different versions.",
                icon="warning", parent=dialog):
            return
        try:
            fsr_handover.cancel(path, item["control"])
        except fsr_handover.HandoverError as error:
            messagebox.showerror(TITLE, str(error), parent=dialog)
            return
        reload(item["control"])

    hand_button.configure(command=hand_over)
    cancel_button.configure(command=cancel_hand_over)
    tree.bind("<<TreeviewSelect>>", changed)
    search.bind("<KeyRelease>", lambda _: fill())

    select = None
    for index, item in enumerate(items):
        if item["kind"] == "draft" and controller is not None and \
                item["value"]["id"] == controller.draft_id:
            select = str(index)
        elif item["kind"] == "report" and state["editing"] and \
                not state["dirty"] and select is None and \
                storage.same_key(
                    item["control"], h["control_entry"].get().strip()):
            select = str(index)
    fill(select)
    h["hand_over_state"]["dialog"] = dialog
    return dialog


def receive(h, chosen=None):
    """Bring a hand-over file in. Returns the result or None."""
    window = h["window"]
    if chosen is None:
        chosen = filedialog.askopenfilename(
            parent=window, title="Select the hand-over file",
            filetypes=[("Hand-over file", " ".join(
                "*" + suffix for suffix in fsr_incoming.SUFFIXES)),
                ("All files", "*.*")])
    if not chosen:
        return None
    if str(chosen).lower().endswith(fsr_incoming.SHIPMENT_SUFFIX) and \
            h.get("open_receive_shipment"):
        return h["open_receive_shipment"](chosen)
    try:
        payload = fsr_handover.read_file(chosen)
    except fsr_handover.HandoverError as error:
        messagebox.showerror(RECEIVE_TITLE, str(error), parent=window)
        return None
    path = h["excel_state"]["path"]
    note = str(payload.get("note") or "").strip()
    if not messagebox.askyesno(
            RECEIVE_TITLE,
            fsr_handover.describe(payload) + "."
            + (f"\n\nNote: {note}" if note else "")
            + f"\n\nBring it into:\n{path}", parent=window):
        return None

    controller = h.get("draft_controller")
    mysql_now = h["mysql_in_use"]()
    guard = h["mysql_guard"]() if mysql_now else None
    store = h["data_store"](path)
    stores = store.save_steps(mysql=h["db_mysql"] if mysql_now else None,
                              guard=guard)
    journal = store.save_record()
    initials = (h.get("current_user") or {}).get("initials", "")

    def run(replace=False):
        return h["busy"](
            fsr_handover.receive, path, payload,
            controller.store if controller else None, initials, journal,
            stores, mysql_now, bool(h.get("IS_OWNER_EDITION")), replace,
            lambda data: form_of(h, data))

    try:
        try:
            result = run()
        except fsr_handover.HandoverConflict as conflict:
            label = h["_import_change_label"]
            listing = "\n".join(
                f"  {label(c['path'])}: {c['previous']}  ->  {c['imported']}"
                for c in conflict.changes[:15])
            more = len(conflict.changes) - 15
            if more > 0:
                listing += f"\n  ... and {more} more"
            if not messagebox.askyesno(
                    RECEIVE_TITLE,
                    f"{conflict}\n\nThis PC -> received:\n"
                    f"{listing or '  (no differences in the report fields)'}"
                    "\n\nReplace this PC's copy with the received report?",
                    icon="warning", parent=window):
                return None
            result = run(replace=True)
    except PermissionError:
        messagebox.showerror(
            "File In Use", f"Cannot write to:\n{path}\n\nNothing was "
            "received. Close the file in Excel and try again.",
            parent=window)
        h["finish_unfinished_saves"]()
        return None
    except (fsr_handover.HandoverError, OSError, ValueError) as error:
        h["log"].exception("Receive hand-over failed")
        messagebox.showerror(RECEIVE_TITLE, f"Nothing was received:\n{error}",
                             parent=window)
        h["finish_unfinished_saves"]()
        return None

    control = result["control"]
    lines = []
    if result["result"] == "added":
        lines.append(f"Report {control} was added. Open it with Open saved "
                     "report (Ctrl+O).")
    elif result["result"] == "updated":
        lines.append(f"Report {control} was updated with the received copy; "
                     "it can be saved here again.")
    elif (result["result"] == "unchanged"
          and result.get("own_file") is not None):
        lines.append(fsr_handover.own_file_text(result["own_file"]))
    elif result["result"] == "unchanged" and control:
        lines.append(f"Nothing changed: this PC already has this copy of "
                     f"{control}, or a newer one.")
    if result["renumbered"]:
        lines.append(f"\nIt was given the number {control}, because "
                     f"{result['sent_as']} is already used by another "
                     "report on this PC.")
    if payload["kind"] == "draft":
        draft = result["draft"]
        kept = None if draft is None else fsr_handover._kept(
            draft.get("received"))
        if kept is not None:
            try:
                number = fsr_handover.kept_number(path, draft["received"])
            except (OSError, ValueError):
                h["log"].exception("The number of a received draft could "
                                   "not be checked")
                number = kept["control"]
            lines.append(
                "\nThe unfinished report is in Account > Unfinished work. "
                "Restore it there to continue; "
                + (f"it keeps its Control # {number} when you save it."
                   if storage.same_key(number, kept["control"]) else
                   f"it gets the number {number} when you save it, because "
                   f"{kept['control']} is already used by another report "
                   "on this PC."))
        elif draft is not None:
            lines.append("\nThe unfinished report is in Account > "
                         "Unfinished work. Restore it there to continue; "
                         + ("it keeps its Control #." if draft[
                             "editing"] else "it gets your next Control # "
                            "when you save it."))
        else:
            lines.append("\nThis draft was received before; it is already "
                         "in Account > Unfinished work.")
    if result.get("lists_failed") is not None:
        lines.append("\nPO_Master and Withdrawn_Item could not be updated "
                     "(is one of them open in Excel?). They are updated at "
                     "the next save or start.")
    if mysql_now and result["result"] in ("added", "updated"):
        lines.append("\nIt is being sent to MySQL in the background.")
    messagebox.showinfo(RECEIVE_TITLE, "\n".join(lines).strip(),
                        parent=window)

    state = h["report_state"]
    if result["result"] == "updated" and state["editing"] and \
            storage.same_key(h["control_entry"].get().strip(),
                                          control):
        if state["dirty"]:
            messagebox.showinfo(
                RECEIVE_TITLE, f"Report {control} is open on the form with "
                "its old values. Open it again before saving.",
                parent=window)
        else:
            h["load_report_into_form"](control)
    if mysql_now and result["result"] in ("added", "updated"):
        h["request_mysql_round"]()
    if h.get("app_shell") is not None:
        h["app_shell"].service.invalidate()
    if result["result"] in ("added", "updated") and \
            h.get("IS_OWNER_EDITION"):
        h["refresh_import_review_count"]()
    if result.get("draft") is not None and controller is not None and \
            messagebox.askyesno(RECEIVE_TITLE, "Open Unfinished work now?",
                                parent=window):
        controller.show()
    return result
