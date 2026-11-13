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


class ExcelStore:
    """The workbook `excel_path` (and the Withdrawal workbook beside it)
    with its JSON files. `required_root`: Demo Mode keeps the Withdrawal
    workbook inside the demo folder."""

    def __init__(self, excel_path, required_root=None):
        self.excel_path = Path(excel_path)
        self.required_root = required_root

    # ---- where things are ----
    @property
    def withdrawal_path(self):
        """The workbook of the PO-linked Withdrawal reports."""
        return fsr_paths.withdrawal_workbook_path(self.excel_path,
                                                  self.required_root)

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
        """Demo Mode reset only (the sample reports)."""
        return fsr_storage.delete_reports_from_excel(self.excel_path,
                                                     control_numbers)

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
