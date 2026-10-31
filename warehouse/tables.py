"""Column definitions + row builders shared by the screens and the exports.

The tables on screen and the Excel / PDF reports are built by the SAME
functions, so an export always shows what the screen shows.

A column is (heading, kind, width in characters); kind is one of
text, date, number, qty. Rows are lists of plain values (date / float /
str / None) - formatting happens in the widget or the exporter.
"""

from fsr_storage import split_quantity_unit

from .analytics import fmt_number
from .inventory import item_history
from .transactions import (NO_WAREHOUSE, normalize_activity, parse_day,
                           split_number)

DATE_FMT = "%d-%b-%Y"

LINE_COLUMNS = [
    ("Date", "date", 11), ("Time", "text", 7),
    ("Transaction ID", "text", 20), ("Report Control #", "text", 15),
    ("SO Number", "text", 15), ("Cargo ID", "text", 16),
    ("Receiving Ref", "text", 24), ("Cargo Description", "text", 32),
    ("Supplier / Shipper", "text", 24), ("Consignee", "text", 22),
    ("Warehouse", "text", 24), ("Quantity", "qty", 10), ("UOM", "text", 7),
    ("Weight (kg)", "number", 11), ("Cargo Condition", "text", 11),
    ("Findings / Remarks", "text", 30), ("Data Check", "text", 30),
]


def line_row(line):
    checks = list(line.problems)
    if line.weight_note:
        checks.append(line.weight_note)
    return [line.date, line.time, line.line_id, line.control_no,
            line.so_number, line.cargo_id, line.receiving_ref,
            line.description, line.supplier, line.consignee, line.warehouse,
            line.quantity, line.unit, line.weight_kg, line.condition,
            "; ".join(t for t in (line.findings, line.remarks) if t),
            "; ".join(checks)]


def line_rows(lines):
    return [line_row(l) for l in lines]


TRANSACTION_COLUMNS = [
    ("Date", "date", 11), ("Time", "text", 7),
    ("Report Control #", "text", 15), ("Activity", "text", 10),
    ("SO Number", "text", 15), ("Supplier / Shipper", "text", 24),
    ("Consignee", "text", 22), ("Warehouse", "text", 24),
    ("Destination", "text", 14), ("Cargo Lines", "number", 8),
    ("Cargo Condition", "text", 11), ("Types of Goods", "text", 16),
]


def transaction_rows(transactions):
    return [[t.date, t.time, t.control_no, t.activity, t.so_number,
             t.supplier, t.consignee, t.warehouse, t.destination,
             t.line_count, t.condition, t.goods_types]
            for t in transactions]


BAD_ORDER_COLUMNS = [
    ("Inspection Date", "date", 11), ("Report Control #", "text", 15),
    ("SO Number", "text", 15), ("Cargo ID", "text", 16),
    ("Cargo Description", "text", 32), ("Supplier / Shipper", "text", 22),
    ("Consignee", "text", 22), ("Warehouse / Location", "text", 24),
    ("Activity", "text", 10), ("Cargo Condition", "text", 10),
    ("Incident Description", "text", 40), ("Remarks", "text", 30),
    ("Case Status", "text", 12),
]


def bad_order_rows(transactions, case_statuses):
    rows = []
    for tx in transactions:
        status = case_statuses.get(tx.control_no, {}).get(
            "status", "Not recorded")
        lines = tx.lines or [None]
        rows.append([
            tx.date, tx.control_no, tx.so_number,
            ", ".join(dict.fromkeys(l.cargo_id for l in tx.lines
                                    if l.cargo_id)),
            "; ".join(dict.fromkeys(l.description for l in tx.lines
                                    if l.description)),
            tx.supplier, tx.consignee, tx.warehouse, tx.activity,
            tx.condition, tx.incident_text,
            "; ".join(t for t in [tx.remarks] + [
                l.findings for l in lines if l and l.findings] if t),
            status])
    return rows


