"""PO-linked Withdrawal reports - plain data layer (no widgets).

The workflow runs only for Activity = Withdrawal on the Default Item List form,
and only when lines are picked from the PO list. A Withdrawal without a usable
PO stays on the normal form and goes to the main workbook, so Withdrawal
reports exist in two places; a Control # is in exactly one of them.

PO lines come from the saved Receiving reports of the main workbook, so a new
Receiving report can be picked at once. Each line's PO is its own PO Number, or
else its report's. Its Quantity is what was RECEIVED, not what was ordered, so
it is always called Received Quantity here. A line is identified by its Receiving
Ref, which also ties the withdrawal to that batch in the warehouse ledger; the
line number shown is only its order within the PO.

What is left of a line is worked out every time: Received Quantity minus what
every saved Withdrawal took by its Receiving Ref. The Receiving report itself is
never changed, so an edited Withdrawal corrects the figure by itself.

Withdrawal workbook (Withdrawal_Reports.xlsx beside the active workbook):
    Withdrawal Reports  one row per report; Control # is the report ID
    Withdrawal Lines    one row per line; Line ID stays with the line when the
                        report is edited
    Declared Goods      as in the main workbook
    Remarks             as in the main workbook

Two lists beside the workbooks are rebuilt from the saved reports after a save,
so an edited report corrects them by itself:
    PO_Master.xlsx      every Receiving line with something left, its Quantity
                        being what remains. Rows of reports that are not in the
                        main workbook (not imported yet) are kept as they are.
    Withdrawn_Item.xlsx one row per withdrawn line, in the same format, with its
                        Inspection Date as the last column, Date Withdrawn.

Quantities are Decimal here, so the limits are exact.
"""

import os  # noqa: F401 - os.replace, via fsr_storage.replace_file
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils.exceptions import InvalidFileException
except ImportError:
    Workbook = None
    InvalidFileException = ValueError

import fsr_paths
import fsr_storage as storage
from fsr_storage import load_workbook   # reads into memory (no file lock)
from warehouse.transactions import (RECEIVING, WITHDRAWAL, normalize_activity,
                                    normalize_unit)

ENTRY_PO_LINKED = "PO-Linked"

# Text found in the PO Number of older reports that does not name a PO.
PLACEHOLDER_PO = re.compile(
    r"^(n/?a|none|nil|tba|-+|consolidated.*|please see.*|see .*)$", re.I)

# Units measured in fractions; every other unit, known or not, is counted whole.
DECIMAL_UNITS = {"M", "KG"}

LINE_NO_HEADER = "PO Line No"
SOURCE_CONTROL_HEADER = "Source Control #"
RECEIVED_HEADER = "Received Quantity"
LINE_ID_HEADER = "Line ID"
LINE_EXTRA_HEADERS = [LINE_NO_HEADER, SOURCE_CONTROL_HEADER, RECEIVED_HEADER,
                      LINE_ID_HEADER]

HEADER_SHEET = storage.WITHDRAWAL_HEADER_SHEET
LINE_SHEET = "Withdrawal Lines"
GOODS_SHEET = "Declared Goods"
REMARK_SHEET = "Remarks"
HEADER_HEADERS = storage.REPORT_HEADERS + ["Entry Source", "PO Source File"]
# "Quantity" on a line is what is withdrawn; the sheet says so.
LINE_HEADERS = (
    storage.ITEM_SHEET_HEADERS[:3]
    + ["Withdrawal Quantity" if h == "Quantity" else h
       for h in storage.ITEM_LINE_HEADERS]
    + LINE_EXTRA_HEADERS
)
WITHDRAWAL_SHEETS = {
    HEADER_SHEET: ("WithdrawalReportsTable", HEADER_HEADERS),
    LINE_SHEET: ("WithdrawalLinesTable", LINE_HEADERS),
    GOODS_SHEET: ("WithdrawalGoodsTable", storage.GOODS_HEADERS),
    REMARK_SHEET: ("WithdrawalRemarksTable", storage.REMARK_HEADERS),
}


class PoSourceError(ValueError):
    """The Receiving reports cannot be read."""


class PoSourceMissing(PoSourceError):
    """There is no main workbook yet."""


