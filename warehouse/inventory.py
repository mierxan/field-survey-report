"""The inventory ledger built from Receiving and Withdrawal lines.

Identification (never by description):
  * an inventory item = (warehouse, Cargo ID). A Receiving line without a
    Cargo ID is its own item, identified by its Receiving Ref.
  * a Withdrawal line is matched by its Receiving Ref (a batch) or by its
    Cargo ID - in the SAME warehouse only (transfers are not assumed).
  * anything else is "unmatched" and goes to reconciliation. A person may
    then link it (propose -> confirm) or exclude it; those decisions come
    from the warehouse side file and never change the original report.

Balances:  Remaining = Total Received - Total Withdrawn, only when every
counted line has a quantity and all use the same unit. Otherwise the item
is "Reconciliation Required" and no balance is shown. Negative balances are
kept (Over-Withdrawn), never forced to zero.
"""

from dataclasses import dataclass, field
from datetime import date

from fsr_storage import default_receiving_ref

from .transactions import RECEIVING, WITHDRAWAL, BAD_ORDER, GOOD_ORDER, \
    norm_key

STATUS_IN_STOCK = "In Stock"
STATUS_PARTIAL = "Partially Withdrawn"
STATUS_FULL = "Fully Withdrawn"
STATUS_OVER = "Over-Withdrawn"
STATUS_RECON = "Reconciliation Required"
STATUSES = [STATUS_IN_STOCK, STATUS_PARTIAL, STATUS_FULL, STATUS_OVER,
            STATUS_RECON]
NO_WITHDRAWAL = "No Recorded Withdrawal"

DEFAULT_AGING_THRESHOLDS = (7, 30, 60, 90)
TOLERANCE = 1e-9

# Issue kinds (what needs reconciliation) -> short title.
ISSUE_TITLES = {
    "unmatched_withdrawal": "Unmatched Withdrawal",
    "link_target_missing": "Linked Item Not Found",
    "missing_quantity": "Missing / Invalid Quantity",
    "unit_mismatch": "Unit of Measure Mismatch",
    "mixed_units": "Incompatible Units Received",
    "duplicate_receiving_ref": "Duplicate Receiving Ref",
    "over_withdrawal": "Over-Withdrawal",
    "withdrawal_before_receiving": "Withdrawal Dated Before Receiving",
    "batch_over_withdrawn": "Batch Over-Withdrawn",
    "missing_date": "Missing / Invalid Date",
}
# Kinds that make a balance unreliable (the item becomes Reconciliation
# Required). The others are reported but leave the balance usable.
BLOCKING_KINDS = {"missing_quantity", "unit_mismatch", "mixed_units",
                  "withdrawal_before_receiving"}

# Decision states (from the reconciliation log).
OPEN = "Open"
PROPOSED = "Proposed"
CONFIRMED = "Confirmed"
REJECTED = "Rejected"
EXCLUDED = "Excluded"
ACCEPTED = "Accepted"
RESOLVED_STATES = {CONFIRMED, EXCLUDED, ACCEPTED}


@dataclass
class LineDecision:
    state: str = OPEN
    target: dict | None = None      # {"warehouse", "cargo_id", "receiving_ref"}
    note: str = ""


@dataclass
class Batch:
    line: object                    # the Receiving TransactionLine
    ref: str
    quantity: float | None
    remaining: float | None = None  # after FIFO allocation of withdrawals


@dataclass
class Issue:
    kind: str
    message: str
    line: object = None             # TransactionLine, when about one line
    item: object = None             # InventoryItem, when known
    severity: str = "error"
    state: str = OPEN

    @property
    def title(self):
        return ISSUE_TITLES.get(self.kind, self.kind)

    @property
    def issue_id(self):
        if self.line is not None:
            return f"{self.kind}:{self.line.line_id}"
        return f"{self.kind}:{self.item.key_text if self.item else ''}"

    @property
    def subject_id(self):
        """What a reconciliation decision is recorded against."""
        if self.line is not None:
            return self.line.line_id
        return f"item:{self.item.key_text}" if self.item else ""

    @property
    def is_open(self):
        return self.state not in RESOLVED_STATES


