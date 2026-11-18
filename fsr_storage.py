"""
Field Survey Report - plain data layer (no widgets).

Field definitions, format helpers, the incident report JSON files and the
Excel storage (Reports / Declared Goods / Item List / Remarks sheets).
This code used to live inside field_survey_report.py; it was moved here
unchanged so the warehouse analytics, the sample-data generator and the
automated tests can use the real storage code without opening a window.
field_survey_report.py imports everything from this module.
"""

import copy
import fsr_drafts
import io
import json
import logging
import math
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import fsr_paths

try:
    from openpyxl import Workbook
    from openpyxl import load_workbook as _openpyxl_load_workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo
except ImportError:
    Workbook = None

log = logging.getLogger("fsr")

CONTROL_PREFIX = "FSR"
NO_INITIALS = "XX"               # as the Android app, when no inspector is known
_control_initials = {"value": NO_INITIALS}


def load_workbook(filename, *args, **kwargs):
    """openpyxl's load_workbook - but a file is first read into memory and
    closed again at once. Reading a large workbook takes seconds; for all
    that time Windows would not let anyone replace the file, so a save made
    while the dashboards (or anything else) were reading it failed with
    "File In Use". Now the file is open only for the moment of copying."""
    if isinstance(filename, (str, os.PathLike)):
        buffer = io.BytesIO(_read_bytes(filename))
        buffer.name = str(filename)     # what openpyxl reports as the file
        filename = buffer
    return _openpyxl_load_workbook(filename, *args, **kwargs)


def _read_bytes(path):
    """The file's bytes. Opening it at the very moment a save replaces it
    fails on Windows ("Permission denied"); it is tried again for about
    two seconds, as replace_file() does for the write."""
    for attempt in range(REPLACE_TRIES):
        try:
            with open(path, "rb") as file:
                return file.read()
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_PAUSE)


REPLACE_TRIES = 10                      # x 0.2 s: about 2 seconds
REPLACE_PAUSE = 0.2


def replace_file(temp_path, path):
    """os.replace(temp_path, path), tried again for about two seconds when
    Windows says the file is in use: a reader that has it open for a moment
    (this program, a virus scanner) must not make a save fail. A file that
    stays open (Excel) still fails, with PermissionError, as before."""
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_PAUSE)


def write_json_atomic(path, data):
    """Write JSON to a temp file first, so a crash can never corrupt `path`.
    The file is replaced with replace_file(): the window and the background
    sender read and write the save record and the ledger at the same time,
    and Windows does not replace a file that is being read."""
    path = Path(path)
    temp_path = path.with_name(path.stem + ".saving.tmp")

    try:
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        replace_file(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def safe_filename(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("_") or "report"


# =====================================================
# FIELD DEFINITIONS + FORMAT HELPERS
# =====================================================

DATE_FORMAT = "%d-%b-%Y"          # 25-Oct-2026  (dd-MMM-yyyy) everywhere
LEGACY_DATE_FORMAT = "%d-%m-%Y"   # only to read older files
TIME_PATTERN = re.compile(r"^(?:[01]\d[0-5]\d|2[0-3][0-5]\d|2400)H$")

# (label, key, entry width, kind, Excel column name)
SCHEDULE_FIELDS = [
    ("Activity", "activity", 35, "choice", "Activity"),
    ("Commenced Date\n(dd-MMM-yyyy)", "commenced_date", 16, "date",
     "Commenced Date"),
    ("Commenced Time\n(e.g. 2400H)", "commenced_time", 12, "time",
     "Commenced Time"),
    ("Completion Date\n(dd-MMM-yyyy)", "completion_date", 16, "date",
     "Completion Date"),
    ("Completion Time\n(e.g. 1800H)", "completion_time", 12, "time",
     "Completion Time"),
]

TRANSPORT_FIELDS = [
    ("Shipment Type", "shipment_type", 25, "choice", "Local / Import"),
    ("Container Type", "container_type", 25, "choice", "Container Type"),
    ("Vessel/Carrier", "vessel_carrier", 35, "text", "Vessel/Carrier"),
    ("Vehicle Type", "vehicle_type", 25, "text", "Vehicle Type"),
    ("Vehicle Plate Number", "vehicle_plate_number", 22, "text",
     "Vehicle Plate Number"),
]


# Fixed drop-down lists for the "choice" fields (key -> values).
CHOICE_VALUES = {
    "activity": ["Receiving", "Withdrawal"],
    "shipment_type": ["Local", "Import"],
    "container_type": ["Containerized", "Non-Containerized"],
}
# Drop-downs the user may also TYPE into (the others only allow the list).
TYPEABLE_CHOICES = {"activity"}


def recent_date_options(days=7):
    """Today first, then each of the previous `days` days (dd-MMM-yyyy)."""
    today = date.today()
    return [
        (today - timedelta(days=n)).strftime(DATE_FORMAT)
        for n in range(days + 1)
    ]


def normalize_field(text, kind):
    """
    Tidy up a date / time typed by the user.
      date: '5-oct-2026' -> '05-Oct-2026'
      time: '1800', '18:00' or '1800h' -> '1800H'
    Returns '' for empty text and None when the format is invalid.
    """
    text = text.strip()
    if not text:
        return ""

    if kind == "date":
        try:
            return datetime.strptime(text, DATE_FORMAT).strftime(DATE_FORMAT)
        except ValueError:
            return None

    if kind == "time":
        text = text.upper().replace(":", "")
        digits = text[:-1] if text.endswith("H") else text
        if digits.isdigit() and len(digits) == 3:
            digits = digits.zfill(4)
        candidate = digits + "H"
        return candidate if TIME_PATTERN.match(candidate) else None

    return text


# ---------- cargo condition, types of goods, incident reports ----------
# (plain data helpers - no widgets)

CONDITION_GOOD = "Good Order"
CONDITION_BAD = "Bad Order"

# (text shown on screen / saved in Excel, key) - same order as the form.
GOODS_TYPES = [
    ("New", "new"),
    ("Used", "used"),
    ("Food Stuff", "food_stuffs"),
    ("Vehicle", "vehicle"),
    ("Pharma / Chemical", "pharma_chemicals"),
]


def empty_goods_types():
    types = {key: False for _, key in GOODS_TYPES}
    types.update({"others": False, "others_text": ""})
    return types


def goods_types_to_text(types):
    """{'new': True, 'others': True, 'others_text': 'Tools'} ->
    'New; Others: Tools'  (one short cell in the Reports sheet).
    'Others' is always last, so the text can be read back."""
    types = types or {}
    parts = [label for label, key in GOODS_TYPES if types.get(key)]
    if types.get("others"):
        other_text = str(types.get("others_text") or "").strip()
        parts.append(f"Others: {other_text}" if other_text else "Others")
    return "; ".join(parts)


def goods_types_from_text(text):
    """Reverse of goods_types_to_text()."""
    types = empty_goods_types()
    text = str(text or "").strip()
    if not text:
        return types

    match = re.search(r"(?:^|;\s*)Others(?::\s*(.*))?$", text, re.S)
    if match:
        types["others"] = True
        types["others_text"] = (match.group(1) or "").strip()
        text = text[:match.start()]

    wanted = {part.strip().casefold() for part in text.split(";")}
    for label, key in GOODS_TYPES:
        if label.casefold() in wanted:
            types[key] = True
    return types


# Incident reports are NOT stored in the Excel file (to keep it small).
# Each report with incidents gets one small JSON file, named after its
# Control #, in the managed JSON tree or beside an external workbook.
INCIDENT_FOLDER_NAME = "Incident Reports"
INCIDENT_MAX_LINES = 15           # lines on one Incident Report form
INCIDENT_HEADER_FIELDS = [        # (label, key) in display order
    ("Vessel", "vessel"),
    ("Voyage", "voyage"),
    ("Client", "client"),
    ("S.O. No.", "so_number"),
    ("Port", "port"),
    ("Date", "date"),
    ("Operation", "operation"),
]


def incident_title(number):
    """Card / sheet name: 1 -> 'Incident Report', 2 -> 'Additional Incident Report 1'."""
    return "Incident Report" if number <= 1 else (
        f"Additional Incident Report {number - 1}"
    )


def incident_json_path(excel_path, control_no):
    return (fsr_paths.json_dir_for_workbook(excel_path) / INCIDENT_FOLDER_NAME
            / f"{safe_filename(control_no)}.json")


def clean_incident_reports(reports):
    """Tidy the incident cards: trimmed text, blank lines dropped,
    at most 15 lines per card."""
    cleaned = []
    for report in reports or []:
        item = {
            key: str(report.get(key) or "").strip()
            for _, key in INCIDENT_HEADER_FIELDS
        }
        item["lines"] = [
            str(line).strip() for line in report.get("lines") or []
            if str(line).strip()
        ][:INCIDENT_MAX_LINES]
        cleaned.append(item)
    return cleaned


def save_incident_data(excel_path, control_no, so_number, reports):
    """Write the incident reports of one report to its JSON file.
    Nothing to store (no lines typed) -> any old file is removed.
    Returns the file path, or None when no file was written."""
    reports = clean_incident_reports(reports)
    path = incident_json_path(excel_path, control_no)

    if not any(report["lines"] for report in reports):
        delete_incident_data(excel_path, control_no)
        return None

    for number, report in enumerate(reports, start=1):
        report["title"] = incident_title(number)

    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {
        "control_no": control_no,
        "so_number": so_number,
        "saved": datetime.now().isoformat(timespec="seconds"),
        "incident_reports": reports,
    })
    return path


def load_incident_data(excel_path, control_no):
    """Incident cards of a saved report ([] when it has none).
    Raises ValueError when the JSON file exists but cannot be read."""
    path = incident_json_path(excel_path, control_no)
    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        reports = data["incident_reports"]
        if not isinstance(reports, list):
            raise TypeError("incident_reports is not a list")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path.name}: {error}") from error

    return clean_incident_reports(
        [r for r in reports if isinstance(r, dict)]
    )


