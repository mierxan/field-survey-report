"""Convert the old application's master data CSV for Import Master Data.

The old file has one row per cargo line: a row with a Comdiv # starts a record,
rows without one continue it. This module turns the records into an
fsr-master-data file (see fsr_import.py), which then goes through the normal
import: backup, ledger, renumbering and the MySQL copy all work as for a phone.

It only reads the CSV and the target workbook. Values are moved as they are;
a field the old file does not have stays blank. Records that cannot be placed
safely (no valid date, possible duplicate) are held back and reported.

  python fsr_legacy_import.py "Old_Master Data.csv" --target data.xlsx --out folder
"""
import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import fsr_import
import fsr_storage as storage

DEVICE_ID = "legacy-old-master-csv"
CONTROL_PREFIX = "OLD"
OTHER_REMARKS_MAX = 12          # lines on the First Page form
ITEM_LIST_MAX_LINES = 30        # lines of one Item List on the Cargo Details form

EXPECTED_HEADERS = [
    "Comdiv #", "Activity", "Container type", "Shipment type", "Date",
    "Location", "Consignee", "Supplier", "Broker", "Hauler", "Destination",
    "Origin", "Invoice", "Purchased order", "Job Order", "Gatepass",
    "BL / AWB", "DR/WB", "other marks", "Plate#/Vehicle type", "Description",
    "Packaging", "Quatity", "Dimension", "Weight", "Unit price", "Total price",
    "Total invoice value", "Condition", "Other Important Remarks",
]
LINE_COLUMNS = EXPECTED_HEADERS[EXPECTED_HEADERS.index("Description"):
                                EXPECTED_HEADERS.index("Total invoice value")]

# MySQL column sizes (data/schema/field_survey_schema.sql): values that are
# longer than the existing columns cannot be saved.
TEXT_LIMITS = {
    "so_number": 100, "consignee": 200, "supplier": 200, "brokerage": 200,
    "hauler": 200, "location": 200, "destination": 200,
    "country_of_origin": 100, "vehicle_type": 100, "vehicle_plate_number": 50,
    "invoice_number": 100, "po_number": 100, "jo_number": 100,
    "gatepass_number": 100, "bl_awb_number": 100, "dr_number": 100,
    "other_documents": 255,
}
LINE_LIMITS = {
    "Description of Goods": 500, "Packaging": 100, "Quantity": 100,
    "Dimensions": 100, "Weights": 100, "Unit Price": 100, "Total Price": 100,
    "Findings": 500, "UOM": 30,
}
LIST_FIELDS = {
    "consignee_list": "consignee", "supplier_list": "supplier",
    "broker_list": "brokerage", "hauler_list": "hauler",
    "location_list": "location", "destination_list": "destination",
    "country_of_origin_list": "country_of_origin",
}

PLACEHOLDERS = {"", "n/a", "na", "n.a", "n/", "n/aa", "b/a", "m/a", "n./a",
                "n/.a", "n.a.", "'", "''"}
DITTO = {"'", "''"}
PLATE = re.compile(r"^(?:Plate#:\s*)?([A-Z]{3}\s?\d{3,4})$")
MONEY = re.compile(
    r"^(php|usd|jpy|eur|sek)\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\.?-+)?$",
    re.I)
BULLET_BREAK = re.compile(r",\s*(?=-\S)|,\s*,(?:\s*,)*\s*")
TOKEN = re.compile(r"\d{4,}")


class LegacyFileError(ValueError):
    """The chosen file is not the old master data CSV."""


