"""Print Report goes straight to a printer, never to a PDF viewer.

The Windows default printer is used without asking. When it is not
available (removed or offline) the user is asked once, from the printers
that are ready, and that answer is used until the default is back.
Change Printer... picks a printer to use instead of the default."""
import sys
import types

import pytest

import fsr_forms


# ---------------------------------------------------------------------------
# Which printers are ready (no GUI)
# ---------------------------------------------------------------------------

def test_offline_printers_are_not_ready():
    assert fsr_forms.printer_is_ready(0, 0x240)
    assert not fsr_forms.printer_is_ready(0x80, 0x248)     # status Offline
    assert not fsr_forms.printer_is_ready(0, 0xE40)        # Use Printer Offline


def test_only_ready_printers_are_offered(monkeypatch):
    fake = types.SimpleNamespace(
        PRINTER_ENUM_LOCAL=2, PRINTER_ENUM_CONNECTIONS=4,
        EnumPrinters=lambda flags, name, level: [
            {"pPrinterName": "EPSON L120", "Status": 0, "Attributes": 0xA40},
            {"pPrinterName": "Office HP", "Status": 0, "Attributes": 0x240},
            {"pPrinterName": "Switched Off", "Status": 0x80,
             "Attributes": 0x248},
            {"pPrinterName": "Set Offline", "Status": 0, "Attributes": 0xE40},
        ],
        GetDefaultPrinter=lambda: "Office HP",
    )
    monkeypatch.setattr(fsr_forms.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32print", fake)
    assert fsr_forms.available_printers() == (
        ["EPSON L120", "Office HP"], "Office HP")


def test_excel_gets_the_printer_with_its_port(monkeypatch):
    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def query(key, name):
        if name == "EPSON L120":
            return "winspool,Ne02:", 1
        raise FileNotFoundError(name)

    fake = types.SimpleNamespace(HKEY_CURRENT_USER=1,
                                 OpenKey=lambda *a: Key(), QueryValueEx=query)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert fsr_forms.excel_printer_name("EPSON L120") == "EPSON L120 on Ne02:"
    assert fsr_forms.excel_printer_name("Unknown") == "Unknown"


def test_windows_prints_the_workbooks_not_a_pdf(monkeypatch, tmp_path):
    printed = []
    monkeypatch.setattr(fsr_forms.sys, "platform", "win32")
    monkeypatch.setattr(fsr_forms, "print_forms_with_excel",
                        lambda forms, printer, black=False:
                        printed.append((forms, printer, black)))
    monkeypatch.setattr(fsr_forms, "make_report_pdf",
                        lambda *a: pytest.fail("no PDF is made to print"))
    monkeypatch.setattr(fsr_forms.os, "startfile",
                        lambda *a: pytest.fail("nothing opens in a viewer"),
                        raising=False)

    forms = [tmp_path / "A_Report.xlsx"]
    assert fsr_forms.send_to_printer(forms, "EPSON L120") == "printed"
    assert fsr_forms.send_to_printer(forms, "EPSON L120",
                                     black_only=True) == "printed"
    assert printed == [(forms, "EPSON L120", False),
                       (forms, "EPSON L120", True)]


class FakeSheet:
    def __init__(self):
        self.PageSetup = types.SimpleNamespace(BlackAndWhite=False)


class FakeWorkbook:
    def __init__(self, log):
        self.log = log
        self.Worksheets = [FakeSheet(), FakeSheet()]

    def PrintOut(self):
        self.log.append(("print", [s.PageSetup.BlackAndWhite
                                   for s in self.Worksheets]))

    def Close(self, save):
        self.log.append(("close", save))


def fake_excel(monkeypatch, log):
    class Books:
        def Open(self, path, ReadOnly):
            log.append(("open", ReadOnly))
            return FakeWorkbook(log)

    excel = types.SimpleNamespace(Workbooks=Books(),
                                  Quit=lambda: log.append(("quit",)))
    client = types.SimpleNamespace(DispatchEx=lambda name: excel)
    win32com = types.SimpleNamespace(client=client)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(sys.modules, "pythoncom", types.SimpleNamespace(
        CoInitialize=lambda: None, CoUninitialize=lambda: None))
    monkeypatch.setattr(fsr_forms, "excel_printer_name", lambda p: p)
    return excel


@pytest.mark.parametrize("black_only", [False, True])
def test_black_only_uses_excels_black_and_white_setting(monkeypatch,
                                                        black_only):
    log = []
    excel = fake_excel(monkeypatch, log)
    fsr_forms.print_forms_with_excel(["a.xlsx"], "EPSON L120", black_only)
    assert excel.ActivePrinter == "EPSON L120"
    assert log == [("open", True), ("print", [black_only, black_only]),
                   ("close", False), ("quit",)]         # file not saved


# ---------------------------------------------------------------------------
# Asking once, and again only when the printer is not available (GUI)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_print_home")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


@pytest.fixture
def printing(app, monkeypatch):
    g, answers = app
    ready = {"printers": ["EPSON L120", "Office HP"], "default": "Office HP"}
    asked = []
    sent = []

    def ask(parent, printers, preselect, message, note=""):
        asked.append((list(printers), preselect, message))
        return asked_answer["printer"]

    asked_answer = {"printer": "EPSON L120"}
    monkeypatch.setitem(g, "available_printers",
                        lambda: (list(ready["printers"]), ready["default"]))
    monkeypatch.setitem(g, "ask_printer", ask)
    monkeypatch.setitem(g, "send_to_printer",
                        lambda forms, printer, pdf=None, black_only=False:
                        sent.append(printer) or colours.append(black_only)
                        or "printed")
    colours = []
    g["colours"] = colours
    monkeypatch.setitem(g, "run_with_progress",
                        lambda parent, msg, work, done, **k: done(work(), None))
    for key in ("printer", "fallback_printer", "print_in"):
        g["settings"].pop(key, None)
    answers.calls.clear()
    yield g, answers, ready, asked, asked_answer, sent
    for key in ("printer", "fallback_printer", "print_in"):
        g["settings"].pop(key, None)


def press_print(g):
    forms = ["Report Forms/C-1_Report.xlsx"]
    g["print_report_forms"](forms, {"control_no": "C-1"}, g["window"])


@pytest.mark.gui
def test_the_default_printer_is_used_without_asking(printing):
    g, answers, ready, asked, asked_answer, sent = printing

    press_print(g)
    press_print(g)
    assert asked == []
    assert sent == ["Office HP", "Office HP"]           # Windows default
    assert "printer" not in g["settings"]
    assert not answers.titles("showerror")


@pytest.mark.gui
def test_no_default_ready_asks_once_from_the_ready_printers(printing):
    g, answers, ready, asked, asked_answer, sent = printing
    ready["printers"] = ["EPSON L120", "Microsoft Print to PDF"]  # HP is off

    press_print(g)
    assert len(asked) == 1
    printers, preselect, message = asked[0]
    assert printers == ["EPSON L120", "Microsoft Print to PDF"]
    assert '"Office HP" is not available' in message
    assert sent == ["EPSON L120"]

    press_print(g)
    press_print(g)
    assert len(asked) == 1                              # asked one time only
    assert sent == ["EPSON L120"] * 3
    assert g["load_settings"]()["fallback_printer"] == "EPSON L120"

    ready["printers"] = ["EPSON L120", "Office HP"]     # the default is back
    press_print(g)
    assert sent[-1] == "Office HP"
    assert len(asked) == 1


@pytest.mark.gui
def test_the_one_picked_last_time_is_asked_again_only_when_it_is_gone(
        printing):
    g, answers, ready, asked, asked_answer, sent = printing
    g["settings"]["fallback_printer"] = "EPSON L120"
    ready["printers"] = ["Microsoft Print to PDF"]      # HP and EPSON off
    asked_answer["printer"] = "Microsoft Print to PDF"

    press_print(g)
    assert len(asked) == 1
    assert asked[0][0] == ["Microsoft Print to PDF"]
    assert sent == ["Microsoft Print to PDF"]


@pytest.mark.gui
def test_cancel_prints_nothing_and_keeps_no_choice(printing):
    g, answers, ready, asked, asked_answer, sent = printing
    ready["printers"] = ["EPSON L120"]
    asked_answer["printer"] = None

    press_print(g)
    assert len(asked) == 1
    assert sent == []
    assert "fallback_printer" not in g["settings"]


@pytest.mark.gui
def test_no_ready_printer_says_so_and_prints_nothing(printing):
    g, answers, ready, asked, asked_answer, sent = printing
    ready["printers"] = []

    press_print(g)
    assert asked == []
    assert sent == []
    assert answers.titles("showerror") == ["No Printer Available"]


@pytest.mark.gui
def test_change_printer_is_used_instead_of_the_default(printing):
    g, answers, ready, asked, asked_answer, sent = printing

    assert g["choose_printer"](g["window"], change=True) == "EPSON L120"
    assert asked[0][1] == "Office HP"                   # default picked first
    assert g["settings"]["printer"] == "EPSON L120"
    assert g["printer_in_use"]() == "Printer: EPSON L120"

    press_print(g)
    assert sent == ["EPSON L120"]
    assert len(asked) == 1

    asked_answer["printer"] = "Office HP"               # back to the default
    g["choose_printer"](g["window"], change=True)
    assert "printer" not in g["settings"]
    assert g["printer_in_use"]() == "Printer: the Windows default printer"


def print_window(g):
    g["show_output_dialog"]("Print / PDF", "Report C-1 is ready",
                            "x.xlsx", ["x_Report.xlsx"], {"control_no": "C-1"})
    g["window"].update()
    return [c for c in g["window"].winfo_children()
            if c.winfo_class() == "Toplevel"
            and c.wm_title() == "Print / PDF"][-1]


@pytest.mark.gui
def test_color_or_black_only_is_chosen_and_kept(printing):
    g, answers, ready, asked, asked_answer, sent = printing
    colours = g["colours"]

    dialog = print_window(g)
    try:
        choice = dialog.print_color_var
        assert choice.get() == "color"                  # color at first
        press_print(g)
        assert colours == [False]
        assert answers.calls[-1][2].endswith('"Office HP" in color.')

        choice.set("black")                             # Black only
        dialog.children_radio = [w for row in dialog.winfo_children()
                                 for w in row.winfo_children()
                                 if w.winfo_class() == "TRadiobutton"]
        [w for w in dialog.children_radio
         if w.cget("text") == "Black only"][0].invoke()
        assert g["load_settings"]()["print_in"] == "black"
        press_print(g)
        assert colours == [False, True]
        assert answers.calls[-1][2].endswith("in black only.")
    finally:
        dialog.destroy()

    dialog = print_window(g)                            # kept next time
    try:
        assert dialog.print_color_var.get() == "black"
    finally:
        dialog.destroy()
