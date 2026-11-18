"""The real program, started without a person at the keyboard (see
gui_harness.py): start-up, every module, and the original inspection
workflow (create, save, open, edit, numbering, report forms, Bad Order
incident report) plus the new warehouse links. Everything happens in a
temporary FSR_HOME folder; the real files are not touched."""

from collections import Counter
import time
from pathlib import Path

import pytest
from openpyxl import load_workbook

import fsr_storage
from conftest import ANCHOR
from warehouse import analytics as an
from warehouse import sample_data as sd
from warehouse import tables as tbl

pytestmark = pytest.mark.gui

WORKBOOK = "Field_Survey_Reports.xlsx"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_home")
    sd.generate(home / "excel", anchor=ANCHOR, workbook_name=WORKBOOK)
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    g["home"] = home
    yield g, answers
    h.stop_app(g, answers)


def settle(g, seconds=1.0):
    end = time.time() + seconds
    while time.time() < end:
        g["window"].update()
        time.sleep(0.03)


def wait_for_data(g, timeout=30):
    shell = g["app_shell"]
    end = time.time() + timeout
    while shell.service.snapshot is None and time.time() < end:
        shell.service.request(lambda *_: None)
        settle(g, 0.2)
    assert shell.service.snapshot is not None, shell.service.error
    return shell.service.snapshot


def errors_shown(answers):
    return [c for c in answers.calls if c[0] == "showerror"]


def fill_form(g, so, activity, location, lines, condition="Good Order"):
    g["new_report"](confirm=False)
    g["choose_condition"](condition)
    g["set_entry"](g["SO_number_entry"], so)
    g["schedule_entries"]["activity"].set(activity)
    g["location_combobox"].set(location)
    g["supplier_combobox"].set("Test Supplier Alpha Industrial")
    section = g["item_frames"][0]
    cols = g["ITEM_FORM_HEADERS"]
    for widgets, values in zip(section.rows, lines):
        for header, value in values.items():
            if header in cols:
                g["set_entry"](widgets[cols.index(header)], value)
            else:                       # not shown (Cargo ID ...)
                widgets.hidden[header] = value


# ---------- start-up + navigation ----------

def test_application_starts_with_navigation(app):
    g, answers = app
    assert g["app_shell"] is not None
    assert g["control_entry"].get().startswith("FSR-")
    assert len(g["app_shell"].buttons) == 8
    assert g["window"].winfo_exists()


def test_every_module_opens_without_errors(app):
    g, answers = app
    shell = g["app_shell"]
    wait_for_data(g)
    for key in ("dashboard", "receiving", "withdrawal", "warehouse",
                "bad_order", "analytics", "settings", "inspection"):
        shell.show(key)
        settle(g, 0.8)
        assert shell.current == key
    for mode in ("weekly", "monthly", "all", "daily"):
        shell.pages["receiving"].set_mode(mode)
        settle(g, 0.3)
    assert not errors_shown(answers), answers.calls


