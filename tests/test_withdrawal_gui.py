"""The PO-linked Withdrawal workflow in the real program (see gui_harness.py),
in a temporary FSR_HOME folder. The Receiving reports are test fixtures."""

import hashlib
import tkinter
from datetime import date
from pathlib import Path
from tkinter import ttk

import pytest
from openpyxl import load_workbook

import fsr_storage
import fsr_withdrawal as wd
from factories import rec, report
from fsr_withdrawal_ui import is_linked
from warehouse import store

pytestmark = pytest.mark.gui

PO_LINES = [
    ("OLD-1", "Pump", "4500001", "Crate", "100 pcs", "1x1x1 cm", "50 kg",
     "JPY 10", "JPY 1,000", "Good Order"),
    ("OLD-1", "Pump", "4500001", "Crate", "7 pcs", "n/a", "'", "n/a", "n/a",
     "Good Order"),
    ("OLD-2", "Cable", "4500001", "Roll", "12.5 m", "n/a", "n/a", "n/a", "n/a",
     "Good Order"),
    ("OLD-3", "Gasket", "4500003", "Box", "n/a", "n/a", "n/a", "n/a", "n/a", ""),
    ("OLD-3", "Seal", "4500003", "Box", "2 pcs", "n/a", "n/a", "n/a", "n/a", ""),
    ("OLD-4", "Shared", "7000 / 7001", "Box", "2 pcs", "", "", "", "", ""),
]


