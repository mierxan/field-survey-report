"""How every chart on the Excel dashboards is drawn and placed (the Dashboard
sheet of the Weekly / Monthly reports, exports.write_dashboard, and the
interactive Dashboard, fsr_weekly_dashboard).

- Placed by cells, not by size: a chart runs from the top-left of its first
  cell to the bottom-right of its last (a two-cell anchor). A chart given in
  centimetres is drawn wider than its columns wherever the columns come out
  narrower - Windows display scaling above 100%, WPS Office, phone viewers -
  and then lies under its neighbour. Side by side, the two charts keep a
  small gap.
- Title, legend, axis and label texts carry their own font size, and the
  title and legend are marked as not overlaying the plot: viewers that
  guess otherwise drew the title over the legend.
- Square corners and a light border, as the cards.
"""
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText, Text
from openpyxl.chart.title import Title
from openpyxl.drawing.line import LineProperties
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.drawing.text import (CharacterProperties, Paragraph,
                                   ParagraphProperties, RegularTextRun,
                                   RichTextProperties)

NAVY = "1F2A44"
TEXT = "334155"
BORDER = "CBD5E1"
TITLE_SIZE = 1400                   # 14 pt
AXIS_TITLE_SIZE = 900
TEXT_SIZE = 900
VERTICAL = -5400000                 # text turned a quarter, bottom to top

EMU_PER_PIXEL = 9525
COLUMN_PIXELS = 73                  # a column 10.5 wide (Calibri 11)
ROW_PIXELS = 20                     # a row 15 points high
GAP_PIXELS = 5                      # each side of the gap between two charts
EDGE_PIXELS = 14                    # clear of the right edge and the foot


def _props(size, bold=False, color=TEXT):
    return CharacterProperties(sz=size, b=bold, solidFill=color)


def _body(rotate=None):
    return RichTextProperties(rot=rotate, vert="horz") if rotate \
        else RichTextProperties()


def text(size=TEXT_SIZE, bold=False, rotate=None, color=TEXT):
    """Text properties for axis numbers, labels and the legend."""
    props = _props(size, bold, color)
    return RichText(bodyPr=_body(rotate), p=[Paragraph(
        pPr=ParagraphProperties(defRPr=props), endParaRPr=props)])


def title(words, size=TITLE_SIZE, rotate=None, color=NAVY):
    """A chart or axis title in its own place above (or beside) the plot."""
    props = _props(size, True, color)
    paragraph = Paragraph(pPr=ParagraphProperties(defRPr=props),
                          r=[RegularTextRun(rPr=props, t=words)])
    return Title(tx=Text(rich=RichText(bodyPr=_body(rotate),
                                       p=[paragraph])),
                 overlay=False)


def finish(chart, words, axis_title="", horizontal=False):
    """Title, legend, axes and frame of a dashboard chart."""
    chart.title = title(words)
    chart.roundedCorners = False
    chart.graphical_properties = GraphicalProperties(
        solidFill="FFFFFF", ln=LineProperties(solidFill=BORDER))
    if chart.legend is not None:
        chart.legend.overlay = False
        chart.legend.txPr = text()
    for axis in (getattr(chart, "x_axis", None),
                 getattr(chart, "y_axis", None)):
        if axis is not None and not getattr(axis, "delete", True):
            axis.txPr = text()
    labels = getattr(chart, "dataLabels", None)
    if labels is not None:
        labels.txPr = text(bold=True)
    for series in chart.series:
        if series.dLbls is not None:
            series.dLbls.txPr = text(bold=True)
    if axis_title:
        chart.y_axis.title = title(axis_title, AXIS_TITLE_SIZE,
                                   rotate=None if horizontal else VERTICAL,
                                   color=TEXT)
    return chart


def anchor(first_column, first_row, last_column, last_row,
           left=0, right=0, bottom=0):
    """From the top-left of (first_column, first_row) to the bottom-right
    of (last_column, last_row); 1-based, both included. left / right /
    bottom: pixels kept clear inside that edge."""
    start = AnchorMarker(col=first_column - 1, colOff=left * EMU_PER_PIXEL,
                         row=first_row - 1, rowOff=0)
    end = AnchorMarker(col=last_column - 1,
                       colOff=(COLUMN_PIXELS - right) * EMU_PER_PIXEL,
                       row=last_row - 1,
                       rowOff=(ROW_PIXELS - bottom) * EMU_PER_PIXEL)
    return TwoCellAnchor(_from=start, to=end)


def place(ws, chart, first_row, rows, side, columns=16):
    """Put `chart` on `ws` at `first_row`, `rows` rows high (the last row
    of the block stays empty, the gap to the next charts). side: "left"
    (the first half), "right" (the second) or "wide" (all the columns).
    A chart keeps clear of the sheet's right edge and of its last row's
    foot: printed, Excel draws a chart a little bigger than its cells."""
    half = columns // 2
    last_row = first_row + rows - 2
    if side == "left":
        where = anchor(1, first_row, half, last_row, right=GAP_PIXELS,
                       bottom=EDGE_PIXELS)
    elif side == "right":
        where = anchor(half + 1, first_row, columns, last_row,
                       left=GAP_PIXELS, right=EDGE_PIXELS,
                       bottom=EDGE_PIXELS)
    else:
        where = anchor(1, first_row, columns, last_row, right=EDGE_PIXELS,
                       bottom=EDGE_PIXELS)
    ws.add_chart(chart, where)
    return where


def page_breaks(ws, rows):
    """Printed pages start at these rows, so no chart is cut in two. Give
    the empty row above a chart: Excel prints a chart a little higher than
    its cells, and its top edge would show at the foot of the page before."""
    from openpyxl.worksheet.pagebreak import Break, RowBreak
    breaks = RowBreak()
    for row in sorted(set(rows)):
        if row > 1:
            breaks.append(Break(id=row - 1))
    ws.row_breaks = breaks
