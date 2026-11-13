"""The Weekly Summary: one line per item of every report inspected in a week, read from the Excel file or MySQL, shown and exported as an Excel file.

Moved here from field_survey_report.py (Phase 4). The code is unchanged
except that the names it takes from the program's window module are
read as `host.<name>`, at the moment they are used (bind() is called
by the window module)."""
from datetime import date
from datetime import datetime
from fsr_storage import ITEM_HEADERS
from fsr_storage import Workbook
from fsr_storage import parse_date
from fsr_storage import split_quantity_unit
from fsr_storage import to_number
import calendar


class _Host:
    """The window module's names, read when they are used."""

    def __init__(self):
        object.__setattr__(self, "names", None)

    def __getattr__(self, name):
        names = object.__getattribute__(self, "names")
        if names is None:
            raise RuntimeError("bind() was not called")
        try:
            return names[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        object.__getattribute__(self, "names")[name] = value


host = _Host()


def bind(names):
    """Called by the window module with its globals()."""
    object.__setattr__(host, "names", names)


def report_to_weekly_rows(data):
    """One report -> weekly summary rows (a row per item line)."""
    info = data["general_information"]
    docs = data["documents_used"]
    transport = data["transport_details"]
    head = [
        info["so_number"], info["inspection_date"],
        data["inspection_schedule"].get("activity", ""),
        transport.get("shipment_type", ""), info["supplier"],
        info["brokerage"], info["hauler"], info["destination"],
        info["country_of_origin"], docs["invoice_number"], docs["po_number"],
        docs["jo_number"], docs["gatepass_number"], docs["bl_awb_number"],
        docs["dr_number"], transport["vehicle_type"],
        transport["vehicle_plate_number"],
    ]
    items = [
        row for section in data["item_lists"] for row in section["rows"]
        if any(str(row.get(key) or "").strip() for key in ITEM_HEADERS)
    ]
    tail = [data["cargo_condition"]]
    if not items:
        return [head + [""] * len(host.WEEKLY_ITEM_KEYS) + tail]
    lines = []
    for row in items:
        row = dict(row)
        row["Quantity"], row["UOM"] = split_quantity_unit(
            row.get("Quantity"), row.get("UOM"))
        lines.append(
            head + [str(row.get(key) or "") for key in host.WEEKLY_ITEM_KEYS]
            + tail)
    return lines


def weekly_rows_from_excel(first_day, last_day):
    path = host.excel_state["path"]
    rows = []
    for entry in host.data_store(path).list_reports():
        day = parse_date(entry[2])
        if not isinstance(day, datetime):
            continue
        if first_day <= day.date() <= last_day:
            rows.append((day, entry[0], report_to_weekly_rows(
                host.data_store(path).read_report(entry[0]))))
    for report in host.data_store().read_all_withdrawal_reports():
        day = parse_date(report["general_information"]["inspection_date"])
        if isinstance(day, datetime) and first_day <= day.date() <= last_day:
            rows.append((day, report["control_no"],
                         report_to_weekly_rows(report)))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [line for _, _, lines in rows for line in lines]


def weekly_rows(year, month, week, source):
    span = host.week_span(year, month, week)
    if span is None:
        return []
    first_day, last_day = date(year, month, span[0]), date(year, month, span[1])
    if source == "mysql":
        return host.db_mysql.weekly_summary(first_day, last_day)
    return weekly_rows_from_excel(first_day, last_day)


def weekly_cells(line):
    """28 weekly fields -> the 26 columns: (text, None) per column, or
    (currency, amount text) for the two price columns."""
    line = [str(value or "").strip() for value in line]
    currency = line[host.WEEKLY_CURRENCY]
    quantity = " ".join(filter(None, (line[host.WEEKLY_QTY], line[host.WEEKLY_UOM])))
    return (line[:host.WEEKLY_QTY] + [quantity] + line[host.WEEKLY_UOM + 1:host.WEEKLY_CURRENCY]
            + [(currency, line[host.WEEKLY_CURRENCY + 1]),
               (currency, line[host.WEEKLY_CURRENCY + 2])]
            + line[host.WEEKLY_CURRENCY + 3:])


def weekly_display(line):
    return [host.price_text(*cell) if isinstance(cell, tuple) else cell
            for cell in weekly_cells(line)]


def weekly_title(year, month, week):
    span = host.week_span(year, month, week)
    name = calendar.month_name[month]
    if week == 0 or span is None:
        return f"Weekly Summary Report - {name} {year} (whole month)"
    return (f"Weekly Summary Report - {name} {year}, Week {week} "
            f"({span[0]}-{span[1]} {name})")


def write_weekly_workbook(path, title, rows):
    """Save the rows as a formatted Excel sheet."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Weekly Summary"
    last_col = len(host.WEEKLY_COLUMNS)
    headings = [h for h, _ in host.WEEKLY_COLUMNS]

    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    blue = PatternFill("solid", fgColor="2E75B6")
    header_row = 1
    for index, (heading, width) in enumerate(host.WEEKLY_COLUMNS, start=1):
        cell = ws.cell(row=header_row, column=index, value=heading)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = blue
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
        ws.column_dimensions[get_column_letter(index)].width = max(width // 7, 9)

    def money_format(currency):
        # The currency shows in front of the amount; the cell stays a number.
        currency = currency.replace('"', "")
        return f'"{currency} "#,##0.00' if currency else "#,##0.00"

    totals = {}                     # currency -> sum of Total Price
    row_no = header_row
    for line in rows:
        row_no += 1
        for index, (heading, value) in enumerate(
                zip(headings, weekly_cells(line)), start=1):
            number_format = None
            if heading == "Date":
                value = parse_date(value)
                if isinstance(value, datetime):
                    number_format = "dd-mmm-yyyy"
                else:
                    value = str(value or "")
            elif heading in host.WEEKLY_NUMBER_COLUMNS:
                currency, amount = value
                value = to_number(amount)
                if isinstance(value, (int, float)):
                    number_format = money_format(currency)
                    if heading == "Total Price":
                        totals[currency] = totals.get(currency, 0) + value
                else:
                    value = host.price_text(currency, amount)
            cell = ws.cell(row=row_no, column=index, value=value or None)
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if number_format:
                cell.number_format = number_format

    if rows:
        # One TOTAL per currency (amounts in different currencies are
        # never added together).
        total_col = headings.index("Total Price") + 1
        for offset, currency in enumerate(sorted(totals), start=1):
            total_row = row_no + offset
            label = ws.cell(row=total_row, column=total_col - 1,
                            value=f"TOTAL {currency.upper()}".strip())
            label.font = Font(bold=True)
            label.alignment = Alignment(horizontal="right")
            total = ws.cell(row=total_row, column=total_col,
                            value=totals[currency])
            total.font = Font(bold=True)
            total.number_format = money_format(currency)
        ws.auto_filter.ref = (f"A{header_row}:"
                              f"{get_column_letter(last_col)}{row_no}")

    ws.oddHeader.center.text = title
    ws.freeze_panes = ws.cell(row=header_row + 1, column=2)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    wb.save(path)