def read_rows(path):
    """[(CSV line number, {column: trimmed value})]. The file is not changed."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    reader = csv.reader(text.splitlines(keepends=True))
    headers = [h.strip() for h in next(reader, [])]
    if headers != EXPECTED_HEADERS:
        raise LegacyFileError("The columns are not those of the old master data.")
    return [
        (reader.line_num, {h: value.strip() for h, value in zip(headers, row)})
        for row in reader
    ]


def group_records(rows):
    """(records, dropped). A record: {"line", "head", "lines": [(no, row)]}.
    dropped holds rows with no information, or none that belongs to a record."""
    records, dropped = [], []
    current = None
    for line_no, row in rows:
        if row.get("Comdiv #"):
            current = {"line": line_no, "head": row, "lines": [(line_no, row)]}
            records.append(current)
        elif not any(row.values()):
            continue
        elif current is None or row_is_empty_line(row):
            dropped.append((line_no, row))
        else:
            current["lines"].append((line_no, row))
    return records, dropped


def row_is_empty_line(row):
    """Only placeholders in the cargo columns and nothing else of use."""
    return (not row.get("Other Important Remarks", "").strip(", ")
            and not row.get("Description")
            and all(_is_placeholder(row.get(c)) for c in LINE_COLUMNS
                    if c != "Packaging"))


def _is_placeholder(value):
    return str(value or "").strip().casefold() in PLACEHOLDERS


def legacy_date(text):
    """'05-Jan-26' -> '05-Jan-2026'; None when it is not exactly that form."""
    try:
        return datetime.strptime(text, "%d-%b-%y").strftime(storage.DATE_FORMAT)
    except (ValueError, TypeError):
        return None


def split_vehicle(text):
    """(vehicle type, plate). Split only when one side is clearly a plate;
    anything else stays whole in Vehicle Type (the bool says so)."""
    match = PLATE.match(text)
    if match:
        return "", match.group(1), False
    parts = [part.strip() for part in text.split(" / ")]
    if len(parts) == 2:
        plates = [PLATE.match(part) for part in parts]
        if plates[1] and not plates[0]:
            return parts[0], plates[1].group(1), False
        if plates[0] and not plates[1]:
            return parts[1], plates[0].group(1), False
    return text, "", not _is_placeholder(text)


def split_money(unit, total):
    """(unit price, total price, currency, ok). Numbers lose their currency
    prefix only if it is clear; otherwise both stay exactly as written."""
    found = [MONEY.match(unit), MONEY.match(total)]
    currencies = {m.group(1).upper() for m in found if m}
    usable = all(m or _is_placeholder(v) for m, v in zip(found, (unit, total)))
    if not usable or len(currencies) > 1:
        return unit, total, "", False
    return (
        found[0].group(2) if found[0] else unit,
        found[1].group(2) if found[1] else total,
        currencies.pop() if currencies else "",
        True,
    )


def split_remarks(text):
    """One remark per '-' bullet / note. The old file joined form lines with
    ', ' and that cannot be undone exactly, so inner commas stay."""
    return [part.strip(" ,") for part in BULLET_BREAK.split(text or "")
            if part.strip(" ,")]


def _container(text):
    return next((v for v in storage.CHOICE_VALUES["container_type"]
                 if v.casefold() == text.casefold()), text)


def _condition(text):
    return next((v for v in (storage.CONDITION_GOOD, storage.CONDITION_BAD)
                 if v.casefold() == text.casefold()), "")


def _price_gap(row):
    """A saved total that differs from quantity x unit price (reported only)."""
    numbers = [storage.to_number(row[h])
               for h in ("Quantity", "Unit Price", "Total Price")]
    if not all(isinstance(n, (int, float)) for n in numbers):
        return False
    expected = numbers[0] * numbers[1]
    return abs(expected - numbers[2]) > max(1.0, abs(expected) * 0.01)


def convert_record(record):
    """{"report", "issues": [(code, detail)], "invoice_value"}."""
    head = record["head"]
    issues = []

    def note(code, detail=""):
        issues.append((code, detail))

    date_text = legacy_date(head["Date"])
    if not date_text:
        note("invalid_date", head["Date"] or "(blank)")

    vehicle_type, plate, unclear = split_vehicle(head["Plate#/Vehicle type"])
    if unclear:
        note("vehicle_not_split", head["Plate#/Vehicle type"])

    condition = _condition(head["Condition"])
    if not condition:
        note("condition_missing", head["Condition"] or "(blank)")
    elif condition == storage.CONDITION_BAD:
        note("bad_order_no_incident")

    rows, remarks = [], []
    for line_no, source in record["lines"]:
        for line in split_remarks(source["Other Important Remarks"]):
            if line not in remarks:
                remarks.append(line)
        if line_no == record["line"] and not any(
                source[c] for c in LINE_COLUMNS):
            note("no_cargo_line")
            continue
        unit, total, currency, money_ok = split_money(
            source["Unit price"], source["Total price"])
        if not money_ok:
            note("price_not_split",
                 f"line {line_no}: {source['Unit price']} | {source['Total price']}")
        quantity, uom = storage.split_quantity_unit(source["Quatity"])
        row = {header: "" for header in storage.ITEM_LINE_HEADERS}
        row.update({
            "Description of Goods": source["Description"],
            "Packaging": source["Packaging"],
            "Quantity": quantity,
            "UOM": uom,
            "Dimensions": source["Dimension"],
            "Weights": source["Weight"],
            "Unit Price": unit,
            "Total Price": total,
            "Currency": currency,
        })
        # A condition written on a continuation row belongs to that line.
        if line_no != record["line"]:
            row["Findings"] = source["Condition"]
        if not source["Description"]:
            note("line_without_description", f"line {line_no}")
        if any(source[c] in DITTO for c in LINE_COLUMNS):
            note("ditto_mark_kept", f"line {line_no}")
        if _price_gap(row):
            note("total_differs_from_qty_x_price", f"line {line_no}")
        for header, limit in LINE_LIMITS.items():
            if len(row[header]) > limit:
                note("value_too_long", f"line {line_no} {header}")
        rows.append(row)

    if len(remarks) > OTHER_REMARKS_MAX:
        note("remarks_over_form_limit", str(len(remarks)))

    item_lists = [
        {"name": f"Item List {n // ITEM_LIST_MAX_LINES + 1}",
         "rows": rows[n:n + ITEM_LIST_MAX_LINES]}
        for n in range(0, len(rows), ITEM_LIST_MAX_LINES)
    ] or [{"name": "Item List 1", "rows": []}]

    report = {
        "cargo_condition": condition or storage.CONDITION_GOOD,
        "goods_types": storage.empty_goods_types(),
        "item_form": storage.ITEM_FORM_DEFAULT,
        "incident_reports": [],
        "other_item_forms": {},
        "general_information": {
            "so_number": head["Comdiv #"],
            "inspection_date": date_text or head["Date"],
            "consignee": head["Consignee"],
            "supplier": head["Supplier"],
            "brokerage": head["Broker"],
            "hauler": head["Hauler"],
            "location": head["Location"],
            "destination": head["Destination"],
            "country_of_origin": head["Origin"],
        },
        "inspection_schedule": {
            "activity": head["Activity"],
            "commenced_date": "", "commenced_time": "",
            "completion_date": "", "completion_time": "",
        },
        "transport_details": {
            "vessel_carrier": "",
            "vehicle_type": vehicle_type,
            "vehicle_plate_number": plate,
            "shipment_type": head["Shipment type"],
            "container_type": _container(head["Container type"]),
        },
        "documents_used": {
            "invoice_number": head["Invoice"],
            "po_number": head["Purchased order"],
            "jo_number": head["Job Order"],
            "gatepass_number": head["Gatepass"],
            "bl_awb_number": head["BL / AWB"],
            "dr_number": head["DR/WB"],
            "other_documents": head["other marks"],
        },
        "declared_goods": [],
        "other_important_remarks": remarks,
        "item_lists": item_lists,
        "findings_and_remarks": [],
    }

    flat = {**report["general_information"], **report["transport_details"],
            **report["documents_used"]}
    for key, limit in TEXT_LIMITS.items():
        if len(flat.get(key) or "") > limit:
            note("value_too_long", key)
    if head["Activity"] not in storage.CHOICE_VALUES["activity"]:
        note("activity_unknown", head["Activity"] or "(blank)")
    if head["Supplier"] == "EDC-DHL warehouse" and head["Activity"] == "Receiving":
        note("receiving_from_own_warehouse")
    if not head["Location"] or not head["Supplier"]:
        note("possible_second_page")
    if len(head["Location"]) == 1 or head["Destination"].startswith("DR#"):
        note("value_in_wrong_column",
             f"{head['Location']} | {head['Destination']}")
    if "E+" in head["Invoice"] or re.fullmatch(r"\d{1,3}(,\d{3}){3,}",
                                               head["Purchased order"]):
        note("number_damaged_by_spreadsheet",
             head["Invoice"] if "E+" in head["Invoice"] else head["Purchased order"])

    report["control_no"] = _control_no(record, date_text)
    report["last_saved"] = "legacy-" + _digest(json.dumps(report, sort_keys=True))
    return {"report": report, "issues": issues, "line": record["line"],
            "invoice_value": head["Total invoice value"]}


def _digest(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:6].upper()


def _control_no(record, date_text):
    """Stable, so running the import again finds the same report in the ledger."""
    head = record["head"]
    period = (datetime.strptime(date_text, storage.DATE_FORMAT).strftime("%y%m")
              if date_text else "0000")
    identity = "|".join(head[c] for c in (
        "Comdiv #", "Activity", "Date", "Supplier", "Purchased order", "DR/WB",
        "Gatepass", "Destination", "Description"))
    return f"{CONTROL_PREFIX}-{period}-{_digest(identity)}"


# ---------- possible duplicates ------------------------------

def _tokens(*values):
    return {t for value in values for t in TOKEN.findall(str(value or ""))}


def _norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _facts(report):
    general = report["general_information"]
    documents = report["documents_used"]
    rows = [row for item_list in report["item_lists"] for row in item_list["rows"]]
    date = storage.parse_date(general["inspection_date"])
    return {
        "activity": _norm(report["inspection_schedule"]["activity"]),
        "date": date if isinstance(date, datetime) else None,
        "supplier": _norm(general["supplier"]),
        "destination": _norm(general["destination"]),
        "po": _tokens(documents["po_number"]),
        "dr": _tokens(documents["dr_number"]),
        "gatepass": _norm(documents["gatepass_number"]),
        "plate": _norm(report["transport_details"]["vehicle_plate_number"]),
        "first": _norm(rows[0]["Description of Goods"]) if rows else "",
    }


def same_in_file(a, b):
    """Two old records that look like one delivery entered twice."""
    if a["activity"] != b["activity"] or a["date"] != b["date"] \
            or a["supplier"] != b["supplier"]:
        return False
    if a["dr"] & b["dr"] or (a["po"] and a["po"] == b["po"] and not b["dr"]):
        return True
    # The same goods under different papers are separate deliveries.
    if (a["dr"] and b["dr"]) or (a["po"] and b["po"] and a["po"] != b["po"]):
        return False
    if a["gatepass"] != b["gatepass"]:
        return False
    return bool(a["first"]) and a["first"] == b["first"] \
        and a["destination"] == b["destination"]


def same_as_existing(old, saved):
    """An old record that may already be a report in the target workbook."""
    if old["activity"] != saved["activity"] or not old["date"] or not saved["date"]:
        return False
    if abs(old["date"] - saved["date"]) > timedelta(days=1):
        return False
    return bool(old["dr"] & saved["dr"]) or bool(old["po"] & saved["po"]) \
        or (old["plate"] and old["plate"] == saved["plate"]) \
        or (old["date"] == saved["date"] and old["supplier"] == saved["supplier"]
            and old["destination"] == saved["destination"])


# ---------- the whole file -----------------------------------

def existing_reports(target):
    """Reports already in the workbook, except earlier runs of this import."""
    if not target or not Path(target).exists():
        return []
    return [report for report in storage.read_all_reports(target)
            if not report["control_no"].startswith(CONTROL_PREFIX + "-")]


def plan_migration(csv_path, target=None, release_lines=()):
    """Decide about every record; nothing is written. release_lines: CSV lines
    of held duplicates that were reviewed and should be imported after all."""
    rows = read_rows(csv_path)
    records, dropped = group_records(rows)
    saved = [(r["control_no"], _facts(r)) for r in existing_reports(target)]
    plan = {"source_rows": len(rows), "records": len(records), "dropped": dropped,
            "import": [], "skipped": [], "duplicates": []}
    accepted, controls = [], {}

    for record in records:
        result = convert_record(record)
        codes = {code for code, _ in result["issues"]}
        facts = _facts(result["report"])
        if "invalid_date" in codes or "value_too_long" in codes \
                or "activity_unknown" in codes:
            result["reason"] = ", ".join(sorted(codes & {
                "invalid_date", "value_too_long", "activity_unknown"}))
            plan["skipped"].append(result)
            continue

        match = next((control for control, other in saved
                      if same_as_existing(facts, other)), None)
        twin = next((item for item, other in accepted
                     if same_in_file(facts, other)), None)
        control = result["report"]["control_no"]
        if record["line"] not in release_lines:
            if "possible_second_page" in codes:
                result["reason"] = "looks like a second page of the record above"
                plan["skipped"].append(result)
                continue
            if match:
                result["reason"] = f"may already exist as {match}"
                plan["duplicates"].append(result)
                continue
            if twin:
                result["reason"] = f"same delivery as CSV line {twin['line']}?"
                plan["duplicates"].append(result)
                continue
            if control.casefold() in controls:
                result["reason"] = ("identical to CSV line "
                                    f"{controls[control.casefold()]}")
                plan["duplicates"].append(result)
                continue
        controls[control.casefold()] = record["line"]
        accepted.append((result, facts))
        plan["import"].append(result)
    return plan


def master_file(plan):
    """The Import Master Data file for the records cleared for import."""
    reports = [item["report"] for item in plan["import"]]
    lists = {key: [] for key in LIST_FIELDS}
    for report in reports:
        for key, field in LIST_FIELDS.items():
            value = report["general_information"][field]
            if value and value not in lists[key]:
                lists[key].append(value)
    return {"format": fsr_import.FORMAT, "version": fsr_import.SUPPORTED_VERSION,
            "device_id": DEVICE_ID, "inspector": "", "reports": reports,
            "master_lists": lists}


def summary_of(plan):
    issue_counts = {}
    for item in plan["import"] + plan["duplicates"] + plan["skipped"]:
        for code in {code for code, _ in item["issues"]}:
            issue_counts[code] = issue_counts.get(code, 0) + 1
    lines = sum(len(item_list["rows"]) for item in plan["import"]
                for item_list in item["report"]["item_lists"])
    return {
        "csv_rows": plan["source_rows"],
        "records": plan["records"],
        "cleared_for_import": len(plan["import"]),
        "cargo_lines_cleared": lines,
        "held_possible_duplicates": len(plan["duplicates"]),
        "skipped_needs_review": len(plan["skipped"]),
        "rows_without_information_dropped": len(plan["dropped"]),
        "records_with_issue": dict(sorted(issue_counts.items())),
    }


def write_outputs(plan, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    storage.write_json_atomic(folder / "legacy_master_data.json", master_file(plan))
    storage.write_json_atomic(folder / "summary.json", summary_of(plan))

    def flat(item, status):
        report = item["report"]
        rows = [r for lst in report["item_lists"] for r in lst["rows"]]
        return {
            "CSV line": item["line"], "Status": status,
            "Reason": item.get("reason", ""),
            "Control #": report["control_no"],
            **report["general_information"],
            "activity": report["inspection_schedule"]["activity"],
            **report["transport_details"], **report["documents_used"],
            "condition": report["cargo_condition"],
            "lines": len(rows),
            "first description": rows[0]["Description of Goods"] if rows else "",
            "total invoice value (no new column)": item["invoice_value"],
            "issues": "; ".join(sorted({code for code, _ in item["issues"]})),
        }

    everything = (
        [flat(i, "cleared for import") for i in plan["import"]]
        + [flat(i, "held: possible duplicate") for i in plan["duplicates"]]
        + [flat(i, "skipped") for i in plan["skipped"]])
    everything.sort(key=lambda row: row["CSV line"])
    with open(folder / "migration_preview.csv", "w", newline="",
              encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(everything[0]))
        writer.writeheader()
        writer.writerows(everything)

    with open(folder / "record_issues.csv", "w", newline="",
              encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["CSV line", "Control #", "Issue", "Detail"])
        for group in (plan["import"], plan["duplicates"], plan["skipped"]):
            for item in group:
                for code, detail in item["issues"]:
                    writer.writerow([item["line"], item["report"]["control_no"],
                                     code, detail])
        for line_no, row in plan["dropped"]:
            writer.writerow([line_no, "", "row_dropped_no_information",
                             " | ".join(v for v in row.values() if v)])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv")
    parser.add_argument("--target", help="workbook to check for duplicates (read only)")
    parser.add_argument("--out", required=True, help="folder for the results")
    parser.add_argument("--release", type=int, nargs="*", default=[],
                        help="CSV lines of reviewed duplicates to import anyway")
    args = parser.parse_args()
    plan = plan_migration(args.csv, args.target, set(args.release))
    write_outputs(plan, args.out)
    print(json.dumps(summary_of(plan), indent=2))


if __name__ == "__main__":
    main()
