"""Live text continuation using the unmodified official forms' line widths.

Only user edits trigger flow. Loading a report or restoring raw draft values
does not rewrite it. Rows remain ordinary entries and ordinary report data.
"""
from functools import lru_cache
import math
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont, messagebox
import xml.etree.ElementTree as ET
import zipfile


NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def column_number(name):
    result = 0
    for char in name:
        result = result * 26 + ord(char) - ord('A') + 1
    return result


@lru_cache(maxsize=16)
def line_spec(path, sheet, ref, end_column=None):
    """Read geometry/font only; never save or modify a template."""
    with zipfile.ZipFile(path) as source:
        styles = ET.fromstring(source.read('xl/styles.xml'))
        page = ET.fromstring(source.read(f'xl/worksheets/sheet{sheet}.xml'))
    fonts = styles.find('m:fonts', NS)
    xfs = styles.find('m:cellXfs', NS)
    def font_for(index):
        font = fonts[int(xfs[index].get('fontId', '0'))]
        return (font.find('m:name', NS).get('val'),
                float(font.find('m:sz', NS).get('val')),
                font.find('m:b', NS) is not None)
    cell = page.find(f'.//m:c[@r="{ref}"]', NS)
    if cell is None:
        raise ValueError(f'The form has no cell {ref}.')
    start = ''.join(char for char in ref if char.isalpha())
    if end_column is None:
        end_column = start
        for merge in page.findall('m:mergeCells/m:mergeCell', NS):
            bounds = merge.get('ref').split(':')
            if bounds[0] == ref:
                end_column = ''.join(char for char in bounds[-1] if char.isalpha())
                break
    widths = []
    for col in range(column_number(start), column_number(end_column) + 1):
        width = 8.43
        for definition in page.findall('m:cols/m:col', NS):
            if int(definition.get('min')) <= col <= int(definition.get('max')):
                width = float(definition.get('width', width))
                break
        widths.append(width)
    return font_for(0), font_for(int(cell.get('s', '0'))), tuple(widths)


class Metrics:
    def __init__(self, root):
        self.root = root
        self.fonts = {}
        self.lines = {}

    def font(self, spec):
        if spec not in self.fonts:
            family, points, bold = spec
            # Negative pixel sizes make measurements independent of display DPI.
            self.fonts[spec] = tkfont.Font(self.root, family=family,
                size=-round(points * 96 / 72), weight='bold' if bold else 'normal')
        return self.fonts[spec]

    def line(self, key):
        if key not in self.lines:
            import fsr_forms as forms
            definitions = {
                'goods': [(forms.FORM_TEMPLATE, 1, 'A22', None)],
                'remarks': [(forms.FORM_TEMPLATE, 1, 'G21', None)],
                # Additional Details can print on any of these existing pages.
                'details': [(forms.CARGO_TEMPLATE, s, 'A20', 'K') for s in (1, 2)]
                    + [(forms.UNIT_FORM_TEMPLATE, s, 'A20', 'K') for s in (1, 2)],
                # The output already normalizes Incident line 1 to line 2's font.
                'incident': [(forms.INCIDENT_TEMPLATE, 1, 'A19', None)],
            }
            limits = []
            for path, sheet, ref, end in definitions[key]:
                normal, content, widths = line_spec(str(Path(path)), sheet, ref, end)
                digit = max(self.font(normal).measure(str(i)) for i in range(10))
                # Conservative column conversion, plus border/padding/font safety.
                pixels = sum(math.floor(width * digit) for width in widths) - 16
                limits.append((self.font(content), max(1, pixels)))
            self.lines[key] = limits
        return self.lines[key]

    def measure(self, key, text):
        if key == 'goods':
            # A Declared Goods Description prints on two small lines when
            # too long for one (as the Findings of a shipment line): it
            # continues on the next line only when it does not fit two.
            import fsr_forms as forms
            import fsr_print_fit
            return 2.0 if forms.goods_description_fit(text) == fsr_print_fit.LONG else 1.0
        return max(font.measure(text) / width for font, width in self.line(key))


def split_spans(text, measure, max_lines):
    """Word-first splitting, preserving spaces and source caret offsets.

    At most max_lines+1 spans are needed: the last span retains excess input
    verbatim so a very large paste cannot lose text or require unbounded rows.
    """
    spans = []
    start = 0
    while True:
        if len(spans) >= max_lines:
            spans.append((start, len(text)))
            break
        newline = text.find('\n', start)
        end = len(text) if newline < 0 else newline
        if measure(text[start:end]) <= 1:
            spans.append((start, end))
            if newline < 0:
                break
            start = end + 1
            continue
        low, high = 1, end - start
        while low < high:
            middle = (low + high + 1) // 2
            if measure(text[start:start + middle]) <= 1:
                low = middle
            else:
                high = middle - 1
        length = low
        prefix = text[start:start + length]
        boundary = max((i + 1 for i, char in enumerate(prefix) if char.isspace()), default=0)
        if boundary and prefix[:boundary].strip():
            length = boundary
        spans.append((start, start + length))
        start += length
    return spans


