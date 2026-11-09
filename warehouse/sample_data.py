"""Isolated sample (TEST-...) Receiving and Withdrawal data.

Every sample record is fictional and recognisable:
    Control #   TEST-REC-0001 ... (Receiving), TEST-WDR-0001 ... (Withdrawal)
    Cargo ID    TEST-...          SO Number  TEST-SO-...
    names       "Test Supplier ...", "TEST Warehouse ..."

The reports are written with the program's own storage code
(fsr_storage.write_report_to_excel / save_incident_data), so the sample
data goes through exactly the same path as a report saved from the form.

Safety:
  * only into a folder that carries the test-data marker file; a folder
    is marked only when it holds no Excel file with non-TEST reports;
  * the program folder itself is never used;
  * running it again UPDATES the same TEST-... reports (no duplicates);
  * reset removes TEST-... reports and files only - nothing else.

Command line (from the program folder):
    python -m warehouse.sample_data generate     (into data\\excel\\demo_data\\)
    python -m warehouse.sample_data status
    python -m warehouse.sample_data reset
"""

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import fsr_storage
import fsr_paths

ROOT = Path(__file__).resolve().parent.parent
DEMO_FOLDER = ROOT / "data" / "excel" / "demo_data"
DEMO_WORKBOOK = "Field_Survey_Reports_DEMO.xlsx"
MARKER_NAME = ".fsr_test_data"
TEST_PREFIX = "TEST-"

WH_A = "TEST Warehouse A - North Yard"
WH_B = "TEST Warehouse B - South Bay"
SUPPLIERS = ["Test Supplier Alpha Industrial", "Test Supplier Beta Valves",
             "Test Supplier Gamma Steel", "Test Supplier Delta Power"]
CONSIGNEES = ["Test Consignee Power Co.", "Test Consignee Geothermal Unit"]
DESTINATIONS = ["TEST-SITE-1", "TEST-SITE-2", "TEST-SITE-3"]
BROKER = "Test Brokerage Services"
HAULER = "Test Hauler Logistics"

# Filler catalogue: (code, description, unit, kg per unit, goods type)
CATALOGUE = [
    ("GV", "Gate Valve 4in Class 300", "PCS", 38.0, "new"),
    ("BV", "Butterfly Valve 10in", "PCS", 52.0, "new"),
    ("SP", "Steel Pipe 4in SCH80, 6m", "PCS", 98.0, "new"),
    ("SC", "Steel Channel C100, 6m", "PCS", 56.0, "new"),
    ("PL", "Steel Plate 12mm 4x8ft", "PCS", 280.0, "new"),
    ("PA", "Pump Assembly 50HP", "SET", 410.0, "new"),
    ("EM", "Electric Motor 7.5kW", "PCS", 65.0, "new"),
    ("TR", "Transformer 75kVA", "UNIT", 520.0, "new"),
    ("IE", "Industrial Equipment - Compressor Skid", "UNIT", 1250.0, "used"),
    ("WC", "Wooden Crate - Mechanical Components", "CRATE", 180.0, "used"),
    ("SPK", "Spare Parts Kit", "BOX", 12.5, "new"),
    ("MC", "Mechanical Components - Bearings", "BOX", 20.0, "new"),
]


class UnsafeTargetError(RuntimeError):
    """Refused: the target could contain or reach real records."""


# ---------- safety ----------

def workbook_controls(path):
    try:
        return [r["control_no"] for r in fsr_storage.read_all_reports(path)]
    except FileNotFoundError:
        return []


def non_test_controls(path):
    return [c for c in workbook_controls(path)
            if not str(c).upper().startswith(TEST_PREFIX)]


def mark_test_folder(folder):
    """Mark `folder` as a test-data folder (creating it). Refused for the
    program folder or a folder with real reports in an Excel file."""
    folder = Path(folder).resolve()
    if folder == ROOT.resolve() or folder in ROOT.resolve().parents:
        raise UnsafeTargetError(
            f"{folder} is the program folder (or above it); sample data "
            "goes into its own folder such as data/excel/demo_data.")
    folder.mkdir(parents=True, exist_ok=True)
    for workbook in folder.glob("*.xlsx"):
        real = non_test_controls(workbook)
        if real:
            raise UnsafeTargetError(
                f"{workbook.name} contains {len(real)} real report(s) "
                f"(e.g. {real[0]}); sample data is never mixed with them.")
    marker = folder / MARKER_NAME
    if not marker.exists():
        marker.write_text(
            "This folder holds FICTIONAL sample data (TEST-... records) for "
            "the Field Survey Report Demo Mode and tests.\n", encoding="utf-8")
    return folder


