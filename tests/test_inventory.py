"""Inventory calculation: each scenario on small hand-made records.

Expected values are worked out by hand in the test, not by the ledger."""

from datetime import date

import pytest

from factories import ledger, rec, report, wdr
from warehouse import inventory as inv

D = date(2026, 10, 1)


def only(ledger_, cargo, warehouse="WH-1"):
    item = ledger_.item(warehouse, cargo)
    assert item is not None, f"{cargo} not in the ledger"
    return item


def test_no_withdrawal_is_in_stock():
    item = only(ledger([rec("R1", D, "C-A", 20)]), "C-A")
    assert (item.received_qty, item.withdrawn_qty, item.remaining_qty) == \
        (20, 0, 20)
    assert item.status == inv.STATUS_IN_STOCK
    assert item.no_recorded_withdrawal
    assert "No Recorded Withdrawal" in item.status_detail


def test_partial_withdrawal():
    item = only(ledger([rec("R1", D, "C-B", 100),
                        wdr("W1", date(2026, 10, 5), "C-B", 35)]), "C-B")
    assert item.remaining_qty == 65
    assert item.status == inv.STATUS_PARTIAL


def test_full_withdrawal():
    item = only(ledger([rec("R1", D, "C-C", 50),
                        wdr("W1", date(2026, 10, 3), "C-C", 30),
                        wdr("W2", date(2026, 10, 4), "C-C", 20)]), "C-C")
    assert item.remaining_qty == 0
    assert item.status == inv.STATUS_FULL


def test_multiple_receiving_transactions():
    item = only(ledger([rec("R1", D, "C-D", 40),
                        rec("R2", date(2026, 10, 9), "C-D", 60),
                        wdr("W1", date(2026, 10, 10), "C-D", 25)]), "C-D")
    assert item.received_qty == 100
    assert len(item.batches) == 2
    assert item.remaining_qty == 75


def test_multiple_withdrawals():
    reports = [rec("R1", D, "C-E", 100)] + [
        wdr(f"W{i}", date(2026, 10, 2 + i), "C-E", q)
        for i, q in enumerate((20, 15, 10), start=1)]
    item = only(ledger(reports), "C-E")
    assert item.withdrawn_qty == 45
    assert item.remaining_qty == 55
    assert item.last_withdrawal == date(2026, 10, 5)


def test_identical_descriptions_different_ids_stay_apart():
    led = ledger([
        rec("R1", D, "VALVE-001", 20, desc="Gate Valve 6in"),
        rec("R2", D, "VALVE-002", 30, desc="Gate Valve 6in"),
        wdr("W1", date(2026, 10, 2), "VALVE-001", 5, desc="Gate Valve 6in")])
    assert only(led, "VALVE-001").remaining_qty == 15
    assert only(led, "VALVE-002").remaining_qty == 30


def test_over_withdrawal_is_flagged_and_not_zeroed():
    led = ledger([rec("R1", D, "C-H", 20),
                  wdr("W1", date(2026, 10, 2), "C-H", 25)])
    item = only(led, "C-H")
    assert item.remaining_qty == -5          # never forced to zero
    assert item.status == inv.STATUS_OVER
    assert any(i.kind == "over_withdrawal" for i in led.open_issues())


def test_unmatched_withdrawal_is_not_assigned_anywhere():
    led = ledger([rec("R1", D, "C-REAL", 10, desc="Pump"),
                  wdr("W1", date(2026, 10, 2), "C-GHOST", 3, desc="Pump")])
    assert only(led, "C-REAL").withdrawn_qty == 0
    assert len(led.unmatched) == 1
    assert "not found" in led.unmatched[0].message


def test_withdrawal_without_ids_never_matched_by_description():
    led = ledger([rec("R1", D, "C-1", 10, desc="Gate Valve"),
                  wdr("W1", date(2026, 10, 2), "", 3, desc="Gate Valve")])
    assert only(led, "C-1").withdrawn_qty == 0
    assert led.unmatched and "descriptions are never used" in \
        led.unmatched[0].message


def test_missing_quantity_blocks_the_balance():
    led = ledger([rec("R1", D, "C-J", None)])
    item = only(led, "C-J")
    assert item.remaining_qty is None
    assert item.status == inv.STATUS_RECON
    assert any(i.kind == "missing_quantity" for i in item.issues)