class WithdrawalError(ValueError):
    """A line or report breaks a Withdrawal rule."""


class WithdrawalWorkbookError(ValueError):
    """The file is not a Withdrawal workbook; it is left untouched."""


# ---------- quantities --------------------------------------

def parse_decimal(value):
    """A cell or typed text -> Decimal, or None when it is not a plain number
    ('1e3', 'NaN', '12 pcs' and booleans are not)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        text = str(value)
    else:
        text = str(value).strip()
        if text.startswith("."):
            text = "0" + text
        if not storage.NUMBER_PATTERN.match(text):
            return None
        text = text.replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def format_quantity(number):
    """Decimal('12.50') -> '12.5', Decimal('1E+2') -> '100'."""
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def decimals_allowed(uom):
    return normalize_unit(uom) in DECIMAL_UNITS


def validate_quantity(text, uom, received, remaining=None):
    """The withdrawal quantity as a Decimal, or WithdrawalError saying why.
    `remaining` is what is left of the line, when that is known."""
    number = parse_decimal(text)
    if number is None:
        raise WithdrawalError(f"Withdrawal quantity '{text}' is not a number.")
    if number <= 0:
        raise WithdrawalError("Withdrawal quantity must be greater than 0.")
    if number != number.to_integral_value() and not decimals_allowed(uom):
        raise WithdrawalError(
            f"Withdrawal quantity {format_quantity(number)} must be a whole "
            f"number for UOM '{uom or 'blank'}'. Decimals are allowed only "
            "for M and KG.")
    limit = parse_decimal(received)
    if limit is None:
        raise WithdrawalError("This line has no valid Received Quantity.")
    if number > limit:
        raise WithdrawalError(
            f"Withdrawal quantity {format_quantity(number)} is more than the "
            f"Received Quantity {format_quantity(limit)}.")
    if remaining is not None and number > remaining:
        raise WithdrawalError(
            f"Withdrawal quantity {format_quantity(number)} is more than the "
            f"{format_quantity(remaining)} remaining of the Received Quantity "
            f"{format_quantity(limit)}.")
    return number


# ---------- the PO list --------------------------------------

def is_usable_po(text):
    text = str(text or "").strip()
    return bool(text) and not PLACEHOLDER_PO.match(text)


@dataclass(frozen=True)
class PoLine:
    po_number: str
    line_no: str
    description: str
    received_qty: Decimal
    remaining_qty: Decimal
    uom: str
    control_no: str = ""
    packaging: str = ""
    dimension: str = ""
    weight: str = ""
    unit_price: str = ""
    currency: str = ""
    cargo_id: str = ""
    receiving_ref: str = ""


@dataclass(frozen=True)
class PoLookup:
    """One PO in the Receiving data: the lines that can be picked, the lines left out
    because their Quantity is not readable, and the lines of cells naming
    several POs ("1001 / 1002"), which cannot be tied to any one of them.
    `finished` counts the lines with nothing left to withdraw."""
    lines: list
    unreadable: int = 0
    shared: int = 0
    finished: int = 0


def line_key(po_number, line_no):
    return (str(po_number).strip().casefold(), str(line_no).strip().casefold())


def _main_reports(path):
    """Every report of the main workbook (one read of it)."""
    path = Path(path)
    if not path.exists():
        raise PoSourceMissing(f"There are no saved reports yet in:\n{path}")
    try:
        return storage.read_all_reports(path)
    except PermissionError:
        raise
    except (OSError, zipfile.BadZipFile, InvalidFileException, KeyError,
            ValueError) as error:
        raise PoSourceError(
            f"The Receiving reports could not be read:\n{path}\n{error}"
        ) from error


def _receiving_lines(path, reports=None):
    """(PO cell, Receiving Ref, Control #, row) of every saved Receiving line.
    `reports`: the main workbook's reports when they were read already."""
    if reports is None:
        reports = _main_reports(path)
    lines = []
    for report in reports:
        if normalize_activity(report["inspection_schedule"].get(
                "activity")) != RECEIVING:
            continue
        control = report["control_no"]
        for list_no, section in enumerate(report["item_lists"], start=1):
            for line_no, row in enumerate(section["rows"], start=1):
                po = (str(row.get("PO Number") or "").strip()
                      or report["documents_used"]["po_number"].strip())
                ref = (str(row.get("Receiving Ref") or "").strip()
                       or storage.default_receiving_ref(control, list_no,
                                                        line_no))
                lines.append((po, ref, control, row,
                              report["cargo_condition"]))
    return lines


def _ref_key(ref):
    return str(ref or "").strip().casefold()


def withdrawn_by_ref(path, except_control="", main_reports=None,
                     book_reports=None):
    """{Receiving Ref: quantity taken} over every saved Withdrawal of both
    workbooks, leaving out the report `except_control` (the one being edited).
    `main_reports` / `book_reports`: the two workbooks' reports when they
    were read already."""
    book = Path(path).resolve().with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)
    reports = (read_all_reports(book) if book_reports is None
               else list(book_reports))
    if main_reports is None and Path(path).exists():
        main_reports = storage.read_all_reports(path)
    reports = reports + [
        report for report in main_reports or []
        if normalize_activity(report["inspection_schedule"].get(
            "activity")) == WITHDRAWAL]
    totals = {}
    for report in reports:
        if storage.same_key(report["control_no"], except_control):
            continue
        for section in report["item_lists"]:
            for row in section["rows"]:
                ref = _ref_key(row.get("Receiving Ref"))
                number = split_received(row.get("Quantity"), row.get("UOM"))[0]
                if ref and number is not None:
                    totals[ref] = totals.get(ref, Decimal(0)) + number
    return totals


