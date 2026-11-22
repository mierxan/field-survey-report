"""The S.O. No. and the Port of an Incident Report are the report's own SO
Number and Location (owner, 23 November 2026: every site has its own SO
number; neither can be changed on the Incident Report). The printed form
takes them from the report, also for a report saved or imported with other
values on its incident card."""
from datetime import date

from openpyxl import load_workbook

import fsr_forms
import fsr_storage
from factories import report


def bad_order(so="SO-SITE-7", location="Yard 7"):
    data = report("FSR-ZZI-202611-0001", "Receiving", date(2026, 11, 2),
                  location, [{"qty": 1, "unit": "Crate", "desc": "Crate"}],
                  condition="Bad Order", so=so)
    data["incident_reports"] = [{
        "vessel": "MV One", "voyage": "V-9", "client": "Con",
        "so_number": "SO-OLD", "port": "Old Yard", "date": "02-Nov-2026",
        "operation": "Receiving", "lines": ["Crate crushed"]}]
    return data


def test_incident_cards_take_so_and_port_from_the_report():
    cards = fsr_storage.incident_reports_of(bad_order())
    assert (cards[0]["so_number"], cards[0]["port"]) == ("SO-SITE-7",
                                                         "Yard 7")
    # everything else on the card is kept as it was
    assert (cards[0]["vessel"], cards[0]["voyage"], cards[0]["operation"],
            cards[0]["lines"]) == ("MV One", "V-9", "Receiving",
                                   ["Crate crushed"])


def test_every_card_of_the_report_gets_them():
    data = bad_order()
    data["incident_reports"].append(dict(data["incident_reports"][0],
                                         so_number="", port="Elsewhere"))
    cards = fsr_storage.incident_reports_of(data)
    assert [(c["so_number"], c["port"]) for c in cards] == \
        [("SO-SITE-7", "Yard 7")] * 2


def test_printed_incident_report_shows_the_reports_so_and_location(tmp_path):
    out = tmp_path / "incident.xlsx"
    pages = fsr_forms.build_incident_workbook(fsr_forms.INCIDENT_TEMPLATE,
                                              out, bad_order())
    assert pages == 1
    sheet = load_workbook(out).worksheets[0]
    cells = fsr_forms.INCIDENT_HEADER_CELLS
    assert sheet[cells["so_number"]].value == "SO-SITE-7"
    assert sheet[cells["port"]].value == "Yard 7"
    assert sheet[cells["vessel"]].value == "MV One"
    assert sheet[f"A{fsr_forms.INCIDENT_FIRST_LINE_ROW}"].value == \
        "Crate crushed"
