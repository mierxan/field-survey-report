"""The ONE storage interface of the program (Phase 4).

Everything the program keeps on this PC about reports goes through a
ReportStore: the reports (main and PO-linked Withdrawal), their incident
texts and other Item List forms, the derived lists PO_Master and
Withdrawn_Item, the record of unfinished saves, the MySQL ownership
ledger and the record of imported reports. The window code calls the
store and never opens a workbook itself.

ExcelStore is today's storage - the Excel workbooks and JSON files beside
them. It only hands the calls on to the existing functions (fsr_storage,
fsr_withdrawal, fsr_save_journal, fsr_mysql_guard, fsr_import,
fsr_renumber, fsr_backup); nothing is done differently. A SQLite store
will be the second implementation: the checklist of what it must provide
is in docs/STORAGE_PROPOSAL.md, section 10.

MySQL is not behind this interface: it is the shared copy on the owner's
PC (db_mysql, written only through fsr_mysql_guard).
"""
from pathlib import Path

import fsr_backup
import fsr_import
import fsr_mysql_guard
import fsr_paths
import fsr_renumber
import fsr_save_journal
import fsr_storage
import fsr_withdrawal


# Demo Mode data: a folder marked with this file, reports numbered TEST-...
# (warehouse/sample_data.py). Nothing else may ever be deleted.
DEMO_MARKER = ".fsr_test_data"
DEMO_PREFIX = "TEST-"


class StoreRefused(ValueError):
    """The store does not do this to real data."""


def check_demo_delete(excel_path, control_numbers):
    """Raises StoreRefused unless the workbook is in a folder marked as test
    data AND every report to delete is a TEST-... sample report (both
    stores call this)."""
    excel_path = Path(excel_path)
    marker = excel_path.resolve().parent / DEMO_MARKER
    if not marker.exists():
        raise StoreRefused(
            f"{excel_path} is not Demo Mode data: reports are "
            "never deleted from it.")
    real = [c for c in control_numbers
            if not str(c).strip().upper().startswith(DEMO_PREFIX)]
    if real:
        raise StoreRefused(
            f"Only TEST-... sample reports can be deleted (not {real[0]}).")


def open_store(excel_path, required_root=None):
    """The store of this workbook: the SQLite store once the workbook has
    moved to its database (fsr_sqlite_migrate), else the workbook itself."""
    import fsr_sqlite_store
    if fsr_sqlite_store.is_active(excel_path):
        return fsr_sqlite_store.SqliteStore(excel_path, required_root)
    return ExcelStore(excel_path, required_root)


def _last_saved(path, sheet):
    """(Moved here from fsr_master_export, unchanged.)"""
    if not Path(path).exists():
        return {}
    wb = fsr_storage.load_workbook(path, data_only=True)
    if sheet not in wb.sheetnames:
        return {}
    return {
        fsr_storage.cell_text(row["Control #"]).casefold():
            str(row.get("Last Saved") or "")
        for row in fsr_storage.report_dicts(wb[sheet]) if row.get("Control #")
    }