INVENTORY_COLUMNS = [
    ("Cargo ID", "text", 16), ("Inventory Reference", "text", 34),
    ("Cargo Description", "text", 30), ("SO Number", "text", 18),
    ("Purchase Order #", "text", 16), ("Receiving Ref", "text", 26),
    ("Warehouse Location", "text", 24), ("First Receiving", "date", 11),
    ("Last Receiving", "date", 11), ("Qty Received", "qty", 10),
    ("Qty Withdrawn", "qty", 10), ("Remaining Qty", "qty", 10),
    ("UOM", "text", 7), ("Weight Received (kg)", "number", 11),
    ("Weight Withdrawn (kg)", "number", 11),
    ("Remaining Weight (kg)", "number", 11),
    ("Last Withdrawal", "date", 11), ("Days in Warehouse", "number", 8),
    ("Cargo Condition", "text", 12), ("Inventory Status", "text", 22),
    ("Notes", "text", 40),
]


def inventory_row(item):
    return [item.cargo_id, f"{item.warehouse} | {item.identity}",
            item.description, item.so_numbers, item.po_numbers,
            item.receiving_refs, item.warehouse, item.first_received,
            item.last_received, item.received_qty, item.withdrawn_qty,
            item.remaining_qty, item.unit, item.received_kg,
            item.withdrawn_kg, item.remaining_kg, item.last_withdrawal,
            item.age_days, item.condition, item.status_detail,
            "; ".join(i.message for i in item.issues)]


def inventory_rows(items):
    return [inventory_row(i) for i in items]


ISSUE_COLUMNS = [
    ("Issue", "text", 24), ("Severity", "text", 8), ("State", "text", 10),
    ("Line / Item", "text", 22), ("Date", "date", 11),
    ("Activity", "text", 10), ("Cargo ID", "text", 16),
    ("Receiving Ref", "text", 24), ("Description", "text", 28),
    ("Warehouse", "text", 22), ("Quantity", "qty", 9), ("UOM", "text", 7),
    ("Details", "text", 50),
]


def issue_row(issue):
    line, item = issue.line, issue.item
    return [issue.title, issue.severity.title(), issue.state,
            line.line_id if line else (item.identity if item else ""),
            line.date if line else None,
            line.activity if line else "",
            line.cargo_id if line else (item.cargo_id if item else ""),
            line.receiving_ref if line else (item.receiving_refs
                                             if item else ""),
            line.description if line else (item.description if item else ""),
            line.warehouse if line else (item.warehouse if item else ""),
            line.quantity if line else None,
            line.unit if line else (item.unit if item else ""),
            issue.message]


def issue_rows(issues):
    return [issue_row(i) for i in issues]


HISTORY_COLUMNS = [
    ("Date", "date", 11), ("Activity", "text", 10),
    ("Transaction ID", "text", 20), ("Report Control #", "text", 15),
    ("Receiving Ref", "text", 26), ("SO Number", "text", 15),
    ("Quantity", "qty", 9), ("UOM", "text", 7),
    ("Balance After", "qty", 10), ("Weight (kg)", "number", 10),
    ("Cargo Condition", "text", 11), ("Counted", "text", 8),
]


def history_rows(item):
    rows = []
    for event in item_history(item):
        line = event["line"]
        rows.append([event["date"], event["activity"], line.line_id,
                     line.control_no,
                     line.receiving_ref or next(
                         (b.ref for b in item.batches if b.line is line), ""),
                     line.so_number, line.quantity, line.unit,
                     event["balance"], line.weight_kg, line.condition,
                     "Yes" if event["quantity"] is not None else "No"])
    return rows


SUMMARY_REPORT_COLUMNS = [
    ("SO Number", "text", 15), ("Date", "date", 11),
    ("Activity", "text", 10), ("Location / Warehouse", "text", 24),
    ("Shipment Type", "text", 10),
    ("Container Type", "text", 14), ("Supplier", "text", 22),
    ("Broker", "text", 18), ("Hauler", "text", 18),
    ("Destination", "text", 14), ("Origin", "text", 12),
    ("Invoice", "text", 13), ("Purchase Order", "text", 14),
    ("Job Order", "text", 12), ("Gatepass", "text", 12),
    ("BL / AWB", "text", 14), ("DR", "text", 11),
    ("Vehicle Type", "text", 13), ("Plate #", "text", 11),
    ("Description", "text", 30), ("PO", "text", 12),
    ("Packaging", "text", 11), ("Quantity", "text", 10),
    ("Dimension", "text", 13), ("Weight", "text", 11),
    ("Unit Price", "text", 15), ("Total Price", "text", 16),
    ("Cargo Condition", "text", 11), ("Findings / Remarks", "text", 36),
]


