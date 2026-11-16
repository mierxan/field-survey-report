"""The interactive Dashboard of the Weekly Summary export
(fsr_weekly_dashboard): the typed Data rows, the dropdowns, the formulas the
cards and charts read, and the Withdrawal delivery destinations.

That the formulas give the right numbers was also checked by opening an
exported file in Excel 2007 and changing the dropdowns (docs/DASHBOARD.md).
"""
import re
import zipfile
from datetime import date

from openpyxl import Workbook, load_workbook

import fsr_weekly_dashboard as wd
from warehouse.exports import _own_label_formats


def line(so, day, activity="Receiving", supplier="Supplier A",
         destination="", condition="Good Order", quantity="5",
         shipment="Import"):
    row = [""] * 28
    row[wd.SO], row[wd.DATE], row[wd.ACTIVITY] = so, day, activity
    row[wd.SHIPMENT], row[wd.SUPPLIER] = shipment, supplier
    row[wd.DESTINATION], row[wd.QUANTITY] = destination, quantity
    row[wd.CONDITION] = condition
    return row


ROWS = [
    # two lines of one Receiving report
    (line("SO-1", "02-Mar-2031", quantity="10"), "FSR-T-0001"),
    (line("SO-1", "02-Mar-2031", quantity="1,250.5"), "FSR-T-0001"),
    (line("SO-2", "09-Mar-2031", supplier="Supplier B",
          condition="Bad Order"), "FSR-T-0002"),
    # Withdrawals: same SO number, different reports
    (line("SO-9", "10-Mar-2031", "Withdrawal", "Depot", "Site North"),
     "FSR-T-0003"),
    (line("SO-9", "10-Mar-2031", "Withdrawal", "Depot", "Site North"),
     "FSR-T-0003"),
    (line("SO-9", "30-Mar-2031", "Withdrawal", "Depot", "Site South",
          condition=""), "FSR-T-0004"),
]
PACKAGES = {"FSR-T-0001": 4, "FSR-T-0003": 2, "FSR-T-0004": 7}


def make(rows=ROWS, packages=PACKAGES, first=date(2031, 3, 1),
         last=date(2031, 3, 31)):
    wb = Workbook()
    wb.active.title = "Weekly Summary"
    wd.add_dashboard(wb, "Weekly Summary Report - March 2031 (whole month)",
                     [r for r, _ in rows], [c for _, c in rows], first, last,
                     packages=packages)
    return wb


def test_the_data_rows_count_each_report_once():
    records = wd.data_rows([r for r, _ in ROWS], [c for _, c in ROWS],
                           PACKAGES)
    assert [r[10] for r in records] == [1, 0, 1, 1, 0, 1]   # transactions
    assert [r[11] for r in records] == [4, None, None, 2, None, 7]
    assert [r[3] for r in records] == [1, 1, 2, 2, 2, 5]    # weeks
    assert records[1][9] == 1250.5                         # a number
    assert records[0][6] == wd.NOT_RECORDED                 # no destination
    assert records[5][8] == wd.NOT_RECORDED                 # no condition


def test_the_workbook_has_the_dashboard_first_and_hidden_helpers(tmp_path):
    wb = make()
    assert wb.sheetnames == ["Dashboard", "Weekly Summary", "Data", "Calc"]
    assert wb.active.title == "Dashboard"
    assert wb["Data"].sheet_state == "hidden"
    assert wb["Calc"].sheet_state == "hidden"
    assert wb.calculation.fullCalcOnLoad is True
    path = tmp_path / "week.xlsx"
    wb.save(path)
    _own_label_formats(path)
    back = load_workbook(path)
    assert back.sheetnames[0] == "Dashboard"
    with zipfile.ZipFile(path) as z:
        charts = [n for n in z.namelist() if n.startswith("xl/charts/")]
        assert len(charts) == 7       # with the Withdrawal destinations
        for name in charts:
            # every label format is the chart's own, so Excel uses it
            text = z.read(name).decode("utf-8")
            assert not re.search(r'<numFmt formatCode="[^"]*" />', text)


