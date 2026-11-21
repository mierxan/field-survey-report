"""The interactive Dashboard of the Weekly Summary export (Inspection
Reports > Weekly Summary > Export).

The client picks from four dropdowns on the sheet - Activity, Week, Cargo
Condition, Supplier - and the KPI cards and charts change at once: they
are Excel formulas (SUMIFS) over a hidden Data sheet, so it needs no
macros, shows no security warning and works in every Excel since 2007.
On the charts the chosen week (or supplier) is coloured and the rest grey.

Layout of the workbook: Dashboard, Weekly Summary (the table as before),
then the hidden sheets Data (one typed row per line) and Calc (the
formulas the cards and charts read).
"""
from collections import Counter, OrderedDict
from datetime import date, timedelta

from fsr_storage import parse_date, to_number
from warehouse import dashboard as dash
from warehouse.exports import NAVY, SLATE_DARK, nice_step

# positions in a weekly row (fsr_weekly.report_to_weekly_rows)
SO, DATE, ACTIVITY, SHIPMENT, SUPPLIER = 0, 1, 2, 3, 4
DESTINATION, QUANTITY, CONDITION = 7, 20, 27
WITHDRAWAL = "Withdrawal"
NOT_RECORDED = "(not recorded)"
ALL = "All"
ALL_WEEKS = "All weeks"
TOP_SUPPLIERS = 10
TOP_DESTINATIONS = 8
GREY = "CBD5E1"
COLUMNS = 16                        # A..P; a card is 4 columns, a chart 8
CHART_ROWS = 18

# the four dropdowns: (label, first column, cell)
SELECTORS = (("ACTIVITY", 1, "A6"), ("WEEK", 5, "E6"),
             ("CARGO CONDITION", 9, "I6"), ("SUPPLIER", 13, "M6"))