def remaining_quantity(path, row, except_control="", main_reports=None,
                       book_reports=None):
    """What is left of this report row's Receiving line, not counting the
    report `except_control`. `main_reports` / `book_reports`: the reports
    when they were read already (the SQLite store passes them)."""
    taken = withdrawn_by_ref(path, except_control, main_reports,
                             book_reports).get(
        _ref_key(row.get("Receiving Ref")), Decimal(0))
    return parse_decimal(row[RECEIVED_HEADER]) - taken


def split_received(text, uom=""):
    """('2 pkgs', '') or ('2', 'pkgs') -> (Decimal('2'), 'pkgs');
    (None, '') when not readable."""
    # A plain number has no unit to split off ("12.5" is not 12 and ".5").
    number = parse_decimal(text)
    if number is not None:
        return (number, str(uom or "").strip()) if number > 0 else (None, "")
    quantity, uom = storage.split_quantity_unit(text, uom)
    number = parse_decimal(quantity)
    if number is None or number <= 0 or re.search(r"\d", uom):
        return None, ""
    return number, uom


def split_price(text):
    """'JPY 433,000' -> ('433,000', 'JPY'); other text stays as it is."""
    text = str(text or "").strip()
    match = re.match(r"^([A-Za-z]{3})\s+(.+)$", text)
    if match:
        return match.group(2).rstrip(".-").strip(), match.group(1).upper()
    return text, ""


def _shares_po(cell, wanted):
    parts = [part.strip().casefold() for part in re.split(r"[,/;&\s]+", cell)]
    return len(parts) > 1 and wanted in parts


def find_po(path, po_number, main_reports=None, book_reports=None):
    """Every Receiving line of one PO that still has something left to withdraw,
    from the main workbook `path` (or from `main_reports` / `book_reports`
    when they were read already)."""
    wanted = str(po_number or "").strip().casefold()
    lines, unreadable, shared, finished, line_no = [], 0, 0, 0, 0
    source = _receiving_lines(path, main_reports)
    taken = withdrawn_by_ref(path, main_reports=main_reports,
                             book_reports=book_reports)
    for cell, ref, control, row, _ in source:
        if cell.casefold() != wanted:
            shared += _shares_po(cell, wanted)
            continue
        line_no += 1
        quantity, uom = split_received(row.get("Quantity"), row.get("UOM"))
        if quantity is None:
            unreadable += 1
            continue
        remaining = quantity - taken.get(_ref_key(ref), Decimal(0))
        if remaining <= 0:
            finished += 1
            continue
        price, currency = split_price(row.get("Unit Price"))
        weight = str(row.get("Weights") or "").strip()
        # A ditto mark in the old data is not a weight of this line.
        lines.append(PoLine(
            cell, str(line_no), str(row.get("Description of Goods") or ""),
            quantity, remaining, uom, control, str(row.get("Packaging") or ""),
            str(row.get("Dimensions") or ""),
            "" if weight in ("'", '"') else weight, price,
            str(row.get("Currency") or "") or currency,
            str(row.get("Cargo ID") or ""), ref))
    return PoLookup(lines, unreadable, shared, finished)