def delete_incident_data(excel_path, control_no):
    try:
        incident_json_path(excel_path, control_no).unlink()
    except FileNotFoundError:
        pass


# (label text, JSON key) in display order.
DOCUMENT_FIELDS = [
    ("Invoice Number", "invoice_number"),
    ("PO Number", "po_number"),
    ("JO Number", "jo_number"),
    ("Gatepass Number", "gatepass_number"),
    ("BL/AWB Number", "bl_awb_number"),
    ("DR Number", "dr_number"),
    ("Other Documents", "other_documents"),
]

ITEM_HEADERS = [
    "Description of Goods",
    "PO Number",
    "Packaging",
    "Quantity",
    "Dimensions",
    "Weights",
    "Unit Price",
    "Total Price",
    "Findings"
]

# Warehouse links of an item line (saved in the Item List sheet and MySQL,
# NOT printed on the Cargo Details form):
#   Cargo ID      - the inventory item (the same ID on every Receiving and
#                   Withdrawal of that cargo; two items may share a
#                   description but never a Cargo ID)
#   Receiving Ref - one received batch. Receiving lines get one
#                   automatically; a Withdrawal line may name the batch.
ITEM_LINK_HEADERS = ["Cargo ID", "Receiving Ref"]
# Added later (older files and databases get the columns on the next save):
#   UOM      - unit of measure; the Quantity column holds the number only
#   Currency - of the Unit Price and Total Price
#   Container / Truck No. - the Container No. (Containerized form) or the
#              Truck Plate No. (Loading form) of the line
UNIT_NO_HEADER = "Container / Truck No."
ITEM_EXTRA_HEADERS = ["UOM", "Currency", UNIT_NO_HEADER]
ITEM_LINE_HEADERS = ITEM_HEADERS + ITEM_LINK_HEADERS + ITEM_EXTRA_HEADERS
# A line received from a Withdrawal's shipment file (fsr_shipment): its
# Packing List No. and the origin line it came from. Hidden like the links
# (saved, never printed in the Item List columns). They are the LAST columns
# of the main workbook's Item List sheet; the Withdrawal workbook does not
# have them (its own columns follow ITEM_LINE_HEADERS by position). A line
# carries them only when they have a value, so every report without them
# reads, exports and compares exactly as before they existed.
SHIPMENT_HEADERS = ["Packing List No.", "Origin Line"]
ITEM_ROW_HEADERS = ITEM_LINE_HEADERS + SHIPMENT_HEADERS


def without_empty_shipment_fields(report):
    """A copy of `report` whose lines carry the shipment fields only when
    they have a value (for fingerprints and comparisons)."""
    result = copy.deepcopy(report)

    def tidy(item_lists):
        for item_list in item_lists or []:
            for row in item_list.get("rows") or []:
                for header in SHIPMENT_HEADERS:
                    if header in row and not str(row[header] or "").strip():
                        del row[header]

    if isinstance(result, dict):
        tidy(result.get("item_lists"))
        for lists in (result.get("other_item_forms") or {}).values():
            tidy(lists)
    return result

