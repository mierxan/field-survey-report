"""Measure save, open and import with invented workbooks of a given size.

Figures for docs/PERFORMANCE_BASELINE.md. Drives the REAL program (the
same harness as the GUI tests) on COPIES in a scratch folder:

  python tools/measure_performance.py --code <folder with the code>
         --work <scratch folder> --sizes 300 1000 3000
         [--real <copy of a real workbook>] [--mysql] [--sqlite]
         --out results.json

* --code: the program to measure. For "before" figures this is a git
  worktree of the commit before any change, so later edits cannot creep
  into the baseline.
* Invented reports only (Control #s FSR-ZZP-...). --real takes a COPY of
  a real workbook; the caller deletes that copy afterwards.
* --mysql: against field_survey_test only, through tests/real_mysql.py
  (which refuses any other database). Rows FSR-ZZP-... are removed at the
  end. Without --mysql, MySQL is off.
* --sqlite (Phase 5): the program moves the workbook into its database at
  the start, as it does on a PC, and works from there; the Excel export is
  written in the background (waited for before the next run, and counted
  in "until_mysql_done").

For every operation: seconds (median of the runs), workbook loads and
workbook writes by file, MySQL connections and the seconds spent opening
them.
"""
import argparse
import importlib.util
import inspect
import json
import shutil
import statistics
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # this project (MySQL login)


# ---------------------------------------------------------------------
# counting workbook loads / writes and MySQL connections
# ---------------------------------------------------------------------

class Counter:
    def __init__(self):
        self.reset()

    def reset(self):
        self.loads, self.writes = {}, {}
        self.connections, self.connect_seconds = 0, 0.0

    @staticmethod
    def kind(name):
        name = Path(str(name)).name
        for word, label in (("Withdrawal_Reports", "withdrawal workbook"),
                            ("Field_Survey_Reports", "main workbook"),
                            ("PO_Master", "PO_Master"),
                            ("Withdrawn_Item", "Withdrawn_Item")):
            if name.startswith(word):
                return label
        return "forms and templates"

    def snapshot(self):
        return {"loads": dict(self.loads), "writes": dict(self.writes),
                "mysql_connections": self.connections,
                "mysql_connect_seconds": round(self.connect_seconds, 3)}


COUNT = Counter()


def install_counters():
    from openpyxl.reader import excel
    from openpyxl.workbook import workbook

    real_read = excel.ExcelReader.read
    real_save = workbook.Workbook.save

    def read(self, *args, **kwargs):
        name = getattr(self.archive, "filename", "?")
        key = Counter.kind(name)
        COUNT.loads[key] = COUNT.loads.get(key, 0) + 1
        return real_read(self, *args, **kwargs)

    def save(self, filename, *args, **kwargs):
        key = Counter.kind(filename)
        COUNT.writes[key] = COUNT.writes.get(key, 0) + 1
        return real_save(self, filename, *args, **kwargs)

    excel.ExcelReader.read = read
    workbook.Workbook.save = save


# ---------------------------------------------------------------------
# invented data
# ---------------------------------------------------------------------

def invented_report(storage, control, number, day, activity="Receiving"):
    rows = []
    for line in range(1, 6):
        row = {h: "" for h in storage.ITEM_LINE_HEADERS}
        row.update({
            "Description of Goods": f"Spare part {number}-{line}, steel",
            "PO Number": f"45000{number % 900:03d}",
            "Packaging": "Crate", "Quantity": str(line * 2), "UOM": "PCS",
            "Dimensions": "120x80x60", "Weights": f"{line * 11}.5",
            "Cargo ID": f"C-{number}-{line}",
        })
        if activity == "Receiving":
            row["Receiving Ref"] = f"RCV-{control}-1-{line:02d}"
        rows.append(row)
    text = day.strftime("%d-%b-%Y")
    goods = storage.empty_goods_types()
    goods["new"] = True
    return {
        "control_no": control, "cargo_condition": "Good Order",
        "goods_types": goods, "incident_reports": [], "item_form": "Default",
        "other_item_forms": {},
        "general_information": {
            "so_number": f"SO-{number:06d}", "inspection_date": text,
            "consignee": "Invented Consignee Inc.",
            "supplier": f"Invented Supplier {number % 40}",
            "brokerage": "Invented Brokerage", "hauler": "Invented Hauler",
            "location": f"Warehouse {number % 7}", "destination": "Site A",
            "country_of_origin": "Japan"},
        "inspection_schedule": {
            "activity": activity, "commenced_date": text,
            "commenced_time": "0800H", "completion_date": text,
            "completion_time": "1100H"},
        "transport_details": {k: "" for _, k, *_ in storage.TRANSPORT_FIELDS},
        "documents_used": {k: f"DOC-{number}" for _, k in
                           storage.DOCUMENT_FIELDS},
        "declared_goods": [
            {"description": "Machinery parts", "quantity": "5",
             "packaging": "Crates"},
            {"description": "Tools", "quantity": "2", "packaging": "Boxes"}],
        "other_important_remarks": ["Seal intact", "Counted with consignee"],
        "item_lists": [{"name": "Item List 1", "rows": rows}],
        "findings_and_remarks": [],
    }


