"""Export Master Data in the real program window (see gui_harness.py): all
data, or only the chosen reports - a PO-linked Withdrawal among them.
Everything happens in a temporary FSR_HOME folder with invented reports."""
import json
from datetime import date

import pytest

from factories import report

RECEIVING = "FSR-TST-209901-0801"
WITHDRAWAL = "FSR-TST-209901-0802"
OTHER = "FSR-TST-209901-0803"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_home_master_export")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    store = g["data_store"](g["excel_state"]["path"])
    store.write_report(report(
        RECEIVING, "Receiving", date(2099, 1, 5), "GUI Yard",
        [{"qty": 2, "unit": "Crate", "desc": "Invented pump", "po": "PO-GUI",
          "ref": f"RCV-{RECEIVING}-1-01"}], so="SO-GUI-R"), False)
    store.write_report(report(
        OTHER, "Receiving", date(2099, 1, 6), "GUI Yard",
        [{"qty": 1, "unit": "Box", "desc": "Invented valve"}],
        so="SO-GUI-O"), False)
    taken = report(WITHDRAWAL, "Withdrawal", date(2099, 1, 7), "GUI Yard",
                   [{"qty": 1, "unit": "Crate", "desc": "Invented pump",
                     "po": "PO-GUI", "ref": f"RCV-{RECEIVING}-1-01"}],
                   so="SO-GUI-W")
    taken["other_item_forms"] = {}
    store.write_withdrawal_report(taken, False)
    yield g, answers
    h.stop_app(g, answers)


def widgets(widget, kind):
    for child in widget.winfo_children():
        if child.winfo_class() == kind:
            yield child
        yield from widgets(child, kind)


def button(dialog, text):
    (found,) = [b for b in widgets(dialog, "TButton")
                if b.cget("text") == text]
    return found


def tree_of(dialog):
    (tree,) = list(widgets(dialog, "Treeview"))
    return tree


def rows(dialog):
    tree = tree_of(dialog)
    return {tree.item(iid, "values")[0]: iid for iid in tree.get_children()}


def exported(target):
    return [r["control_no"] for r in json.loads(
        target.read_text(encoding="utf-8"))["reports"]]


def test_the_window_asks_all_or_chosen_and_lists_both_workbooks(app):
    g, _ = app
    dialog = g["export_master_data"]()
    try:
        texts = [r.cget("text") for r in widgets(dialog, "TRadiobutton")]
        assert texts[0].startswith("All data: every saved report (3)")
        assert texts[1].startswith("Only the reports I choose")
        listed = rows(dialog)
        assert set(listed) == {RECEIVING, WITHDRAWAL, OTHER}
        values = tree_of(dialog).item(listed[WITHDRAWAL], "values")
        assert values[1] == "SO-GUI-W"
        assert values[5] == "Withdrawal (PO-linked)"
        # a second click on Export Master Data shows the same window
        assert g["export_master_data"]() is dialog
    finally:
        dialog.destroy()


def test_all_data_exports_every_report(app, tmp_path, monkeypatch):
    g, answers = app
    target = tmp_path / "all.json"
    asked = {}

    def save_as(**options):
        asked.update(options)
        return str(target)
    monkeypatch.setattr(g["fsr_master_export_ui"].filedialog,
                        "asksaveasfilename", save_as)
    dialog = g["export_master_data"]()
    answers.calls.clear()
    button(dialog, "Export...").invoke()
    assert not [c for c in answers.calls if c[0] == "showerror"]
    assert sorted(exported(target)) == sorted([RECEIVING, WITHDRAWAL, OTHER])
    assert "_" + date.today().strftime("%Y-%m-%d") in asked["initialfile"]
    assert not dialog.winfo_exists()


def test_only_the_chosen_withdrawal_is_exported(app, tmp_path, monkeypatch):
    g, answers = app
    target = tmp_path / "one.json"
    asked = {}

    def save_as(**options):
        asked.update(options)
        return str(target)
    monkeypatch.setattr(g["fsr_master_export_ui"].filedialog,
                        "asksaveasfilename", save_as)
    dialog = g["export_master_data"]()
    radio = list(widgets(dialog, "TRadiobutton"))[1]
    radio.invoke()
    assert str(button(dialog, "Export...").cget("state")) == "disabled"
    tree = tree_of(dialog)
    tree.selection_set(rows(dialog)[WITHDRAWAL])
    g["window"].update()
    assert str(button(dialog, "Export...").cget("state")) == "normal"
    answers.calls.clear()
    button(dialog, "Export...").invoke()
    assert not [c for c in answers.calls if c[0] == "showerror"]
    assert exported(target) == [WITHDRAWAL]
    assert WITHDRAWAL in asked["initialfile"]
    (info,) = [c for c in answers.calls if c[0] == "showinfo"]
    assert "1 report(s)" in str(info) and WITHDRAWAL in str(info)


def test_choosing_a_report_switches_to_only_these_and_search_keeps_it(
        app, tmp_path, monkeypatch):
    g, answers = app
    target = tmp_path / "two.json"
    monkeypatch.setattr(g["fsr_master_export_ui"].filedialog,
                        "asksaveasfilename", lambda **_: str(target))
    dialog = g["export_master_data"]()
    tree = tree_of(dialog)
    tree.selection_set(rows(dialog)[OTHER])
    g["window"].update()
    choice = list(widgets(dialog, "TRadiobutton"))[1]
    assert str(choice.cget("value")) == "chosen"
    assert "selected" in choice.state()
    # the search shows another report; the one chosen before stays chosen
    (search,) = list(widgets(dialog, "TEntry"))
    search.insert(0, "SO-GUI-W")
    g["window"].update()
    assert set(rows(dialog)) == {WITHDRAWAL}
    tree.selection_set(rows(dialog)[WITHDRAWAL])
    g["window"].update()
    button(dialog, "Export...").invoke()
    assert sorted(exported(target)) == sorted([OTHER, WITHDRAWAL])


def test_cancel_writes_nothing(app, tmp_path, monkeypatch):
    g, _ = app
    monkeypatch.setattr(g["fsr_master_export_ui"].filedialog,
                        "asksaveasfilename", lambda **_: "")
    dialog = g["export_master_data"]()
    button(dialog, "Export...").invoke()
    assert dialog.winfo_exists()            # still open, nothing written
    button(dialog, "Cancel").invoke()
    assert not dialog.winfo_exists()
    assert not list(tmp_path.iterdir())