def test_dashboard_kpis_match_the_analytics(app):
    g, _ = app
    shell = g["app_shell"]
    shell.show("dashboard")
    snap = wait_for_data(g)
    settle(g, 0.5)
    page = shell.pages["dashboard"]
    expected = an.inspection_kpis(snap.transactions, page.bar.filters())
    shown = [[w.cget("text") for w in card.texts[:2]]
             for card in page.inspection.cards]
    # the same figures; a Bad Order report is shown as an Incident Report
    names = ["Total Inspection Reports", "Good Order Reports",
             "Incident Reports", "Incident Report Percentage",
             "Receiving Transactions", "Withdrawal Transactions"]
    assert shown == [[name, k.display] for name, k in zip(names, expected)]
    assert [k.name for k in expected] == [
        "Total Inspection Reports", "Good Order Reports", "Bad Order Reports",
        "Bad Order Percentage", "Receiving Transactions",
        "Withdrawal Transactions"]
    # Warehouse Items / Cargo Status: the period's Item List lines (This
    # Year: the test reports are dated up to October)
    from warehouse import periods as pr
    page.bar.period_var.set(pr.PERIOD_LABELS["this_year"])
    page.bar._changed()
    settle(g, 0.5)
    f = page.bar.filters()
    stored = len(an.lines_of(an.filter_transactions(snap.transactions, an.Filters(
        **{**f.__dict__, "activity": "Receiving"}))))
    bars = [b.get_width() for b in page.status.ax.patches][-3:]
    assert bars[0] == stored and stored > 0
    # In Stock = the Inventory Aging total (all dates, stock left today)
    in_stock = len(snap.inventory.aging_rows)
    assert bars[2] == in_stock
    aging = [b.get_height() for b in page.aging.ax.patches]
    assert sum(aging) == 2 * in_stock          # each bar has its glow
    # the Inventory Aging List: every in-stock line, then one bar's lines
    assert len(page.aging_table.all_rows) == in_stock
    labels, _ = page.aging.clickable
    counts = Counter(r.bucket for r in snap.inventory.aging_rows)
    index = next(i for i, label in enumerate(labels) if counts[label])
    assert page.aging.category_at(index + 0.3, 0) == (index, labels[index])
    assert page.aging.category_at(index + 0.5, 0) is None   # between bars
    page.aging.on_bar_click(index, labels[index])
    settle(g, 0.2)
    rows = page.aging_table.all_rows
    assert len(rows) == counts[labels[index]]
    assert [c[0] for c in page.aging_table.columns][:3] == [
        "Control Number", "Date", "Line Item"]
    assert all(row[2].startswith("List ") for row in rows)
    assert str(page.aging_all_btn.cget("state")) == "normal"
    assert labels[index] in page.aging_shown.cget("text")
    page.show_aging(None)
    assert len(page.aging_table.all_rows) == in_stock
    assert not hasattr(page, "activity") and not hasattr(page, "balance")
    for chart in (page.trend, page.receiving, page.withdrawal, page.status,
                  page.good_bad, page.aging):
        assert chart.neo and chart.ax is not None


def test_transaction_pages_show_transactions_packages_and_items(app):
    g, answers = app
    shell = g["app_shell"]
    wait_for_data(g)
    for key in ("receiving", "withdrawal"):
        shell.show(key)
        settle(g, 0.8)
        page = shell.pages[key]
        page.set_mode("monthly")
        settle(g, 0.5)
        summary = page.current_summary()
        expected = an.activity_kpis(
            summary.transactions,
            summary.previous.transactions if summary.previous else None,
            summary.period.describe())
        assert [[w.cget("text") for w in card.texts[:2]]
                for card in page.kpis.cards] == \
            [[k.name, k.display] for k in expected]
        assert [k.name for k in expected] == [
            "Total Transactions", "Total Packages", "Items Inspected"]
    assert not errors_shown(answers), answers.calls


def test_incident_reports_page_lists_the_reports_by_month(app):
    g, answers = app
    shell = g["app_shell"]
    snap = wait_for_data(g)
    shell.show("bad_order")
    settle(g, 1.0)
    page = shell.pages["bad_order"]
    assert page.title == "Incident Reports Monitoring"
    months = page.months.get_children()
    shown = sum(len(page.months.get_children(m)) for m in months)
    bad, _ = page.reports(page.bar.filters())
    assert shown == len(bad) > 0
    assert len(page.month_reports) == shown
    assert page.per_month.ax is not None
    # four cards: no Affected Cargo Lines, no Unresolved cases; no cargo type
    # chart and no Bad Order Records table
    assert [c.texts[0].cget("text") for c in page.kpis.cards] == [
        "Total Incident Reports", "Incident Reports - Receiving",
        "Incident Reports - Withdrawal", "Incident Report Percentage"]
    assert not hasattr(page, "by_type") and not hasattr(page, "table")
    # a report chosen in the month list: its case status can be set
    first = page.months.get_children(months[0])[0]
    page.months.selection_set(first)
    settle(g, 0.3)
    assert str(page.status_btn.cget("state")) == "normal"
    assert not errors_shown(answers), answers.calls


