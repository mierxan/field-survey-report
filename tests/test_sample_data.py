"""The isolated sample data set: volume, isolation, and every scenario
(A-M) checked on the data as saved by the real storage code."""

from collections import defaultdict
from datetime import date

import pytest

import fsr_storage
from conftest import ANCHOR
from warehouse import analytics as an
from warehouse import inventory as inv
from warehouse import sample_data as sd
from warehouse import store

A, B = sd.WH_A, sd.WH_B


def item(sample, cargo, warehouse=A):
    found = sample["snapshot"].inventory.item(warehouse, cargo)
    assert found is not None, cargo
    return found


def test_volume_and_spread(sample):
    snap = sample["snapshot"]
    rec = [t for t in snap.transactions if t.activity == "Receiving"]
    wdr = [t for t in snap.transactions if t.activity == "Withdrawal"]
    assert len(rec) >= 50 and len(wdr) >= 30
    months = {(t.date.year, t.date.month) for t in snap.transactions}
    assert len(months) >= 3
    weeks = {t.date.isocalendar()[:2] for t in snap.transactions}
    assert len(weeks) >= 10
    assert len({t.warehouse for t in snap.transactions}) >= 2


def test_every_record_is_recognisable_test_data(sample):
    for tx in sample["snapshot"].transactions:
        assert tx.control_no.startswith(("TEST-REC-", "TEST-WDR-"))
        assert tx.so_number.startswith("TEST-SO-")
        assert tx.warehouse.startswith("TEST ")
        assert all(l.cargo_id.startswith("TEST-") or not l.cargo_id
                   for l in tx.lines)
        assert tx.supplier.startswith("Test ") or tx.activity == "Withdrawal"


@pytest.mark.parametrize("cargo,warehouse,received,withdrawn,remaining,status", [
    ("TEST-PUMP-A01", A, 20, 0, 20, inv.STATUS_IN_STOCK),          # A
    ("TEST-PIPE-B01", A, 100, 35, 65, inv.STATUS_PARTIAL),         # B
    ("TEST-MOTOR-C01", A, 50, 50, 0, inv.STATUS_FULL),             # C
    ("TEST-CHAN-D01", A, 100, 25, 75, inv.STATUS_PARTIAL),         # D
    ("TEST-PLATE-E01", A, 100, 45, 55, inv.STATUS_PARTIAL),        # E
    ("TEST-VALVE-001", A, 20, 5, 15, inv.STATUS_PARTIAL),          # G
    ("TEST-VALVE-002", A, 30, 0, 30, inv.STATUS_IN_STOCK),         # G
    ("TEST-XFMR-H01", A, 20, 25, -5, inv.STATUS_OVER),             # H
    ("TEST-COMP-K01", A, 30, 0, 30, inv.STATUS_IN_STOCK),          # K
    ("TEST-COMP-K01", B, 10, 5, 5, inv.STATUS_PARTIAL),            # K
    ("TEST-BFV-M01", B, 12, 0, 12, inv.STATUS_IN_STOCK),           # M dup
    ("TEST-BFV-M02", B, 12, 0, 12, inv.STATUS_IN_STOCK),           # M alike
    ("TEST-BFV-M03", B, 12, 0, 12, inv.STATUS_IN_STOCK),
])
def test_scenarios(sample, cargo, warehouse, received, withdrawn, remaining,
                   status):
    found = item(sample, cargo, warehouse)
    assert found.received_qty == received
    assert found.withdrawn_qty == withdrawn
    assert found.remaining_qty == remaining
    assert found.status == status
    assert found.unit == "PCS" or cargo == "TEST-COMP-K01"


def test_scenario_d_has_two_batches(sample):
    assert [b.quantity for b in item(sample, "TEST-CHAN-D01").batches] == \
        [40, 60]


def test_scenario_e_three_withdrawals(sample):
    assert sorted(w.quantity for w in
                  item(sample, "TEST-PLATE-E01").withdrawals) == [10, 15, 20]


def test_scenario_i_unmatched(sample):
    unmatched = {u.line.cargo_id: u for u in
                 sample["snapshot"].inventory.unmatched}
    assert "TEST-GHOST-999" in unmatched
    assert sample["snapshot"].inventory.item(A, "TEST-GHOST-999") is None
    assert "received at TEST Warehouse A" in unmatched["TEST-PLATE-E01"] \
        .message                                    # cross-warehouse
    assert "" in unmatched                          # no IDs at all


def test_scenario_j_missing_quantity(sample):
    for cargo, wh in (("TEST-SPARE-J01", A), ("TEST-GEAR-J02", B)):
        found = item(sample, cargo, wh)
        assert found.status == inv.STATUS_RECON
        assert found.remaining_qty is None
        assert any(i.kind == "missing_quantity" for i in found.issues)


def test_incompatible_units_flagged(sample):
    assert item(sample, "TEST-CABLE-U01").status == inv.STATUS_RECON
    assert item(sample, "TEST-BOLT-U02").withdrawn_qty == 0


