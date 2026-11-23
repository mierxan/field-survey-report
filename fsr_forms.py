"""The official report forms (OPSF-068 v4.0): First Page, Cargo Details,
the Containerized / Loading forms and the Incident Report - filled from a
report's data into copies of the templates in data/excel, put together as
ONE workbook per report, and turned into a PDF or printed.

Moved here unchanged from field_survey_report.py (Phase 4), so it can be
used and tested without the program's window. The window code imports
these names. `print_name["value"]` is the name printed as the preparer;
the program sets it.
"""
import functools
import html
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import fsr_print_fit
from fsr_storage import (
    printed_findings,
    DATE_FORMAT, INCIDENT_MAX_LINES, incident_reports_of, incident_title,
    ITEM_FORM_CONTAINERIZED, ITEM_FORM_DEFAULT, ITEM_FORM_LOADING,
    item_form_name, ITEM_FORMS, LEGACY_DATE_FORMAT, safe_filename,
    split_quantity_unit, UNIT_NO_HEADER,
)

# The templates: beside the program (or inside the built one), as the
# window code finds them.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    BASE_DIR = Path(__file__).resolve().parent

# The preparer printed on the forms (set by the program after sign-in).
print_name = {"value": ""}


# Cargo Details sheet geometry. The screen and the printed form share it:
# item lines and remarks use the same rows (13-42) of one sheet.
CARGO_FIRST_ROW = 13
CARGO_LAST_ROW = 42
CARGO_MAX_ITEMS = CARGO_LAST_ROW - CARGO_FIRST_ROW + 1      # 30
CARGO_MIN_ITEM_ROWS = 5
MIN_REMARK_LINES = 5        # fewer rows left than this -> blank Remarks page


def remark_capacity(total_items):
    """
    Remark lines that fit on the last Cargo Details page after
    `total_items` item lines. Returns (lines, item lines on that page).
    """
    last_items = ((total_items - 1) % CARGO_MAX_ITEMS) + 1 if total_items else 0
    label_row = max(19, CARGO_FIRST_ROW + last_items)
    available = max(CARGO_LAST_ROW - label_row, 0)
    return (available if available >= MIN_REMARK_LINES else 0), last_items


# =====================================================
# XML HELPERS + OFFICIAL REPORT FORM - FIRST PAGE
# =====================================================
# After a report is saved, its data is also written into a copy of
# your official form (data/excel/First_Page.xlsx). The copy goes into a
# "Report Forms" folder next to the Excel
# file, named after the Control # (for example FSR-JDC-202610-0001_First_Page.xlsx).
#
# The template is edited directly inside the .xlsx package, so
# everything on your form (logo, check boxes, borders, print setup)
# stays exactly as designed. Only the "Entry for ..." cells are filled.

FORM_TEMPLATE = BASE_DIR / "data" / "excel" / "First_Page.xlsx"
FORM_FOLDER_NAME = "Report Forms"

FORM_SHEET_XML = "xl/worksheets/sheet1.xml"
FORM_STYLES_XML = "xl/styles.xml"
CALC_CHAIN_PART = "xl/calcChain.xml"

GOODS_FIRST_ROW = 22                                   # A22:E26 on the form
GOODS_ROW_COUNT = 5
# the Description of each Declared Goods line: two small lines when long
GOODS_DESCRIPTION_CELLS = tuple(f"A{GOODS_FIRST_ROW + i}"
                                for i in range(GOODS_ROW_COUNT))


def too_long_note(where):
    """The note shown after printing when a Description does not fit two
    printed lines."""
    return (f"{where}: the Description is too long for two printed lines, "
            "so it prints in a smaller font. Shorten it to keep it "
            "readable.")
# Remark lines on the form: rows 21-26 and 28-33 (row 27 is a thin spacer).
REMARK_CELLS = [f"G{row}" for row in (*range(21, 27), *range(28, 34))]


# safe_filename() is in fsr_storage.py