def test_theme_toggle(app):
    g, answers = app
    g["toggle_theme"]()
    settle(g, 0.5)
    g["toggle_theme"]()
    settle(g, 0.5)
    assert not errors_shown(answers)


# ---------- the original inspection workflow ----------

def test_create_save_open_edit_report(app):
    g, answers = app
    g["app_shell"].show("inspection")
    fill_form(g, "SO-GUI-1", "Receiving", "GUI Warehouse",
              [{"Description of Goods": "GUI Pump", "Quantity": "10",
                "UOM": "PCS", "Packaging": "Box", "Currency": "USD",
                "Unit Price": "5.00", "Cargo ID": "GUI-CARGO-1"}])
    control = g["control_entry"].get()
    assert g["save_report"]() is True
    path = Path(g["excel_state"]["path"])
    saved = fsr_storage.read_report(path, control)
    row = saved["item_lists"][0]["rows"][0]
    assert row["Cargo ID"] == "GUI-CARGO-1"
    assert row["Receiving Ref"] == f"RCV-{control}-1-01"
    assert (row["Quantity"], row["UOM"], row["Currency"]) == \
        ("10", "PCS", "USD")
    # the Receiving Ref is kept with the line after saving
    widgets = g["item_frames"][0].rows[0]
    assert widgets.hidden["Receiving Ref"] == row["Receiving Ref"]
    # report form workbook made from the templates
    form = path.parent / "Report Forms" / f"{control}_Report.xlsx"
    assert form.exists()
    assert {"First Page"} <= set(load_workbook(form).sheetnames)
    # open it again, edit, save -> updated in place
    g["new_report"](confirm=False)
    assert g["control_entry"].get() != control       # next number
    g["load_report_into_form"](control, "excel")
    assert g["SO_number_entry"].get() == "SO-GUI-1"
    g["set_entry"](g["SO_number_entry"], "SO-GUI-1-EDITED")
    assert g["save_report"]() is True
    assert fsr_storage.read_report(path, control)["general_information"][
        "so_number"] == "SO-GUI-1-EDITED"
    assert sum(1 for r in fsr_storage.list_saved_reports(path)
               if r[0] == control) == 1
    assert not errors_shown(answers)


def test_bad_order_incident_report(app):
    g, answers = app
    fill_form(g, "SO-GUI-BO", "Receiving", "GUI Warehouse",
              [{"Description of Goods": "Crate", "Quantity": "1",
                "Packaging": "crate", "Cargo ID": "GUI-BO-1"}],
              condition="Bad Order")
    g["incident_cards"][0].rows[0].insert(0, "Crate broken on arrival")
    control = g["control_entry"].get()
    assert g["save_report"]() is True
    path = Path(g["excel_state"]["path"])
    assert fsr_storage.read_report(path, control)["incident_reports"][0][
        "lines"] == ["Crate broken on arrival"]
    form = path.parent / "Report Forms" / f"{control}_Report.xlsx"
    assert any("Incident" in name for name in load_workbook(form).sheetnames)


def test_withdrawal_without_link_goes_to_reconciliation(app):
    g, answers = app
    wait_for_data(g)
    fill_form(g, "SO-GUI-2", "Withdrawal", "GUI Warehouse",
              [{"Description of Goods": "GUI Pump", "Quantity": "4",
                "UOM": "PCS"}])
    control = g["control_entry"].get()
    assert g["save_report"]() is True
    snap = wait_for_data(g)
    issue = next(u for u in snap.inventory.unmatched
                 if u.line.control_no == control)
    assert (issue.line.quantity, issue.line.unit) == (4, "PCS")


def test_warehouse_page_lists_inventory_and_issues(app):
    g, answers = app
    shell = g["app_shell"]
    snapshot = wait_for_data(g)
    shell.show("warehouse")
    settle(g, 0.3)
    page = shell.pages["warehouse"]

    assert page.inventory_table.all_rows == \
        tbl.inventory_rows(snapshot.inventory.items)
    assert len(page.issue_table.all_rows) == len(snapshot.inventory.issues)
    assert page.audit_table.all_rows == []
    assert not errors_shown(answers), answers.calls


