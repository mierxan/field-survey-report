"""Excel and PDF reports of the warehouse modules.

Every report is first built as a ReportDocument (title, reporting period,
date generated, filters, KPI summary, tables with totals) from the same
functions the screens use; write_excel() / write_pdf() then only lay it
out. The inspection-report templates (First Page, Cargo Details, Incident
Report) are not used or changed here.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import analytics as an
from . import tables as tb
from .periods import day_period, month_period, week_period
from .transactions import BAD_ORDER, RECEIVING, WITHDRAWAL


@dataclass
class Section:
    title: str
    columns: list
    rows: list
    totals: list | None = None
    note: str = ""


@dataclass
class ReportDocument:
    title: str
    period: str
    filters: list
    kpis: list                      # analytics.KPI
    sections: list = field(default_factory=list)
    statements: list = field(default_factory=list)   # (topic, text)
    generated: datetime = field(default_factory=datetime.now)
    source: str = ""

    @property
    def file_stem(self):
        safe = "".join(c if c.isalnum() or c in " -_" else "_"
                       for c in self.title)
        return f"{safe} {self.generated:%Y-%m-%d %H%M}".strip()


# =====================================================
# report builders (one per report type)
# =====================================================

SUMMARY_KINDS = {"daily": ("Daily", day_period),
                 "weekly": ("Weekly", week_period),
                 "monthly": ("Monthly", month_period)}


def summary_kpis(summary):
    prev = summary.previous
    transactions = an.KPI(
        "Transactions", summary.tx_count,
        an.fmt_number(summary.tx_count), "transactions (reports)",
        comparison=an.change_text(summary.tx_count,
                                  prev.tx_count if prev else None))
    condition = an.KPI(
        "Good / Bad Order",
        summary.by_condition.get(BAD_ORDER),
        f"{summary.by_condition.get('Good Order', 0)} Good · "
        f"{summary.by_condition.get(BAD_ORDER, 0)} Bad",
        "transactions")
    if summary.activity == RECEIVING:
        total = sum(summary.qty.values()) if summary.qty else None
        return [
            transactions,
            an.KPI("Total Quantity Received", total, an.fmt_number(total),
                   "all units combined"),
            an.KPI("Total Packages", summary.packages,
                   an.fmt_number(summary.packages), "from Declared Goods"),
            condition,
        ]
    return [
        transactions,
        an.KPI("Total Packages", summary.packages,
               an.fmt_number(summary.packages), "from Declared Goods"),
        condition,
    ]


def transaction_summary_report(snapshot, activity, kind, day, filters=None):
    """Daily / Weekly / Monthly Receiving or Withdrawal Summary."""
    filters = filters or an.Filters()
    name, make_period = SUMMARY_KINDS[kind]
    period = make_period(day)
    summary = an.summarize(snapshot.transactions, activity, period, filters)
    party = "Supplier / Shipper" if activity == RECEIVING else "Consignee"
    doc = ReportDocument(
        f"{name} {activity} Summary", period.describe(),
        filters.describe(), summary_kpis(summary), source=str(snapshot.source))
    if kind != "daily":
        breakdown = (summary.by_day if kind == "weekly"
                     else summary.by_week)
        doc.sections.append(Section(
            "Daily Breakdown" if kind == "weekly" else "Weekly Breakdown",
            [("Day" if kind == "weekly" else "Week Starting", "date", 14),
             ("Transactions", "number", 12)],
            [[d, n] for d, n in breakdown.items()],
            ["TOTAL", sum(breakdown.values())]))
    def breakdown_section(title, label, groups):
        return Section(title,
                       [(label, "text", 30), ("Transactions", "number", 12)],
                       [list(r[:2]) for r in groups],
                       ["TOTAL", summary.tx_count])

    doc.sections.append(breakdown_section(
        "Warehouse Breakdown", "Warehouse", summary.by_warehouse))
    if kind == "monthly" or activity == WITHDRAWAL:
        groups = (summary.by_supplier if activity == RECEIVING
                  else summary.by_consignee)
        doc.sections.append(breakdown_section(
            f"{party} Breakdown", party, groups))
    if kind == "monthly":
        doc.sections.append(Section(
            "Cargo Category Breakdown (Types of Goods)",
            [("Category", "text", 24), ("Transactions", "number", 12)],
            [list(r) for r in summary.by_cargo_type]))
    doc.sections.append(Section(
        "Good Order / Bad Order",
        [("Cargo Condition", "text", 16), ("Transactions", "number", 12)],
        [[k, v] for k, v in summary.by_condition.items()],
        ["TOTAL", summary.tx_count]))
    if summary.previous is not None:
        doc.sections.append(Section(
            f"Comparison with {summary.previous.period.describe()}",
            [("Measure", "text", 30), ("This Period", "text", 14),
             ("Previous Period", "text", 14), ("Change", "text", 40)],
            [list(r) for r in an.comparison_rows(summary)]))
    rows = tb.line_rows(summary.lines)
    doc.sections.append(Section(
        f"{activity} Transaction Lines", tb.LINE_COLUMNS, rows,
        tb.column_totals(tb.LINE_COLUMNS, rows)))
    return doc


def summary_report(snapshot, activity, kind, day):
    """Weekly / Monthly Receiving or Withdrawal Summary Report: every item
    line of the period in the summary-report format (SO Number ... Cargo
    Condition, Findings / Remarks)."""
    name, make_period = SUMMARY_KINDS[kind]
    period = make_period(day)
    summary = an.summarize(snapshot.transactions, activity, period)
    rows, totals = tb.summary_report_rows(snapshot.reports, activity, period)
    doc = ReportDocument(
        f"{name} {activity} Summary Report", period.describe(),
        [f"Activity: {activity}"], summary_kpis(summary),
        source=str(snapshot.source))
    columns = tb.SUMMARY_REPORT_COLUMNS
    total_row = None
    if totals:
        # Amounts in different currencies are never added together.
        total_row = [None] * len(columns)
        total_row[0] = "TOTAL"
        total_row[[c[0] for c in columns].index("Total Price")] = " / ".join(
            f"{currency} {amount:,.2f}".strip()
            for currency, amount in sorted(totals.items()))
    doc.sections.append(Section(
        f"{activity} Summary Report", columns, rows, total_row,
        note="Findings / Remarks = the report's Other Important Remarks."))
    return doc


def bad_order_report(snapshot, filters):
    statuses = snapshot.side.case_statuses()
    kpis = an.bad_order_kpis(snapshot.transactions, filters, statuses)
    bad = an.filter_transactions(snapshot.transactions, an.Filters(
        **{**filters.__dict__, "condition": BAD_ORDER}))
    doc = ReportDocument("Bad Order Summary",
                         filters.period.describe() if filters.period
                         else "All Records", filters.describe(), kpis,
                         source=str(snapshot.source))
    split = an.good_vs_bad(snapshot.transactions, filters)
    doc.sections.append(Section(
        "Good Order versus Bad Order",
        [("Cargo Condition", "text", 16), ("Reports", "number", 10)],
        [[k, v] for k, v in split.items()], ["TOTAL", sum(split.values())]))
    breakdowns = an.bad_order_breakdowns(snapshot.transactions, filters)
    for key, title in (("warehouse", "Bad Order Reports by Warehouse"),
                       ("activity", "Bad Order Reports by Activity"),
                       ("cargo_type", "Bad Order Reports by Cargo Type")):
        doc.sections.append(Section(
            title, [(title.split(" by ")[1], "text", 30),
                    ("Reports", "number", 10)],
            [list(r) for r in breakdowns[key]]))
    doc.sections.append(Section("Bad Order Records", tb.BAD_ORDER_COLUMNS,
                                tb.bad_order_rows(bad, statuses)))
    return doc


def _inventory_kpis(items, inventory):
    counts = {s: sum(1 for i in items if i.status == s)
              for s in ("In Stock", "Partially Withdrawn", "Fully Withdrawn",
                        "Over-Withdrawn", "Reconciliation Required")}
    remaining = {}
    for item in items:
        if item.remaining_qty is not None and item.remaining_qty > 0:
            remaining[item.unit] = remaining.get(item.unit, 0) \
                + item.remaining_qty
    label = f"As of {inventory.as_of:%d-%b-%Y}"
    return [an.KPI("Inventory Items", len(items), an.fmt_number(len(items)),
                   "items", label),
            an.KPI("Remaining Quantity", remaining or None,
                   an.fmt_units(remaining), "by unit - recorded, not "
                   "physically verified", label)] + [
        an.KPI(status, n, an.fmt_number(n), "items", label)
        for status, n in counts.items()]


def warehouse_inventory_report(snapshot, warehouse="", title=None,
                               items=None):
    inv = snapshot.inventory
    items = items if items is not None else [
        i for i in inv.items if not warehouse
        or an.norm_key(i.warehouse) == an.norm_key(warehouse)]
    rows = tb.inventory_rows(items)
    doc = ReportDocument(title or "Warehouse Inventory Report",
                         f"Recorded balances as of {inv.as_of:%d-%b-%Y}",
                         [f"Warehouse: {warehouse}" if warehouse
                          else "Warehouse: All"],
                         _inventory_kpis(items, inv),
                         source=str(snapshot.source))
    doc.sections.append(Section("Inventory Items", tb.INVENTORY_COLUMNS,
                                rows,
                                tb.column_totals(tb.INVENTORY_COLUMNS, rows),
                                "Balances are calculated from the recorded "
                                "transactions; they are not a physical "
                                "stock count."))
    return doc


def remaining_cargo_report(snapshot, items, filters_text=None):
    doc = warehouse_inventory_report(snapshot, title="Remaining Warehouse "
                                     "Cargo Report", items=items)
    doc.filters = filters_text or ["Positive recorded balance only"]
    return doc


def cargo_history_report(snapshot, item):
    rows = tb.history_rows(item)
    doc = ReportDocument(
        "Cargo Transaction History",
        f"All recorded transactions up to {snapshot.inventory.as_of:%d-%b-%Y}",
        [f"Cargo: {item.identity}", f"Warehouse: {item.warehouse}"],
        [an.KPI("Received", item.received_qty,
                f"{an.fmt_number(item.received_qty)} {item.unit}", "total"),
         an.KPI("Withdrawn", item.withdrawn_qty,
                f"{an.fmt_number(item.withdrawn_qty)} {item.unit}", "total"),
         an.KPI("Remaining", item.remaining_qty,
                f"{an.fmt_number(item.remaining_qty)} {item.unit}",
                "recorded balance"),
         an.KPI("Status", None, item.status_detail, "")],
        source=str(snapshot.source))
    doc.sections.append(Section("Receiving and Withdrawal History",
                                tb.HISTORY_COLUMNS, rows))
    if item.issues:
        doc.sections.append(Section("Open Points", tb.ISSUE_COLUMNS,
                                    tb.issue_rows(item.issues)))
    return doc


def management_report(snapshot, filters):
    statuses = snapshot.side.case_statuses()
    ms = an.management_summary(snapshot.transactions, snapshot.inventory,
                               filters, statuses)
    kpis = (an.inspection_kpis(snapshot.transactions, filters)
            + an.warehouse_kpis(snapshot.transactions, snapshot.inventory,
                                filters))
    doc = ReportDocument("Management KPI Summary",
                         filters.period.describe() if filters.period
                         else "All Records", filters.describe(), kpis,
                         statements=ms.statements,
                         source=str(snapshot.source))
    for summary in (ms.receiving, ms.withdrawal):
        if summary.previous is not None:
            doc.sections.append(Section(
                f"{summary.activity}: Comparison with Previous Period",
                [("Measure", "text", 30), ("This Period", "text", 14),
                 ("Previous Period", "text", 14), ("Change", "text", 40)],
                [list(r) for r in an.comparison_rows(summary)]))
    counts = snapshot.inventory.status_counts()
    doc.sections.append(Section(
        "Remaining Warehouse Cargo by Status",
        [("Inventory Status", "text", 26), ("Items", "number", 9)],
        [[k, v] for k, v in counts.items()], ["TOTAL", sum(counts.values())]))
    return doc


def table_report(title, period_text, filters_text, columns, rows,
                 kpis=None, source=""):
    """A filtered table exactly as shown on screen."""
    doc = ReportDocument(title, period_text, filters_text, kpis or [],
                         source=source)
    doc.sections.append(Section(title, columns, rows,
                                tb.column_totals(columns, rows)
                                if rows else None))
    return doc


# =====================================================
# writers
# =====================================================

NAVY = "1F2A44"
LIGHT = "EEF2F7"


def write_excel(doc, path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor=NAVY)
    band = PatternFill("solid", fgColor=LIGHT)
    thin = Side(style="thin", color="C9D1DC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def header_block(sheet, title):
        sheet["A1"] = title
        sheet["A1"].font = Font(bold=True, size=14, color=NAVY)
        meta = [("Reporting Period", doc.period),
                ("Date Generated", doc.generated.strftime("%d-%b-%Y %H:%M")),
                ("Selected Filters", "; ".join(doc.filters))]
        if doc.source:
            meta.append(("Data Source", doc.source))
        for row, (label, value) in enumerate(meta, start=2):
            sheet.cell(row=row, column=1, value=label).font = bold
            sheet.cell(row=row, column=2, value=value)
        return len(meta) + 3

    row = header_block(ws, doc.title)
    if doc.kpis:
        ws.cell(row=row, column=1, value="KPI SUMMARY").font = bold
        row += 1
        for col, heading in enumerate(("Metric", "Value", "Unit / Basis",
                                       "Period", "Comparison", "Note"), 1):
            cell = ws.cell(row=row, column=col, value=heading)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill
        for kpi in doc.kpis:
            row += 1
            value = kpi.value if isinstance(kpi.value, (int, float)) \
                and not isinstance(kpi.value, bool) and "%" not in \
                kpi.display else kpi.display
            for col, v in enumerate((kpi.name, value, kpi.unit, kpi.period,
                                     kpi.comparison, kpi.note), 1):
                ws.cell(row=row, column=col, value=v).border = border
        row += 2
    if doc.statements:
        ws.cell(row=row, column=1, value="SUMMARY").font = bold
        for topic, text in doc.statements:
            row += 1
            ws.cell(row=row, column=1, value=topic).font = bold
            cell = ws.cell(row=row, column=2, value=text)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        row += 2
    for col, width in zip("ABCDEF", (34, 40, 30, 34, 36, 36)):
        ws.column_dimensions[col].width = width

    used = {"Summary"}
    for section in doc.sections:
        name = "".join(c for c in section.title if c not in "[]:*?/\\")[:31]
        base, n = name, 2
        while name in used:
            name = f"{base[:28]}~{n}"
            n += 1
        used.add(name)
        sheet = wb.create_sheet(name)
        start = header_block(sheet, f"{doc.title} - {section.title}")
        if section.note:
            sheet.cell(row=start - 1, column=1, value=section.note).font = \
                Font(italic=True, color="666666")
        for col, (heading, _kind, width) in enumerate(section.columns, 1):
            cell = sheet.cell(row=start, column=col, value=heading)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
            cell.border = border
            sheet.column_dimensions[get_column_letter(col)].width = \
                max(width + 2, len(heading) * 0.9, 9)
        for r_index, values in enumerate(section.rows, start=start + 1):
            for col, ((_, kind, _), value) in enumerate(
                    zip(section.columns, values), 1):
                cell = sheet.cell(row=r_index, column=col, value=value)
                cell.border = border
                if kind == "date" and isinstance(value, (date, datetime)):
                    cell.number_format = "dd-mmm-yyyy"
                elif kind in ("qty", "number") and \
                        isinstance(value, (int, float)):
                    cell.number_format = "#,##0.##"
                if (r_index - start) % 2 == 0:
                    cell.fill = band
        last = start + len(section.rows)
        if section.rows:
            sheet.auto_filter.ref = (f"A{start}:"
                                     f"{get_column_letter(len(section.columns))}"
                                     f"{last}")
        if section.totals:
            for col, ((_, kind, _), value) in enumerate(
                    zip(section.columns, section.totals), 1):
                cell = sheet.cell(row=last + 1, column=col, value=value)
                cell.font = bold
                if kind in ("qty", "number") and \
                        isinstance(value, (int, float)):
                    cell.number_format = "#,##0.##"
        if not section.rows:
            sheet.cell(row=start + 1, column=1,
                       value="No records for the selected filters.")
        sheet.freeze_panes = sheet.cell(row=start + 1, column=1)
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.print_title_rows = f"{start}:{start}"
    path = Path(path)
    temp = path.with_name(path.stem + ".saving.tmp.xlsx")
    wb.save(temp)
    temp.replace(path)
    return path


def write_pdf(doc, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import (KeepTogether, Paragraph,
                                    PageBreak, SimpleDocTemplate, Spacer,
                                    Table)

    navy = colors.HexColor("#" + NAVY)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("t", parent=styles["Title"], alignment=0,
                                 textColor=navy, fontSize=16, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=navy,
                        fontSize=11, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("s", parent=styles["BodyText"], fontSize=7,
                           leading=8.5)
    small_bold = ParagraphStyle("sb", parent=small, fontName="Helvetica-Bold",
                                textColor=colors.white)
    meta = ParagraphStyle("m", parent=styles["BodyText"], fontSize=8.5,
                          leading=11)

    class NumberedCanvas(rl_canvas.Canvas):
        """Adds 'Page X of Y' (needs all pages first)."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.setFont("Helvetica", 7.5)
                self.setFillColor(colors.HexColor("#5B6B82"))
                width = self._pagesize[0]
                self.drawString(12 * mm, 8 * mm,
                                f"{doc.title} - generated "
                                f"{doc.generated:%d-%b-%Y %H:%M}")
                self.drawRightString(width - 12 * mm, 8 * mm,
                                     f"Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()

    page = landscape(A4)
    frame_width = page[0] - 24 * mm
    max_cell_lines = max(1, int(
        (page[1] - 26 * mm) / small.leading * 0.55))
    story = [Paragraph(doc.title, title_style)]
    long_details = []
    seen_long_details = set()
    meta_text = (f"<b>Reporting Period:</b> {doc.period}<br/>"
                 f"<b>Date Generated:</b> "
                 f"{doc.generated:%d-%b-%Y %H:%M}<br/>"
                 f"<b>Selected Filters:</b> {'; '.join(doc.filters)}")
    if doc.source:
        meta_text += f"<br/><b>Data Source:</b> {doc.source}"
    story += [Paragraph(meta_text, meta), Spacer(1, 4 * mm)]

    def esc(text):
        return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    if doc.kpis:
        story.append(Paragraph("KPI Summary", h2))
        data = [[Paragraph(h, small_bold) for h in
                 ("Metric", "Value", "Unit / Basis", "Comparison / Note")]]
        for kpi in doc.kpis:
            data.append([Paragraph(esc(kpi.name), small),
                         Paragraph(f"<b>{esc(kpi.display)}</b>", small),
                         Paragraph(esc(kpi.unit), small),
                         Paragraph(esc(" ".join(t for t in (kpi.comparison,
                                                            kpi.note) if t)),
                                   small)])
        table = Table(data, colWidths=[frame_width * f for f in
                                       (0.27, 0.27, 0.2, 0.26)],
                      repeatRows=1)
        table.setStyle(_table_style(navy))
        story.append(table)
    if doc.statements:
        story.append(Paragraph("Summary", h2))
        for topic, text in doc.statements:
            story.append(Paragraph(f"<b>{esc(topic)}:</b> {esc(text)}",
                                   meta))
    for section in doc.sections:
        if not section.rows:
            story.append(KeepTogether([Paragraph(esc(section.title), h2), Paragraph(
                "No records for the selected filters.", meta)]))
            continue
        identifiers = [
            index for index, (heading, _, _) in enumerate(section.columns)
            if heading in ("Report Control #", "Control #", "SO Number",
                           "Date", "Activity")
        ]
        remaining = [index for index in range(len(section.columns))
                     if index not in identifiers]
        if len(section.columns) > 14:
            groups = [
                identifiers + remaining[start:start + 9]
                for start in range(0, len(remaining), 9)
            ]
        else:
            groups = [list(range(len(section.columns)))]

        for group_number, indices in enumerate(groups, start=1):
            columns = [section.columns[index] for index in indices]
            weights = [max(column[2], 6) for column in columns]
            total_w = sum(weights)
            widths = [frame_width * weight / total_w for weight in weights]
            data = [[Paragraph(esc(column[0]), small_bold)
                     for column in columns]]

            def append_row(values, bold=False):
                identifier_index = next((
                    index for index, (heading, _, _) in
                    enumerate(section.columns)  # noqa: B023 - used in this same pass
                    if heading in ("Report Control #", "Control #",
                                   "SO Number")
                ), 0)
                identifier = tb.cell_text(
                    values[identifier_index],
                    section.columns[identifier_index][1])  # noqa: B023 - used in this same pass
                cells = []
                for index, width in zip(indices, widths):  # noqa: B023 - used in this same pass
                    column = section.columns[index]  # noqa: B023 - used in this same pass
                    text = tb.cell_text(values[index], column[1])
                    characters_per_line = max(
                        1, int(width / (small.fontSize * 0.5)))
                    chunk_width = max(
                        32, min(500, characters_per_line * max_cell_lines))
                    if len(text) > chunk_width:
                        detail = (section.title, identifier, column[0], text)  # noqa: B023 - used in this same pass
                        if detail not in seen_long_details:
                            seen_long_details.add(detail)
                            long_details.append(detail)
                        text = "[Full text in Long Text Details section]"
                    text = esc(text)
                    cells.append(Paragraph(
                        f"<b>{text}</b>" if bold else text, small))
                data.append(cells)  # noqa: B023 - used in this same pass

            for values in section.rows:
                append_row(values)
            if section.totals:
                append_row(section.totals, bold=True)
            table = Table(data, colWidths=widths, repeatRows=1)
            table.setStyle(_table_style(
                navy, has_totals=bool(section.totals)))
            heading = section.title
            if len(groups) > 1:
                heading += f" (Part {group_number} of {len(groups)})"
            group_flowables = [Paragraph(esc(heading), h2)]
            if section.note and group_number == 1:
                group_flowables.append(
                    Paragraph(f"<i>{esc(section.note)}</i>", small))
            group_flowables.append(table)
            if len(groups) > 1 and len(section.rows) <= 10:
                story.append(KeepTogether(group_flowables))
            else:
                story.extend(group_flowables)

    if long_details:
        story.append(PageBreak())
        story.append(Paragraph("Long Text Details", h2))
        for section, identifier, column, text in long_details:
            label = " - ".join(value for value in (section, identifier, column)
                               if value)
            story.append(Paragraph(esc(label), meta))
            story.append(Paragraph(esc(text), meta))
            story.append(Spacer(1, 2 * mm))

    path = Path(path)
    temp = path.with_name(path.stem + ".saving.tmp.pdf")
    pdf = SimpleDocTemplate(str(temp), pagesize=page, leftMargin=12 * mm,
                            rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=doc.title,
                            author="Field Survey Report")
    pdf.build(story, canvasmaker=NumberedCanvas)
    temp.replace(path)
    return path


def _table_style(navy, has_totals=False):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D1DC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F3F6FA")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if has_totals:
        commands.append(("BACKGROUND", (0, -1), (-1, -1),
                         colors.HexColor("#E4E9F0")))
    return TableStyle(commands)


def export(doc, path):
    """Write by file extension (.xlsx or .pdf)."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return write_pdf(doc, path)
    return write_excel(doc, path)


# Report catalogue for the Analytics & Reports page:
# (key, title, needs a period/day)
REPORT_TYPES = [
    ("daily_receiving", "Daily Receiving Summary"),
    ("weekly_receiving", "Weekly Receiving Summary"),
    ("monthly_receiving", "Monthly Receiving Summary"),
    ("daily_withdrawal", "Daily Withdrawal Summary"),
    ("weekly_withdrawal", "Weekly Withdrawal Summary"),
    ("monthly_withdrawal", "Monthly Withdrawal Summary"),
    ("weekly_receiving_report", "Weekly Receiving Summary Report"),
    ("monthly_receiving_report", "Monthly Receiving Summary Report"),
    ("weekly_withdrawal_report", "Weekly Withdrawal Summary Report"),
    ("monthly_withdrawal_report", "Monthly Withdrawal Summary Report"),
    ("bad_order", "Bad Order Summary"),
    ("remaining", "Remaining Warehouse Cargo Report"),
    ("history", "Cargo Transaction History"),
    ("management", "Management KPI Summary"),
]


def build_report(key, snapshot, filters, day=None, item=None):
    """One report of REPORT_TYPES. `day` = the day of a daily / weekly /
    monthly summary; `item` = the cargo of a transaction history."""
    day = day or (filters.period.end if filters.period
                  and filters.period.end else date.today())
    if key.endswith("_report"):
        kind, activity, _ = key.split("_")
        return summary_report(
            snapshot, RECEIVING if activity == "receiving" else WITHDRAWAL,
            kind, day)
    if key.split("_")[0] in SUMMARY_KINDS and "_" in key:
        kind, activity = key.split("_")
        return transaction_summary_report(
            snapshot, RECEIVING if activity == "receiving" else WITHDRAWAL,
            kind, day, filters)
    if key == "bad_order":
        return bad_order_report(snapshot, filters)
    if key == "remaining":
        items = [i for i in snapshot.inventory.remaining_items()
                 if not filters.warehouse
                 or an.norm_key(i.warehouse) == an.norm_key(filters.warehouse)]
        return remaining_cargo_report(snapshot, items, [
            f"Warehouse: {filters.warehouse or 'All'}",
            "Positive recorded balance only"])
    if key == "history":
        if item is None:
            raise ValueError("Choose a cargo item for its history.")
        return cargo_history_report(snapshot, item)
    if key == "management":
        return management_report(snapshot, filters)
    raise ValueError(f"Unknown report: {key}")