def check_target(path):
    path = Path(path).resolve()
    if not (path.parent / MARKER_NAME).exists():
        raise UnsafeTargetError(
            f"{path.parent} is not marked as a test-data folder "
            f"(missing {MARKER_NAME}).")
    real = non_test_controls(path) if path.exists() else []
    if real:
        raise UnsafeTargetError(
            f"{path.name} contains real reports (e.g. {real[0]}); sample "
            "data is never written into it.")
    return path


# ---------- the data set ----------

@dataclass
class LineSpec:
    cargo_id: str
    description: str
    quantity: object                # number, or "" for a missing quantity
    unit: str
    weight_kg: float | None = None
    receiving_ref: str = ""
    po_number: str = ""
    source_cargo_id: str = ""       # withdrawals by Receiving Ref: the item


@dataclass
class ReportSpec:
    control_no: str
    activity: str
    day: date
    warehouse: str
    lines: list
    condition: str = "Good Order"
    supplier: str = ""
    consignee: str = CONSIGNEES[0]
    destination: str = ""
    goods_type: str = "new"
    incident: list = field(default_factory=list)
    scenario: str = ""
    so_number: str = ""


@dataclass
class SampleSet:
    anchor: date
    reports: list                   # ReportSpec

    @property
    def receiving(self):
        return [r for r in self.reports if r.activity == "Receiving"]

    @property
    def withdrawals(self):
        return [r for r in self.reports if r.activity == "Withdrawal"]