# The Item List form of a report (one for all its Item Lists):
#   Default       - the original columns (PO Number, prices ...)
#   Containerized - Container No. first, no PO Number / prices
#   Loading       - Truck Plate No. first, no PO Number / prices
ITEM_FORM_DEFAULT = "Default"
ITEM_FORM_CONTAINERIZED = "Containerized"
ITEM_FORM_LOADING = "Loading"
ITEM_FORMS = [ITEM_FORM_DEFAULT, ITEM_FORM_CONTAINERIZED, ITEM_FORM_LOADING]
# Heading of the Container / Truck No. column on each form.
UNIT_NO_LABELS = {ITEM_FORM_CONTAINERIZED: "Container No.",
                  ITEM_FORM_LOADING: "Truck Plate No."}


def item_form_name(value):
    """A saved form name -> one of ITEM_FORMS (older reports: Default)."""
    text = str(value or "").strip().casefold()
    return next((form for form in ITEM_FORMS if form.casefold() == text),
                ITEM_FORM_DEFAULT)


# The Excel file and MySQL hold the lines of the selected form only (they
# count as stock). Lines typed on the other forms are kept in a JSON file,
# so they still print and come back when the report is opened.
ITEM_FORM_FOLDER_NAME = "Item Forms"


def other_item_forms_path(excel_path, control_no):
    return (fsr_paths.json_dir_for_workbook(excel_path) / ITEM_FORM_FOLDER_NAME
            / f"{safe_filename(control_no)}.json")


def save_other_item_forms(excel_path, control_no, forms):
    """Write {form: item lists} for one report. Nothing to store -> any old
    file is removed."""
    path = other_item_forms_path(excel_path, control_no)
    if not forms:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {
        "control_no": control_no,
        "saved": datetime.now().isoformat(timespec="seconds"),
        "item_forms": forms,
    })


def load_other_item_forms(excel_path, control_no):
    """{form: item lists} of a saved report ({} when it has none).
    Raises ValueError when the JSON file exists but cannot be read."""
    path = other_item_forms_path(excel_path, control_no)
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as file:
            forms = json.load(file)["item_forms"]
        return {
            form: [{"name": item_list["name"], "rows": list(item_list["rows"])}
                   for item_list in forms[form]]
            for form in ITEM_FORMS if form in forms
        }
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path.name}: {error}") from error


CURRENCIES =["JPY", "USD", "PHP", "SEK", "EUR"]
UOM_CHOICES = ["PCS", "SET", "UNIT", "BOX", "CASE", "CRATE", "PALLET",
               "PKG", "BUNDLE", "ROLL", "DRUM", "LOT", "LENGTH", "M", "KG"]
# Units offered next to Weights; the Weights column keeps "1,250 KG".
WEIGHT_UNIT_CHOICES = ["KG", "G", "L", "ML", "MT", "LBS"]
QUANTITY_UNIT_PATTERN = re.compile(
    r"^\s*(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*([^\d\s,.\-].*?)\s*$")


def split_quantity_unit(quantity, uom=""):
    """('12 pcs', '') -> ('12', 'pcs'). A Quantity saved before the UOM
    column existed may carry its unit; a UOM that is already filled in is
    kept as it is."""
    quantity, uom = str(quantity or "").strip(), str(uom or "").strip()
    match = QUANTITY_UNIT_PATTERN.match(quantity)
    if uom or not match:
        return quantity, uom
    return match.group(1), match.group(2)


def default_receiving_ref(control_no, list_no, line_no):
    """RCV-FSR-JDC-202610-0001-1-03 for line 3 of Item List 1 of FSR-JDC-202610-0001."""
    return f"RCV-{control_no}-{list_no}-{int(line_no):02d}"


# =====================================================
# EXCEL STORAGE (Control # based)
# =====================================================
# All reports are kept in ONE workbook with four Excel Tables.
# Every table starts with the "Control #" column, which links them:
#   Reports        - one row per report (general info + documents)
#   Declared Goods - one row per declared item
#   Item List      - one row per line of every Item List
#   Remarks        - one row per remark / finding
#
# Control # is generated automatically (FSR-JDC-202610-0001, 0002, ...).
# Saving a report whose Control # is already in the file UPDATES it.

REPORT_HEADERS = (
    ["Control #", "SO Number", "Inspection Date", "Consignee", "Supplier",
     "Brokerage", "Hauler", "Location", "Destination", "Country of Origin"]
    + [field[4] for field in SCHEDULE_FIELDS]
    + [field[4] for field in TRANSPORT_FIELDS]
    + [label for label, _ in DOCUMENT_FIELDS]
    + ["Cargo Condition", "Types of Goods", "Item List Form", "Last Saved"]
)

# Number formats for the date columns of the Reports sheet.
REPORT_FORMATS = {
    REPORT_HEADERS.index("Inspection Date") + 1: "dd-mmm-yyyy",
    REPORT_HEADERS.index("Commenced Date") + 1: "dd-mmm-yyyy",
    REPORT_HEADERS.index("Completion Date") + 1: "dd-mmm-yyyy",
    REPORT_HEADERS.index("Last Saved") + 1: "dd-mm-yyyy hh:mm",
}
# Headings that were renamed; older Excel files are updated on the next save.
# Only where the new name belongs: "UOM" is a column of its own now too.
LEGACY_HEADERS = {"UOM": "Packaging"}


def legacy_header(value, expected):
    """The current name of an older heading at the place of `expected`."""
    renamed = LEGACY_HEADERS.get(value)
    return renamed if renamed == expected else value

GOODS_HEADERS = ["Control #", "Description", "Quantity", "Packaging"]
ITEM_SHEET_HEADERS = (["Control #", "Item List", "Line No"] + ITEM_LINE_HEADERS
                      + SHIPMENT_HEADERS)
# where the shipment fields start on an Item List row (after the line fields)
SHIPMENT_AT = 3 + len(ITEM_LINE_HEADERS)
REMARK_HEADERS = ["Control #", "Section", "Line No", "Remark"]

# The quantity columns, kept as typed (0-based columns of the sheet).
TYPED_COLUMNS = {
    "Item List": (ITEM_SHEET_HEADERS.index("Quantity"),),
    "Declared Goods": (GOODS_HEADERS.index("Quantity"),),
}

# sheet name -> (table name, headers)
EXCEL_SHEETS = {
    "Reports": ("ReportsTable", REPORT_HEADERS),
    "Declared Goods": ("DeclaredGoodsTable", GOODS_HEADERS),
    "Item List": ("ItemListTable", ITEM_SHEET_HEADERS),
    "Remarks": ("RemarksTable", REMARK_HEADERS),
}

# Item List columns stored as real numbers so Excel can sum them.
NUMERIC_ITEM_HEADERS = {"Quantity", "Unit Price", "Total Price"}
MONEY_ITEM_HEADERS = {"Unit Price", "Total Price"}

