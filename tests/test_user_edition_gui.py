"""The User (site) edition, started for real: no MySQL anywhere, no import,
and Export Master Data writes the file for the owner."""
import json
import sys

import pytest

pytestmark = pytest.mark.gui


def export_now(window):
    """Press Export... in the Export Master Data window."""
    def buttons(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TButton":
                yield child
            yield from buttons(child)
    (button,) = [b for b in buttons(window) if b.cget("text") == "Export..."]
    button.invoke()


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    import db_mysql
    home = tmp_path_factory.mktemp("fsr_user_home")
    # a MySQL config that WOULD be used by the Owner edition
    private = home / "json" / "private"
    private.mkdir(parents=True)
    (private / "db_config.json").write_text(json.dumps(
        {"enabled": True, "user": "fsr_app", "host": "127.0.0.1"}),
        encoding="utf-8")
    import fsr_storage
    saved_enabled = db_mysql.is_enabled
    saved_initials = dict(fsr_storage._control_initials)
    sys.modules.pop("fsr_edition", None)
    try:
        g, answers = h.start_app(home, {"FSR_EDITION": "user"})
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    g["home"] = home
    yield g, answers
    h.stop_app(g, answers)
    import os
    os.environ.pop("FSR_EDITION", None)
    sys.modules.pop("fsr_edition", None)
    db_mysql.is_enabled = saved_enabled
    fsr_storage._control_initials.update(saved_initials)   # the test user's TST


def test_user_edition_never_uses_mysql(app):
    g, _ = app
    assert g["IS_OWNER_EDITION"] is False
    assert g["db_mysql"].is_enabled() is False
    assert "dots_canvas" not in g and "check_mysql_status" not in g
    menu = g["account_menu"]
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
              if menu.type(i) == "command"]
    assert "MySQL Settings..." not in labels
    assert not g["import_master_button"].winfo_ismapped()
    assert g["export_master_button"].winfo_manager() == "pack"


def test_user_edition_exports_master_data(app, tmp_path):
    g, answers = app
    target = tmp_path / "FSR_Master_Data_site.json"
    dialog = g["filedialog"]
    original = dialog.asksaveasfilename
    dialog.asksaveasfilename = lambda **_: str(target)
    try:
        g["export_master_button"].invoke()
        # the window asks All data / only the chosen reports; All is preset
        window = g["master_export_state"]["dialog"]
        export_now(window)
        assert not window.winfo_exists()
    finally:
        dialog.asksaveasfilename = original
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["format"] == "fsr-master-data"
    assert "consignee_list" in data["master_lists"]
    assert any(c[1] == "Export Master Data" and c[0] == "showinfo"
               for c in answers.calls)