def test_reconciliation_can_be_proposed_and_confirmed_in_the_ui(app):
    g, answers = app
    shell = g["app_shell"]
    shell.show("inspection")
    fill_form(
        g, "SO-GUI-RECON-RECEIVING", "Receiving", "GUI Reconciliation",
        [{"Description of Goods": "Reconciliation Pump", "Quantity": "10",
          "UOM": "PCS", "Cargo ID": "GUI-RECON-CARGO"}])
    assert g["save_report"]() is True

    fill_form(
        g, "SO-GUI-RECON-WITHDRAWAL", "Withdrawal", "GUI Reconciliation",
        [{"Description of Goods": "Reconciliation Pump", "Quantity": "4",
          "UOM": "PCS"}])
    withdrawal_control = g["control_entry"].get()
    assert g["save_report"]() is True

    snapshot = wait_for_data(g)
    shell.show("warehouse")
    settle(g, 0.3)
    page = shell.pages["warehouse"]
    issue_index = next(
        index for index, (_row, issue) in enumerate(page.issue_table.view)
        if issue.line and issue.line.control_no == withdrawal_control)
    page.issue_table.tree.selection_set(str(issue_index))
    page.issue_table._selected()
    candidate_index = next(
        index for index, (_row, candidate) in
        enumerate(page.suggestion_table.view)
        if candidate[0].cargo_id == "GUI-RECON-CARGO")
    page.suggestion_table.tree.selection_set(str(candidate_index))
    page.suggestion_table._selected()
    assert str(page.propose_button.cget("state")) == "normal"
    page.propose_button.invoke()

    snapshot = wait_for_data(g)
    page = shell.pages["warehouse"]
    issue_index = next(
        index for index, (_row, issue) in enumerate(page.issue_table.view)
        if issue.line and issue.line.control_no == withdrawal_control)
    page.issue_table.tree.selection_set(str(issue_index))
    page.issue_table._selected()
    assert str(page.confirm_button.cget("state")) == "normal"

    page.ctx.is_owner = False
    page._update_actions()
    assert str(page.confirm_button.cget("state")) == "disabled"
    page.ctx.is_owner = True
    page._update_actions()
    page.confirm_button.invoke()

    snapshot = wait_for_data(g)
    item = snapshot.inventory.item("GUI Reconciliation",
                                   "GUI-RECON-CARGO")
    assert item.remaining_qty == 6
    assert [entry["action"] for entry in
            snapshot.side.history(withdrawal_control + "/1/1")] == [
                "propose", "confirm"]
    saved = fsr_storage.read_report(
        Path(g["excel_state"]["path"]), withdrawal_control)
    assert saved["item_lists"][0]["rows"][0]["Cargo ID"] == ""

    audit_index = next(
        index for index, (_row, entry) in enumerate(page.audit_table.view)
        if entry["subject"] == withdrawal_control + "/1/1"
        and entry["action"] == "confirm")
    page.audit_table.tree.selection_set(str(audit_index))
    page.audit_table._selected()
    assert str(page.reopen_audit_button.cget("state")) == "normal"
    page.reopen_audit_button.invoke()

    snapshot = wait_for_data(g)
    assert any(issue.line and issue.line.control_no == withdrawal_control
               for issue in snapshot.inventory.unmatched)
    assert [entry["action"] for entry in
            snapshot.side.history(withdrawal_control + "/1/1")] == [
                "propose", "confirm", "reopen"]
    assert not errors_shown(answers), answers.calls


def test_old_quantity_with_unit_is_split_on_load(app):
    g, answers = app
    section = g["item_frames"][0]
    section.set_values([{"Description of Goods": "Old line",
                         "Quantity": "12 pcs", "Cargo ID": "OLD-1"}])
    cols = g["ITEM_FORM_HEADERS"]
    widgets = section.rows[0]
    assert widgets[cols.index("Quantity")].get() == "12"
    assert widgets[cols.index("UOM")].get() == "pcs"
    assert section.values()[0]["Cargo ID"] == "OLD-1"
    g["new_report"](confirm=False)