def control_of(number, year="2099"):
    month = (number - 1) // 9999 % 12 + 1
    return f"FSR-ZZP-{year}{month:02d}-{(number - 1) % 9999 + 1:04d}"


def build_workbook(storage, path, count):
    """`count` invented reports, written the way write_report_to_excel()
    writes them, but in one pass and one save (building 3,000 reports one
    save at a time would take hours)."""
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    sheets = {name: storage.get_or_create_sheet(wb, name, headers)
              for name, (_, headers) in storage.EXCEL_SHEETS.items()}
    price_formats = {4 + storage.ITEM_HEADERS.index(h): "#,##0.00"
                     for h in storage.MONEY_ITEM_HEADERS}
    start = date(2026, 1, 5)
    saved = datetime(2026, 11, 1, 8, 0)
    for number in range(1, count + 1):
        control = control_of(number)
        activity = "Receiving" if number % 3 else "Withdrawal"
        data = invented_report(storage, control, number,
                               start + timedelta(days=number % 300), activity)
        storage.append_row(sheets["Reports"], storage.report_row_values(
            data, control, saved + timedelta(minutes=number)),
            storage.REPORT_FORMATS)
        for row in data["declared_goods"]:
            storage.append_row(sheets["Declared Goods"], [
                control, row["description"],
                storage.to_number(row["quantity"]), row["packaging"]])
        for _list_no, item_list in enumerate(data["item_lists"], start=1):
            for line_no, row in enumerate(item_list["rows"], start=1):
                values = [control, item_list["name"], line_no]
                for header in storage.ITEM_LINE_HEADERS:
                    value = row.get(header, "")
                    values.append(storage.to_number(value)
                                  if header in storage.NUMERIC_ITEM_HEADERS
                                  else storage.text_or_none(value))
                storage.append_row(sheets["Item List"], values, price_formats)
        for line_no, remark in enumerate(data["other_important_remarks"], 1):
            storage.append_row(sheets["Remarks"], [
                control, "Other Important Remarks", line_no, remark])
    for name, (table, headers) in storage.EXCEL_SHEETS.items():
        storage.finalize_sheet(sheets[name], table, headers)
    wb.save(path)


def master_file(storage, path, count, first=1):
    reports = []
    for number in range(first, first + count):
        control = control_of(number, year="2098")
        report = invented_report(storage, control, 50_000 + number,
                                 date(2026, 10, 1), "Receiving")
        report["last_saved"] = "01-Nov-2026 10:00"
        for row in report["item_lists"][0]["rows"]:
            row["Receiving Ref"] = ""
        reports.append(report)
    path.write_text(json.dumps({
        "format": "fsr-master-data", "version": 1,
        "device_id": "perf-phone", "inspector": "Invented Inspector",
        "reports": reports}), encoding="utf-8")


# ---------------------------------------------------------------------
# MySQL: field_survey_test only
# ---------------------------------------------------------------------