def build_sample_set(anchor=None, seed=2026):
    """The fixed scenario reports + generated filler, dated relative to
    `anchor` (default today) so the aging scenarios always hold."""
    anchor = anchor or date.today()
    rng = random.Random(seed)
    reports = []
    counters = {"Receiving": 0, "Withdrawal": 0}

    def day(offset):
        return anchor - timedelta(days=offset)

    def add(activity, offset, warehouse, lines, scenario="", **extra):
        counters[activity] += 1
        prefix = "TEST-REC" if activity == "Receiving" else "TEST-WDR"
        number = counters[activity]
        spec = ReportSpec(
            control_no=f"{prefix}-{number:04d}", activity=activity,
            day=day(offset), warehouse=warehouse, lines=lines,
            scenario=scenario,
            so_number=f"TEST-SO-{'R' if activity == 'Receiving' else 'W'}"
                      f"{number:04d}", **extra)
        if activity == "Receiving" and not spec.supplier:
            spec.supplier = SUPPLIERS[number % len(SUPPLIERS)]
        if activity == "Withdrawal" and not spec.destination:
            spec.destination = DESTINATIONS[number % len(DESTINATIONS)]
        reports.append(spec)
        return spec

    def L(cargo, desc, qty, unit, kg=None, **kw):
        weight = None if kg is None or qty in ("", None) else qty * kg
        return LineSpec(cargo, desc, qty, unit, weight, **kw)

    R, W = "Receiving", "Withdrawal"
    # --- A-E: basic balances ---
    add(R, 60, WH_A, [L("TEST-PUMP-A01", "Pump Assembly 30HP", 20, "PCS",
                        95)], "A")
    add(R, 80, WH_A, [L("TEST-PIPE-B01", "Steel Pipe 6in SCH40, 6m", 100,
                        "PCS", 170)], "B")
    add(R, 95, WH_A, [L("TEST-MOTOR-C01", "Electric Motor 15kW", 50, "PCS",
                        110)], "C")
    add(R, 70, WH_A, [L("TEST-CHAN-D01", "Steel Channel C150, 6m", 40, "PCS",
                        80)], "D")
    add(R, 40, WH_A, [L("TEST-CHAN-D01", "Steel Channel C150, 6m", 60, "PCS",
                        80)], "D")
    add(R, 85, WH_A, [L("TEST-PLATE-E01", "Steel Plate 10mm 4x8ft", 100,
                        "PCS", 230)], "E")
    # --- G: same description, different Cargo IDs ---
    add(R, 50, WH_A, [L("TEST-VALVE-001", "Gate Valve 6in Class 150", 20,
                        "PCS", 60)], "G")
    add(R, 48, WH_A, [L("TEST-VALVE-002", "Gate Valve 6in Class 150", 30,
                        "PCS", 60)], "G")
    # --- H: over-withdrawal ---
    add(R, 65, WH_A, [L("TEST-XFMR-H01", "Transformer 500kVA", 20, "PCS",
                        900)], "H")
    # --- J: missing quantity on a Receiving line ---
    add(R, 30, WH_A, [L("TEST-SPARE-J01", "Spare Parts Kit - Pump Seals", "",
                        "BOX")], "J")
    # --- K: same Cargo ID in two warehouses ---
    add(R, 55, WH_A, [L("TEST-COMP-K01", "Mechanical Components - Couplings",
                        30, "SET", 15)], "K")
    add(R, 52, WH_B, [L("TEST-COMP-K01", "Mechanical Components - Couplings",
                        10, "SET", 15)], "K")
    # --- L: aging 3 / 14 / 45 / 75 / >90 days ---
    for age in (3, 14, 45, 75, 100):
        add(R, age, WH_B, [L(f"TEST-AGE-{age:03d}",
                             "Wooden Crate - Industrial Equipment", 5,
                             "CRATE", 200)], "L", goods_type="used")
    # --- M: duplicate import (same Receiving Ref) + look-alikes ---
    add(R, 20, WH_B, [L("TEST-BFV-M01", "Butterfly Valve 8in", 12, "PCS", 40,
                        receiving_ref="TEST-RR-DUP-01")], "M")
    add(R, 20, WH_B, [L("TEST-BFV-M01", "Butterfly Valve 8in", 12, "PCS", 40,
                        receiving_ref="TEST-RR-DUP-01")], "M-duplicate")
    add(R, 18, WH_B, [L("TEST-BFV-M02", "Butterfly Valve 8in", 12, "PCS", 40),
                      L("TEST-BFV-M03", "Butterfly Valve 8in", 12, "PCS", 40)],
        "M-lookalike")
    # --- incompatible units ---
    add(R, 35, WH_A, [L("TEST-CABLE-U01", "Power Cable 3C x 95mm2", 100, "M",
                        4.2)], "U1")
    add(R, 33, WH_A, [L("TEST-CABLE-U01", "Power Cable 3C x 95mm2", 2,
                        "ROLL", 420)], "U1")
    add(R, 28, WH_A, [L("TEST-BOLT-U02", "Anchor Bolts M24", 500, "PCS",
                        0.9)], "U2")
    add(R, 26, WH_B, [L("TEST-GEAR-J02", "Gearbox Reducer 1:20", 8, "PCS",
                        140)], "J2")
    # --- F: Bad Order receiving ---
    for offset, wh, cargo, desc, qty, unit, kg in (
            (22, WH_A, "TEST-EQP-F01", "Industrial Equipment - Air Dryer Skid",
             2, "UNIT", 800),
            (12, WH_B, "TEST-VALVE-F02", "Gate Valve 4in Class 150", 15, "PCS",
             30),
            (5, WH_A, "TEST-PUMP-F03", "Pump Assembly 10HP", 3, "PCS", 60)):
        add(R, offset, wh, [L(cargo, desc, qty, unit, kg)], "F",
            condition="Bad Order",
            incident=[f"TEST incident: {desc} - crate damaged on arrival.",
                      "TEST incident: photos taken, consignee notified."])

    # --- filler Receiving (fictional, seeded) ---
    filler = []                     # (spec line, report) for withdrawals
    serial = 0
    while counters[R] < 52:
        lines = []
        for _ in range(rng.choice((1, 1, 2, 3))):
            code, desc, unit, kg, kind = rng.choice(CATALOGUE)
            serial += 1
            qty = rng.choice((4, 6, 10, 12, 20, 24, 30, 40, 50, 80, 120))
            lines.append(L(f"TEST-{code}-{serial:03d}", desc, qty, unit, kg))
        offset = rng.randint(1, 110)
        warehouse = rng.choice((WH_A, WH_A, WH_B))
        bad = counters[R] % 7 == 3
        spec = add(R, offset, warehouse, lines, "filler",
                   condition="Bad Order" if bad else "Good Order",
                   goods_type=rng.choice(("new", "new", "used")),
                   incident=(["TEST incident: wet packaging found."]
                             if bad else []))
        filler.extend((line, spec) for line in lines)

    # --- withdrawals of the scenarios ---
    add(W, 60, WH_A, [L("TEST-PIPE-B01", "Steel Pipe 6in SCH40, 6m", 35,
                        "PCS", 170)], "B")
    add(W, 70, WH_A, [L("TEST-MOTOR-C01", "Electric Motor 15kW", 30, "PCS",
                        110)], "C")
    add(W, 40, WH_A, [L("TEST-MOTOR-C01", "Electric Motor 15kW", 20, "PCS",
                        110)], "C")
    add(W, 30, WH_A, [L("TEST-CHAN-D01", "Steel Channel C150, 6m", 25, "PCS",
                        80)], "D")
    for offset, qty in ((75, 20), (50, 15), (20, 10)):
        add(W, offset, WH_A, [L("TEST-PLATE-E01", "Steel Plate 10mm 4x8ft",
                                qty, "PCS", 230)], "E")
    add(W, 30, WH_A, [L("TEST-VALVE-001", "Gate Valve 6in Class 150", 5,
                        "PCS", 60)], "G")
    add(W, 45, WH_A, [L("TEST-XFMR-H01", "Transformer 500kVA", 25, "PCS",
                        900)], "H")
    add(W, 15, WH_A, [L("TEST-GHOST-999", "Gate Valve 6in Class 150", 3,
                        "PCS")], "I")
    add(W, 25, WH_B, [L("TEST-COMP-K01", "Mechanical Components - Couplings",
                        5, "SET", 15)], "K")
    add(W, 10, WH_B, [L("TEST-PLATE-E01", "Steel Plate 10mm 4x8ft", 5, "PCS",
                        230)], "K-cross")
    add(W, 14, WH_A, [L("TEST-BOLT-U02", "Anchor Bolts M24", 5, "BOX")], "U2")
    add(W, 8, WH_B, [L("TEST-GEAR-J02", "Gearbox Reducer 1:20", "", "PCS")],
        "J2")
    add(W, 9, WH_A, [L("", "Gate Valve 6in Class 150", 2, "PCS")], "I-no-id")

    # --- filler withdrawals: partial, never more than what is left ---
    left = {}
    for line, spec in filler:
        left[line.cargo_id] = [line, spec, line.quantity]
    candidates = sorted(left.values(), key=lambda v: v[1].day)
    rng.shuffle(candidates)
    by_ref_done = 0
    for line, spec, _ in candidates:
        if counters[W] >= 32:
            break
        remaining = left[line.cargo_id][2]
        if remaining < 2:
            continue
        qty = max(1, remaining // rng.choice((2, 3, 4)))
        offset = max(0, (anchor - spec.day).days - rng.randint(1, 20))
        kw = {}
        if by_ref_done < 3:
            # name the batch (Receiving Ref) instead of the Cargo ID
            kw["receiving_ref"] = fsr_storage.default_receiving_ref(
                spec.control_no, 1, spec.lines.index(line) + 1)
            cargo = ""
            by_ref_done += 1
        else:
            cargo = line.cargo_id
        wline = L(cargo, line.description, qty, line.unit,
                  line.weight_kg / line.quantity if line.weight_kg else None,
                  **kw)
        bad = counters[W] == 20
        add(W, offset, spec.warehouse, [wline], "filler",
            condition="Bad Order" if bad else "Good Order",
            incident=(["TEST incident: forklift scratch on outer box."]
                      if bad else []))
        left[line.cargo_id][2] -= qty
        wline.source_cargo_id = line.cargo_id
    return SampleSet(anchor, reports)


# ---------- spec -> report data (collect_report_data() shape) ----------

def report_data(spec):
    goods = fsr_storage.empty_goods_types()
    goods[spec.goods_type] = True
    rows = []
    for line in spec.lines:
        row = {h: "" for h in fsr_storage.ITEM_LINE_HEADERS}
        row.update({
            "Description of Goods": line.description,
            "PO Number": f"TEST-PO-{spec.control_no[-4:]}",
            "Packaging": line.unit,
            "Quantity": ("" if line.quantity in ("", None)
                         else f"{line.quantity:g}"),
            "UOM": line.unit,
            "Weights": ("" if line.weight_kg is None
                        else f"{line.weight_kg:,.1f} kg"),
            "Findings": ("Damaged packaging" if spec.condition == "Bad Order"
                         else "Good condition"),
            "Cargo ID": line.cargo_id,
            "Receiving Ref": line.receiving_ref,
        })
        rows.append(row)
    date_text = spec.day.strftime(fsr_storage.DATE_FORMAT)
    return {
        "control_no": spec.control_no,
        "cargo_condition": spec.condition,
        "goods_types": goods,
        "incident_reports": [{
            "vessel": "n/a", "voyage": "", "client": spec.consignee,
            "so_number": spec.so_number, "port": spec.warehouse,
            "date": date_text, "operation": spec.activity,
            "lines": spec.incident}] if spec.incident else [],
        "general_information": {
            "so_number": spec.so_number, "inspection_date": date_text,
            "consignee": spec.consignee, "supplier": spec.supplier,
            "brokerage": BROKER, "hauler": HAULER,
            "location": spec.warehouse, "destination": spec.destination,
            "country_of_origin": "",
        },
        "inspection_schedule": {
            "activity": spec.activity, "commenced_date": date_text,
            "commenced_time": "0800H", "completion_date": date_text,
            "completion_time": "1100H"},
        "transport_details": {
            "shipment_type": "Local", "container_type": "Non-Containerized",
            "vessel_carrier": "n/a", "vehicle_type": "Test Truck 10W",
            "vehicle_plate_number": "TEST-123"},
        "documents_used": {
            "invoice_number": f"TEST-INV-{spec.control_no[-4:]}",
            "po_number": f"TEST-PO-{spec.control_no[-4:]}",
            "jo_number": "", "gatepass_number": "",
            "bl_awb_number": "",
            "dr_number": f"TEST-DR-{spec.control_no[-4:]}",
            "other_documents": "TEST DATA - fictional record"},
        "declared_goods": [],
        "other_important_remarks": [
            f"TEST DATA - scenario {spec.scenario or 'filler'}"],
        "item_lists": [{"name": "Item List 1", "rows": rows}],
        "findings_and_remarks": [],
    }


# ---------- write / reset ----------

def generate(folder=DEMO_FOLDER, anchor=None, workbook_name=DEMO_WORKBOOK):
    """Write (or update) every sample report. Returns (path, SampleSet)."""
    folder = mark_test_folder(folder)
    path = check_target(folder / workbook_name)
    sample = build_sample_set(anchor)
    for spec in sample.reports:
        data = report_data(spec)
        fsr_storage.write_report_to_excel(path, data, editing=True)
        if spec.condition == "Bad Order":
            fsr_storage.save_incident_data(path, spec.control_no,
                                           spec.so_number,
                                           data["incident_reports"])
        else:
            fsr_storage.delete_incident_data(path, spec.control_no)
    return path, sample


def is_test_subject(subject):
    """A reconciliation subject (line id or item key) of TEST data."""
    subject = str(subject or "").casefold()
    if subject.startswith("test-"):
        return True
    return "|id:test-" in subject or "|ref:test-" in subject         or "|ref:rcv-test-" in subject


def reset(folder=DEMO_FOLDER, workbook_name=DEMO_WORKBOOK):
    """Remove the TEST-... reports, their incident files and report forms,
    and TEST-related reconciliation entries - nothing else, even when
    other reports were typed in Demo Mode. Returns what was removed."""
    from .store import side_file_path
    folder = Path(folder).resolve()
    if not (folder / MARKER_NAME).exists():
        raise UnsafeTargetError(f"{folder} is not a test-data folder.")
    path = folder / workbook_name
    tests = [c for c in workbook_controls(path)
             if str(c).upper().startswith(TEST_PREFIX)] if path.exists() else []
    removed = fsr_storage.delete_reports_from_excel(path, tests) if tests else 0
    files = 0
    json_folder = fsr_paths.json_dir_for_workbook(path)
    test_file_folders = (
        json_folder / fsr_storage.INCIDENT_FOLDER_NAME,
        folder / "Report Forms",
        json_folder / fsr_storage.ITEM_FORM_FOLDER_NAME,
    )
    for test_file_folder in test_file_folders:
        for item in test_file_folder.glob(f"{TEST_PREFIX}*"):
            item.unlink()
            files += 1
    side = side_file_path(path)
    if side.exists():
        import json
        data = json.loads(side.read_text(encoding="utf-8"))
        data["reconciliation"] = [
            e for e in data.get("reconciliation", [])
            if not is_test_subject(e.get("subject"))]
        data["case_status"] = [
            e for e in data.get("case_status", [])
            if not str(e.get("control_no", "")).upper().startswith(
                TEST_PREFIX)]
        fsr_storage.write_json_atomic(side, data)
    return {"reports": removed, "files": files}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fictional TEST-... sample data for Demo Mode.")
    parser.add_argument("action", choices=("generate", "reset", "status"))
    parser.add_argument("--folder", default=str(DEMO_FOLDER))
    args = parser.parse_args(argv)
    try:
        if args.action == "generate":
            path, sample = generate(args.folder)
            print(f"{len(sample.receiving)} Receiving and "
                  f"{len(sample.withdrawals)} Withdrawal TEST reports "
                  f"written to:\n  {path}")
        elif args.action == "reset":
            result = reset(args.folder)
            print(f"Removed {result['reports']} TEST report(s) and "
                  f"{result['files']} TEST file(s).")
        else:
            path = Path(args.folder) / DEMO_WORKBOOK
            controls = workbook_controls(path) if path.exists() else []
            print(f"{path}: {len(controls)} report(s), "
                  f"{len(non_test_controls(path)) if controls else 0} "
                  "non-TEST.")
    except UnsafeTargetError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