def test_weight_unit_is_split_and_saved_with_the_weight(app):
    g, answers = app
    section = g["item_frames"][0]
    section.set_values([{"Description of Goods": "Drum",
                         "Weights": "1,250 kg"}])
    cols = g["ITEM_FORM_HEADERS"]
    widgets = section.rows[0]
    assert widgets[cols.index("Weights")].get() == "1,250"
    assert widgets[cols.index("Weight Unit")].get() == "kg"
    g["set_entry"](widgets[cols.index("Weight Unit")], "ML")
    line = section.values()[0]
    assert line["Weights"] == "1,250 ML" and "Weight Unit" not in line
    g["new_report"](confirm=False)


def test_real_project_files_untouched(app):
    g, _ = app
    assert Path(g["excel_state"]["path"]).parent == g["home"] / "excel"
    assert Path(g["SETTINGS_FILE"]).parent == g["home"] / "json" / "private"


# ---------- Item List forms: Default / Containerized / Loading ----------

def test_each_item_form_keeps_its_own_lines(app):
    g, answers = app
    g["new_report"](confirm=False)
    g["item_frames"][0].set_values([{"Description of Goods": "Pump",
                                     "PO Number": "PO-7"}])
    g["set_item_form"]("Containerized")
    section = g["item_frames"][0]
    assert section.headers == g["UNIT_FORM_HEADERS"]
    assert section.label(fsr_storage.UNIT_NO_HEADER) == "Container No."
    assert section.values() == []           # nothing from the Default form
    g["set_entry"](section.rows[0][0], "MSKU 123456-7")
    g["set_item_form"]("Loading")
    section = g["item_frames"][0]
    assert section.label(fsr_storage.UNIT_NO_HEADER) == "Truck Plate No."
    assert section.values() == []
    g["set_item_form"]("Containerized")
    assert g["item_frames"][0].rows[0][0].get() == "MSKU 123456-7"
    g["set_item_form"]("Default")
    section = g["item_frames"][0]
    assert section.headers == g["ITEM_FORM_HEADERS"]
    line = section.values()[0]
    assert (line["Description of Goods"], line["PO Number"]) ==         ("Pump", "PO-7")
    assert line[fsr_storage.UNIT_NO_HEADER] == ""
    g["new_report"](confirm=False)
    assert g["item_form_var"].get() == "Default"
    assert not g["item_form_store"]
    assert not errors_shown(answers)


@pytest.mark.parametrize("form, label", [("Containerized", "Container No."),
                                         ("Loading", "Truck details")])
def test_item_form_is_saved_loaded_and_printed(app, form, label):
    g, answers = app
    g["app_shell"].show("inspection")
    fill_form(g, f"SO-GUI-{form}", "Receiving", "GUI Warehouse", [])
    g["set_item_form"](form)
    section = g["item_frames"][0]
    section.set_values([{fsr_storage.UNIT_NO_HEADER: "UNIT-1",
                         "Description of Goods": "Steel coil",
                         "Packaging": "Bundle", "Quantity": "4 pcs",
                         "Dimensions": "1x1x1", "Weights": "2,000 kg",
                         "Findings": "Good"}])
    control = g["control_entry"].get()
    assert g["save_report"]() is True
    path = Path(g["excel_state"]["path"])
    saved = fsr_storage.read_report(path, control)
    assert saved["item_form"] == form
    row = saved["item_lists"][0]["rows"][0]
    assert row[fsr_storage.UNIT_NO_HEADER] == "UNIT-1"
    assert (row["Quantity"], row["UOM"], row["Weights"]) == \
        ("4", "pcs", "2,000 kg")

    report = load_workbook(
        path.parent / "Report Forms" / f"{control}_Report.xlsx")
    ws = report["Cargo Details"]
    assert ws["A12"].value == label
    assert [ws[c].value for c in ("A13", "B13", "E13", "G13", "J13",
                                  "K13")] == \
        ["UNIT-1", "Steel coil", "Bundle", "4 pcs", "2,000 kg", "Good"]
    assert "B13:D13" in {str(r) for r in ws.merged_cells.ranges}

    g["new_report"](confirm=False)
    g["load_report_into_form"](control, "excel")
    assert g["item_form_var"].get() == form
    section = g["item_frames"][0]
    assert section.form == form
    assert section.rows[0][0].get() == "UNIT-1"
    g["new_report"](confirm=False)
    assert not errors_shown(answers)


