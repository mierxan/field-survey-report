"""Share with Destination in the real program window (see gui_harness.py).
Everything happens in a temporary FSR_HOME folder with invented reports."""
import pytest

import fsr_shipment
from test_shipment import digest, withdrawal


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_home_shipment")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def widgets(widget, kind):
    for child in widget.winfo_children():
        if child.winfo_class() == kind:
            yield child
        yield from widgets(child, kind)


def press(dialog, text):
    (button,) = [b for b in widgets(dialog, "TButton")
                 if b.cget("text") == text]
    button.invoke()


def trees(dialog):
    return list(widgets(dialog, "Treeview"))


def test_packing_lists_go_to_their_destinations_as_separate_files(
        app, tmp_path, monkeypatch):
    g, answers = app
    path = g["excel_state"]["path"]
    number = "FSR-TST-209901-0700"
    destinations = g["master_data"][g["DESTINATION_LIST_KEY"]]
    for name in ("NORTH PLANT", "SOUTH PLANT"):
        if name not in destinations:
            destinations.append(name)
    g["data_store"](path).write_report(withdrawal(number), False)
    g["load_report_into_form"](number)
    before = digest(path.parent)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(g["filedialog"], "askdirectory",
                        lambda **_: str(out))

    dialog = g["open_share_shipment"]()
    reports_tree, pl_tree = trees(dialog)
    # the saved Withdrawal open on the form is chosen; its destination is
    # one known destination, so every Packing List starts there
    assert reports_tree.item(reports_tree.selection()[0], "values")[0] == \
        number
    rows = [pl_tree.item(i, "values") for i in pl_tree.get_children()]
    assert [(r[0], r[3]) for r in rows] == [
        ("NOR111126-001 & 002", "NORTH PLANT"),
        ("NOR111126-003", "NORTH PLANT"),
        (fsr_shipment.NO_PACKING_LIST_LABEL, "NORTH PLANT"),
        ("SOU111126-001", "NORTH PLANT")]

    # the last two go to SOUTH PLANT
    (box,) = list(widgets(dialog, "TCombobox"))
    pl_tree.selection_set(pl_tree.get_children()[2:])
    box.set("SOUTH PLANT")
    press(dialog, "Assign")
    assert [pl_tree.item(i, "values")[3] for i in pl_tree.get_children()] \
        == ["NORTH PLANT", "NORTH PLANT", "SOUTH PLANT", "SOUTH PLANT"]

    answers.calls.clear()
    press(dialog, "Create Shipment Files...")
    g["window"].update()
    assert not [c for c in answers.calls if c[0] == "showerror"]
    files = sorted(out.iterdir())
    assert [f.name.split("_to_")[1].rsplit("_", 1)[0] for f in files] == [
        "NORTH_PLANT", "SOUTH_PLANT"]
    north, south = (fsr_shipment.read_file(f) for f in files)
    assert [p["number"] for p in north["packing_lists"]] == [
        "NOR111126-001 & 002", "NOR111126-003"]
    assert [p["number"] for p in south["packing_lists"]] == [
        "", "SOU111126-001"]
    assert north["from"]["initials"] == g["current_user"]["initials"]
    assert digest(path.parent) == before        # the report is unchanged
    dialog.destroy()


def test_removing_every_destination_makes_no_file(app, tmp_path,
                                                  monkeypatch):
    g, answers = app
    path = g["excel_state"]["path"]
    number = "FSR-TST-209901-0701"
    g["data_store"](path).write_report(withdrawal(number, "Unknown"), False)
    g["load_report_into_form"](number)
    dialog = g["open_share_shipment"]()
    _, pl_tree = trees(dialog)
    # "Unknown" is not a known destination: nothing is assigned yet
    assert {pl_tree.item(i, "values")[3] for i in pl_tree.get_children()} \
        == {""}
    (create,) = [b for b in widgets(dialog, "TButton")
                 if b.cget("text") == "Create Shipment Files..."]
    assert str(create.cget("state")) == "disabled"
    pl_tree.selection_set(pl_tree.get_children()[:1])
    (box,) = list(widgets(dialog, "TCombobox"))
    box.set("NORTH PLANT")
    press(dialog, "Assign")
    assert str(create.cget("state")) == "normal"
    press(dialog, "Remove Destination")
    assert str(create.cget("state")) == "disabled"
    dialog.destroy()