def _price(currency, amount):
    """('JPY', '460000') -> 'JPY 460,000.00'; unreadable amounts as typed."""
    number, rest = split_number(amount)
    if number is not None and not rest:
        amount = f"{number:,.2f}"
    return " ".join(t for t in (currency, str(amount or "").strip()) if t)


def summary_report_rows(reports, activity, period):
    """(rows, {currency: total price}) for the reports of `activity`
    inspected within `period`, sorted by date then Control #."""
    chosen = []
    for report in reports or []:
        info = report.get("general_information") or {}
        schedule = report.get("inspection_schedule") or {}
        day = parse_day(info.get("inspection_date"))
        if (normalize_activity(schedule.get("activity")) == activity
                and period.contains(day)):
            chosen.append((day, str(report.get("control_no") or ""), report))
    chosen.sort(key=lambda c: (c[0], c[1]))

    rows, totals = [], {}
    for day, _, report in chosen:
        info = report.get("general_information") or {}
        docs = report.get("documents_used") or {}
        transport = report.get("transport_details") or {}

        def text(source, key):
            return str(source.get(key) or "").strip()

        head = [
            text(info, "so_number"), day, activity,
            text(info, "location") or NO_WAREHOUSE,
            text(transport, "shipment_type"),
            text(transport, "container_type"), text(info, "supplier"),
            text(info, "brokerage"), text(info, "hauler"),
            text(info, "destination"), text(info, "country_of_origin"),
            text(docs, "invoice_number"), text(docs, "po_number"),
            text(docs, "jo_number"), text(docs, "gatepass_number"),
            text(docs, "bl_awb_number"), text(docs, "dr_number"),
            text(transport, "vehicle_type"),
            text(transport, "vehicle_plate_number"),
        ]
        tail = [
            text(report, "cargo_condition"),
            "; ".join(str(t).strip() for t in
                      report.get("other_important_remarks") or []
                      if str(t).strip()),
        ]
        items = [row for section in report.get("item_lists") or []
                 for row in section.get("rows") or []
                 if any(str(v or "").strip() for v in row.values())]
        if not items:
            rows.append(head + [""] * 8 + tail)
            continue
        for row in items:
            quantity, unit = split_quantity_unit(row.get("Quantity"),
                                                 row.get("UOM"))
            currency = text(row, "Currency").upper()
            total, rest = split_number(row.get("Total Price"))
            if total is not None and not rest:
                totals[currency] = totals.get(currency, 0) + total
            rows.append(head + [
                text(row, "Description of Goods"), text(row, "PO Number"),
                text(row, "Packaging"),
                " ".join(t for t in (quantity, unit) if t),
                text(row, "Dimensions"), text(row, "Weights"),
                _price(currency, row.get("Unit Price")),
                _price(currency, row.get("Total Price")),
            ] + tail)
    return rows, totals


def cell_text(value, kind):
    """How a value looks on screen (and in the PDF)."""
    if value is None or value == "":
        return "" if kind not in ("qty", "number") else "-"
    if kind == "date":
        return value.strftime(DATE_FMT) if hasattr(value, "strftime") \
            else str(value)
    if kind in ("qty", "number"):
        return fmt_number(value) if isinstance(value, (int, float)) \
            else str(value)
    return str(value)


def column_totals(columns, rows, unit_column="UOM"):
    """A totals row: quantities per unit (only when one unit), numbers
    summed; text columns blank. Quantities of different units are never
    added: the cell then says 'mixed units'."""
    names = [c[0] for c in columns]
    unit_index = names.index(unit_column) if unit_column in names else None
    units = ({r[unit_index] for r in rows if r[unit_index]}
             if unit_index is not None else set())
    totals = []
    for index, (name, kind, _) in enumerate(columns):
        values = [r[index] for r in rows
                  if isinstance(r[index], (int, float))]
        if kind == "qty":
            totals.append(sum(values) if values and len(units) <= 1
                          else ("mixed units" if values else None))
        elif kind == "number" and "kg" in name.lower():
            totals.append(sum(values) if values else None)
        else:
            totals.append(None)
    totals[0] = "TOTAL"
    return totals