def unit_line(number):
    return {fsr_storage.UNIT_NO_HEADER: number, "Description of Goods": "Coil",
            "Packaging": "Bundle", "Quantity": "4 pcs"}


def fill_item_forms(g, *forms):
    """Type one line on each of these Item List forms."""
    fill_form(g, "SO-GUI-FORMS", "Receiving", "GUI Warehouse", [])
    for form in forms:
        g["set_item_form"](form)
        line = ({"Description of Goods": "Pump", "Packaging": "Box"}
                if form == "Default" else unit_line(f"{form}-1"))
        g["item_frames"][0].set_values([line])


def report_sheets(g):
    forms, notes, _ = g["create_report_forms"](g["excel_state"]["path"],
                                               g["collect_report_data"]())
    assert not notes
    return load_workbook(forms[0])


@pytest.mark.parametrize("forms, expected", [
    (("Default",), ["First Page", "Cargo Details"]),
    (("Loading",), ["First Page", "Cargo Details"]),
    (("Default", "Loading"), ["First Page", "Cargo Details",
                              "Loading Details"]),
    (("Containerized", "Loading"), ["First Page", "Containerized Details",
                                    "Loading Details"]),
    (("Default", "Containerized", "Loading"),
     ["First Page", "Cargo Details", "Containerized Details",
      "Loading Details"]),
])
def test_every_item_form_with_lines_is_printed(app, forms, expected):
    g, answers = app
    fill_item_forms(g, *forms)
    assert report_sheets(g).sheetnames == expected
    g["new_report"](confirm=False)
    assert not errors_shown(answers)


def test_no_item_lines_prints_the_first_page_only(app):
    g, _ = app
    fill_form(g, "SO-GUI-EMPTY", "Receiving", "GUI Warehouse", [])
    assert report_sheets(g).sheetnames == ["First Page"]


def test_remarks_follow_the_last_form_and_incident_comes_last(app):
    g, answers = app
    fill_item_forms(g, "Default", "Loading")
    g["choose_condition"]("Bad Order")
    g["incident_cards"][0].rows[0].insert(0, "Crate broken")
    g["set_entry"](g["findings_entries"][0], "Remark one")
    book = report_sheets(g)
    assert book.sheetnames == ["First Page", "Cargo Details",
                               "Loading Details", "Incident Report"]
    text = [[str(c.value) for row in book[name].iter_rows() for c in row]
            for name in ("Cargo Details", "Loading Details")]
    assert not any("Remark one" in t for t in text[0])
    assert any("Remark one" in t for t in text[1])
    g["new_report"](confirm=False)
    assert not errors_shown(answers)


def test_other_item_forms_survive_save_and_open(app):
    g, answers = app
    fill_item_forms(g, "Default", "Containerized", "Loading")
    g["set_item_form"]("Default")
    control = g["control_entry"].get()
    assert g["save_report"]() is True
    path = Path(g["excel_state"]["path"])
    # only the selected form is in the Excel file (stock)
    saved = fsr_storage.read_report(path, control)
    assert [r["Description of Goods"]
            for r in saved["item_lists"][0]["rows"]] == ["Pump"]

    g["new_report"](confirm=False)
    g["load_report_into_form"](control, "excel")
    assert report_sheets(g).sheetnames == [
        "First Page", "Cargo Details", "Containerized Details",
        "Loading Details"]
    g["set_item_form"]("Loading")
    assert g["item_frames"][0].rows[0][0].get() == "Loading-1"

    # a form emptied again is not kept
    g["item_frames"][0].clear()
    g["set_item_form"]("Default")
    assert g["save_report"]() is True
    assert set(fsr_storage.load_other_item_forms(path, control)) == {
        "Containerized"}
    g["new_report"](confirm=False)
    assert not errors_shown(answers)