def parse_any_date(text):
    for fmt in (DATE_FORMAT, LEGACY_DATE_FORMAT):
        try:
            return datetime.strptime((text or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def form_date(text):
    """Show dates on the form as dd-MMM-yyyy."""
    day = parse_any_date(text)
    return day.strftime(DATE_FORMAT) if day else (text or "")


def remove_calc_chain_refs(xml_text_value):
    """The calculation chain is rebuilt by Excel; a stale one makes Excel
    show a 'repair' prompt, so every reference to it is dropped."""
    xml_text_value = re.sub(r"<Override\b[^>]*calcChain[^>]*/>", "",
                            xml_text_value)
    return re.sub(r"<Relationship\b[^>]*calcChain[^>]*/>", "",
                  xml_text_value)


def build_first_page_values(data):
    """
    Map the report data to the cells of the First Page form.
    Returns ({cell: text}, [notes]). Every cell that holds an
    "Entry for ..." placeholder is included, so unused ones are cleared.
    """
    general = data["general_information"]
    schedule = data["inspection_schedule"]
    transport = data["transport_details"]
    documents = data["documents_used"]
    notes = []

    dr_number = documents["dr_number"]

    values = {
        # General information
        "H5": general["so_number"],
        "H6": form_date(general["inspection_date"]),
        "B6": general["consignee"],
        "B7": general["supplier"],
        "B8": general["brokerage"],
        "B9": general["hauler"],
        "H7": general["location"],
        "H8": general["destination"],
        "H9": general["country_of_origin"],
        # Documents used for inspection
        "B12": documents["invoice_number"],
        "B13": documents["po_number"],
        "B14": documents["jo_number"],
        "B15": documents["gatepass_number"],
        "B16": documents["bl_awb_number"],
        "B17": f"DR No.: {dr_number}" if dr_number else "",
        "B18": documents["other_documents"],
        # Transport details
        "I18": (data.get("goods_types") or {}).get("others_text", "")
        if (data.get("goods_types") or {}).get("others") else "",
        "A38": print_name["value"],     # prepared by (complete name)
        "H12": transport["vessel_carrier"],
        "H13": transport["vehicle_type"],
        "H14": transport["vehicle_plate_number"],
        # Inspection schedule summary
        "B29": schedule["activity"],
        "B30": schedule["commenced_date"],
        "B31": schedule["commenced_time"],
        "B32": schedule["completion_date"],
        "B33": schedule["completion_time"],
    }

    # Declared goods: Description | Qty | Packaging
    goods = data["declared_goods"]
    for index in range(GOODS_ROW_COUNT):
        row = GOODS_FIRST_ROW + index
        item = goods[index] if index < len(goods) else {}
        values[f"A{row}"] = item.get("description", "")
        values[f"D{row}"] = item.get("quantity", "")
        values[f"E{row}"] = item.get("packaging", "")

    # Other important remarks: 12 lines on the form
    remarks = data["other_important_remarks"]
    for index, cell in enumerate(REMARK_CELLS):
        values[cell] = remarks[index] if index < len(remarks) else ""

    if len(remarks) > len(REMARK_CELLS):
        notes.append(
            f"Only the first {len(REMARK_CELLS)} of {len(remarks)} "
            "Other Important Remarks fit on the form."
        )

    if len(goods) > GOODS_ROW_COUNT:
        notes.append(
            f"Only the first {GOODS_ROW_COUNT} of {len(goods)} "
            "Declared Goods fit on the form."
        )

    return values, notes


# ---------- editing the template inside the .xlsx package ---

def xml_text(text):
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text or "")
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


class StyleCloner:
    """
    Adds a "shrink text to fit" copy of a cell style, so a long value
    is made smaller instead of being cut off inside the merged cell.
    Optionally the copy is also left/center/right aligned.
    """

    def __init__(self, styles_xml):
        self.xml = styles_xml
        match = re.search(
            r"<cellXfs count=\"(\d+)\">(.*?)</cellXfs>", styles_xml, re.S
        )
        if not match:
            raise ValueError("The form template has no cell styles.")

        self.block = match
        self.xfs = re.findall(r"<xf\b[^>]*?(?:/>|>.*?</xf>)", match.group(2),
                              re.S)
        self.added = []
        self.cache = {}

    @staticmethod
    def _variant(xf, horizontal=None):
        # Split the opening tag from the rest.
        if xf.endswith("/>"):
            opening, body = xf[:-2], ""
        else:
            end = xf.index(">")
            opening, body = xf[:end], xf[end + 1:-len("</xf>")]

        opening = re.sub(r'\s+applyAlignment="[^"]*"', "", opening)
        opening += ' applyAlignment="1"'

        remove = "shrinkToFit|wrapText" + ("|horizontal" if horizontal else "")
        extra = (f' horizontal="{horizontal}"' if horizontal else "")
        extra += ' shrinkToFit="1"'

        if "<alignment" in body:
            body = re.sub(
                r"<alignment\b([^>]*?)(/?)>",
                lambda m: "<alignment"
                + re.sub(rf'\s+(?:{remove})="[^"]*"', "", m.group(1))
                + extra + m.group(2) + ">",
                body, count=1
            )
        else:
            body += f"<alignment{extra}/>"

        return f"{opening}>{body}</xf>"

    def shrink_index(self, index, horizontal=None):
        key = (index, horizontal)
        if key not in self.cache:
            self.xfs.append(self._variant(self.xfs[index], horizontal))
            self.added.append(len(self.xfs) - 1)
            self.cache[key] = len(self.xfs) - 1
        return self.cache[key]

    def wrap_small_index(self, index, size):
        """Copy of style `index` that WRAPS its text (no shrinking) in a
        font of `size` points: two readable lines in a one-line cell."""
        key = ("wrap", index, size)
        if key not in self.cache:
            xf = self.xfs[index]
            found = re.search(r'fontId="(\d+)"', xf)
            font = self._sized_font(int(found.group(1)) if found else 0, size)
            if xf.endswith("/>"):
                opening, body = xf[:-2], ""
            else:
                end = xf.index(">")
                opening, body = xf[:end], xf[end + 1:-len("</xf>")]
            opening = re.sub(r'\s+apply(?:Alignment|Font)="[^"]*"', "",
                             opening)
            if 'fontId="' in opening:
                opening = re.sub(r'fontId="\d+"', f'fontId="{font}"', opening)
            else:
                opening += f' fontId="{font}"'
            opening += ' applyAlignment="1" applyFont="1"'
            if "<alignment" in body:
                body = re.sub(
                    r"<alignment\b([^>]*?)(/?)>",
                    lambda m: "<alignment" + re.sub(
                        r'\s+(?:shrinkToFit|wrapText)="[^"]*"', "",
                        m.group(1)) + ' wrapText="1"' + m.group(2) + ">",
                    body, count=1)
            else:
                body += '<alignment wrapText="1"/>'
            self.xfs.append(f"{opening}>{body}</xf>")
            self.added.append(len(self.xfs) - 1)
            self.cache[key] = len(self.xfs) - 1
        return self.cache[key]

    def _sized_font(self, font_id, size):
        """The index of a copy of font `font_id` at `size` points (added to
        the template's fonts)."""
        key = ("font-size", font_id, size)
        if key in self.cache:
            return self.cache[key]
        if not hasattr(self, "fonts"):
            block = re.search(r"<fonts\b[^>]*>(.*?)</fonts>", self.xml, re.S)
            self.fonts = re.findall(r"<font\b[^>]*?(?:/>|>.*?</font>)",
                                    block.group(1), re.S)
            self.fonts_added = False
        font = self.fonts[font_id]
        if "<sz " in font:
            font = re.sub(r'<sz val="[^"]*"/>', f'<sz val="{size}"/>', font)
        else:
            font = font.replace("<font>", f'<font><sz val="{size}"/>', 1)
        self.fonts.append(font)
        self.fonts_added = True
        self.cache[key] = len(self.fonts) - 1
        return self.cache[key]

    def font_size(self, index):
        """The point size of the font of style `index` (11 when unknown)."""
        found = re.search(r'fontId="(\d+)"', self.xfs[index])
        block = re.search(r"<fonts\b[^>]*>(.*?)</fonts>", self.xml, re.S)
        fonts = re.findall(r"<font\b[^>]*?(?:/>|>.*?</font>)",
                           block.group(1), re.S) if block else []
        font_id = int(found.group(1)) if found else 0
        size = (re.search(r'<sz val="([\d.]+)"', fonts[font_id])
                if font_id < len(fonts) else None)
        return float(size.group(1)) if size else 11.0

    def same_font_as(self, index, model):
        """Copy of style `index` that uses the font of style `model`."""
        key = ("font", index, model)
        if key not in self.cache:
            font = re.search(r'fontId="(\d+)"', self.xfs[model]).group(1)
            xf = re.sub(r'\s+applyFont="[^"]*"', "", self.xfs[index])
            xf = re.sub(r'fontId="\d+"', f'fontId="{font}"', xf, count=1)
            self.xfs.append(xf)
            self.added.append(len(self.xfs) - 1)
            self.cache[key] = len(self.xfs) - 1
        return self.cache[key]

    def result(self):
        if not self.added:
            return self.xml
        block = (
            f'<cellXfs count="{len(self.xfs)}">'
            + "".join(self.xfs) + "</cellXfs>"
        )
        start, end = self.block.span()
        xml = self.xml[:start] + block + self.xml[end:]
        if getattr(self, "fonts_added", False):
            xml = re.sub(r"<fonts\b[^>]*>.*?</fonts>",
                         lambda m: f'<fonts count="{len(self.fonts)}">'
                         + "".join(self.fonts) + "</fonts>",
                         xml, count=1, flags=re.S)
        return xml


def set_cell_text(sheet_xml, ref, text, styles):
    """Put text into one cell (blank text clears it). -> (xml, found)"""
    pattern = re.compile(rf'<c r="{ref}"([^>]*?)(?:/>|>.*?</c>)', re.S)
    match = pattern.search(sheet_xml)
    if not match:
        return sheet_xml, False

    style = re.search(r'\bs="(\d+)"', match.group(1))
    style_index = int(style.group(1)) if style else 0

    if text:
        new_style = styles.shrink_index(style_index)
        cell = (
            f'<c r="{ref}" s="{new_style}" t="inlineStr">'
            f'<is><t xml:space="preserve">{xml_text(text)}</t></is></c>'
        )
    else:
        cell = f'<c r="{ref}" s="{style_index}"/>' if style else f'<c r="{ref}"/>'

    return sheet_xml[:match.start()] + cell + sheet_xml[match.end():], True


def column_letters_number(letters):
    number = 0
    for char in letters:
        number = number * 26 + ord(char) - ord("A") + 1
    return number


def column_widths(sheet_xml, first, last=None):
    """The widths (in characters) of the columns first..last of a sheet."""
    default = re.search(r'<sheetFormatPr\b[^>]*defaultColWidth="([\d.]+)"',
                        sheet_xml)
    default = float(default.group(1)) if default else 8.43
    defined = [(int(m.group(1)), int(m.group(2)), float(m.group(3)))
               for m in re.finditer(
                   r'<col\b[^>]*?min="(\d+)"[^>]*?max="(\d+)"[^>]*?'
                   r'width="([\d.]+)"', sheet_xml)]
    widths = []
    for column in range(column_letters_number(first),
                        column_letters_number(last or first) + 1):
        widths.append(next((w for low, high, w in defined
                            if low <= column <= high), default))
    return tuple(widths)


def merged_widths(sheet_xml, ref):
    """The column widths of the cell `ref`: every column of the merged
    cell that starts there, or its own column."""
    start = re.match(r"[A-Z]+", ref).group(0)
    merge = re.search(rf'<mergeCell ref="{ref}:([A-Z]+)\d+"/>', sheet_xml)
    return column_widths(sheet_xml, start, merge.group(1) if merge else None)


def two_line_style(style, text, widths, styles):
    """(style index, layout) of a text that may print on two lines: as the
    Findings of a shipment line, a text too long for one line of the cell's
    own font prints on two wrapped lines of fsr_print_fit.SMALL_SIZE
    points; one still longer shrinks to fit on one line (as every cell)."""
    fit = fsr_print_fit.layout(text, widths, styles.font_size(style))
    if fit == fsr_print_fit.TWO:
        return styles.wrap_small_index(style, fsr_print_fit.SMALL_SIZE), fit
    return styles.shrink_index(style), fit


def set_two_line_text(sheet_xml, ref, text, styles):
    """set_cell_text for a text that may print on two lines (a Declared
    Goods Description). -> (xml, found, layout)"""
    pattern = re.compile(rf'<c r="{ref}"([^>]*?)(?:/>|>.*?</c>)', re.S)
    match = pattern.search(sheet_xml)
    if not match or not text:
        xml, found = set_cell_text(sheet_xml, ref, text, styles)
        return xml, found, fsr_print_fit.ONE
    style = re.search(r'\bs="(\d+)"', match.group(1))
    new_style, fit = two_line_style(int(style.group(1)) if style else 0,
                                    text, merged_widths(sheet_xml, ref),
                                    styles)
    cell = (f'<c r="{ref}" s="{new_style}" t="inlineStr">'
            f'<is><t xml:space="preserve">{xml_text(text)}</t></is></c>')
    return sheet_xml[:match.start()] + cell + sheet_xml[match.end():], True, fit


PLACEHOLDER_PATTERN = re.compile(r"^\s*entry\s+for\b", re.I)


def find_placeholder_cells(sheet_xml, shared_xml):
    """{cell: text} for every cell showing an 'Entry for ...' placeholder."""
    strings = [
        html.unescape("".join(re.findall(r"<t\b[^>]*>(.*?)</t>", item, re.S)))
        for item in re.findall(r"<si\b[^>]*>.*?</si>", shared_xml, re.S)
    ]

    found = {}
    for match in re.finditer(
        r'<c r="([A-Z]+\d+)"([^>]*?)>\s*<v>(\d+)</v>\s*</c>', sheet_xml
    ):
        if 't="s"' not in match.group(2):
            continue
        index = int(match.group(3))
        if index < len(strings) and PLACEHOLDER_PATTERN.match(strings[index]):
            found[match.group(1)] = strings[index]

    return found


# ---------- Types of Goods check boxes ----------------------
# The six check boxes of the First Page are Excel "Form Control" check
# boxes. To tick one, the package needs two small changes: checked="Checked"
# in its ctrlProp part and <x:Checked>1</x:Checked> in the drawing (VML).
# The boxes are recognised by where they sit on the sheet (row + left /
# right column), so the order of the files does not matter.
#           (sheet row, 0 = left column / 1 = right column) -> key
CHECKBOX_POSITIONS = {
    (16, 0): "new",
    (17, 0): "used",
    (18, 0): "food_stuffs",
    (16, 1): "vehicle",
    (17, 1): "pharma_chemicals",
    (18, 1): "others",
}
RIGHT_COLUMN_OFFSET = 800000        # EMU: right-hand boxes start further in


def checked_goods_keys(data):
    """Keys of the Types of Goods that are ticked in this report."""
    types = data.get("goods_types") or {}
    return {key for key in CHECKBOX_POSITIONS.values() if types.get(key)}


def find_form_checkboxes(source, sheet_xml):
    """{key: (shape id, ctrlProp part)} for the check boxes on the sheet."""
    rels_part = posixpath.join(
        posixpath.dirname(FORM_SHEET_XML), "_rels",
        posixpath.basename(FORM_SHEET_XML) + ".rels"
    )
    try:
        rels = {
            r["Id"]: r["Target"] for r in package_relationships(
                source.read(rels_part).decode("utf-8")
            )
        }
    except KeyError:
        return {}

    found = {}
    for match in re.finditer(
        r'<control\b([^>]*)>(.*?)</control>', sheet_xml, re.S
    ):
        attrs, inner = match.groups()
        shape = re.search(r'shapeId="(\d+)"', attrs)
        rid = re.search(r'r:id="([^"]+)"', attrs)
        origin = re.search(
            r"<(?:xdr:)?from>\s*<xdr:col>\d+</xdr:col>\s*<xdr:colOff>(\d+)"
            r"</xdr:colOff>\s*<xdr:row>(\d+)</xdr:row>", inner)
        if not (shape and rid and origin and rid.group(1) in rels):
            continue

        side = 1 if int(origin.group(1)) > RIGHT_COLUMN_OFFSET else 0
        key = CHECKBOX_POSITIONS.get((int(origin.group(2)) + 1, side))
        if key:
            part = posixpath.normpath(posixpath.join(
                posixpath.dirname(FORM_SHEET_XML), rels[rid.group(1)]))
            found[key] = (shape.group(1), part)
    return found


def tick_form_checkboxes(source, sheet_xml, keys):
    """Return {part name: new bytes} that tick the given check boxes."""
    if not keys:
        return {}

    boxes = find_form_checkboxes(source, sheet_xml)
    changed = {}

    rels_part = posixpath.join(
        posixpath.dirname(FORM_SHEET_XML), "_rels",
        posixpath.basename(FORM_SHEET_XML) + ".rels"
    )
    vml_part = next(
        (posixpath.normpath(posixpath.join(
            posixpath.dirname(FORM_SHEET_XML), r["Target"]))
         for r in package_relationships(
             source.read(rels_part).decode("utf-8"))
         if r["Type"].endswith("/vmlDrawing")),
        None
    )
    vml = source.read(vml_part).decode("utf-8") if vml_part else ""

    for key in keys:
        if key not in boxes:
            continue
        shape_id, prop_part = boxes[key]

        prop = changed.get(prop_part) or source.read(prop_part).decode("utf-8")
        if 'checked="' not in prop:
            prop = prop.replace(
                'objectType="CheckBox"',
                'objectType="CheckBox" checked="Checked"', 1)
        changed[prop_part] = prop

        if vml:
            vml = re.sub(
                rf'(<v:shape\b[^>]*\bid="_x0000_s{shape_id}"'
                r'.*?<x:Anchor>[^<]*</x:Anchor>)(?!\s*<x:Checked>)',
                r"\1<x:Checked>1</x:Checked>", vml, count=1, flags=re.S)

    if vml_part and vml:
        changed[vml_part] = vml

    return {name: text.encode("utf-8") if isinstance(text, str) else text
            for name, text in changed.items()}


def fill_first_page_form(template_path, output_path, values, by_label=(),
                         checked=(), two_lines=(), too_long=None):
    """
    Copy the template and fill the cells. Everything else is kept.

    values   : {cell: text} for the known cells.
    by_label : [(regex, text)] - fills any cell whose "Entry for ..."
               placeholder matches the regex (e.g. "Entry for control #"),
               wherever you put it on the form.
    checked  : keys of the Types of Goods check boxes to tick.
    two_lines: cells whose text may print on two small lines (the
               Declared Goods Descriptions); the ones still too long for
               two lines are added to the list `too_long`.
    Returns the placeholders that matched nothing (they are cleared).
    """
    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.exists():
        raise FileNotFoundError(
            "The report form template was not found.\n\n"
            f"Put First_Page.xlsx here:\n{template_path}"
        )

    with zipfile.ZipFile(template_path) as source:
        sheet_xml = source.read(FORM_SHEET_XML).decode("utf-8")
        styles = StyleCloner(source.read(FORM_STYLES_XML).decode("utf-8"))

        try:
            shared_xml = source.read("xl/sharedStrings.xml").decode("utf-8")
        except KeyError:
            shared_xml = ""
        placeholders = find_placeholder_cells(sheet_xml, shared_xml)

        missing = []
        for ref, text in values.items():
            if ref in two_lines:
                sheet_xml, found, fit = set_two_line_text(sheet_xml, ref,
                                                          text, styles)
                if fit == fsr_print_fit.LONG and too_long is not None:
                    too_long.append(ref)
            else:
                sheet_xml, found = set_cell_text(sheet_xml, ref, text, styles)
            if not found:
                missing.append(ref)

        if missing:
            raise ValueError(
                "The form template does not match the program "
                f"(cells not found: {', '.join(missing)})."
            )

        # Placeholders not in the fixed list (for example "Entry for
        # control #"): fill them by their label, or clear them so the
        # words "Entry for ..." never appear on the printed form.
        leftover = []
        for ref, placeholder in placeholders.items():
            if ref in values:
                continue
            text = next(
                (t for pattern, t in by_label
                 if re.search(pattern, placeholder, re.I)),
                None
            )
            if text is None:
                leftover.append(placeholder.strip())
                text = ""
            sheet_xml, _ = set_cell_text(sheet_xml, ref, text, styles)

        ticked = tick_form_checkboxes(source, sheet_xml, checked)

        # Open the form at the top instead of where it was last scrolled.
        sheet_xml = re.sub(r'\s+topLeftCell="[^"]*"', "", sheet_xml, count=1)
        sheet_xml = re.sub(
            r"<selection\b[^>]*/>",
            '<selection activeCell="A1" sqref="A1"/>',
            sheet_xml, count=1
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(output_path.stem + ".saving.tmp")

        try:
            with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
                for item in source.infolist():
                    name = item.filename
                    if name == CALC_CHAIN_PART:
                        continue

                    content = source.read(name)
                    if name == FORM_SHEET_XML:
                        content = sheet_xml.encode("utf-8")
                    elif name in ticked:
                        content = ticked[name]
                    elif name == FORM_STYLES_XML:
                        content = styles.result().encode("utf-8")
                    elif name in ("[Content_Types].xml",
                                  "xl/_rels/workbook.xml.rels"):
                        content = remove_calc_chain_refs(
                            content.decode("utf-8")
                        ).encode("utf-8")
                    target.writestr(item, content)

            os.replace(temp_path, output_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    return leftover


def create_report_form(excel_path, data, folder=None):
    """
    Fill the First Page form for this report.
    Returns (path of the filled form, [notes]).
    """
    folder = Path(folder or Path(excel_path).parent / FORM_FOLDER_NAME)
    output = folder / f"{safe_filename(data['control_no'])}_First_Page.xlsx"

    values, notes = build_first_page_values(data)
    too_long = []
    leftover = fill_first_page_form(
        FORM_TEMPLATE, output, values,
        by_label=[(r"control", data["control_no"])],
        checked=checked_goods_keys(data),
        two_lines=GOODS_DESCRIPTION_CELLS, too_long=too_long,
    )
    for ref in too_long:
        notes.append(too_long_note(
            f"Declared Goods line "
            f"{GOODS_DESCRIPTION_CELLS.index(ref) + 1}"))

    if leftover:
        notes.append(
            "These placeholders on the form are not connected to any "
            "field yet, so they were left blank: "
            + ", ".join(f'"{text}"' for text in leftover) + "."
        )

    return output, notes


# =====================================================
# OFFICIAL REPORT FORM - SECOND PAGE: CARGO DETAILS
# (item lists + findings and remarks)
# =====================================================
# data/excel/Cargo_Details.xlsx has two sheets:
#   WarehouseReceiving - the Cargo Details page
#   BlankForm          - a ruled page used for extra remarks
#
# Layout rules used when filling it:
#   * Row 12 is the heading. Item lines start in row 13 (five rows are
#     always shown). Row 18 is the 6th item line.
#   * The "Remarks:" row follows the last item (row 19 up to 6 items),
#     so with 7 or more items the Remarks area moves down one row per item.
#   * If fewer than 5 remark rows are left on the page, the remarks go
#     to a blank form page. Remarks that do not fit also continue there.
#   * A page holds 30 item lines (rows 13-42). More items = another
#     Cargo Details sheet with the heading repeated.
#
# Containerized_Loading_Form.xlsx has the same layout for the
# Containerized / Loading Item List forms: sheets "Containerized" and
# "Loading" (Container No. / Truck Plate No. in A, Descriptions in B:D).
# It has no blank form: extra remarks go on its own sheet with rows
# 12-42 ruled as remark lines.

CARGO_TEMPLATE = BASE_DIR / "data" / "excel" / "Cargo_Details.xlsx"
UNIT_FORM_TEMPLATE = (BASE_DIR / "data" / "excel"
                      / "Containerized_Loading_Form.xlsx")

BLANK_FIRST_LINE_ROW = 12
BLANK_LINES_PER_PAGE = CARGO_LAST_ROW - BLANK_FIRST_LINE_ROW + 1   # 31

# Cargo Details column -> Item List field (A:C, E:F and H:I are merged).
CARGO_COLUMNS = {
    "A": "Description of Goods",
    "D": "PO Number",
    "E": "Packaging",
    "G": "Quantity",
    "H": "Dimensions",
    "J": "Weights",
    "K": "Findings",
}
# Containerized / Loading form column -> Item List field (B:D, E:F and
# H:I are merged).
UNIT_CARGO_COLUMNS = {
    "A": UNIT_NO_HEADER,
    "B": "Description of Goods",
    "E": "Packaging",
    "G": "Quantity",
    "H": "Dimensions",
    "J": "Weights",
    "K": "Findings",
}
# The Findings column of a line with a Packing List ("<Packing List> ·
# <Findings>"): what fits one line of the form's font; up to
# FINDINGS_TWO_LINES characters it is printed on two wrapped lines of
# FINDINGS_SMALL_SIZE points instead of one shrunken line (longer text still
# shrinks to fit, as every cell does).
FINDINGS_ONE_LINE = 23
FINDINGS_TWO_LINES = 56
FINDINGS_SMALL_SIZE = 9
# Item List form -> (template sheet, blank form sheet, columns, merged
# cells of an item row)
CARGO_LAYOUTS = {
    ITEM_FORM_DEFAULT: ("WarehouseReceiving", "BlankForm", CARGO_COLUMNS,
                        ("A{0}:C{0}", "E{0}:F{0}", "H{0}:I{0}")),
    ITEM_FORM_CONTAINERIZED: ("Containerized", "Containerized",
                              UNIT_CARGO_COLUMNS,
                              ("B{0}:D{0}", "E{0}:F{0}", "H{0}:I{0}")),
    ITEM_FORM_LOADING: ("Loading", "Loading", UNIT_CARGO_COLUMNS,
                        ("B{0}:D{0}", "E{0}:F{0}", "H{0}:I{0}")),
}


def cargo_template_for(form):
    """The workbook holding the Cargo Details page of an Item List form."""
    if item_form_name(form) == ITEM_FORM_DEFAULT:
        return CARGO_TEMPLATE
    return UNIT_FORM_TEMPLATE

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"]


# ---------- header: inspection date / period ----------------

def long_date(day):
    return f"{MONTH_NAMES[day.month - 1]} {day.day}, {day.year}"


def format_inspection_period(inspection, commenced, completion):
    """
    Same day            -> the inspection date          Oct 26, 2026
    Several days        -> commenced - completion       Oct 2-4, 2026
    Across two months   ->                              Oct 29 - Nov 5, 2026
    """
    inspection_day = parse_any_date(inspection)
    start = parse_any_date(commenced) or inspection_day
    end = parse_any_date(completion) or start

    if start is None:
        return ""

    if end < start:
        start, end = end, start

    if start == end:
        return long_date(inspection_day or start)

    first = MONTH_NAMES[start.month - 1]
    last = MONTH_NAMES[end.month - 1]

    if start.year == end.year and start.month == end.month:
        return f"{first} {start.day}-{end.day}, {start.year}"
    if start.year == end.year:
        return f"{first} {start.day} - {last} {end.day}, {end.year}"
    return f"{long_date(start)} - {long_date(end)}"


# ---------- page planning (pure logic) ---------------------

def plan_cargo_pages(items, remarks):
    """
    Decide what goes on which page.
    Returns a list of pages:
      {"kind": "cargo", "items": [...], "remarks": [...], "continued": bool}
      {"kind": "blank", "remarks": [...]}
    """
    pages = []

    chunks = [
        items[i:i + CARGO_MAX_ITEMS]
        for i in range(0, len(items), CARGO_MAX_ITEMS)
    ] or [[]]

    # Full pages in front carry items only.
    for chunk in chunks[:-1]:
        pages.append(
            {"kind": "cargo", "items": chunk, "remarks": [], "continued": False}
        )

    # Last Cargo Details page: the Remarks area follows the items.
    last = chunks[-1]
    available, _ = remark_capacity(len(items))

    # The Cargo Details page holds 30 rows shared by the items and the
    # remarks. If the remarks do not all fit, ALL of them move to the
    # blank Additional Details form (they are never split between the two pages).
    if 0 < available and len(remarks) <= available:
        on_page, rest = list(remarks), []
    else:
        on_page, rest = [], list(remarks)

    pages.append({
        "kind": "cargo", "items": last,
        "remarks": on_page, "continued": bool(rest),
    })

    # Remarks that did not fit continue on blank form pages.
    for i in range(0, len(rest), BLANK_LINES_PER_PAGE):
        pages.append(
            {"kind": "blank", "remarks": rest[i:i + BLANK_LINES_PER_PAGE]}
        )

    return pages


# ---------- building the sheet XML --------------------------

def read_template_row(sheet_xml, row):
    """-> (row attributes, {column: style index}) of a template row."""
    match = re.search(rf'<row r="{row}"([^>]*)>(.*?)</row>', sheet_xml, re.S)
    if not match:
        raise ValueError(f"The Cargo Details template has no row {row}.")

    styles = {}
    for cell in re.finditer(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>)', match.group(2)):
        style = re.search(r'\bs="(\d+)"', cell.group(2))
        styles[cell.group(1)] = int(style.group(1)) if style else 0

    return match.group(1), styles


def cell_xml(ref, style, text, styles, horizontal=None, fixed=False):
    if text:
        # fixed: the style is used as it is (already a wrapping variant)
        shrunk = style if fixed else styles.shrink_index(style, horizontal)
        return (
            f'<c r="{ref}" s="{shrunk}" t="inlineStr">'
            f'<is><t xml:space="preserve">{xml_text(text)}</t></is></c>'
        )
    return f'<c r="{ref}" s="{style}"/>'


def row_xml(row, attrs, cell_styles, texts, styles, horizontal=None,
            fixed=()):
    cells = "".join(
        cell_xml(f"{col}{row}", cell_styles[col], texts.get(col, ""),
                 styles, horizontal, fixed=col in fixed)
        for col in "ABCDEFGHIJK"
    )
    return f'<row r="{row}"{attrs}>{cells}</row>'


def replace_rows(sheet_xml, first_row, last_row, rows_xml):
    """Swap the XML of rows first_row..last_row for new rows."""
    start = sheet_xml.index(f'<row r="{first_row}"')
    end = sheet_xml.index(f'<row r="{last_row + 1}"')
    return sheet_xml[:start] + "".join(rows_xml) + sheet_xml[end:]


def replace_merges(sheet_xml, first_row, last_row, new_merges):
    """Drop the merged cells starting in these rows and add new ones."""
    match = re.search(r'<mergeCells count="\d+">(.*?)</mergeCells>',
                      sheet_xml, re.S)
    refs = re.findall(r'<mergeCell ref="([^"]+)"/>', match.group(1))

    kept = [
        ref for ref in refs
        if not first_row <= int(re.search(r"\d+", ref).group(0)) <= last_row
    ]
    merged = kept + list(new_merges)

    block = (
        f'<mergeCells count="{len(merged)}">'
        + "".join(f'<mergeCell ref="{ref}"/>' for ref in merged)
        + "</mergeCells>"
    )
    return sheet_xml[:match.start()] + block + sheet_xml[match.end():]


def fill_page_header(sheet_xml, period, consignee, styles):
    # A45 (Cargo Details and the Blank form) = the user's complete name
    for ref, text in (("I3", period), ("C5", consignee),
                      ("A45", print_name["value"])):
        sheet_xml, found = set_cell_text(sheet_xml, ref, text, styles)
        if not found:
            raise ValueError(f"The Cargo Details template has no cell {ref}.")
    return sheet_xml


def build_cargo_page_xml(sheet_xml, page, period, consignee, styles,
                         form=ITEM_FORM_DEFAULT, too_long=None):
    """too_long: a list the item lines whose Description does not fit two
    printed lines are added to."""
    sheet_xml = fill_page_header(sheet_xml, period, consignee, styles)
    _, _, columns, item_merges = CARGO_LAYOUTS[item_form_name(form)]
    # the Description: two small lines when too long for one, as Findings
    description = next(col for col, header in columns.items()
                       if header == "Description of Goods")
    merged = next((merge.format("").split(":") for merge in item_merges
                   if merge.startswith(description)), (description,))
    description_widths = column_widths(sheet_xml, *merged)

    attrs, item_styles = read_template_row(sheet_xml, CARGO_FIRST_ROW)
    _, ruled_styles = read_template_row(sheet_xml, 18)
    _, line_styles = read_template_row(sheet_xml, 20)
    _, last_styles = read_template_row(sheet_xml, CARGO_LAST_ROW)

    rows, merges = [], []
    row = CARGO_FIRST_ROW
    items = page["items"]

    # Item lines (always at least five rows).
    for index in range(max(len(items), CARGO_MIN_ITEM_ROWS)):
        item = items[index] if index < len(items) else {}
        texts = {
            col: item.get(header, "") for col, header in columns.items()
        }
        # a line received from a shipment: "<Packing List> · <Findings>"
        texts["K"] = printed_findings(item) if item else ""
        texts["G"] = " ".join(t for t in split_quantity_unit(
            item.get("Quantity"), item.get("UOM")) if t)
        cell_styles, fixed = item_styles, ()
        if item and str(item.get("Packing List No.") or "").strip() and \
                FINDINGS_ONE_LINE < len(texts["K"]) <= FINDINGS_TWO_LINES:
            # two readable lines instead of one shrunken line
            cell_styles = dict(item_styles, K=styles.wrap_small_index(
                item_styles["K"], FINDINGS_SMALL_SIZE))
            fixed = ("K",)
        if texts[description].strip():
            style, fit = two_line_style(item_styles[description],
                                        texts[description],
                                        description_widths, styles)
            cell_styles = dict(cell_styles, **{description: style})
            fixed += (description,)
            if fit == fsr_print_fit.LONG and too_long is not None:
                too_long.append(item)
        rows.append(row_xml(row, attrs, cell_styles, texts, styles,
                            fixed=fixed))
        merges += [merge.format(row) for merge in item_merges]
        row += 1

    # Up to five items: row 18 stays an empty ruled row.
    if row == CARGO_FIRST_ROW + CARGO_MIN_ITEM_ROWS:
        rows.append(row_xml(row, attrs, ruled_styles, {}, styles))
        row += 1

    # "Remarks:" row, then the remark lines down to row 42.
    if row <= CARGO_LAST_ROW:
        label = ""                  # no "Remarks:" text (the row stays)
        if page["continued"]:
            merges.append(f"A{row}:K{row}")
        rows.append(row_xml(row, attrs, ruled_styles, {"A": label}, styles))
        row += 1

        remarks = page["remarks"]
        index = 0
        while row <= CARGO_LAST_ROW:
            cell_styles = last_styles if row == CARGO_LAST_ROW else line_styles
            text = remarks[index] if index < len(remarks) else ""
            rows.append(row_xml(row, attrs, cell_styles, {"A": text},
                                styles, horizontal="left"))
            merges.append(f"A{row}:K{row}")
            index += 1
            row += 1

    sheet_xml = replace_rows(sheet_xml, CARGO_FIRST_ROW, CARGO_LAST_ROW, rows)
    return replace_merges(sheet_xml, CARGO_FIRST_ROW, CARGO_LAST_ROW, merges)


def build_blank_page_xml(sheet_xml, page, period, consignee, styles):
    sheet_xml = fill_page_header(sheet_xml, period, consignee, styles)
    sheet_xml, _ = set_cell_text(sheet_xml, "A11", "ADDITIONAL DETAILS", styles)

    attrs, line_styles = read_template_row(sheet_xml, 20)
    _, last_styles = read_template_row(sheet_xml, CARGO_LAST_ROW)

    rows, merges = [], []
    remarks = page["remarks"]

    for index, row in enumerate(range(BLANK_FIRST_LINE_ROW,
                                      CARGO_LAST_ROW + 1)):
        cell_styles = last_styles if row == CARGO_LAST_ROW else line_styles
        text = remarks[index] if index < len(remarks) else ""
        rows.append(row_xml(row, attrs, cell_styles, {"A": text},
                            styles, horizontal="left"))
        merges.append(f"A{row}:K{row}")

    sheet_xml = replace_rows(sheet_xml, BLANK_FIRST_LINE_ROW, CARGO_LAST_ROW,
                             rows)
    return replace_merges(sheet_xml, BLANK_FIRST_LINE_ROW, CARGO_LAST_ROW,
                          merges)


def tidy_sheet_xml(sheet_xml, selected):
    """Plain sheet view; only the first sheet is selected."""
    sheet_xml = re.sub(r'(<sheetPr)\s+codeName="[^"]*"', r"\1", sheet_xml,
                       count=1)
    flag = 'tabSelected="1" ' if selected else ""
    view = (
        f'<sheetViews><sheetView {flag}workbookViewId="0">'
        '<selection activeCell="A1" sqref="A1"/></sheetView></sheetViews>'
    )
    return re.sub(r"<sheetViews>.*?</sheetViews>", view, sheet_xml,
                  count=1, flags=re.S)


# ---------- building the workbook package -------------------

def package_relationships(xml):
    """[{Id, Type, Target, ...}] of a .rels file."""
    return [
        dict(re.findall(r'([\w:]+)="([^"]*)"', element))
        for element in re.findall(r"<Relationship\b[^>]*/>", xml)
    ]


def locate_template_sheet(source, sheet_name):
    """-> (sheet xml, drawing xml bytes, drawing rels bytes)"""
    workbook = source.read("xl/workbook.xml").decode("utf-8")
    sheet = re.search(
        rf'<sheet\b[^>]*\bname="{re.escape(sheet_name)}"[^>]*>', workbook
    )
    if not sheet:
        raise ValueError(f'The sheet "{sheet_name}" was not found in '
                         "the form template.")
    rid = re.search(r'r:id="([^"]+)"', sheet.group(0)).group(1)

    rels = package_relationships(
        source.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    )
    target = next(r["Target"] for r in rels if r["Id"] == rid)
    sheet_part = posixpath.normpath(posixpath.join("xl", target))

    sheet_rels_part = posixpath.join(
        posixpath.dirname(sheet_part), "_rels",
        posixpath.basename(sheet_part) + ".rels"
    )
    drawing_target = next(
        r["Target"] for r in package_relationships(
            source.read(sheet_rels_part).decode("utf-8")
        )
        if r["Type"].endswith("/drawing")
    )
    drawing_part = posixpath.normpath(
        posixpath.join(posixpath.dirname(sheet_part), drawing_target)
    )
    drawing_rels_part = posixpath.join(
        posixpath.dirname(drawing_part), "_rels",
        posixpath.basename(drawing_part) + ".rels"
    )

    return (
        source.read(sheet_part).decode("utf-8"),
        source.read(drawing_part),
        source.read(drawing_rels_part),
    )


XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'


def write_pages_package(source, output_path, new_parts, names, styles,
                        print_area):
    """
    Write a workbook made of the given sheet pages.
      source      - the open template package (zipfile)
      new_parts   - {part name: bytes} of the new sheets + drawings
      names       - sheet names in page order
      print_area  - e.g. '$A$1:$K$53' (the same for every page)
    """
    # workbook.xml: the list of sheets and their print areas
    workbook = source.read("xl/workbook.xml").decode("utf-8")
    sheets = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rIdPage{index}"/>'
        for index, name in enumerate(names, start=1)
    )
    workbook = re.sub(r"<sheets>.*?</sheets>", f"<sheets>{sheets}</sheets>",
                      workbook, count=1, flags=re.S)
    defined = "".join(
        f'<definedName name="_xlnm.Print_Area" localSheetId="{index - 1}">'
        f"'{name}'!{print_area}</definedName>"
        for index, name in enumerate(names, start=1)
    )
    workbook = re.sub(r"<definedNames>.*?</definedNames>",
                      f"<definedNames>{defined}</definedNames>",
                      workbook, count=1, flags=re.S)

    # workbook.xml.rels: replace the worksheet relationships
    rels_xml = source.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rels_xml = re.sub(
        r'<Relationship\b[^>]*relationships/worksheet"[^>]*/>', "",
        rels_xml
    )
    page_rels = "".join(
        '<Relationship Id="rIdPage%d" Type="http://schemas.openxmlformats.'
        'org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet%d.xml"/>' % (index, index)
        for index in range(1, len(names) + 1)
    )
    rels_xml = rels_xml.replace("</Relationships>",
                                page_rels + "</Relationships>")
    rels_xml = remove_calc_chain_refs(rels_xml)

    # [Content_Types].xml
    types_xml = source.read("[Content_Types].xml").decode("utf-8")
    types_xml = re.sub(
        r'<Override PartName="/xl/(?:worksheets/sheet|drawings/drawing)'
        r'\d+\.xml"[^>]*/>', "", types_xml
    )
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.worksheet+xml"/>'
        f'<Override PartName="/xl/drawings/drawing{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'drawing+xml"/>'
        for index in range(1, len(names) + 1)
    )
    types_xml = types_xml.replace("</Types>", overrides + "</Types>")
    types_xml = remove_calc_chain_refs(types_xml)

    # docProps/app.xml: list of sheet names
    app_xml = (
        XML_HEAD
        + '<Properties xmlns="http://schemas.openxmlformats.org/'
        'officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/'
        'docPropsVTypes"><Application>Microsoft Excel</Application>'
        '<HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant>'
        f"<vt:lpstr>Worksheets</vt:lpstr></vt:variant><vt:variant><vt:i4>"
        f"{len(names)}</vt:i4></vt:variant></vt:vector></HeadingPairs>"
        f'<TitlesOfParts><vt:vector size="{len(names)}" baseType="lpstr">'
        + "".join(f"<vt:lpstr>{name}</vt:lpstr>" for name in names)
        + "</vt:vector></TitlesOfParts></Properties>"
    )

    replaced = {
        "[Content_Types].xml": types_xml.encode("utf-8"),
        "xl/workbook.xml": workbook.encode("utf-8"),
        "xl/_rels/workbook.xml.rels": rels_xml.encode("utf-8"),
        "xl/styles.xml": styles.result().encode("utf-8"),
        "docProps/app.xml": app_xml.encode("utf-8"),
    }

    def is_old_page_part(name):
        return (
            name.startswith(("xl/worksheets/", "xl/drawings/",
                                     "xl/printerSettings/"))
            or name == CALC_CHAIN_PART
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.stem + ".saving.tmp")

    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
            target.writestr("[Content_Types].xml",
                            replaced["[Content_Types].xml"])

            for item in source.infolist():
                name = item.filename
                if name == "[Content_Types].xml" or is_old_page_part(name):
                    continue
                target.writestr(item, replaced.get(name,
                                                   source.read(name)))

            for name, content in new_parts.items():
                target.writestr(name, content)

        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass



def printable_items(form, item_lists):
    """The lines of an Item List form that go on its Cargo Details page."""
    items = [row for item_list in item_lists for row in item_list["rows"]]
    if form != ITEM_FORM_DEFAULT:
        # Lines kept only for a column this form does not print (PO
        # Number, prices typed on the Default form) are left out.
        columns = CARGO_LAYOUTS[form][2]
        items = [row for row in items
                 if any(str(row.get(header) or "").strip()
                        for header in columns.values())]
    return items


@functools.lru_cache(maxsize=8)
def _description_cell(form):
    """(column widths, font size) of the Description cell of the Cargo
    Details page of an Item List form, read from its template."""
    sheet_name, _, columns, item_merges = CARGO_LAYOUTS[item_form_name(form)]
    with zipfile.ZipFile(cargo_template_for(form)) as source:
        xml, _, _ = locate_template_sheet(source, sheet_name)
        styles = StyleCloner(source.read(FORM_STYLES_XML).decode("utf-8"))
    description = next(col for col, header in columns.items()
                       if header == "Description of Goods")
    merged = next((merge.format("").split(":") for merge in item_merges
                   if merge.startswith(description)), (description,))
    _, row_styles = read_template_row(xml, CARGO_FIRST_ROW)
    return (column_widths(xml, *merged),
            styles.font_size(row_styles[description]))


@functools.lru_cache(maxsize=1)
def _goods_description_cell():
    """(column widths, font size) of a Declared Goods Description cell of
    the First Page."""
    with zipfile.ZipFile(FORM_TEMPLATE) as source:
        xml = source.read(FORM_SHEET_XML).decode("utf-8")
        styles = StyleCloner(source.read(FORM_STYLES_XML).decode("utf-8"))
    ref = GOODS_DESCRIPTION_CELLS[0]
    style = re.search(rf'<c r="{ref}"[^>]*?\bs="(\d+)"', xml)
    return (merged_widths(xml, ref),
            styles.font_size(int(style.group(1)) if style else 0))


def description_fit(text, form=ITEM_FORM_DEFAULT):
    """fsr_print_fit.ONE / TWO / LONG: how an Item List Description prints
    on the Cargo Details page of `form`."""
    return fsr_print_fit.layout(text, *_description_cell(item_form_name(form)))


def goods_description_fit(text):
    """fsr_print_fit.ONE / TWO / LONG for a Declared Goods Description."""
    return fsr_print_fit.layout(text, *_goods_description_cell())


def too_long_notes(item_lists, too_long):
    """The notes for the item lines (of `item_lists`) printed with a
    Description too long for two lines: "Item List 1, line 3: ..."."""
    notes = []
    for number, item_list in enumerate(item_lists, start=1):
        for line, row in enumerate(item_list["rows"], start=1):
            if any(row is long for long in too_long):
                notes.append(too_long_note(f"Item List {number}, line {line}"))
    return notes


def item_forms_to_print(data):
    """[(form, item lists)] of every Item List form that has lines, in the
    order of the form buttons."""
    selected = item_form_name(data.get("item_form"))
    lists = dict(data.get("other_item_forms") or {})
    lists[selected] = data["item_lists"]
    return [(form, lists[form]) for form in ITEM_FORMS
            if form in lists and printable_items(form, lists[form])]


def build_cargo_workbook(template_path, output_path, data,
                         cargo_name="Cargo Details"):
    """
    Write the Cargo Details workbook for this report.
    Returns the number of pages as {"cargo": n, "blank": n}, and under
    "too_long" the item lines whose Description is too long for two
    printed lines.
    """
    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.exists():
        raise FileNotFoundError(
            "The Cargo Details template was not found.\n\n"
            f"Put {template_path.name} here:\n{template_path}"
        )

    general = data["general_information"]
    schedule = data["inspection_schedule"]
    period = format_inspection_period(
        general["inspection_date"],
        schedule["commenced_date"],
        schedule["completion_date"],
    )

    form = item_form_name(data.get("item_form"))
    cargo_sheet, blank_sheet, _, _ = CARGO_LAYOUTS[form]

    items = printable_items(form, data["item_lists"])
    pages = plan_cargo_pages(items, data["findings_and_remarks"])

    with zipfile.ZipFile(template_path) as source:
        cargo_xml, cargo_drawing, cargo_drawing_rels = locate_template_sheet(
            source, cargo_sheet)
        blank_xml, blank_drawing, blank_drawing_rels = locate_template_sheet(
            source, blank_sheet)
        styles = StyleCloner(source.read(FORM_STYLES_XML).decode("utf-8"))

        cargo_total = sum(1 for page in pages if page["kind"] == "cargo")
        blank_total = len(pages) - cargo_total

        new_parts = {}
        names = []
        counters = {"cargo": 0, "blank": 0}
        too_long = []

        for number, page in enumerate(pages, start=1):
            kind = page["kind"]
            counters[kind] += 1
            total = cargo_total if kind == "cargo" else blank_total
            base = cargo_name if kind == "cargo" else "Additional Details"
            names.append(base if total == 1 else f"{base} {counters[kind]}")

            if kind == "cargo":
                xml = build_cargo_page_xml(
                    cargo_xml, page, period, general["consignee"], styles,
                    form, too_long)
                drawing, drawing_rels = cargo_drawing, cargo_drawing_rels
            else:
                xml = build_blank_page_xml(
                    blank_xml, page, period, general["consignee"], styles)
                drawing, drawing_rels = blank_drawing, blank_drawing_rels

            xml = tidy_sheet_xml(xml, selected=(number == 1))

            new_parts[f"xl/worksheets/sheet{number}.xml"] = xml.encode("utf-8")
            new_parts[f"xl/worksheets/_rels/sheet{number}.xml.rels"] = (
                XML_HEAD
                + '<Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships"><Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                f'relationships/drawing" Target="../drawings/drawing{number}.xml"/>'
                "</Relationships>"
            ).encode("utf-8")
            new_parts[f"xl/drawings/drawing{number}.xml"] = drawing
            new_parts[f"xl/drawings/_rels/drawing{number}.xml.rels"] = (
                drawing_rels)

        write_pages_package(source, output_path, new_parts, names, styles,
                            "$A$1:$K$53")

    return {"cargo": cargo_total, "blank": blank_total, "too_long": too_long}


def create_cargo_form(excel_path, data, folder=None,
                      cargo_name="Cargo Details"):
    """Fill Cargo Details of data["item_form"]. Returns (path, page counts)."""
    folder = Path(folder or Path(excel_path).parent / FORM_FOLDER_NAME)
    form = item_form_name(data.get("item_form"))
    output = folder / (
        f"{safe_filename(data['control_no'])}_{form}_Cargo_Details.xlsx")
    pages = build_cargo_workbook(cargo_template_for(form), output, data,
                                 cargo_name)
    return output, pages


# =====================================================
# OFFICIAL REPORT FORM - INCIDENT REPORT (Bad Order only)
# =====================================================
# data/excel/Incident_Report.xlsx has one sheet,
# "IncidentReport": header cells B5 B6 B7 B8 / G5 G6 G7 and 15 lines
# A18 ... A32. Every incident card of the report becomes one sheet:
# "Incident Report", "Additional Incident Report 1", ...

INCIDENT_TEMPLATE = BASE_DIR / "data" / "excel" / "Incident_Report.xlsx"
INCIDENT_SHEET_NAME = "IncidentReport"
INCIDENT_PRINT_AREA = "$A$1:$I$46"
INCIDENT_FIRST_LINE_ROW = 18

INCIDENT_HEADER_CELLS = {
    "vessel": "B5", "voyage": "B6", "client": "B7", "so_number": "B8",
    "port": "G5", "date": "G6", "operation": "G7",
}


def fill_incident_page_xml(sheet_xml, report, styles):
    """Fill one Incident Report sheet from one incident card."""
    values = {
        cell: report.get(key, "")
        for key, cell in INCIDENT_HEADER_CELLS.items()
    }
    values[INCIDENT_HEADER_CELLS["date"]] = form_date(report.get("date", ""))

    # In the template line 1 is written in a bigger font than the other
    # 14 lines; print all 15 lines in the same font.
    first = re.search(rf'<c r="A{INCIDENT_FIRST_LINE_ROW}" s="(\d+)"',
                      sheet_xml)
    second = re.search(rf'<c r="A{INCIDENT_FIRST_LINE_ROW + 1}" s="(\d+)"',
                       sheet_xml)
    if first and second:
        new_style = styles.same_font_as(int(first.group(1)),
                                        int(second.group(1)))
        sheet_xml = (sheet_xml[:first.start(1)] + str(new_style)
                     + sheet_xml[first.end(1):])

    values["A38"] = print_name["value"]     # complete name of the preparer

    lines = [t for t in report.get("lines", []) if t][:INCIDENT_MAX_LINES]
    for index in range(INCIDENT_MAX_LINES):
        values[f"A{INCIDENT_FIRST_LINE_ROW + index}"] = (
            lines[index] if index < len(lines) else "")

    for ref, text in values.items():
        sheet_xml, found = set_cell_text(sheet_xml, ref, text, styles)
        if not found:
            raise ValueError(
                f"The Incident Report template does not match the program "
                f"(cell {ref} not found)."
            )

    # Printer settings are not copied into the new workbook, and the
    # drawing becomes the first (only) relationship of every page.
    sheet_xml = re.sub(r'(<pageSetup\b[^>]*?)\s+r:id="[^"]*"', r"\1",
                       sheet_xml, count=1)
    return re.sub(r'<drawing r:id="[^"]*"\s*/>', '<drawing r:id="rId1"/>',
                  sheet_xml, count=1)


def build_incident_workbook(template_path, output_path, data):
    """
    Write the Incident Report workbook (one sheet per card that has lines).
    Returns the number of pages (0 = nothing written).
    """
    reports = [
        (number, report)
        # S.O. No. and Port from the report itself (fsr_storage), also for
        # a report saved or imported with other values on its incident card
        for number, report in enumerate(incident_reports_of(data), start=1)
        if report["lines"]
    ]
    if not reports:
        return 0

    template_path = Path(template_path)
    if not template_path.exists():
        raise FileNotFoundError(
            "The Incident Report template was not found.\n\n"
            f"Put Incident_Report.xlsx here:\n{template_path}"
        )

    with zipfile.ZipFile(template_path) as source:
        page_xml, drawing, drawing_rels = locate_template_sheet(
            source, INCIDENT_SHEET_NAME)
        styles = StyleCloner(source.read(FORM_STYLES_XML).decode("utf-8"))

        new_parts, names = {}, []
        for page_no, (number, report) in enumerate(reports, start=1):
            names.append(incident_title(number))
            xml = fill_incident_page_xml(page_xml, report, styles)
            xml = tidy_sheet_xml(xml, selected=(page_no == 1))

            new_parts[f"xl/worksheets/sheet{page_no}.xml"] = xml.encode("utf-8")
            new_parts[f"xl/worksheets/_rels/sheet{page_no}.xml.rels"] = (
                XML_HEAD
                + '<Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships"><Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                f'relationships/drawing" Target="../drawings/drawing{page_no}.xml"/>'
                "</Relationships>"
            ).encode("utf-8")
            new_parts[f"xl/drawings/drawing{page_no}.xml"] = drawing
            new_parts[f"xl/drawings/_rels/drawing{page_no}.xml.rels"] = (
                drawing_rels)

        write_pages_package(source, output_path, new_parts, names, styles,
                            INCIDENT_PRINT_AREA)

    return len(reports)


def create_incident_form(excel_path, data, folder=None):
    """Fill the Incident Report form. Returns (path or None, pages)."""
    folder = Path(folder or Path(excel_path).parent / FORM_FOLDER_NAME)
    output = folder / f"{safe_filename(data['control_no'])}_Incident_Report.xlsx"
    pages = build_incident_workbook(INCIDENT_TEMPLATE, output, data)
    return (output if pages else None), pages


# =====================================================
# ONE WORKBOOK FOR THE WHOLE REPORT
# =====================================================
# First Page, Cargo Details (+ Remarks) and the Incident Report(s) are
# each built from their own template. merge_workbooks() then puts all of
# their sheets into ONE .xlsx (one sheet per page) - the cell styles,
# pictures and the Types of Goods check boxes come along unchanged.

def _style_sections(styles_xml):
    """Pieces of styles.xml that the merge needs."""
    def block(tag):
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", styles_xml, re.S)
        return match.group(1) if match else ""

    return {
        "numFmts": re.findall(r"<numFmt\b[^>]*/>", block("numFmts")),
        "fonts": re.findall(r"<font\b(?:[^>]*/>|[^>]*>.*?</font>)",
                            block("fonts"), re.S),
        "fills": re.findall(r"<fill\b(?:[^>]*/>|[^>]*>.*?</fill>)",
                            block("fills"), re.S),
        "borders": re.findall(r"<border\b(?:[^>]*/>|[^>]*>.*?</border>)",
                              block("borders"), re.S),
        "xfs": re.findall(r"<xf\b[^>]*?(?:/>|>.*?</xf>)", block("cellXfs"),
                          re.S),
    }


def _set_block(styles_xml, tag, items):
    """Replace <tag count=..>...</tag> with the given items."""
    new = f'<{tag} count="{len(items)}">' + "".join(items) + f"</{tag}>"
    pattern = re.compile(rf"<{tag}\b[^>]*>.*?</{tag}>", re.S)
    assert pattern.search(styles_xml), tag
    return pattern.sub(lambda _: new, styles_xml, count=1)


def _shift_attr(tag_text, attr, offset):
    return re.sub(
        rf'(\b{attr}=")(\d+)(")',
        lambda m: f"{m.group(1)}{int(m.group(2)) + offset}{m.group(3)}",
        tag_text
    )


def append_styles(base_xml, source_xml):
    """
    Add every cell style of `source_xml` to `base_xml`.
    Returns (new styles xml, offset) - a cell that used style n in the
    source uses style n + offset in the merged workbook.
    """
    base = _style_sections(base_xml)
    source = _style_sections(source_xml)

    # Number formats: keep built-in ids, give custom ones a free id.
    codes = {
        re.search(r'formatCode="([^"]*)"', f).group(1):
        int(re.search(r'numFmtId="(\d+)"', f).group(1))
        for f in base["numFmts"]
    }
    used_ids = set(codes.values())
    next_id = max([175, *used_ids]) + 1
    id_map = {}
    for fmt in source["numFmts"]:
        old_id = int(re.search(r'numFmtId="(\d+)"', fmt).group(1))
        code = re.search(r'formatCode="([^"]*)"', fmt).group(1)
        if code in codes:
            id_map[old_id] = codes[code]
        else:
            id_map[old_id] = next_id
            codes[code] = next_id
            base["numFmts"].append(
                re.sub(r'numFmtId="\d+"', f'numFmtId="{next_id}"', fmt,
                       count=1))
            next_id += 1

    offsets = {key: len(base[key]) for key in ("fonts", "fills", "borders")}
    offset = len(base["xfs"])

    for key in ("fonts", "fills", "borders"):
        base[key].extend(source[key])

    for xf in source["xfs"]:
        opening = re.match(r"<xf\b[^>]*", xf).group(0)
        changed = _shift_attr(opening, "fontId", offsets["fonts"])
        changed = _shift_attr(changed, "fillId", offsets["fills"])
        changed = _shift_attr(changed, "borderId", offsets["borders"])
        changed = re.sub(
            r'(\bnumFmtId=")(\d+)(")',
            lambda m: f"{m.group(1)}{id_map.get(int(m.group(2)), int(m.group(2)))}"
                      f"{m.group(3)}", changed)
        changed = re.sub(r'\bxfId="\d+"', 'xfId="0"', changed)
        base["xfs"].append(changed + xf[len(opening):])

    merged = base_xml
    if base["numFmts"]:
        if "<numFmts" in merged:
            merged = _set_block(merged, "numFmts", base["numFmts"])
        else:
            merged = merged.replace(
                "<fonts", '<numFmts count="%d">%s</numFmts><fonts' % (
                    len(base["numFmts"]), "".join(base["numFmts"])), 1)
    for key, tag in (("fonts", "fonts"), ("fills", "fills"),
                     ("borders", "borders"), ("xfs", "cellXfs")):
        merged = _set_block(merged, tag, base[key])

    # The fonts / cellXfs tags may carry extra attributes (x14ac:knownFonts)
    return merged, offset


def _plain_sheet_parts(source, strict=True):
    """
    Every sheet of a workbook package:
    [(name, sheet xml, drawing xml or None, drawing rels or None,
      print area or None)]
    """
    workbook = source.read("xl/workbook.xml").decode("utf-8")
    rels = {
        r["Id"]: r["Target"] for r in package_relationships(
            source.read("xl/_rels/workbook.xml.rels").decode("utf-8"))
    }
    areas = {}
    for match in re.finditer(
        r'<definedName\b[^>]*name="_xlnm.Print_Area"[^>]*localSheetId="(\d+)"'
        r"[^>]*>(.*?)</definedName>", workbook, re.S
    ):
        areas[int(match.group(1))] = match.group(2).split("!", 1)[-1]

    # shared strings of this package (cells become inline text)
    try:
        shared_xml = source.read("xl/sharedStrings.xml").decode("utf-8")
    except KeyError:
        shared_xml = ""
    strings = [
        m.group(1) or "" for m in re.finditer(
            r"<si\b[^>]*>(.*?)</si>|<si\s*/>", shared_xml, re.S)
    ]

    result = []
    sheets = re.findall(r"<sheet\b[^>]*/>", workbook)
    for index, tag in enumerate(sheets):
        name = html.unescape(re.search(r'name="([^"]*)"', tag).group(1))
        rid = re.search(r'r:id="([^"]+)"', tag).group(1)
        sheet_part = posixpath.normpath(posixpath.join("xl", rels[rid]))
        sheet_xml = source.read(sheet_part).decode("utf-8")

        def inline(match):
            text = strings[int(match.group(3))]
            attrs = (match.group(1) + match.group(2)).replace(' t="s"', "")
            return (f'<c{attrs} t="inlineStr"><is>{text}</is></c>')

        sheet_xml = re.sub(
            r'<c((?:\s[^>]*?)?)(\st="s")([^>]*)>\s*<v>(\d+)</v>\s*</c>',
            lambda m: (
                f'<c{m.group(1)}{m.group(3)} t="inlineStr"><is>'
                f"{strings[int(m.group(4))]}</is></c>"
            ), sheet_xml)

        rels_part = posixpath.join(
            posixpath.dirname(sheet_part), "_rels",
            posixpath.basename(sheet_part) + ".rels")
        drawing = drawing_rels = None
        if rels_part in source.namelist():
            sheet_rels = package_relationships(
                source.read(rels_part).decode("utf-8"))
            others = [r for r in sheet_rels
                      if not r["Type"].endswith(("/drawing", "/printerSettings"))]
            if others and strict:
                raise ValueError(
                    f'Sheet "{name}" has parts the merge cannot copy: '
                    + ", ".join(r["Type"].rsplit("/", 1)[-1] for r in others))
            target = next((r["Target"] for r in sheet_rels
                           if r["Type"].endswith("/drawing")), None)
            if target:
                drawing_part = posixpath.normpath(posixpath.join(
                    posixpath.dirname(sheet_part), target))
                drawing = source.read(drawing_part)
                d_rels = posixpath.join(
                    posixpath.dirname(drawing_part), "_rels",
                    posixpath.basename(drawing_part) + ".rels")
                drawing_rels = (source.read(d_rels)
                                if d_rels in source.namelist() else None)

        result.append((name, sheet_xml, drawing, drawing_rels,
                       areas.get(index)))
    return result


def merge_workbooks(paths, output_path, first_name=None):
    """
    Put all sheets of the given .xlsx files into one workbook.
    The first file is the base (its check boxes, pictures and settings stay
    as they are); the sheets of the other files are appended in order.
    """
    paths = [Path(p) for p in paths]
    output_path = Path(output_path)

    with zipfile.ZipFile(paths[0]) as base_zip:
        parts = {n: base_zip.read(n) for n in base_zip.namelist()
                 if not n.endswith("/")}
        base_sheets = _plain_sheet_parts(base_zip, strict=False)

    workbook = parts["xl/workbook.xml"].decode("utf-8")
    rels_xml = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    types_xml = parts["[Content_Types].xml"].decode("utf-8")
    styles_xml = parts["xl/styles.xml"].decode("utf-8")

    names = [name for name, *_ in base_sheets]
    areas = {name: area for name, _, _, _, area in base_sheets}

    if first_name and len(names) == 1:           # "FirstPage" -> "First Page"
        old = names[0]
        workbook = workbook.replace(f'name="{xml_text(old)}"',
                                    f'name="{xml_text(first_name)}"', 1)
        workbook = re.sub(
            rf"(<definedName\b[^>]*>){re.escape(old)}!",
            lambda m: f"{m.group(1)}'{first_name}'!", workbook)
        names[0] = first_name
        areas[first_name] = areas.pop(old)

    sheet_numbers = [int(n) for n in re.findall(
        r"xl/worksheets/sheet(\d+)\.xml", " ".join(parts))]
    drawing_numbers = [int(n) for n in re.findall(
        r"xl/drawings/drawing(\d+)\.xml", " ".join(parts))]
    next_sheet = max(sheet_numbers, default=0) + 1
    next_drawing = max(drawing_numbers, default=0) + 1
    next_sheet_id = max(
        [int(i) for i in re.findall(r'sheetId="(\d+)"', workbook)],
        default=0) + 1

    new_sheet_tags, new_rels, new_types, new_names = [], [], [], []
    new_defined = []
    media_done = {}

    for source_no, path in enumerate(paths[1:], start=1):
        with zipfile.ZipFile(path) as source:
            styles_xml, offset = append_styles(
                styles_xml, source.read("xl/styles.xml").decode("utf-8"))

            for name, sheet_xml, drawing, drawing_rels, area in \
                    _plain_sheet_parts(source):
                # --- styles + selection of this sheet
                sheet_xml = re.sub(
                    r"<(?:c|row)\b[^>]*>",
                    lambda m: _shift_attr(m.group(0), "s", offset), sheet_xml)  # noqa: B023 - used in this same pass
                sheet_xml = re.sub(
                    r"<col\b[^>]*>",
                    lambda m: _shift_attr(m.group(0), "style", offset),  # noqa: B023 - used in this same pass
                    sheet_xml)
                sheet_xml = sheet_xml.replace(' tabSelected="1"', "")
                sheet_xml = re.sub(r'(<pageSetup\b[^>]*?)\s+r:id="[^"]*"',
                                   r"\1", sheet_xml, count=1)

                # --- unique sheet name
                unique, copy_no = name, 2
                while unique in names or unique in new_names:
                    unique = f"{name[:28]} {copy_no}"
                    copy_no += 1
                new_names.append(unique)

                number = next_sheet
                next_sheet += 1
                parts[f"xl/worksheets/sheet{number}.xml"] = sheet_xml.encode(
                    "utf-8")

                if drawing is not None:
                    d_no = next_drawing
                    next_drawing += 1
                    parts[f"xl/drawings/drawing{d_no}.xml"] = drawing
                    if drawing_rels is not None:
                        text = drawing_rels.decode("utf-8")

                        def move_media(m):
                            base_name = posixpath.basename(m.group(2))
                            key = (source_no, base_name)  # noqa: B023 - used in this same pass
                            if key not in media_done:
                                new_media = f"merged{source_no}_{base_name}"  # noqa: B023 - used in this same pass
                                parts[f"xl/media/{new_media}"] = source.read(
                                    posixpath.normpath(posixpath.join(
                                        "xl/drawings", m.group(2))))
                                media_done[key] = new_media
                            return (f'{m.group(1)}../media/'
                                    f'{media_done[key]}"')

                        text = re.sub(r'(Target=")((?:\.\./)?media/[^"]+)"',
                                      move_media, text)
                        parts[f"xl/drawings/_rels/drawing{d_no}.xml.rels"] = \
                            text.encode("utf-8")
                    parts[f"xl/worksheets/_rels/sheet{number}.xml.rels"] = (
                        XML_HEAD
                        + '<Relationships xmlns="http://schemas.openxmlformats.'
                        'org/package/2006/relationships"><Relationship '
                        'Id="rId1" Type="http://schemas.openxmlformats.org/'
                        'officeDocument/2006/relationships/drawing" '
                        f'Target="../drawings/drawing{d_no}.xml"/>'
                        "</Relationships>").encode("utf-8")
                    sheet_xml = re.sub(r'<drawing r:id="[^"]*"\s*/>',
                                       '<drawing r:id="rId1"/>', sheet_xml)
                    parts[f"xl/worksheets/sheet{number}.xml"] = \
                        sheet_xml.encode("utf-8")
                    new_types.append(
                        f'<Override PartName="/xl/drawings/drawing{d_no}.xml" '
                        'ContentType="application/vnd.openxmlformats-'
                        'officedocument.drawing+xml"/>')

                new_sheet_tags.append(
                    f'<sheet name="{xml_text(unique)}" sheetId="{next_sheet_id}"'
                    f' r:id="rIdMerged{number}"/>')
                new_rels.append(
                    f'<Relationship Id="rIdMerged{number}" Type="http://schemas.'
                    'openxmlformats.org/officeDocument/2006/relationships/'
                    f'worksheet" Target="worksheets/sheet{number}.xml"/>')
                new_types.append(
                    f'<Override PartName="/xl/worksheets/sheet{number}.xml" '
                    'ContentType="application/vnd.openxmlformats-'
                    'officedocument.spreadsheetml.worksheet+xml"/>')
                next_sheet_id += 1
                index = len(names) + len(new_names) - 1
                if area:
                    new_defined.append(
                        f'<definedName name="_xlnm.Print_Area" '
                        f'localSheetId="{index}">'
                        f"'{unique}'!{area}</definedName>")

    all_names = names + new_names

    workbook = workbook.replace("</sheets>", "".join(new_sheet_tags)
                                + "</sheets>", 1)
    if "<definedNames>" in workbook:
        workbook = workbook.replace("</definedNames>",
                                    "".join(new_defined) + "</definedNames>", 1)
    elif new_defined:
        workbook = workbook.replace(
            "</sheets>", "</sheets><definedNames>" + "".join(new_defined)
            + "</definedNames>", 1)
    rels_xml = rels_xml.replace("</Relationships>",
                                "".join(new_rels) + "</Relationships>")

    # picture / drawing file types the base did not have yet
    for extension, kind in (("png", "image/png"), ("jpeg", "image/jpeg"),
                            ("emf", "image/x-emf"), ("jpg", "image/jpeg")):
        used = any(n.lower().endswith("." + extension) for n in parts)
        has = re.search(rf'Extension="{extension}"', types_xml, re.I)
        if used and not has:
            types_xml = types_xml.replace(
                "<Default ", f'<Default Extension="{extension}" '
                f'ContentType="{kind}"/><Default ', 1)
    types_xml = types_xml.replace("</Types>", "".join(new_types) + "</Types>")

    app_xml = (
        XML_HEAD
        + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
        '2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/'
        'officeDocument/2006/docPropsVTypes"><Application>Microsoft Excel'
        "</Application><HeadingPairs><vt:vector size=\"2\" baseType=\"variant\">"
        "<vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant><vt:variant>"
        f"<vt:i4>{len(all_names)}</vt:i4></vt:variant></vt:vector></HeadingPairs>"
        f'<TitlesOfParts><vt:vector size="{len(all_names)}" baseType="lpstr">'
        + "".join(f"<vt:lpstr>{xml_text(n)}</vt:lpstr>" for n in all_names)
        + "</vt:vector></TitlesOfParts></Properties>"
    )

    parts["xl/workbook.xml"] = workbook.encode("utf-8")
    parts["xl/_rels/workbook.xml.rels"] = rels_xml.encode("utf-8")
    parts["[Content_Types].xml"] = types_xml.encode("utf-8")
    parts["xl/styles.xml"] = styles_xml.encode("utf-8")
    parts["docProps/app.xml"] = app_xml.encode("utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.stem + ".saving.tmp")
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
            target.writestr("[Content_Types].xml", parts["[Content_Types].xml"])
            for name, content in parts.items():
                if name != "[Content_Types].xml":
                    target.writestr(name, content)
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def report_workbook_path(excel_path, control_no):
    return (Path(excel_path).parent / FORM_FOLDER_NAME
            / f"{safe_filename(control_no)}_Report.xlsx")


# ---------- PDF + printing ---------------------------------

def find_libreoffice():
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found

    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if Path(candidate).exists():
            return candidate

    return None


def export_pdf_with_excel(xlsx_path, pdf_path):
    """Windows: Microsoft Excel does the conversion (needs pywin32).
    Safe to call from a background thread."""
    import pythoncom                # pip install pywin32
    import win32com.client

    pythoncom.CoInitialize()
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        try:
            workbook = excel.Workbooks.Open(
                str(Path(xlsx_path).resolve()), ReadOnly=True
            )
            try:
                workbook.ExportAsFixedFormat(0, str(Path(pdf_path).resolve()))
            finally:
                workbook.Close(False)
        finally:
            excel.Quit()
    finally:
        pythoncom.CoUninitialize()


def export_pdf_with_libreoffice(xlsx_path, pdf_path):
    soffice = find_libreoffice()
    if not soffice:
        raise RuntimeError("LibreOffice was not found.")

    with tempfile.TemporaryDirectory() as temp_dir:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", temp_dir, str(xlsx_path)],
            check=True, capture_output=True, timeout=180
        )
        produced = Path(temp_dir) / (Path(xlsx_path).stem + ".pdf")
        if not produced.exists():
            raise RuntimeError("LibreOffice did not create the PDF.")
        shutil.move(str(produced), str(pdf_path))


def convert_form_to_pdf(xlsx_path, pdf_path):
    """Try Microsoft Excel first (Windows), then LibreOffice."""
    errors = []

    if sys.platform == "win32":
        try:
            export_pdf_with_excel(xlsx_path, pdf_path)
            return
        except Exception as error:
            errors.append(f"Microsoft Excel: {error}")

    try:
        export_pdf_with_libreoffice(xlsx_path, pdf_path)
        return
    except Exception as error:
        errors.append(f"LibreOffice: {error}")

    raise RuntimeError(
        "The PDF could not be created.\n\n"
        "It needs Microsoft Excel together with the pywin32 package\n"
        "    (pip install pywin32)\n"
        "or LibreOffice installed on this computer.\n\n"
        "Details:\n- " + "\n- ".join(errors)
    )


def make_report_pdf(forms, pdf_path):
    """
    One PDF with every page of the report, in order:
    First Page, then the Cargo Details of every Item List form with lines
    (and extra remarks pages), then the Incident Report page(s) when the
    cargo is in Bad Order.
    Runs in a background thread (no GUI calls in here).
    """
    if len(forms) == 1:         # one workbook = one PDF with every sheet
        Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            part = Path(temp_dir) / "report.pdf"
            convert_form_to_pdf(forms[0], part)
            shutil.copyfile(part, pdf_path)
        return

    try:
        from pypdf import PdfWriter      # pip install pypdf
    except ImportError:
        raise RuntimeError(
            "Combining the pages into one PDF needs the pypdf package.\n\n"
            "Install it with:\n    pip install pypdf"
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        parts = []
        for number, form in enumerate(forms, start=1):
            part = Path(temp_dir) / f"part{number}.pdf"
            convert_form_to_pdf(form, part)
            parts.append(part)

        writer = PdfWriter()
        try:
            for part in parts:
                writer.append(str(part))

            combined = Path(temp_dir) / "combined.pdf"
            with open(combined, "wb") as file:
                writer.write(file)
        finally:
            writer.close()

        Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(combined, pdf_path)      # replaces an existing PDF


# A printer Windows marks "Offline" (switched off, unplugged, or set to
# "Use Printer Offline") is not offered: a print sent there just waits.
PRINTER_STATUS_OFFLINE = 0x80
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x400


def printer_is_ready(status, attributes):
    return not (status & PRINTER_STATUS_OFFLINE
                or attributes & PRINTER_ATTRIBUTE_WORK_OFFLINE)


def available_printers():
    """(the printers ready to print, the Windows default printer or "").
    Only names that are installed and not offline are listed."""
    if sys.platform != "win32":
        try:
            out = subprocess.run(["lpstat", "-a"], capture_output=True,
                                 text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return [], ""
        return [line.split()[0] for line in out.splitlines()
                if line.strip()], ""

    import win32print               # pip install pywin32

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    ready = [p["pPrinterName"]
             for p in win32print.EnumPrinters(flags, None, 2)
             if printer_is_ready(p.get("Status", 0), p.get("Attributes", 0))]
    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        default = ""
    return ready, default


def excel_printer_name(printer):
    """Excel wants "<name> on <port>:", e.g. "EPSON L120 Series on Ne02:".
    The port comes from the same list Windows gives every program."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\Devices")
        with key:
            value, _ = winreg.QueryValueEx(key, printer)
        port = str(value).split(",")[-1].strip()
        if port:
            return f"{printer} on {port}"
    except OSError:
        pass
    return printer


def print_forms_with_excel(forms, printer):
    """Windows: Microsoft Excel prints every report workbook, in order,
    straight to the printer - the same pages as the PDF, no viewer.
    Safe to call from a background thread."""
    import pythoncom                # pip install pywin32
    import win32com.client

    pythoncom.CoInitialize()
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        try:
            for form in forms:
                workbook = excel.Workbooks.Open(
                    str(Path(form).resolve()), ReadOnly=True
                )
                try:
                    # Excel refuses a printer while no workbook is open.
                    excel.ActivePrinter = excel_printer_name(printer)
                    workbook.PrintOut()
                finally:
                    workbook.Close(False)
        finally:
            excel.Quit()
    finally:
        pythoncom.CoUninitialize()


def send_to_printer(forms, printer, pdf_path=None):
    """Print the whole report on the chosen printer (no PDF viewer).
    Other systems print the report PDF with lp."""
    if sys.platform == "win32":
        print_forms_with_excel(forms, printer)
        return "printed"

    if pdf_path is None:
        pdf_path = Path(tempfile.gettempdir()) / "fsr_print.pdf"
    make_report_pdf(forms, pdf_path)
    subprocess.run(["lp", "-d", printer, str(pdf_path)], check=True)
    return "printed"