class ExcelStore:
    """The workbook `excel_path` (and the Withdrawal workbook beside it)
    with its JSON files. `required_root`: Demo Mode keeps the Withdrawal
    workbook inside the demo folder."""

    kind = "excel"

    def __init__(self, excel_path, required_root=None):
        self.excel_path = Path(excel_path)
        self.required_root = required_root

    # ---- where things are ----
    @property
    def withdrawal_path(self):
        """The workbook of the PO-linked Withdrawal reports."""
        return fsr_paths.withdrawal_workbook_path(self.excel_path,
                                                  self.required_root)

    def ledger_files(self):
        """The files the MySQL ledger's note is about: both workbooks."""
        return [self.excel_path,
                self.excel_path.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)]

    # ---- reports of the main workbook ----
    def list_reports(self):
        """[(Control #, SO, inspection date, consignee, last saved)]"""
        return fsr_storage.list_saved_reports(self.excel_path)

    def read_report(self, control_no):
        return fsr_storage.read_report(self.excel_path, control_no)

    def read_all_reports(self):
        return fsr_storage.read_all_reports(self.excel_path)

    def search_index(self):
        return fsr_storage.search_index_excel(self.excel_path)

    def write_report(self, data, editing, saved_at=None):
        return fsr_storage.write_report_to_excel(self.excel_path, data,
                                                 editing, saved_at)

    def write_reports(self, items):
        """[(data, editing, saved_at)] in ONE write - all or none."""
        return fsr_storage.write_reports_to_excel(self.excel_path, items)

    def delete_reports(self, control_numbers):
        """Demo Mode reset only: refused (StoreRefused) unless the workbook
        is in a folder marked as test data AND every report to delete is a
        TEST-... sample report - enforced here, whoever calls it."""
        check_demo_delete(self.excel_path, control_numbers)
        return fsr_storage.delete_reports_from_excel(self.excel_path,
                                                     control_numbers)

    def last_saved_times(self):
        """{Control # in lower case: its Last Saved cell as text}."""
        return _last_saved(self.excel_path, "Reports")

    def saved_stamp(self, control_no, linked):
        """The Last Saved time of a report in its workbook (ISO text), or
        None when the workbook or the report is not there. (Moved here
        from fsr_save_journal.Stores.stamp, unchanged.)"""
        from datetime import datetime
        book = self.withdrawal_path if linked else self.excel_path
        sheet = fsr_withdrawal.HEADER_SHEET if linked else "Reports"
        if not Path(book).exists():
            return None
        wb = fsr_storage.load_workbook(book, read_only=True, data_only=True)
        try:
            if sheet not in wb.sheetnames:
                return None
            rows = wb[sheet].iter_rows(values_only=True)
            header = next(rows, None) or ()
            if "Last Saved" not in header:
                return None
            column = header.index("Last Saved")
            for row in rows:
                if row and fsr_storage.same_key(row[0], control_no):
                    value = row[column] if len(row) > column else None
                    if isinstance(value, datetime):
                        return value.isoformat(timespec="milliseconds")
                    return str(value) if value is not None else ""
            return None
        finally:
            wb.close()

    # ---- PO lines (the Receiving lines a Withdrawal can take from) ----
    def find_po(self, po_number):
        return fsr_withdrawal.find_po(self.excel_path, po_number)

    def remaining_quantity(self, row, except_control=""):
        return fsr_withdrawal.remaining_quantity(self.excel_path, row,
                                                 except_control)

    # ---- PO-linked Withdrawal reports ----
    def owns_withdrawal(self, control_no):
        """Is this report kept in the Withdrawal workbook?"""
        return fsr_withdrawal.owns_report(self.excel_path, control_no)

    def withdrawal_numbers(self):
        return fsr_storage.withdrawal_control_numbers(self.excel_path)

    def list_withdrawal_reports(self):
        return fsr_withdrawal.list_reports(self.withdrawal_path)

    def read_withdrawal_report(self, control_no):
        return fsr_withdrawal.read_report(self.withdrawal_path, control_no)

    def read_all_withdrawal_reports(self):
        return fsr_withdrawal.read_all_reports(self.withdrawal_path)

    def withdrawal_search_index(self):
        return fsr_withdrawal.search_index(self.withdrawal_path)

    def withdrawal_last_saved_times(self):
        return _last_saved(self.withdrawal_path, fsr_withdrawal.HEADER_SHEET)

    def write_withdrawal_report(self, data, editing, saved_at=None):
        extra = {} if saved_at is None else {"saved_at": saved_at}
        return fsr_withdrawal.write_withdrawal_report(
            self.withdrawal_path, data, editing, self.excel_path, **extra)

    # ---- Control #s ----
    def next_control_number(self):
        return fsr_storage.generate_control_number(self.excel_path)

    def control_numbers(self):
        """Every Control # of this PC (both workbooks)."""
        return fsr_renumber.local_numbers(self.excel_path)

    def next_free_number(self, old, also_taken=()):
        return fsr_renumber.next_free(self.excel_path, old, also_taken)

    def renumber(self, old, new):
        return fsr_renumber.renumber_report(self.excel_path, old, new,
                                            self.required_root)

    # ---- the files beside a report ----
    def save_incidents(self, control_no, so_number, reports):
        return fsr_storage.save_incident_data(self.excel_path, control_no,
                                              so_number, reports)

    def load_incidents(self, control_no):
        return fsr_storage.load_incident_data(self.excel_path, control_no)

    def delete_incidents(self, control_no):
        return fsr_storage.delete_incident_data(self.excel_path, control_no)

    def save_item_forms(self, control_no, forms):
        return fsr_storage.save_other_item_forms(self.excel_path, control_no,
                                                 forms)

    def load_item_forms(self, control_no):
        return fsr_storage.load_other_item_forms(self.excel_path, control_no)

    # ---- derived lists ----
    def rebuild_item_lists(self):
        """PO_Master and Withdrawn_Item from the reports."""
        return fsr_withdrawal.sync_item_lists(self.excel_path)

    # ---- records kept beside the reports ----
    def save_record(self):
        """The record of unfinished saves (fsr_save_journal.Journal)."""
        return fsr_save_journal.Journal(self.excel_path)

    def save_steps(self, mysql=None, guard=None):
        """The writes of one save (fsr_save_journal.Stores)."""
        return fsr_save_journal.Stores(self.excel_path, mysql=mysql,
                                       required_root=self.required_root,
                                       guard=guard)

    def mysql_guard(self, db, user=""):
        """The MySQL ownership ledger of this store, with its guard."""
        return fsr_mysql_guard.Guard(db, self.excel_path, user=user)

    def imported_inspector(self, control_no):
        return fsr_import.imported_inspector(self.excel_path, control_no)

    def import_master_data(self, data, **options):
        return fsr_import.import_master_data(self.excel_path, data,
                                             **options)

    def backup_before_save(self, keep, linked=False):
        """Today's copy of the workbook that is about to be written."""
        target = self.withdrawal_path if linked else self.excel_path
        return fsr_backup.backup_before_save(target, keep)