def test_scenario_l_aging(sample):
    expected = {"TEST-AGE-003": (3, "0-7 Days"),
                "TEST-AGE-014": (14, "8-30 Days"),
                "TEST-AGE-045": (45, "31-60 Days"),
                "TEST-AGE-075": (75, "61-90 Days"),
                "TEST-AGE-100": (100, "More Than 90 Days")}
    rows = {r.item.cargo_id: (r.age_days, r.bucket)
            for r in sample["snapshot"].inventory.aging_rows
            if r.item.cargo_id in expected}
    assert rows == expected


def test_scenario_m_duplicate_flagged(sample):
    dups = [i for i in sample["snapshot"].inventory.issues
            if i.kind == "duplicate_receiving_ref"]
    assert len(dups) == 1 and dups[0].line.receiving_ref == "TEST-RR-DUP-01"


def test_scenario_f_bad_order(sample):
    snap = sample["snapshot"]
    bad = [t for t in snap.transactions if t.condition == "Bad Order"]
    expected_bad_rec = sum(1 for r in sample["spec"].receiving
                           if r.condition == "Bad Order")
    expected_bad_wdr = sum(1 for r in sample["spec"].withdrawals
                           if r.condition == "Bad Order")
    kpis = {k.name: k.value for k in an.bad_order_kpis(
        snap.transactions, an.Filters(), {})}
    assert kpis["Total Bad Order Reports"] == len(bad) == \
        expected_bad_rec + expected_bad_wdr
    assert kpis["Bad Order Receiving Transactions"] == expected_bad_rec
    assert kpis["Bad Order Withdrawal Transactions"] == expected_bad_wdr >= 1
    split = an.good_vs_bad(snap.transactions, an.Filters())
    assert split["Bad Order"] == len(bad)
    assert split["Good Order"] == len(snap.transactions) - len(bad)
    # Bad Order cargo stays in the inventory
    assert item(sample, "TEST-VALVE-F02", B).remaining_qty == 15
    # incident files were written by the real code
    assert all(t.incident_text for t in bad)


def test_filler_balances_match_an_independent_calculation(sample):
    """Recompute every filler balance from the generator's spec (plain
    arithmetic, no ledger code) and compare."""
    received, withdrawn, where = defaultdict(float), defaultdict(float), {}
    for spec in sample["spec"].receiving:
        if spec.scenario != "filler":
            continue
        for line in spec.lines:
            received[line.cargo_id] += line.quantity
            where[line.cargo_id] = spec.warehouse
    for spec in sample["spec"].withdrawals:
        if spec.scenario != "filler":
            continue
        for line in spec.lines:
            withdrawn[line.source_cargo_id or line.cargo_id] += line.quantity
    assert len(received) >= 30
    for cargo, qty in received.items():
        found = item(sample, cargo, where[cargo])
        assert found.remaining_qty == pytest.approx(qty - withdrawn[cargo]), \
            cargo


def test_generation_is_repeatable_without_duplicates(sample, tmp_path):
    before = len(fsr_storage.read_all_reports(sample["path"]))
    sd.generate(sample["folder"], anchor=ANCHOR)
    after = fsr_storage.read_all_reports(sample["path"])
    assert len(after) == before
    assert len({r["control_no"] for r in after}) == before


def test_refuses_folder_with_real_records(tmp_path):
    real = rec_report = fsr_storage
    path = tmp_path / "Field_Survey_Reports_DEMO.xlsx"
    from factories import rec
    real.write_report_to_excel(path, rec("FSR-2026-0001", date(2026, 1, 1),
                                         "X", 1), False)
    with pytest.raises(sd.UnsafeTargetError, match="real report"):
        sd.generate(tmp_path)
    assert [r["control_no"] for r in rec_report.read_all_reports(path)] == \
        ["FSR-2026-0001"]


def test_refuses_program_folder_and_unmarked_folder(tmp_path):
    with pytest.raises(sd.UnsafeTargetError):
        sd.mark_test_folder(sd.ROOT)
    with pytest.raises(sd.UnsafeTargetError, match="not marked"):
        sd.check_target(tmp_path / "x.xlsx")


def test_reset_removes_only_test_records(tmp_path):
    from factories import rec
    path, _ = sd.generate(tmp_path, anchor=ANCHOR)
    # someone typed their own report in Demo Mode
    fsr_storage.write_report_to_excel(path, rec("FSR-2026-0009",
                                                date(2026, 10, 1), "Q", 1),
                                      False)
    side = store.SideStore(path)
    side.add_decision("TEST-WDR-0010/1/1", "note", "u", note="test note")
    side.add_decision("FSR-2026-0009/1/1", "note", "u", note="keep me")
    result = sd.reset(tmp_path)
    left = fsr_storage.read_all_reports(path)
    assert [r["control_no"] for r in left] == ["FSR-2026-0009"]
    assert result["reports"] >= 80
    assert not list((tmp_path / "Incident Reports").glob("TEST-*"))
    assert [e["subject"] for e in store.SideStore(path).history()] == \
        ["FSR-2026-0009/1/1"]


def test_real_project_files_untouched():
    """The sample data never goes into the program folder's workbook."""
    assert not (sd.ROOT / "Field_Survey_Reports.xlsx").exists() or all(
        not r["control_no"].startswith("TEST-")
        for r in fsr_storage.read_all_reports(
            sd.ROOT / "Field_Survey_Reports.xlsx"))