def test_the_four_dropdowns_offer_what_the_data_holds():
    wb = make()
    ws = wb["Dashboard"]
    rules = {cell: rule.formula1 for rule in ws.data_validations.dataValidation
             for cell in str(rule.sqref).split()}
    assert rules == {"A6": "=ActivityChoices", "E6": "=WeekChoices",
                     "I6": "=ConditionChoices", "M6": "=SupplierChoices"}
    calc = wb["Calc"]

    def choices(name):
        ref = wb.defined_names[name].attr_text.split("!")[1].replace("$", "")
        return [c.value for row in calc[ref] for c in row]
    assert choices("ActivityChoices") == ["All", "Receiving", "Withdrawal"]
    assert choices("WeekChoices") == [
        "All weeks", "Week 1 (1-7)", "Week 2 (8-14)", "Week 3 (15-21)",
        "Week 4 (22-28)", "Week 5 (29-31)"]
    assert choices("ConditionChoices") == ["All", "(not recorded)",
                                           "Bad Order", "Good Order"]
    assert choices("SupplierChoices") == ["All", "Depot", "Supplier A",
                                          "Supplier B"]
    assert [ws[c].value for c in ("A6", "E6", "I6", "M6")] == [
        "All", "All weeks", "All", "All"]


def test_one_week_exported_starts_on_that_week():
    wb = make(rows=ROWS[3:5], first=date(2031, 3, 8), last=date(2031, 3, 14))
    assert wb["Dashboard"]["E6"].value == "Week 2 (8-14)"


def test_the_cards_read_the_formulas_over_all_the_data():
    wb = make()
    calc, ws = wb["Calc"], wb["Dashboard"]
    n = len(ROWS) + 1
    assert calc["B7"].value.startswith(f"=SUMIFS(Data!$K$2:$K${n},")
    assert f"Data!$D$2:$D${n},\">=\"&Calc!$B$4" in calc["B7"].value
    assert calc["B8"].value.startswith(f"=SUMIFS(Data!$M$2:$M${n},")
    assert calc["B9"].value.startswith(f"=SUMIFS(Data!$J$2:$J${n},")
    assert calc["B10"].value.endswith('Data!$I$2:$I$7,"Good Order")')
    assert ws["A10"].value == "=Calc!$B$7"
    assert ws["E10"].value == "=Calc!$B$8"
    assert ws["I10"].value == "=Calc!$B$9"
    # "All" matches everything; a name is matched exactly
    assert calc["B1"].value.startswith('=IF(Dashboard!$A$6="All","*",')
    assert "SUBSTITUTE" in calc["B3"].value


def test_names_with_wildcards_are_matched_exactly():
    assert wd._exact('A*B?C~"D') == '"=A~*B~?C~~""D"'


def test_the_withdrawal_destinations_table_follows_the_choices():
    wb = make()
    calc, ws = wb["Calc"], wb["Dashboard"]
    rows = [r for r in calc.iter_rows(values_only=True)
            if r[0] in ("Site North", "Site South")]
    assert [r[0] for r in rows] == ["Site North", "Site South"]
    north = rows[0]
    assert all('Data!$E$2:$E$7,"=Withdrawal"' in f for f in north[1:4])
    assert "Data!$L$2" in north[2] and "Data!$M$2" in north[3]
    titles = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row)]
    assert any(str(t).startswith("WITHDRAWAL  ·  DELIVERY DESTINATIONS")
               for t in titles)
    total = [r for r in range(1, ws.max_row + 1)
             if ws.cell(row=r, column=1).value == "TOTAL WITHDRAWAL"]
    assert ws.cell(row=total[0], column=5).value == "=Calc!$B$12"
    assert ws.conditional_formatting        # the in-cell bars


def test_without_withdrawals_the_section_says_so():
    wb = make(rows=ROWS[:3])
    ws = wb["Dashboard"]
    texts = [c.value for row in ws.iter_rows() for c in row if c.value]
    assert "No Withdrawal reports in this period." in texts
    assert len(ws._charts) == 6


def test_many_suppliers_keep_the_top_ones_and_add_up_the_rest():
    rows = [(line(f"SO-{i}", "05-Mar-2031", supplier=f"Supplier {i:02d}"),
             f"FSR-T-{i:04d}") for i in range(14)]
    wb = make(rows=rows, packages={})
    calc = wb["Calc"]
    labels = [r[0] for r in calc.iter_rows(values_only=True)
              if str(r[0]).startswith(("Supplier ", "Others"))]
    assert len(labels) == wd.TOP_SUPPLIERS
    assert labels[-1] == "Others (5)"