# ---------- report rows --------------------------------------

def set_quantity(row, number):
    """Withdraw `number` on this row. The Total Price follows it. The weight
    received is that of the whole received line, so it is kept only while
    the whole line is withdrawn."""
    row["Quantity"] = format_quantity(number)
    price = parse_decimal(row["Unit Price"])
    row["Total Price"] = "" if price is None else f"{price * number:,.2f}"
    if number != parse_decimal(row[RECEIVED_HEADER]):
        row["Weights"] = ""


def new_row(line):
    """A report row made from THAT Receiving line. The withdrawal quantity
    starts at what is left of it."""
    row = {header: "" for header in storage.ITEM_LINE_HEADERS}
    row.update({
        "Description of Goods": line.description,
        "PO Number": line.po_number,
        "Packaging": line.packaging,
        "Dimensions": line.dimension,
        "Weights": line.weight,
        "Unit Price": line.unit_price,
        "Currency": line.currency,
        "UOM": line.uom,
        "Cargo ID": line.cargo_id,
        "Receiving Ref": line.receiving_ref,
        LINE_NO_HEADER: line.line_no,
        SOURCE_CONTROL_HEADER: line.control_no,
        RECEIVED_HEADER: format_quantity(line.received_qty),
        LINE_ID_HEADER: "",
    })
    set_quantity(row, line.remaining_qty)
    return row


def row_key(row):
    return line_key(row["PO Number"],
                    row.get("Receiving Ref") or row.get(LINE_NO_HEADER, ""))


def validate_rows(rows, main_path=None, control_no="", taken=None):
    """Everything that must hold for the lines of a report being saved. A line
    typed by hand has no Received Quantity, so it has no limit to check. All
    the lines are checked against what the OTHER reports already took."""
    if not rows:
        raise WithdrawalError("A PO-linked Withdrawal needs at least one line.")
    if taken is None:
        taken = withdrawn_by_ref(main_path, control_no) if main_path else {}
    seen = set()
    for row in rows:
        if not row.get(LINE_NO_HEADER):
            continue
        label = f"PO {row['PO Number']} line {row[LINE_NO_HEADER]}"
        if row_key(row) in seen:
            raise WithdrawalError(f"{label} is in this report twice.")
        seen.add(row_key(row))
        try:
            validate_quantity(
                row["Quantity"], row["UOM"], row[RECEIVED_HEADER],
                parse_decimal(row[RECEIVED_HEADER]) - taken.get(
                    _ref_key(row.get("Receiving Ref")), Decimal(0)))
        except WithdrawalError as error:
            raise WithdrawalError(f"{label}: {error}") from error


# ---------- the Withdrawal workbook: reading ------------------

def _open(path, **options):
    """The workbook after checking its layout. It is never overwritten when
    the layout is wrong."""
    try:
        wb = load_workbook(path, **options)
    except PermissionError:
        raise
    except (OSError, zipfile.BadZipFile, InvalidFileException, KeyError,
            ValueError) as error:
        raise WithdrawalWorkbookError(
            f"{Path(path).name} is not a readable Withdrawal workbook, so it "
            f"was left as it is:\n{error}") from error
    for name, (_, headers) in WITHDRAWAL_SHEETS.items():
        first_row = () if name not in wb.sheetnames else next(
            wb[name].iter_rows(min_row=1, max_row=1, values_only=True), ())
        if [value for value in first_row if value is not None] != headers:
            raise WithdrawalWorkbookError(
                f'The sheet "{name}" of {Path(path).name} is missing or has a '
                "different layout, so the file was left as it is.\n\nMove or "
                "rename the file to start a new one.")
    return wb


