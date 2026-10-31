"""Excel / PDF reports: every type is produced, and the exported figures are
the same as the analytics (read back from the files)."""

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from warehouse import analytics as an
from warehouse import exports as ex
from warehouse import sample_data as sd
from warehouse import tables as tb
from warehouse.periods import month_period
from conftest import ANCHOR


@pytest.fixture(scope="module")
def outdir(tmp_path_factory):
    return tmp_path_factory.mktemp("exports")


@pytest.mark.parametrize("key,title", ex.REPORT_TYPES)
def test_every_report_type_exports(sample, outdir, key, title):
    snap = sample["snapshot"]
    filters = an.Filters(period=month_period(ANCHOR))
    item = snap.inventory.item(sd.WH_A, "TEST-PLATE-E01")
    doc = ex.build_report(key, snap, filters, item=item)
    assert doc.title == title
    xlsx = ex.export(doc, outdir / f"{key}.xlsx")
    pdf = ex.export(doc, outdir / f"{key}.pdf")
    wb = load_workbook(xlsx)
    summary = wb["Summary"]
    assert summary["A1"].value == title
    labels = [summary.cell(row=r, column=1).value for r in range(2, 6)]
    assert {"Reporting Period", "Date Generated", "Selected Filters"} <= \
        set(labels)
    reader = PdfReader(str(pdf))
    last = reader.pages[-1].extract_text()
    assert f"Page {len(reader.pages)} of {len(reader.pages)}" in last
    assert title in reader.pages[0].extract_text()


def sheet_rows(ws, header):
    rows, start = [], None
    for r in ws.iter_rows(values_only=True):
        if start is None:
            if r and r[0] == header:
                start = True
            continue
        if r[0] in (None, "TOTAL"):
            break
        rows.append(r)
    return rows


def test_monthly_receiving_export_matches_summary(sample, outdir):
    snap = sample["snapshot"]
    summary = an.monthly_summary(snap.transactions, "Receiving", ANCHOR)
    doc = ex.build_report("monthly_receiving", snap,
                          an.Filters(period=month_period(ANCHOR)), ANCHOR)
    path = ex.export(doc, outdir / "check_monthly.xlsx")
    wb = load_workbook(path)
    lines = sheet_rows(wb["Receiving Transaction Lines"], "Date")
    assert len(lines) == summary.line_count
    qty_col = [c[0] for c in tb.LINE_COLUMNS].index("Quantity")
    unit_col = [c[0] for c in tb.LINE_COLUMNS].index("UOM")
    exported = {}
    for r in lines:
        if isinstance(r[qty_col], (int, float)):
            exported[r[unit_col]] = exported.get(r[unit_col], 0) + r[qty_col]
    assert exported == pytest.approx(summary.qty)
    warehouses = sheet_rows(wb["Warehouse Breakdown"], "Warehouse")
    assert sum(r[1] for r in warehouses) == summary.tx_count


def test_inventory_export_matches_ledger(sample, outdir):
    snap = sample["snapshot"]
    doc = ex.warehouse_inventory_report(snap)
    wb = load_workbook(ex.export(doc, outdir / "check_inventory.xlsx"))
    rows = sheet_rows(wb["Inventory Items"], "Cargo ID")
    assert len(rows) == len(snap.inventory.items)
    names = [c[0] for c in tb.INVENTORY_COLUMNS]
    by_ref = {r[names.index("Inventory Reference")]: r for r in rows}
    for item_ in snap.inventory.items:
        row = by_ref[f"{item_.warehouse} | {item_.identity}"]
        assert row[names.index("Remaining Qty")] == item_.remaining_qty
        assert row[names.index("Inventory Status")] == item_.status_detail


def test_totals_never_add_different_units():
    rows = [[None] * 11 + [5, "PCS"] + [None] * 4,
            [None] * 11 + [3, "SET"] + [None] * 4]
    totals = tb.column_totals(tb.LINE_COLUMNS, rows)
    assert totals[11] == "mixed units"
    same = tb.column_totals(tb.LINE_COLUMNS, [rows[0], rows[0]])
    assert same[11] == 10


def test_empty_report_exports(tmp_path):
    from warehouse import store
    snap = store.load_snapshot(tmp_path / "none.xlsx")
    for key in ("management", "remaining", "bad_order",
                "weekly_withdrawal"):
        doc = ex.build_report(key, snap, an.Filters(
            period=month_period(ANCHOR)))
        ex.export(doc, tmp_path / f"{key}.pdf")
        ex.export(doc, tmp_path / f"{key}.xlsx")


@pytest.mark.parametrize("kind", ["weekly", "monthly"])
@pytest.mark.parametrize("activity", ["Receiving", "Withdrawal"])
def test_summary_report_has_one_row_per_item_line(sample, outdir, kind,
                                                  activity):
    snap = sample["snapshot"]
    doc = ex.summary_report(snap, activity, kind, ANCHOR)
    section = doc.sections[0]
    assert [c[0] for c in section.columns][:3] == [
        "SO Number", "Date", "Activity"]
    assert [c[0] for c in section.columns][-2:] == [
        "Cargo Condition", "Findings / Remarks"]
    period = ex.SUMMARY_KINDS[kind][1](ANCHOR)
    summary = an.summarize(snap.transactions, activity, period)
    assert len(section.rows) == sum(max(t.line_count, 1) for t in
                                    an.filter_transactions(
                                        snap.transactions,
                                        an.Filters(period=period,
                                                   activity=activity)))
    assert len(section.rows) >= summary.line_count
    assert all(r[2] == activity and period.contains(r[1])
               for r in section.rows)
    location = [c[0] for c in section.columns].index("Location / Warehouse")
    assert {r[location] for r in section.rows} == {
        t.warehouse for t in an.filter_transactions(
            snap.transactions, an.Filters(period=period, activity=activity))}
    path = ex.export(doc, outdir / f"report_{kind}_{activity}.xlsx")
    ws = load_workbook(path)[section.title]
    assert len(sheet_rows(ws, "SO Number")) == len(section.rows)