NUMBER_PATTERN = re.compile(
    r"^-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$"
)


# ---------- small helpers ----------------------------------

def text_or_none(text):
    """Empty text becomes an empty cell."""
    text = (text or "").strip()
    return text if text else None


def to_number(text):
    """'1,250.50' -> 1250.5, '12' -> 12. Anything else ('1e3', '1,5',
    '12 pcs') stays as text."""
    text = (text or "").strip()
    if not text:
        return None

    if not NUMBER_PATTERN.match(text):
        return text

    cleaned = text.replace(",", "")
    value = float(cleaned)

    if not math.isfinite(value):
        return text

    if "." not in cleaned:
        return int(cleaned)
    return value


# ---------- quantities shown as they were typed ----------------
#
# A quantity is stored as a number (Excel can add it up), and the program
# shows it the way it was typed: "1,250.50", not "1250.5". The number keeps
# its typed form (TypedInt / TypedFloat); in the workbook its cell gets a
# display format that shows it the same way (for "1,250.50": 0,000.00), and
# reading the cell back gives the typed form again.

class TypedFloat(float):
    """A number typed with a look of its own. Calculations use the number;
    `typed` is what was typed."""

    typed = ""

    def __new__(cls, value, typed):
        number = super().__new__(cls, value)
        number.typed = typed
        return number

    def __reduce__(self):
        return type(self), (float(self), self.typed)


class TypedInt(int):
    """A whole number typed with a look of its own ("1,000", "007")."""

    typed = ""

    def __new__(cls, value, typed):
        number = super().__new__(cls, value)
        number.typed = typed
        return number

    def __reduce__(self):
        return type(self), (int(self), self.typed)


# the display formats the program writes for typed quantities
_TYPED_FORMAT = re.compile(r"^(?:0{1,3}(?:,000)+|0+)(?:\.0+)?$")


def typed_format(typed):
    """The Excel number format that shows the number as `typed`."""
    whole, _, decimals = typed.lstrip("-").partition(".")
    pattern = "".join("0" if ch.isdigit() else ch for ch in whole)
    return pattern + ("." + "0" * len(decimals) if decimals else "")


def _group(digits):
    parts = []
    while len(digits) > 3:
        parts.insert(0, digits[-3:])
        digits = digits[:-3]
    parts.insert(0, digits)
    return ",".join(parts)


def text_in_format(value, number_format):
    """The number as one of those formats shows it, or None for any other
    format (General, dates, money ...)."""
    if not isinstance(number_format, str) or \
            not _TYPED_FORMAT.match(number_format):
        return None
    whole, _, decimals = number_format.partition(".")
    text = f"{abs(value):.{len(decimals)}f}"
    int_part, _, fraction = text.partition(".")
    int_part = int_part.zfill(whole.count("0"))
    if "," in whole:
        int_part = _group(int_part)
    sign = "-" if value < 0 else ""
    return sign + int_part + ("." + fraction if fraction else "")


def typed_number(text):
    """to_number(), keeping how the number was typed when the program would
    otherwise show it differently ("1,250.50", "12.50", "007")."""
    number = to_number(text)
    if not isinstance(number, (int, float)) or isinstance(number, bool):
        return number
    typed = (text or "").strip()
    if cell_text(number) == typed or \
            text_in_format(number, typed_format(typed)) != typed:
        return number               # it shows as typed anyway (or cannot)
    return (TypedInt if isinstance(number, int) else TypedFloat)(number, typed)


def with_typed(value, number_format):
    """A cell's number with its display format -> the typed number, when the
    format is one the program writes for a typed quantity."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    typed = text_in_format(value, number_format)
    if typed is None or typed == cell_text(value):
        return value
    return (TypedInt if isinstance(value, int) else TypedFloat)(value, typed)


def put_cell(ws, row_no, col_index, value):
    """Write one cell. A typed number is written as a plain number with the
    display format that shows it as typed; a cell that had such a format
    and gets another value goes back to General."""
    typed = getattr(value, "typed", None)
    if typed:
        plain = int(value) if isinstance(value, int) else float(value)
        cell = ws.cell(row=row_no, column=col_index, value=plain)
        cell.number_format = typed_format(typed)
        return cell
    cell = ws.cell(row=row_no, column=col_index, value=value)
    if _TYPED_FORMAT.match(cell.number_format or ""):
        cell.number_format = "General"
    return cell


def sheet_rows(ws, typed_columns=()):
    """The rows below the heading, as values. A number in one of the
    `typed_columns` (0-based) that carries a typed display format comes
    back as typed (TypedInt / TypedFloat)."""
    rows = [list(row) for row in ws.iter_rows(min_row=2, values_only=True)]
    for column in typed_columns:
        cells = ws.iter_rows(min_row=2, min_col=column + 1,
                             max_col=column + 1)
        for index, (cell,) in enumerate(cells):
            if index < len(rows) and column < len(rows[index]) and \
                    cell.number_format != "General":
                rows[index][column] = with_typed(rows[index][column],
                                                 cell.number_format)
    return [tuple(row) for row in rows]


def parse_date(text, fmt=DATE_FORMAT):
    """Turn text into a real Excel date (falls back to text)."""
    for candidate in (fmt, DATE_FORMAT, LEGACY_DATE_FORMAT):
        try:
            return datetime.strptime(text, candidate)
        except (ValueError, TypeError):
            continue
    return text_or_none(text)


def cell_text(value, money=False, with_time=False, date_fmt=DATE_FORMAT):
    """Excel cell value -> text for an Entry box or a list."""
    if value is None:
        return ""

    typed = getattr(value, "typed", None)
    if typed and not money:
        return typed                    # a quantity, as it was typed

    if isinstance(value, datetime):
        return value.strftime(f"{date_fmt} %H:%M" if with_time else date_fmt)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if money:
            return f"{value:,.2f}"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    return str(value).strip()


def same_key(value, key):
    return str(value or "").strip().casefold() == key.strip().casefold()


def control_key(value):
    """What two Control #s are compared by: no outer spaces, no letter case
    ('fsr-abc-001' and 'FSR-ABC-001 ' are the same report)."""
    return str(value or "").strip().casefold()


class ControlKeyed(dict):
    """A dictionary keyed by Control # that finds its entries without regard
    to letter case or outer spaces. It keeps the spelling of the first key
    (the one in the workbook); name() returns that spelling."""

    def __init__(self, items=()):
        super().__init__()
        self._names = {}
        self.update(items)

    def name(self, control):
        """The stored spelling of this Control #, or None."""
        return self._names.get(control_key(control))

    def __setitem__(self, control, value):
        name = self._names.setdefault(control_key(control), control)
        super().__setitem__(name, value)

    def __getitem__(self, control):
        return super().__getitem__(self._names[control_key(control)])

    def __contains__(self, control):
        return control_key(control) in self._names

    def __delitem__(self, control):
        super().__delitem__(self._names.pop(control_key(control)))

    def get(self, control, default=None):
        name = self._names.get(control_key(control))
        return default if name is None else super().__getitem__(name)

    def pop(self, control, *default):
        name = self._names.pop(control_key(control), None)
        if name is None:
            if default:
                return default[0]
            raise KeyError(control)
        return super().pop(name)

    def setdefault(self, control, default=None):
        if control not in self:
            self[control] = default
        return self[control]

    def update(self, items=(), **more):
        for control, value in dict(items, **more).items():
            self[control] = value