@dataclass
class InventoryItem:
    warehouse: str
    cargo_id: str
    identity: str                   # cargo ID, or the Receiving Ref
    key: tuple
    batches: list = field(default_factory=list)
    withdrawals: list = field(default_factory=list)     # counted lines
    unit: str = ""
    received_qty: float | None = None
    withdrawn_qty: float = 0.0
    remaining_qty: float | None = None
    received_kg: float | None = None
    withdrawn_kg: float | None = None
    remaining_kg: float | None = None
    status: str = STATUS_RECON
    issues: list = field(default_factory=list)
    age_days: int | None = None
    withdrawal_batch: dict = field(default_factory=dict)  # line id -> Batch
    counted_ids: set = field(default_factory=set)         # counted lines

    def counted_withdrawals(self):
        return [w for w in self.withdrawals if w.line_id in self.counted_ids]

    def is_counted(self, line):
        return line.line_id in self.counted_ids

    @property
    def key_text(self):
        return f"{self.key[0]}|{self.key[1]}"

    @property
    def receipts(self):
        return [batch.line for batch in self.batches]

    def _values(self, name):
        seen = []
        for line in self.receipts + self.withdrawals:
            value = getattr(line, name)
            if value and value not in seen:
                seen.append(value)
        return seen

    @property
    def description(self):
        values = [b.line.description for b in self.batches
                  if b.line.description]
        return values[0] if values else ""

    @property
    def so_numbers(self):
        return ", ".join(self._values("so_number"))

    @property
    def po_numbers(self):
        return ", ".join(self._values("po_number"))

    @property
    def suppliers(self):
        return ", ".join(dict.fromkeys(
            b.line.supplier for b in self.batches if b.line.supplier))

    @property
    def consignees(self):
        return ", ".join(self._values("consignee"))

    @property
    def receiving_refs(self):
        return ", ".join(b.ref for b in self.batches)

    @property
    def first_received(self):
        days = [b.line.date for b in self.batches if b.line.date]
        return min(days) if days else None

    @property
    def last_received(self):
        days = [b.line.date for b in self.batches if b.line.date]
        return max(days) if days else None

    @property
    def last_withdrawal(self):
        days = [w.date for w in self.withdrawals if w.date]
        return max(days) if days else None

    @property
    def condition(self):
        conditions = {b.line.condition for b in self.batches}
        if conditions == {BAD_ORDER}:
            return BAD_ORDER
        if BAD_ORDER in conditions:
            return "Mixed (Good / Bad Order)"
        return GOOD_ORDER

    @property
    def has_bad_order(self):
        return any(b.line.condition == BAD_ORDER for b in self.batches)

    @property
    def no_recorded_withdrawal(self):
        return not self.withdrawals

    @property
    def status_detail(self):
        if self.status == STATUS_IN_STOCK:
            return f"{STATUS_IN_STOCK} - {NO_WITHDRAWAL}"
        return self.status


@dataclass
class AgingRow:
    item: InventoryItem
    batch: Batch
    remaining: float
    age_days: int
    bucket: str


@dataclass
class Inventory:
    as_of: date
    items: list
    issues: list
    unmatched: list                 # Issues of unmatched withdrawals
    excluded_lines: list            # (line, reason) not counted on purpose
    aging_rows: list
    aging_excluded: list            # (item or batch line, reason)
    thresholds: tuple

    # ---- views ----
    def by_status(self, status):
        return [i for i in self.items if i.status == status]

    def remaining_items(self):
        """Positive recorded balance (In Stock + Partially Withdrawn)."""
        return [i for i in self.items
                if i.remaining_qty is not None
                and i.remaining_qty > TOLERANCE]

    def no_withdrawal_items(self):
        return [i for i in self.items if i.no_recorded_withdrawal]

    def open_issues(self):
        return [i for i in self.issues if i.is_open]

    def item(self, warehouse, cargo_id):
        key = (norm_key(warehouse), "id:" + norm_key(cargo_id))
        return next((i for i in self.items if i.key == key), None)

    def status_counts(self):
        counts = {status: 0 for status in STATUSES}
        for item in self.items:
            counts[item.status] += 1
        return counts

    def aging_buckets(self):
        """{bucket label: (batches, {unit: remaining quantity})}."""
        result = {label: [0, {}] for label in bucket_labels(self.thresholds)}
        for row in self.aging_rows:
            entry = result[row.bucket]
            entry[0] += 1
            unit = row.item.unit or "(no unit)"
            entry[1][unit] = entry[1].get(unit, 0) + row.remaining
        return {k: (v[0], v[1]) for k, v in result.items()}


def bucket_labels(thresholds=DEFAULT_AGING_THRESHOLDS):
    labels, low = [], 0
    for high in thresholds:
        labels.append(f"{low}-{high} Days")
        low = high + 1
    labels.append(f"More Than {thresholds[-1]} Days")
    return labels


def aging_bucket(age_days, thresholds=DEFAULT_AGING_THRESHOLDS):
    labels = bucket_labels(thresholds)
    for label, high in zip(labels, thresholds):
        if age_days <= high:
            return label
    return labels[-1]


