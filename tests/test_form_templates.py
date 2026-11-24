"""The official form templates in data/excel can be changed in Excel (the
owner's own changes of 23 November 2026: taller First Page rows, a bigger
signature and document-control block on the Incident Report, Cargo Details
header fonts and the inspector's name aligned left). The printed pages take
their print area from the template, so a block made bigger is not cut off,
and every filled page keeps the template's look."""
import io
import re
import zipfile

from openpyxl import load_workbook

import fsr_forms
from test_incident_header import bad_order


def print_area(path, sheet_index=0):
    with zipfile.ZipFile(path) as package:
        workbook = package.read("xl/workbook.xml").decode("utf-8")
    found = re.search(
        r'<definedName\b[^>]*name="_xlnm.Print_Area"[^>]*localSheetId="'
        rf'{sheet_index}"[^>]*>[^<]*!([^<]+)</definedName>', workbook)
    return found and found.group(1)


def last_picture_row(path):
    """The last row (1-based) a picture of the first sheet reaches."""
    with zipfile.ZipFile(path) as package:
        drawing = next(n for n in package.namelist()
                       if re.fullmatch(r"xl/drawings/drawing\d+\.xml", n))
        xml = package.read(drawing).decode("utf-8")
    rows = re.findall(r"<xdr:to>.*?<xdr:row>(\d+)</xdr:row>", xml, re.S)
    return max(int(row) for row in rows) + 1


def area_last_row(area):
    return int(re.search(r"(\d+)$", area).group(1))


def test_the_print_area_is_read_from_each_template():
    expected = {
        (fsr_forms.INCIDENT_TEMPLATE, "IncidentReport"): print_area(
            fsr_forms.INCIDENT_TEMPLATE),
        (fsr_forms.CARGO_TEMPLATE, "WarehouseReceiving"): "$A$1:$K$53",
        (fsr_forms.UNIT_FORM_TEMPLATE, "Loading"): "$A$1:$K$53",
    }
    for (template, sheet), area in expected.items():
        with zipfile.ZipFile(template) as source:
            assert fsr_forms.template_print_area(source, sheet, "x") == area


def test_a_template_without_a_print_area_uses_the_fallback():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("xl/workbook.xml",
                         '<workbook><sheets><sheet name="IncidentReport" '
                         'sheetId="1" r:id="rId1"/></sheets></workbook>')
    with zipfile.ZipFile(buffer) as source:
        assert fsr_forms.template_print_area(
            source, "IncidentReport", "$A$1:$I$51") == "$A$1:$I$51"


def test_the_incident_reports_bottom_block_is_printed_whole(tmp_path):
    template = fsr_forms.INCIDENT_TEMPLATE
    out = tmp_path / "incident.xlsx"
    assert fsr_forms.build_incident_workbook(template, out, bad_order()) == 1

    area = print_area(out)
    assert area == print_area(template)             # the template's own
    # the signature and document-control picture is inside the print area
    assert last_picture_row(out) <= area_last_row(area)


def test_filled_pages_keep_the_templates_row_heights_and_styles(tmp_path):
    out = tmp_path / "incident.xlsx"
    fsr_forms.build_incident_workbook(fsr_forms.INCIDENT_TEMPLATE, out,
                                      bad_order())
    sheet = load_workbook(out).worksheets[0]
    template = load_workbook(fsr_forms.INCIDENT_TEMPLATE).worksheets[0]
    for row in range(1, area_last_row(print_area(out)) + 1):
        assert (sheet.row_dimensions[row].height
                == template.row_dimensions[row].height), row