# ---------- control number ---------------------------------

def set_control_initials(initials):
    """The signed-in inspector's initials, used for every new Control #."""
    cleaned = re.sub(r"[^A-Z0-9]", "", str(initials or "").upper())
    _control_initials["value"] = cleaned or NO_INITIALS


def control_initials_of(control_no):
    """'FSR-JDC-202610-0001' -> 'JDC'; None for any other format."""
    match = re.match(rf"^{CONTROL_PREFIX}-([A-Z0-9]+)-\d{{6}}-\d+$",
                     str(control_no or "").strip())
    return match.group(1) if match else None


def control_sort_key(control_no):
    """Sorts by period and running number, whoever the inspector, so a list is
    in order of age. Numbers of the older formats have the same order."""
    text = str(control_no or "").strip()
    match = re.match(
        rf"^{CONTROL_PREFIX}-(?:[A-Z0-9]*[A-Z][A-Z0-9]*-)?(\d{{4}})(\d{{2}})?-(\d+)$", text)
    if not match:
        return (0, 0, 0, text)
    period = int(match.group(1)) * 100 + int(match.group(2) or 0)
    return (1, period, int(match.group(3)), text)


def next_control_number(existing_numbers, initials=None):
    """FSR-<initials>-<year><month>-<running number>, e.g. FSR-JDC-202610-0007.
    Each inspector's running number starts again at 0001 every month. Numbers
    of the older FSR-<year><month>-NNNN format stay as they are and do not count."""
    period = datetime.now().strftime("%Y%m")
    initials = initials or _control_initials["value"]
    prefix = f"{CONTROL_PREFIX}-{initials}-{period}-"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")

    highest = 0
    for value in existing_numbers:
        match = pattern.match(str(value or "").strip())
        if match:
            highest = max(highest, int(match.group(1)))

    return f"{prefix}{highest + 1:04d}"


# PO-linked Withdrawal reports live in their own workbook beside this one
# (fsr_withdrawal.py). A Control # must stay unique across both files, because
# incident files and printed forms are named after it.
WITHDRAWAL_HEADER_SHEET = "Withdrawal Reports"


def withdrawal_control_numbers(path):
    """The Control #s in the Withdrawal workbook beside `path` ([] when there
    is none). Reads only the first column, so a file with a damaged layout
    still reserves its numbers."""
    other = Path(path).resolve().with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)
    if Workbook is None or other == Path(path).resolve() or not other.exists():
        return []
    try:
        wb = load_workbook(other, data_only=True)
        if WITHDRAWAL_HEADER_SHEET not in wb.sheetnames:
            return []
        return [
            cell_text(row[0]) for row in wb[WITHDRAWAL_HEADER_SHEET].iter_rows(
                min_row=2, max_col=1, values_only=True
            ) if row[0]
        ]
    except Exception:
        log.exception("Could not read control numbers from %s", other)
        return []


def check_layout(wb):
    """Stop if the file was not made by this program."""
    for name, (_, headers) in EXCEL_SHEETS.items():
        if name not in wb.sheetnames:
            continue

        first_row = next(
            wb[name].iter_rows(min_row=1, max_row=1, values_only=True), ()
        )
        actual = [value for value in first_row if value is not None]
        actual = [
            legacy_header(value, headers[index] if index < len(headers)
                          else None)
            for index, value in enumerate(actual)
        ]

        if name == "Reports":
            # Files saved by an earlier version may lack newer columns;
            # they are upgraded automatically when the next report is saved.
            ok = (
                bool(actual)
                and actual[0] == "Control #"
                and all(header in headers for header in actual)
            )
        else:
            # Newer trailing columns (e.g. Findings) may be missing in
            # older files; they are added when the next report is saved.
            ok = bool(actual) and actual == headers[:len(actual)]

        if not ok:
            raise ValueError(
                f'The sheet "{name}" in this Excel file has a different '
                "layout (it was not saved by this program).\n\n"
                "Use \"Change Excel File...\" to start a new file, or "
                "rename/delete this one."
            )


def report_dicts(ws):
    """Rows of the Reports sheet as {column name: value}.
    Works with older files because it uses the sheet's own header row."""
    first_row = next(
        ws.iter_rows(min_row=1, max_row=1, values_only=True), ()
    )
    headers = [value for value in first_row if value is not None]

    for row in ws.iter_rows(
        min_row=2, max_col=len(headers), values_only=True
    ):
        yield dict(zip(headers, row))


def migrate_reports_sheet(ws):
    """Add the newer columns to an older Reports sheet, keeping its data."""
    first_row = next(
        ws.iter_rows(min_row=1, max_row=1, values_only=True), ()
    )
    if [v for v in first_row if v is not None] == REPORT_HEADERS:
        return

    saved = [values for values in report_dicts(ws) if any(values.values())]

    ws.delete_rows(1, ws.max_row)
    for col_index, header in enumerate(REPORT_HEADERS, start=1):
        ws.cell(row=1, column=col_index, value=header)

    for values in saved:
        append_row(
            ws, [values.get(header) for header in REPORT_HEADERS],
            REPORT_FORMATS
        )


def rename_legacy_headers(ws, headers):
    """Give renamed columns (UOM -> Packaging) their new heading."""
    for index, cell in enumerate(ws[1]):
        if index < len(headers):
            cell.value = legacy_header(cell.value, headers[index])


def extend_sheet_headers(ws, headers):
    """Add the headings of newer trailing columns to an older sheet."""
    first_row = next(
        ws.iter_rows(min_row=1, max_row=1, values_only=True), ()
    )
    actual = [value for value in first_row if value is not None]

    for index in range(len(actual), len(headers)):
        ws.cell(row=1, column=index + 1, value=headers[index])


def open_workbook_for_read(path):
    wb = load_workbook(path, data_only=True)
    check_layout(wb)
    return wb


