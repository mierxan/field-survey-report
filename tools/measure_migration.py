"""Time the move into the database (fsr_sqlite_migrate.migrate) - backup,
copying every row, the field-by-field comparison and the row-by-row check of
the export - and the export itself, on COPIES:

  python tools/measure_migration.py --work <scratch folder>
         --sizes 300 3000 6000 [--real <copy of a real workbook>]

Invented workbooks are built as tools/measure_performance.py builds them
(Control #s FSR-ZZP-...). --real takes a COPY; the caller deletes it
afterwards. Prints one line per workbook and writes nothing else.
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--sizes", nargs="*", type=int, default=[300])
    parser.add_argument("--real", type=Path)
    args = parser.parse_args()

    import fsr_paths
    import fsr_sqlite_export as export
    import fsr_sqlite_migrate as migrate
    import fsr_storage as storage
    import fsr_store
    from measure_performance import build_workbook

    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    # JSON files beside each workbook (not in the program's data folder)
    fsr_paths.configure_data_dirs(work / "_unused", work / "_unused" / "json",
                                  work / "_unused" / "excel")
    books = [(str(n), n) for n in args.sizes]
    if args.real:
        books.append(("real", None))
    for name, size in books:
        folder = work / f"migrate_{name}"
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir()
        book = folder / "Field_Survey_Reports.xlsx"
        if size is None:
            shutil.copy2(args.real, book)
            linked = args.real.with_name(fsr_paths.WITHDRAWAL_WORKBOOK_NAME)
            if linked.exists():
                shutil.copy2(linked, folder / linked.name)
        else:
            source = work / f"invented_{size}.xlsx"
            if not source.exists():
                print(f"building {size} reports ...", flush=True)
                build_workbook(storage, source, size)
            shutil.copy2(source, book)
        kb = round(book.stat().st_size / 1024)
        started = time.perf_counter()
        result = migrate.migrate(book)
        moved = time.perf_counter() - started
        line = f"{name}: {result.status} in {moved:.1f} s (workbook {kb} KB)"
        if result.status == "migrated":
            store = fsr_store.open_store(book)
            db_kb = round(store.db_path.stat().st_size / 1024)
            started = time.perf_counter()
            store.read_all_reports()
            read = time.perf_counter() - started
            started = time.perf_counter()
            export.write_export(store, force=True)
            written = time.perf_counter() - started
            line += (f"; database {db_kb} KB; all reports read in "
                     f"{read:.2f} s; export written in {written:.1f} s")
        else:
            line += "\n  " + result.message.replace("\n", "\n  ")
        print(line, flush=True)


if __name__ == "__main__":
    main()
