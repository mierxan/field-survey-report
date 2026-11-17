"""Save: the report on the form is written on this PC (the Excel file, its incident and item-form files, the save record), the user is told what happened, and MySQL and PO_Master / Withdrawn_Item follow in the background.

Moved here from field_survey_report.py (Phase 4). The code is unchanged
except that the names it takes from the program's window module are
read as `host.<name>`, at the moment they are used (bind() is called
by the window module)."""
from fsr_storage import CONDITION_BAD
from fsr_storage import Workbook
from tkinter import messagebox
import fsr_backup
import fsr_mysql_guard
import fsr_save_journal
import fsr_text_flow


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


def host_globals():
    """The window module's globals (where the moved code used globals())."""
    return object.__getattribute__(host, "names")


def host_handover_allows_save():
    """A report handed over to the next inspector is finished there: this
    PC's copy is not saved, so the two copies cannot both change."""
    import fsr_handover
    control = host.control_entry.get().strip()
    entry = fsr_handover.handed_over(host.excel_state["path"], control)
    if entry is None:
        return True
    messagebox.showwarning(
        "Handed Over",
        f"{control} was handed over to "
        f"{entry.get('to') or 'the next inspector'} on "
        f"{str(entry.get('at') or '')[:10]}, who finishes it. This copy can "
        "be opened and printed, not saved.\n\nTo work on it here again: "
        "receive it back (Storage > Receive Hand-over...), or choose "
        "Storage > Hand Over... > Cancel Hand-over.",
        parent=host.window)
    return False


