"""Inventory browsing and reconciliation actions."""

from fsr_typeahead import Combobox as TypeaheadCombobox

import tkinter
from tkinter import messagebox, simpledialog, ttk

import ttkbootstrap as tb

from warehouse import inventory as inv
from warehouse import tables as tbl
from .components import Card, DataTable
from .pages import Page


DECISION_KINDS = {
    "unmatched_withdrawal", "link_target_missing", "duplicate_receiving_ref",
}


class WarehousePage(Page):
    title = "Warehouse Monitoring"
    subtitle = (
        "Current recorded inventory and reconciliation issues. Decisions "
        "are saved in the warehouse audit log and never edit inspection "
        "reports."
    )
    show_when_empty = True

    def build(self):
        filters = ttk.Frame(self.main, style="Page.TFrame")
        filters.grid(row=0, column=0, sticky="we")
        ttk.Label(filters, text="Warehouse",
                  style="PageMuted.TLabel").pack(side="left")
        self.warehouse_filter = tkinter.StringVar(value="All Warehouses")
        self.warehouse_combo = TypeaheadCombobox(
            filters, textvariable=self.warehouse_filter, state="readonly",
            width=24)
        self.warehouse_combo.pack(side="left", padx=(6, 18))
        self.warehouse_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_inventory())
        ttk.Label(filters, text="Inventory status",
                  style="PageMuted.TLabel").pack(side="left")
        self.inventory_status_filter = tkinter.StringVar(value="All")
        self.inventory_status_combo = TypeaheadCombobox(
            filters, textvariable=self.inventory_status_filter,
            values=["All", *inv.STATUSES], state="readonly", width=25)
        self.inventory_status_combo.pack(side="left", padx=6)
        self.inventory_status_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_inventory())

        inventory_card = Card(
            self.main, "Inventory",
            "Balances are calculated from saved Receiving and Withdrawal "
            "reports; they are not a physical stock count.")
        inventory_card.grid(row=1, column=0, sticky="we", pady=(10, 0))
        self.inventory_table = DataTable(
            inventory_card.content, tbl.INVENTORY_COLUMNS, height=8,
            on_select=self._select_item)
        self.inventory_table.grid(row=0, column=0, sticky="we")

        history_card = Card(self.main, "Selected Item History")
        history_card.grid(row=2, column=0, sticky="we", pady=(10, 0))
        self.history_table = DataTable(
            history_card.content, tbl.HISTORY_COLUMNS, height=5, search=False)
        self.history_table.grid(row=0, column=0, sticky="we")

        issues_card = Card(
            self.main, "Reconciliation Issues",
            "Suggested matches are advisory. A proposed match changes the "
            "ledger only after an owner confirms it.")
        issues_card.grid(row=3, column=0, sticky="we", pady=(10, 0))
        issue_filters = ttk.Frame(issues_card.content,
                                  style="CardPlain.TFrame")
        issue_filters.grid(row=0, column=0, sticky="we", pady=(0, 6))
        ttk.Label(issue_filters, text="Issue state",
                  style="CardMuted.TLabel").pack(side="left")
        self.issue_state_filter = tkinter.StringVar(value="All")
        self.issue_state_combo = TypeaheadCombobox(
            issue_filters, textvariable=self.issue_state_filter,
            values=["All", inv.OPEN, inv.PROPOSED, inv.CONFIRMED,
                    inv.REJECTED, inv.EXCLUDED, inv.ACCEPTED],
            state="readonly", width=18)
        self.issue_state_combo.pack(side="left", padx=6)
        self.issue_state_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._render_issues())
        self.issue_table = DataTable(
            issues_card.content, tbl.ISSUE_COLUMNS, height=8,
            on_select=self._select_issue)
        self.issue_table.grid(row=1, column=0, sticky="we")

        self.issue_detail = ttk.Label(
            issues_card.content, text="Select an issue to see its details.",
            style="CardMuted.TLabel", justify="left", wraplength=950)
        self.issue_detail.grid(row=2, column=0, sticky="we", pady=(8, 0))

        suggestions_card = Card(
            issues_card.content, "Suggested Matches",
            "Choose a candidate before proposing a match.")
        suggestions_card.grid(row=3, column=0, sticky="we", pady=(10, 0))
        self.suggestion_table = DataTable(
            suggestions_card.content,
            [("Cargo ID / Reference", "text", 24),
             ("Warehouse", "text", 20), ("Description", "text", 30),
             ("Inventory Status", "text", 22), ("Why suggested", "text", 40)],
            height=5, on_select=self._select_suggestion)
        self.suggestion_table.grid(row=0, column=0, sticky="we")

        actions = ttk.Frame(issues_card.content, style="CardPlain.TFrame")
        actions.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.note_button = tb.Button(
            actions, text="Add Note...", bootstyle="secondary-outline",
            command=self.add_note, state="disabled")
        self.note_button.pack(side="left")
        self.propose_button = tb.Button(
            actions, text="Propose Match", bootstyle="info",
            command=self.propose_match, state="disabled")
        self.propose_button.pack(side="left", padx=6)
        self.confirm_button = tb.Button(
            actions, text="Confirm Match", bootstyle="success",
            command=self.confirm_match, state="disabled")
        self.confirm_button.pack(side="left")
        self.reject_button = tb.Button(
            actions, text="Reject Proposal", bootstyle="warning-outline",
            command=self.reject_proposal, state="disabled")
        self.reject_button.pack(side="left", padx=6)
        self.accept_button = tb.Button(
            actions, text="Accept as Separate Batch", bootstyle="success-outline",
            command=self.accept_batch, state="disabled")
        self.accept_button.pack(side="left")
        self.exclude_button = tb.Button(
            actions, text="Exclude...", bootstyle="danger-outline",
            command=self.exclude_issue, state="disabled")
        self.exclude_button.pack(side="left", padx=6)
        self.reopen_button = tb.Button(
            actions, text="Reopen", bootstyle="secondary-outline",
            command=self.reopen_issue, state="disabled")
        self.reopen_button.pack(side="left")

        audit_card = Card(
            self.main, "Reconciliation Audit Log",
            "The append-only decision history is stored beside the selected "
            "Excel workbook.")
        audit_card.grid(row=4, column=0, sticky="we", pady=(10, 0))
        self.audit_table = DataTable(
            audit_card.content,
            [("Action", "text", 14), ("Subject", "text", 34),
             ("Target", "text", 34), ("Note", "text", 36),
             ("User", "text", 16), ("Timestamp", "text", 22)],
            height=6, on_select=self._select_audit)
        self.audit_table.grid(row=0, column=0, sticky="we")
        self.reopen_audit_button = tb.Button(
            audit_card.content, text="Reopen Selected Decision",
            bootstyle="secondary-outline", state="disabled",
            command=self.reopen_audit_decision)
        self.reopen_audit_button.grid(row=1, column=0, sticky="w",
                                      pady=(8, 0))

    def render(self, snapshot):
        warehouses = sorted(
            {item.warehouse for item in snapshot.inventory.items
             if item.warehouse},
            key=str.casefold)
        choices = ["All Warehouses", *warehouses]
        self.warehouse_combo.configure(values=choices)
        if self.warehouse_filter.get() not in choices:
            self.warehouse_filter.set("All Warehouses")
        self._render_inventory()
        self._render_issues()
        self._render_audit()

    def _render_inventory(self):
        if self.snapshot is None:
            return
        warehouse = self.warehouse_filter.get()
        status = self.inventory_status_filter.get()
        items = [
            item for item in self.snapshot.inventory.items
            if (warehouse == "All Warehouses"
                or item.warehouse == warehouse)
            and (status == "All" or item.status == status)
        ]
        self.inventory_table.set_rows(
            tbl.inventory_rows(items), items,
            "No inventory items match these filters.")
        self._select_item(None)

    def _render_issues(self):
        if self.snapshot is None:
            return
        state = self.issue_state_filter.get()
        issues = [
            issue for issue in self.snapshot.inventory.issues
            if state == "All" or issue.state == state
        ]
        self.issue_table.set_rows(
            tbl.issue_rows(issues), issues,
            "No reconciliation issues match this filter.")
        self._select_issue(None)

    def _render_audit(self):
        entries = self.snapshot.side.history()
        self.audit_table.set_rows(
            [[entry["action"], entry["subject"],
              str(entry.get("target") or ""), entry.get("note", ""),
              entry.get("user", ""), entry.get("timestamp", "")]
             for entry in entries],
            entries, "No reconciliation decisions have been recorded.")
        self._select_audit(None)

    def _select_item(self, item):
        if item is None:
            self.history_table.set_rows(
                [], [], "Select an inventory item to view its history.")
            return
        self.history_table.set_rows(tbl.history_rows(item))

    def _select_issue(self, issue):
        self._selected_issue = issue
        self.suggestion_table.set_rows(
            [], [], "Select an unmatched issue to see possible matches.")
        if issue is None:
            self.issue_detail.configure(
                text="Select an issue to see its details.")
            self._update_actions()
            return

        decision = self.snapshot.side.decisions().get(issue.subject_id)
        history = self.snapshot.side.history(issue.subject_id)
        details = [f"{issue.title} — {issue.state}",
                   f"Subject: {issue.subject_id}", issue.message]
        if decision and decision.target:
            details.append(f"Proposed target: {decision.target}")
        if decision and decision.note:
            details.append(f"Latest note: {decision.note}")
        if history:
            details.append("Audit: " + " → ".join(
                f"{entry['action']} ({entry['timestamp'][:10]}, "
                f"{entry['user'] or 'unknown'})" for entry in history))
        self.issue_detail.configure(text="\n".join(details))

        if issue.kind in ("unmatched_withdrawal", "link_target_missing") \
                and issue.line is not None:
            suggestions = inv.suggest_matches(
                issue.line, self.snapshot.inventory)
            self.suggestion_table.set_rows(
                [[item.cargo_id or item.identity, item.warehouse,
                  item.description, item.status_detail, reason]
                 for item, reason in suggestions],
                suggestions,
                "No suggested matches. Review the issue and correct the "
                "source report if needed.")
        self._update_actions()

    def _select_suggestion(self, _selection):
        self._update_actions()

    def _select_audit(self, entry):
        self._selected_audit = entry
        self._update_actions()

    def _update_actions(self):
        issue = getattr(self, "_selected_issue", None)
        owner = self.ctx.is_owner
        proposed = issue is not None and issue.state == inv.PROPOSED
        actionable = issue is not None and issue.kind in DECISION_KINDS
        candidate = self.suggestion_table.selected_object() \
            if hasattr(self, "suggestion_table") else None
        self.note_button.configure(
            state="normal" if issue is not None else "disabled")
        self.propose_button.configure(
            state="normal" if issue is not None
            and issue.kind in ("unmatched_withdrawal", "link_target_missing")
            and candidate is not None else "disabled")
        self.confirm_button.configure(
            state="normal" if owner and proposed
            and issue.kind in ("unmatched_withdrawal",
                               "link_target_missing") else "disabled")
        self.reject_button.configure(
            state="normal" if owner and proposed else "disabled")
        self.accept_button.configure(
            state="normal" if owner and issue is not None
            and issue.kind == "duplicate_receiving_ref"
            and issue.state not in (inv.ACCEPTED, inv.EXCLUDED)
            else "disabled")
        self.exclude_button.configure(
            state="normal" if owner and actionable
            and issue.state not in (inv.ACCEPTED, inv.EXCLUDED)
            else "disabled")
        self.reopen_button.configure(
            state="normal" if owner and actionable
            and issue.state in (inv.CONFIRMED, inv.REJECTED,
                                inv.EXCLUDED, inv.ACCEPTED)
            else "disabled")
        audit = getattr(self, "_selected_audit", None)
        decision = (self.snapshot.side.decisions().get(audit["subject"])
                    if audit is not None else None)
        reopenable = decision is not None and decision.state in (
            inv.CONFIRMED, inv.REJECTED, inv.EXCLUDED, inv.ACCEPTED)
        self.reopen_audit_button.configure(
            state="normal" if owner and reopenable else "disabled")

    def _record_decision(self, action, target=None, note=""):
        issue = getattr(self, "_selected_issue", None)
        if issue is None:
            return
        try:
            self.snapshot.side.add_decision(
                issue.subject_id, action, self.ctx.user_name,
                "owner" if self.ctx.is_owner else "user",
                target=target, note=note)
        except (ValueError, OSError) as error:
            if isinstance(error, OSError):
                self.ctx.log.exception("Saving a reconciliation decision failed")
            messagebox.showerror("Reconciliation", str(error),
                                 parent=self.ctx.window)
            return
        self.service.invalidate()

    def add_note(self):
        note = simpledialog.askstring(
            "Reconciliation Note", "Enter a note for this issue:",
            parent=self.ctx.window)
        if note and note.strip():
            self._record_decision("note", note=note.strip())

    def propose_match(self):
        selected = self.suggestion_table.selected_object()
        if selected is None:
            return
        item, _reason = selected
        receiving_ref = ""
        if not item.cargo_id and item.batches:
            receiving_ref = item.batches[0].ref
        target = {
            "warehouse": item.warehouse,
            "cargo_id": item.cargo_id,
            "receiving_ref": receiving_ref,
        }
        self._record_decision("propose", target=target)

    def confirm_match(self):
        issue = getattr(self, "_selected_issue", None)
        if issue is None or not messagebox.askyesno(
                "Confirm Match",
                "Confirm the proposed match? This changes the derived "
                "inventory ledger, not the inspection report.",
                parent=self.ctx.window):
            return
        self._record_decision("confirm")

    def reject_proposal(self):
        issue = getattr(self, "_selected_issue", None)
        if issue is None or not messagebox.askyesno(
                "Reject Proposal", "Reject this proposed match?",
                parent=self.ctx.window):
            return
        self._record_decision("reject")

    def accept_batch(self):
        issue = getattr(self, "_selected_issue", None)
        if issue is None or not messagebox.askyesno(
                "Accept Separate Batch",
                "Count this duplicate Receiving Ref as a separate batch?",
                parent=self.ctx.window):
            return
        self._record_decision("accept")

    def exclude_issue(self):
        note = simpledialog.askstring(
            "Exclude Issue", "Explain why this issue should be excluded:",
            parent=self.ctx.window)
        if note and note.strip():
            self._record_decision("exclude", note=note.strip())

    def reopen_issue(self):
        issue = getattr(self, "_selected_issue", None)
        if issue is None or not messagebox.askyesno(
                "Reopen Issue", "Reopen this reconciliation issue?",
                parent=self.ctx.window):
            return
        self._record_decision("reopen")

    def reopen_audit_decision(self):
        entry = getattr(self, "_selected_audit", None)
        if entry is None or not self.ctx.is_owner or not messagebox.askyesno(
                "Reopen Decision",
                "Reopen this reconciliation decision?",
                parent=self.ctx.window):
            return
        try:
            self.snapshot.side.add_decision(
                entry["subject"], "reopen", self.ctx.user_name, "owner")
        except (ValueError, OSError) as error:
            if isinstance(error, OSError):
                self.ctx.log.exception("Reopening a reconciliation failed")
            messagebox.showerror("Reconciliation", str(error),
                                 parent=self.ctx.window)
            return
        self.service.invalidate()