class Flow:
    def __init__(self, frame, rows, ensure, key, title, limit, changed):
        self.frame, self.rows, self.ensure = frame, rows, ensure
        self.key, self.title, self.limit, self.changed = key, title, limit, changed
        root = frame.winfo_toplevel()
        if not hasattr(root, '_text_flow_metrics'):
            root._text_flow_metrics = Metrics(root)
        self.metrics = root._text_flow_metrics
        self.pending = None
        self.busy = False
        self.warning = tk.StringVar(frame)
        self.warning_label = None
        frame.text_flow = self
        frame.bind('<Destroy>', self.destroy, add='+')
        self.watch()

    def watch(self):
        for row in self.rows():
            entry = row[0]
            if getattr(entry, 'text_flow', None) is self:
                continue
            entry.text_flow = self
            entry.bind('<KeyPress>', lambda e, w=entry: self.keypress(w, e), add='+')
            entry.bind('<<Paste>>', lambda e, w=entry: self.paste(w), add='+')
            for event in ('<<Cut>>', '<<Clear>>'):
                entry.bind(event, lambda e, w=entry: self.schedule(w), add='+')

    def keypress(self, entry, event):
        if str(entry.cget('state')) != 'normal':
            return None
        if event.keysym in ('Return', 'KP_Enter'):
            self.insert(entry, '\n')
            return 'break'
        if event.keysym in ('BackSpace', 'Delete') or (
                event.char and event.char.isprintable()):
            self.schedule(entry)
        return None

    def paste(self, entry):
        if str(entry.cget('state')) != 'normal':
            return 'break'
        try:
            text = entry.clipboard_get()
        except tk.TclError:
            return None
        self.insert(entry, text.replace('\r\n', '\n').replace('\r', '\n'))
        return 'break'

    def insert(self, entry, text):
        if entry.selection_present():
            entry.delete('sel.first', 'sel.last')
        entry.insert('insert', text)
        self.schedule(entry)
        self.flush()
        self.changed()

    def schedule(self, entry):
        if self.busy:
            return
        if self.pending is not None:
            self.frame.after_cancel(self.pending[0])
        timer = self.frame.after_idle(self.flush)
        self.pending = timer, entry

    def cancel(self):
        if self.pending is not None:
            self.frame.after_cancel(self.pending[0])
            self.pending = None

    def error(self):
        for row in self.rows():
            text = row[0].get()
            if text.strip() and ('\n' in text or self.metrics.measure(self.key, text.strip()) > 1):
                return ('Text is kept, but does not fit a printed line. '
                        f'{self.title} has room for {self.limit} lines. '
                        'Shorten it or make room before Save/Print.')
        return ''

    def refresh(self):
        self.watch()
        try:
            error = self.error()
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            error = f'Text is kept. Printed line width could not be checked: {exc}'
        self.warning.set(error)
        return error

    def flush(self):
        if self.pending is None:
            return
        timer, entry = self.pending
        self.pending = None
        self.frame.after_cancel(timer)
        if not entry.winfo_exists():
            return
        rows = self.rows()
        if not any(row[0] is entry for row in rows):
            return
        index = next(i for i, row in enumerate(rows) if row[0] is entry)
        text = entry.get()
        try:
            spans = split_spans(text, lambda t: self.metrics.measure(self.key, t), self.limit)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            self.refresh()
            return
        if len(spans) == 1:
            self.refresh()
            self.changed()
            return
        values = [[widget.get() for widget in row] for row in rows]
        original = values[index]
        additions = [[text[a:b], *([''] * (len(original) - 1))] for a, b in spans]
        additions[0][1:] = original[1:]
        following = values[index + 1:]
        # Empty rows immediately below are available for continuation. Occupied
        # rows (including goods Quantity/Packaging) always move together.
        spare = len(additions) - 1
        while spare and following and not any(following[0]):
            following.pop(0)
            spare -= 1
        result = values[:index] + additions + following
        while (len(result) > self.limit and len(result) > index + len(additions)
               and not any(result[-1])):
            result.pop()
        if len(result) > self.limit:
            self.refresh()  # Leave the entire original input untouched.
            self.changed()
            return
        caret = entry.index('insert')
        destination = len(spans) - 1
        for i, (_, end) in enumerate(spans):
            if caret <= end:
                destination = i
                break
        offset = max(0, caret - spans[destination][0])
        focused = entry.focus_get() is entry
        self.busy = True
        try:
            self.ensure(len(result))
            rows = self.rows()
            for row, value in zip(rows, result):
                for widget, content in zip(row, value):
                    if widget.get() != content:
                        widget.delete(0, 'end')
                        widget.insert(0, content)
            target = rows[index + destination][0]
            target.icursor(min(offset, len(target.get())))
            if focused:
                target.focus_set()
        finally:
            self.busy = False
        self.refresh()
        self.changed()

    def destroy(self, event):
        if event.widget is self.frame and self.pending is not None:
            self.cancel()


def flows(host):
    seen = set()
    stack = [host['notebook']]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        flow = getattr(widget, 'text_flow', None)
        if flow is not None and id(flow) not in seen:
            seen.add(id(flow))
            yield flow


def validate(host):
    """Before normal Save, never quietly print a retained overlong line."""
    for flow in flows(host):
        flow.flush()
        error = flow.refresh()
        if error:
            if host.get('app_shell'):
                host['app_shell'].show('inspection')
            for tab in (host['documents_tab'], host['findings_tab'], host['incident_tab']):
                if str(flow.frame).startswith(str(tab)):
                    host['notebook'].select(tab)
                    break
            messagebox.showwarning(flow.title, error, parent=host['window'])
            flow.rows()[0][0].focus_set()
            return False
    return True
