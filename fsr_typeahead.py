"""Shared prefix picker. The popup never borrows Tk's mutable row indices.

Editable boxes keep ordinary text entry. Readonly boxes have a separate search
query (shown above the results); their value changes only on a valid selection.
"""
from bisect import bisect_left
import tkinter as tk

import ttkbootstrap as tb


class PrefixIndex:
    def __init__(self, values):
        self.values = tuple(str(value) for value in values)
        self.sorted = sorted((value.casefold(), i) for i, value in enumerate(self.values))
        self.keys = [key for key, _ in self.sorted]

    def matches(self, query):
        if not query:
            return self.values
        prefix = query.casefold()
        start = bisect_left(self.keys, prefix)
        found = []
        for position in range(start, len(self.sorted)):
            key, index = self.sorted[position]
            if not key.startswith(prefix):
                break
            found.append(index)
        return tuple(self.values[i] for i in sorted(found))


class Combobox(tb.Combobox):
    """A normal ttk combobox with one shared, non-focus-stealing picker."""
    def __init__(self, *args, **kwargs):
        self.values_provider = kwargs.pop('values_provider', None)
        super().__init__(*args, **kwargs)
        self.typeahead = Picker(self)

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        changes = dict(cnf) if isinstance(cnf, dict) else {}
        changes.update(kwargs)
        picker = getattr(self, 'typeahead', None)
        if picker and 'values' in changes:
            picker.index = PrefixIndex(self.cget('values'))
            if picker.opened:
                picker.show(picker.query)
        if picker and 'state' in changes and picker.blocked:
            picker.close()
        return result

    config = configure