@pytest.fixture(scope="module")
def started(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_home")
    g, answers = h.start_app(home)
    yield g, answers
    h.stop_app(g, answers)


@pytest.fixture
def app(started):
    g, answers = started
    answers.yes = True
    answers.calls.clear()
    g["new_report"](confirm=False)
    write_receiving(g)
    if book_path(g).exists():       # each test starts with nothing withdrawn
        book_path(g).unlink()
    g["app_shell"].show("inspection")
    yield g, answers
    g["new_report"](confirm=False)


def live(g):
    """The program's real globals (`g` from runpy is only a copy of them)."""
    return g["save_report"].__globals__


def main_path(g):
    return Path(g["excel_state"]["path"])


def book_path(g):
    return g["withdrawal_book"]()


def write_receiving(g):
    """The Receiving reports the picker reads, saved in the main workbook."""
    by_control = {}
    for line in PO_LINES:
        by_control.setdefault(line[0], []).append(line)
    for control, group in by_control.items():
        data = report(control, "Receiving", date(2026, 1, 5))
        rows = []
        for _, desc, po, pack, qty, dim, weight, unit, total, _ in group:
            row = {h: "" for h in fsr_storage.ITEM_LINE_HEADERS}
            row.update({"Description of Goods": desc, "PO Number": po,
                        "Packaging": pack, "Quantity": qty, "Dimensions": dim,
                        "Weights": weight, "Unit Price": unit,
                        "Total Price": total})
            rows.append(row)
        data["item_lists"][0]["rows"] = rows
        fsr_storage.write_report_to_excel(main_path(g), data, True)


def begin(g, activity="Withdrawal", so="SO-WD-1"):
    g["choose_condition"]("Good Order")
    g["set_entry"](g["SO_number_entry"], so)
    g["location_combobox"].set("GUI Warehouse")
    g["schedule_entries"]["activity"].set(activity)
    g["withdrawal_panel"].sync()


def show(g, po="4500001"):
    panel = g["withdrawal_panel"]
    panel.po_entry.delete(0, "end")
    panel.po_entry.insert(0, po)
    panel.find_po()
    return panel


def pick(g, po="4500001", indexes=(0,)):
    panel = show(g, po)
    panel.add_lines([str(i) for i in indexes])
    return panel


def lines(g):
    """The taken lines, as they would be saved."""
    panel = g["withdrawal_panel"]
    return [section.line_values(widgets)
            for section, widgets in panel.linked_lines()]


def set_qty(g, index, text):
    panel = g["withdrawal_panel"]
    section, widgets = panel.linked_lines()[index]
    panel.edit_quantity(section, widgets)
    cell = section.cell(widgets, "Quantity")
    cell.delete(0, "end")
    cell.insert(0, text)
    return panel.commit_quantity()


def titles(answers, kind=None):
    return answers.titles(kind)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean(answers):
    assert not [c for c in answers.calls if c[0] == "showerror"], answers.calls


def double_click(widget, x, y):
    """Two presses in a row, as a mouse sends them."""
    for _ in range(2):
        widget.event_generate("<ButtonPress-1>", x=x, y=y)
        widget.event_generate("<ButtonRelease-1>", x=x, y=y)


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


# ---------- 1. Activity + form ----------

@pytest.mark.parametrize("activity, form, shown", [
    ("Withdrawal", "Default", True),
    ("withdrawal", "Default", True),
    ("Receiving", "Default", False),
    ("", "Default", False),
    ("Withdrawal", "Containerized", False),
    ("Withdrawal", "Loading", False),
    ("Receiving", "Containerized", False),
    ("Receiving", "Loading", False),
])
def test_panel_only_for_withdrawal_on_default_form(app, activity, form, shown):
    g, _ = app
    g["set_item_form"](form)
    begin(g, activity)
    panel = g["withdrawal_panel"]
    assert panel.applies() is shown
    assert bool(panel.frame.grid_info()) is shown


def test_item_lists_stay_on_screen_with_the_picker(app):
    g, _ = app
    begin(g)
    pick(g)
    assert g["item_lists_frame"].grid_info()
    assert g["new_frame_button"].grid_info()


def test_panel_has_no_second_list_or_quantity_box(app):
    g, _ = app
    begin(g)
    panel = g["withdrawal_panel"]
    children = list(walk(panel.frame))
    assert [w for w in children if isinstance(w, ttk.Treeview)] == \
        [panel.source_tree]
    assert not [w for w in children if isinstance(w, ttk.Combobox)]
    buttons = [w.cget("text") for w in children if isinstance(w, ttk.Button)]
    assert "All in the Item List" in buttons
    assert "Add Selected Lines" not in buttons and "Apply" not in buttons
    entries = [w for w in children if isinstance(w, ttk.Entry)]
    assert entries == [panel.po_entry]


def test_refusing_to_leave_keeps_the_lines_and_puts_activity_back(app):
    g, answers = app
    begin(g)
    panel = pick(g)
    answers.yes = False
    g["schedule_entries"]["activity"].set("Receiving")
    assert panel.context_changed() is False
    assert g["schedule_entries"]["activity"].get() == "Withdrawal"
    assert len(lines(g)) == 1


def test_refusing_to_change_form_keeps_the_lines(app):
    g, answers = app
    begin(g)
    pick(g)
    answers.yes = False
    g["item_form_var"].set("Loading")
    g["choose_item_form"]()
    assert g["item_form_var"].get() == "Default"
    assert g["item_frames"][0].form == "Default"
    assert len(lines(g)) == 1


def test_agreeing_to_leave_discards_only_taken_lines_after_asking(app):
    g, answers = app
    begin(g)
    panel = pick(g, indexes=(0, 1))
    section = g["item_frames"][0]
    typed = section.rows[2]
    g["set_entry"](section.cell(typed, "Description of Goods"), "Typed")
    g["schedule_entries"]["activity"].set("Receiving")
    assert panel.context_changed() is True
    assert "PO-Linked Withdrawal" in titles(answers, "askyesno")
    assert lines(g) == []
    assert [r["Description of Goods"] for r in section.values()] == ["Typed"]


# ---------- 2. + 3. PO lookup and lines ----------

def test_valid_po_lists_every_line_and_adds_none(app):
    g, _ = app
    begin(g)
    panel = show(g)
    tree = panel.source_tree
    assert [tree.item(i, "values")[1] for i in tree.get_children()] == \
        ["1", "2", "3"]
    assert tree.item("2", "values")[2:] == \
        ("OLD-2", "Cable", "12.5", "12.5", "m", "Roll")
    assert lines(g) == []


def test_a_new_receiving_report_can_be_picked_at_once(app):
    g, _ = app
    begin(g)
    fill = rec("FSR-209901-0700", date(2026, 1, 6), "", 5, po="4500777")
    fsr_storage.write_report_to_excel(main_path(g), fill, True)
    assert len(show(g, "4500777").found) == 1


@pytest.mark.parametrize("text, title", [
    ("9999", "PO Not Found"), ("n/a", "PO Not Usable"),
    ("Consolidated", "PO Not Usable"), ("", "PO Not Usable"),
])
def test_unusable_po_says_so_and_stays_editable(app, text, title):
    g, answers = app
    begin(g)
    panel = show(g, text)
    assert title in titles(answers)
    assert panel.po_entry.get() == text
    assert str(panel.po_entry.cget("state")) == "normal"
    assert lines(g) == []


def test_lines_with_unreadable_quantity_are_left_out_and_counted(app):
    g, answers = app
    begin(g)
    tree = show(g, "4500003").source_tree
    assert [tree.item(i, "values")[3] for i in tree.get_children()] == ["Seal"]
    assert "Lines Left Out" in titles(answers, "showwarning")


def test_po_in_a_shared_cell_is_explained_and_not_offered(app):
    g, answers = app
    begin(g)
    assert not show(g, "7000").source_tree.get_children()
    message = next(m for _, t, m in answers.calls if t == "PO Not Found")
    assert "several" in message


def test_quantity_is_called_received_not_original_on_screen(app):
    g, _ = app
    tree = g["withdrawal_panel"].source_tree
    headings = [tree.heading(c, "text") for c in tree["columns"]]
    assert "Received Qty" in headings
    assert not any("Original" in h for h in headings)


def test_double_click_adds_that_line_to_the_item_list(app):
    g, _ = app
    begin(g)
    panel = show(g)
    g["notebook"].select(g["items_tab"])
    window = g["window"]
    window.update()
    tree = panel.source_tree
    x, y, width, height = tree.bbox("1")
    double_click(tree, x + 5, y + height // 2)
    window.update()
    row = lines(g)[0]
    assert len(lines(g)) == 1 and row[wd.LINE_NO_HEADER] == "2"
    # into the visible Item List, filled from that line
    section = g["item_frames"][0]
    cells = section.rows[0]
    assert section.cell(cells, "Description of Goods").get() == "Pump"
    assert section.cell(cells, "PO Number").get() == "4500001"
    assert section.cell(cells, "Quantity").get() == "7"
    assert section.cell(cells, "UOM").get() == "pcs"
    assert g["document_entries"]["po_number"].get() == "4500001"


def test_double_click_on_a_heading_adds_nothing(app):
    g, _ = app
    begin(g)
    panel = show(g)
    g["notebook"].select(g["items_tab"])
    g["window"].update()
    double_click(panel.source_tree, 20, 5)
    g["window"].update()
    assert lines(g) == []


def test_all_button_adds_every_line_shown(app):
    g, _ = app
    begin(g)
    panel = show(g)
    panel.add_all()
    assert [r[wd.LINE_NO_HEADER] for r in lines(g)] == ["1", "2", "3"]
    assert [r["Description of Goods"] for r in lines(g)] == \
        ["Pump", "Pump", "Cable"]


def test_same_line_is_blocked_the_second_time(app):
    g, answers = app
    begin(g)
    panel = pick(g, indexes=(0, 2))
    panel.add_all()
    assert [r[wd.LINE_NO_HEADER] for r in lines(g)] == ["1", "3", "2"]
    assert "Not Added" in titles(answers, "showwarning")


def test_taken_lines_go_after_typed_lines_and_never_replace_them(app):
    g, _ = app
    begin(g)
    section = g["item_frames"][0]
    g["set_entry"](section.cell(section.rows[0], "Description of Goods"), "Typed")
    pick(g)
    assert [r["Description of Goods"] for r in section.values()] == \
        ["Typed", "Pump"]


def test_more_lines_than_rows_grow_the_item_list(app):
    g, _ = app
    begin(g)
    panel = show(g)
    section = g["item_frames"][0]
    section.set_values([{"Description of Goods": f"T{n}"} for n in range(5)])
    panel.add_all()
    assert len(section.rows) == 8 and len(lines(g)) == 3


def test_taken_line_is_locked_except_findings_and_clears_for_the_next_report(app):
    g, _ = app
    begin(g)
    pick(g)
    section = g["item_frames"][0]
    cells = section.rows[0]
    for header in ("Description of Goods", "PO Number", "Quantity", "UOM",
                   "Unit Price", "Total Price"):
        assert str(section.cell(cells, header).cget("state")) == "readonly"
    assert str(section.cell(cells, "Findings").cget("state")) == "normal"
    g["new_report"](confirm=False)
    fresh = g["item_frames"][0].rows[0]
    assert not is_linked(fresh)
    assert str(g["item_frames"][0].cell(fresh, "Quantity").cget("state")) == "normal"
    assert g["item_frames"][0].cell(fresh, "PO Number").get() == ""


def test_remove_clicked_line_keeps_the_others(app):
    g, answers = app
    begin(g)
    panel = show(g)
    panel.add_all()
    section, widgets = panel.linked_lines()[1]
    panel.line_clicked(section, widgets)
    panel.remove_clicked()
    assert [r[wd.LINE_NO_HEADER] for r in lines(g)] == ["1", "3"]
    panel.remove_clicked()      # nothing clicked now
    assert "Remove Line" in titles(answers)


# ---------- what is left of a line ----------

def test_partial_withdrawal_shows_as_remaining_on_the_next_report(app):
    g, answers = app
    begin(g, so="SO-WD-PART1")
    panel = pick(g)
    set_qty(g, 0, "40")
    assert g["save_report"]() is True
    # the list on screen is brought up to date by the save
    assert panel.source_tree.item("0", "values")[4:6] == ("100", "60")

    g["new_report"](confirm=False)
    begin(g, so="SO-WD-PART2")
    panel = show(g)
    assert panel.source_tree.item("0", "values")[4:6] == ("100", "60")
    panel.add_lines(["0"])
    assert lines(g)[0]["Quantity"] == "60"
    assert lines(g)[0][wd.RECEIVED_HEADER] == "100"
    assert set_qty(g, 0, "61") is False
    assert "Withdrawal Quantity" in titles(answers, "showwarning")
    assert lines(g)[0]["Quantity"] == "60"
    assert g["save_report"]() is True

    # nothing left: not offered any more
    g["new_report"](confirm=False)
    begin(g, so="SO-WD-PART3")
    panel = show(g)
    assert [panel.source_tree.item(i, "values")[1]
            for i in panel.source_tree.get_children()] == ["2", "3"]


def test_fully_withdrawn_po_says_so(app):
    g, answers = app
    begin(g, so="SO-WD-FULL")
    panel = show(g, "4500003")
    panel.add_all()
    assert g["save_report"]() is True
    g["new_report"](confirm=False)
    begin(g)
    answers.calls.clear()
    show(g, "4500003")
    assert "Fully Withdrawn" in titles(answers)


def test_editing_a_saved_report_can_use_its_own_quantity_again(app):
    g, answers = app
    begin(g, so="SO-WD-OWN")
    pick(g)
    set_qty(g, 0, "40")
    assert g["save_report"]() is True
    assert set_qty(g, 0, "100") is True
    assert g["save_report"]() is True
    clean(answers)


def test_withdrawal_does_not_change_the_receiving_report(app):
    g, _ = app
    before = sha(main_path(g))
    begin(g, so="SO-WD-SRC")
    pick(g)
    set_qty(g, 0, "40")
    assert g["save_report"]() is True
    assert sha(main_path(g)) == before


def test_save_updates_po_master_and_withdrawn_item(app):
    g, answers = app
    begin(g, so="SO-WD-LISTS")
    pick(g)
    set_qty(g, 0, "40")
    assert g["save_report"]() is True
    folder = main_path(g).parent
    master = list(load_workbook(folder / "PO_Master.xlsx").worksheets[0]
                  .iter_rows(values_only=True))
    assert ("OLD-1", "4500001", "60 pcs") in [(r[0], r[2], r[4]) for r in master]
    withdrawn = list(load_workbook(folder / "Withdrawn_Item.xlsx").worksheets[0]
                     .iter_rows(values_only=True))
    assert withdrawn[0][-1] == "Date Withdrawn"
    assert withdrawn[-1][2] == "4500001" and withdrawn[-1][4] == "40 pcs"
    assert withdrawn[-1][-1].date() == date.today()
    clean(answers)


def test_open_list_in_excel_does_not_lose_the_report(app, monkeypatch):
    g, answers = app
    begin(g, so="SO-WD-LISTOPEN")
    pick(g)

    def locked(_):
        raise PermissionError("in use")
    monkeypatch.setattr(wd, "sync_item_lists", locked)
    assert g["save_report"]() is True
    assert wd.owns_report(main_path(g), g["control_entry"].get())
    message = next(m for _, t, m in answers.calls if t == "Report Saved - Note")
    assert "PO_Master" in message


# ---------- 4. quantities ----------

def test_double_click_opens_the_quantity_for_editing(app):
    g, _ = app
    begin(g)
    panel = pick(g)
    g["notebook"].select(g["items_tab"])
    g["window"].update()
    section, widgets = panel.linked_lines()[0]
    cell = section.cell(widgets, "Quantity")
    assert str(cell.cget("state")) == "readonly"
    double_click(cell, 3, 3)
    g["window"].update()
    assert str(cell.cget("state")) == "normal"
    cell.delete(0, "end")
    cell.insert(0, "40")
    cell.focus_force()      # key presses go to the focused window
    g["window"].update()
    cell.event_generate("<Return>")
    g["window"].update()
    assert str(cell.cget("state")) == "readonly"
    assert lines(g)[0]["Quantity"] == "40"


def test_double_click_leaves_typed_lines_alone(app):
    g, _ = app
    begin(g)
    section = g["item_frames"][0]
    panel = g["withdrawal_panel"]
    panel.edit_quantity(section, section.rows[0])
    assert panel.editing is None


@pytest.mark.parametrize("text, accepted", [
    ("40", True), ("100", True), ("0", False), ("-1", False), ("abc", False),
    ("101", False), ("1.5", False),
])
def test_quantity_rules_on_a_pcs_line(app, text, accepted):
    g, answers = app
    begin(g)
    pick(g)
    assert set_qty(g, 0, text) is accepted
    assert lines(g)[0]["Quantity"] == (text if accepted else "100")
    assert lines(g)[0][wd.RECEIVED_HEADER] == "100"
    assert ("Withdrawal Quantity" in titles(answers, "showwarning")) \
        is (not accepted)


def test_quantity_recalculates_total_and_clears_weight_on_partial(app):
    g, _ = app
    begin(g)
    pick(g)
    assert lines(g)[0]["Weights"] == "50 kg"
    assert set_qty(g, 0, "40") is True
    row = lines(g)[0]
    assert (row["Total Price"], row["Weights"]) == ("400.00", "")


def test_decimals_are_allowed_on_a_metre_line(app):
    g, _ = app
    begin(g)
    pick(g, indexes=(2,))
    assert set_qty(g, 0, "2.5") is True
    assert set_qty(g, 0, "12.6") is False
    assert lines(g)[0]["Quantity"] == "2.5"


def test_save_finishes_a_quantity_still_being_edited(app):
    g, _ = app
    begin(g, so="SO-WD-PENDING")
    panel = pick(g)
    section, widgets = panel.linked_lines()[0]
    panel.edit_quantity(section, widgets)
    cell = section.cell(widgets, "Quantity")
    cell.delete(0, "end")
    cell.insert(0, "25")
    assert g["save_report"]() is True
    saved = wd.read_report(book_path(g), g["control_entry"].get())
    assert saved["item_lists"][0]["rows"][0]["Quantity"] == "25"


# ---------- 5. save, retrieve, edit, search ----------

def test_save_open_edit_goes_to_the_withdrawal_workbook_only(app):
    g, answers = app
    main_before = sha(main_path(g))
    begin(g, so="SO-WD-SAVE")
    pick(g, indexes=(0, 2))
    set_qty(g, 0, "40")
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    assert sha(main_path(g)) == main_before
    assert wd.owns_report(main_path(g), control)
    saved = wd.read_report(book_path(g), control)
    assert saved["general_information"]["so_number"] == "SO-WD-SAVE"
    assert [r["Quantity"] for r in saved["item_lists"][0]["rows"]] == ["40", "12.5"]

    # the printed form: the withdrawal quantity in the existing Quantity column
    form = load_workbook(main_path(g).parent / "Report Forms"
                         / f"{control}_Report.xlsx")
    text = [str(c.value) for row in form["Cargo Details"].iter_rows()
            for c in row if c.value is not None]
    assert "4500001" in text and "Pump" in text
    assert "40 pcs" in text
    assert not any(cell.strip().startswith("100") for cell in text)

    # re-opened, edited, saved again: same report, same workbook
    g["new_report"](confirm=False)
    g["load_report_into_form"](control, "excel")
    panel = g["withdrawal_panel"]
    assert panel.owned and [r["Quantity"] for r in lines(g)] == ["40", "12.5"]
    assert g["item_lists_frame"].grid_info()
    ids = [r[wd.LINE_ID_HEADER] for r in lines(g)]
    set_qty(g, 1, "1.5")
    assert g["save_report"]() is True
    assert g["control_entry"].get() == control
    assert sha(main_path(g)) == main_before
    rows = wd.read_report(book_path(g), control)["item_lists"][0]["rows"]
    assert [(r[wd.LINE_ID_HEADER], r["Quantity"]) for r in rows] == \
        [(ids[0], "40"), (ids[1], "1.5")]
    assert sum(r[0] == control for r in wd.list_reports(book_path(g))) == 1
    clean(answers)


def test_typed_line_beside_taken_lines_saves_with_them_and_has_no_limit(app):
    g, answers = app
    begin(g, so="SO-WD-MIXED")
    section = g["item_frames"][0]
    pick(g)
    extra = section.rows[1]
    g["set_entry"](section.cell(extra, "Description of Goods"), "Typed")
    g["set_entry"](section.cell(extra, "Quantity"), "999")
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    assert g["save_report"]() is True       # again: Line IDs kept, no duplicates
    rows = wd.read_report(book_path(g), control)["item_lists"][0]["rows"]
    assert [(r["Description of Goods"], r["Quantity"], r[wd.RECEIVED_HEADER])
            for r in rows] == [("Pump", "100", "100"), ("Typed", "999", "")]
    clean(answers)


def test_saved_po_linked_report_cannot_change_activity(app):
    g, answers = app
    begin(g, so="SO-WD-LOCK")
    pick(g)
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    g["schedule_entries"]["activity"].set("Receiving")
    assert g["save_report"]() is False
    assert g["schedule_entries"]["activity"].get() == "Withdrawal"
    assert wd.read_report(book_path(g), control)["inspection_schedule"][
        "activity"] == "Withdrawal"


def test_removing_every_line_of_a_saved_report_is_refused(app):
    g, answers = app
    begin(g, so="SO-WD-EMPTY")
    panel = pick(g)
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    panel.line_clicked(*panel.linked_lines()[0])
    panel.remove_clicked()
    assert g["save_report"]() is False
    assert "Save Error" in titles(answers, "showerror")
    assert len(wd.read_report(book_path(g), control)["item_lists"][0]["rows"]) == 1


def test_locked_workbook_keeps_everything_on_the_form(app, monkeypatch):
    g, answers = app
    begin(g, so="SO-WD-LOCKED")
    pick(g)
    set_qty(g, 0, "33")

    def locked(*_):
        raise PermissionError("in use")
    monkeypatch.setattr(wd.os, "replace", locked)
    assert g["save_report"]() is False
    assert "File In Use" in titles(answers, "showerror")
    assert lines(g)[0]["Quantity"] == "33"

    monkeypatch.undo()
    assert g["save_report"]() is True


def _dialog_tree(g):
    dialog = next(w for w in g["window"].winfo_children()
                  if isinstance(w, tkinter.Toplevel)
                  and w.title() == "Open Saved Report")
    tree = next(w for w in walk(dialog) if isinstance(w, ttk.Treeview))
    return tree, dialog


def test_open_dialog_searches_both_workbooks_and_labels_withdrawals(app):
    g, answers = app
    begin(g, so="SO-WD-DIALOG")
    pick(g)
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    fsr_storage.write_report_to_excel(
        main_path(g), rec("FSR-209901-0901", date(2026, 10, 1), "C", 5), True)
    g["open_saved_report_dialog"]()
    tree, dialog = _dialog_tree(g)
    try:
        rows = {i: tree.item(i, "values") for i in tree.get_children()}
        assert rows[control][0] == f"{control} [Withdrawal]"
        assert rows["FSR-209901-0901"][0] == "FSR-209901-0901"
        assert "4500001" in rows[control][5]
    finally:
        dialog.destroy()


def test_mysql_copy_is_not_used_to_open_a_po_linked_report(app, monkeypatch):
    g, answers = app
    begin(g, so="SO-WD-MYSQL")
    pick(g)
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    g["new_report"](confirm=False)

    class NoMysql:
        def load_report(self, _):
            raise AssertionError("MySQL must not be read for this report")
    monkeypatch.setitem(live(g), "db_mysql", NoMysql())
    g["load_report_into_form"](control, "mysql")
    assert lines(g)[0][wd.LINE_NO_HEADER] == "1"
    clean(answers)


def test_mysql_failure_is_reported_like_any_other_report(app, monkeypatch):
    g, answers = app
    begin(g, so="SO-WD-MYSQLFAIL")
    pick(g)

    class Failing:
        @staticmethod
        def is_enabled():
            return True

        @staticmethod
        def save_report(_):
            raise OSError("server away")

        save_master_lists = save_report

        @staticmethod
        def explain_error(error):
            return str(error)
    monkeypatch.setitem(live(g), "db_mysql", Failing())
    assert g["save_report"]() is True
    assert "Report Saved - Note" in titles(answers, "showwarning")
    assert wd.owns_report(main_path(g), g["control_entry"].get())


# ---------- 6. no usable PO: the manual route ----------

def test_po_without_receiving_lines_means_manual_entry_in_the_main_workbook(app):
    g, answers = app
    begin(g, so="SO-WD-MANUAL")
    panel = show(g, "NOT-RECEIVED")
    assert "PO Not Found" in titles(answers)

    g["set_entry"](g["document_entries"]["po_number"], "n/a")
    g["item_frames"][0].set_values([{"Description of Goods": "Typed Pump",
                                     "Quantity": "4", "UOM": "PCS"}])
    before = sha(book_path(g)) if book_path(g).exists() else None
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    assert not wd.owns_report(main_path(g), control)
    saved = fsr_storage.read_report(main_path(g), control)
    row = saved["item_lists"][0]["rows"][0]
    assert (row["Description of Goods"], row["Quantity"]) == ("Typed Pump", "4")
    # nothing about it claims a link to the Receiving data
    assert wd.RECEIVED_HEADER not in row and "entry_source" not in saved
    assert (sha(book_path(g)) if book_path(g).exists() else None) == before

    # opened again it stays manual, in the main workbook
    g["new_report"](confirm=False)
    g["load_report_into_form"](control, "excel")
    panel = g["withdrawal_panel"]
    assert not panel.linked()
    pick(g)
    assert lines(g) == []
    assert "Saved in the Main Workbook" in titles(answers, "showwarning")


# ---------- 7. control numbers in the program ----------

def test_next_report_number_skips_both_workbooks(app):
    g, answers = app
    begin(g, so="SO-WD-NUM")
    pick(g)
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    g["new_report"](confirm=False)
    assert g["control_entry"].get() > control


# ---------- 8. stock in the program ----------

def test_saved_withdrawal_reaches_the_snapshot_once_and_reduces_its_batch(app):
    g, answers = app
    begin(g, so="SO-WD-STOCK")
    g["location_combobox"].set("WH-1")
    pick(g)
    set_qty(g, 0, "30")
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    snapshot = store.load_snapshot(main_path(g))
    assert sum(t.control_no == control for t in snapshot.transactions) == 1
    line = next(t for t in snapshot.transactions if t.control_no == control).lines[0]
    assert (line.quantity, line.activity) == (30, "Withdrawal")
    item = next(i for i in snapshot.inventory.items
                if i.identity == "RCV-OLD-1-1-01")
    assert item.is_counted(line)


# ---------- 10. exports ----------

def test_print_uses_the_default_form_and_the_withdrawal_quantity(app):
    g, answers = app
    begin(g, so="SO-WD-PRINT")
    pick(g)
    set_qty(g, 0, "40")
    forms, notes, _ = g["create_report_forms"](g["excel_state"]["path"],
                                               g["collect_report_data"]())
    assert not notes
    book = load_workbook(forms[0])
    assert book.sheetnames == ["First Page", "Cargo Details"]
    row = next(r for r in book["Cargo Details"].iter_rows(values_only=True)
               if "Pump" in r)
    assert "4500001" in row
    assert any(str(v).startswith("40") for v in row if v is not None)


def test_weekly_summary_includes_po_linked_reports(app):
    g, answers = app
    begin(g, so="SO-WD-WEEKLY")
    pick(g)
    assert g["save_report"]() is True
    today = date.today()
    found = g["weekly_rows_from_excel"](today, today)
    assert any("SO-WD-WEEKLY" in map(str, line) for line in found)


# ---------- 11. configured workbook paths ----------

def test_changing_the_excel_file_refuses_the_withdrawal_workbook(app, monkeypatch):
    g, answers = app
    before = g["excel_state"]["path"]
    monkeypatch.setitem(live(g), "choose_excel_path",
                        lambda: main_path(g).with_name("Withdrawal_Reports.xlsx"))
    g["change_excel_file"]()
    assert g["excel_state"]["path"] == before
    assert "Change Excel File" in titles(answers, "showwarning")


def test_withdrawal_book_follows_the_configured_workbook(app, tmp_path):
    g, _ = app
    before = g["excel_state"]["path"]
    g["excel_state"]["path"] = tmp_path / "Elsewhere.xlsx"
    try:
        assert book_path(g) == (tmp_path / "Withdrawal_Reports.xlsx").resolve()
        assert g["withdrawal_panel"].host.main_path() == \
            tmp_path / "Elsewhere.xlsx"
    finally:
        g["excel_state"]["path"] = before


def test_demo_mode_refuses_a_path_outside_the_demo_folder(app, tmp_path, monkeypatch):
    g, _ = app
    before = g["excel_state"]["path"]
    monkeypatch.setitem(live(g), "DEMO_MODE", True)
    g["excel_state"]["path"] = tmp_path / "Field_Survey_Reports.xlsx"
    try:
        with pytest.raises(ValueError, match="outside"):
            g["withdrawal_book"]()
    finally:
        g["excel_state"]["path"] = before


# ---------- 12. the other workflows ----------

@pytest.mark.parametrize("activity, form", [
    ("Receiving", "Default"), ("Receiving", "Containerized"),
    ("Receiving", "Loading"), ("Withdrawal", "Containerized"),
    ("Withdrawal", "Loading"),
])
def test_other_workflows_save_to_the_main_workbook_only(app, activity, form):
    g, answers = app
    existing = sha(book_path(g)) if book_path(g).exists() else None
    g["set_item_form"](form)
    begin(g, activity, so=f"SO-OTHER-{activity}-{form}")
    assert not g["withdrawal_panel"].applies()
    g["item_frames"][0].set_values([{"Description of Goods": "Coil",
                                     "Quantity": "4", "UOM": "PCS"}])
    assert g["save_report"]() is True
    control = g["control_entry"].get()
    saved = fsr_storage.read_report(main_path(g), control)
    assert saved["item_form"] == form
    assert saved["item_lists"][0]["rows"][0]["Quantity"] == "4"
    assert not wd.owns_report(main_path(g), control)
    assert (sha(book_path(g)) if book_path(g).exists() else None) == existing
    clean(answers)