def line_numbers(line_id):
    control, list_no, line_no = line_id.rsplit("/", 2)
    return control, int(list_no), int(line_no)


def effective_ref(line):
    """The batch reference of a Receiving line: the saved one, or for
    reports saved before the warehouse links existed, the same reference
    the program would have generated."""
    if line.receiving_ref:
        return line.receiving_ref
    return default_receiving_ref(*line_numbers(line.line_id))


def _same(a, b):
    return abs(a - b) <= TOLERANCE


def build_inventory(transactions, decisions=None, as_of=None,
                    thresholds=DEFAULT_AGING_THRESHOLDS):
    """The ledger of all Receiving / Withdrawal lines dated up to `as_of`
    (undated lines are included and flagged). `decisions` maps a subject id
    (line id or "item:<key>") to a LineDecision."""
    as_of = as_of or date.today()
    decisions = decisions or {}
    thresholds = tuple(sorted(int(t) for t in thresholds))

    lines = [line for tx in transactions for line in tx.lines
             if line.activity in (RECEIVING, WITHDRAWAL)
             and (line.date is None or line.date <= as_of)]
    lines.sort(key=lambda l: (l.date or date.min, l.line_id))

    items, issues, unmatched, excluded = {}, [], [], []
    by_ref, by_cargo = {}, {}

    def decision(subject):
        return decisions.get(subject, LineDecision())

    def add_issue(kind, message, line=None, item=None, severity="error"):
        issue = Issue(kind, message, line, item, severity)
        issue.state = decision(issue.subject_id if line or item else "").state
        if kind not in ("unmatched_withdrawal", "link_target_missing",
                        "duplicate_receiving_ref"):
            # only notes can be recorded against these: the source report
            # has to be corrected, so they stay open until it is
            issue.state = OPEN
        issues.append(issue)
        if item is not None:
            item.issues.append(issue)
        return issue

    # ---- 1. Receiving lines -> batches ----
    for line in (l for l in lines if l.activity == RECEIVING):
        if line.date is None:
            add_issue("missing_date", "Receiving line has no valid "
                      "Inspection Date (left out of aging)", line,
                      severity="warning")
        ref = effective_ref(line)
        ref_key = norm_key(ref)
        if ref_key in by_ref:
            first = by_ref[ref_key][1].line
            state = decision(line.line_id).state
            if state != ACCEPTED:
                issue = add_issue(
                    "duplicate_receiving_ref",
                    f"Receiving Ref {ref} was already recorded on "
                    f"{first.line_id}; this line is NOT counted (accept it "
                    "as a separate batch if it is not a duplicate)", line)
                if state == EXCLUDED:
                    issue.state = EXCLUDED
                excluded.append((line, "Duplicate Receiving Ref"))
                continue
            ref = f"{ref}#{line.line_id}"
            ref_key = norm_key(ref)
        key = ((line.warehouse_key, "id:" + line.cargo_key) if line.cargo_id
               else (line.warehouse_key, "ref:" + ref_key))
        item = items.get(key)
        if item is None:
            item = items[key] = InventoryItem(
                warehouse=line.warehouse, cargo_id=line.cargo_id,
                identity=line.cargo_id or ref, key=key)
            if line.cargo_id:
                by_cargo.setdefault(line.cargo_key, []).append(item)
        batch = Batch(line, ref, line.quantity)
        item.batches.append(batch)
        by_ref[ref_key] = (item, batch)
        if line.quantity is None:
            add_issue("missing_quantity",
                      "; ".join(line.problems) or "Quantity is missing",
                      line, item)

    # ---- 2. Withdrawal lines -> matched to an item, or unmatched ----
    for line in (l for l in lines if l.activity == WITHDRAWAL):
        if line.date is None:
            add_issue("missing_date", "Withdrawal line has no valid "
                      "Inspection Date", line, severity="warning")
        chosen = decision(line.line_id)
        if chosen.state == EXCLUDED:
            excluded.append((line, chosen.note or "Excluded during "
                             "reconciliation"))
            issue = add_issue("unmatched_withdrawal",
                              "Excluded during reconciliation"
                              + (f": {chosen.note}" if chosen.note else ""),
                              line)
            issue.state = EXCLUDED
            continue

        item, batch, reason = None, None, ""
        if chosen.state == CONFIRMED and chosen.target:
            item, batch, reason = _resolve_target(chosen.target, by_ref,
                                                  items)
            if item is None:
                add_issue("link_target_missing",
                          f"The confirmed link points to an item that is "
                          f"not in the records any more ({reason})", line)
                continue
        else:
            item, batch, reason = _match(line, by_ref, by_cargo)

        if item is None:
            issue = add_issue("unmatched_withdrawal", reason, line)
            unmatched.append(issue)
            continue

        item.withdrawals.append(line)
        item.withdrawal_batch[line.line_id] = batch  # batch-specific or None
        if line.quantity is None:
            add_issue("missing_quantity",
                      "; ".join(line.problems) or "Quantity is missing",
                      line, item)
        else:
            item.counted_ids.add(line.line_id)

    # ---- 3. balances, statuses, aging ----
    aging_rows, aging_excluded = [], []
    for item in items.values():
        _settle(item, add_issue)
        _allocate_and_age(item, as_of, thresholds, aging_rows,
                          aging_excluded, add_issue)

    ordered = sorted(items.values(),
                     key=lambda i: (norm_key(i.warehouse), norm_key(i.identity)))
    return Inventory(as_of, ordered, issues, unmatched, excluded, aging_rows,
                     aging_excluded, thresholds)