class Picker:
    PAGE = 100

    def __init__(self, combo):
        self.combo = combo
        self.fixed = str(combo.cget('state')) == 'readonly'
        # Tk uses Mod1 (0x8) for Num Lock on Windows, not Alt. The
        # extended-key bit is also unrelated to modifiers we act on.
        self.alt_mask = 0x20000 if combo.tk.call('tk', 'windowingsystem') == 'win32' else 8
        self.index = PrefixIndex(combo.cget('values'))
        self.query = ''
        self.items = ()
        self.selected = 0
        self.offset = 0
        self.popup = None
        self.pending = None
        self.tag = 'FSRTypeahead:' + str(combo)
        self.bindings = []
        combo.bindtags((self.tag, *combo.bindtags()))
        for event, callback in (
                ('<KeyPress>', self.key), ('<KeyRelease>', self.released),
                ('<Button-1>', self.click_arrow),
                ('<FocusIn>', self.refresh),
                ('<FocusOut>', self.focus_out), ('<Destroy>', self.destroy),
                ('<<Paste>>', self.edited), ('<<Cut>>', self.edited),
                ('<<Clear>>', self.edited)):
            self.bindings.append(combo.bind_class(self.tag, event, callback))
        root = combo.winfo_toplevel()
        if not hasattr(root, '_typeahead_active'):
            root._typeahead_active = None
            root.bind('<Button-1>', lambda e: Picker.outside(root, e), add='+')
            root.bind('<Configure>', lambda e: Picker.moved(root, e), add='+')

    @property
    def opened(self):
        return self.popup is not None

    @property
    def blocked(self):
        state = str(self.combo.cget('state'))
        return self.combo.instate(('disabled',)) or (state == 'readonly' and not self.fixed)

    @staticmethod
    def outside(root, event):
        active = root._typeahead_active
        if active and event.widget is not active.combo:
            active.close()

    @staticmethod
    def moved(root, event):
        if event.widget is root and root._typeahead_active:
            root._typeahead_active.close()

    def edited(self, event=None):
        if not self.blocked and not self.fixed:
            if self.pending is not None:
                self.combo.after_cancel(self.pending)
            self.pending = self.combo.after_idle(self.typed)

    def refresh(self, event=None):
        if self.combo.values_provider:
            values = tuple(str(value) for value in self.combo.values_provider())
            if values != self.index.values:
                self.combo.configure(values=values)

    def typed(self):
        self.pending = None
        self.show(self.combo.get())

    def key(self, event):
        key = {'KP_Up': 'Up', 'KP_Down': 'Down',
               'KP_Enter': 'Return'}.get(event.keysym, event.keysym)
        if self.blocked:
            # A PO-linked editable box becomes readonly at runtime. Native
            # ttk bindings would still let Down/F4 select a different value.
            navigation = key in ('Tab', 'ISO_Left_Tab') or (
                key in ('Up', 'Down') and event.state & 4)
            return None if navigation else 'break'
        if key == 'F4' or (key == 'Down' and event.state & self.alt_mask):
            if self.opened:
                self.close()
            else:
                self.show('')
            return 'break'
        if key in ('Up', 'Down') and not event.state & 4:
            if not self.opened:
                self.show('' if self.fixed else self.combo.get())
            elif self.items:
                self.selected = max(0, min(len(self.items) - 1,
                                          self.selected + (1 if key == 'Down' else -1)))
                self.render()
            return 'break'
        if key in ('Return', 'KP_Enter'):
            if self.pending is not None:
                self.combo.after_cancel(self.pending)
                self.typed()
            if self.opened:
                self.accept()
                return 'break'
        if key == 'Escape':
            self.close()
            return 'break'
        if key in ('Tab', 'ISO_Left_Tab'):
            self.close()
            return None
        if self.fixed:
            if key == 'BackSpace':
                self.show(self.query[:-1])
                return 'break'
            if event.char and event.char.isprintable() and not event.state & (4 | self.alt_mask):
                self.show((self.query if self.opened or self.query else '') + event.char)
                return 'break'
        elif key in ('BackSpace', 'Delete') or (event.char and event.char.isprintable()):
            self.edited()
        return None

    def released(self, event):
        # Readonly search is not a report edit (including the application's
        # global dirty handler and field-level KeyRelease callbacks).
        if self.fixed or self.blocked or event.keysym in (
                'Up', 'Down', 'KP_Up', 'KP_Down', 'Return', 'KP_Enter'):
            return 'break'

    def click_arrow(self, event):
        if self.blocked:
            return 'break'
        # Match ttk's hit testing: themed arrow padding is not necessarily
        # identified as "downarrow" (notably the bootstrap Windows themes).
        element = self.combo.identify(event.x, event.y).lower()
        if 'textarea' not in element or self.fixed:
            self.refresh()
            self.combo.focus_set()
            if self.opened:
                self.close()
            else:
                self.show('')
            return 'break'

    def show(self, query):
        if self.blocked or not self.combo.winfo_ismapped():
            return
        self.query = query
        self.items = self.index.matches(query)
        self.selected = 0
        self.offset = 0
        if not self.items:
            self.close(clear_query=False)
            return
        if not self.popup:
            root = self.combo.winfo_toplevel()
            if root._typeahead_active and root._typeahead_active is not self:
                root._typeahead_active.close()
            root._typeahead_active = self
            self.popup = tk.Toplevel(self.combo, takefocus=False)
            self.popup.withdraw()
            self.popup.overrideredirect(True)
            self.popup.transient(root)
            self.caption = tk.Label(self.popup, anchor='w')
            self.listbox = tk.Listbox(self.popup, exportselection=False,
                                      activestyle='none', takefocus=False)
            self.scroll = tk.Scrollbar(self.popup, command=self.scroll_to)
            self.scroll.pack(side='right', fill='y')
            self.listbox.pack(side='bottom', fill='both', expand=True)
            self.listbox.bind('<Button-1>', self.choose_mouse)
            self.listbox.bind('<B1-Motion>', lambda e: 'break')
            self.listbox.bind('<Motion>', self.hover)
            self.listbox.bind('<MouseWheel>', self.wheel)
        if self.fixed and query:
            self.caption.configure(text='Search: ' + query)
            self.caption.pack(side='top', fill='x', before=self.listbox)
        else:
            self.caption.pack_forget()
        self.render()
        self.popup.update_idletasks()
        x, y = self.combo.winfo_rootx(), self.combo.winfo_rooty() + self.combo.winfo_height()
        width = max(self.combo.winfo_width(), self.popup.winfo_reqwidth())
        height = self.popup.winfo_reqheight()
        if y + height > self.combo.winfo_screenheight():
            y = max(0, self.combo.winfo_rooty() - height)
        x = max(0, min(x, self.combo.winfo_screenwidth() - width))
        self.popup.geometry(f'{width}x{height}+{x}+{y}')
        self.popup.deiconify()
        self.popup.lift()

    def render(self):
        # Bound the Tcl list size even for very large master lists. Scrollbar
        # and keyboard navigation still reach every filtered item.
        if not self.popup:
            return
        if not self.offset <= self.selected < self.offset + self.PAGE:
            self.offset = max(0, self.selected - self.PAGE // 2)
        self.offset = min(self.offset, max(0, len(self.items) - self.PAGE))
        page = self.items[self.offset:self.offset + self.PAGE]
        self.listbox.delete(0, 'end')
        self.listbox.insert('end', *page)
        self.listbox.configure(height=min(8, len(page)), width=30)
        local = self.selected - self.offset
        self.listbox.selection_set(local)
        self.listbox.activate(local)
        self.listbox.see(local)
        self.scroll.set(self.selected / len(self.items),
                        min(1, (self.selected + 8) / len(self.items)))

    def scroll_to(self, action, value, units=None):
        if action == 'moveto':
            self.selected = min(len(self.items) - 1, int(float(value) * len(self.items)))
        else:
            self.selected = max(0, min(len(self.items) - 1,
                self.selected + int(value) * (8 if units == 'pages' else 1)))
        self.render()

    def wheel(self, event):
        self.scroll_to('scroll', -1 if event.delta > 0 else 1, 'units')
        return 'break'

    def hover(self, event):
        self.selected = self.offset + self.listbox.nearest(event.y)
        self.listbox.selection_clear(0, 'end')
        self.listbox.selection_set(self.selected - self.offset)

    def choose_mouse(self, event):
        self.hover(event)
        self.accept()
        return 'break'

    def accept(self):
        if self.blocked or not self.items:
            self.close()
            return
        value = self.items[self.selected]
        self.close()
        self.combo.set(value)
        self.combo.icursor('end')
        self.combo.selection_clear()
        self.combo.event_generate('<<ComboboxSelected>>')

    def close(self, clear_query=True):
        if self.pending is not None:
            self.combo.after_cancel(self.pending)
            self.pending = None
        if self.popup:
            self.popup.destroy()
            self.popup = None
        root = self.combo.winfo_toplevel()
        if getattr(root, '_typeahead_active', None) is self:
            root._typeahead_active = None
        if clear_query:
            self.query = ''

    def focus_out(self, event):
        self.close()

    def destroy(self, event):
        if event.widget is self.combo:
            self.close()
            for sequence in self.combo.bind_class(self.tag):
                self.combo.unbind_class(self.tag, sequence)
            for command in self.bindings:
                self.combo._root().deletecommand(command)
            self.bindings.clear()
