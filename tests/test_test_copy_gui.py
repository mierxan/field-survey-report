"""The program run from the source folder says TEST COPY in its title bar
and shows the refusal of the real database as "Server inactive"."""
import time

import pytest

import db_mysql

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import gui_harness as h
    home = tmp_path_factory.mktemp("fsr_test_copy_home")
    try:
        g, answers = h.start_app(home)
    except Exception as error:          # no display available
        pytest.skip(f"GUI cannot start here: {error}")
    yield g, answers
    h.stop_app(g, answers)


def live(g):
    return g["save_report"].__globals__


def test_title_bar_says_test_copy(app):
    g, _ = app
    assert live(g)["TEST_COPY"] is True
    g["new_report"](confirm=False)
    assert g["window"].title().startswith("TEST COPY - Field Survey Report")
    g["set_entry"](g["SO_number_entry"], "SO-TITLE")
    g["update_status"]()
    assert "TEST COPY - Field Survey Report" in g["window"].title()


def test_title_warns_when_the_real_database_is_allowed(app, monkeypatch):
    g, _ = app

    class Allowed:
        PRODUCTION_DATABASE = db_mysql.PRODUCTION_DATABASE
        ALLOW_REAL = db_mysql.ALLOW_REAL

        @staticmethod
        def load_config():
            return {"database": "field_survey", "user": "fsr_app",
                    "allow_real_database": True}

    monkeypatch.setitem(live(g), "db_mysql", Allowed)
    monkeypatch.setitem(live(g), "MYSQL_ALLOWED", True)
    assert live(g)["title_prefix"]() == "TEST COPY (REAL DATABASE) - "
    Allowed.load_config = staticmethod(lambda: {
        "database": "field_survey_test", "user": "fsr_test"})
    assert live(g)["title_prefix"]() == "TEST COPY - "


def test_real_database_settings_show_as_inactive_with_the_reason(
        app, monkeypatch, tmp_path):
    """The source copy configured for the real database: no connection is
    made, the status says why."""
    g, _ = app
    monkeypatch.setattr(db_mysql, "CONFIG_FILE", tmp_path / "db_config.json")
    monkeypatch.setattr(db_mysql, "SECRET_STORE", None)
    db_mysql.write_config({"enabled": True, "host": "localhost",
                           "port": 3306, "user": "fsr_app", "password": "x",
                           "database": "field_survey"})
    monkeypatch.setattr(db_mysql, "is_enabled",
                        lambda: db_mysql.load_config() is not None)
    monkeypatch.setitem(live(g), "db_mysql", db_mysql)

    live(g)["check_mysql_status"]()
    end = time.time() + 10
    while time.time() < end and str(live(g)["mysql_label"].cget(
            "text")) != "Server inactive":
        g["window"].update()
        time.sleep(0.05)

    assert str(live(g)["mysql_label"].cget("text")) == "Server inactive"
    assert "TEST COPY" in live(g)["mysql_state"]["text"]
    assert "will not connect to the real database" in         live(g)["mysql_state"]["text"]