def test_import_master_data_button(app, tmp_path):
    """The Import Master Data button, with a phone file, up to the printout."""
    import fsr_import
    g, answers = app
    phone = {
        "format": fsr_import.FORMAT, "version": 1, "device_id": "gui-phone",
        "inspector": "Phone Inspector",
        "master_lists": {"supplier_list": ["Phone Only Supplier Co"]},
        "reports": [{
            "control_no": "FSR-209901-0001", "last_saved": "1",
            "cargo_condition": "Good Order", "item_form": "Default",
            "goods_types": {"new": True},
            "general_information": {
                "so_number": "SO-GUI-IMPORT", "inspection_date": "05-Oct-2026",
                "consignee": "EDC", "supplier": "Phone Only Supplier Co",
                "brokerage": "", "hauler": "", "location": "",
                "destination": "", "country_of_origin": ""},
            "inspection_schedule": {
                "activity": "", "commenced_date": "", "commenced_time": "",
                "completion_date": "", "completion_time": ""},
            "transport_details": {
                "shipment_type": "", "container_type": "",
                "vessel_carrier": "", "vehicle_type": "",
                "vehicle_plate_number": ""},
            "documents_used": {
                "invoice_number": "", "po_number": "", "jo_number": "",
                "gatepass_number": "", "bl_awb_number": "", "dr_number": "",
                "other_documents": ""},
            "declared_goods": [], "other_important_remarks": [],
            "item_lists": [{"name": "Item List 1", "rows": []}],
            "findings_and_remarks": [], "incident_reports": [],
            "other_item_forms": {},
        }],
    }
    source = tmp_path / "FSR_Master_Data.json"
    source.write_text(__import__("json").dumps(phone), encoding="utf-8")
    dialog = g["filedialog"]
    original = dialog.askopenfilename
    dialog.askopenfilename = lambda **_: str(source)
    answers.calls.clear()
    try:
        g["import_master_button"].invoke()
        # The import runs in the background with a progress window (Phase
        # 3); the window keeps working until it is done.
        import time
        state = g["save_report"].__globals__["import_state"]
        deadline = time.monotonic() + 60
        while state["running"] and time.monotonic() < deadline:
            g["window"].update()
            time.sleep(0.02)
        assert not state["running"]
    finally:
        dialog.askopenfilename = original

    path = g["excel_state"]["path"]
    saved = fsr_storage.read_report(path, "FSR-209901-0001")
    assert saved["general_information"]["so_number"] == "SO-GUI-IMPORT"
    assert "Phone Only Supplier Co" in g["master_data"]["supplier_list"]
    assert any("Added: 1" in str(call[2]) for call in answers.calls)

    change_text = g["import_change_text"]([{
        "control": "FSR-209901-0001",
        "fields": [{
            "path": ("item_lists", 0, "rows", 1, "Packaging"),
            "previous": "(not present)", "imported": "1x40 cvan",
        }, {
            "path": ("other_important_remarks", 0),
            "previous": "Old remark", "imported": "New remark",
        }],
    }])
    assert "Item Lists > Item List 1 > Rows > Row 2 > Packaging" in change_text
    assert "Previous: (not present)" in change_text
    assert "Imported: 1x40 cvan" in change_text
    assert "Other Important Remarks > Entry 1" in change_text

    forms, _, _ = g["create_report_forms"](path, saved)
    sheet = load_workbook(forms[0])["First Page"]
    assert sheet["A38"].value == "Phone Inspector"
    # A report made on this PC still prints this PC's user.
    g["create_report_forms"](path, dict(saved, control_no="FSR-209901-9999"))
    assert g["print_name"]["value"] == g["USER_FULL_NAME"]


