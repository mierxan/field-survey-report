"""The two new hidden line fields (Packing List No., Origin Line) against the
PREVIOUS version of the program: its own code, taken from the last commit
(git archive HEAD) and run as a separate program. Invented data only, in
temporary folders.

  * workbooks and reports databases written by the previous version read the
    same in this version (every report, every line, PO-linked Withdrawals too)
  * this version adds the columns at the END of the main Item List sheet when
    it saves; the Withdrawal workbook keeps its layout
  * the way back: the previous version still reads a reports database this
    version wrote to (the fields are simply not known to it); a WORKBOOK
    this version saved is refused by the previous version (the known caveat)
"""
import json
import os
import subprocess
import sys
import tarfile
import io
from datetime import date
from pathlib import Path

import pytest

import fsr_paths
import fsr_shipment as sh
import fsr_storage as storage
import fsr_store
import fsr_withdrawal as wd
from factories import report
from test_withdrawal import linked_report

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def previous(tmp_path_factory):
    """The previous version's program files (the last commit)."""
    folder = tmp_path_factory.mktemp("previous_version")
    try:
        archive = subprocess.run(["git", "archive", "HEAD"], cwd=ROOT,
                                 capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        pytest.skip(f"git is not available: {error}")
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(folder, filter="data")
    assert "SHIPMENT_HEADERS" not in (folder / "fsr_storage.py").read_text(
        encoding="utf-8")                # really the version before
    return folder


def run_previous(previous, script, home, **env):
    """Runs `script` with the previous version's code; returns its JSON."""
    code = ("import sys, json\n"
            f"sys.path[:0] = [{str(previous)!r}, {str(previous / 'tests')!r}]\n"
            "import fsr_paths\n"
            f"home = {str(home)!r}\n"
            "from pathlib import Path\n"
            "fsr_paths.configure_data_dirs(Path(home), Path(home) / 'json', "
            "Path(home) / 'excel')\n" + script)
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=previous, env={**os.environ, "FSR_SECRET_STORE": "memory", **env})
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def invented(control, activity="Receiving", findings=""):
    value = report(control, activity, date(2026, 11, 10), "TEST Yard",
                   [{"qty": 3, "unit": "Crate", "desc": "TEST valve",
                     "po": "TEST-PO-1"},
                    {"qty": 1, "unit": "Box", "desc": "TEST seat",
                     "po": "TEST-PO-2"}])
    for row in value["item_lists"][0]["rows"]:
        row["Findings"] = findings
        row["UOM"] = "PCS"
    return value


def home_of(tmp_path, name):
    home = tmp_path / name
    (home / "excel").mkdir(parents=True)
    (home / "json").mkdir()
    fsr_paths.configure_data_dirs(home, home / "json", home / "excel")
    return home, home / "excel" / "Field_Survey_Reports.xlsx"


WRITE_OLD = """
import fsr_store
from datetime import date
from factories import report
book = Path(home) / 'excel' / 'Field_Survey_Reports.xlsx'
for control, activity, findings in %s:
    value = report(control, activity, date(2026, 11, 10), 'TEST Yard',
                   [{'qty': 3, 'unit': 'Crate', 'desc': 'TEST valve',
                     'po': 'TEST-PO-1'},
                    {'qty': 1, 'unit': 'Box', 'desc': 'TEST seat',
                     'po': 'TEST-PO-2'}])
    for row in value['item_lists'][0]['rows']:
        row['Findings'] = findings
        row['UOM'] = 'PCS'
    fsr_store.ExcelStore(book).write_report(value, False)
print(json.dumps(fsr_store.ExcelStore(book).read_all_reports(), default=str))
"""

READ_OLD = """
import fsr_store
book = Path(home) / 'excel' / 'Field_Survey_Reports.xlsx'
store = fsr_store.open_store(book)
print(json.dumps({'kind': store.kind,
                  'reports': store.read_all_reports()}, default=str))
"""

OLD_REPORTS = [("FSR-OLD-202611-0001", "Receiving", "Good Order"),
               ("FSR-OLD-202611-0002", "Withdrawal", "NOR111126-003")]


def with_shipment_line(control):
    """A Receiving report as made from a shipment file (this version)."""
    value = invented(control)
    rows = value["item_lists"][0]["rows"]
    rows[0].update({"Packing List No.": "NOR111126-001 & 002",
                    "Origin Line": "FSR-ORG-202611-0001/1/1",
                    "Findings": "Good Order and Complete"})
    rows[1].update({"Packing List No.": "NOR111126-003",
                    "Origin Line": "FSR-ORG-202611-0001/1/2",
                    "Findings": "1 crate dented"})
    return value


# ---------- the workbook ----------

def test_a_workbook_of_the_previous_version_reads_the_same(previous,
                                                           tmp_path):
    home, book = home_of(tmp_path, "pc")
    old = run_previous(previous, WRITE_OLD % OLD_REPORTS, home)
    now = fsr_store.ExcelStore(book).read_all_reports()
    assert json.loads(json.dumps(now, default=str)) == old
    assert all(sh.PACKING_LIST not in row and sh.ORIGIN_LINE not in row
               for r in now for il in r["item_lists"] for row in il["rows"])


