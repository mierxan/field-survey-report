"""db_mysql itself against the REAL test database field_survey_test (never
field_survey - tests/real_mysql.py refuses any other): every read and
write the overwrite guard and the background sender rely on, with a full
report (Bad Order with incidents, several item lists, link columns,
remarks, declared goods).

Skipped, with the reason, when the test database is not set up on this
PC."""
from datetime import date

import pytest

import db_mysql
import real_mysql
from factories import report

NAME_PREFIX = "ZZT-TEST-"            # master list names written here


@pytest.fixture(scope="module")
def database():
    try:
        db = real_mysql.open_database()
    except real_mysql.NotAvailable as why:
        pytest.skip(f"{real_mysql.SKIP_PREFIX}: {why}")
    db.remove_test_rows()
    yield db
    db.remove_test_rows()
    db.run("DELETE FROM master_list WHERE item_name LIKE %s",
           (NAME_PREFIX + "%",))


@pytest.fixture
def conn(database):
    connection = database.connect()
    yield connection
    try:
        connection.rollback()
    finally:
        connection.close()


_serial = iter(range(1, 10_000))


def control():
    return f"{real_mysql.PREFIX}10-{next(_serial):04d}"


def full_report(number, condition="Bad Order"):
    data = report(number, "Receiving", date(2026, 10, 5), "Warehouse 9",
                  [{"qty": 3, "unit": "Box", "desc": "Valve body", "po": "PO-1",
                    "cargo": "CID-1", "ref": f"RCV-{number}-1-01"},
                   {"qty": "1,250.50", "unit": "Kg", "desc": "Steel bar",
                    "po": "PO-2", "cargo": "CID-2",
                    "ref": f"RCV-{number}-1-02"}],
                  so="SO-REAL-DB", condition=condition)
    data["item_lists"].append({"name": "Item List 2", "rows": [
        dict(data["item_lists"][0]["rows"][0], **{
            "Description of Goods": "Second list line",
            "Receiving Ref": f"RCV-{number}-2-01"})]})
    data["declared_goods"] = [{"description": "Machinery", "quantity": "2",
                               "packaging": "Crates"}]
    data["other_important_remarks"] = ["Seal intact", "Counted"]
    data["findings_and_remarks"] = ["Dent on crate 2"]
    data["documents_used"].update(bl_awb_number="BL-77", dr_number="DR-5",
                                  gatepass_number="GP-9", po_number="PO-9")
    data["incident_reports"] = ([{
        "vessel": "MV Test", "voyage": "V1", "client": "Client",
        "so_number": "SO-REAL-DB", "port": "Port", "date": "05-Oct-2026",
        "operation": "Discharge", "lines": ["Crate 2 dented", "Photo taken"]}]
        if condition == "Bad Order" else [])
    data["item_form"] = "Default"
    return data


def test_a_full_report_reads_back_as_written(conn):
    number = control()
    data = full_report(number)
    notes = db_mysql.write_report(conn, data)
    conn.commit()
    assert notes == [] or all("Excel only" in n for n in notes)

    back = db_mysql.load_report(number, conn)
    assert back["general_information"]["so_number"] == "SO-REAL-DB"
    assert back["general_information"]["location"] == "Warehouse 9"
    assert back["cargo_condition"] == "Bad Order"
    assert [s["name"] for s in back["item_lists"]] == ["Item List 1",
                                                      "Item List 2"]
    rows = back["item_lists"][0]["rows"]
    assert [r["Description of Goods"] for r in rows] == ["Valve body",
                                                         "Steel bar"]
    assert rows[0]["Receiving Ref"] == f"RCV-{number}-1-01"
    assert back["declared_goods"][0]["description"] == "Machinery"
    assert back["other_important_remarks"] == ["Seal intact", "Counted"]
    assert back["findings_and_remarks"] == ["Dent on crate 2"]
    (incident,) = back["incident_reports"]
    assert incident["lines"] == ["Crate 2 dented", "Photo taken"]
    assert incident["date"] == "05-Oct-2026"


def test_writing_again_replaces_the_lines_not_adds_to_them(conn):
    number = control()
    db_mysql.write_report(conn, full_report(number))
    conn.commit()
    changed = full_report(number, condition="Good Order")
    changed["item_lists"] = changed["item_lists"][:1]
    changed["findings_and_remarks"] = []
    db_mysql.write_report(conn, changed)
    conn.commit()
    back = db_mysql.load_report(number, conn)
    assert back["cargo_condition"] == "Good Order"
    assert back["incident_reports"] == []          # Good Order: none kept
    assert [s["name"] for s in back["item_lists"]] == ["Item List 1"]
    assert back["findings_and_remarks"] == []


def test_a_rollback_leaves_nothing_behind(database, conn):
    """The guard writes inside a transaction and rolls back on a
    conflict: nothing of the half-written report may stay."""
    number = control()
    db_mysql.write_report(conn, full_report(number))
    conn.rollback()
    assert not db_mysql.report_exists(conn, number)
    assert database.run("SELECT COUNT(*) FROM item_lines WHERE control_no "
                        "= %s", (number,)) == [(0,)]