def _reports_from(path, wb):
    grouped = {name: {} for name in (LINE_SHEET, GOODS_SHEET, REMARK_SHEET)}
    for name, by_control in grouped.items():
        for row in wb[name].iter_rows(min_row=2, values_only=True):
            if row and row[0] is not None:
                by_control.setdefault(
                    str(row[0]).strip().casefold(), []).append(row)
    return reports_from_rows(path, storage.report_dicts(wb[HEADER_SHEET]),
                             grouped)


def reports_from_rows(path, header_rows, grouped):
    """The reports of the Withdrawal workbook from its rows: `header_rows`
    ({column: value} per report, in sheet order) and `grouped` ({sheet name:
    {Control # in lower case: [row values, ...]}}). Shared by the workbook
    and the SQLite store."""
    sheet_for = {"Item List": LINE_SHEET, "Declared Goods": GOODS_SHEET,
                 "Remarks": REMARK_SHEET}
    extra_at = len(storage.ITEM_SHEET_HEADERS)
    reports = []
    for values in header_rows:
        if not values.get("Control #"):
            continue
        key = str(values["Control #"]).strip().casefold()
        report = storage.report_from_rows(
            path, values,
            lambda sheet, key=key: grouped[sheet_for[sheet]].get(key, []))
        lines = sorted(grouped[LINE_SHEET].get(key, []),
                       key=lambda row: (int(str(row[1]).split()[-1]), row[2] or 0))
        rows = [row for section in report["item_lists"]
                for row in section["rows"]]
        for row, line in zip(rows, lines):
            extras = dict(zip(LINE_EXTRA_HEADERS, line[extra_at:]))
            for header in (LINE_NO_HEADER, SOURCE_CONTROL_HEADER,
                           LINE_ID_HEADER):
                row[header] = storage.cell_text(extras.get(header))
            row[RECEIVED_HEADER] = _quantity_text(extras.get(RECEIVED_HEADER))
            # A line typed by hand may hold text; it stays as it was read.
            row["Quantity"] = _quantity_text(line[LINE_HEADERS.index(
                "Withdrawal Quantity")]) or row["Quantity"]
        report["entry_source"] = storage.cell_text(values.get("Entry Source"))
        report["po_source_file"] = storage.cell_text(
            values.get("PO Source File"))
        reports.append(report)
    return reports


def _quantity_text(value):
    number = parse_decimal(value)
    return "" if number is None else format_quantity(number)


def read_all_reports(path):
    """Every saved report, in the shape of fsr_storage.read_report() plus the
    extra line fields. [] when the workbook does not exist yet."""
    if not Path(path).exists():
        return []
    return _reports_from(path, _open(path, data_only=True))


def read_report(path, control_no):
    for report in read_all_reports(path):
        if storage.same_key(report["control_no"], control_no):
            return report
    raise ValueError(
        f"Control # {control_no} was not found in {Path(path).name}.")


def list_reports(path):
    """Same shape as fsr_storage.list_saved_reports()."""
    if not Path(path).exists():
        return []
    reports = []
    for values in storage.report_dicts(
            _open(path, data_only=True)[HEADER_SHEET]):
        if values.get("Control #"):
            reports.append((
                storage.cell_text(values.get("Control #")),
                storage.cell_text(values.get("SO Number")),
                storage.cell_text(values.get("Inspection Date")),
                storage.cell_text(values.get("Consignee")),
                storage.cell_text(values.get("Last Saved"), with_time=True),
            ))
    return reports


def search_index(path, reports=None):
    """Same shape as fsr_storage.search_index_excel(). `reports`: the
    reports when they were read already."""
    index = {}
    for report in (read_all_reports(path) if reports is None else reports):
        documents = report["documents_used"]
        rows = [row for section in report["item_lists"]
                for row in section["rows"]]
        parts = {
            "so": [report["general_information"]["so_number"]],
            "bl": [documents["bl_awb_number"]],
            "po": [documents["po_number"]] + [r["PO Number"] for r in rows],
            "dr": [documents["dr_number"]],
            "gatepass": [documents["gatepass_number"]],
            "description": (
                [r["Description of Goods"] for r in rows]
                + [g["description"] for g in report["declared_goods"]]),
        }
        index[report["control_no"]] = {
            key: [value for value in values if value]
            for key, values in parts.items()}
    return index


# ---------- the Withdrawal workbook: writing ------------------