def load_real_mysql():
    spec = importlib.util.spec_from_file_location(
        "real_mysql", HERE / "tests" / "real_mysql.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def perf_db(real_mysql):
    import db_mysql

    class PerfDB(real_mysql.RealTestDB):
        """field_survey_test with every db_mysql function the program
        calls; connections are counted."""

        def connect(self, config=None):
            started = time.perf_counter()
            try:
                return super().connect(config)
            finally:
                COUNT.connections += 1
                COUNT.connect_seconds += time.perf_counter() - started

        def is_enabled(self):
            return True

        def test_connection(self, config=None):
            return self.check_connection(config)[:2]

        def check_connection(self, config=None):
            try:
                conn = self.connect()
            except Exception as error:
                return False, str(error), db_mysql.is_unreachable(error)
            conn.close()
            return True, "Connected.", False

        def __getattr__(self, name):
            func = getattr(db_mysql, name)
            if not callable(func):
                return func
            try:
                params = list(inspect.signature(func).parameters)
            except (TypeError, ValueError):
                return func
            if "connection" not in params:
                return func
            at = params.index("connection")

            def call(*args, **kwargs):
                if len(args) > at or kwargs.get("connection") is not None:
                    return func(*args, **kwargs)
                conn = self.connect()
                try:
                    kwargs["connection"] = conn
                    return func(*args, **kwargs)
                finally:
                    conn.close()
            return call

    database = real_mysql.open_database()
    return PerfDB(database._config)


def remove_invented_rows(database):
    for table in ("incident_reports", "remarks", "item_lines",
                  "declared_goods", "reports"):
        database.run(f"DELETE FROM {table} WHERE control_no LIKE %s",
                     ("FSR-ZZP-%",))


# ---------------------------------------------------------------------
# driving the program
# ---------------------------------------------------------------------

def wait_until_quiet(g, limit=600):
    """After an operation: the program's background work (if this version
    has any) is finished. Returns the seconds waited."""
    started = time.perf_counter()
    live = g["save_report"].__globals__
    while time.perf_counter() - started < limit:
        g["window"].update()
        busy = False
        for name in ("mysql_sender", "lists_sender", "export_sender"):
            sender = live.get(name)
            if sender is not None and not sender.idle():
                busy = True
        if (live.get("import_state") or {}).get("running"):
            busy = True
        if (live.get("db_move_state") or {}).get("running"):
            busy = True
        shell = live.get("app_shell")
        if shell is not None and getattr(shell.service, "loading", False):
            busy = True                 # the dashboards reading the workbook
        if not busy:
            break
        time.sleep(0.02)
    return time.perf_counter() - started


def measure(g, label, action, runs, results, prepare=None, after=None):
    times, quiet, counts = [], [], []
    for _ in range(runs):
        wait_until_quiet(g)             # nothing of the last step still runs
        if prepare is not None:
            prepare()
        wait_until_quiet(g)
        COUNT.reset()
        started = time.perf_counter()
        action()
        returned = time.perf_counter() - started
        waited = wait_until_quiet(g)
        if after is not None:
            after()
        times.append(returned)
        quiet.append(returned + waited)
        counts.append(COUNT.snapshot())
    results[label] = {
        "seconds": round(statistics.median(times), 3),
        "until_mysql_done": round(statistics.median(quiet), 3),
        "runs": [round(t, 3) for t in times],
        **counts[len(counts) // 2],
    }
    print(f"  {label}: {results[label]['seconds']} s "
          f"(done {results[label]['until_mysql_done']} s) "
          f"loads {results[label]['loads']} writes {results[label]['writes']} "
          f"mysql {results[label]['mysql_connections']}", flush=True)


def run_size(code, work, name, source_book, mysql, real_mysql, runs,
             imports, saves=True, sqlite=False):
    sys.path.insert(0, str(code / "tests"))
    import gui_harness as h
    import fsr_storage as storage

    home = work / (f"home_{name}_{'mysql' if mysql else 'off'}"
                   + ("_sqlite" if sqlite else ""))
    if home.exists():
        shutil.rmtree(home)
    (home / "excel").mkdir(parents=True)
    book = home / "excel" / "Field_Survey_Reports.xlsx"
    shutil.copy2(source_book, book)

    started = time.perf_counter()
    g, answers = h.start_app(home, {"FSR_NO_SQLITE": "0" if sqlite
                                    else "1"})
    live = g["save_report"].__globals__
    results = {}
    if sqlite:
        wait_until_quiet(g, limit=3600)     # the move into the database
        results["start incl. the move into the database"] = {
            "seconds": round(time.perf_counter() - started, 3)}
        print("  moved:", [m for k, t, m in answers.calls
                           if t == "Reports Database"], flush=True)
        assert live["data_store"]().kind == "sqlite"
    for name in ("mysql_sender", "lists_sender", "export_sender"):
        if name in live:                            # works in the
            live[name].inline = False               # background
    storage.set_control_initials("ZZP")
    live["set_control_initials"]("ZZP")
    database = None
    if mysql:
        database = perf_db(real_mysql)
        live["db_mysql"] = database
        if "check_mysql_status" in live:
            pass
        live["mysql_numbers"]["values"] = []
    try:
        controls = [row[0] for row in storage.list_saved_reports(book)]
        target = sorted(controls)[len(controls) // 2]
        if saves:
            measure_saves(g, target, runs, results)
        if not mysql:
            run_imports(g, answers, live, storage, work, home, book, name,
                        imports, runs, results)
    finally:
        h.stop_app(g, answers)
        if database is not None:
            remove_invented_rows(database)
        sys.path.remove(str(code / "tests"))
    return results


def measure_saves(g, target, runs, results):
    measure(g, "open a saved report",
            lambda: g["load_report_into_form"](target, "excel"),
            runs, results)
    counter = {"n": 0}

    def edit_and_save():
        counter["n"] += 1
        g["set_entry"](g["SO_number_entry"], f"EDITED {counter['n']}")
        g["schedule_entries"]["activity"].set("Receiving")
        assert g["save_report"]() is True

    measure(g, "save (edit of a saved report)", edit_and_save, runs,
            results,
            prepare=lambda: g["load_report_into_form"](target, "excel"))

    def new_and_save():
        g["new_report"](confirm=False)
        g["choose_condition"]("Good Order")
        g["set_entry"](g["SO_number_entry"], "SO-NEW-PERF")
        g["schedule_entries"]["activity"].set("Receiving")
        g["location_combobox"].set("Warehouse 1")
        section = g["item_frames"][0]
        cols = g["ITEM_FORM_HEADERS"]
        for header, value in {"Description of Goods": "Valve",
                              "Quantity": "3", "UOM": "PCS",
                              "Packaging": "Box"}.items():
            g["set_entry"](section.rows[0][cols.index(header)], value)
        assert g["save_report"]() is True

    measure(g, "save (new report)", new_and_save, runs, results)


def run_imports(g, answers, live, storage, work, home, book, name, imports,
                runs, results):
    """Each import starts from the same workbook (`pristine`). What the
    program says afterwards is printed, so a failed import is seen."""
    pristine = work / f"pristine_{name}.xlsx"
    shutil.copy2(book, pristine)

    def reset():
        shutil.copy2(pristine, book)
        for pattern in ("*_imported_reports.json", "*_pending_saves.json",
                        "*_mysql_ledger.json", "*_import_review.json",
                        "*_import_history.jsonl", "*_handovers.json"):
            for found in (home / "json").glob(pattern):
                found.unlink()
        for found in (home / "excel").glob("*_before_import_*"):
            found.unlink()
        answers.calls.clear()

    def told():
        for kind, title, message in answers.calls:
            if kind != "askyesno":
                print(f"    the program said ({title}):",
                      " | ".join(str(message).splitlines()[:3]), flush=True)
        answers.calls.clear()

    for count in imports:
        file = work / f"master_{count}.json"
        master_file(storage, file, count)

        def do_import(file=file):
            fd = live["filedialog"]
            saved = fd.askopenfilename
            fd.askopenfilename = lambda **kw: str(file)
            try:
                live["import_master_data_file"]()
            finally:
                fd.askopenfilename = saved

        measure(g, f"import {count} report(s)", do_import,
                1 if count >= 50 else runs, results, prepare=reset,
                after=told)
    shutil.copy2(pristine, book)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--sizes", nargs="*", type=int, default=[300])
    parser.add_argument("--real", type=Path)
    parser.add_argument("--mysql", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--imports", nargs="*", type=int,
                        default=[1, 50, 200])
    parser.add_argument("--no-saves", action="store_true")
    parser.add_argument("--sqlite", action="store_true")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    code = args.code.resolve()
    sys.path.insert(0, str(code))
    import os
    os.environ["FSR_SECRET_STORE"] = "memory"     # never the real store
    install_counters()
    import fsr_storage as storage
    real_mysql = load_real_mysql() if args.mysql else None

    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    out = json.loads(args.out.read_text(encoding="utf-8")) \
        if args.out.exists() else {}
    books = [(str(n), n) for n in args.sizes]
    if args.real:
        books.append(("real", None))
    for name, size in books:
        if size is None:
            source = args.real
        else:
            source = work / f"invented_{size}.xlsx"
            if not source.exists():
                print(f"building {size} reports ...", flush=True)
                build_workbook(storage, source, size)
        print(f"{name} reports, MySQL {'on' if args.mysql else 'off'}",
              flush=True)
        key = (f"{name}|{'mysql' if args.mysql else 'off'}"
               + ("|sqlite" if args.sqlite else ""))
        found = out.get(key, {})
        found.update(run_size(code, work, name, source, args.mysql,
                              real_mysql, args.runs, args.imports,
                              saves=not args.no_saves, sqlite=args.sqlite))
        out[key] = found
        out[key]["workbook_kb"] = round(source.stat().st_size / 1024)
        args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
