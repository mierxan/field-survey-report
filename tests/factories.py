"""Small hand-made reports for unit tests (independent of the generator)."""

from datetime import date

import fsr_storage


def report(control, activity, day, warehouse="WH-1", lines=(),
           condition="Good Order", supplier="Sup", consignee="Con",
           so="SO-1", goods="new"):
    """lines: dicts with cargo, qty, unit, ref, desc, weight."""
    rows = []
    for spec in lines:
        row = {h: "" for h in fsr_storage.ITEM_LINE_HEADERS}
        row.update({
            "Description of Goods": spec.get("desc", "Item"),
            "Quantity": "" if spec.get("qty") is None else str(spec["qty"]),
            "Packaging": spec.get("unit", "pcs"),
            "Weights": spec.get("weight", ""),
            "Cargo ID": spec.get("cargo", ""),
            "Receiving Ref": spec.get("ref", ""),
            "PO Number": spec.get("po", ""),
        })
        rows.append(row)
    goods_types = fsr_storage.empty_goods_types()
    if goods:
        goods_types[goods] = True
    text = day.strftime("%d-%b-%Y") if isinstance(day, date) else day
    return {
        "control_no": control,
        "cargo_condition": condition,
        "goods_types": goods_types,
        "incident_reports": [],
        "general_information": {
            "so_number": so, "inspection_date": text,
            "consignee": consignee, "supplier": supplier, "brokerage": "",
            "hauler": "", "location": warehouse, "destination": "",
            "country_of_origin": ""},
        "inspection_schedule": {"activity": activity, "commenced_date": text,
                                "commenced_time": "0800H",
                                "completion_date": "", "completion_time": ""},
        "transport_details": {k: "" for _, k, *_ in
                              fsr_storage.TRANSPORT_FIELDS},
        "documents_used": {k: "" for _, k in fsr_storage.DOCUMENT_FIELDS},
        "declared_goods": [],
        "other_important_remarks": [],
        "item_lists": [{"name": "Item List 1", "rows": rows}],
        "findings_and_remarks": [],
    }


def rec(control, day, cargo, qty, unit="pcs", warehouse="WH-1", **kw):
    line = {"cargo": cargo, "qty": qty, "unit": unit}
    for key in ("ref", "desc", "weight", "po"):
        if key in kw:
            line[key] = kw.pop(key)
    return report(control, "Receiving", day, warehouse, [line], **kw)


def wdr(control, day, cargo, qty, unit="pcs", warehouse="WH-1", **kw):
    line = {"cargo": cargo, "qty": qty, "unit": unit}
    for key in ("ref", "desc", "weight", "po"):
        if key in kw:
            line[key] = kw.pop(key)
    return report(control, "Withdrawal", day, warehouse, [line], **kw)


def ledger(reports, as_of=date(2026, 10, 29), decisions=None):
    from warehouse.inventory import build_inventory
    from warehouse.transactions import build_transactions
    return build_inventory(build_transactions(reports), decisions, as_of)