def _resolve_target(target, by_ref, items):
    ref = norm_key(target.get("receiving_ref"))
    if ref:
        found = by_ref.get(ref)
        if found:
            return found[0], found[1], ""
        return None, None, f"Receiving Ref {target.get('receiving_ref')}"
    key = (norm_key(target.get("warehouse")),
           "id:" + norm_key(target.get("cargo_id")))
    if key in items:
        return items[key], None, ""
    return None, None, (f"Cargo ID {target.get('cargo_id')} in "
                        f"{target.get('warehouse')}")


def _match(line, by_ref, by_cargo):
    """(item, batch or None, reason when unmatched)."""
    if line.receiving_ref:
        found = by_ref.get(line.ref_key)
        if found is None:
            return None, None, (f"Receiving Ref {line.receiving_ref} was "
                                "not found in the Receiving records")
        item, batch = found
        if item.key[0] != line.warehouse_key:
            return None, None, (f"Receiving Ref {line.receiving_ref} was "
                                f"received at {item.warehouse}, not at "
                                f"{line.warehouse}")
        if line.cargo_id and norm_key(item.cargo_id) != line.cargo_key:
            return None, None, (f"Cargo ID {line.cargo_id} does not match "
                                f"Receiving Ref {line.receiving_ref} "
                                f"(Cargo ID {item.cargo_id or 'none'})")
        return item, batch, ""
    if line.cargo_id:
        candidates = by_cargo.get(line.cargo_key, [])
        same_place = [i for i in candidates if i.key[0] == line.warehouse_key]
        if same_place:
            return same_place[0], None, ""
        if candidates:
            places = ", ".join(i.warehouse for i in candidates)
            return None, None, (f"Cargo ID {line.cargo_id} was received at "
                                f"{places}, not at {line.warehouse}")
        return None, None, (f"Cargo ID {line.cargo_id} was not found in "
                            "the Receiving records")
    return None, None, ("No Cargo ID or Receiving Ref - the withdrawal "
                        "cannot be linked (descriptions are never used "
                        "to match)")


def _settle(item, add_issue):
    counted = item.counted_withdrawals()
    units = {b.line.unit for b in item.batches if b.quantity is not None}
    if len(units) > 1:
        add_issue("mixed_units",
                  "Received in different units: "
                  + ", ".join(sorted(u or "(none)" for u in units))
                  + " - no conversion rule, so no balance", item=item)
    item.unit = next(iter(units)) if len(units) == 1 else (
        "/".join(sorted(u or "?" for u in units)) if units else "")

    for line in list(counted):
        if len(units) == 1 and line.unit != item.unit:
            add_issue("unit_mismatch",
                      f"Withdrawn in '{line.unit or 'no unit'}' but the item "
                      f"was received in '{item.unit or 'no unit'}'",
                      line, item)
            item.counted_ids.discard(line.line_id)
            counted.remove(line)
        elif item.first_received and line.date \
                and line.date < item.first_received:
            add_issue("withdrawal_before_receiving",
                      f"Withdrawn on {line.date:%d-%b-%Y}, before the first "
                      f"receiving on {item.first_received:%d-%b-%Y}",
                      line, item)

    known = [b.quantity for b in item.batches if b.quantity is not None]
    item.received_qty = sum(known) if known else None
    item.withdrawn_qty = sum(w.quantity for w in counted)

    blocked = any(i.kind in BLOCKING_KINDS for i in item.issues)
    if blocked or item.received_qty is None:
        item.status = STATUS_RECON
        item.remaining_qty = None
    else:
        item.remaining_qty = item.received_qty - item.withdrawn_qty
        if item.remaining_qty < -TOLERANCE:
            item.status = STATUS_OVER
            add_issue("over_withdrawal",
                      f"Withdrawn {item.withdrawn_qty:g} {item.unit} but "
                      f"only {item.received_qty:g} {item.unit} received "
                      f"(balance {item.remaining_qty:g})", item=item)
        elif _same(item.remaining_qty, 0):
            item.remaining_qty = 0.0
            item.status = STATUS_FULL
        elif not item.withdrawals:
            item.status = STATUS_IN_STOCK
        else:
            item.status = STATUS_PARTIAL

    # Weights: only when every counted line has a weight in a known unit.
    weights = [b.line.weight_kg for b in item.batches]
    item.received_kg = (sum(weights) if weights and None not in weights
                        else None)
    w_weights = [w.weight_kg for w in counted]
    item.withdrawn_kg = (sum(w_weights) if None not in w_weights else None)
    item.remaining_kg = (item.received_kg - item.withdrawn_kg
                         if item.status != STATUS_RECON
                         and item.received_kg is not None
                         and item.withdrawn_kg is not None else None)