def generate_control_number(path):
    """Next free Control # for the given Excel file."""
    numbers = []

    try:
        if Workbook is not None and Path(path).exists():
            wb = open_workbook_for_read(path)
            if "Reports" in wb.sheetnames:
                numbers = [
                    row[0] for row in wb["Reports"].iter_rows(
                        min_row=2, max_col=1, values_only=True
                    )
                ]
    except Exception:
        log.exception("Could not read control numbers from %s", path)
        numbers = []   # unreadable file: the save itself will report it

    return next_control_number([*numbers, *withdrawal_control_numbers(path)])


# ---------- reading saved reports --------------------------

def list_saved_reports(path):
    """[(control, so, inspection date, consignee, last saved), ...]"""
    if Workbook is None or not Path(path).exists():
        return []

    wb = open_workbook_for_read(path)
    if "Reports" not in wb.sheetnames:
        return []

    reports = []
    for values in report_dicts(wb["Reports"]):
        if not values.get("Control #"):
            continue
        reports.append((
            cell_text(values.get("Control #")),
            cell_text(values.get("SO Number")),
            cell_text(values.get("Inspection Date")),
            cell_text(values.get("Consignee")),
            cell_text(values.get("Last Saved"), with_time=True),
        ))

    reports.sort(key=lambda entry: control_sort_key(entry[0]),
                 reverse=True)     # newest control # first
    return reports


def search_index_excel(path):
    """The same shape as db_mysql.search_index(), read from the workbook."""
    if Workbook is None or not Path(path).exists():
        return {}
    wb = open_workbook_for_read(path)
    index = {}

    def entry(control):
        return index.setdefault(control, {
            "so": [], "bl": [], "po": [], "dr": [], "gatepass": [],
            "description": []})

    def add(item, key, value):
        value = cell_text(value)
        if value:
            item[key].append(value)

    if "Reports" in wb.sheetnames:
        for values in report_dicts(wb["Reports"]):
            if not values.get("Control #"):
                continue
            item = entry(cell_text(values["Control #"]))
            add(item, "so", values.get("SO Number"))
            add(item, "bl", values.get("BL/AWB Number"))
            add(item, "po", values.get("PO Number"))
            add(item, "dr", values.get("DR Number"))
            add(item, "gatepass", values.get("Gatepass Number"))
    for sheet, desc_key in (("Item List", "Description of Goods"),
                            ("Declared Goods", "Description")):
        if sheet not in wb.sheetnames:
            continue
        for values in report_dicts(wb[sheet]):
            if not values.get("Control #"):
                continue
            item = entry(cell_text(values["Control #"]))
            add(item, "description", values.get(desc_key))
            if sheet == "Item List":
                add(item, "po", values.get("PO Number"))
    return index


def read_report(path, control_no):
    """Read one saved report; same shape as collect_report_data()."""
    wb = open_workbook_for_read(path)

    def rows_for(sheet_name):
        if sheet_name not in wb.sheetnames:
            return []
        return [
            row for row in sheet_rows(wb[sheet_name],
                                      TYPED_COLUMNS.get(sheet_name, ()))
            if same_key(row[0], control_no)
        ]

    matches = [
        values
        for values in (
            report_dicts(wb["Reports"]) if "Reports" in wb.sheetnames else []
        )
        if same_key(values.get("Control #"), control_no)
    ]
    if not matches:
        raise ValueError(
            f"Control # {control_no} was not found in the Excel file."
        )

    return report_from_rows(path, matches[0], rows_for)


def read_all_reports(path):
    """Every saved report (same shape as read_report()), reading the
    workbook ONCE. Used by the dashboard, the warehouse monitoring and
    the sample-data checks. [] when the file does not exist yet."""
    if Workbook is None or not Path(path).exists():
        return []
    wb = open_workbook_for_read(path)
    if "Reports" not in wb.sheetnames:
        return []

    grouped = {}
    for sheet_name in ("Declared Goods", "Item List", "Remarks"):
        by_control = grouped.setdefault(sheet_name, {})
        if sheet_name not in wb.sheetnames:
            continue
        for row in sheet_rows(wb[sheet_name],
                              TYPED_COLUMNS.get(sheet_name, ())):
            if row and row[0] is not None:
                key = str(row[0]).strip().casefold()
                by_control.setdefault(key, []).append(row)

    reports = []
    for values in report_dicts(wb["Reports"]):
        if not values.get("Control #"):
            continue
        key = str(values["Control #"]).strip().casefold()
        reports.append(report_from_rows(
            path, values,
            lambda sheet_name, key=key: grouped[sheet_name].get(key, [])))
    return reports


def report_from_rows(path, r, rows_for, shipment=True):
    """One report from its Reports row `r` (a {column: value} dict) and
    rows_for(sheet name) -> that report's rows of a child sheet.
    `shipment`: the Item List rows end with the SHIPMENT_HEADERS columns
    (the main workbook; not the Withdrawal workbook, whose own columns
    follow at that place)."""

    def text(header, **options):
        return cell_text(r.get(header), **options)

    # Declared goods
    declared_goods = [
        {
            "description": cell_text(row[1]),
            "quantity": cell_text(row[2]),
            "packaging": cell_text(row[3]),
        }
        for row in rows_for("Declared Goods")
    ]

    # Item lists ("Item List 1", "Item List 2", ...)
    lines_by_list = {}
    for row in rows_for("Item List"):
        try:
            list_no = int(str(row[1]).split()[-1])
        except (ValueError, IndexError):
            continue
        values = {
            header: cell_text(
                value,
                money=header in MONEY_ITEM_HEADERS
            )
            for header, value in zip(ITEM_LINE_HEADERS, row[3:])
        }
        for header in ITEM_LINE_HEADERS:     # older files: no Findings / links
            values.setdefault(header, "")
        if shipment:
            # older rows end before these columns; a line carries them only
            # when they hold something
            for header, value in zip(SHIPMENT_HEADERS, row[SHIPMENT_AT:]):
                if cell_text(value).strip():
                    values[header] = cell_text(value)
        lines_by_list.setdefault(list_no, []).append((row[2] or 0, values))

    item_lists = []
    for list_no in range(1, max(lines_by_list, default=1) + 1):
        lines = sorted(lines_by_list.get(list_no, []), key=lambda x: x[0])
        item_lists.append({
            "name": f"Item List {list_no}",
            "rows": [values for _, values in lines],
        })

    # Remarks
    remarks = {"Other Important Remarks": [], "Findings and Remarks": []}
    for row in sorted(rows_for("Remarks"), key=lambda x: x[2] or 0):
        remarks.setdefault(str(row[1]), []).append(cell_text(row[3]))

    # Cargo condition + incident reports (the incidents live in a JSON file).
    incident_reports, incident_error = [], None
    try:
        incident_reports = load_incident_data(path, text("Control #"))
    except ValueError as error:
        incident_error = str(error)
        log.exception("Incident file could not be read")

    condition = text("Cargo Condition")
    if condition not in (CONDITION_GOOD, CONDITION_BAD):
        condition = CONDITION_BAD if incident_reports else CONDITION_GOOD

    return {
        "control_no": text("Control #"),
        "cargo_condition": condition,
        "goods_types": goods_types_from_text(text("Types of Goods")),
        "item_form": item_form_name(text("Item List Form")),
        "incident_reports": incident_reports,
        "incident_error": incident_error,
        "general_information": {
            "so_number": text("SO Number"),
            "inspection_date": text("Inspection Date"),
            "consignee": text("Consignee"),
            "supplier": text("Supplier"),
            "brokerage": text("Brokerage"),
            "hauler": text("Hauler"),
            "location": text("Location"),
            "destination": text("Destination"),
            "country_of_origin": text("Country of Origin"),
        },
        "inspection_schedule": {
            key: text(header)
            for _, key, _, _, header in SCHEDULE_FIELDS
        },
        "transport_details": {
            key: text(header)
            for _, key, _, _, header in TRANSPORT_FIELDS
        },
        "documents_used": {
            key: text(label) for label, key in DOCUMENT_FIELDS
        },
        "declared_goods": declared_goods,
        "other_important_remarks": remarks["Other Important Remarks"],
        "item_lists": item_lists,
        "findings_and_remarks": remarks["Findings and Remarks"],
    }