def test_saving_adds_the_columns_at_the_end_and_old_reports_stay(
        previous, tmp_path):
    home, book = home_of(tmp_path, "pc")
    old = run_previous(previous, WRITE_OLD % OLD_REPORTS, home)
    fsr_store.ExcelStore(book).write_report(
        with_shipment_line("FSR-NEW-202611-0003"), False)
    from openpyxl import load_workbook
    headers = [c.value for c in load_workbook(book)["Item List"][1]]
    assert headers == storage.ITEM_SHEET_HEADERS
    assert headers[-2:] == ["Packing List No.", "Origin Line"]
    now = {r["control_no"]: r for r in
           json.loads(json.dumps(fsr_store.ExcelStore(book).read_all_reports(),
                                 default=str))}
    for before in old:                      # every old report, unchanged
        assert now[before["control_no"]] == before
    rows = now["FSR-NEW-202611-0003"]["item_lists"][0]["rows"]
    assert [(r["Packing List No."], r["Origin Line"], r["Findings"])
            for r in rows] == [
        ("NOR111126-001 & 002", "FSR-ORG-202611-0001/1/1",
         "Good Order and Complete"),
        ("NOR111126-003", "FSR-ORG-202611-0001/1/2", "1 crate dented")]


def test_the_previous_version_refuses_a_workbook_saved_by_this_one(
        previous, tmp_path):
    """The caveat you accepted: going back to the previous installer needs a
    backup for a WORKBOOK this version saved (not for the database)."""
    home, book = home_of(tmp_path, "pc")
    run_previous(previous, WRITE_OLD % OLD_REPORTS[:1], home)
    fsr_store.ExcelStore(book).write_report(
        with_shipment_line("FSR-NEW-202611-0003"), False)
    code = ("import fsr_storage\ntry:\n"
            "    fsr_storage.read_all_reports(Path(home) / 'excel' / "
            "'Field_Survey_Reports.xlsx')\n    print(json.dumps('read'))\n"
            "except ValueError as error:\n    print(json.dumps(str(error)))\n")
    assert "different layout" in run_previous(previous, code, home)


# ---------- the reports database (what the installed program uses) ----------

def test_a_database_of_the_previous_version_reads_the_same_and_back(
        previous, tmp_path, monkeypatch):
    home, book = home_of(tmp_path, "pc")
    databases = tmp_path / "databases"
    databases.mkdir()
    env = {"FSR_DATABASE_DIR": str(databases)}
    run_previous(previous, WRITE_OLD % OLD_REPORTS + (
        "import fsr_sqlite_migrate\n"
        "print(json.dumps(fsr_sqlite_migrate.migrate(book).status))\n"), home,
        **env)
    monkeypatch.setenv("FSR_DATABASE_DIR", str(databases))
    old = run_previous(previous, READ_OLD, home, **env)
    assert old["kind"] == "sqlite"
    store = fsr_store.open_store(book)
    assert store.kind == "sqlite"
    assert json.loads(json.dumps(store.read_all_reports(), default=str)) == \
        old["reports"]
    # this version saves a report with the new fields into that database
    store.write_report(with_shipment_line("FSR-NEW-202611-0003"), False)
    rows = fsr_store.open_store(book).read_report(
        "FSR-NEW-202611-0003")["item_lists"][0]["rows"]
    assert rows[1]["Packing List No."] == "NOR111126-003"
    # the way back: the previous version still reads EVERY report of it
    back = run_previous(previous, READ_OLD, home, **env)
    by_control = {r["control_no"]: r for r in back["reports"]}
    for before in old["reports"]:
        assert by_control[before["control_no"]] == before
    new = by_control["FSR-NEW-202611-0003"]["item_lists"][0]["rows"]
    assert [(r["Description of Goods"], r["Findings"]) for r in new] == [
        ("TEST valve", "Good Order and Complete"),
        ("TEST seat", "1 crate dented")]
    assert all("Packing List No." not in r for r in new)   # not known there


# ---------- the PO-linked Withdrawal workbook keeps its layout ----------

def test_po_linked_withdrawals_keep_their_columns(tmp_path):
    main = tmp_path / "Field_Survey_Reports.xlsx"
    book = tmp_path / fsr_paths.WITHDRAWAL_WORKBOOK_NAME
    data = linked_report(tmp_path, picks=[("4500001", "1"), ("4500001", "3")],
                         quantities=["40", "2.5"])
    data["item_lists"][0]["rows"][0]["Findings"] = "LEY111126-003"
    wd.write_withdrawal_report(book, data, False, main)
    from openpyxl import load_workbook
    headers = [c.value for c in load_workbook(book)[wd.LINE_SHEET][1]]
    assert headers == wd.LINE_HEADERS
    assert "Packing List No." not in headers and "Origin Line" not in headers
    rows = wd.read_report(book, data["control_no"])["item_lists"][0]["rows"]
    # the Withdrawal workbook's own columns are read where they always were
    assert [(r[wd.LINE_NO_HEADER], r[wd.RECEIVED_HEADER], r["Quantity"])
            for r in rows] == [("1", "100", "40"), ("3", "12.5", "2.5")]
    assert rows[0][wd.LINE_ID_HEADER].startswith(data["control_no"])
    assert all("Packing List No." not in r and "Origin Line" not in r
               for r in rows)


# ---------- the Owner's import sees nothing changed ----------

def test_fingerprints_and_changes_ignore_empty_new_fields():
    import fsr_import
    value = invented("FSR-OLD-202611-0001")
    padded = json.loads(json.dumps(value))
    for row in padded["item_lists"][0]["rows"]:
        row.update({"Packing List No.": "", "Origin Line": " "})
    assert fsr_import.report_fingerprint(padded) == \
        fsr_import.report_fingerprint(value)
    assert fsr_import.report_changes(value, padded) == []
    filled = with_shipment_line("FSR-OLD-202611-0001")
    assert fsr_import.report_fingerprint(filled) != \
        fsr_import.report_fingerprint(value)