def test_missing_withdrawal_quantity_blocks_the_balance():
    led = ledger([rec("R1", D, "C-J2", 8),
                  wdr("W1", date(2026, 10, 2), "C-J2", None)])
    item = only(led, "C-J2")
    assert item.status == inv.STATUS_RECON and item.remaining_qty is None
    assert len(item.withdrawals) == 1       # kept for review


def test_warehouses_are_separate_and_transfers_not_assumed():
    led = ledger([rec("R1", D, "C-K", 30, warehouse="WH-A"),
                  rec("R2", D, "C-K", 10, warehouse="WH-B"),
                  wdr("W1", date(2026, 10, 2), "C-K", 5, warehouse="WH-B"),
                  rec("R3", D, "C-X", 7, warehouse="WH-A"),
                  wdr("W2", date(2026, 10, 3), "C-X", 2, warehouse="WH-B")])
    assert only(led, "C-K", "WH-A").remaining_qty == 30
    assert only(led, "C-K", "WH-B").remaining_qty == 5
    assert only(led, "C-X", "WH-A").withdrawn_qty == 0
    assert "received at WH-A" in led.unmatched[0].message


def test_incompatible_units_received():
    led = ledger([rec("R1", D, "CABLE", 100, unit="m"),
                  rec("R2", D, "CABLE", 2, unit="roll")])
    item = only(led, "CABLE")
    assert item.status == inv.STATUS_RECON and item.remaining_qty is None
    assert any(i.kind == "mixed_units" for i in item.issues)


def test_incompatible_withdrawal_unit_is_not_counted():
    led = ledger([rec("R1", D, "BOLT", 500, unit="pcs"),
                  wdr("W1", date(2026, 10, 2), "BOLT", 5, unit="box")])
    item = only(led, "BOLT")
    assert item.withdrawn_qty == 0
    assert item.status == inv.STATUS_RECON
    assert any(i.kind == "unit_mismatch" for i in item.issues)


def test_unit_aliases_are_compatible():
    led = ledger([rec("R1", D, "P", 10, unit="pcs"),
                  wdr("W1", date(2026, 10, 2), "P", 4, unit="Pieces")])
    assert only(led, "P").remaining_qty == 6


def test_duplicate_receiving_ref_is_not_double_counted():
    led = ledger([rec("R1", D, "M1", 12, ref="RR-DUP"),
                  rec("R2", D, "M1", 12, ref="RR-DUP")])
    assert only(led, "M1").received_qty == 12
    assert [i.kind for i in led.open_issues()] == ["duplicate_receiving_ref"]


def test_same_description_date_quantity_is_not_a_duplicate():
    led = ledger([rec("R1", D, "M2", 12, desc="Valve"),
                  rec("R2", D, "M3", 12, desc="Valve"),
                  rec("R3", D, "M2", 12, desc="Valve")])
    assert only(led, "M2").received_qty == 24       # two separate batches
    assert only(led, "M3").received_qty == 12
    assert not led.open_issues()


def test_withdrawal_by_receiving_ref_and_fifo_aging():
    as_of = date(2026, 10, 29)
    led = ledger([rec("R1", date(2026, 8, 1), "CR", 10),
                  rec("R2", date(2026, 10, 1), "CR", 10),
                  wdr("W1", date(2026, 10, 5), "", 4, ref="RCV-R2-1-01"),
                  wdr("W2", date(2026, 10, 6), "CR", 10)], as_of=as_of)
    item = only(led, "CR")
    assert item.remaining_qty == 6
    batches = {b.ref: b.remaining for b in item.batches}
    # W1 comes off batch R2; W2 (no batch named) off the oldest (R1) first
    assert batches == {"RCV-R1-1-01": 0, "RCV-R2-1-01": 6}
    assert [r.age_days for r in led.aging_rows] == [28]
    assert item.age_days == 28


@pytest.mark.parametrize("age,bucket", [
    (0, "0-7 Days"), (3, "0-7 Days"), (7, "0-7 Days"), (8, "8-30 Days"),
    (14, "8-30 Days"), (30, "8-30 Days"), (45, "31-60 Days"),
    (75, "61-90 Days"), (90, "61-90 Days"), (91, "More Than 90 Days"),
    (120, "More Than 90 Days")])