# ---------- writing ----------------------------------------

def get_or_create_sheet(wb, name, headers):
    if name in wb.sheetnames:
        return wb[name]

    ws = wb.create_sheet(name)
    ws.append(headers)
    return ws


def apply_formats(ws, row_no, formats):
    for col_index, number_format in (formats or {}).items():
        cell = ws.cell(row=row_no, column=col_index)
        if cell.value is not None and not isinstance(cell.value, str):
            cell.number_format = number_format


def append_row(ws, values, formats=None):
    """Write below the last row (does not rely on private openpyxl state)."""
    row_no = ws.max_row + 1
    for col_index, value in enumerate(values, start=1):
        put_cell(ws, row_no, col_index, value)
    apply_formats(ws, row_no, formats)


def set_row(ws, row_no, values, formats=None):
    """Overwrite an existing row in place (used to update a report)."""
    for col_index, value in enumerate(values, start=1):
        put_cell(ws, row_no, col_index, value)
    apply_formats(ws, row_no, formats)


def find_row(ws, key):
    for row_no, (value,) in enumerate(
        ws.iter_rows(min_row=2, max_col=1, values_only=True), start=2
    ):
        if same_key(value, key):
            return row_no
    return None


def remove_key_rows(ws, key):
    """Delete every row of one report. Rows are removed in contiguous
    blocks, so this stays fast even when the file grows large."""
    matching = [
        row_no for row_no, (value,) in enumerate(
            ws.iter_rows(min_row=2, max_col=1, values_only=True), start=2
        )
        if same_key(value, key)
    ]

    blocks = []
    for row_no in matching:
        if blocks and row_no == blocks[-1][1] + 1:
            blocks[-1][1] = row_no
        else:
            blocks.append([row_no, row_no])

    for start, end in reversed(blocks):
        ws.delete_rows(start, end - start + 1)


def finalize_sheet(ws, table_name, headers):
    """Rebuild the Excel Table so it covers all rows, then tidy up."""

    for existing in list(ws.tables):
        del ws.tables[existing]

    last_row = ws.max_row
    last_col = get_column_letter(len(headers))

    # An Excel Table needs the header row plus at least one data row.
    if last_row >= 2:
        table = Table(displayName=table_name, ref=f"A1:{last_col}{last_row}")
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showRowStripes=True
        )
        ws.add_table(table)

    ws.freeze_panes = "A2"

    longest = [0] * len(headers)
    for row in ws.iter_rows(max_col=len(headers), values_only=True):
        for index, value in enumerate(row):
            if value is not None:
                longest[index] = max(longest[index], len(str(value)))

    for index, size in enumerate(longest, start=1):
        ws.column_dimensions[get_column_letter(index)].width = min(
            max(size + 3, 12), 60
        )


def report_row_values(data, control_no, saved_at=None):
    """One report as the values of a REPORT_HEADERS row."""
    general = data["general_information"]
    schedule = data["inspection_schedule"]
    transport = data["transport_details"]
    documents = data["documents_used"]

    values_by_header = {
        "Control #": control_no,
        "SO Number": text_or_none(general["so_number"]),
        "Inspection Date": parse_date(general["inspection_date"]),
        "Consignee": text_or_none(general["consignee"]),
        "Supplier": text_or_none(general["supplier"]),
        "Brokerage": text_or_none(general["brokerage"]),
        "Hauler": text_or_none(general["hauler"]),
        "Location": text_or_none(general["location"]),
        "Destination": text_or_none(general["destination"]),
        "Country of Origin": text_or_none(general["country_of_origin"]),
        "Cargo Condition": data.get("cargo_condition") or CONDITION_GOOD,
        "Types of Goods": text_or_none(
            goods_types_to_text(data.get("goods_types"))
        ),
        "Item List Form": item_form_name(data.get("item_form")),
        # `saved_at`: the time a save chose in advance, so that exactly
        # this save can be recognised later (fsr_save_journal).
        "Last Saved": saved_at or datetime.now(),
    }

    for _, key, _, kind, header in SCHEDULE_FIELDS:
        values_by_header[header] = (
            parse_date(schedule[key])
            if kind == "date" else text_or_none(schedule[key])
        )

    for _, key, _, _, header in TRANSPORT_FIELDS:
        values_by_header[header] = text_or_none(transport[key])

    for label, key in DOCUMENT_FIELDS:
        values_by_header[label] = text_or_none(documents[key])

    return [values_by_header[header] for header in REPORT_HEADERS]


def write_report_to_excel(path, data, editing, saved_at=None):
    """
    Save one report. If its Control # is already in the file the
    report is UPDATED, otherwise it is ADDED. `saved_at` becomes the
    report's Last Saved time (default: now).
    Returns {"control", "updated", "goods", "items", "remarks"}.
    """
    return write_reports_to_excel(path, [(data, editing, saved_at)])[0]