def week_of(day):
    """Week 1 = days 1-7 ... Week 5 = day 29 to the month's end."""
    return min((day - 1) // 7 + 1, 5)


def week_label(week, first, last):
    return f"Week {week} ({first}-{last})"


def _text(value):
    return str(value or "").strip() or NOT_RECORDED


def data_rows(rows, controls, packages=None):
    """One typed row per weekly line: (control, date, day, week, activity,
    supplier, destination, shipment, condition, quantity, first line of
    its report, Declared Goods packages of the report on its first line)."""
    packages = packages or {}
    seen = set()
    result = []
    for control, line in zip(controls, rows):
        day = parse_date(line[DATE])
        day = day.date() if hasattr(day, "date") else None
        quantity = to_number(line[QUANTITY])
        first = control not in seen
        seen.add(control)
        result.append((
            control, day, day.day if day else None,
            week_of(day.day) if day else None, _text(line[ACTIVITY]),
            _text(line[SUPPLIER]), _text(line[DESTINATION]),
            _text(line[SHIPMENT]), _text(line[CONDITION]),
            quantity if isinstance(quantity, (int, float)) else None,
            1 if first else 0, packages.get(control) if first else None))
    return result


def _quote(text):
    """A text as an Excel formula string."""
    return '"' + str(text).replace('"', '""') + '"'


def _exact(text):
    """A SUMIFS criterion matching exactly this text (wildcards escaped)."""
    escaped = str(text).replace("~", "~~").replace("*", "~*") \
        .replace("?", "~?")
    return _quote("=" + escaped)


def add_dashboard(wb, title, rows, controls, first_day, last_day,
                  packages=None):
    """Add the Dashboard (first) and the hidden Data and Calc sheets to the
    Weekly Summary workbook `wb`. rows: the weekly rows; controls: the
    Control # of each row; first_day / last_day: the exported period;
    packages: {Control #: Declared Goods packages}."""
    from openpyxl.chart import BarChart, DoughnutChart, Reference
    from openpyxl.chart.label import DataLabelList
    from openpyxl.chart.series import DataPoint
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.drawing.line import LineProperties
    from openpyxl.formatting.rule import DataBarRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.workbook.defined_name import DefinedName
    from warehouse import chart_style
    from openpyxl.worksheet.datavalidation import DataValidation

    records = data_rows(rows, controls, packages)
    n = len(records) + 1                    # last data row

    # ---------- Data (hidden): one typed row per line ----------
    data = wb.create_sheet("Data")
    data.append(["Control #", "Date", "Day", "Week", "Activity", "Supplier",
                 "Destination", "Shipment type", "Cargo Condition",
                 "Quantity", "Transaction", "Packages", "Line"])
    for record in records:
        data.append([*record, 1])          # the last column counts lines
        data.cell(row=data.max_row, column=2).number_format = "dd-mmm-yyyy"
    data.sheet_state = "hidden"

    def col(letter):
        return f"Data!${letter}$2:${letter}${n}"

    TX, PKG, LINE, QTY = col("K"), col("L"), col("M"), col("J")
    DAY, WEEK = col("C"), col("D")
    ACT, SUP, DEST, COND = col("E"), col("F"), col("G"), col("I")

    # ---------- the choices ----------
    def ranked(index, flag=10):
        counts = Counter()
        for record in records:
            counts[record[index]] += record[flag]
        return [name for name, _ in sorted(
            counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))]

    activities = sorted({r[4] for r in records}, key=str.casefold)
    conditions = sorted({r[8] for r in records}, key=str.casefold)
    suppliers = ranked(5)
    days = []
    current = first_day
    while current <= last_day:
        days.append(current)
        current += timedelta(days=1)
    weeks = OrderedDict()
    for day in days:
        weeks.setdefault(week_of(day.day), []).append(day.day)
    week_names = [week_label(w, d[0], d[-1]) for w, d in weeks.items()]

    # ---------- Calc (hidden): what the cards and charts read ----------
    calc = wb.create_sheet("Calc")
    calc.sheet_state = "hidden"

    def esc(cell):
        return (f'SUBSTITUTE(SUBSTITUTE(SUBSTITUTE({cell},"~","~~"),'
                f'"*","~*"),"?","~?")')

    choice = {"act": "Dashboard!$A$6", "week": "Dashboard!$E$6",
              "cond": "Dashboard!$I$6", "sup": "Dashboard!$M$6"}
    calc["A1"], calc["B1"] = "Activity", \
        f'=IF({choice["act"]}="{ALL}","*","="&{esc(choice["act"])})'
    calc["A2"], calc["B2"] = "Condition", \
        f'=IF({choice["cond"]}="{ALL}","*","="&{esc(choice["cond"])})'
    calc["A3"], calc["B3"] = "Supplier", \
        f'=IF({choice["sup"]}="{ALL}","*","="&{esc(choice["sup"])})'
    calc["A4"], calc["B4"] = "From week", \
        f'=IF(LEFT({choice["week"]},5)="Week ",VALUE(MID({choice["week"]},6,1)),1)'
    calc["A5"], calc["B5"] = "To week", \
        f'=IF(LEFT({choice["week"]},5)="Week ",VALUE(MID({choice["week"]},6,1)),5)'

    week_crit = f'{WEEK},">="&Calc!$B$4,{WEEK},"<="&Calc!$B$5'
    act_crit = f"{ACT},Calc!$B$1"
    cond_crit = f"{COND},Calc!$B$2"
    sup_crit = f"{SUP},Calc!$B$3"

    def crit(*parts):
        return ",".join(parts)

    every = crit(act_crit, cond_crit, sup_crit, week_crit)
    calc["A7"], calc["B7"] = "Transactions", f"=SUMIFS({TX},{every})"
    calc["A8"], calc["B8"] = "Lines", f"=SUMIFS({LINE},{every})"
    calc["A9"], calc["B9"] = "Quantity", f"=SUMIFS({QTY},{every})"
    calc["A10"], calc["B10"] = "Good", \
        f'=SUMIFS({TX},{every},{COND},"Good Order")'
    calc["A11"], calc["B11"] = "Bad", \
        f'=SUMIFS({TX},{every},{COND},"Bad Order")'

    tables = {}                         # name -> (first row, last row)
    row = 13

    def table(name, headings, lines):
        """Rows of formulas: (label, *formulas). Returns its range."""
        nonlocal row
        calc.cell(row=row, column=1, value=name).font = Font(bold=True)
        for index, heading in enumerate(headings, start=2):
            calc.cell(row=row, column=index, value=heading)
        first = row + 1
        for offset, (label, *cells) in enumerate(lines):
            calc.cell(row=first + offset, column=1, value=label)
            for index, value in enumerate(cells, start=2):
                calc.cell(row=first + offset, column=index, value=value)
        last = first + len(lines) - 1
        tables[name] = (row, first, last)
        row = last + 2

    no_week = crit(act_crit, cond_crit, sup_crit)

    def in_week(week):
        return f"AND({week}>=Calc!$B$4,{week}<=Calc!$B$5)"

    day_lines = []
    for day in days:
        number = day.day
        count = f"SUMIFS({TX},{DAY},{number},{no_week})"
        qty = f"SUMIFS({QTY},{DAY},{number},{no_week})"
        week = week_of(number)
        # a month: the day of the month only (31 dates ran together)
        day_lines.append((day.strftime("%d-%b") if len(days) <= 7
                          else str(day.day),
                          f"=IF({in_week(week)},{count},0)",
                          f"=IF({in_week(week)},0,{count})",
                          f"=IF({in_week(week)},{qty},0)",
                          f"=IF({in_week(week)},0,{qty})"))
    table("days", ["Selected", "Other days", "Quantity (selected)",
                   "Quantity (other days)"], day_lines)

    week_lines = []
    for (week, _numbers), name in zip(weeks.items(), week_names):
        count = f"SUMIFS({TX},{WEEK},{week},{no_week})"
        week_lines.append((name, f"=IF({in_week(week)},{count},0)",
                           f"=IF({in_week(week)},0,{count})"))
    table("weeks", ["Selected", "Other weeks"], week_lines)

    table("condition", ["Transactions"],
          [("Good Order", "=Calc!$B$10"), ("Bad Order", "=Calc!$B$11")])
    split = crit(cond_crit, sup_crit, week_crit)
    table("activity", ["Transactions"],
          [(name, f"=SUMIFS({TX},{ACT},{_exact(name)},{split})")
           for name in ("Receiving", "Withdrawal")])

    others_crit = crit(act_crit, cond_crit, week_crit)
    shown = suppliers[:TOP_SUPPLIERS - 1] if len(suppliers) > TOP_SUPPLIERS \
        else suppliers
    supplier_lines = []
    for name in shown:
        count = f"SUMIFS({TX},{SUP},{_exact(name)},{others_crit})"
        chosen = f'OR({choice["sup"]}="{ALL}",{choice["sup"]}={_quote(name)})'
        supplier_lines.append((name, f"=IF({chosen},{count},0)",
                               f"=IF({chosen},0,{count})"))
    if len(suppliers) > len(shown):
        first_supplier = tables_row = row + 1      # rows of the named ones
        rest = (f"SUMIFS({TX},{others_crit})-SUM(B{first_supplier}:"
                f"C{first_supplier + len(shown) - 1})")
        chosen = (f'OR({choice["sup"]}="{ALL}",ISNA(MATCH({choice["sup"]},'
                  f'A{tables_row}:A{tables_row + len(shown) - 1},0)))')
        supplier_lines.append((f"Others ({len(suppliers) - len(shown)})",
                               f"=IF({chosen},{rest},0)",
                               f"=IF({chosen},0,{rest})"))
    table("suppliers", ["Selected", "Other suppliers"], supplier_lines)

    # Withdrawal: where the cargo was delivered (follows the Week, Cargo
    # Condition and Supplier choices; always Withdrawal reports)
    withdrawn = [r for r in records if r[4].casefold() == WITHDRAWAL.casefold()]
    by_place = Counter()
    for r in withdrawn:
        by_place[r[6]] += r[10]
    places = [name for name, _ in sorted(
        by_place.items(), key=lambda kv: (-kv[1], kv[0].casefold()))]
    named = places[:TOP_DESTINATIONS - 1] if len(places) > TOP_DESTINATIONS \
        else places
    wd_crit = crit(f"{ACT},{_exact(WITHDRAWAL)}", cond_crit, sup_crit,
                   week_crit)
    place_lines = [(name, *[f"=SUMIFS({what},{DEST},{_exact(name)},{wd_crit})"
                            for what in (TX, PKG, LINE)])
                   for name in named]
    if len(places) > len(named):
        first_place = row + 1
        last_place = first_place + len(named) - 1
        place_lines.append((f"Others ({len(places) - len(named)})", *[
            f"=SUMIFS({what},{wd_crit})-SUM({letter}{first_place}:"
            f"{letter}{last_place})"
            for what, letter in ((TX, "B"), (PKG, "C"), (LINE, "D"))]))
    if place_lines:
        table("destinations", ["Shipments", "Packages", "Cargo lines"],
              place_lines)
        calc["A12"], calc["B12"] = "Withdrawal shipments", \
            f"=SUMIFS({TX},{wd_crit})"
        calc["C12"] = f"=SUMIFS({PKG},{wd_crit})"
        calc["D12"] = f"=SUMIFS({LINE},{wd_crit})"

    # the dropdown lists
    lists_col = 8
    lists = {"ActivityChoices": [ALL, *activities],
             "WeekChoices": [ALL_WEEKS, *week_names],
             "ConditionChoices": [ALL, *conditions],
             "SupplierChoices": [ALL, *sorted(suppliers, key=str.casefold)]}
    for offset, (name, values) in enumerate(lists.items()):
        column = lists_col + offset
        letter = get_column_letter(column)
        calc.cell(row=1, column=column, value=name)
        for index, value in enumerate(values, start=2):
            calc.cell(row=index, column=column, value=value)
        wb.defined_names[name] = DefinedName(
            name, attr_text=f"Calc!${letter}$2:${letter}${len(values) + 1}")

    # ---------- the Dashboard ----------
    ws = wb.create_sheet("Dashboard", 0)
    wb.active = 0
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 90
    for column in range(1, COLUMNS + 1):
        ws.column_dimensions[get_column_letter(column)].width = 10.5
    last = get_column_letter(COLUMNS)

    def fill(color):
        return PatternFill("solid", fgColor=color)

    def band(at, height, color, text, font):
        ws.merge_cells(f"A{at}:{last}{at}")
        cell = ws.cell(row=at, column=1, value=text)
        cell.font = font
        cell.alignment = Alignment(horizontal="left", vertical="center",
                                   indent=1)
        for column in range(1, COLUMNS + 1):
            ws.cell(row=at, column=column).fill = fill(color)
        ws.row_dimensions[at].height = height

    band(1, 40, NAVY, "INTERACTIVE DASHBOARD",
         Font(bold=True, size=22, color="FFFFFF"))
    band(2, 22, NAVY, title.replace("Weekly Summary Report - ", ""),
         Font(size=12, color="CBD5E1"))
    band(3, 20, dash.BLUE, "Pick from the yellow boxes: the cards and charts "
         "change at once.   ·   Field Survey Report",
         Font(bold=True, size=10, color="FFFFFF"))
    ws.row_dimensions[4].height = 10

    # the dropdowns
    amber = Side(style="medium", color=dash.AMBER)
    defaults = {"A6": ALL, "E6": ALL_WEEKS if len(week_names) > 1
                else week_names[0], "I6": ALL, "M6": ALL}
    sources = dict(zip(("A6", "E6", "I6", "M6"), lists))
    for label, first, cell in SELECTORS:
        letters = (get_column_letter(first), get_column_letter(first + 3))
        ws.merge_cells(f"{letters[0]}5:{letters[1]}5")
        head = ws.cell(row=5, column=first, value=f"▼ {label}")
        head.font = Font(bold=True, size=9, color="475569")
        head.alignment = Alignment(indent=1)
        ws.merge_cells(f"{letters[0]}6:{letters[1]}6")
        box = ws[cell]
        box.value = defaults[cell]
        box.font = Font(bold=True, size=13, color=NAVY)
        box.alignment = Alignment(horizontal="left", vertical="center",
                                  indent=1)
        for column in range(first, first + 4):
            ws.cell(row=6, column=column).fill = fill("FEF3C7")
            ws.cell(row=6, column=column).border = Border(
                top=amber, bottom=amber,
                left=amber if column == first else None,
                right=amber if column == first + 3 else None)
        rule = DataValidation(type="list", formula1=f"={sources[cell]}",
                              allow_blank=False, showDropDown=False)
        rule.error = "Choose from the list."
        rule.errorTitle = "Dashboard"
        rule.prompt = "Choose from the list"
        rule.promptTitle = label.title()
        ws.add_data_validation(rule)
        rule.add(cell)
    ws.row_dimensions[6].height = 26
    ws.merge_cells(f"A7:{last}7")
    ws["A7"] = ('="Showing: "&A6&"   ·   "&E6&"   ·   "&I6&"   ·   "&'
                'IF(M6="All","all suppliers",M6)')
    ws["A7"].font = Font(italic=True, size=10, color="475569")
    ws["A7"].alignment = Alignment(indent=1)

    # the cards: rows 9..13
    white = Side(style="thick", color="FFFFFF")
    cards = [
        ("TRANSACTIONS", "=Calc!$B$7", "inspection reports", dash.BLUE),
        ("LINE ITEMS", "=Calc!$B$8", "Item List lines", dash.TEAL),
        ("TOTAL QUANTITY", "=Calc!$B$9", "all units combined", dash.AMBER),
        ("GOOD / BAD ORDER",
         '=Calc!$B$10&" Good · "&Calc!$B$11&" Bad"',
         '=IF(Calc!$B$10+Calc!$B$11=0,"no condition recorded",'
         'TEXT(Calc!$B$10/(Calc!$B$10+Calc!$B$11),"0%")&" Good Order")',
         dash.GREEN),
    ]
    for index, (label, value, note, color) in enumerate(cards):
        first = index * 4 + 1
        end = first + 3
        accent = Side(style="thick", color=color)
        for r in range(9, 14):
            for column in range(first, end + 1):
                cell = ws.cell(row=r, column=column)
                cell.fill = fill("F8FAFC")
                cell.border = Border(
                    left=white if column == first else None,
                    right=white if column == end else None,
                    top=accent if r == 9 else None,
                    bottom=Side(style="thin", color="E2E8F0")
                    if r == 13 else None)
        letters = (get_column_letter(first), get_column_letter(end))
        for r in (9, 12, 13):
            ws.merge_cells(f"{letters[0]}{r}:{letters[1]}{r}")
        ws.merge_cells(f"{letters[0]}10:{letters[1]}11")
        cells = ((9, label, Font(bold=True, size=10, color="475569")),
                 (10, value, Font(bold=True, size=28 if index < 3 else 20,
                                  color=color)),
                 (12, note, Font(size=9, color="64748B")))
        for r, text, font in cells:
            cell = ws.cell(row=r, column=first, value=text)
            cell.font = font
            cell.alignment = Alignment(horizontal="left", vertical="center",
                                       indent=1, shrink_to_fit=True)
            if r == 10 and index < 3:
                cell.number_format = "#,##0"
    for r, height in ((9, 20), (10, 24), (11, 24), (12, 16), (13, 10)):
        ws.row_dimensions[r].height = height

    # ---------- charts ----------
    totals_by_day = Counter(r[2] for r in records if r[10])
    qty_by_day = Counter()
    for r in records:
        if r[9] is not None and r[2] is not None:
            qty_by_day[r[2]] += r[9]

    def labels_only(values=True, percent=False):
        return DataLabelList(showVal=values, showPercent=percent,
                             showSerName=False, showCatName=False,
                             showLegendKey=False, showLeaderLines=False)

    def ref(name, column, header=False):
        head, first, end = tables[name]
        return Reference(calc, min_col=column,
                         min_row=head if header else first, max_row=end)

    def bars(name, title, columns, colors, top, horizontal=False,
             stacked=True, axis="", labels=True):
        chart = BarChart()
        chart.type = "bar" if horizontal else "col"
        if stacked:
            chart.grouping = "stacked"
            chart.overlap = 100
        for column in columns:
            chart.add_data(ref(name, column, header=True),
                           titles_from_data=True)
        chart.set_categories(ref(name, 1))
        for series, color in zip(chart.series, colors):
            series.graphicalProperties.solidFill = color
            series.graphicalProperties.line.solidFill = color
        if labels:
            first = chart.series[0]
            first.dLbls = labels_only()
            first.dLbls.numFmt = "#,##0;-#,##0;;"
        chart.gapWidth = 50
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        chart.y_axis.majorGridlines.spPr = GraphicalProperties(
            ln=LineProperties(solidFill="E2E8F0"))
        chart.y_axis.numFmt = "#,##0"
        chart.y_axis.scaling.min = 0
        chart.y_axis.majorUnit = nice_step(max(top, 1))
        if horizontal:
            chart.x_axis.scaling.orientation = "maxMin"
            chart.y_axis.crosses = "max"
        if len(columns) > 1:
            chart.legend.position = "b"
        else:
            chart.legend = None
        chart_style.finish(chart, title, axis, horizontal=horizontal)
        if labels and stacked:
            # stacked: the numbers stand inside the coloured bars
            chart.series[0].dLbls.txPr = chart_style.text(bold=True,
                                                          color="FFFFFF")
        return chart

    def ring(name, title, colors):
        chart = DoughnutChart(holeSize=55)
        chart.add_data(ref(name, 2))
        chart.set_categories(ref(name, 1))
        for index, color in enumerate(colors):
            point = DataPoint(idx=index)
            point.graphicalProperties.solidFill = color
            point.graphicalProperties.line.solidFill = "FFFFFF"
            chart.series[0].dPt.append(point)
        chart.dataLabels = labels_only(values=False, percent=True)
        chart.dataLabels.numFmt = "0%;-0%;;"         # no label for 0%
        chart.legend.position = "b"
        return chart_style.finish(chart, title)

    top_day = max(totals_by_day.values() or [1])
    week_totals = Counter(r[3] for r in records if r[10])
    supplier_totals = Counter(r[5] for r in records if r[10])
    start = 15
    placed = [
        (bars("days", "Transactions per Day", [2, 3], [dash.BLUE, GREY],
              top_day, axis="Transactions"), "A", start, True),
        (bars("weeks", "Transactions per Week", [2, 3], [dash.BLUE, GREY],
              max(week_totals.values() or [1])), "A", start + CHART_ROWS,
         False),
        (ring("condition", "Good Order / Bad Order", [dash.GREEN, dash.RED]),
         "I", start + CHART_ROWS, False),
        (bars("suppliers", "Top Suppliers (transactions)", [2, 3],
              [dash.PURPLE, GREY], max(supplier_totals.values() or [1]),
              horizontal=True), "A", start + 2 * CHART_ROWS, False),
        (ring("activity", "Receiving vs Withdrawal",
              [dash.TEAL, dash.AMBER]), "I", start + 2 * CHART_ROWS, False),
        (bars("days", "Quantity per Day", [4, 5], [dash.TEAL, GREY],
              max(qty_by_day.values() or [1]), axis="Quantity",
              labels=len(days) <= 7),
         "A", start + 3 * CHART_ROWS, False),
    ]
    alone = "destinations" not in tables
    if "destinations" in tables:
        placed.append((bars(
            "destinations", "Withdrawal: Shipments per Destination", [2],
            [dash.AMBER], max(by_place.values() or [1]), horizontal=True,
            stacked=False), "I", start + 3 * CHART_ROWS, False))
    for chart, column, at, wide in placed:
        if wide or (alone and at == start + 3 * CHART_ROWS):
            side = "wide"
        else:
            side = "left" if column == "A" else "right"
        chart_style.place(ws, chart, at, CHART_ROWS, side, COLUMNS)

    # Withdrawal: the delivery destinations as a table with in-cell bars
    at = start + 4 * CHART_ROWS
    band(at, 24, NAVY, "WITHDRAWAL  ·  DELIVERY DESTINATIONS   (follows the "
         "Week, Cargo Condition and Supplier choices)",
         Font(bold=True, size=11, color="FFFFFF"))
    heads = (("Destination", 1, 4), ("Shipments", 5, 7),
             ("Total Packages", 8, 10), ("Cargo Line Items", 11, 13),
             ("Share of Shipments", 14, 16))
    thin = Side(style="thin", color="E2E8F0")

    def table_row(r, values, font=None, formats=(None,) * 4):
        for (_, first, end), value, number in zip(heads, values,
                                                  (None, *formats)):
            ws.merge_cells(start_row=r, start_column=first, end_row=r,
                           end_column=end)
            cell = ws.cell(row=r, column=first, value=value)
            cell.alignment = Alignment(horizontal="left", vertical="center",
                                       indent=1)
            if font:
                cell.font = font
            if number:
                cell.number_format = number
            for column in range(first, end + 1):
                ws.cell(row=r, column=column).border = Border(bottom=thin)
        ws.row_dimensions[r].height = 18

    table_row(at + 1, [h for h, *_ in heads],
              Font(bold=True, color="475569"))
    if "destinations" in tables:
        _, first, end = tables["destinations"]
        numbers = ("#,##0", "#,##0", "#,##0", "0%")
        for offset, source in enumerate(range(first, end + 1)):
            r = at + 2 + offset
            table_row(r, [f"=Calc!A{source}", f"=Calc!B{source}",
                          f"=Calc!C{source}", f"=Calc!D{source}",
                          f'=IF(Calc!$B$12=0,"",Calc!B{source}/Calc!$B$12)'],
                      formats=numbers)
            if offset % 2:
                for column in range(1, COLUMNS + 1):
                    ws.cell(row=r, column=column).fill = fill("F8FAFC")
        last_row = at + 2 + (end - first)
        for letter, color in (("E", dash.AMBER), ("H", dash.TEAL),
                              ("K", dash.BLUE)):
            ws.conditional_formatting.add(
                f"{letter}{at + 2}:{letter}{last_row}",
                DataBarRule(start_type="num", start_value=0,
                            end_type="max", color=color, showValue=True))
        total_row = last_row + 1
        table_row(total_row, ["TOTAL WITHDRAWAL", "=Calc!$B$12",
                              "=Calc!$C$12", "=Calc!$D$12", None],
                  Font(bold=True, color=NAVY), numbers)
        end_row = total_row + 3
    else:
        ws.cell(row=at + 2, column=1,
                value="No Withdrawal reports in this period.").font = Font(
            italic=True, color="64748B")
        end_row = at + 5
    note = ws.cell(row=end_row, column=1, value=(
        "The figures come from the Weekly Summary sheet. A transaction is "
        "one inspection report; Total Quantity adds every unit together."))
    note.font = Font(italic=True, size=9, color="64748B")
    for column in range(1, COLUMNS + 1):
        ws.cell(row=end_row - 1, column=column).border = Border(
            top=Side(style="thin", color=SLATE_DARK))

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    # one spare column: Excel prints a chart a little wider than its cells
    ws.print_area = f"A1:{get_column_letter(COLUMNS + 1)}{end_row}"
    # printed: the dropdowns, cards and the day chart on page 1, then two
    # rows of charts a page, the last with the destinations - no chart
    # cut in two
    chart_style.page_breaks(ws, [start - 1 + CHART_ROWS,
                                 start - 1 + 3 * CHART_ROWS])
    # the formulas are worked out when Excel opens the file
    wb.calculation.fullCalcOnLoad = True
    return ws


def period_of(year, month, week, week_span):
    """(first day, last day) of the exported period."""
    span = week_span(year, month, week)
    return date(year, month, span[0]), date(year, month, span[1])