def test_aging_buckets(age, bucket):
    assert inv.aging_bucket(age) == bucket


def test_configurable_aging_thresholds():
    assert inv.bucket_labels((15, 45)) == ["0-15 Days", "16-45 Days",
                                           "More Than 45 Days"]
    assert inv.aging_bucket(20, (15, 45)) == "16-45 Days"


def test_invalid_dates_not_used_for_aging():
    led = ledger([report("R1", "Receiving", "not a date", "WH-1",
                         [{"cargo": "ND", "qty": 5, "unit": "pcs"}])])
    item = only(led, "ND")
    assert item.remaining_qty == 5            # balance still known
    assert item.age_days is None and not led.aging_rows
    assert any(i.kind == "missing_date" for i in led.issues)


def test_confirmed_link_resolves_unmatched_and_original_untouched():
    reports = [rec("R1", D, "C-1", 10),
               wdr("W1", date(2026, 10, 2), "C-TYPO", 4)]
    led = ledger(reports)
    assert len(led.unmatched) == 1
    decision = inv.LineDecision(inv.CONFIRMED, {
        "warehouse": "WH-1", "cargo_id": "C-1", "receiving_ref": ""})
    linked = ledger(reports, decisions={"W1/1/1": decision})
    assert only(linked, "C-1").remaining_qty == 6
    assert not linked.unmatched
    assert reports[1]["item_lists"][0]["rows"][0]["Cargo ID"] == "C-TYPO"


def test_proposed_link_does_not_change_balance():
    reports = [rec("R1", D, "C-1", 10),
               wdr("W1", date(2026, 10, 2), "C-TYPO", 4)]
    proposal = inv.LineDecision(inv.PROPOSED, {
        "warehouse": "WH-1", "cargo_id": "C-1", "receiving_ref": ""})
    led = ledger(reports, decisions={"W1/1/1": proposal})
    assert only(led, "C-1").remaining_qty == 10
    assert led.unmatched[0].state == inv.PROPOSED and \
        led.unmatched[0].is_open


def test_excluded_withdrawal_is_resolved_and_not_counted():
    reports = [rec("R1", D, "C-1", 10),
               wdr("W1", date(2026, 10, 2), "C-GHOST", 4)]
    led = ledger(reports, decisions={
        "W1/1/1": inv.LineDecision(inv.EXCLUDED, note="test entry")})
    assert not led.open_issues()
    assert led.excluded_lines[0][0].line_id == "W1/1/1"


def test_suggestions_rank_ids_above_description():
    reports = [rec("R1", D, "C-1", 10, desc="Pump"),
               rec("R2", D, "C-2", 10, desc="Pump", so="SO-9"),
               wdr("W1", date(2026, 10, 2), "", 1, desc="Pump", so="SO-9")]
    led = ledger(reports)
    suggestions = inv.suggest_matches(led.unmatched[0].line, led)
    assert suggestions[0][0].cargo_id == "C-2"
    assert "same SO Number" in suggestions[0][1]
    assert "verify" in suggestions[1][1]


def test_history_running_balance():
    led = ledger([rec("R1", D, "H", 10), wdr("W1", date(2026, 10, 2), "H", 3),
                  rec("R2", date(2026, 10, 3), "H", 5)])
    rows = inv.item_history(only(led, "H"))
    assert [r["balance"] for r in rows] == [10, 7, 12]


def test_as_of_excludes_later_transactions():
    led = ledger([rec("R1", D, "T", 10), wdr("W1", date(2026, 10, 20), "T", 4)],
                 as_of=date(2026, 10, 10))
    assert only(led, "T").remaining_qty == 10


def test_weights_only_when_all_known():
    led = ledger([rec("R1", D, "W", 10, weight="1,000 kg"),
                  wdr("W1", date(2026, 10, 2), "W", 4, weight="0.4 MT")])
    item = only(led, "W")
    assert item.received_kg == 1000 and item.withdrawn_kg == 400
    assert item.remaining_kg == 600
    led2 = ledger([rec("R1", D, "W", 10, weight="1000"),        # no unit
                   wdr("W1", date(2026, 10, 2), "W", 4)])
    assert only(led2, "W").remaining_kg is None


def test_empty_ledger():
    led = ledger([])
    assert led.items == [] and led.issues == [] and led.aging_rows == []