def _line_values(control_no, list_name, line_no, row):
    values = [control_no, list_name, line_no]
    for header in storage.ITEM_LINE_HEADERS:
        if header == "Quantity":
            number = parse_decimal(row["Quantity"])
            values.append(storage.text_or_none(row["Quantity"])
                          if number is None else number)
        elif header in storage.NUMERIC_ITEM_HEADERS:
            values.append(storage.to_number(row.get(header, "")))
        else:
            values.append(storage.text_or_none(row.get(header, "")))
    values += [
        storage.text_or_none(row.get(LINE_NO_HEADER, "")),
        storage.text_or_none(row.get(SOURCE_CONTROL_HEADER, "")),
        parse_decimal(row.get(RECEIVED_HEADER)),
        row[LINE_ID_HEADER],
    ]
    return values


def _line_rows(ws, control_no):
    """{Line ID: sheet row} of one report."""
    id_column = LINE_HEADERS.index(LINE_ID_HEADER)
    return {
        str(row[id_column]): row_no
        for row_no, row in enumerate(
            ws.iter_rows(min_row=2, values_only=True), start=2)
        if storage.same_key(row[0], control_no)
    }


def plan_lines(existing_ids, control_no, item_lists):
    """What a save does to the lines of one report, given the Line IDs it
    has now: (Line IDs to delete, [(Line ID, row values, is it an existing
    line)] in order). A new line gets the next free Line ID, written back
    into its row, so the form keeps it. Shared by the workbook and the
    SQLite store."""
    prefix = f"{control_no}-L"
    number = 1 + max(
        (int(line_id[len(prefix):]) for line_id in existing_ids
         if line_id.startswith(prefix) and line_id[len(prefix):].isdigit()),
        default=0)
    keep = {row.get(LINE_ID_HEADER) for section in item_lists
            for row in section["rows"]}
    delete = [line_id for line_id in existing_ids if line_id not in keep]
    remaining = set(existing_ids) - set(delete)
    lines = []
    for section in item_lists:
        for line_no, row in enumerate(section["rows"], start=1):
            if row.get(LINE_ID_HEADER) in remaining:
                lines.append((row[LINE_ID_HEADER], _line_values(
                    control_no, section["name"], line_no, row), True))
            else:
                row[LINE_ID_HEADER] = f"{control_no}-L{number:04d}"
                number += 1
                lines.append((row[LINE_ID_HEADER], _line_values(
                    control_no, section["name"], line_no, row), False))
    return delete, lines


def _write_lines(ws, control_no, item_lists):
    """Changed lines are updated in place, removed lines deleted, new lines
    added. Each row gets its Line ID back, so the form keeps it."""
    existing = _line_rows(ws, control_no)
    delete, lines = plan_lines(list(existing), control_no, item_lists)
    for line_id, row_no in sorted(existing.items(), key=lambda kv: -kv[1]):
        if line_id in delete:
            ws.delete_rows(row_no)

    locations = _line_rows(ws, control_no)
    for line_id, values, kept in lines:
        if kept:
            storage.set_row(ws, locations[line_id], values)
        else:
            storage.append_row(ws, values)


def header_values(data, control_no, saved_at=None):
    """The Withdrawal Reports row of one report (marks it PO-linked)."""
    data["entry_source"] = ENTRY_PO_LINKED
    return storage.report_row_values(data, control_no, saved_at) + [
        ENTRY_PO_LINKED, storage.text_or_none(data.get("po_source_file", ""))]


def goods_and_remarks(data, control_no):
    """The Declared Goods and Remarks rows of one Withdrawal report."""
    goods = [[control_no, storage.text_or_none(row["description"]),
              storage.to_number(row["quantity"]),
              storage.text_or_none(row["packaging"])]
             for row in data["declared_goods"]]
    sections = [("Other Important Remarks", data["other_important_remarks"]),
                ("Findings and Remarks", data["findings_and_remarks"])]
    remarks = [[control_no, section_name, line_no, remark]
               for section_name, lines in sections
               for line_no, remark in enumerate(lines, start=1)]
    return goods, remarks