def _allocate_and_age(item, as_of, thresholds, aging_rows, aging_excluded,
                      add_issue):
    """FIFO: withdrawals that name a batch come off that batch first; the
    rest come off the oldest batches. Aging is per batch that still has a
    remaining balance."""
    if item.status == STATUS_RECON:
        for batch in item.batches:
            batch.remaining = None
        aging_excluded.append((item, "Balance not established "
                               "(reconciliation required)"))
        return
    for batch in item.batches:
        batch.remaining = batch.quantity
    pool = 0.0
    for line in item.counted_withdrawals():
        batch = item.withdrawal_batch.get(line.line_id)
        if batch is not None:
            take = min(line.quantity, max(batch.remaining, 0))
            batch.remaining -= take
            if line.quantity - take > TOLERANCE:
                add_issue("batch_over_withdrawn",
                          f"{line.quantity:g} {item.unit} withdrawn from "
                          f"batch {batch.ref}, which had only "
                          f"{take:g} left; the rest is taken from the "
                          "item's other batches", line, item,
                          severity="warning")
                pool += line.quantity - take
        else:
            pool += line.quantity
    ordered = sorted(item.batches,
                     key=lambda b: (b.line.date or date.max, b.line.line_id))
    for batch in ordered:
        take = min(pool, max(batch.remaining, 0))
        batch.remaining -= take
        pool -= take

    oldest = None
    for batch in ordered:
        if batch.remaining is None or batch.remaining <= TOLERANCE:
            continue
        if batch.line.date is None:
            aging_excluded.append((batch.line, "No valid Receiving date"))
            continue
        age = (as_of - batch.line.date).days
        aging_rows.append(AgingRow(item, batch, batch.remaining, age,
                                   aging_bucket(age, thresholds)))
        oldest = age if oldest is None else max(oldest, age)
    item.age_days = oldest


def item_history(item):
    """Receiving and Withdrawal lines of an item in date order, with the
    running balance after each (None once a line cannot be counted)."""
    events = [(b.line.date, 0, b.line, b.quantity) for b in item.batches]
    events += [(w.date, 1, w, w.quantity if item.is_counted(w) else None)
               for w in item.withdrawals]
    events.sort(key=lambda e: (e[0] or date.min, e[1], e[2].line_id))
    balance, rows = 0.0, []
    for day, order, line, qty in events:
        if balance is not None:
            balance = None if qty is None else (
                balance + qty if order == 0 else balance - qty)
        rows.append({"date": day, "activity": line.activity, "line": line,
                     "quantity": qty, "balance": balance})
    return rows


def suggest_matches(line, inventory, limit=10):
    """Possible items for an unmatched withdrawal, best first, with WHY.
    Only suggestions - a person must confirm a link."""
    suggestions = []
    for item in inventory.items:
        reasons, score = [], 0
        if line.cargo_id and norm_key(item.cargo_id) == line.cargo_key:
            reasons.append("same Cargo ID")
            score += 50
        if line.so_number and line.so_number in item.so_numbers.split(", "):
            reasons.append("same SO Number")
            score += 20
        if line.po_number and line.po_number in item.po_numbers.split(", "):
            reasons.append("same PO Number")
            score += 20
        if item.key[0] == line.warehouse_key:
            if score:
                reasons.append("same warehouse")
                score += 10
        if line.description and norm_key(item.description) == \
                norm_key(line.description):
            reasons.append("same description only (verify!)")
            score += 5
        if score:
            suggestions.append((score, item, ", ".join(reasons)))
    suggestions.sort(key=lambda s: -s[0])
    return [(item, why) for _, item, why in suggestions[:limit]]