def _phone_report_with_identity(revision, so):
    return {
        "control_no": "FSR-209901-0002", "last_saved": f"r{revision}",
        "report_id": "gui-report-1", "revision": revision,
        "cargo_condition": "Good Order", "item_form": "Default",
        "goods_types": {"new": True},
        "general_information": {
            "so_number": so, "inspection_date": "06-Oct-2026",
            "consignee": "EDC", "supplier": "", "brokerage": "",
            "hauler": "", "location": "", "destination": "",
            "country_of_origin": ""},
        "inspection_schedule": {
            "activity": "", "commenced_date": "", "commenced_time": "",
            "completion_date": "", "completion_time": ""},
        "transport_details": {
            "shipment_type": "", "container_type": "", "vessel_carrier": "",
            "vehicle_type": "", "vehicle_plate_number": ""},
        "documents_used": {
            "invoice_number": "", "po_number": "", "jo_number": "",
            "gatepass_number": "", "bl_awb_number": "", "dr_number": "",
            "other_documents": ""},
        "declared_goods": [], "other_important_remarks": [],
        "item_lists": [{"name": "Item List 1", "rows": []}],
        "findings_and_remarks": [], "incident_reports": [],
        "other_item_forms": {},
    }


def _import_through_button(g, tmp_path, name, reports):
    import json
    import fsr_import
    source = tmp_path / name
    source.write_text(json.dumps({
        "format": fsr_import.FORMAT, "version": 1, "device_id": "gui-phone-2",
        "location_id": "gui-location", "location_name": "GUI Test Yard",
        "inspector": "Review Inspector", "master_lists": {},
        "reports": reports}), encoding="utf-8")
    dialog = g["filedialog"]
    original = dialog.askopenfilename
    dialog.askopenfilename = lambda **_: str(source)
    try:
        g["import_master_button"].invoke()
        wait_until_not_running(g)
    finally:
        dialog.askopenfilename = original


def wait_until_not_running(g):
    state = g["save_report"].__globals__["import_state"]
    deadline = time.monotonic() + 60
    while state["running"] and time.monotonic() < deadline:
        g["window"].update()
        time.sleep(0.02)
    assert not state["running"]


def _buttons(widget):
    for child in widget.winfo_children():
        if child.winfo_class() == "TButton":
            yield child
        yield from _buttons(child)


def test_import_review_window_accepts_a_newer_revision(app, tmp_path):
    """A user's newer revision waits in Import Review until accepted."""
    import fsr_import
    g, answers = app
    path = g["excel_state"]["path"]
    _import_through_button(g, tmp_path, "first.json",
                           [_phone_report_with_identity(1, "SO-REV-1")])
    assert fsr_storage.read_report(path, "FSR-209901-0002")[
        "general_information"]["so_number"] == "SO-REV-1"

    answers.calls.clear()
    _import_through_button(g, tmp_path, "second.json",
                           [_phone_report_with_identity(2, "SO-REV-2")])
    assert any("Waiting for your review" in str(call[2])
               for call in answers.calls)
    # not applied yet
    assert fsr_storage.read_report(path, "FSR-209901-0002")[
        "general_information"]["so_number"] == "SO-REV-1"
    review = g["import_review_state"]["dialog"]
    assert review is not None and review.winfo_exists()
    assert "1 waiting" in g["import_review_button"].cget("text")

    (waiting,) = fsr_import.pending_reviews(path)
    text = g["import_review_text"](
        waiting, fsr_import.review_comparison(path, waiting["key"]))
    assert "CHANGED BY THE USER" in text
    assert "User:   SO-REV-2" in text and "Before: SO-REV-1" in text
    assert "GUI Test Yard" in text

    (accept,) = [b for b in _buttons(review)
                 if b.cget("text") == "Accept User Changes"]
    accept.invoke()
    wait_until_not_running(g)
    g["window"].update()
    assert fsr_storage.read_report(path, "FSR-209901-0002")[
        "general_information"]["so_number"] == "SO-REV-2"
    assert fsr_import.pending_reviews(path) == []
    assert fsr_import.load_import_history(path)[-1]["result"] == "accepted"
    assert g["import_review_button"].cget("text") == "Import Review..."
    assert not errors_shown(answers)
    review.destroy()