def write_withdrawal_report(path, data, editing, main_path,
                            saved_at=None):
    """Save one PO-linked report here and nowhere else. Same result as
    fsr_storage.write_report_to_excel(). A new report takes the next free number
    when its Control # is used in either workbook."""
    path = Path(path)
    rows = [row for section in data["item_lists"] for row in section["rows"]]

    if path.exists():
        wb = _open(path)
    else:
        wb = Workbook()
        wb.remove(wb.active)
        for name, (_, headers) in WITHDRAWAL_SHEETS.items():
            wb.create_sheet(name).append(headers)

    header_ws = wb[HEADER_SHEET]
    control_no = data["control_no"]
    existing_row = storage.find_row(header_ws, control_no)
    main_numbers = [entry[0] for entry in storage.list_saved_reports(main_path)]
    in_main = any(storage.same_key(n, control_no) for n in main_numbers)

    if editing and in_main and not existing_row:
        raise WithdrawalError(
            f"Control # {control_no} belongs to the main workbook and cannot "
            "be saved into the Withdrawal workbook.")
    validate_rows(rows, main_path, control_no if editing else "")
    if (existing_row or in_main) and not editing:
        control_no = storage.next_control_number([
            *main_numbers,
            *(row[0] for row in header_ws.iter_rows(
                min_row=2, max_col=1, values_only=True)),
        ])
        existing_row = None

    values = header_values(data, control_no, saved_at)
    if existing_row:
        storage.set_row(header_ws, existing_row, values, storage.REPORT_FORMATS)
    else:
        storage.append_row(header_ws, values, storage.REPORT_FORMATS)

    _write_lines(wb[LINE_SHEET], control_no, data["item_lists"])

    for name in (GOODS_SHEET, REMARK_SHEET):
        storage.remove_key_rows(wb[name], control_no)
    goods, remarks = goods_and_remarks(data, control_no)
    for values in goods:
        storage.append_row(wb[GOODS_SHEET], values)
    for values in remarks:
        storage.append_row(wb[REMARK_SHEET], values)
    remark_rows = len(remarks)

    for name, (table_name, headers) in WITHDRAWAL_SHEETS.items():
        storage.finalize_sheet(wb[name], table_name, headers)

    temp_path = path.with_name(path.stem + ".saving.tmp")
    try:
        wb.save(temp_path)
        storage.replace_file(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    return {
        "control": control_no,
        "updated": existing_row is not None,
        "goods": len(data["declared_goods"]),
        "items": len(rows),
        "remarks": remark_rows,
    }


# ---------- PO_Master.xlsx and Withdrawn_Item.xlsx ------------

LIST_SHEET = "PO Lines"
WITHDRAWN_SHEET = "Withdrawn Items"
LIST_COLUMNS = [("Control #", 16), ("Description", 40), ("PO", 16),
                ("Packaging", 16), ("Quantity", 15), ("Dimension", 19),
                ("Weight", 15), ("Unit Price", 16), ("Total Price", 16),
                ("Findings", 20)]
DATE_WITHDRAWN = "Date Withdrawn"
TEXT_COLUMNS = {"Control #", "PO"}


def _with_currency(currency, value):
    value = str(value or "").strip()
    return f"{currency} {value}" if currency and value and not re.search(
        r"[A-Za-z]", value) else value


def _list_row(control, po, row, quantity, total, findings):
    return [control, row.get("Description of Goods"), po, row.get("Packaging"),
            quantity, row.get("Dimensions"), row.get("Weights"),
            _with_currency(row.get("Currency"), row.get("Unit Price")),
            _with_currency(row.get("Currency"), total), findings]


def _write_list(path, title, columns, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    line = Side(style="thin", color="000000")
    box = Border(left=line, right=line, top=line, bottom=line)
    wrap = Alignment(wrap_text=True, vertical="top")
    for index, (heading, width) in enumerate(columns, start=1):
        cell = ws.cell(1, index, heading)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2E75B6")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = box
        ws.column_dimensions[cell.column_letter].width = width
    for row_no, values in enumerate(rows, start=2):
        for index, value in enumerate(values, start=1):
            cell = ws.cell(row_no, index, None if value == "" else value)
            cell.border = box
            cell.alignment = wrap
            heading = columns[index - 1][0]
            if heading in TEXT_COLUMNS:
                cell.number_format = "@"
            elif heading == DATE_WITHDRAWN and isinstance(value, datetime):
                cell.number_format = "dd-mmm-yyyy"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{ws.cell(1, len(columns)).column_letter}" \
                         f"{max(len(rows) + 1, 2)}"
    temp_path = path.with_name(path.stem + ".saving.tmp")
    try:
        wb.save(temp_path)
        storage.replace_file(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _kept_list_rows(path, saved_controls):
    """Rows of the PO_Master file whose report is not in the main workbook."""
    if not path.exists():
        return []
    wb = load_workbook(path, data_only=True)
    ws = wb[LIST_SHEET] if LIST_SHEET in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    headers = list(next(rows, ()))[:len(LIST_COLUMNS)]
    if headers != [heading for heading, _ in LIST_COLUMNS]:
        raise WithdrawalWorkbookError(
            f"{path.name} has a different layout, so it was left as it is.")
    return [list(row[:len(LIST_COLUMNS)]) for row in rows
            if any(value is not None for value in row)
            and storage.cell_text(row[0]).casefold() not in saved_controls]


def sync_item_lists(main_path, main_reports=None, book_reports=None):
    """Rebuild PO_Master.xlsx and Withdrawn_Item.xlsx beside `main_path`.
    Each workbook is read once (it used to be read four times); the SQLite
    store passes the reports instead."""
    main_path = Path(main_path).resolve()
    po_path = main_path.with_name(fsr_paths.PO_MASTER_NAME)
    withdrawn_path = main_path.with_name(fsr_paths.WITHDRAWN_ITEM_NAME)
    book = main_path.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)

    if main_reports is None:
        main_reports = _main_reports(main_path) if main_path.exists() else []
    if book_reports is None:
        book_reports = read_all_reports(book)
    lines = _receiving_lines(main_path, main_reports)
    saved_controls = {
        storage.cell_text(report["control_no"]).casefold()
        for report in main_reports}
    rows = _kept_list_rows(po_path, saved_controls)
    taken = withdrawn_by_ref(main_path, main_reports=main_reports,
                             book_reports=book_reports)
    for po, ref, control, row, condition in lines:
        findings = str(row.get("Findings") or "").strip() or condition
        received, uom = split_received(row.get("Quantity"), row.get("UOM"))
        if received is None:            # not readable: listed as recorded
            quantity = " ".join(filter(None, (str(row.get("Quantity") or ""),
                                              str(row.get("UOM") or ""))))
            rows.append(_list_row(control, po, row, quantity,
                                  row.get("Total Price"), findings))
            continue
        remaining = received - taken.get(_ref_key(ref), Decimal(0))
        if remaining <= 0:
            continue
        price = parse_decimal(split_price(row.get("Unit Price"))[0])
        total = (row.get("Total Price") if price is None or remaining == received
                 else f"{price * remaining:,.2f}")
        rows.append(_list_row(
            control, po, row,
            " ".join(filter(None, (format_quantity(remaining), uom))),
            total, findings))
    _write_list(po_path, LIST_SHEET, LIST_COLUMNS, rows)

    withdrawn = []
    reports = list(book_reports) + [
        report for report in main_reports
        if normalize_activity(report["inspection_schedule"].get(
            "activity")) == WITHDRAWAL and any(
                row.get("Receiving Ref") for section in report["item_lists"]
                for row in section["rows"])]
    for report in reports:
        day = storage.parse_date(report["general_information"]["inspection_date"])
        for section in report["item_lists"]:
            for row in section["rows"]:
                quantity = " ".join(filter(None, (
                    str(row.get("Quantity") or ""), str(row.get("UOM") or ""))))
                withdrawn.append(_list_row(
                    report["control_no"],
                    row.get("PO Number")
                    or report["documents_used"]["po_number"], row, quantity,
                    row.get("Total Price"),
                    str(row.get("Findings") or "").strip()
                    or report["cargo_condition"]) + [day])
    _write_list(withdrawn_path, WITHDRAWN_SHEET,
                LIST_COLUMNS + [(DATE_WITHDRAWN, 16)], withdrawn)


def owns_report(path, control_no):
    """True when this Control # belongs to the Withdrawal workbook beside the
    main workbook `path`."""
    return any(storage.same_key(number, control_no)
               for number in storage.withdrawal_control_numbers(path))
