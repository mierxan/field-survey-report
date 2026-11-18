"""Does a text fit a printed form cell? One line (in the form's own font,
or shrunk but not below SMALL_SIZE points), two wrapped lines in the small
font (as the Findings of a shipment line), or neither (it is then printed
on one shrunken line, as every cell was, with a warning).

The letters are measured with Calibri's own widths (the font of the form
templates, read from calibri.ttf), so the answer is the same on every PC
and without a window: the printed forms, the PDF and the warnings while
typing all use it. No Tk, no font files at run time.
"""

ONE = "one"            # one line (shrunk if needed, never below SMALL_SIZE)
TWO = "two"            # two wrapped lines of SMALL_SIZE points
LONG = "long"          # more: printed on one shrunken line (warned)

SMALL_SIZE = 9         # the size of the two-line Findings
MAX_DIGIT_PIXELS = 7   # Calibri 11, the templates' normal font
CELL_PADDING_PIXELS = 7
SAFETY = 0.95          # Excel and LibreOffice draw letters a little apart

FONT_UNITS = 2048
# Calibri's advance widths (font units of 2048 per em) - generated once
# from C:\Windows\Fonts\calibri.ttf with fontTools.
_CHARS = (
    ' !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFG'
    'HIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmno'
    'pqrstuvwxyz{|}~\xa0¡¢£¤¥¦§¨©ª«¬\xad®¯°±²³´µ¶·¸'
    '¹º»¼½¾¿ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßà'
    'áâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ–—‘’“”•…€'
    '₱'
)
_WIDTHS = (
    463, 667, 821, 1020, 1038, 1464, 1397, 452, 621, 621, 1020, 1020, 511, 627,
    517, 791, 1038, 1038, 1038, 1038, 1038, 1038, 1038, 1038, 1038, 1038, 548, 548,
    1020, 1020, 1020, 949, 1831, 1185, 1114, 1092, 1260, 1000, 941, 1292, 1276, 516,
    653, 1064, 861, 1751, 1322, 1356, 1058, 1378, 1112, 941, 998, 1314, 1162, 1822,
    1063, 998, 959, 628, 791, 628, 1020, 1020, 596, 981, 1076, 866, 1076, 1019,
    625, 964, 1076, 470, 490, 931, 470, 1636, 1076, 1080, 1076, 1076, 714, 801,
    686, 1076, 925, 1464, 887, 927, 809, 644, 943, 644, 1020, 463, 667, 1020,
    1038, 1020, 1038, 1020, 1020, 804, 1709, 824, 1049, 1020, 627, 1038, 807, 694,
    1020, 688, 685, 598, 1126, 1200, 517, 629, 504, 865, 1049, 1303, 1375, 1383,
    949, 1185, 1185, 1185, 1185, 1185, 1185, 1563, 1092, 1000, 1000, 1000, 1000, 516,
    516, 516, 516, 1279, 1322, 1356, 1356, 1356, 1356, 1356, 1020, 1359, 1314, 1314,
    1314, 1314, 998, 1058, 1080, 981, 981, 981, 981, 981, 981, 1583, 866, 1019,
    1019, 1019, 1019, 470, 470, 470, 470, 1076, 1076, 1080, 1080, 1080, 1080, 1080,
    1020, 1084, 1076, 1076, 1076, 1076, 927, 1076, 927, 1020, 1854, 511, 511, 857,
    857, 1020, 1414, 1038, 1154,
)
_WIDTH = dict(zip("".join(_CHARS), _WIDTHS))
# a letter not in the table (another script, a symbol): as wide as the
# widest letter, so a text with one never counts as fitting by mistake
_UNKNOWN = FONT_UNITS


def text_points(text, size):
    """The width of `text` in points at `size` points."""
    return sum(_WIDTH.get(char, _UNKNOWN) for char in text) * size / FONT_UNITS


def column_pixels(width):
    """Excel's pixels of a column `width` characters wide (Calibri 11)."""
    return int((256 * width + int(128 / MAX_DIGIT_PIXELS)) / 256
               * MAX_DIGIT_PIXELS)


def cell_points(widths):
    """The room for text, in points, of a cell spanning columns `widths`
    (a merged cell: every column's width)."""
    pixels = sum(column_pixels(width) for width in widths)
    return max(1.0, (pixels - CELL_PADDING_PIXELS) * 0.75 * SAFETY)


def wrapped_lines(text, room, size):
    """The lines a wrapping cell `room` points wide shows `text` on: words
    move to the next line at a space; a word longer than a line is cut."""
    lines = []
    for paragraph in str(text).split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if text_points(candidate, size) <= room:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = word
            while text_points(line, size) > room and len(line) > 1:
                cut = len(line) - 1
                while cut > 1 and text_points(line[:cut], size) > room:
                    cut -= 1
                lines.append(line[:cut])
                line = line[cut:]
        lines.append(line)
    return lines


def layout(text, widths, size):
    """ONE, TWO or LONG for `text` in a cell of columns `widths` whose own
    font is `size` points."""
    text = str(text or "").strip()
    room = cell_points(widths)
    # one line at its own size, or shrunk to no smaller than SMALL_SIZE:
    # bigger than two SMALL_SIZE lines, so it stays on one line
    if "\n" not in text and text_points(text, SMALL_SIZE) <= room:
        return ONE
    if len(wrapped_lines(text, room, SMALL_SIZE)) <= 2:
        return TWO
    return LONG
