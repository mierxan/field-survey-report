"""Saved inspection reports -> transactions and transaction lines.

One inspection report = one transaction (its Activity says Receiving or
Withdrawal). Each Item List line of the report = one transaction line
(a cargo line). Report counts, line counts, quantities and weights are kept
apart everywhere.

Field mapping (existing fields of the inspection report):
    transaction date   Inspection Date
    transaction time   Commenced Time
    warehouse          Location
    unit of measure    UOM (older lines: Packaging)
    quantity           Quantity
    weight             Weights   (the line's weight, e.g. "1,250 kg")
    Cargo ID / Receiving Ref   the two warehouse link columns
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from fsr_storage import goods_types_to_text

RECEIVING = "Receiving"
WITHDRAWAL = "Withdrawal"
GOOD_ORDER = "Good Order"
BAD_ORDER = "Bad Order"
NO_WAREHOUSE = "(Location not recorded)"

DATE_FORMATS = ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d")

# Unit of measure aliases -> one code. Units that are not listed keep
# their own (upper-case) name; different names are never added together.
UNIT_ALIASES = {
    "PCS": ("pc", "pcs", "pce", "pces", "piece", "pieces", "ea", "each"),
    "SET": ("set", "sets"),
    "BOX": ("box", "boxes", "bx", "bxs"),
    "CRATE": ("crate", "crates", "wooden crate", "wooden crates"),
    "PALLET": ("pallet", "pallets", "plt", "plts"),
    "UNIT": ("unit", "units"),
    "LOT": ("lot", "lots"),
    "ROLL": ("roll", "rolls"),
    "BUNDLE": ("bundle", "bundles", "bdl", "bdls"),
    "LENGTH": ("length", "lengths", "lgth", "lgths"),
    "CASE": ("case", "cases", "cs"),
    "DRUM": ("drum", "drums"),
    "PKG": ("pkg", "pkgs", "package", "packages", "pack", "packs"),
    "M": ("m", "meter", "meters", "metre", "metres", "mtr", "mtrs", "lm"),
    "KG": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"),
}
UNIT_LOOKUP = {alias: code for code, aliases in UNIT_ALIASES.items()
               for alias in aliases}

# Weight units -> factor to kilograms (fixed conversion rules only).
WEIGHT_TO_KG = {
    "kg": 1.0, "kgs": 1.0, "kilo": 1.0, "kilos": 1.0, "kilogram": 1.0,
    "kilograms": 1.0,
    "g": 0.001, "gram": 0.001, "grams": 0.001,
    "mt": 1000.0, "t": 1000.0, "ton": 1000.0, "tons": 1000.0,
    "tonne": 1000.0, "tonnes": 1000.0, "metric ton": 1000.0,
    "metric tons": 1000.0,
    "lb": 0.45359237, "lbs": 0.45359237,
}

NUMBER_TEXT = re.compile(
    r"^\s*(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|-?\.\d+)\s*(.*?)\s*$")


def parse_day(text):
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    text = str(text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_unit(text):
    text = re.sub(r"\s+", " ", str(text or "").strip().rstrip(".")).casefold()
    if not text:
        return ""
    return UNIT_LOOKUP.get(text, text.upper())


def split_number(text):
    """'1,250.5 pcs' -> (1250.5, 'pcs');  '12' -> (12.0, '');
    'n/a' -> (None, 'n/a');  '' -> (None, '')."""
    text = str(text or "").strip()
    if not text:
        return None, ""
    match = NUMBER_TEXT.match(text)
    if not match:
        return None, text
    return float(match.group(1).replace(",", "")), match.group(2)


def parse_quantity(quantity_text, packaging_text, uom_text=""):
    """(quantity or None, unit code, problems). The unit is the UOM column,
    or the Packaging column for lines saved before UOM existed; a unit typed
    after the number ("12 pcs") is used when both are empty, and a clash
    between the two is reported."""
    problems = []
    number, trailing = split_number(quantity_text)
    if str(uom_text or "").strip():
        packaging_text = uom_text
    unit = normalize_unit(packaging_text)
    trailing_unit = normalize_unit(trailing)
    if number is None:
        if str(quantity_text or "").strip():
            problems.append(f"Quantity '{quantity_text}' is not a number")
        else:
            problems.append("Quantity is missing")
        return None, unit or trailing_unit, problems
    if number < 0:
        problems.append(f"Quantity {quantity_text} is negative")
        return None, unit or trailing_unit, problems
    if trailing_unit and unit and trailing_unit != unit:
        problems.append(f"Quantity unit '{trailing}' differs from "
                        f"UOM / Packaging '{packaging_text}'")
        return None, unit, problems
    return number, unit or trailing_unit, problems


def parse_weight(text):
    """(kilograms or None, note). A weight without a unit, or with an
    unknown unit, is not converted (it cannot be added to other weights)."""
    number, unit_text = split_number(text)
    if number is None:
        return None, ("" if not str(text or "").strip()
                      else f"Weight '{text}' is not a number")
    unit_text = re.sub(r"\s+", " ", unit_text.strip().rstrip(".")).casefold()
    if not unit_text:
        return None, "Weight has no unit (kg, MT, lbs)"
    factor = WEIGHT_TO_KG.get(unit_text)
    if factor is None:
        return None, f"Weight unit '{unit_text}' is not known"
    return number * factor, ""


def normalize_activity(text):
    text = str(text or "").strip().casefold()
    if text.startswith("receiv"):
        return RECEIVING
    if text.startswith("withdraw"):
        return WITHDRAWAL
    return text.title() if text else ""


def norm_key(text):
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


@dataclass
class Transaction:
    """One inspection report seen as a warehouse transaction."""
    control_no: str
    activity: str
    date: date | None
    date_text: str
    time: str
    so_number: str
    supplier: str
    consignee: str
    warehouse: str
    destination: str
    condition: str
    po_number: str
    dr_number: str
    gatepass_number: str
    bl_awb_number: str
    remarks: str
    incident_text: str
    goods_types: str = ""
    packages: float | None = None   # sum of the Declared Goods quantities
    line_count: int = 0
    is_test: bool = False
    lines: list = field(default_factory=list)

    @property
    def transaction_id(self):
        return self.control_no


@dataclass
class TransactionLine:
    """One cargo line of a transaction."""
    line_id: str                # <Control #>/<item list no>/<line no>
    control_no: str
    activity: str
    date: date | None
    time: str
    so_number: str
    cargo_id: str
    receiving_ref: str          # as recorded (Receiving lines: always set)
    description: str
    po_number: str
    supplier: str
    consignee: str
    warehouse: str
    destination: str
    condition: str
    quantity_text: str
    quantity: float | None
    unit: str
    weight_text: str
    weight_kg: float | None
    weight_note: str
    findings: str
    remarks: str
    problems: list = field(default_factory=list)
    currency: str = ""          # of the Unit Price and Total Price
    unit_price: str = ""        # as recorded
    total_price: str = ""

    @property
    def cargo_key(self):
        return norm_key(self.cargo_id)

    @property
    def ref_key(self):
        return norm_key(self.receiving_ref)

    @property
    def warehouse_key(self):
        return norm_key(self.warehouse)


def report_to_transaction(report):
    """A saved report (read_report() shape) -> Transaction with its lines."""
    info = report.get("general_information") or {}
    schedule = report.get("inspection_schedule") or {}
    docs = report.get("documents_used") or {}
    control = str(report.get("control_no") or "").strip()
    day = parse_day(info.get("inspection_date"))
    condition = (BAD_ORDER if report.get("cargo_condition") == BAD_ORDER
                 else GOOD_ORDER)
    remarks = "; ".join(str(t) for t in report.get("other_important_remarks")
                        or [] if str(t).strip())
    incident_text = " / ".join(
        line for card in report.get("incident_reports") or []
        for line in card.get("lines") or [] if str(line).strip())
    warehouse = str(info.get("location") or "").strip() or NO_WAREHOUSE
    tx = Transaction(
        control_no=control,
        activity=normalize_activity(schedule.get("activity")),
        date=day,
        date_text=str(info.get("inspection_date") or ""),
        time=str(schedule.get("commenced_time") or ""),
        so_number=str(info.get("so_number") or "").strip(),
        supplier=str(info.get("supplier") or "").strip(),
        consignee=str(info.get("consignee") or "").strip(),
        warehouse=warehouse,
        destination=str(info.get("destination") or "").strip(),
        condition=condition,
        po_number=str(docs.get("po_number") or "").strip(),
        dr_number=str(docs.get("dr_number") or "").strip(),
        gatepass_number=str(docs.get("gatepass_number") or "").strip(),
        bl_awb_number=str(docs.get("bl_awb_number") or "").strip(),
        remarks=remarks,
        incident_text=incident_text,
        goods_types=goods_types_to_text(report.get("goods_types")),
        is_test=control.upper().startswith("TEST-"),
    )
    declared = [split_number(g.get("quantity"))[0]
                for g in report.get("declared_goods") or []]
    declared = [q for q in declared if q is not None and q >= 0]
    tx.packages = sum(declared) if declared else None
    for list_no, item_list in enumerate(report.get("item_lists") or [],
                                        start=1):
        for line_no, row in enumerate(item_list.get("rows") or [], start=1):
            if not any(str(v or "").strip() for v in row.values()):
                continue
            quantity, unit, problems = parse_quantity(
                row.get("Quantity"), row.get("Packaging"), row.get("UOM"))
            weight_kg, weight_note = parse_weight(row.get("Weights"))
            tx.lines.append(TransactionLine(
                line_id=f"{control}/{list_no}/{line_no}",
                control_no=control,
                activity=tx.activity,
                date=day,
                time=tx.time,
                so_number=tx.so_number,
                cargo_id=str(row.get("Cargo ID") or "").strip(),
                receiving_ref=str(row.get("Receiving Ref") or "").strip(),
                description=str(row.get("Description of Goods") or "").strip(),
                po_number=(str(row.get("PO Number") or "").strip()
                           or tx.po_number),
                supplier=tx.supplier,
                consignee=tx.consignee,
                warehouse=warehouse,
                destination=tx.destination,
                condition=condition,
                quantity_text=str(row.get("Quantity") or "").strip(),
                quantity=quantity,
                unit=unit,
                weight_text=str(row.get("Weights") or "").strip(),
                weight_kg=weight_kg,
                weight_note=weight_note,
                findings=str(row.get("Findings") or "").strip(),
                remarks=remarks,
                problems=problems,
                currency=str(row.get("Currency") or "").strip(),
                unit_price=str(row.get("Unit Price") or "").strip(),
                total_price=str(row.get("Total Price") or "").strip(),
            ))
    tx.line_count = len(tx.lines)
    return tx


def build_transactions(reports):
    """Reports -> transactions, sorted by date then Control #. Reports
    without a usable date are kept (they appear in "All Records" and are
    flagged by the inventory)."""
    transactions = [report_to_transaction(r) for r in reports or []]
    transactions.sort(key=lambda t: (t.date or date.max, t.control_no))
    return transactions


def all_lines(transactions):
    return [line for tx in transactions for line in tx.lines]