@fsr_drafts.report_write_lock
def write_reports_to_excel(path, items, expected=None, expected_file=fsr_drafts._UNSET):
    """Save several reports with ONE load and ONE save of the workbook
    (Import Master Data). `items`: [(data, editing, saved_at), ...], applied
    in this order exactly as write_report_to_excel() would apply them one
    by one. The file is replaced as a whole at the end, so either all of
    them are in it or none. Returns one result per item."""
    path = Path(path)
    fsr_drafts.check_stamp(fsr_drafts.file_version(path), expected_file)

    if path.exists():
        wb = load_workbook(path)
        check_layout(wb)
    else:
        wb = Workbook()
        wb.remove(wb.active)

    if expected is not None:
        fsr_drafts.check_stamp(fsr_drafts.workbook_stamp(wb, "Reports", expected[0]), expected[1])
    sheets = {
        name: get_or_create_sheet(wb, name, headers)
        for name, (_, headers) in EXCEL_SHEETS.items()
    }

    # Older files: add the newer columns, keep the saved reports.
    for name, (_, headers) in EXCEL_SHEETS.items():
        rename_legacy_headers(sheets[name], headers)
    migrate_reports_sheet(sheets["Reports"])
    for name, (_, headers) in EXCEL_SHEETS.items():
        if name != "Reports":
            extend_sheet_headers(sheets[name], headers)

    elsewhere = withdrawal_control_numbers(path)
    results = [_apply_report(sheets, data, editing, saved_at, elsewhere)
               for data, editing, saved_at in items]

    for name, (table_name, headers) in EXCEL_SHEETS.items():
        finalize_sheet(sheets[name], table_name, headers)

    # Save to a temporary file first so a failed save can never
    # damage the existing workbook.
    temp_path = path.with_name(path.stem + ".saving.tmp")

    try:
        wb.save(temp_path)
        fsr_drafts.check_stamp(fsr_drafts.file_version(path), expected_file)
        replace_file(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
    return results


def _apply_report(sheets, data, editing, saved_at, elsewhere):
    """Put one report into the open workbook's sheets."""
    reports_ws = sheets["Reports"]

    control_no = data["control_no"]
    existing_row = find_row(reports_ws, control_no)
    taken_elsewhere = any(same_key(n, control_no) for n in elsewhere)

    if editing and taken_elsewhere and not existing_row:
        raise ValueError(
            f"Control # {control_no} belongs to the Withdrawal workbook and "
            "cannot be saved into this file."
        )

    # A NEW report must never overwrite someone else's report that
    # got the same number in the meantime -> take the next free one.
    if (existing_row or taken_elsewhere) and not editing:
        control_no = next_control_number([
            *(row[0] for row in reports_ws.iter_rows(
                min_row=2, max_col=1, values_only=True
            )),
            *elsewhere,
        ])
        existing_row = None

    # --- Reports sheet (updated in place when it already exists) --
    report_values = report_row_values(data, control_no, saved_at)

    if existing_row:
        set_row(reports_ws, existing_row, report_values, REPORT_FORMATS)
    else:
        append_row(reports_ws, report_values, REPORT_FORMATS)

    # --- Child sheets: remove the old lines, write the current ones
    for name in ("Declared Goods", "Item List", "Remarks"):
        remove_key_rows(sheets[name], control_no)

    child = report_child_rows(data, control_no)
    price_formats = {
        4 + ITEM_HEADERS.index(header): "#,##0.00"
        for header in MONEY_ITEM_HEADERS
    }
    for name in ("Declared Goods", "Item List", "Remarks"):
        for values in child[name]:
            append_row(sheets[name], values,
                       price_formats if name == "Item List" else None)

    return {
        "control": control_no,
        "updated": existing_row is not None,
        "goods": len(data["declared_goods"]),
        "items": len(child["Item List"]),
        "remarks": len(child["Remarks"]),
    }


def report_child_rows(data, control_no):
    """The rows of one report on the Declared Goods, Item List and Remarks
    sheets, as cell values: {sheet name: [row values, ...]}. A Receiving
    line without a Receiving Ref gets its default one, written back into
    `data` (MySQL and the form use it too). Shared by the workbook and the
    SQLite store, so both hold exactly the same values."""
    schedule = data["inspection_schedule"]
    goods = [
        [
            control_no,
            text_or_none(row["description"]),
            typed_number(row["quantity"]),
            text_or_none(row["packaging"]),
        ]
        for row in data["declared_goods"]
    ]

    items = []
    receiving = same_key(schedule.get("activity"), "Receiving")
    for list_no, item_list in enumerate(data["item_lists"], start=1):
        for line_no, row in enumerate(item_list["rows"], start=1):
            # Every received line is a batch with its own reference; it is
            # written back into `data` so MySQL and the form get it too.
            if receiving and not str(row.get("Receiving Ref") or "").strip():
                row["Receiving Ref"] = default_receiving_ref(
                    control_no, list_no, line_no)
            values = [control_no, item_list["name"], line_no]
            for header in ITEM_LINE_HEADERS:
                if header == "Quantity":
                    values.append(typed_number(row.get(header, "")))
                elif header in NUMERIC_ITEM_HEADERS:
                    values.append(to_number(row.get(header, "")))
                else:
                    values.append(text_or_none(row.get(header, "")))
            for header in SHIPMENT_HEADERS:          # the last columns
                values.append(text_or_none(row.get(header, "")))
            items.append(values)

    remarks = []
    sections = [
        ("Other Important Remarks", data["other_important_remarks"]),
        ("Findings and Remarks", data["findings_and_remarks"]),
    ]
    for section_name, lines in sections:
        for line_no, remark in enumerate(lines, start=1):
            remarks.append([control_no, section_name, line_no, remark])

    return {"Declared Goods": goods, "Item List": items, "Remarks": remarks}


def delete_reports_from_excel(path, control_numbers):
    """Remove whole reports (every sheet) from the workbook. Used ONLY by
    the Demo Mode reset to remove TEST-... sample reports. Returns the
    number of reports removed."""
    path = Path(path)
    if Workbook is None or not path.exists():
        return 0
    wb = load_workbook(path)
    check_layout(wb)
    wanted = {str(c).strip() for c in control_numbers}
    removed = 0
    if "Reports" in wb.sheetnames:
        present = {control_key(row[0]) for row in wb["Reports"].iter_rows(
            min_row=2, max_col=1, values_only=True)}
        removed = len({control_key(c) for c in wanted} & present)
    for name, (table_name, headers) in EXCEL_SHEETS.items():
        if name not in wb.sheetnames:
            continue
        for control in wanted:
            remove_key_rows(wb[name], control)
        finalize_sheet(wb[name], table_name, headers)

    temp_path = path.with_name(path.stem + ".saving.tmp")
    try:
        wb.save(temp_path)
        replace_file(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
    return removed