def save_report():
    """Add the report to the Excel file, or update it if it is a
    saved report that was opened for editing. Returns True when saved."""

    if Workbook is None:
        host.excel_missing_message()
        return False

    if host.report_state["editing"] and not host_handover_allows_save():
        return False

    if not host.condition_var.get():
        messagebox.showwarning(
            "Cargo Condition",
            "Please select the Cargo Condition (Good Order or Bad Order) "
            "before saving.",
            parent=host.window
        )
        host.good_button.focus_set()
        return False

    if not host.SO_number_entry.get().strip():
        host.notebook.select(host.general_tab)
        messagebox.showwarning(
            "Missing SO Number",
            "Please enter the SO Number before saving.",
            parent=host.window
        )
        host.SO_number_entry.focus_set()
        return False

    if not host.validate_format_fields():
        return False

    if not fsr_text_flow.validate(host_globals()):
        return False

    # a price with no Currency cannot be counted in the value reports
    if not host.prices_have_currency():
        return False

    if host.condition_var.get() == CONDITION_BAD and not host.incidents_have_content():
        host.notebook.select(host.incident_tab)
        if not messagebox.askyesno(
            "Bad Order - No Incident Lines",
            "Bad Order is selected but the Incident Report has no lines "
            "yet.\n\nSave anyway?",
            parent=host.window
        ):
            return False

    # Offer to add any typed name that is not in the master lists yet.
    for combo in host.searchable_combos:
        combo.commit()

    if not host.withdrawal_panel.context_changed():
        return False

    controller = host_globals().get("draft_controller")
    draft_ref = None
    if controller is not None and (host.report_state["dirty"] or controller.draft_id):
        draft_ref = controller.before_save()
        if draft_ref is False:
            return False
    path = host.excel_state["path"]
    data = host.collect_report_data()
    target = path
    backup_note = None
    linked = host.withdrawal_panel.linked()
    mysql_on = host.mysql_in_use()
    guard = host.mysql_guard() if mysql_on else None
    stores = host.data_store(path).save_steps(
        mysql=host.db_mysql if mysql_on else None, guard=guard)
    stores.draft_ref = draft_ref
    journal = record = None
    earlier_open = []
    if mysql_on and not host.report_state["editing"]:
        free = host.free_number_for_new_report(data["control_no"])
        if free != data["control_no"]:
            data["control_no"] = free
            host.set_control_number(free)

    try:
        if linked:
            target = host.withdrawal_book()
        # Before the first save of each day the workbook is copied, as it
        # is now, into the Backups folder beside it. A backup that cannot
        # be made never stops the save; the user is told below.
        try:
            host.data_store(path).backup_before_save(
                fsr_backup.keep_setting(host.settings), linked)
        except OSError as error:
            host.log.exception("Daily backup failed")
            backup_note = (
                "Today's backup copy of the Excel file could NOT be made:\n"
                f"{error}\n\nThe report itself was saved. Check the "
                f"{fsr_backup.FOLDER_NAME} folder beside the Excel file.")

        # The save goes on record before its first write, so a save that
        # stops halfway (power cut, file open in Excel, MySQL away) is
        # finished at the next save or the next start (fsr_save_journal).
        try:
            journal = host.data_store(path).save_record()
            # An earlier save of this same report that did not finish is
            # replaced by this one; what it still owed is done by this save
            # and said in the note below.
            earlier_open = fsr_save_journal.open_local_steps(
                journal, data["control_no"])
            record = fsr_save_journal.open_save(
                journal, stores, data, host.report_state["editing"], linked,
                mysql_on)
        except (OSError, ValueError, TypeError):
            host.log.exception("The save record could not be written")
            journal = None
            record = fsr_save_journal.new_record(
                data, host.report_state["editing"], linked,
                fsr_save_journal.steps_for(data, linked, mysql_on))

        if draft_ref:
            record["draft"] = draft_ref
        # Excel first, then the incident file, the other Item List forms
        # and PO_Master / Withdrawn_Item. Only a failure of the Excel write
        # stops the save. MySQL follows in the background (its step stays
        # open in the record) - unless there is no record to hold it.
        outcome = host.busy(fsr_save_journal.run, journal, record, stores,
                       journal is None, journal is None)
        result = outcome["result"]

    except PermissionError:
        fsr_save_journal.discard(journal, record)
        messagebox.showerror(
            "File In Use",
            f"Cannot write to:\n{target}\n\n"
            "Close the file in Excel and click Save again.",
            parent=host.window
        )
        return False

    except Exception as error:
        host.log.exception("Save failed")
        fsr_save_journal.discard(journal, record)
        messagebox.showerror(
            "Save Error",
            f"Unable to save the report:\n{error}",
            parent=host.window
        )
        return False

    failed = outcome["failed"]
    data = record["data"]       # as written: Control #, Receiving Refs ...
    later = ("\n\nIt will also be finished automatically at the next save "
             "or the next start." if journal is not None else "")

    # The report now exists in the file, so further saves update it.
    if controller is not None:
        controller.muted = True
    try:
        host.set_control_number(result["control"])
        host.report_state["editing"] = True
        host.report_state["dirty"] = False
        host.withdrawal_panel.saved(data)
    finally:
        if controller is not None:
            controller.muted = False
    if controller is not None:
        try:
            controller.saved(data, record, failed, journal)
        except (OSError, ValueError) as error:
            controller.failed(error)
    host.update_status()

    # remember SO Number + Consignee for the next report / next start
    host.settings["last_so_number"] = host.SO_number_entry.get().strip()
    host.settings["last_consignee"] = host.consignee_combobox.get().strip()
    host.save_settings()

    action = "updated" if result["updated"] else "saved"
    data["control_no"] = result["control"]

    # Incident reports go to their own JSON file (not into the Excel file).
    incident_note = None
    if "incidents" in failed:
        incident_note = (
            "The incident report file could not be saved:\n"
            f"{failed['incidents']}\n\nClick Save again to retry." + later
        )

    if "item_forms" in failed:
        incident_note = "\n\n".join(t for t in (incident_note, (
            "The lines of the other Item List forms could not be saved:\n"
            f"{failed['item_forms']}\n\nClick Save again to retry."
            + later)) if t)

    # PO_Master and Withdrawn_Item follow the saved reports, in the
    # background (at once in the automated tests, which then say it here).
    if journal is not None and "item_lists" in record["steps"]:
        host.lists_feedback.pop(record["id"], None)
        host.request_lists_round(save_id=record["id"], compose=host.lists_sender.inline)
        if record["id"] in host.lists_feedback:
            lists_error = host.lists_feedback.pop(record["id"])
            if lists_error is not None:
                failed["item_lists"] = lists_error
        elif "item_lists" in earlier_open:
            earlier_open.remove("item_lists")   # said by the rebuild
    elif journal is not None:
        host.request_lists_round()       # earlier saves may still wait for them
    if "item_lists" in failed:
        if isinstance(failed["item_lists"], PermissionError):
            incident_note = "\n\n".join(t for t in (incident_note, (
                "PO_Master or Withdrawn_Item could not be updated because it "
                "is open in another program.\nClose it and click Save again."
                + later)) if t)
        else:
            incident_note = "\n\n".join(t for t in (incident_note, (
                "PO_Master and Withdrawn_Item could not be updated:\n"
                f"{failed['item_lists']}" + later)) if t)

    completed_now = [step for step in earlier_open if step not in failed]
    if completed_now:
        incident_note = "\n\n".join(t for t in ((
            "Unfinished Save: an earlier save of this report had not "
            "finished. It was completed now: "
            f"{fsr_save_journal.words(completed_now)}."), incident_note)
            if t)

    # Also store the report in MySQL (when db_config.json is set up): in
    # the background, so the window does not wait for the server.
    db_note = None
    mysql_waits = False
    mysql_conflict = None
    sending = False
    if mysql_on and journal is not None:
        host.mysql_feedback.pop(record["id"], None)
        host.request_mysql_round(save_id=record["id"],
                            compose=host.mysql_sender.inline)
        told = host.mysql_feedback.pop(record["id"], None)
        sending = not host.mysql_sender.inline
        kind, detail = told or (None, None)
        if kind == "sent":
            db_note = "\n".join(detail or []) or None
        elif kind == "conflict":
            mysql_waits = True
            mysql_conflict = detail
            db_note = (
                "The report is saved in the Excel file, but MySQL was NOT "
                f"updated:\n{detail['text']}\n\nNothing in MySQL was "
                "changed. Decide in the MySQL Conflicts window what to do; "
                "until then MySQL keeps its report.")
        elif kind == "away":
            mysql_waits = True
        elif kind == "error":
            mysql_waits = True
            db_note = (
                "The report was saved to Excel, but NOT to MySQL:\n"
                f"{host.db_mysql.explain_error(detail)}\n\nClick Save again "
                "to retry, or use 'Sync to MySQL'." + later)
    elif mysql_on:
        # No save record (it could not be written): MySQL was done at once.
        error = failed.get("mysql")
        if error is None:
            try:
                host.busy(host.db_mysql.save_master_lists, host.master_data)
            except Exception as lists_error:
                host.log.exception("MySQL master lists failed")
                error = lists_error
        conflict = isinstance(error, fsr_mysql_guard.MySQLConflict)
        if error is None:
            db_note = "\n".join(outcome.get("mysql_notes") or []) or None
            if "set_mysql_dots" in host_globals():
                host.set_mysql_dots("ok")
            if result["control"] not in host.mysql_numbers["values"]:
                host.mysql_numbers["values"].append(result["control"])
        elif conflict:
            # MySQL answered, but holds ANOTHER report under this number.
            # Nothing was written there. The report is safe in the Excel
            # file; the decision waits in MySQL Conflicts.
            mysql_waits = True
            mysql_conflict = error.conflict
            db_note = (
                "The report is saved in the Excel file, but MySQL was NOT "
                f"updated:\n{error}\n\nNothing in MySQL was changed. "
                "Decide in the MySQL Conflicts window what to do; until "
                "then MySQL keeps its report.")
        else:
            mysql_waits = "mysql" in failed
            if "set_mysql_dots" in host_globals():
                host.set_mysql_dots("bad", host.db_mysql.explain_error(error))
            # A server that cannot be reached is normal on an offline PC:
            # no message box, the notice below says that MySQL comes later.
            if not (mysql_waits and journal is not None
                    and getattr(host.db_mysql, "is_unreachable",
                                lambda e: False)(error)):
                db_note = (
                    "The report was saved to Excel, but NOT to MySQL:\n"
                    f"{host.db_mysql.explain_error(error)}\n\nClick Save again "
                    "to retry, or use 'Sync to MySQL'." + (
                        later if mysql_waits else ""))

    # Also record the report on the official form (First Page + Cargo Details).
    warning, summary = None, ""
    try:
        forms, notes, summary = host.busy(host.create_report_forms, path, data)
        warning = "\n".join(notes) or None
    except PermissionError:
        warning = (
            "The report form could not be updated because it is open in "
            "another program.\nClose it, then use the Print / PDF... button."
        )
    except Exception as error:
        host.log.exception("Report form failed")
        warning = f"The report form could not be created:\n{error}"

    if mysql_conflict:
        host.notify(
            f"Report {result['control']} {action} on this PC  -  NOT sent "
            "to MySQL (it holds a different report under this number)",
            bootstyle="warning")
    elif sending:
        host.notify(
            f"Report {result['control']} {action} on this PC  -  "
            f"{result['goods']} goods, {result['items']} item lines, "
            f"{result['remarks']} remarks. Sending it to MySQL...")
    elif mysql_waits:
        host.notify(
            f"Report {result['control']} {action} on this PC  -  MySQL was "
            "not reached; it will be sent at the next save or start",
            bootstyle="warning")
    else:
        host.notify(
            f"Report {result['control']} {action}  -  "
            f"{result['goods']} goods, {result['items']} item lines, "
            f"{result['remarks']} remarks"
        )

    warning = "\n\n".join(
        t for t in (backup_note, incident_note, db_note, warning) if t
    ) or None
    if warning:
        messagebox.showwarning("Report Saved - Note", warning, parent=host.window)

    host.show_saved_links(data)
    if host_globals().get("app_shell") is not None:
        host.app_shell.service.invalidate()      # dashboards use the new data
    # Earlier saves that did not finish are completed now (this PC's
    # files; MySQL is in the round above).
    host.finish_unfinished_saves(skip={record["id"]})
    if mysql_conflict:
        host.open_mysql_conflicts(select=record["id"])
    host.refresh_conflict_count()
    host.refresh_mysql_waiting()
    return True