def test_lists_search_and_numbers(conn):
    number = control()
    db_mysql.write_report(conn, full_report(number))
    conn.commit()
    listed = {row[0]: row for row in db_mysql.list_reports(conn)}
    assert listed[number][1] == "SO-REAL-DB"
    assert listed[number][2] == "05-Oct-2026"
    assert number in db_mysql.control_numbers(conn)
    index = db_mysql.search_index(conn)[number]
    assert "BL-77" in index["bl"] and "DR-5" in index["dr"]
    assert "GP-9" in index["gatepass"]
    assert {"PO-1", "PO-2", "PO-9"} <= set(index["po"])
    assert "Steel bar" in index["description"]
    assert any(r["control_no"] == number
               for r in db_mysql.load_all_reports(conn))


def test_weekly_summary_has_one_row_per_item_line(conn):
    number = control()
    data = full_report(number)
    so = f"SO-WEEK-{number}"               # the rows carry the SO, not the #
    data["general_information"]["so_number"] = so
    db_mysql.write_report(conn, data)
    conn.commit()
    rows = [r for r in db_mysql.weekly_summary(
        date(2026, 10, 1), date(2026, 10, 10), conn) if r[0] == so]
    assert len(rows) == 3                  # 2 + 1 item lines
    assert all(len(r) == 28 for r in rows)
    assert rows[0][1] == "05-Oct-2026" and rows[0][-1] == "Bad Order"
    assert not [r for r in db_mysql.weekly_summary(
        date(2026, 11, 1), date(2026, 11, 2), conn) if r[0] == so]


def test_the_lock_of_one_report_keeps_out_a_second_connection(database,
                                                              conn):
    number = control()
    other = database.connect()
    try:
        assert db_mysql.lock_report(conn, number) is True
        assert db_mysql.lock_report(other, number, timeout=1) is False
        assert db_mysql.lock_report(other, control(), timeout=1) is True
        db_mysql.unlock_report(conn, number)
        assert db_mysql.lock_report(other, number, timeout=1) is True
    finally:
        other.close()


def test_report_exists_holds_the_row_inside_the_transaction(conn):
    number = control()
    db_mysql.write_report(conn, full_report(number))
    conn.commit()
    assert db_mysql.report_exists(conn, number) is True
    assert db_mysql.report_exists(conn, control()) is False
    conn.rollback()


def test_master_lists_add_names_and_never_duplicate(database, conn):
    names = {"consignee_list": [f"{NAME_PREFIX}Consignee",
                                f"{NAME_PREFIX}Consignee"],
             "supplier_list": [f"{NAME_PREFIX}Supplier", "  "]}
    db_mysql.save_master_lists(names, conn)
    db_mysql.save_master_lists(names, conn)
    rows = database.run("SELECT list_name, item_name FROM master_list WHERE "
                        "item_name LIKE %s ORDER BY list_name",
                        (NAME_PREFIX + "%",))
    assert rows == [("consignee_list", f"{NAME_PREFIX}Consignee"),
                    ("supplier_list", f"{NAME_PREFIX}Supplier")]


def test_the_connection_check_and_the_tables(database):
    ok, message, away = db_mysql.check_connection(dict(database._config))
    assert ok and "Connected" in message and away is False
    conn = database.connect()
    try:
        assert db_mysql.missing_link_columns(conn) == []
        assert db_mysql.short_control_tables(conn) == []
    finally:
        conn.close()


def test_a_server_that_is_not_there_is_reported_as_away(database):
    config = dict(database._config, port=1)        # nothing listens there
    ok, message, away = db_mysql.check_connection(config)
    assert not ok and away is True
    assert "cannot reach" in message or "2003" in message


def test_the_shipment_fields_are_kept_and_old_lines_carry_none(conn):
    """Packing List No. / Origin Line (a line received from a shipment
    file) in the real test database: written, read back, and a line without
    them reads exactly as before (no empty keys)."""
    number = control()
    data = full_report(number, condition="Good Order")
    rows = data["item_lists"][0]["rows"]
    rows[0].update({"Packing List No.": "NOR111126-001 & 002",
                    "Origin Line": "FSR-ORG-202611-0001/1/1",
                    "Findings": "Good Order and Complete"})
    notes = db_mysql.write_report(conn, data)
    conn.commit()
    assert not any("Packing List" in n for n in notes)   # the columns exist
    back = db_mysql.load_report(number, conn)["item_lists"][0]["rows"]
    assert (back[0]["Packing List No."], back[0]["Origin Line"],
            back[0]["Findings"]) == ("NOR111126-001 & 002",
                                     "FSR-ORG-202611-0001/1/1",
                                     "Good Order and Complete")
    assert "Packing List No." not in back[1] and "Origin Line" not in back[1]
